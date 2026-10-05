"""Zyte extraction API response, before decoding the upstream response body."""

from .base import SourceModel
from .content import RawContent


class ResponseHeader(SourceModel):
    name: str
    value: str


class ZyteResponse(SourceModel):
    url: str | None = None
    statusCode: int
    httpResponseBody: str
    httpResponseHeaders: list[ResponseHeader] | None = None
    requestId: str | None = None


class SourceCapture(SourceModel):
    """One source response, with provider facts kept separate from the publisher."""

    requested_url: str
    request_url: str | None = None
    url: str
    retrieved_at: str
    transport: str
    complete: bool
    http_status: int | None = None
    response_headers: dict[str, str] = {}
    response_header_items: list[dict[str, str]] = []
    content: RawContent | None = None
    provider_http_status: int | None = None
    provider_response: dict | None = None
    provider_content: RawContent | None = None
    provider_metadata: dict | None = None
    source_metadata: dict | None = None
    error: str | None = None
    redirects: list[dict] = []
