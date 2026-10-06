"""Bounded full-response capture for direct and Zyte transports."""

import base64
from datetime import datetime, timezone
import json
import threading
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from congress_api.models.content import CapturedBody, RawContent
from congress_api.models.transport import SourceCapture, ZyteResponse
from congress_api.parsers.archive_links import allowed_url
from congress_api.transport import zyte
from congress_api.transport.http import UA, pace_request, response_metadata

_local = threading.local()


def request_url(url):
    """Use House's verified HTTPS origin without altering the source link."""
    parts = urlsplit(url)
    # The retained live test confirmed same-path HTTP -> HTTPS 301s for this
    # origin. Other hosts and nonstandard ports retain their supplied scheme.
    if parts.scheme == 'http' and parts.netloc.lower() in {'docs.house.gov', 'docs.house.gov:80'}:
        return urlunsplit(('https', parts.netloc.removesuffix(':80'), parts.path, parts.query, parts.fragment))
    return url


def read_bounded(response, limit):
    parts, size = [], 0
    for part in response.iter_content(chunk_size=65536):
        size += len(part)
        if size > limit:
            parts.append(part[: limit - (size - len(part))])
            return b"".join(parts), False
        parts.append(part)
    return b"".join(parts), getattr(response, "capture_complete", True)


def fetch_source(url, *, transport="zyte", max_bytes=64 * 1024**2, session=None, pace=True,
                 read=read_bounded, raw=False):
    if not allowed_url(url):
        raise ValueError("URL is outside capture scope")
    if transport not in {"zyte", "direct"}:
        raise ValueError("Unknown transport")
    content = CapturedBody if raw else RawContent
    if session is None:
        if not hasattr(_local, "session"):
            _local.session = requests.Session()
        session = _local.session
    result = dict(
        requested_url=url,
        url=url,
        transport=transport,
        complete=False,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
    initial_url = request_url(url)
    if initial_url != url:
        result['request_url'] = initial_url
    try:
        if transport == "zyte":
            # No browser rendering; preserve native body bytes and native headers.
            with zyte.request(initial_url, session=session, stream=True) as response:
                result.update(
                    provider_http_status=response.status_code,
                    provider_metadata=response_metadata(response),
                )
                data, complete = read(response, (max_bytes * 4 // 3) + 1024**2)
                if not complete:
                    result.update(
                        error=getattr(response, "capture_error", None) or (
                            "provider_response_limit" if len(data) >= (max_bytes * 4 // 3) + 1024**2
                            else "incomplete_response"),
                        provider_content=content.from_bytes(
                            data, "application/json"
                        ),
                    )
                else:
                    try:
                        payload = json.loads(data)
                    except (ValueError, UnicodeError):
                        payload = None
                    if not isinstance(payload, dict):
                        result.update(
                            error="invalid_provider_response",
                            provider_content=content.from_bytes(
                                data, "application/json"
                            ),
                        )
                    else:
                        result["provider_response"] = payload
                        if response.status_code == 200:
                            source = ZyteResponse.model_validate(payload)
                            body = base64.b64decode(
                                source.httpResponseBody, validate=True
                            )
                            headers = {
                                h.name.lower(): h.value
                                for h in source.httpResponseHeaders or []
                            }
                            result.update(
                                url=source.url or initial_url,
                                http_status=source.statusCode,
                                response_headers=headers,
                                response_header_items=[
                                    h.source_dict()
                                    for h in source.httpResponseHeaders or []
                                ],
                                content=content.from_bytes(
                                    body[:max_bytes], headers.get("content-type", "")
                                ),
                                complete=len(body) <= max_bytes
                                and source.statusCode != 206
                                and "content-range" not in headers,
                            )
                            if len(body) > max_bytes:
                                result["error"] = "source_response_limit"
                        else:
                            result["error"] = "provider_http_error"
        else:
            target = initial_url
            result["redirects"] = []
            for _ in range(6):
                if not allowed_url(target):
                    result["error"] = "excluded_redirect"
                    break
                if pace:
                    pace_request(target)
                with session.get(
                    target,
                    headers=UA,
                    timeout=(15, 90),
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    metadata = response_metadata(response)
                    if response.is_redirect:
                        result["redirects"].append(metadata)
                        target = urljoin(target, response.headers["Location"])
                        continue
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    body, complete = read(response, max_bytes)
                    result.update(
                        url=response.url,
                        http_status=response.status_code,
                        response_headers=headers,
                        source_metadata=metadata,
                        response_header_items=metadata["response_header_items"],
                        complete=complete
                        and response.status_code != 206
                        and "content-range" not in headers,
                        content=content.from_bytes(
                            body, headers.get("content-type", "")
                        ),
                    )
                    if not complete:
                        result["error"] = getattr(response, "capture_error", None) or (
                            "source_response_limit" if len(body) >= max_bytes else "incomplete_response")
                    break
            else:
                result["error"] = "redirect_limit"
    except (requests.RequestException, ValueError) as error:
        # Error classes carry no credentials or secret query strings.
        result.update(error=getattr(error, "capture_error", None) or type(error).__name__, complete=False)
        if "provider_response" in result:
            result.pop("provider_response")
            result["provider_content"] = content.from_bytes(data, "application/json")
    # Runtime bodies are created here from the bounded reader, never accepted
    # from serialized input. Validate transport metadata with the same model;
    # keep acquired bytes intact until the receipt writer separates them.
    bodies = {key: result.pop(key) for key in ('content', 'provider_content')
              if raw and key in result}
    capture = SourceCapture.model_validate(result).model_dump(
        mode="json", exclude_none=True
    )
    capture.update({key: body.source_dict() for key, body in bodies.items()})
    return capture
