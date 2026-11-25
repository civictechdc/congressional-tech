"""Local interactive corpus viewer for DocMeta V7.3a.1 (`docmeta_v7_3.parquet`).

Serves a zero-CDN interactive web inspector on localhost backed by DuckDB and a
lightweight byte-offset index into the paired 9K source-text candidate JSONL files,
plus published-release joins (`detail.parquet`, `sources.parquet`) and a `/api/raw/`
caching proxy for inline PDF/HTML/XML inspection and download.

Usage:
    .venv/bin/python scripts/view_docmeta_v7_3.py
    .venv/bin/python scripts/view_docmeta_v7_3.py --port 8733 --no-open
"""

from __future__ import annotations

import argparse
import gzip
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
import unicodedata
import urllib.error
from urllib.parse import parse_qs, unquote, urlparse
import urllib.request
import webbrowser

import duckdb

try:
    from viewer_publication.body_text_slices import strip_invisible_format_chars
except ImportError:  # pragma: no cover - fallback when run outside package env
    _INVISIBLE_FORMAT_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f\ufeff\u00ad]")

    def strip_invisible_format_chars(text: str) -> str:
        """Strip bidi/zero-width invisible format characters matching `body_text_slices`."""
        return _INVISIBLE_FORMAT_RE.sub("", text) if text else text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARQUET = ROOT / ".cache/archive-release/docmeta-v7-corpus/sealed/docmeta_v7_3.parquet"
DEFAULT_RELEASE_ROOT = ROOT / ".cache/archive-release/published-releases"
DEFAULT_BLOB_CACHE = ROOT / ".cache/docmeta-viewer-blobs"
DEFAULT_RAW_BASE = "https://congressional-data.spicygov.ai"
DEFAULT_HTML = Path(__file__).resolve().with_name("docmeta_v7_3_viewer.html")
NULL_SENTINEL = "__NULL__"

FACET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("split", "varchar"),
    ("status", "varchar"),
    ("primary_genre", "varchar"),
    ("specialist_family", "varchar"),
    ("verdict", "varchar"),
    ("chamber", "varchar"),
    ("media_format", "varchar"),
    ("specialist_teacher", "varchar"),
    ("is_packet", "bool"),
)

SORT_CLAUSES: dict[str, str] = {
    "default": "g.split ASC, g.primary_genre ASC NULLS LAST, g.doc_key ASC",
    "date_desc": "g.doc_date DESC NULLS LAST, g.congress DESC NULLS LAST, g.doc_key ASC",
    "date_asc": "g.doc_date ASC NULLS LAST, g.congress ASC NULLS LAST, g.doc_key ASC",
    "title_asc": "lower(coalesce(g.verbatim_title, c.filename, g.doc_key)) ASC, g.doc_key ASC",
    "congress_desc": "g.congress DESC NULLS LAST, g.doc_date DESC NULLS LAST, g.doc_key ASC",
    "random": "random()",
}

FORMAT_MEDIA_MAP: dict[str, str] = {
    "pdf": "application/pdf",
    "html": "text/html",
    "xml": "application/xml",
    "text": "text/plain",
    "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "zip": "application/zip",
}

MEDIA_EXT_MAP: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/zip": ".zip",
}


