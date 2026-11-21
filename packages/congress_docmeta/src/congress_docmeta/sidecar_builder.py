#!/usr/bin/env python3
"""Release-parameterized DocMeta V6 sidecar builder (`ct-0zry`).

100% Python standard library at import time (`/usr/bin/python3 -B -I -S` clean); `pyarrow` and
`viewer_publication.body_text_ssot` are imported lazily when building a sidecar.

Takes any published release directory (`manifest.json`, `list.parquet`, `detail.parquet`, plus optional
`meetings.parquet`, `witnesses.parquet`, `people.parquet`, `bills.parquet`, `committee_records.parquet`,
`sources.parquet`), optional `BodyTextSSOT` export directory, and optional `body_text` selection JSON/gzip,
applies current DocMeta V6 rules (including R4-R8 and `ct-2cig` lock guards), and writes the three canonical
sidecar parts atomically:
  1. `completed_no_llm.parquet` (`100%` `strict_validate_v4` valid)
  2. `llm_queue.parquet` (`run_docmeta_parquet_sweep`-compatible queue)
  3. `sha_dup_alias.parquet` (exact `saved_body` duplicate aliases mapped to canonical `link_key_hex`)
plus `sidecar_manifest.json`.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import datetime
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse

WINDOW_MAX_CHARS = 9_000
WINDOW_HEAD_RATIO = 0.72
WINDOW_TAIL_CHARS = 2_520
WINDOW_HEAD_BUDGET = WINDOW_MAX_CHARS - WINDOW_TAIL_CHARS  # 6,480
ROW_GROUP_SIZE_TARGET = 32_768

ZERO_LLM_BYPASS_KINDS: frozenset[str] = frozenset(
    {
        "truth_in_testimony_disclosure",
        "attendance_quorum_sheet",
        "witness_list",
        "legislative_schedule_or_calendar",
    }
)

GENERIC_EMPTY_CMS_BANNERS: frozenset[str] = frozenset(
    {
        "the official u.s. congressional website of the republican budget committee",
        "the official u.s. congressional website of the house budget committee",
    }
)


def _read_json_or_gz(path: Path) -> Any:
    raw = path.read_bytes()
    if path.suffix.lower() == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _infer_effective_format(fmt: Any, saved_suffix: Any, saved_media_type: Any, filename: str) -> str:
    for cand in (fmt, saved_suffix):
        if isinstance(cand, str) and cand.strip():
            s = cand.strip().lower().lstrip(".")
            if s in ("htm", "xhtml", "aspx", "php"):
                return "html"
            return s
    mt = str(saved_media_type or "").lower()
    if "pdf" in mt:
        return "pdf"
    if "html" in mt:
        return "html"
    if "xml" in mt:
        return "xml"
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext in ("htm", "aspx", "php"):
        return "html"
    return ext or "bin"


def _has_r8_deps() -> bool:
    from .silicon_runtime_v6 import check_r8_dependencies

    return len(check_r8_dependencies(strict=False)) == 0


def build_hybrid_ssot_window(
    text: str,
    page_offsets: Sequence[int],
    *,
    max_chars: int = WINDOW_MAX_CHARS,
    tail_chars: int = WINDOW_TAIL_CHARS,
    head_budget: int = WINDOW_HEAD_BUDGET,
) -> tuple[str, bool, str | None, str | None]:
    """Compute `(window_text, is_cover_roster_p12, p3_toc_or_gavel_slice, stapled_ttf_disclosure_json)`."""
    from viewer_publication.body_text_slices import head_tail_window, slice_pages
    from . import multipage_rules_v5 as mp5

    n_pages = len(page_offsets)
    if n_pages <= 1:
        win = head_tail_window(text, page_offsets, max_chars=max_chars, head_pages=2, tail_chars=tail_chars)
        return win, False, None, None

    if len(text) <= max_chars:
        eff_head_pages = n_pages
    else:
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


def _sanitize_persona_dict(p: Mapping[str, Any], valid_roles: frozenset[str], valid_etypes: frozenset[str], key_order: tuple[str, ...]) -> dict[str, Any] | None:
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
    if role not in valid_roles:
        return None
    etype = str(p.get("entity_type") or "non_gov_person").strip()
    if etype not in valid_etypes:
        etype = "non_gov_person"

    out: dict[str, Any] = {}
    for k in key_order:
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


def build_release_sidecar(
    release_dir: str | Path,
    out_root: str | Path,
    *,
    body_text_export_dir: str | Path | None = None,
    selection_path: str | Path | None = None,
    limit: int | None = None,
    link_keys: set[str] | None = None,
    compression_level: int = 6,
) -> dict[str, Any]:
    """Build `completed_no_llm.parquet`, `llm_queue.parquet`, and `sha_dup_alias.parquet` for `release_dir`."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from . import (
        anomaly_router_v6 as ar6,
        citations_and_signals_v6 as cs6,
        cover_locks_v6 as cl6,
        hygiene_and_line_parsers_v6 as h6,
        provenance_rules_v5 as pr5,
        pythonic_v5 as pv5,
        pythonic_v6 as pv6,
        relational_rules_v6 as rv6,
        schema_v4 as s4,
    )

    t0 = time.perf_counter()
    rel_dir = Path(release_dir).expanduser().resolve()
    out_dir = Path(out_root).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_p = rel_dir / "manifest.json"
    release_id = (
        str(json.loads(manifest_p.read_text(encoding="utf-8")).get("release_id") or rel_dir.name)
        if manifest_p.is_file()
        else rel_dir.name
    )

    excluded_by_sha: dict[str, dict[str, Any]] = {}
    if selection_path is not None:
        sel_p = Path(selection_path).expanduser().resolve()
        if sel_p.is_file():
            sel_obj = _read_json_or_gz(sel_p)
            for e in sel_obj.get("excluded_bodies") or ():
                if isinstance(e, Mapping) and e.get("body_sha256"):
                    excluded_by_sha[str(e["body_sha256"]).strip().lower()] = dict(e)

    valid_roles = frozenset(pv5.SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["role"]["enum"])
    valid_etypes = frozenset(pv5.SCHEMA_OBJ["properties"]["personas"]["items"]["properties"]["entity_type"]["enum"])
    key_order = rv6.PERSONA_KEYS_ORDER_V6
    r8_ready = _has_r8_deps()

    def _finalize(raw_obj: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        working = dict(raw_obj)
        for dt_k in ("doc_date", "event_date", "due_date"):
            if isinstance(working.get(dt_k), datetime.date):
                working[dt_k] = working[dt_k].isoformat()
        if "personas" in working and isinstance(working["personas"], Sequence) and not isinstance(working["personas"], str):
            ps = [
                sp
                for item in working["personas"]
                if isinstance(item, Mapping)
                for sp in [_sanitize_persona_dict(item, valid_roles, valid_etypes, key_order)]
                if sp is not None
            ]
            if ps:
                working["personas"] = ps[: s4.MAX_PERSONAS]
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
            working["gist"] = (" ".join(gw[:22]).rstrip(" ,;:-–—") + ".") if len(gw) > 22 else " ".join(gw)

        canon = pv5.canonicalize_docmeta_v4(working)
        j_str = json.dumps(canon, separators=(",", ":"), ensure_ascii=False)
        ok_s, errs_s = pv5.validate_docmeta_v4_all(j_str)
        if not ok_s:
            raise ValueError(f"strict_validate_v4 failed: {errs_s}")
        return canon, j_str

    def _triage_docmeta(*, status: str, text_quality: str, base_reason: str, detail_title: str | None, committees: Sequence[str], filename: str) -> tuple[dict[str, Any], str]:
        ctx_parts: list[str] = []
        if isinstance(detail_title, str) and detail_title.strip():
            norm_title = re.sub(r"\s+", " ", detail_title).strip()[:65]
            ctx_parts.append(f"title={norm_title}")
        if committees:
            ctx_parts.append(f"committee={str(committees[0]).strip()[:50]}")
        elif filename.strip():
            ctx_parts.append(f"file={filename.strip()[:45]}")
        reason = f"{base_reason.strip()} ({'; '.join(ctx_parts)})" if ctx_parts else base_reason.strip()
        return _finalize(
            {
                "status": status,
                "text_quality": text_quality,
                "error_reason": re.sub(r"\s+", " ", reason).strip()[:200],
            }
        )

    # 1. Read `detail.parquet` (filtering to `link_keys` / `limit` when requested)
    detail_cols = [
        "link_key", "saved_body", "saved_suffix", "saved_media_type", "package_id",
        "description", "main_content", "selected_text", "filename", "title",
        "document_kind", "committee_keys", "chambers", "congress", "format",
        "document_date", "meeting_keys", "measure_keys", "bioguide_ids", "witness_keys",
    ]
    avail_detail_cols = [c for c in detail_cols if c in set(pq.read_schema(rel_dir / "detail.parquet").names)]
    detail_tbl = pq.read_table(rel_dir / "detail.parquet", columns=avail_detail_cols)
    all_detail_rows = detail_tbl.to_pylist()
    del detail_tbl

    selected_indices: list[int] = []
    norm_link_keys = {k.strip().lower() for k in link_keys} if link_keys else None
    for idx, r in enumerate(all_detail_rows):
        lk_hex = bytes(r["link_key"]).hex()
        if norm_link_keys is not None and lk_hex not in norm_link_keys:
            continue
        selected_indices.append(idx)
        if limit is not None and len(selected_indices) >= int(limit):
            break

    target_set = set(selected_indices)

    # 2. Load optional relational tables (`meetings`, `witnesses`, `people`, `bills`, `committee_records`, `sources`)
    meetings_by_id: dict[str, dict[str, Any]] = {}
    if (rel_dir / "meetings.parquet").is_file():
        needed_mkeys = {mk for idx in selected_indices for mk in (all_detail_rows[idx].get("meeting_keys") or ()) if mk}
        if needed_mkeys:
            m_cols = [c for c in ("event_id", "chamber", "title", "meeting_date", "meeting_type", "sittings", "committees", "congress", "not_held") if c in set(pq.read_schema(rel_dir / "meetings.parquet").names)]
            for mr in pq.read_table(rel_dir / "meetings.parquet", columns=m_cols).to_pylist():
                eid = str(mr.get("event_id") or "")
                if eid in needed_mkeys:
                    meetings_by_id[eid] = mr

    rosters_lookup = rv6.load_rosters_lookup_v6(required=False)
    people_by_key: dict[str, dict[str, Any]] = {}
    witnesses_by_key: dict[str, dict[str, Any]] = {}
    needed_wkeys = {wk for idx in selected_indices for wk in (all_detail_rows[idx].get("witness_keys") or ()) if wk}
    if needed_wkeys and (rel_dir / "witnesses.parquet").is_file():
        w_cols = [c for c in ("witness_key", "name", "rank", "credentials", "position", "organization", "on_behalf_of", "location", "panel", "panel_order", "witness_type", "bioguide_id", "matched_bioguide_id", "person_key") if c in set(pq.read_schema(rel_dir / "witnesses.parquet").names)]
        for wr in pq.read_table(rel_dir / "witnesses.parquet", columns=w_cols).to_pylist():
            wk = str(wr.get("witness_key") or "")
            if wk in needed_wkeys:
                witnesses_by_key[wk] = wr
        needed_pkeys = {str(w.get("person_key") or "") for w in witnesses_by_key.values() if w.get("person_key")}
        if needed_pkeys and (rel_dir / "people.parquet").is_file():
            p_cols = [c for c in ("person_key", "bioguide_id", "name", "rank", "credentials") if c in set(pq.read_schema(rel_dir / "people.parquet").names)]
            for pr in pq.read_table(rel_dir / "people.parquet", columns=p_cols).to_pylist():
                pk_s = str(pr.get("person_key") or "")
                if pk_s in needed_pkeys:
                    people_by_key[pk_s] = pr

    sources_by_lr: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if (rel_dir / "sources.parquet").is_file() and target_set:
        s_cols = [c for c in ("list_row", "url", "member_path", "listed_on", "link_text") if c in set(pq.read_schema(rel_dir / "sources.parquet").names)]
        pf_src = pq.ParquetFile(rel_dir / "sources.parquet")
        for rb in pf_src.iter_batches(batch_size=8192, columns=s_cols):
            for sr in rb.to_pylist():
                lr_val = int(sr["list_row"])
                if lr_val in target_set:
                    sources_by_lr[lr_val].append(sr)

    # 3. Assign `rn` per `saved_body_hex` and identify needed SSOT bodies
    sb_seen_counts: Counter[str] = Counter()
    canonical_lr_by_sb: dict[str, int] = {}
    row_rns: dict[int, int] = {}
    needed_sbs: set[bytes] = set()

    for lr in selected_indices:
        r = all_detail_rows[lr]
        sb_b = bytes(r["saved_body"]) if r.get("saved_body") is not None else (b"\x00" * 32)
        sb_hex = sb_b.hex()
        sb_seen_counts[sb_hex] += 1
        rn_val = sb_seen_counts[sb_hex]
        row_rns[lr] = rn_val
        if rn_val == 1:
            canonical_lr_by_sb[sb_hex] = lr
            if sb_hex not in excluded_by_sha and sb_b != (b"\x00" * 32):
                needed_sbs.add(sb_b)

    # 4. Stream `BodyTextSSOT` (`export.parquet`) in bounded 1,024-row batches when provided
    ssot_windows: dict[bytes, tuple[str, bool, str | None, str | None]] = {}
    export_parquet_path: Path | None = None
    if body_text_export_dir is not None and needed_sbs:
        bt_dir = Path(body_text_export_dir).expanduser().resolve()
        cand_pq = bt_dir if bt_dir.is_file() else (bt_dir / "export.parquet")
        if cand_pq.is_file():
            export_parquet_path = cand_pq
            pf_ssot = pq.ParquetFile(cand_pq)
            for rb in pf_ssot.iter_batches(batch_size=1024, columns=["saved_body", "text", "page_offsets"]):
                for sb_raw, txt_s, offs in zip(
                    rb.column(0).to_pylist(),
                    rb.column(1).to_pylist(),
                    rb.column(2).to_pylist(),
                ):
                    sb_bytes = bytes(sb_raw)
                    if sb_bytes in needed_sbs:
                        ssot_windows[sb_bytes] = build_hybrid_ssot_window(txt_s or "", offs or ())

    refspec_oracles = cs6.get_cached_refspec_oracles_v6()
    usc_oracle = pv6.load_default_usc_oracle_v6()

    completed_rows: list[dict[str, Any]] = []
    queue_rows: list[dict[str, Any]] = []
    alias_indices: list[int] = []
    bucket_by_lr: dict[int, tuple[str, str]] = {}
    stats: Counter[str] = Counter()

    for lr in selected_indices:
        r = all_detail_rows[lr]
        lk_bin = bytes(r["link_key"])
        lk_hex = lk_bin.hex()
        doc_key = f"doc:{lk_hex}"
        sb_bin = bytes(r["saved_body"]) if r.get("saved_body") is not None else (b"\x00" * 32)
        sb_hex = sb_bin.hex()
        eff_hex = sb_hex
        pkg_id = str(r["package_id"]) if r.get("package_id") is not None else None
        rn_val = row_rns[lr]
        fn = str(r.get("filename") or "")
        fmt = _infer_effective_format(r.get("format"), r.get("saved_suffix"), r.get("saved_media_type"), fn)

        if rn_val > 1 and sb_bin != (b"\x00" * 32):
            alias_indices.append(lr)
            continue

        # Build provenance & relational signals from the release tables
        src_list = sources_by_lr.get(lr, ())
        urls = [str(s["url"]) for s in src_list if s.get("url")]
        listed_ons = [str(s["listed_on"]) for s in src_list if s.get("listed_on")]
        member_paths = [str(s["member_path"]) for s in src_list if s.get("member_path")]
        link_texts = [str(s["link_text"]).strip() for s in src_list if s.get("link_text") and str(s["link_text"]).strip()]

        slug_info = pr5.extract_url_official_slug_info(
            urls=urls, listed_ons=listed_ons, member_paths=member_paths, filename=fn
        )
        mkeys = list(r.get("meeting_keys") or ())
        m0 = meetings_by_id.get(str(mkeys[0])) if len(mkeys) == 1 else None

        rel_cong_raw = r.get("congress") or (m0.get("congress") if m0 else None) or slug_info.get("slug_congress")
        rel_cong = int(rel_cong_raw) if isinstance(rel_cong_raw, int) and not isinstance(rel_cong_raw, bool) else None

        ch_list = [str(c).lower() for c in (r.get("chambers") or ()) if c]
        rel_ch = (
            ch_list[0]
            if len(ch_list) == 1
            else (str(m0["chamber"]).lower() if m0 and m0.get("chamber") else slug_info.get("slug_chamber"))
        )

        raw_ckeys = [str(c).lower() for c in (r.get("committee_keys") or ()) if c]
        if not raw_ckeys and slug_info.get("slug_committee_code"):
            raw_ckeys.append(str(slug_info["slug_committee_code"]))
        for u in urls + listed_ons:
            host = (urlparse(u).hostname or "").lower()
            if host in pr5.DOMAIN_TO_COMMITTEE_CODE:
                dc = pr5.DOMAIN_TO_COMMITTEE_CODE[host]
                if dc not in raw_ckeys:
                    raw_ckeys.append(dc)

        hsru_status = "rules_host" if ("hsru00" in raw_ckeys and any(u for u in urls if "rules.house.gov/bill" in u.lower())) else "not_hsru"
        det_cmts: list[str] = []
        for ck in raw_ckeys:
            if ck == "hsru00" and hsru_status == "rules_host":
                continue
            canon_cmt = rv6.committee_code_to_canonical_v6(ck, rel_cong)
            if canon_cmt and canon_cmt[1] not in det_cmts:
                det_cmts.append(canon_cmt[1])

        # Priority 1: Selection `excluded_bodies` -> `error_or_block`
        excl = excluded_by_sha.get(sb_hex)
        if excl is not None:
            src_role = str(excl.get("source_role") or "error_response")
            raw_rsn = re.sub(r"\(body:[0-9a-f]{64}\):\s*", ": ", str(excl.get("reason") or "confirmed non-document HTTP error/wrapper"))
            t_canon, t_json = _triage_docmeta(
                status="error_or_block",
                text_quality="native",
                base_reason=f"Excluded {src_role}: {raw_rsn[:115]}",
                detail_title=r.get("title"),
                committees=det_cmts,
                filename=fn,
            )
            completed_rows.append(
                {
                    "list_row": lr, "link_key": lk_bin, "link_key_hex": lk_hex, "doc_key": doc_key,
                    "saved_body": sb_bin, "saved_body_hex": sb_hex, "effective_body_sha_hex": eff_hex,
                    "package_id": pkg_id, "rn": rn_val, "disposition": "excluded_body",
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": "selection_excluded_error_or_wrapper",
                    "filename": fn, "effective_format": fmt, "primary_kind": None,
                    "status": "error_or_block", "congress": rel_cong, "chamber": rel_ch,
                    "committees": det_cmts, "docmeta_json": t_json, "strict_v4_valid": True,
                }
            )
            bucket_by_lr[lr] = ("completed_no_llm", "deterministic_triage_non_usable")
            stats["excluded_selection_body"] += 1
            continue

        # Hydrate prose from `BodyTextSSOT` or release `selected_text` / `main_content` / `description`
        if sb_bin in ssot_windows:
            ssot_win, is_cov_p12, p3_slice, stapled_ttf_json = ssot_windows[sb_bin]
            raw_txt = ssot_win.strip()
            text_src = "body_text_ssot_head_tail_9000"
            stats["hydrated_from_ssot"] += 1
        else:
            fallback_txt = str(r.get("selected_text") or r.get("main_content") or r.get("description") or "").strip()
            raw_txt, is_cov_p12, p3_slice, stapled_ttf_json = build_hybrid_ssot_window(fallback_txt, [0] if fallback_txt else [])
            raw_txt = raw_txt.strip()
            text_src = "release_detail_text" if (r.get("selected_text") or r.get("main_content")) else "detail_description_fallback"
            stats[f"hydrated_{text_src}"] += 1

        if fmt == "zip" and not raw_txt:
            t_canon, t_json = _triage_docmeta(
                status="stub_or_blank",
                text_quality="native",
                base_reason="Unextracted application/zip archive container without standalone prose body",
                detail_title=r.get("title"),
                committees=det_cmts,
                filename=fn,
            )
            completed_rows.append(
                {
                    "list_row": lr, "link_key": lk_bin, "link_key_hex": lk_hex, "doc_key": doc_key,
                    "saved_body": sb_bin, "saved_body_hex": sb_hex, "effective_body_sha_hex": eff_hex,
                    "package_id": pkg_id, "rn": rn_val, "disposition": "non_prose_container",
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": "triage_zip_container",
                    "filename": fn, "effective_format": fmt, "primary_kind": None,
                    "status": "stub_or_blank", "congress": rel_cong, "chamber": rel_ch,
                    "committees": det_cmts, "docmeta_json": t_json, "strict_v4_valid": True,
                }
            )
            bucket_by_lr[lr] = ("completed_no_llm", "deterministic_triage_non_usable")
            stats["triaged_zip_container"] += 1
            continue

        if not raw_txt or (text_src == "detail_description_fallback" and raw_txt.lower().rstrip(".") in GENERIC_EMPTY_CMS_BANNERS):
            st_empty = "stub_or_blank" if fmt in ("html", "xml", "txt") else "ocr_unreadable"
            tq_empty = "native" if st_empty == "stub_or_blank" else "garbled"
            t_canon, t_json = _triage_docmeta(
                status=st_empty,
                text_quality=tq_empty,
                base_reason=f"No usable prose extracted for {fmt} document ({text_src})",
                detail_title=r.get("title"),
                committees=det_cmts,
                filename=fn,
            )
            completed_rows.append(
                {
                    "list_row": lr, "link_key": lk_bin, "link_key_hex": lk_hex, "doc_key": doc_key,
                    "saved_body": sb_bin, "saved_body_hex": sb_hex, "effective_body_sha_hex": eff_hex,
                    "package_id": pkg_id, "rn": rn_val, "disposition": "empty_or_unreadable",
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": f"triage_{st_empty}",
                    "filename": fn, "effective_format": fmt, "primary_kind": None,
                    "status": st_empty, "congress": rel_cong, "chamber": rel_ch,
                    "committees": det_cmts, "docmeta_json": t_json, "strict_v4_valid": True,
                }
            )
            bucket_by_lr[lr] = ("completed_no_llm", "deterministic_triage_non_usable")
            stats[f"triaged_empty:{st_empty}"] += 1
            continue

        is_h = pv6.infer_is_html_v6(fn, raw_txt, explicit_format=fmt or None)
        clean_s, _, _ = pv6.clean_html_and_cms_v6(raw_txt, is_html=is_h)
        rep_s, _ = h6.repair_bgsdd_mojibake_v6(
            clean_s,
            filename=fn,
            is_gpo=fn.upper().startswith(("CHRG-", "HHRG-", "BILLS-", "CRPT-", "CPRT-", "CDOC-")),
        )
        clean_txt = (rep_s.strip() or clean_s.strip() or raw_txt)[:WINDOW_MAX_CHARS]
        raw_final = (raw_txt or clean_txt)[:WINDOW_MAX_CHARS]

        tr_hit = pv6.triage_non_usable_v6(clean_txt, filename=fn, explicit_format=fmt or None)
        if tr_hit is not None:
            tr_dm = tr_hit["docmeta"]
            t_canon, t_json = _triage_docmeta(
                status=str(tr_dm["status"]),
                text_quality=str(tr_dm.get("text_quality") or "native"),
                base_reason=str(tr_dm.get("error_reason") or "Non-usable document detected"),
                detail_title=r.get("title"),
                committees=det_cmts,
                filename=fn,
            )
            completed_rows.append(
                {
                    "list_row": lr, "link_key": lk_bin, "link_key_hex": lk_hex, "doc_key": doc_key,
                    "saved_body": sb_bin, "saved_body_hex": sb_hex, "effective_body_sha_hex": eff_hex,
                    "package_id": pkg_id, "rn": rn_val, "disposition": "non_usable_triage",
                    "v6_route": "deterministic_triage_non_usable",
                    "zero_llm_source": f"triage_{t_canon['status']}",
                    "filename": fn, "effective_format": fmt, "primary_kind": None,
                    "status": t_canon["status"], "congress": rel_cong, "chamber": rel_ch,
                    "committees": det_cmts, "docmeta_json": t_json, "strict_v4_valid": True,
                }
            )
            bucket_by_lr[lr] = ("completed_no_llm", "deterministic_triage_non_usable")
            stats[f"triaged_content:{t_canon['status']}"] += 1
            continue

        # Genre locks: SHA override -> Tier-1 text -> V6 cover lock -> GovInfo package lock (with `ct-2cig` reprint guard) -> link anchor
        lock_id, locked_pk, lock_src = None, None, None
        sha_hit = cl6.lookup_saved_name_sha_override_v6(sb_hex)
        if sha_hit is not None:
            lock_id, locked_pk, lock_src = sha_hit[0], sha_hit[1], "saved_name_sha_override"
        if locked_pk is None:
            s_t1, k_t1 = pv6.detect_exact_tier1_signature_v5(fn, clean_txt, is_html=is_h)
            if k_t1 in pv6.DOC_KINDS_SET:
                lock_id, locked_pk, lock_src = s_t1, k_t1, "tier1_text"
        if locked_pk is None:
            c_id, c_kind, c_src = pv6.detect_cover_or_sha_lock_v6(
                fn,
                clean_txt,
                p12_lines=clean_txt,
                body_sha_hex=sb_hex,
                bioguide_ids=r.get("bioguide_ids"),
                witness_keys=r.get("witness_keys"),
                is_html=is_h,
            )
            if c_kind in pv6.DOC_KINDS_SET:
                lock_id, locked_pk, lock_src = c_id, c_kind, c_src or "cover_lock_v6"
        if locked_pk is None and pkg_id:
            p_id, p_kind, p_src = cl6.resolve_govinfo_pkg_lock_v6(
                pkg_id,
                r.get("document_kind") or (),
                title=str(r.get("title") or ""),
                filename=fn,
                text=clean_txt,
            )
            if p_kind in pv6.DOC_KINDS_SET:
                lock_id, locked_pk, lock_src = p_id, p_kind, p_src
        if locked_pk is None and link_texts:
            la_id, la_kind, _ = pr5.detect_provenance_link_anchor(
                link_texts, filename=fn, text=clean_txt
            )
            if la_kind in pv6.DOC_KINDS_SET:
                lock_id, locked_pk, lock_src = la_id, la_kind, "provenance_link_anchor"

        # Relational event & witness persona seeds (with R4-R6 disambiguation!)
        rel_eid = str(m0["event_id"]) if m0 and m0.get("event_id") else None
        rel_edate = (
            m0["meeting_date"].isoformat()
            if m0 and isinstance(m0.get("meeting_date"), datetime.date)
            else (str(m0["meeting_date"]) if m0 and m0.get("meeting_date") else slug_info.get("slug_meeting_date"))
        )
        rel_etitle = str(m0["title"]).strip() if m0 and m0.get("title") else None
        rel_etype = rv6.normalize_meeting_event_type_v6(m0.get("meeting_type")) if m0 else None
        rel_venue = rv6.format_sitting_venue_v6(m0.get("sittings"))[0] if m0 else None

        w_personas: list[dict[str, Any]] = []
        for wk in (r.get("witness_keys") or ()):
            wr = witnesses_by_key.get(str(wk))
            if wr is not None:
                pr = people_by_key.get(str(wr.get("person_key") or ""))
                wp = rv6.build_witness_persona_v6(wr, person_row=pr, congress=rel_cong, lookup=rosters_lookup)
                if wp is not None:
                    w_personas.append(wp)

        wl_ps = h6.parse_witness_list_personas_v6(clean_txt, body_sha_hex=sb_hex)
        gpo_ps = h6.parse_gpo_p12_personas_v6(clean_txt)
        gpo_p3_ps = h6.parse_gpo_p3_slice_personas_v6(p3_slice) if isinstance(p3_slice, str) and p3_slice else []
        seed_list = w_personas or wl_ps or gpo_ps or gpo_p3_ps
        if seed_list:
            seed_list = rv6.disambiguate_persona_roles_v6(
                seed_list[: s4.MAX_PERSONAS], primary_kind=locked_pk, text=clean_txt, congress=rel_cong, lookup=rosters_lookup
            )
            seed_clean = [
                sp
                for item in seed_list
                for sp in [_sanitize_persona_dict(item, valid_roles, valid_etypes, key_order)]
                if sp is not None
            ]
            personas_seed_json = (
                json.dumps(seed_clean[: s4.MAX_PERSONAS], separators=(",", ":"), ensure_ascii=False) if seed_clean else None
            )
        else:
            personas_seed_json = None

        cit = cs6.extract_citations_and_signals_v6(
            clean_txt, filename=fn, congress=rel_cong, oracles=refspec_oracles
        )
        det_refs = list(cit.get("det_refs") or ())[:25]
        det_sts = list(cit.get("det_short_titles") or ())[:8]
        det_fys = [int(y) for y in (cit.get("det_fiscal_years") or ()) if y is not None][:12]
        usc_inv = list(cit.get("usc_oracle_invalid_refs") or ())

        # Production key order: `congress,cmt,chambers,date` (`L4` finding 5)
        known_d: dict[str, Any] = {}
        if rel_cong is not None:
            known_d["congress"] = rel_cong
        if raw_ckeys:
            known_d["cmt"] = raw_ckeys[:6]
        if rel_ch:
            known_d["chambers"] = [rel_ch]
        doc_dt = r.get("document_date")
        dt_iso = doc_dt.isoformat() if isinstance(doc_dt, datetime.date) else (str(doc_dt) if doc_dt else rel_edate)
        if dt_iso:
            known_d["date"] = dt_iso
        known_json = json.dumps(known_d, separators=(",", ":"), ensure_ascii=False) if known_d else None

        rel_ctx: dict[str, Any] = {
            "rel_congress": rel_cong,
            "rel_chamber": rel_ch,
            "rel_host_chamber": rel_ch,
            "rel_host_committee_codes": raw_ckeys,
            "rel_author_safe_committees": det_cmts,
            "rel_event_id": rel_eid,
            "rel_event_date": rel_edate,
            "rel_event_title": rel_etitle,
            "rel_event_type": rel_etype,
            "rel_venue": rel_venue,
            "rel_not_held": bool(m0.get("not_held")) if m0 else False,
            "witness_keys": list(r.get("witness_keys") or ()),
            "bioguide_ids": list(r.get("bioguide_ids") or ()),
            "rel_witness_personas_json": personas_seed_json,
        }
        prov_ctx: dict[str, Any] = {
            "hsru_host_status": hsru_status,
            "url_congress": rel_cong,
            "provenance_committees": det_cmts,
            "clean_link_texts": link_texts,
        }
        hyg_ctx: dict[str, Any] = {
            "p12_lines": clean_txt,
            "has_newlines": "\n" in clean_txt,
            "witness_list_personas_json": json.dumps(wl_ps, ensure_ascii=False) if wl_ps else None,
            "gpo_p12_personas_json": json.dumps(gpo_ps, ensure_ascii=False) if gpo_ps else None,
            "gpo_p3_personas_json": json.dumps(gpo_p3_ps, ensure_ascii=False) if gpo_p3_ps else None,
        }
        cit_ctx: dict[str, Any] = {
            "det_refs": det_refs,
            "det_short_titles": det_sts,
            "det_fiscal_years": det_fys,
            "usc_oracle_invalid_refs": usc_inv,
        }

        # Zero-LLM synthesis with full current R4-R8 post-pass (`post_pass_v6` runs R4-R6, R7, and R8!)
        if locked_pk in ZERO_LLM_BYPASS_KINDS:
            synth_cand = pv6.try_zero_llm_bypass_v6(
                locked_primary_kind=locked_pk,
                tier1_signature_id=lock_id,
                filename=fn,
                text=clean_txt,
                p12_lines=clean_txt,
                known_dict=known_d,
                provenance=prov_ctx,
                relational=rel_ctx,
                citations=cit_ctx,
                hygiene=hyg_ctx,
            )
            if synth_cand is not None:
                try:
                    if r8_ready:
                        synth_post, _ = pv6.post_pass_v6(
                            synth_cand,
                            known=known_d,
                            filename=fn,
                            text=clean_txt,
                            p12_lines=clean_txt,
                            explicit_format=fmt or None,
                            provenance=prov_ctx,
                            relational=rel_ctx,
                            citations=cit_ctx,
                            hygiene=hyg_ctx,
                            usc_oracle=usc_oracle,
                        )
                    else:
                        synth_post = rv6.apply_relational_post_pass_v6(
                            dict(synth_cand),
                            rel_ctx,
                            filename=fn,
                            text=clean_txt,
                            hsru_status=hsru_status,
                            lookup=rosters_lookup,
                        )
                        if synth_post.get("subcommittees"):
                            synth_post["subcommittees"] = rv6.ground_subcommittees_v6(
                                synth_post["subcommittees"],
                                text=clean_txt,
                                committee_codes=raw_ckeys,
                                congress=synth_post.get("congress") or rel_cong,
                                lookup=rosters_lookup,
                            )
                    canon_s, j_str_s = _finalize(synth_post)
                    g_chk = ar6.check_gist_title_grounding_v6(canon_s, text=clean_txt, filename=fn, known=known_d)
                    if g_chk["is_grounded"]:
                        completed_rows.append(
                            {
                                "list_row": lr, "link_key": lk_bin, "link_key_hex": lk_hex, "doc_key": doc_key,
                                "saved_body": sb_bin, "saved_body_hex": sb_hex, "effective_body_sha_hex": eff_hex,
                                "package_id": pkg_id, "rn": rn_val, "disposition": "zero_llm_bypass",
                                "v6_route": "zero_llm_synthesized_docmeta",
                                "zero_llm_source": f"sidecar_zero_llm_{canon_s['primary_kind']}",
                                "filename": fn, "effective_format": fmt,
                                "primary_kind": canon_s["primary_kind"], "status": canon_s["status"],
                                "congress": canon_s.get("congress") if canon_s.get("congress") is not None else rel_cong,
                                "chamber": canon_s.get("chamber") or rel_ch,
                                "committees": list(canon_s.get("committees") or det_cmts),
                                "docmeta_json": j_str_s, "strict_v4_valid": True,
                            }
                        )
                        bucket_by_lr[lr] = ("completed_no_llm", "zero_llm_synthesized_docmeta")
                        stats[f"zero_llm:{canon_s['primary_kind']}"] += 1
                        continue
                except Exception:
                    pass

        v6_route = (
            "tier1_or_cover_or_anchor_grammar_locked"
            if locked_pk is not None
            else (
                "deterministic_enriched_open_kind"
                if (rel_cong is not None or det_cmts or rel_ch is not None or det_refs or det_sts or det_fys)
                else "llm_open_extraction"
            )
        )
        queue_rows.append(
            {
                "list_row": lr,
                "link_key": lk_bin,
                "link_key_hex": lk_hex,
                "doc_key": doc_key,
                "saved_body": sb_bin,
                "saved_body_hex": sb_hex,
                "effective_body_sha_hex": eff_hex,
                "package_id": pkg_id,
                "rn": rn_val,
                "disposition": "target_llm_queue",
                "v6_route": v6_route,
                "filename": fn,
                "effective_format": fmt,
                "text_source": text_src,
                "p12_raw_text": raw_final,
                "p12_clean_text": clean_txt,
                "known_json": known_json,
                "locked_primary_kind": locked_pk,
                "grammar_lock_source": lock_src,
                "lock_id": lock_id,
                "rel_congress": rel_cong,
                "rel_chamber": rel_ch,
                "rel_committees": det_cmts,
                "rel_event_id": rel_eid,
                "rel_event_date": rel_edate,
                "rel_event_title": rel_etitle,
                "rel_event_type": rel_etype,
                "rel_venue": rel_venue,
                "personas_seed_json": personas_seed_json,
                "det_refs": det_refs,
                "det_short_titles": det_sts,
                "det_fiscal_years": det_fys,
                "usc_oracle_invalid_refs": usc_inv,
                "hsru_host_status": hsru_status,
                "is_cover_roster_p12": is_cov_p12,
                "p3_toc_or_gavel_slice": p3_slice,
                "stapled_ttf_disclosure_json": stapled_ttf_json,
            }
        )
        bucket_by_lr[lr] = ("llm_queue", v6_route)
        stats[f"queued:{v6_route}"] += 1

    # 5. Build `sha_dup_alias` rows for `rn > 1`
    alias_rows: list[dict[str, Any]] = []
    for lr in alias_indices:
        r = all_detail_rows[lr]
        lk_bin = bytes(r["link_key"])
        lk_hex = lk_bin.hex()
        sb_bin = bytes(r["saved_body"])
        sb_hex = sb_bin.hex()
        canon_lr = canonical_lr_by_sb[sb_hex]
        canon_r = all_detail_rows[canon_lr]
        canon_lk_bin = bytes(canon_r["link_key"])
        canon_lk_hex = canon_lk_bin.hex()
        canon_bucket, canon_route = bucket_by_lr[canon_lr]
        fn = str(r.get("filename") or "")
        fmt = _infer_effective_format(r.get("format"), r.get("saved_suffix"), r.get("saved_media_type"), fn)
        alias_rows.append(
            {
                "list_row": lr,
                "link_key": lk_bin,
                "link_key_hex": lk_hex,
                "doc_key": f"doc:{lk_hex}",
                "saved_body": sb_bin,
                "saved_body_hex": sb_hex,
                "effective_body_sha_hex": sb_hex,
                "package_id": str(r["package_id"]) if r.get("package_id") is not None else None,
                "rn": row_rns[lr],
                "disposition": "target_sraw_sha_dup",
                "sub_disposition": "exact_saved_body_dup",
                "v6_route": "sha_dup_alias",
                "filename": fn,
                "effective_format": fmt,
                "canonical_list_row": canon_lr,
                "canonical_link_key": canon_lk_bin,
                "canonical_link_key_hex": canon_lk_hex,
                "canonical_doc_key": f"doc:{canon_lk_hex}",
                "canonical_rn": 1,
                "canonical_partition_bucket": canon_bucket,
                "canonical_v6_route": canon_route,
            }
        )
        stats["sha_dup_alias"] += 1

    total_expected = len(selected_indices)
    if len(completed_rows) + len(queue_rows) + len(alias_rows) != total_expected:
        raise RuntimeError(
            f"Conservation failure: {len(completed_rows)} + {len(queue_rows)} + {len(alias_rows)} != {total_expected}"
        )

    # 6. Explicit Arrow schemas so even 0-row bounded partitions carry exact column types
    comp_schema = pa.schema(
        [
            pa.field("list_row", pa.int32(), nullable=False),
            pa.field("link_key", pa.binary(8), nullable=False),
            pa.field("link_key_hex", pa.string(), nullable=False),
            pa.field("doc_key", pa.string(), nullable=False),
            pa.field("saved_body", pa.binary(32), nullable=False),
            pa.field("saved_body_hex", pa.string(), nullable=False),
            pa.field("effective_body_sha_hex", pa.string(), nullable=False),
            pa.field("package_id", pa.string()),
            pa.field("rn", pa.int32(), nullable=False),
            pa.field("disposition", pa.string()),
            pa.field("v6_route", pa.string()),
            pa.field("zero_llm_source", pa.string()),
            pa.field("filename", pa.string()),
            pa.field("effective_format", pa.string()),
            pa.field("primary_kind", pa.string()),
            pa.field("status", pa.string()),
            pa.field("congress", pa.int64()),
            pa.field("chamber", pa.string()),
            pa.field("committees", pa.list_(pa.string())),
            pa.field("docmeta_json", pa.string(), nullable=False),
            pa.field("strict_v4_valid", pa.bool_(), nullable=False),
        ]
    )
    queue_schema = pa.schema(
        [
            pa.field("list_row", pa.int32(), nullable=False),
            pa.field("link_key", pa.binary(8), nullable=False),
            pa.field("link_key_hex", pa.string(), nullable=False),
            pa.field("doc_key", pa.string(), nullable=False),
            pa.field("saved_body", pa.binary(32), nullable=False),
            pa.field("saved_body_hex", pa.string(), nullable=False),
            pa.field("effective_body_sha_hex", pa.string(), nullable=False),
            pa.field("package_id", pa.string()),
            pa.field("rn", pa.int32(), nullable=False),
            pa.field("disposition", pa.string()),
            pa.field("v6_route", pa.string()),
            pa.field("filename", pa.string()),
            pa.field("effective_format", pa.string()),
            pa.field("text_source", pa.string()),
            pa.field("p12_raw_text", pa.string(), nullable=False),
            pa.field("p12_clean_text", pa.string(), nullable=False),
            pa.field("known_json", pa.string()),
            pa.field("locked_primary_kind", pa.string()),
            pa.field("grammar_lock_source", pa.string()),
            pa.field("lock_id", pa.string()),
            pa.field("rel_congress", pa.int64()),
            pa.field("rel_chamber", pa.string()),
            pa.field("rel_committees", pa.list_(pa.string())),
            pa.field("rel_event_id", pa.string()),
            pa.field("rel_event_date", pa.string()),
            pa.field("rel_event_title", pa.string()),
            pa.field("rel_event_type", pa.string()),
            pa.field("rel_venue", pa.string()),
            pa.field("personas_seed_json", pa.string()),
            pa.field("det_refs", pa.list_(pa.string())),
            pa.field("det_short_titles", pa.list_(pa.string())),
            pa.field("det_fiscal_years", pa.list_(pa.int64())),
            pa.field("usc_oracle_invalid_refs", pa.list_(pa.string())),
            pa.field("hsru_host_status", pa.string()),
            pa.field("is_cover_roster_p12", pa.bool_()),
            pa.field("p3_toc_or_gavel_slice", pa.string()),
            pa.field("stapled_ttf_disclosure_json", pa.string()),
        ]
    )
    alias_schema = pa.schema(
        [
            pa.field("list_row", pa.int32(), nullable=False),
            pa.field("link_key", pa.binary(8), nullable=False),
            pa.field("link_key_hex", pa.string(), nullable=False),
            pa.field("doc_key", pa.string(), nullable=False),
            pa.field("saved_body", pa.binary(32), nullable=False),
            pa.field("saved_body_hex", pa.string(), nullable=False),
            pa.field("effective_body_sha_hex", pa.string(), nullable=False),
            pa.field("package_id", pa.string()),
            pa.field("rn", pa.int32(), nullable=False),
            pa.field("disposition", pa.string()),
            pa.field("sub_disposition", pa.string()),
            pa.field("v6_route", pa.string()),
            pa.field("filename", pa.string()),
            pa.field("effective_format", pa.string()),
            pa.field("canonical_list_row", pa.int32(), nullable=False),
            pa.field("canonical_link_key", pa.binary(8), nullable=False),
            pa.field("canonical_link_key_hex", pa.string(), nullable=False),
            pa.field("canonical_doc_key", pa.string(), nullable=False),
            pa.field("canonical_rn", pa.int32(), nullable=False),
            pa.field("canonical_partition_bucket", pa.string()),
            pa.field("canonical_v6_route", pa.string()),
        ]
    )

    def _write_atomic(rows_list: list[dict[str, Any]], schema: pa.Schema, filename: str) -> dict[str, Any]:
        tbl = pa.Table.from_pylist(rows_list, schema=schema)
        out_p = out_dir / filename
        tmp_p = out_p.with_suffix(".parquet.tmp")
        rg_size = ROW_GROUP_SIZE_TARGET if tbl.num_rows > ROW_GROUP_SIZE_TARGET else max(1, (tbl.num_rows + 1) // 2)
        try:
            pq.write_table(
                tbl,
                tmp_p,
                compression="zstd",
                compression_level=compression_level,
                row_group_size=rg_size,
                write_statistics=True,
            )
            os.replace(tmp_p, out_p)
        except BaseException:
            tmp_p.unlink(missing_ok=True)
            raise
        raw_b = out_p.read_bytes()
        return {
            "path": filename,
            "rows": tbl.num_rows,
            "bytes": len(raw_b),
            "sha256": hashlib.sha256(raw_b).hexdigest(),
        }

    meta_comp = _write_atomic(completed_rows, comp_schema, "completed_no_llm.parquet")
    meta_queue = _write_atomic(queue_rows, queue_schema, "llm_queue.parquet")
    meta_alias = _write_atomic(alias_rows, alias_schema, "sha_dup_alias.parquet")

    manifest = {
        "schema_version": "docmeta_sidecar_v6_3",
        "release_id": release_id,
        "release_dir": str(rel_dir),
        "body_text_export_parquet": str(export_parquet_path) if export_parquet_path else None,
        "selection_path": str(Path(selection_path).resolve()) if selection_path else None,
        "r8_work_addr_enabled": r8_ready,
        "bounded_sample": limit is not None or norm_link_keys is not None,
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "counts": {
            "total_rows": total_expected,
            "completed_no_llm": len(completed_rows),
            "llm_queue": len(queue_rows),
            "sha_dup_alias": len(alias_rows),
        },
        "stats": dict(sorted(stats.items(), key=lambda kv: (-kv[1], kv[0]))),
        "parts": {
            "completed_no_llm": meta_comp,
            "llm_queue": meta_queue,
            "sha_dup_alias": meta_alias,
        },
    }
    (out_dir / "sidecar_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release-dir", type=Path, required=True, help="Published release directory (`list.parquet`, `detail.parquet`, ...)")
    ap.add_argument("--out-root", type=Path, required=True, help="Output directory for the three sidecar Parquet parts")
    ap.add_argument("--body-text-dir", type=Path, default=None, help="Optional BodyTextSSOT export directory (`export.parquet`)")
    ap.add_argument("--selection", type=Path, default=None, help="Optional body_text selection JSON or `.json.gz`")
    ap.add_argument("--limit", type=int, default=None, help="Optional bounded row limit for smoke/sample verification")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_release_sidecar(
        args.release_dir,
        args.out_root,
        body_text_export_dir=args.body_text_dir,
        selection_path=args.selection,
        limit=args.limit,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
