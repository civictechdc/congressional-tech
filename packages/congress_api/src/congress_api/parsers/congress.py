"""Decode upstream Congress.gov bodies and Congressional HTML chrome independently of storage."""

import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from congress_api.models.congress import (
    CommitteeMeeting,
    CommitteeResponse,
    CommitteesPage,
    MeetingResponse,
    MeetingsPage,
)
from congress_api.models.congress_xml import CongressXmlDocument
from congress_api.models.content import RawContent
from congress_api.parsers.xml import parse_xml_element

CongressResponse = MeetingsPage | MeetingResponse | CommitteesPage | CommitteeResponse | CongressXmlDocument

_HTML_SNIFF_RE = re.compile(
    r'^(?:\s|\ufeff|<\?xml[^>]*\?>|<!--[\s\S]{0,1024}?-->)*<(?:!doctype\s+html\b|html[\s>/])',
    re.I,
)
_BARE_UUID_RE = re.compile(
    r'(?:^|/)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:[/?#]|$)',
    re.I,
)
_EXPLICIT_HTML_EXT_RE = re.compile(r'\.(?:x?html?|shtml|asp|aspx|cfm|php|jsp)$', re.I)
_NON_HTML_EXT_RE = re.compile(r'\.(?:pdf|xml|json|zip|mp4|mp3|vtt|m3u8|docx?|xlsx?|pptx?|rtf|csv)$', re.I)
_HIDDEN_CSS_RE = re.compile(
    r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)',
    re.I,
)
_CHROME_TOKEN_RE = re.compile(
    r'(?:^|[\s_-])(?:nav|navbar|navigation|menu|menubar|superfish|megamenu|breadcrumb|breadcrumbs|'
    r'sidebar|sidenav|subnav|skip-link|skiplink|site-header|site-footer|global-header|global-footer|'
    r'region-header|region-navigation|region-sidebar|region-footer|header-nav|footer-nav|mobile-menu|'
    r'social-share|share-links|cookie-banner|alert-banner|congress-banner)(?:$|[\s_-])',
    re.I,
)
_CONTENT_PROTECT_RE = re.compile(
    r'(?:^|[\s_-])(?:main|main-content|content-area|article|entry-content|post-content|node-content|'
    r'field-name-body|hearing-body|hearing-detail|press-release|testimony)(?:$|[\s_-])',
    re.I,
)
_ORDINAL_CONGRESS_RE = re.compile(r'\b(1[0-2]\d)\s*(?:th|st|nd|rd)\s+Congress\b', re.I)
_YEAR_4_RE = re.compile(r'\b(199\d|20[0-2]\d)\b')
_GPO_PRE_BANNER_RE = re.compile(
    r'\[(?:House|Senate|Joint)\s+Hearing\b[^\]]*\]\s*\[From the U\.S\. Government (?:Publishing|Printing) Office\]',
    re.I,
)
_DOCS_HOUSE_WEEKLY_RE = re.compile(
    r'\b(?:Bills\s+This\s+Week|Floor\s+Proceedings\s*\|\s*house\.gov)\b',
    re.I,
)
_CMS_LEAD_CUES_RE = re.compile(
    r'^(?:Skip\s+to\s+(?:main\s+)?content\b|Toggle\s+navigation\b|Main\s+navigation\b|'
    r'Breadcrumb\b|Search\s+Search\b|MENU\s+Home\b|×\s*Close\b)',
    re.I,
)
_BREADCRUMB_TRAIL_RE = re.compile(
    r'^(?:Home\s*(?:>|»|/|\|)\s*)+(?:Committee\s+Activity|Hearings?|Markups?|Events?|News|Press\s+Releases?|Legislation)'
    r'(?:\s*(?:>|»|/|\|)\s*[^\n]{1,120})?\s*',
    re.I,
)
_DRUPAL_CLOSE_NAV_RE = re.compile(
    r'^[\s\S]{0,1800}?(?:×\s*Close|Close\s+menu|Toggle\s+navigation|Main\s+menu)\s+',
    re.I,
)
_COLDFUSION_MAJORITY_CHROME_RE = re.compile(
    r'^(?:Majority\s*(?:\||:)\s*Minority\s+|Majority\s+News\s+Minority\s+News\s+|'
    r'(?:1[0-2]\d(?:th|st|nd|rd)\s+Congress\s+)+(?:Majority|Minority|Chair(?:man|woman)?|Ranking\s+Member)[^\n]{0,180}\n+)',
    re.I,
)
_TRAILING_FOOTER_CHROME_RE = re.compile(
    r'\n+(?:Privacy\s+Policy\s*\|\s*Accessibility|Sign\s+up\s+for\s+(?:newsletter|updates)|'
    r'Office\s+Locations?\s+Washington,?\s+D\.?C\.?\s+Office[\s\S]{0,400})$',
    re.I,
)


