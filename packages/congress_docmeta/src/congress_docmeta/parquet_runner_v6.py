#!/usr/bin/env python3
"""Streaming, Atomic `link_key_hex`-Checkpointed DocMeta V6.2 Parquet Runner (`parquet_runner_v6.py`).

Top-level import is 100% Python stdlib (`/usr/bin/python3 -B -I -S` clean); all ML/Parquet/ANE/Pass-2
runtime dependencies (`pyarrow`, `numpy`, `FastGemma4Engine`, `FastBgeSmall`, `FastEmbeddingGemma2`,
`FastGptOssEngine`) are loaded lazily inside execution entrypoints.

Key capabilities:
  1. Streams bounded `chunk_rows` (default `4,096`) batches from `llm_queue_v6_2.parquet` (or directory/glob)
     with `0` full-corpus prompt pre-materialization in RAM and `0` `skip_empty` silent row drops.
  2. Reuses precomputed `llm_queue_v6_2` deterministic columns (`known_json`, `locked_primary_kind`,
     `det_refs`, `rel_*`, `personas_seed_json`, `p3_toc_or_gavel_slice`, `stapled_ttf_disclosure_json`)
     without redundant `pre_pass_v6` regex scans, while falling back to `pre_pass_v6` on raw Parquets.
  3. Synchronizes per-document `LLMatcher` grammar locks (`PerDocGrammarHelperV6`) with `run_decode_rolling`'s
     exact `doc_order` length sort and forwards `use_ane_ring` to `FastGemma4Engine.run_rolling(...)`.
  4. Checkpoints atomically per chunk via `.part-NNNNN.parquet.tmp -> os.replace` (`unlink` `.tmp` on
     `BaseException`) keyed on `link_key_hex` (`--resume`), and optionally seals a single `zstd`
     `row_group_size=32768` output Parquet compatible with `viewer_publication.docmeta_v6_1`.
  5. Logs per-row `llm_vs_det_diff_json`, runs `anomaly_router_v6` (`+ C0_Stdlib` `check_gist_title_grounding_v6`),
     exposes a 1-line `external_verifier` hook, co-executes optional background ANE search embeddings
     (`--embed-ane bge-small|embeddinggemma-2|none`, `Proposal B4`), and runs optional `fast-gpt-oss`
     `H2_Sel` Pass-2 escalation (`escalate_anomalies_gpt_oss`) on anomaly-flagged documents.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
from dataclasses import dataclass
import glob
import inspect
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Union

from .compact_wire_v6 import (
    DOCMETA_V6_COMPACT_SCHEMA_STR,
    build_prompt_v6_compact,
    detect_checkpoint_wire_format,
    expand_compact_v6_to_v4,
)
from .pythonic_v5 import (
    DocMetaValidationError,
    SCHEMA_OBJ,
    SCHEMA_V4_STR,
    SYS_DOCMETA_V4,
    _build_triage_result,
    _salvage_truncated_docmeta_v4,
    build_prompt_v4,
    canonicalize_docmeta_v4,
    validate_docmeta_v4,
)
from .pythonic_v6 import (
    DOC_KINDS_SET,
    build_doc_kind_schema_v6,
    clean_html_and_cms_v6,
    infer_is_html_v6,
    load_default_usc_oracle_v6,
    per_doc_grammar_v6,
    post_pass_v6,
    pre_pass_v6,
)

ExternalVerifierFn = Callable[
    [Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    Sequence[Union[Mapping[str, Any], float, bool, None]],
]


@dataclass
class DocMetaSweepSummary:
    """End-to-end execution receipt for `run_docmeta_parquet_sweep`."""

    docs_processed: int
    docs_skipped_resume: int
    llm_decoded_docs: int
    triage_short_circuited_docs: int
    strict_v4_valid_docs: int
    anomaly_flagged_docs: int
    pass2_escalated_docs: int
    pass2_accepted_docs: int
    ane_embedded_docs: int
    chunks_written: int
    prompt_tokens: int
    completion_tokens: int
    elapsed_sec: float
    docs_per_sec: float
    decode_tok_s: float
    output_path: Path
    parts_dir: Path


def _row_resume_key(row: Mapping[str, Any], fallback_idx: int) -> str:
    lk_hex = row.get("link_key_hex")
    if isinstance(lk_hex, str) and lk_hex:
        return lk_hex
    lk_bin = row.get("link_key")
    if isinstance(lk_bin, (bytes, bytearray)) and len(lk_bin) > 0:
        return bytes(lk_bin).hex()
    dk = row.get("doc_key")
    if isinstance(dk, str) and dk:
        return f"dk:{dk}"
    lr = row.get("list_row")
    if lr is not None:
        return f"lr:{int(lr)}"
    return f"idx:{fallback_idx}"


def _resolve_parquet_inputs(input_path: str | Path) -> list[Path]:
    s = str(input_path)
    if any(ch in s for ch in ("*", "?", "[")):
        files = sorted(Path(p) for p in glob.glob(s) if p.endswith(".parquet"))
        if not files:
            raise FileNotFoundError(f"No Parquet files matched glob: {input_path}")
        return files
    p = Path(input_path)
    if p.is_dir():
        files = sorted(
            f for f in p.glob("*.parquet") if not f.name.startswith(".") and not f.name.endswith(".tmp")
        )
        if not files:
            raise FileNotFoundError(f"No Parquet files found in directory: {p}")
        return files
    if not p.is_file():
        raise FileNotFoundError(f"Input Parquet file does not exist: {p}")
    return [p]


def _parse_json_safe(val: Any) -> Any:
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str) and val.strip():
        try:
            return json.loads(val)
        except Exception:
            return None
    return None


def compute_llm_vs_det_diff_v6(
    raw_llm_obj: Mapping[str, Any] | None,
    final_obj: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    raw_valid_json: bool = True,
    salvaged_truncated: bool = False,
) -> dict[str, Any]:
    """Compare raw pre-`post_pass_v6` 2B output against deterministic signals and final canonical `DocMetaV4Causal`."""
    raw_d = dict(raw_llm_obj) if isinstance(raw_llm_obj, Mapping) else {}
    changed_fields: list[str] = []
    for k in sorted(set(raw_d.keys()) | set(final_obj.keys())):
        if raw_d.get(k) != final_obj.get(k):
            changed_fields.append(k)

    raw_refs = {x for x in (raw_d.get("refs") or ()) if isinstance(x, str)} if isinstance(raw_d.get("refs"), list) else set()
    fin_refs = {x for x in (final_obj.get("refs") or ()) if isinstance(x, str)} if isinstance(final_obj.get("refs"), list) else set()
    raw_cmts = list(raw_d.get("committees") or ()) if isinstance(raw_d.get("committees"), list) else []
    fin_cmts = list(final_obj.get("committees") or ()) if isinstance(final_obj.get("committees"), list) else []

    det_cong = row.get("rel_congress")
    det_ch = row.get("rel_chamber")
    locked_pk = row.get("locked_primary_kind")

    det_contradictions: list[str] = []
    if locked_pk and raw_d.get("primary_kind") and raw_d.get("primary_kind") != locked_pk:
        det_contradictions.append(f"locked_kind:{raw_d.get('primary_kind')}!={locked_pk}")
    if det_cong is not None and raw_d.get("congress") is not None and raw_d.get("congress") != int(det_cong):
        det_contradictions.append(f"rel_congress:{raw_d.get('congress')}!={int(det_cong)}")
    if det_ch and raw_d.get("chamber") and raw_d.get("chamber") != det_ch:
        det_contradictions.append(f"rel_chamber:{raw_d.get('chamber')}!={det_ch}")

    raw_personas = raw_d.get("personas") if isinstance(raw_d.get("personas"), list) else []
    fin_personas = final_obj.get("personas") if isinstance(final_obj.get("personas"), list) else []

    return {
        "raw_valid_json": bool(raw_valid_json),
        "salvaged_truncated": bool(salvaged_truncated),
        "primary_kind_raw": raw_d.get("primary_kind"),
        "primary_kind_final": final_obj.get("primary_kind"),
        "congress_raw": raw_d.get("congress"),
        "congress_final": final_obj.get("congress"),
        "chamber_raw": raw_d.get("chamber"),
        "chamber_final": final_obj.get("chamber"),
        "committees_added": [c for c in fin_cmts if c not in raw_cmts],
        "refs_added_count": len(fin_refs - raw_refs),
        "personas_count_raw": len(raw_personas),
        "personas_count_final": len(fin_personas),
        "fields_changed_by_post_pass": changed_fields,
        "det_contradictions": det_contradictions,
    }


def _build_precomputed_context_from_queue_row(
    row: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str, str, bool]:
    """Reconstruct `(known_str, pmeta_like, fn, raw_prompt_text, has_precomputed_queue_cols)` in O(1)."""
    fn = str(row.get("filename") or "")
    fmt = str(row.get("effective_format") or row.get("format") or "").lower()
    has_queue_cols = ("p12_clean_text" in row) and ("known_json" in row)
    if not has_queue_cols:
        txt_any = str(
            row.get("p12_raw_text")
            or row.get("p12_clean_text")
            or row.get("text")
            or row.get("body_text")
            or ""
        )
        known_raw = _parse_json_safe(row.get("known_json")) or row.get("known")
        enr_known_str, pmeta = pre_pass_v6(
            known_raw,
            fn,
            txt_any,
            explicit_format=fmt or None,
            body_sha_hex=row.get("saved_body_hex") or row.get("effective_body_sha_hex"),
            use_zero_llm_bypass=False,
        )
        return enr_known_str, pmeta, fn, txt_any, False

    raw_txt = str(row.get("p12_raw_text") or row.get("p12_clean_text") or "")
    clean_txt = str(row.get("p12_clean_text") or raw_txt)
    known_d = _parse_json_safe(row.get("known_json"))
    if not isinstance(known_d, dict):
        known_d = {}

    # Enrich advisory known metadata from precomputed relational columns if missing
    if known_d.get("congress") is None and row.get("rel_congress") is not None:
        known_d["congress"] = int(row["rel_congress"])
    if not known_d.get("cmt") and row.get("rel_committees"):
        known_d["cmt"] = list(row["rel_committees"])
    if not known_d.get("chambers") and row.get("rel_chamber"):
        known_d["chambers"] = [str(row["rel_chamber"])]
    known_str = json.dumps(known_d, separators=(",", ":"), ensure_ascii=False) if known_d else "<NONE>"

    is_h = infer_is_html_v6(fn, raw_txt, explicit_format=fmt or None)
    locked_pk = row.get("locked_primary_kind")
    if locked_pk not in DOC_KINDS_SET:
        locked_pk = None

    # Check empty-text guard (`0` silent row drops!)
    triage_d = None
    if not raw_txt.strip() and not clean_txt.strip():
        triage_d = {
            **_build_triage_result(
                "stub_or_blank",
                "native",
                f"Empty document text in queue row ({fn or 'unnamed'})",
            ),
            "source": "runner_empty_guard",
        }

    rel_d: dict[str, Any] = {
        "rel_congress": row.get("rel_congress"),
        "rel_chamber": row.get("rel_chamber"),
        "rel_author_safe_committees": list(row.get("rel_committees") or ()),
        "rel_event_id": row.get("rel_event_id"),
        "rel_event_date": row.get("rel_event_date"),
        "rel_event_title": row.get("rel_event_title"),
        "rel_event_type": row.get("rel_event_type"),
        "rel_venue": row.get("rel_venue"),
        "rel_witness_personas_json": row.get("personas_seed_json"),
    }
    cit_d: dict[str, Any] = {
        "det_refs": list(row.get("det_refs") or ()),
        "det_short_titles": list(row.get("det_short_titles") or ()),
        "det_fiscal_years": [int(y) for y in (row.get("det_fiscal_years") or ()) if y is not None],
        "usc_oracle_invalid_refs": list(row.get("usc_oracle_invalid_refs") or ()),
    }
    hyg_d: dict[str, Any] = {
        "p12_lines": clean_txt,
        "has_newlines": "\n" in clean_txt,
        "witness_list_personas_json": row.get("personas_seed_json") if locked_pk == "witness_list" else None,
        "gpo_p12_personas_json": row.get("personas_seed_json") if locked_pk == "hearing_transcript" else None,
    }
    stapled_ttf = _parse_json_safe(row.get("stapled_ttf_disclosure_json"))
    mp_d: dict[str, Any] = {
        "is_cover_roster_p12": bool(row.get("is_cover_roster_p12")),
        "p3_toc_or_gavel_slice": row.get("p3_toc_or_gavel_slice"),
        "stapled_ttf_disclosure": stapled_ttf if isinstance(stapled_ttf, dict) else None,
    }
    prov_d: dict[str, Any] = {
        "hsru_host_status": row.get("hsru_host_status") or "not_hsru",
        "url_congress": row.get("rel_congress"),
        "provenance_committees": list(row.get("rel_committees") or ()),
    }
    pmeta: dict[str, Any] = {
        "known_dict": known_d,
        "is_html": is_h,
        "p12_lines": clean_txt,
        "clean_text_v6": clean_txt,
        "tier1_signature_id": row.get("lock_id"),
        "tier1_target_kind": locked_pk,
        "grammar_lock_source": row.get("grammar_lock_source"),
        "triage": triage_d,
        "zero_llm_docmeta": None,
        "provenance": prov_d,
        "multipage": mp_d,
        "relational": rel_d,
        "citations": cit_d,
        "hygiene": hyg_d,
        "cms_nav_stripped": False,
        "cms_nav_family": None,
        "html_script_stripped": False,
        "mojibake_repaired": False,
    }
    return known_str, pmeta, fn, raw_txt, True


def _init_ane_embedder(embed_ane: str) -> tuple[Any | None, str]:
    mode_norm = (embed_ane or "none").strip().lower()
    if mode_norm in ("", "none", "off", "false"):
        return None, "none"
    if mode_norm in ("bge-small", "bge_small", "bge"):
        from fast_bge_small import FastBgeSmall

        emb = FastBgeSmall(default_mode="ane", warmup=True, enable_ane=True)
        return emb, "bge-small"
    if mode_norm in ("embeddinggemma-2", "embeddinggemma_2", "emb2"):
        from fast_embeddinggemma_2 import FastEmbeddingGemma2

        emb = FastEmbeddingGemma2(
            default_mode="ane",
            warmup=True,
            enable_ane=True,
            enable_cpu_sme=False,
            dimensions=256,
        )
        return emb, "embeddinggemma-2"
    raise ValueError(
        f"Unsupported --embed-ane value {embed_ane!r}; expected 'none', 'bge-small', or 'embeddinggemma-2'."
    )


def _encode_batch_pure_ane(embedder: Any, model_tag: str, texts: Sequence[str]) -> list[list[float]]:
    """Encode `texts` strictly on ANE (`max_length=512`, `0` Metal/MLX GPU dispatches) for safe GPU co-execution."""
    import numpy as np

    if not texts:
        return []
    clipped = [t[:2400] if t else "document" for t in texts]
    if model_tag == "bge-small":
        tok_lists = embedder.tokenizer.encode_batch(clipped, add_query_prefix=False, max_length=512)
        vecs = embedder.encode_corpus(tok_lists, mode="ane")
    else:
        tok_lists = embedder.tokenizer.encode_batch(
            clipped,
            add_document_prefix=True,
            max_length=512,
        )
        # Ensure every sequence is `<= 512` tokens so `FastEmbeddingGemma2` sets `over_q = []` (`use_gpu = False`)!
        tok_lists_512 = [t[:512] for t in tok_lists]
        vecs = embedder.encode_corpus(tok_lists_512, mode="ane", dimensions=embedder.dim)
    arr_f16 = np.asarray(vecs, dtype=np.float16)
    return arr_f16.astype(np.float32).tolist()


def build_excluded_kind_schema_v6(
    excluded_kind: str,
    base_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build `DocMetaV4Causal` schema forbidding a rejected Pass-1 `primary_kind` on unlocked docs."""
    schema = copy.deepcopy(base_schema if base_schema is not None else SCHEMA_OBJ)
    allowed = [k for k in schema["$defs"]["doc_kind"]["enum"] if k != excluded_kind]
    if allowed:
        schema["properties"]["primary_kind"] = {"type": "string", "enum": allowed}
    return schema


