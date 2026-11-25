#!/usr/bin/env python3
"""DocMeta V7.3 quick-polish tooling: rare-genre budget top-up + 2-fam/deadlock/Cleanlab reconciliation."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

import duckdb

from congress_docmeta.v7.factory.cache import SixTupleCache, canonical_json_sha256, default_cache_path, make_cache_key, sha256_text
from congress_docmeta.v7.factory.corpus_builder import (
    _format_audit_batch_prompt,
    _format_specialist_batch_prompt,
    _norm_candidate_record,
    _pack_char_bounded_chunks,
    _run_batched_stage_for_family,
    _single_doc_cache_key,
    _unpack_and_store_batch_items,
    build_audit_system_prompt,
    build_batch_schema,
    default_corpus_dir,
    default_parquet_paths,
    split_specialist_prefix,
)
from congress_docmeta.v7.factory.grounding import (
    adjudicate_three_family,
    extract_triage_tuple,
    merge_consensus_payload,
    reconcile_and_validate_v7_payload,
    repair_span_refs_in_payload,
    run_checkeval_arbiter,
    verify_span_grounding,
)
from congress_docmeta.v7.factory.pilot import (
    GENRE_TO_SPECIALIST_FAMILY,
    _parse_and_validate,
    _resolve_v7_runtime_specs,
    build_live_sota_checkeval_fn,
    render_core_triage_prompt,
    render_specialist_prompt as render_pilot_specialist_prompt,
)
from congress_docmeta.v7.factory.runners import (
    AdapterOutput,
    FamilyRunResult,
    RunnerConfig,
    UsageGuard,
    _resolve_adapter,
    invoke_agy_stripped_cli,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _atomic_write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    tmp.replace(path)


def _parse_committees(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                loaded = json.loads(s)
                if isinstance(loaded, list):
                    return [str(x).strip() for x in loaded if str(x).strip()]
            except json.JSONDecodeError:
                pass
        return [p.strip() for p in s.split(",") if p.strip()]
    return []


def cmd_mine_budget(
    *,
    corpus_dir: Path,
    out_dir: Path,
    llm_queue_path: Path,
    limit: int = 55,
    seed: int = 20261123,
    expand: bool = False,
    exclude_candidates: Sequence[Path] = (),
) -> dict[str, Any]:
    """Mine unseen high-precision `budget_or_cost_estimate` documents from the 323K archive parquet."""
    base_cands = corpus_dir / "candidates_v7_3.jsonl"
    if not base_cands.is_file():
        raise FileNotFoundError(f"Missing base candidates: {base_cands}")

    seen_keys: set[str] = set()
    seen_shas: set[str] = set()
    for cp in [base_cands, *exclude_candidates]:
        for row in _read_jsonl(cp):
            if row.get("doc_key"):
                seen_keys.add(str(row["doc_key"]))
            if row.get("text_sha256"):
                seen_shas.add(str(row["text_sha256"]))

    q_path = str(llm_queue_path.resolve())
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB';")
    con.execute("SET threads=2;")

    sql = f"""
    SELECT
        doc_key,
        left(coalesce(nullif(trim(p12_clean_text), ''), nullif(trim(p12_raw_text), '')), 9000) AS body_text,
        filename,
        rel_event_date,
        rel_chamber,
        rel_committees,
        locked_primary_kind,
        effective_format
    FROM read_parquet('{q_path}')
    WHERE length(trim(coalesce(p12_clean_text, p12_raw_text, ''))) >= 150
      AND (
          locked_primary_kind IN ('revenue_or_cost_estimate', 'budget_views_and_estimates')
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%congressional budget office%cost estimate%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%cbo cost estimate%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%estimated revenue effects%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%estimated budget effects%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%estimated budgetary effects%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%millions of dollars%outlays%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%budget authority%outlays%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%congressional budget justification%'
          OR lower(left(coalesce(p12_clean_text, ''), 600)) LIKE '%budget in brief%'
          OR regexp_matches(coalesce(p12_clean_text, ''), '(?i)views and estimates of the committee on ')
          OR ({"lower(coalesce(filename, '')) LIKE '%cbo%' OR lower(coalesce(filename, '')) LIKE '%budget_views%' OR regexp_matches(coalesce(filename, ''), '(?i)(?:cbo.*(?:score|cost|est)|jcx[-_]?\\d+)')" if expand else "regexp_matches(coalesce(filename, ''), '(?i)(?:cbo.*(?:score|cost|est)|jcx[-_]?\\d+)')"} )
      )
      AND coalesce(locked_primary_kind, '') NOT IN (
          'committee_amendment', 'hearing_memo_or_charter', 'hearing_transcript',
          'witness_statement', 'member_opening_statement', 'hearing_notice', 'truth_in_testimony_disclosure'
      )
      AND lower(left(coalesce(p12_clean_text, ''), 200)) NOT LIKE '%amendment%'
      AND lower(left(coalesce(p12_clean_text, ''), 200)) NOT LIKE '%testimony%'
      AND lower(left(coalesce(p12_clean_text, ''), 200)) NOT LIKE '%agenda%'
      AND lower(left(coalesce(p12_clean_text, ''), 200)) NOT LIKE '%opening statement%'
      AND lower(left(coalesce(p12_clean_text, ''), 200)) NOT LIKE '%statement for the record%'
      AND lower(left(coalesce(p12_clean_text, ''), 120)) NOT LIKE '%markup%'
      AND lower(left(coalesce(p12_clean_text, ''), 120)) NOT LIKE 'description of %'
      AND lower(coalesce(filename, '')) NOT LIKE '%bio-%'
      AND lower(coalesce(filename, '')) NOT LIKE '%wstate%'
      AND lower(coalesce(filename, '')) NOT LIKE '%mstate%'
      AND lower(coalesce(filename, '')) NOT LIKE '%vote%'
      AND lower(coalesce(filename, '')) NOT LIKE '%amdt%'
      AND lower(coalesce(filename, '')) NOT LIKE '%amnd%'
      AND lower(coalesce(filename, '')) NOT LIKE '%memo%'
      AND lower(coalesce(filename, '')) NOT LIKE 'crpt%'
      AND coalesce(effective_format, 'pdf') != 'html'
    ORDER BY hash(doc_key || '|{seed}|budget_topup')
    LIMIT 400
    """
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    picked: list[dict[str, Any]] = []
    start_idx = 10500 + sum(len(_read_jsonl(Path(ep))) for ep in exclude_candidates)
    for tup in cur.fetchall():
        row = dict(zip(cols, tup))
        rec = _norm_candidate_record(
            doc_key=str(row["doc_key"]),
            text=str(row.get("body_text") or ""),
            filename=str(row.get("filename") or ""),
            source_pool="archive_v6_2_topup",
            stratum="budget_topup:fiscal",
            doc_date=None,
            event_date=row.get("rel_event_date"),
            chamber=row.get("rel_chamber"),
            committees=_parse_committees(row.get("rel_committees")),
            prior_kind=row.get("locked_primary_kind"),
            effective_format=row.get("effective_format"),
            split_hint=None,
        )
        dk = rec["doc_key"]
        sha = rec["text_sha256"]
        if dk in seen_keys or sha in seen_shas or not rec["text"].strip():
            continue
        seen_keys.add(dk)
        seen_shas.add(sha)
        picked.append({"pool_index": start_idx + len(picked), **rec})
        if len(picked) >= limit:
            break
    con.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "candidates_budget_topup.jsonl"
    _atomic_write_jsonl(out_path, picked)
    return {
        "out_path": str(out_path),
        "picked_count": len(picked),
        "sample_filenames": [p["filename"] for p in picked[:10]],
    }


def _compute_cleanlab_flagged_over_corpus(
    row_by_key: Mapping[str, Mapping[str, Any]],
    cand_by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    import numpy as np
    from cleanlab.filter import find_label_issues
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    items: list[tuple[str, str, str]] = []
    for dk in sorted(row_by_key):
        r = row_by_key[dk]
        if r.get("verdict") not in {"auto_accept_gold", "checkeval_resolved"}:
            continue
        g = r.get("gold") or {}
        if g.get("status") != "usable" or not g.get("primary_genre"):
            continue
        txt = str((cand_by_key.get(dk) or {}).get("text") or "")
        if txt.strip():
            items.append((dk, txt, str(g["primary_genre"])))

    uniq = sorted({lbl for _, _, lbl in items})
    l2i = {l: i for i, l in enumerate(uniq)}
    y = np.array([l2i[lbl] for _, _, lbl in items], dtype=int)
    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    X = vec.fit_transform([t for _, t, _ in items])
    clf = LogisticRegression(max_iter=1000, C=2.0)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    probs = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")
    issue_idx = find_label_issues(labels=y, pred_probs=probs, return_indices_ranked_by="self_confidence", n_jobs=1)
    out: list[dict[str, Any]] = []
    for i in issue_idx:
        idx = int(i)
        dk, _t, given = items[idx]
        pred_i = int(np.argmax(probs[idx]))
        out.append(
            {
                "doc_key": dk,
                "given_genre": given,
                "pred_genre": uniq[pred_i],
                "p_given": round(float(probs[idx, y[idx]]), 4),
                "p_pred": round(float(probs[idx, pred_i]), 4),
            }
        )
    return out


def _lookup_cached_payload(
    *,
    cache: SixTupleCache,
    family: str,
    model_ids: Sequence[str],
    blind_text: str,
    doc_key: str,
    cb_ver: str,
    core_schema: Mapping[str, Any],
    core_cls: Any,
) -> dict[str, Any] | None:
    single_prompt = render_core_triage_prompt(blind_text, cb_ver, doc_id=doc_key)
    for mid in model_ids:
        ck = _single_doc_cache_key(
            family=family,
            model_id=mid,
            blind_text=blind_text,
            single_prompt=single_prompt,
            single_schema=core_schema,
            cb_ver=cb_ver,
            slice_spec="blind_text_only:core_triage",
        )
        entry = cache.get(ck)
        if entry is not None and entry.returncode == 0 and entry.error is None:
            try:
                parsed = _parse_and_validate(entry.raw_text, blind_text, model_cls=core_cls)
                if verify_span_grounding(blind_text, parsed).passed:
                    return parsed
            except Exception:
                pass
    return None


def _run_gemini_core_triage_map(
    *,
    doc_keys: Sequence[str],
    cand_by_key: Mapping[str, Mapping[str, Any]],
    cache: SixTupleCache,
    cb_ver: str,
    core_schema: Mapping[str, Any],
    core_cls: Any,
    runner_cfg: RunnerConfig,
    usage_guard: UsageGuard,
    workers: int = 4,
) -> dict[str, dict[str, Any]]:
    """Return grounded `gemini-4-neon-low` core payloads for `doc_keys`, querying `agy` only on cache misses."""
    out_map: dict[str, dict[str, Any]] = {}
    uncached: list[tuple[str, str, Any]] = []
    model_id = runner_cfg.model_id_for("gemini")

    for dk in doc_keys:
        txt = str((cand_by_key.get(dk) or {}).get("text") or "")
        if not txt:
            continue
        sprompt = render_core_triage_prompt(txt, cb_ver, doc_id=dk)
        ck = _single_doc_cache_key(
            family="gemini",
            model_id=model_id,
            blind_text=txt,
            single_prompt=sprompt,
            single_schema=core_schema,
            cb_ver=cb_ver,
            slice_spec="blind_text_only:core_triage",
        )
        entry = cache.get(ck)
        if entry is not None and entry.returncode == 0 and entry.error is None:
            try:
                parsed = _parse_and_validate(entry.raw_text, txt, model_cls=core_cls)
                if verify_span_grounding(txt, parsed).passed:
                    out_map[dk] = parsed
                    continue
            except Exception:
                pass
        uncached.append((dk, txt, ck))

    if not uncached or usage_guard.should_stop():
        return out_map

    sys_prompt = build_audit_system_prompt(core_schema)
    chunks = _pack_char_bounded_chunks(uncached, max_items=12, max_chars=110_000, len_fn=lambda t: len(t[1]) + 160)

    def _run_ch(ch: Sequence[tuple[str, str, Any]]) -> None:
        if usage_guard.should_stop():
            return
        batch_docs = [(f"d{idx:02d}", dk, txt, ck, None) for idx, (dk, txt, ck) in enumerate(ch)]
        prompt = _format_audit_batch_prompt([(did, txt) for did, _dk, txt, _ck, _m in batch_docs])
        res = invoke_agy_stripped_cli(
            prompt,
            system_prompt=sys_prompt,
            model_id=model_id,
            timeout_s=runner_cfg.timeout_s,
            binary=runner_cfg.agy_bin,
        )
        usage_guard.record("gemini", res.usage_pct, res.rate_limit_info, res.error, returncode=res.returncode)
        if res.returncode == 0 and res.error is None:
            accepted = _unpack_and_store_batch_items(
                raw_output=res,
                batch_docs=batch_docs,
                provider="agy_cli",
                family="gemini",
                stage="core_triage",
                model_cls=core_cls,
                cache=cache,
            )
            for idx, parsed in accepted.items():
                out_map[batch_docs[idx][1]] = parsed

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as pool:
        for fut in as_completed([pool.submit(_run_ch, ch) for ch in chunks]):
            fut.result()

    return out_map


def _validate_and_ground_core(raw_core: Mapping[str, Any], text: str, core_cls: Any) -> dict[str, Any] | None:
    try:
        repaired = repair_span_refs_in_payload(text, dict(raw_core))
        raw_s = json.dumps(repaired, ensure_ascii=False)
        parsed = _parse_and_validate(raw_s, text, model_cls=core_cls)
        rec_core, _rec_spec, _repairs, errs = reconcile_and_validate_v7_payload(text, parsed)
        if not errs:
            return rec_core
    except Exception:
        return None
    return None


def cmd_build_overrides(
    *,
    corpus_dir: Path,
    bulk_review_dir: Path,
    out_dir: Path,
    cache_path: Path,
    workers: int = 6,
    max_usage_pct: float = 50.0,
    cleanlab_json: Path | None = None,
) -> dict[str, Any]:
    """Reconcile middle 2-fam shards, 87 deadlocks, and Cleanlab flags + run Stage 2 specialist extraction."""
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = corpus_dir / "candidates_v7_3.jsonl"
    shards_dir = corpus_dir / "shards"

    cand_by_key = {str(r["doc_key"]): r for r in _read_jsonl(candidates_path) if r.get("doc_key")}
    row_by_key: dict[str, dict[str, Any]] = {}
    shard_idx_by_key: dict[str, int] = {}
    for sf in sorted(shards_dir.glob("shard_*.jsonl")):
        s_idx = int(sf.stem.split("_")[1])
        for row in _read_jsonl(sf):
            dk = str(row["doc_key"])
            row_by_key[dk] = row
            shard_idx_by_key[dk] = s_idx

    cb_ver, core_schema, specialist_schemas, core_cls, spec_clses = _resolve_v7_runtime_specs(None)

    empty_cwd = Path(tempfile.gettempdir()) / "docmeta_v7_empty_cwd"
    empty_cwd.mkdir(parents=True, exist_ok=True)

    usage_guard = UsageGuard(
        max_usage_pct=max_usage_pct,
        require_telemetry=True,
        telemetry_families=("claude", "codex"),
    )
    runner_cfg = RunnerConfig(
        claude_model="claude-opus-5-5",
        claude_effort="low",
        codex_model="gpt-6.1-terra",
        codex_reasoning_effort="low",
        gemini_model="gemini-4-neon-low",
        timeout_s=240.0,
        max_workers=4,
        stripped_prefix=True,
        fixed_cwd=empty_cwd,
        emit_usage_telemetry=True,
        on_adapter_output=lambda fam, out: usage_guard.record(
            fam, out.usage_pct, out.rate_limit_info, out.error, returncode=out.returncode
        ),
    )
    ce_cfg = replace(
        runner_cfg,
        system_prompt=(
            "You are an evidence-locked binary checklist arbiter for Congressional "
            "document classification. Answer strictly from the document text and emit JSON."
        ),
    )

    overrides_by_key: dict[str, dict[str, Any]] = {}
    need_specialist: dict[str, dict[str, Any]] = {}
    stats: Counter[str] = Counter()
    details: dict[str, list[dict[str, Any]]] = {
        "2fam_flipped": [],
        "deadlocks_promoted": [],
        "cleanlab_flipped": [],
        "cleanlab_retained": [],
    }

    with SixTupleCache(cache_path) as cache:
        raw_ce = build_live_sota_checkeval_fn(cache, cb_ver, ce_cfg, arbiter_family="claude")

        def _guarded_ce(
            text: str,
            questions: Sequence[Any],
            sides: Mapping[str, Any],
            candidates: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            if usage_guard.should_stop():
                return {"answers": [], "winner": "ambiguous"}
            return raw_ce(text, questions, sides, candidates)

        # ------------------------------------------------------------------
        # Pass A: Reconcile shards 18..28 using bulk_review/shards/review_shard_0018..0028.jsonl
        # ------------------------------------------------------------------
        review_by_key: dict[str, dict[str, Any]] = {}
        disagreements: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for s_idx in range(18, 29):
            rev_path = bulk_review_dir / "shards" / f"review_shard_{s_idx:04d}.jsonl"
            for rrow in _read_jsonl(rev_path):
                dk = str(rrow["doc_key"])
                review_by_key[dk] = rrow
                base_row = row_by_key.get(dk)
                if not base_row:
                    continue
                st = str(rrow.get("audit_status") or "")
                if st in {"confirmed_3of3", "confirmed_checkeval"}:
                    fams = list(base_row.get("consensus_families") or [])
                    if "gemini" not in fams:
                        fams.append("gemini")
                    overrides_by_key[dk] = {"doc_key": dk, "consensus_families": fams}
                    stats[f"pass_a:{st}"] += 1
                elif st in {"disagreement_gold", "disagreement_checkeval"}:
                    disagreements.append((dk, base_row, rrow))
                else:
                    stats[f"pass_a:{st}"] += 1

        def _adj_2fam_one(item: tuple[str, dict[str, Any], dict[str, Any]]) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, str]:
            dk, base_row, rrow = item
            if usage_guard.should_stop():
                return dk, None, None, "usage_halted"
            text = str((cand_by_key.get(dk) or {}).get("text") or "")
            neon_payload = rrow.get("neon_payload")
            if not text or not isinstance(neon_payload, Mapping):
                return dk, None, None, "missing_payload"
            base_gold = base_row.get("gold")
            if not isinstance(base_gold, Mapping):
                return dk, None, None, "missing_base_gold"

            claude_p = _lookup_cached_payload(
                cache=cache,
                family="claude",
                model_ids=("claude-opus-5-5:effort=low", "claude-opus-5-5:effort=medium"),
                blind_text=text,
                doc_key=dk,
                cb_ver=cb_ver,
                core_schema=core_schema,
                core_cls=core_cls,
            )
            codex_p = _lookup_cached_payload(
                cache=cache,
                family="codex",
                model_ids=("gpt-6.2-sol:effort=low", "gpt-6.1-terra:effort=low", "gpt-6.2-sol:effort=medium"),
                blind_text=text,
                doc_key=dk,
                cb_ver=cb_ver,
                core_schema=core_schema,
                core_cls=core_cls,
            )
            if base_row.get("verdict") == "auto_accept_gold":
                claude_p = claude_p or dict(base_gold)
                codex_p = codex_p or dict(base_gold)
            else:
                if claude_p is None and codex_p is None:
                    claude_p = dict(base_gold)
                elif claude_p is None:
                    claude_p = dict(base_gold)
                elif codex_p is None:
                    codex_p = dict(base_gold)

            fam_map: dict[str, Any] = {"claude": claude_p, "codex": codex_p, "gemini": dict(neon_payload)}
            dec = adjudicate_three_family(text, fam_map, doc_key=dk, check_eval_fn=_guarded_ce)
            if dec.verdict in {"auto_accept_gold", "checkeval_resolved"} and dec.accepted_payload is not None:
                old_t = extract_triage_tuple(base_gold)
                new_t = extract_triage_tuple(dec.accepted_payload)
                if new_t != old_t:
                    ov: dict[str, Any] = {
                        "doc_key": dk,
                        "verdict": dec.verdict,
                        "deadlock_reason": None,
                        "consensus_families": list(dec.consensus_families),
                        "gold": dict(dec.accepted_payload),
                        "polish_source": "2fam_3rd_adjudication",
                    }
                    need_spec_gold: dict[str, Any] | None = None
                    if dec.accepted_payload.get("status") != "usable":
                        ov["specialist_fields"] = None
                    elif (
                        dec.accepted_payload.get("specialist_family") != base_gold.get("specialist_family")
                        or base_row.get("specialist_fields") is None
                    ):
                        need_spec_gold = dict(dec.accepted_payload)
                    return dk, ov, need_spec_gold, f"flipped:{old_t}->{new_t}"
                return (
                    dk,
                    {"doc_key": dk, "consensus_families": list(dec.consensus_families)},
                    None,
                    "confirmed_existing_gold",
                )
            return dk, None, None, f"kept_existing_over_{dec.deadlock_reason or 'deadlock'}"

        print(f"[polish] Pass A: adjudicating {len(disagreements)} 2-vs-1 shard_0018..0028 disagreements...", file=sys.stderr, flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(_adj_2fam_one, it) for it in disagreements]):
                dk, ov, sp_gold, status_tag = fut.result()
                stats[f"pass_a_disagree:{status_tag.split(':', 1)[0]}"] += 1
                if ov:
                    overrides_by_key[dk] = ov
                if sp_gold:
                    need_specialist[dk] = sp_gold
                if status_tag.startswith("flipped:"):
                    details["2fam_flipped"].append({"doc_key": dk, "change": status_tag, "filename": row_by_key[dk].get("filename")})

        # ------------------------------------------------------------------
        # Pass B: Adjudicate deadlocks from bulk_review/deadlock_resolutions.jsonl
        # ------------------------------------------------------------------
        dl_recs = _read_jsonl(bulk_review_dir / "deadlock_resolutions.jsonl")
        dl_new_ce: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

        for dl in dl_recs:
            dk = str(dl.get("doc_key") or "")
            base_row = row_by_key.get(dk)
            if not base_row or base_row.get("verdict") != "deadlock_needs_owner":
                continue
            if (
                dl.get("recommended_action") != "resolve"
                or dl.get("validation_passed") is not True
                or dl.get("confidence") not in {"high", "medium"}
                or not isinstance(dl.get("recommended_core"), Mapping)
            ):
                stats["pass_b:kept_deadlock_filter"] += 1
                continue

            text = str((cand_by_key.get(dk) or {}).get("text") or "")
            validated_core = _validate_and_ground_core(dl["recommended_core"], text, core_cls)
            if validated_core is None:
                stats["pass_b:kept_deadlock_grounding_fail"] += 1
                continue

            match_fam = dl.get("matches_prior_family")
            if match_fam in {"claude", "codex", "gemini"}:
                fams = [str(match_fam)] if str(match_fam) == "gemini" else [str(match_fam), "gemini"]
                ov = {
                    "doc_key": dk,
                    "verdict": "checkeval_resolved",
                    "deadlock_reason": None,
                    "consensus_families": fams,
                    "gold": validated_core,
                    "polish_source": "deadlock_2of3_verified",
                }
                if validated_core.get("status") != "usable":
                    ov["specialist_fields"] = None
                else:
                    need_specialist[dk] = validated_core
                overrides_by_key[dk] = ov
                stats["pass_b:promoted_2of3"] += 1
                details["deadlocks_promoted"].append(
                    {
                        "doc_key": dk,
                        "source": "deadlock_2of3_verified",
                        "tuple": extract_triage_tuple(validated_core),
                        "filename": base_row.get("filename"),
                    }
                )
            elif match_fam == "new":
                dl_new_ce.append((dk, base_row, dl, validated_core))
            else:
                stats["pass_b:kept_deadlock_other"] += 1

        def _confirm_new_dl(item: tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
            dk, base_row, dl, validated_core = item
            if usage_guard.should_stop():
                return dk, None, None
            text = str((cand_by_key.get(dk) or {}).get("text") or "")
            rec_tup = extract_triage_tuple(validated_core)
            prior_votes = dl.get("prior_family_votes") or {}
            prior_tup: tuple[Any, Any, Any, Any] = (None, None, None, None)
            prior_payload_stub: dict[str, Any] = {}
            for pfam in ("claude", "codex", "gemini"):
                pv = prior_votes.get(pfam)
                if isinstance(pv, Mapping):
                    prior_tup = (pv.get("status"), pv.get("media_format"), pv.get("is_packet"), pv.get("primary_genre"))
                    prior_payload_stub = {
                        "status": pv.get("status"),
                        "media_format": pv.get("media_format"),
                        "is_packet": pv.get("is_packet"),
                        "primary_genre": pv.get("primary_genre"),
                    }
                    break
            assert rec_tup is not None
            if rec_tup == prior_tup:
                resolved = True
            else:
                ce = run_checkeval_arbiter(
                    text,
                    rec_tup,
                    prior_tup,
                    check_eval_fn=_guarded_ce,
                    candidates={"majority": [validated_core], "minority": [prior_payload_stub] if prior_payload_stub else []},
                )
                resolved = bool(ce.resolved and ce.winner_side == "majority")
            if not resolved:
                return dk, None, None
            ov: dict[str, Any] = {
                "doc_key": dk,
                "verdict": "checkeval_resolved",
                "deadlock_reason": None,
                "consensus_families": ["gemini", "checkeval_arbiter"],
                "gold": validated_core,
                "polish_source": "deadlock_new_ce_verified",
            }
            need_sp: dict[str, Any] | None = None
            if validated_core.get("status") != "usable":
                ov["specialist_fields"] = None
            else:
                need_sp = validated_core
            return dk, ov, need_sp

        print(f"[polish] Pass B: verifying {len(dl_new_ce)} new-proposal deadlocks via CheckEval...", file=sys.stderr, flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(_confirm_new_dl, it) for it in dl_new_ce]):
                dk, ov, sp_gold = fut.result()
                if ov:
                    overrides_by_key[dk] = ov
                    if sp_gold:
                        need_specialist[dk] = sp_gold
                    stats["pass_b:promoted_new_ce"] += 1
                    details["deadlocks_promoted"].append(
                        {
                            "doc_key": dk,
                            "source": "deadlock_new_ce_verified",
                            "tuple": extract_triage_tuple(ov["gold"]),
                            "filename": row_by_key[dk].get("filename"),
                        }
                    )
                else:
                    stats["pass_b:kept_deadlock_new_unconfirmed"] += 1

        # ------------------------------------------------------------------
        # Pass C: Cleanlab-flagged rows (CheckEval + independent family confirmation)
        # ------------------------------------------------------------------
        if cleanlab_json and cleanlab_json.is_file():
            flagged_rows = json.loads(cleanlab_json.read_text(encoding="utf-8"))
        else:
            flagged_rows = _compute_cleanlab_flagged_over_corpus(row_by_key, cand_by_key)

        eligible_cl: list[dict[str, Any]] = []
        for fl in flagged_rows:
            dk = str(fl["doc_key"])
            if dk in overrides_by_key and overrides_by_key[dk].get("polish_source") == "2fam_3rd_adjudication":
                stats["pass_c:already_reconciled_pass_a"] += 1
                continue
            base_row = row_by_key.get(dk)
            if not base_row or not isinstance(base_row.get("gold"), Mapping):
                continue
            if base_row["gold"].get("status") != "usable":
                continue
            eligible_cl.append(fl)

        print(f"[polish] Pass C: auditing {len(eligible_cl)} Cleanlab-flagged docs with gemini-4-neon-low + CheckEval...", file=sys.stderr, flush=True)
        gemini_cl_map = _run_gemini_core_triage_map(
            doc_keys=[str(fl["doc_key"]) for fl in eligible_cl],
            cand_by_key=cand_by_key,
            cache=cache,
            cb_ver=cb_ver,
            core_schema=core_schema,
            core_cls=core_cls,
            runner_cfg=runner_cfg,
            usage_guard=usage_guard,
            workers=workers,
        )

        def _audit_cleanlab_one(fl: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
            dk = str(fl["doc_key"])
            given_genre = str(fl["given_genre"])
            pred_genre = str(fl["pred_genre"])
            base_row = row_by_key[dk]
            base_gold = dict(base_row["gold"])
            text = str((cand_by_key.get(dk) or {}).get("text") or "")

            gem_p = gemini_cl_map.get(dk)
            if gem_p is None and dk in review_by_key and isinstance(review_by_key[dk].get("neon_payload"), Mapping):
                gem_p = dict(review_by_key[dk]["neon_payload"])
            codex_p = _lookup_cached_payload(
                cache=cache,
                family="codex",
                model_ids=("gpt-6.1-terra:effort=low", "gpt-6.2-sol:effort=low", "gpt-6.2-sol:effort=medium"),
                blind_text=text,
                doc_key=dk,
                cb_ver=cb_ver,
                core_schema=core_schema,
                core_cls=core_cls,
            )

            gem_genre = gem_p.get("primary_genre") if gem_p else None
            codex_genre = codex_p.get("primary_genre") if codex_p else None
            confirming = [f for f, g in (("gemini", gem_genre), ("codex", codex_genre)) if g == pred_genre]

            info = {
                "doc_key": dk,
                "shard": shard_idx_by_key.get(dk),
                "filename": base_row.get("filename"),
                "given_genre": given_genre,
                "pred_genre": pred_genre,
                "gemini_genre": gem_genre,
                "codex_genre": codex_genre,
                "p_given": fl.get("p_given"),
                "p_pred": fl.get("p_pred"),
            }

            if not confirming or usage_guard.should_stop():
                return dk, None, None, {**info, "outcome": "retained_no_family_second"}

            mf = base_gold.get("media_format")
            pkt = base_gold.get("is_packet", False)
            pred_tup = ("usable", mf, pkt, pred_genre)
            given_tup = ("usable", mf, pkt, given_genre)
            pred_cand = dict(gem_p) if gem_genre == pred_genre and gem_p else (dict(codex_p) if codex_p else {**base_gold, "primary_genre": pred_genre})
            ce = run_checkeval_arbiter(
                text,
                pred_tup,
                given_tup,
                check_eval_fn=_guarded_ce,
                candidates={"majority": [pred_cand], "minority": [base_gold]},
            )
            if not (ce.resolved and ce.winner_side == "majority"):
                return dk, None, None, {**info, "outcome": f"retained_ce_{ce.reason}"}

            new_sf = GENRE_TO_SPECIALIST_FAMILY.get(pred_genre, base_gold.get("specialist_family"))
            new_gold = dict(base_gold)
            new_gold["primary_genre"] = pred_genre
            new_gold["specialist_family"] = new_sf
            new_gold["rationale"] = (
                f"Cleanlab + CheckEval ({','.join(confirming)} confirmed) shifted {given_genre} -> {pred_genre}. "
                + str(base_gold.get("rationale") or "")[:300]
            )[:475]

            existing_ov = dict(overrides_by_key.get(dk) or {"doc_key": dk})
            fams = list(existing_ov.get("consensus_families") or base_row.get("consensus_families") or [])
            for cf in confirming:
                if cf not in fams:
                    fams.append(cf)
            existing_ov.update(
                {
                    "doc_key": dk,
                    "verdict": "checkeval_resolved",
                    "deadlock_reason": None,
                    "consensus_families": fams,
                    "gold": new_gold,
                    "polish_source": "cleanlab_checkeval_confirmed",
                }
            )
            need_sp: dict[str, Any] | None = None
            if new_sf != base_gold.get("specialist_family") or base_row.get("specialist_fields") is None:
                need_sp = new_gold
            return dk, existing_ov, need_sp, {**info, "outcome": "flipped", "confirming": confirming}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(_audit_cleanlab_one, fl) for fl in eligible_cl]):
                dk, ov, sp_gold, info = fut.result()
                if ov:
                    overrides_by_key[dk] = ov
                    if sp_gold:
                        need_specialist[dk] = sp_gold
                    stats["pass_c:flipped"] += 1
                    details["cleanlab_flipped"].append(info)
                else:
                    stats["pass_c:retained"] += 1
                    details["cleanlab_retained"].append(info)

        # ------------------------------------------------------------------
        # Pass D: Batch Stage 2 Claude specialist extraction for promoted/changed usable docs
        # ------------------------------------------------------------------
        if need_specialist and not usage_guard.should_stop():
            by_sf: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
            for dk, fg in sorted(need_specialist.items()):
                pg = fg.get("primary_genre")
                sf = fg.get("specialist_family") or GENRE_TO_SPECIALIST_FAMILY.get(str(pg or ""))
                if sf and sf in specialist_schemas:
                    by_sf.setdefault(str(sf), []).append((dk, cand_by_key[dk], fg))

            warmed_prefix_keys: set[tuple[str, str]] = set()
            for sf, items in sorted(by_sf.items()):
                if usage_guard.should_stop():
                    break
                sf_schema = specialist_schemas[sf]
                sf_cls = spec_clses.get(sf)
                sf_sys_prompt, sf_prefix = split_specialist_prefix(sf)
                sf_batch_schema = build_batch_schema(sf_schema, f"DocMetaSpecialistBatch_{sf}")
                sf_cfg = replace(runner_cfg, system_prompt=sf_sys_prompt)
                docs_spec = []
                for pos, (dk, crow, fg) in enumerate(items):
                    txt = str(crow["text"])
                    sprompt = render_pilot_specialist_prompt(
                        txt, sf, str(fg.get("primary_genre") or ""), cb_ver, core_result=fg
                    )
                    ck = _single_doc_cache_key(
                        family="claude",
                        model_id=sf_cfg.model_id_for("claude"),
                        blind_text=txt,
                        single_prompt=sprompt,
                        single_schema=sf_schema,
                        cb_ver=cb_ver,
                        slice_spec=f"blind_text_only:specialist:{sf}",
                    )
                    docs_spec.append((pos, crow, sprompt, ck, fg))

                print(f"[polish] Pass D: extracting Stage 2 `{sf}` for {len(docs_spec)} updated docs...", file=sys.stderr, flush=True)
                sf_res = _run_batched_stage_for_family(
                    family="claude",
                    docs_spec=docs_spec,
                    batch_size=8,
                    workers=min(workers, 4),
                    single_schema=sf_schema,
                    batch_schema=sf_batch_schema,
                    single_model_cls=sf_cls,
                    cb_ver=cb_ver,
                    slice_spec=f"blind_text_only:specialist:{sf}",
                    stage=f"specialist:{sf}",
                    cfg=sf_cfg,
                    codebook_prefix=sf_prefix,
                    format_batch_prompt_fn=lambda batch_items, s=sf: _format_specialist_batch_prompt(batch_items, s),
                    cache=cache,
                    adapters=None,
                    usage_guard=usage_guard,
                    warmed_prefix_keys=warmed_prefix_keys,
                )
                for pos, (dk, crow, _fg) in enumerate(items):
                    r = sf_res.get(pos)
                    txt = str(crow["text"])
                    if r and r.ok and r.parsed is not None and verify_span_grounding(txt, r.parsed).passed:
                        merged_spec = merge_consensus_payload(txt, [r.parsed])
                        ov_entry = overrides_by_key.setdefault(dk, {"doc_key": dk})
                        gold_for_doc = ov_entry.get("gold") or row_by_key.get(dk, {}).get("gold")
                        if isinstance(gold_for_doc, Mapping):
                            _rc, rec_sp, _reps, s_errs = reconcile_and_validate_v7_payload(txt, gold_for_doc, merged_spec)
                            if not s_errs and rec_sp is not None:
                                ov_entry["specialist_fields"] = rec_sp
                                stats["pass_d:specialist_ok"] += 1
                            else:
                                stats["pass_d:specialist_failed"] += 1
                        else:
                            ov_entry["specialist_fields"] = merged_spec
                            stats["pass_d:specialist_ok"] += 1
                    else:
                        stats["pass_d:specialist_failed"] += 1

    # Reconcile every override payload containing `gold` so overrides satisfy canonical grounding pre-seal.
    for dk, ov in list(overrides_by_key.items()):
        if not isinstance(ov.get("gold"), Mapping):
            continue
        txt = str((cand_by_key.get(dk) or {}).get("text") or "")
        if not txt.strip():
            continue
        rec_core, rec_spec, _repairs, val_errs = reconcile_and_validate_v7_payload(
            txt, ov["gold"], ov.get("specialist_fields")
        )
        if not val_errs:
            ov["gold"] = rec_core
            if "specialist_fields" in ov:
                ov["specialist_fields"] = rec_spec
        else:
            stats["overrides:canonical_reconcile_failed"] += 1

    ordered_overrides = [overrides_by_key[dk] for dk in sorted(overrides_by_key)]
    ov_path = out_dir / "polish_overrides.jsonl"
    _atomic_write_jsonl(ov_path, ordered_overrides)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overrides_path": str(ov_path),
        "total_overrides": len(ordered_overrides),
        "stats": dict(sorted(stats.items())),
        "usage_guard": usage_guard.summary(),
        "details": details,
    }
    rep_path = out_dir / "polish_report.json"
    rep_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DocMeta V7.3 quick-polish tooling.")
    sub = p.add_subparsers(dest="cmd", required=True)

    mb = sub.add_parser("mine-budget", help="Mine unseen fiscal/budget/cost-estimate candidates.")
    mb.add_argument("--corpus-dir", type=Path, default=default_corpus_dir())
    mb.add_argument("--out-dir", type=Path, default=default_corpus_dir() / "topup_budget")
    mb.add_argument("--llm-queue-path", type=Path, default=default_parquet_paths()["llm_queue"])
    mb.add_argument("--limit", type=int, default=55)
    mb.add_argument("--seed", type=int, default=20261123)
    mb.add_argument("--expand", action="store_true")
    mb.add_argument("--exclude-candidates", action="append", type=Path, default=[])

    bo = sub.add_parser("build-overrides", help="Build polish_overrides.jsonl from bulk_review + Cleanlab.")
    bo.add_argument("--corpus-dir", type=Path, default=default_corpus_dir())
    bo.add_argument("--bulk-review-dir", type=Path, default=default_corpus_dir() / "bulk_review")
    bo.add_argument("--out-dir", type=Path, default=default_corpus_dir() / "polish")
    bo.add_argument("--cache-path", type=Path, default=default_cache_path())
    bo.add_argument("--workers", type=int, default=6)
    bo.add_argument("--max-usage-pct", type=float, default=50.0)
    bo.add_argument("--cleanlab-json", type=Path, default=None)

    args = p.parse_args(argv)
    if args.cmd == "mine-budget":
        res = cmd_mine_budget(
            corpus_dir=args.corpus_dir,
            out_dir=args.out_dir,
            llm_queue_path=args.llm_queue_path,
            limit=args.limit,
            seed=args.seed,
            expand=args.expand,
            exclude_candidates=args.exclude_candidates,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    res = cmd_build_overrides(
        corpus_dir=args.corpus_dir,
        bulk_review_dir=args.bulk_review_dir,
        out_dir=args.out_dir,
        cache_path=args.cache_path,
        workers=args.workers,
        max_usage_pct=args.max_usage_pct,
        cleanlab_json=args.cleanlab_json,
    )
    print(json.dumps({k: v for k, v in res.items() if k != "details"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
