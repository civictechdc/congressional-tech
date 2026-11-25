"""V7.3 Clean-Slate 10K+ 3-Family Corpus Builder, Checkpointed Sharder & Sealer (`ct-so28`).

Usage:
    .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder build-pool --target 10500
    .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder run --workers 10 --shard-size 250
    .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder seal
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..codebook import (
    codebook_version as compute_codebook_sha256,
    render_core_prompt,
    render_specialist_prompt as render_codebook_specialist_prompt,
)
from ..crosswalk import (
    map_genre_to_congress_gov,
    map_genre_to_docs_house_gov,
    map_genre_to_document_kind,
    map_genre_to_lcgft,
)
from ..models import PrimaryGenre
from ..release_metadata import (
    build_croissant_manifest,
    build_dcat3_catalog,
    validate_croissant_manifest,
    validate_dcat3_catalog,
)
from .cache import (
    CacheEntry,
    SixTupleCache,
    canonical_json_sha256,
    default_cache_path,
    discover_main_checkout_root,
    make_cache_key,
    sha256_text,
)
from .counterfactual import run_counterfactual_suite
from .grounding import (
    ConsensusDecision,
    adjudicate_three_family,
    format_deadlock_digest,
    merge_consensus_payload,
    reconcile_and_validate_v7_payload,
    strip_invisible_format_chars,
    verify_span_grounding,
)
from .pilot import (
    CORE_TRIAGE_SCHEMA,
    GENRE_TO_SPECIALIST_FAMILY,
    _parse_and_validate,
    _process_single_doc,
    _resolve_v7_runtime_specs,
    build_dry_run_adapters,
    build_live_sota_checkeval_fn,
    default_ssot_path,
    load_ssot_rows,
    render_core_triage_prompt,
    render_specialist_prompt as render_pilot_specialist_prompt,
)
from .runners import (
    AdapterOutput,
    FamilyRunResult,
    RunnerConfig,
    UsageGuard,
    _resolve_adapter,
    extract_json_payload,
    run_family_with_cache,
)
from .splits import audit_decontamination, build_event_temporal_splits, extract_event_group_key


_FILENAME_2026_RE = re.compile(r"(?:2026[01]\d[0-3]\d|^2026-\d{2}-\d{2}|[-_]2026[-_])")


def default_corpus_dir() -> Path:
    """Return `<main checkout>/.cache/archive-release/docmeta-v7-corpus`."""
    return discover_main_checkout_root() / ".cache" / "archive-release" / "docmeta-v7-corpus"


def default_parquet_paths() -> dict[str, Path]:
    """Return paths to canonical upstream V6.5 SSOT and 323K archive Parquets."""
    cache_root = discover_main_checkout_root() / ".cache" / "archive-release"
    return {
        "ssot": default_ssot_path(),
        "llm_queue": cache_root / "docmeta-v6-20261116" / "parquets_v6_2" / "llm_queue_v6_2.parquet",
        "deterministic": cache_root / "docmeta-v6-20261116" / "parquets_v6_2" / "deterministic_323k_v6_2.parquet",
        "p12": cache_root / "docmeta-v6-20261116" / "parquets" / "p12_newlines_and_hygiene_323k.parquet",
    }


def _parse_committees(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    return [str(x).strip() for x in loaded if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return []


def _is_2026_row(row: Mapping[str, Any], temporal_cutoff: str = "2026-01-01") -> bool:
    for field in ("doc_date", "event_date"):
        val = row.get(field)
        if isinstance(val, str) and len(val) >= 4 and val[:10] >= temporal_cutoff:
            return True
    fname = str(row.get("filename") or "")
    if _FILENAME_2026_RE.search(fname):
        return True
    _, dt = extract_event_group_key(row)
    return bool(dt is not None and dt[0] >= 2026)


_BLANK_HEAD_TAIL_RE = re.compile(r"^\s*\[\.\.\.\s*page\s+\d+\s+tail\s*\.\.\.\]", re.IGNORECASE)
_TAIL_MARKER_RE = re.compile(r"\[\.\.\.\s*page\s+\d+\s+tail\s*\.\.\.\]", re.IGNORECASE)


def _is_blank_or_stub_head_tail(text: str, *, max_head_chars: int = 80) -> bool:
    """Return True if `[... page N tail ...]` appears with blank or <`max_head_chars` stub head text."""
    m = _TAIL_MARKER_RE.search(text or "")
    if m is None:
        return False
    return len(" ".join((text or "")[: m.start()].split())) < max_head_chars


def _norm_candidate_record(
    *,
    doc_key: str,
    text: str,
    filename: str,
    source_pool: str,
    stratum: str,
    doc_date: str | None = None,
    event_date: str | None = None,
    chamber: str | None = None,
    committees: list[str] | None = None,
    prior_kind: str | None = None,
    effective_format: str | None = None,
    split_hint: str | None = None,
    link_key_hex: str | None = None,
    saved_body_hex: str | None = None,
    effective_body_sha_hex: str | None = None,
) -> dict[str, Any]:
    cleaned_text = strip_invisible_format_chars(text)
    capped_text = cleaned_text[:9000] if len(cleaned_text) > 9000 else cleaned_text
    rec = {
        "doc_key": str(doc_key),
        "text_sha256": sha256_text(capped_text),
        "text": capped_text,
        "filename": str(filename or ""),
        "source_pool": source_pool,
        "stratum": stratum,
        "doc_date": doc_date,
        "event_date": event_date,
        "chamber": chamber,
        "committees": list(committees or []),
        "prior_kind": prior_kind,
        "effective_format": effective_format,
        "split_hint": split_hint,
        "link_key_hex": link_key_hex,
        "saved_body_hex": saved_body_hex,
        "effective_body_sha_hex": effective_body_sha_hex,
    }
    rec["is_2026"] = _is_2026_row(rec)
    return rec


def build_v73_candidate_pool(
    *,
    ssot_path: Path | None = None,
    llm_queue_path: Path | None = None,
    deterministic_path: Path | None = None,
    p12_path: Path | None = None,
    out_dir: Path | None = None,
    target_total: int = 10500,
    min_2026: int = 700,
    seed: int = 20261122,
) -> dict[str, Any]:
    """Assemble a stratified 10K+ V7.3 candidate pool from all V6.5 SSOT rows + 323K archive Parquets."""
    defaults = default_parquet_paths()
    resolved_ssot = Path(ssot_path) if ssot_path is not None else defaults["ssot"]
    resolved_queue = Path(llm_queue_path) if llm_queue_path is not None else defaults["llm_queue"]
    resolved_det = Path(deterministic_path) if deterministic_path is not None else defaults["deterministic"]
    resolved_p12 = Path(p12_path) if p12_path is not None else defaults["p12"]
    resolved_out = (Path(out_dir) if out_dir is not None else default_corpus_dir()).resolve()
    resolved_out.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_shas: set[str] = set()

    def _try_add(rec: dict[str, Any]) -> bool:
        dk = rec["doc_key"]
        ts = rec["text_sha256"]
        if not dk or not rec["text"].strip() and "non_usable" not in rec["stratum"]:
            return False
        if dk in seen_keys or ts in seen_shas:
            return False
        seen_keys.add(dk)
        seen_shas.add(ts)
        candidates.append(rec)
        return True

    # 1. Always ingest all unique SSOT V6.5 docs first (clean blind text).
    if resolved_ssot.is_file():
        ssot_rows = load_ssot_rows(resolved_ssot)
        for row in ssot_rows:
            rec = _norm_candidate_record(
                doc_key=str(row["doc_key"]),
                text=str(row.get("text") or ""),
                filename=str(row.get("filename") or ""),
                source_pool="ssot_v6_5",
                stratum=f"ssot:{row.get('v65_primary_kind') or row.get('status') or 'unknown'}",
                doc_date=row.get("doc_date"),
                event_date=row.get("event_date"),
                chamber=row.get("chamber"),
                committees=_parse_committees(row.get("committees")),
                prior_kind=row.get("v65_primary_kind"),
                effective_format=None,
                split_hint=row.get("split"),
            )
            # Even empty stubs in SSOT (e.g. [EMPTY_BODY]) are kept by preserving non-empty blind text.
            dk = rec["doc_key"]
            ts = rec["text_sha256"]
            if dk not in seen_keys and ts not in seen_shas:
                seen_keys.add(dk)
                seen_shas.add(ts)
                candidates.append(rec)

    ssot_count = len(candidates)

    # 2. Stream stratified unseen docs via DuckDB from the 323K archive Parquets.
    if resolved_queue.is_file() and len(candidates) < target_total:
        con = duckdb.connect()
        con.execute("SET memory_limit='3GB';")
        con.execute("SET threads=2;")

        q_path = str(resolved_queue.resolve())
        det_exists = resolved_det.is_file()
        p12_exists = resolved_p12.is_file()
        d_path = str(resolved_det.resolve()) if det_exists else ""
        p_path = str(resolved_p12.resolve()) if p12_exists else ""
        q_cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{q_path}')").fetchall()}

        def _build_lq_body_expr(*, require_p3: bool = False) -> str:
            base_expr = "coalesce(nullif(trim(p12_clean_text), ''), nullif(trim(p12_raw_text), ''))"
            if "p3_toc_or_gavel_slice" in q_cols:
                if require_p3:
                    cond = "length(trim(coalesce(p3_toc_or_gavel_slice, ''))) > 0"
                elif "is_cover_roster_p12" in q_cols:
                    cond = "coalesce(is_cover_roster_p12, FALSE) AND length(trim(coalesce(p3_toc_or_gavel_slice, ''))) > 0"
                else:
                    return f"left({base_expr}, 9000)"
                merged_expr = (
                    f"CASE WHEN ({cond}) AND position(left(trim(p3_toc_or_gavel_slice), 40) IN coalesce({base_expr}, '')) = 0 "
                    f"THEN concat(left(coalesce({base_expr}, ''), 6400), chr(10), chr(10), '[... p3 rescue ...]', chr(10), left(trim(p3_toc_or_gavel_slice), 2500)) "
                    f"ELSE left({base_expr}, 9000) END"
                )
                return merged_expr
            return f"left({base_expr}, 9000)"

        lq_body_cover_p3 = _build_lq_body_expr(require_p3=False)
        lq_body_pkt_p3 = _build_lq_body_expr(require_p3=True)

        def _ingest_query(sql: str, *, source_pool: str, stratum_prefix: str, limit_add: int | None = None) -> int:
            added = 0
            cur = con.execute(sql)
            cols = [desc[0] for desc in cur.description]
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for tup in batch:
                    if len(candidates) >= target_total:
                        return added
                    if limit_add is not None and added >= limit_add:
                        return added
                    row = dict(zip(cols, tup))
                    label = row.get("stratum_label") or "unknown"
                    rec = _norm_candidate_record(
                        doc_key=str(row["doc_key"]),
                        text=str(row.get("body_text") or ""),
                        filename=str(row.get("filename") or ""),
                        source_pool=source_pool,
                        stratum=f"{stratum_prefix}:{label}",
                        doc_date=None,
                        event_date=row.get("rel_event_date"),
                        chamber=row.get("rel_chamber"),
                        committees=_parse_committees(row.get("rel_committees")),
                        prior_kind=row.get("locked_primary_kind"),
                        effective_format=row.get("effective_format"),
                        split_hint=None,
                    )
                    if _try_add(rec):
                        added += 1
            return added

        # Stratum A: 2026 locked docs (up to 450 stratified across locked_primary_kind)
        _ingest_query(
            f"""
            WITH ranked AS (
                SELECT
                    doc_key,
                    {lq_body_cover_p3} AS body_text,
                    filename,
                    rel_event_date,
                    rel_chamber,
                    rel_committees,
                    locked_primary_kind,
                    effective_format,
                    locked_primary_kind AS stratum_label,
                    row_number() OVER (
                        PARTITION BY locked_primary_kind
                        ORDER BY hash(doc_key || '|{seed}|2026l')
                    ) AS rn
                FROM read_parquet('{q_path}')
                WHERE locked_primary_kind IS NOT NULL
                  AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 40
                  AND (rel_event_date >= '2026-01-01' OR regexp_matches(coalesce(filename, ''), '2026[01][0-9][0-9]{{2}}'))
            )
            SELECT doc_key, body_text, filename, rel_event_date, rel_chamber, rel_committees,
                   locked_primary_kind, effective_format, stratum_label
            FROM ranked
            WHERE rn <= 40
            ORDER BY rn ASC, hash(doc_key || '|{seed}|2026l')
            LIMIT 450
            """,
            source_pool="archive_v6_2",
            stratum_prefix="2026_locked",
        )

        # Stratum B: 2026 unlocked docs (HTML + PDF, enough to guarantee >= min_2026 total)
        need_2026 = max(0, min_2026 - sum(1 for c in candidates if c["is_2026"]) + 100)
        if need_2026 > 0:
            _ingest_query(
                f"""
                SELECT
                    doc_key,
                    {lq_body_cover_p3} AS body_text,
                    filename,
                    rel_event_date,
                    rel_chamber,
                    rel_committees,
                    locked_primary_kind,
                    effective_format,
                    coalesce(effective_format, 'unknown') AS stratum_label
                FROM read_parquet('{q_path}')
                WHERE locked_primary_kind IS NULL
                  AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 40
                  AND (rel_event_date >= '2026-01-01' OR regexp_matches(coalesce(filename, ''), '2026[01][0-9][0-9]{{2}}'))
                ORDER BY hash(doc_key || '|{seed}|2026u')
                LIMIT {int(need_2026 + 150)}
                """,
                source_pool="archive_v6_2",
                stratum_prefix="2026_unlocked",
                limit_add=need_2026,
            )

        # Stratum C: Rare & balanced locked_primary_kind strata (up to 220 per distinct kind across all 30 kinds)
        _ingest_query(
            f"""
            WITH ranked AS (
                SELECT
                    doc_key,
                    {lq_body_cover_p3} AS body_text,
                    filename,
                    rel_event_date,
                    rel_chamber,
                    rel_committees,
                    locked_primary_kind,
                    effective_format,
                    locked_primary_kind AS stratum_label,
                    row_number() OVER (
                        PARTITION BY locked_primary_kind
                        ORDER BY hash(doc_key || '|{seed}|rare')
                    ) AS rn
                FROM read_parquet('{q_path}')
                WHERE locked_primary_kind IS NOT NULL
                  AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 40
            )
            SELECT doc_key, body_text, filename, rel_event_date, rel_chamber, rel_committees,
                   locked_primary_kind, effective_format, stratum_label
            FROM ranked
            WHERE rn <= 220
            ORDER BY rn ASC, hash(doc_key || '|{seed}|rare')
            LIMIT 4200
            """,
            source_pool="archive_v6_2",
            stratum_prefix="locked_kind",
            limit_add=3800,
        )

        # Stratum D: Packets & stapled documents
        _ingest_query(
            f"""
            SELECT
                doc_key,
                {lq_body_pkt_p3} AS body_text,
                filename,
                rel_event_date,
                rel_chamber,
                rel_committees,
                locked_primary_kind,
                effective_format,
                'packet_or_stapled' AS stratum_label
            FROM read_parquet('{q_path}')
            WHERE (stapled_ttf_disclosure_json IS NOT NULL
                   OR p3_toc_or_gavel_slice IS NOT NULL
                   OR lower(coalesce(p12_clean_text, '')) LIKE '%table of exhibits%')
              AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 60
            ORDER BY hash(doc_key || '|{seed}|pkt')
            LIMIT 600
            """,
            source_pool="archive_v6_2",
            stratum_prefix="packet",
            limit_add=450,
        )

        # Stratum E: Committee HTML web pages
        _ingest_query(
            f"""
            SELECT
                doc_key,
                {lq_body_cover_p3} AS body_text,
                filename,
                rel_event_date,
                rel_chamber,
                rel_committees,
                locked_primary_kind,
                effective_format,
                coalesce(locked_primary_kind, 'unlocked_html') AS stratum_label
            FROM read_parquet('{q_path}')
            WHERE effective_format = 'html'
              AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 40
            ORDER BY hash(doc_key || '|{seed}|html')
            LIMIT 900
            """,
            source_pool="archive_v6_2",
            stratum_prefix="web_html",
            limit_add=600,
        )

        # Stratum F: Non-usable / WAF / XML / blank / OCR hard negatives from deterministic + p12
        # Exclude `sha_alias` so duplicate-body links to full hearings are never pulled in with cover-only p12 lines.
        if det_exists and p12_exists:
            _ingest_query(
                f"""
                WITH ranked AS (
                    SELECT
                        d.doc_key,
                        left(coalesce(nullif(trim(p.p12_lines), ''), nullif(trim(p.html_cms_nav_stripped_text), ''), '[EMPTY_BODY]'), 9000) AS body_text,
                        d.filename,
                        d.rel_event_date,
                        d.v6_det_chamber AS rel_chamber,
                        d.v6_det_committees AS rel_committees,
                        CAST(NULL AS VARCHAR) AS locked_primary_kind,
                        d.effective_format,
                        coalesce(d.deterministic_status, 'waf_or_error') AS stratum_label,
                        row_number() OVER (
                            PARTITION BY coalesce(d.deterministic_status, 'unknown')
                            ORDER BY hash(d.doc_key || '|{seed}|neg')
                        ) AS rn
                    FROM read_parquet('{d_path}') d
                    JOIN read_parquet('{p_path}') p USING (list_row)
                    WHERE (p.waf_or_error_detected = TRUE
                           OR d.deterministic_status NOT IN ('usable', 'queued_llm', 'sha_alias'))
                      AND coalesce(d.deterministic_status, '') != 'sha_alias'
                )
                SELECT doc_key, body_text, filename, rel_event_date, rel_chamber, rel_committees,
                       locked_primary_kind, effective_format, stratum_label
                FROM ranked
                WHERE rn <= 160
                ORDER BY rn ASC, hash(doc_key || '|{seed}|neg')
                LIMIT 650
                """,
                source_pool="archive_v6_2_det",
                stratum_prefix="non_usable",
                limit_add=500,
            )

        # Stratum G: Fill remaining slots up to target_total from unlocked diverse tail
        remaining = max(0, target_total - len(candidates))
        if remaining > 0:
            _ingest_query(
                f"""
                SELECT
                    doc_key,
                    {lq_body_cover_p3} AS body_text,
                    filename,
                    rel_event_date,
                    rel_chamber,
                    rel_committees,
                    locked_primary_kind,
                    effective_format,
                    coalesce(effective_format, 'unknown') AS stratum_label
                FROM read_parquet('{q_path}')
                WHERE locked_primary_kind IS NULL
                  AND length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 80
                ORDER BY hash(doc_key || '|{seed}|tail')
                LIMIT {int(remaining + 800)}
                """,
                source_pool="archive_v6_2",
                stratum_prefix="unlocked_tail",
                limit_add=remaining,
            )

        con.close()

    # Deterministic interleave by SHA-256 of (seed, doc_key) so every shard is homogeneously stratified.
    candidates.sort(key=lambda r: hashlib.sha256(f"{seed}:{r['doc_key']}".encode("utf-8")).hexdigest())

    candidates_path = resolved_out / "candidates_v7_3.jsonl"
    with candidates_path.open("w", encoding="utf-8") as fh:
        for idx, rec in enumerate(candidates):
            out_rec = {"pool_index": idx, **rec}
            fh.write(json.dumps(out_rec, ensure_ascii=False) + "\n")

    pool_sha = hashlib.sha256(candidates_path.read_bytes()).hexdigest()
    count_2026 = sum(1 for c in candidates if c["is_2026"])
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates_path": str(candidates_path),
        "candidates_sha256": pool_sha,
        "total_candidates": len(candidates),
        "ssot_count": ssot_count,
        "mined_archive_count": len(candidates) - ssot_count,
        "count_2026": count_2026,
        "min_2026_target": min_2026,
        "source_pool_counts": dict(Counter(c["source_pool"] for c in candidates)),
        "stratum_bucket_counts": dict(Counter(c["stratum"].split(":", 1)[0] for c in candidates)),
        "top_strata_counts": dict(Counter(c["stratum"] for c in candidates).most_common(45)),
        "seed": seed,
    }
    manifest_path = resolved_out / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _shard_doc_hash(docs: Sequence[Mapping[str, Any]]) -> str:
    joined = "|".join(str(d["doc_key"]) for d in docs)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_batch_schema(item_schema: Mapping[str, Any], title: str) -> dict[str, Any]:
    """Build strict JSON schema wrapping a list of items keyed by `doc_id`."""
    item_props: dict[str, Any] = {"doc_id": {"type": "string"}}
    for k, v in (item_schema.get("properties") or {}).items():
        item_props[str(k)] = copy.deepcopy(v)
    item_req = ["doc_id", *(item_schema.get("required") or ())]
    out: dict[str, Any] = {
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": item_props,
                    "required": item_req,
                },
            }
        },
        "required": ["items"],
    }
    if isinstance(item_schema.get("$defs"), Mapping) and item_schema["$defs"]:
        out["$defs"] = copy.deepcopy(dict(item_schema["$defs"]))
    return out


def split_core_codebook_prefix() -> tuple[str, str]:
    """Return `(stripped_system_prompt, codebook_prefix)` from `render_core_prompt`."""
    full = render_core_prompt("<<PER_DOC_TEXT>>", doc_id="<<DOC_ID>>")
    marker = "DOC_ID: <<DOC_ID>>"
    idx = full.find(marker)
    if idx < 0:
        raise RuntimeError("Could not split static codebook prefix from render_core_prompt")
    prefix = full[:idx].strip()
    sys_prompt = (
        "You are a deterministic, high-precision Congressional archive document classifier "
        "and JSON extractor. Follow the DocMeta V7.1 codebook below strictly using ONLY "
        "verbatim document text. Output ONLY valid JSON conforming strictly to the requested "
        "schema. Never invent titles, dates, committees, or external metadata.\n\n"
        + prefix
    )
    return sys_prompt, prefix


def _enum_summary(core_schema: Mapping[str, Any]) -> dict[str, list[str]]:
    defs = core_schema.get("$defs")
    if not isinstance(defs, Mapping):
        return {}
    out: dict[str, list[str]] = {}
    for key in ("DocStatus", "MediaFormat", "PrimaryGenre", "SpecialistFamily", "Chamber"):
        block = defs.get(key)
        if isinstance(block, Mapping) and isinstance(block.get("enum"), list):
            out[key] = [str(v) for v in block["enum"]]
    return out


def build_audit_system_prompt(core_schema: Mapping[str, Any]) -> str:
    """Build static codebook + strict CoreEnvelopeExtraction batch JSON instructions for `agent.md`."""
    _, codebook_prefix = split_core_codebook_prefix()
    enums = _enum_summary(core_schema)
    genre_map_str = ", ".join(f"{g}->{f}" for g, f in sorted(GENRE_TO_SPECIALIST_FAMILY.items()))
    return (
        "You are a stripped, deterministic DocMeta V7.1 Congressional archive JSON classifier.\n"
        "NEVER call any tools. Output ONLY a single valid JSON object (no markdown prose).\n\n"
        f"{codebook_prefix}\n\n"
        "OUTPUT JSON CONTRACT (`items` list ordered by `doc_id`):\n"
        '{"items": [{"doc_id": "d00", "rationale": "<=450 char grounded rationale", '
        '"status": "<DocStatus>", "media_format": "<MediaFormat or null>", '
        '"is_packet": false, "contains_genres": ["<PrimaryGenre>"], '
        '"primary_genre": "<PrimaryGenre or null>", "specialist_family": "<SpecialistFamily or null>", '
        '"subkind": "<string or null>", "verbatim_title": "<string or null>", '
        '"title_span": {"quote": "<verbatim>", "start": 0, "end": 1}, '
        '"doc_date": "<YYYY-MM-DD or null>", "date_spans": [{"quote": "<verbatim>", "start": 0, "end": 1}], '
        '"chamber": "<Chamber or null>", "congress": 119, '
        '"committees": ["..."], "subcommittees": ["..."], '
        '"gist": "<concise grounded 1-2 sentence summary>", "topics": ["tag1"]}]}\n\n'
        "STRICT ENUM VALUES & NULL RULES:\n"
        f"- DocStatus: {enums.get('DocStatus', [])}\n"
        f"- MediaFormat (MUST be null when status != 'usable'): {enums.get('MediaFormat', [])}\n"
        f"- PrimaryGenre (MUST be null when status != 'usable'): {enums.get('PrimaryGenre', [])}\n"
        f"- SpecialistFamily (MUST be null when status != 'usable'; mapping: {genre_map_str})\n"
        f"- Chamber (or null): {enums.get('Chamber', [])}\n"
        "- Required on EVERY item even when null/empty: doc_id, rationale, status, media_format, "
        "is_packet, contains_genres, primary_genre, specialist_family, subkind, verbatim_title, "
        "title_span, doc_date, date_spans, chamber, congress, committees, subcommittees, gist, topics.\n"
        "- Non-usable documents (status != 'usable'): set media_format=null, is_packet=false, "
        "contains_genres=[], primary_genre=null, specialist_family=null, subkind=null, "
        "verbatim_title=null, title_span=null, doc_date=null, date_spans=[], topics=[].\n"
        "- title_span (or null) and date_spans[].quote MUST be exact verbatim substrings of THAT doc_id's text."
    )


def _pack_char_bounded_chunks(
    items: Sequence[Any],
    *,
    max_items: int,
    max_chars: int,
    len_fn: Callable[[Any], int],
) -> list[list[Any]]:
    chunks: list[list[Any]] = []
    cur: list[Any] = []
    cur_chars = 0
    for item in items:
        item_len = max(1, int(len_fn(item)))
        if cur and (len(cur) >= max(1, max_items) or cur_chars + item_len > max(1, max_chars)):
            chunks.append(cur)
            cur = []
            cur_chars = 0
        cur.append(item)
        cur_chars += item_len
    if cur:
        chunks.append(cur)
    return chunks


def _format_audit_batch_prompt(docs: Sequence[tuple[str, str]]) -> str:
    doc_ids = [did for did, _ in docs]
    lines = [
        f"Classify all {len(docs)} Congressional document(s) below independently from verbatim text only.",
        f"Return JSON `items` containing ONE entry for EVERY `doc_id` in exact order: {doc_ids}.",
        "Include all 18 required CoreEnvelopeExtraction keys plus `doc_id` on every item.",
    ]
    for idx, (did, text) in enumerate(docs, start=1):
        lines.append(
            f"\n=== DOCUMENT {idx}/{len(docs)} | doc_id={did} ===\n"
            f"<<<DOC_TEXT>>>\n{text}\n<<<END_DOC_TEXT>>>"
        )
    return "\n".join(lines)


def split_specialist_prefix(spec_family: str) -> tuple[str, str]:
    """Return `(stripped_system_prompt, codebook_prefix)` for one Stage 2 specialist family."""
    sample_genre = next(
        (g for g, fam in GENRE_TO_SPECIALIST_FAMILY.items() if fam == spec_family),
        "witness_testimony",
    )
    full = render_codebook_specialist_prompt(
        spec_family,
        "<<PER_DOC_TEXT>>",
        {
            "status": "usable",
            "specialist_family": spec_family,
            "primary_genre": sample_genre,
            "subkind": None,
            "media_format": "prose",
            "is_packet": False,
            "contains_genres": [],
        },
    )
    ctx_marker = "Stage 1 Context (text-derived only):"
    fields_marker = f"\nFields for `{spec_family}`:"
    doc_marker = "\n<<<DOC_TEXT>>>"
    c_idx = full.find(ctx_marker)
    f_idx = full.find(fields_marker)
    d_idx = full.find(doc_marker)
    if c_idx >= 0 and f_idx > c_idx and d_idx > f_idx:
        prefix = (full[:c_idx].rstrip() + "\n\n" + full[f_idx + 1 : d_idx].strip()).strip()
    elif d_idx > 0:
        prefix = full[:d_idx].strip()
    else:
        prefix = full
    sys_prompt = (
        "You are a deterministic, high-precision Congressional archive structured field extractor. "
        "Follow the Stage 2 Specialist rules below strictly using ONLY each document's verbatim text. "
        "Output ONLY valid JSON conforming strictly to the requested schema.\n\n"
        + prefix
    )
    return sys_prompt, prefix


def _format_core_batch_prompt(
    docs: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    codebook_prefix: str = "",
) -> str:
    parts: list[str] = []
    if codebook_prefix:
        parts.extend([codebook_prefix, ""])
    doc_ids = [did for did, _ in docs]
    parts.append(
        f"Classify all {len(docs)} documents below independently using strictly each "
        "document's own text (`<<<DOC_TEXT>>>`...`<<<END_DOC_TEXT>>>`).\n"
        f"Return JSON `DocMetaCoreTriageBatch` with `items` containing ONE entry for EVERY "
        f"`doc_id` in exact order: {doc_ids}.\n"
        "Do NOT invoke any tools; output the JSON object directly. Exact SpanRef start/end "
        "character offsets are computed downstream from your verbatim quotes.\n"
        "Never skip, merge, or reorder documents. Keep `title_span` and `date_spans` verbatim "
        "substrings from THAT document's text."
    )
    for i, (did, row) in enumerate(docs, start=1):
        parts.append(
            f"\n=== DOCUMENT {i} / {len(docs)} | doc_id={did} ===\n"
            f"<<<DOC_TEXT>>>\n{row['text']}\n<<<END_DOC_TEXT>>>"
        )
    return "\n".join(parts)


def _format_specialist_batch_prompt(
    docs: Sequence[tuple[str, Mapping[str, Any], Mapping[str, Any]]],
    spec_family: str,
    *,
    codebook_prefix: str = "",
) -> str:
    parts: list[str] = []
    if codebook_prefix:
        parts.extend([codebook_prefix, ""])
    doc_ids = [did for did, _, _ in docs]
    parts.append(
        f"Extract Stage 2 Specialist fields (`{spec_family}`) for all {len(docs)} documents below "
        "independently using strictly each document's own text.\n"
        f"Return JSON `DocMetaSpecialistBatch_{spec_family}` with `items` containing ONE entry for "
        f"EVERY `doc_id` in exact order: {doc_ids}.\n"
        "Do NOT invoke any tools; output the JSON object directly. Exact SpanRef start/end "
        "character offsets are computed downstream from your verbatim quotes.\n"
        "Every SpanRef quote and persona/entity name MUST appear verbatim in THAT document's text."
    )
    for i, (did, row, core_res) in enumerate(docs, start=1):
        stage1_ctx = {
            "primary_genre": core_res.get("primary_genre"),
            "subkind": core_res.get("subkind"),
            "media_format": core_res.get("media_format"),
            "is_packet": core_res.get("is_packet", False),
            "contains_genres": core_res.get("contains_genres", []),
        }
        parts.append(
            f"\n=== DOCUMENT {i} / {len(docs)} | doc_id={did} ===\n"
            f"Stage 1 Context (text-derived only): {json.dumps(stage1_ctx, ensure_ascii=False)}\n"
            f"<<<DOC_TEXT>>>\n{row['text']}\n<<<END_DOC_TEXT>>>"
        )
    return "\n".join(parts)


def _invoke_adapter_for_family(
    *,
    family: str,
    prompt_text: str,
    schema: dict[str, Any],
    config: RunnerConfig,
    adapters: Mapping[str, Callable[..., Any]] | None,
) -> AdapterOutput:
    resolved_model_id = config.model_id_for(family)
    _, adapter_fn = _resolve_adapter(family, config, adapters)
    out = adapter_fn(
        prompt_text,
        schema,
        model_id=resolved_model_id,
        timeout_s=config.timeout_s,
        rollout_id=0,
    )
    if config.on_adapter_output is not None:
        config.on_adapter_output(family, out)
    return out


def _single_doc_cache_key(
    *,
    family: str,
    model_id: str,
    blind_text: str,
    single_prompt: str,
    single_schema: Mapping[str, Any],
    cb_ver: str,
    slice_spec: str,
) -> Any:
    return make_cache_key(
        input_sha256=sha256_text(blind_text),
        codebook_version=cb_ver,
        model_id=model_id,
        prompt_hash=sha256_text(single_prompt),
        schema_hash=canonical_json_sha256(single_schema),
        slice_spec=slice_spec,
        rollout_id=0,
    )


def _unpack_and_store_batch_items(
    *,
    raw_output: AdapterOutput,
    batch_docs: Sequence[tuple[str, str, str, Mapping[str, Any], Any]],
    provider: str,
    family: str,
    stage: str,
    model_cls: Any,
    cache: SixTupleCache,
) -> dict[int, dict[str, Any]]:
    """Unpack batch `items` by `doc_id`, validate + span-ground each, and persist to `SixTupleCache`.

    `batch_docs` elements are `(short_id, doc_key, blind_text, single_cache_key, extra_meta)`.
    Returns `{idx_in_batch: parsed_dict}` for items that validated and grounded cleanly.
    """
    payload_text = raw_output.extracted_json_str or raw_output.raw_text
    try:
        _, payload = extract_json_payload(payload_text, provider=provider)
    except ValueError:
        return {}
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if (
        not isinstance(raw_items, list)
        and isinstance(payload, dict)
        and len(batch_docs) == 1
        and ("status" in payload or "rationale" in payload)
    ):
        raw_items = [payload]
    if not isinstance(raw_items, list):
        return {}

    by_id: dict[str, dict[str, Any]] = {}
    for entry in raw_items:
        if isinstance(entry, Mapping) and entry.get("doc_id"):
            by_id[str(entry["doc_id"]).strip()] = dict(entry)

    accepted: dict[int, dict[str, Any]] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    per_doc_lat = float(raw_output.latency_ms) / max(1, len(batch_docs))

    for idx, (short_id, _dk, blind_text, cache_key, _meta) in enumerate(batch_docs):
        candidate = by_id.get(short_id)
        if candidate is None and len(raw_items) == len(batch_docs) and isinstance(raw_items[idx], Mapping):
            candidate = dict(raw_items[idx])
        if candidate is None:
            continue

        cleaned = {k: v for k, v in candidate.items() if k != "doc_id"}
        raw_item_str = json.dumps(cleaned, ensure_ascii=False)
        try:
            parsed = _parse_and_validate(raw_item_str, blind_text, model_cls=model_cls)
        except Exception:
            continue

        if not verify_span_grounding(blind_text, parsed).passed:
            continue

        cache.put(
            CacheEntry(
                key=cache_key,
                raw_text=raw_item_str,
                extracted_json_str=raw_item_str,
                latency_ms=per_doc_lat,
                created_at=now_iso,
                returncode=0,
                error=None,
                family=family,
                stage=stage,
            )
        )
        accepted[idx] = parsed

    return accepted


def _run_batched_stage_for_family(
    *,
    family: str,
    docs_spec: Sequence[tuple[int, Mapping[str, Any], str, Mapping[str, Any], dict[str, Any] | None]],
    batch_size: int,
    workers: int,
    single_schema: dict[str, Any],
    batch_schema: dict[str, Any],
    single_model_cls: Any,
    cb_ver: str,
    slice_spec: str,
    stage: str,
    cfg: RunnerConfig,
    codebook_prefix: str,
    format_batch_prompt_fn: Callable[[Sequence[Any]], str],
    cache: SixTupleCache,
    adapters: Mapping[str, Callable[..., Any]] | None,
    usage_guard: UsageGuard,
    warmed_prefix_keys: set[tuple[str, str]],
) -> dict[int, FamilyRunResult]:
    """Run one stage (`core_triage` or `specialist:*`) for one family using `SixTupleCache` + micro-batches."""
    model_id = cfg.model_id_for(family)
    provider = "custom" if (adapters and family in adapters) else cfg.provider_for(family)
    is_stripped_agy = bool(provider == "agy_cli" and cfg.stripped_prefix and cfg.system_prompt and adapters is None)
    use_sys_prefix = bool(
        cfg.stripped_prefix and cfg.system_prompt and (family == "claude" or is_stripped_agy) and adapters is None
    )
    batch_prompt_prefix = "" if use_sys_prefix else codebook_prefix

    results: dict[int, FamilyRunResult] = {}
    uncached: list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]] = []

    for doc_pos, row, single_prompt, cache_key, core_res in docs_spec:
        entry = cache.get(cache_key)
        if entry is not None and entry.returncode == 0 and entry.error is None:
            try:
                parsed = _parse_and_validate(entry.raw_text, str(row["text"]), model_cls=single_model_cls)
                results[doc_pos] = FamilyRunResult(
                    family=family,
                    model_id=model_id,
                    cache_hit=True,
                    rollout_id=0,
                    ok=True,
                    raw_text=entry.raw_text,
                    extracted_json_str=entry.extracted_json_str,
                    parsed=parsed,
                    latency_ms=entry.latency_ms,
                    returncode=0,
                    error=None,
                    cache_key=cache_key,
                )
                continue
            except Exception:
                pass
        uncached.append((doc_pos, row, single_prompt, cache_key, core_res))

    if not uncached or usage_guard.should_stop():
        return results

    if is_stripped_agy:
        chunks = _pack_char_bounded_chunks(
            uncached,
            max_items=min(max(1, batch_size), 12),
            max_chars=110_000,
            len_fn=lambda it: len(str(it[1]["text"])) + 160,
        )
    else:
        chunks = [uncached[i : i + max(1, batch_size)] for i in range(0, len(uncached), max(1, batch_size))]
    failed_single_items: list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]] = []

    def _run_chunk(ch_idx: int, chunk: Sequence[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]]) -> tuple[int, list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]]]:
        if usage_guard.should_stop():
            return ch_idx, []
        short_docs = [(f"d{idx:02d}", row, core_res) for idx, (_pos, row, _sp, _ck, core_res) in enumerate(chunk)]
        if is_stripped_agy and stage == "core_triage":
            prompt_txt = _format_audit_batch_prompt([(did, str(r["text"])) for did, r, _ in short_docs])
        elif stage == "core_triage":
            prompt_txt = format_batch_prompt_fn([(did, r) for did, r, _ in short_docs])  # type: ignore[arg-type]
        else:
            prompt_txt = format_batch_prompt_fn(short_docs)  # type: ignore[arg-type]
        if batch_prompt_prefix:
            prompt_txt = batch_prompt_prefix + "\n\n" + prompt_txt

        out = _invoke_adapter_for_family(
            family=family,
            prompt_text=prompt_txt,
            schema=batch_schema,
            config=cfg,
            adapters=adapters,
        )
        if cfg.on_adapter_output is None:
            usage_guard.record(
                family,
                out.usage_pct,
                out.rate_limit_info,
                out.error,
                returncode=out.returncode,
            )

        err_blob = f"{out.error or ''} {out.raw_text or ''}".lower()
        if len(chunk) > 1 and out.returncode != 0 and (
            "invalid_json_schema" in err_blob or "invalid schema" in err_blob
        ):
            print(
                f"[batch] family={family} stage={stage} chunk={ch_idx + 1}/{len(chunks)} "
                f"accepted=0/{len(chunk)} rc={out.returncode} "
                f"usage_pct={out.usage_pct} guard={usage_guard.summary()['usage_by_family']} "
                f"err={str(out.error or out.raw_text)[:160]}",
                file=sys.stderr,
                flush=True,
            )
            usage_guard.trip(f"{family} batch schema rejected in {stage}: {(out.error or out.raw_text)[:200]}")
            return ch_idx, []

        batch_tuples = [
            (f"d{idx:02d}", str(row["doc_key"]), str(row["text"]), cache_key, core_res)
            for idx, (_pos, row, _sp, cache_key, core_res) in enumerate(chunk)
        ]
        accepted: dict[int, dict[str, Any]] = {}
        if out.returncode == 0 and out.error is None:
            accepted = _unpack_and_store_batch_items(
                raw_output=out,
                batch_docs=batch_tuples,
                provider=provider,
                family=family,
                stage=stage,
                model_cls=single_model_cls,
                cache=cache,
            )

        print(
            f"[batch] family={family} stage={stage} chunk={ch_idx + 1}/{len(chunks)} "
            f"accepted={len(accepted)}/{len(chunk)} rc={out.returncode} "
            f"usage_pct={out.usage_pct} guard={usage_guard.summary()['usage_by_family']}"
            + (f" err={str(out.error)[:160]}" if out.error else ""),
            file=sys.stderr,
            flush=True,
        )

        leftovers: list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]] = []
        per_doc_lat = float(out.latency_ms) / max(1, len(chunk))
        for idx, item in enumerate(chunk):
            doc_pos, row, _sp, cache_key, _cr = item
            if idx in accepted:
                raw_s = json.dumps(accepted[idx], ensure_ascii=False)
                results[doc_pos] = FamilyRunResult(
                    family=family,
                    model_id=model_id,
                    cache_hit=False,
                    rollout_id=0,
                    ok=True,
                    raw_text=raw_s,
                    extracted_json_str=raw_s,
                    parsed=accepted[idx],
                    latency_ms=per_doc_lat,
                    returncode=0,
                    error=None,
                    cache_key=cache_key,
                )
            else:
                leftovers.append(item)
        return ch_idx, leftovers

    warm_key = (family, stage)
    start_idx = 0
    if (
        use_sys_prefix
        and family == "claude"
        and warm_key not in warmed_prefix_keys
        and len(chunks) > 1
        and not usage_guard.should_stop()
    ):
        _, left0 = _run_chunk(0, chunks[0])
        failed_single_items.extend(left0)
        warmed_prefix_keys.add(warm_key)
        start_idx = 1

    remaining_chunks = list(enumerate(chunks))[start_idx:]
    if remaining_chunks and not usage_guard.should_stop():
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(remaining_chunks)))) as pool:
            fmap = {pool.submit(_run_chunk, ci, ch): ci for ci, ch in remaining_chunks}
            for fut in as_completed(fmap):
                _, left = fut.result()
                failed_single_items.extend(left)

    # Single-doc fallback only for missing/malformed/ungrounded leftovers (when not halted by UsageGuard).
    if failed_single_items and not usage_guard.should_stop():
        single_cfg = replace(cfg, system_prompt=cfg.system_prompt)
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(failed_single_items)))) as pool:
            def _fallback_one(
                item: tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]
            ) -> tuple[int, FamilyRunResult]:
                doc_pos, row, single_prompt, cache_key, core_res = item
                blind_text = str(row["text"])
                if usage_guard.should_stop():
                    return doc_pos, FamilyRunResult(
                        family=family,
                        model_id=model_id,
                        cache_hit=False,
                        rollout_id=0,
                        ok=False,
                        raw_text="",
                        extracted_json_str=None,
                        parsed=None,
                        latency_ms=0.0,
                        returncode=-1,
                        error="aborted_by_usage_guard",
                        cache_key=cache_key,
                    )
                if is_stripped_agy and stage == "core_triage":
                    fb_prompt = _format_audit_batch_prompt([("d00", blind_text)])
                elif family == "claude" and single_cfg.stripped_prefix and single_cfg.system_prompt and adapters is None:
                    if stage == "core_triage":
                        fb_prompt = f"DOC_ID: {row['doc_key']}\n<<<DOC_TEXT>>>\n{blind_text}\n<<<END_DOC_TEXT>>>"
                    else:
                        stage1_ctx = {
                            "primary_genre": (core_res or {}).get("primary_genre"),
                            "subkind": (core_res or {}).get("subkind"),
                            "media_format": (core_res or {}).get("media_format"),
                            "is_packet": (core_res or {}).get("is_packet", False),
                            "contains_genres": (core_res or {}).get("contains_genres", []),
                        }
                        fb_prompt = (
                            f"Stage 1 Context (text-derived only): {json.dumps(stage1_ctx, ensure_ascii=False)}\n"
                            f"<<<DOC_TEXT>>>\n{blind_text}\n<<<END_DOC_TEXT>>>"
                        )
                else:
                    fb_prompt = single_prompt

                out = _invoke_adapter_for_family(
                    family=family,
                    prompt_text=fb_prompt,
                    schema=single_schema,
                    config=single_cfg,
                    adapters=adapters,
                )
                if single_cfg.on_adapter_output is None:
                    usage_guard.record(
                        family,
                        out.usage_pct,
                        out.rate_limit_info,
                        out.error,
                        returncode=out.returncode,
                    )
                if out.returncode == 0 and out.error is None:
                    if is_stripped_agy and stage == "core_triage":
                        accepted = _unpack_and_store_batch_items(
                            raw_output=out,
                            batch_docs=[("d00", str(row["doc_key"]), blind_text, cache_key, core_res)],
                            provider=provider,
                            family=family,
                            stage=stage,
                            model_cls=single_model_cls,
                            cache=cache,
                        )
                        if 0 in accepted:
                            raw_s = json.dumps(accepted[0], ensure_ascii=False)
                            return doc_pos, FamilyRunResult(
                                family=family,
                                model_id=model_id,
                                cache_hit=False,
                                rollout_id=0,
                                ok=True,
                                raw_text=raw_s,
                                extracted_json_str=raw_s,
                                parsed=accepted[0],
                                latency_ms=out.latency_ms,
                                returncode=0,
                                error=None,
                                cache_key=cache_key,
                            )
                        return doc_pos, FamilyRunResult(
                            family=family,
                            model_id=model_id,
                            cache_hit=False,
                            rollout_id=0,
                            ok=False,
                            raw_text=out.raw_text,
                            extracted_json_str=out.extracted_json_str,
                            parsed=None,
                            latency_ms=out.latency_ms,
                            returncode=out.returncode,
                            error="parse_or_grounding_error",
                            cache_key=cache_key,
                        )
                    try:
                        parsed = _parse_and_validate(out.raw_text, blind_text, model_cls=single_model_cls)
                        cache.put(
                            CacheEntry(
                                key=cache_key,
                                raw_text=out.raw_text,
                                extracted_json_str=out.extracted_json_str,
                                latency_ms=out.latency_ms,
                                created_at=datetime.now(timezone.utc).isoformat(),
                                returncode=0,
                                error=None,
                                family=family,
                                stage=stage,
                            )
                        )
                        return doc_pos, FamilyRunResult(
                            family=family,
                            model_id=model_id,
                            cache_hit=False,
                            rollout_id=0,
                            ok=True,
                            raw_text=out.raw_text,
                            extracted_json_str=out.extracted_json_str,
                            parsed=parsed,
                            latency_ms=out.latency_ms,
                            returncode=0,
                            error=None,
                            cache_key=cache_key,
                        )
                    except Exception as exc:
                        return doc_pos, FamilyRunResult(
                            family=family,
                            model_id=model_id,
                            cache_hit=False,
                            rollout_id=0,
                            ok=False,
                            raw_text=out.raw_text,
                            extracted_json_str=out.extracted_json_str,
                            parsed=None,
                            latency_ms=out.latency_ms,
                            returncode=out.returncode,
                            error=f"parse_error: {exc}",
                            cache_key=cache_key,
                        )
                return doc_pos, FamilyRunResult(
                    family=family,
                    model_id=model_id,
                    cache_hit=False,
                    rollout_id=0,
                    ok=False,
                    raw_text=out.raw_text,
                    extracted_json_str=out.extracted_json_str,
                    parsed=None,
                    latency_ms=out.latency_ms,
                    returncode=out.returncode,
                    error=out.error or f"adapter exited with code {out.returncode}",
                    cache_key=cache_key,
                )

            sfuts = [pool.submit(_fallback_one, it) for it in failed_single_items]
            for fut in as_completed(sfuts):
                doc_pos, res = fut.result()
                results[doc_pos] = res

    return results


def _run_batched_shard(
    *,
    s_idx: int,
    total_shards: int,
    shard_rows: Sequence[Mapping[str, Any]],
    families: Sequence[str],
    specialist_families: Sequence[str] | None,
    batch_size: int,
    specialist_batch_size: int,
    workers: int,
    skip_specialist: bool,
    cb_ver: str,
    core_schema: dict[str, Any],
    specialist_schemas: Mapping[str, dict[str, Any]],
    core_cls: Any,
    spec_clses: Mapping[str, Any],
    base_runner_cfg: RunnerConfig,
    core_sys_prompt: str,
    core_prefix: str,
    core_batch_schema: dict[str, Any],
    spec_prefix_map: Mapping[str, tuple[str, str]],
    spec_batch_schemas: Mapping[str, dict[str, Any]],
    cache: SixTupleCache,
    adapters: Mapping[str, Callable[..., Any]] | None,
    check_eval_fn: Callable[..., Any] | None,
    usage_guard: UsageGuard,
    warmed_prefix_keys: set[tuple[str, str]],
) -> tuple[bool, dict[int, dict[str, Any]]]:
    """Run one shard via micro-batched Stage 1, 2/3-family CheckEval, and micro-batched Stage 2.

    Returns `(completed_without_usage_halt, ordered_doc_results)`.
    """
    n_docs = len(shard_rows)
    core_specs: list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]] = []
    core_by_family: dict[str, list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]]] = {
        fam: [] for fam in families
    }
    for pos, row in enumerate(shard_rows):
        txt = str(row["text"])
        dk = str(row["doc_key"])
        sprompt = render_core_triage_prompt(txt, cb_ver, doc_id=dk)
        for fam in families:
            ck = _single_doc_cache_key(
                family=fam,
                model_id=base_runner_cfg.model_id_for(fam),
                blind_text=txt,
                single_prompt=sprompt,
                single_schema=core_schema,
                cb_ver=cb_ver,
                slice_spec="blind_text_only:core_triage",
            )
            core_by_family[fam].append((pos, row, sprompt, ck, None))
        core_specs.append((pos, row, sprompt, None, None))

    core_cfg = replace(base_runner_cfg, system_prompt=core_sys_prompt if base_runner_cfg.stripped_prefix else None)
    core_agy_sys_prompt = build_audit_system_prompt(core_schema) if base_runner_cfg.stripped_prefix else None

    def _core_cfg_for_family(fam: str) -> RunnerConfig:
        fam_provider = "custom" if (adapters and fam in adapters) else base_runner_cfg.provider_for(fam)
        if fam_provider == "agy_cli" and base_runner_cfg.stripped_prefix:
            return replace(base_runner_cfg, system_prompt=core_agy_sys_prompt)
        return core_cfg

    core_results_by_family: dict[str, dict[int, FamilyRunResult]] = {}

    # Stage 1: run configured families concurrently in micro-batches.
    with ThreadPoolExecutor(max_workers=max(1, len(families))) as fam_pool:
        fam_futs = {
            fam_pool.submit(
                _run_batched_stage_for_family,
                family=fam,
                docs_spec=core_by_family[fam],
                batch_size=batch_size,
                workers=workers,
                single_schema=core_schema,
                batch_schema=core_batch_schema,
                single_model_cls=core_cls,
                cb_ver=cb_ver,
                slice_spec="blind_text_only:core_triage",
                stage="core_triage",
                cfg=_core_cfg_for_family(fam),
                codebook_prefix=core_prefix,
                format_batch_prompt_fn=lambda batch_items: _format_core_batch_prompt(batch_items),
                cache=cache,
                adapters=adapters,
                usage_guard=usage_guard,
                warmed_prefix_keys=warmed_prefix_keys,
            ): fam
            for fam in families
        }
        for fut in as_completed(fam_futs):
            fam = fam_futs[fut]
            core_results_by_family[fam] = fut.result()

    if usage_guard.should_stop():
        return False, {}

    # Adjudicate + CheckEval across resolved families.
    decisions: dict[int, ConsensusDecision] = {}
    final_golds: dict[int, dict[str, Any] | None] = {}

    def _guarded_ce(
        text: str,
        questions: Sequence[Any],
        sides: Mapping[str, Any],
        candidates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if usage_guard.should_stop() or check_eval_fn is None:
            return {"answers": [], "winner": "ambiguous"}
        try:
            return check_eval_fn(text, questions, sides, candidates)
        except TypeError:
            try:
                return check_eval_fn(text, questions, sides)
            except TypeError:
                return check_eval_fn(text, questions)

    active_ce = _guarded_ce if check_eval_fn is not None else None

    def _adj_one(pos: int) -> tuple[int, ConsensusDecision]:
        row = shard_rows[pos]
        dk = str(row["doc_key"])
        txt = str(row["text"])
        fam_map = {
            fam: core_results_by_family[fam][pos]
            for fam in families
            if pos in core_results_by_family.get(fam, {})
        }
        # Fill any missing entry cleanly so adjudicate sees all configured families.
        for fam in families:
            if fam not in fam_map:
                fam_map[fam] = FamilyRunResult(
                    family=fam,
                    model_id=base_runner_cfg.model_id_for(fam),
                    cache_hit=False,
                    rollout_id=0,
                    ok=False,
                    raw_text="",
                    extracted_json_str=None,
                    parsed=None,
                    latency_ms=0.0,
                    returncode=-1,
                    error="missing_result",
                    cache_key=core_by_family[fam][pos][3],
                )
        dec = adjudicate_three_family(txt, fam_map, doc_key=dk, check_eval_fn=active_ce)
        return pos, dec

    with ThreadPoolExecutor(max_workers=max(1, min(workers, n_docs))) as ce_pool:
        for fut in as_completed([ce_pool.submit(_adj_one, pos) for pos in range(n_docs)]):
            pos, dec = fut.result()
            decisions[pos] = dec
            if dec.verdict in {"auto_accept_gold", "checkeval_resolved"} and dec.accepted_payload is not None:
                final_golds[pos] = dict(dec.accepted_payload)
            else:
                final_golds[pos] = None

    if usage_guard.should_stop():
        return False, {}

    # Stage 2: micro-batched specialist extraction grouped by `specialist_family`.
    spec_fields_by_pos: dict[int, dict[str, Any] | None] = {pos: None for pos in range(n_docs)}
    active_spec_fams = tuple(specialist_families) if specialist_families else tuple(families)

    if not skip_specialist and active_spec_fams:
        by_spec_family: dict[str, list[int]] = {}
        for pos in range(n_docs):
            fg = final_golds[pos]
            if not fg or fg.get("status") != "usable":
                continue
            pg = fg.get("primary_genre")
            sf = fg.get("specialist_family") or GENRE_TO_SPECIALIST_FAMILY.get(str(pg or ""))
            if sf and sf in specialist_schemas:
                by_spec_family.setdefault(str(sf), []).append(pos)

        for sf, pos_list in sorted(by_spec_family.items()):
            if usage_guard.should_stop():
                return False, {}
            sf_schema = specialist_schemas[sf]
            sf_cls = spec_clses.get(sf)
            sf_sys_prompt, sf_prefix = spec_prefix_map[sf]
            sf_results: dict[str, dict[int, FamilyRunResult]] = {}

            for fam in active_spec_fams:
                fam_provider = "custom" if (adapters and fam in adapters) else base_runner_cfg.provider_for(fam)
                sf_cfg = replace(
                    base_runner_cfg,
                    system_prompt=(
                        sf_sys_prompt if (base_runner_cfg.stripped_prefix and fam_provider != "agy_cli") else None
                    ),
                )
                docs_spec: list[tuple[int, Mapping[str, Any], str, Any, dict[str, Any] | None]] = []
                for pos in pos_list:
                    row = shard_rows[pos]
                    txt = str(row["text"])
                    fg = final_golds[pos] or {}
                    sprompt = render_pilot_specialist_prompt(
                        txt, sf, str(fg.get("primary_genre") or ""), cb_ver, core_result=fg
                    )
                    ck = _single_doc_cache_key(
                        family=fam,
                        model_id=sf_cfg.model_id_for(fam),
                        blind_text=txt,
                        single_prompt=sprompt,
                        single_schema=sf_schema,
                        cb_ver=cb_ver,
                        slice_spec=f"blind_text_only:specialist:{sf}",
                    )
                    docs_spec.append((pos, row, sprompt, ck, fg))

                sf_results[fam] = _run_batched_stage_for_family(
                    family=fam,
                    docs_spec=docs_spec,
                    batch_size=specialist_batch_size,
                    workers=workers,
                    single_schema=sf_schema,
                    batch_schema=spec_batch_schemas[sf],
                    single_model_cls=sf_cls,
                    cb_ver=cb_ver,
                    slice_spec=f"blind_text_only:specialist:{sf}",
                    stage=f"specialist:{sf}",
                    cfg=sf_cfg,
                    codebook_prefix=sf_prefix,
                    format_batch_prompt_fn=lambda batch_items, s=sf: _format_specialist_batch_prompt(batch_items, s),
                    cache=cache,
                    adapters=adapters,
                    usage_guard=usage_guard,
                    warmed_prefix_keys=warmed_prefix_keys,
                )
                if usage_guard.should_stop():
                    return False, {}

            for pos in pos_list:
                txt = str(shard_rows[pos]["text"])
                grounded_payloads = [
                    sf_results[fam][pos].parsed
                    for fam in active_spec_fams
                    if pos in sf_results.get(fam, {})
                    and sf_results[fam][pos].ok
                    and sf_results[fam][pos].parsed is not None
                    and verify_span_grounding(txt, sf_results[fam][pos].parsed).passed
                ]
                if grounded_payloads:
                    spec_fields_by_pos[pos] = merge_consensus_payload(txt, grounded_payloads)  # type: ignore[arg-type]

    if usage_guard.should_stop():
        return False, {}

    ordered: dict[int, dict[str, Any]] = {}
    shard_verdicts: Counter[str] = Counter()
    for pos, row in enumerate(shard_rows):
        dec = decisions[pos]
        shard_verdicts[dec.verdict] += 1
        ordered[pos] = {
            "row": dict(row),
            "decision": dec,
            "final_gold": final_golds[pos],
            "specialist_fields": spec_fields_by_pos[pos],
        }
    print(
        f"[corpus] shard={s_idx + 1}/{total_shards} DONE docs={n_docs}/{n_docs} "
        f"verdicts={dict(shard_verdicts)} usage={usage_guard.summary()['usage_by_family']}",
        file=sys.stderr,
        flush=True,
    )
    return True, ordered


def run_sharded_corpus_build(
    *,
    candidates_path: Path | None = None,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
    shard_size: int = 250,
    max_shards: int | None = None,
    workers: int = 10,
    families: Sequence[str] = ("claude", "codex", "gemini"),
    timeout_s: float = 120.0,
    codex_reasoning_effort: str | None = "low",
    gemini_model: str | None = "gemini-4-carbon-low",
    claude_model: str | None = None,
    claude_effort: str | None = None,
    codex_model: str | None = None,
    dry_run: bool = False,
    skip_specialist: bool = False,
    specialist_families: Sequence[str] | None = None,
    batch_size: int = 1,
    specialist_batch_size: int = 8,
    stripped_prefix: bool = False,
    max_usage_pct: float | None = None,
    live_checkeval: bool | None = None,
    adapters: Mapping[str, Callable[..., Any]] | None = None,
    check_eval_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Process V7.3 candidate pool in checkpointed shards with idempotent resume across crashes."""
    resolved_out = (Path(out_dir) if out_dir is not None else default_corpus_dir()).resolve()
    resolved_candidates = Path(candidates_path) if candidates_path is not None else (resolved_out / "candidates_v7_3.jsonl")
    if not resolved_candidates.is_file():
        raise FileNotFoundError(f"Missing candidate pool: {resolved_candidates}")

    shards_dir = resolved_out / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    empty_cwd = Path(tempfile.gettempdir()) / "docmeta_v7_empty_cwd"
    if stripped_prefix or batch_size > 1:
        empty_cwd.mkdir(parents=True, exist_ok=True)

    resolved_cache = (
        Path(cache_path)
        if cache_path is not None
        else (resolved_out / "dry_run_cache.sqlite" if dry_run else default_cache_path())
    )

    cb_ver, core_schema, specialist_schemas, core_cls, spec_clses = _resolve_v7_runtime_specs(None)

    all_docs: list[dict[str, Any]] = []
    with resolved_candidates.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                all_docs.append(json.loads(line))

    shards = [all_docs[i : i + max(1, shard_size)] for i in range(0, len(all_docs), max(1, shard_size))]
    if max_shards is not None:
        shards = shards[: max(0, max_shards)]

    emit_telemetry = max_usage_pct is not None
    active_adapters = adapters if adapters is not None else (build_dry_run_adapters(families) if dry_run else None)
    telemetry_families = tuple(fam for fam in families if fam in ("claude", "codex")) or None
    usage_guard = UsageGuard(
        max_usage_pct=max_usage_pct,
        require_telemetry=(
            emit_telemetry
            and active_adapters is None
            and not dry_run
            and telemetry_families is not None
        ),
        telemetry_families=telemetry_families,
    )

    runner_cfg_kwargs: dict[str, Any] = {
        "timeout_s": timeout_s,
        "max_workers": max(1, len(families)),
        "stripped_prefix": bool(stripped_prefix),
        "fixed_cwd": empty_cwd if (stripped_prefix or batch_size > 1) and active_adapters is None else None,
        "emit_usage_telemetry": emit_telemetry,
        "on_adapter_output": (
            lambda fam, out: usage_guard.record(
                fam,
                out.usage_pct,
                out.rate_limit_info,
                out.error,
                returncode=out.returncode,
            )
        )
        if emit_telemetry
        else None,
    }
    if claude_model:
        runner_cfg_kwargs["claude_model"] = claude_model
    if claude_effort:
        runner_cfg_kwargs["claude_effort"] = claude_effort
    if codex_model:
        runner_cfg_kwargs["codex_model"] = codex_model
    if codex_reasoning_effort:
        runner_cfg_kwargs["codex_reasoning_effort"] = codex_reasoning_effort
    if gemini_model:
        runner_cfg_kwargs["gemini_model"] = gemini_model
    runner_cfg = RunnerConfig(**runner_cfg_kwargs)
    use_live_ce = (not dry_run and adapters is None) if live_checkeval is None else bool(live_checkeval)

    # Precompute batch schemas & stripped prefixes once for B>1 runs.
    use_batched = batch_size > 1
    core_sys_prompt, core_prefix = split_core_codebook_prefix() if use_batched else ("", "")
    core_batch_schema = build_batch_schema(core_schema, "DocMetaCoreTriageBatch") if use_batched else {}
    spec_prefix_map: dict[str, tuple[str, str]] = (
        {sf: split_specialist_prefix(sf) for sf in specialist_schemas} if use_batched else {}
    )
    spec_batch_schemas: dict[str, dict[str, Any]] = (
        {sf: build_batch_schema(sc, f"DocMetaSpecialistBatch_{sf}") for sf, sc in specialist_schemas.items()}
        if use_batched
        else {}
    )
    warmed_prefix_keys: set[tuple[str, str]] = set()

    completed_shards = 0
    skipped_shards = 0
    stopped_reason: str | None = None
    global_verdicts: Counter[str] = Counter()

    with SixTupleCache(resolved_cache) as cache:
        effective_ce = check_eval_fn
        if effective_ce is None and use_live_ce:
            arb_fam = "claude" if "claude" in families else families[0]
            ce_cfg = (
                replace(
                    runner_cfg,
                    system_prompt=(
                        "You are an evidence-locked binary checklist arbiter for Congressional "
                        "document classification. Answer strictly from the document text and emit JSON."
                    ),
                )
                if stripped_prefix
                else runner_cfg
            )
            effective_ce = build_live_sota_checkeval_fn(cache, cb_ver, ce_cfg, arbiter_family=arb_fam)

        total_shards = len(shards)
        for s_idx, shard_rows in enumerate(shards):
            if usage_guard.should_stop():
                stopped_reason = usage_guard.triggered_reason
                break

            shard_tag = f"shard_{s_idx:04d}"
            jsonl_path = shards_dir / f"{shard_tag}.jsonl"
            meta_path = shards_dir / f"{shard_tag}.meta.json"
            deadlock_md_path = shards_dir / f"deadlocks_{shard_tag}.md"
            expected_hash = _shard_doc_hash(shard_rows)

            if meta_path.is_file() and jsonl_path.is_file():
                try:
                    existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if (
                        existing_meta.get("codebook_version") == cb_ver
                        and existing_meta.get("shard_doc_hash") == expected_hash
                        and existing_meta.get("dry_run") == bool(dry_run)
                        and int(existing_meta.get("total_docs", -1)) == len(shard_rows)
                    ):
                        skipped_shards += 1
                        completed_shards += 1
                        for k, v in (existing_meta.get("verdict_counts") or {}).items():
                            global_verdicts[k] += int(v)
                        continue
                except Exception:
                    pass

            if use_batched:
                completed_ok, ordered = _run_batched_shard(
                    s_idx=s_idx,
                    total_shards=total_shards,
                    shard_rows=shard_rows,
                    families=families,
                    specialist_families=specialist_families,
                    batch_size=batch_size,
                    specialist_batch_size=specialist_batch_size,
                    workers=workers,
                    skip_specialist=skip_specialist,
                    cb_ver=cb_ver,
                    core_schema=core_schema,
                    specialist_schemas=specialist_schemas,
                    core_cls=core_cls,
                    spec_clses=spec_clses,
                    base_runner_cfg=runner_cfg,
                    core_sys_prompt=core_sys_prompt,
                    core_prefix=core_prefix,
                    core_batch_schema=core_batch_schema,
                    spec_prefix_map=spec_prefix_map,
                    spec_batch_schemas=spec_batch_schemas,
                    cache=cache,
                    adapters=active_adapters,
                    check_eval_fn=effective_ce,
                    usage_guard=usage_guard,
                    warmed_prefix_keys=warmed_prefix_keys,
                )
                if not completed_ok or usage_guard.should_stop():
                    stopped_reason = usage_guard.triggered_reason or "stopped_by_usage_guard"
                    progress = {
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "codebook_version": cb_ver,
                        "dry_run": bool(dry_run),
                        "completed_shards": completed_shards,
                        "skipped_cached_shards": skipped_shards,
                        "total_shards": total_shards,
                        "stopped_reason": stopped_reason,
                        "usage_guard": usage_guard.summary(),
                        "verdict_counts": dict(global_verdicts),
                        "cache_stats": cache.stats(),
                    }
                    tmp_prog = resolved_out / ".progress.json.tmp"
                    tmp_prog.write_text(json.dumps(progress, indent=2), encoding="utf-8")
                    tmp_prog.replace(resolved_out / "progress.json")
                    print(
                        f"[corpus] STOPPED_USAGE_CAP at shard={s_idx + 1}/{total_shards}: "
                        f"{stopped_reason} | summary={usage_guard.summary()}",
                        file=sys.stderr,
                        flush=True,
                    )
                    break

                shard_verdicts = Counter(ordered[i]["decision"].verdict for i in range(len(shard_rows)))
                global_verdicts.update(shard_verdicts)
            else:
                ordered = {}
                shard_verdicts = Counter()
                with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                    fut_map = {
                        pool.submit(
                            _process_single_doc,
                            row,
                            families=families,
                            codebook_version=cb_ver,
                            core_schema=core_schema,
                            specialist_schemas=specialist_schemas,
                            core_model_cls=core_cls,
                            specialist_model_classes=spec_clses,
                            cache=cache,
                            runner_config=runner_cfg,
                            adapters=active_adapters,
                            skip_specialist=skip_specialist,
                            check_eval_fn=effective_ce,
                            specialist_families=specialist_families,
                        ): idx
                        for idx, row in enumerate(shard_rows)
                    }
                    done = 0
                    for fut in as_completed(fut_map):
                        item = fut.result()
                        idx_in_shard = fut_map[fut]
                        ordered[idx_in_shard] = item
                        vname = item["decision"].verdict
                        shard_verdicts[vname] += 1
                        global_verdicts[vname] += 1
                        done += 1
                        if done % 10 == 0 or done == len(shard_rows):
                            print(
                                f"[corpus] shard={s_idx + 1}/{total_shards} doc={done}/{len(shard_rows)} "
                                f"key={item['row']['doc_key'][:12]} verdict={vname} "
                                f"shard_counts={dict(shard_verdicts)}",
                                file=sys.stderr,
                                flush=True,
                            )

            deadlocks = [
                ordered[i]["decision"]
                for i in range(len(shard_rows))
                if ordered[i]["decision"].verdict == "deadlock_needs_owner"
            ]
            tmp_jsonl = shards_dir / f".{shard_tag}.jsonl.tmp"
            with tmp_jsonl.open("w", encoding="utf-8") as fh:
                for i in range(len(shard_rows)):
                    it = ordered[i]
                    r = it["row"]
                    dec = it["decision"]
                    out_row = {
                        "doc_key": r["doc_key"],
                        "text_sha256": r.get("text_sha256") or sha256_text(r["text"]),
                        "filename": r.get("filename"),
                        "source_pool": r.get("source_pool"),
                        "stratum": r.get("stratum"),
                        "doc_date": r.get("doc_date"),
                        "event_date": r.get("event_date"),
                        "chamber": r.get("chamber"),
                        "committees": r.get("committees") or [],
                        "prior_kind": r.get("prior_kind"),
                        "is_2026": bool(r.get("is_2026")),
                        "verdict": dec.verdict,
                        "deadlock_reason": dec.deadlock_reason,
                        "consensus_families": dec.consensus_families,
                        "gold": it["final_gold"],
                        "specialist_fields": it["specialist_fields"],
                    }
                    fh.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            tmp_jsonl.replace(jsonl_path)

            deadlock_md_path.write_text(format_deadlock_digest(deadlocks), encoding="utf-8")
            shard_meta = {
                "shard_index": s_idx,
                "shard_tag": shard_tag,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "codebook_version": cb_ver,
                "dry_run": bool(dry_run),
                "shard_doc_hash": expected_hash,
                "total_docs": len(shard_rows),
                "verdict_counts": dict(shard_verdicts),
            }
            tmp_meta = shards_dir / f".{shard_tag}.meta.json.tmp"
            tmp_meta.write_text(json.dumps(shard_meta, indent=2), encoding="utf-8")
            tmp_meta.replace(meta_path)
            completed_shards += 1

            progress = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "codebook_version": cb_ver,
                "dry_run": bool(dry_run),
                "completed_shards": completed_shards,
                "skipped_cached_shards": skipped_shards,
                "total_shards": total_shards,
                "stopped_reason": stopped_reason,
                "usage_guard": usage_guard.summary() if max_usage_pct is not None else None,
                "verdict_counts": dict(global_verdicts),
                "cache_stats": cache.stats(),
            }
            tmp_prog = resolved_out / ".progress.json.tmp"
            tmp_prog.write_text(json.dumps(progress, indent=2), encoding="utf-8")
            tmp_prog.replace(resolved_out / "progress.json")

        cache_stats = cache.stats()

    return {
        "out_dir": str(resolved_out),
        "codebook_version": cb_ver,
        "completed_shards": completed_shards,
        "skipped_shards": skipped_shards,
        "total_shards": len(shards),
        "stopped_reason": stopped_reason,
        "usage_guard": usage_guard.summary() if max_usage_pct is not None else None,
        "verdict_counts": dict(global_verdicts),
        "cache_stats": cache_stats,
    }


