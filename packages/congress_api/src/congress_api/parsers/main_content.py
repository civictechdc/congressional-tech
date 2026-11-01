"""Select a page's main text from explicit article-body markup, with an extractor fallback.

Class-name heuristics such as ``entry-content`` are not explicit markup and are not
candidates. Marked text under ``SHORT_MARKED_CHARS`` is not testimony ("No prepared
statement.") and never falls back: the extractor would present other page text as
the statement.
"""
from lxml import etree

from congress_api.models.html_metadata import ContentCandidate, ContentLink, HtmlMetadata, MainContent
from congress_api.parsers.html_metadata import parse_document

SHORT_MARKED_CHARS = 200
PROPERTIES = ('content:encoded', 'schema:articleBody', 'articleBody')
_DROPPED = {'script', 'style', 'noscript', 'template'}
_BLOCKS = {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'table', 'section', 'article',
           'blockquote', 'ul', 'ol'}


def block_text(node) -> str:
    """Plain text keeping paragraph order and words intact at inline tags.

    html_text.extract_text(guess_layout=True) split words at inline tags on 7 of 45
    measured bodies ("t he"). The nested visible() in senate_page.py is the same idea
    but extracting it changes a byte-hashed parser; do that at its next re-version.
    Iterative, because real bodies nest past the recursion limit.
    """
    parts = []
    walker = etree.iterwalk(node, events=('start', 'end', 'comment', 'pi'))
    for event, element in walker:
        tag = element.tag.lower() if isinstance(element.tag, str) else None
        if event == 'start':
            if tag in _DROPPED:
                walker.skip_subtree()
                continue
            if tag in _BLOCKS:
                parts.append('\n')
            parts.append(element.text or '')
            continue
        if event == 'end' and tag in _BLOCKS:
            parts.append('\n')
        if element is not node:
            parts.append(element.tail or '')
    lines = (' '.join(line.split()) for line in ''.join(parts).splitlines())
    return '\n'.join(line for line in lines if line)


def _tokens(name: str) -> str:
    return f'contains(concat(" ",normalize-space(@{name})," ")," %s ")'


def _rdfa_confirms(metadata: HtmlMetadata) -> bool:
    return any(key.endswith('content/encoded') for item in metadata.formats['rdfa'].items for key in item)


def _json_ld_bodies(value, path: str):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'articleBody' and isinstance(item, str):
                yield path + '/articleBody', item
            else:
                yield from _json_ld_bodies(item, f"{path}/{key.replace('~', '~0').replace('/', '~1')}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _json_ld_bodies(item, f'{path}/{index}')


def _dom_candidates(tree, metadata: HtmlMetadata) -> list[ContentCandidate]:
    tests = [(_tokens('property') % name, name) for name in PROPERTIES] + [(_tokens('itemprop') % 'articleBody', 'itemprop:articleBody')]
    named = {}
    for test, name in tests:
        for node in tree.xpath(f'//*[{test}]'):
            named.setdefault(node, name)
    roots = tree.getroottree()
    out = []
    confirmed = _rdfa_confirms(metadata)
    for node, name in named.items():
        if any(ancestor in named for ancestor in node.iterancestors()):  # nested candidates resolve to the outermost
            continue
        body = block_text(node)
        links = [ContentLink(href=link.get('href'), text=' '.join(link.text_content().split())) for link in node.xpath('.//a[@href]')]
        out.append(ContentCandidate(selector=roots.getpath(node), property=name, text=body, char_count=len(body), links=links,
                                    rdfa_confirmed=name == 'content:encoded' and confirmed))
    return out


def _fallback(body: bytes) -> tuple[str | None, str | None]:
    from trafilatura import extract  # the archive extra; the same call as archive_readings

    try:
        return extract(body, include_comments=False, output_format='txt') or None, None
    except (etree.Error, UnicodeError, ValueError, RuntimeError) as error:
        return None, 'extractor_error:' + type(error).__name__


def select_main_content(body: bytes, metadata: HtmlMetadata) -> MainContent:
    common = dict(body_sha256=metadata.body_sha256)
    def result(outcome, *, text=None, selected=None, candidates=(), reason=None):
        return MainContent(**common, outcome=outcome, text=text, selector=selected.selector if selected else None,
                           property=selected.property if selected else None, candidates=list(candidates), fallback_reason=reason)
    if metadata.document_kind != 'html' or metadata.error_title_hint:
        return result('none', reason='not_substantive')
    tree = parse_document(body)
    if tree is None:
        return result('none', reason='unparseable')
    candidates = _dom_candidates(tree, metadata)
    for path, value in _json_ld_bodies(metadata.formats['json-ld'].items, '/formats/json-ld/items'):
        candidates.append(ContentCandidate(selector=path, property='json-ld:articleBody', text=value, char_count=len(value), links=[], rdfa_confirmed=False))
    distinct = list({candidate.text: candidate for candidate in reversed(candidates) if candidate.text}.values())[::-1]
    substantive = [candidate for candidate in distinct if candidate.char_count >= SHORT_MARKED_CHARS]
    if len(substantive) == 1:
        return result('marked', text=substantive[0].text, selected=substantive[0], candidates=candidates)
    if distinct and not substantive:
        return result('marked_no_content', selected=distinct[0], candidates=candidates, reason='short_marked_text')
    conflict = len(substantive) > 1
    text, error = _fallback(body)
    reason = error or ('conflicting_candidates' if conflict else 'empty_candidate' if candidates else 'no_candidate')
    if conflict:
        return result('conflicting_candidates', text=text, candidates=candidates, reason=reason)
    return result('fallback_extractor' if text else 'none', text=text, candidates=candidates, reason=reason)
