#!/usr/bin/env python3
"""Bounded `fast-ocr` archive rescue (`ct-o7ew`) for vector-outlined & low-text PDFs.

Subcommands cleanly separate environments per AGENTS.md:
- `build-targets` & `package-and-validate` run in `congressional-tech/.venv/bin/python`
  (requires `duckdb` and `pyarrow`).
- `run-ocr` runs in `/Users/mikewolfd/Work/fast-silicon/.venv/bin/python`
  (uses only Python stdlib + `pypdfium2` + `fast_ocr`).
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import time
from typing import Any, Callable, Final
import urllib.error
import urllib.request
import zlib

DEFAULT_ORIGIN: Final[str] = "https://congressional-data.spicygov.ai"
MAX_RESCUED_TEXT_CHARS: Final[int] = 25_000
PREFETCH_MAX_BYTES: Final[int] = 50_000_000
CHUNK_BYTES: Final[int] = 256 * 1024

SENTINEL_PREFIXES: Final[tuple[str, ...]] = (
    "559314189628",  # LOC_Modernization_Oversight.pdf
    "d78dcdd75e9a",  # Nomination_Hearing_GPO.pdf
    "21034e186187",  # Official Hearing Transcript_9.21.2023.pdf
    "bf0ab631d968",  # Testimony_Cole_05.04.2023.pdf
    "455febeab7a7",  # HHRG-114-WM03-Transcript-20150715.pdf
    "ae8b6afb9e55",  # HHRG-114-IF03-20151007-SD022.pdf
    "2c4ec309eab7",  # HMKP-116-JU00-20191211-SD1306.pdf
    "04932d9232ed",  # frpp_facility_assets_chart_2017_data_for_roundtable_1.pdf
)


def default_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[2]
    cache = root / ".cache" / "archive-release"
    return {
        "out_dir": cache / "docmeta-v7-ocr-rescue",
        "detail": cache / "publish-44901822543" / "base-release" / "detail.parquet",
        "det": cache / "docmeta-v6-20261116" / "parquets_v6_2" / "deterministic_323k_v6_2.parquet",
        "llm_queue": cache / "docmeta-v6-20261116" / "parquets_v6_2" / "llm_queue_v6_2.parquet",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def build_targets(
    *,
    out_dir: Path,
    detail_path: Path,
    det_path: Path,
    llm_queue_path: Path,
) -> dict[str, Any]:
    """Build deduplicated per-SHA target manifest for `ct-o7ew`."""
    import duckdb

    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    con.execute("SET memory_limit='2GB';")
    con.execute("SET threads=2;")

    sentinel_sql_list = ", ".join(f"'{p}'" for p in SENTINEL_PREFIXES)
    det_q = str(det_path).replace("'", "''")
    lq_q = str(llm_queue_path).replace("'", "''")
    detail_q = str(detail_path).replace("'", "''")

    sql = f"""
    WITH ocr_un AS (
        SELECT
            lower(hex(d.saved_body)) AS sha,
            coalesce(d.saved_suffix, '.gz') AS saved_suffix,
            lower(hex(d.link_key)) AS link_key_hex,
            det.doc_key,
            det.filename,
            d.saved_bytes,
            det.deterministic_status AS orig_status,
            0::BIGINT AS orig_chars,
            'ocr_unreadable' AS cohort
        FROM read_parquet('{det_q}') det
        JOIN read_parquet('{detail_q}') d ON d.link_key = det.link_key
        WHERE det.deterministic_status = 'ocr_unreadable'
          AND d.saved_bytes >= 300000
          AND lower(coalesce(det.effective_format, '')) = 'pdf'
    ),
    lq_short AS (
        SELECT
            lower(hex(d.saved_body)) AS sha,
            coalesce(d.saved_suffix, '.gz') AS saved_suffix,
            lower(hex(d.link_key)) AS link_key_hex,
            q.doc_key,
            q.filename,
            d.saved_bytes,
            'queued_llm_lt400' AS orig_status,
            length(trim(coalesce(nullif(trim(q.p12_clean_text), ''), q.p12_raw_text, '')))::BIGINT AS orig_chars,
            'llm_queue_lt400' AS cohort
        FROM read_parquet('{lq_q}') q
        JOIN read_parquet('{detail_q}') d ON d.link_key = q.link_key
        WHERE d.saved_bytes >= 300000
          AND lower(coalesce(q.effective_format, '')) = 'pdf'
          AND length(trim(coalesce(nullif(trim(q.p12_clean_text), ''), q.p12_raw_text, ''))) < 400
    ),
    sentinels AS (
        SELECT
            lower(hex(d.saved_body)) AS sha,
            coalesce(d.saved_suffix, '.gz') AS saved_suffix,
            lower(hex(d.link_key)) AS link_key_hex,
            det.doc_key,
            det.filename,
            d.saved_bytes,
            coalesce(det.deterministic_status, 'sentinel') AS orig_status,
            length(trim(coalesce(nullif(trim(q.p12_clean_text), ''), q.p12_raw_text, '')))::BIGINT AS orig_chars,
            'sentinel' AS cohort
        FROM read_parquet('{det_q}') det
        JOIN read_parquet('{detail_q}') d ON d.link_key = det.link_key
        LEFT JOIN read_parquet('{lq_q}') q ON q.link_key = det.link_key
        WHERE substr(det.doc_key, 1, 12) IN ({sentinel_sql_list})
    )
    SELECT sha, saved_suffix, link_key_hex, doc_key, filename, saved_bytes, orig_status, orig_chars, cohort
    FROM (
        SELECT * FROM ocr_un
        UNION ALL
        SELECT * FROM lq_short
        UNION ALL
        SELECT * FROM sentinels
    )
    """
    raw_rows = con.execute(sql).fetchall()
    con.close()

    by_sha: dict[str, dict[str, Any]] = {}
    for sha, saved_suffix, lk_hex, dk, fname, sbytes, orig_st, orig_ch, cohort in raw_rows:
        rec = by_sha.get(sha)
        is_sent = str(dk).startswith(SENTINEL_PREFIXES) or cohort == "sentinel"
        if rec is None:
            by_sha[sha] = {
                "saved_body_hex": sha,
                "saved_suffix": str(saved_suffix if saved_suffix is not None else ".gz"),
                "saved_bytes": int(sbytes),
                "doc_key": str(dk),
                "doc_keys": [str(dk)],
                "link_keys": [str(lk_hex)],
                "filename": str(fname or ""),
                "orig_status": str(orig_st or ""),
                "orig_chars": int(orig_ch or 0),
                "cohorts": [str(cohort)],
                "is_sentinel": bool(is_sent),
            }
        else:
            if str(dk) not in rec["doc_keys"]:
                rec["doc_keys"].append(str(dk))
            if str(lk_hex) not in rec["link_keys"]:
                rec["link_keys"].append(str(lk_hex))
            if str(cohort) not in rec["cohorts"]:
                rec["cohorts"].append(str(cohort))
            if is_sent and not rec["is_sentinel"]:
                rec["is_sentinel"] = True
                rec["doc_key"] = str(dk)
                rec["filename"] = str(fname or rec["filename"])
            if cohort != "sentinel" and rec["orig_status"] == "sentinel":
                rec["orig_status"] = str(orig_st or rec["orig_status"])
            if int(orig_ch or 0) > 0 and rec["orig_chars"] == 0:
                rec["orig_chars"] = int(orig_ch)

    targets = sorted(
        by_sha.values(),
        key=lambda r: (not bool(r["is_sentinel"]), int(r["saved_bytes"]), str(r["saved_body_hex"])),
    )
    targets_path = out_dir / "targets.jsonl"
    _atomic_write_text(
        targets_path,
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in targets),
    )

    cohort_counts = Counter(c for r in targets for c in r["cohorts"])
    summary = {
        "targets_path": str(targets_path),
        "unique_shas": len(targets),
        "sentinels": sum(1 for r in targets if r["is_sentinel"]),
        "total_mb": round(sum(r["saved_bytes"] for r in targets) / 1e6, 2),
        "cohort_counts": dict(sorted(cohort_counts.items())),
    }
    print(json.dumps(summary, indent=2))
    return summary


def index_local_cache(cache_dir: Path | None) -> dict[str, Path]:
    """Map SHA-256 hex digest -> local PDF path to reuse cached downloads."""
    mapping: dict[str, Path] = {}
    if cache_dir is None or not cache_dir.is_dir():
        return mapping
    for pdf_path in sorted(cache_dir.glob("*.pdf")):
        if pdf_path.is_file():
            mapping[_sha256_file(pdf_path)] = pdf_path
    return mapping


def stream_download_verified_pdf(
    sha_hex: str,
    dst_path: Path,
    *,
    origin: str = DEFAULT_ORIGIN,
    saved_suffix: str | None = None,
    timeout_s: float = 60.0,
    retries: int = 2,
    opener: Callable[..., Any] | None = None,
) -> tuple[str, int, str | None]:
    """Stream body from R2 (`<sha>.gz` or suffix-less `<sha>`), gunzip if gzipped, and verify SHA-256."""
    open_fn = opener or urllib.request.urlopen
    suffix_candidates = (saved_suffix,) if saved_suffix is not None else (".gz", "")
    last_err: str | None = None

    for suffix_idx, suffix in enumerate(suffix_candidates):
        url = f"{origin.rstrip('/')}/bodies/sha256/{sha_hex[:2]}/{sha_hex}{suffix}"
        for attempt in range(retries + 1):
            dst_path.unlink(missing_ok=True)
            hasher = hashlib.sha256()
            total_out = 0
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "docmeta-ct-o7ew-rescue/1.0"})
                with open_fn(req, timeout=timeout_s) as resp, dst_path.open("wb") as out_fh:
                    headers = getattr(resp, "headers", None)
                    content_encoding = str(headers.get("Content-Encoding") or "").lower() if headers is not None else ""
                    use_gzip = (suffix == ".gz") or ("gzip" in content_encoding)
                    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS) if use_gzip else None
                    while raw := resp.read(CHUNK_BYTES):
                        out_bytes = decomp.decompress(raw) if decomp is not None else raw
                        if out_bytes:
                            hasher.update(out_bytes)
                            out_fh.write(out_bytes)
                            total_out += len(out_bytes)
                    if decomp is not None:
                        tail = decomp.flush()
                        if tail:
                            hasher.update(tail)
                            out_fh.write(tail)
                            total_out += len(tail)
            except urllib.error.HTTPError as exc:
                dst_path.unlink(missing_ok=True)
                last_err = f"http_{exc.code}"
                if exc.code == 404 and suffix_idx + 1 < len(suffix_candidates):
                    break
                if exc.code in (403, 404, 410) or attempt >= retries:
                    return "fetch_error", 0, last_err
                time.sleep(1.0 * (attempt + 1))
                continue
            except zlib.error as exc:
                dst_path.unlink(missing_ok=True)
                return "fetch_error", 0, f"zlib_error:{exc}"
            except Exception as exc:
                dst_path.unlink(missing_ok=True)
                last_err = f"{type(exc).__name__}:{exc}"
                if attempt >= retries:
                    return "fetch_error", 0, last_err
                time.sleep(1.0 * (attempt + 1))
                continue

            actual_sha = hasher.hexdigest()
            if actual_sha != sha_hex:
                dst_path.unlink(missing_ok=True)
                return "sha_mismatch", total_out, f"expected={sha_hex},got={actual_sha}"
            return "ok", total_out, None

    dst_path.unlink(missing_ok=True)
    return "fetch_error", 0, last_err or "unknown_fetch_error"


def _classify_page_failure_mode(*, path_counts: list[int], image_counts: list[int]) -> str:
    if any(ic == 0 and pc >= 200 for ic, pc in zip(image_counts, path_counts)):
        return "vector_outlined"
    if any(ic > 0 for ic in image_counts):
        return "image_scan"
    return "native_text"


def _ocr_single_pdf(
    pipe: Any,
    pdf_path: Path,
    *,
    extract_native_fn: Any,
    pdfium_mod: Any,
    dpi: int,
    max_pages: int,
) -> dict[str, Any]:
    try:
        doc = pdfium_mod.PdfDocument(str(pdf_path))
        try:
            n_pages_total = len(doc)
        finally:
            doc.close()
    except Exception as exc:
        return {
            "rescued_status": "corrupt_pdf",
            "page_failure_mode": "corrupt_pdf",
            "n_pages_total": 0,
            "pages_ocred": 0,
            "rescued_chars": 0,
            "rescued_p12_chars": 0,
            "used_raster_ocr": False,
            "max_path_count": 0,
            "max_image_count": 0,
            "path_counts": [],
            "image_counts": [],
            "native_body_chars": [],
            "backends": [],
            "rescued_text": "",
            "rescued_text_sha256": hashlib.sha256(b"").hexdigest(),
            "error": f"pdfium_open_failed:{type(exc).__name__}:{exc}",
        }

    if n_pages_total <= 0:
        return {
            "rescued_status": "corrupt_pdf",
            "page_failure_mode": "corrupt_pdf",
            "n_pages_total": 0,
            "pages_ocred": 0,
            "rescued_chars": 0,
            "rescued_p12_chars": 0,
            "used_raster_ocr": False,
            "max_path_count": 0,
            "max_image_count": 0,
            "path_counts": [],
            "image_counts": [],
            "native_body_chars": [],
            "backends": [],
            "rescued_text": "",
            "rescued_text_sha256": hashlib.sha256(b"").hexdigest(),
            "error": "zero_pages",
        }

    page_indices = list(range(min(max_pages, n_pages_total)))
    try:
        native_pages = extract_native_fn(pdf_path, page_indices=page_indices)
        path_counts = [int(p.path_count) for p in native_pages]
        image_counts = [int(p.image_count) for p in native_pages]
        native_body_chars = [
            int(p.native_body_char_count if p.native_body_char_count is not None else p.native_char_count)
            for p in native_pages
        ]
        outs = pipe.ocr_pdf(pdf_path, page_indices=page_indices, use_native_text=True, dpi=dpi)
    except Exception as exc:
        return {
            "rescued_status": "corrupt_pdf",
            "page_failure_mode": "corrupt_pdf",
            "n_pages_total": n_pages_total,
            "pages_ocred": 0,
            "rescued_chars": 0,
            "rescued_p12_chars": 0,
            "used_raster_ocr": False,
            "max_path_count": 0,
            "max_image_count": 0,
            "path_counts": [],
            "image_counts": [],
            "native_body_chars": [],
            "backends": [],
            "rescued_text": "",
            "rescued_text_sha256": hashlib.sha256(b"").hexdigest(),
            "error": f"ocr_failed:{type(exc).__name__}:{exc}",
        }

    backends = [str(o.backend_used) for o in outs]
    used_raster_ocr = any(not b.startswith("native") for b in backends)
    page_blocks = [
        f"--- Page {o.page_index + 1} ---\n{o.text.strip()}"
        for o in outs
        if isinstance(o.text, str) and o.text.strip()
    ]
    full_text = "\n\n".join(page_blocks).strip()
    p12_text = "\n\n".join(o.text.strip() for o in outs[:2] if isinstance(o.text, str) and o.text.strip()).strip()
    stored_text = full_text[:MAX_RESCUED_TEXT_CHARS]
    failure_mode = _classify_page_failure_mode(path_counts=path_counts, image_counts=image_counts)
    return {
        "rescued_status": "ok" if len(full_text) > 0 else "empty_ocr",
        "page_failure_mode": failure_mode,
        "n_pages_total": n_pages_total,
        "pages_ocred": len(outs),
        "rescued_chars": len(full_text),
        "rescued_p12_chars": len(p12_text),
        "used_raster_ocr": used_raster_ocr,
        "max_path_count": max(path_counts) if path_counts else 0,
        "max_image_count": max(image_counts) if image_counts else 0,
        "path_counts": path_counts,
        "image_counts": image_counts,
        "native_body_chars": native_body_chars,
        "backends": backends,
        "rescued_text": stored_text,
        "rescued_text_sha256": hashlib.sha256(stored_text.encode("utf-8")).hexdigest(),
        "error": None,
    }


def run_ocr(
    *,
    out_dir: Path,
    dpi: int = 200,
    max_pages: int = 5,
    limit: int | None = None,
    sentinels_only: bool = False,
    resume: bool = True,
    retry_fetch_errors: bool = False,
    local_cache_dir: Path | None = None,
    origin: str = DEFAULT_ORIGIN,
) -> dict[str, Any]:
    """Stream target PDFs, run `FastOCR(backend='apple-vision')`, and checkpoint per SHA."""
    import pypdfium2 as pdfium
    from fast_ocr import FastOCR
    from fast_ocr.preprocess import extract_native_pdf_text

    targets_path = out_dir / "targets.jsonl"
    if not targets_path.is_file():
        raise FileNotFoundError(f"Missing targets manifest: {targets_path}")

    all_targets = _read_jsonl(targets_path)
    out_jsonl = out_dir / "rescued_pages.jsonl"
    latest_status_by_sha: dict[str, str] = {}
    if resume and out_jsonl.is_file():
        for row in _read_jsonl(out_jsonl):
            if row.get("saved_body_hex"):
                latest_status_by_sha[str(row["saved_body_hex"])] = str(row.get("rescued_status") or "")
    done_shas: set[str] = {
        sha
        for sha, st in latest_status_by_sha.items()
        if not (retry_fetch_errors and st == "fetch_error")
    }

    pending = [
        t
        for t in all_targets
        if (not sentinels_only or bool(t.get("is_sentinel"))) and str(t["saved_body_hex"]) not in done_shas
    ]
    if limit is not None:
        pending = pending[: max(0, int(limit))]

    if not pending:
        print(f"No pending targets (already completed={len(done_shas)} / total={len(all_targets)}).")
        return {"processed": 0, "skipped_existing": len(done_shas)}

    local_map = index_local_cache(local_cache_dir)
    tmp_dir = out_dir / ".tmp_pdf"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    small_items = [t for t in pending if int(t["saved_bytes"]) < PREFETCH_MAX_BYTES]
    large_items = [t for t in pending if int(t["saved_bytes"]) >= PREFETCH_MAX_BYTES]

    processed = 0
    ok_count = 0
    err_count = 0
    t_run_start = time.perf_counter()

    def _prepare(item: dict[str, Any]) -> tuple[Path, bool, str, int, str | None]:
        sha = str(item["saved_body_hex"])
        cached = local_map.get(sha)
        if cached is not None and cached.is_file():
            return cached, False, "ok", cached.stat().st_size, None
        dst = tmp_dir / f"{sha}.pdf"
        st, n_b, err = stream_download_verified_pdf(
            sha,
            dst,
            origin=origin,
            saved_suffix=item.get("saved_suffix"),
        )
        return dst, True, st, n_b, err

    try:
        with (
            FastOCR(backend="apple-vision", output_format="markdown") as pipe,
            out_jsonl.open("a", encoding="utf-8") as out_fh,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            def _handle_target(item: dict[str, Any], prep_res: tuple[Path, bool, str, int, str | None]) -> None:
                nonlocal processed, ok_count, err_count
                sha = str(item["saved_body_hex"])
                pdf_path, cleanup_pdf, dl_st, _n_b, dl_err = prep_res
                t0 = time.perf_counter()
                try:
                    if dl_st != "ok":
                        rec_body = {
                            "rescued_status": dl_st,
                            "page_failure_mode": dl_st,
                            "n_pages_total": 0,
                            "pages_ocred": 0,
                            "rescued_chars": 0,
                            "rescued_p12_chars": 0,
                            "used_raster_ocr": False,
                            "max_path_count": 0,
                            "max_image_count": 0,
                            "path_counts": [],
                            "image_counts": [],
                            "native_body_chars": [],
                            "backends": [],
                            "rescued_text": "",
                            "rescued_text_sha256": hashlib.sha256(b"").hexdigest(),
                            "error": dl_err,
                        }
                    else:
                        rec_body = _ocr_single_pdf(
                            pipe,
                            pdf_path,
                            extract_native_fn=extract_native_pdf_text,
                            pdfium_mod=pdfium,
                            dpi=dpi,
                            max_pages=max_pages,
                        )
                finally:
                    if cleanup_pdf:
                        pdf_path.unlink(missing_ok=True)

                elapsed_s = round(time.perf_counter() - t0, 3)
                full_rec = {
                    "saved_body_hex": sha,
                    "doc_key": item["doc_key"],
                    "filename": item["filename"],
                    "saved_bytes": int(item["saved_bytes"]),
                    "cohorts": item["cohorts"],
                    "orig_status": item["orig_status"],
                    "orig_chars": int(item["orig_chars"]),
                    "is_sentinel": bool(item.get("is_sentinel")),
                    "elapsed_s": elapsed_s,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    **rec_body,
                }
                out_fh.write(json.dumps(full_rec, ensure_ascii=False) + "\n")
                out_fh.flush()

                processed += 1
                if full_rec["rescued_status"] == "ok":
                    ok_count += 1
                else:
                    err_count += 1
                if processed <= 12 or processed % 25 == 0 or processed == len(pending):
                    rate = processed / max(1e-6, time.perf_counter() - t_run_start)
                    print(
                        f"[{processed}/{len(pending)}] {sha[:12]} status={full_rec['rescued_status']} "
                        f"mode={full_rec['page_failure_mode']} chars={full_rec['orig_chars']}->{full_rec['rescued_chars']} "
                        f"({elapsed_s:.2f}s, {rate:.2f} pdf/s) {item['filename'][:45]}",
                        flush=True,
                    )

            # Bounded 2-ahead prefetch for <50MB PDFs
            inflight: list[tuple[dict[str, Any], Future[Any]]] = []
            idx_small = 0
            while idx_small < len(small_items) and len(inflight) < 2:
                it = small_items[idx_small]
                inflight.append((it, pool.submit(_prepare, it)))
                idx_small += 1
            while inflight:
                it, fut = inflight.pop(0)
                if idx_small < len(small_items):
                    nxt = small_items[idx_small]
                    inflight.append((nxt, pool.submit(_prepare, nxt)))
                    idx_small += 1
                _handle_target(it, fut.result())

            # Synchronous single-file processing for >=50MB PDFs to cap temp disk
            for it in large_items:
                _handle_target(it, _prepare(it))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    summary = {
        "processed": processed,
        "ok": ok_count,
        "non_ok": err_count,
        "elapsed_s": round(time.perf_counter() - t_run_start, 2),
        "out_jsonl": str(out_jsonl),
    }
    print(json.dumps(summary, indent=2))
    return summary


def _pct(num: int, den: int) -> float:
    return round((100.0 * num / den), 2) if den > 0 else 0.0


def _cohort_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    chars_list = sorted(int(r.get("rescued_chars") or 0) for r in rows)
    elapsed_list = sorted(float(r.get("elapsed_s") or 0.0) for r in rows)
    status_counts = dict(sorted(Counter(str(r.get("rescued_status") or "") for r in rows).items()))
    mode_counts = dict(sorted(Counter(str(r.get("page_failure_mode") or "") for r in rows).items()))
    ge_100 = sum(1 for r in rows if int(r.get("rescued_chars") or 0) >= 100)
    ge_400 = sum(1 for r in rows if int(r.get("rescued_chars") or 0) >= 400)
    p12_ge_200 = sum(1 for r in rows if int(r.get("rescued_p12_chars") or 0) >= 200)
    used_raster = sum(1 for r in rows if bool(r.get("used_raster_ocr")))
    return {
        "count": n,
        "status_counts": status_counts,
        "failure_mode_counts": mode_counts,
        "used_raster_ocr_count": used_raster,
        "recovered_ge_100_chars": ge_100,
        "recovered_ge_100_pct": _pct(ge_100, n),
        "recovered_ge_400_chars": ge_400,
        "recovered_ge_400_pct": _pct(ge_400, n),
        "recovered_p12_ge_200_chars": p12_ge_200,
        "recovered_p12_ge_200_pct": _pct(p12_ge_200, n),
        "median_rescued_chars": int(statistics.median(chars_list)) if chars_list else 0,
        "p90_rescued_chars": int(chars_list[int(0.9 * (len(chars_list) - 1))]) if chars_list else 0,
        "median_elapsed_s": round(float(statistics.median(elapsed_list)), 3) if elapsed_list else 0.0,
        "total_elapsed_s": round(sum(elapsed_list), 2),
    }


def package_and_validate(*, out_dir: Path) -> dict[str, Any]:
    """Validate 100% SHA accounting, emit `rescued_p15.parquet`, report & spot check."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    targets = _read_jsonl(out_dir / "targets.jsonl")
    if not targets:
        raise ValueError(f"Empty or missing targets.jsonl in {out_dir}")
    latest_by_sha: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(out_dir / "rescued_pages.jsonl"):
        latest_by_sha[str(row["saved_body_hex"])] = row

    missing = [str(t["saved_body_hex"]) for t in targets if str(t["saved_body_hex"]) not in latest_by_sha]
    if missing:
        raise RuntimeError(f"Incomplete rescue run: {len(missing)} target SHAs missing (first={missing[0]})")

    sha_mismatches = [
        sha for sha, r in latest_by_sha.items() if r.get("rescued_status") == "sha_mismatch"
    ]
    if sha_mismatches:
        raise RuntimeError(f"Fail-closed SHA-256 mismatch detected: {sha_mismatches[:5]}")

    ordered_rows: list[dict[str, Any]] = []
    pq_rows: list[dict[str, Any]] = []
    for t in targets:
        sha = str(t["saved_body_hex"])
        r = latest_by_sha[sha]
        merged = {
            **r,
            "cohorts": list(t.get("cohorts") or []),
            "doc_keys": list(t.get("doc_keys") or [t["doc_key"]]),
            "link_keys": list(t.get("link_keys") or []),
            "is_sentinel": bool(t.get("is_sentinel")),
        }
        ordered_rows.append(merged)
        pq_rows.append(
            {
                "saved_body": bytes.fromhex(sha),
                "saved_body_hex": sha,
                "doc_key": str(t["doc_key"]),
                "filename": str(t["filename"]),
                "saved_bytes": int(t["saved_bytes"]),
                "cohorts": list(t["cohorts"]),
                "orig_status": str(t["orig_status"]),
                "orig_chars": int(t["orig_chars"]),
                "rescued_status": str(r["rescued_status"]),
                "page_failure_mode": str(r["page_failure_mode"]),
                "n_pages_total": int(r["n_pages_total"]),
                "pages_ocred": int(r["pages_ocred"]),
                "rescued_chars": int(r["rescued_chars"]),
                "rescued_p12_chars": int(r["rescued_p12_chars"]),
                "used_raster_ocr": bool(r["used_raster_ocr"]),
                "max_path_count": int(r["max_path_count"]),
                "max_image_count": int(r["max_image_count"]),
                "backends": list(r["backends"]),
                "rescued_text": str(r["rescued_text"]),
                "rescued_text_sha256": str(r["rescued_text_sha256"]),
                "elapsed_s": float(r["elapsed_s"]),
            }
        )

    schema = pa.schema(
        [
            pa.field("saved_body", pa.binary(32), nullable=False),
            pa.field("saved_body_hex", pa.string(), nullable=False),
            pa.field("doc_key", pa.string(), nullable=False),
            pa.field("filename", pa.string(), nullable=False),
            pa.field("saved_bytes", pa.int64(), nullable=False),
            pa.field("cohorts", pa.list_(pa.string()), nullable=False),
            pa.field("orig_status", pa.string(), nullable=False),
            pa.field("orig_chars", pa.int64(), nullable=False),
            pa.field("rescued_status", pa.string(), nullable=False),
            pa.field("page_failure_mode", pa.string(), nullable=False),
            pa.field("n_pages_total", pa.int64(), nullable=False),
            pa.field("pages_ocred", pa.int64(), nullable=False),
            pa.field("rescued_chars", pa.int64(), nullable=False),
            pa.field("rescued_p12_chars", pa.int64(), nullable=False),
            pa.field("used_raster_ocr", pa.bool_(), nullable=False),
            pa.field("max_path_count", pa.int64(), nullable=False),
            pa.field("max_image_count", pa.int64(), nullable=False),
            pa.field("backends", pa.list_(pa.string()), nullable=False),
            pa.field("rescued_text", pa.string(), nullable=False),
            pa.field("rescued_text_sha256", pa.string(), nullable=False),
            pa.field("elapsed_s", pa.float64(), nullable=False),
        ]
    )
    pq_path = out_dir / "rescued_p15.parquet"
    pq_tmp = out_dir / "rescued_p15.parquet.tmp"
    pq.write_table(pa.Table.from_pylist(pq_rows, schema=schema), pq_tmp, compression="zstd")
    os.replace(pq_tmp, pq_path)

    report = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "total_targets": len(ordered_rows),
        "parquet_path": str(pq_path),
        "parquet_sha256": _sha256_file(pq_path),
        "sha_mismatch_count": 0,
        "overall": _cohort_metrics(ordered_rows),
        "by_cohort": {
            "ocr_unreadable": _cohort_metrics([r for r in ordered_rows if "ocr_unreadable" in r["cohorts"]]),
            "llm_queue_lt400": _cohort_metrics([r for r in ordered_rows if "llm_queue_lt400" in r["cohorts"]]),
            "sentinel": _cohort_metrics([r for r in ordered_rows if bool(r["is_sentinel"])]),
        },
        "sentinel_rows": [
            {
                "doc_key": r["doc_key"],
                "saved_body_hex": r["saved_body_hex"],
                "filename": r["filename"],
                "orig_status": r["orig_status"],
                "orig_chars": r["orig_chars"],
                "rescued_status": r["rescued_status"],
                "page_failure_mode": r["page_failure_mode"],
                "rescued_chars": r["rescued_chars"],
                "rescued_p12_chars": r["rescued_p12_chars"],
                "max_path_count": r["max_path_count"],
                "max_image_count": r["max_image_count"],
                "backends": r["backends"],
            }
            for r in ordered_rows
            if bool(r["is_sentinel"])
        ],
    }
    report_path = out_dir / "validation_report.json"
    _atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    # 12-doc deterministic spot check: 8 sentinels + 2 ocr_unreadable + 2 llm_queue_lt400
    spot_rows = [r for r in ordered_rows if bool(r["is_sentinel"])]
    non_sent = sorted((r for r in ordered_rows if not r["is_sentinel"]), key=lambda x: x["saved_body_hex"])
    spot_rows.extend([r for r in non_sent if "ocr_unreadable" in r["cohorts"] and r["rescued_status"] == "ok"][:2])
    spot_rows.extend([r for r in non_sent if "llm_queue_lt400" in r["cohorts"] and r["rescued_status"] == "ok"][:2])

    md_lines = [
        "# `ct-o7ew` Spot Check (12 Rescued PDFs)",
        "",
        f"- Total targets validated: **{len(ordered_rows)}** (`0` missing, `0` SHA mismatches)",
        f"- Overall `>= 100` chars recovered: **{report['overall']['recovered_ge_100_chars']}/{len(ordered_rows)} ({report['overall']['recovered_ge_100_pct']}%)**",
        f"- Overall `>= 400` chars recovered: **{report['overall']['recovered_ge_400_chars']}/{len(ordered_rows)} ({report['overall']['recovered_ge_400_pct']}%)**",
        "",
    ]
    for idx, r in enumerate(spot_rows, start=1):
        preview = " ".join(str(r["rescued_text"] or "").split())[:400]
        md_lines.extend(
            [
                f"## {idx}. `{r['filename']}` (`{r['doc_key'][:12]}`, sha `{r['saved_body_hex'][:12]}`)",
                f"- Cohorts: `{r['cohorts']}` | Mode: `{r['page_failure_mode']}` | Status: `{r['rescued_status']}`",
                f"- Chars: `{r['orig_chars']}` -> `{r['rescued_chars']}` (`p12={r['rescued_p12_chars']}`) | Max paths/images: `{r['max_path_count']}/{r['max_image_count']}`",
                f"- Backends: `{r['backends']}`",
                f"- Preview: `{preview}`",
                "",
            ]
        )
    spot_path = out_dir / "spot_check_10.md"
    _atomic_write_text(spot_path, "\n".join(md_lines))
    print(json.dumps({"report_path": str(report_path), "spot_check": str(spot_path), **report["overall"]}, indent=2))
    return report