def _run_cleanlab_audit(texts: Sequence[str], labels: Sequence[str]) -> dict[str, Any]:
    """Run Cleanlab Confident Learning TF-IDF OOF label-issue audit (`n_jobs=1`)."""
    counts = Counter(labels)
    viable_indices = [i for i, lbl in enumerate(labels) if counts[lbl] >= 5]
    if len(viable_indices) < 30 or len({labels[i] for i in viable_indices}) < 2:
        return {
            "checked": False,
            "reason": "insufficient_multiclass_support",
            "n_usable": len(labels),
        }

    try:
        from cleanlab.filter import find_label_issues
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
    except ImportError as exc:
        return {
            "checked": False,
            "reason": f"optional_dependency_missing:{exc.name or 'cleanlab'}",
            "n_usable": len(labels),
        }

    sub_texts = [texts[i] for i in viable_indices]
    sub_labels = [labels[i] for i in viable_indices]
    uniq = sorted(set(sub_labels))
    label_to_idx = {lbl: idx for idx, lbl in enumerate(uniq)}
    y = np.array([label_to_idx[lbl] for lbl in sub_labels], dtype=int)

    n_splits = min(5, min(Counter(y).values()))
    if n_splits < 2:
        return {"checked": False, "reason": "min_class_count_lt_2", "n_usable": len(labels)}

    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    X = vec.fit_transform(sub_texts)
    clf = LogisticRegression(max_iter=1000, C=2.0)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    pred_probs = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")
    oof_accuracy = round(float(np.mean(np.argmax(pred_probs, axis=1) == y)), 4)
    issue_idx = find_label_issues(labels=y, pred_probs=pred_probs, return_indices_ranked_by="self_confidence", n_jobs=1)

    return {
        "checked": True,
        "n_audited": len(sub_texts),
        "num_classes": len(uniq),
        "n_splits": n_splits,
        "oof_accuracy": oof_accuracy,
        "flagged_count": int(len(issue_idx)),
        "flagged_rate": round(len(issue_idx) / max(1, len(sub_texts)), 4),
    }


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")


