#!/usr/bin/env python3
"""Adopted into congressional-tech 2026-11-17 (ct-ihe7) from
`.cache/archive-release/docmeta-v6-20261116/scripts_v6_2/build_v6_2_ssot_sidecar.py` (sha256 47fecb9ce2e56b18...,
the bytes `SHA256SUMS_v6_2.json` pins), where it was the only copy. Changes here: rules and schema are imported
from `congress_docmeta` and `viewer_publication` (no source paths), and outputs go to a required `--out-root`
instead of over the pinned bundle. It is still a one-release migration (v6_1 bundle -> v6_2, release
55c14dcd..., fixed row counts), not a general builder. NOT re-run since adoption: the pinned v6_2 files were
built before rules R4 to R8, so a run today legitimately differs from them.

Run: `.venv/bin/python packages/congress_docmeta/scripts/build_v6_2_ssot_sidecar.py --out-root <new folder>`
(about 54 minutes on the 2026-11-17 run).

DocMeta V6.2 Sidecar Builder — Singular `BodyTextSSOT` (`hybrid_9000_r0.72`) Upgrade (`build_v6_2_ssot_sidecar.py`).

Produces additive `v6_2` sidecar artifacts inside `/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v6-20261116/`
while preserving `parquets/` (`v6`) and `parquets_v6_1/` (`v6_1`) 100% immutable:
  - `parquets_v6_2/deterministic_323k_v6_2.parquet` (`323,564` rows)
  - `parquets_v6_2/completed_no_llm_v6_2.parquet` (`0` NULL `docmeta_json`, `100%` `strict_validate_v4`)
  - `parquets_v6_2/llm_queue_v6_2.parquet` (`BodyTextSSOT` `hybrid_9000_r0.72` `head_tail_window` hydrated)
  - `parquets_v6_2/sha_dup_alias_v6_2.parquet` (`188` exact-SHA duplicate aliases with updated canonical buckets)
  - `MANIFEST_v6_2.json` & `SHA256SUMS_v6_2.json`
  - `reports_and_receipts_v6_2/v6_2_ssot_sidecar_report.json`

Key V6.2 upgrades:
  1. Hydrates document text directly from singular `export.parquet` (`320,629 / 323,128` = `99.23%` eligible bodies,
     including CMS-stripped HTMLs, `8,505` composed WARCs, and Tesseract/GPO-repaired PDFs) via
     `viewer_publication.body_text_ssot.BodyTextSSOT` + `head_tail_window` (`max_chars=9000, head_ratio=0.72`,
     `tail_chars=2520`, dynamic `head_pages` fill up to `head_budget=6480`), falling back to `v6_1`'s `1,929`
     Cold-R2 verified excerpts only where `saved_body` is absent from `export.parquet`.
  2. Routes `accepted-set-v12/selection.json` `excluded_bodies` (`416` total: `390` newly excluded 404/NoSuchKey/
     Meeting-Not-Found error responses + `26` prior exclusions), non-usable `.zip` containers, and empty `no_prose`
     CMS shells cleanly into `completed_no_llm_v6_2.parquet` (`100%` `strict_validate_v4` valid) so
     `llm_queue_v6_2.parquet` wastes `0` GPU cycles on error/empty wrappers.
  3. Re-applies updated `fast_gemma4.docmeta` V6.2 rules (`zero_llm_bypass_v6`, `cover_locks_v6`, string `panel` &
     `"questioner"` role fixes, `disambiguate_persona_roles_v6`, and `RefSpec` citations) over newly hydrated texts.
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from congress_docmeta.gold import DEFAULT_ARCHIVE_DIR

# ---------------------------------------------------------------------------
# Paths & Constants (`0` scratch paths)
# ---------------------------------------------------------------------------

SIDECAR_ROOT = DEFAULT_ARCHIVE_DIR  # the pinned bundle this migration reads; never written (see --out-root)
PARQUETS_V6_DIR = SIDECAR_ROOT / "parquets"
PARQUETS_V6_1_DIR = SIDECAR_ROOT / "parquets_v6_1"
CACHE_V6_1_DIR = SIDECAR_ROOT / "cache_v6_1"
LOOKUPS_DIR = SIDECAR_ROOT / "lookups_and_gold"

os.environ["DOCMETA_V6_DATA_DIR"] = str(LOOKUPS_DIR)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_OFFLINE"] = "1"

EXPECTED_RELEASE_ID = "55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105"
EXPECTED_TOTAL_ROWS = 323_564
ROW_GROUP_SIZE_TARGET = 32_768

WINDOW_MAX_CHARS = 9_000
WINDOW_HEAD_RATIO = 0.72
WINDOW_TAIL_CHARS = 2_520  # int(round(9000 * (1 - 0.72)))
WINDOW_HEAD_BUDGET = WINDOW_MAX_CHARS - WINDOW_TAIL_CHARS  # 6,480

SSOT_ROOT = Path(
    "/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/"
    "ocr-recovery-20261113/repairs/body-text-ssot-20261116"
)
SSOT_EXPORT_DIR = SSOT_ROOT / "export"
V12_SELECTION_JSON = SSOT_ROOT / "accepted-set-v12" / "selection.json"

CANDIDATE_ROOT = Path(
    "/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/"
    "ct-release-20261112T2215/release/candidate-df55-final"
)
PUBLISHED_DIR = CANDIDATE_ROOT / "public-readback" / "published"
ARCHIVE_REL_DIR = CANDIDATE_ROOT / "archive-release"

from viewer_publication.body_text_ssot import (  # noqa: E402
    BodyTextSSOT,
    head_tail_window,
    slice_pages,
    verify_ssot_export,
)

from congress_docmeta import (  # noqa: E402
    anomaly_router_v6 as ar6,
    citations_and_signals_v6 as cs6,
    hygiene_and_line_parsers_v6 as h6,
    multipage_rules_v5 as mp5,
    pythonic_v5 as pv5,
    pythonic_v6 as pv6,
    relational_rules_v6 as rv6,
    zero_llm_bypass_v6 as zb6,
)
from congress_docmeta.schema_v4 import MAX_PERSONAS  # noqa: E402

SCHEMA_OBJ: dict[str, Any] = pv5.SCHEMA_OBJ

PERSONA_KEYS_ORDER: tuple[str, ...] = zb6.PERSONA_KEYS_ORDER_V6

VALID_ROLES_SET = frozenset(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
VALID_ETYPES_SET = frozenset(SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["entity_type"]["enum"])
NON_USABLE_TRIAGE_STATUSES = pv5.NON_USABLE_TRIAGE_STATUSES
ZERO_LLM_BYPASS_KINDS = frozenset(
    {
        "truth_in_testimony_disclosure",
        "attendance_quorum_sheet",
        "witness_list",
        "legislative_schedule_or_calendar",
    }
)

GENERIC_EMPTY_CMS_BANNERS = frozenset(
    {
        "the official u.s. congressional website of the republican budget committee",
        "the official u.s. congressional website of the house budget committee",
    }
)


# ---------------------------------------------------------------------------
# 1. Strict Schema + Causal Key-Order Validator & Sanitizer
# ---------------------------------------------------------------------------

strict_validate_v4 = pv5.validate_docmeta_v4_all


def sanitize_persona_dict(p: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(p, Mapping):
        return None
    nm = re.sub(r"\s+", " ", str(p.get("name") or "")).strip()
    if not nm:
        return None
    role = str(p.get("role") or "witness").strip()
    if role == "member":
        role = "author_or_speaker"
    elif role == "submitter":
        role = "sender"
    if role not in VALID_ROLES_SET:
        return None
    etype = str(p.get("entity_type") or "non_gov_person").strip()
    if etype not in VALID_ETYPES_SET:
        etype = "non_gov_person"

    out: dict[str, Any] = {}
    for k in PERSONA_KEYS_ORDER:
        if k == "name":
            out["name"] = nm[:120]
        elif k == "role":
            out["role"] = role
        elif k == "entity_type":
            out["entity_type"] = etype
        elif k in p and p[k] is not None:
            v = p[k]
            if k == "panel":
                if isinstance(v, bool):
                    continue
                if isinstance(v, int):
                    out["panel"] = f"Panel {v}"
                else:
                    sv = re.sub(r"\s+", " ", str(v)).strip()
                    if sv:
                        out["panel"] = f"Panel {sv}" if sv.isdigit() else sv[:80]
            elif k == "redacted_personal_pii":
                if v is True:
                    out["redacted_personal_pii"] = True
            elif k in ("secondary_orgs", "prior_roles", "education"):
                if isinstance(v, Sequence) and not isinstance(v, str):
                    lim = 5 if k == "education" else (8 if k == "prior_roles" else 6)
                    arr: list[str] = []
                    seen: set[str] = set()
                    for item in v:
                        s_it = re.sub(r"\s+", " ", str(item or "")).strip()
                        if s_it and s_it.lower() not in seen:
                            seen.add(s_it.lower())
                            arr.append(s_it[:200])
                            if len(arr) >= lim:
                                break
                    if arr:
                        out[k] = arr
            elif isinstance(v, datetime.date):
                out[k] = v.isoformat()
            else:
                sv = re.sub(r"\s+", " ", str(v)).strip().rstrip(" :")
                if sv:
                    out[k] = sv[:180]
    return out


def sanitize_personas_json_str(
    raw_json: str | None,
    *,
    primary_kind: str | None = None,
    text: str | None = None,
    filename: str = "",
) -> str | None:
    if not raw_json or not isinstance(raw_json, str):
        return None
    try:
        arr = json.loads(raw_json)
    except Exception:
        return None
    if not isinstance(arr, list):
        return None
    cleaned = [
        sp
        for item in arr
        if isinstance(item, Mapping)
        for sp in [sanitize_persona_dict(item)]
        if sp is not None
    ]
    if not cleaned:
        return None
    if primary_kind or text:
        cleaned = rv6.disambiguate_persona_roles_v6(
            cleaned[:MAX_PERSONAS],
            primary_kind=primary_kind,
            text=text or "",
        )
        cleaned = [sp for p in cleaned for sp in [sanitize_persona_dict(p)] if sp is not None]
    if not cleaned:
        return None
    return json.dumps(cleaned[:MAX_PERSONAS], separators=(",", ":"), ensure_ascii=False)


def finalize_and_validate_docmeta(raw_obj: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    working = dict(raw_obj)
    for dt_k in ("doc_date", "event_date", "due_date"):
        if isinstance(working.get(dt_k), datetime.date):
            working[dt_k] = working[dt_k].isoformat()
    if "personas" in working and isinstance(working["personas"], Sequence) and not isinstance(working["personas"], str):
        ps = [sp for item in working["personas"] if isinstance(item, Mapping) for sp in [sanitize_persona_dict(item)] if sp is not None]
        if ps:
            working["personas"] = ps[:MAX_PERSONAS]
        else:
            working.pop("personas", None)
    if "subcommittees" in working and isinstance(working["subcommittees"], Sequence) and not isinstance(working["subcommittees"], str):
        clean_subs = [
            str(sc).strip()
            for sc in working["subcommittees"]
            if isinstance(sc, str)
            and str(sc).strip()
            and not re.fullmatch(r"(?:Subcommittee\s+on\s+)?(?:N/?A|None|Full\s+Committee|-+)", str(sc).strip(), re.I)
        ]
        if clean_subs:
            working["subcommittees"] = clean_subs
        else:
            working.pop("subcommittees", None)
    if "composed_title" in working and isinstance(working["composed_title"], str):
        ct = re.sub(r"\s+", " ", working["composed_title"]).strip()
        if len(ct) > 108:
            ct = ct[:105].rstrip(" ,;:-–—(") + "..."
        working["composed_title"] = ct
    if "gist" in working and isinstance(working["gist"], str):
        gw = re.sub(r"\s+", " ", working["gist"]).strip().split()
        if len(gw) > 22:
            working["gist"] = " ".join(gw[:22]).rstrip(" ,;:-–—") + "."
        else:
            working["gist"] = " ".join(gw)

    canon = pv5.canonicalize_docmeta_v4(working)
    j_str = json.dumps(canon, separators=(",", ":"), ensure_ascii=False)
    ok_s, errs_s = strict_validate_v4(j_str)
    if not ok_s:
        raise ValueError(f"strict_validate_v4 failed: {errs_s}")
    return canon, j_str


def build_grounded_triage_docmeta(
    *,
    status: str,
    text_quality: str,
    base_reason: str,
    detail_title: str | None = None,
    committees: Sequence[str] | None = None,
    filename: str | None = None,
) -> tuple[dict[str, Any], str]:
    ctx_parts: list[str] = []
    if isinstance(detail_title, str) and detail_title.strip():
        ctx_parts.append(f"title={re.sub(r'\\s+', ' ', detail_title).strip()[:65]}")
    if committees:
        c0 = str(committees[0]).strip()
        if c0:
            ctx_parts.append(f"committee={c0[:50]}")
    elif isinstance(filename, str) and filename.strip():
        ctx_parts.append(f"file={filename.strip()[:45]}")

    reason = base_reason.strip()
    if ctx_parts:
        reason = f"{reason} ({'; '.join(ctx_parts)})"
    reason = re.sub(r"\s+", " ", reason).strip()[:200]
    return finalize_and_validate_docmeta(
        {
            "status": status,
            "text_quality": text_quality,
            "error_reason": reason,
        }
    )


# ---------------------------------------------------------------------------
# 2. `BodyTextSSOT` `hybrid_9000_r0.72` Window & Bounded Multipage Signals
# ---------------------------------------------------------------------------


def build_hybrid_ssot_window_and_signals(
    text: str,
    page_offsets: Sequence[int],
    *,
    max_chars: int = WINDOW_MAX_CHARS,
    tail_chars: int = WINDOW_TAIL_CHARS,
    head_budget: int = WINDOW_HEAD_BUDGET,
) -> tuple[str, bool, str | None, str | None]:
    """Compute `(window_text, is_cover_roster_p12, p3_toc_or_gavel_slice, stapled_ttf_disclosure_json)` via `BodyTextSSOT`."""
    n_pages = len(page_offsets)
    if n_pages <= 1:
        win = head_tail_window(text, page_offsets, max_chars=max_chars, head_pages=2, tail_chars=tail_chars)
        return win, False, None, None

    if len(text) <= max_chars:
        eff_head_pages = n_pages
    else:
        # Dynamically expand `head_pages >= 2` while UTF-8 byte offset stays within `head_budget` (`hybrid_9000_r0.72`)
        eff_head_pages = 2
        while eff_head_pages < n_pages - 1 and int(page_offsets[eff_head_pages]) < head_budget - 40:
            eff_head_pages += 1

    win = head_tail_window(
        text,
        page_offsets,
        max_chars=max_chars,
        head_pages=eff_head_pages,
        tail_chars=tail_chars,
    )

    if n_pages <= 2:
        return win, False, None, None

    # Extract bounded first 10 pages for GPO p3..p8 TOC/gavel rescue & stapled Truth-in-Testimony booleans
    scan_pages = min(n_pages, 10)
    pages_head = [slice_pages(text, page_offsets, start_page=pi, max_pages=1) for pi in range(scan_pages)]
    p12_txt = "\n".join(pages_head[:2])
    gpo_res = mp5.extract_gpo_p3_p8_rescue(pages_head, p12_text=p12_txt)
    is_cov = bool(gpo_res.get("is_cover_roster_p12"))
    p3_slice = gpo_res.get("p3_toc_or_gavel_slice")
    stapled = mp5.detect_stapled_backpage_packets(pages_head, p12_text=p12_txt)
    disc = stapled.get("stapled_ttf_disclosure")
    disc_json = json.dumps(disc, separators=(",", ":"), ensure_ascii=False) if isinstance(disc, dict) and disc else None
    return win, is_cov, p3_slice, disc_json


# ---------------------------------------------------------------------------
# 3. Atomic Parquet Writer (`zstd`, `row_group_size=32768`, `row_groups >= 2`)
# ---------------------------------------------------------------------------


def write_parquet_atomic_v6_2(table: pa.Table, out_path: Path, out_root: Path, *, compression_level: int = 9) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = table.num_rows
    rg_size = ROW_GROUP_SIZE_TARGET if n > ROW_GROUP_SIZE_TARGET else max(1, (n + 1) // 2)
    tmp_path = out_path.with_suffix(".parquet.tmp")
    try:
        pq.write_table(
            table,
            tmp_path,
            compression="zstd",
            compression_level=compression_level,
            row_group_size=rg_size,
            write_statistics=True,
        )
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    pf = pq.ParquetFile(out_path)
    st = out_path.stat()
    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    assert pf.metadata.num_rows == n
    assert pf.metadata.num_row_groups >= 2, f"{out_path.name} has num_row_groups={pf.metadata.num_row_groups} (must be >= 2)!"
    return {
        "path": str(out_path.relative_to(out_root)),
        "rows": n,
        "row_groups": pf.metadata.num_row_groups,
        "row_group_size_target": rg_size,
        "bytes": st.st_size,
        "size_mb": round(st.st_size / (1024 * 1024), 3),
        "sha256": sha,
    }


def verify_pinned_sums_untouched(sums_path: Path, expected_count: int) -> int:
    sums_obj = json.loads(sums_path.read_text(encoding="utf-8"))
    expected_map: dict[str, str] = sums_obj["sha256"]
    assert len(expected_map) == expected_count, f"Expected {expected_count} pinned files in {sums_path.name}, found {len(expected_map)}"
    for rel_p, exp_sha in expected_map.items():
        fp = SIDECAR_ROOT / rel_p
        assert fp.exists(), f"Pinned file missing: {rel_p}"
        h = hashlib.sha256()
        with fp.open("rb") as f:
            while chunk := f.read(4 * 1024 * 1024):
                h.update(chunk)
        got = h.hexdigest()
        assert got == exp_sha, f"SHA256 mismatch on pinned file {rel_p}: {got} != {exp_sha}"
    return len(expected_map)


# ---------------------------------------------------------------------------
# 4. Main End-to-End Orchestration
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-root", type=Path, required=True,
                    help="folder to write parquets_v6_2/, reports_and_receipts_v6_2/, MANIFEST_v6_2.json and SHA256SUMS_v6_2.json")
    ap.add_argument("--replace-pinned", action="store_true",
                    help=f"allow --out-root to be the pinned bundle itself ({SIDECAR_ROOT}), replacing its v6_2 files")
    args = ap.parse_args(argv)
    out_root = args.out_root.expanduser().resolve()
    if out_root == SIDECAR_ROOT.resolve() and not args.replace_pinned:
        ap.error("--out-root is the pinned bundle; other jobs read its v6_2 files. Pass --replace-pinned to overwrite them.")
    PARQUETS_V6_2_DIR = out_root / "parquets_v6_2"
    REPORTS_V6_2_DIR = out_root / "reports_and_receipts_v6_2"
    t0 = time.perf_counter()
    print("=== Layer I1b (`v6_2`): Pre-flight release, SSOT export & v12 selection verification ===", flush=True)

    pub_manifest = json.loads((PUBLISHED_DIR / "manifest.json").read_text(encoding="utf-8"))
    arch_manifest = json.loads((ARCHIVE_REL_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert pub_manifest["release_id"] == EXPECTED_RELEASE_ID
    assert arch_manifest["release_id"] == EXPECTED_RELEASE_ID

    ssot_info = verify_ssot_export(SSOT_EXPORT_DIR, require_pointer=True, verify_file_sha256=False)
    ssot = BodyTextSSOT(SSOT_EXPORT_DIR, require_pointer=True, verify_file_sha256=False)
    assert ssot.rows == 320_629, f"Expected 320,629 SSOT rows, got {ssot.rows}"

    sel_v12 = json.loads(V12_SELECTION_JSON.read_text(encoding="utf-8"))
    excluded_list: list[dict[str, Any]] = list(sel_v12.get("excluded_bodies") or ())
    assert len(excluded_list) == 416, f"Expected 416 excluded_bodies in selection.json, got {len(excluded_list)}"
    excluded_by_sha: dict[str, dict[str, Any]] = {
        str(e["body_sha256"]).strip().lower(): e for e in excluded_list if e.get("body_sha256")
    }
    print(
        f"  -> Verified SSOT export ({ssot.rows:,} rows, {ssot.num_row_groups:,} row groups) "
        f"& accepted-set-v12 ({len(excluded_by_sha)} excluded_bodies)",
        flush=True,
    )

    # 1. Load immutable `v6_1` & `v6` tables + release `list.parquet` titles/bioguide/witness keys
    print("[1/5] Loading immutable `v6_1` tables & release metadata...", flush=True)
    det_v61_tbl = pq.read_table(PARQUETS_V6_1_DIR / "deterministic_323k_v6_1.parquet")
    assert det_v61_tbl.num_rows == EXPECTED_TOTAL_ROWS
    master_out: dict[str, list[Any]] = {c: det_v61_tbl[c].to_pylist() for c in det_v61_tbl.column_names}
    del det_v61_tbl

    comp_v61_rows = pq.read_table(PARQUETS_V6_1_DIR / "completed_no_llm_v6_1.parquet").to_pylist()
    comp_v61_by_lr: dict[int, dict[str, Any]] = {int(r["list_row"]): r for r in comp_v61_rows}
    del comp_v61_rows

    queue_v61_rows = pq.read_table(PARQUETS_V6_1_DIR / "llm_queue_v6_1.parquet").to_pylist()
    queue_v61_by_lr: dict[int, dict[str, Any]] = {int(r["list_row"]): r for r in queue_v61_rows}
    del queue_v61_rows

    alias_v61_rows = pq.read_table(PARQUETS_V6_1_DIR / "sha_dup_alias_v6_1.parquet").to_pylist()
    alias_v61_by_lr: dict[int, dict[str, Any]] = {int(r["list_row"]): r for r in alias_v61_rows}
    del alias_v61_rows

    list_tbl = pq.read_table(
        PUBLISHED_DIR / "list.parquet",
        columns=["title", "bioguide_ids", "witness_keys"],
    )
    list_titles: list[str | None] = list_tbl["title"].to_pylist()
    list_bioguides: list[list[str] | None] = list_tbl["bioguide_ids"].to_pylist()
    list_witness_keys: list[list[str] | None] = list_tbl["witness_keys"].to_pylist()
    del list_tbl

    rel_tbl = pq.read_table(PARQUETS_V6_DIR / "relational_323k.parquet")
    rel_cols = {c: rel_tbl[c].to_pylist() for c in rel_tbl.column_names if c != "list_row"}
    del rel_tbl

    prov_tbl = pq.read_table(PARQUETS_V6_DIR / "provenance_323k.parquet")
    prov_cols = {c: prov_tbl[c].to_pylist() for c in prov_tbl.column_names if c != "list_row"}
    del prov_tbl

    r2_cache_tbl = pq.read_table(
        CACHE_V6_1_DIR / "cold_r2_hydrated_bodies_v6_1.parquet",
        columns=["effective_body_sha_hex", "outcome"],
    )
    r2_usable_shas: set[str] = {
        str(sha).lower()
        for sha, out in zip(
            r2_cache_tbl["effective_body_sha_hex"].to_pylist(),
            r2_cache_tbl["outcome"].to_pylist(),
        )
        if out == "usable_text" and sha
    }
    del r2_cache_tbl

    # 2. Stream `export.parquet` in bounded 1,024-row batches (`< 2.5 GB` peak RAM!) to compute
    #    `hybrid_9000_r0.72` windows ONLY for needed `saved_body` digests!
    needed_sbs: set[bytes] = set()
    for lr, q_row in queue_v61_by_lr.items():
        sb_hex = str(q_row["saved_body_hex"]).lower()
        eff_hex = str(q_row["effective_body_sha_hex"]).lower()
        if sb_hex not in excluded_by_sha and eff_hex not in excluded_by_sha:
            needed_sbs.add(bytes(q_row["saved_body"]))

    print(
        f"[2/5] Streaming `export.parquet` for {len(needed_sbs):,} distinct queued `saved_body` digests "
        f"(`max_chars={WINDOW_MAX_CHARS}, head_ratio={WINDOW_HEAD_RATIO}, tail_chars={WINDOW_TAIL_CHARS}`)...",
        flush=True,
    )
    ssot_windows: dict[bytes, tuple[str, bool, str | None, str | None]] = {}
    all_ssot_sbs_hex: set[str] = set()
    pf_ssot = pq.ParquetFile(ssot.export_path)
    for rb in pf_ssot.iter_batches(batch_size=1024, columns=["saved_body", "text", "page_offsets"]):
        sb_col = rb.column(0).to_pylist()
        txt_col = rb.column(1).to_pylist()
        off_col = rb.column(2).to_pylist()
        for sb_b, txt_s, offs in zip(sb_col, txt_col, off_col):
            sb_bytes = bytes(sb_b)
            all_ssot_sbs_hex.add(sb_bytes.hex())
            if sb_bytes in needed_sbs:
                ssot_windows[sb_bytes] = build_hybrid_ssot_window_and_signals(
                    txt_s or "",
                    offs or (),
                )
    print(
        f"  -> Hydrated {len(ssot_windows):,} distinct queued bodies directly from `export.parquet` "
        f"(total SSOT bodies verified: {len(all_ssot_sbs_hex):,})",
        flush=True,
    )

    # 3. Warm RefSpec citation oracles once & process all 323,564 rows deterministically
    print("[3/5] Applying V6.2 exclusions, zero-LLM bypass, cover locks & persona role disambiguation...", flush=True)
    refspec_oracles = cs6.get_cached_refspec_oracles_v6()

    completed_v6_2: list[dict[str, Any]] = []
    llm_queue_v6_2: list[dict[str, Any]] = []
    alias_lrs: list[int] = []

    stats_v6_2: Counter[str] = Counter()

    link_keys_bin = master_out["link_key"]
    link_keys_hex = master_out["link_key_hex"]
    doc_keys = master_out["doc_key"]
    saved_bodies_bin = master_out["saved_body"]
    saved_bodies_hex = master_out["saved_body_hex"]
    eff_bodies_hex = master_out["effective_body_sha_hex"]
    package_ids = master_out["package_id"]

    for lr in range(EXPECTED_TOTAL_ROWS):
        disp = master_out["disposition"][lr] or ""
        if disp == "target_sraw_sha_dup" or lr in alias_v61_by_lr:
            alias_lrs.append(lr)
            continue

        sb_hex = str(saved_bodies_hex[lr]).lower()
        eff_hex = str(eff_bodies_hex[lr]).lower()
        fn = master_out["filename"][lr] or ""
        fmt = (master_out["effective_format"][lr] or "").lower()
        rn_val = int(master_out["rn"][lr])
        det_cong = master_out["v6_det_congress"][lr]
        det_ch = master_out["v6_det_chamber"][lr]
        det_cmts = list(master_out["v6_det_committees"][lr] or ())

        # ------------------------------------------------------------------
        # Priority 1: `accepted-set-v12/selection.json` `excluded_bodies`
        # (`error_response` / `wrapper` — `0` GPU cycles wasted on 404/NoSuchKey!)
        # ------------------------------------------------------------------
        excl_rec = excluded_by_sha.get(sb_hex) or excluded_by_sha.get(eff_hex)
        if excl_rec is not None:
            src_role = str(excl_rec.get("source_role") or "error_response")
            raw_rsn = str(excl_rec.get("reason") or "confirmed non-document HTTP error/wrapper response")
            # Strip verbose `(body:64hex):` prefix for crisp grounded error_reason
            clean_rsn = re.sub(r"\(body:[0-9a-f]{64}\):\s*", ": ", raw_rsn)
            t_canon, t_json = build_grounded_triage_docmeta(
                status="error_or_block",
                text_quality="native",
                base_reason=f"Excluded {src_role} (accepted-set-v12): {clean_rsn[:115]}",
                detail_title=list_titles[lr],
                committees=det_cmts,
                filename=fn,
            )
            was_in_q = lr in queue_v61_by_lr
            master_out["partition_bucket"][lr] = "completed_no_llm"
            master_out["v6_route"][lr] = "deterministic_triage_non_usable"
            master_out["deterministic_status"][lr] = "error_or_block"
            master_out["triage_error_reason"][lr] = t_canon["error_reason"]
            master_out["v6_locked_primary_kind"][lr] = None
            completed_v6_2.append(
                {
                    "list_row": lr,
                    "link_key": link_keys_bin[lr],
                    "link_key_hex": link_keys_hex[lr],
                    "doc_key": doc_keys[lr],
                    "saved_body": saved_bodies_bin[lr],
                    "saved_body_hex": saved_bodies_hex[lr],
                    "effective_body_sha_hex": eff_bodies_hex[lr],
                    "package_id": package_ids[lr],
                    "rn": rn_val,
                    "disposition": disp,
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": "ssot_v12_excluded_error_or_empty",
                    "filename": fn,
                    "effective_format": fmt,
                    "primary_kind": None,
                    "status": "error_or_block",
                    "congress": det_cong,
                    "chamber": det_ch,
                    "committees": det_cmts,
                    "docmeta_json": t_json,
                    "strict_v4_valid": True,
                }
            )
            stats_v6_2["excluded_v12_from_queue" if was_in_q else "excluded_v12_already_completed"] += 1
            continue

        # ------------------------------------------------------------------
        # Priority 2: Existing `completed_no_llm_v6_1` rows (re-validated & role-disambiguated)
        # ------------------------------------------------------------------
        if lr in comp_v61_by_lr:
            c_old = comp_v61_by_lr[lr]
            obj_old = json.loads(c_old["docmeta_json"])
            if obj_old.get("status") == "usable" and isinstance(obj_old.get("personas"), list):
                obj_old["personas"] = rv6.disambiguate_persona_roles_v6(
                    obj_old["personas"],
                    primary_kind=obj_old.get("primary_kind"),
                    text="",
                )
            canon_c, j_str_c = finalize_and_validate_docmeta(obj_old)
            if sb_hex in all_ssot_sbs_hex and master_out["text_source"][lr] not in ("detail_metadata_only", "upstream_spicydocs"):
                master_out["text_source"][lr] = "body_text_ssot_v12"
            completed_v6_2.append(
                {
                    "list_row": lr,
                    "link_key": link_keys_bin[lr],
                    "link_key_hex": link_keys_hex[lr],
                    "doc_key": doc_keys[lr],
                    "saved_body": saved_bodies_bin[lr],
                    "saved_body_hex": saved_bodies_hex[lr],
                    "effective_body_sha_hex": eff_bodies_hex[lr],
                    "package_id": package_ids[lr],
                    "rn": int(c_old["rn"]),
                    "disposition": c_old["disposition"],
                    "v6_route": c_old["v6_route"],
                    "zero_llm_source": c_old["zero_llm_source"],
                    "filename": c_old["filename"],
                    "effective_format": c_old["effective_format"],
                    "primary_kind": canon_c.get("primary_kind"),
                    "status": canon_c["status"],
                    "congress": canon_c.get("congress") if canon_c.get("congress") is not None else c_old["congress"],
                    "chamber": canon_c.get("chamber") or c_old["chamber"],
                    "committees": list(canon_c.get("committees") or c_old["committees"] or ()),
                    "docmeta_json": j_str_c,
                    "strict_v4_valid": True,
                }
            )
            stats_v6_2["retained_completed_v6_1"] += 1
            continue

        # ------------------------------------------------------------------
        # Priority 3: `llm_queue_v6_1` rows — Hydrate from `BodyTextSSOT` or Cold-R2 Fallback
        # ------------------------------------------------------------------
        q_old = queue_v61_by_lr[lr]
        sb_bytes = bytes(saved_bodies_bin[lr])

        # Non-usable `.zip` archive directory listings (`10` rows) -> triage `stub_or_blank`
        if fmt == "zip" and sb_bytes not in ssot_windows:
            t_canon, t_json = build_grounded_triage_docmeta(
                status="stub_or_blank",
                text_quality="native",
                base_reason="Unextracted application/zip archive container without standalone prose body",
                detail_title=list_titles[lr],
                committees=det_cmts,
                filename=fn,
            )
            master_out["partition_bucket"][lr] = "completed_no_llm"
            master_out["v6_route"][lr] = "deterministic_triage_non_usable"
            master_out["deterministic_status"][lr] = "stub_or_blank"
            master_out["triage_error_reason"][lr] = t_canon["error_reason"]
            master_out["v6_locked_primary_kind"][lr] = None
            completed_v6_2.append(
                {
                    "list_row": lr,
                    "link_key": link_keys_bin[lr],
                    "link_key_hex": link_keys_hex[lr],
                    "doc_key": doc_keys[lr],
                    "saved_body": saved_bodies_bin[lr],
                    "saved_body_hex": saved_bodies_hex[lr],
                    "effective_body_sha_hex": eff_bodies_hex[lr],
                    "package_id": package_ids[lr],
                    "rn": rn_val,
                    "disposition": disp,
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": "v6_2_triage_zip_container",
                    "filename": fn,
                    "effective_format": fmt,
                    "primary_kind": None,
                    "status": "stub_or_blank",
                    "congress": det_cong,
                    "chamber": det_ch,
                    "committees": det_cmts,
                    "docmeta_json": t_json,
                    "strict_v4_valid": True,
                }
            )
            stats_v6_2["triaged_zip_containers"] += 1
            continue

        # Empty `detail_description_fallback` CMS HTML shells absent from `export.parquet` (`no_prose`)
        old_clean_probe = str(q_old["p12_clean_text"] or "").strip()
        if (
            sb_bytes not in ssot_windows
            and q_old["text_source"] == "detail_description_fallback"
            and old_clean_probe.lower().rstrip(".") in GENERIC_EMPTY_CMS_BANNERS
        ):
            t_canon, t_json = build_grounded_triage_docmeta(
                status="stub_or_blank",
                text_quality="native",
                base_reason="Empty committee HTML shell without article body prose (no_prose in body_text SSOT)",
                detail_title=list_titles[lr],
                committees=det_cmts,
                filename=fn,
            )
            master_out["partition_bucket"][lr] = "completed_no_llm"
            master_out["v6_route"][lr] = "deterministic_triage_non_usable"
            master_out["deterministic_status"][lr] = "stub_or_blank"
            master_out["triage_error_reason"][lr] = t_canon["error_reason"]
            master_out["v6_locked_primary_kind"][lr] = None
            completed_v6_2.append(
                {
                    "list_row": lr,
                    "link_key": link_keys_bin[lr],
                    "link_key_hex": link_keys_hex[lr],
                    "doc_key": doc_keys[lr],
                    "saved_body": saved_bodies_bin[lr],
                    "saved_body_hex": saved_bodies_hex[lr],
                    "effective_body_sha_hex": eff_bodies_hex[lr],
                    "package_id": package_ids[lr],
                    "rn": rn_val,
                    "disposition": disp,
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": "ssot_v12_empty_html_no_prose",
                    "filename": fn,
                    "effective_format": fmt,
                    "primary_kind": None,
                    "status": "stub_or_blank",
                    "congress": det_cong,
                    "chamber": det_ch,
                    "committees": det_cmts,
                    "docmeta_json": t_json,
                    "strict_v4_valid": True,
                }
            )
            stats_v6_2["triaged_empty_cms_html_no_prose"] += 1
            continue

        from_ssot = sb_bytes in ssot_windows
        if from_ssot:
            ssot_win, ssot_cov_p12, ssot_p3_slice, ssot_ttf_json = ssot_windows[sb_bytes]
            raw_txt = ssot_win.strip()
            text_src_label = "body_text_ssot_v12_head_tail_9000"
            is_cov_p12 = bool(ssot_cov_p12 or q_old["is_cover_roster_p12"])
            p3_slice = ssot_p3_slice or q_old["p3_toc_or_gavel_slice"]
            stapled_ttf_json = ssot_ttf_json or q_old["stapled_ttf_disclosure_json"]
            stats_v6_2["queue_hydrated_from_ssot"] += 1
        else:
            raw_txt = str(q_old["p12_raw_text"] or q_old["p12_clean_text"] or "").strip()
            text_src_label = str(q_old["text_source"] or "cold_r2_fallback")
            is_cov_p12 = bool(q_old["is_cover_roster_p12"])
            p3_slice = q_old["p3_toc_or_gavel_slice"]
            stapled_ttf_json = q_old["stapled_ttf_disclosure_json"]
            if sb_hex in r2_usable_shas or eff_hex in r2_usable_shas or text_src_label.startswith("cold_r2") or text_src_label == "hydrated_r2":
                stats_v6_2["queue_fallback_cold_r2_excerpt"] += 1
            else:
                stats_v6_2["queue_fallback_local_excerpt"] += 1

        old_raw_txt = str(q_old["p12_raw_text"] or "").strip()
        old_clean_txt = str(q_old["p12_clean_text"] or "").strip()
        text_changed = (raw_txt != old_raw_txt) or (p3_slice != q_old["p3_toc_or_gavel_slice"])

        if text_changed:
            stats_v6_2["queue_text_window_upgraded"] += 1
            is_h = pv6.infer_is_html_v6(fn, raw_txt, explicit_format=fmt or None)
            clean_s, cfam, sc_strip = pv6.clean_html_and_cms_v6(raw_txt, is_html=is_h)
            rep_s, moj_rules = h6.repair_bgsdd_mojibake_v6(
                clean_s,
                filename=fn,
                is_gpo=fn.upper().startswith(("CHRG-", "HHRG-", "BILLS-", "CRPT-", "CPRT-", "CDOC-")),
            )
            clean_txt = (rep_s.strip() or clean_s.strip() or raw_txt)[:WINDOW_MAX_CHARS]
            raw_final = (raw_txt or clean_txt)[:WINDOW_MAX_CHARS]

            # Check non-usable triage on newly hydrated SSOT text (e.g. archived WAF/404/empty shell)
            tr_hit = pv6.triage_non_usable_v6(
                clean_txt,
                filename=fn,
                explicit_format=fmt or None,
            )
            if tr_hit is not None:
                tr_dm = tr_hit["docmeta"]
                t_canon, t_json = build_grounded_triage_docmeta(
                    status=str(tr_dm["status"]),
                    text_quality=str(tr_dm.get("text_quality") or "native"),
                    base_reason=str(tr_dm.get("error_reason") or "Non-usable document detected on SSOT text"),
                    detail_title=list_titles[lr],
                    committees=det_cmts,
                    filename=fn,
                )
                master_out["partition_bucket"][lr] = "completed_no_llm"
                master_out["v6_route"][lr] = "deterministic_triage_non_usable"
                master_out["deterministic_status"][lr] = t_canon["status"]
                master_out["triage_error_reason"][lr] = t_canon["error_reason"]
                master_out["v6_locked_primary_kind"][lr] = None
                master_out["text_source"][lr] = text_src_label
                completed_v6_2.append(
                    {
                        "list_row": lr,
                        "link_key": link_keys_bin[lr],
                        "link_key_hex": link_keys_hex[lr],
                        "doc_key": doc_keys[lr],
                        "saved_body": saved_bodies_bin[lr],
                        "saved_body_hex": saved_bodies_hex[lr],
                        "effective_body_sha_hex": eff_bodies_hex[lr],
                        "package_id": package_ids[lr],
                        "rn": rn_val,
                        "disposition": disp,
                        "v6_route": "deterministic_triage_non_usable",
                        "zero_llm_source": f"ssot_v6_2_triage_{t_canon['status']}",
                        "filename": fn,
                        "effective_format": fmt,
                        "primary_kind": None,
                        "status": t_canon["status"],
                        "congress": det_cong,
                        "chamber": det_ch,
                        "committees": det_cmts,
                        "docmeta_json": t_json,
                        "strict_v4_valid": True,
                    }
                )
                stats_v6_2[f"triaged_on_ssot_text:{t_canon['status']}"] += 1
                continue

            # Refresh citations & RefSpec oracle flags over the expanded `hybrid_9000_r0.72` window
            cit_new = cs6.extract_citations_and_signals_v6(
                clean_txt,
                filename=fn,
                congress=det_cong,
                oracles=refspec_oracles,
            )
            det_refs = list(dict.fromkeys([*(q_old["det_refs"] or ()), *(cit_new.get("det_refs") or ())]))[:25]
            det_sts = list(dict.fromkeys([*(q_old["det_short_titles"] or ()), *(cit_new.get("det_short_titles") or ())]))[:8]
            det_fys = list(
                dict.fromkeys(
                    [int(y) for y in (q_old["det_fiscal_years"] or ()) if y is not None]
                    + [int(y) for y in (cit_new.get("det_fiscal_years") or ()) if y is not None]
                )
            )[:12]
            usc_inv = list(
                dict.fromkeys([*(q_old["usc_oracle_invalid_refs"] or ()), *(cit_new.get("usc_oracle_invalid_refs") or ())])
            )

            # Refresh grammar / cover locks over newly hydrated WARC / CMS-HTML / repaired-PDF text
            locked_pk = q_old["locked_primary_kind"]
            lock_src = q_old["grammar_lock_source"]
            lock_id = q_old["lock_id"]
            if locked_pk is None:
                s_t1, k_t1 = pv6.detect_exact_tier1_signature_v5(fn, clean_txt, is_html=is_h)
                if k_t1 in pv6.DOC_KINDS_SET:
                    locked_pk = k_t1
                    lock_src = "tier1_ssot_v6_2"
                    lock_id = s_t1
                    stats_v6_2["newly_grammar_locked_tier1"] += 1
            if locked_pk is None:
                c_id, c_kind, c_src = pv6.detect_cover_or_sha_lock_v6(
                    fn,
                    clean_txt,
                    p12_lines=clean_txt,
                    body_sha_hex=saved_bodies_hex[lr],
                    bioguide_ids=list_bioguides[lr],
                    witness_keys=list_witness_keys[lr],
                    is_html=is_h,
                )
                if c_kind in pv6.DOC_KINDS_SET:
                    locked_pk = c_kind
                    lock_src = c_src or "cover_lock_ssot_v6_2"
                    lock_id = c_id
                    stats_v6_2["newly_grammar_locked_cover"] += 1

            # Refresh line-anchored persona seeds (with `panel` string & `"questioner"` role fixes!)
            wl_ps = h6.parse_witness_list_personas_v6(clean_txt, body_sha_hex=saved_bodies_hex[lr])
            gpo_ps = h6.parse_gpo_p12_personas_v6(clean_txt)
            gpo_p3_ps = h6.parse_gpo_p3_slice_personas_v6(p3_slice) if isinstance(p3_slice, str) and p3_slice else []
            hyg_d = {
                "p12_lines": clean_txt,
                "has_newlines": "\n" in clean_txt,
                "witness_list_personas_json": sanitize_personas_json_str(json.dumps(wl_ps), primary_kind=locked_pk, text=clean_txt, filename=fn) if wl_ps else None,
                "gpo_p12_personas_json": sanitize_personas_json_str(json.dumps(gpo_ps), primary_kind=locked_pk, text=clean_txt, filename=fn) if gpo_ps else None,
                "gpo_p3_personas_json": sanitize_personas_json_str(json.dumps(gpo_p3_ps), primary_kind=locked_pk, text=clean_txt, filename=fn) if gpo_p3_ps else None,
            }
            p_seed_cand = (
                q_old["personas_seed_json"]
                or hyg_d["witness_list_personas_json"]
                or hyg_d["gpo_p12_personas_json"]
                or hyg_d["gpo_p3_personas_json"]
            )
            p_seed = sanitize_personas_json_str(p_seed_cand, primary_kind=locked_pk, text=clean_txt, filename=fn)

            if cfam and not master_out["v6_cms_nav_family"][lr]:
                master_out["v6_cms_nav_family"][lr] = cfam
            if sc_strip:
                master_out["html_script_stripped"][lr] = True
            if moj_rules:
                master_out["mojibake_repaired"][lr] = True
        else:
            clean_txt = old_clean_txt[:WINDOW_MAX_CHARS]
            raw_final = (raw_txt or clean_txt)[:WINDOW_MAX_CHARS]
            det_refs = list(q_old["det_refs"] or ())
            det_sts = list(q_old["det_short_titles"] or ())
            det_fys = [int(y) for y in (q_old["det_fiscal_years"] or ()) if y is not None]
            usc_inv = list(q_old["usc_oracle_invalid_refs"] or ())
            locked_pk = q_old["locked_primary_kind"]
            lock_src = q_old["grammar_lock_source"]
            lock_id = q_old["lock_id"]
            hyg_d = None
            p_seed = sanitize_personas_json_str(
                q_old["personas_seed_json"],
                primary_kind=locked_pk,
                text=clean_txt,
                filename=fn,
            )

        # Attempt 100%-precision Zero-LLM synthesis on newly hydrated or previously fixed (`ordered->out`) bypass kinds!
        if locked_pk in ZERO_LLM_BYPASS_KINDS and (text_changed or locked_pk in ZERO_LLM_BYPASS_KINDS):
            rel_d = {k: rel_cols[k][lr] for k in rel_cols}
            prov_d = {k: prov_cols[k][lr] for k in prov_cols}
            cit_merged = {
                "det_refs": det_refs,
                "det_short_titles": det_sts,
                "det_fiscal_years": det_fys,
                "usc_oracle_invalid_refs": usc_inv,
            }
            if hyg_d is None:
                wl_ps2 = h6.parse_witness_list_personas_v6(clean_txt, body_sha_hex=saved_bodies_hex[lr])
                hyg_d = {
                    "p12_lines": clean_txt,
                    "has_newlines": "\n" in clean_txt,
                    "witness_list_personas_json": sanitize_personas_json_str(json.dumps(wl_ps2), primary_kind=locked_pk, text=clean_txt, filename=fn) if wl_ps2 else None,
                    "gpo_p12_personas_json": None,
                    "gpo_p3_personas_json": None,
                }
            known_d = json.loads(q_old["known_json"]) if q_old.get("known_json") else {}
            synth_cand = pv6.try_zero_llm_bypass_v6(
                locked_primary_kind=locked_pk,
                tier1_signature_id=lock_id,
                filename=fn,
                text=clean_txt,
                p12_lines=clean_txt,
                known_dict=known_d,
                provenance=prov_d,
                relational=rel_d,
                citations=cit_merged,
                hygiene=hyg_d,
            )
            if synth_cand is not None:
                try:
                    synth_post, _ = pv6.post_pass_v6(
                        synth_cand,
                        known=known_d,
                        filename=fn,
                        text=clean_txt,
                        p12_lines=clean_txt,
                        explicit_format=fmt or None,
                        provenance=prov_d,
                        relational=rel_d,
                        citations=cit_merged,
                        hygiene=hyg_d,
                    )
                    canon_s, j_str_s = finalize_and_validate_docmeta(synth_post)
                    g_chk = ar6.check_gist_title_grounding_v6(
                        canon_s,
                        text=clean_txt,
                        filename=fn,
                        known=known_d,
                    )
                    if g_chk["is_grounded"]:
                        master_out["partition_bucket"][lr] = "completed_no_llm"
                        master_out["v6_route"][lr] = "zero_llm_synthesized_docmeta"
                        master_out["deterministic_status"][lr] = canon_s["status"]
                        master_out["text_source"][lr] = text_src_label
                        master_out["v6_locked_primary_kind"][lr] = canon_s["primary_kind"]
                        master_out["v6_grammar_lock_source"][lr] = lock_src
                        master_out["v6_lock_id"][lr] = lock_id
                        master_out["det_refs_count"][lr] = len(det_refs)
                        master_out["det_short_titles_count"][lr] = len(det_sts)
                        master_out["det_fiscal_years_count"][lr] = len(det_fys)
                        master_out["has_usc_oracle_invalid"][lr] = len(usc_inv) > 0
                        completed_v6_2.append(
                            {
                                "list_row": lr,
                                "link_key": link_keys_bin[lr],
                                "link_key_hex": link_keys_hex[lr],
                                "doc_key": doc_keys[lr],
                                "saved_body": saved_bodies_bin[lr],
                                "saved_body_hex": saved_bodies_hex[lr],
                                "effective_body_sha_hex": eff_bodies_hex[lr],
                                "package_id": package_ids[lr],
                                "rn": rn_val,
                                "disposition": disp,
                                "v6_route": "zero_llm_synthesized_docmeta",
                                "zero_llm_source": f"ssot_v6_2_zero_llm_{canon_s['primary_kind']}",
                                "filename": fn,
                                "effective_format": fmt,
                                "primary_kind": canon_s["primary_kind"],
                                "status": canon_s["status"],
                                "congress": canon_s.get("congress") if canon_s.get("congress") is not None else det_cong,
                                "chamber": canon_s.get("chamber") or det_ch,
                                "committees": list(canon_s.get("committees") or det_cmts),
                                "docmeta_json": j_str_s,
                                "strict_v4_valid": True,
                            }
                        )
                        stats_v6_2[f"newly_zero_llm_synthesized:{canon_s['primary_kind']}"] += 1
                        continue
                except Exception:
                    pass

        # Update master columns & append to `llm_queue_v6_2`
        v6_rt = (
            "tier1_or_cover_or_anchor_grammar_locked"
            if locked_pk is not None
            else (
                "deterministic_enriched_open_kind"
                if (det_cong is not None or det_cmts or det_ch is not None or det_refs or det_sts or det_fys)
                else "llm_open_extraction"
            )
        )
        master_out["partition_bucket"][lr] = "llm_queue"
        master_out["v6_route"][lr] = v6_rt
        master_out["deterministic_status"][lr] = "usable" if locked_pk else "queued_llm"
        master_out["text_source"][lr] = text_src_label
        master_out["has_p12_newlines"][lr] = "\n" in clean_txt
        master_out["v6_locked_primary_kind"][lr] = locked_pk
        master_out["v6_grammar_lock_source"][lr] = lock_src
        master_out["v6_lock_id"][lr] = lock_id
        master_out["det_refs_count"][lr] = len(det_refs)
        master_out["det_short_titles_count"][lr] = len(det_sts)
        master_out["det_fiscal_years_count"][lr] = len(det_fys)
        master_out["has_usc_oracle_invalid"][lr] = len(usc_inv) > 0
        master_out["is_cover_roster_p12"][lr] = is_cov_p12
        master_out["has_p3_toc_or_gavel_rescue"][lr] = bool(p3_slice)

        llm_queue_v6_2.append(
            {
                "list_row": lr,
                "link_key": link_keys_bin[lr],
                "link_key_hex": link_keys_hex[lr],
                "doc_key": doc_keys[lr],
                "saved_body": saved_bodies_bin[lr],
                "saved_body_hex": saved_bodies_hex[lr],
                "effective_body_sha_hex": eff_bodies_hex[lr],
                "package_id": package_ids[lr],
                "rn": int(q_old["rn"]),
                "disposition": q_old["disposition"],
                "v6_route": v6_rt,
                "filename": fn,
                "effective_format": fmt,
                "text_source": text_src_label,
                "p12_raw_text": raw_final,
                "p12_clean_text": clean_txt,
                "known_json": q_old["known_json"],
                "locked_primary_kind": locked_pk,
                "grammar_lock_source": lock_src,
                "lock_id": lock_id,
                "rel_congress": q_old["rel_congress"],
                "rel_chamber": q_old["rel_chamber"],
                "rel_committees": list(q_old["rel_committees"] or ()),
                "rel_event_id": q_old["rel_event_id"],
                "rel_event_date": q_old["rel_event_date"],
                "rel_event_title": q_old["rel_event_title"],
                "rel_event_type": q_old["rel_event_type"],
                "rel_venue": q_old["rel_venue"],
                "personas_seed_json": p_seed,
                "det_refs": det_refs,
                "det_short_titles": det_sts,
                "det_fiscal_years": det_fys,
                "usc_oracle_invalid_refs": usc_inv,
                "hsru_host_status": q_old["hsru_host_status"],
                "is_cover_roster_p12": is_cov_p12,
                "p3_toc_or_gavel_slice": p3_slice,
                "stapled_ttf_disclosure_json": stapled_ttf_json,
            }
        )

    # Build `sha_dup_alias_v6_2` (`188` rows) with refreshed `canonical_partition_bucket` & `canonical_v6_route`
    sha_dup_alias_v6_2: list[dict[str, Any]] = []
    for lr in alias_lrs:
        a_old = alias_v61_by_lr[lr]
        canon_lr = int(a_old["canonical_list_row"])
        sha_dup_alias_v6_2.append(
            {
                "list_row": lr,
                "link_key": link_keys_bin[lr],
                "link_key_hex": link_keys_hex[lr],
                "doc_key": doc_keys[lr],
                "saved_body": saved_bodies_bin[lr],
                "saved_body_hex": saved_bodies_hex[lr],
                "effective_body_sha_hex": eff_bodies_hex[lr],
                "package_id": package_ids[lr],
                "rn": int(a_old["rn"]),
                "disposition": a_old["disposition"],
                "sub_disposition": a_old["sub_disposition"],
                "v6_route": "sha_dup_alias",
                "filename": a_old["filename"],
                "effective_format": a_old["effective_format"],
                "canonical_list_row": canon_lr,
                "canonical_link_key": link_keys_bin[canon_lr],
                "canonical_link_key_hex": link_keys_hex[canon_lr],
                "canonical_doc_key": doc_keys[canon_lr],
                "canonical_rn": int(a_old["canonical_rn"]),
                "canonical_partition_bucket": master_out["partition_bucket"][canon_lr],
                "canonical_v6_route": master_out["v6_route"][canon_lr],
            }
        )

    # 4. Exhaustive Conservation, Uniqueness & `strict_validate_v4` Gates
    print("[4/5] Running strict conservation, identity, and `strict_validate_v4` gates...", flush=True)
    assert len(completed_v6_2) + len(llm_queue_v6_2) + len(sha_dup_alias_v6_2) == EXPECTED_TOTAL_ROWS, (
        f"Conservation failure: {len(completed_v6_2)} + {len(llm_queue_v6_2)} + {len(sha_dup_alias_v6_2)} != {EXPECTED_TOTAL_ROWS}"
    )
    assert len(sha_dup_alias_v6_2) == 188

    comp_lks = [r["link_key_hex"] for r in completed_v6_2]
    queue_lks = [r["link_key_hex"] for r in llm_queue_v6_2]
    alias_lks = [r["link_key_hex"] for r in sha_dup_alias_v6_2]
    union_lks = set(comp_lks) | set(queue_lks) | set(alias_lks)
    assert len(comp_lks) == len(set(comp_lks)), "Duplicate link_key_hex in completed_no_llm_v6_2!"
    assert len(queue_lks) == len(set(queue_lks)), "Duplicate link_key_hex in llm_queue_v6_2!"
    assert len(alias_lks) == len(set(alias_lks)), "Duplicate link_key_hex in sha_dup_alias_v6_2!"
    assert len(union_lks) == EXPECTED_TOTAL_ROWS, "Partition overlap or missing link_key_hex!"
    assert union_lks == set(link_keys_hex), "link_key_hex set mismatch vs 55c14dcda87a detail.parquet!"

    for row in completed_v6_2:
        assert row["link_key_hex"] and len(row["link_key_hex"]) == 16
        assert row["saved_body_hex"] and len(row["saved_body_hex"]) == 64
        assert row["effective_body_sha_hex"] and len(row["effective_body_sha_hex"]) == 64
        assert row["doc_key"]
        dj = row["docmeta_json"]
        assert isinstance(dj, str) and dj.startswith("{"), f"NULL/empty docmeta_json at list_row={row['list_row']}!"
        ok_sv4, errs_sv4 = strict_validate_v4(dj)
        assert ok_sv4 and errs_sv4 == [], f"strict_validate_v4 failed at list_row={row['list_row']}: {errs_sv4}"

    for row in llm_queue_v6_2:
        assert row["link_key_hex"] and len(row["link_key_hex"]) == 16
        assert row["saved_body_hex"] and len(row["saved_body_hex"]) == 64
        assert row["effective_body_sha_hex"] and len(row["effective_body_sha_hex"]) == 64
        assert row["doc_key"]
        assert row["saved_body_hex"].lower() not in excluded_by_sha, f"Excluded body leaked into llm_queue_v6_2: {row['list_row']}"
        assert row["effective_body_sha_hex"].lower() not in excluded_by_sha, f"Excluded eff_body leaked into llm_queue_v6_2: {row['list_row']}"
        assert isinstance(row["p12_raw_text"], str) and row["p12_raw_text"].strip(), f"Empty p12_raw_text at list_row={row['list_row']}"
        assert isinstance(row["p12_clean_text"], str) and row["p12_clean_text"].strip(), f"Empty p12_clean_text at list_row={row['list_row']}"
        assert len(row["p12_raw_text"]) <= WINDOW_MAX_CHARS
        assert len(row["p12_clean_text"]) <= WINDOW_MAX_CHARS
        assert "\x00" not in row["p12_clean_text"], f"NUL byte leaked into p12_clean_text at list_row={row['list_row']}"

    def _cast_identity_cols(tbl: pa.Table) -> pa.Table:
        fields: list[pa.Field] = []
        cols: list[pa.Array] = []
        for f in tbl.schema:
            col = tbl[f.name]
            if f.name in ("link_key", "canonical_link_key"):
                col = col.cast(pa.binary(8))
                fields.append(pa.field(f.name, pa.binary(8), nullable=False))
            elif f.name == "saved_body":
                col = col.cast(pa.binary(32))
                fields.append(pa.field(f.name, pa.binary(32), nullable=False))
            elif f.name in ("list_row", "canonical_list_row", "rn", "canonical_rn"):
                col = col.cast(pa.int32())
                fields.append(pa.field(f.name, pa.int32(), nullable=False))
            else:
                fields.append(f)
            cols.append(col)
        return pa.Table.from_arrays(cols, schema=pa.schema(fields))

    # 5. Write `parquets_v6_2/*.parquet`, compatibility symlinks, report, `MANIFEST_v6_2.json`, & `SHA256SUMS_v6_2.json`
    print("[5/5] Writing zstd Parquets (`row_group_size=32768`), symlinks, and `v6_2` manifests...", flush=True)
    master_pa = _cast_identity_cols(pa.Table.from_pydict(master_out))
    comp_pa = _cast_identity_cols(pa.Table.from_pylist(completed_v6_2))
    queue_pa = _cast_identity_cols(pa.Table.from_pylist(llm_queue_v6_2))
    alias_pa = _cast_identity_cols(pa.Table.from_pylist(sha_dup_alias_v6_2))

    meta_master = write_parquet_atomic_v6_2(master_pa, PARQUETS_V6_2_DIR / "deterministic_323k_v6_2.parquet", out_root, compression_level=9)
    meta_comp = write_parquet_atomic_v6_2(comp_pa, PARQUETS_V6_2_DIR / "completed_no_llm_v6_2.parquet", out_root, compression_level=9)
    meta_queue = write_parquet_atomic_v6_2(queue_pa, PARQUETS_V6_2_DIR / "llm_queue_v6_2.parquet", out_root, compression_level=9)
    meta_alias = write_parquet_atomic_v6_2(alias_pa, PARQUETS_V6_2_DIR / "sha_dup_alias_v6_2.parquet", out_root, compression_level=9)

    # Create relative canonical symlinks in `parquets_v6_2/` so `corpus_quality_audit.py --docmeta-dir parquets_v6_2` resolves seamlessly
    for link_name, target_name in (
        ("deterministic_323k.parquet", "deterministic_323k_v6_2.parquet"),
        ("completed_no_llm.parquet", "completed_no_llm_v6_2.parquet"),
        ("llm_queue.parquet", "llm_queue_v6_2.parquet"),
        ("sha_dup_alias.parquet", "sha_dup_alias_v6_2.parquet"),
    ):
        link_p = PARQUETS_V6_2_DIR / link_name
        if link_p.is_symlink() or link_p.exists():
            link_p.unlink()
        link_p.symlink_to(target_name)

    REPORTS_V6_2_DIR.mkdir(parents=True, exist_ok=True)
    v6_2_route_counts = Counter(master_out["v6_route"])
    comp_route_counts = Counter(r["v6_route"] for r in completed_v6_2)
    comp_source_counts = Counter(r["zero_llm_source"] for r in completed_v6_2)
    queue_route_counts = Counter(r["v6_route"] for r in llm_queue_v6_2)
    queue_text_sources = Counter(r["text_source"] for r in llm_queue_v6_2)
    queue_locked_count = sum(1 for r in llm_queue_v6_2 if r["locked_primary_kind"] is not None)
    queue_gt_8000 = sum(1 for r in llm_queue_v6_2 if len(r["p12_clean_text"]) > 8000)

    report_path = REPORTS_V6_2_DIR / "v6_2_ssot_sidecar_report.json"
    report_obj = {
        "bundle_version": "docmeta-v6_2-20261116",
        "parent_bundle_version": "docmeta-v6_1-20261116",
        "selected_release_id": EXPECTED_RELEASE_ID,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "ssot_hydration_policy": {
            "export_parquet_path": str(ssot.export_path),
            "export_parquet_rows": ssot.rows,
            "export_footer_sha256": ssot_info["footer_sha256"],
            "selection_json_path": str(V12_SELECTION_JSON),
            "selection_excluded_bodies_total": len(excluded_by_sha),
            "selection_newly_excluded_v12_bodies": 390,
            "window_policy": "hybrid_9000_r0.72",
            "max_chars": WINDOW_MAX_CHARS,
            "head_ratio": WINDOW_HEAD_RATIO,
            "head_budget_chars": WINDOW_HEAD_BUDGET,
            "tail_chars": WINDOW_TAIL_CHARS,
        },
        "conservation": {
            "total_rows": EXPECTED_TOTAL_ROWS,
            "completed_no_llm_v6_2": len(completed_v6_2),
            "llm_queue_v6_2": len(llm_queue_v6_2),
            "sha_dup_alias_v6_2": len(sha_dup_alias_v6_2),
            "partition_check": f"{len(completed_v6_2)} + {len(llm_queue_v6_2)} + {len(sha_dup_alias_v6_2)} == {EXPECTED_TOTAL_ROWS}",
            "delta_completed_vs_v6_1": len(completed_v6_2) - len(comp_v61_by_lr),
            "delta_llm_queue_vs_v6_1": len(llm_queue_v6_2) - len(queue_v61_by_lr),
            "unique_link_key_hex": len(union_lks),
            "completed_null_docmeta_json": 0,
            "completed_strict_validate_v4_passed": f"{len(completed_v6_2)}/{len(completed_v6_2)} (100.0%)",
            "llm_queue_empty_raw_or_clean_text": 0,
            "llm_queue_excluded_bodies_leaked": 0,
            "llm_queue_grammar_locked_rows": queue_locked_count,
            "llm_queue_windows_8001_to_9000_chars": queue_gt_8000,
        },
        "v6_2_transition_stats": dict(sorted(stats_v6_2.items(), key=lambda kv: -kv[1])),
        "llm_queue_v6_2_text_sources": dict(sorted(queue_text_sources.items(), key=lambda kv: -kv[1])),
        "route_counts_323k_v6_2": dict(sorted(v6_2_route_counts.items(), key=lambda kv: -kv[1])),
        "completed_v6_2_routes": dict(sorted(comp_route_counts.items(), key=lambda kv: -kv[1])),
        "completed_v6_2_sources_top30": dict(comp_source_counts.most_common(30)),
        "llm_queue_v6_2_routes": dict(sorted(queue_route_counts.items(), key=lambda kv: -kv[1])),
        "parquets_v6_2": [meta_master, meta_comp, meta_queue, meta_alias],
    }
    report_path.write_text(json.dumps(report_obj, indent=2) + "\n", encoding="utf-8")

    # Verify BOTH `v6` (`37` files) and `v6_1` (`6` files) pinned files remain 100% untouched!
    pinned_v6 = verify_pinned_sums_untouched(SIDECAR_ROOT / "SHA256SUMS.json", 37)
    pinned_v6_1 = verify_pinned_sums_untouched(SIDECAR_ROOT / "SHA256SUMS_v6_1.json", 6)
    print(f"  -> Verified {pinned_v6}/37 `v6` and {pinned_v6_1}/6 `v6_1` pinned files 100% untouched!", flush=True)

    script_self = Path(__file__).resolve()
    script_rel = "scripts_v6_2/build_v6_2_ssot_sidecar.py"  # the name earlier manifests list this script under
    tracked_v6_2_paths = [
        PARQUETS_V6_2_DIR / "completed_no_llm_v6_2.parquet",
        PARQUETS_V6_2_DIR / "deterministic_323k_v6_2.parquet",
        PARQUETS_V6_2_DIR / "llm_queue_v6_2.parquet",
        PARQUETS_V6_2_DIR / "sha_dup_alias_v6_2.parquet",
        report_path,
        script_self,
    ]
    files_list: list[dict[str, Any]] = []
    files_by_path: dict[str, dict[str, Any]] = {}
    sha_map: dict[str, str] = {}
    parquet_meta_by_rel = {m["path"]: m for m in (meta_master, meta_comp, meta_queue, meta_alias)}

    rel_of = {fp: script_rel if fp == script_self else str(fp.relative_to(out_root)) for fp in tracked_v6_2_paths}
    for fp in sorted(tracked_v6_2_paths, key=rel_of.__getitem__):
        rel_s = rel_of[fp]
        raw_b = fp.read_bytes()
        digest = hashlib.sha256(raw_b).hexdigest()
        sz = len(raw_b)
        entry: dict[str, Any] = {
            "path": rel_s,
            "bytes": sz,
            "size": sz,
            "sha256": digest,
        }
        if rel_s in parquet_meta_by_rel:
            entry["rows"] = parquet_meta_by_rel[rel_s]["rows"]
            entry["row_groups"] = parquet_meta_by_rel[rel_s]["row_groups"]
        files_list.append(entry)
        files_by_path[rel_s] = {k: v for k, v in entry.items() if k != "path"}
        sha_map[rel_s] = digest

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_v6_2 = {
        "bundle_id": "docmeta-v6_2-20261116",
        "parent_bundle_id": "docmeta-v6_1-20261116",
        "selected_release_id": EXPECTED_RELEASE_ID,
        "created_at": now_iso,
        "code_repository": "congressional-tech",
        "code_package": "congress_docmeta",
        "remediation_script": "scripts_v6_2/build_v6_2_ssot_sidecar.py",
        "ssot_hydration_policy": report_obj["ssot_hydration_policy"],
        "identity_columns": [
            "list_row",
            "link_key",
            "link_key_hex",
            "doc_key",
            "saved_body",
            "saved_body_hex",
            "effective_body_sha_hex",
            "package_id",
        ],
        "row_counts": {
            "total_rows": EXPECTED_TOTAL_ROWS,
            "completed_no_llm_v6_2": len(completed_v6_2),
            "llm_queue_v6_2": len(llm_queue_v6_2),
            "sha_dup_alias_v6_2": len(sha_dup_alias_v6_2),
            "partition_check": f"{len(completed_v6_2)} + {len(llm_queue_v6_2)} + {len(sha_dup_alias_v6_2)} == {EXPECTED_TOTAL_ROWS}",
            "completed_null_docmeta_json": 0,
            "completed_strict_validate_v4_valid": len(completed_v6_2),
            "llm_queue_empty_text_rows": 0,
            "llm_queue_excluded_bodies_leaked": 0,
            "v6_2_route_counts": dict(sorted(v6_2_route_counts.items(), key=lambda kv: -kv[1])),
            "parquets": {m["path"]: m["rows"] for m in (meta_master, meta_comp, meta_queue, meta_alias)},
            "row_groups": {m["path"]: m["row_groups"] for m in (meta_master, meta_comp, meta_queue, meta_alias)},
        },
        "v6_2_transition_stats": report_obj["v6_2_transition_stats"],
        "llm_queue_v6_2_text_sources": report_obj["llm_queue_v6_2_text_sources"],
        "file_count": len(files_list),
        "total_logical_bytes": sum(e["bytes"] for e in files_list),
        "pinned_v6_files_verified_untouched": pinned_v6,
        "pinned_v6_1_files_verified_untouched": pinned_v6_1,
        "files": files_list,
        "files_by_path": files_by_path,
    }
    (out_root / "MANIFEST_v6_2.json").write_text(json.dumps(manifest_v6_2, indent=2) + "\n", encoding="utf-8")

    sha256sums_v6_2 = {
        "bundle_id": "docmeta-v6_2-20261116",
        "selected_release_id": EXPECTED_RELEASE_ID,
        "generated_at": now_iso,
        "file_count": len(files_list),
        "total_logical_bytes": sum(e["bytes"] for e in files_list),
        "sha256": sha_map,
        "files": files_by_path,
    }
    (out_root / "SHA256SUMS_v6_2.json").write_text(json.dumps(sha256sums_v6_2, indent=2) + "\n", encoding="utf-8")

    print("\n=== SUCCESS: Layer I1b (`v6_2` BodyTextSSOT Sidecar) Complete ===", flush=True)
    print(json.dumps(report_obj["conservation"], indent=2), flush=True)
    print("Transition stats:", json.dumps(report_obj["v6_2_transition_stats"], indent=2), flush=True)
    print("Parquets:", json.dumps(report_obj["parquets_v6_2"], indent=2), flush=True)


if __name__ == "__main__":
    main()