def _build_parser() -> argparse.ArgumentParser:
    defs = default_paths()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    bt = sub.add_parser("build-targets", help="Build deduplicated SHA target manifest via DuckDB.")
    bt.add_argument("--out-dir", type=Path, default=defs["out_dir"])
    bt.add_argument("--detail-path", type=Path, default=defs["detail"])
    bt.add_argument("--det-path", type=Path, default=defs["det"])
    bt.add_argument("--llm-queue-path", type=Path, default=defs["llm_queue"])

    ro = sub.add_parser("run-ocr", help="Stream PDFs from R2/cache and run fast-ocr pages 1-5.")
    ro.add_argument("--out-dir", type=Path, default=defs["out_dir"])
    ro.add_argument("--dpi", type=int, default=200)
    ro.add_argument("--max-pages", type=int, default=5)
    ro.add_argument("--limit", type=int, default=None)
    ro.add_argument("--sentinels-only", action="store_true")
    ro.add_argument("--resume", action="store_true", default=True)
    ro.add_argument("--no-resume", dest="resume", action="store_false")
    ro.add_argument("--retry-fetch-errors", action="store_true")
    ro.add_argument("--local-cache-dir", type=Path, default=None)
    ro.add_argument("--origin", type=str, default=DEFAULT_ORIGIN)

    pv = sub.add_parser("package-and-validate", help="Validate 100%% accounting & emit rescued_p15.parquet.")
    pv.add_argument("--out-dir", type=Path, default=defs["out_dir"])
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "build-targets":
        build_targets(
            out_dir=args.out_dir,
            detail_path=args.detail_path,
            det_path=args.det_path,
            llm_queue_path=args.llm_queue_path,
        )
        return 0
    if args.cmd == "run-ocr":
        run_ocr(
            out_dir=args.out_dir,
            dpi=args.dpi,
            max_pages=args.max_pages,
            limit=args.limit,
            sentinels_only=args.sentinels_only,
            resume=args.resume,
            retry_fetch_errors=args.retry_fetch_errors,
            local_cache_dir=args.local_cache_dir,
            origin=args.origin,
        )
        return 0
    if args.cmd == "package-and-validate":
        package_and_validate(out_dir=args.out_dir)
        return 0
    raise AssertionError(f"Unhandled command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