def _clean_hex(val: Any, pat: re.Pattern[str], *, reject_zero: bool = True) -> str | None:
    if not isinstance(val, str):
        return None
    norm = val.strip().lower()
    if not pat.fullmatch(norm):
        return None
    if reject_zero and set(norm) == {"0"}:
        return None
    return norm


def _load_source_byte_identity_lookup(
    doc_keys: Sequence[str],
    *,
    cand_by_key: Mapping[str, Mapping[str, Any]],
    ssot_path: Path | None = None,
    llm_queue_path: Path | None = None,
    deterministic_path: Path | None = None,
) -> dict[str, dict[str, str | None]]:
    """Resolve authentic `(link_key_hex, saved_body_hex, effective_body_sha_hex)` without fabricating digests."""
    wanted = {str(dk) for dk in doc_keys if str(dk)}
    lookup: dict[str, dict[str, str | None]] = {}

    for dk in wanted:
        cand = cand_by_key.get(dk) or {}
        lk = _clean_hex(cand.get("link_key_hex"), _HEX16_RE, reject_zero=False)
        sb = _clean_hex(cand.get("saved_body_hex"), _HEX64_RE)
        eb = _clean_hex(cand.get("effective_body_sha_hex"), _HEX64_RE)
        if lk or sb or eb:
            lookup[dk] = {
                "link_key_hex": lk,
                "saved_body_hex": sb,
                "effective_body_sha_hex": eb,
            }

    missing = [dk for dk in sorted(wanted) if not (lookup.get(dk) or {}).get("saved_body_hex")]
    if not missing:
        return lookup

    defaults = default_parquet_paths()
    res_ssot = Path(ssot_path) if ssot_path is not None else defaults["ssot"]
    res_queue = Path(llm_queue_path) if llm_queue_path is not None else defaults["llm_queue"]
    res_det = Path(deterministic_path) if deterministic_path is not None else defaults["deterministic"]

    missing_set = set(missing)
    if res_ssot.is_file():
        with res_ssot.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                dk = str(row.get("doc_key") or "")
                if dk not in missing_set:
                    continue
                cur = lookup.setdefault(dk, {"link_key_hex": None, "saved_body_hex": None, "effective_body_sha_hex": None})
                cur["link_key_hex"] = cur["link_key_hex"] or _clean_hex(row.get("link_key_hex"), _HEX16_RE, reject_zero=False)
                cur["saved_body_hex"] = cur["saved_body_hex"] or _clean_hex(row.get("saved_body_hex"), _HEX64_RE)
                cur["effective_body_sha_hex"] = cur["effective_body_sha_hex"] or _clean_hex(
                    row.get("effective_body_sha_hex"), _HEX64_RE
                )

    still_missing = [dk for dk in sorted(wanted) if not (lookup.get(dk) or {}).get("saved_body_hex")]
    parquet_sources = [p for p in (res_queue, res_det) if p.is_file()]
    if still_missing and parquet_sources:
        con = duckdb.connect()
        con.execute("SET memory_limit='2GB';")
        con.execute("SET threads=2;")
        try:
            for pq_path in parquet_sources:
                still_missing = [dk for dk in sorted(wanted) if not (lookup.get(dk) or {}).get("saved_body_hex")]
                if not still_missing:
                    break
                p_str = str(pq_path.resolve())
                cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p_str}')").fetchall()}
                if "doc_key" not in cols or (
                    "saved_body_hex" not in cols and "link_key_hex" not in cols and "effective_body_sha_hex" not in cols
                ):
                    continue
                sel_cols = ["p.doc_key"]
                sel_cols.append("p.link_key_hex" if "link_key_hex" in cols else "CAST(NULL AS VARCHAR) AS link_key_hex")
                sel_cols.append("p.saved_body_hex" if "saved_body_hex" in cols else "CAST(NULL AS VARCHAR) AS saved_body_hex")
                sel_cols.append(
                    "p.effective_body_sha_hex"
                    if "effective_body_sha_hex" in cols
                    else "CAST(NULL AS VARCHAR) AS effective_body_sha_hex"
                )
                con.register("_wanted_keys", pa.table({"doc_key": still_missing}))
                rows = con.execute(
                    f"SELECT {', '.join(sel_cols)} FROM read_parquet('{p_str}') p "
                    "JOIN _wanted_keys w ON p.doc_key = w.doc_key"
                ).fetchall()
                for dk_raw, lk_raw, sb_raw, eb_raw in rows:
                    dk = str(dk_raw)
                    cur = lookup.setdefault(
                        dk,
                        {"link_key_hex": None, "saved_body_hex": None, "effective_body_sha_hex": None},
                    )
                    cur["link_key_hex"] = cur["link_key_hex"] or _clean_hex(lk_raw, _HEX16_RE, reject_zero=False)
                    cur["saved_body_hex"] = cur["saved_body_hex"] or _clean_hex(sb_raw, _HEX64_RE)
                    cur["effective_body_sha_hex"] = cur["effective_body_sha_hex"] or _clean_hex(eb_raw, _HEX64_RE)
        finally:
            con.close()

    return lookup


