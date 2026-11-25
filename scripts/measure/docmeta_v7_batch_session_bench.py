#!/usr/bin/env python3
"""Controlled benchmark: doc count per request & persistent sessions on DocMeta V7.1 core triage.

Compares ONLY `claude-opus-5-5 --effort low` (`opus_low`) and `gpt-6.2-sol` effort=low (`sol_low`)
across stateless micro-batches (B=1, 8, 16, 24) and persistent resumed sessions (48 across 6x8
turns, and 24 across 24x1 turns) against locked 3-family gold labels from `pilot-100-v70b`.

Outputs `.cache/archive-release/docmeta-v7-batch-bench-20261123/{results.json,report.md}`.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

from congress_docmeta.v7.codebook import render_core_prompt
from congress_docmeta.v7.factory.grounding import (
    extract_triage_tuple,
    repair_span_refs_in_payload,
    verify_span_grounding,
)
from congress_docmeta.v7.factory.pilot import (
    CORE_TRIAGE_SCHEMA,
    default_ssot_path,
    load_ssot_rows,
)
from congress_docmeta.v7.factory.runners import (
    DEFAULT_CLAUDE_BIN,
    DEFAULT_CODEX_BIN,
    extract_json_payload,
)
from congress_docmeta.v7.factory.splits import compute_agreement_metrics


DEFAULT_PILOT_GOLD = Path(
    ".cache/archive-release/docmeta-v7-factory/pilot-100-v70b/gold_candidates.jsonl"
)
DEFAULT_OUT_DIR = Path(".cache/archive-release/docmeta-v7-batch-bench-20261123")


def _build_stripped_system_prompt_and_template() -> tuple[str, str]:
    """Split `render_core_prompt` into static stripped codebook prefix and doc template."""
    full = render_core_prompt("<<PER_DOC_TEXT>>", doc_id="<<DOC_ID>>")
    marker = "DOC_ID: <<DOC_ID>>"
    idx = full.find(marker)
    if idx < 0:
        raise RuntimeError("Could not split static codebook prefix from render_core_prompt")
    codebook_prefix = full[:idx].strip()
    sys_prompt = (
        "You are a deterministic, high-precision Congressional archive document classifier "
        "and JSON extractor. Follow the DocMeta V7.1 codebook below strictly using ONLY "
        "verbatim document text. Output ONLY valid JSON conforming strictly to the requested "
        "schema. Never invent titles, dates, committees, or external metadata.\n\n"
        + codebook_prefix
    )
    return sys_prompt, codebook_prefix


def _build_batch_schema() -> dict[str, Any]:
    """Build strict JSON schema wrapping a list of `CORE_TRIAGE_SCHEMA` items keyed by `doc_id`."""
    item_props = {"doc_id": {"type": "string"}}
    for k, v in CORE_TRIAGE_SCHEMA["properties"].items():
        item_props[k] = copy.deepcopy(v)
    item_req = ["doc_id", *CORE_TRIAGE_SCHEMA["required"]]
    return {
        "title": "DocMetaCoreTriageBatch",
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


BATCH_TRIAGE_SCHEMA: dict[str, Any] = _build_batch_schema()


def load_stratified_gold_48(
    *,
    pilot_gold_path: Path = DEFAULT_PILOT_GOLD,
    ssot_path: Path | None = None,
    limit: int = 48,
    seed: int = 20261123,
) -> list[dict[str, Any]]:
    """Load 48 stratified 3-family gold docs with blind text from `pilot-100-v70b`."""
    resolved_ssot = ssot_path or default_ssot_path()
    ssot_rows = load_ssot_rows(resolved_ssot)
    text_by_key: dict[str, str] = {}
    for row in ssot_rows:
        txt = str(row.get("text") or "")
        text_by_key[str(row["doc_key"])] = txt[:9000] if len(txt) > 9000 else txt

    eligible_by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with pilot_gold_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("verdict") not in {"auto_accept_gold", "checkeval_resolved"}:
                continue
            gold = rec.get("gold")
            if not isinstance(gold, Mapping):
                continue
            dk = str(rec["doc_key"])
            if dk not in text_by_key:
                continue
            gt = extract_triage_tuple(gold)
            if gt is None:
                continue
            item = {
                "doc_key": dk,
                "stratum": str(rec.get("pilot_stratum") or "other"),
                "verdict": rec["verdict"],
                "text": text_by_key[dk],
                "gold_payload": dict(gold),
                "gold_tuple": list(gt),
            }
            eligible_by_stratum[item["stratum"]].append(item)

    rng = random.Random(seed)
    for bucket in eligible_by_stratum.values():
        bucket.sort(key=lambda x: x["doc_key"])
        rng.shuffle(bucket)

    strata_order = sorted(eligible_by_stratum.keys())
    selected: list[dict[str, Any]] = []
    idx = 0
    while len(selected) < limit:
        added_any = False
        for st in strata_order:
            b = eligible_by_stratum[st]
            if idx < len(b):
                selected.append(b[idx])
                added_any = True
                if len(selected) >= limit:
                    break
        if not added_any:
            break
        idx += 1

    # Shuffle selected into homogeneous batch order while assigning clean short doc_ids d00..d47.
    rng.shuffle(selected)
    out: list[dict[str, Any]] = []
    for i, item in enumerate(selected):
        out.append({"doc_id": f"d{i:02d}", "pool_pos": i, **item})
    return out


def _format_docs_prompt(
    docs: Sequence[Mapping[str, Any]],
    *,
    is_batch: bool,
    extra_header: str = "",
    codebook_prefix: str = "",
) -> str:
    """Render user prompt containing 1 or N delimited documents."""
    parts: list[str] = []
    if codebook_prefix:
        parts.append(codebook_prefix)
        parts.append("")
    if extra_header:
        parts.append(extra_header)
        parts.append("")

    if is_batch:
        doc_ids = [str(d["doc_id"]) for d in docs]
        parts.append(
            f"Classify all {len(docs)} documents below independently using strictly each "
            f"document's own text (`<<<DOC_TEXT>>>`...`<<<END_DOC_TEXT>>>`).\n"
            f"Return JSON `DocMetaCoreTriageBatch` with `items` containing ONE entry for EVERY "
            f"doc_id in exact order: {doc_ids}.\n"
            "Do NOT merge, skip, or reorder documents. Every `title_span` and `date_spans` "
            "must be verbatim substrings from THAT document's own text."
        )
    else:
        d = docs[0]
        parts.append(
            f"Classify document `doc_id={d['doc_id']}` strictly from its text below and "
            "output JSON conforming to `CoreEnvelopeExtraction`."
        )

    n = len(docs)
    for i, d in enumerate(docs, start=1):
        parts.append(
            f"\n=== DOCUMENT {i} / {n} | doc_id={d['doc_id']} ===\n"
            f"<<<DOC_TEXT>>>\n{d['text']}\n<<<END_DOC_TEXT>>>"
        )
    return "\n".join(parts)


def _norm_claude_usage(obj: Mapping[str, Any]) -> dict[str, Any]:
    mu = obj.get("modelUsage") or {}
    u = next(iter(mu.values()), {}) if isinstance(mu, Mapping) else {}
    return {
        "input_tokens": int(u.get("inputTokens", 0) or 0),
        "cache_read_tokens": int(u.get("cacheReadInputTokens", 0) or 0),
        "cache_create_tokens": int(u.get("cacheCreationInputTokens", 0) or 0),
        "output_tokens": int(u.get("outputTokens", 0) or 0),
        "thinking_tokens": int(u.get("thinkingTokens", 0) or 0),
        "cost_usd": float(u.get("costUSD", 0.0) or 0.0),
        "num_turns": int(obj.get("num_turns", 0) or 0),
    }


def _call_claude_opus_low(
    prompt: str,
    *,
    system_prompt: str,
    schema: dict[str, Any],
    empty_cwd: Path,
    timeout_s: float,
    session_id: str | None = None,
    persist_session: bool = False,
) -> dict[str, Any]:
    schema_json = json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
    cmd = [
        DEFAULT_CLAUDE_BIN,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        schema_json,
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--system-prompt",
        system_prompt,
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--model",
        "claude-opus-5-5",
        "--effort",
        "low",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])
    elif not persist_session:
        cmd.append("--no-session-persistence")

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=empty_cwd,
        )
        wall_s = time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"timeout after {timeout_s}s",
            "wall_s": time.monotonic() - t0,
            "session_id": session_id,
            "usage": {},
            "payload": None,
        }

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or f"rc={proc.returncode}")[-400:],
            "wall_s": wall_s,
            "session_id": session_id,
            "usage": {},
            "payload": None,
        }

    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": f"json_decode_env: {exc}",
            "wall_s": wall_s,
            "session_id": session_id,
            "usage": {},
            "payload": None,
        }

    new_sid = str(env.get("session_id") or session_id or "") or None
    usage = _norm_claude_usage(env)
    payload = env.get("structured_output")
    if not isinstance(payload, dict):
        _, payload = extract_json_payload(proc.stdout, provider="claude_cli")
    return {
        "ok": isinstance(payload, dict),
        "error": None if isinstance(payload, dict) else f"missing structured_output: {str(env)[:240]}",
        "wall_s": wall_s,
        "session_id": new_sid,
        "usage": usage,
        "payload": payload if isinstance(payload, dict) else None,
    }


def _call_codex_sol_low(
    prompt: str,
    *,
    schema: dict[str, Any],
    empty_cwd: Path,
    timeout_s: float,
    thread_id: str | None = None,
    persist_session: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sol_schema_") as td:
        schema_path = Path(td) / "schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

        if thread_id:
            cmd = [
                DEFAULT_CODEX_BIN,
                "exec",
                "resume",
                thread_id,
                "--json",
                "--skip-git-repo-check",
                "-c",
                "mcp_servers={}",
                "-c",
                'model_reasoning_effort="low"',
                "--disable",
                "memories",
                "--disable",
                "multi_agent",
                "--disable",
                "goals",
                "--disable",
                "steer",
                "-m",
                "gpt-6.2-sol",
                "-",
            ]
        else:
            cmd = [
                DEFAULT_CODEX_BIN,
                "exec",
                "--json",
                "-s",
                "read-only",
                *([] if persist_session else ["--ephemeral"]),
                "--skip-git-repo-check",
                "-c",
                "mcp_servers={}",
                "-c",
                'model_reasoning_effort="low"',
                "--disable",
                "memories",
                "--disable",
                "multi_agent",
                "--disable",
                "goals",
                "--disable",
                "steer",
                "-m",
                "gpt-6.2-sol",
                "--output-schema",
                str(schema_path),
                "-",
            ]

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout_s,
                cwd=empty_cwd,
            )
            wall_s = time.monotonic() - t0
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"timeout after {timeout_s}s",
                "wall_s": time.monotonic() - t0,
                "session_id": thread_id,
                "usage": {},
                "payload": None,
            }

    events: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
        except json.JSONDecodeError:
            continue

    new_tid = next(
        (str(e["thread_id"]) for e in events if e.get("type") == "thread.started" and e.get("thread_id")),
        thread_id,
    )
    raw_usage = next((e.get("usage") for e in reversed(events) if isinstance(e.get("usage"), dict)), {})
    usage = {
        "input_tokens": int(raw_usage.get("input_tokens", 0) or 0),
        "cache_read_tokens": int(raw_usage.get("cached_input_tokens", 0) or 0),
        "cache_create_tokens": int(raw_usage.get("cache_write_input_tokens", 0) or 0),
        "output_tokens": int(raw_usage.get("output_tokens", 0) or 0),
        "thinking_tokens": int(raw_usage.get("reasoning_output_tokens", 0) or 0),
        "cost_usd": None,
        "num_turns": 1,
    }
    msg_text = next(
        (
            str(e["item"].get("text") or "")
            for e in reversed(events)
            if isinstance(e.get("item"), dict) and e["item"].get("type") == "agent_message"
        ),
        "",
    )
    if proc.returncode != 0 and not msg_text:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or f"rc={proc.returncode}")[-400:],
            "wall_s": wall_s,
            "session_id": new_tid,
            "usage": usage,
            "payload": None,
        }

    _, payload = extract_json_payload(msg_text, provider="codex_cli")
    return {
        "ok": isinstance(payload, dict),
        "error": None if isinstance(payload, dict) else f"unparsed_agent_msg: {msg_text[:240]}",
        "wall_s": wall_s,
        "session_id": new_tid,
        "usage": usage,
        "payload": payload if isinstance(payload, dict) else None,
    }


def _tuple_label(t: Sequence[Any] | None) -> str:
    if not t:
        return "MISSING"
    status, mf, pkt, pg = t[0], t[1], t[2], t[3]
    if status != "usable":
        return f"STATUS:{status}"
    return f"{pg or 'NONE'}|{mf or 'NONE'}|pkt={bool(pkt)}"


def _status_genre_label(t: Sequence[Any] | None) -> str:
    if not t:
        return "MISSING"
    if t[0] != "usable":
        return f"STATUS:{t[0]}"
    return str(t[3] or "NONE")


def _extract_batch_items(
    payload: Mapping[str, Any] | None,
    docs: Sequence[Mapping[str, Any]],
    *,
    is_batch: bool,
) -> list[dict[str, Any] | None]:
    if payload is None:
        return [None] * len(docs)
    if not is_batch:
        return [dict(payload)]
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return [None] * len(docs)
    by_id: dict[str, dict[str, Any]] = {}
    for entry in raw_items:
        if isinstance(entry, Mapping) and entry.get("doc_id"):
            by_id[str(entry["doc_id"]).strip()] = dict(entry)
    out: list[dict[str, Any] | None] = []
    for idx, d in enumerate(docs):
        hit = by_id.get(str(d["doc_id"]))
        if hit is None and len(raw_items) == len(docs) and isinstance(raw_items[idx], Mapping):
            hit = dict(raw_items[idx])
        out.append(hit)
    return out


def _score_doc_prediction(
    doc: Mapping[str, Any],
    pred_payload: Mapping[str, Any] | None,
    *,
    batch_pos: int,
    batch_len: int,
    turn_idx: int,
) -> dict[str, Any]:
    gt = tuple(doc["gold_tuple"])
    text = str(doc["text"])
    if not isinstance(pred_payload, Mapping):
        return {
            "doc_id": doc["doc_id"],
            "doc_key": doc["doc_key"],
            "stratum": doc["stratum"],
            "pool_pos": doc["pool_pos"],
            "batch_pos": batch_pos,
            "batch_len": batch_len,
            "turn_idx": turn_idx,
            "parsed_ok": False,
            "grounding_ok": False,
            "grounding_errors": ["missing_payload"],
            "gold_tuple": list(gt),
            "pred_tuple": None,
            "exact_match": False,
            "genre_status_match": False,
        }
    repaired = repair_span_refs_in_payload(text, dict(pred_payload))
    g_res = verify_span_grounding(text, repaired)
    pt = extract_triage_tuple(repaired)
    if pt is None:
        return {
            "doc_id": doc["doc_id"],
            "doc_key": doc["doc_key"],
            "stratum": doc["stratum"],
            "pool_pos": doc["pool_pos"],
            "batch_pos": batch_pos,
            "batch_len": batch_len,
            "turn_idx": turn_idx,
            "parsed_ok": False,
            "grounding_ok": False,
            "grounding_errors": ["invalid_triage_tuple"],
            "gold_tuple": list(gt),
            "pred_tuple": None,
            "exact_match": False,
            "genre_status_match": False,
        }
    exact = tuple(pt) == tuple(gt)
    gs_match = (pt[0] == gt[0]) and (True if gt[0] != "usable" else pt[3] == gt[3])
    return {
        "doc_id": doc["doc_id"],
        "doc_key": doc["doc_key"],
        "stratum": doc["stratum"],
        "pool_pos": doc["pool_pos"],
        "batch_pos": batch_pos,
        "batch_len": batch_len,
        "turn_idx": turn_idx,
        "parsed_ok": True,
        "grounding_ok": bool(g_res.passed),
        "grounding_errors": [f"{e.path}:{e.reason}" for e in g_res.errors],
        "gold_tuple": list(gt),
        "pred_tuple": list(pt),
        "exact_match": exact,
        "genre_status_match": gs_match,
    }


def _run_model_arm(
    *,
    model_name: str,
    arm_name: str,
    docs: Sequence[Mapping[str, Any]],
    chunk_size: int,
    persistent: bool,
    concurrency: int,
    system_prompt: str,
    codebook_prefix: str,
    empty_cwd: Path,
) -> dict[str, Any]:
    chunks = [list(docs[i : i + chunk_size]) for i in range(0, len(docs), chunk_size)]
    is_batch = chunk_size > 1
    schema = BATCH_TRIAGE_SCHEMA if is_batch else CORE_TRIAGE_SCHEMA
    timeout_s = {1: 90.0, 8: 180.0, 16: 240.0, 24: 300.0}.get(chunk_size, 240.0)

    turn_records: list[dict[str, Any]] = [{} for _ in range(len(chunks))]
    doc_scores_by_pos: dict[int, dict[str, Any]] = {}

    def _invoke_one(prompt_txt: str, *, sid: str | None, persist: bool) -> dict[str, Any]:
        if model_name == "opus_low":
            return _call_claude_opus_low(
                prompt_txt,
                system_prompt=system_prompt,
                schema=schema,
                empty_cwd=empty_cwd,
                timeout_s=timeout_s,
                session_id=sid,
                persist_session=persist,
            )
        return _call_codex_sol_low(
            prompt_txt,
            schema=schema,
            empty_cwd=empty_cwd,
            timeout_s=timeout_s,
            thread_id=sid,
            persist_session=persist,
        )

    t_arm_0 = time.monotonic()

    if persistent:
        sid: str | None = None
        for t_idx, chunk in enumerate(chunks):
            is_first = t_idx == 0
            if model_name == "opus_low":
                prompt_txt = _format_docs_prompt(
                    chunk,
                    is_batch=is_batch,
                    extra_header="" if is_first else f"Continuing session (turn {t_idx + 1}/{len(chunks)}). Apply the exact same DocMeta V7.1 system codebook and JSON schema.",
                    codebook_prefix="",
                )
            else:
                schema_hint = ""
                if is_first:
                    schema_hint = (
                        "Remember this exact JSON output schema for all turns in this session:\n"
                        + json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
                    )
                else:
                    schema_hint = (
                        f"Continuing session (turn {t_idx + 1}/{len(chunks)}). Apply the EXACT same "
                        "DocMeta V7.1 codebook rules from Turn 1 and reply ONLY with raw valid JSON matching the schema (no markdown fences)."
                    )
                prompt_txt = _format_docs_prompt(
                    chunk,
                    is_batch=is_batch,
                    extra_header=schema_hint,
                    codebook_prefix=codebook_prefix if is_first else "",
                )

            res = _invoke_one(prompt_txt, sid=sid, persist=True)
            if res.get("session_id"):
                sid = res["session_id"]

            items = _extract_batch_items(res.get("payload"), chunk, is_batch=is_batch)
            scored_chunk = [
                _score_doc_prediction(d, p, batch_pos=bi, batch_len=len(chunk), turn_idx=t_idx)
                for bi, (d, p) in enumerate(zip(chunk, items))
            ]
            for d, sc in zip(chunk, scored_chunk):
                doc_scores_by_pos[int(d["pool_pos"])] = sc

            ex_ok = sum(1 for sc in scored_chunk if sc["exact_match"])
            turn_records[t_idx] = {
                "turn_idx": t_idx,
                "n_docs": len(chunk),
                "ok": bool(res["ok"]),
                "error": res["error"],
                "wall_s": round(float(res["wall_s"]), 2),
                "usage": res.get("usage") or {},
                "exact_acc": ex_ok / len(chunk),
                "parsed_ok": sum(1 for sc in scored_chunk if sc["parsed_ok"]),
            }
            print(
                f"[bench] {model_name} {arm_name} turn={t_idx + 1}/{len(chunks)} "
                f"ok={res['ok']} wall={res['wall_s']:.1f}s exact={ex_ok}/{len(chunk)} "
                f"usage={res.get('usage')}",
                file=sys.stderr,
                flush=True,
            )
    else:
        def _run_stateless_chunk(t_idx: int, chunk: list[Mapping[str, Any]]) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
            if model_name == "opus_low":
                prompt_txt = _format_docs_prompt(chunk, is_batch=is_batch)
            else:
                prompt_txt = _format_docs_prompt(chunk, is_batch=is_batch, codebook_prefix=codebook_prefix)
            res = _invoke_one(prompt_txt, sid=None, persist=False)
            items = _extract_batch_items(res.get("payload"), chunk, is_batch=is_batch)
            scored_chunk = [
                _score_doc_prediction(d, p, batch_pos=bi, batch_len=len(chunk), turn_idx=t_idx)
                for bi, (d, p) in enumerate(zip(chunk, items))
            ]
            return t_idx, res, scored_chunk

        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(chunks)))) as pool:
            futs = {pool.submit(_run_stateless_chunk, ti, ch): ti for ti, ch in enumerate(chunks)}
            for fut in as_completed(futs):
                t_idx, res, scored_chunk = fut.result()
                for sc in scored_chunk:
                    doc_scores_by_pos[int(sc["pool_pos"])] = sc
                ex_ok = sum(1 for sc in scored_chunk if sc["exact_match"])
                turn_records[t_idx] = {
                    "turn_idx": t_idx,
                    "n_docs": len(scored_chunk),
                    "ok": bool(res["ok"]),
                    "error": res["error"],
                    "wall_s": round(float(res["wall_s"]), 2),
                    "usage": res.get("usage") or {},
                    "exact_acc": ex_ok / len(scored_chunk),
                    "parsed_ok": sum(1 for sc in scored_chunk if sc["parsed_ok"]),
                }
                print(
                    f"[bench] {model_name} {arm_name} chunk={t_idx + 1}/{len(chunks)} "
                    f"ok={res['ok']} wall={res['wall_s']:.1f}s exact={ex_ok}/{len(scored_chunk)}",
                    file=sys.stderr,
                    flush=True,
                )

    total_wall_s = time.monotonic() - t_arm_0
    ordered_scores = [doc_scores_by_pos[i] for i in sorted(doc_scores_by_pos.keys())]
    n_docs = len(ordered_scores)

    y_true_full = [_tuple_label(sc["gold_tuple"]) for sc in ordered_scores]
    y_pred_full = [_tuple_label(sc["pred_tuple"]) for sc in ordered_scores]
    agree_full = compute_agreement_metrics(y_true_full, y_pred_full)

    y_true_gs = [_status_genre_label(sc["gold_tuple"]) for sc in ordered_scores]
    y_pred_gs = [_status_genre_label(sc["pred_tuple"]) for sc in ordered_scores]
    agree_gs = compute_agreement_metrics(y_true_gs, y_pred_gs)

    half = n_docs // 2
    first_half_acc = sum(1 for sc in ordered_scores[:half] if sc["exact_match"]) / max(1, half)
    second_half_acc = sum(1 for sc in ordered_scores[half:] if sc["exact_match"]) / max(1, n_docs - half)

    # Batch position quartile accuracy for multi-doc single turns
    batch_pos_acc: dict[str, float] = {}
    if chunk_size >= 4:
        q_buckets: dict[int, list[bool]] = defaultdict(list)
        for sc in ordered_scores:
            q_idx = min(3, (sc["batch_pos"] * 4) // max(1, sc["batch_len"]))
            q_buckets[q_idx].append(sc["exact_match"])
        for q_idx in sorted(q_buckets.keys()):
            vals = q_buckets[q_idx]
            batch_pos_acc[f"q{q_idx + 1}"] = sum(vals) / len(vals)

    tokens_per_doc = _summarize_tokens_per_doc(model_name, persistent, turn_records, n_docs)

    return {
        "model": model_name,
        "arm": arm_name,
        "chunk_size": chunk_size,
        "persistent": persistent,
        "n_docs": n_docs,
        "calls": len(chunks),
        "parsed_ok_count": sum(1 for sc in ordered_scores if sc["parsed_ok"]),
        "parsed_rate": sum(1 for sc in ordered_scores if sc["parsed_ok"]) / max(1, n_docs),
        "exact_tuple_acc": sum(1 for sc in ordered_scores if sc["exact_match"]) / max(1, n_docs),
        "genre_status_acc": sum(1 for sc in ordered_scores if sc["genre_status_match"]) / max(1, n_docs),
        "macro_f1_full": agree_full["macro_f1"],
        "gwet_ac1_full": agree_full["gwet_ac1"],
        "macro_f1_genre": agree_gs["macro_f1"],
        "gwet_ac1_genre": agree_gs["gwet_ac1"],
        "grounding_pass_rate": sum(1 for sc in ordered_scores if sc["grounding_ok"]) / max(1, n_docs),
        "first_half_acc": first_half_acc,
        "second_half_acc": second_half_acc,
        "batch_pos_acc": batch_pos_acc,
        "wall_s_total": round(total_wall_s, 2),
        "wall_s_per_doc": round(total_wall_s / max(1, n_docs), 2),
        "tokens_per_doc": tokens_per_doc,
        "turn_records": turn_records,
        "doc_scores": ordered_scores,
    }


def _summarize_tokens_per_doc(
    model_name: str,
    persistent: bool,
    turn_records: Sequence[Mapping[str, Any]],
    n_docs: int,
) -> dict[str, Any]:
    """Compute true per-doc token & cost usage (CLIs report cumulative usage on `--resume`)."""
    if persistent and turn_records:
        last_u = turn_records[-1].get("usage") or {}
        tot_in = int(last_u.get("input_tokens", 0) or 0)
        tot_cr = int(last_u.get("cache_read_tokens", 0) or 0)
        tot_cc = int(last_u.get("cache_create_tokens", 0) or 0)
        tot_out = int(last_u.get("output_tokens", 0) or 0)
        tot_usd = float(last_u["cost_usd"]) if last_u.get("cost_usd") is not None else None
    else:
        tot_in = sum(int((tr.get("usage") or {}).get("input_tokens", 0) or 0) for tr in turn_records)
        tot_cr = sum(int((tr.get("usage") or {}).get("cache_read_tokens", 0) or 0) for tr in turn_records)
        tot_cc = sum(int((tr.get("usage") or {}).get("cache_create_tokens", 0) or 0) for tr in turn_records)
        tot_out = sum(int((tr.get("usage") or {}).get("output_tokens", 0) or 0) for tr in turn_records)
        usd_vals = [
            float((tr.get("usage") or {}).get("cost_usd"))
            for tr in turn_records
            if (tr.get("usage") or {}).get("cost_usd") is not None
        ]
        tot_usd = float(sum(usd_vals)) if usd_vals else None

    if model_name.startswith("sol"):
        tot_uncached_in_plus_cc = max(0, tot_in - tot_cr) + tot_cc
    else:
        tot_uncached_in_plus_cc = tot_in + tot_cc

    return {
        "fresh_input": round(tot_uncached_in_plus_cc / max(1, n_docs), 1),
        "cache_read": round(tot_cr / max(1, n_docs), 1),
        "cache_create": round(tot_cc / max(1, n_docs), 1),
        "output": round(tot_out / max(1, n_docs), 1),
        "usd_per_doc": round(tot_usd / max(1, n_docs), 5) if tot_usd is not None else None,
        "est_10k_usd": round((tot_usd / max(1, n_docs)) * 10000.0, 2) if tot_usd is not None else None,
    }


def _render_report_markdown(report_json: Mapping[str, Any]) -> str:
    all_runs = report_json["runs"]
    paired = report_json["paired_consensus"]
    strata_cnt = report_json["strata_counts"]
    n_docs_pool = report_json["n_docs_pool"]

    md: list[str] = [
        "# DocMeta V7.1 — Batch Size & Session Persistence Benchmark (`opus_low` vs `sol_low`)",
        "",
        f"- **Dataset:** `{n_docs_pool}` stratified docs from `pilot-100-v70b` 3-family gold (`{len(strata_cnt)}` strata)",
        "- **Models:** `claude-opus-5-5 --effort low` (`opus_low`) and `gpt-6.2-sol effort=low` (`sol_low`), stripped prefixes + fixed `cwd`",
        "- **Note:** Session token/USD metrics report exact per-turn deltas (CLI `--resume` outputs are cumulative); `Uncached+CC / Doc` counts uncached input + cache writes (`input_tokens - cached_input_tokens` for Codex).",
        "",
        "## 1. Per-Model Accuracy, Grounding & Token Efficiency",
        "",
        "| Arm | Model | Docs | Parsed | Exact 4-Tuple | Genre+Status | Macro-F1 (Genre) | AC1 (Genre) | Grounding | d00–23→d24–47 | Wall/Doc | Uncached+CC / Doc | CacheRead / Doc | Out / Doc | Est $/10K |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in all_runs:
        tp = _summarize_tokens_per_doc(r["model"], r["persistent"], r["turn_records"], r["n_docs"])
        r["tokens_per_doc"] = tp
        usd_10k = f"${tp['est_10k_usd']:.2f}" if tp["est_10k_usd"] is not None else "n/a"
        md.append(
            f"| `{r['arm']}` | `{r['model']}` | {r['n_docs']} | {r['parsed_rate']:.1%} | "
            f"**{r['exact_tuple_acc']:.1%}** | {r['genre_status_acc']:.1%} | "
            f"{r['macro_f1_genre']:.3f} | {r['gwet_ac1_genre']:.3f} | {r['grounding_pass_rate']:.1%} | "
            f"{r['first_half_acc']:.1%}→{r['second_half_acc']:.1%} | {r['wall_s_per_doc']:.2f}s | "
            f"{tp['fresh_input']:.0f} | {tp['cache_read']:.0f} | {tp['output']:.0f} | {usd_10k} |"
        )

    md.extend([
        "",
        "## 2. Paired 2-Model Consensus (`opus_low` + `sol_low`) Accuracy vs 3-Family Gold",
        "",
        "| Arm | Exact 4-Tuple Agree | Agreed Exact Acc | Agreed Errors | Genre+Status Agree | Agreed Genre Acc | Disagreement Queue |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for arm_name, p in paired.items():
        md.append(
            f"| `{arm_name}` | {p['exact_agree_rate']:.1%} | **{p['agreed_exact_acc']:.1%}** | "
            f"{p['agreed_exact_errors']}/{p['n_docs']} | {p['genre_agree_rate']:.1%} | "
            f"{p['agreed_genre_acc']:.1%} | {p['disagreement_rate']:.1%} |"
        )

    md.extend(["", "## 3. Turn-by-Turn Deltas & Within-Batch Position Breakdown", ""])
    for r in all_runs:
        if r["batch_pos_acc"]:
            pos_str = ", ".join(f"{k}={v:.1%}" for k, v in r["batch_pos_acc"].items())
            md.append(f"- `{r['arm']}` (`{r['model']}`) batch position quartile exact acc: {pos_str}")
        if r["persistent"]:
            md.append(f"### Persistent `{r['arm']}` (`{r['model']}`) Turn-by-Turn (Per-Turn Deltas)")
            md.append("| Turn | Docs | OK | Wall (s) | Exact Acc | ΔUncached | ΔCacheRead | ΔCacheCreate | ΔOut | ΔUSD |")
            md.append("| ---: | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            prev = {"in": 0, "cr": 0, "cc": 0, "out": 0, "usd": 0.0}
            for tr in r["turn_records"]:
                u = tr.get("usage") or {}
                cur_in = int(u.get("input_tokens", 0) or 0)
                cur_cr = int(u.get("cache_read_tokens", 0) or 0)
                cur_cc = int(u.get("cache_create_tokens", 0) or 0)
                cur_out = int(u.get("output_tokens", 0) or 0)
                cur_usd = float(u["cost_usd"]) if u.get("cost_usd") is not None else None
                d_in = cur_in - prev["in"]
                d_cr = cur_cr - prev["cr"]
                d_cc = cur_cc - prev["cc"]
                d_out = cur_out - prev["out"]
                d_unc = max(0, d_in - d_cr) if r["model"].startswith("sol") else d_in
                d_usd = (cur_usd - prev["usd"]) if cur_usd is not None else None
                usd_s = f"${d_usd:.4f}" if d_usd is not None else "n/a"
                md.append(
                    f"| {tr['turn_idx'] + 1} | {tr['n_docs']} | {tr['ok']} | {tr['wall_s']:.1f} | "
                    f"{tr['exact_acc']:.1%} | {d_unc} | {d_cr} | {d_cc} | {d_out} | {usd_s} |"
                )
                prev = {
                    "in": cur_in,
                    "cr": cur_cr,
                    "cc": cur_cc,
                    "out": cur_out,
                    "usd": cur_usd if cur_usd is not None else prev["usd"],
                }
            md.append("")

    md.extend(["## 4. Sample Errors Across Arms (First 20 Mismatches)", ""])
    shown = 0
    for r in all_runs:
        for sc in r["doc_scores"]:
            if not sc["exact_match"]:
                md.append(
                    f"- `{r['arm']}` `{r['model']}` `{sc['doc_id']}` (`{sc['stratum']}`): "
                    f"gold=`{sc['gold_tuple']}` vs pred=`{sc['pred_tuple']}` grounding={sc['grounding_ok']}"
                )
                shown += 1
                if shown >= 20:
                    break
        if shown >= 20:
            break

    return "\n".join(md) + "\n"


def _compute_paired_consensus(
    opus_res: Mapping[str, Any],
    sol_res: Mapping[str, Any],
) -> dict[str, Any]:
    by_id_o = {s["doc_id"]: s for s in opus_res["doc_scores"]}
    by_id_s = {s["doc_id"]: s for s in sol_res["doc_scores"]}
    common = sorted(set(by_id_o.keys()) & set(by_id_s.keys()))
    n = len(common)
    if n == 0:
        return {}

    agree_exact = 0
    agree_exact_correct = 0
    agree_gs = 0
    agree_gs_correct = 0
    disagree_either_wrong = 0

    for did in common:
        so = by_id_o[did]
        ss = by_id_s[did]
        po = tuple(so["pred_tuple"]) if so["pred_tuple"] else None
        ps = tuple(ss["pred_tuple"]) if ss["pred_tuple"] else None
        gt = tuple(so["gold_tuple"])

        if po is not None and ps is not None and po == ps:
            agree_exact += 1
            if po == gt:
                agree_exact_correct += 1
        elif (not so["exact_match"]) or (not ss["exact_match"]):
            disagree_either_wrong += 1

        gs_o = _status_genre_label(po)
        gs_s = _status_genre_label(ps)
        gs_g = _status_genre_label(gt)
        if gs_o != "MISSING" and gs_o == gs_s:
            agree_gs += 1
            if gs_o == gs_g:
                agree_gs_correct += 1

    return {
        "n_docs": n,
        "exact_agree_rate": agree_exact / n,
        "agreed_exact_acc": agree_exact_correct / max(1, agree_exact),
        "agreed_exact_errors": agree_exact - agree_exact_correct,
        "genre_agree_rate": agree_gs / n,
        "agreed_genre_acc": agree_gs_correct / max(1, agree_gs),
        "disagreement_rate": (n - agree_exact) / n,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark doc batch size & session persistence on opus_low and sol_low.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--pilot-gold", type=Path, default=DEFAULT_PILOT_GOLD)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recompute-only", action="store_true")
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    if args.recompute_only:
        res_path = out_dir / "results.json"
        report_json = json.loads(res_path.read_text(encoding="utf-8"))
        report_md = _render_report_markdown(report_json)
        res_path.write_text(json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "report.md").write_text(report_md, encoding="utf-8")
        print(report_md)
        return 0
    empty_cwd = out_dir / "empty_cwd"
    empty_cwd.mkdir(parents=True, exist_ok=True)

    docs48 = load_stratified_gold_48(pilot_gold_path=args.pilot_gold, limit=48, seed=args.seed)
    docs24 = docs48[:24]
    sys_prompt, codebook_prefix = _build_stripped_system_prompt_and_template()

    strata_cnt = dict(Counter(d["stratum"] for d in docs48))
    print(f"Loaded 48 stratified pilot gold docs across {len(strata_cnt)} strata: {strata_cnt}", file=sys.stderr, flush=True)
    if args.dry_run:
        return 0

    arms: list[tuple[str, Sequence[Mapping[str, Any]], int, bool, int]] = [
        ("stateless_b1", docs48, 1, False, 8),
        ("stateless_b8", docs48, 8, False, 6),
        ("stateless_b16", docs48, 16, False, 3),
        ("stateless_b24", docs48, 24, False, 2),
        ("session_48_by_8", docs48, 8, True, 1),
        ("session_24_by_1", docs24, 1, True, 1),
    ]

    def _run_all_for_model(model_name: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for arm_name, arm_docs, chunk_sz, persist, conc in arms:
            res = _run_model_arm(
                model_name=model_name,
                arm_name=arm_name,
                docs=arm_docs,
                chunk_size=chunk_sz,
                persistent=persist,
                concurrency=conc,
                system_prompt=sys_prompt,
                codebook_prefix=codebook_prefix,
                empty_cwd=empty_cwd,
            )
            out.append(res)
        return out

    # Run opus_low and sol_low in parallel!
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_opus = pool.submit(_run_all_for_model, "opus_low")
        f_sol = pool.submit(_run_all_for_model, "sol_low")
        opus_runs = f_opus.result()
        sol_runs = f_sol.result()

    all_runs = opus_runs + sol_runs
    opus_by_arm = {r["arm"]: r for r in opus_runs}
    sol_by_arm = {r["arm"]: r for r in sol_runs}
    paired = {arm_name: _compute_paired_consensus(opus_by_arm[arm_name], sol_by_arm[arm_name]) for arm_name, *_ in arms}

    report_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_docs_pool": len(docs48),
        "strata_counts": strata_cnt,
        "runs": all_runs,
        "paired_consensus": paired,
    }
    report_md = _render_report_markdown(report_json)
    (out_dir / "results.json").write_text(json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")
    print(report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
