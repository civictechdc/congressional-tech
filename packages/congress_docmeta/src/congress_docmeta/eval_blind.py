#!/usr/bin/env python3
"""Blind end-to-end DocMeta eval for a packed/fused Gemma-4 checkpoint.

Runs the production `PythonicEngineV6.run_records` path (pre-pass, grammar-locked decode, post-pass)
on three held-out sets and scores the final `DocMetaV4Causal` objects against gold:

  val48        eval_val48_v4_gold.json (48 stratified blind docs), via `PythonicEngineV6.run_records`
  docs8        eval_docs8_v4_gold.json (8 stress-test docs), via `run_records`
  valid_sweep  the split `gold.select_val_indices` holds out of the V6.4 gold, via `run_docmeta_parquet_sweep`
  val48_sweep  the val48 docs present in the sweep queue, via `run_docmeta_parquet_sweep`

The `*_sweep` sets feed the model the queue rows the production sweep will feed it, through the sweep's own
code path. `--llm-only` turns the deterministic pre/post rules off for the `run_records` sets.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import time
from typing import Any

from .gold import (
    DEFAULT_DOCS8_JSON,
    DEFAULT_GOLD_JSONL,
    DEFAULT_QUEUE_PARQUET,
    DEFAULT_VAL48_JSON,
    head_tail_window_chars,
    load_queue_rows,
    parse_gold_rows,
    select_val_indices,
)

KIND_FAMILIES = {
    "qfr_request": "qfr",
    "qfr_response": "qfr",
    "witness_statement": "statement",
    "member_opening_statement": "statement",
    "member_or_floor_statement": "statement",
    "hearing_notice": "notice",
    "markup_notice": "notice",
    "committee_vote": "vote_or_results",
    "meeting_results": "vote_or_results",
    "oversight_letter": "letter_or_submission",
    "witness_invitation": "letter_or_submission",
    "nomination_or_support_letter": "letter_or_submission",
    "external_submission_letter": "letter_or_submission",
    "public_comment_or_submission": "letter_or_submission",
    "agency_or_gao_crs_report": "report",
    "external_report_or_whitepaper": "report",
    "committee_report": "report",
    "bill_or_draft": "legislative_text",
    "committee_amendment": "legislative_text",
    "comparative_print": "legislative_text",
    "section_by_section": "legislative_text",
    "explanatory_statement": "legislative_text",
    "investigative_exhibit": "investigative",
    "legal_or_investigative_filing": "investigative",
}
SCALAR_KEYS = ("status", "text_quality", "chamber", "congress", "event_type", "primary_kind", "correspondence_flow")
LIST_KEYS = ("subcommittees", "secondary_kinds", "short_titles", "refs", "fiscal_years", "topics")
DATE_KEYS = ("doc_date", "event_date", "due_date")

_CMT_STOP_RE = re.compile(
    r"\b(u\.?s\.?|united states|house|senate|committee|on|the|of|and|select|permanent|special)\b"
)
_HONORIFIC_RE = re.compile(
    r"\b(Jr\.?|Sr\.?|II|III|IV|M\.?D\.?|Ph\.?D\.?|Esq\.?|Hon\.?|Rep\.?|Sen\.?|Mr\.?|Ms\.?|Mrs\.?|Dr\.?)\b", re.I
)


def norm_cmt(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _CMT_STOP_RE.sub(" ", c.lower())).strip()


def surname_of(name: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z'-]+", _HONORIFIC_RE.sub("", name)) if len(p) > 1]
    return parts[-1].lower() if parts else name.lower().strip()


def _norm_str(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x)).strip().lower()


class _F1:
    def __init__(self) -> None:
        self.tp = self.p = self.g = 0

    def add(self, pred: set, gold: set) -> None:
        self.tp += len(pred & gold)
        self.p += len(pred)
        self.g += len(gold)

    def value(self) -> float:
        return 100.0 if self.p + self.g == 0 else round(200.0 * self.tp / (self.p + self.g), 1)


def work_addr_match(pred: str, gold: str) -> bool:
    """Same office: the street / room / box number and the ZIP agree where both sides give one; a gold address with
    no number ("Los Angeles, CA") is matched by any address that says at least that. "N.W." and "NW" are one."""
    p_tok, g_tok = (re.findall(r"[a-z0-9]+", re.sub(r"(?<=\b[a-z])\.", "", a.lower())) for a in (pred, gold))
    p_num, g_num = (next((t for t in toks if t[0].isdigit()), None) for toks in (p_tok, g_tok))
    if g_num is None:
        return set(g_tok) <= set(p_tok)
    p_zip, g_zip = (next((t for t in reversed(toks) if re.fullmatch(r"\d{5}", t)), None) for toks in (p_tok, g_tok))
    return p_num == g_num and (p_zip == g_zip or p_zip is None or g_zip is None)


def _personas(obj: dict[str, Any]) -> list[dict[str, Any]]:
    raw = obj.get("personas")
    return [p for p in (raw if isinstance(raw, list) else []) if isinstance(p, dict) and str(p.get("name") or "").strip()]


def score(objs: list[dict[str, Any] | None], golds: list[dict[str, Any]], valid_flags: list[bool]) -> dict[str, Any]:
    """Score final V4 objects against gold. Missing scalar keys count as wrong only when gold has the key."""
    n = len(golds)
    hit: Counter[str] = Counter()
    tot: Counter[str] = Counter()
    f1 = {k: _F1() for k in ("committees", "dates", "personas_name", "personas_name_role", "personas_name_etype", *LIST_KEYS)}
    kind_family = other = roster_spam = 0
    addr: Counter[str] = Counter()
    per_doc: list[dict[str, Any]] = []

    for obj_raw, gold in zip(objs, golds):
        obj = obj_raw if isinstance(obj_raw, dict) else {}
        for k in SCALAR_KEYS:
            if k in gold:
                tot[k] += 1
                hit[k] += int(obj.get(k) == gold[k])
        pk_p, pk_g = obj.get("primary_kind"), gold.get("primary_kind")
        other += int(pk_p == "other")
        if pk_g is not None:
            kind_family += int(pk_p == pk_g or KIND_FAMILIES.get(pk_p, pk_p) == KIND_FAMILIES.get(pk_g, pk_g))

        f1["committees"].add(
            {norm_cmt(x) for x in obj.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
            {norm_cmt(x) for x in gold.get("committees") or [] if isinstance(x, str) and norm_cmt(x)},
        )
        f1["dates"].add(
            {str(obj[k]) for k in DATE_KEYS if obj.get(k) not in (None, "", "N/A")},
            {str(gold[k]) for k in DATE_KEYS if gold.get(k) not in (None, "", "N/A")},
        )
        for k in LIST_KEYS:
            f1[k].add(
                {_norm_str(x) for x in obj.get(k) or [] if isinstance(x, (str, int))},
                {_norm_str(x) for x in gold.get(k) or [] if isinstance(x, (str, int))},
            )

        p_pers, g_pers = _personas(obj), _personas(gold)
        roster_spam += int(len(p_pers) > 10 or (pk_g == "committee_vote" and len(p_pers) > 4))
        f1["personas_name"].add({surname_of(p["name"]) for p in p_pers}, {surname_of(str(p["name"])) for p in g_pers})
        f1["personas_name_role"].add(
            {(surname_of(p["name"]), str(p.get("role"))) for p in p_pers},
            {(surname_of(str(p["name"])), str(p.get("role"))) for p in g_pers},
        )
        f1["personas_name_etype"].add(
            {(surname_of(p["name"]), str(p.get("entity_type"))) for p in p_pers},
            {(surname_of(str(p["name"])), str(p.get("entity_type"))) for p in g_pers},
        )
        # `work_addr`, person by person. Gold leaves it blank for many people whose office the text prints, so a
        # predicted address on a gold-blank person is counted apart: gold can neither confirm nor refute it.
        g_addr = {surname_of(str(p["name"])): str(p["work_addr"]) for p in g_pers if p.get("work_addr")}
        p_addr = {surname_of(p["name"]): str(p["work_addr"]) for p in p_pers if p.get("work_addr")}
        addr["gold"] += len(g_addr)
        addr["pred"] += len(p_addr)
        addr["matched"] += sum(1 for k, a in p_addr.items() if k in g_addr and work_addr_match(a, g_addr[k]))
        addr["pred_gold_has"] += sum(1 for k in p_addr if k in g_addr)
        per_doc.append({"gold_kind": pk_g, "pred_kind": pk_p, "kind_ok": pk_p == pk_g})

    def pct(a: int, b: int) -> float:
        return round(100.0 * a / max(b, 1), 1)

    metrics: dict[str, Any] = {
        "n": n,
        "strict_valid_pct": pct(sum(valid_flags), n),
        **{f"{k}_acc": pct(hit[k], tot[k]) for k in SCALAR_KEYS},
        "primary_kind_family_acc": pct(kind_family, tot["primary_kind"]),
        **{f"{k}_f1": v.value() for k, v in f1.items()},
        "other_count": other,
        "roster_spam_docs": roster_spam,
        # Not in the headline. recall = gold addresses found; precision counts a gold-blank person as wrong;
        # agreement is precision over the people gold does give an address for.
        "work_addr_gold": addr["gold"],
        "work_addr_pred": addr["pred"],
        "work_addr_matched": addr["matched"],
        "work_addr_recall": pct(addr["matched"], addr["gold"]),
        "work_addr_precision": pct(addr["matched"], addr["pred"]),
        "work_addr_agreement": pct(addr["matched"], addr["pred_gold_has"]),
        "work_addr_pred_gold_blank": addr["pred"] - addr["pred_gold_has"],
    }
    # One headline number: mean of the fields a reader actually searches by.
    headline = (
        "primary_kind_acc", "status_acc", "chamber_acc", "congress_acc", "committees_f1",
        "dates_f1", "personas_name_f1", "personas_name_role_f1",
    )
    metrics["headline_mean"] = round(sum(float(metrics[k]) for k in headline) / len(headline), 2)
    return {"metrics": metrics, "per_doc": per_doc}


def load_record_sets(names: list[str]) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    out: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for name, path in (("val48", DEFAULT_VAL48_JSON), ("docs8", DEFAULT_DOCS8_JSON)):
        if name in names:
            rows = json.loads(path.read_text(encoding="utf-8"))
            recs = [
                {"known": r.get("known", "<NONE>"), "filename": r.get("filename", ""), "text": r.get("text") or "",
                 "format": r.get("format")}
                for r in rows
            ]
            out[name] = (recs, [r["gold"] for r in rows])
    return out


def load_sweep_sets(
    names: list[str], gold_jsonl: Path, extra: dict[str, Path] | None = None
) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """`name -> (queue rows, golds)` for the held-out docs the sweep queue contains.

    `extra` adds whole labeled files as their own sets (every row that is in the queue), for gold that was
    never trained on or was split off before training.
    """
    out: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for name, path in (extra or {}).items():
        rows = [r for r in parse_gold_rows(path, (DEFAULT_VAL48_JSON, DEFAULT_DOCS8_JSON))[0] if r["queue_row"] is not None]
        out[name] = ([r["queue_row"] for r in rows], [r["gold_v4"] for r in rows])
    if "valid_sweep" in names:
        parsed, _ = parse_gold_rows(gold_jsonl, (DEFAULT_VAL48_JSON, DEFAULT_DOCS8_JSON))
        val_idx, _ = select_val_indices(parsed)
        rows = [parsed[i] for i in sorted(val_idx) if parsed[i]["queue_row"] is not None]
        out["valid_sweep"] = ([r["queue_row"] for r in rows], [r["gold_v4"] for r in rows])
    if "val48_sweep" in names:
        v48 = json.loads(DEFAULT_VAL48_JSON.read_text(encoding="utf-8"))
        by_sha = load_queue_rows(DEFAULT_QUEUE_PARQUET, {str(r["body_sha"]) for r in v48}, "saved_body_hex")
        hits = [r for r in v48 if str(r["body_sha"]) in by_sha]
        out["val48_sweep"] = ([by_sha[str(r["body_sha"])] for r in hits], [r["gold"] for r in hits])
    return out


def run_sweep_sets(
    eng: Any, sets: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]], args: argparse.Namespace
) -> dict[str, dict[str, Any]]:
    """One pass of the real sweep over every set's queue rows, scored per set."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    from .parquet_runner_v6 import run_docmeta_parquet_sweep

    all_rows = {str(r["link_key_hex"]): r for rows, _ in sets.values() for r in rows}
    with tempfile.TemporaryDirectory(prefix="docmeta_eval_") as td:
        in_p, out_p = Path(td) / "in.parquet", Path(td) / "out.parquet"
        pq.write_table(pa.Table.from_pylist(list(all_rows.values())), in_p)
        summary = run_docmeta_parquet_sweep(
            eng, in_p, out_p, b_slots=args.b_slots, max_tokens=args.max_tokens,
            use_ane_ring="auto" if args.ane_ring else False,
            wire_format=args.wire_format, atomic_verifier=args.atomic_verifier,
            repair_persona_roles=args.repair_persona_roles, escalate_gpt_oss=args.escalate_gpt_oss,
        )
        out_rows = {str(r["link_key_hex"]): r for r in pq.read_table(out_p).to_pylist()}

    results: dict[str, dict[str, Any]] = {}
    for name, (rows, golds) in sets.items():
        outs = [out_rows.get(str(r["link_key_hex"])) or {} for r in rows]
        objs = [json.loads(o["docmeta_json"]) if o.get("docmeta_json") else None for o in outs]
        scored = score(objs, golds, [bool(o.get("strict_v4_valid")) for o in outs])
        toks = [int(o.get("completion_tokens") or 0) for o in outs]
        toks = [t for t in toks if t]
        scored["metrics"].update(
            {
                "llm_docs": len(toks),
                "avg_out_tok": round(sum(toks) / max(len(toks), 1), 1),
                "truncated_docs": sum(1 for t in toks if t >= args.max_tokens),
                "anomaly_flagged": sum(1 for o in outs if o.get("needs_teacher_escalation")),
            }
        )
        for d, r, o in zip(scored["per_doc"], rows, objs):
            d["filename"] = r.get("filename")
            d["link_key_hex"] = r.get("link_key_hex")
            d["pred"] = o
        results[name] = scored
    sweep_stats = {
        "docs": summary.docs_processed,
        "elapsed_sec": round(summary.elapsed_sec, 1),
        "docs_per_sec": round(summary.docs_per_sec, 3),
        "decode_tok_s": round(summary.decode_tok_s, 1),
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "pass2_escalated": summary.pass2_escalated_docs,
        "pass2_accepted": summary.pass2_accepted_docs,
        # None means the ring did not engage (off, or its bundle was missing or not fully on the ANE): a ring-on
        # run that fell back to GPU only would otherwise look like perfect parity.
        "ane_ring_bundle": f"{bundle.parent.name}/{bundle.name}" if (bundle := eng.ane_ring_bundle) else None,
    }
    for scored in results.values():
        scored["sweep"] = sweep_stats
    return results


