"""One-hop transports: owned spool files, bounded chunks and no hidden redirects."""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

import requests

from congress_api.models.raw_fetch import Transfer
from congress_api.transport.http import UA

CHUNK = 1024**2
SINGLE_PUT_LIMIT = 5 * 1024**3


_REQUEST_ERROR_CODES=frozenset(name for name,value in vars(requests.exceptions).items()
    if isinstance(value,type) and issubclass(value,requests.RequestException))


def network_outcome_unknown(transfer):
    """A partial streamed requests failure has no settled remote outcome.

    Derive codes from the installed requests exception hierarchy, including SSL
    stream failures, rather than maintaining a drifting list of class names.
    Completed HTTP provider errors remain ordinary response evidence.
    """
    return not transfer.complete and transfer.error in (_REQUEST_ERROR_CODES|{'OSError'})


def _spool(response, destination, limit):
    destination = Path(destination)
    native_path = getattr(response, 'path', None)
    if isinstance(native_path, Path) and getattr(response, 'detached', None) is False:
        size = native_path.stat().st_size
        if size <= limit:
            with destination.open('xb'):
                pass
            with native_path.open('rb') as source:
                sha = hashlib.file_digest(source, 'sha256').hexdigest()
            shutil.move(str(native_path), str(destination))
            response.detached = True
            complete = getattr(response, 'capture_complete', True)
            error = None if complete else getattr(response, 'capture_error', None) or 'size_limit'
            return sha, size, complete, error
    digest, size, complete = hashlib.sha256(), 0, True
    with destination.open('xb') as target:
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


def _partial_response(status, headers):
    return status == 206 or any(key.lower() == 'content-range' for key in headers)


class DirectAdapter:
    """Adapt requests or the existing native one-hop session without page parsing."""
    def __init__(self, session):
        self.session = session

    def hop(self, url, destination, *, limit, headers):
        extra = {'max_bytes': limit} if hasattr(self.session, '_request') else {}
        with self.session.get(url, headers={**UA, **headers}, timeout=(15, 300),
                              stream=True, allow_redirects=False, **extra) as response:
            sha, size, complete, error = _spool(response, destination, limit)
            if _partial_response(response.status_code,response.headers):
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


def decode_provider(source, destination, *, limit, chunk_bytes=CHUNK, metadata_limit=CHUNK,
                    body_field="httpResponseBody", validate_metadata=None):
    """Stream one base64 JSON scalar with bounded buffers and strict metadata.

    Keep metadata around an empty scalar, decode aligned base64 chunks, then
    validate the complete JSON structure. No full scalar or mmap enters RSS.
    """
    if chunk_bytes<=0 or limit<0:raise ValueError('Invalid provider decoding limit')
    marker=re.compile(rb'"'+re.escape(body_field.encode())+rb'"\s*:\s*"')
    with Path(source).open('rb') as stream:
        prefix=b''
        while True:
            block=stream.read(min(chunk_bytes,metadata_limit+1-len(prefix)))
            if not block:raise ValueError('Expected one provider response body')
            prefix+=block
            match=marker.search(prefix)
            if match is not None:
                start=match.end();pending=prefix[start:];prefix=prefix[:start];break
            if len(prefix)>metadata_limit:raise ValueError('Oversized provider metadata')
        digest=hashlib.sha256();size=0;encoded=b'';closed=False
        with Path(destination).open('xb') as target:
            while True:
                end=pending.find(b'"')
                if end>=0:
                    piece=pending[:end];suffix=pending[end:];closed=True
                else:
                    cutoff=len(pending)
                    slash=pending.rfind(b'\\')
                    if slash>=0 and len(pending)-slash<(6 if pending[slash:slash+2]==b'\\u' else 2):cutoff=slash
                    piece=pending[:cutoff];pending=pending[cutoff:]
                if piece:
                    encoded+=json.loads(b'"'+piece+b'"').encode('ascii')
                count=len(encoded)//4*4
                if not closed:count=max(0,count-4)
                if count:
                    if not closed and b'=' in encoded[:count]:raise ValueError('Padding before end of provider body')
                    raw=base64.b64decode(encoded[:count],validate=True);encoded=encoded[count:]
                    size+=len(raw)
                    if size>limit:raise ProviderSizeLimit('Provider body exceeds spool limit')
                    target.write(raw);digest.update(raw)
                if closed:
                    if encoded:raise ValueError('Incomplete base64 quartet')
                    suffix+=stream.read(metadata_limit+1)
                    if len(prefix)+len(suffix)>metadata_limit:raise ValueError('Oversized provider metadata')
                    metadata=json.loads(prefix+suffix,object_pairs_hook=_unique_object)
                    break
                block=stream.read(chunk_bytes)
                if not block:raise ValueError('Incomplete provider body')
                pending+=block
    if validate_metadata is not None:metadata=validate_metadata(metadata)
    if (not isinstance(metadata,dict) or metadata.get('httpResponseBody')!=''
            or type(metadata.get('statusCode')) is not int or not 100<=metadata['statusCode']<=599
            or not isinstance(metadata.get('url'),str)
            or not isinstance(metadata.get('httpResponseHeaders',[]),list)
            or any(not isinstance(item,dict) or not isinstance(item.get('name'),str)
                   or not isinstance(item.get('value'),str) for item in metadata.get('httpResponseHeaders',[]))):
        raise ValueError('Invalid provider response metadata')
    from congress_api.retention.body_store import validate_record
    validate_record(metadata['url'])
    parsed=urlsplit(metadata['url'])
    if parsed.scheme not in {'http','https'} or not parsed.hostname:raise ValueError('Invalid provider final URL')
    return metadata,digest.hexdigest(),size


