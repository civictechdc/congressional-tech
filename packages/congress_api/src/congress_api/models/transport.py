"""Zyte extraction API response, before decoding the upstream response body."""

from .base import SourceModel


class ResponseHeader(SourceModel):
    name: str
    value: str


class ZyteResponse(SourceModel):
    url: str | None = None
    statusCode: int = 200
    httpResponseBody: str
    httpResponseHeaders: list[ResponseHeader] | None = None
    requestId: str | None = None