def _normalize_ext_verdict(v_item: Any) -> dict[str, Any] | None:
    if v_item is None:
        return None
    if isinstance(v_item, bool):
        return {"is_faithful": v_item, "escalate": not v_item}
    if isinstance(v_item, (int, float)):
        sc_v = float(v_item)
        return {"score": round(sc_v, 4), "is_faithful": sc_v >= 0.5, "escalate": sc_v < 0.5}
    if isinstance(v_item, Mapping):
        return dict(v_item)
    return None


def _verdict_defect_and_unfaithful(v_dict: Mapping[str, Any] | None) -> tuple[float, bool]:
    if not v_dict:
        return 0.0, False
    if isinstance(v_dict.get("defect_score"), (int, float)):
        defect = float(v_dict["defect_score"])
    elif isinstance(v_dict.get("score"), (int, float)):
        defect = max(0.0, min(1.0, 1.0 - float(v_dict["score"])))
    else:
        defect = 0.75 if (v_dict.get("escalate") or v_dict.get("is_faithful") is False) else 0.0
    unfaithful = bool(
        v_dict.get("escalate")
        or v_dict.get("is_faithful") is False
        or (isinstance(v_dict.get("score"), (int, float)) and float(v_dict["score"]) < 0.5)
    )
    return defect, unfaithful


