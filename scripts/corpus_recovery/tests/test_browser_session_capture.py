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

    def test_emit_snippet_validates_same_origin_and_writes_script(self) -> None:
        targets_path = self.root / "targets.json"
        targets_path.write_text(json.dumps([
            {
                "case_id": "zero-page-test",
                "original_url": "http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "fetch_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))
        out = self.root / "snippet.js"
        bsc.emit_snippet(targets_path, out, interval_seconds=15.0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("showDirectoryPicker", text)
        self.assertIn("15000", text)
        self.assertIn("cf-mitigated", text)
        self.assertIn("zero-page-test", text)

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
        self.assertEqual(entry["pages"], 2)
        self.assertEqual(entry["shared_prefix"]["shared_prefix_bytes"], 200)
        raw_receipt = stage / "raw" / entry["receipt_key"]
        self.assertTrue(raw_receipt.is_file())
        line = json.loads(gzip.decompress(raw_receipt.read_bytes()))
        self.assertEqual(line["transport"], "browser_same_origin")
        self.assertEqual(line["outcome"], "stored")

    def _run_ingest_single(self, row: dict, pdf_bytes: bytes | None = None) -> dict:
        capture_dir = self.root / ("cap_" + hashlib.sha256(json.dumps(row).encode()).hexdigest()[:8])
        capture_dir.mkdir(exist_ok=True)
        if pdf_bytes is not None:
            (capture_dir / f"{row['sha256']}.pdf").write_bytes(pdf_bytes)
        (capture_dir / "browser-captures.jsonl").write_text(json.dumps(row) + "\n")
        return bsc.ingest_captures(
            capture_dir,
            self.root / ("stage_" + capture_dir.name),
            writer_identity=self.identity,
            write_date="2026-11-18",
        )

    def test_ingest_rejects_digest_mismatch_non14digit_loc_and_throttling(self) -> None:
        tmp_pdf = self.root / "ok.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        base = {
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
