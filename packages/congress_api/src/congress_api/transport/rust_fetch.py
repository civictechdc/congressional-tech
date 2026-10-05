"""Adapt one persistent, rate-limited reqwest worker to the capture reader."""

from concurrent.futures import Future
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading

import requests

from congress_api.parsers.archive_links import inspect_capture
from congress_api.transport.source_capture import fetch_source, read_bounded
from congress_api.transport import zyte


class RustResponse:
    """Response metadata and a bounded body, already read by reqwest."""

    def __init__(self, result, root):
        self.path = Path(result["body_file"])
        if self.path.parent != root:
            raise RuntimeError("Native transport returned a body outside its directory")
        self.status_code = result["http_status"]
        self.url = result["final_url"]
        self.headers = requests.structures.CaseInsensitiveDict(
            (item["name"], item["value"]) for item in result["response_header_items"]
        )
        self.capture_complete = result["complete"]
        self.capture_error = result.get("error")
        self.capture_metadata = {
            key: value for key, value in result.items()
            if key not in {"body_file", "bytes", "complete", "error"}
        }
        self.capture_metadata["response_headers"] = dict(self.headers)
        self.is_redirect = self.status_code in {301, 302, 303, 307, 308} and "location" in self.headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.path.unlink(missing_ok=True)

    def iter_content(self, chunk_size):
        with self.path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                yield chunk


class _NativeSession:
    """The requests-compatible methods used by the shared capture reader."""

    def get(self, url, *, headers, timeout, stream, allow_redirects):
        if allow_redirects or not stream:
            raise RuntimeError("Native capture requires explicit redirects and bounded bodies")
        return self._request(url, "direct", headers=headers)

    def post(self, url, *, json, auth, timeout, stream):
        if url != zyte.API or not stream:
            raise RuntimeError("Unexpected provider request")
        # Credentials stay in the inherited environment, never in request JSON.
        return self._request(json["url"], "zyte")


class _FileSession(_NativeSession):
    """Charge one start slot for a file, including its redirects and fallback."""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.started = False

    def _request(self, url, transport, **kwargs):
        new_file = not self.started
        self.started = True
        return self.fetcher._request(url, transport, new_file=new_file, **kwargs)


class RustFetcher(_NativeSession):
    """Multiplex thread callers over one native HTTP pool and one file-start limiter."""

    def __init__(self, binary, *, files_per_second=60, workers=80, max_bytes=64 * 1024**2):
        self.directory = TemporaryDirectory(prefix="source-fetch-")
        self.root = Path(self.directory.name)
        self.max_bytes = max_bytes
        self.pending = {}
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.sequence = 0
        self.file_dispatches = 0
        self.failure = None
        try:
            self.process = subprocess.Popen(
                [str(binary), str(self.root), str(files_per_second), str(workers)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
            )
        except BaseException:
            self.directory.cleanup()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                result = json.loads(line)
                fatal = result.get("fatal")
                response = None if fatal else result["response"]
                if not fatal and not isinstance(response, dict):
                    raise ValueError("Invalid native response metadata")
                with self.lock:
                    future = self.pending.pop(result["id"])
                if fatal:
                    future.set_exception(RuntimeError(fatal))
                else:
                    future.set_result(response)
        except Exception:
            self._fail("Native transport returned an invalid response")
        finally:
            self._fail("Native transport exited")

    def _fail(self, message):
        with self.lock:
            self.failure = message
            pending, self.pending = self.pending, {}
        for future in pending.values():
            future.set_exception(RuntimeError(message))

    def _request(self, url, transport, *, headers=None, new_file=True):
        future = Future()
        with self.lock:
            if self.failure:
                raise RuntimeError(self.failure)
            self.sequence += 1
            self.file_dispatches += int(new_file)
            request_id = self.sequence
            self.pending[request_id] = future
        request = dict(
            id=request_id, url=url, transport=transport, headers=headers or {}, new_file=new_file,
            max_bytes=self.max_bytes if transport == "direct" else self.max_bytes * 4 // 3 + 1024**2,
        )
        try:
            with self.write_lock:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
        except (OSError, ValueError) as error:
            self._fail("Could not send a request to the native transport")
            raise RuntimeError(self.failure) from error
        try:
            result = future.result(timeout=180)
        except Exception as error:
            # A fatal/malformed/timed-out native command can leave a partial
            # file. Stop its writer before releasing this request's disk quota.
            self.process.kill()
            self.process.wait()
            self._fail('Native transport did not complete its response')
            (self.root / f'{request_id}.body').unlink(missing_ok=True)
            raise RuntimeError('Native transport did not complete its response') from error
        if "http_status" not in result:
            (self.root / f'{request_id}.body').unlink(missing_ok=True)
            raise requests.RequestException(result.get("error", "native_request_error"))
        try:
            return RustResponse(result, self.root)
        except Exception:
            (self.root / f'{request_id}.body').unlink(missing_ok=True)
            raise

    def fetch(self, url, *, transport="auto"):
        return self._fetch(url, transport=transport)[0]

    def fetch_spooled(self, url, *, before_read, transport="auto"):
        """Leave native files on disk until the caller admits their payloads."""
        def read(response, limit):
            before_read()
            return read_bounded(response, limit)

        return self._fetch(url, transport=transport, read=read, raw=True)

    def _fetch(self, url, *, transport, **options):
        if transport not in {"auto", "direct", "zyte"}:
            raise ValueError("Unknown transport")
        session = _FileSession(self)
        first = fetch_source(
            url, transport="direct" if transport == "auto" else transport,
            max_bytes=self.max_bytes, session=session, pace=False, **options,
        )
        inspection = inspect_capture(first)
        if (transport != "auto" or first.get("error") == "excluded_redirect"
                or inspection[0] in {"saved", "excluded_media"}):
            return first, inspection
        fallback = fetch_source(url, transport="zyte", max_bytes=self.max_bytes, session=session, pace=False, **options)
        fallback["prior_attempts"] = [first]
        return fallback, inspect_capture(fallback)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=130)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.reader.join(timeout=5)
            self.process.stdout.close()
        finally:
            self.directory.cleanup()
