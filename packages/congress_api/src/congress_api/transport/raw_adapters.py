"""One-hop transports: owned spool files, bounded chunks and no hidden redirects."""
import base64
import binascii
import hashlib
import json
import mmap
from pathlib import Path
import re

import requests

from congress_api.models.raw_fetch import Transfer
from congress_api.transport.http import UA

CHUNK = 1024**2
SINGLE_PUT_LIMIT = 5 * 1024**3


def _spool(response, destination, limit):
    digest, size, complete = hashlib.sha256(), 0, True
    with Path(destination).open('xb') as target:
        try:
            for chunk in response.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                if size + len(chunk) > limit:
                    chunk = chunk[:limit - size]
                    complete = False
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if not complete:
                    break
        except requests.RequestException as error:
            return digest.hexdigest(), size, False, type(error).__name__
    complete = complete and getattr(response, 'capture_complete', True)
    error = None if complete else getattr(response, 'capture_error', None) or 'size_limit'
    return digest.hexdigest(), size, complete, error


class DirectAdapter:
    """Adapt requests or the existing native one-hop session without page parsing."""
    def __init__(self, session):
        self.session = session

    def hop(self, url, destination, *, limit, headers):
        with self.session.get(url, headers={**UA, **headers}, timeout=(15, 300),
                              stream=True, allow_redirects=False) as response:
            sha, size, complete, error = _spool(response, destination, limit)
            if response.status_code == 206 or 'content-range' in {k.lower() for k in response.headers}:
                complete, error = False, error or 'partial_response'
            return Transfer(Path(destination), response.url, response.status_code,
                            {k.lower(): v for k, v in response.headers.items()},
                            complete, error, sha256=sha, size=size)


def _unique_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ValueError('Duplicate provider metadata key')
        value[key] = child
    return value


def decode_provider(source, destination, *, limit, chunk_bytes=CHUNK, metadata_limit=CHUNK):
    """Decode the provider's one base64 scalar; JSON metadata remains bounded.

    ijson emits complete scalar strings, so it cannot bound this field. The
    provider's schema has exactly one top-level httpResponseBody string. Locate
    that scalar in a read-only mapping, substitute an empty JSON string, then
    let the standard parser validate all metadata and JSON structure. Base64
    chunks are unescaped through that same parser before strict decoding.
    """
    if chunk_bytes <= 0 or limit < 0:
        raise ValueError('Invalid provider decoding limit')
    with Path(source).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
        matches = re.finditer(rb'"httpResponseBody"\s*:\s*"', view)
        match = next(matches,None)
        if match is None or next(matches,None) is not None:
            raise ValueError('Expected one provider response body')
        start = match.end()
        end = view.find(b'"', start)
        if end < 0 or start + len(view) - end > metadata_limit:
            raise ValueError('Incomplete or oversized provider metadata')
        metadata = json.loads(view[:start] + view[end:], object_pairs_hook=_unique_object)
        if (not isinstance(metadata, dict) or metadata.get('httpResponseBody') != ''
                or type(metadata.get('statusCode')) is not int
                or not 100 <= metadata['statusCode'] <= 599):
            raise ValueError('Invalid provider response metadata')
        digest, size, encoded, pending = hashlib.sha256(), 0, b'', b''
        with Path(destination).open('xb') as target:
            for position in range(start, end, chunk_bytes):
                pending += view[position:min(end, position + chunk_bytes)]
                cutoff = len(pending)
                slash = pending.rfind(b'\\')
                if slash >= 0 and len(pending) - slash < (6 if pending[slash:slash+2] == b'\\u' else 2):
                    cutoff = slash
                if not cutoff:
                    continue
                decoded = json.loads(b'"' + pending[:cutoff] + b'"').encode('ascii')
                pending = pending[cutoff:]
                encoded += decoded
                count = len(encoded) // 4 * 4
                # Hold the final quartet: padding must occur only at the end.
                count = max(0, count - 4)
                if count:
                    if b'=' in encoded[:count]:
                        raise ValueError('Padding before end of provider body')
                    raw = base64.b64decode(encoded[:count], validate=True)
                    encoded = encoded[count:]
                    size += len(raw)
                    if size > limit:
                        raise ProviderSizeLimit('Provider body exceeds spool limit')
                    target.write(raw)
                    digest.update(raw)
            if pending:
                raise ValueError('Incomplete provider string escape')
            raw = base64.b64decode(encoded, validate=True)
            size += len(raw)
            if size > limit:
                raise ProviderSizeLimit('Provider body exceeds spool limit')
            target.write(raw)
            digest.update(raw)
    return metadata, digest.hexdigest(), size