def _apply_ext_verdict_to_anomaly(anom: dict[str, Any], v_dict: Mapping[str, Any]) -> None:
    _, should_esc = _verdict_defect_and_unfaithful(v_dict)
    if not should_esc:
        return
    anom["has_anomaly"] = True
    anom["escalate_to_teacher"] = True
    anom["needs_teacher_escalation"] = True
    codes = list(anom.get("anomaly_codes") or ())
    custom_codes = v_dict.get("codes")
    if isinstance(custom_codes, (list, tuple)):
        for cc in custom_codes:
            cc_s = str(cc).strip()
            if cc_s and cc_s not in codes:
                codes.append(cc_s)
    if "external_verifier_flagged" not in codes:
        codes.append("external_verifier_flagged")
    anom["anomaly_codes"] = codes
    anom["anomaly_score"] = max(float(anom.get("anomaly_score", 0.0)), 1.0)


def _build_pass2_critique_hint(
    obj: Mapping[str, Any],
    anom: Mapping[str, Any],
    verdict: Mapping[str, Any] | None,
    *,
    is_kind_locked: bool,
) -> str:
    codes = set(str(c) for c in (anom.get("anomaly_codes") or ()))
    if verdict and isinstance(verdict.get("codes"), (list, tuple)):
        codes.update(str(c) for c in verdict["codes"])
    notes: list[str] = []
    cur_kind = str(obj.get("primary_kind") or "")
    if not is_kind_locked and cur_kind and ({"atomic_kind_suspect", "kind_structural_contradiction"} & codes):
        notes.append(f"re-verify primary_kind (Pass-1 '{cur_kind}' conflicted with document headers)")
    if {"ungrounded_committee_hallucination", "atomic_committee_suspect"} & codes:
        notes.append("include ONLY committees explicitly named in the text or authoritative metadata")
    if {"missing_or_ungrounded_vote_summary", "atomic_action_summary_suspect"} & codes:
        notes.append("populate action_summary with exact vote outcome and tally grounded in text")
    if {"ungrounded_gist_or_title", "atomic_gist_suspect"} & codes:
        notes.append("keep composed_title and gist strictly faithful to stated numbers, dates, citations, and modality")
    if {"suspected_persona_omission", "invalid_or_misroled_persona", "atomic_persona_suspect"} & codes:
        notes.append("extract all active human actors (witnesses/senders/recipients) with accurate roles and omit buildings/orgs")
    if {"ungrounded_iso_date", "atomic_date_suspect"} & codes:
        notes.append("omit doc_date/event_date unless explicitly grounded in text (never default to YYYY-01-01)")
    if not notes:
        return ""
    return "\n\n[Pass-1 Verifier Critique: " + "; ".join(notes) + ".]"


