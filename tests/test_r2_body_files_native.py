"""Real SDK file upload serialization against a local HTTP server."""

import base64
import hashlib
from congress_api.retention.r2 import R2Store


def test_sdk_file_upload_sends_complete_bytes_and_conditional_md5(tmp_path):
    """Exercise SDK serialization rather than only the injected client."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import boto3
    from botocore.config import Config

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((dict(self.headers), data))
            self.send_response(200)
            self.send_header("ETag", '"' + hashlib.md5(data).hexdigest() + '"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"http://127.0.0.1:{server.server_port}",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="auto",
            config=Config(
                retries={"total_max_attempts": 1},
                request_checksum_calculation="when_required",
            ),
        )
        data = b"actual-sdk-body" * 10000
        path = tmp_path / "body"
        path.write_bytes(data)
        assert R2Store(client, "test").put_file("bodies/object.gz", path)
        headers, actual = received[0]
        assert actual == data
        assert headers["If-None-Match"] == "*"
        assert (
            headers["Content-MD5"]
            == base64.b64encode(hashlib.md5(data).digest()).decode()
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
