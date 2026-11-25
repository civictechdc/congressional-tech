"""Tests for `scripts/view_docmeta_v7_3.py` (`docmeta_v7_3.parquet` corpus viewer)."""

from __future__ import annotations

import datetime as dt
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_viewer():
    spec = importlib.util.spec_from_file_location("view_docmeta_v7_3", ROOT / "scripts" / "view_docmeta_v7_3.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


viewer = _load_viewer()


def _make_warc_html(html_bytes: bytes) -> bytes:
    http_block = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: " + str(len(html_bytes)).encode("ascii") + b"\r\n\r\n" + html_bytes
    )
    warc_header = (
        b"WARC/1.0\r\n"
        b"WARC-Type: response\r\n"
        b"Content-Length: " + str(len(http_block)).encode("ascii") + b"\r\n\r\n"
    )
    return warc_header + http_block + b"\r\n\r\n"


def _write_fixture_corpus(tmp_path: Path) -> tuple[Path, list[Path], Path, dict[str, bytes]]:
    corpus_dir = tmp_path / "docmeta-v7-corpus"
    sealed_dir = corpus_dir / "sealed"
    topup_dir = corpus_dir / "topup_budget"
    rel_dir = tmp_path / "published_release"
    sealed_dir.mkdir(parents=True)
    topup_dir.mkdir(parents=True)
    rel_dir.mkdir(parents=True)

    raw_bidi_text = "\u202dTESTIMONY OF JANE DOE\u202c\nDate: March 18, 2025\nIssuer: Acme Foundation\nBody text."
    raw_plain_text = "<p>H.R. 4210 Markup Packet</p>\nAdopted June 2, 2026 by voice vote."

    c1 = corpus_dir / "candidates_v7_3.jsonl"
    c1.write_text(
        json.dumps(
            {
                "doc_key": "k1",
                "filename": "doe_testimony.pdf",
                "source_pool": "archive_v6_2",
                "stratum": "ssot:witness",
                "effective_format": "pdf",
                "text": raw_bidi_text,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    c2 = topup_dir / "candidates_budget_topup.jsonl"
    c2.write_text(
        json.dumps(
            {
                "doc_key": "k2",
                "filename": "hr4210_markup.html",
                "source_pool": "archive_v6_2",
                "stratum": "unlocked_tail:html",
                "effective_format": "html",
                "text": raw_plain_text,
            }
        )
        + "\n"
        + json.dumps(
            {
                "doc_key": "k3",
                "filename": "notes.docx",
                "source_pool": "archive_v6_2",
                "stratum": "other",
                "effective_format": "docx",
                "text": "Docx notes",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    schema = pa.schema(
        [
            ("doc_key", pa.string()),
            ("link_key_hex", pa.string()),
            ("body_sha256", pa.string()),
            ("effective_body_sha_hex", pa.string()),
            ("text_window_spec", pa.string()),
            ("text_window_sha256", pa.string()),
            ("split", pa.string()),
            ("verdict", pa.string()),
            ("consensus_families", pa.list_(pa.string())),
            ("specialist_teacher", pa.string()),
            ("status", pa.string()),
            ("media_format", pa.string()),
            ("is_packet", pa.bool_()),
            ("contains_genres", pa.list_(pa.string())),
            ("primary_genre", pa.string()),
            ("archive_document_kind", pa.string()),
            ("specialist_family", pa.string()),
            ("subkind", pa.string()),
            ("verbatim_title", pa.string()),
            ("doc_date", pa.string()),
            ("chamber", pa.string()),
            ("congress", pa.int64()),
            ("committees", pa.list_(pa.string())),
            ("gist", pa.string()),
            ("topics", pa.list_(pa.string())),
            ("rationale", pa.string()),
            ("title_span_json", pa.string()),
            ("date_spans_json", pa.string()),
            ("specialist_payload_json", pa.string()),
            ("codebook_version", pa.string()),
            ("crosswalk_congress_gov_types", pa.list_(pa.string())),
            ("crosswalk_docs_house_codes", pa.list_(pa.string())),
            ("crosswalk_lcgft_uris", pa.list_(pa.string())),
        ]
    )

    title_start = raw_bidi_text.index("TESTIMONY OF JANE DOE")
    issuer_start = raw_bidi_text.index("Acme Foundation")
    date_start = raw_bidi_text.index("March 18, 2025")

    sb1 = "aa" * 32
    sb2 = "bb" * 32
    sb3 = "cc" * 32

    rows = [
        {
            "doc_key": "k1",
            "link_key_hex": "00010001",
            "body_sha256": sb1,
            "effective_body_sha_hex": sb1,
            "text_window_spec": "p12_clean_or_raw_head_9000",
            "text_window_sha256": "w1",
            "split": "train",
            "verdict": "auto_accept_gold",
            "consensus_families": ["claude", "codex", "gemini"],
            "specialist_teacher": "claude",
            "status": "usable",
            "media_format": "prose",
            "is_packet": False,
            "contains_genres": [],
            "primary_genre": "witness_testimony",
            "archive_document_kind": "witness-statement",
            "specialist_family": "testimony_bio_disclosure",
            "subkind": "public_witness",
            "verbatim_title": "TESTIMONY OF JANE DOE",
            "doc_date": "2025-03-18",
            "chamber": "house",
            "congress": 119,
            "committees": ["House Energy"],
            "gist": "Testimony on AI weather modeling.",
            "topics": ["weather", "AI"],
            "rationale": "Single witness testimony.",
            "title_span_json": json.dumps({"quote": "TESTIMONY OF JANE DOE", "start": title_start, "end": title_start + 21}),
            "date_spans_json": json.dumps([{"quote": "March 18, 2025", "start": date_start, "end": date_start + 14}]),
            "specialist_payload_json": json.dumps(
                {
                    "issuer_org": "Acme Foundation",
                    "issuer_org_span": {"quote": "Acme Foundation", "start": issuer_start, "end": issuer_start + 15},
                }
            ),
            "codebook_version": "cb1",
            "crosswalk_congress_gov_types": ["Witness Statement"],
            "crosswalk_docs_house_codes": ["WS"],
            "crosswalk_lcgft_uris": ["http://example.org/ws"],
        },
        {
            "doc_key": "k2",
            "link_key_hex": "00020002",
            "body_sha256": sb2,
            "effective_body_sha_hex": sb2,
            "text_window_spec": "p12_clean_or_raw_head_9000",
            "text_window_sha256": "w2",
            "split": "sealed_temporal_2026",
            "verdict": "checkeval_resolved",
            "consensus_families": ["claude", "codex"],
            "specialist_teacher": "claude",
            "status": "usable",
            "media_format": "prose",
            "is_packet": True,
            "contains_genres": ["bill_or_amendment", "committee_vote_or_action"],
            "primary_genre": "committee_vote_or_action",
            "archive_document_kind": "committee-action",
            "specialist_family": "transcript_vote_attendance",
            "subkind": "markup_packet",
            "verbatim_title": "H.R. 4210 Markup Packet",
            "doc_date": "2026-06-02",
            "chamber": "senate",
            "congress": 119,
            "committees": ["Senate Commerce"],
            "gist": "Combined bill text and voice vote action.",
            "topics": ["telecom"],
            "rationale": "Packet combining bill and vote.",
            "title_span_json": json.dumps({"quote": "H.R. 4210 Markup Packet", "start": 3, "end": 26}),
            "date_spans_json": None,
            "specialist_payload_json": None,
            "codebook_version": "cb1",
            "crosswalk_congress_gov_types": [],
            "crosswalk_docs_house_codes": [],
            "crosswalk_lcgft_uris": [],
        },
        {
            "doc_key": "k3",
            "link_key_hex": "00030003",
            "body_sha256": sb3,
            "effective_body_sha_hex": sb3,
            "text_window_spec": "p12_clean_or_raw_head_9000",
            "text_window_sha256": "w3",
            "split": "dev_iter",
            "verdict": "auto_accept_gold",
            "consensus_families": ["claude", "codex", "gemini"],
            "specialist_teacher": None,
            "status": "stub_or_blank",
            "media_format": "unknown",
            "is_packet": False,
            "contains_genres": [],
            "primary_genre": None,
            "archive_document_kind": None,
            "specialist_family": None,
            "subkind": None,
            "verbatim_title": None,
            "doc_date": None,
            "chamber": None,
            "congress": None,
            "committees": [],
            "gist": "Blank stub page.",
            "topics": [],
            "rationale": "Empty whitespace body.",
            "title_span_json": None,
            "date_spans_json": None,
            "specialist_payload_json": None,
            "codebook_version": "cb1",
            "crosswalk_congress_gov_types": [],
            "crosswalk_docs_house_codes": [],
            "crosswalk_lcgft_uris": [],
        },
    ]

    parquet_path = sealed_dir / "docmeta_v7_3.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), parquet_path)

    # Published release detail.parquet & sources.parquet
    detail_rows = [
        {
            "link_key": bytes.fromhex("00010001"),
            "saved_body": bytes.fromhex(sb1),
            "saved_suffix": ".gz",
            "saved_media_type": "application/pdf",
            "saved_bytes": 1024,
            "format": "pdf",
            "filename": "doe_testimony.pdf",
            "src_start": 0,
            "src_len": 2,
        },
        {
            "link_key": bytes.fromhex("00020002"),
            "saved_body": bytes.fromhex(sb2),
            "saved_suffix": ".gz",
            "saved_media_type": "application/warc+gzip",
            "saved_bytes": 512,
            "format": "html",
            "filename": "hr4210_markup.html",
            "src_start": 2,
            "src_len": 1,
        },
        {
            "link_key": bytes.fromhex("00030003"),
            "saved_body": bytes.fromhex(sb3),
            "saved_suffix": ".gz",
            "saved_media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "saved_bytes": 256,
            "format": "docx",
            "filename": "notes.docx",
            "src_start": 0,
            "src_len": 0,
        },
    ]
    pq.write_table(
        pa.table(
            {
                "link_key": pa.array([r["link_key"] for r in detail_rows], type=pa.binary()),
                "saved_body": pa.array([r["saved_body"] for r in detail_rows], type=pa.binary()),
                "saved_suffix": [r["saved_suffix"] for r in detail_rows],
                "saved_media_type": [r["saved_media_type"] for r in detail_rows],
                "saved_bytes": pa.array([r["saved_bytes"] for r in detail_rows], type=pa.int64()),
                "format": [r["format"] for r in detail_rows],
                "filename": [r["filename"] for r in detail_rows],
                "src_start": pa.array([r["src_start"] for r in detail_rows], type=pa.int64()),
                "src_len": pa.array([r["src_len"] for r in detail_rows], type=pa.int64()),
            }
        ),
        rel_dir / "detail.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "list_row": [0, 0, 1],
                "ordinal": [0, 1, 0],
                "url": [
                    "https://energycommerce.house.gov/doe_testimony.pdf",
                    "https://web.archive.org/doe_testimony.pdf",
                    "https://commerce.senate.gov/hr4210_markup.html",
                ],
                "member_path": [None, None, None],
                "is_saved": [True, False, True],
                "first_seen": [dt.date(2025, 3, 18), dt.date(2025, 3, 19), dt.date(2026, 6, 2)],
                "listed_on": [
                    "https://energycommerce.house.gov/hearings/weather",
                    None,
                    "https://commerce.senate.gov/markups/hr4210",
                ],
                "link_text": ["Jane Doe Written Testimony", "Archive Mirror", "HR 4210 Markup"],
                "doc_type": ["Witness Statement", None, "Markup"],
                "posted": [None, None, None],
            }
        ),
        rel_dir / "sources.parquet",
    )

    (sealed_dir / "quarantined_v7_3.jsonl").write_text(
        json.dumps({"doc_key": "q1", "filename": "q1.pdf", "verdict": "quarantined_excluded", "deadlock_reason": "cover_truncation"}) + "\n",
        encoding="utf-8",
    )
    (sealed_dir / "deadlocks_v7_3.jsonl").write_text(
        json.dumps({"doc_key": "d1", "filename": "d1.pdf", "verdict": "deadlock_needs_owner", "deadlock_reason": "checkeval_explicit_ambiguous"}) + "\n",
        encoding="utf-8",
    )
    (sealed_dir / "MANIFEST.json").write_text(json.dumps({"gold_count": 3, "quarantined_count": 1, "deadlock_count": 1}), encoding="utf-8")

    blobs = {
        f"/bodies/sha256/{sb1[:2]}/{sb1}.gz": gzip.compress(b"%PDF-1.7\n%Synthetic PDF bytes\n%%EOF"),
        f"/bodies/sha256/{sb2[:2]}/{sb2}.gz": gzip.compress(_make_warc_html(b"<html><body>Hello WARC</body></html>")),
        f"/bodies/sha256/{sb3[:2]}/{sb3}.gz": gzip.compress(b"PK\x03\x04FAKE_DOCX"),
    }
    return parquet_path, [c1, c2], rel_dir, blobs


def test_unwrap_warc_helper() -> None:
    raw_warc = _make_warc_html(b"<html><body>Hello</body></html>")
    body, ct = viewer.unwrap_warc_or_arc(raw_warc)
    assert body == b"<html><body>Hello</body></html>"
    assert ct == "text/html"
    assert viewer.unwrap_warc_or_arc(b"%PDF-1.7")[0] == b"%PDF-1.7"

    # Legacy Internet Archive ARC v1/v2 container with leading filedesc:// metadata record
    arc_meta = b"version-1\n"
    arc_http = b"HTTP/1.0 200 OK\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n%%EOF"
    raw_arc = (
        f"filedesc://old.arc 0.0.0.0 20110101000000 text/plain {len(arc_meta)}\n".encode("ascii")
        + arc_meta
        + b"\n"
        + f"https://example.gov/doc.pdf 1.2.3.4 20110101000001 application/pdf {len(arc_http)}\n".encode("ascii")
        + arc_http
        + b"\n"
    )
    arc_body, arc_ct = viewer.unwrap_warc_or_arc(raw_arc)
    assert arc_body == b"%PDF-1.4\n%%EOF"
    assert arc_ct == "application/pdf"


def test_store_filtering_spans_bidi_and_release_links(tmp_path: Path) -> None:
    parquet_path, candidates, rel_dir, _ = _write_fixture_corpus(tmp_path)
    store = viewer.DocMetaCorpusStore(
        parquet_path,
        candidate_paths=candidates,
        release_dir=rel_dir,
        blob_cache_dir=tmp_path / "blobs",
    )
    try:
        meta = store.get_meta()
        assert meta["total_gold"] == 3
        assert meta["text_covered_count"] == 3
        assert meta["detail_matched_count"] == 3
        assert meta["sources_matched_count"] == 2
        assert meta["quarantined_count"] == 1
        assert meta["deadlock_count"] == 1

        res_null = store.query_records({"primary_genre": viewer.NULL_SENTINEL})
        assert res_null["total"] == 1
        assert res_null["items"][0]["doc_key"] == "k3"

        res_pkt = store.query_records({"is_packet": "true"})
        assert res_pkt["total"] == 1
        assert res_pkt["items"][0]["doc_key"] == "k2"

        res_q = store.query_records({"q": "doe_testimony.pdf", "page_size": "1", "page": "1"})
        assert res_q["total"] == 1
        assert res_q["items"][0]["doc_key"] == "k1"

        rec = store.get_record("k1")
        assert rec is not None
        assert rec["bidi_chars_removed"] == 2
        by_field = {sp["field"]: sp for sp in rec["spans"]}
        assert by_field["title_span"]["status"] == "bidi_reanchored"
        assert by_field["issuer_org_span"]["status"] == "bidi_reanchored"
        assert rec["raw_file"]["preview_kind"] == "pdf"
        assert len(rec["raw_file"]["sources"]) == 2
        assert rec["raw_file"]["sources"][0]["url"] == "https://energycommerce.house.gov/doe_testimony.pdf"

        # DOCX must NOT be misclassified as xml due to "openxmlformats"
        rec_k3 = store.get_record("k3")
        assert rec_k3 is not None
        assert rec_k3["raw_file"]["preview_kind"] == "download_only"

        # HTML served from a .pdf URL must stay preview_kind="html", not "pdf"
        store._detail_meta["k1_html"] = {
            "saved_body_hex": "aa" * 32,
            "saved_suffix": ".gz",
            "saved_media_type": "text/html",
            "saved_bytes": 100,
            "detail_format": "html",
            "detail_filename": "fake_html_at_pdf_url.pdf",
            "src_start": 0,
            "src_len": 0,
        }
        store._cand_meta["k1_html"] = {"filename": "fake_html_at_pdf_url.pdf", "effective_format": "html"}
        html_pdf_info = store.build_raw_file_info("k1_html", {"doc_key": "k1_html", "effective_body_sha_hex": "aa" * 32})
        assert html_pdf_info["preview_kind"] == "html"
    finally:
        store.close()


def test_http_server_and_raw_proxy_endpoints(tmp_path: Path) -> None:
    parquet_path, candidates, rel_dir, blobs = _write_fixture_corpus(tmp_path)

    class FakeR2Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def do_GET(self) -> None:
            data = blobs.get(self.path)
            if data is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    r2_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeR2Handler)
    r2_thread = threading.Thread(target=r2_server.serve_forever, daemon=True)
    r2_thread.start()

    store = viewer.DocMetaCorpusStore(
        parquet_path,
        candidate_paths=candidates,
        release_dir=rel_dir,
        raw_base=f"http://127.0.0.1:{r2_server.server_port}",
        blob_cache_dir=tmp_path / "blobs",
    )
    server = viewer.ThreadingHTTPServer(("127.0.0.1", 0), viewer.make_handler(store, viewer.DEFAULT_HTML))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        html_body = urlopen(f"{base}/").read().decode("utf-8")
        assert "Inline Raw File" in html_body

        rec = json.loads(urlopen(f"{base}/api/records/k1").read().decode("utf-8"))
        assert rec["raw_file"]["preview_kind"] == "pdf"
        assert rec["raw_file"]["viewer_url"] == "/api/raw/k1"

        # URL-encoded doc_key path segments decode cleanly
        rec_enc = json.loads(urlopen(f"{base}/api/records/k%31").read().decode("utf-8"))
        assert rec_enc["doc_key"] == "k1"

        # Inline PDF response must NOT include sandbox CSP
        with urlopen(f"{base}/api/raw/k1") as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "application/pdf"
            assert resp.headers["Content-Disposition"].startswith('inline; filename="doe_testimony.pdf"')
            assert resp.headers.get("Content-Security-Policy") is None
            assert resp.read().startswith(b"%PDF-1.7")

        # Download PDF forces attachment
        with urlopen(f"{base}/api/raw/k1?download=1") as resp:
            assert resp.headers["Content-Disposition"].startswith('attachment; filename="doe_testimony.pdf"')

        # Unwrapped WARC HTML response MUST include sandbox CSP
        with urlopen(f"{base}/api/raw/k2") as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "text/html; charset=utf-8"
            assert resp.headers.get("Content-Security-Policy") == "sandbox"
            assert resp.read() == b"<html><body>Hello WARC</body></html>"

        with urlopen(f"{base}/api/raw/k2?mode=source") as resp:
            assert resp.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert resp.headers.get("Content-Security-Policy") == "sandbox"

        # Binary docx forces attachment
        with urlopen(f"{base}/api/raw/k3") as resp:
            assert resp.headers["Content-Disposition"].startswith('attachment; filename="notes.docx"')

        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base}/api/raw/does-not-exist")
        assert exc_info.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        r2_server.shutdown()
        r2_server.server_close()
        store.close()
