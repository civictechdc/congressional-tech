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

from lxml import etree, html as dom

from congress_api.models.html_metadata import ContentCandidate, ContentLink, HtmlMetadata, MainContent
from congress_api.parsers.html_metadata import page_facts, parse_document

SHORT_MARKED_CHARS = 200
# Empirical shrinkage guard fitted to 3 observed main_landmark content-loss cases
# (9d3094e1 Nicaragua open letter outside role=main, 653afe17 Senate Commerce header
# outside main, 9b166e1e Senate Banking notice inside a display:none container; ct-m704).
# Fitted to three cases: this is a safety guard, not a proof against other losses.
CMS_GUARD_MAX_CHOSEN_BYTES = 500
CMS_GUARD_MIN_DEFAULT_BYTES = 2000
CMS_GUARD_RATIO_DENOMINATOR = 10
CONTENT_PROPERTY = 'content:encoded'
CONTENT_NAMESPACE = 'http://purl.org/rss/1.0/modules/content/'
CONTENT_PREFIX = re.compile(r'(?:^|\s)content:\s+(\S+)', re.I)
_DROPPED = {'script', 'style', 'noscript', 'template'}
_VOID_TAGS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
})
_CMS_CHROME_TAGS = frozenset({'nav'})
_CMS_CHROME_ROLES = frozenset({'navigation', 'search', 'banner', 'contentinfo'})
_CMS_CHROME_CONTAINER_TAGS = frozenset({'header', 'footer', 'aside', 'div', 'section', 'ul'})
_CMS_CHROME_ATTR_RE = re.compile(
    r'(?:^|[\s_-])(?:'
    r'site-header|site-footer|site-nav(?:igation)?|main-nav(?:igation)?|'
    r'primary-nav(?:igation)?|secondary-nav(?:igation)?|'
    r'region-header|region-navigation|region-sidebar(?:-first|-second)?|region-footer|'
    r'navbar|nav-menu|menu-main|breadcrumb|breadcrumbs|'
    r'social-share|share-links|share-buttons|skip-link|skip-to-main|'
    r'cookie-banner|cookie-notice|search-form|search-block'
    r')(?:$|[\s_-])',
    re.I,
)
_BLOCKS = {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'table', 'section', 'article',
           'blockquote', 'ul', 'ol', 'td', 'th', 'dt', 'dd', 'dl', 'hr', 'caption', 'pre', 'figure', 'figcaption'}
# Match declarations, including !important, without treating custom properties as CSS visibility.
HIDDEN_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)', re.I)
SOFT_HYPHEN = '\u00ad'
_PRE_OPEN = '\x00PRE_OPEN\x00'
_PRE_CLOSE = '\x00PRE_CLOSE\x00'
_YEAR_4_RE = re.compile(r'\b(199[5-9]|20[0-3][0-9])\b')
_ISO_YEAR_PREFIX_RE = re.compile(r'^\s*(199[5-9]|20[0-3][0-9])-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])')
_CONGRESS_ORDINAL_RE = re.compile(r'\b(1[0-2][0-9])(?:st|nd|rd|th)\s+congress\b', re.I)
_CMS_CONGRESS_BANNER_RE = re.compile(
    r'^(?:'
    r'(?:the\s+|official\s+website\s+of\s+the\s+)?1[12][0-9](?:st|nd|rd|th)\s+congress(?:\s*[|–—•:/-]\s*[^\n.]{0,90})?|'
    r'[^\n.]{1,80}\s*[|–—•]\s*1[12][0-9](?:st|nd|rd|th)\s+congress'
    r')$',
    re.I,
)


def _hidden(element) -> bool:
    return 'hidden' in element.attrib or bool(HIDDEN_STYLE.search(element.get('style', '')))


def _is_cms_chrome(element) -> bool:
    tag = element.tag.lower() if isinstance(element.tag, str) else None
    if tag is None or tag in _VOID_TAGS:
        return False
    if tag in _CMS_CHROME_TAGS:
        return True
    role = (element.get('role') or '').strip().lower()
    if role in _CMS_CHROME_ROLES:
        return True
    if tag in _CMS_CHROME_CONTAINER_TAGS:
        tokens = f"{element.get('id', '')} {element.get('class', '')}"
        if tokens.strip() and _CMS_CHROME_ATTR_RE.search(tokens):
            return True
    return False


