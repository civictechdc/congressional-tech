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
from contextlib import nullcontext
import threading
import time
from urllib.parse import urlsplit

import requests

from congress_api import zyte

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
COUNTS = collections.Counter()
_locks = collections.defaultdict(threading.Lock)
_next = collections.defaultdict(float)
_local = threading.local()


class HttpRequestError(RuntimeError):
    """Failed transport with a status callers can inspect without parsing text."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def response_metadata(response: requests.Response) -> dict:
    """Retain all received headers, including repeated fields, without reading the body.

    The mapping is convenient for callers; the ordered list preserves fields such
    as repeated Link headers that requests combines in its mapping. These are
    parsed HTTP headers, not a byte-for-byte copy of the wire protocol.
    """
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


def get_with_retry(session, url, params=None, attempts=3, *, method="GET", allowed=(200,), through_zyte=False):
    """Return a response or raise, without putting API keys from query strings in errors."""
    if session is None:
        if not hasattr(_local, "session"):
            _local.session = requests.Session()
        session = _local.session
    host = urlsplit(url).hostname
    pace_key = f"zyte:{host}" if through_zyte else host
    gap = 0 if through_zyte else 1.2 if host == "docs.house.gov" else 0.2
    status = "request error"
    for attempt in range(attempts):
        with nullcontext() if through_zyte else _locks[host]:
            time.sleep(max(0, _next[pace_key] - time.monotonic()))
            _next[pace_key] = time.monotonic() + gap
        try:
            if through_zyte:
                status, body = zyte.get(url, session)
                response = requests.Response()
                response.status_code, response._content, response.url = status, body, url
                response.encoding = "utf-8"
            else:
                response = session.request(method, url, params=params, timeout=60, headers=UA)
                status = response.status_code
            COUNTS[f"{'Zyte' if through_zyte else method} {host} {status}"] += 1
            if status in allowed:
                return response
        except requests.RequestException:
            status = "request error"
            COUNTS[f"{method} {host} request error"] += 1
        ## A refusal is retryable, including a site's 200 challenge when a caller rejects its format.
        delay = 60 if status == 403 and host == "docs.house.gov" and not through_zyte else 2 ** (attempt + 1)
        with nullcontext() if through_zyte else _locks[host]:
            _next[pace_key] = max(_next[pace_key], time.monotonic() + delay)
        if isinstance(status, int) and status not in (202, 403, 408, 429, 500, 502, 503, 504, 520):
            break
    raise HttpRequestError(f"{method} {host}{urlsplit(url).path}: {status}", status)
