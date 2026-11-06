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
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

import regex

from . import __version__
from .models import DocumentQuery, ExplorerError, MAX_BYTES
from .release import atomic_json, encoded
from .citations import add_body_citations, text_citation

MAX_BODY_BYTES = 64 << 20
MAX_RAW_BYTES = MAX_BODY_BYTES
MAX_CACHE_ENTRIES = 256
MAX_CACHE_BYTES = 128 << 20
MAX_PAGE_MATCH_ITERATIONS = 10_000
BODY_CACHE_VERSION = 2
SNIPPET_CONTEXT_CHARS = 160

TEXT_FORMATS = frozenset({'pdf', 'html', 'htm', 'xhtml', 'xml', 'text', 'txt', 'json', 'csv', 'md', 'vtt', 'srt', 'ttml', 'dfxp', 'm3u8'})
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
        if kind == 'dfxp':
            return 'ttml'
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
        return 'html' if ext in ('htm', 'xhtml') else ('text' if ext == 'txt' else ('ttml' if ext == 'dfxp' else ext))
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


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExplorerError('Archive body fetch redirected outside archive_origin')


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError('Document text read timed out')


def _fetch_raw_bytes(
    saved_url: str,
    origin_netloc: str,
    origin_scheme: str,
    *,
    timeout: float,
    max_bytes: int,
    deadline: float | None = None,
) -> bytes:
    _check_deadline(deadline)
    request = Request(saved_url, headers={'User-Agent': f'CongressExplorerMCP/{__version__}'})
    opener = build_opener(_NoRedirectHandler())
    sock_timeout = max(0.05, min(timeout, deadline - time.monotonic())) if deadline is not None else timeout
    try:
        with opener.open(request, timeout=sock_timeout) as stream:
            final = urlsplit(stream.url)
            if final.scheme != origin_scheme or final.netloc != origin_netloc:
                raise ExplorerError('Archive body fetch redirected outside archive_origin')
            chunks: list[bytes] = []
            total = 0
            while chunk := stream.read(65536):
                _check_deadline(deadline)
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


