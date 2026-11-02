"""Select a page's main text from explicit article-body markup.

Only RDFa ``content:encoded`` is a candidate. JSON-LD ``articleBody`` is a publisher string,
not the page: it can carry raw markup (gov.uk f3a990b3) or a truncated body, and nothing
compares it with the DOM. Class-name heuristics such as ``entry-content`` are not explicit
markup either. Two or more distinct candidates are never chosen between: a long sidebar is
as marked as a short body. Marked text under ``SHORT_MARKED_CHARS`` is not testimony ("No prepared
statement.") and never falls back: an extractor would present other page text as
the statement. Everything else is ``fallback_required``: the caller reuses the stored
trafilatura reading (archive_readings), rather than a second unbounded run of it here.
"""
import re

from lxml import etree

from congress_api.models.html_metadata import ContentCandidate, ContentLink, HtmlMetadata, MainContent
from congress_api.parsers.html_metadata import parse_document

SHORT_MARKED_CHARS = 200
PROPERTIES = ('content:encoded',)
_DROPPED = {'script', 'style', 'noscript', 'template'}
_BLOCKS = {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'table', 'section', 'article',
           'blockquote', 'ul', 'ol', 'td', 'th', 'dt', 'dd', 'dl', 'hr', 'caption', 'pre', 'figure', 'figcaption'}
# The hidden-element rule of archive_readings._markup_facts (a byte-hashed reader this one
# may not import from); a test holds the two equal.
HIDDEN_STYLE = re.compile(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', re.I)
SOFT_HYPHEN = '\u00ad'


def _hidden(element) -> bool:
    return 'hidden' in element.attrib or bool(HIDDEN_STYLE.search(element.get('style', '')))


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
            if tag in _DROPPED or (tag is not None and element is not node and _hidden(element)):
                walker.skip_subtree()  # the end event still comes, so the tail is kept
                continue
            if tag in _BLOCKS:
                parts.append('\n')
            parts.append(element.text or '')
            continue
        if event == 'end' and tag in _BLOCKS:
            parts.append('\n')
        if element is not node:
            parts.append(element.tail or '')
    lines = (' '.join(line.split()) for line in ''.join(parts).replace(SOFT_HYPHEN, '').splitlines())
    return '\n'.join(line for line in lines if line)


def _tokens(name: str) -> str:
    return f'contains(concat(" ",normalize-space(@{name})," ")," %s ")'


def _rdfa_confirms(metadata: HtmlMetadata) -> bool:
    return any(key.endswith('content/encoded') for item in metadata.formats['rdfa'].items for key in item)


def _dom_candidates(tree, metadata: HtmlMetadata) -> list[ContentCandidate]:
    tests = [(_tokens('property') % name, name) for name in PROPERTIES]
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


def select_main_content(body: bytes, metadata: HtmlMetadata) -> MainContent:
    common = dict(body_sha256=metadata.body_sha256)
    def result(outcome, *, text=None, selected=None, candidates=(), reason=None):
        return MainContent(**common, outcome=outcome, text=text, selector=selected.selector if selected else None,
                           property=selected.property if selected else None, candidates=list(candidates), fallback_reason=reason)
    if metadata.document_kind != 'html' or metadata.error_title_hint:
        return result('none', reason='not_substantive')
    if metadata.document_truncated:  # a marked element may be among what the parser dropped
        return result('failed', reason='document_too_deep')
    tree = parse_document(body)
    if tree is None:
        return result('fallback_required', reason='unparseable')
    candidates = _dom_candidates(tree, metadata)
    distinct = list({candidate.text: candidate for candidate in reversed(candidates) if candidate.text}.values())[::-1]
    if len(distinct) > 1:
        return result('fallback_required', candidates=candidates, reason='multiple_candidates')
    if distinct and distinct[0].char_count >= SHORT_MARKED_CHARS:
        return result('marked', text=distinct[0].text, selected=distinct[0], candidates=candidates)
    if distinct:
        return result('marked_no_content', selected=distinct[0], candidates=candidates, reason='short_marked_text')
    return result('fallback_required', candidates=candidates, reason='empty_candidate' if candidates else 'no_candidate')