class ProviderSizeLimit(ValueError):
    """Provider envelope and decoded entity exceed their shared disk quota."""


class ProviderAdapter:
    """Zyte HTTP mode, with redirects disabled so the fetcher checks every hop.

    followRedirect and pre-decoded body semantics follow
    https://docs.zyte.com/zyte-api/usage/reference . Authentication is supplied
    by the caller's request function and is never stored in transfer metadata.
    """
    def __init__(self, request, *, max_entity_bytes=16<<20):
        if type(max_entity_bytes) is not int or not 0<max_entity_bytes<=16<<20:raise ValueError('Provider entity capacity is qualified only through 16MiB')
        self.request = request
        self.max_entity_bytes=max_entity_bytes

    def hop(self, url, destination, *, limit, headers):
        destination = Path(destination)
        provider_path = destination.with_suffix('.provider')
        payload = dict(url=url, httpResponseBody=True, httpResponseHeaders=True, followRedirect=False)
        if headers:
            payload['customHttpRequestHeaders'] = [dict(name=k, value=v) for k, v in headers.items()]
        try:
            with self.request(payload) as response:
                status = response.status_code
                _, _, complete, error = _spool(response, provider_path,min(limit,2*((self.max_entity_bytes*4+2)//3)+CHUNK))
                if status != 200 or not complete:
                    provider_path.replace(destination)
                    return Transfer(destination, url, None, {}, False,
                                    error or ('provider_credits' if status==402 else 'provider_quota' if status==429 else 'provider_http_error'), provider_status=status)
                try:
                    meta, sha, size = decode_provider(provider_path, destination, limit=min(self.max_entity_bytes,limit-provider_path.stat().st_size))
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
                partial = _partial_response(meta['statusCode'],headers)
                return Transfer(destination, meta.get('url') or url, meta['statusCode'], headers,
                                not partial, 'partial_response' if partial else None,
                                provider_status=status, sha256=sha, size=size,wire_bytes=provider_path.stat().st_size)
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


class FirecrawlAdapter:
    """Firecrawl rawBase64 mode; no HTML/text substitution for source bytes.

    https://docs.firecrawl.dev/api-reference/endpoint/scrape documents rawBase64,
    metadata.statusCode/sourceURL, and parsers=[] to disable PDF extraction.
    """
    def __init__(self,request,*,max_entity_bytes=16<<20):
        if type(max_entity_bytes) is not int or not 0<max_entity_bytes<=16<<20:raise ValueError('Provider entity capacity is qualified only through 16MiB')
        self.request=request;self.max_entity_bytes=max_entity_bytes

    def hop(self,url,destination,*,limit,headers):
        destination=Path(destination);encoded=destination.with_suffix('.provider')
        payload=dict(url=url,formats=['rawBase64'],parsers=[],onlyMainContent=False)
        if headers:payload['headers']=headers
        def validate(value):
            if not isinstance(value,dict) or value.get('success') is not True:raise ValueError('Invalid Firecrawl success')
            data=value.get('data');meta=data.get('metadata') if isinstance(data,dict) else None
            if not isinstance(meta,dict) or data.get('rawBase64')!='':raise ValueError('Invalid Firecrawl body')
            final=meta.get('url') or meta.get('sourceURL');status=meta.get('statusCode')
            if not isinstance(final,str) or type(status) is not int:raise ValueError('Invalid Firecrawl source metadata')
            return dict(httpResponseBody='',statusCode=status,url=final,httpResponseHeaders=[])
        try:
            with self.request(payload) as response:
                status=response.status_code
                _,_,complete,error=_spool(response,encoded,min(limit,2*((self.max_entity_bytes*4+2)//3)+CHUNK))
                if status!=200 or not complete:
                    encoded.replace(destination)
                    code=error or ('provider_credits' if status==402 else 'provider_quota' if status==429 else 'provider_http_error')
                    return Transfer(destination,url,None,{},False,code,provider_status=status)
                try:
                    meta,sha,size=decode_provider(encoded,destination,limit=min(self.max_entity_bytes,limit-encoded.stat().st_size),
                        body_field='rawBase64',validate_metadata=validate)
                except (ValueError,UnicodeError,binascii.Error):
                    destination.unlink(missing_ok=True);encoded.replace(destination)
                    return Transfer(destination,url,None,{},False,'invalid_provider_response',provider_status=status)
                partial=meta['statusCode']==206
                return Transfer(destination,meta['url'],meta['statusCode'],{},not partial,
                    'partial_response' if partial else None,provider_status=status,sha256=sha,size=size,wire_bytes=encoded.stat().st_size)
        finally:encoded.unlink(missing_ok=True)