class ProviderSizeLimit(ValueError):
    """Provider envelope and decoded entity exceed their shared disk quota."""


class ProviderAdapter:
    """Zyte HTTP mode, with redirects disabled so the fetcher checks every hop.

    followRedirect and pre-decoded body semantics follow
    https://docs.zyte.com/zyte-api/usage/reference . Authentication is supplied
    by the caller's request function and is never stored in transfer metadata.
    """
    def __init__(self, request):
        self.request = request

    def hop(self, url, destination, *, limit, headers):
        destination = Path(destination)
        provider_path = destination.with_suffix('.provider')
        payload = dict(url=url, httpResponseBody=True, httpResponseHeaders=True, followRedirect=False)
        if headers:
            payload['customHttpRequestHeaders'] = [dict(name=k, value=v) for k, v in headers.items()]
        try:
            with self.request(payload) as response:
                status = response.status_code
                _, _, complete, error = _spool(response, provider_path, limit)
                if status != 200 or not complete:
                    provider_path.replace(destination)
                    return Transfer(destination, url, None, {}, False,
                                    error or 'provider_http_error', provider_status=status)
                try:
                    meta, sha, size = decode_provider(provider_path, destination, limit=limit-provider_path.stat().st_size)
                except ProviderSizeLimit:
                    destination.unlink(missing_ok=True)
                    provider_path.replace(destination)
                    return Transfer(destination,url,None,{},False,'size_limit',provider_status=status)
                except (ValueError, UnicodeError, binascii.Error):
                    destination.unlink(missing_ok=True)
                    provider_path.replace(destination)
                    return Transfer(destination, url, None, {}, False,
                                    'invalid_provider_response', provider_status=status)
                raw_headers = meta.get('httpResponseHeaders') or []
                headers = {item['name'].lower(): item['value'] for item in raw_headers}
                # Zyte already removes HTTP content encoding; do not decode again.
                return Transfer(destination, meta.get('url') or url, meta['statusCode'], headers,
                                True, provider_status=status, sha256=sha, size=size)
        finally:
            provider_path.unlink(missing_ok=True)


def download_ranges(session, url, destination, *, size, validator, range_bytes=16*CHUNK, headers=None):
    """One fresh file, covering one strong-validator entity; no resume journal."""
    if (size <= 0 or range_bytes <= 0 or not isinstance(validator, str)
            or not validator.startswith('"') or not validator.endswith('"') or validator.startswith('W/')):
        raise ValueError('Ranges require a strong ETag and positive size')
    destination = Path(destination)
    digest, count = hashlib.sha256(), 0
    with destination.open('xb') as target:
        for start in range(0, size, range_bytes):
            end = min(size, start + range_bytes) - 1
            request_headers = {**(headers or {}), 'Range': f'bytes={start}-{end}',
                               'If-Range': validator, 'Accept-Encoding': 'identity'}
            with session.get(url, headers=request_headers, timeout=(15,300), stream=True,
                             allow_redirects=False) as response:
                actual = {k.lower(): v for k,v in response.headers.items()}
                if (response.status_code != 206 or response.url != url
                        or actual.get('content-range') != f'bytes {start}-{end}/{size}'
                        or actual.get('etag') != validator
                        or actual.get('content-encoding', 'identity') != 'identity'):
                    return Transfer(destination,url,response.status_code,actual,False,'range_entity_changed',
                                    sha256=digest.hexdigest(),size=count)
                received = 0
                for chunk in response.iter_content(chunk_size=CHUNK):
                    received += len(chunk)
                    if received > end-start+1:
                        return Transfer(destination,url,206,actual,False,'range_length_mismatch',
                                        sha256=digest.hexdigest(),size=count)
                    target.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
                if received != end-start+1:
                    return Transfer(destination,url,206,actual,False,'incomplete_range',
                                    sha256=digest.hexdigest(),size=count)
    return Transfer(destination,url,206,actual,True,sha256=digest.hexdigest(),size=count)