def _extract_pdf_pages(payload: bytes, *, deadline: float | None = None) -> list[str]:
    _check_deadline(deadline)
    header_pos = payload.find(b'%PDF-', 0, 1024)
    if header_pos < 0:
        raise ExplorerError('Invalid or corrupt PDF body')
    pdf_data = payload[header_pos:]
    # 1. Primary: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_data), strict=False)
        if len(reader.pages) > 0:
            pages = []
            for page in reader.pages:
                _check_deadline(deadline)
                pages.append((page.extract_text() or '').strip())
            if any(pages):
                return pages
    except TimeoutError:
        raise
    except Exception:
        pass
    # 2. Secondary: poppler pdftotext
    pdftotext = shutil.which('pdftotext')
    if pdftotext:
        _check_deadline(deadline)
        pdf_timeout = max(1.0, deadline - time.monotonic()) if deadline is not None else 15.0
        try:
            proc = subprocess.run(
                [pdftotext, '-q', '-', '-'],
                input=pdf_data,
                capture_output=True,
                timeout=pdf_timeout,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                raw_pages = proc.stdout.decode('utf-8', errors='replace').split('\f')
                if raw_pages and raw_pages[-1] == '':
                    raw_pages.pop()
                pages = [p.strip() for p in raw_pages]
                if any(pages):
                    return pages
        except subprocess.TimeoutExpired as error:
            raise TimeoutError('Document text read timed out') from error
        except TimeoutError:
            raise
        except Exception:
            pass
    raise ExplorerError('Unable to extract text from PDF body')


def _extract_xml_text(payload: bytes) -> str:
    parser = _MarkupTextExtractor()
    parser.feed(payload.decode('utf-8', errors='replace'))
    parser.close()
    return parser.get_text()


def extract_pages(payload: bytes, fmt: str, *, deadline: float | None = None) -> list[str]:
    _check_deadline(deadline)
    if fmt == 'pdf' or payload.startswith(b'%PDF-'):
        return _extract_pdf_pages(payload, deadline=deadline)
    if b'\x00' in payload[:8192]:
        raise ExplorerError('Unsupported binary document body')
    if fmt in ('html', 'xml'):
        return [_extract_xml_text(payload)]
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = payload.decode('latin-1')
    return [text.strip()]


def _read_cached_pages(cache_path: Path, body_hex: str, *, max_bytes: int = MAX_BODY_BYTES) -> list[str] | None:
    if cache_path.is_symlink():
        raise ExplorerError('Cached document body entry is a symlink')
    if not cache_path.exists():
        return None
    try:
        stat = cache_path.stat()
    except OSError as error:
        raise ExplorerError('Corrupt cached document body') from error
    if stat.st_size > max_bytes:
        raise ExplorerError('Corrupt cached document body')
    try:
        cached = json.loads(cache_path.read_bytes())
    except Exception as error:
        raise ExplorerError('Corrupt cached document body') from error
    if (
        not isinstance(cached, dict)
        or cached.get('version') != BODY_CACHE_VERSION
        or cached.get('saved_body') != body_hex
        or not isinstance(cached.get('pages'), list)
        or len(cached['pages']) == 0
        or not all(isinstance(p, str) for p in cached['pages'])
    ):
        raise ExplorerError('Corrupt cached document body')
    return cached['pages']


def _write_cached_pages(
    cache_path: Path,
    body_hex: str,
    fmt: str,
    pages: list[str],
    *,
    max_entries: int = MAX_CACHE_ENTRIES,
    max_cache_bytes: int = MAX_CACHE_BYTES,
) -> None:
    cache_dir = cache_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    value = dict(
            version=BODY_CACHE_VERSION,
            saved_body=body_hex,
            format=fmt,
            page_count=len(pages),
            pages=pages,
        )
    # A count limit alone permits 256 x 64 MiB of disposable text. Keep one
    # byte quota as well, and avoid caching entries the reader cannot reopen.
    if len(encoded(value)) > min(MAX_BODY_BYTES, max_cache_bytes):
        return
    atomic_json(cache_path, value)
    try:
        entries = []
        for p in cache_dir.glob('*.json'):
            if not p.is_symlink():
                try:
                    info = p.stat()
                    entries.append((info.st_mtime_ns, p, info.st_size))
                except OSError:
                    pass
        total = sum(size for _, _, size in entries)
        entries.sort(key=lambda item: (item[0], str(item[1])))
        remaining = len(entries)
        for _, old_path, size in entries:
            if remaining > max_entries or total > max_cache_bytes:
                try:
                    old_path.unlink(missing_ok=True)
                    total -= size
                    remaining -= 1
                except OSError:
                    pass
    except OSError:
        pass


def _load_or_extract_pages(
    target: dict,
    *,
    data_dir: Path | None,
    timeout: float,
    max_bytes: int,
    deadline: float | None = None,
) -> tuple[list[str], str, str, str]:
    _check_deadline(deadline)
    fmt = _normalize_format(target.get('format'), target.get('saved_media_type'), target.get('filename'))
    saved_url, body_hex, suffix = _validate_archive_url(
        target.get('saved_url'),
        target.get('archive_origin'),
        target.get('saved_body'),
        target.get('saved_suffix'),
    )
    # Keep legacy entries out of the new reader and leave their paths usable by older installs.
    cache_path = (
        Path(data_dir) / 'bodies' / f'{body_hex}.v{BODY_CACHE_VERSION}.json'
        if data_dir is not None else None
    )
    if cache_path is not None:
        cached_pages = _read_cached_pages(cache_path, body_hex, max_bytes=max_bytes)
        if cached_pages is not None:
            return cached_pages, fmt, body_hex, saved_url

    origin_parts = urlsplit(target['archive_origin'])
    raw_bytes = _fetch_raw_bytes(
        saved_url,
        origin_parts.netloc,
        origin_parts.scheme,
        timeout=timeout,
        max_bytes=max_bytes,
        deadline=deadline,
    )
    _check_deadline(deadline)
    decoded = verify_and_decode_body(raw_bytes, body_hex, suffix, max_bytes=max_bytes)
    pages = extract_pages(decoded, fmt, deadline=deadline)
    if cache_path is not None and pages:
        _write_cached_pages(cache_path, body_hex, fmt, pages)
    return pages, fmt, body_hex, saved_url


def _search(pattern: regex.Pattern, text: str, offset: int, deadline: float) -> regex.Match | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Document text read timed out')
    return pattern.search(text, offset, timeout=remaining)


def _compile_query(query: str, deadline: float) -> regex.Pattern:
    flags = regex.IGNORECASE | regex.VERSION0
    try:
        # Fall back to a literal when the expression is invalid in Python.
        re.compile(query, re.IGNORECASE)
        pattern = regex.compile(query, flags)
    except (re.error, regex.error, OverflowError, RecursionError):
        return regex.compile(re.escape(query), flags)
    if _search(pattern, '', 0, deadline) is not None:
        return regex.compile(re.escape(query), flags)
    return pattern

def read_document_body(
    target: dict,
    query: DocumentQuery | dict,
    *,
    data_dir: Path | None = None,
    timeout: float = 10.0,
) -> dict:
    deadline = time.monotonic() + timeout
    query = query if isinstance(query, DocumentQuery) else DocumentQuery.model_validate(query)
    if query.cursor:
        raise ExplorerError('Text section uses page or offset, not cursor')
    resolved_dir = data_dir or (Path(target['data_dir']) if target.get('data_dir') else None)
    pages, fmt, body_hex, saved_url = _load_or_extract_pages(
        target,
        data_dir=resolved_dir,
        timeout=timeout,
        max_bytes=MAX_BODY_BYTES,
        deadline=deadline,
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
    source_text = pages[query.page - 1] if query.page is not None else '\n\n'.join(p for p in pages if p)

    if query.query and query.query.strip():
        snippet_budget = min(query.max_chars, max(256, (MAX_BYTES - len(encoded(base)) - 4096) // 6))
        pattern = _compile_query(query.query.strip(), deadline)
        scoped_pages = [(query.page, pages[query.page - 1])] if query.page is not None else list(enumerate(pages, start=1))
        matches: list[dict] = []
        total_matches = 0
        used_chars = 0
        has_more = False
        for page_num, page_text in scoped_pages:
            _check_deadline(deadline)
            pos = query.offset if (query.page is not None or page_num == 1) else 0
            iterations = 0
            while pos <= len(page_text) and iterations < MAX_PAGE_MATCH_ITERATIONS:
                m = _search(pattern, page_text, pos, deadline)
                if m is None:
                    break
                iterations += 1
                total_matches += 1
                pos = m.end() if m.end() > m.start() else m.end() + 1
                if len(matches) >= query.limit:
                    has_more = True
                    continue
                left = max(0, m.start() - SNIPPET_CONTEXT_CHARS)
                right = min(len(page_text), m.end() + SNIPPET_CONTEXT_CHARS)
                snippet = ('...' if left > 0 else '') + page_text[left:right].strip() + ('...' if right < len(page_text) else '')
                if used_chars + len(snippet) > snippet_budget and matches:
                    has_more = True
                    continue
                if len(snippet) > snippet_budget:
                    snippet = snippet[:snippet_budget]
                    has_more = True
                matched_text = m.group(0)
                if len(matched_text) > 240:
                    matched_text = matched_text[:240]
                entry = dict(
                    page=page_num,
                    offset=m.start(),
                    match=matched_text,
                    snippet=snippet,
                    text=snippet,
                )
                entry['citation'] = text_citation(target,dict(kind='body_text',page=page_num,offset=m.start(),length=len(matched_text)),matched_text)
                matches.append(entry)
                used_chars += len(snippet)
            if iterations >= MAX_PAGE_MATCH_ITERATIONS:
                has_more = True
        joined = '\n\n...\n\n'.join(m['snippet'] for m in matches)
        result = dict(
            base,
            query=query.query,
            total_chars=len(source_text),
            match_count=total_matches,
            matches=matches,
            snippets=[m['snippet'] for m in matches],
            text=joined,
            rows=matches,
            has_more=has_more,
            truncated=has_more,
        )
        while len(encoded(result)) > MAX_BYTES and len(matches) > 1:
            matches.pop()
            result['snippets'] = [m['snippet'] for m in matches]
            result['text'] = '\n\n...\n\n'.join(result['snippets'])
            result['has_more'] = result['truncated'] = True
        while len(encoded(result)) > MAX_BYTES and len(matches) == 1 and len(matches[0]['snippet']) > 128:
            shrunk = matches[0]['snippet'][: max(128, len(matches[0]['snippet']) - 512)]
            matches[0]['snippet'] = matches[0]['text'] = shrunk
            result['snippets'] = [shrunk]
            result['text'] = shrunk
            result['has_more'] = result['truncated'] = True
        return result

    char_budget = min(query.max_chars, max(256, (MAX_BYTES - len(encoded(base)) - 2048) // 2))
    total_chars = len(source_text)
    window = source_text[query.offset : query.offset + char_budget]
    has_more = (query.offset + len(window)) < total_chars
    next_offset = (query.offset + len(window)) if has_more else None
    next_page = (query.page + 1) if (query.page is not None and query.page < page_count) else None
    result = dict(
        base,
        total_chars=total_chars,
        text=window,
        rows=[dict(page=base['page'], offset=query.offset, text=window)],
        has_more=has_more,
        truncated=has_more,
        next_offset=next_offset,
        next_page=next_page,
    )
    add_body_citations(result,target)
    while len(encoded(result)) > MAX_BYTES and len(window) > 256:
        window = window[: len(window) - 1024]
        result['text'] = window
        result['rows'][0]['text'] = window
        result['has_more'] = result['truncated'] = True
        result['next_offset'] = query.offset + len(window)
        add_body_citations(result,target)
    return result


read_document_text = read_document_body