def infer_document_congress(text: str, *, declared_dates: tuple[str, ...] = ()) -> int | None:
    """Infer a page's Congress without pre-filtering 2025+ years (preserving live 119th Congress pages)."""
    pub_years = [
        int(m.group(1))
        for raw in declared_dates
        if isinstance(raw, str) and (m := _ISO_YEAR_PREFIX_RE.match(raw))
    ]
    if pub_years:
        max_pub = max(pub_years)
        return (max_pub - 1789) // 2 + 1

    prose_lines = [
        ln.strip()
        for ln in text[:4000].splitlines()
        if ln.strip() and not _CMS_CONGRESS_BANNER_RE.match(ln.strip())
    ]
    prose_sample = '\n'.join(prose_lines)
    years = [int(y) for y in _YEAR_4_RE.findall(prose_sample)]
    if years:
        max_yr = max(years)
        return (max_yr - 1789) // 2 + 1

    congs = [int(m.group(1)) for m in _CONGRESS_ORDINAL_RE.finditer(prose_sample)]
    return max(congs) if congs else None


def strip_cms_time_travel_lines(
    text: str,
    *,
    declared_dates: tuple[str, ...] = (),
    reference_congress: int | None = None,
) -> str:
    """Strip standalone live-CMS Congress banner lines (e.g. ``119th Congress``) on archived earlier-Congress pages."""
    if not text:
        return text
    doc_congress = reference_congress if reference_congress is not None else infer_document_congress(text, declared_dates=declared_dates)
    if doc_congress is None:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) <= 120 and '.' not in stripped and _CMS_CONGRESS_BANNER_RE.match(stripped):
            banner_congs = [int(m.group(1)) for m in _CONGRESS_ORDINAL_RE.finditer(stripped)]
            if banner_congs and max(banner_congs) > doc_congress:
                continue
        kept.append(line)
    return '\n'.join(kept)


def block_text(node) -> str:
    """Plain text keeping paragraph order, multi-line ``<pre>`` transcripts, and words intact at inline tags.

    html_text.extract_text(guess_layout=True) split words at inline tags on 7 of 45
    measured bodies ("t he"). The nested visible() in senate_page.py is the same idea
    but extracting it changes a byte-hashed parser; do that at its next re-version.
    Iterative, because real bodies nest past the recursion limit.
    """
    parts = []
    pre_depth = 0
    walker = etree.iterwalk(node, events=('start', 'end', 'comment', 'pi'))
    for event, element in walker:
        tag = element.tag.lower() if isinstance(element.tag, str) else None
        if event == 'start':
            if tag in _DROPPED or (
                tag is not None
                and element is not node
                and (_hidden(element) or _is_cms_chrome(element))
            ):
                walker.skip_subtree()  # the end event still comes, so the tail is kept (including void tags)
                continue
            if tag == 'pre':
                if pre_depth == 0:
                    parts.append('\n' + _PRE_OPEN)
                pre_depth += 1
            elif tag in _BLOCKS:
                parts.append('\n')
            parts.append(element.text or '')
            continue
        if event == 'end':
            if tag == 'pre' and pre_depth > 0:
                pre_depth -= 1
                if pre_depth == 0:
                    parts.append(_PRE_CLOSE + '\n')
            elif tag in _BLOCKS and tag not in _DROPPED:
                parts.append('\n')
        if element is not node:
            parts.append(element.tail or '')

    joined = ''.join(parts).replace(SOFT_HYPHEN, '')
    if _PRE_OPEN not in joined:
        lines = (' '.join(line.split()) for line in joined.splitlines())
        return '\n'.join(line for line in lines if line)

    out_lines: list[str] = []
    cursor = 0
    while cursor < len(joined):
        open_idx = joined.find(_PRE_OPEN, cursor)
        if open_idx == -1:
            for line in joined[cursor:].splitlines():
                collapsed = ' '.join(line.split())
                if collapsed:
                    out_lines.append(collapsed)
            break
        for line in joined[cursor:open_idx].splitlines():
            collapsed = ' '.join(line.split())
            if collapsed:
                out_lines.append(collapsed)
        pre_start = open_idx + len(_PRE_OPEN)
        close_idx = joined.find(_PRE_CLOSE, pre_start)
        if close_idx == -1:
            pre_body = joined[pre_start:]
            cursor = len(joined)
        else:
            pre_body = joined[pre_start:close_idx]
            cursor = close_idx + len(_PRE_CLOSE)
        if '\n' in pre_body:
            for line in pre_body.splitlines():
                trimmed = line.rstrip()
                if trimmed.strip():
                    out_lines.append(trimmed)
        else:
            collapsed = ' '.join(pre_body.split())
            if collapsed:
                out_lines.append(collapsed)
    return '\n'.join(out_lines)


