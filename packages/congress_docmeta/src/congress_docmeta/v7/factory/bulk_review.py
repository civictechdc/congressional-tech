"""Stripped `gemini-4-neon-medium` `agy` bulk auditor & deadlock adjudicator (`ct-so28`).

Runs safely alongside an active `corpus_builder` daemon:
  * Treats sealed shards (`shards/shard_*.jsonl`, `shards/deadlocks_shard_*.md`) and the
    production `cache.sqlite` as strictly read-only.
  * Stores all review artifacts in a separate output directory (`bulk_review/`) with its own
    dedicated `review_cache.sqlite`.
  * Pass A: Blind 3rd-family (`gemini-4-neon-medium`) micro-batched audit of 2-family shards.
  * Pass B: Micro-batched deadlock adjudication across all sealed shards (`deadlock_needs_owner`).

Usage:
    .venv/bin/python -m congress_docmeta.v7.factory.bulk_review run \\
        --corpus-dir .cache/archive-release/docmeta-v7-corpus \\
        --out-dir .cache/archive-release/docmeta-v7-corpus/bulk_review \\
        --model gemini-4-neon-medium --follow-until-shards 42
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from .cache import (
    CacheEntry,
    SixTupleCache,
    canonical_json_sha256,
    make_cache_key,
    sha256_text,
)
from .corpus_builder import (
    _enum_summary,
    _format_audit_batch_prompt,
    _pack_char_bounded_chunks,
    _shard_doc_hash,
    build_audit_system_prompt,
    default_corpus_dir,
    split_core_codebook_prefix,
)
from .grounding import (
    _collapse_ws,
    _norm_typography,
    extract_triage_tuple,
    verify_span_grounding,
)
from .pilot import (
    GENRE_TO_SPECIALIST_FAMILY,
    _parse_and_validate,
    _resolve_v7_runtime_specs,
)
from .runners import (
    AdapterOutput,
    UsageGuard,
    _AGY_QUOTA_ERR_RE,
    _QUOTA_ERR_RE,
    _normalize_adapter_result,
    extract_json_payload,
    invoke_agy_stripped_cli,
)

DEFAULT_BULK_MODEL = "gemini-4-neon-medium"
_DL_HEADER_RE = re.compile(r"^##\s+\d+\.\s+`([^`]+)`\s+\(`([^`]+)`\)")
_DL_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|$"
)
_DL_ISSUE_RE = re.compile(r"^-\s+\*\*(\w+)\s+grounding issues:\*\*\s*(.+)$")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp"
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _atomic_write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp"
    with tmp_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    tmp_path.replace(path)


def _is_quota_error(text: str | None) -> bool:
    if not text:
        return False
    return bool(_QUOTA_ERR_RE.search(text) or _AGY_QUOTA_ERR_RE.search(text))


def build_deadlock_system_prompt(core_schema: Mapping[str, Any]) -> str:
    """Build static codebook + deadlock adjudication JSON instructions for `agent.md`."""
    _, codebook_prefix = split_core_codebook_prefix()
    enums = _enum_summary(core_schema)
    genre_map_str = ", ".join(f"{g}->{f}" for g, f in sorted(GENRE_TO_SPECIALIST_FAMILY.items()))
    return (
        "You are a stripped, deterministic DocMeta V7.1 Congressional archive deadlock adjudicator.\n"
        "NEVER call any tools. Inspect each document's verbatim text and the prior family/CheckEval "
        "notes, then decide whether the codebook cleanly resolves the tie or genuinely needs an owner patch.\n"
        "Output ONLY a single valid JSON object.\n\n"
        f"{codebook_prefix}\n\n"
        "OUTPUT JSON CONTRACT (`items` list ordered by `doc_id`):\n"
        '{"items": [{"doc_id": "d00", '
        '"recommended_action": "resolve" | "keep_deadlock", '
        '"matches_prior_family": "claude" | "codex" | "gemini" | "new" | null, '
        '"confidence": "high" | "medium" | "low", '
        '"evidence_quote": "<exact verbatim substring from THIS doc text supporting your decision>", '
        '"rationale": "<concise evidence-grounded adjudication rationale>", '
        '"recommended_core": {"rationale": "...", "status": "<DocStatus>", '
        '"media_format": "<MediaFormat or null>", "is_packet": false, "contains_genres": [], '
        '"primary_genre": "<PrimaryGenre or null>", "specialist_family": "<SpecialistFamily or null>", '
        '"subkind": null, "verbatim_title": null, "title_span": null, "doc_date": null, '
        '"date_spans": [], "chamber": null, "congress": null, "committees": [], "subcommittees": [], '
        '"gist": "...", "topics": []}}]}\n\n'
        "STRICT RULES:\n"
        "- If recommended_action == 'resolve', recommended_core MUST include ALL 18 CoreEnvelopeExtraction fields above.\n"
        "- If recommended_action == 'keep_deadlock', set recommended_core=null and matches_prior_family=null.\n"
        f"- DocStatus: {enums.get('DocStatus', [])}\n"
        f"- MediaFormat (null if status != 'usable'): {enums.get('MediaFormat', [])}\n"
        f"- PrimaryGenre (null if status != 'usable'): {enums.get('PrimaryGenre', [])}\n"
        f"- SpecialistFamily ({genre_map_str}): {enums.get('SpecialistFamily', [])}\n"
        f"- Chamber (or null): {enums.get('Chamber', [])}\n"
        "- evidence_quote and every SpanRef.quote in recommended_core MUST appear verbatim in THAT doc_id's text."
    )


def _format_deadlock_batch_prompt(docs: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
    doc_ids = [did for did, _ in docs]
    lines = [
        f"Adjudicate all {len(docs)} deadlocked document(s) below from verbatim text and prior family votes.",
        f"Return JSON `items` containing ONE entry for EVERY `doc_id` in exact order: {doc_ids}.",
    ]
    for idx, (did, ctx) in enumerate(docs, start=1):
        prior_rows = ctx.get("family_votes") or {}
        ce_info = ctx.get("checkeval_summary") or ""
        issues = ctx.get("grounding_issues") or {}
        lines.append(
            f"\n=== DEADLOCK {idx}/{len(docs)} | doc_id={did} | reason={ctx.get('deadlock_reason')} ===\n"
            f"Prior family votes: {json.dumps(prior_rows, ensure_ascii=False)}\n"
            + (f"Grounding issues: {json.dumps(issues, ensure_ascii=False)}\n" if issues else "")
            + (f"CheckEval summary: {ce_info}\n" if ce_info else "")
            + f"<<<DOC_TEXT>>>\n{ctx['text']}\n<<<END_DOC_TEXT>>>"
        )
    return "\n".join(lines)


def parse_deadlock_digest_md(md_path: Path) -> dict[str, dict[str, Any]]:
    """Parse `deadlocks_shard_XXXX.md` into per-`doc_key` prior family votes & CheckEval context."""
    if not md_path.is_file():
        return {}
    entries: dict[str, dict[str, Any]] = {}
    cur_key: str | None = None
    cur: dict[str, Any] = {}

    with md_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            m_hdr = _DL_HEADER_RE.match(line.strip())
            if m_hdr:
                if cur_key:
                    entries[cur_key] = cur
                cur_key = m_hdr.group(1).strip()
                cur = {
                    "doc_key": cur_key,
                    "deadlock_reason": m_hdr.group(2).strip(),
                    "family_votes": {},
                    "grounding_issues": {},
                    "checkeval_summary": "",
                }
                continue
            if not cur_key:
                continue

            stripped = line.strip()
            m_row = _DL_ROW_RE.match(stripped)
            if m_row:
                fam, st, mf, pkt, pg, gr = (m_row.group(i) for i in range(1, 7))
                cur["family_votes"][fam] = {
                    "status": None if st == "None" else st,
                    "media_format": None if mf == "None" else mf,
                    "is_packet": None if pkt == "None" else (pkt == "True"),
                    "primary_genre": None if pg == "None" else pg,
                    "grounding": gr,
                }
                continue

            m_iss = _DL_ISSUE_RE.match(stripped)
            if m_iss:
                cur["grounding_issues"][m_iss.group(1)] = m_iss.group(2).strip()
                continue

            if stripped.startswith("- **CheckEval arbiter:**"):
                cur["checkeval_summary"] = stripped[len("- **CheckEval arbiter:**") :].strip()
            elif stripped.startswith("- `q_") and cur.get("checkeval_summary") is not None:
                prev = cur["checkeval_summary"]
                cur["checkeval_summary"] = f"{prev} | {stripped[2:]}" if prev else stripped[2:]

    if cur_key:
        entries[cur_key] = cur
    return entries


def _quote_in_text(quote: str | None, doc_text: str) -> bool:
    if not isinstance(quote, str):
        return False
    cleaned = _collapse_ws(_norm_typography(quote))
    if len(cleaned) < 3:
        return False
    if quote in doc_text:
        return True
    norm_doc = _collapse_ws(_norm_typography(doc_text))
    return cleaned.casefold() in norm_doc.casefold()


def _invoke_review_adapter(
    *,
    prompt: str,
    system_prompt: str,
    model_id: str,
    timeout_s: float,
    adapter_fn: Callable[..., Any] | None,
) -> AdapterOutput:
    if adapter_fn is not None:
        t0 = time.perf_counter()
        try:
            res = adapter_fn(
                prompt,
                system_prompt=system_prompt,
                model_id=model_id,
                timeout_s=timeout_s,
            )
        except TypeError:
            try:
                res = adapter_fn(prompt, system_prompt, model_id=model_id, timeout_s=timeout_s)
            except TypeError:
                res = adapter_fn(prompt, system_prompt)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return _normalize_adapter_result(res, elapsed, provider="agy_cli")

    return invoke_agy_stripped_cli(
        prompt,
        system_prompt=system_prompt,
        model_id=model_id,
        timeout_s=timeout_s,
    )


def _extract_batch_items(out: AdapterOutput) -> list[Any] | None:
    payload_text = out.extracted_json_str or out.raw_text
    if not payload_text:
        return None
    try:
        _, payload = extract_json_payload(payload_text, provider="agy_cli")
    except ValueError:
        return None
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
        if "status" in payload or "recommended_action" in payload:
            return [payload]
    return None


def _load_candidates_text_map(candidates_path: Path) -> dict[str, str]:
    text_by_key: dict[str, str] = {}
    with candidates_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            dk = str(row.get("doc_key") or "")
            if dk:
                text_by_key[dk] = str(row.get("text") or "")
    return text_by_key


def _discover_sealed_shards(shards_dir: Path) -> list[tuple[int, Path, Path]]:
    """Return sorted `[(shard_idx, jsonl_path, meta_path)]` for all valid sealed shards."""
    found: list[tuple[int, Path, Path]] = []
    if not shards_dir.is_dir():
        return found
    for meta_path in sorted(shards_dir.glob("shard_*.meta.json")):
        m = re.match(r"^shard_(\d+)\.meta\.json$", meta_path.name)
        if not m:
            continue
        idx = int(m.group(1))
        jsonl_path = shards_dir / f"shard_{idx:04d}.jsonl"
        if not jsonl_path.is_file():
            continue
        found.append((idx, jsonl_path, meta_path))
    found.sort(key=lambda t: t[0])
    return found


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _classify_audit_status(
    *,
    verdict: str,
    gold_tuple: tuple[Any, Any, Any, Any] | None,
    neon_tuple: tuple[Any, Any, Any, Any] | None,
) -> tuple[str, list[str]]:
    if neon_tuple is None:
        return "neon_failed", []
    if verdict == "deadlock_needs_owner" or gold_tuple is None:
        return "deadlock_neon_vote", []
    field_names = ("status", "media_format", "is_packet", "primary_genre")
    diffs = [name for name, gval, nval in zip(field_names, gold_tuple, neon_tuple) if gval != nval]
    if not diffs:
        return ("confirmed_checkeval" if verdict == "checkeval_resolved" else "confirmed_3of3"), []
    return ("disagreement_checkeval" if verdict == "checkeval_resolved" else "disagreement_gold"), diffs


def _review_one_2fam_shard(
    *,
    shard_idx: int,
    shard_jsonl: Path,
    review_shards_dir: Path,
    text_by_key: Mapping[str, str],
    model_id: str,
    cb_ver: str,
    core_schema: Mapping[str, Any],
    core_cls: Any,
    audit_sys_prompt: str,
    batch_size: int,
    max_batch_chars: int,
    workers: int,
    timeout_s: float,
    cache: SixTupleCache,
    guard: UsageGuard,
    adapter_fn: Callable[..., Any] | None,
) -> tuple[bool, list[dict[str, Any]]]:
    shard_rows = _read_jsonl_rows(shard_jsonl)
    expected_hash = _shard_doc_hash(shard_rows)
    rev_jsonl = review_shards_dir / f"review_shard_{shard_idx:04d}.jsonl"
    rev_meta = review_shards_dir / f"review_shard_{shard_idx:04d}.meta.json"

    if rev_meta.is_file() and rev_jsonl.is_file():
        try:
            meta = json.loads(rev_meta.read_text(encoding="utf-8"))
            if (
                meta.get("model_id") == model_id
                and meta.get("codebook_version") == cb_ver
                and meta.get("shard_doc_hash") == expected_hash
                and int(meta.get("total_docs", -1)) == len(shard_rows)
            ):
                return True, _read_jsonl_rows(rev_jsonl)
        except Exception:
            pass

    schema_hash = canonical_json_sha256(core_schema)
    prompt_hash = sha256_text(audit_sys_prompt)
    cache_lock = threading.Lock()

    parsed_by_pos: dict[int, dict[str, Any]] = {}
    uncached: list[tuple[int, str, str, Any]] = []  # (pos, doc_key, blind_text, cache_key)

    for pos, row in enumerate(shard_rows):
        dk = str(row["doc_key"])
        blind_text = text_by_key.get(dk, "")
        ck = make_cache_key(
            input_sha256=sha256_text(blind_text),
            codebook_version=cb_ver,
            model_id=model_id,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            slice_spec="blind_text_only:bulk_review_core",
            rollout_id=0,
        )
        with cache_lock:
            entry = cache.get(ck)
        if entry is not None and entry.returncode == 0 and entry.error is None:
            try:
                parsed = _parse_and_validate(entry.raw_text, blind_text, model_cls=core_cls)
                if verify_span_grounding(blind_text, parsed).passed:
                    parsed_by_pos[pos] = parsed
                    continue
            except Exception:
                pass
        if blind_text:
            uncached.append((pos, dk, blind_text, ck))

    def _store_accepted(
        batch_docs: Sequence[tuple[str, int, str, str, Any]],
        out: AdapterOutput,
    ) -> dict[int, dict[str, Any]]:
        raw_items = _extract_batch_items(out)
        if not raw_items:
            return {}
        by_id: dict[str, dict[str, Any]] = {}
        for entry in raw_items:
            if isinstance(entry, Mapping) and entry.get("doc_id"):
                by_id[str(entry["doc_id"]).strip()] = dict(entry)

        accepted: dict[int, dict[str, Any]] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        per_doc_lat = float(out.latency_ms) / max(1, len(batch_docs))
        for idx, (short_id, pos, _dk, blind_text, ck) in enumerate(batch_docs):
            cand = by_id.get(short_id)
            if cand is None and len(raw_items) == len(batch_docs) and isinstance(raw_items[idx], Mapping):
                cand = dict(raw_items[idx])
            if cand is None:
                continue
            cleaned = {k: v for k, v in cand.items() if k != "doc_id"}
            raw_item_str = json.dumps(cleaned, ensure_ascii=False)
            try:
                parsed = _parse_and_validate(raw_item_str, blind_text, model_cls=core_cls)
            except Exception:
                continue
            if not verify_span_grounding(blind_text, parsed).passed:
                continue
            with cache_lock:
                cache.put(
                    CacheEntry(
                        key=ck,
                        raw_text=raw_item_str,
                        extracted_json_str=raw_item_str,
                        latency_ms=per_doc_lat,
                        created_at=now_iso,
                        returncode=0,
                        error=None,
                        family="gemini",
                        stage="bulk_review_core",
                    )
                )
            accepted[pos] = parsed
        return accepted

    chunks = _pack_char_bounded_chunks(
        uncached,
        max_items=max(1, batch_size),
        max_chars=max(10_000, max_batch_chars),
        len_fn=lambda it: len(it[2]) + 120,
    )
    leftovers: list[tuple[int, str, str, Any]] = []

    def _run_chunk(ch_idx: int, chunk: Sequence[tuple[int, str, str, Any]]) -> list[tuple[int, str, str, Any]]:
        if guard.should_stop():
            return []
        short_docs = [(f"d{idx:02d}", it[0], it[1], it[2], it[3]) for idx, it in enumerate(chunk)]
        prompt = _format_audit_batch_prompt([(did, txt) for did, _pos, _dk, txt, _ck in short_docs])
        out = _invoke_review_adapter(
            prompt=prompt,
            system_prompt=audit_sys_prompt,
            model_id=model_id,
            timeout_s=timeout_s,
            adapter_fn=adapter_fn,
        )
        guard.record("gemini", None, None, out.error)
        if _is_quota_error(out.error) or (out.returncode != 0 and _is_quota_error(out.raw_text)):
            guard.trip(f"gemini quota/rate-limit error: {(out.error or out.raw_text)[:160]}")

        accepted = _store_accepted(short_docs, out) if (out.returncode == 0 and out.error is None) else {}
        for pos, parsed in accepted.items():
            parsed_by_pos[pos] = parsed
        print(
            f"[bulk-review] pass=audit shard={shard_idx:04d} chunk={ch_idx + 1}/{len(chunks)} "
            f"accepted={len(accepted)}/{len(chunk)} rc={out.returncode} lat_s={out.latency_ms / 1000.0:.1f}"
            + (f" err={str(out.error)[:120]}" if out.error else ""),
            file=sys.stderr,
            flush=True,
        )
        if guard.should_stop():
            return []
        return [it for it in chunk if it[0] not in accepted]

    if chunks and not guard.should_stop():
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as pool:
            futs = [pool.submit(_run_chunk, ci, ch) for ci, ch in enumerate(chunks)]
            for fut in as_completed(futs):
                leftovers.extend(fut.result())

    if leftovers and not guard.should_stop():
        def _run_single(item: tuple[int, str, str, Any]) -> None:
            if guard.should_stop():
                return
            pos, dk, blind_text, ck = item
            short_docs = [("d00", pos, dk, blind_text, ck)]
            prompt = _format_audit_batch_prompt([("d00", blind_text)])
            out = _invoke_review_adapter(
                prompt=prompt,
                system_prompt=audit_sys_prompt,
                model_id=model_id,
                timeout_s=timeout_s,
                adapter_fn=adapter_fn,
            )
            guard.record("gemini", None, None, out.error)
            if _is_quota_error(out.error) or (out.returncode != 0 and _is_quota_error(out.raw_text)):
                guard.trip(f"gemini quota/rate-limit error: {(out.error or out.raw_text)[:160]}")
                return
            if out.returncode == 0 and out.error is None:
                accepted = _store_accepted(short_docs, out)
                parsed_by_pos.update(accepted)

        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(leftovers)))) as pool:
            futs = [pool.submit(_run_single, it) for it in leftovers]
            for fut in as_completed(futs):
                fut.result()

    if guard.should_stop():
        return False, []

    out_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for pos, row in enumerate(shard_rows):
        verdict = str(row.get("verdict") or "")
        gold_payload = row.get("gold") if isinstance(row.get("gold"), Mapping) else None
        gold_tuple = extract_triage_tuple(gold_payload)
        neon_payload = parsed_by_pos.get(pos)
        neon_tuple = extract_triage_tuple(neon_payload)
        audit_status, diff_fields = _classify_audit_status(
            verdict=verdict,
            gold_tuple=gold_tuple,
            neon_tuple=neon_tuple,
        )
        status_counts[audit_status] += 1
        out_rows.append(
            {
                "shard_idx": shard_idx,
                "doc_key": row["doc_key"],
                "filename": row.get("filename"),
                "source_pool": row.get("source_pool"),
                "stratum": row.get("stratum"),
                "sealed_verdict": verdict,
                "consensus_families": row.get("consensus_families") or [],
                "deadlock_reason": row.get("deadlock_reason"),
                "gold_tuple": list(gold_tuple) if gold_tuple is not None else None,
                "neon_tuple": list(neon_tuple) if neon_tuple is not None else None,
                "audit_status": audit_status,
                "diff_fields": diff_fields,
                "neon_rationale": neon_payload.get("rationale") if neon_payload else None,
                "neon_verbatim_title": neon_payload.get("verbatim_title") if neon_payload else None,
                "neon_payload": neon_payload,
            }
        )

    _atomic_write_jsonl(rev_jsonl, out_rows)
    meta_obj = {
        "shard_idx": shard_idx,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id,
        "codebook_version": cb_ver,
        "shard_doc_hash": expected_hash,
        "total_docs": len(out_rows),
        "audit_status_counts": dict(status_counts),
    }
    _atomic_write_text(rev_meta, json.dumps(meta_obj, indent=2))
    print(
        f"[bulk-review] shard={shard_idx:04d} SEALED docs={len(out_rows)} statuses={dict(status_counts)}",
        file=sys.stderr,
        flush=True,
    )
    return True, out_rows


def _validate_deadlock_item(
    entry: Mapping[str, Any],
    *,
    doc_text: str,
    core_cls: Any,
) -> tuple[bool, dict[str, Any]]:
    action = str(entry.get("recommended_action") or "").strip()
    if action not in {"resolve", "keep_deadlock"}:
        return False, {"error": f"invalid_action:{action}"}

    ev_quote = entry.get("evidence_quote")
    evidence_grounded = _quote_in_text(ev_quote if isinstance(ev_quote, str) else None, doc_text)
    validated_core: dict[str, Any] | None = None
    core_grounded = False

    if action == "resolve":
        rec_core = entry.get("recommended_core")
        if isinstance(rec_core, Mapping):
            try:
                parsed = _parse_and_validate(
                    json.dumps(dict(rec_core), ensure_ascii=False),
                    doc_text,
                    model_cls=core_cls,
                )
                if verify_span_grounding(doc_text, parsed).passed:
                    validated_core = parsed
                    core_grounded = True
            except Exception:
                core_grounded = False
        validation_passed = bool(evidence_grounded and core_grounded)
    else:
        validation_passed = bool(evidence_grounded)

    cleaned = {
        "recommended_action": action,
        "matches_prior_family": entry.get("matches_prior_family"),
        "confidence": entry.get("confidence") if entry.get("confidence") in {"high", "medium", "low"} else "low",
        "evidence_quote": ev_quote,
        "evidence_grounded": evidence_grounded,
        "rationale": str(entry.get("rationale") or "")[:600],
        "recommended_core": validated_core,
        "recommended_tuple": list(extract_triage_tuple(validated_core) or []) or None,
        "validation_passed": validation_passed,
    }
    return validation_passed, cleaned


def _review_deadlocks(
    *,
    sealed_shards: Sequence[tuple[int, Path, Path]],
    shards_dir: Path,
    resolutions_path: Path,
    text_by_key: Mapping[str, str],
    model_id: str,
    cb_ver: str,
    core_schema: Mapping[str, Any],
    core_cls: Any,
    deadlock_sys_prompt: str,
    batch_size: int,
    max_batch_chars: int,
    max_deadlocks: int | None,
    workers: int,
    timeout_s: float,
    cache: SixTupleCache,
    guard: UsageGuard,
    adapter_fn: Callable[..., Any] | None,
) -> list[dict[str, Any]]:
    existing_by_key: dict[str, dict[str, Any]] = {}
    if resolutions_path.is_file():
        for rec in _read_jsonl_rows(resolutions_path):
            dk = str(rec.get("doc_key") or "")
            if dk:
                existing_by_key[dk] = rec

    all_deadlocks: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for shard_idx, s_jsonl, _s_meta in sealed_shards:
        digest_info = parse_deadlock_digest_md(shards_dir / f"deadlocks_shard_{shard_idx:04d}.md")
        for row in _read_jsonl_rows(s_jsonl):
            if row.get("verdict") != "deadlock_needs_owner":
                continue
            dk = str(row["doc_key"])
            if dk in seen_keys:
                continue
            seen_keys.add(dk)
            d_meta = digest_info.get(dk, {})
            all_deadlocks.append(
                {
                    "shard_idx": shard_idx,
                    "doc_key": dk,
                    "filename": row.get("filename"),
                    "source_pool": row.get("source_pool"),
                    "stratum": row.get("stratum"),
                    "deadlock_reason": row.get("deadlock_reason") or d_meta.get("deadlock_reason"),
                    "family_votes": d_meta.get("family_votes") or {},
                    "grounding_issues": d_meta.get("grounding_issues") or {},
                    "checkeval_summary": d_meta.get("checkeval_summary") or "",
                    "text": text_by_key.get(dk, ""),
                }
            )

    if max_deadlocks is not None:
        all_deadlocks = all_deadlocks[: max(0, int(max_deadlocks))]

    schema_hash = canonical_json_sha256(core_schema)
    prompt_hash = sha256_text(deadlock_sys_prompt)
    cache_lock = threading.Lock()
    uncached: list[tuple[dict[str, Any], Any]] = []

    for ctx in all_deadlocks:
        dk = ctx["doc_key"]
        prev = existing_by_key.get(dk)
        if prev and prev.get("model_id") == model_id and (
            prev.get("validation_passed") is True or prev.get("final_attempt") is True
        ):
            continue
        doc_text = ctx["text"]
        if not doc_text:
            continue
        context_hash_src = json.dumps(
            {
                "text": doc_text,
                "reason": ctx["deadlock_reason"],
                "votes": ctx["family_votes"],
                "ce": ctx["checkeval_summary"],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        ck = make_cache_key(
            input_sha256=sha256_text(context_hash_src),
            codebook_version=cb_ver,
            model_id=model_id,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            slice_spec="blind_text_only:bulk_review_deadlock",
            rollout_id=0,
        )
        with cache_lock:
            c_entry = cache.get(ck)
        if c_entry is not None and c_entry.returncode == 0 and c_entry.error is None:
            try:
                loaded = json.loads(c_entry.raw_text)
                passed, cleaned = _validate_deadlock_item(loaded, doc_text=doc_text, core_cls=core_cls)
                if passed:
                    existing_by_key[dk] = _build_deadlock_record(ctx, cleaned, model_id=model_id)
                    continue
            except Exception:
                pass
        uncached.append((ctx, ck))

    chunks = _pack_char_bounded_chunks(
        uncached,
        max_items=max(1, batch_size),
        max_chars=max(10_000, max_batch_chars),
        len_fn=lambda pair: len(pair[0]["text"]) + 450,
    )

    def _accept_items(
        batch_pairs: Sequence[tuple[str, dict[str, Any], Any]],
        out: AdapterOutput,
    ) -> dict[str, dict[str, Any]]:
        raw_items = _extract_batch_items(out)
        if not raw_items:
            return {}
        by_id: dict[str, dict[str, Any]] = {}
        for entry in raw_items:
            if isinstance(entry, Mapping) and entry.get("doc_id"):
                by_id[str(entry["doc_id"]).strip()] = dict(entry)

        resolved_map: dict[str, dict[str, Any]] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        per_lat = float(out.latency_ms) / max(1, len(batch_pairs))
        for idx, (short_id, ctx, ck) in enumerate(batch_pairs):
            cand = by_id.get(short_id)
            if cand is None and len(raw_items) == len(batch_pairs) and isinstance(raw_items[idx], Mapping):
                cand = dict(raw_items[idx])
            if cand is None:
                continue
            cleaned_in = {k: v for k, v in cand.items() if k != "doc_id"}
            passed, validated = _validate_deadlock_item(cleaned_in, doc_text=ctx["text"], core_cls=core_cls)
            dk = ctx["doc_key"]
            if passed:
                with cache_lock:
                    cache.put(
                        CacheEntry(
                            key=ck,
                            raw_text=json.dumps(cleaned_in, ensure_ascii=False),
                            extracted_json_str=json.dumps(validated, ensure_ascii=False),
                            latency_ms=per_lat,
                            created_at=now_iso,
                            returncode=0,
                            error=None,
                            family="gemini",
                            stage="bulk_review_deadlock",
                        )
                    )
                resolved_map[dk] = _build_deadlock_record(ctx, validated, model_id=model_id)
            elif len(batch_pairs) == 1 and "error" not in validated:
                # Preserve failed grounding transparently only on final 1-doc attempt.
                resolved_map[dk] = _build_deadlock_record(
                    ctx, validated, model_id=model_id, final_attempt=True
                )
        return resolved_map

    leftovers: list[tuple[dict[str, Any], Any]] = []

    def _run_dl_chunk(ch_idx: int, chunk: Sequence[tuple[dict[str, Any], Any]]) -> list[tuple[dict[str, Any], Any]]:
        if guard.should_stop():
            return []
        batch_pairs = [(f"d{idx:02d}", ctx, ck) for idx, (ctx, ck) in enumerate(chunk)]
        prompt = _format_deadlock_batch_prompt([(did, ctx) for did, ctx, _ck in batch_pairs])
        out = _invoke_review_adapter(
            prompt=prompt,
            system_prompt=deadlock_sys_prompt,
            model_id=model_id,
            timeout_s=timeout_s,
            adapter_fn=adapter_fn,
        )
        guard.record("gemini", None, None, out.error)
        if _is_quota_error(out.error) or (out.returncode != 0 and _is_quota_error(out.raw_text)):
            guard.trip(f"gemini quota/rate-limit error: {(out.error or out.raw_text)[:160]}")

        accepted = _accept_items(batch_pairs, out) if (out.returncode == 0 and out.error is None) else {}
        existing_by_key.update(accepted)
        print(
            f"[bulk-review] pass=deadlock chunk={ch_idx + 1}/{len(chunks)} "
            f"accepted={len(accepted)}/{len(chunk)} rc={out.returncode} lat_s={out.latency_ms / 1000.0:.1f}"
            + (f" err={str(out.error)[:120]}" if out.error else ""),
            file=sys.stderr,
            flush=True,
        )
        if guard.should_stop():
            return []
        return [(ctx, ck) for ctx, ck in chunk if ctx["doc_key"] not in accepted]

    if chunks and not guard.should_stop():
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as pool:
            futs = [pool.submit(_run_dl_chunk, ci, ch) for ci, ch in enumerate(chunks)]
            for fut in as_completed(futs):
                leftovers.extend(fut.result())

    if leftovers and not guard.should_stop():
        def _run_dl_single(pair: tuple[dict[str, Any], Any]) -> None:
            if guard.should_stop():
                return
            ctx, ck = pair
            batch_pairs = [("d00", ctx, ck)]
            prompt = _format_deadlock_batch_prompt([("d00", ctx)])
            out = _invoke_review_adapter(
                prompt=prompt,
                system_prompt=deadlock_sys_prompt,
                model_id=model_id,
                timeout_s=timeout_s,
                adapter_fn=adapter_fn,
            )
            guard.record("gemini", None, None, out.error)
            if _is_quota_error(out.error) or (out.returncode != 0 and _is_quota_error(out.raw_text)):
                guard.trip(f"gemini quota/rate-limit error: {(out.error or out.raw_text)[:160]}")
                return
            if out.returncode == 0 and out.error is None:
                existing_by_key.update(_accept_items(batch_pairs, out))

        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(leftovers)))) as pool:
            futs = [pool.submit(_run_dl_single, p) for p in leftovers]
            for fut in as_completed(futs):
                fut.result()

    ordered_records = [
        existing_by_key[ctx["doc_key"]]
        for ctx in all_deadlocks
        if ctx["doc_key"] in existing_by_key
    ]
    if ordered_records or resolutions_path.is_file():
        # Include any records reviewed for shards beyond current slice if present.
        extra_keys = [k for k in existing_by_key if k not in {c["doc_key"] for c in all_deadlocks}]
        for ek in sorted(extra_keys):
            ordered_records.append(existing_by_key[ek])
        _atomic_write_jsonl(resolutions_path, ordered_records)
    return [existing_by_key[ctx["doc_key"]] for ctx in all_deadlocks if ctx["doc_key"] in existing_by_key]


def _build_deadlock_record(
    ctx: Mapping[str, Any],
    cleaned: Mapping[str, Any],
    *,
    model_id: str,
    final_attempt: bool = False,
) -> dict[str, Any]:
    return {
        "shard_idx": ctx["shard_idx"],
        "doc_key": ctx["doc_key"],
        "filename": ctx.get("filename"),
        "source_pool": ctx.get("source_pool"),
        "stratum": ctx.get("stratum"),
        "deadlock_reason": ctx.get("deadlock_reason"),
        "prior_family_votes": ctx.get("family_votes") or {},
        "checkeval_summary": ctx.get("checkeval_summary") or "",
        "model_id": model_id,
        "final_attempt": bool(final_attempt),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **cleaned,
    }


def _write_reports(
    *,
    out_dir: Path,
    model_id: str,
    cb_ver: str,
    sealed_shards: Sequence[tuple[int, Path, Path]],
    review_shards_dir: Path,
    deadlock_records: Sequence[Mapping[str, Any]],
    total_deadlocks_seen: int,
    stopped_reason: str | None,
) -> dict[str, Any]:
    audit_rows: list[dict[str, Any]] = []
    reviewed_shards: list[int] = []
    for rmeta in sorted(review_shards_dir.glob("review_shard_*.meta.json")):
        m = re.match(r"^review_shard_(\d+)\.meta\.json$", rmeta.name)
        if not m:
            continue
        s_idx = int(m.group(1))
        rjsonl = review_shards_dir / f"review_shard_{s_idx:04d}.jsonl"
        if rjsonl.is_file():
            reviewed_shards.append(s_idx)
            audit_rows.extend(_read_jsonl_rows(rjsonl))

    audit_counts: Counter[str] = Counter()
    field_diffs: Counter[str] = Counter()
    genre_confusions: Counter[str] = Counter()
    top_ce_disagree: list[dict[str, Any]] = []
    top_gold_disagree: list[dict[str, Any]] = []

    for row in audit_rows:
        st = str(row.get("audit_status") or "")
        audit_counts[st] += 1
        for df in row.get("diff_fields") or []:
            field_diffs[str(df)] += 1
        gt = row.get("gold_tuple")
        nt = row.get("neon_tuple")
        if st in {"disagreement_gold", "disagreement_checkeval"} and gt and nt:
            pair = f"{gt[3] or gt[0]} -> {nt[3] or nt[0]}"
            genre_confusions[pair] += 1
            item_brief = {
                "shard_idx": row.get("shard_idx"),
                "doc_key": row.get("doc_key"),
                "filename": row.get("filename"),
                "gold_tuple": gt,
                "neon_tuple": nt,
                "diff_fields": row.get("diff_fields"),
                "rationale": str(row.get("neon_rationale") or "")[:180],
            }
            if st == "disagreement_checkeval" and len(top_ce_disagree) < 20:
                top_ce_disagree.append(item_brief)
            elif st == "disagreement_gold" and len(top_gold_disagree) < 20:
                top_gold_disagree.append(item_brief)

    dl_actions: Counter[str] = Counter()
    dl_conf: Counter[str] = Counter()
    dl_fam: Counter[str] = Counter()
    dl_valid = 0
    top_dl_resolved: list[dict[str, Any]] = []

    for rec in deadlock_records:
        act = str(rec.get("recommended_action") or "")
        dl_actions[act] += 1
        dl_conf[str(rec.get("confidence") or "low")] += 1
        if rec.get("matches_prior_family") is not None:
            dl_fam[str(rec["matches_prior_family"])] += 1
        if rec.get("validation_passed") is True:
            dl_valid += 1
            if act == "resolve" and len(top_dl_resolved) < 20:
                top_dl_resolved.append(
                    {
                        "shard_idx": rec.get("shard_idx"),
                        "doc_key": rec.get("doc_key"),
                        "filename": rec.get("filename"),
                        "reason": rec.get("deadlock_reason"),
                        "confidence": rec.get("confidence"),
                        "matches_prior_family": rec.get("matches_prior_family"),
                        "recommended_tuple": rec.get("recommended_tuple"),
                        "evidence_quote": str(rec.get("evidence_quote") or "")[:120],
                    }
                )

    total_aud = len(audit_rows)
    confirmed = audit_counts["confirmed_3of3"] + audit_counts["confirmed_checkeval"]
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id,
        "codebook_version": cb_ver,
        "stopped_reason": stopped_reason,
        "sealed_corpus_shards": len(sealed_shards),
        "reviewed_2fam_shards": sorted(reviewed_shards),
        "total_2fam_docs_reviewed": total_aud,
        "confirmed_rate": round(confirmed / max(1, total_aud), 4) if total_aud else 0.0,
        "audit_status_counts": dict(audit_counts),
        "per_field_diff_counts": dict(field_diffs),
        "top_genre_confusions": dict(genre_confusions.most_common(15)),
        "total_deadlocks_seen": total_deadlocks_seen,
        "total_deadlocks_reviewed": len(deadlock_records),
        "deadlock_actions": dict(dl_actions),
        "deadlock_confidence": dict(dl_conf),
        "deadlock_matches_prior_family": dict(dl_fam),
        "deadlock_validation_passed": dl_valid,
        "sample_disagreement_checkeval": top_ce_disagree,
        "sample_disagreement_gold": top_gold_disagree,
        "sample_resolved_deadlocks": top_dl_resolved,
    }
    _atomic_write_text(out_dir / "bulk_review_summary.json", json.dumps(summary, indent=2, ensure_ascii=False))

    md_lines = [
        "# DocMeta V7.3 Stripped Gemini Neon Medium Bulk Review Report",
        "",
        f"- **Updated:** `{summary['updated_at']}`",
        f"- **Reviewer Model:** `{model_id}` | **Codebook:** `{cb_ver}`",
        f"- **Stopped Reason:** `{stopped_reason}`",
        f"- **Sealed Corpus Shards Seen:** `{len(sealed_shards)}` | **2-Family Shards Reviewed:** `{len(reviewed_shards)}` (`{total_aud}` docs)",
        "",
        "## Pass A — 2-Family Blind Audit Summary",
        "",
        f"- **3-of-3 / CheckEval Confirmed:** `{confirmed}/{total_aud}` (`{summary['confirmed_rate']:.1%}`)",
        f"- **Audit Status Counts:** `{dict(audit_counts)}`",
        f"- **Per-Field Disagreements:** `{dict(field_diffs)}`",
        f"- **Top Genre / Status Shifts (`sealed -> neon`):** `{dict(genre_confusions.most_common(10))}`",
        "",
        "### Sample CheckEval Disagreements (up to 10)",
        "",
        "| Shard | Doc Key | Sealed Gold | Neon Medium | Diff Fields |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for item in top_ce_disagree[:10]:
        md_lines.append(
            f"| {item['shard_idx']} | `{item['doc_key'][:12]}` | `{item['gold_tuple']}` | `{item['neon_tuple']}` | `{item['diff_fields']}` |"
        )

    md_lines.extend(
        [
            "",
            "### Sample Unanimous-Gold Disagreements (up to 10)",
            "",
            "| Shard | Doc Key | Sealed Gold | Neon Medium | Diff Fields |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for item in top_gold_disagree[:10]:
        md_lines.append(
            f"| {item['shard_idx']} | `{item['doc_key'][:12]}` | `{item['gold_tuple']}` | `{item['neon_tuple']}` | `{item['diff_fields']}` |"
        )

    md_lines.extend(
        [
            "",
            "## Pass B — Deadlock Adjudication Summary",
            "",
            f"- **Deadlocks Seen / Reviewed:** `{len(deadlock_records)}/{total_deadlocks_seen}` (`validation_passed={dl_valid}`)",
            f"- **Actions:** `{dict(dl_actions)}` | **Confidence:** `{dict(dl_conf)}` | **Matched Prior Family:** `{dict(dl_fam)}`",
            "",
            "### Sample Grounded Deadlock Resolutions (up to 10)",
            "",
            "| Shard | Doc Key | Conf | Matches | Recommended Tuple | Quote |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for item in top_dl_resolved[:10]:
        q = str(item.get("evidence_quote") or "").replace("|", "/").replace("\n", " ")[:60]
        md_lines.append(
            f"| {item['shard_idx']} | `{item['doc_key'][:12]}` | `{item['confidence']}` | `{item['matches_prior_family']}` | `{item['recommended_tuple']}` | `{q}` |"
        )

    _atomic_write_text(out_dir / "bulk_review_report.md", "\n".join(md_lines) + "\n")
    return summary


def run_bulk_review(
    *,
    corpus_dir: Path | None = None,
    out_dir: Path | None = None,
    model_id: str = DEFAULT_BULK_MODEL,
    min_2fam_shard: int = 18,
    batch_size: int = 12,
    deadlock_batch_size: int = 8,
    max_batch_chars: int = 110_000,
    workers: int = 4,
    timeout_s: float = 240.0,
    max_2fam_shards: int | None = None,
    max_deadlocks: int | None = None,
    follow_until_shards: int | None = None,
    poll_seconds: float = 60.0,
    adapter_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run stripped `gemini-4-neon-medium` Pass A (2-family audit) + Pass B (deadlock adjudication)."""
    resolved_corpus = (Path(corpus_dir) if corpus_dir is not None else default_corpus_dir()).resolve()
    resolved_out = (Path(out_dir) if out_dir is not None else (resolved_corpus / "bulk_review")).resolve()
    candidates_path = resolved_corpus / "candidates_v7_3.jsonl"
    shards_dir = resolved_corpus / "shards"
    if not candidates_path.is_file():
        raise FileNotFoundError(f"Missing candidate pool: {candidates_path}")

    review_shards_dir = resolved_out / "shards"
    review_shards_dir.mkdir(parents=True, exist_ok=True)
    resolutions_path = resolved_out / "deadlock_resolutions.jsonl"
    review_cache_path = resolved_out / "review_cache.sqlite"

    cb_ver, core_schema, _spec_schemas, core_cls, _spec_clses = _resolve_v7_runtime_specs(None)
    audit_sys_prompt = build_audit_system_prompt(core_schema)
    deadlock_sys_prompt = build_deadlock_system_prompt(core_schema)
    text_by_key = _load_candidates_text_map(candidates_path)

    guard = UsageGuard(max_usage_pct=None)
    latest_summary: dict[str, Any] = {}

    with SixTupleCache(review_cache_path) as cache:
        while True:
            sealed = _discover_sealed_shards(shards_dir)
            eligible_2fam = [t for t in sealed if t[0] >= min_2fam_shard]
            if max_2fam_shards is not None:
                eligible_2fam = eligible_2fam[: max(0, int(max_2fam_shards))]

            for s_idx, s_jsonl, _s_meta in eligible_2fam:
                if guard.should_stop():
                    break
                completed, _rows = _review_one_2fam_shard(
                    shard_idx=s_idx,
                    shard_jsonl=s_jsonl,
                    review_shards_dir=review_shards_dir,
                    text_by_key=text_by_key,
                    model_id=model_id,
                    cb_ver=cb_ver,
                    core_schema=core_schema,
                    core_cls=core_cls,
                    audit_sys_prompt=audit_sys_prompt,
                    batch_size=batch_size,
                    max_batch_chars=max_batch_chars,
                    workers=workers,
                    timeout_s=timeout_s,
                    cache=cache,
                    guard=guard,
                    adapter_fn=adapter_fn,
                )
                if not completed:
                    break

            deadlock_records: list[dict[str, Any]] = []
            if not guard.should_stop():
                deadlock_records = _review_deadlocks(
                    sealed_shards=sealed,
                    shards_dir=shards_dir,
                    resolutions_path=resolutions_path,
                    text_by_key=text_by_key,
                    model_id=model_id,
                    cb_ver=cb_ver,
                    core_schema=core_schema,
                    core_cls=core_cls,
                    deadlock_sys_prompt=deadlock_sys_prompt,
                    batch_size=deadlock_batch_size,
                    max_batch_chars=min(max_batch_chars, 100_000),
                    max_deadlocks=max_deadlocks,
                    workers=workers,
                    timeout_s=timeout_s,
                    cache=cache,
                    guard=guard,
                    adapter_fn=adapter_fn,
                )
            elif resolutions_path.is_file():
                deadlock_records = _read_jsonl_rows(resolutions_path)

            total_dl_seen = sum(
                1
                for _i, s_j, _m in sealed
                for r in _read_jsonl_rows(s_j)
                if r.get("verdict") == "deadlock_needs_owner"
            )
            latest_summary = _write_reports(
                out_dir=resolved_out,
                model_id=model_id,
                cb_ver=cb_ver,
                sealed_shards=sealed,
                review_shards_dir=review_shards_dir,
                deadlock_records=deadlock_records,
                total_deadlocks_seen=total_dl_seen,
                stopped_reason=guard.triggered_reason,
            )

            if guard.should_stop():
                print(
                    f"[bulk-review] STOPPED: {guard.triggered_reason}",
                    file=sys.stderr,
                    flush=True,
                )
                break
            if follow_until_shards is None:
                break
            if len(sealed) >= follow_until_shards:
                all_2fam_done = all(
                    (review_shards_dir / f"review_shard_{idx:04d}.meta.json").is_file()
                    for idx, _j, _m in sealed
                    if idx >= min_2fam_shard
                )
                dl_target = total_dl_seen if max_deadlocks is None else min(total_dl_seen, int(max_deadlocks))
                if all_2fam_done and len(deadlock_records) >= dl_target:
                    break
            time.sleep(max(1.0, float(poll_seconds)))

    return latest_summary


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DocMeta V7.3 stripped neon-medium bulk reviewer")
    sub = parser.add_subparsers(dest="command", required=True)
    rn = sub.add_parser("run", help="Run Pass A (2-family audit) and Pass B (deadlock adjudication)")
    rn.add_argument("--corpus-dir", type=Path, default=None)
    rn.add_argument("--out-dir", type=Path, default=None)
    rn.add_argument("--model", type=str, default=DEFAULT_BULK_MODEL)
    rn.add_argument("--min-2fam-shard", type=int, default=18)
    rn.add_argument("--batch-size", type=int, default=12)
    rn.add_argument("--deadlock-batch-size", type=int, default=8)
    rn.add_argument("--max-batch-chars", type=int, default=110_000)
    rn.add_argument("--workers", type=int, default=4)
    rn.add_argument("--timeout", type=float, default=240.0)
    rn.add_argument("--max-2fam-shards", type=int, default=None)
    rn.add_argument("--max-deadlocks", type=int, default=None)
    rn.add_argument("--follow-until-shards", type=int, default=None)
    rn.add_argument("--poll-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "run":
        summary = run_bulk_review(
            corpus_dir=args.corpus_dir,
            out_dir=args.out_dir,
            model_id=args.model,
            min_2fam_shard=args.min_2fam_shard,
            batch_size=args.batch_size,
            deadlock_batch_size=args.deadlock_batch_size,
            max_batch_chars=args.max_batch_chars,
            workers=args.workers,
            timeout_s=args.timeout,
            max_2fam_shards=args.max_2fam_shards,
            max_deadlocks=args.max_deadlocks,
            follow_until_shards=args.follow_until_shards,
            poll_seconds=args.poll_seconds,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