def _collect_git_codebook_provenance(repo_root: Path) -> dict[str, Any]:
    """Capture non-mutating git HEAD / untracked state of `v7/` for transparent MANIFEST provenance."""
    v7_rel = "packages/congress_docmeta/src/congress_docmeta/v7"
    codebook_rel = f"{v7_rel}/codebook_v7_0.yaml"
    try:
        head_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if head_res.returncode != 0:
            return {"git_repo": False, "git_head": None, "git_dirty": None, "codebook_tracked": False, "untracked_v7_files": []}
        git_head = head_res.stdout.strip() or None
        tracked_res = subprocess.run(
            ["git", "ls-files", "--error-unmatch", codebook_rel],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        codebook_tracked = tracked_res.returncode == 0
        st_res = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", v7_rel],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        untracked_v7: list[str] = []
        v7_dirty = False
        for ln in st_res.stdout.splitlines():
            if not ln.strip():
                continue
            v7_dirty = True
            if ln.startswith("?? "):
                untracked_v7.append(ln[3:].strip())
        repo_st_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        repo_dirty = bool(repo_st_res.stdout.strip()) or v7_dirty
        return {
            "git_repo": True,
            "git_head": git_head,
            "git_dirty": repo_dirty,
            "v7_dirty": v7_dirty,
            "codebook_tracked": codebook_tracked,
            "untracked_v7_files": sorted(untracked_v7),
        }
    except Exception:
        return {"git_repo": False, "git_head": None, "git_dirty": None, "codebook_tracked": False, "untracked_v7_files": []}


def _seal_column_specs() -> list[tuple[str, pa.DataType, str, str, bool]]:
    """Single source of truth for sealed training Parquet Arrow schema and Croissant fields_spec."""
    return [
        ("doc_key", pa.string(), "sc:Text", "Stable logical document identifier.", False),
        ("link_key_hex", pa.string(), "sc:Text", "16-char lowercase hex archive link_key when matched from source tables.", False),
        ("body_sha256", pa.string(), "sc:Text", "Lowercase SHA-256 hex digest of captured source bytes (`saved_body_hex`) when retained; null when absent.", False),
        ("effective_body_sha_hex", pa.string(), "sc:Text", "Lowercase SHA-256 hex digest of normalized effective body bytes when recorded upstream.", False),
        ("text_window_spec", pa.string(), "sc:Text", "Bounded blind text window specification fed to the V7 ensemble (`p12_clean_or_raw_head_9000`).", False),
        ("text_window_sha256", pa.string(), "sc:Text", "SHA-256 hex digest of the exact text window seen by the ensemble.", False),
        ("split", pa.string(), "sc:Text", "Leakage-proof dataset split (`train`, `dev_iter`, or `sealed_temporal_2026`).", False),
        ("verdict", pa.string(), "sc:Text", "Stage-1 triage adjudication verdict (`auto_accept_gold` or `checkeval_resolved`).", False),
        ("consensus_families", pa.list_(pa.string()), "sc:Text", "Model families participating in the winning Stage-1 triage consensus/arbiter verdict.", True),
        ("specialist_teacher", pa.string(), "sc:Text", "Single Stage-2 teacher family generating specialist_payload_json (e.g. `claude`) when populated.", False),
        ("status", pa.string(), "sc:Text", "Orthogonal V7 DocStatus triage label (usable vs wrapper/error/blank).", False),
        ("media_format", pa.string(), "sc:Text", "Orthogonal medium layout (prose, slides, web_page, table_or_form).", False),
        ("is_packet", pa.bool_(), "sc:Boolean", "Whether the captured file bundles multiple distinct substantive documents.", False),
        ("contains_genres", pa.list_(pa.string()), "sc:Text", "Ordered list of component PrimaryGenre values when is_packet is true.", True),
        ("primary_genre", pa.string(), "sc:Text", "One of 14 orthogonal V7 PrimaryGenre values when status='usable'.", False),
        ("archive_document_kind", pa.string(), "sc:Text", "Unified archive list.parquet `document_kind` string mapped via v7_to_document_kind.", False),
        ("specialist_family", pa.string(), "sc:Text", "Assigned Stage-2 specialist extractor family.", False),
        ("subkind", pa.string(), "sc:Text", "Optional fine-grained document subtype.", False),
        ("verbatim_title", pa.string(), "sc:Text", "Verbatim heading anchored in document text.", False),
        ("doc_date", pa.string(), "sc:Text", "Document's stated ISO date (YYYY, YYYY-MM, or YYYY-MM-DD).", False),
        ("chamber", pa.string(), "sc:Text", "Institutional chamber stated in document text.", False),
        ("congress", pa.int64(), "sc:Integer", "Congress number (1..130) explicitly stated in document text.", False),
        ("committees", pa.list_(pa.string()), "sc:Text", "Authoring or jurisdictional congressional committees.", True),
        ("gist", pa.string(), "sc:Text", "Concise factual summary (<= 220 chars).", False),
        ("topics", pa.list_(pa.string()), "sc:Text", "Normalized policy subject tags.", True),
        ("rationale", pa.string(), "sc:Text", "Concise CRANE/SLOT reasoning citing document cues.", False),
        ("title_span_json", pa.string(), "sc:Text", "JSON SpanRef anchoring verbatim_title inside text window.", False),
        ("date_spans_json", pa.string(), "sc:Text", "JSON list of SpanRef anchors grounding doc_date inside text window.", False),
        ("specialist_payload_json", pa.string(), "sc:Text", "JSON serialization of the Stage-2 single-teacher specialist extraction model.", False),
        ("codebook_version", pa.string(), "sc:Text", "Canonical SHA-256 hex digest of codebook_v7_0.yaml.", False),
        ("crosswalk_congress_gov_types", pa.list_(pa.string()), "sc:Text", "Mapped Congress.gov v3 committee-meeting documentType values.", True),
        ("crosswalk_docs_house_codes", pa.list_(pa.string()), "sc:Text", "Mapped docs.house.gov XML document codes.", True),
        ("crosswalk_lcgft_uris", pa.list_(pa.string()), "sc:Text", "Mapped Library of Congress LCGFT genre/form URIs.", True),
    ]


def seal_v73_corpus(
    *,
    corpus_dir: Path | None = None,
    candidates_path: Path | None = None,
    out_dir: Path | None = None,
    extra_candidates_paths: Sequence[Path] | None = None,
    extra_shard_paths: Sequence[Path] | None = None,
    overrides_path: Path | None = None,
    ssot_path: Path | None = None,
    llm_queue_path: Path | None = None,
    deterministic_path: Path | None = None,
    strict: bool = False,
    min_genre_count: int = 150,
    require_minilm: bool = False,
    require_cleanlab: bool = False,
    allow_boilerplate_tfidf: bool = False,
    decontam_waivers_path: Path | None = None,
) -> dict[str, Any]:
    """Merge completed shards, enforce canonical grounding/identity/decontam/Cleanlab gates, and emit Parquet + Croissant + DCAT-3."""
    resolved_corpus = (Path(corpus_dir) if corpus_dir is not None else default_corpus_dir()).resolve()
    resolved_out = (Path(out_dir) if out_dir is not None else (resolved_corpus / "sealed")).resolve()
    resolved_out.mkdir(parents=True, exist_ok=True)
    resolved_candidates = Path(candidates_path) if candidates_path is not None else (resolved_corpus / "candidates_v7_3.jsonl")

    # Map candidate text & metadata by doc_key so sealed output retains split/decontam context.
    cand_by_key: dict[str, dict[str, Any]] = {}
    if resolved_candidates.is_file():
        with resolved_candidates.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    cand_by_key[str(rec["doc_key"])] = rec
    for extra_cp in extra_candidates_paths or ():
        cp = Path(extra_cp)
        if cp.is_file():
            with cp.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rec = json.loads(line)
                        cand_by_key.setdefault(str(rec["doc_key"]), rec)

    shards_dir = resolved_corpus / "shards"
    shard_files = sorted(shards_dir.glob("shard_*.jsonl"))
    if not shard_files:
        raise FileNotFoundError(f"No shard_*.jsonl files found under {shards_dir}")
    for extra_sp in extra_shard_paths or ():
        sp = Path(extra_sp)
        if sp.is_file() and sp not in shard_files:
            shard_files.append(sp)

    all_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sf in shard_files:
        with sf.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                dk = str(rec["doc_key"])
                if dk not in seen:
                    seen.add(dk)
                    all_rows.append(rec)

    applied_count = 0
    resolved_overrides = Path(overrides_path) if overrides_path is not None else None
    if resolved_overrides is not None and resolved_overrides.is_file():
        overrides_by_key: dict[str, dict[str, Any]] = {}
        with resolved_overrides.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    ov = json.loads(line)
                    if ov.get("doc_key"):
                        overrides_by_key[str(ov["doc_key"])] = ov
        overlay_fields = ("verdict", "deadlock_reason", "consensus_families", "gold", "specialist_fields", "polish_source")
        for idx, row in enumerate(all_rows):
            ov = overrides_by_key.get(str(row["doc_key"]))
            if not ov:
                continue
            updated = dict(row)
            for k in overlay_fields:
                if k in ov:
                    updated[k] = ov[k]
            all_rows[idx] = updated
            applied_count += 1

    # Partition rows and enforce canonical Pydantic + verify_grounded_extraction invariants.
    gold_rows: list[dict[str, Any]] = []
    deadlock_rows: list[dict[str, Any]] = []
    quarantined_rows: list[dict[str, Any]] = []
    repair_tag_counts: Counter[str] = Counter()
    repaired_doc_count = 0
    missing_text_count = 0
    grounding_rejected: list[dict[str, Any]] = []

    for r in all_rows:
        if r.get("verdict") == "quarantined_excluded":
            quarantined_rows.append(r)
            continue
        if r.get("verdict") not in {"auto_accept_gold", "checkeval_resolved"} or not r.get("gold"):
            if r.get("verdict") == "deadlock_needs_owner":
                deadlock_rows.append(r)
            continue

        dk = str(r["doc_key"])
        txt = str((cand_by_key.get(dk) or {}).get("text") or "")
        if not txt.strip():
            missing_text_count += 1
            gold_rows.append(r)
            continue

        rec_core, rec_spec, repairs, val_errs = reconcile_and_validate_v7_payload(
            txt, r["gold"], r.get("specialist_fields")
        )
        if repairs:
            repaired_doc_count += 1
            for tag in repairs:
                repair_tag_counts[tag] += 1
        if val_errs:
            grounding_rejected.append({"doc_key": dk, "errors": val_errs})
            deadlock_rows.append(
                {
                    **r,
                    "verdict": "deadlock_needs_owner",
                    "deadlock_reason": f"canonical_grounding_validation_failed:{val_errs[0][:120]}",
                    "gold": None,
                    "specialist_fields": None,
                }
            )
            continue

        gold_rows.append({**r, "gold": rec_core, "specialist_fields": rec_spec})

    split_docs = []
    with_event_key = 0
    without_event_key = 0
    for r in gold_rows:
        c = cand_by_key.get(r["doc_key"], {})
        sd = {
            "doc_key": r["doc_key"],
            "text": str(c.get("text") or ""),
            "filename": r.get("filename") or c.get("filename") or "",
            "doc_date": (r["gold"] or {}).get("doc_date") or r.get("doc_date"),
            "event_date": r.get("event_date") or c.get("event_date"),
            "chamber": (r["gold"] or {}).get("chamber") or r.get("chamber"),
            "committees": (r["gold"] or {}).get("committees") or r.get("committees") or [],
        }
        ev_k, _ = extract_event_group_key(sd)
        if ev_k:
            with_event_key += 1
        else:
            without_event_key += 1
        split_docs.append(sd)

    split_res = build_event_temporal_splits(split_docs)
    eval_docs = split_res.splits["dev_iter"] + split_res.splits["sealed_temporal_2026"]
    decontam = audit_decontamination(split_res.splits["train"], eval_docs)

    audit_texts: list[str] = []
    audit_labels: list[str] = []
    for r in gold_rows:
        g = r["gold"] or {}
        if g.get("status") == "usable" and g.get("primary_genre"):
            txt = str((cand_by_key.get(r["doc_key"]) or {}).get("text") or "")
            if txt.strip():
                audit_texts.append(txt)
                audit_labels.append(str(g["primary_genre"]))
    cleanlab_report = _run_cleanlab_audit(audit_texts, audit_labels)
    cf_report = run_counterfactual_suite()

    id_lookup = _load_source_byte_identity_lookup(
        [str(r["doc_key"]) for r in gold_rows],
        cand_by_key=cand_by_key,
        ssot_path=ssot_path,
        llm_queue_path=llm_queue_path,
        deterministic_path=deterministic_path,
    )

    cb_hex = compute_codebook_sha256()
    cb_ver = f"v7.0:{cb_hex[:12]}"

    parquet_rows: list[dict[str, Any]] = []
    matched_link_key = 0
    matched_saved_body = 0
    missing_saved_body = 0
    consensus_tier_counts: Counter[str] = Counter()
    consensus_tuple_counts: Counter[str] = Counter()
    specialist_teacher_counts: Counter[str] = Counter()
    split_genre_counts: dict[str, dict[str, int]] = {}

    staging_dir = resolved_out / ".staging_seal"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    gold_jsonl = staging_dir / "gold_v7_3.jsonl"
    with gold_jsonl.open("w", encoding="utf-8") as fh:
        for r in gold_rows:
            dk = str(r["doc_key"])
            g = dict(r["gold"])
            c = cand_by_key.get(dk, {})
            ident = id_lookup.get(dk, {})
            lk_hex = ident.get("link_key_hex")
            sb_hex = ident.get("saved_body_hex")
            eb_hex = ident.get("effective_body_sha_hex")
            if lk_hex:
                matched_link_key += 1
            if sb_hex:
                matched_saved_body += 1
            else:
                missing_saved_body += 1

            raw_txt = str(c.get("text") or "")
            tw_sha = _clean_hex(c.get("text_sha256"), _HEX64_RE) or (sha256_text(raw_txt) if raw_txt else None)
            split_name = split_res.assignments.get(dk, "train")
            genre = g.get("primary_genre")
            if genre:
                cg_types = map_genre_to_congress_gov(genre)
                dh_codes = map_genre_to_docs_house_gov(genre)
                arch_dk = map_genre_to_document_kind(genre, subkind=g.get("subkind"))
                lcgft = map_genre_to_lcgft(genre)
                split_bucket = split_genre_counts.setdefault(split_name, {})
                split_bucket[genre] = split_bucket.get(genre, 0) + 1
            else:
                cg_types, dh_codes, arch_dk, lcgft = [], [], None, []

            cons_fams = [str(f) for f in (r.get("consensus_families") or [])]
            consensus_tier_counts[str(len(cons_fams))] += 1
            consensus_tuple_counts[",".join(sorted(cons_fams))] += 1
            spec_fields = r.get("specialist_fields")
            spec_teacher = str(r.get("specialist_teacher") or "claude") if spec_fields is not None else None
            if spec_teacher:
                specialist_teacher_counts[spec_teacher] += 1

            full_rec = {
                **r,
                "split": split_name,
                "link_key_hex": lk_hex,
                "body_sha256": sb_hex,
                "effective_body_sha_hex": eb_hex,
                "text_window_spec": "p12_clean_or_raw_head_9000",
                "text_window_sha256": tw_sha,
                "specialist_teacher": spec_teacher,
                "archive_document_kind": arch_dk,
            }
            fh.write(json.dumps(full_rec, ensure_ascii=False) + "\n")
            parquet_rows.append(
                {
                    "doc_key": dk,
                    "link_key_hex": lk_hex,
                    "body_sha256": sb_hex,
                    "effective_body_sha_hex": eb_hex,
                    "text_window_spec": "p12_clean_or_raw_head_9000",
                    "text_window_sha256": tw_sha,
                    "split": split_name,
                    "verdict": str(r["verdict"]),
                    "consensus_families": cons_fams,
                    "specialist_teacher": spec_teacher,
                    "status": str(g["status"]),
                    "media_format": g.get("media_format"),
                    "is_packet": bool(g.get("is_packet", False)),
                    "contains_genres": list(g.get("contains_genres") or []),
                    "primary_genre": genre,
                    "archive_document_kind": arch_dk,
                    "specialist_family": g.get("specialist_family"),
                    "subkind": g.get("subkind"),
                    "verbatim_title": g.get("verbatim_title"),
                    "doc_date": g.get("doc_date"),
                    "chamber": g.get("chamber"),
                    "congress": g.get("congress"),
                    "committees": list(g.get("committees") or []),
                    "gist": g.get("gist"),
                    "topics": list(g.get("topics") or []),
                    "rationale": g.get("rationale"),
                    "title_span_json": json.dumps(g.get("title_span"), ensure_ascii=False)
                    if g.get("title_span") is not None
                    else None,
                    "date_spans_json": json.dumps(g.get("date_spans"), ensure_ascii=False)
                    if g.get("date_spans")
                    else None,
                    "specialist_payload_json": json.dumps(spec_fields, ensure_ascii=False)
                    if spec_fields is not None
                    else None,
                    "codebook_version": cb_hex,
                    "crosswalk_congress_gov_types": cg_types,
                    "crosswalk_docs_house_codes": dh_codes,
                    "crosswalk_lcgft_uris": lcgft,
                }
            )

    col_specs = _seal_column_specs()
    schema = pa.schema([(name, dtype) for name, dtype, _sc, _desc, _rep in col_specs])
    fields_spec = [(name, sc_type, desc, rep) for name, _dt, sc_type, desc, rep in col_specs]

    parquet_path = staging_dir / "docmeta_v7_3.parquet"
    pq.write_table(pa.Table.from_pylist(parquet_rows, schema=schema), parquet_path)

    deadlock_jsonl = staging_dir / "deadlocks_v7_3.jsonl"
    with deadlock_jsonl.open("w", encoding="utf-8") as fh:
        for r in deadlock_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    quarantined_jsonl = staging_dir / "quarantined_v7_3.jsonl"
    with quarantined_jsonl.open("w", encoding="utf-8") as fh:
        for r in quarantined_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Load explicit reviewed similarity waivers (NEVER bypasses hard decontam hits).
    waiver_map: dict[tuple[str, str], str] = {}
    resolved_waivers = Path(decontam_waivers_path) if decontam_waivers_path is not None else None
    if resolved_waivers is not None:
        if not resolved_waivers.is_file():
            raise FileNotFoundError(f"Missing decontam_waivers_path: {resolved_waivers}")
        raw_waivers = json.loads(resolved_waivers.read_text(encoding="utf-8"))
        if not isinstance(raw_waivers, list):
            raise ValueError("decontam_waivers_path JSON root must be a list of objects.")
        for w in raw_waivers:
            if not isinstance(w, Mapping):
                raise ValueError("Each decontam waiver entry must be a mapping.")
            e_dk = str(w.get("eval_doc_key") or "").strip()
            t_dk = str(w.get("matched_train_doc_key") or "").strip()
            reason = str(w.get("reason") or "").strip()
            if not e_dk or not t_dk or not reason:
                raise ValueError(f"Invalid decontam waiver entry (requires eval_doc_key, matched_train_doc_key, reason): {w!r}")
            waiver_map[(e_dk, t_dk)] = reason

    # Write auditable decontamination hit table with full file/event context.
    split_doc_map = {sd["doc_key"]: sd for sd in split_docs}
    decontam_audit_entries: list[dict[str, Any]] = []
    applied_waivers: list[dict[str, str]] = []
    for f in decontam.flagged_docs:
        ed = split_doc_map.get(f.eval_doc_key, {})
        td = split_doc_map.get(f.matched_train_doc_key, {})
        e_ev_key, _ = extract_event_group_key(ed) if ed else (None, None)
        t_ev_key, _ = extract_event_group_key(td) if td else (None, None)
        e_dt = ed.get("event_date") or ed.get("doc_date")
        t_dt = td.get("event_date") or td.get("doc_date")
        distinct_event = bool(
            (e_ev_key and t_ev_key and e_ev_key != t_ev_key)
            or (e_dt and t_dt and str(e_dt)[:10] != str(t_dt)[:10])
        )
        w_reason = waiver_map.get((f.eval_doc_key, f.matched_train_doc_key))
        waived = w_reason is not None
        if waived:
            applied_waivers.append(
                {
                    "eval_doc_key": f.eval_doc_key,
                    "matched_train_doc_key": f.matched_train_doc_key,
                    "reason": str(w_reason),
                }
            )
        decontam_audit_entries.append(
            {
                "eval_doc_key": f.eval_doc_key,
                "eval_split": f.eval_split,
                "eval_filename": ed.get("filename"),
                "eval_event_date": e_dt,
                "eval_event_key": e_ev_key,
                "matched_train_doc_key": f.matched_train_doc_key,
                "matched_train_filename": td.get("filename"),
                "matched_train_event_date": t_dt,
                "matched_train_event_key": t_ev_key,
                "is_distinct_event": distinct_event,
                "waived": waived,
                "waiver_reason": w_reason,
                "reasons": list(f.reasons),
                "ngram8_containment": round(f.ngram8_containment, 4),
                "ngram13_containment": round(f.ngram13_containment, 4),
                "tfidf_cosine": round(f.tfidf_cosine, 4),
                "minilm_cosine": round(f.minilm_cosine, 4) if f.minilm_cosine is not None else None,
            }
        )
    decontam_audit_path = staging_dir / "decontamination_audit.json"
    decontam_audit_path.write_text(
        json.dumps(
            {
                "summary": {k: v for k, v in decontam.to_dict().items() if k != "flagged_docs"},
                "flagged_entries": decontam_audit_entries,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    today_iso = datetime.now(timezone.utc).date().isoformat()
    pq_bytes = parquet_path.read_bytes()
    pq_sha = hashlib.sha256(pq_bytes).hexdigest()
    croissant = build_croissant_manifest(
        dataset_id="urn:congressional-tech:docmeta-v7-3-training-corpus",
        name="congressional-tech-docmeta-v7-3-training-corpus",
        description=(
            "Internal DocMeta V7.3a balanced training and sealed-evaluation corpus for U.S. Congressional "
            "committee documents. Emits per-document CoreEnvelopeExtraction gold (multi-family consensus) "
            "and single-teacher (`claude`) Stage-2 specialist silver extractions. Six FRBR/ELI-DL cross-document "
            "classes in v7/models.py are retained as unpopulated future scaffolding."
        ),
        version="7.3.0",
        date_published=today_iso,
        url="urn:congressional-tech:docmeta-v7-3-training-corpus",
        parquet_filename="docmeta_v7_3.parquet",
        parquet_url="docmeta_v7_3.parquet",
        parquet_sha256=pq_sha,
        parquet_byte_size=len(pq_bytes),
        crosswalk_url="crosswalk_v7_0.yaml",
        codebook_url="codebook_v7_0.yaml",
        codebook_ver=cb_ver,
        record_count=len(parquet_rows),
        fields_spec=fields_spec,
        data_collection_raw=(
            "Bounded p12_clean_or_raw_head_9000 text windows paired with captured source byte digests "
            f"(matched_saved_body={matched_saved_body}/{len(gold_rows)}; null where legacy SSOT lacks retained bytes)."
        ),
        annotation_protocol=(
            f"Versioned codebook_v7.0 (sha256={cb_ver}); blind multi-family Stage-1 triage consensus across "
            f"Gemini, Claude CLI, and Codex CLI with CheckEval arbitration (family_tier_counts={dict(sorted(consensus_tier_counts.items()))}); "
            f"single-teacher Stage-2 specialist extraction (specialist_teacher_counts={dict(sorted(specialist_teacher_counts.items()))}); "
            "canonical Pydantic v2 + verify_grounded_extraction enforcement and Cleanlab OOF audit."
        ),
        limitations=(
            "Training-corpus artifact, not a public archive release: Stage-2 specialist payloads come from a single teacher (`claude`), "
            "not multi-family consensus. Per-document observations only; FRBR/ELI-DL cross-document classes remain unpopulated scaffolding "
            "while archive SQL owns editions and sittings. Legacy SSOT records without saved_body_hex carry body_sha256=null."
        ),
    )
    croissant_errs = validate_croissant_manifest(croissant, expected_columns=schema.names)
    if croissant_errs:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError(f"Croissant manifest validation failed: {croissant_errs}")
    croissant_path = staging_dir / "croissant_v7_3.jsonld"
    croissant_bytes = json.dumps(croissant, indent=2, ensure_ascii=False).encode("utf-8")
    croissant_path.write_bytes(croissant_bytes)
    croissant_sha = hashlib.sha256(croissant_bytes).hexdigest()

    dcat3 = build_dcat3_catalog(
        catalog_id="urn:congressional-tech:docmeta-training-catalog",
        catalog_title="Congressional Tech DocMeta V7 Training Corpus Catalog",
        dataset_id="urn:congressional-tech:docmeta-v7-3-training-corpus",
        dataset_title="DocMeta V7.3a Balanced Training & Evaluation Corpus",
        dataset_description=(
            "Internal sealed training/evaluation corpus with 3-family triage gold, single-teacher specialist silver, "
            "temporal/event-grouped splits, MiniLM + TF-IDF decontamination audit, and Cleanlab OOF audit."
        ),
        series_id="urn:congressional-tech:docmeta-training-series",
        version="7.3.0",
        issued=today_iso,
        modified=today_iso,
        publisher_url="https://congressional.tech",
        parquet_url="docmeta_v7_3.parquet",
        parquet_sha256=pq_sha,
        parquet_byte_size=len(pq_bytes),
        croissant_url="croissant_v7_3.jsonld",
        croissant_sha256=croissant_sha,
        crosswalk_url="crosswalk_v7_0.yaml",
        codebook_ver=cb_ver,
        version_notes=f"DocMeta V7.3a corpus locked to codebook_v7.0 sha256={cb_ver}",
    )
    dcat3_errs = validate_dcat3_catalog(dcat3)
    if dcat3_errs:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError(f"DCAT-3 catalog validation failed: {dcat3_errs}")
    dcat3_path = staging_dir / "dcat3_v7_3.jsonld"
    dcat3_path.write_text(json.dumps(dcat3, indent=2, ensure_ascii=False), encoding="utf-8")

    genre_counts = dict(Counter(r["primary_genre"] for r in parquet_rows if r["primary_genre"]))
    hard_decontam_reasons = ("exact_sha", "normalized_text_hash", "event_group_overlap", "ngram8_containment", "ngram13_containment")
    hard_decontam_zero = all(decontam.reason_counts.get(k, 0) == 0 for k in hard_decontam_reasons)
    all_sim_accounted = (
        all(e["is_distinct_event"] or e["waived"] for e in decontam_audit_entries) if decontam_audit_entries else True
    )
    sim_gate_ok = bool(decontam.clean) or (allow_boilerplate_tfidf and hard_decontam_zero and all_sim_accounted)
    minilm_gate_ok = bool(decontam.minilm_checked) if (require_minilm or strict) else True
    cleanlab_gate_ok = bool(cleanlab_report.get("checked")) if (require_cleanlab or strict) else True
    missing_floor_genres = [
        g.value for g in PrimaryGenre if genre_counts.get(g.value, 0) < min_genre_count
    ]
    genre_floor_ok = (len(missing_floor_genres) == 0) if strict else True
    grounding_gate_ok = len(grounding_rejected) == 0
    croissant_parity_ok = len(croissant_errs) == 0

    # Hygiene audit checks: same body_sha256 must not hold conflicting status labels,
    # and zero sealed gold rows may have blank-head or stub-head tail-only windows (`[... page N tail ...]`).
    statuses_by_body: dict[str, set[str]] = {}
    blank_head_tail_docs: list[str] = []
    for pr in parquet_rows:
        sb = pr.get("body_sha256")
        if sb:
            statuses_by_body.setdefault(str(sb), set()).add(str(pr.get("status") or ""))
        dk_row = str(pr.get("doc_key") or "")
        cand_txt = str((cand_by_key.get(dk_row) or {}).get("text") or "")
        if _is_blank_or_stub_head_tail(cand_txt):
            blank_head_tail_docs.append(dk_row)
    body_sha_contradictions = sorted(sb for sb, s_set in statuses_by_body.items() if len(s_set) > 1)
    body_sha_consistency_ok = len(body_sha_contradictions) == 0
    zero_blank_head_tail_ok = len(blank_head_tail_docs) == 0
    hygiene_audit = {
        "quarantined_count": len(quarantined_rows),
        "body_sha_contradiction_count": len(body_sha_contradictions),
        "body_sha_contradictions": body_sha_contradictions[:25],
        "blank_head_tail_only_count": len(blank_head_tail_docs),
        "blank_head_tail_only_docs": blank_head_tail_docs[:25],
    }

    checks = {
        "hard_decontam_zero": hard_decontam_zero,
        "similarity_decontam": sim_gate_ok,
        "minilm_checked": minilm_gate_ok,
        "cleanlab_checked": cleanlab_gate_ok,
        "genre_floor": genre_floor_ok,
        "canonical_grounding_zero_errors": grounding_gate_ok,
        "croissant_column_parity": croissant_parity_ok,
        "body_sha_status_consistency": body_sha_consistency_ok,
        "zero_blank_head_tail_only": zero_blank_head_tail_ok,
    }
    failed_gates = [name for name, ok in checks.items() if not ok]
    seal_gates = {
        "strict_mode": bool(strict),
        "min_genre_count": min_genre_count,
        "passed": len(failed_gates) == 0,
        "failed_gates": failed_gates,
        "missing_floor_genres": missing_floor_genres,
        "checks": checks,
    }

    git_provenance = _collect_git_codebook_provenance(discover_main_checkout_root())

    manifest = {
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "codebook_version": cb_ver,
        "codebook_sha256": cb_hex,
        "git_provenance": git_provenance,
        "total_processed": len(all_rows),
        "gold_count": len(gold_rows),
        "deadlock_count": len(deadlock_rows),
        "quarantined_count": len(quarantined_rows),
        "verdict_counts": dict(Counter(r.get("verdict") for r in all_rows)),
        "consensus_family_tier_counts": dict(sorted(consensus_tier_counts.items())),
        "consensus_family_tuple_counts": dict(sorted(consensus_tuple_counts.items())),
        "specialist_teacher_counts": dict(sorted(specialist_teacher_counts.items())),
        "genre_counts": genre_counts,
        "split_genre_counts": {k: dict(sorted(v.items())) for k, v in sorted(split_genre_counts.items())},
        "status_counts": dict(Counter(r["status"] for r in parquet_rows)),
        "splits": {"counts": split_res.counts, "temporal_cutoff": split_res.temporal_cutoff},
        "event_key_coverage": {
            "total_gold": len(gold_rows),
            "with_event_key": with_event_key,
            "without_event_key": without_event_key,
        },
        "source_identity_coverage": {
            "total_gold": len(gold_rows),
            "matched_link_key": matched_link_key,
            "matched_saved_body": matched_saved_body,
            "missing_saved_body": missing_saved_body,
        },
        "grounding_audit": {
            "checked": len(gold_rows) + len(grounding_rejected) - missing_text_count,
            "missing_text_count": missing_text_count,
            "repaired_count": repaired_doc_count,
            "repair_tag_counts": dict(sorted(repair_tag_counts.items())),
            "rejected_count": len(grounding_rejected),
            "rejected_docs": grounding_rejected,
            "verified_zero_errors": len(grounding_rejected) == 0,
        },
        "decontamination": decontam.to_dict(),
        "cleanlab": cleanlab_report,
        "counterfactual_suite": {
            "total": cf_report.total,
            "passed_count": cf_report.passed_count,
            "pass_rate": cf_report.pass_rate,
            "evaluation_mode": cf_report.evaluation_mode,
        },
        "hygiene_audit": hygiene_audit,
        "seal_gates": seal_gates,
        "files": {
            "parquet": str(resolved_out / parquet_path.name),
            "parquet_sha256": pq_sha,
            "gold_jsonl": str(resolved_out / gold_jsonl.name),
            "deadlocks_jsonl": str(resolved_out / deadlock_jsonl.name),
            "quarantined_jsonl": str(resolved_out / quarantined_jsonl.name),
            "decontamination_audit": str(resolved_out / decontam_audit_path.name),
            "croissant": str(resolved_out / croissant_path.name),
            "croissant_sha256": croissant_sha,
            "dcat3": str(resolved_out / dcat3_path.name),
        },
    }
    if resolved_overrides is not None:
        manifest["polish_overrides_applied"] = applied_count
    if resolved_waivers is not None:
        manifest["decontamination_waivers_applied"] = applied_waivers
        manifest["files"]["decontam_waivers"] = str(resolved_waivers)

    failed_manifest_path = resolved_out / "MANIFEST_FAILED.json"
    manifest_path = resolved_out / "MANIFEST.json"
    if strict and not seal_gates["passed"]:
        shutil.rmtree(staging_dir, ignore_errors=True)
        failed_tmp = resolved_out / "MANIFEST_FAILED.json.tmp"
        failed_tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(failed_tmp, failed_manifest_path)
        raise RuntimeError(
            f"Strict seal gate failed ({failed_gates}); missing_floor_genres={missing_floor_genres}; "
            f"forensics written to {failed_manifest_path}"
        )

    for staged_file in (
        gold_jsonl,
        parquet_path,
        deadlock_jsonl,
        quarantined_jsonl,
        decontam_audit_path,
        croissant_path,
        dcat3_path,
    ):
        os.replace(staged_file, resolved_out / staged_file.name)
    shutil.rmtree(staging_dir, ignore_errors=True)

    if failed_manifest_path.is_file():
        failed_manifest_path.unlink()
    manifest_tmp = resolved_out / "MANIFEST.json.tmp"
    manifest_tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(manifest_tmp, manifest_path)
    return manifest


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DocMeta V7.3 10K+ corpus builder, sharder & sealer.")
    sub = p.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("build-pool", help="Build stratified V7.3 10K+ candidate pool.")
    bp.add_argument("--ssot-path", type=Path, default=None)
    bp.add_argument("--llm-queue-path", type=Path, default=None)
    bp.add_argument("--deterministic-path", type=Path, default=None)
    bp.add_argument("--p12-path", type=Path, default=None)
    bp.add_argument("--out-dir", type=Path, default=None)
    bp.add_argument("--target", type=int, default=10500)
    bp.add_argument("--min-2026", type=int, default=700)
    bp.add_argument("--seed", type=int, default=20261122)

    rn = sub.add_parser("run", help="Run checkpointed 3-family labeling shards.")
    rn.add_argument("--candidates", type=Path, default=None)
    rn.add_argument("--out-dir", type=Path, default=None)
    rn.add_argument("--cache-path", type=Path, default=None)
    rn.add_argument("--shard-size", type=int, default=250)
    rn.add_argument("--max-shards", type=int, default=None)
    rn.add_argument("--workers", type=int, default=10)
    rn.add_argument("--timeout", type=float, default=120.0)
    rn.add_argument("--families", type=str, default="claude,codex,gemini")
    rn.add_argument("--codex-reasoning", type=str, default="low")
    rn.add_argument("--gemini-model", type=str, default="gemini-4-carbon-low")
    rn.add_argument("--claude-model", type=str, default=None)
    rn.add_argument("--claude-effort", type=str, default=None)
    rn.add_argument("--codex-model", type=str, default=None)
    rn.add_argument("--skip-specialist", action="store_true")
    rn.add_argument("--specialist-families", type=str, default=None)
    rn.add_argument("--batch-size", type=int, default=1)
    rn.add_argument("--specialist-batch-size", type=int, default=8)
    rn.add_argument("--stripped-prefix", action="store_true")
    rn.add_argument("--max-usage-pct", type=float, default=None)
    rn.add_argument("--no-live-checkeval", action="store_true")
    rn.add_argument("--dry-run", action="store_true")

    sl = sub.add_parser("seal", help="Merge shards, run Cleanlab/decontam/splits, emit Croissant + DCAT-3.")
    sl.add_argument("--corpus-dir", type=Path, default=None)
    sl.add_argument("--candidates", type=Path, default=None)
    sl.add_argument("--out-dir", type=Path, default=None)
    sl.add_argument("--extra-candidates", action="append", type=Path, default=None)
    sl.add_argument("--extra-shards", action="append", type=Path, default=None)
    sl.add_argument("--overrides", type=Path, default=None)
    sl.add_argument("--ssot-path", type=Path, default=None)
    sl.add_argument("--llm-queue-path", type=Path, default=None)
    sl.add_argument("--deterministic-path", type=Path, default=None)
    sl.add_argument("--strict", action="store_true")
    sl.add_argument("--min-genre-count", type=int, default=150)
    sl.add_argument("--require-minilm", action="store_true")
    sl.add_argument("--require-cleanlab", action="store_true")
    sl.add_argument("--allow-boilerplate-tfidf", action="store_true")
    sl.add_argument("--decontam-waivers", type=Path, default=None)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "build-pool":
        res = build_v73_candidate_pool(
            ssot_path=args.ssot_path,
            llm_queue_path=args.llm_queue_path,
            deterministic_path=args.deterministic_path,
            p12_path=args.p12_path,
            out_dir=args.out_dir,
            target_total=args.target,
            min_2026=args.min_2026,
            seed=args.seed,
        )
        print(json.dumps(res, indent=2))
        return 0
    if args.command == "run":
        fams = [f.strip() for f in args.families.split(",") if f.strip()]
        spec_fams = (
            [f.strip() for f in args.specialist_families.split(",") if f.strip()]
            if args.specialist_families
            else None
        )
        res = run_sharded_corpus_build(
            candidates_path=args.candidates,
            out_dir=args.out_dir,
            cache_path=args.cache_path,
            shard_size=args.shard_size,
            max_shards=args.max_shards,
            workers=args.workers,
            families=fams,
            timeout_s=args.timeout,
            codex_reasoning_effort=args.codex_reasoning,
            gemini_model=args.gemini_model,
            claude_model=args.claude_model,
            claude_effort=args.claude_effort,
            codex_model=args.codex_model,
            dry_run=args.dry_run,
            skip_specialist=args.skip_specialist,
            specialist_families=spec_fams,
            batch_size=args.batch_size,
            specialist_batch_size=args.specialist_batch_size,
            stripped_prefix=args.stripped_prefix,
            max_usage_pct=args.max_usage_pct,
            live_checkeval=False if args.no_live_checkeval else None,
        )
        print(json.dumps(res, indent=2))
        return 0
    res = seal_v73_corpus(
        corpus_dir=args.corpus_dir,
        candidates_path=args.candidates,
        out_dir=args.out_dir,
        extra_candidates_paths=args.extra_candidates,
        extra_shard_paths=args.extra_shards,
        overrides_path=args.overrides,
        ssot_path=args.ssot_path,
        llm_queue_path=args.llm_queue_path,
        deterministic_path=args.deterministic_path,
        strict=args.strict,
        min_genre_count=args.min_genre_count,
        require_minilm=args.require_minilm,
        require_cleanlab=args.require_cleanlab,
        allow_boilerplate_tfidf=args.allow_boilerplate_tfidf,
        decontam_waivers_path=args.decontam_waivers,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_v73_candidate_pool",
    "default_corpus_dir",
    "default_parquet_paths",
    "main",
    "run_sharded_corpus_build",
    "seal_v73_corpus",
]