def _year_to_congress(year: int) -> int:
    return ((year - 1789) // 2) + 1


def sniff_html_markup(content: bytes | str | None) -> bool:
    """Return True if ``content`` begins with an HTML ``<!DOCTYPE html`` or ``<html`` root."""
    if not content:
        return False
    if isinstance(content, bytes):
        head = content[:2048].decode('utf-8', errors='ignore')
    else:
        head = content[:2048]
    return bool(_HTML_SNIFF_RE.match(head))


def is_bare_uuid_html(content: bytes | str | None, url_or_filename: str | None = None) -> bool:
    """Detect content-sniffed HTML (``<!DOCTYPE html`` / ``<html``) when URL/name lacks ``.html``/``.htm``.

    Covers Senate/House bare-UUID download endpoints (e.g. ``/imo/media/doc/<uuid>``,
    ``/hearings/.../<uuid>``) and extensionless committee URLs that serve HTML bodies.
    """
    if not sniff_html_markup(content):
        return False
    if not url_or_filename:
        return True
    parsed_path = urlsplit(url_or_filename.strip()).path or url_or_filename.strip()
    leaf = parsed_path.rstrip('/').rsplit('/', 1)[-1]
    if _EXPLICIT_HTML_EXT_RE.search(leaf):
        return False
    if _BARE_UUID_RE.search(parsed_path):
        return True
    if '.' not in leaf or _NON_HTML_EXT_RE.search(leaf):
        return True
    return True


def _infer_archived_congress_from_body(body_text: str, explicit_congress: int | None) -> int | None:
    if explicit_congress is not None and 90 <= explicit_congress <= 130:
        return explicit_congress
    # Look past top chrome for historical proceeding dates (e.g. 2011..2024 vs live 119th Congress banner).
    years = [int(y) for y in _YEAR_4_RE.findall(body_text[:4000]) if 1995 <= int(y) <= 2024]
    if years:
        # Use max historical year in body if clearly pre-119th Congress (<= 2024).
        max_yr = max(years)
        if max_yr <= 2024:
            return _year_to_congress(max_yr)
    return None


def strip_cms_text_chrome(text: str, *, target_congress: int | None = None) -> str:
    """Strip Congressional CMS nav/header/sidebar chrome & live-Congress time-travel pollution from text."""
    if not text:
        return ''
    if _GPO_PRE_BANNER_RE.search(text[:600]) or _DOCS_HOUSE_WEEKLY_RE.search(text[:600]):
        return text

    cur = text.replace('\u00ad', '')
    inferred_cong = _infer_archived_congress_from_body(cur, target_congress)

    # Strip leading CMS skip-links / menu / close-drawer blocks when substantive text remains.
    m_close = _DRUPAL_CLOSE_NAV_RE.match(cur)
    if m_close and len(cur) - m_close.end() >= 80:
        cur = cur[m_close.end():]

    lines = cur.splitlines()
    cleaned_lines: list[str] = []
    in_leading_chrome = True

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if not in_leading_chrome:
                cleaned_lines.append('')
            continue

        if in_leading_chrome and idx < 35:
            if _CMS_LEAD_CUES_RE.match(stripped) or _BREADCRUMB_TRAIL_RE.match(stripped):
                continue
            if _COLDFUSION_MAJORITY_CHROME_RE.match(stripped + '\n'):
                continue
            # Time-travel guard: drop short header/sidebar banner lines naming a newer live Congress
            # (e.g. "119th Congress" or "119th Congress | House Committee on ...") on an archived 111th-118th page.
            cong_hits = [int(m.group(1)) for m in _ORDINAL_CONGRESS_RE.finditer(stripped)]
            if cong_hits and inferred_cong is not None and any(c > inferred_cong for c in cong_hits):
                if len(stripped) <= 180:
                    continue
            if stripped.lower() in {
                'home', 'about', 'subcommittees', 'hearings', 'markups', 'legislation',
                'news', 'press releases', 'contact', 'calendar', 'watch live', 'majority', 'minority',
                'menu', 'search', 'skip to content', 'skip to main content',
            }:
                continue
            in_leading_chrome = False
        elif inferred_cong is not None and len(stripped) <= 140:
            # Also guard sidebar/footer chrome lines carrying a time-traveled live Congress ordinal
            cong_hits = [int(m.group(1)) for m in _ORDINAL_CONGRESS_RE.finditer(stripped)]
            if cong_hits and any(c > inferred_cong for c in cong_hits) and re.search(
                r'\b(?:majority|minority|chair(?:man|woman)?|ranking\s+member|navigation|menu|copyright|official\s+website)\b',
                stripped,
                re.I,
            ):
                continue

        cleaned_lines.append(line)

    candidate = '\n'.join(cleaned_lines).strip()
    candidate = _BREADCRUMB_TRAIL_RE.sub('', candidate, count=1).strip()
    candidate = _TRAILING_FOOTER_CHROME_RE.sub('', candidate).strip()
    if len(candidate) >= 40 or not text.strip():
        return candidate
    return text.strip()


class _CongressionalHtmlCleaner(HTMLParser):
    """Stdlib HTML cleaner that drops script/style/nav/sidebar chrome and preserves ``<pre>`` transcripts."""

    _DROP_TAGS = frozenset({'script', 'style', 'noscript', 'template', 'nav', 'aside', 'svg', 'iframe'})
    _BLOCK_TAGS = frozenset({
        'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'table',
        'section', 'article', 'blockquote', 'ul', 'ol', 'td', 'th', 'dt', 'dd', 'dl',
        'hr', 'caption', 'figure', 'figcaption', 'main', 'header', 'footer',
    })

    def __init__(self, *, target_congress: int | None = None) -> None:
        super().__init__(convert_charrefs=False)
        self._target_congress = target_congress
        self._skip_stack: list[str] = []
        self._pre_depth = 0
        self._segments: list[tuple[bool, str]] = []
        self._buf: list[str] = []

    def _flush(self, is_pre: bool) -> None:
        if self._buf:
            self._segments.append((is_pre, ''.join(self._buf)))
            self._buf = []

    def _should_drop_element(self, tag: str, attrs_dict: dict[str, str]) -> bool:
        if tag in self._DROP_TAGS:
            return True
        if 'hidden' in attrs_dict or attrs_dict.get('aria-hidden', '').lower() == 'true':
            return True
        style = attrs_dict.get('style', '')
        if style and _HIDDEN_CSS_RE.search(style):
            return True
        role = attrs_dict.get('role', '').strip().lower()
        if role in {'navigation', 'menubar', 'complementary', 'search'}:
            return True
        ident = f"{attrs_dict.get('id', '')} {attrs_dict.get('class', '')}".strip()
        if tag in {'header', 'footer'} and not _CONTENT_PROTECT_RE.search(ident):
            # Drop page-level chrome headers/footers unless inside <article>/<main> heading
            if role in {'banner', 'contentinfo'} or _CHROME_TOKEN_RE.search(ident) or tag == 'footer':
                return True
        if ident and _CHROME_TOKEN_RE.search(ident) and not _CONTENT_PROTECT_RE.search(ident):
            return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._skip_stack:
            self._skip_stack.append(t)
            return
        attrs_dict = {k.lower(): (v or '') for k, v in attrs if k}
        if self._should_drop_element(t, attrs_dict):
            self._skip_stack.append(t)
            return
        if t == 'pre':
            if self._pre_depth == 0:
                self._flush(False)
            self._pre_depth += 1
            return
        if self._pre_depth == 0 and t in self._BLOCK_TAGS:
            self._buf.append('\n')

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._skip_stack:
            if self._skip_stack[-1] == t:
                self._skip_stack.pop()
            elif t in self._skip_stack:
                while self._skip_stack and self._skip_stack[-1] != t:
                    self._skip_stack.pop()
                if self._skip_stack:
                    self._skip_stack.pop()
            return
        if t == 'pre' and self._pre_depth > 0:
            self._pre_depth -= 1
            if self._pre_depth == 0:
                self._flush(True)
            return
        if self._pre_depth == 0 and t in self._BLOCK_TAGS:
            self._buf.append('\n')

    def handle_data(self, data: str) -> None:
        if not self._skip_stack:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_stack:
            self._buf.append(html.unescape(f'&{name};'))

    def handle_charref(self, name: str) -> None:
        if not self._skip_stack:
            self._buf.append(html.unescape(f'&#{name};'))

    def get_text(self) -> str:
        self._flush(self._pre_depth > 0)
        rendered: list[str] = []
        for is_pre, chunk in self._segments:
            cleaned = chunk.replace('\u00ad', '').replace('\r\n', '\n').replace('\r', '\n')
            if is_pre:
                pre_txt = cleaned.strip('\n')
                if pre_txt.strip():
                    rendered.append(pre_txt if '\n' in pre_txt else pre_txt.strip())
            else:
                lines = [' '.join(line.split()) for line in cleaned.splitlines()]
                prose = '\n'.join(line for line in lines if line)
                if prose:
                    rendered.append(prose)
        joined = '\n'.join(rendered)
        if any(is_pre for is_pre, _ in self._segments):
            # Strip CMS chrome only outside preformatted transcript blocks when a page wraps <pre> in CMS layout
            if len(self._segments) > 1:
                non_pre_cleaned: list[str] = []
                for is_pre, chunk in self._segments:
                    cleaned = chunk.replace('\u00ad', '').replace('\r\n', '\n').replace('\r', '\n')
                    if is_pre:
                        pre_txt = cleaned.strip('\n')
                        if pre_txt.strip():
                            non_pre_cleaned.append(pre_txt if '\n' in pre_txt else pre_txt.strip())
                    else:
                        lines = [' '.join(line.split()) for line in cleaned.splitlines()]
                        prose = '\n'.join(line for line in lines if line)
                        prose = strip_cms_text_chrome(prose, target_congress=self._target_congress)
                        if prose:
                            non_pre_cleaned.append(prose)
                return '\n'.join(non_pre_cleaned).strip()
            return joined.strip()
        return strip_cms_text_chrome(joined, target_congress=self._target_congress)


def clean_congressional_html(
    raw_html: bytes | str,
    *,
    target_congress: int | None = None,
) -> str:
    """Strip Congressional CMS ``<nav>``/header/sidebar chrome & scripts while preserving ``<pre>`` transcripts."""
    if isinstance(raw_html, bytes):
        try:
            text = raw_html.decode('utf-8')
        except UnicodeDecodeError:
            text = raw_html.decode('cp1252', errors='replace')
    else:
        text = raw_html
    if not sniff_html_markup(text) and '<' not in text:
        return strip_cms_text_chrome(text, target_congress=target_congress)
    cleaner = _CongressionalHtmlCleaner(target_congress=target_congress)
    cleaner.feed(text)
    cleaner.close()
    return cleaner.get_text()


def parse_congress_xml(data: bytes | str) -> CongressXmlDocument:
    content = data if isinstance(data, bytes) else data.encode("utf-8")
    root = parse_xml_element(content)
    if root.tag != "api-root":
        raise ValueError("Congress.gov XML requires an api-root element")
    return CongressXmlDocument(xml=root, content=RawContent.from_bytes(content, "application/xml"))


# Only known meeting list containers and integer fields are interpreted. Every
# original value, attribute and unknown node remains in _source_xml.
_MEETING_LISTS = {
    ('committees',): 'item', ('witnesses',): 'item', ('videos',): 'item',
    ('meetingDocuments',): 'item', ('witnessDocuments',): 'item',
    ('continuations',): 'item', ('hearingTranscript',): 'item',
    ('relatedItems', 'bills'): 'bill', ('relatedItems', 'treaties'): 'item',
    ('relatedItems', 'nominations'): 'item',
}


_MEETING_INTEGERS = {
    ('congress',), ('hearingTranscript', '*', 'jacketNumber'),
    ('relatedItems', 'bills', '*', 'congress'),
    ('relatedItems', 'treaties', '*', 'congress'), ('relatedItems', 'treaties', '*', 'number'),
    ('relatedItems', 'nominations', '*', 'congress'), ('relatedItems', 'nominations', '*', 'number'),
}


def meeting_from_xml(source: CongressXmlDocument) -> CommitteeMeeting:
    """Interpret a retained XML meeting for existing readers without losing bytes.

    This is not a JSON response: _source_xml marks the interpretation and retains
    its evidence. Unknown values stay literal. Malformed known structures fail
    instead of silently dropping children or flattening repeated scalar fields.
    """
    meetings = source.xml.findall('committeeMeeting')
    if len(meetings) != 1:
        raise ValueError('Congress.gov XML must contain exactly one committeeMeeting')

    def value(node, path=()):
        if path in _MEETING_LISTS:
            if node.text.strip() or any(child.tag != _MEETING_LISTS[path] or child.tail.strip() for child in node.children):
                raise ValueError(f'Unexpected XML list structure at {path}')
            return [value(child, (*path, '*')) for child in node.children]
        if path in {('location',), ('relatedItems',)} and not node.children and not node.text.strip():
            return {}
        if node.children:
            result = {}
            for child in node.children:
                if child.tag in result:
                    raise ValueError(f'Repeated XML field at {(*path, child.tag)}')
                result[child.tag] = value(child, (*path, child.tag))
            return result
        if path in _MEETING_INTEGERS:
            text = node.text.strip()
            if not text.isascii() or not text.isdecimal():
                raise ValueError(f'Invalid XML integer at {path}')
            return int(text)
        return node.text

    fields = value(meetings[0])
    fields['_source_xml'] = source.content.source_dict()
    return CommitteeMeeting.model_validate(fields)