def _json_safe(value: Any) -> Any:
    """Recursively convert DuckDB / NumPy / Arrow values into plain JSON types."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "tolist"):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _safe_json_loads(raw: Any) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw if isinstance(raw, (dict, list)) else None
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _exact_slice(text: str | None, start: int, end: int, quote: str) -> bool:
    if not text or not quote or start < 0 or end <= start or end > len(text):
        return False
    return text[start:end] == quote


def _extract_nested_spans(node: Any, path: str, out: list[tuple[str, dict[str, Any]]]) -> None:
    """Walk nested JSON structures and collect every `{quote, start, end}` span object."""
    if isinstance(node, dict):
        quote = node.get("quote")
        start = node.get("start")
        end = node.get("end")
        if (
            isinstance(quote, str)
            and isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
        ):
            out.append((path, node))
        for key, val in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            _extract_nested_spans(val, child_path, out)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _extract_nested_spans(item, f"{path}[{idx}]", out)


def collect_spans(
    row: dict[str, Any],
    raw_text: str | None,
    clean_text: str | None,
) -> list[dict[str, Any]]:
    """Collect and verify title, date, and specialist spans against raw and bidi-clean text."""
    collected: list[tuple[str, str, dict[str, Any]]] = []

    title_span = _safe_json_loads(row.get("title_span_json"))
    if isinstance(title_span, dict) and isinstance(title_span.get("quote"), str):
        collected.append(("title", "title_span", title_span))

    date_spans = _safe_json_loads(row.get("date_spans_json"))
    if isinstance(date_spans, dict) and isinstance(date_spans.get("quote"), str):
        collected.append(("date", "date_spans[0]", date_spans))
    elif isinstance(date_spans, list):
        for idx, item in enumerate(date_spans):
            if isinstance(item, dict) and isinstance(item.get("quote"), str):
                collected.append(("date", f"date_spans[{idx}]", item))

    specialist_payload = _safe_json_loads(row.get("specialist_payload_json"))
    if specialist_payload is not None:
        nested: list[tuple[str, dict[str, Any]]] = []
        _extract_nested_spans(specialist_payload, "", nested)
        for path, item in nested:
            collected.append(("specialist", path or "specialist", item))

    spans: list[dict[str, Any]] = []
    for category, field, item in collected:
        quote = item.get("quote")
        start = item.get("start")
        end = item.get("end")
        if not isinstance(quote, str) or not isinstance(start, int) or not isinstance(end, int):
            continue

        raw_match = _exact_slice(raw_text, start, end, quote)
        clean_match = _exact_slice(clean_text, start, end, quote)
        clean_start: int | None = start if clean_match else None
        clean_end: int | None = end if clean_match else None

        if clean_match:
            status = "exact" if raw_match or raw_text is None else "clean_exact"
        elif raw_match:
            status = "raw_exact"
            if clean_text:
                pos = clean_text.find(quote)
                if pos != -1:
                    clean_start = pos
                    clean_end = pos + len(quote)
                    status = "bidi_reanchored"
        elif clean_text and quote in clean_text:
            pos = clean_text.find(quote)
            clean_start = pos
            clean_end = pos + len(quote)
            status = "substring_fallback"
        elif raw_text is None and clean_text is None:
            status = "no_text"
        else:
            status = "mismatch"

        spans.append(
            {
                "category": category,
                "field": field,
                "quote": quote,
                "start": start,
                "end": end,
                "clean_start": clean_start,
                "clean_end": clean_end,
                "status": status,
                "raw_match": raw_match,
                "clean_match": clean_match,
            }
        )

    spans.sort(key=lambda s: (s["start"], s["end"], s["category"], s["field"]))
    return spans


_ARC_HEADER_RE = re.compile(r"^(\S+)\s+\S+\s+\d{8,14}\s+(\S+)\s+(\d+)$")


def _extract_http_response(payload: bytes) -> tuple[bytes, str | None]:
    """Strip HTTP status/header lines from a captured response block and extract Content-Type."""
    if not payload.startswith(b"HTTP/"):
        return payload, None
    http_sep_len = 4
    http_end = payload.find(b"\r\n\r\n")
    if http_end == -1:
        http_end = payload.find(b"\n\n")
        http_sep_len = 2
    if http_end == -1:
        return payload, None
    http_hdr = payload[:http_end].decode("latin-1", errors="replace")
    ct: str | None = None
    for hline in http_hdr.splitlines()[1:]:
        if ":" in hline:
            hk, hv = hline.split(":", 1)
            if hk.strip().lower() == "content-type":
                ct = hv.split(";", 1)[0].strip().lower() or None
                break
    return payload[http_end + http_sep_len :], ct


def unwrap_warc_or_arc(data: bytes) -> tuple[bytes, str | None]:
    """Unwrap the first HTTP response payload and Content-Type from a WARC or legacy ARC container."""
    total = len(data)
    if data.startswith(b"WARC/"):
        pos = 0
        while pos < total:
            while pos < total and data[pos : pos + 1] in (b"\r", b"\n"):
                pos += 1
            if pos >= total or not data[pos:].startswith(b"WARC/"):
                break

            sep_len = 4
            hdr_end = data.find(b"\r\n\r\n", pos)
            if hdr_end == -1:
                hdr_end = data.find(b"\n\n", pos)
                sep_len = 2
            if hdr_end == -1:
                break

            hdr_text = data[pos:hdr_end].decode("latin-1", errors="replace")
            warc_headers: dict[str, str] = {}
            for line in hdr_text.splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    warc_headers[k.strip().lower()] = v.strip()

            try:
                content_len = int(warc_headers.get("content-length", "0"))
            except ValueError:
                break
            body_start = hdr_end + sep_len
            body_end = min(total, body_start + max(0, content_len))
            payload = data[body_start:body_end]
            pos = body_end

            if warc_headers.get("warc-type", "").lower() == "response":
                return _extract_http_response(payload)
        return data, None

    # Legacy Internet Archive ARC v1/v2 container
    pos = 0
    first_nl = data.find(b"\n")
    if first_nl != -1:
        first_line = data[:first_nl].decode("latin-1", errors="replace").rstrip("\r\n")
        if _ARC_HEADER_RE.match(first_line):
            while pos < total:
                while pos < total and data[pos : pos + 1] in (b"\r", b"\n"):
                    pos += 1
                if pos >= total:
                    break
                nl = data.find(b"\n", pos)
                if nl == -1:
                    break
                arc_line = data[pos:nl].decode("latin-1", errors="replace").rstrip("\r\n")
                m = _ARC_HEADER_RE.match(arc_line)
                if not m:
                    break
                rec_url, arc_ct, rec_len_str = m.groups()
                rec_len = int(rec_len_str)
                body_start = nl + 1
                body_end = min(total, body_start + rec_len)
                payload = data[body_start:body_end]
                pos = body_end
                if rec_url.startswith("filedesc://"):
                    continue
                body, http_ct = _extract_http_response(payload)
                fallback_ct = arc_ct.lower() if "/" in arc_ct else None
                return body, http_ct or fallback_ct

    return data, None


def sniff_media_type(payload: bytes, fallback: str | None) -> str:
    """Detect the true MIME type from leading magic bytes, falling back to metadata."""
    head = payload[:16]
    if b"%PDF-" in head:
        return "application/pdf"
    probe = payload[:512].lstrip().lower()
    if probe.startswith(b"<?xml"):
        return "application/xml"
    if probe.startswith(b"<!doctype html") or probe.startswith(b"<html"):
        return "text/html"
    return fallback or "application/octet-stream"


def sanitize_filename(name: str | None, fallback_sha: str, media_type: str) -> str:
    """Return a header-safe ASCII filename preserving extension when known."""
    cleaned = ""
    if name:
        cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip(" .")
    if not cleaned:
        ext = MEDIA_EXT_MAP.get(media_type, "")
        cleaned = f"{fallback_sha[:16]}{ext}"
    elif "." not in cleaned and media_type in MEDIA_EXT_MAP:
        cleaned = f"{cleaned}{MEDIA_EXT_MAP[media_type]}"
    return cleaned[:180]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def discover_candidate_paths(parquet_path: Path, explicit: list[Path] | None = None) -> list[Path]:
    if explicit is not None:
        return [p for p in explicit if p.exists()]
    parent_corpus = parquet_path.resolve().parent.parent
    defaults = [
        parent_corpus / "candidates_v7_3.jsonl",
        parent_corpus / "topup_budget/candidates_budget_topup.jsonl",
    ]
    return [p for p in defaults if p.exists()]


def discover_release_dir(explicit: Path | None = None) -> Path | None:
    """Return the newest published release directory containing `detail.parquet`."""
    if explicit is not None:
        return explicit if (explicit / "detail.parquet").exists() else None
    if not DEFAULT_RELEASE_ROOT.exists():
        return None
    dirs = [d for d in DEFAULT_RELEASE_ROOT.iterdir() if d.is_dir() and (d / "detail.parquet").exists()]
    if not dirs:
        return None
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0]


class DocMetaCorpusStore:
    """In-memory DuckDB + byte-offset JSONL + release/blob store backing the corpus inspector API."""

    def __init__(
        self,
        parquet_path: Path,
        *,
        candidate_paths: list[Path] | None = None,
        release_dir: Path | None = None,
        raw_base: str = DEFAULT_RAW_BASE,
        blob_cache_dir: Path | None = None,
    ) -> None:
        self.parquet_path = Path(parquet_path).resolve()
        if not self.parquet_path.exists():
            raise FileNotFoundError(f"Parquet file not found: {self.parquet_path}")

        self.sealed_dir = self.parquet_path.parent
        self.candidate_paths = discover_candidate_paths(self.parquet_path, candidate_paths)
        self.release_dir = Path(release_dir).resolve() if release_dir is not None else None
        self.raw_base = (raw_base or DEFAULT_RAW_BASE).rstrip("/")
        self.blob_cache_dir = Path(blob_cache_dir or DEFAULT_BLOB_CACHE).resolve()

        self._lock = threading.Lock()
        self._con = duckdb.connect(":memory:")
        self._con.execute("CREATE TABLE gold AS SELECT * FROM read_parquet(?)", [str(self.parquet_path)])
        self._con.execute(
            """
            CREATE TABLE candidates_meta (
                doc_key VARCHAR,
                filename VARCHAR,
                stratum VARCHAR,
                effective_format VARCHAR,
                source_pool VARCHAR
            )
            """
        )

        self._text_index: dict[str, tuple[Path, int]] = {}
        self._cand_meta: dict[str, dict[str, Any]] = {}
        self._index_candidates()

        self._detail_meta: dict[str, dict[str, Any]] = {}
        self._sources_by_doc: dict[str, list[dict[str, Any]]] = {}
        self._preload_release_links()

        self._quarantined = _read_jsonl(self.sealed_dir / "quarantined_v7_3.jsonl")
        self._deadlocks = _read_jsonl(self.sealed_dir / "deadlocks_v7_3.jsonl")
        manifest_path = self.sealed_dir / "MANIFEST.json"
        self._manifest: dict[str, Any] | None = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        )

        self._gold_count = int(self._con.execute("SELECT count(*) FROM gold").fetchone()[0])
        self._text_covered_count = int(
            self._con.execute(
                "SELECT count(*) FROM gold g JOIN candidates_meta c ON g.doc_key = c.doc_key"
            ).fetchone()[0]
        )

    def _index_candidates(self) -> None:
        batch: list[tuple[str, str | None, str | None, str | None, str | None]] = []
        for path in self.candidate_paths:
            with path.open("rb") as fh:
                while True:
                    offset = fh.tell()
                    raw_line = fh.readline()
                    if not raw_line:
                        break
                    if not raw_line.strip():
                        continue
                    obj = json.loads(raw_line)
                    doc_key = obj.get("doc_key")
                    if not isinstance(doc_key, str) or doc_key in self._text_index:
                        continue
                    self._text_index[doc_key] = (path, offset)
                    meta = {
                        "filename": obj.get("filename"),
                        "stratum": obj.get("stratum"),
                        "effective_format": obj.get("effective_format"),
                        "source_pool": obj.get("source_pool"),
                    }
                    self._cand_meta[doc_key] = meta
                    batch.append(
                        (
                            doc_key,
                            meta["filename"],
                            meta["stratum"],
                            meta["effective_format"],
                            meta["source_pool"],
                        )
                    )
        if batch:
            self._con.executemany("INSERT INTO candidates_meta VALUES (?, ?, ?, ?, ?)", batch)

    def _preload_release_links(self) -> None:
        if self.release_dir is None:
            return
        detail_path = self.release_dir / "detail.parquet"
        if not detail_path.exists():
            return

        rows = self._con.execute(
            """
            SELECT
                g.doc_key,
                lower(hex(d.saved_body)) AS saved_body_hex,
                d.saved_suffix,
                d.saved_media_type,
                d.saved_bytes,
                d.format AS detail_format,
                d.filename AS detail_filename,
                d.src_start,
                d.src_len
            FROM gold g
            JOIN read_parquet(?) d
              ON regexp_matches(g.link_key_hex, '^[0-9a-fA-F]+$')
             AND length(g.link_key_hex) % 2 = 0
             AND d.link_key = from_hex(g.link_key_hex)
            """,
            [str(detail_path)],
        ).fetchall()

        ranges: list[tuple[str, int, int]] = []
        for (
            doc_key,
            saved_body_hex,
            saved_suffix,
            saved_media_type,
            saved_bytes,
            detail_format,
            detail_filename,
            src_start,
            src_len,
        ) in rows:
            self._detail_meta[doc_key] = {
                "saved_body_hex": saved_body_hex or None,
                "saved_suffix": saved_suffix if saved_suffix is not None else "",
                "saved_media_type": saved_media_type,
                "saved_bytes": int(saved_bytes) if saved_bytes is not None else None,
                "detail_format": detail_format,
                "detail_filename": detail_filename,
                "src_start": int(src_start) if src_start is not None else None,
                "src_len": int(src_len) if src_len is not None else None,
            }
            if src_start is not None and src_len is not None and int(src_len) > 0:
                ranges.append((doc_key, int(src_start), int(src_len)))

        sources_path = self.release_dir / "sources.parquet"
        if not sources_path.exists() or not ranges:
            return

        self._con.execute(
            "CREATE TEMP TABLE _matched_ranges (doc_key VARCHAR, src_start BIGINT, src_len BIGINT)"
        )
        try:
            self._con.executemany("INSERT INTO _matched_ranges VALUES (?, ?, ?)", ranges)
            src_rows = self._con.execute(
                """
                WITH numbered_sources AS (
                    SELECT
                        row_number() OVER () - 1 AS rn,
                        url,
                        listed_on,
                        link_text,
                        is_saved,
                        CAST(first_seen AS VARCHAR) AS first_seen,
                        doc_type
                    FROM read_parquet(?)
                )
                SELECT
                    r.doc_key,
                    s.rn,
                    s.url,
                    s.listed_on,
                    s.link_text,
                    s.is_saved,
                    s.first_seen,
                    s.doc_type
                FROM _matched_ranges r
                JOIN numbered_sources s
                  ON s.rn >= r.src_start AND s.rn < r.src_start + r.src_len
                ORDER BY r.doc_key, s.is_saved DESC NULLS LAST, s.rn ASC
                """,
                [str(sources_path)],
            ).fetchall()
            for doc_key, rn, url, listed_on, link_text, is_saved, first_seen, doc_type in src_rows:
                bucket = self._sources_by_doc.setdefault(doc_key, [])
                if len(bucket) >= 20:
                    continue
                bucket.append(
                    {
                        "ordinal": int(rn),
                        "url": url,
                        "listed_on": listed_on,
                        "link_text": link_text,
                        "is_saved": bool(is_saved) if is_saved is not None else False,
                        "first_seen": first_seen,
                        "doc_type": doc_type,
                    }
                )
        finally:
            self._con.execute("DROP TABLE IF EXISTS _matched_ranges")

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def build_raw_file_info(self, doc_key: str, row: dict[str, Any]) -> dict[str, Any]:
        """Build raw file location, media type, inline preview mode, and source links for `doc_key`."""
        detail = self._detail_meta.get(doc_key) or {}
        cand = self._cand_meta.get(doc_key) or {}

        sha256_hex = (
            detail.get("saved_body_hex")
            or row.get("effective_body_sha_hex")
            or row.get("body_sha256")
            or ""
        ).lower()
        has_detail_body = bool(detail.get("saved_body_hex"))
        saved_suffix = detail["saved_suffix"] if has_detail_body else ".gz"

        filename = cand.get("filename") or detail.get("detail_filename") or ""
        fmt = (cand.get("effective_format") or detail.get("detail_format") or "").lower()
        inferred_mt = FORMAT_MEDIA_MAP.get(fmt)
        if not inferred_mt and filename:
            ext = Path(filename).suffix.lower().lstrip(".")
            inferred_mt = FORMAT_MEDIA_MAP.get(ext)
        media_type = (detail.get("saved_media_type") or inferred_mt or "application/octet-stream").lower()

        is_container = media_type in {
            "application/warc+gzip",
            "application/arc+gzip",
            "application/warc",
            "application/arc",
        }
        if media_type == "application/pdf":
            preview_kind = "pdf"
        elif (is_container or media_type == "application/octet-stream") and filename.lower().endswith(".pdf"):
            preview_kind = "pdf"
        elif media_type in {"text/html", "application/xhtml+xml"} or is_container:
            preview_kind = "html"
        elif media_type in {"application/xml", "text/xml"} or media_type.endswith("+xml"):
            preview_kind = "xml"
        elif media_type == "application/octet-stream" and filename.lower().endswith(".xml"):
            preview_kind = "xml"
        elif media_type.startswith("text/"):
            preview_kind = "text"
        else:
            preview_kind = "download_only"

        archive_url = (
            f"{self.raw_base}/bodies/sha256/{sha256_hex[:2]}/{sha256_hex}{saved_suffix}"
            if len(sha256_hex) >= 2
            else None
        )

        return {
            "available": bool(sha256_hex),
            "sha256": sha256_hex or None,
            "saved_suffix": saved_suffix,
            "suffix_inferred": not has_detail_body,
            "media_type": media_type,
            "saved_bytes": detail.get("saved_bytes"),
            "preview_kind": preview_kind,
            "archive_url": archive_url,
            "viewer_url": f"/api/raw/{doc_key}" if sha256_hex else None,
            "download_url": f"/api/raw/{doc_key}?download=1" if sha256_hex else None,
            "source_mode_url": f"/api/raw/{doc_key}?mode=source" if sha256_hex else None,
            "sources": self._sources_by_doc.get(doc_key, []),
        }

    def fetch_raw_file(self, doc_key: str) -> tuple[bytes, str, str]:
        """Fetch (via cache or remote R2), gunzip/unwrap, and sniff raw bytes for `doc_key`."""
        with self._lock:
            cur = self._con.execute(
                "SELECT doc_key, effective_body_sha_hex, body_sha256, media_format FROM gold WHERE doc_key = ? LIMIT 1",
                [doc_key],
            )
            row_tuple = cur.fetchone()
        if row_tuple is None:
            raise KeyError(doc_key)

        row = {
            "doc_key": row_tuple[0],
            "effective_body_sha_hex": row_tuple[1],
            "body_sha256": row_tuple[2],
            "media_format": row_tuple[3],
        }
        info = self.build_raw_file_info(doc_key, row)
        sha = info["sha256"]
        if not sha:
            raise FileNotFoundError(f"No SHA-256 associated with doc_key={doc_key}")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"Invalid archive SHA-256 for doc_key={doc_key}: {sha!r}")

        cand = self._cand_meta.get(doc_key) or {}
        detail = self._detail_meta.get(doc_key) or {}
        filename_hint = cand.get("filename") or detail.get("detail_filename")

        if info["suffix_inferred"]:
            candidate_suffixes = [".gz", ".pdf", ""]
        elif info["saved_suffix"] in {"", ".gz", ".pdf"}:
            candidate_suffixes = [info["saved_suffix"]]
        else:
            candidate_suffixes = [info["saved_suffix"] if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", info["saved_suffix"]) else ".gz"]

        blob_bytes: bytes | None = None
        saw_not_found = False
        last_err: Exception | None = None

        for suffix in candidate_suffixes:
            cache_path = (self.blob_cache_dir / sha[:2] / f"{sha}{suffix}").resolve()
            if not cache_path.is_relative_to(self.blob_cache_dir):
                raise ValueError(f"Refusing cache path outside blob directory: {cache_path}")
            if cache_path.exists():
                blob_bytes = cache_path.read_bytes()
                break

            url = f"{self.raw_base}/bodies/sha256/{sha[:2]}/{sha}{suffix}"
            req = urllib.request.Request(url, headers={"User-Agent": "congressional-tech-viewer/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    fetched = resp.read()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=cache_path.parent, delete=False) as tf:
                    tf.write(fetched)
                    tmp_path = tf.name
                os.replace(tmp_path, cache_path)
                blob_bytes = fetched
                break
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code == HTTPStatus.NOT_FOUND:
                    saw_not_found = True
                    continue
                raise RuntimeError(f"Upstream HTTP {exc.code} fetching {url}") from exc
            except OSError as exc:
                last_err = exc
                raise RuntimeError(f"Upstream fetch failed for {url}: {exc}") from exc

        if blob_bytes is None:
            if saw_not_found:
                raise FileNotFoundError(f"Archive object not found for {doc_key} ({sha})")
            raise RuntimeError(f"Unable to fetch raw file for {doc_key}: {last_err}")

        if blob_bytes[:2] == b"\x1f\x8b":
            payload = gzip.decompress(blob_bytes)
        else:
            payload = blob_bytes

        unwrapped_ct: str | None = None
        if info["media_type"] in {"application/warc+gzip", "application/arc+gzip", "application/warc", "application/arc"} or payload.startswith(b"WARC/"):
            payload, unwrapped_ct = unwrap_warc_or_arc(payload)

        content_type = sniff_media_type(payload, unwrapped_ct or info["media_type"])
        safe_name = sanitize_filename(filename_hint, sha, content_type)
        return payload, content_type, safe_name

    def get_source_text(self, doc_key: str) -> dict[str, Any] | None:
        loc = self._text_index.get(doc_key)
        if loc is None:
            return None
        path, offset = loc
        with path.open("rb") as fh:
            fh.seek(offset)
            obj = json.loads(fh.readline())
        raw_text = obj.get("text")
        clean_text = strip_invisible_format_chars(raw_text) if isinstance(raw_text, str) else None
        bidi_removed = (len(raw_text) - len(clean_text)) if (raw_text is not None and clean_text is not None) else 0
        return {
            "doc_key": doc_key,
            "filename": obj.get("filename"),
            "stratum": obj.get("stratum"),
            "effective_format": obj.get("effective_format"),
            "source_pool": obj.get("source_pool"),
            "raw_text": raw_text,
            "clean_text": clean_text,
            "bidi_chars_removed": bidi_removed,
        }

    def _build_where(
        self,
        params: dict[str, str],
        *,
        exclude_facet: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        args: list[Any] = []

        for col, kind in FACET_COLUMNS:
            if col == exclude_facet:
                continue
            val = (params.get(col) or "").strip()
            if not val:
                continue
            if val == NULL_SENTINEL:
                clauses.append(f"g.{col} IS NULL")
            elif kind == "bool":
                if val.lower() in {"true", "1", "yes"}:
                    clauses.append(f"g.{col} IS TRUE")
                elif val.lower() in {"false", "0", "no"}:
                    clauses.append(f"g.{col} IS FALSE")
            else:
                clauses.append(f"g.{col} = ?")
                args.append(val)

        congress_val = (params.get("congress") or "").strip()
        if congress_val:
            if congress_val == NULL_SENTINEL:
                clauses.append("g.congress IS NULL")
            else:
                try:
                    clauses.append("g.congress = ?")
                    args.append(int(congress_val))
                except ValueError:
                    pass

        q = (params.get("q") or "").strip()
        if q:
            like_pat = f"%{q.lower()}%"
            clauses.append(
                "("
                "lower(coalesce(g.doc_key, '')) LIKE ? OR "
                "lower(coalesce(g.link_key_hex, '')) LIKE ? OR "
                "lower(coalesce(g.verbatim_title, '')) LIKE ? OR "
                "lower(coalesce(g.gist, '')) LIKE ? OR "
                "lower(coalesce(g.subkind, '')) LIKE ? OR "
                "lower(coalesce(g.rationale, '')) LIKE ? OR "
                "lower(coalesce(c.filename, '')) LIKE ? OR "
                "lower(array_to_string(coalesce(g.topics, []), ' ')) LIKE ?"
                ")"
            )
            args.extend([like_pat] * 8)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where_sql, args

    def _facet_counts_locked(self, params: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
        facets: dict[str, list[dict[str, Any]]] = {}
        for col, kind in FACET_COLUMNS:
            where_sql, args = self._build_where(params, exclude_facet=col)
            rows = self._con.execute(
                f"""
                SELECT g.{col} AS val, count(*) AS cnt
                FROM gold g
                LEFT JOIN candidates_meta c ON g.doc_key = c.doc_key
                {where_sql}
                GROUP BY 1
                ORDER BY 2 DESC, 1 ASC NULLS LAST
                """,
                args,
            ).fetchall()
            out_list: list[dict[str, Any]] = []
            for raw_val, cnt in rows:
                if raw_val is None:
                    key = NULL_SENTINEL
                    label = "(none)"
                elif kind == "bool":
                    key = "true" if raw_val else "false"
                    label = "Packet" if raw_val else "Single doc"
                else:
                    key = str(raw_val)
                    label = key
                out_list.append({"value": key, "label": label, "count": int(cnt)})
            facets[col] = out_list
        return facets

    def get_meta(self) -> dict[str, Any]:
        with self._lock:
            facets = self._facet_counts_locked({})
        manifest_summary: dict[str, Any] | None = None
        if self._manifest is not None:
            manifest_summary = {
                "sealed_at": self._manifest.get("sealed_at"),
                "codebook_version": self._manifest.get("codebook_version"),
                "total_processed": self._manifest.get("total_processed"),
                "gold_count": self._manifest.get("gold_count"),
                "quarantined_count": self._manifest.get("quarantined_count"),
                "deadlock_count": self._manifest.get("deadlock_count"),
            }
        return {
            "parquet_path": str(self.parquet_path),
            "release_dir": str(self.release_dir) if self.release_dir else None,
            "raw_base": self.raw_base,
            "total_gold": self._gold_count,
            "quarantined_count": len(self._quarantined),
            "deadlock_count": len(self._deadlocks),
            "text_covered_count": self._text_covered_count,
            "detail_matched_count": len(self._detail_meta),
            "sources_matched_count": len(self._sources_by_doc),
            "manifest": manifest_summary,
            "facets": facets,
        }

    def query_records(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            page = max(1, int(params.get("page") or 1))
        except ValueError:
            page = 1
        try:
            page_size = min(200, max(1, int(params.get("page_size") or 50)))
        except ValueError:
            page_size = 50
        sort_key = params.get("sort") or "default"
        order_sql = SORT_CLAUSES.get(sort_key, SORT_CLAUSES["default"])
        offset = (page - 1) * page_size

        with self._lock:
            where_sql, args = self._build_where(params)
            total = int(
                self._con.execute(
                    f"""
                    SELECT count(*)
                    FROM gold g
                    LEFT JOIN candidates_meta c ON g.doc_key = c.doc_key
                    {where_sql}
                    """,
                    args,
                ).fetchone()[0]
            )
            cur = self._con.execute(
                f"""
                SELECT
                    g.doc_key,
                    g.link_key_hex,
                    g.split,
                    g.status,
                    g.media_format,
                    g.is_packet,
                    g.primary_genre,
                    g.specialist_family,
                    g.subkind,
                    g.verdict,
                    g.consensus_families,
                    g.specialist_teacher,
                    g.verbatim_title,
                    g.gist,
                    g.doc_date,
                    g.chamber,
                    g.congress,
                    g.committees,
                    c.filename,
                    c.effective_format,
                    c.stratum
                FROM gold g
                LEFT JOIN candidates_meta c ON g.doc_key = c.doc_key
                {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                [*args, page_size, offset],
            )
            cols = [desc[0] for desc in cur.description]
            items = [{col: _json_safe(val) for col, val in zip(cols, row)} for row in cur.fetchall()]
            facets = self._facet_counts_locked(params)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
            "facets": facets,
        }

    def get_record(self, doc_key: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._con.execute("SELECT * FROM gold WHERE doc_key = ? LIMIT 1", [doc_key])
            row_tuple = cur.fetchone()
            if row_tuple is None:
                return None
            cols = [desc[0] for desc in cur.description]
            row = {col: _json_safe(val) for col, val in zip(cols, row_tuple)}

        text_info = self.get_source_text(doc_key)
        cand_meta = self._cand_meta.get(doc_key, {})
        raw_text = text_info["raw_text"] if text_info else None
        clean_text = text_info["clean_text"] if text_info else None

        spans = collect_spans(row, raw_text, clean_text)
        row["filename"] = cand_meta.get("filename")
        row["stratum"] = cand_meta.get("stratum")
        row["effective_format"] = cand_meta.get("effective_format")
        row["source_pool"] = cand_meta.get("source_pool")
        row["raw_text"] = raw_text
        row["clean_text"] = clean_text
        row["bidi_chars_removed"] = text_info["bidi_chars_removed"] if text_info else 0
        row["title_span"] = _safe_json_loads(row.get("title_span_json"))
        row["date_spans"] = _safe_json_loads(row.get("date_spans_json"))
        row["specialist_payload"] = _safe_json_loads(row.get("specialist_payload_json"))
        row["spans"] = spans
        row["raw_file"] = self.build_raw_file_info(doc_key, row)
        return row

    def get_overview(self) -> dict[str, Any]:
        with self._lock:
            split_by_genre = self._con.execute(
                """
                SELECT coalesce(primary_genre, '(none)') AS genre, split, count(*) AS cnt
                FROM gold
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ).fetchall()
            split_by_status = self._con.execute(
                """
                SELECT status, split, count(*) AS cnt
                FROM gold
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ).fetchall()
            split_by_verdict = self._con.execute(
                """
                SELECT verdict, split, count(*) AS cnt
                FROM gold
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ).fetchall()
            consensus_counts = self._con.execute(
                """
                SELECT array_to_string(coalesce(consensus_families, []), ' + ') AS combo, count(*) AS cnt
                FROM gold
                GROUP BY 1
                ORDER BY 2 DESC, 1 ASC
                """
            ).fetchall()
            congress_counts = self._con.execute(
                """
                SELECT congress, count(*) AS cnt
                FROM gold
                WHERE congress IS NOT NULL
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT 25
                """
            ).fetchall()
            facets = self._facet_counts_locked({})

        return {
            "total_gold": self._gold_count,
            "quarantined_count": len(self._quarantined),
            "deadlock_count": len(self._deadlocks),
            "facets": facets,
            "split_by_genre": [
                {"genre": str(g), "split": str(s), "count": int(c)} for g, s, c in split_by_genre
            ],
            "split_by_status": [
                {"status": str(st), "split": str(s), "count": int(c)} for st, s, c in split_by_status
            ],
            "split_by_verdict": [
                {"verdict": str(v), "split": str(s), "count": int(c)} for v, s, c in split_by_verdict
            ],
            "consensus_counts": [
                {"combo": combo or "(none)", "count": int(c)} for combo, c in consensus_counts
            ],
            "congress_counts": [
                {"congress": int(cong), "count": int(c)} for cong, c in congress_counts
            ],
        }

    def get_quarantined(self) -> dict[str, Any]:
        return {
            "quarantined": self._quarantined,
            "deadlocks": self._deadlocks,
        }


def make_handler(store: DocMetaCorpusStore, html_path: Path) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to `store` and static viewer `html_path`."""

    class ViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_bytes(
            self,
            status: int,
            content_type: str,
            body: bytes,
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra_headers:
                for hk, hv in extra_headers.items():
                    self.send_header(hk, hv)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", body)

        def _handle_raw(self, doc_key: str, query_str: str) -> None:
            qs = parse_qs(query_str, keep_blank_values=True)
            download = (qs.get("download") or [""])[-1] == "1"
            mode = (qs.get("mode") or [""])[-1]
            try:
                payload, content_type, safe_name = store.fetch_raw_file(doc_key)
            except KeyError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown doc_key: {doc_key}"})
                return
            except FileNotFoundError as exc:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return

            headers: dict[str, str] = {"X-Content-Type-Options": "nosniff"}
            if download:
                headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
                if content_type != "application/pdf":
                    headers["Content-Security-Policy"] = "sandbox"
                self._send_bytes(HTTPStatus.OK, content_type, payload, extra_headers=headers)
                return

            if content_type == "application/pdf":
                headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
                self._send_bytes(HTTPStatus.OK, "application/pdf", payload, extra_headers=headers)
                return

            if content_type in {"text/html", "application/xhtml+xml"}:
                headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
                headers["Content-Security-Policy"] = "sandbox"
                served_ct = "text/plain; charset=utf-8" if mode == "source" else "text/html; charset=utf-8"
                self._send_bytes(HTTPStatus.OK, served_ct, payload, extra_headers=headers)
                return

            if content_type in {"application/xml", "text/xml", "text/plain"} or content_type.startswith("text/"):
                headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
                headers["Content-Security-Policy"] = "sandbox"
                self._send_bytes(HTTPStatus.OK, "text/plain; charset=utf-8", payload, extra_headers=headers)
                return

            headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
            headers["Content-Security-Policy"] = "sandbox"
            self._send_bytes(HTTPStatus.OK, content_type, payload, extra_headers=headers)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "/index.html":
                if not html_path.exists():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Missing HTML UI at {html_path}"})
                    return
                self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", html_path.read_bytes())
                return

            if path == "/api/meta":
                self._send_json(HTTPStatus.OK, store.get_meta())
                return

            if path == "/api/records":
                raw_qs = parse_qs(parsed.query, keep_blank_values=True)
                params = {k: vals[-1] for k, vals in raw_qs.items() if vals}
                self._send_json(HTTPStatus.OK, store.query_records(params))
                return

            if path.startswith("/api/records/"):
                doc_key = unquote(path[len("/api/records/") :].strip("/"))
                rec = store.get_record(doc_key)
                if rec is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown doc_key: {doc_key}"})
                    return
                self._send_json(HTTPStatus.OK, rec)
                return

            if path.startswith("/api/raw/"):
                doc_key = unquote(path[len("/api/raw/") :].strip("/"))
                self._handle_raw(doc_key, parsed.query)
                return

            if path.startswith("/api/text/"):
                doc_key = unquote(path[len("/api/text/") :].strip("/"))
                text_info = store.get_source_text(doc_key)
                if text_info is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"No source text for doc_key: {doc_key}"})
                    return
                self._send_json(HTTPStatus.OK, text_info)
                return

            if path == "/api/overview":
                self._send_json(HTTPStatus.OK, store.get_overview())
                return

            if path == "/api/quarantined":
                self._send_json(HTTPStatus.OK, store.get_quarantined())
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Not found: {path}"})

    return ViewerHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive localhost viewer for docmeta_v7_3.parquet")
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET, help="Path to docmeta_v7_3.parquet")
    parser.add_argument(
        "--candidates",
        type=Path,
        nargs="*",
        default=None,
        help="Optional candidate JSONL files containing 9K source text",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        help="Published release directory containing detail.parquet and sources.parquet (default: newest local)",
    )
    parser.add_argument("--raw-base", default=DEFAULT_RAW_BASE, help="Public R2 raw archive base URL")
    parser.add_argument("--blob-cache-dir", type=Path, default=DEFAULT_BLOB_CACHE, help="Local cache dir for fetched raw files")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8733, help="Bind port (default: 8733)")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    resolved_release = discover_release_dir(args.release_dir)
    store = DocMetaCorpusStore(
        args.parquet,
        candidate_paths=args.candidates,
        release_dir=resolved_release,
        raw_base=args.raw_base,
        blob_cache_dir=args.blob_cache_dir,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, DEFAULT_HTML))
    url = f"http://{args.host}:{server.server_port}"
    print(
        f"DocMeta V7.3 viewer listening on {url} "
        f"({store._gold_count:,} gold, {store._text_covered_count:,} text-matched, "
        f"{len(store._detail_meta):,} release-linked, {len(store._quarantined)} quarantined, "
        f"{len(store._deadlocks)} deadlocks)",
        flush=True,
    )
    if not args.no_open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
