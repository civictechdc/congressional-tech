"""HTTP with retries, host pacing and optional Zyte; callers keep parsed results.

docs.house.gov refused 389 requests in 17 seconds and 137 at five/second during
the research run. Direct requests start at least 1.2 seconds apart; a 403 pauses
that host for 60 seconds. Other hosts use a 0.2-second gap. Errors never become
confirmed absences. Request counts include retries and are reported by host.
The pacing lock controls request starts, not requests already in flight.

The authoritative policy matrix is in packages/congress_api/README.md, under
"HTTP policy". meetings.get delegates here with five attempts instead of three.
Senate captions sess and transcribe HTTP calls remain separate clients with
characterized behavior; this module does not
silently replace their retry, pooling or parsing policies. response_metadata
describes received headers; callers decide whether to retain that metadata.
"""

import collections
import math
import threading
import time
from contextlib import nullcontext
from urllib.parse import urlsplit

import requests

from congress_api.transport import zyte

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


COUNTS = collections.Counter()


_locks = collections.defaultdict(threading.Lock)


_next = collections.defaultdict(float)


_local = threading.local()


class RequestPacer:
    """Space top-level HTTP attempts across threads, including retries, without bursts."""

    def __init__(self, requests_per_second):
        if not math.isfinite(requests_per_second) or requests_per_second <= 0:
            raise ValueError('requests_per_second must be positive finite')
        self.gap = 1 / requests_per_second
        self.lock = threading.Lock()
        self.next_start = 0.0

    def __call__(self):
        with self.lock:
            time.sleep(max(0, self.next_start - time.monotonic()))
            self.next_start = time.monotonic() + self.gap


class HttpRequestError(RuntimeError):
    """Failed transport with a status callers can inspect without parsing text."""

    def __init__(self, message, status, *, attempts=0, exception_types=()):
        super().__init__(message)
        self.status = status
        self.details = dict(status=status, attempts=attempts, exception_types=list(exception_types))


def exception_types(error):
    """Keep bounded error classes, never exception messages containing secrets."""
    pending, seen, result = [error], set(), []
    while pending and len(seen) < 8:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        name = type(current).__name__
        if name not in result:
            result.append(name)
        pending.extend(value for value in [current.__cause__, current.__context__,
                       getattr(current, 'reason', None), *current.args] if isinstance(value, BaseException))
    return result


def response_metadata(response: requests.Response) -> dict:
    """Retain all received headers, including repeated fields, without reading the body.

    The mapping is convenient for callers; the ordered list preserves fields such
    as repeated Link headers that requests combines in its mapping. These are
    parsed HTTP headers, not a byte-for-byte copy of the wire protocol.
    """
    if metadata := getattr(response, "capture_metadata", None):
        return metadata
    original = getattr(response.raw, "_original_response", None)
    message = getattr(original, "msg", None)
    raw_headers = getattr(response.raw, "headers", None)
    if message is not None and hasattr(message, "raw_items"):
        items = list(message.raw_items())
        fidelity = "ordered_fields"
    elif raw_headers is not None and hasattr(raw_headers, "iteritems"):
        items = list(raw_headers.iteritems())
        fidelity = "repeated_fields"
    else:
        items = list(response.headers.items())
        fidelity = "combined_mapping_only"
    return {
        "http_status": response.status_code,
        "final_url": response.url,
        "response_headers": dict(response.headers),
        "response_header_items": [{"name": k, "value": v} for k, v in items],
        "response_header_fidelity": fidelity,
        "response_reason": response.reason,
        "http_version": getattr(response.raw, "version", None),
        "response_metadata_version": 2,
    }


def pace_request(url, *, through_zyte=False, request_pacer=None):
    """Share the publisher request-start limit across HTTP implementations."""
    host = urlsplit(url).hostname
    pace_key = f"zyte:{host}" if through_zyte else host
    gap = 0 if through_zyte else 1.2 if host == "docs.house.gov" else 0.2
    with nullcontext() if through_zyte else _locks[host]:
        time.sleep(max(0, _next[pace_key] - time.monotonic()))
        if request_pacer is not None:
            request_pacer()
        _next[pace_key] = time.monotonic() + gap


def get_with_retry(session, url, params=None, attempts=3, *, method="GET", allowed=(200,), through_zyte=False, json_body=None, json_content_type="application/json", request_pacer=None):
    """Return a response or raise, without putting API keys from query strings in errors."""
    if session is None:
        if not hasattr(_local, "session"):
            _local.session = requests.Session()
        session = _local.session
    host = urlsplit(url).hostname
    pace_key = f"zyte:{host}" if through_zyte else host
    status = "request error"
    attempted, failure_types = 0, []
    if json_body is not None and method != "POST":
        raise ValueError("JSON request bodies require POST")
    for attempt in range(attempts):
        attempted = attempt + 1
        pace_request(url, through_zyte=through_zyte, request_pacer=request_pacer)
        try:
            if through_zyte:
                options = {"json_body": json_body, "json_content_type": json_content_type} if json_body is not None else {}
                status, body, header_items = zyte.decode(zyte.request(url, session, **options))
                response = requests.Response()
                response.status_code, response._content, response.url = status, body, url
                response.encoding = "utf-8"
                for item in header_items:
                    response.headers[item.name] = item.value
            else:
                options = {"json": json_body} if json_body is not None else {}
                headers = dict(UA)
                if json_body is not None and json_content_type != "application/json":
                    import json
                    options = {"data": json.dumps(json_body)}
                    headers["Content-Type"] = json_content_type
                response = session.request(method, url, params=params, timeout=60, headers=headers, **options)
                status = response.status_code
            COUNTS[f"{'Zyte' if through_zyte else method} {host} {status}"] += 1
            failure_types = []
            if status in allowed:
                return response
        except requests.RequestException as error:
            status = "request error"
            failure_types = exception_types(error)
            COUNTS[f"{method} {host} request error"] += 1
        ## A refusal is retryable, including a site's 200 challenge when a caller rejects its format.
        delay = 60 if status == 403 and host == "docs.house.gov" and not through_zyte else 2 ** (attempt + 1)
        with nullcontext() if through_zyte else _locks[host]:
            _next[pace_key] = max(_next[pace_key], time.monotonic() + delay)
        if isinstance(status, int) and status not in (202, 403, 408, 429, 500, 502, 503, 504, 520):
            break
    detail = f" ({', '.join(failure_types)}; {attempted} attempts)" if failure_types else ''
    raise HttpRequestError(f"{method} {host}{urlsplit(url).path}: {status}{detail}", status,
                           attempts=attempted, exception_types=failure_types) from None
