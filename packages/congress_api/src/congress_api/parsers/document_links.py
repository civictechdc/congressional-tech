"""Read explicit download links from supplied HTML; never fetch or guess URLs."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree, html

from congress_api.models.documents import DocumentLink

FILE = re.compile(r'\.(?:pdf|xml|docx?|xlsx?|pptx?|zip|rtf|txt|csv)(?:$|[?#])', re.I)
PROMPT = re.compile(r'(?:please )?click here[.!]?|download(?: file)?|continue|pdf|xml|docx?|xlsx?|pptx?|zip|rtf|txt|csv', re.I)


def http_url(value, base=''):
    try:
        url = urlsplit(urljoin(base, value))
        if url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password:
            return urlunsplit(url._replace(fragment=''))
    except ValueError:
        pass
    return None


def document_links(body: bytes, url: str) -> list[DocumentLink]:
    """Keep publisher labels/attributes, including malformed-but-working & URLs."""
    try:
        tree = html.fromstring(body, parser=html.HTMLParser(no_network=True))
    except (etree.ParserError, ValueError):
        return []
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
        elif node.tag == 'meta' and node.get('http-equiv', '').lower() == 'refresh':
            if match := re.fullmatch(r'\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.+?)\s*', node.get('content', ''), re.I):
                value, basis = match[1].strip('\'"'), 'meta_refresh'
        elif node.tag in ('object', 'embed', 'iframe') and (
                node.get('type', '').lower() == 'application/pdf' or FILE.search(value)):
            basis = 'embedded_document'
        target = http_url(value, base) if value.strip() else None
        if basis and target and target not in seen:
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
