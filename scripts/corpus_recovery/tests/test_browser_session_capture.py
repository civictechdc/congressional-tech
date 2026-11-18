"""Tests for scripts/corpus_recovery/browser_session_capture.py."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
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


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    fallback = Path("/Users/mikewolfd/.nvm/versions/node/v22.22.2/bin/node")
    return str(fallback) if fallback.is_file() else None


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

    def test_emit_snippet_requires_14digit_loc_url_and_same_origin(self) -> None:
        # 4-digit year-selector LoC URL must be rejected up front by emit_snippet
        unusable_loc = self.root / "unusable_loc.json"
        unusable_loc.write_text(json.dumps([
            {
                "case_id": "zero-page-test",
                "original_url": "http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "fetch_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/images/stories/Testimony/Foo.pdf",
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))
        with self.assertRaisesRegex(ValueError, "14-digit id_ replay URL"):
            bsc.emit_snippet(unusable_loc, self.root / "unusable.js")

        # Valid 14-digit LoC URL succeeds
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
        self.assertIn("redirect: 'manual'", text)
        self.assertNotIn("redirect: 'follow'", text)
        self.assertIn("hasValidPdfHeader", text)

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

    def test_generated_js_snippet_executes_capture_resume_and_safe_folder_switch_in_node(self) -> None:
        node_bin = _find_node()
        if node_bin is None:
            self.skipTest("node runtime not available")

        targets_path = self.root / "js_targets.json"
        t1_url = "https://webarchive.loc.gov/all/20111102120000id_/http://oversight.house.gov/images/stories/Testimony/One.pdf"
        t2_url = "https://webarchive.loc.gov/all/20111102120500id_/http://oversight.house.gov/images/stories/Testimony/Two.pdf"
        t3_url = "https://webarchive.loc.gov/all/20111102121000id_/http://oversight.house.gov/images/stories/Testimony/Three.pdf"
        targets_path.write_text(json.dumps([
            {
                "case_id": "case-1",
                "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/One.pdf",
                "fetch_url": t1_url,
                "expected_origin": "https://webarchive.loc.gov",
            },
            {
                "case_id": "case-2",
                "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/Two.pdf",
                "fetch_url": t2_url,
                "expected_origin": "https://webarchive.loc.gov",
            },
            {
                "case_id": "case-3",
                "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/Three.pdf",
                "fetch_url": t3_url,
                "expected_origin": "https://webarchive.loc.gov",
            },
        ]))
        snippet_path = self.root / "generated.js"
        # Use tiny cooldown (0.001s -> 1ms) so sequential clicks in Node test run instantaneously
        bsc.emit_snippet(targets_path, snippet_path, interval_seconds=0.001, timeout_seconds=5.0)

        harness = self.root / "harness.mjs"
        harness.write_text(
            f"""
import fs from 'node:fs';
import assert from 'node:assert/strict';

class FakeDir {{
  constructor(initial = {{}}, failReadOn = new Set()) {{
    this.files = new Map(Object.entries(initial));
    this.failReadOn = failReadOn;
    this.pauseNextPdfClose = false;
    this.pdfCloseStarted = null;
    this.releasePdfClose = null;
  }}
  armPdfClosePause() {{
    this.pauseNextPdfClose = true;
    this.pdfCloseStarted = new Promise((resolve) => {{ this._markPdfCloseStarted = resolve; }});
    this._pdfCloseGate = new Promise((resolve) => {{ this.releasePdfClose = resolve; }});
  }}
  async getFileHandle(name, opts = {{}}) {{
    if (!this.files.has(name)) {{
      if (opts.create) {{
        this.files.set(name, new Uint8Array(0));
      }} else {{
        const e = new Error('Not found');
        e.name = 'NotFoundError';
        throw e;
      }}
    }}
    const dir = this;
    return {{
      async getFile() {{
        if (dir.failReadOn.has(name)) {{
          throw new Error('Simulated read failure on ' + name);
        }}
        const raw = dir.files.get(name);
        return {{
          async text() {{
            return typeof raw === 'string' ? raw : new TextDecoder().decode(raw);
          }}
        }};
      }},
      async createWritable() {{
        let pending = null;
        return {{
          async write(data) {{ pending = data; }},
          async close() {{
            if (dir.pauseNextPdfClose && name.endsWith('.pdf')) {{
              dir.pauseNextPdfClose = false;
              dir._markPdfCloseStarted();
              await dir._pdfCloseGate;
            }}
            dir.files.set(name, pending);
          }}
        }};
      }}
    }};
  }}
}}

