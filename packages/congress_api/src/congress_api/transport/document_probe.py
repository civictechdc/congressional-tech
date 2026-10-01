"""Stream one bounded GET. Redirect bodies and complete PDFs are never drained."""
import httpx

from congress_api.models.content import RawContent
from congress_api.models.documents import DocumentProbeResponse
from congress_api.parsers.document_links import response_kind
from congress_api.transport.http import COUNTS, UA, pace_request
from urllib.parse import urlsplit

DEFAULT_LIMIT = 256 * 1024


def get_prefix(url, *, max_bytes=DEFAULT_LIMIT, client=None):
    if max_bytes < 1024:
        raise ValueError('The response limit must be at least 1024 bytes.')
    if client is None:
        with httpx.Client(timeout=15) as owned:
            return get_prefix(url, max_bytes=max_bytes, client=owned)
    pace_request(url)
    try:
        # Follow redirects explicitly in acquisition: automatic following can
        # consume entire intermediate bodies even with a streaming final GET.
        with client.stream('GET', url, follow_redirects=False, headers={
                **UA, 'Accept-Encoding': 'identity', 'Range': f'bytes=0-{max_bytes - 1}'}) as response:
            COUNTS[f'GET {urlsplit(url).hostname} {response.status_code}'] += 1
            body = bytearray()
            complete = False
            encoding = response.headers.get('content-encoding', 'identity').lower()
            if not 300 <= response.status_code < 400 and encoding == 'identity':
                # iter_raw bounds compressed input too; unexpected compression
                # remains unresolved rather than risking unbounded inflation.
                for chunk in response.iter_raw(chunk_size=1024):
                    body.extend(chunk[:max_bytes - len(body)])
                    if len(body) >= max_bytes or response_kind(body, '') in ('pdf', 'zip', 'legacy_office', 'rtf'):
                        break
                else:
                    complete = response.status_code != 206
            return DocumentProbeResponse(url=str(response.url), status_code=response.status_code,
                headers=dict(response.headers), header_items=list(response.headers.multi_items()),
                content=RawContent.from_bytes(bytes(body), response.headers.get('content-type', '')),
                complete=complete)
    except httpx.HTTPError as error:
        raise RuntimeError(f'Document probe failed: {type(error).__name__}') from error
