"""Read raw bodies from the raw bucket's public custom domain through R2Store's pinned reads.

Its own module, not r2.py, so the readings producers' import closure (and the drift evidence over
it) does not take in a client only the body-text producer uses.
"""


class PublicOrigin:
    """The GetObject subset R2Store's pinned reads use, served by the raw bucket's public custom domain.

    So R2Store.read and the readings range cache verify a public-origin read exactly as an SDK one:
    the If-Match condition, the 206 and its Content-Range, the length and the MD5 ETag. Accept-Encoding
    is gzip because the edge then returns a body stored with Content-Encoding gzip as stored (the
    strong MD5 ETag and stored length); asked for identity it decompresses on the fly under a weak
    ETag. Redirects are refused. It can only read: there is no put, list or head. HTTP errors are SDK
    ClientErrors and a cut body an IncompleteReadError, so R2Store's own handling applies; one request
    per call, and R2Store re-reads a cut body up to ``attempts`` times.
    """

    def __init__(self, origin, *, user_agent, timeout=60, attempts=3):
        from types import SimpleNamespace
        from urllib.request import HTTPRedirectHandler, build_opener

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None  # the 3xx itself is the answer: an HTTPError

        self.origin, self.user_agent, self.timeout = origin.rstrip('/'), user_agent, timeout
        self._open = build_opener(NoRedirect()).open
        # The SDK surface R2Store configures: a body re-read budget and a retry hook it may register.
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': attempts}),
                                    events=SimpleNamespace(register_first=lambda *args, **kwargs: None))

    def get_object(self, *, Bucket, Key, IfMatch=None, Range=None):
        from botocore.exceptions import ClientError
        from urllib.error import HTTPError
        from urllib.request import Request
        from congress_api.retention.body_store import validate_key
        validate_key(Key)
        headers = {'User-Agent': self.user_agent, 'Accept-Encoding': 'gzip',
                   **({'If-Match': IfMatch} if IfMatch else {}), **({'Range': Range} if Range else {})}
        try:
            response = self._open(Request(f'{self.origin}/{Key}', headers=headers), timeout=self.timeout)
        except HTTPError as error:
            error.close()
            raise ClientError({'Error': {'Code': str(error.code), 'Message': str(error.reason)},
                               'ResponseMetadata': {'HTTPStatusCode': error.code}}, 'GetObject') from None
        length = response.headers.get('Content-Length')
        return dict(Body=_OriginBody(response), ETag=response.headers.get('ETag'),
                    ContentLength=int(length) if length is not None and length.isdigit() else None,
                    ContentRange=response.headers.get('Content-Range', ''),
                    ContentEncoding=response.headers.get('Content-Encoding'),
                    ResponseMetadata={'HTTPStatusCode': response.status})


class _OriginBody:
    """A response body whose cut read surfaces as the SDK's IncompleteReadError."""

    def __init__(self, response):
        self.response = response

    def read(self, size=-1):
        from http.client import IncompleteRead
        from botocore.exceptions import IncompleteReadError
        try:
            return self.response.read(size)
        except IncompleteRead as error:
            raise IncompleteReadError(actual_bytes=len(error.partial),
                                      expected_bytes=len(error.partial) + (error.expected or 0)) from None

    def close(self):
        self.response.close()