const elements = new Map();
function makeEl(tag) {{
  const listeners = new Map();
  return {{
    tag,
    style: {{}},
    children: [],
    disabled: false,
    textContent: '',
    set id(v) {{ this._id = v; elements.set(v, this); }},
    get id( ) {{ return this._id; }},
    appendChild(c) {{ this.children.push(c); }},
    remove() {{ elements.delete(this._id); }},
    addEventListener(ev, fn) {{ listeners.set(ev, fn); }},
    async click() {{
      if (this.disabled) return;
      const fn = listeners.get('click');
      if (fn) await fn();
    }},
    async forceListenerClick() {{
      const fn = listeners.get('click');
      if (fn) await fn();
    }}
  }};
}}

let currentPickerResult = null;
globalThis.document = {{
  getElementById: (id) => elements.get(id) || null,
  createElement: (tag) => makeEl(tag),
  body: makeEl('body'),
}};
globalThis.window = {{
  location: {{ origin: 'https://webarchive.loc.gov' }},
  showDirectoryPicker: async () => {{
    if (currentPickerResult instanceof Error) throw currentPickerResult;
    return currentPickerResult;
  }}
}};

const pdf1 = new TextEncoder().encode('%PDF-1.4\\nFake PDF 1\\n%%EOF\\n');
const pdf2 = new TextEncoder().encode('%PDF-1.4\\nFake PDF 2\\n%%EOF\\n');
const pdf3 = new TextEncoder().encode('%PDF-1.4\\nFake PDF 3\\n%%EOF\\n');
globalThis.fetch = async (url, opts) => {{
  assert.equal(opts.redirect, 'manual');
  const payload = url.endsWith('One.pdf') ? pdf1 : (url.endsWith('Two.pdf') ? pdf2 : pdf3);
  return {{
    type: 'basic',
    status: 200,
    url,
    headers: {{
      get(k) {{
        if (k.toLowerCase() === 'content-type') return 'application/pdf';
        return null;
      }}
    }},
    async arrayBuffer() {{ return payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength); }}
  }};
}};

const code = fs.readFileSync({json.dumps(str(snippet_path))}, 'utf8');
eval(code);

const pickBtn = elements.get('ct-browser-pick-btn');
const stepBtn = elements.get('ct-browser-step-btn');
assert.equal(stepBtn.disabled, true);

// 1. Capture case-1 into Folder A
const folderA = new FakeDir();
currentPickerResult = folderA;
await pickBtn.click();
assert.equal(stepBtn.disabled, false);
await stepBtn.click();
const aManifestAfter1 = folderA.files.get('browser-captures.jsonl');
assert.ok(aManifestAfter1.includes('"case_id":"case-1"'));
await new Promise((r) => setTimeout(r, 5));
assert.equal(stepBtn.disabled, false);

// 2. Switch to Folder B whose manifest read FAILS -> must disable stepBtn and NEVER overwrite B's manifest!
const bOriginalManifest = '{{"case_id":"precious-existing"}}\\n';
const folderB = new FakeDir({{ 'browser-captures.jsonl': bOriginalManifest }}, new Set(['browser-captures.jsonl']));
currentPickerResult = folderB;
await pickBtn.click();
assert.equal(stepBtn.disabled, true, 'stepBtn must be disabled after failed folder switch');
await stepBtn.click(); // no-op while disabled
assert.equal(folderB.files.get('browser-captures.jsonl'), bOriginalManifest, 'Folder B manifest must remain untouched');
assert.equal(folderA.files.get('browser-captures.jsonl'), aManifestAfter1, 'Folder A manifest must remain untouched');