def escalate_anomalies_gpt_oss(
    gpt_oss_engine: Any,
    *,
    flagged_indices: Sequence[int],
    prompts_user_content: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    pmetas: Sequence[Mapping[str, Any]],
    current_objs: list[dict[str, Any]],
    current_texts: list[str],
    current_anomalies: list[dict[str, Any]],
    usc_oracle: Any = None,
    external_verifier: ExternalVerifierFn | None = None,
    current_verdicts: Sequence[Mapping[str, Any] | None] | None = None,
    current_verdicts_json: list[str | None] | None = None,
    max_tokens: int = 768,
    batch_size: int = 8,
    k: int = 1,
) -> tuple[int, int, dict[int, str]]:
    """Run closed-loop `fast-gpt-oss` (`H2_Sel` Pass-2 teacher escalation) on anomaly-flagged documents.

    Feeds structured Pass-1 verifier critique hints + excluded-kind grammar constraints into Pass-2,
    and re-verifies Pass-2 candidates through `external_verifier` so teacher hallucinations never
    overwrite faithful Pass-1 fields.
    Returns `(escalated_attempted_count, escalated_accepted_count, pass1_json_by_idx)`.
    """
    if not flagged_indices:
        return 0, 0, {}

    sub_prompts: list[str] = []
    sub_schemas: list[Any] = []
    for i in flagged_indices:
        lk = pmetas[i].get("tier1_target_kind")
        is_locked = lk in DOC_KINDS_SET
        old_v = current_verdicts[i] if (current_verdicts is not None and i < len(current_verdicts)) else None
        anom_i = current_anomalies[i]
        codes_i = set(str(c) for c in (anom_i.get("anomaly_codes") or ()))
        cur_kind = str(current_objs[i].get("primary_kind") or "")
        fp_kind = (
            float(old_v["field_probs"]["primary_kind"])
            if (
                isinstance(old_v, Mapping)
                and isinstance(old_v.get("field_probs"), Mapping)
                and isinstance(old_v["field_probs"].get("primary_kind"), (int, float))
            )
            else 1.0
        )

        if is_locked:
            schema_i: Any = build_doc_kind_schema_v6(str(lk))
        elif cur_kind in DOC_KINDS_SET and (
            "kind_structural_contradiction" in codes_i
            or ("atomic_kind_suspect" in codes_i and fp_kind < 0.25)
        ):
            schema_i = build_excluded_kind_schema_v6(cur_kind)
        else:
            schema_i = SCHEMA_V4_STR

        hint = _build_pass2_critique_hint(current_objs[i], anom_i, old_v, is_kind_locked=is_locked)
        sub_prompts.append(prompts_user_content[i] + hint if hint else prompts_user_content[i])
        sub_schemas.append(schema_i)

    sig = inspect.signature(gpt_oss_engine.generate_batch)
    supports_per_doc = "per_doc_grammars" in sig.parameters

    if supports_per_doc:
        batch_res = gpt_oss_engine.generate_batch(
            sub_prompts,
            system_prompt=None,
            json_schema=SCHEMA_V4_STR,
            per_doc_grammars=sub_schemas,
            max_tokens=max_tokens,
            temperature=0.0,
            batch_size=batch_size,
            whitespace_flexible=False,
        )
        gen_items = list(batch_res.items)
    else:
        # Fallback if running against an older `FastGptOssEngine` without `per_doc_grammars`
        gen_items = [None] * len(flagged_indices)
        by_schema: dict[str, tuple[Any, list[int]]] = {}
        for pos, sc_obj in enumerate(sub_schemas):
            s_key = json.dumps(sc_obj, sort_keys=True) if isinstance(sc_obj, Mapping) else str(sc_obj)
            if s_key not in by_schema:
                by_schema[s_key] = (sc_obj, [])
            by_schema[s_key][1].append(pos)
        for _s_key, (schema_s, positions) in by_schema.items():
            r_sub = gpt_oss_engine.generate_batch(
                [sub_prompts[p] for p in positions],
                system_prompt=None,
                json_schema=schema_s,
                max_tokens=max_tokens,
                temperature=0.0,
                batch_size=batch_size,
                whitespace_flexible=False,
            )
            for p, it in zip(positions, r_sub.items):
                gen_items[p] = it

    valid_candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for orig_i, item in zip(flagged_indices, gen_items):
        if item is None:
            continue
        parsed_cand = item.parsed
        if not isinstance(parsed_cand, dict):
            try:
                parsed_cand = json.loads(item.text)
            except Exception:
                parsed_cand = None
        if not isinstance(parsed_cand, dict):
            continue

        row = rows[orig_i]
        pmeta = pmetas[orig_i]
        fn = str(row.get("filename") or "")
        txt = str(row.get("p12_raw_text") or row.get("p12_clean_text") or row.get("text") or "")
        try:
            clean_cand, sidecar_cand = post_pass_v6(
                parsed_cand,
                known=pmeta.get("known_dict"),
                filename=fn,
                text=txt,
                p12_lines=pmeta.get("p12_lines"),
                explicit_format=row.get("effective_format") or row.get("format"),
                pre_meta=pmeta,
                provenance=pmeta.get("provenance"),
                multipage=pmeta.get("multipage"),
                relational=pmeta.get("relational"),
                citations=pmeta.get("citations"),
                hygiene=pmeta.get("hygiene"),
                usc_oracle=usc_oracle,
            )
            canon_cand = canonicalize_docmeta_v4(clean_cand)
        except DocMetaValidationError:
            continue
        ok_v4, _ = validate_docmeta_v4(canon_cand)
        if not ok_v4:
            continue
        valid_candidates.append((orig_i, canon_cand, dict(sidecar_cand["anomaly_routing"])))

    cand_verdicts_by_i: dict[int, dict[str, Any] | None] = {}
    if external_verifier is not None and valid_candidates:
        raw_cand_vs = external_verifier(
            [c for (_oi, c, _ca) in valid_candidates],
            [rows[oi] for (oi, _c, _ca) in valid_candidates],
        )
        for (oi, _c, _ca), cv_raw in zip(valid_candidates, raw_cand_vs):
            cand_verdicts_by_i[oi] = _normalize_ext_verdict(cv_raw)

    accepted = 0
    pass1_backup: dict[int, str] = {}
    for orig_i, canon_cand, cand_anom in valid_candidates:
        old_anom = current_anomalies[orig_i]
        if float(cand_anom.get("anomaly_score", 0.0)) > float(old_anom.get("anomaly_score", 1.0)):
            continue

        cand_v = cand_verdicts_by_i.get(orig_i)
        if external_verifier is not None:
            old_v = current_verdicts[orig_i] if (current_verdicts is not None and orig_i < len(current_verdicts)) else None
            old_def, old_unfaith = _verdict_defect_and_unfaithful(old_v)
            cand_def, cand_unfaith = _verdict_defect_and_unfaithful(cand_v)
            if not old_unfaith:
                if cand_unfaith:
                    continue
            else:
                if cand_unfaith and cand_def > old_def + 1e-6:
                    continue
            if cand_v is not None:
                _apply_ext_verdict_to_anomaly(cand_anom, cand_v)

        pass1_backup[orig_i] = current_texts[orig_i]
        current_objs[orig_i] = canon_cand
        current_texts[orig_i] = json.dumps(canon_cand, separators=(",", ":"), ensure_ascii=False)
        current_anomalies[orig_i] = cand_anom
        if current_verdicts_json is not None and orig_i < len(current_verdicts_json) and cand_v is not None:
            current_verdicts_json[orig_i] = json.dumps(cand_v, separators=(",", ":"), ensure_ascii=False)
        accepted += 1

    return len(flagged_indices), accepted, pass1_backup


def _cast_results_arrow_table(rows_out: list[dict[str, Any]]) -> Any:
    import pyarrow as pa

    tbl = pa.Table.from_pylist(rows_out)
    fields: list[Any] = []
    cols: list[Any] = []
    for f in tbl.schema:
        col = tbl[f.name]
        if f.name == "link_key":
            if pa.types.is_null(f.type):
                col = pa.nulls(len(col), type=pa.binary(8))
            else:
                col = col.cast(pa.binary(8))
            fields.append(pa.field(f.name, pa.binary(8), nullable=col.null_count > 0))
        elif f.name == "saved_body":
            if pa.types.is_null(f.type):
                col = pa.nulls(len(col), type=pa.binary(32))
            else:
                col = col.cast(pa.binary(32))
            fields.append(pa.field(f.name, pa.binary(32), nullable=col.null_count > 0))
        elif f.name in ("list_row", "rn", "congress"):
            if pa.types.is_null(f.type):
                col = pa.nulls(len(col), type=pa.int32())
            else:
                col = col.cast(pa.int32())
            fields.append(pa.field(f.name, pa.int32(), nullable=True))
        elif f.name == "committees":
            if pa.types.is_null(f.type):
                col = pa.nulls(len(col), type=pa.list_(pa.string()))
            else:
                col = col.cast(pa.list_(pa.string()))
            fields.append(pa.field(f.name, pa.list_(pa.string()), nullable=True))
        else:
            fields.append(f)
        cols.append(col)
    return pa.Table.from_arrays(cols, schema=pa.schema(fields))


