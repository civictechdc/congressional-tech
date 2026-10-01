import base64
import json


from congress_api.cli.raw_sync import parser
from congress_api.models.content import RawContent
from congress_api.transport.source_capture import fetch_source


class Response:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.url = "https://api.zyte.com/v1/extract"
        self.reason = "Result"
        self.raw = None
        self.headers = {"content-type": "application/json"}
        self.data = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i : i + chunk_size]


def test_production_defaults_to_zyte_and_retains_native_metadata(monkeypatch):
    assert parser().parse_args([]).transport == "zyte"
    raw = b"%PDF-1.7\n\xff\n%%EOF"
    payload = {
        "url": "https://example.gov/final.pdf",
        "statusCode": 200,
        "httpResponseBody": base64.b64encode(raw).decode(),
        "httpResponseHeaders": [
            {"name": "Content-Type", "value": "application/pdf"},
            {"name": "Link", "value": "one"},
            {"name": "Link", "value": "two"},
        ],
        "futureField": {"keep": True},
    }
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return Response(payload)

    monkeypatch.setattr("congress_api.transport.source_capture.zyte.request", request)
    result = fetch_source("https://example.gov/start")
    assert calls[0][1]["stream"] is True
    assert result["url"] == payload["url"]
    assert result["provider_response"] == payload
    assert len(result["response_header_items"]) == 3
    assert RawContent.model_validate(result["content"]).body_bytes() == raw
    assert result["complete"]


def test_provider_failures_never_become_publisher_status(monkeypatch):
    monkeypatch.setattr(
        "congress_api.transport.source_capture.zyte.request",
        lambda *a, **kw: Response({"detail": "Refused"}, 429),
    )
    result = fetch_source("https://example.gov/file.pdf")
    assert result["provider_http_status"] == 429
    assert "http_status" not in result
    assert not result["complete"]
    assert result["provider_response"] == {"detail": "Refused"}


def test_oversized_source_and_partial_response_are_not_complete(monkeypatch):
    payload = {
        "statusCode": 200,
        "httpResponseBody": base64.b64encode(b"x" * 1025).decode(),
    }
    monkeypatch.setattr(
        "congress_api.transport.source_capture.zyte.request",
        lambda *a, **kw: Response(payload),
    )
    result = fetch_source("https://example.gov/file.pdf", max_bytes=1024)
    assert result["error"] == "source_response_limit"
    assert len(RawContent.model_validate(result["content"]).body_bytes()) == 1024
    assert not result["complete"]
    payload.update(statusCode=206, httpResponseBody=base64.b64encode(b"part").decode())
    assert not fetch_source("https://example.gov/file.pdf")["complete"]


def test_invalid_zyte_body_is_retained_without_breaking_receipt_serialization(
    monkeypatch,
):
    from congress_api.retention.bundles import separate

    payload = {"statusCode": 200, "httpResponseBody": "not valid base64!"}
    monkeypatch.setattr(
        "congress_api.transport.source_capture.zyte.request",
        lambda *a, **kw: Response(payload),
    )
    result = fetch_source("https://example.gov/a.pdf")
    assert result["error"]
    assert (
        json.loads(RawContent.model_validate(result["provider_content"]).body_bytes())
        == payload
    )
    separate(result, lambda body: "bodies/test")