// 3. Re-open Folder A (resume): preserves case-1 and advances straight to case-2 without clobbering!
currentPickerResult = folderA;
await pickBtn.click();
assert.equal(stepBtn.disabled, false);
assert.ok(stepBtn.textContent.includes('case-2'));
await stepBtn.click();
const aLinesAfter2 = folderA.files.get('browser-captures.jsonl').trim().split('\\n');
assert.equal(aLinesAfter2.length, 2);
assert.equal(JSON.parse(aLinesAfter2[0]).case_id, 'case-1');
assert.equal(JSON.parse(aLinesAfter2[1]).case_id, 'case-2');

// 4. In-flight folder-switch interleaving during case-3 PDF write:
// Pause PDF close() in Folder A, attempt to switch to Folder C mid-capture (both normal click and raw listener),
// then release the write and verify Folder C stays empty while Folder A holds both PDF and manifest row!
await new Promise((r) => setTimeout(r, 5));
assert.equal(stepBtn.disabled, false);
assert.ok(stepBtn.textContent.includes('case-3'));
folderA.armPdfClosePause();
const folderC = new FakeDir();
currentPickerResult = folderC;

const inFlightCapture = stepBtn.click();
await folderA.pdfCloseStarted;
assert.equal(window.__ctBrowserCaptureActive, true, 'global busy lock must be set during capture');
assert.equal(pickBtn.disabled, true, 'pickBtn must be disabled throughout in-flight capture');
assert.equal(stepBtn.disabled, true, 'stepBtn must be disabled throughout in-flight capture');
await pickBtn.click(); // ignored while disabled
await pickBtn.forceListenerClick(); // also blocked by captureInFlight guard
// Repasting snippet during active capture must refuse panel replacement so no second panel can race!
eval(code);
assert.equal(elements.get('ct-browser-step-btn'), stepBtn, 'active panel must not be replaced mid-capture');
assert.ok(elements.get('ct-browser-capture-status').textContent.includes('Refused snippet reload'));
folderA.releasePdfClose();
await inFlightCapture;

assert.equal(window.__ctBrowserCaptureActive, false, 'global busy lock cleared after capture finishes');
assert.equal(pickBtn.disabled, false, 'pickBtn re-enabled after capture finishes');
assert.equal(folderC.files.size, 0, 'Folder C must remain completely empty after blocked in-flight switch');
const aLinesAfter3 = folderA.files.get('browser-captures.jsonl').trim().split('\\n');
assert.equal(aLinesAfter3.length, 3);
const row3 = JSON.parse(aLinesAfter3[2]);
assert.equal(row3.case_id, 'case-3');
assert.ok(folderA.files.has(`${{row3.sha256}}.pdf`), 'Folder A must hold case-3 PDF alongside its manifest row');

