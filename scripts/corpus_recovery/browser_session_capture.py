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
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
from congress_api.parsers.archive_links import ARCHIVE_REPLAY_PATHS, allowed_url
from congress_api.parsers.document_links import binary_pdf_header
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_record
from congress_api.retention.provenance import instant, verify_local_file
from congress_api.retention.receipt_writer import ReceiptWriter
from corpus_recovery.acceptance import receipt_binding
from corpus_recovery.discovery import shared_prefix
from corpus_recovery.pipeline import cutoff_size_hint, qualify_candidate_body

LOC_REPLAY_ID_RE = re.compile(r"^/all/[0-9]{14}id_/(https?://.+)$")
LOC_REPLAY_LEGACY_SELECTOR_RE = re.compile(r"^/all/[0-9]{4,13}id_/(https?://.+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_PDF_MEDIA_TYPES = frozenset({"application/pdf", "application/octet-stream"})
TRANSPORT_NAME = "browser_same_origin"

_SNIPPET_TEMPLATE = r"""(() => {
  const TARGETS = __TARGETS_JSON__;
  const EXPECTED_ORIGIN = __EXPECTED_ORIGIN_JSON__;
  const INTERVAL_MS = __INTERVAL_MS__;
  const TIMEOUT_MS = __TIMEOUT_MS__;
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
    fontSize: '12px', maxWidth: '500px', boxShadow: '0 8px 24px rgba(0,0,0,0.35)'
  });

  const statusEl = document.createElement('div');
  statusEl.style.marginBottom = '8px';
  statusEl.style.whiteSpace = 'pre-wrap';

  const btnRow = document.createElement('div');
  btnRow.style.display = 'flex';
  btnRow.style.gap = '8px';
  btnRow.style.flexWrap = 'wrap';

  const pickBtn = document.createElement('button');
  pickBtn.id = 'ct-browser-pick-btn';
  pickBtn.textContent = '1. Pick output folder';
  Object.assign(pickBtn.style, {
    background: '#374151', color: '#ffffff', border: '0', borderRadius: '6px',
    padding: '8px 12px', cursor: 'pointer', fontWeight: '600'
  });

  const stepBtn = document.createElement('button');
  stepBtn.id = 'ct-browser-step-btn';
  stepBtn.textContent = '2. Capture next target (pick folder first)';
  stepBtn.disabled = true;
  Object.assign(stepBtn.style, {
    background: '#2563eb', color: '#ffffff', border: '0', borderRadius: '6px',
    padding: '8px 12px', cursor: 'pointer', fontWeight: '600', opacity: '0.5'
  });

  if (window.location.origin !== EXPECTED_ORIGIN) {
    statusEl.textContent = `Wrong origin: open ${EXPECTED_ORIGIN} (currently ${window.location.origin}).`;
    pickBtn.disabled = true;
    pickBtn.style.opacity = '0.5';
  } else {
    statusEl.textContent = `Ready on ${EXPECTED_ORIGIN} for ${TARGETS.length} target(s). Pick folder, then click once per target.`;
  }

  btnRow.appendChild(pickBtn);
  btnRow.appendChild(stepBtn);
  panel.appendChild(statusEl);
  panel.appendChild(btnRow);
  document.body.appendChild(panel);

  let dirHandle = null;
  let existingLines = [];
  let existingErrors = [];
  let capturedCaseIds = new Set();
  let nextIndex = 0;
  let cooldownUntil = 0;
  let captureInFlight = false;
  let folderPickInFlight = false;

  async function sha256Hex(buffer) {
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function readExistingLines(handle, name) {
    try {
      const fh = await handle.getFileHandle(name);
      const file = await fh.getFile();
      const text = await file.text();
      return text.split('\n').map((ln) => ln.trim()).filter(Boolean);
    } catch (err) {
      if (err && err.name === 'NotFoundError') return [];
      throw err;
    }
  }

  async function writeTextFile(handle, name, content) {
    const fh = await handle.getFileHandle(name, { create: true });
    const writable = await fh.createWritable();
    await writable.write(content);
    await writable.close();
  }

  async function persistManifest(targetDir = dirHandle) {
    await writeTextFile(targetDir, 'browser-captures.jsonl', existingLines.join('\n') + '\n');
  }

  async function persistErrors(targetDir = dirHandle) {
    await writeTextFile(targetDir, 'browser-captures.errors.jsonl', existingErrors.join('\n') + '\n');
  }

  function advanceToNextUncaptured() {
    while (nextIndex < TARGETS.length && capturedCaseIds.has(TARGETS[nextIndex].case_id)) {
      nextIndex += 1;
    }
  }

  function refreshStepButton() {
    advanceToNextUncaptured();
    if (captureInFlight || folderPickInFlight) {
      stepBtn.disabled = true;
      stepBtn.style.opacity = '0.5';
      return;
    }
    if (!dirHandle || window.location.origin !== EXPECTED_ORIGIN) {
      stepBtn.disabled = true;
      stepBtn.style.opacity = '0.5';
      stepBtn.textContent = '2. Capture next target (pick folder first)';
      return;
    }
    if (nextIndex >= TARGETS.length) {
      stepBtn.disabled = true;
      stepBtn.style.opacity = '0.5';
      stepBtn.textContent = `Done (${capturedCaseIds.size}/${TARGETS.length} captured)`;
      return;
    }
    const target = TARGETS[nextIndex];
    const remainingMs = Math.max(0, cooldownUntil - Date.now());
    if (remainingMs > 0) {
      stepBtn.disabled = true;
      stepBtn.style.opacity = '0.5';
      stepBtn.textContent = `Wait ${Math.ceil(remainingMs / 1000)}s before [${nextIndex + 1}/${TARGETS.length}] ${target.case_id}`;
      setTimeout(refreshStepButton, Math.min(remainingMs, 1000));
      return;
    }
    stepBtn.disabled = false;
    stepBtn.style.opacity = '1';
    stepBtn.textContent = `2. Capture [${nextIndex + 1}/${TARGETS.length}] ${target.case_id}`;
  }

  function hasValidPdfHeader(buf) {
    const bytes = new Uint8Array(buf.slice(0, 1024));
    const head = new TextDecoder('latin1').decode(bytes);
    const trimmed = head.replace(/^(?:\u00ef\u00bb\u00bf|[ \t\r\n])+/, '');
    if (trimmed.startsWith('%PDF-')) return true;
    const m = /%PDF-[12]\.\d(?:\r|\n)/.exec(head);
    if (!m || m.index === 0) return false;
    const preamble = bytes.subarray(0, m.index);
    let hasBinary = false;
    for (let i = 0; i < preamble.length; i++) {
      if (preamble[i] === 0x3c) return false; // '<' markup forbidden before %PDF-
      if (preamble[i] >= 128 || preamble[i] < 9) hasBinary = true;
    }
    return hasBinary;
  }

  function arrayBufferWithAbort(res, signal) {
    if (signal.aborted) {
      return Promise.reject(signal.reason || new Error('Aborted before body read'));
    }
    return new Promise((resolve, reject) => {
      const onAbort = () => reject(signal.reason || new Error('Body read timed out'));
      signal.addEventListener('abort', onAbort, { once: true });
      res.arrayBuffer().then(
        (buf) => {
          signal.removeEventListener('abort', onAbort);
          resolve(buf);
        },
        (err) => {
          signal.removeEventListener('abort', onAbort);
          reject(err);
        }
      );
    });
  }

  pickBtn.addEventListener('click', async () => {
    if (captureInFlight || folderPickInFlight || window.location.origin !== EXPECTED_ORIGIN) return;
    if (typeof window.showDirectoryPicker !== 'function') {
      statusEl.textContent = 'File System Access API (window.showDirectoryPicker) is unavailable in this browser.';
      return;
    }
    folderPickInFlight = true;
    pickBtn.disabled = true;
    pickBtn.style.opacity = '0.5';
    stepBtn.disabled = true;
    stepBtn.style.opacity = '0.5';

    try {
      let nextHandle;
      try {
        nextHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
      } catch (err) {
        statusEl.textContent = `Folder selection canceled: ${err && err.message ? err.message : err}`;
        return;
      }
      if (captureInFlight) return;

      // Read proposed folder into temporaries FIRST; if reading fails, clear active folder so
      // neither the previous folder nor the new folder can ever be overwritten with stale state.
      try {
        const nextLines = await readExistingLines(nextHandle, 'browser-captures.jsonl');
        const nextErrors = await readExistingLines(nextHandle, 'browser-captures.errors.jsonl');
        const nextCaptured = new Set();
        for (const ln of nextLines) {
          const parsed = JSON.parse(ln);
          if (!parsed || typeof parsed.case_id !== 'string' || !parsed.case_id.trim()) {
            throw new Error('Malformed existing browser-captures.jsonl row');
          }
          nextCaptured.add(parsed.case_id);
        }
        if (captureInFlight) return;
        dirHandle = nextHandle;
        existingLines = nextLines;
        existingErrors = nextErrors;
        capturedCaseIds = nextCaptured;
        nextIndex = 0;
        advanceToNextUncaptured();
        const previewTarget = nextIndex < TARGETS.length ? `\nNext URL: ${TARGETS[nextIndex].fetch_url}` : '';
        statusEl.textContent = `Folder ready (${existingLines.length} prior capture(s) preserved).${previewTarget}`;
      } catch (err) {
        if (captureInFlight) return;
        dirHandle = null;
        existingLines = [];
        existingErrors = [];
        capturedCaseIds = new Set();
        nextIndex = 0;
        statusEl.textContent = `Failed to read existing manifest in selected folder (capture disabled): ${err && err.message ? err.message : err}`;
      }
    } finally {
      folderPickInFlight = false;
      if (!captureInFlight && window.location.origin === EXPECTED_ORIGIN) {
        pickBtn.disabled = false;
        pickBtn.style.opacity = '1';
      }
      refreshStepButton();
    }
  });

  stepBtn.addEventListener('click', async () => {
    if (captureInFlight || folderPickInFlight || !dirHandle || window.location.origin !== EXPECTED_ORIGIN) return;
    advanceToNextUncaptured();
    if (nextIndex >= TARGETS.length) {
      refreshStepButton();
      return;
    }
    const target = TARGETS[nextIndex];
    const activeDir = dirHandle;
    let captureSucceeded = false;
    captureInFlight = true;
    pickBtn.disabled = true;
    pickBtn.style.opacity = '0.5';
    stepBtn.disabled = true;
    stepBtn.style.opacity = '0.5';
    statusEl.textContent = `Fetching [${nextIndex + 1}/${TARGETS.length}] ${target.case_id}...\n${target.fetch_url}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error(`Timeout after ${TIMEOUT_MS}ms`)), TIMEOUT_MS);
    try {
      const res = await fetch(target.fetch_url, {
        credentials: 'same-origin',
        redirect: 'manual',
        signal: controller.signal
      });

      if (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) {
        const loc = res.headers ? res.headers.get('location') : null;
        const msg = `Redirect refused under redirect:'manual' (type=${res.type}, status=${res.status}, location=${loc || 'opaque'}). Supply a resolved canonical 14-digit URL on ${EXPECTED_ORIGIN}.`;
        existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg, at: new Date().toISOString() }));
        await persistErrors(activeDir);
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

      if (
        res.status !== 200 ||
        cfMitigated ||
        'retry-after' in headers ||
        'content-range' in headers ||
        contentType.startsWith('text/html')
      ) {
        const reason = `status=${res.status} cf=${cfMitigated || '-'} ct=${contentType || '-'} range=${headers['content-range'] || '-'}`;
        existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, final_url: res.url, reason, headers, at: new Date().toISOString() }));
        await persistErrors(activeDir);
        statusEl.textContent = `STOPPED (${reason}) on ${target.case_id}. ${existingLines.length} prior capture(s) preserved.`;
        return;
      }

      const finalUrlObj = new URL(res.url);
      if (finalUrlObj.origin !== EXPECTED_ORIGIN) {
        const msg = `Cross-origin response URL refused: ${res.url}`;
        existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg, at: new Date().toISOString() }));
        await persistErrors(activeDir);
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }
      if (finalUrlObj.hostname === 'webarchive.loc.gov' && !LOC_REPLAY_RE.test(finalUrlObj.pathname)) {
        const msg = `Non-14-digit or non-id_ replay URL refused: ${res.url}`;
        existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg, at: new Date().toISOString() }));
        await persistErrors(activeDir);
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }

      const buf = await arrayBufferWithAbort(res, controller.signal);
      if (!hasValidPdfHeader(buf)) {
        const msg = `Response is not a PDF (${buf.byteLength} bytes) for ${target.case_id}`;
        existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, final_url: res.url, error: msg, at: new Date().toISOString() }));
        await persistErrors(activeDir);
        statusEl.textContent = `STOPPED: ${msg}`;
        return;
      }

      const sha256 = await sha256Hex(buf);
      const pdfHandle = await activeDir.getFileHandle(`${sha256}.pdf`, { create: true });
      const pdfWritable = await pdfHandle.createWritable();
      await pdfWritable.write(buf);
      await pdfWritable.close();

      existingLines.push(JSON.stringify({
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
      await persistManifest(activeDir);
      capturedCaseIds.add(target.case_id);
      nextIndex += 1;
      cooldownUntil = Date.now() + INTERVAL_MS;
      advanceToNextUncaptured();
      const nextNote = nextIndex < TARGETS.length
        ? `\nNext (${Math.round(INTERVAL_MS / 1000)}s cooldown): ${TARGETS[nextIndex].case_id}\n${TARGETS[nextIndex].fetch_url}`
        : '\nAll targets captured.';
      statusEl.textContent = `Saved ${target.case_id} (${buf.byteLength} bytes, ${sha256.slice(0, 12)}). Total: ${capturedCaseIds.size}/${TARGETS.length}.${nextNote}`;
      captureSucceeded = true;
    } catch (err) {
      const msg = `Capture failed on ${target.case_id}: ${err && err.message ? err.message : err}`;
      existingErrors.push(JSON.stringify({ case_id: target.case_id, fetch_url: target.fetch_url, error: msg, at: new Date().toISOString() }));
      await persistErrors(activeDir);
      statusEl.textContent = `STOPPED: ${msg}`;
    } finally {
      clearTimeout(timer);
      captureInFlight = false;
      if (window.location.origin === EXPECTED_ORIGIN) {
        pickBtn.disabled = false;
        pickBtn.style.opacity = '1';
      }
      if (captureSucceeded) {
        refreshStepButton();
      }
    }
  });
})();
"""


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _validate_target(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValueError("Target entry must be an object")
    required = ("case_id", "original_url", "fetch_url", "expected_origin")
    if any(not isinstance(item.get(k), str) or not item[k].strip() for k in required):
        raise ValueError(
            "Target entry requires non-empty case_id, original_url, fetch_url, and expected_origin"
        )
    fetch_url = item["fetch_url"].strip()
    expected_origin = item["expected_origin"].strip()
    original_url = item["original_url"].strip()
    fetch_parts = urlsplit(fetch_url)
    origin_parts = urlsplit(expected_origin)
    if fetch_parts.scheme not in {"http", "https"} or not fetch_parts.hostname:
        raise ValueError(f"Invalid fetch_url: {fetch_url}")
    if origin_parts.scheme not in {"http", "https"} or not origin_parts.netloc or origin_parts.path not in {"", "/"}:
        raise ValueError(f"Invalid expected_origin: {expected_origin}")
    if f"{fetch_parts.scheme}://{fetch_parts.netloc}" != f"{origin_parts.scheme}://{origin_parts.netloc}":
        raise ValueError(f"fetch_url origin differs from expected_origin: {fetch_url}")
    if (fetch_parts.hostname or "").lower() == "webarchive.loc.gov" and not LOC_REPLAY_ID_RE.fullmatch(fetch_parts.path):
        raise ValueError(
            f"webarchive.loc.gov fetch_url must be a resolved 14-digit id_ replay URL "
            f"(/all/YYYYMMDDHHMMSSid_/http...); resolve the exact timestamp from "
            f"https://webarchive.loc.gov/all/*/{original_url} in your browser first: {fetch_url}"
        )
    if allowed_url(fetch_url) is None:
        raise ValueError(f"Target fetch_url failed archive_links.allowed_url: {fetch_url}")
    orig_parts = urlsplit(original_url)
    if orig_parts.scheme not in {"http", "https"} or not orig_parts.hostname:
        raise ValueError(f"Invalid original_url: {original_url}")
    return {
        "case_id": item["case_id"].strip(),
        "original_url": original_url,
        "fetch_url": fetch_url,
        "expected_origin": expected_origin,
    }


def _load_validated_targets(targets_path: Path) -> list[dict[str, str]]:
    if not targets_path.is_file():
        raise FileNotFoundError(f"Missing targets file: {targets_path}")
    raw = json.loads(targets_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Targets JSON must be a non-empty array")
    targets = [_validate_target(item) for item in raw]
    seen_cases: set[str] = set()
    for t in targets:
        if t["case_id"] in seen_cases:
            raise ValueError(f"Duplicate case_id in targets JSON: {t['case_id']}")
        seen_cases.add(t["case_id"])
    return targets


def emit_snippet(
    targets_path: Path,
    out_path: Path,
    *,
    interval_seconds: float = 15.0,
    timeout_seconds: float = 60.0,
) -> Path:
    """Validate targets JSON and emit a single-origin, single-target-per-click Chrome DevTools snippet."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    targets = _load_validated_targets(targets_path)
    origins = {t["expected_origin"] for t in targets}
    if len(origins) != 1:
        raise ValueError(f"All targets in one snippet must share expected_origin; got {sorted(origins)}")
    expected_origin = next(iter(origins))
    snippet = (
        _SNIPPET_TEMPLATE
        .replace("__TARGETS_JSON__", json.dumps(targets, indent=2))
        .replace("__EXPECTED_ORIGIN_JSON__", json.dumps(expected_origin))
        .replace("__INTERVAL_MS__", str(int(round(interval_seconds * 1000))))
        .replace("__TIMEOUT_MS__", str(int(round(timeout_seconds * 1000))))
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


def _validate_requested_url(requested_url: str, final_url: str, case_id: str) -> str:
    req_parts = urlsplit(requested_url)
    fin_parts = urlsplit(final_url)
    if (req_parts.scheme, req_parts.netloc) != (fin_parts.scheme, fin_parts.netloc):
        raise ValueError(f"Record {case_id} requested_url origin differs from final_url: {requested_url}")
    if req_parts.username is not None or req_parts.password is not None or req_parts.fragment:
        raise ValueError(f"Record {case_id} requested_url carries credentials or fragment: {requested_url}")
    if requested_url == final_url:
        return requested_url
    # Allow explicit unresolved (<14-digit) LoC selector shorthand ONLY when embedded original URL
    # (including full query string) matches final_url; resolved 14-digit URLs require exact equality.
    if (req_parts.hostname or "").lower() == "webarchive.loc.gov":
        req_full = req_parts.path + (f"?{req_parts.query}" if req_parts.query else "")
        fin_full = fin_parts.path + (f"?{fin_parts.query}" if fin_parts.query else "")
        req_m = LOC_REPLAY_LEGACY_SELECTOR_RE.fullmatch(req_full)
        fin_m = LOC_REPLAY_ID_RE.fullmatch(fin_full)
        if req_m and fin_m and req_m.group(1) == fin_m.group(1):
            return requested_url
    raise ValueError(
        f"Record {case_id} requested_url does not match final_url target ({requested_url!r} vs {final_url!r})"
    )


def _validate_utc_retrieved_at(raw_ts: str, case_id: str) -> str:
    trimmed = raw_ts.strip()
    if not trimmed.endswith(("Z", "+00:00")):
        raise ValueError(
            f"Record {case_id} retrieved_at must be an explicit UTC timestamp ending in 'Z' or '+00:00': {raw_ts!r}"
        )
    dt = instant(trimmed)
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"Record {case_id} retrieved_at has non-zero UTC offset: {raw_ts!r}")
    return dt.astimezone(timezone.utc).isoformat()


def _has_valid_pdf_header(head: bytes) -> bool:
    return head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF-") or binary_pdf_header(head)


def _load_damaged_manifest(damaged_manifest: Path) -> dict[str, str]:
    if not damaged_manifest.is_file():
        raise FileNotFoundError(f"Missing damaged_manifest: {damaged_manifest}")
    damaged_by_case: dict[str, str] = {}
    with damaged_manifest.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            case_id = (row.get("case") or "").strip()
            digest = (row.get("sha256") or "").strip()
            if not case_id or not SHA256_RE.fullmatch(digest):
                raise ValueError(f"Invalid damaged_manifest entry for case {case_id!r}: sha256={digest!r}")
            damaged_by_case[case_id] = digest
    return damaged_by_case


def _resolve_damaged_original(damaged_sources_dir: Path, digest: str) -> Path:
    if not SHA256_RE.fullmatch(digest):
        raise ValueError(f"Invalid damaged source sha256: {digest!r}")
    root = damaged_sources_dir.resolve()
    orig_file = (root / digest / "original.bin").resolve()
    if not orig_file.is_relative_to(root):
        raise ValueError(f"Damaged source path escapes damaged_sources_dir: {orig_file}")
    return orig_file


def ingest_captures(
    capture_dir: Path,
    output_dir: Path,
    *,
    writer_identity: dict[str, str],
    run_id: str = "browser-session-capture",
    write_date: str | None = None,
    damaged_manifest: Path | None = None,
    damaged_sources_dir: Path | None = None,
    targets_path: Path | None = None,
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
        damaged_by_case = _load_damaged_manifest(damaged_manifest)

    trusted_targets: dict[str, dict[str, str]] | None = None
    if targets_path is not None:
        trusted_targets = {t["case_id"]: t for t in _load_validated_targets(targets_path)}

    # Pass 1: Preflight every manifest row & local PDF before creating/freezing any receipt.
    preflight: list[dict[str, Any]] = []
    for idx, line_text in enumerate(raw_lines, 1):
        rec = json.loads(line_text, object_pairs_hook=_unique_object)
        validate_record(rec)
        for req in ("case_id", "original_url", "requested_url", "final_url", "retrieved_at", "sha256"):
            if not isinstance(rec.get(req), str) or not rec[req].strip():
                raise ValueError(f"Record {idx} missing required field {req}")
        case_id = rec["case_id"].strip()
        normalized_retrieved_at = _validate_utc_retrieved_at(rec["retrieved_at"], case_id)

        if rec.get("http_status") != 200:
            raise ValueError(f"Record {case_id} requires http_status=200, got {rec.get('http_status')}")
        if type(rec.get("bytes")) is not int or rec["bytes"] <= 0:
            raise ValueError(f"Record {case_id} requires positive integer bytes")
        if not SHA256_RE.fullmatch(rec["sha256"]):
            raise ValueError(f"Record {case_id} has invalid sha256: {rec['sha256']}")

        raw_headers = rec.get("headers")
        if raw_headers is not None and not isinstance(raw_headers, dict):
            raise ValueError(f"Record {case_id} headers must be an object")
        headers = {str(k).lower(): str(v) for k, v in (raw_headers or {}).items()}
        if "retry-after" in headers or "cf-mitigated" in headers:
            raise ValueError(f"Record {case_id} carries retry-after or cf-mitigated challenge header")
        if "content-range" in headers:
            raise ValueError(f"Record {case_id} carries content-range header (partial transfer refused)")

        final_url = _validate_capture_url(rec["final_url"].strip())
        requested_url = _validate_requested_url(rec["requested_url"].strip(), final_url, case_id)
        original_url = rec["original_url"].strip()

        if trusted_targets is not None:
            if case_id not in trusted_targets:
                raise ValueError(f"Record {case_id} is not present in trusted --targets")
            target = trusted_targets[case_id]
            if original_url != target["original_url"]:
                raise ValueError(
                    f"Record {case_id} original_url {original_url!r} does not match trusted target {target['original_url']!r}"
                )
            if requested_url != target["fetch_url"] or final_url != target["fetch_url"]:
                raise ValueError(
                    f"Record {case_id} URL ({requested_url!r} -> {final_url!r}) does not match trusted target {target['fetch_url']!r}"
                )

        media_type = headers.get("content-type", "application/pdf").split(";", 1)[0].strip().lower() or "application/pdf"
        if media_type not in ALLOWED_PDF_MEDIA_TYPES:
            raise ValueError(f"Record {case_id} refused non-PDF content-type: {media_type!r}")

        pdf_path = capture_dir / f"{rec['sha256']}.pdf"
        verified = verify_local_file(pdf_path, expected_sha256=rec["sha256"], expected_size=rec["bytes"])
        with verified.path.open("rb") as stream:
            head = stream.read(1024)
        if not _has_valid_pdf_header(head):
            raise ValueError(f"Record {case_id} body is not a valid PDF (failed leading %PDF- header check)")

        preflight.append({
            "case_id": case_id,
            "original_url": original_url,
            "retrieved_at": normalized_retrieved_at,
            "headers": headers,
            "final_url": final_url,
            "requested_url": requested_url,
            "media_type": media_type,
            "verified": verified,
        })

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
    for item in preflight:
        case_id = item["case_id"]
        original_url = item["original_url"]
        retrieved_at = item["retrieved_at"]
        headers = item["headers"]
        final_url = item["final_url"]
        requested_url = item["requested_url"]
        media_type = item["media_type"]
        verified = item["verified"]

        op_id = hashlib.sha256(f"{case_id}|{final_url}|{verified.sha256}".encode()).hexdigest()[:24]
        attempt = FetchAttempt(
            requested_url=requested_url,
            url=final_url,
            retrieved_at=retrieved_at,
            transport=TRANSPORT_NAME,
            http_status=200,
            provider_status=None,
            headers=headers,
            redirects=(requested_url,) if requested_url != final_url else (),
            complete=True,
            body=BodyFile(verified.path, verified.sha256, verified.size_bytes, media_type, None, None, None),
        )
        observations = [
            {"source": TRANSPORT_NAME, "case_id": case_id, "original_url": original_url}
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
        qual_media_type = qual_dict.get("media_type")
        is_qualified_pdf = (qual_dict.get("status") == "qualified" and qual_media_type == "application/pdf")
        effective_status = "qualified" if is_qualified_pdf else "unresolved"
        effective_reason = (
            qual_dict.get("reason")
            if qual_media_type == "application/pdf"
            else f"non_pdf_qualification:{qual_media_type}"
        )

        prefix_info = None
        if damaged_sources_dir is not None and case_id in damaged_by_case:
            orig_file = _resolve_damaged_original(damaged_sources_dir, damaged_by_case[case_id])
            if orig_file.is_file():
                prefix_info = shared_prefix(orig_file.read_bytes(), verified.path.read_bytes())

        entries.append({
            "case_id": case_id,
            "original_url": original_url,
            "final_url": final_url,
            "sha256": verified.sha256,
            "bytes": verified.size_bytes,
            "receipt_key": receipt_key,
            "operation_id": op_id,
            "media_type": qual_media_type,
            "qualification_status": effective_status,
            "qualification_reason": effective_reason,
            "pages": qual_dict.get("pages"),
            "cutoff_size_hint": cutoff_size_hint(qual_dict),
            "shared_prefix": prefix_info,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "total": len(entries),
        "qualified": sum(
            1 for e in entries if e["qualification_status"] == "qualified" and e["media_type"] == "application/pdf"
        ),
        "entries": entries,
    }
    _write_json_atomic(output_dir / "qualification-report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_emit = sub.add_parser("emit-snippet", help="Generate a same-origin single-target-per-click Chrome DevTools snippet")
    p_emit.add_argument("--targets", type=Path, required=True)
    p_emit.add_argument("--out", type=Path, required=True)
    p_emit.add_argument("--interval-seconds", type=float, default=15.0)
    p_emit.add_argument("--timeout-seconds", type=float, default=60.0)

    p_ing = sub.add_parser("ingest", help="Verify and stage browser-captured PDFs into ReceiptWriter/LocalAdapter")
    p_ing.add_argument("--capture-dir", type=Path, required=True)
    p_ing.add_argument("--output", type=Path, required=True)
    p_ing.add_argument("--writer-identity", type=Path, required=True)
    p_ing.add_argument("--run-id", default="browser-session-capture")
    p_ing.add_argument("--write-date", default=None)
    p_ing.add_argument("--damaged-manifest", type=Path, default=None)
    p_ing.add_argument("--damaged-sources-dir", type=Path, default=None)
    p_ing.add_argument("--targets", type=Path, default=None, help="Optional trusted targets JSON to bind case_id/URLs")

    args = parser.parse_args(argv)
    if args.command == "emit-snippet":
        out = emit_snippet(
            args.targets,
            args.out,
            interval_seconds=args.interval_seconds,
            timeout_seconds=args.timeout_seconds,
        )
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
        targets_path=args.targets,
    )
    print(json.dumps({"total": report["total"], "qualified": report["qualified"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
