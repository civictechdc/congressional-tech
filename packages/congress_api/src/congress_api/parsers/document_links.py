"""Read explicit download links from supplied HTML; never fetch or guess URLs."""
import re
import ipaddress
from urllib.parse import urljoin, urlsplit, urlunsplit

from congress_api.models.documents import DocumentLink
from congress_api.parsers.page_content import page_trees

FILE = re.compile(r'\.(?:pdf|xml|docx?|xlsx?|pptx?|zip|rtf|txt|csv)(?:$|[?#])', re.I)
PROMPT = re.compile(r'(?:please )?click here[.!]?|download(?: file)?|continue|pdf|xml|docx?|xlsx?|pptx?|zip|rtf|txt|csv', re.I)


def remove_dot_segments(path):
    """Normalize literal URL path dots, preserving escapes and repeated slashes."""
    segments = path.split('/')
    result = []
    for index, segment in enumerate(segments):
        if segment == '..':
            if len(result) > 1:
                result.pop()
        elif segment != '.':
            result.append(segment)
        if segment in {'.', '..'} and index == len(segments) - 1:
            result.append('')
    return '/'.join(result)


def http_url(value, base=''):
    # urlsplit silently removes control characters; do not repair an authority
    # by deleting bytes. Spaces in publisher filenames remain valid path data.
    if not isinstance(value, str) or re.search(r'[\x00-\x1f\x7f]', value + base):
        return None
    try:
        url = urlsplit(urljoin(base, value))
        if url.scheme not in ('https', 'http') or not url.hostname or '@' in url.netloc:
            return None
        authority = url.netloc
        if authority.startswith('['):
            host, separator, tail = authority[1:].partition(']')
            if not separator or '%' in host or ipaddress.ip_address(host).version != 6:
                return None
        else:
            host, separator, port = authority.partition(':')
            tail = ':' + port if separator else ''
            host = host.encode('idna').decode('ascii').removesuffix('.')
            if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                                          for label in host.split('.')):
                return None
        if tail and (not re.fullmatch(r':[0-9]+', tail) or url.port is None):
            return None
        return urlunsplit(url._replace(path=remove_dot_segments(url.path), fragment=''))
    except (ValueError, UnicodeError):
        pass
    return None


def feed_link(node, url):
    """Publisher feeds describe a site, not an attached document."""
    return ((node.get('type') or '').lower() in {'application/rss+xml', 'application/atom+xml'}
            or bool(re.search(r'/(?:rss|atom|sitemap)\.xml(?:$|[?#])', url, re.I)))


def document_links(body: bytes, url: str) -> list[DocumentLink]:
    """Keep publisher labels/attributes, including malformed-but-working & URLs."""
    return links_from_trees(page_trees(body), url)


def links_from_trees(trees, url, *, include_link=None):
    """Use one link reader and URL deduplication for each supplied page tree."""
    result, seen = [], set()
    for selector, tree in trees:
        for link in tree_document_links(tree, url, include_link=include_link):
            if link.url not in seen:
                seen.add(link.url)
                if selector:
                    link = link.model_copy(update={'source_selector': selector})
                result.append(link)
    return result


def tree_document_links(tree, url, *, include_link=None):
    """One link reader for static markup and decoded publisher HTML fields."""
    bases = tree.xpath('//base[@href]/@href')
    base = (http_url(bases[0], url) if bases else None) or url
    result = []
    seen = set()
    for node in tree.xpath('//a[@href] | //object[@data] | //embed[@src] | //iframe[@src] | //meta[@http-equiv]'):
        value = node.get('href') or node.get('data') or node.get('src') or ''
        label = ' '.join(node.text_content().split())
        basis = None
        if node.tag == 'a':
            if (FILE.search(value) or node.get('download') is not None or PROMPT.fullmatch(label)
                    or 'wp-block-file__button' in node.get('class', '').split()):
                basis = 'download_link'
            elif include_link and include_link(node):
                basis = 'publisher_document_context'
        elif node.tag == 'meta' and node.get('http-equiv', '').lower() == 'refresh':
            if match := re.fullmatch(r'\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.+?)\s*', node.get('content', ''), re.I):
                value, basis = match[1].strip('\'"'), 'meta_refresh'
        elif node.tag in ('object', 'embed', 'iframe') and (
                node.get('type', '').lower() == 'application/pdf' or FILE.search(value)):
            basis = 'embedded_document'
        target = http_url(value, base) if value.strip() else None
        if basis and target and not feed_link(node, target) and target not in seen:
            seen.add(target)
            result.append(DocumentLink(url=target, basis=basis, text=label,
                                       tag=node.tag, attributes=dict(node.attrib)))
    return result


def response_kind(body: bytes, media_type: str) -> str:
    """Identify HTML before trusting a claimed PDF content type."""
    prefix = body[:1024].lstrip(b'\xef\xbb\xbf \t\r\n')
    if prefix.startswith(b'%PDF-'):
        return 'pdf'
    if prefix.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        return 'zip'  # Also includes Office documents; do not infer a subtype.
    if prefix.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return 'legacy_office'
    if prefix.startswith(b'{\\rtf'):
        return 'rtf'
    if body.startswith(b'rtfd'):
        return 'file_wrapper'
    if re.search(br'<(?:!doctype\s+html|html|head|body)\b', prefix, re.I):
        return 'html'
    media = media_type.split(';', 1)[0].strip().lower()
    if media in ('text/html', 'application/xhtml+xml'):
        return 'html'
    if prefix.startswith(b'<?xml'):
        return 'xml'
    if media == 'application/pdf':
        return 'unverified_pdf'  # Headers alone do not establish PDF bytes.
    return 'other'
