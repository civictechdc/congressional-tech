"""HTTP capture keeps publisher metadata without consuming the document stream."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import requests

from congress_api.http import response_metadata


def test_streaming_metadata_retains_unknown_duplicate_and_redirect_headers():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if self.path == "/redirect" else 200)
            self.send_header("Location", "/file")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''Witness%20Statement.pdf")
            self.send_header("Link", '</metadata.xml>; rel="describedby"')
            self.send_header("Link", '</alternate.pdf>; rel="alternate"')
            self.send_header("X-Publisher-Document-Type", "Witness Statement")
            self.end_headers()
            self.wfile.write(b"original bytes")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, status in [("/file", 200), ("/redirect", 302)]:
            with requests.get(f"http://127.0.0.1:{server.server_port}{path}",
                              stream=True, allow_redirects=False, timeout=5) as response:
                metadata = response_metadata(response)
                assert metadata["http_status"] == status
                assert metadata["response_headers"]["X-Publisher-Document-Type"] == "Witness Statement"
                assert metadata["response_headers"]["Content-Disposition"].endswith("Witness%20Statement.pdf")
                links = [h["value"] for h in metadata["response_header_items"] if h["name"] == "Link"]
                assert links == ['</metadata.xml>; rel="describedby"', '</alternate.pdf>; rel="alternate"']
                assert metadata["response_header_fidelity"] == "ordered_fields"
                assert response.content == b"original bytes"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_synthetic_response_marks_combined_header_limit():
    response = requests.Response()
    response.status_code = 200
    response.headers["X-Unknown"] = "retained"
    metadata = response_metadata(response)
    assert metadata["response_header_items"] == [{"name": "X-Unknown", "value": "retained"}]
    assert metadata["response_header_fidelity"] == "combined_mapping_only"
