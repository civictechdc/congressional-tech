"""Fetch, verify, extract, cache, and slice archived document body text outside the query worker."""
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import gzip
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zlib

from . import __version__
from .models import DocumentQuery, ExplorerError, MAX_BYTES
from .release import atomic_json, encoded

MAX_BODY_BYTES = 64 << 20
SNIPPET_CONTEXT_CHARS = 160

TEXT_FORMATS = frozenset({'pdf', 'html', 'htm', 'xhtml', 'xml', 'text', 'txt', 'json', 'csv', 'md', 'vtt', 'm3u8'})
UNSUPPORTED_FORMATS = frozenset({
    'mp4', 'mp2t', 'ts', 'm4a', 'mp3', 'wav', 'webm', 'mov', 'avi',
    'zip', 'tar', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'tiff', 'bmp', 'ico',
    'other', 'binary', 'empty',
})
_BLOCK_TAGS = frozenset({
    'p', 'div', 'br', 'li', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'pre', 'blockquote', 'section', 'article', 'header', 'footer', 'table', 'hr',
})
_SKIP_TAGS = frozenset({'script', 'style', 'head', 'noscript', 'svg', 'template'})


class _MarkupTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        lower = tag.lower()
        if lower in _SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and lower in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        lower = tag.lower()
        if lower in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and lower in _BLOCK_TAGS:
            self.parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0 and data:
            self.parts.append(data)

    def get_text(self) -> str:
        raw = unescape(''.join(self.parts))
        lines = [re.sub(r'[ \t\r\f\v]+', ' ', line).strip() for line in raw.splitlines()]
        cleaned: list[str] = []
        blank = False
        for line in lines:
            if line:
                cleaned.append(line)
                blank = False
            elif cleaned and not blank:
                cleaned.append('')
                blank = True
        while cleaned and not cleaned[-1]:
            cleaned.pop()
        return '\n'.join(cleaned)


def _normalize_format(fmt: str | None, media_type: str | None, filename: str | None) -> str:
    kind = (fmt or '').strip().lower()
    if kind in UNSUPPORTED_FORMATS:
        raise ExplorerError(f'Unsupported document format {kind!r} for text extraction')
    if kind in TEXT_FORMATS:
        if kind in ('htm', 'xhtml'):
            return 'html'
        if kind == 'txt':
            return 'text'
        return kind
    media = (media_type or '').split(';', 1)[0].strip().lower()
    if media == 'application/pdf':
        return 'pdf'
    if media in ('text/html', 'application/xhtml+xml'):
        return 'html'
    if media in ('application/xml', 'text/xml'):
        return 'xml'
    if media.startswith('text/') or media == 'application/json':
        return 'text'
    ext = Path(filename or '').suffix.lower().lstrip('.')
    if ext in TEXT_FORMATS:
        return 'html' if ext in ('htm', 'xhtml') else ('text' if ext == 'txt' else ext)
    raise ExplorerError(f'Unsupported document format {fmt or media_type or ext or "unknown"!r} for text extraction')


def _validate_archive_url(saved_url: str | None, archive_origin: str | None, saved_body: str | None, saved_suffix: str | None) -> tuple[str, str, str]:
    if not saved_body or not saved_url or not archive_origin:
        raise ExplorerError('Document has no verified archived body URL in this release')
    body_hex = saved_body.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', body_hex):
        raise ExplorerError('Invalid published body digest')
    suffix = saved_suffix or ''
    if suffix not in ('', '.pdf', '.gz'):
        raise ExplorerError('Invalid published body suffix')
    origin_parts = urlsplit(archive_origin)
    if (
        origin_parts.scheme not in ('http', 'https')
        or not origin_parts.netloc
        or origin_parts.username
        or origin_parts.password
        or origin_parts.query
        or origin_parts.fragment
        or origin_parts.path not in ('', '/')
    ):
        raise ExplorerError('Archive origin must be an HTTP(S) origin without path, query, or credentials')
    url_parts = urlsplit(saved_url)
    expected_path = f'/bodies/sha256/{body_hex[:2]}/{body_hex}{suffix}'
    if (
        url_parts.scheme != origin_parts.scheme
        or url_parts.netloc != origin_parts.netloc
        or url_parts.username
        or url_parts.password
        or url_parts.query
        or url_parts.fragment
        or url_parts.path != expected_path
    ):
        raise ExplorerError('Refusing to fetch document body outside archive_origin')
    return saved_url, body_hex, suffix


