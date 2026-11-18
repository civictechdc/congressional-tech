"""Tests for scripts/corpus_recovery/browser_session_capture.py."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/corpus_recovery"))
import browser_session_capture as bsc  # noqa: E402


def _make_valid_pdf(path: Path, pages: int = 2) -> tuple[str, int]:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Witness testimony test page {i + 1}")
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


class BrowserSessionCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.identity = {
            "job": "test-browser-capture",
            "commit": "0" * 40,
            "lockfile_digest": "a" * 64,
        }

    def test_emit_snippet_single_target_manual_redirect_timeout_and_resume(self) -> None:
        targets_path = self.root / "targets.json"
        targets_path.write_text(json.dumps([
            {
                "case_id": "zero-page-test",
                "original_url": "http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "fetch_url": "https://webarchive.loc.gov/all/20111102120000id_/http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))
        out = self.root / "snippet.js"
        bsc.emit_snippet(targets_path, out, interval_seconds=15.0, timeout_seconds=45.0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("showDirectoryPicker", text)
        self.assertIn("15000", text)
        self.assertIn("45000", text)
        self.assertIn("cf-mitigated", text)
        self.assertIn("content-range", text)
        self.assertIn("redirect: 'manual'", text)
        self.assertNotIn("redirect: 'follow'", text)
        self.assertIn("opaqueredirect", text)
        self.assertIn("AbortController", text)
        self.assertIn("arrayBufferWithAbort", text)
        self.assertIn("readExistingLines", text)
        self.assertIn("zero-page-test", text)
        # Single-target-per-click step button, not a multi-target fetch loop
        self.assertNotIn("for (let i = 0; i < TARGETS.length", text)

        bad_targets = self.root / "bad_targets.json"
        bad_targets.write_text(json.dumps([
            {
                "case_id": "bad",
                "original_url": "http://example.gov/a.pdf",
                "fetch_url": "https://other.example.gov/a.pdf",
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))
        with self.assertRaisesRegex(ValueError, "origin differs"):
            bsc.emit_snippet(bad_targets, self.root / "bad.js")

    def test_ingest_valid_pdf_writes_frozen_receipt_and_qualifies(self) -> None:
        capture_dir = self.root / "captured"
        capture_dir.mkdir()
        tmp_pdf = self.root / "sample.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=2)
        (capture_dir / f"{digest}.pdf").write_bytes(tmp_pdf.read_bytes())

        final_url = (
            "https://webarchive.loc.gov/all/20111102120000id_/"
            "http://oversight.house.gov/images/stories/Testimony/Test_File.pdf"
        )
        manifest_row = {
            "case_id": "zero-page-test",
            "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/Test_File.pdf",
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/Test_File.pdf",
            "final_url": final_url,
            "http_status": 200,
            "retrieved_at": "2026-11-18T19:00:00+00:00",
            "headers": {"content-type": "application/pdf", "memento-datetime": "Wed, 02 Nov 2011 12:00:00 GMT"},
            "sha256": digest,
            "bytes": size,
        }
        (capture_dir / "browser-captures.jsonl").write_text(json.dumps(manifest_row) + "\n")

        damaged_sources = self.root / "sources"
        damaged_hex = "b" * 64
        (damaged_sources / damaged_hex).mkdir(parents=True)
        (damaged_sources / damaged_hex / "original.bin").write_bytes(tmp_pdf.read_bytes()[:200])
        damaged_manifest = self.root / "manifest.tsv"
        damaged_manifest.write_text(f"case\tsha256\tbytes\nzero-page-test\t{damaged_hex}\t200\n")

        stage = self.root / "stage"
        report = bsc.ingest_captures(
            capture_dir,
            stage,
            writer_identity=self.identity,
            run_id="test-browser-run",
            write_date="2026-11-18",
            damaged_manifest=damaged_manifest,
            damaged_sources_dir=damaged_sources,
        )
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["qualified"], 1)
        entry = report["entries"][0]
        self.assertEqual(entry["media_type"], "application/pdf")
        self.assertEqual(entry["pages"], 2)
        self.assertEqual(entry["shared_prefix"]["shared_prefix_bytes"], 200)
        raw_receipt = stage / "raw" / entry["receipt_key"]
        self.assertTrue(raw_receipt.is_file())
        line = json.loads(gzip.decompress(raw_receipt.read_bytes()))
        self.assertEqual(line["transport"], "browser_same_origin")
        self.assertEqual(line["outcome"], "stored")
        # Atomic report published cleanly with no leftover temp files
        report_file = stage / "qualification-report.json"
        self.assertTrue(report_file.is_file())
        self.assertEqual(json.loads(report_file.read_text(encoding="utf-8"))["qualified"], 1)
        self.assertEqual(list(stage.glob(".qualification-report.json.*.tmp")), [])

    def _run_ingest_single(
        self,
        row: dict,
        pdf_bytes: bytes | None = None,
        *,
        stage_dir: Path | None = None,
        damaged_manifest: Path | None = None,
        damaged_sources_dir: Path | None = None,
    ) -> dict:
        tag = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:10]
        capture_dir = self.root / f"cap_{tag}"
        capture_dir.mkdir(exist_ok=True)
        if pdf_bytes is not None:
            (capture_dir / f"{row['sha256']}.pdf").write_bytes(pdf_bytes)
        (capture_dir / "browser-captures.jsonl").write_text(json.dumps(row) + "\n")
        return bsc.ingest_captures(
            capture_dir,
            stage_dir or (self.root / f"stage_{tag}"),
            writer_identity=self.identity,
            write_date="2026-11-18",
            damaged_manifest=damaged_manifest,
            damaged_sources_dir=damaged_sources_dir,
        )

    def _base_row(self, digest: str, size: int) -> dict:
        return {
            "case_id": "c1",
            "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/A.pdf",
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
            "http_status": 200,
            "retrieved_at": "2026-11-18T19:00:00+00:00",
            "headers": {"content-type": "application/pdf"},
            "sha256": digest,
            "bytes": size,
        }

    def test_ingest_rejects_digest_mismatch_non14digit_loc_and_throttling(self) -> None:
        tmp_pdf = self.root / "ok.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        base = self._base_row(digest, size)

        with self.assertRaisesRegex(ValueError, "size mismatch"):
            self._run_ingest_single(base, ok_bytes + b"tamper")

        same_len_tamper = (b"X" if ok_bytes[0:1] != b"X" else b"Y") + ok_bytes[1:]
        with self.assertRaisesRegex(ValueError, "SHA-256|sha256|digest"):
            self._run_ingest_single(base, same_len_tamper)

        bad_loc = {**base, "final_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/A.pdf"}
        with self.assertRaisesRegex(ValueError, "allowed_url|14-digit"):
            self._run_ingest_single(bad_loc, ok_bytes)

        bad_403 = {**base, "http_status": 403}
        with self.assertRaisesRegex(ValueError, "http_status=200"):
            self._run_ingest_single(bad_403, ok_bytes)

        bad_retry = {**base, "headers": {"content-type": "application/pdf", "Retry-After": "60"}}
        with self.assertRaisesRegex(ValueError, "retry-after"):
            self._run_ingest_single(bad_retry, ok_bytes)

    def test_ingest_rejects_content_range_partial_transfer(self) -> None:
        tmp_pdf = self.root / "partial.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        partial_row = {
            **self._base_row(digest, size),
            "headers": {"content-type": "application/pdf", "Content-Range": f"bytes 0-{size - 1}/{size + 100}"},
        }
        stage = self.root / "stage_partial"
        with self.assertRaisesRegex(ValueError, "content-range"):
            self._run_ingest_single(partial_row, ok_bytes, stage_dir=stage)
        self.assertFalse((stage / "frozen-receipts").exists())

    def test_ingest_rejects_html_content_type_and_html_body(self) -> None:
        html_bytes = b"<!doctype html><html><body>" + (b"Witness testimony paragraph. " * 40) + b"</body></html>"
        html_sha = hashlib.sha256(html_bytes).hexdigest()
        base = self._base_row(html_sha, len(html_bytes))

        # 1. Explicit text/html header refused
        html_ct_row = {**base, "headers": {"content-type": "text/html; charset=utf-8"}}
        with self.assertRaisesRegex(ValueError, "non-PDF content-type"):
            self._run_ingest_single(html_ct_row, html_bytes)

        # 2. HTML body masquerading as application/pdf refused before writing any receipt
        stage = self.root / "stage_html_disguised"
        with self.assertRaisesRegex(ValueError, "not a PDF"):
            self._run_ingest_single(base, html_bytes, stage_dir=stage)
        self.assertFalse((stage / "frozen-receipts").exists())

    def test_ingest_validates_timestamp_before_writing_frozen_receipt(self) -> None:
        tmp_pdf = self.root / "ts.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        stage = self.root / "stage_bad_ts"
        bad_ts_row = {**self._base_row(digest, size), "retrieved_at": "not-an-iso-timestamp"}
        with self.assertRaises(ValueError):
            self._run_ingest_single(bad_ts_row, ok_bytes, stage_dir=stage)
        # Must NOT strand a frozen receipt directory on failed timestamp validation
        self.assertFalse((stage / "frozen-receipts").exists())

        # Retrying with a fixed timestamp in the SAME output directory must succeed cleanly
        fixed_row = {**bad_ts_row, "retrieved_at": "2026-11-18T19:00:00+00:00"}
        report = self._run_ingest_single(fixed_row, ok_bytes, stage_dir=stage)
        self.assertEqual(report["qualified"], 1)

    def test_ingest_rejects_damaged_manifest_traversal_and_bad_sha256(self) -> None:
        tmp_pdf = self.root / "trav.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        base = self._base_row(digest, size)

        damaged_sources = self.root / "dmg_sources"
        damaged_sources.mkdir()

        bad_manifest = self.root / "traversal.tsv"
        bad_manifest.write_text("case\tsha256\tbytes\nc1\t../../etc\t10\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid damaged_manifest"):
            self._run_ingest_single(
                base, ok_bytes, damaged_manifest=bad_manifest, damaged_sources_dir=damaged_sources
            )

        # Also test direct helper containment/digest guard
        with self.assertRaisesRegex(ValueError, "Invalid damaged source sha256"):
            bsc._resolve_damaged_original(damaged_sources, "../outside")

    def test_ingest_rejects_cross_origin_or_mismatched_requested_url(self) -> None:
        tmp_pdf = self.root / "orig.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        base = self._base_row(digest, size)

        cross_origin = {**base, "requested_url": "https://other.example.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/A.pdf"}
        with self.assertRaisesRegex(ValueError, "origin differs"):
            self._run_ingest_single(cross_origin, ok_bytes)

        diff_target = {**base, "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/OTHER.pdf"}
        with self.assertRaisesRegex(ValueError, "invalid requested_url"):
            self._run_ingest_single(diff_target, ok_bytes)

    def test_ingest_marks_truncated_pdf_unresolved_with_cutoff_hint(self) -> None:
        tmp_pdf = self.root / "full.pdf"
        _make_valid_pdf(tmp_pdf, pages=1)
        raw = tmp_pdf.read_bytes()
        truncated = (raw[:100] + b"\x00" * 1024)[:1024]
        digest = hashlib.sha256(truncated).hexdigest()
        row = {
            "case_id": "trunc",
            "original_url": "https://www.gao.gov/assets/gao-26-109023.pdf",
            "requested_url": "https://www.gao.gov/assets/gao-26-109023.pdf",
            "final_url": "https://www.gao.gov/assets/gao-26-109023.pdf",
            "http_status": 200,
            "retrieved_at": "2026-11-18T19:00:00+00:00",
            "headers": {"content-type": "application/pdf"},
            "sha256": digest,
            "bytes": len(truncated),
        }
        report = self._run_ingest_single(row, truncated)
        self.assertEqual(report["qualified"], 0)
        self.assertEqual(report["entries"][0]["qualification_status"], "unresolved")
        self.assertEqual(report["entries"][0]["qualification_reason"], "missing_pdf_eof")
        self.assertEqual(report["entries"][0]["cutoff_size_hint"], "1 KiB")


if __name__ == "__main__":
    unittest.main()
