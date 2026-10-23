"""HTTP capture keeps publisher metadata without consuming the document stream."""
from http.client import HTTPResponse as ParsedResponse
from io import BytesIO
from types import SimpleNamespace

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPHeaderDict, HTTPResponse

from congress_api.transport.http import response_metadata


def test_streaming_metadata_retains_unknown_duplicate_and_redirect_headers():
    for path, status, reason in [("/file", 200, "OK"), ("/redirect", 302, "Found")]:
        wire = BytesIO(
            f"HTTP/1.1 {status} {reason}\r\n".encode()
            + b"Location: /file\r\n"
            b"Content-Disposition: attachment; filename*=UTF-8''Witness%20Statement.pdf\r\n"
            b'Link: </metadata.xml>; rel="describedby"\r\n'
            b'Link: </alternate.pdf>; rel="alternate"\r\n'
            b"X-Publisher-Document-Type: Witness Statement\r\n"
            b"Content-Length: 14\r\n\r\noriginal bytes"
        )
        # Exercise the HTTP parser and requests response adapter without sockets.
        parsed = ParsedResponse(SimpleNamespace(makefile=lambda *_: wire))
        parsed.begin()
        raw = HTTPResponse(body=parsed, headers=HTTPHeaderDict(parsed.getheaders()),
                           status=parsed.status, version=parsed.version, reason=parsed.reason,
                           original_response=parsed, preload_content=False)
        request = requests.Request("GET", f"https://example.org{path}").prepare()
        with HTTPAdapter().build_response(request, raw) as response:
            body_position = wire.tell()
            metadata = response_metadata(response)
            assert wire.tell() == body_position
            assert metadata["http_status"] == status
            assert metadata["final_url"] == request.url
            assert metadata["response_reason"] == reason
            assert metadata["http_version"] == 11
            assert metadata["response_headers"]["Location"] == "/file"
            assert metadata["response_headers"]["X-Publisher-Document-Type"] == "Witness Statement"
            assert metadata["response_headers"]["Content-Disposition"].endswith("Witness%20Statement.pdf")
            links = [h["value"] for h in metadata["response_header_items"] if h["name"] == "Link"]
            assert links == ['</metadata.xml>; rel="describedby"', '</alternate.pdf>; rel="alternate"']
            assert metadata["response_header_fidelity"] == "ordered_fields"
            assert response.content == b"original bytes"


def test_synthetic_response_marks_combined_header_limit():
    response = requests.Response()
    response.status_code = 200
    response.headers["X-Unknown"] = "retained"
    metadata = response_metadata(response)
    assert metadata["response_header_items"] == [{"name": "X-Unknown", "value": "retained"}]
    assert metadata["response_header_fidelity"] == "combined_mapping_only"