def _fetch_raw_bytes(saved_url: str, origin_netloc: str, origin_scheme: str, *, timeout: float, max_bytes: int) -> bytes:
    request = Request(saved_url, headers={'User-Agent': f'CongressExplorerMCP/{__version__}'})
    try:
        with urlopen(request, timeout=timeout) as stream:
            final = urlsplit(stream.url)
            if final.scheme != origin_scheme or final.netloc != origin_netloc:
                raise ExplorerError('Archive body fetch redirected outside archive_origin')
            chunks: list[bytes] = []
            total = 0
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ExplorerError(f'Fetched document body exceeds size limit ({max_bytes} bytes)')
                chunks.append(chunk)
            return b''.join(chunks)
    except ExplorerError:
        raise
    except TimeoutError as error:
        raise ExplorerError('Document body fetch timed out') from error
    except (HTTPError, URLError, OSError) as error:
        if 'timed out' in str(error).lower():
            raise ExplorerError('Document body fetch timed out') from error
        raise ExplorerError(f'Failed to fetch archived document body: {error}') from error


def _decompress_bounded(raw_bytes: bytes, *, max_bytes: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as gz:
            chunks: list[bytes] = []
            total = 0
            while chunk := gz.read(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ExplorerError(f'Decompressed document body exceeds size limit ({max_bytes} bytes)')
                chunks.append(chunk)
            return b''.join(chunks)
    except ExplorerError:
        raise
    except (OSError, EOFError, zlib.error) as error:
        raise ExplorerError(f'Invalid gzip stream in archived document body: {error}') from error


def verify_and_decode_body(raw_bytes: bytes, saved_body_hex: str, saved_suffix: str, *, max_bytes: int) -> bytes:
    """Verify SHA-256 against detail.saved_body before decompressing (.gz) or parsing.

    Supports both:
    1. Wire-digest pin: sha256(raw_bytes) == bytes.fromhex(saved_body_hex), followed by bounded
       .gz decompression when saved_suffix == '.gz' and the bytes start with gzip magic.
    2. R2 content-addressed .gz storage encoding (readings.py _storage_gzip): when saved_suffix == '.gz'
       and raw_bytes is a gzip stream whose bounded decompression hashes to bytes.fromhex(saved_body_hex).
    """
    expected_digest = bytes.fromhex(saved_body_hex)
    raw_digest = sha256(raw_bytes).digest()
    if raw_digest == expected_digest:
        if saved_suffix == '.gz' and raw_bytes.startswith(b'\x1f\x8b'):
            return _decompress_bounded(raw_bytes, max_bytes=max_bytes)
        return raw_bytes
    if saved_suffix == '.gz' and raw_bytes.startswith(b'\x1f\x8b'):
        decoded = _decompress_bounded(raw_bytes, max_bytes=max_bytes)
        if sha256(decoded).digest() == expected_digest:
            return decoded
    raise ExplorerError('Fetched document body SHA-256 does not match published saved_body')


def _extract_pdf_pages(payload: bytes) -> list[str]:
    header_pos = payload.find(b'%PDF-', 0, 1024)
    if header_pos < 0:
        raise ExplorerError('Invalid or corrupt PDF body')
    pdf_data = payload[header_pos:]
    # 1. Primary: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_data), strict=False)
        if len(reader.pages) > 0:
            pages = [(page.extract_text() or '').strip() for page in reader.pages]
            if any(pages):
                return pages
    except Exception:
        pass
    # 2. Secondary: poppler pdftotext
    pdftotext = shutil.which('pdftotext')
    if pdftotext:
        try:
            proc = subprocess.run(
                [pdftotext, '-q', '-', '-'],
                input=pdf_data,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                raw_pages = proc.stdout.decode('utf-8', errors='replace').split('\f')
                if raw_pages and raw_pages[-1] == '':
                    raw_pages.pop()
                pages = [p.strip() for p in raw_pages]
                if any(pages):
                    return pages
        except Exception:
            pass
    # 3. Fallback for minimal PDF streams with literal (text) Tj operators
    blocks = re.findall(rb'BT\b(.*?)\bET', pdf_data, flags=re.DOTALL)
    if blocks:
        pages = []
        for block in blocks:
            tokens = re.findall(rb'\((?:\\.|[^\\()])*\)', block)
            lines = []
            for tok in tokens:
                inner = tok[1:-1].replace(b'\\(', b'(').replace(b'\\)', b')').replace(b'\\\\', b'\\')
                lines.append(inner.decode('latin-1', errors='replace'))
            pages.append('\n'.join(lines).strip())
        if any(pages):
            return pages
    raise ExplorerError('Unable to extract text from PDF body')


def _extract_xml_text(payload: bytes) -> str:
    parser = _MarkupTextExtractor()
    parser.feed(payload.decode('utf-8', errors='replace'))
    parser.close()
    return parser.get_text()


def extract_pages(payload: bytes, fmt: str) -> list[str]:
    if fmt == 'pdf' or payload.startswith(b'%PDF-'):
        return _extract_pdf_pages(payload)
    if b'\x00' in payload[:8192]:
        raise ExplorerError('Unsupported binary document body')
    if fmt in ('html', 'xml'):
        return [_extract_xml_text(payload)]
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = payload.decode('latin-1')
    return [text.strip()]


def _load_or_extract_pages(
    target: dict,
    *,
    data_dir: Path | None,
    timeout: float,
    max_bytes: int,
) -> tuple[list[str], str, str, str]:
    fmt = _normalize_format(target.get('format'), target.get('saved_media_type'), target.get('filename'))
    saved_url, body_hex, suffix = _validate_archive_url(
        target.get('saved_url'),
        target.get('archive_origin'),
        target.get('saved_body'),
        target.get('saved_suffix'),
    )
    cache_path = (Path(data_dir) / 'bodies' / f'{body_hex}.json') if data_dir is not None else None
    if cache_path is not None:
        if cache_path.is_symlink():
            raise ExplorerError('Cached document body entry is a symlink')
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_bytes())
            except Exception as error:
                raise ExplorerError('Corrupt cached document body') from error
            if (
                not isinstance(cached, dict)
                or cached.get('version') != 1
                or cached.get('saved_body') != body_hex
                or not isinstance(cached.get('pages'), list)
                or not all(isinstance(p, str) for p in cached['pages'])
            ):
                raise ExplorerError('Corrupt cached document body')
            return cached['pages'], fmt, body_hex, saved_url

    origin_parts = urlsplit(target['archive_origin'])
    raw_bytes = _fetch_raw_bytes(
        saved_url,
        origin_parts.netloc,
        origin_parts.scheme,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    decoded = verify_and_decode_body(raw_bytes, body_hex, suffix, max_bytes=max_bytes)
    pages = extract_pages(decoded, fmt)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(
            cache_path,
            dict(
                version=1,
                saved_body=body_hex,
                format=fmt,
                page_count=len(pages),
                pages=pages,
            ),
        )
    return pages, fmt, body_hex, saved_url


def _compile_query(query: str) -> re.Pattern[str]:
    try:
        return re.compile(query, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(query), re.IGNORECASE)


def read_document_body(
    target: dict,
    query: DocumentQuery | dict,
    *,
    data_dir: Path | None = None,
    timeout: float = 10.0,
) -> dict:
    query = query if isinstance(query, DocumentQuery) else DocumentQuery.model_validate(query)
    if query.cursor:
        raise ExplorerError('Text section uses page or offset, not cursor')
    resolved_dir = data_dir or (Path(target['data_dir']) if target.get('data_dir') else None)
    pages, fmt, body_hex, saved_url = _load_or_extract_pages(
        target,
        data_dir=resolved_dir,
        timeout=timeout,
        max_bytes=MAX_BODY_BYTES,
    )
    page_count = len(pages)
    if query.page is not None and query.page > page_count:
        raise ExplorerError(f'Requested page {query.page} exceeds document page_count ({page_count})')

    base = dict(
        release_id=target['release_id'],
        reference=target['reference'],
        filename=target.get('filename'),
        title=target.get('title'),
        format=fmt,
        saved_kind=target.get('saved_kind'),
        saved_body=body_hex,
        saved_url=saved_url,
        page_count=page_count,
        page=query.page,
        offset=query.offset,
        max_chars=query.max_chars,
    )
    if target.get('redirected_from'):
        base['redirected_from'] = target['redirected_from']

    # Reserve JSON framing budget so the serialized response (including rows) never exceeds MAX_BYTES.
    char_budget = min(query.max_chars, (MAX_BYTES - len(encoded(base)) - 4096) // 3)

    if query.query and query.query.strip():
        pattern = _compile_query(query.query.strip())
        scoped_pages = [(query.page, pages[query.page - 1])] if query.page is not None else list(enumerate(pages, start=1))
        matches: list[dict] = []
        total_matches = 0
        used_chars = 0
        has_more = False
        for page_num, page_text in scoped_pages:
            start_pos = query.offset if (query.page is not None or page_num == 1) else 0
            for m in pattern.finditer(page_text, start_pos):
                total_matches += 1
                left = max(0, m.start() - SNIPPET_CONTEXT_CHARS)
                right = min(len(page_text), m.end() + SNIPPET_CONTEXT_CHARS)
                snippet = ('...' if left > 0 else '') + page_text[left:right].strip() + ('...' if right < len(page_text) else '')
                if len(matches) >= query.limit or (used_chars + len(snippet) > char_budget and matches):
                    has_more = True
                    continue
                if len(snippet) > char_budget:
                    snippet = snippet[:char_budget]
                    has_more = True
                entry = dict(
                    page=page_num,
                    offset=m.start(),
                    match=m.group(0),
                    snippet=snippet,
                    text=snippet,
                )
                matches.append(entry)
                used_chars += len(snippet)
        joined = '\n\n...\n\n'.join(m['snippet'] for m in matches)
        result = dict(
            base,
            query=query.query,
            total_chars=sum(len(t) for _, t in scoped_pages),
            match_count=total_matches,
            matches=matches,
            snippets=[m['snippet'] for m in matches],
            text=joined,
            rows=matches,
            has_more=has_more,
            truncated=has_more,
        )
        while len(encoded(result)) > MAX_BYTES and matches:
            matches.pop()
            result['snippets'] = [m['snippet'] for m in matches]
            result['text'] = '\n\n...\n\n'.join(result['snippets'])
            result['has_more'] = result['truncated'] = True
        return result

    source_text = pages[query.page - 1] if query.page is not None else '\n\n'.join(p for p in pages if p)
    total_chars = len(source_text)
    window = source_text[query.offset : query.offset + char_budget]
    has_more = (query.offset + len(window)) < total_chars
    next_offset = (query.offset + len(window)) if has_more else None
    next_page = (query.page + 1) if (query.page is not None and query.page < page_count) else None
    result = dict(
        base,
        total_chars=total_chars,
        text=window,
        rows=[dict(page=query.page or 1, offset=query.offset, text=window)],
        has_more=has_more,
        truncated=has_more,
        next_offset=next_offset,
        next_page=next_page,
    )
    while len(encoded(result)) > MAX_BYTES and len(window) > 256:
        window = window[: len(window) - 1024]
        result['text'] = window
        result['rows'][0]['text'] = window
        result['has_more'] = result['truncated'] = True
        result['next_offset'] = query.offset + len(window)
    return result