def rescore(report_path: Path, out_path: Path, gold_jsonl: Path, label: str | None) -> int:
    """Score an earlier report's saved predictions again, so a metric added later can be read off an old run."""
    from . import strict_validate_v4

    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = list(report["sets"])
    golds = {**load_record_sets(names), **load_sweep_sets(names, gold_jsonl)}
    for name, old in report["sets"].items():
        objs = [d.get("pred") for d in old["per_doc"]]
        assert len(objs) == len(golds[name][1]), f"{name}: the gold set changed size since {report_path}"
        valid = [bool(strict_validate_v4(o)[0]) if isinstance(o, dict) else False for o in objs]
        fresh = score(objs, golds[name][1], valid)
        moved = {k: (old["metrics"][k], v) for k, v in fresh["metrics"].items() if old["metrics"].get(k, v) != v}
        if moved:
            print(f"[{name}] metrics that differ from the saved report (old, new): {moved}")
        old["metrics"].update(fresh["metrics"])
    if label:
        report["label"] = label
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, default=None, help="required unless --rescore")
    ap.add_argument("--label", default=None)
    ap.add_argument("--wire-format", choices=("auto", "v4", "compact"), default="auto")
    ap.add_argument("--sets", default="val48,docs8,valid_sweep,val48_sweep")
    ap.add_argument("--extra-sweep-set", action="append", default=[], metavar="NAME=GOLD_JSONL",
                    help="score every queue doc of another labeled file as its own sweep set (repeatable)")
    ap.add_argument("--gold-jsonl", type=Path, default=DEFAULT_GOLD_JSONL)
    ap.add_argument("--max-tokens", type=int, default=768)
    ap.add_argument("--b-slots", type=int, default=64)
    ap.add_argument("--max-chars", type=int, default=9000, help="head/tail char window applied to every doc text")
    ap.add_argument("--llm-only", action="store_true", help="disable deterministic pre/post rules")
    ap.add_argument("--atomic-verifier", choices=("none", "laya-ane", "kev-0.8b", "both"), default="none",
                    help="post-LLM output validator for the *_sweep sets")
    ap.add_argument("--repair-persona-roles", action="store_true", help="let the validator repair suspect roles")
    ap.add_argument("--ane-ring", action="store_true", help="hybrid ANE prefill ring for the *_sweep sets")
    ap.add_argument("--escalate-gpt-oss", action="store_true",
                    help="send anomaly-flagged docs to the fast-gpt-oss Pass-2 teacher (*_sweep sets)")
    ap.add_argument("--ane-variant", choices=("w8", "fp16"), default="w8", help="bundle the ring runs")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rescore", type=Path, default=None,
                    help="re-score the saved predictions of an earlier report with this script's metrics; no model run")
    args = ap.parse_args()
    if args.rescore is not None:
        return rescore(args.rescore, args.out, args.gold_jsonl, args.label)
    if args.model_dir is None:
        ap.error("--model-dir is required unless --rescore is given")

    from fast_gemma4 import FastGemma4Engine
    from . import PythonicEngineV6, strict_validate_v4

    names = [s.strip() for s in args.sets.split(",") if s.strip()]
    sets = load_record_sets(names)
    extra_sets = dict(item.split("=", 1) for item in args.extra_sweep_set)
    sweep_sets = load_sweep_sets(names, args.gold_jsonl, {k: Path(v) for k, v in extra_sets.items()})
    eng = FastGemma4Engine(
        model_dir=args.model_dir, default_mode="auto" if args.ane_ring else "gpu", ane_variant=args.ane_variant,
        ane_ring_variant=args.ane_variant,
        warmup=True,
        warmup_ane=args.ane_ring,
    )
    pe = PythonicEngineV6(eng, wire_format=args.wire_format)
    rule_flags = {
        k: not args.llm_only
        for k in (
            "use_provenance", "use_multipage", "use_provenance_link_anchor", "use_hygiene", "use_cover_locks",
            "use_citations", "use_relational", "use_zero_llm_bypass", "short_circuit_triage",
        )
    }

    report: dict[str, Any] = {
        "label": args.label or args.model_dir.name,
        "model_dir": str(args.model_dir),
        "wire_format": pe.wire_format,
        "llm_only": args.llm_only,
        "atomic_verifier": args.atomic_verifier,
        "repair_persona_roles": args.repair_persona_roles,
        "max_tokens": args.max_tokens,
        "sets": {},
    }
    try:
        for name, (recs, golds) in sets.items():
            for r in recs:
                r["text"] = head_tail_window_chars(r["text"], args.max_chars)
            t0 = time.perf_counter()
            res = pe.run_records(recs, max_tokens=args.max_tokens, B_slots=args.b_slots, **rule_flags)
            wall = time.perf_counter() - t0
            objs = res["clean_objs"]
            valid = [bool(strict_validate_v4(o)[0]) if isinstance(o, dict) else False for o in objs]
            scored = score(objs, golds, valid)
            llm_n = len(recs) - len(res["zero_llm_bypassed_indices"]) - len(res["triage_short_circuited_indices"])
            toks = [t for t in res["out_tok_lens"] if t]
            scored["metrics"].update(
                {
                    "wall_sec": round(wall, 1),
                    "docs_per_sec": round(len(recs) / wall, 3),
                    "llm_docs": llm_n,
                    "avg_out_tok": round(sum(toks) / max(len(toks), 1), 1),
                    "truncated_docs": sum(1 for t in toks if t >= args.max_tokens),
                    "mask_fallbacks": res["mask_fallbacks"],
                }
            )
            for d, r, o in zip(scored["per_doc"], recs, objs):
                d["filename"] = r["filename"]
                d["pred"] = o
            report["sets"][name] = scored
            print(f"[{report['label']}] {name}: {json.dumps(scored['metrics'])}", flush=True)
        if sweep_sets:
            for name, scored in run_sweep_sets(eng, sweep_sets, args).items():
                report["sets"][name] = scored
                print(f"[{report['label']}] {name}: {json.dumps(scored['metrics'])} {json.dumps(scored['sweep'])}", flush=True)
    finally:
        eng.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
