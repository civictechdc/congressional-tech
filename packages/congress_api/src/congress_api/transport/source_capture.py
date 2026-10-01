"""Bounded full-response capture; Zyte is the production default."""

import base64
from datetime import datetime, timezone
import json
import threading
from urllib.parse import urljoin

import requests

from congress_api.models.content import RawContent
from congress_api.models.transport import SourceCapture, ZyteResponse
from congress_api.parsers.archive_links import allowed_url
from congress_api.transport import zyte
from congress_api.transport.http import UA, pace_request, response_metadata

_local = threading.local()


def read_bounded(response, limit):
    parts, size = [], 0
    for part in response.iter_content(chunk_size=65536):
        size += len(part)
        if size > limit:
            parts.append(part[: limit - (size - len(part))])
            return b"".join(parts), False
        parts.append(part)
    return b"".join(parts), True


def fetch_source(url, *, transport="zyte", max_bytes=64 * 1024**2, session=None):
    if not allowed_url(url):
        raise ValueError("URL is outside capture scope")
    if transport not in {"zyte", "direct"}:
        raise ValueError("Unknown transport")
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
    try:
        if transport == "zyte":
            # No browser rendering; preserve native body bytes and native headers.
            with zyte.request(url, session=session, stream=True) as response:
                result.update(
                    provider_http_status=response.status_code,
                    provider_metadata=response_metadata(response),
                )
                data, complete = read_bounded(response, (max_bytes * 4 // 3) + 1024**2)
                if not complete:
                    result.update(
                        error="provider_response_limit",
                        provider_content=RawContent.from_bytes(
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
                            provider_content=RawContent.from_bytes(
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
                                url=source.url or url,
                                http_status=source.statusCode,
                                response_headers=headers,
                                response_header_items=[
                                    h.source_dict()
                                    for h in source.httpResponseHeaders or []
                                ],
                                content=RawContent.from_bytes(
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
            target = url
            result["redirects"] = []
            for _ in range(6):
                if not allowed_url(target):
                    result["error"] = "excluded_redirect"
                    break
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
                    body, complete = read_bounded(response, max_bytes)
                    result.update(
                        url=response.url,
                        http_status=response.status_code,
                        response_headers=headers,
                        source_metadata=metadata,
                        response_header_items=metadata["response_header_items"],
                        complete=complete
                        and response.status_code != 206
                        and "content-range" not in headers,
                        content=RawContent.from_bytes(
                            body, headers.get("content-type", "")
                        ),
                    )
                    if not complete:
                        result["error"] = "source_response_limit"
                    break
            else:
                result["error"] = "redirect_limit"
    except (requests.RequestException, ValueError) as error:
        # Error classes carry no credentials or secret query strings.
        result.update(error=type(error).__name__, complete=False)
        if "provider_response" in result:
            result.pop("provider_response")
            result["provider_content"] = RawContent.from_bytes(data, "application/json")
    return SourceCapture.model_validate(result).model_dump(
        mode="json", exclude_none=True
    )
