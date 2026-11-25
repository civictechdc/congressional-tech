#!/usr/bin/env python3
"""Head-to-head speed & accuracy benchmark on the 32 hardest verified DocMeta V7 files.

Compares 26 model x effort configurations across:
  * Claude CLI (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` at `low` / `medium`)
  * Codex CLI (`gpt-6.2-sol`, `gpt-6.2-astra`, `gpt-6.1-terra` at `low` / `medium`, default tier)
  * Antigravity `agy` stripped CLI (`gemini-4-neon` low/medium/high, `gemini-3.8-flash` low/medium, `gemini-4-carbon-medium`)
  * OpenCode Z.AI Coding Plan (`zai-coding-plan/glm-5.4` low/high, `glm-5.3-flash`)
  * OpenCode Go (`glm-5.3` low/high, `deepseek-v4-pro`, `kimi-k3.1-pro`, `qwen4-max`, `minimax-m3`)

Sample: 32 stratified `checkeval_resolved` documents from 3-family medium shards `0000..0017`
where frontier models disagreed on `status`, `media_format`, `is_packet`, or `primary_genre`.

Usage:
    .venv/bin/python scripts/measure/docmeta_v7_hard_model_bench.py --models claude_haiku_5_5_low,zai_glm53_flash
    .venv/bin/python scripts/measure/docmeta_v7_hard_model_bench.py --resume
    .venv/bin/python scripts/measure/docmeta_v7_hard_model_bench.py --recompute-only
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from congress_docmeta.v7.factory.bulk_review import (
    _format_audit_batch_prompt,
    _load_candidates_text_map,
    _pack_char_bounded_chunks,
    build_audit_system_prompt,
)
from congress_docmeta.v7.factory.corpus_builder import (
    _format_core_batch_prompt,
    build_batch_schema,
    split_core_codebook_prefix,
)
from congress_docmeta.v7.factory.grounding import (
    extract_triage_tuple,
    verify_span_grounding,
)
from congress_docmeta.v7.factory.pilot import (
    _parse_and_validate,
    _resolve_v7_runtime_specs,
)
from congress_docmeta.v7.factory.runners import (
    AdapterOutput,
    UsageGuard,
    extract_json_payload,
    invoke_agy_stripped_cli,
    invoke_claude_cli,
    invoke_codex_cli,
)

DEFAULT_CORPUS_DIR = Path(".cache/archive-release/docmeta-v7-corpus")
DEFAULT_OUT_DIR = Path(".cache/archive-release/docmeta-v7-hard-bench-20261123")
SEED = 20261123


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str  # "claude" | "codex" | "agy" | "opencode"
    subscription: str
    model_id: str
    effort: str
    batch_size: int = 16


MODEL_MATRIX: tuple[ModelSpec, ...] = (
    # Claude CLI
    ModelSpec("claude_opus_5_5_low", "claude", "claude", "claude-opus-5-5", "low"),
    ModelSpec("claude_opus_5_5_med", "claude", "claude", "claude-opus-5-5", "medium"),
    ModelSpec("claude_sonnet_5_5_low", "claude", "claude", "claude-sonnet-5-5", "low"),
    ModelSpec("claude_sonnet_5_5_med", "claude", "claude", "claude-sonnet-5-5", "medium"),
    ModelSpec("claude_haiku_5_5_low", "claude", "claude", "claude-haiku-5-5", "low"),
    ModelSpec("claude_haiku_5_5_med", "claude", "claude", "claude-haiku-5-5", "medium"),
    # Codex CLI
    ModelSpec("codex_gpt62_sol_low", "codex", "codex", "gpt-6.2-sol", "low"),
    ModelSpec("codex_gpt62_sol_med", "codex", "codex", "gpt-6.2-sol", "medium"),
    ModelSpec("codex_gpt62_astra_low", "codex", "codex", "gpt-6.2-astra", "low"),
    ModelSpec("codex_gpt62_astra_med", "codex", "codex", "gpt-6.2-astra", "medium"),
    ModelSpec("codex_gpt61_terra_low", "codex", "codex", "gpt-6.1-terra", "low"),
    # Antigravity agy stripped CLI (Gemini)
    ModelSpec("agy_neon_low", "agy", "agy_gemini", "gemini-4-neon-low", "low", batch_size=12),
    ModelSpec("agy_neon_med", "agy", "agy_gemini", "gemini-4-neon-medium", "medium", batch_size=12),
    ModelSpec("agy_neon_high", "agy", "agy_gemini", "gemini-4-neon-high", "high", batch_size=12),
    ModelSpec("agy_flash38_low", "agy", "agy_gemini", "gemini-3.8-flash-low", "low", batch_size=12),
    ModelSpec("agy_flash38_med", "agy", "agy_gemini", "gemini-3.8-flash-medium", "medium", batch_size=12),
    ModelSpec("agy_carbon_med", "agy", "agy_gemini", "gemini-4-carbon-medium", "medium", batch_size=12),
    ModelSpec("agy_hydrogen_low", "agy", "agy_gemini", "gemini-4-hydrogen-low", "low", batch_size=12),
    ModelSpec("agy_hydrogen_med", "agy", "agy_gemini", "gemini-4-hydrogen-medium", "medium", batch_size=12),
    ModelSpec("agy_hydrogen_high", "agy", "agy_gemini", "gemini-4-hydrogen-high", "high", batch_size=12),
    # OpenCode Z.AI Coding Plan
    ModelSpec("zai_glm54_low", "opencode", "z.ai", "zai-coding-plan/glm-5.4#low", "low", batch_size=8),
    ModelSpec("zai_glm54_high", "opencode", "z.ai", "zai-coding-plan/glm-5.4#high", "high", batch_size=8),
    ModelSpec("zai_glm53_flash", "opencode", "z.ai", "zai-coding-plan/glm-5.3-flash", "default", batch_size=8),
    # OpenCode Go
    ModelSpec("ocgo_glm53_low", "opencode", "opencode-go", "opencode-go/glm-5.3#low", "low", batch_size=8),
    ModelSpec("ocgo_glm53_high", "opencode", "opencode-go", "opencode-go/glm-5.3#high", "high", batch_size=8),
    ModelSpec("ocgo_deepseek_v4_pro", "opencode", "opencode-go", "opencode-go/deepseek-v4-pro", "default", batch_size=8),
    ModelSpec("ocgo_kimi_k31_pro", "opencode", "opencode-go", "opencode-go/kimi-k3.1-pro", "default", batch_size=8),
    ModelSpec("ocgo_qwen4_max", "opencode", "opencode-go", "opencode-go/qwen4-max", "default", batch_size=8),
    ModelSpec("ocgo_minimax_m3", "opencode", "opencode-go", "opencode-go/minimax-m3", "default", batch_size=8),
)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def build_or_load_hard_32(
    *,
    corpus_dir: Path,
    out_dir: Path,
    seed: int = SEED,
) -> list[dict[str, Any]]:
    """Build (or reuse frozen) 32 stratified hardest `checkeval_resolved` docs from shards 0000..0017."""
    hard_path = out_dir / "hard_32.jsonl"
    if hard_path.is_file():
        existing = []
        with hard_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    existing.append(json.loads(line))
        if len(existing) == 32:
            return existing

    text_by_key = _load_candidates_text_map(corpus_dir / "candidates_v7_3.jsonl")
    shards_dir = corpus_dir / "shards"
    pool: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_shas: set[str] = set()

    for idx in range(18):
        sp = shards_dir / f"shard_{idx:04d}.jsonl"
        if not sp.is_file():
            continue
        with sp.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("verdict") != "checkeval_resolved":
                    continue
                gold = row.get("gold")
                if not isinstance(gold, dict):
                    continue
                dk = str(row.get("doc_key") or "")
                tsha = str(row.get("text_sha256") or "")
                txt = text_by_key.get(dk, "")
                if not dk or not txt or dk in seen_keys or (tsha and tsha in seen_shas):
                    continue
                seen_keys.add(dk)
                if tsha:
                    seen_shas.add(tsha)
                gt = extract_triage_tuple(gold)
                if gt is None:
                    continue
                pool.append(
                    {
                        "shard_idx": idx,
                        "doc_key": dk,
                        "text_sha256": tsha,
                        "filename": row.get("filename"),
                        "stratum": row.get("stratum"),
                        "source_pool": row.get("source_pool"),
                        "consensus_families": row.get("consensus_families") or [],
                        "gold_tuple": list(gt),
                        "gold": gold,
                        "text": txt,
                    }
                )

    rng = random.Random(seed)
    rng.shuffle(pool)

    picked: list[dict[str, Any]] = []
    picked_keys: set[str] = set()

    def _take(cands: Sequence[dict[str, Any]], quota: int, bucket_name: str) -> None:
        taken = 0
        for r in cands:
            if taken >= quota:
                break
            if r["doc_key"] in picked_keys:
                continue
            picked_keys.add(r["doc_key"])
            picked.append({**r, "hard_bucket": bucket_name})
            taken += 1

    packets = [
        r
        for r in pool
        if bool(r["gold"].get("is_packet")) or str(r.get("stratum") or "").startswith("packet:")
    ]
    _take(packets, 6, "packet")

    non_prose = [
        r
        for r in pool
        if r["doc_key"] not in picked_keys
        and r["gold"].get("status") == "usable"
        and r["gold"].get("media_format") in {"table_or_form", "web_page", "slides"}
    ]
    _take(non_prose, 6, "non_prose_media")

    non_usable = [
        r
        for r in pool
        if r["doc_key"] not in picked_keys and r["gold"].get("status") != "usable"
    ]
    _take(non_usable, 5, "non_usable")

    # 15 hard prose genre boundaries spread round-robin across primary_genre.
    by_genre: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in pool:
        if r["doc_key"] in picked_keys:
            continue
        if r["gold"].get("status") == "usable" and r["gold"].get("media_format") == "prose":
            by_genre[str(r["gold"].get("primary_genre") or "unknown")].append(r)

    genre_keys = sorted(by_genre.keys())
    rng.shuffle(genre_keys)
    while len(picked) < 32 and any(by_genre.values()):
        progressed = False
        for gk in genre_keys:
            if len(picked) >= 32:
                break
            lst = by_genre[gk]
            while lst and lst[0]["doc_key"] in picked_keys:
                lst.pop(0)
            if lst:
                r = lst.pop(0)
                picked_keys.add(r["doc_key"])
                picked.append({**r, "hard_bucket": "hard_prose"})
                progressed = True
        if not progressed:
            break

    # Backfill if any bucket came up short.
    for r in pool:
        if len(picked) >= 32:
            break
        if r["doc_key"] not in picked_keys:
            picked_keys.add(r["doc_key"])
            picked.append({**r, "hard_bucket": "backfill"})

    out_dir.mkdir(parents=True, exist_ok=True)
    with hard_path.open("w", encoding="utf-8") as fh:
        for idx, rec in enumerate(picked[:32]):
            fh.write(json.dumps({"bench_idx": idx, **rec}, ensure_ascii=False) + "\n")
    return picked[:32]


def _invoke_opencode_cli(
    prompt: str,
    *,
    model_id: str,
    timeout_s: float,
    empty_cwd: Path,
) -> tuple[AdapterOutput, dict[str, Any]]:
    t0 = time.perf_counter()
    cmd = [
        "opencode",
        "run",
        "--archived",
        "--format",
        "json",
        "-m",
        model_id,
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=empty_cwd,
            stdin=subprocess.DEVNULL,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
    except subprocess.TimeoutExpired:
        return (
            AdapterOutput(
                raw_text="",
                extracted_json_str=None,
                returncode=-1,
                error=f"timeout after {timeout_s:.1f}s",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            ),
            {},
        )
    except OSError as exc:
        return (
            AdapterOutput(
                raw_text="",
                extracted_json_str=None,
                returncode=-1,
                error=f"os_error: {exc}",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            ),
            {},
        )

    text_parts: list[str] = []
    err_msgs: list[str] = []
    toks = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    cost_usd = 0.0

    for line in proc.stdout.splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "text" and isinstance(ev.get("part"), dict):
            txt = ev["part"].get("text")
            if isinstance(txt, str) and txt:
                text_parts.append(txt)
        elif etype == "step_finish" and isinstance(ev.get("part"), dict):
            part = ev["part"]
            c = part.get("cost")
            if isinstance(c, (int, float)):
                cost_usd += float(c)
            t = part.get("tokens")
            if isinstance(t, dict):
                toks["input"] += int(t.get("input", 0) or 0)
                toks["output"] += int(t.get("output", 0) or 0)
                toks["reasoning"] += int(t.get("reasoning", 0) or 0)
                cache_d = t.get("cache")
                if isinstance(cache_d, dict):
                    toks["cache_read"] += int(cache_d.get("read", 0) or 0)
                    toks["cache_write"] += int(cache_d.get("write", 0) or 0)
        elif etype == "error":
            err_obj = ev.get("error")
            if isinstance(err_obj, dict):
                err_msgs.append(str(err_obj.get("message") or err_obj))
            elif err_obj:
                err_msgs.append(str(err_obj))

    combined_text = "\n".join(text_parts).strip()
    err = "; ".join(err_msgs) if err_msgs else (proc.stderr.strip() or None if proc.returncode != 0 else None)
    rc = proc.returncode if not err_msgs else (proc.returncode or 1)
    extracted: str | None = None
    if rc == 0 and combined_text:
        try:
            extracted, _ = extract_json_payload(combined_text, provider="opencode")
        except ValueError as exc:
            err = str(exc)
    elif rc == 0 and not combined_text:
        err = "opencode emitted empty text"

    meta = {
        "input_tokens": toks["input"],
        "output_tokens": toks["output"],
        "thinking_tokens": toks["reasoning"],
        "cache_read_tokens": toks["cache_read"],
        "cache_write_tokens": toks["cache_write"],
        "cost_usd": cost_usd,
    }
    return (
        AdapterOutput(
            raw_text=combined_text or proc.stdout,
            extracted_json_str=extracted,
            returncode=rc,
            error=err,
            latency_ms=latency_ms,
            cost_usd=cost_usd if cost_usd > 0 else None,
        ),
        meta,
    )


def _extract_claude_and_agy_usage(provider: str, out: AdapterOutput) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": out.cost_usd or 0.0,
        "usage_pct": out.usage_pct,
        "num_turns": None,
    }
    if not out.raw_text:
        return meta
    try:
        env = json.loads(out.raw_text)
    except Exception:
        return meta
    if not isinstance(env, dict):
        return meta
    u = env.get("usage")
    if isinstance(u, dict):
        meta["input_tokens"] = int(u.get("input_tokens", 0) or 0)
        meta["output_tokens"] = int(u.get("output_tokens", 0) or 0)
        if provider == "claude":
            meta["cache_read_tokens"] = int(u.get("cache_read_input_tokens", 0) or 0)
            meta["cache_write_tokens"] = int(u.get("cache_creation_input_tokens", 0) or 0)
            det = u.get("output_tokens_details")
            if isinstance(det, dict):
                meta["thinking_tokens"] = int(det.get("thinking_tokens", 0) or 0)
        elif provider == "agy":
            meta["thinking_tokens"] = int(u.get("thinking_tokens", 0) or 0)
            meta["cache_read_tokens"] = int(u.get("cache_read_tokens", 0) or 0)
    if "num_turns" in env:
        meta["num_turns"] = env.get("num_turns")
    return meta


def _run_one_model(
    spec: ModelSpec,
    *,
    docs: Sequence[Mapping[str, Any]],
    empty_cwd: Path,
    core_schema: dict[str, Any],
    core_batch_schema: dict[str, Any],
    core_cls: Any,
    claude_sys_prompt: str,
    codex_prefix: str,
    audit_sys_prompt: str,
    timeout_s: float,
    usage_guards: Mapping[str, UsageGuard],
) -> dict[str, Any]:
    """Run all 32 docs in `B=16` char-bounded batches (no single-doc fallback) for one ModelSpec."""
    guard = usage_guards.get(spec.provider)
    if guard is not None and guard.should_stop():
        return {
            **asdict(spec),
            "skipped_reason": guard.triggered_reason,
            "wall_s": 0.0,
            "batches": [],
            "predictions": {},
            "metrics": {},
        }

    max_chars = 65_000 if spec.provider == "opencode" else 110_000
    chunks = _pack_char_bounded_chunks(
        list(docs),
        max_items=spec.batch_size,
        max_chars=max_chars,
        len_fn=lambda r: len(str(r["text"])) + 120,
    )

    t_start = time.perf_counter()
    predictions: dict[str, dict[str, Any]] = {}
    batch_logs: list[dict[str, Any]] = []
    schema_valid_keys: set[str] = set()
    grounded_keys: set[str] = set()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "usage_pct": None,
        "num_turns_max": 0,
    }

    consec_fail = 0
    stopped_early: str | None = None
    eff_timeout = min(timeout_s, 180.0) if spec.provider == "opencode" else timeout_s

    for c_idx, chunk in enumerate(chunks):
        if guard is not None and guard.should_stop():
            batch_logs.append({"chunk": c_idx + 1, "skipped": guard.triggered_reason})
            break

        batch_items = [(f"d{i:02d}", row) for i, row in enumerate(chunk)]
        batch_texts = [(did, str(row["text"])) for did, row in batch_items]

        if spec.provider == "claude":
            prompt = _format_core_batch_prompt(batch_items)
            out = invoke_claude_cli(
                prompt,
                core_batch_schema,
                model_id=spec.model_id,
                effort=spec.effort,
                timeout_s=eff_timeout,
                cwd=empty_cwd,
                system_prompt=claude_sys_prompt,
                stripped_prefix=True,
                stream_json=True,
            )
            b_meta = _extract_claude_and_agy_usage("claude", out)
        elif spec.provider == "codex":
            prompt = f"{codex_prefix}\n\n{_format_core_batch_prompt(batch_items)}"
            out = invoke_codex_cli(
                prompt,
                core_batch_schema,
                model_id=spec.model_id,
                reasoning_effort=spec.effort,
                timeout_s=eff_timeout,
                cwd=empty_cwd,
                stripped_prefix=True,
                json_events=True,
                ephemeral=False,
            )
            b_meta = {
                "input_tokens": 0,
                "output_tokens": 0,
                "thinking_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_usd": 0.0,
                "usage_pct": out.usage_pct,
                "num_turns": None,
            }
        elif spec.provider == "agy":
            prompt = _format_audit_batch_prompt(batch_texts)
            out = invoke_agy_stripped_cli(
                prompt,
                system_prompt=audit_sys_prompt,
                model_id=spec.model_id,
                timeout_s=eff_timeout,
            )
            b_meta = _extract_claude_and_agy_usage("agy", out)
        elif spec.provider == "opencode":
            prompt = f"{audit_sys_prompt}\n\n{_format_audit_batch_prompt(batch_texts)}"
            out, b_meta = _invoke_opencode_cli(
                prompt,
                model_id=spec.model_id,
                timeout_s=eff_timeout,
                empty_cwd=empty_cwd,
            )
        else:
            raise ValueError(f"Unknown provider: {spec.provider}")

        if guard is not None:
            guard.record(
                spec.provider,
                out.usage_pct,
                out.rate_limit_info,
                out.error,
                returncode=out.returncode,
            )

        for k in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "cache_write_tokens"):
            usage_totals[k] += int(b_meta.get(k, 0) or 0)
        usage_totals["cost_usd"] += float(b_meta.get("cost_usd", 0.0) or 0.0)
        if b_meta.get("usage_pct") is not None:
            usage_totals["usage_pct"] = b_meta["usage_pct"]
        if isinstance(b_meta.get("num_turns"), int):
            usage_totals["num_turns_max"] = max(usage_totals["num_turns_max"], b_meta["num_turns"])

        raw_items: list[Any] = []
        if out.returncode == 0 and out.error is None:
            payload_txt = out.extracted_json_str or out.raw_text
            try:
                _, payload = extract_json_payload(payload_txt, provider=spec.provider)
                if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                    raw_items = payload["items"]
            except ValueError:
                raw_items = []

        by_id: dict[str, dict[str, Any]] = {}
        for entry in raw_items:
            if isinstance(entry, Mapping) and entry.get("doc_id"):
                by_id[str(entry["doc_id"]).strip()] = dict(entry)

        c_valid = 0
        c_grounded = 0
        for idx, (did, row) in enumerate(batch_items):
            dk = str(row["doc_key"])
            txt = str(row["text"])
            cand = by_id.get(did)
            if cand is None and len(raw_items) == len(batch_items) and isinstance(raw_items[idx], Mapping):
                cand = dict(raw_items[idx])
            if cand is None:
                continue
            cleaned = {k: v for k, v in cand.items() if k != "doc_id"}
            try:
                parsed = _parse_and_validate(json.dumps(cleaned, ensure_ascii=False), txt, model_cls=core_cls)
            except Exception as exc:
                predictions[dk] = {"schema_valid": False, "grounded": False, "error": str(exc)[:140], "tuple": None}
                continue
            c_valid += 1
            schema_valid_keys.add(dk)
            gr = verify_span_grounding(txt, parsed)
            tup = extract_triage_tuple(parsed)
            if gr.passed:
                c_grounded += 1
                grounded_keys.add(dk)
            predictions[dk] = {
                "schema_valid": True,
                "grounded": gr.passed,
                "grounding_issues": gr.to_dict()["errors"][:4],
                "tuple": list(tup) if tup is not None else None,
                "rationale": str(parsed.get("rationale") or "")[:220],
                "verbatim_title": parsed.get("verbatim_title"),
            }

        batch_logs.append(
            {
                "chunk": c_idx + 1,
                "size": len(chunk),
                "rc": out.returncode,
                "lat_s": round(out.latency_ms / 1000.0, 2),
                "schema_valid": c_valid,
                "grounded": c_grounded,
                "usage_pct": b_meta.get("usage_pct"),
                "error": str(out.error)[:160] if out.error else None,
            }
        )
        print(
            f"[hard-bench] {spec.name:22s} chunk={c_idx + 1}/{len(chunks)} "
            f"grounded={c_grounded}/{len(chunk)} valid={c_valid}/{len(chunk)} "
            f"rc={out.returncode} lat={out.latency_ms / 1000.0:.1f}s usage_pct={b_meta.get('usage_pct')}"
            + (f" err={str(out.error)[:100]}" if out.error else ""),
            file=sys.stderr,
            flush=True,
        )
        if out.returncode != 0 and c_grounded == 0:
            consec_fail += 1
            if consec_fail >= 2:
                stopped_early = f"aborted after {consec_fail} consecutive failed chunks"
                print(
                    f"[hard-bench] {spec.name:22s} {stopped_early}",
                    file=sys.stderr,
                    flush=True,
                )
                break
        else:
            consec_fail = 0

    wall_s = time.perf_counter() - t_start
    return {
        **asdict(spec),
        "skipped_reason": None,
        "stopped_early": stopped_early,
        "wall_s": round(wall_s, 2),
        "sec_per_doc": round(wall_s / max(1, len(docs)), 2),
        "schema_valid_count": len(schema_valid_keys),
        "grounded_count": len(grounded_keys),
        "batches": batch_logs,
        "usage_totals": usage_totals,
        "predictions": predictions,
        "metrics": {},
    }


def recompute_scores_and_report(
    *,
    docs: Sequence[Mapping[str, Any]],
    runs: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    """Compute reference accuracy, cross-model consensus alignment, and render Markdown report."""
    n_total = len(docs)
    usable_keys = {str(d["doc_key"]) for d in docs if tuple(d["gold_tuple"])[0] == "usable"}

    # Step 1: Identify qualifying models (>= 75% grounded) for cross-model consensus tuple.
    qualifying = [
        r for r in runs.values() if not r.get("skipped_reason") and int(r.get("grounded_count", 0)) >= int(0.75 * n_total)
    ]
    consensus_by_key: dict[str, dict[str, Any]] = {}
    ref_disagreement_docs: list[dict[str, Any]] = []

    for d in docs:
        dk = str(d["doc_key"])
        gt = tuple(d["gold_tuple"])
        votes: Counter[tuple[Any, Any, Any, Any]] = Counter()
        for r in qualifying:
            pred = (r.get("predictions") or {}).get(dk)
            if pred and pred.get("grounded") and pred.get("tuple"):
                votes[tuple(pred["tuple"])] += 1
        total_v = sum(votes.values())
        maj_tup, maj_cnt = votes.most_common(1)[0] if votes else (None, 0)
        consensus_by_key[dk] = {
            "majority_tuple": list(maj_tup) if maj_tup is not None else None,
            "majority_frac": round(maj_cnt / total_v, 3) if total_v else 0.0,
            "n_voters": total_v,
        }
        if maj_tup is not None and total_v >= 4 and maj_tup != gt and (maj_cnt / total_v) >= 0.75:
            ref_disagreement_docs.append(
                {
                    "doc_key": dk,
                    "filename": d.get("filename"),
                    "bucket": d.get("hard_bucket"),
                    "gold_tuple": list(gt),
                    "majority_tuple": list(maj_tup),
                    "majority_votes": f"{maj_cnt}/{total_v}",
                }
            )

    # Step 2: Score every model run cleanly.
    scored_rows: list[dict[str, Any]] = []
    for spec in MODEL_MATRIX:
        r = runs.get(spec.name)
        if not r:
            continue
        preds = r.get("predictions") or {}
        grounded_n = 0
        exact_n = 0
        sg_n = 0
        st_n = 0
        mf_n = 0
        pkt_n = 0
        cons_n = 0
        by_bucket: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [exact, total]

        for d in docs:
            dk = str(d["doc_key"])
            gt = tuple(d["gold_tuple"])
            bkt = str(d.get("hard_bucket") or "other")
            by_bucket[bkt][1] += 1
            pred = preds.get(dk)
            if not pred or not pred.get("grounded") or not pred.get("tuple"):
                continue
            grounded_n += 1
            pt = tuple(pred["tuple"])
            if pt == gt:
                exact_n += 1
                by_bucket[bkt][0] += 1
            if (pt[0], pt[3]) == (gt[0], gt[3]):
                sg_n += 1
            if pt[0] == gt[0]:
                st_n += 1
            if dk in usable_keys and pt[1] == gt[1]:
                mf_n += 1
            if pt[2] == gt[2]:
                pkt_n += 1
            ct = consensus_by_key.get(dk, {}).get("majority_tuple")
            if ct is not None and pt == tuple(ct):
                cons_n += 1

        metrics = {
            "exact_4tuple_pct": round(100.0 * exact_n / max(1, n_total), 1),
            "exact_on_grounded_pct": round(100.0 * exact_n / max(1, grounded_n), 1) if grounded_n else 0.0,
            "consensus_4tuple_pct": round(100.0 * cons_n / max(1, n_total), 1),
            "status_genre_pct": round(100.0 * sg_n / max(1, n_total), 1),
            "status_pct": round(100.0 * st_n / max(1, n_total), 1),
            "media_format_pct": round(100.0 * mf_n / max(1, len(usable_keys)), 1),
            "packet_pct": round(100.0 * pkt_n / max(1, n_total), 1),
            "grounded_pct": round(100.0 * grounded_n / max(1, n_total), 1),
            "bucket_exact": {b: f"{v[0]}/{v[1]}" for b, v in sorted(by_bucket.items())},
        }
        r["metrics"] = metrics
        scored_rows.append(r)

    scored_rows.sort(
        key=lambda x: (
            -float(x["metrics"].get("exact_4tuple_pct", 0.0)),
            -float(x["metrics"].get("consensus_4tuple_pct", 0.0)),
            float(x.get("wall_s", 9999.0)),
        )
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": n_total,
        "usable_docs": len(usable_keys),
        "bucket_counts": dict(Counter(str(d.get("hard_bucket") or "") for d in docs)),
        "qualifying_consensus_models": len(qualifying),
        "reference_disagreement_docs": ref_disagreement_docs,
        "consensus_by_doc": consensus_by_key,
        "leaderboard": [
            {
                "name": r["name"],
                "subscription": r["subscription"],
                "provider": r["provider"],
                "model_id": r["model_id"],
                "effort": r["effort"],
                "wall_s": r.get("wall_s"),
                "sec_per_doc": r.get("sec_per_doc"),
                "grounded": f"{r.get('grounded_count', 0)}/{n_total}",
                "schema_valid": f"{r.get('schema_valid_count', 0)}/{n_total}",
                "usage": r.get("usage_totals"),
                "metrics": r.get("metrics"),
                "skipped_reason": r.get("skipped_reason"),
            }
            for r in scored_rows
        ],
        "runs": runs,
    }
    _atomic_write_text(out_dir / "results.json", json.dumps(payload, indent=2, ensure_ascii=False))

    # Render Markdown Report
    md = [
        "# DocMeta V7 Hardest-32 Head-to-Head Model & Effort Benchmark",
        "",
        f"- **Generated:** `{payload['generated_at']}`",
        f"- **Dataset:** `hard_32.jsonl` (`32` stratified `checkeval_resolved` disagreements from 3-family medium shards `0000..0017`, seed `{SEED}`)",
        f"- **Buckets:** `{payload['bucket_counts']}`",
        f"- **Mode:** Stripped stateless `B=16` chunks (no single-doc fallback; no `--json-schema` for `agy`/`opencode`; strict Pydantic + `verify_span_grounding`)",
        f"- **Qualifying Cross-Model Consensus Pool (`>=75%` grounded):** `{len(qualifying)}` models | **Docs where `>=75%` of top models disagree with CheckEval reference:** `{len(ref_disagreement_docs)}`",
        "",
        "## Leaderboard (Ranked by Exact 4-Tuple Accuracy -> Cross-Model Consensus -> Speed)",
        "",
        "| Rank | Config | Sub | Model | Effort | Wall (s) | s/doc | Grounded | Ref Exact | Ref S+G | Consensus | Media% | Packet% | Usage% | Cost |",
        "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rk, row in enumerate(payload["leaderboard"], start=1):
        m = row["metrics"] or {}
        u = row["usage"] or {}
        upct = f"{u['usage_pct']}%" if u.get("usage_pct") is not None else "-"
        cost = f"${u.get('cost_usd', 0.0):.3f}" if u.get("cost_usd") else "-"
        md.append(
            f"| {rk} | `{row['name']}` | `{row['subscription']}` | `{row['model_id']}` | `{row['effort']}` | "
            f"{row.get('wall_s', '-')} | {row.get('sec_per_doc', '-')} | {row['grounded']} | "
            f"**{m.get('exact_4tuple_pct', 0.0)}%** | {m.get('status_genre_pct', 0.0)}% | "
            f"{m.get('consensus_4tuple_pct', 0.0)}% | {m.get('media_format_pct', 0.0)}% | {m.get('packet_pct', 0.0)}% | "
            f"{upct} | {cost} |"
        )

    # Effort scaling section
    pairs = [
        ("Claude Opus 5.5", "claude_opus_5_5_low", "claude_opus_5_5_med"),
        ("Claude Sonnet 5.5", "claude_sonnet_5_5_low", "claude_sonnet_5_5_med"),
        ("Claude Haiku 5.5", "claude_haiku_5_5_low", "claude_haiku_5_5_med"),
        ("Codex GPT-6.2 Sol", "codex_gpt62_sol_low", "codex_gpt62_sol_med"),
        ("Codex GPT-6.2 Astra", "codex_gpt62_astra_low", "codex_gpt62_astra_med"),
        ("Gemini 4 Neon (agy)", "agy_neon_low", "agy_neon_med", "agy_neon_high"),
        ("Gemini 4 Hydrogen (agy)", "agy_hydrogen_low", "agy_hydrogen_med", "agy_hydrogen_high"),
        ("Gemini 3.8 Flash (agy)", "agy_flash38_low", "agy_flash38_med"),
        ("Z.AI GLM-5.4", "zai_glm54_low", "zai_glm54_high"),
        ("OpenCode Go GLM-5.3", "ocgo_glm53_low", "ocgo_glm53_high"),
    ]
    md.extend(
        [
            "",
            "## Effort Scaling Comparison",
            "",
            "| Family | Lower -> Higher Effort | Exact 4-Tuple Delta | Consensus Delta | Wall Time Delta |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
    )
    for fam_pair in pairs:
        fname = fam_pair[0]
        present = [runs[k] for k in fam_pair[1:] if k in runs and not runs[k].get("skipped_reason")]
        if len(present) >= 2:
            a, b = present[0], present[-1]
            ex_a = a["metrics"].get("exact_4tuple_pct", 0.0)
            ex_b = b["metrics"].get("exact_4tuple_pct", 0.0)
            cs_a = a["metrics"].get("consensus_4tuple_pct", 0.0)
            cs_b = b["metrics"].get("consensus_4tuple_pct", 0.0)
            w_a, w_b = float(a.get("wall_s", 0.0)), float(b.get("wall_s", 0.0))
            md.append(
                f"| {fname} | `{a['effort']}` -> `{b['effort']}` | "
                f"{ex_a}% -> {ex_b}% ({ex_b - ex_a:+.1f}pp) | "
                f"{cs_a}% -> {cs_b}% ({cs_b - cs_a:+.1f}pp) | "
                f"{w_a:.1f}s -> {w_b:.1f}s ({w_b / max(0.1, w_a):.2f}x) |"
            )

    if ref_disagreement_docs:
        md.extend(
            [
                "",
                "## Docs Where >=75% of Qualifying Models Disagree With CheckEval Reference",
                "",
                "| Doc Key | Bucket | Filename | CheckEval Ref | Model Majority (Votes) |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for item in ref_disagreement_docs:
            md.append(
                f"| `{item['doc_key'][:12]}` | `{item['bucket']}` | `{str(item.get('filename'))[:36]}` | `{item['gold_tuple']}` | `{item['majority_tuple']}` ({item['majority_votes']}) |"
            )

    _atomic_write_text(out_dir / "report.md", "\n".join(md) + "\n")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hardest-32 head-to-head model & effort benchmark")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--models", type=str, default=None, help="Comma-separated ModelSpec names to run")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--recompute-only", action="store_true")
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    corpus_dir = args.corpus_dir.resolve()
    docs = build_or_load_hard_32(corpus_dir=corpus_dir, out_dir=out_dir)

    results_path = out_dir / "results.json"
    runs: dict[str, dict[str, Any]] = {}
    if (args.resume or args.recompute_only) and results_path.is_file():
        loaded = json.loads(results_path.read_text(encoding="utf-8"))
        if isinstance(loaded.get("runs"), dict):
            runs = loaded["runs"]

    if args.recompute_only:
        summary = recompute_scores_and_report(docs=docs, runs=runs, out_dir=out_dir)
        print(json.dumps(summary["leaderboard"], indent=2))
        return 0

    selected = MODEL_MATRIX
    if args.models:
        wanted = {m.strip() for m in args.models.split(",") if m.strip()}
        selected = tuple(s for s in MODEL_MATRIX if s.name in wanted)
        if not selected:
            raise ValueError(f"No matching models in {wanted}")

    todo = [
        s
        for s in selected
        if not (
            args.resume
            and s.name in runs
            and not runs[s.name].get("skipped_reason")
            and (int(runs[s.name].get("grounded_count", 0)) > 0 or runs[s.name].get("stopped_early"))
        )
    ]

    _cb_ver, core_schema, _spec_schemas, core_cls, _spec_clses = _resolve_v7_runtime_specs(None)
    core_batch_schema = build_batch_schema(core_schema, "DocMetaCoreTriageBatch")
    claude_sys_prompt, codex_prefix = split_core_codebook_prefix()
    audit_sys_prompt = build_audit_system_prompt(core_schema)

    empty_cwd = Path(tempfile.gettempdir()) / "docmeta_v7_empty_cwd"
    empty_cwd.mkdir(parents=True, exist_ok=True)

    usage_guards = {
        "claude": UsageGuard(max_usage_pct=50.0, require_telemetry=True),
        "codex": UsageGuard(max_usage_pct=50.0, require_telemetry=True),
    }
    runs_lock = threading.Lock()

    by_provider: dict[str, list[ModelSpec]] = defaultdict(list)
    for s in todo:
        by_provider[s.provider].append(s)

    provider_workers = {"claude": 2, "codex": 2, "agy": 2, "opencode": 4}

    def _run_provider_lane(prov: str, specs: Sequence[ModelSpec]) -> None:
        max_w = max(1, min(provider_workers.get(prov, 2), len(specs)))
        with ThreadPoolExecutor(max_workers=max_w) as pool:
            fmap = {
                pool.submit(
                    _run_one_model,
                    sp,
                    docs=docs,
                    empty_cwd=empty_cwd,
                    core_schema=core_schema,
                    core_batch_schema=core_batch_schema,
                    core_cls=core_cls,
                    claude_sys_prompt=claude_sys_prompt,
                    codex_prefix=codex_prefix,
                    audit_sys_prompt=audit_sys_prompt,
                    timeout_s=args.timeout,
                    usage_guards=usage_guards,
                ): sp
                for sp in specs
            }
            for fut in as_completed(fmap):
                sp = fmap[fut]
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {
                        **asdict(sp),
                        "skipped_reason": f"exception: {exc}",
                        "wall_s": 0.0,
                        "batches": [],
                        "predictions": {},
                        "metrics": {},
                    }
                with runs_lock:
                    runs[sp.name] = res
                    recompute_scores_and_report(docs=docs, runs=runs, out_dir=out_dir)

    if by_provider:
        with ThreadPoolExecutor(max_workers=len(by_provider)) as lane_pool:
            lane_futs = [lane_pool.submit(_run_provider_lane, prov, specs) for prov, specs in by_provider.items()]
            for fut in as_completed(lane_futs):
                fut.result()

    summary = recompute_scores_and_report(docs=docs, runs=runs, out_dir=out_dir)
    print(f"Benchmark done: {len(summary['leaderboard'])} configs -> {out_dir / 'report.md'}")
    for row in summary["leaderboard"][:10]:
        m = row["metrics"]
        print(
            f"  {row['name']:24s} exact={m.get('exact_4tuple_pct')}% "
            f"cons={m.get('consensus_4tuple_pct')}% gr={row['grounded']} wall={row.get('wall_s')}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