def cms_cleaned_text_too_small(chosen_bytes: int, default_bytes: int) -> bool:
    """Return True when cleaned HTML leaves <500 UTF-8 bytes and <10% of a >=2,000-byte default.

    Fitted to three observed main_landmark losses (9d3094e1, 653afe17, 9b166e1e; ct-m704):
    guard only, not a proof that larger selections never lose content.
    """
    return (
        chosen_bytes < CMS_GUARD_MAX_CHOSEN_BYTES
        and default_bytes >= CMS_GUARD_MIN_DEFAULT_BYTES
        and chosen_bytes * CMS_GUARD_RATIO_DENOMINATOR < default_bytes
    )


def _unpruned_dom_text(node) -> str:
    """Visible+hidden non-script/style/title DOM text for shrinkage-guard baseline comparison."""
    parts = []
    dropped = _DROPPED | {'title'}
    walker = etree.iterwalk(node, events=('start', 'end', 'comment', 'pi'))
    for event, element in walker:
        tag = element.tag.lower() if isinstance(element.tag, str) else None
        if event == 'start':
            if tag in dropped:
                walker.skip_subtree()
                continue
            if tag in _BLOCKS:
                parts.append('\n')
            parts.append(element.text or '')
            continue
        if event == 'end' and tag in _BLOCKS and tag not in dropped:
            parts.append('\n')
        if element is not node:
            parts.append(element.tail or '')
    joined = ''.join(parts).replace(SOFT_HYPHEN, '')
    lines = (' '.join(line.split()) for line in joined.splitlines())
    return '\n'.join(line for line in lines if line)


def clean_congressional_html(raw_html: str | bytes, *, declared_dates: tuple[str, ...] = ()) -> str:
    """Extract clean Congressional page text, stripping CMS ``<nav>``/header/sidebar chrome,
    preserving ``<pre>`` hearing transcripts, keeping text past void chrome tags, and removing
    retroactive ``119th Congress`` banners on archived earlier-Congress pages."""
    data = raw_html.encode('utf-8', errors='replace') if isinstance(raw_html, str) else raw_html
    tree = parse_document(data)
    if tree is None:
        return ''
    roots = tree.xpath('//body') or [tree]
    mains = [
        m for m in roots[0].xpath('.//main | .//*[@role="main"]')
        if not _hidden(m) and not any(_hidden(a) for a in m.iterancestors())
    ]
    target = mains[0] if len(mains) == 1 and sum(not c.isspace() for c in block_text(mains[0])) >= 40 else roots[0]
    cleaned = strip_cms_time_travel_lines(block_text(target), declared_dates=declared_dates)
    chosen_bytes = len(cleaned.encode('utf-8'))
    if chosen_bytes < CMS_GUARD_MAX_CHOSEN_BYTES:
        default_text = _unpruned_dom_text(roots[0])
        if cms_cleaned_text_too_small(chosen_bytes, len(default_text.encode('utf-8'))):
            return default_text
    return cleaned


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


def _declared_published_dates(metadata: HtmlMetadata) -> tuple[str, ...]:
    if metadata.error_title_hint:
        return ()
    return tuple(
        fact.value
        for fact in page_facts(metadata)
        if fact.field == 'published_time' and isinstance(fact.value, str)
    )


def _dom_candidates(tree, metadata: HtmlMetadata) -> list[ContentCandidate]:
    marked = tree.xpath(f'//*[{_tokens("property") % CONTENT_PROPERTY}]')
    named = {node for node in marked if not _rebound_content_prefix((node, *node.iterancestors()))}
    roots = tree.getroottree()
    out = []
    confirmed = _rdfa_confirms(metadata)
    declared_dates = _declared_published_dates(metadata)
    for node in marked:
        if node not in named:
            continue
        ancestors = tuple(node.iterancestors())
        if _hidden(node) or node.tag in _DROPPED or any(
            ancestor in named or ancestor.tag in _DROPPED or _hidden(ancestor) for ancestor in ancestors
        ):
            continue
        body = strip_cms_time_travel_lines(block_text(node), declared_dates=declared_dates)
        links = [
            ContentLink(href=link.get('href'), text=' '.join(block_text(link).split()))
            for link in node.xpath('.//a[@href]')
            if not _hidden(link) and not any(
                ancestor is not node
                and (ancestor.tag in _DROPPED or _hidden(ancestor) or _is_cms_chrome(ancestor))
                for ancestor in link.iterancestors()
            ) and not any(
                ancestor is node and (ancestor.tag in _DROPPED or _hidden(ancestor))
                for ancestor in link.iterancestors()
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