// Idle reload replaces panel cleanly and preserves all 3 existing rows
eval(code);
const reloadedPickBtn = elements.get('ct-browser-pick-btn');
const reloadedStepBtn = elements.get('ct-browser-step-btn');
assert.notEqual(reloadedStepBtn, stepBtn, 'idle reload mounts fresh panel');
currentPickerResult = folderA;
await reloadedPickBtn.click();
assert.ok(reloadedStepBtn.textContent.includes('Done (3/3 captured)'));
console.log('JS_SNIPPET_BEHAVIOR_OK');
""",
            encoding="utf-8",
        )
        proc = subprocess.run([node_bin, str(harness)], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn("JS_SNIPPET_BEHAVIOR_OK", proc.stdout)

    def test_ingest_valid_pdf_with_targets_binding_and_end_to_end_readback(self) -> None:
        capture_dir = self.root / "captured"
        capture_dir.mkdir()
        tmp_pdf = self.root / "sample.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=2)
        (capture_dir / f"{digest}.pdf").write_bytes(tmp_pdf.read_bytes())

        final_url = (
            "https://webarchive.loc.gov/all/20111102120000id_/"
            "http://oversight.house.gov/images/stories/Testimony/Test_File.pdf"
        )
        orig_url = "https://oversight.house.gov/wp-content/uploads/2012/01/Test_File.pdf"
        targets_file = self.root / "trusted_targets.json"
        targets_file.write_text(json.dumps([
            {
                "case_id": "zero-page-test",
                "original_url": orig_url,
                "fetch_url": final_url,
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))

        manifest_row = {
            "case_id": "zero-page-test",
            "original_url": orig_url,
            "requested_url": final_url,
            "final_url": final_url,
            "http_status": 200,
            "retrieved_at": "2026-11-18T19:00:00Z",
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
            targets_path=targets_file,
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
        self.assertEqual(line["retrieved_at"], "2026-11-18T19:00:00+00:00")
        # Frozen receipt also matches raw receipt digest
        frozen_meta = json.loads((stage / "frozen-receipts" / entry["operation_id"] / "receipt.json").read_text())
        frozen_gz = (stage / "frozen-receipts" / entry["operation_id"] / "receipt.gz").read_bytes()
        self.assertEqual(hashlib.sha256(frozen_gz).hexdigest(), frozen_meta["sha256"])

    def _run_ingest_single(
        self,
        row: dict,
        pdf_bytes: bytes | None = None,
        *,
        stage_dir: Path | None = None,
        damaged_manifest: Path | None = None,
        damaged_sources_dir: Path | None = None,
        targets_path: Path | None = None,
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
            targets_path=targets_path,
        )

    def _base_row(self, digest: str, size: int) -> dict:
        return {
            "case_id": "c1",
            "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/A.pdf",
            "requested_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
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

    def test_ingest_rejects_html_including_html_mentioning_pdf_marker(self) -> None:
        # HTML mentioning %PDF-1.4 inside markup must STILL be rejected beforeReceiptWriter!
        html_with_marker = b"<!doctype html><html><body>Note: %PDF-1.4 header missing\n" + (b"Text " * 30) + b"</body></html>"
        html_sha = hashlib.sha256(html_with_marker).hexdigest()
        base = self._base_row(html_sha, len(html_with_marker))

        html_ct_row = {**base, "headers": {"content-type": "text/html; charset=utf-8"}}
        with self.assertRaisesRegex(ValueError, "non-PDF content-type"):
            self._run_ingest_single(html_ct_row, html_with_marker)

        stage = self.root / "stage_html_marker"
        with self.assertRaisesRegex(ValueError, "not a valid PDF"):
            self._run_ingest_single(base, html_with_marker, stage_dir=stage)
        self.assertFalse((stage / "frozen-receipts").exists())

    def test_ingest_requires_explicit_utc_timestamp_before_writing_frozen_receipt(self) -> None:
        tmp_pdf = self.root / "ts.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        stage = self.root / "stage_bad_ts"

        for bad_ts in ("not-an-iso-timestamp", "2026-11-18T14:00:00-05:00", "2026-11-18T19:00:00"):
            bad_row = {**self._base_row(digest, size), "retrieved_at": bad_ts}
            with self.assertRaises(ValueError):
                self._run_ingest_single(bad_row, ok_bytes, stage_dir=stage)
            self.assertFalse((stage / "frozen-receipts").exists())

        fixed_row = {**self._base_row(digest, size), "retrieved_at": "2026-11-18T19:00:00Z"}
        report = self._run_ingest_single(fixed_row, ok_bytes, stage_dir=stage)
        self.assertEqual(report["qualified"], 1)

    def test_ingest_rejects_mismatched_a_to_b_urls_and_enforces_trusted_targets(self) -> None:
        tmp_pdf = self.root / "orig.pdf"
        digest, size = _make_valid_pdf(tmp_pdf, pages=1)
        ok_bytes = tmp_pdf.read_bytes()
        base = self._base_row(digest, size)

        # Two valid 14-digit LoC URLs for DIFFERENT files (A.pdf vs B.pdf) must be rejected!
        a_to_b = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/images/stories/Testimony/B.pdf",
        }
        with self.assertRaisesRegex(ValueError, "does not match final_url target"):
            self._run_ingest_single(a_to_b, ok_bytes)

        # Query-string file mismatch on legacy selector (download?file=A.pdf -> download?file=B.pdf) must be rejected!
        query_a_to_b = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/download?file=A.pdf",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?file=B.pdf",
        }
        with self.assertRaisesRegex(ValueError, "does not match final_url target"):
            self._run_ingest_single(query_a_to_b, ok_bytes)

        # Two DIFFERENT 14-digit timestamps for the same path must be rejected (resolved replays require exact equality)!
        diff_14digit_ts = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
            "final_url": "https://webarchive.loc.gov/all/20111102120000id_/http://oversight.house.gov/images/stories/Testimony/A.pdf",
        }
        with self.assertRaisesRegex(ValueError, "does not match final_url target"):
            self._run_ingest_single(diff_14digit_ts, ok_bytes)

        # Matching legacy selector + query string (download?file=A.pdf -> download?file=A.pdf) succeeds without --targets
        matching_legacy_query = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/download?file=A.pdf",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?file=A.pdf",
        }
        ok_legacy_report = self._run_ingest_single(matching_legacy_query, ok_bytes)
        self.assertEqual(ok_legacy_report["qualified"], 1)

        # Empty-query symmetry: identical '/download?' -> '/download?' passes, whereas '/download' -> '/download?' fails!
        matching_empty_query = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?",
        }
        self.assertEqual(self._run_ingest_single(matching_empty_query, ok_bytes)["qualified"], 1)

        mismatched_empty_query_resolved = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?",
        }
        with self.assertRaisesRegex(ValueError, "does not match final_url target"):
            self._run_ingest_single(mismatched_empty_query_resolved, ok_bytes)

        mismatched_empty_query_legacy = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/download",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?",
        }
        with self.assertRaisesRegex(ValueError, "does not match final_url target"):
            self._run_ingest_single(mismatched_empty_query_legacy, ok_bytes)

        matching_empty_query_legacy = {
            **base,
            "requested_url": "https://webarchive.loc.gov/all/2011id_/http://oversight.house.gov/download?",
            "final_url": "https://webarchive.loc.gov/all/20111010000000id_/http://oversight.house.gov/download?",
        }
        self.assertEqual(self._run_ingest_single(matching_empty_query_legacy, ok_bytes)["qualified"], 1)

        # Trusted --targets rejects wrong case_id or wrong original_url
        targets_file = self.root / "targets_bind.json"
        targets_file.write_text(json.dumps([
            {
                "case_id": "c1",
                "original_url": base["original_url"],
                "fetch_url": base["final_url"],
                "expected_origin": "https://webarchive.loc.gov",
            }
        ]))
        spoofed_orig = {**base, "original_url": "https://oversight.house.gov/wp-content/uploads/2012/01/SPOOF.pdf"}
        with self.assertRaisesRegex(ValueError, "does not match trusted target"):
            self._run_ingest_single(spoofed_orig, ok_bytes, targets_path=targets_file)

        spoofed_case = {**base, "case_id": "unknown-case"}
        with self.assertRaisesRegex(ValueError, "not present in trusted --targets"):
            self._run_ingest_single(spoofed_case, ok_bytes, targets_path=targets_file)

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

        with self.assertRaisesRegex(ValueError, "Invalid damaged source sha256"):
            bsc._resolve_damaged_original(damaged_sources, "../outside")

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
