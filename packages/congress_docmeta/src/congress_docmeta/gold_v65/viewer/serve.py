#!/usr/bin/env python3
"""Local-only HTTP server for DocMeta v6.5 dataset review (stdlib only)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit

from ..paths import resolve_docmeta_v65_dir

STATIC_DIR = Path(__file__).resolve().parent
MAX_POST_BYTES = 65536

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
}


def default_data_dir() -> Path:
    """Resolve `<v65_dir>/viewer` where bundled JSON docs and `review_notes.jsonl` live."""
    return resolve_docmeta_v65_dir() / "viewer"


def _read_reviews(notes_path: Path, lock: threading.Lock) -> list[dict]:
    if not notes_path.exists():
        return []
    out: list[dict] = []
    with lock:
        with notes_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                try:
                    out.append(json.loads(s))
                except json.JSONDecodeError:
                    continue
    return out


def make_handler(
    *,
    static_dir: Path = STATIC_DIR,
    data_dir: Path | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to `static_dir` (HTML/JS/CSS) and `data_dir` (bundle + notes)."""
    eff_static = static_dir.resolve()
    eff_data = (data_dir if data_dir is not None else default_data_dir()).expanduser().resolve()
    notes_path = eff_data / "review_notes.jsonl"
    write_lock = threading.Lock()

    class ViewerHandler(BaseHTTPRequestHandler):
        server_version = "DocMetaViewer/1.0"

        def log_message(self, fmt: str, *args: object) -> None:
            super().log_message(fmt, *args)

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _resolve_target(self, req_path: str) -> Path | None:
            rel = "index.html" if req_path in ("", "/") else req_path.lstrip("/")
            if rel == "review_notes.jsonl" or rel.startswith("data/"):
                base = eff_data
            else:
                base = eff_static
                if not (base / rel).is_file() and (eff_data / rel).is_file():
                    base = eff_data
            target = (base / rel).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                return None
            if base == eff_static and target.suffix.lower() == ".py":
                return None
            return target

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            req_path = unquote(parsed.path)

            if req_path == "/api/reviews":
                self._send_json(HTTPStatus.OK, _read_reviews(notes_path, write_lock))
                return

            target = self._resolve_target(req_path)
            if target is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": req_path})
                return

            ctype = CONTENT_TYPES.get(target.suffix.lower())
            if not ctype:
                guessed, _ = mimetypes.guess_type(str(target))
                ctype = guessed or "application/octet-stream"

            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def do_HEAD(self) -> None:
            parsed = urlsplit(self.path)
            req_path = unquote(parsed.path)
            if req_path == "/api/reviews":
                body = json.dumps(_read_reviews(notes_path, write_lock), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return

            target = self._resolve_target(req_path)
            if target is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return

            ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlsplit(self.path)
            if unquote(parsed.path) != "/api/review":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
                return

            if length <= 0 or length > MAX_POST_BYTES:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body_size"})
                return

            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return

            if not isinstance(data, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "expected_json_object"})
                return

            key = str(data.get("key") or "").strip()
            verdict = str(data.get("verdict") or data.get("status") or "").strip()
            if not key or not verdict:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "key_and_verdict_required"})
                return

            record: dict[str, object] = {
                "key": key,
                "verdict": verdict,
                "field": (str(data.get("field") or "").strip() or None),
                "note": (str(data.get("note") or "").strip() or None),
                "timestamp": str(data.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            }
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            with write_lock:
                with notes_path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()

            self._send_json(HTTPStatus.OK, {"ok": True, "review": record})

    return ViewerHandler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Port on 127.0.0.1 (default: 8765)")
    parser.add_argument("--data-dir", type=Path, default=None, help="Directory holding data/ and review_notes.jsonl")
    args = parser.parse_args(argv)

    data_dir = (args.data_dir if args.data_dir is not None else default_data_dir()).expanduser().resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(data_dir=data_dir))
    print(f"Serving UI={STATIC_DIR} data={data_dir} at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
