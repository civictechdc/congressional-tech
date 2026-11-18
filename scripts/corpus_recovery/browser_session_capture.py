#!/usr/bin/env python3
"""Emit same-origin browser capture helpers and ingest captured PDFs into local ReceiptWriter staging.

Designed for origins that screen automated clients behind interactive browser checks
(such as webarchive.loc.gov) while keeping every captured file bound to a standard
ReceiptWriter receipt, LocalAdapter raw store, acceptance.receipt_binding, and
corpus_recovery qualification.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
from congress_api.parsers.archive_links import ARCHIVE_REPLAY_PATHS, allowed_url
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_record
from congress_api.retention.provenance import verify_local_file
from congress_api.retention.receipt_writer import ReceiptWriter
from corpus_recovery.acceptance import receipt_binding
from corpus_recovery.discovery import shared_prefix
from corpus_recovery.pipeline import cutoff_size_hint, qualify_candidate_body

LOC_REPLAY_ID_RE = re.compile(r"^/all/[0-9]{14}id_/(https?://.+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRANSPORT_NAME = "browser_same_origin"

_SNIPPET_TEMPLATE = r"""(() => {
  const TARGETS = __TARGETS_JSON__;
  const EXPECTED_ORIGIN = __EXPECTED_ORIGIN_JSON__;
  const INTERVAL_MS = __INTERVAL_MS__;
  const LOC_REPLAY_RE = /^\/all\/[0-9]{14}id_\/https?:\/\/.+/;
  const ALLOWED_HEADERS = [
    'content-type', 'content-length', 'content-disposition', 'content-range',
    'last-modified', 'etag', 'content-encoding', 'retry-after', 'date',
    'cache-control', 'accept-ranges', 'memento-datetime'
  ];

  const existing = document.getElementById('ct-browser-capture-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.id = 'ct-browser-capture-panel';
  Object.assign(panel.style, {
    position: 'fixed', bottom: '16px', right: '16px', zIndex: '2147483647',
    background: '#111827', color: '#f9fafb', padding: '12px 14px',
    borderRadius: '8px', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: '12px', maxWidth: '460px', boxShadow: '0 8px 24px rgba(0,0,0,0.35)'
  });

  const statusEl = document.createElement('div');
  statusEl.style.marginBottom = '8px';
  statusEl.style.whiteSpace = 'pre-wrap';

  const btn = document.createElement('button');
  btn.textContent = `Pick output folder & fetch ${TARGETS.length} file(s) (${Math.round(INTERVAL_MS / 1000)}s spacing)`;
  Object.assign(btn.style, {
    background: '#2563eb', color: '#ffffff', border: '0', borderRadius: '6px',
    padding: '8px 12px', cursor: 'pointer', fontWeight: '600'
  });

  if (window.location.origin !== EXPECTED_ORIGIN) {
    statusEl.textContent = `Wrong origin: open ${EXPECTED_ORIGIN} (currently ${window.location.origin}).`;
    btn.disabled = true;
    btn.style.opacity = '0.5';
  } else {
    statusEl.textContent = `Ready on ${EXPECTED_ORIGIN} for ${TARGETS.length} target(s).`;
  }

  panel.appendChild(statusEl);
  panel.appendChild(btn);
  document.body.appendChild(panel);

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function sha256Hex(buffer) {
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function writeTextFile(dirHandle, name, content) {
    const handle = await dirHandle.getFileHandle(name, { create: true });
    const writable = await handle.createWritable();
    await writable.write(content);
    await writable.close();
  }

  btn.addEventListener('click', async () => {
    if (window.location.origin !== EXPECTED_ORIGIN) return;
    if (typeof window.showDirectoryPicker !== 'function') {
      statusEl.textContent = 'File System Access API (window.showDirectoryPicker) is unavailable in this browser.';
      return;
    }
    btn.disabled = true;
    let dirHandle;
    try {
      dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
    } catch (err) {
      statusEl.textContent = `Folder selection canceled: ${err && err.message ? err.message : err}`;
      btn.disabled = false;
      return;
    }

    const lines = [];
    const errors = [];
    for (let i = 0; i < TARGETS.length; i++) {
      const target = TARGETS[i];
      if (i > 0) {
        statusEl.textContent = `Waiting ${Math.round(INTERVAL_MS / 1000)}s before [${i + 1}/${TARGETS.length}] ${target.case_id}...`;
        await sleep(INTERVAL_MS);
      }
      statusEl.textContent = `Fetching [${i + 1}/${TARGETS.length}] ${target.case_id}...`;
      let res;
      try {
        res = await fetch(target.fetch_url, { credentials: 'same-origin', redirect: 'follow' });
      } catch (err) {
        const msg = `Network error on ${target.case_id}: ${err && err.message ? err.message : err}`;
        errors.push({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg });
        await writeTextFile(dirHandle, 'browser-captures.errors.jsonl', errors.map((e) => JSON.stringify(e)).join('\n') + '\n');
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }

      const headers = {};
      for (const name of ALLOWED_HEADERS) {
        const v = res.headers.get(name);
        if (v !== null) headers[name] = v;
      }
      const cfMitigated = res.headers.get('cf-mitigated');
      const contentType = (headers['content-type'] || '').toLowerCase();

      if (res.status === 429 || res.status === 403 || cfMitigated || 'retry-after' in headers || res.status !== 200 || contentType.startsWith('text/html')) {
        const reason = `status=${res.status} cf=${cfMitigated || '-'} ct=${contentType || '-'}`;
        errors.push({ case_id: target.case_id, fetch_url: target.fetch_url, final_url: res.url, reason, headers });
        await writeTextFile(dirHandle, 'browser-captures.errors.jsonl', errors.map((e) => JSON.stringify(e)).join('\n') + '\n');
        statusEl.textContent = `STOPPED immediately (${reason}) on ${target.case_id}. Saved ${lines.length} prior capture(s).`;
        return;
      }

      const finalUrlObj = new URL(res.url);
      if (finalUrlObj.origin !== EXPECTED_ORIGIN) {
        const msg = `Cross-origin redirect to ${res.url}`;
        errors.push({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg });
        await writeTextFile(dirHandle, 'browser-captures.errors.jsonl', errors.map((e) => JSON.stringify(e)).join('\n') + '\n');
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }
      if (finalUrlObj.hostname === 'webarchive.loc.gov' && !LOC_REPLAY_RE.test(finalUrlObj.pathname)) {
        const msg = `Non-14-digit or non-id_ replay URL: ${res.url}`;
        errors.push({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg });
        await writeTextFile(dirHandle, 'browser-captures.errors.jsonl', errors.map((e) => JSON.stringify(e)).join('\n') + '\n');
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }

      const buf = await res.arrayBuffer();
      const head = new TextDecoder('ascii').decode(new Uint8Array(buf.slice(0, 16)));
      if (!head.includes('%PDF-')) {
        const msg = `Response is not a PDF (${buf.byteLength} bytes) for ${target.case_id}`;
        errors.push({ case_id: target.case_id, fetch_url: target.fetch_url, final_url: res.url, error: msg });
        await writeTextFile(dirHandle, 'browser-captures.errors.jsonl', errors.map((e) => JSON.stringify(e)).join('\n') + '\n');
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }

      const sha256 = await sha256Hex(buf);
      const pdfHandle = await dirHandle.getFileHandle(`${sha256}.pdf`, { create: true });
      const pdfWritable = await pdfHandle.createWritable();
      await pdfWritable.write(buf);
      await pdfWritable.close();

      lines.push(JSON.stringify({
        case_id: target.case_id,
        original_url: target.original_url,
        requested_url: target.fetch_url,
        final_url: res.url,
        http_status: res.status,
        retrieved_at: new Date().toISOString(),
        headers,
        sha256,
        bytes: buf.byteLength,
      }));
      await writeTextFile(dirHandle, 'browser-captures.jsonl', lines.join('\n') + '\n');
    }

    statusEl.textContent = `Done: saved ${lines.length}/${TARGETS.length} PDF(s) and browser-captures.jsonl.`;
  });
})();
"""


def _validate_target(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValueError("Target entry must be an object")
    required = ("case_id", "original_url", "fetch_url", "expected_origin")
    if any(not isinstance(item.get(k), str) or not item[k].strip() for k in required):
        raise ValueError("Target entry requires non-empty case_id, original_url, fetch_url, and expected_origin")
    fetch_parts = urlsplit(item["fetch_url"])
    origin_parts = urlsplit(item["expected_origin"])
    if fetch_parts.scheme not in {"http", "https"} or not fetch_parts.hostname:
        raise ValueError(f"Invalid fetch_url: {item['fetch_url']}")
    if origin_parts.scheme not in {"http", "https"} or not origin_parts.netloc or origin_parts.path not in {"", "/"}:
        raise ValueError(f"Invalid expected_origin: {item['expected_origin']}")
    if f"{fetch_parts.scheme}://{fetch_parts.netloc}" != f"{origin_parts.scheme}://{origin_parts.netloc}":
        raise ValueError(f"fetch_url origin differs from expected_origin: {item['fetch_url']}")
    orig_parts = urlsplit(item["original_url"])
    if orig_parts.scheme not in {"http", "https"} or not orig_parts.hostname:
        raise ValueError(f"Invalid original_url: {item['original_url']}")
    return {k: item[k].strip() for k in required}


def emit_snippet(targets_path: Path, out_path: Path, *, interval_seconds: float = 15.0) -> Path:
    """Validate targets JSON and emit a single-origin Chrome DevTools capture snippet."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    raw = json.loads(targets_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Targets JSON must be a non-empty array")
    targets = [_validate_target(item) for item in raw]
    origins = {t["expected_origin"] for t in targets}
    if len(origins) != 1:
        raise ValueError(f"All targets in one snippet must share expected_origin; got {sorted(origins)}")
    expected_origin = next(iter(origins))
    snippet = (
        _SNIPPET_TEMPLATE
        .replace("__TARGETS_JSON__", json.dumps(targets, indent=2))
        .replace("__EXPECTED_ORIGIN_JSON__", json.dumps(expected_origin))
        .replace("__INTERVAL_MS__", str(int(round(interval_seconds * 1000))))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(snippet, encoding="utf-8")
    return out_path


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"Duplicate capture record field: {k}")
        out[k] = v
    return out


def _validate_capture_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Capture final_url must be a non-empty string")
    checked = allowed_url(url)
    if checked is None:
        raise ValueError(f"Capture URL failed archive_links.allowed_url: {url}")
    parts = urlsplit(checked)
    host = (parts.hostname or "").lower()
    if host == "webarchive.loc.gov" and not LOC_REPLAY_ID_RE.fullmatch(parts.path):
        raise ValueError(f"webarchive.loc.gov URL must use 14-digit id_ replay path: {url}")
    if host in ARCHIVE_REPLAY_PATHS and "id_/" not in parts.path:
        raise ValueError(f"Archive replay URL must use raw id_ modifier: {url}")
    return checked


def ingest_captures(
    capture_dir: Path,
    output_dir: Path,
    *,
    writer_identity: dict[str, str],
    run_id: str = "browser-session-capture",
    write_date: str | None = None,
    damaged_manifest: Path | None = None,
    damaged_sources_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify captured browser PDFs, retain via ReceiptWriter, verify receipt_binding, and qualify."""
    manifest_path = capture_dir / "browser-captures.jsonl"
    if not manifest_path.is_file():
        raise ValueError(f"Missing browser capture manifest: {manifest_path}")
    raw_lines = [ln for ln in manifest_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not raw_lines:
        raise ValueError("Browser capture manifest is empty")

    damaged_by_case: dict[str, str] = {}
    if damaged_manifest is not None:
        with damaged_manifest.open(encoding="utf-8") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                damaged_by_case[row["case"]] = row["sha256"]

    output_dir.mkdir(parents=True, exist_ok=True)
    store = BodyStore(LocalAdapter(output_dir / "raw"))
    utc_date = write_date or datetime.now(timezone.utc).date().isoformat()
    writer = ReceiptWriter(
        store,
        identity=writer_identity,
        run_id=run_id,
        write_date=utc_date,
        archive_limits=None,
    )
    freeze_dir = output_dir / "frozen-receipts"
    qual_cache = output_dir / "qualification-cache"

    entries: list[dict[str, Any]] = []
    for idx, line_text in enumerate(raw_lines, 1):
        rec = json.loads(line_text, object_pairs_hook=_unique_object)
        validate_record(rec)
        for req in ("case_id", "original_url", "requested_url", "final_url", "retrieved_at", "sha256"):
            if not isinstance(rec.get(req), str) or not rec[req].strip():
                raise ValueError(f"Record {idx} missing required field {req}")
        if rec.get("http_status") != 200:
            raise ValueError(f"Record {rec['case_id']} requires http_status=200, got {rec.get('http_status')}")
        if type(rec.get("bytes")) is not int or rec["bytes"] <= 0:
            raise ValueError(f"Record {rec['case_id']} requires positive integer bytes")
        if not SHA256_RE.fullmatch(rec["sha256"]):
            raise ValueError(f"Record {rec['case_id']} has invalid sha256: {rec['sha256']}")

        headers = {str(k).lower(): str(v) for k, v in (rec.get("headers") or {}).items()}
        if "retry-after" in headers or "cf-mitigated" in headers:
            raise ValueError(f"Record {rec['case_id']} carries retry-after or cf-mitigated challenge header")

        final_url = _validate_capture_url(rec["final_url"])
        requested_url = rec["requested_url"]
        if allowed_url(requested_url) is None:
            # Allow 2011*/2011id_ shorthand only when requested_url was an explicit LoC year selector
            # that resolved to a canonical 14-digit final_url, as long as no secrets exist.
            req_parts = urlsplit(requested_url)
            if req_parts.scheme not in {"http", "https"} or req_parts.hostname != urlsplit(final_url).hostname:
                raise ValueError(f"Record {rec['case_id']} invalid requested_url: {requested_url}")

        pdf_path = capture_dir / f"{rec['sha256']}.pdf"
        verified = verify_local_file(pdf_path, expected_sha256=rec["sha256"], expected_size=rec["bytes"])
        media_type = headers.get("content-type", "application/pdf").split(";", 1)[0].strip().lower() or "application/pdf"

        op_id = hashlib.sha256(f"{rec['case_id']}|{final_url}|{verified.sha256}".encode()).hexdigest()[:24]
        attempt = FetchAttempt(
            requested_url=requested_url,
            url=final_url,
            retrieved_at=rec["retrieved_at"],
            transport=TRANSPORT_NAME,
            http_status=200,
            provider_status=None,
            headers=headers,
            redirects=(requested_url,) if requested_url != final_url else (),
            complete=True,
            body=BodyFile(verified.path, verified.sha256, verified.size_bytes, media_type, None, None, None),
        )
        observations = [
            {"source": TRANSPORT_NAME, "case_id": rec["case_id"], "original_url": rec["original_url"]}
        ]
        receipt_key, receipt_line = writer.write(
            FetchResult(final=attempt),
            family="documents",
            observations=observations,
            mode="fetch",
            operation_id=op_id,
            freeze_dir=freeze_dir,
        )
        receipt_binding(receipt_line, url=final_url, digest=verified.sha256, size=verified.size_bytes)

        _, qual_record = qualify_candidate_body(verified.path, qual_cache, expected_sha256=verified.sha256)
        qual_dict = dict(qual_record)
        prefix_info = None
        if damaged_sources_dir is not None and rec["case_id"] in damaged_by_case:
            orig_file = damaged_sources_dir / damaged_by_case[rec["case_id"]] / "original.bin"
            if orig_file.is_file():
                prefix_info = shared_prefix(orig_file.read_bytes(), verified.path.read_bytes())

        entries.append({
            "case_id": rec["case_id"],
            "original_url": rec["original_url"],
            "final_url": final_url,
            "sha256": verified.sha256,
            "bytes": verified.size_bytes,
            "receipt_key": receipt_key,
            "operation_id": op_id,
            "qualification_status": qual_dict["status"],
            "qualification_reason": qual_dict.get("reason"),
            "pages": qual_dict.get("pages"),
            "cutoff_size_hint": cutoff_size_hint(qual_dict),
            "shared_prefix": prefix_info,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "total": len(entries),
        "qualified": sum(1 for e in entries if e["qualification_status"] == "qualified"),
        "entries": entries,
    }
    (output_dir / "qualification-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_emit = sub.add_parser("emit-snippet", help="Generate a same-origin Chrome DevTools snippet")
    p_emit.add_argument("--targets", type=Path, required=True)
    p_emit.add_argument("--out", type=Path, required=True)
    p_emit.add_argument("--interval-seconds", type=float, default=15.0)

    p_ing = sub.add_parser("ingest", help="Verify and stage browser-captured PDFs into ReceiptWriter/LocalAdapter")
    p_ing.add_argument("--capture-dir", type=Path, required=True)
    p_ing.add_argument("--output", type=Path, required=True)
    p_ing.add_argument("--writer-identity", type=Path, required=True)
    p_ing.add_argument("--run-id", default="browser-session-capture")
    p_ing.add_argument("--write-date", default=None)
    p_ing.add_argument("--damaged-manifest", type=Path, default=None)
    p_ing.add_argument("--damaged-sources-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "emit-snippet":
        out = emit_snippet(args.targets, args.out, interval_seconds=args.interval_seconds)
        print(f"Wrote snippet to {out}")
        return 0
    identity = json.loads(args.writer_identity.read_text(encoding="utf-8"))
    report = ingest_captures(
        args.capture_dir,
        args.output,
        writer_identity=identity,
        run_id=args.run_id,
        write_date=args.write_date,
        damaged_manifest=args.damaged_manifest,
        damaged_sources_dir=args.damaged_sources_dir,
    )
    print(json.dumps({"total": report["total"], "qualified": report["qualified"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
