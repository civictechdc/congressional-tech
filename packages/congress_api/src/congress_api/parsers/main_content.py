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
CONTENT_PROPERTY = 'content:encoded'
CONTENT_NAMESPACE = 'http://purl.org/rss/1.0/modules/content/'
CONTENT_PREFIX = re.compile(r'(?:^|\s)content:\s+(\S+)', re.I)
_DROPPED = {'script', 'style', 'noscript', 'template'}
_BLOCKS = {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'table', 'section', 'article',
           'blockquote', 'ul', 'ol', 'td', 'th', 'dt', 'dd', 'dl', 'hr', 'caption', 'pre', 'figure', 'figcaption'}
# Match declarations, including !important, without treating custom properties as CSS visibility.
HIDDEN_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)', re.I)
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
    return any(CONTENT_NAMESPACE + 'encoded' in item for item in metadata.formats['rdfa'].items)


def _rebound_content_prefix(elements) -> bool:
    for element in elements:
        prefix = CONTENT_PREFIX.search(element.get('prefix', ''))
        namespace = prefix.group(1) if prefix else element.get('xmlns:content')
        if namespace is not None:
            return namespace != CONTENT_NAMESPACE
    return False


def _dom_candidates(tree, metadata: HtmlMetadata) -> list[ContentCandidate]:
    marked = tree.xpath(f'//*[{_tokens("property") % CONTENT_PROPERTY}]')
    named = {node for node in marked if not _rebound_content_prefix((node, *node.iterancestors()))}
    roots = tree.getroottree()
    out = []
    confirmed = _rdfa_confirms(metadata)
    for node in marked:
        if node not in named:
            continue
        ancestors = tuple(node.iterancestors())
        if _hidden(node) or node.tag in _DROPPED or any(
            ancestor in named or ancestor.tag in _DROPPED or _hidden(ancestor) for ancestor in ancestors
        ):
            continue
        body = block_text(node)
        links = [
            ContentLink(href=link.get('href'), text=' '.join(block_text(link).split()))
            for link in node.xpath('.//a[@href]')
            if not _hidden(link) and not any(
                ancestor.tag in _DROPPED or _hidden(ancestor) for ancestor in link.iterancestors()
            )
        ]
        out.append(ContentCandidate(selector=roots.getpath(node), property=CONTENT_PROPERTY, text=body, char_count=len(body), links=links,
                                    rdfa_confirmed=confirmed))
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
    distinct = {}
    for candidate in candidates:
        if candidate.text:
            key = (candidate.text, tuple((link.href, link.text) for link in candidate.links))
            distinct.setdefault(key, candidate)
    distinct = list(distinct.values())
    if len(distinct) > 1:
        return result('fallback_required', candidates=candidates, reason='multiple_candidates')
    if distinct and distinct[0].char_count >= SHORT_MARKED_CHARS:
        return result('marked', text=distinct[0].text, selected=distinct[0], candidates=candidates)
    if distinct:
        return result('marked_no_content', selected=distinct[0], candidates=candidates, reason='short_marked_text')
    return result('fallback_required', candidates=candidates, reason='empty_candidate' if candidates else 'no_candidate')
