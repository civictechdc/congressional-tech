"""
Fetch a URL through Zyte's API, for sites that refuse a plain client: c-span.org answers with a bot
challenge, and docs.house.gov's firewall refuses a client for about 90 seconds after a few hundred
requests in quick succession (measured: 389 in 17 seconds, then 137 at five a second).

    status, body = zyte.get(url)      # the site's own status and bytes; Zyte's failure as (its status, b"")

The token is ZYTE_TOKEN from the environment. Never print it or copy it
anywhere. Zyte charges per request.
"""

import base64
import os

import requests

from congress_api.models.transport import ZyteResponse

API = "https://api.zyte.com/v1/extract"


def token():
    tok = os.environ.get("ZYTE_TOKEN")
    if not tok:
        raise RuntimeError("ZYTE_TOKEN not found")
    return tok


def request(url, session=None, timeout=120, *, stream=False):
    """Return the complete API response so capture callers can retain its evidence.

    Request binary-safe native bytes and publisher headers. Callers must keep
    Zyte's HTTP status separate from the publisher status inside successful JSON.
    Authentication stays on the request and must not be written into receipts.
    """
    return (session or requests).post(API, auth=(token(), ""), timeout=timeout,
        json={"url": url, "httpResponseBody": True, "httpResponseHeaders": True},
        **({"stream": True} if stream else {}))


def decode(response):
    """Publisher status, body, and headers from a Zyte API response.

    A non-200 Zyte status is (that status, b"", []). A 200 JSON body missing
    statusCode fails validation instead of inventing HTTP 200.
    """
    if response.status_code != 200:
        return response.status_code, b"", []
    parsed = ZyteResponse.model_validate(response.json())
    return parsed.statusCode, base64.b64decode(parsed.httpResponseBody), list(parsed.httpResponseHeaders or [])


def get(url, session=None, timeout=120):
    """(the site's status, its body); when Zyte itself fails (429, 503, 520 ...), (Zyte's status, b"")."""
    status, body, _headers = decode(request(url, session, timeout))
    return status, body