def _write_table_atomic(table: Any, out_path: Path, *, row_group_size: int = 32768) -> None:
    import pyarrow.parquet as pq

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.parent / f".{out_path.name}.tmp"
    eff_rg = row_group_size if table.num_rows > row_group_size else max(1, table.num_rows)
    try:
        pq.write_table(
            table,
            tmp_path,
            compression="zstd",
            compression_level=6,
            row_group_size=eff_rg,
            write_statistics=True,
        )
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def run_docmeta_parquet_sweep(
    engine: Any,
    input_path: str | Path,
    output_path: str | Path,
    *,
    chunk_rows: int = 4096,
    b_slots: int = 256,
    refill_min: int = 32,
    max_tokens: int = 768,
    doc_cap_full: int = 2048,
    swa_ring_cap: int = 512,
    sort_by_length: bool = True,
    use_ane_ring: bool | str = "auto",
    resume: bool = False,
    wire_format: str = "auto",
    embed_ane: str = "none",
    grammar_router: str = "none",
    atomic_verifier: str = "none",
    repair_persona_roles: bool = False,
    external_verifier: ExternalVerifierFn | None = None,
    escalate_gpt_oss: bool = False,
    gpt_oss_engine: Any = None,
    gpt_oss_model_dir: str | Path | None = None,
    gpt_oss_batch_size: int = 8,
    gpt_oss_k: int = 1,
    model_source_tag: str = "fast-gemma4-e2b-v6_2",
    _after_chunk_hook: Callable[[int, Path], None] | None = None,
) -> DocMetaSweepSummary:
    """Stream `llm_queue_v6_2.parquet` in `chunk_rows` batches with atomic `link_key_hex` checkpointing."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from fast_gemma4.grammar import GrammarHelper
    from fast_gemma4.per_doc_grammar import compute_rolling_doc_order

    if chunk_rows <= 0:
        raise ValueError(f"chunk_rows must be >= 1, got {chunk_rows}")

    t0 = time.perf_counter()
    in_files = _resolve_parquet_inputs(input_path)
    out_target = Path(output_path)
    seal_single_file = out_target.suffix.lower() == ".parquet"
    parts_dir = (
        out_target.parent / f"{out_target.stem}.parts"
        if seal_single_file
        else out_target
    )
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Clean up any leftover `.part-*.parquet.tmp` files from interrupted runs
    for stale_tmp in parts_dir.glob(".*.tmp"):
        stale_tmp.unlink(missing_ok=True)
    for stale_tmp2 in parts_dir.glob("*.tmp"):
        stale_tmp2.unlink(missing_ok=True)

    done_keys: set[str] = set()
    next_shard_idx = 0
    existing_parts = sorted(parts_dir.glob("part-*.parquet"))
    if resume and existing_parts:
        for ep in existing_parts:
            pf_ep = pq.ParquetFile(ep)
            ep_cols = set(pf_ep.schema_arrow.names)
            read_cols = [c for c in ("link_key_hex", "link_key", "doc_key", "list_row") if c in ep_cols]
            tbl_ep = pf_ep.read(columns=read_cols)
            for r_ep in tbl_ep.to_pylist():
                done_keys.add(_row_resume_key(r_ep, -1))
            m_idx = ep.stem.split("-")[-1]
            if m_idx.isdigit():
                next_shard_idx = max(next_shard_idx, int(m_idx) + 1)
    elif not resume and existing_parts:
        for ep in existing_parts:
            ep.unlink()

    tok = getattr(engine, "tokenizer", None)
    if tok is None:
        raise ValueError("Engine must expose `.tokenizer` for `run_docmeta_parquet_sweep`.")
    new_to_old = getattr(engine, "new_to_old", None)
    if new_to_old is None and hasattr(engine, "model"):
        new_to_old = engine.model.new_to_old

    wf_norm = str(wire_format or "auto").strip().lower()
    if wf_norm not in ("auto", "v4", "compact", "compact_v6"):
        raise ValueError(f"Unsupported wire_format={wire_format!r}; expected 'auto', 'v4', or 'compact'.")
    if wf_norm == "auto":
        eng_mdir = getattr(engine, "model_dir", getattr(getattr(engine, "model", None), "model_dir", None))
        wf_norm = detect_checkpoint_wire_format(eng_mdir)
    is_compact_wire = wf_norm in ("compact", "compact_v6")
    pass1_schema_str = DOCMETA_V6_COMPACT_SCHEMA_STR if is_compact_wire else SCHEMA_V4_STR
    pass1_prompt_fn = build_prompt_v6_compact if is_compact_wire else build_prompt_v4
    pass1_wire = "compact" if is_compact_wire else "v4"

    gh_std = GrammarHelper(tok, pass1_schema_str, new_to_old, whitespace_flexible=False)
    kind_grammar_cache: dict[str, tuple[Any, list[int]]] = {}

    def _fmt_chat(user_content: str) -> str:
        msgs = [{"role": "user", "content": user_content}]
        if hasattr(tok, "apply_chat_template"):
            return str(tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
        return str(tok.format_chat(msgs, add_generation_prompt=True, enable_thinking=False))

    probe_a = tok.encode(_fmt_chat(pass1_prompt_fn('{"a":1}', "a.pdf", "Alpha")), add_special_tokens=False)
    probe_b = tok.encode(_fmt_chat(pass1_prompt_fn('{"b":2}', "b.pdf", "Beta")), add_special_tokens=False)
    base_lcp = min(len(probe_a), len(probe_b))
    for k_i in range(base_lcp):
        if probe_a[k_i] != probe_b[k_i]:
            base_lcp = k_i
            break
    shared_sys_ids = probe_a[:base_lcp]

    usc_oracle = load_default_usc_oracle_v6()
    ane_embedder, ane_model_tag = _init_ane_embedder(embed_ane)

    owned_atomic_verifier: Any = None
    av_mode = str(atomic_verifier or "none").strip().lower()
    if av_mode not in ("none", "laya-ane", "kev-0.8b", "both"):
        raise ValueError(
            f"Unsupported atomic_verifier={atomic_verifier!r}; expected 'none', 'laya-ane', 'kev-0.8b', or 'both'."
        )
    if external_verifier is None and av_mode != "none":
        from .atomic_validator_v6 import AtomicOutputValidatorV6

        owned_atomic_verifier = AtomicOutputValidatorV6(mode=av_mode)  # type: ignore[arg-type]
        external_verifier = owned_atomic_verifier

    owned_grammar_router: Any = None
    gr_mode = str(grammar_router or "none").strip().lower()
    if gr_mode not in ("none", "fast", "ane"):
        raise ValueError(f"Unsupported grammar_router={grammar_router!r}; expected 'none', 'fast', or 'ane'.")
    if gr_mode != "none":
        from .grammar_router_ane_v6 import PreDecodeGrammarRouterV6

        shared_laya = getattr(external_verifier, "laya_backend", None)
        owned_grammar_router = PreDecodeGrammarRouterV6(mode=gr_mode, shared_laya_backend=shared_laya)  # type: ignore[arg-type]

    owned_gpt_oss = False
    if escalate_gpt_oss and gpt_oss_engine is None:
        from fast_gpt_oss import FastGptOssEngine

        gpt_oss_engine = FastGptOssEngine(model_dir=gpt_oss_model_dir, warmup=True)
        owned_gpt_oss = True

    docs_processed = 0
    docs_skipped_resume = 0
    llm_decoded_docs = 0
    triage_short_circuited_docs = 0
    strict_v4_valid_docs = 0
    anomaly_flagged_docs = 0
    pass2_escalated_docs = 0
    pass2_accepted_docs = 0
    ane_embedded_docs = 0
    chunks_written = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_decode_sec = 0.0

    global_row_cursor = 0
    can_async_stage1 = bool(
        external_verifier is not None
        and getattr(external_verifier, "supports_async_ane_stage1", False)
        and callable(getattr(external_verifier, "run_stage1_ane", None))
        and callable(getattr(external_verifier, "finish_stage2", None))
        and _after_chunk_hook is None
        and ane_embedder is None
    )
    pending_prev: dict[str, Any] | None = None
    prev_stage1_thread: threading.Thread | None = None
    prev_stage1_out: list[dict[str, Any]] = []
    prev_stage1_err: list[BaseException] = []

    def _finalize_and_write_chunk(
        ctx: dict[str, Any],
        precomputed_stage1: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal strict_v4_valid_docs, anomaly_flagged_docs, pass2_escalated_docs, pass2_accepted_docs
        nonlocal docs_processed, chunks_written, next_shard_idx

        c_chunk: list[dict[str, Any]] = ctx["chunk"]
        c_pmetas: list[dict[str, Any]] = ctx["pmetas"]
        c_user_contents: list[str] = ctx["user_contents"]
        c_out_tok_lens: list[int] = ctx["out_tok_lens"]
        c_ane_vectors: list[list[float] | None] = ctx["ane_vectors"]
        c_clean_objs: list[dict[str, Any]] = ctx["clean_objs"]
        c_clean_texts: list[str] = ctx["clean_texts"]
        c_anomalies: list[dict[str, Any]] = ctx["anomalies"]
        c_diffs_json: list[str] = ctx["diffs_json"]
        n_c = len(c_chunk)

        ext_verdicts_json: list[str | None] = [None] * n_c
        parsed_verdicts: list[dict[str, Any] | None] = [None] * n_c
        if external_verifier is not None:
            if precomputed_stage1 is not None:
                verdicts: Any = external_verifier.finish_stage2(precomputed_stage1)  # type: ignore[attr-defined]
            else:
                verdicts = external_verifier(c_clean_objs, c_chunk)
            for i, v_item in enumerate(verdicts):
                v_dict = _normalize_ext_verdict(v_item)
                if v_dict is None:
                    continue
                parsed_verdicts[i] = v_dict
                ext_verdicts_json[i] = json.dumps(v_dict, separators=(",", ":"), ensure_ascii=False)
                _apply_ext_verdict_to_anomaly(c_anomalies[i], v_dict)

            if repair_persona_roles and callable(getattr(external_verifier, "repair_suspect_personas", None)):
                candidate_objs = copy.deepcopy(c_clean_objs)
                repairs = external_verifier.repair_suspect_personas(candidate_objs, c_chunk, parsed_verdicts)  # type: ignore[attr-defined]
                repaired_by_doc: dict[int, set[int]] = {}
                for rep_item in repairs:
                    r_di = int(rep_item["doc_idx"])
                    try:
                        re_canon = canonicalize_docmeta_v4(candidate_objs[r_di])
                    except DocMetaValidationError:
                        continue
                    ok_rep, _ = validate_docmeta_v4(re_canon)
                    if ok_rep:
                        repaired_by_doc.setdefault(r_di, set()).add(int(rep_item["persona_idx"]))
                        c_clean_objs[r_di] = re_canon
                        c_clean_texts[r_di] = json.dumps(re_canon, separators=(",", ":"), ensure_ascii=False)
                # De-escalate Pass-2 if ANE role repair resolved every suspect persona on a persona-only flag!
                for r_di, fixed_pis in repaired_by_doc.items():
                    vd_r = parsed_verdicts[r_di]
                    anom_r = c_anomalies[r_di]
                    if isinstance(vd_r, dict) and vd_r.get("flagged_fields") == ["personas"]:
                        p_defs = list(vd_r.get("persona_defect_scores") or ())
                        unfixed_high = any(
                            idx_p not in fixed_pis and float(sc_p) >= 0.48 for idx_p, sc_p in enumerate(p_defs)
                        )
                        other_codes = [
                            c
                            for c in (anom_r.get("anomaly_codes") or ())
                            if str(c) not in ("atomic_persona_suspect", "external_verifier_unfaithful")
                        ]
                        if not unfixed_high and not other_codes:
                            anom_r["escalate_to_teacher"] = False
                            anom_r["needs_teacher_escalation"] = False

        pass1_backup_by_i: dict[int, str] = {}
        if escalate_gpt_oss and gpt_oss_engine is not None:
            flagged_idxs = [
                i
                for i, a in enumerate(c_anomalies)
                if bool(a.get("escalate_to_teacher") or a.get("needs_teacher_escalation"))
                and c_pmetas[i].get("triage") is None
            ]
            esc_n, acc_n, pass1_backup_by_i = escalate_anomalies_gpt_oss(
                gpt_oss_engine,
                flagged_indices=flagged_idxs,
                prompts_user_content=c_user_contents,
                rows=c_chunk,
                pmetas=c_pmetas,
                current_objs=c_clean_objs,
                current_texts=c_clean_texts,
                current_anomalies=c_anomalies,
                usc_oracle=usc_oracle,
                external_verifier=external_verifier,
                current_verdicts=parsed_verdicts,
                current_verdicts_json=ext_verdicts_json,
                max_tokens=max_tokens,
                batch_size=gpt_oss_batch_size,
                k=gpt_oss_k,
            )
            pass2_escalated_docs += esc_n
            pass2_accepted_docs += acc_n

        out_rows: list[dict[str, Any]] = []
        for i, (row, c_obj, c_json, anom, diff_j) in enumerate(
            zip(c_chunk, c_clean_objs, c_clean_texts, c_anomalies, c_diffs_json)
        ):
            ok_final, _ = validate_docmeta_v4(c_obj)
            if ok_final:
                strict_v4_valid_docs += 1
            is_flagged = bool(anom.get("escalate_to_teacher") or anom.get("needs_teacher_escalation"))
            if is_flagged:
                anomaly_flagged_docs += 1

            r_key = str(row["_resume_key"])
            lk_bin = row.get("link_key")
            if lk_bin is None and len(r_key) == 16:
                try:
                    lk_bin = bytes.fromhex(r_key)
                except ValueError:
                    lk_bin = None
            sb_bin = row.get("saved_body")
            sb_hex = row.get("saved_body_hex")
            if sb_bin is None and isinstance(sb_hex, str) and len(sb_hex) == 64:
                sb_bin = bytes.fromhex(sb_hex)
            if sb_hex is None and isinstance(sb_bin, (bytes, bytearray)) and len(sb_bin) == 32:
                sb_hex = bytes(sb_bin).hex()

            was_p2_accepted = i in pass1_backup_by_i
            src_tag = (
                "fast-gpt-oss-20b-pass2"
                if was_p2_accepted
                else (
                    "runner_triage_short_circuit"
                    if c_pmetas[i].get("triage") is not None
                    else model_source_tag
                )
            )

            rec_out: dict[str, Any] = {
                "list_row": int(row["list_row"]) if row.get("list_row") is not None else None,
                "link_key": lk_bin,
                "link_key_hex": row.get("link_key_hex") or (r_key if len(r_key) == 16 else None),
                "doc_key": row.get("doc_key") or r_key,
                "saved_body": sb_bin,
                "saved_body_hex": sb_hex,
                "effective_body_sha_hex": row.get("effective_body_sha_hex") or sb_hex,
                "package_id": row.get("package_id"),
                "rn": int(row["rn"]) if row.get("rn") is not None else None,
                "disposition": row.get("disposition") or "llm_extracted",
                "v6_route": row.get("v6_route") or "llm_open_extraction",
                "docmeta_source": src_tag,
                "filename": str(row.get("filename") or ""),
                "effective_format": str(row.get("effective_format") or row.get("format") or ""),
                "primary_kind": c_obj.get("primary_kind"),
                "status": c_obj.get("status"),
                "congress": c_obj.get("congress") if c_obj.get("congress") is not None else row.get("rel_congress"),
                "chamber": c_obj.get("chamber") or row.get("rel_chamber"),
                "committees": list(c_obj.get("committees") or row.get("rel_committees") or ()),
                "docmeta_json": c_json,
                "strict_v4_valid": bool(ok_final),
                "completion_tokens": int(c_out_tok_lens[i]),
                "llm_vs_det_diff_json": diff_j,
                "anomaly_score": float(anom.get("anomaly_score", 0.0)),
                "anomaly_flags": list(
                    anom.get("anomaly_codes")
                    or [
                        f["code"] if isinstance(f, Mapping) and "code" in f else str(f)
                        for f in (anom.get("anomalies") or anom.get("anomaly_flags") or ())
                    ]
                ),
                "needs_teacher_escalation": is_flagged,
                "gist_grounding_score": float((anom.get("gist_grounding") or {}).get("grounding_score", 1.0)),
                "external_verifier_json": ext_verdicts_json[i],
                "pass2_escalated": was_p2_accepted,
                "pass1_docmeta_json": pass1_backup_by_i.get(i),
            }
            if ane_embedder is not None:
                rec_out["ane_embed_model"] = ane_model_tag
                rec_out["ane_embedding"] = c_ane_vectors[i]
            out_rows.append(rec_out)

        part_path = parts_dir / f"part-{next_shard_idx:05d}.parquet"
        shard_tbl = _cast_results_arrow_table(out_rows)
        _write_table_atomic(shard_tbl, part_path, row_group_size=min(32768, max(1, len(out_rows))))

        for row in c_chunk:
            done_keys.add(str(row["_resume_key"]))
        docs_processed += n_c
        chunks_written += 1
        written_idx = next_shard_idx
        next_shard_idx += 1

        if _after_chunk_hook is not None:
            _after_chunk_hook(written_idx, part_path)

    try:
        def _iter_pending_chunks() -> Any:
            nonlocal global_row_cursor, docs_skipped_resume
            buf: list[dict[str, Any]] = []
            for fp in in_files:
                pf = pq.ParquetFile(fp)
                for rb in pf.iter_batches(batch_size=min(chunk_rows, 4096)):
                    for row in rb.to_pylist():
                        r_key = _row_resume_key(row, global_row_cursor)
                        global_row_cursor += 1
                        if r_key in done_keys:
                            docs_skipped_resume += 1
                            continue
                        row["_resume_key"] = r_key
                        buf.append(row)
                        if len(buf) >= chunk_rows:
                            yield buf
                            buf = []
            if buf:
                yield buf

        for chunk in _iter_pending_chunks():
            n_chunk = len(chunk)
            pmetas: list[dict[str, Any]] = []
            user_contents: list[str] = [""] * n_chunk
            active_indices: list[int] = []
            formatted_prompts: list[str] = []
            doc_target_kinds: dict[int, str] = {}

            for i, row in enumerate(chunk):
                known_str, pmeta, fn, raw_txt, _ = _build_precomputed_context_from_queue_row(row)
                pmetas.append(pmeta)
                if pmeta.get("triage") is not None:
                    triage_short_circuited_docs += 1
                    continue
                u_content = build_prompt_v4(known_str, fn, raw_txt)
                user_contents[i] = u_content
                p1_u_content = pass1_prompt_fn(known_str, fn, raw_txt)
                slot = len(active_indices)
                active_indices.append(i)
                formatted_prompts.append(_fmt_chat(p1_u_content))
                tk = pmeta.get("tier1_target_kind")
                if tk in DOC_KINDS_SET:
                    doc_target_kinds[slot] = str(tk)

            if owned_grammar_router is not None and active_indices:
                route_decisions = owned_grammar_router.route_chunk(chunk, pmetas)
                for slot_idx, orig_idx in enumerate(active_indices):
                    if slot_idx not in doc_target_kinds:
                        lspec = route_decisions[orig_idx].get("lock_spec")
                        if isinstance(lspec, str) and lspec:
                            doc_target_kinds[slot_idx] = lspec

            # Start optional background ANE search embedding co-execution (`Proposal B4`) concurrently with GPU decode!
            ane_vectors: list[list[float] | None] = [None] * n_chunk
            ane_err: list[BaseException] = []
            ane_thread: threading.Thread | None = None
            if ane_embedder is not None:
                embed_inputs = [
                    f"{row.get('filename') or ''}\n{str(row.get('p12_clean_text') or row.get('p12_raw_text') or row.get('text') or '')[:2200]}".strip()
                    for row in chunk
                ]

                def _bg_ane_worker(inp: list[str]) -> None:
                    try:
                        vecs = _encode_batch_pure_ane(ane_embedder, ane_model_tag, inp)
                        for idx_v, v in enumerate(vecs):
                            ane_vectors[idx_v] = v
                    except BaseException as exc:
                        ane_err.append(exc)

                ane_thread = threading.Thread(target=_bg_ane_worker, args=(embed_inputs,), name="docmeta-ane-b4")
                ane_thread.start()

            raw_llm_texts: list[str] = [""] * n_chunk
            out_tok_lens: list[int] = [0] * n_chunk
            n_act = len(active_indices)

            if n_act > 0:
                prompts_ids = [tok.encode(p, add_special_tokens=False) for p in formatted_prompts]
                total_prompt_tokens += sum(len(x) for x in prompts_ids)
                if n_act >= 2:
                    lcp = min(len(x) for x in prompts_ids)
                    for k_i in range(lcp):
                        if any(x[k_i] != prompts_ids[0][k_i] for x in prompts_ids[1:]):
                            lcp = k_i
                            break
                    sys_ids = prompts_ids[0][:lcp]
                else:
                    lcp = len(shared_sys_ids)
                    sys_ids = shared_sys_ids if prompts_ids[0][:lcp] == shared_sys_ids else []
                    lcp = len(sys_ids)

                std_up_ff = list(gh_std.upfront_ff)
                suf_ids = [x[lcp:] + std_up_ff for x in prompts_ids]
                eff_b = min(b_slots, n_act)
                doc_order = compute_rolling_doc_order(
                    suf_ids,
                    b_slots=eff_b,
                    sort_by_length=sort_by_length,
                )
                gh_dispatch: Any = (
                    per_doc_grammar_v6(
                        gh_std,
                        doc_order,
                        wire_format=pass1_wire,
                        doc_target_kinds=doc_target_kinds,
                        grammar_cache=kind_grammar_cache,
                        sync_ff_with_std=True,
                    )
                    if doc_target_kinds
                    else gh_std
                )
                # Pre-warm any new kind grammars before GPU timer starts
                if doc_target_kinds:
                    for tk_warm in set(doc_target_kinds.values()):
                        gh_dispatch.get_grammar_entry(tk_warm)

                res = engine.run_rolling(
                    sys_ids=sys_ids,
                    suf_ids_list=suf_ids,
                    schema_str=pass1_schema_str,
                    tok=tok,
                    max_tokens=max_tokens,
                    B_slots=eff_b,
                    refill_min=min(refill_min, n_act),
                    doc_cap_full=doc_cap_full,
                    swa_ring_cap=swa_ring_cap,
                    gh=gh_dispatch,
                    sort_by_length=sort_by_length,
                    use_ane_ring=use_ane_ring,
                )
                if doc_target_kinds:
                    assert gh_dispatch._cursor == n_act
                    assert set(gh_dispatch.dispatched_doc_indices) == set(range(n_act))

                for slot_i, gen_t in enumerate(res["gen_toks"]):
                    orig_idx = active_indices[slot_i]
                    full_t = std_up_ff + list(gen_t)
                    raw_llm_texts[orig_idx] = tok.decode(full_t, skip_special_tokens=True)
                    out_tok_lens[orig_idx] = len(full_t)
                    total_completion_tokens += len(full_t)

                total_decode_sec += float(res.get("decode_sec", 0.0))
                llm_decoded_docs += n_act

            if ane_thread is not None:
                ane_thread.join()
                if ane_err:
                    raise ane_err[0]
                ane_embedded_docs += sum(1 for v in ane_vectors if v is not None)

            # Post-pass V6 + deterministic diff logging + C0_Stdlib anomaly scoring
            clean_objs: list[dict[str, Any]] = []
            clean_texts: list[str] = []
            anomalies: list[dict[str, Any]] = []
            diffs_json: list[str] = []

            for i, (row, pmeta, raw_txt_out) in enumerate(zip(chunk, pmetas, raw_llm_texts)):
                fn = str(row.get("filename") or "")
                src_txt = str(row.get("p12_raw_text") or row.get("p12_clean_text") or row.get("text") or "")
                raw_ok = True
                salvaged = False
                if pmeta.get("triage") is not None:
                    parsed_raw: dict[str, Any] = dict(pmeta["triage"]["docmeta"])
                else:
                    try:
                        parsed_cand = json.loads(raw_txt_out)
                        if isinstance(parsed_cand, dict):
                            parsed_raw = expand_compact_v6_to_v4(parsed_cand) if is_compact_wire else parsed_cand
                        else:
                            raw_ok = False
                            salvaged = True
                            parsed_raw = _salvage_truncated_docmeta_v4(raw_txt_out, filename=fn)
                    except Exception:
                        raw_ok = False
                        salvaged = True
                        parsed_raw = _salvage_truncated_docmeta_v4(raw_txt_out, filename=fn)

                try:
                    clean_obj, sidecar = post_pass_v6(
                        parsed_raw,
                        known=pmeta.get("known_dict"),
                        filename=fn,
                        text=src_txt,
                        p12_lines=pmeta.get("p12_lines"),
                        explicit_format=row.get("effective_format") or row.get("format"),
                        pre_meta=pmeta,
                        provenance=pmeta.get("provenance"),
                        multipage=pmeta.get("multipage"),
                        triage=pmeta.get("triage"),
                        relational=pmeta.get("relational"),
                        citations=pmeta.get("citations"),
                        hygiene=pmeta.get("hygiene"),
                        usc_oracle=usc_oracle,
                    )
                    canon_obj = canonicalize_docmeta_v4(clean_obj)
                    ok_v4, _ = validate_docmeta_v4(canon_obj)
                except DocMetaValidationError:
                    ok_v4 = False
                    canon_obj = {}
                    sidecar = {}

                if not ok_v4:
                    # Guaranteed schema-valid fallback if model output or truncated salvage failed a constraint
                    fallback_triage = _build_triage_result(
                        "stub_or_blank",
                        "garbled",
                        f"Malformed 2B extraction output salvaged to non-usable triage ({fn[:60]})",
                    )
                    canon_obj, sidecar = post_pass_v6(
                        fallback_triage["docmeta"],
                        known=pmeta.get("known_dict"),
                        filename=fn,
                        text=src_txt,
                        p12_lines=pmeta.get("p12_lines"),
                        explicit_format=row.get("effective_format") or row.get("format"),
                        pre_meta=pmeta,
                        provenance=pmeta.get("provenance"),
                        multipage=pmeta.get("multipage"),
                        triage=fallback_triage,
                        relational=pmeta.get("relational"),
                        citations=pmeta.get("citations"),
                        hygiene=pmeta.get("hygiene"),
                        usc_oracle=usc_oracle,
                    )
                    ok_v4, _ = validate_docmeta_v4(canon_obj)

                diff_d = compute_llm_vs_det_diff_v6(
                    parsed_raw,
                    canon_obj,
                    row,
                    raw_valid_json=raw_ok,
                    salvaged_truncated=salvaged,
                )
                clean_objs.append(canon_obj)
                clean_texts.append(json.dumps(canon_obj, separators=(",", ":"), ensure_ascii=False))
                anomalies.append(dict(sidecar["anomaly_routing"]))
                diffs_json.append(json.dumps(diff_d, separators=(",", ":"), ensure_ascii=False))

            cur_ctx: dict[str, Any] = {
                "chunk": chunk,
                "pmetas": pmetas,
                "user_contents": user_contents,
                "out_tok_lens": out_tok_lens,
                "ane_vectors": ane_vectors,
                "clean_objs": clean_objs,
                "clean_texts": clean_texts,
                "anomalies": anomalies,
                "diffs_json": diffs_json,
            }

            if can_async_stage1:
                # 1. Flush previous chunk whose Pure-ANE Stage-1 ran in parallel with this chunk's Metal GPU decode!
                if pending_prev is not None:
                    if prev_stage1_thread is not None:
                        prev_stage1_thread.join()
                        prev_stage1_thread = None
                    if prev_stage1_err:
                        raise prev_stage1_err[0]
                    _finalize_and_write_chunk(pending_prev, prev_stage1_out[0] if prev_stage1_out else None)
                    pending_prev = None

                # 2. Launch this chunk's Pure-ANE Stage-1 (`0` GPU ops) so it overlaps with the NEXT chunk's GPU decode!
                prev_stage1_out = []
                prev_stage1_err = []

                def _bg_stage1_ane_worker(
                    objs_arg: list[dict[str, Any]],
                    chunk_arg: list[dict[str, Any]],
                    out_slot: list[dict[str, Any]],
                    err_slot: list[BaseException],
                ) -> None:
                    try:
                        out_slot.append(external_verifier.run_stage1_ane(objs_arg, chunk_arg))  # type: ignore[union-attr]
                    except BaseException as exc:
                        err_slot.append(exc)

                pending_prev = cur_ctx
                prev_stage1_thread = threading.Thread(
                    target=_bg_stage1_ane_worker,
                    args=(clean_objs, chunk, prev_stage1_out, prev_stage1_err),
                    name="docmeta-laya-ane-stage1",
                )
                prev_stage1_thread.start()
            else:
                _finalize_and_write_chunk(cur_ctx, None)

        if pending_prev is not None:
            if prev_stage1_thread is not None:
                prev_stage1_thread.join()
                prev_stage1_thread = None
            if prev_stage1_err:
                raise prev_stage1_err[0]
            _finalize_and_write_chunk(pending_prev, prev_stage1_out[0] if prev_stage1_out else None)
            pending_prev = None

        # If caller requested a single `.parquet` output file, seal all parts atomically with `row_group_size=32768`
        if seal_single_file:
            all_part_files = sorted(parts_dir.glob("part-*.parquet"))
            if all_part_files:
                tables = [pq.read_table(pf_p) for pf_p in all_part_files]
                merged = pa.concat_tables(tables, promote_options="default")
                _write_table_atomic(merged, out_target, row_group_size=32768)

    finally:
        # Join any in-flight ANE worker BEFORE closing CoreML handles (`laya_ane_free`)
        if prev_stage1_thread is not None and prev_stage1_thread.is_alive():
            prev_stage1_thread.join()
        if owned_grammar_router is not None and hasattr(owned_grammar_router, "close"):
            owned_grammar_router.close()
        if owned_atomic_verifier is not None and hasattr(owned_atomic_verifier, "close"):
            owned_atomic_verifier.close()
        if owned_gpt_oss and gpt_oss_engine is not None and hasattr(gpt_oss_engine, "close"):
            gpt_oss_engine.close()

    elapsed = time.perf_counter() - t0
    return DocMetaSweepSummary(
        docs_processed=docs_processed,
        docs_skipped_resume=docs_skipped_resume,
        llm_decoded_docs=llm_decoded_docs,
        triage_short_circuited_docs=triage_short_circuited_docs,
        strict_v4_valid_docs=strict_v4_valid_docs,
        anomaly_flagged_docs=anomaly_flagged_docs,
        pass2_escalated_docs=pass2_escalated_docs,
        pass2_accepted_docs=pass2_accepted_docs,
        ane_embedded_docs=ane_embedded_docs,
        chunks_written=chunks_written,
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        elapsed_sec=elapsed,
        docs_per_sec=docs_processed / elapsed if elapsed > 0 else 0.0,
        decode_tok_s=total_completion_tokens / total_decode_sec if total_decode_sec > 0 else 0.0,
        output_path=out_target,
        parts_dir=parts_dir,
    )


__all__ = [
    "DocMetaSweepSummary",
    "ExternalVerifierFn",
    "build_excluded_kind_schema_v6",
    "compute_llm_vs_det_diff_v6",
    "escalate_anomalies_gpt_oss",
    "run_docmeta_parquet_sweep",
]
