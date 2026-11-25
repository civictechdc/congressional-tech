#!/usr/bin/env python3
"""Real-archive Org Entities Phase 1 build, 150-group AC #4 sampling & 3-family triage (ct-6him)."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


DEFAULT_WITNESSES = Path(
    ".cache/archive-release/published-releases/"
    "0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3/witnesses.parquet"
)
DEFAULT_PLANNER_SAMPLE = Path(
    ".cache/archive-release/investigations/entity-matching-measure-20261108/fuzzy_bag_groups_sample_L2.txt"
)
DEFAULT_OUT_DIR = Path(".cache/archive-release/org-entities-phase1-ac4-20261122")

AC4_SCHEMA: dict[str, Any] = {
    "title": "OrgBagMergeVerdict",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["valid_merge", "wrong_merge"],
        },
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "rationale"],
}


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for anc in here.parents:
        if (anc / "pyproject.toml").is_file() and (anc / "model" / "sql").is_dir():
            return anc
    return here.parents[2]


def _load_planner_l2_groups(path: Path) -> list[set[str]]:
    groups: list[set[str]] = []
    if not path.is_file():
        return groups
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = {p.strip().casefold() for p in line.split("||") if p.strip()}
        if len(parts) >= 2:
            groups.append(parts)
    return groups


def _query_org_strings_via_docspec(
    *,
    witnesses_path: Path,
    engine: Any,
    scratch_dir: Path,
    out_parquet: Path,
    root: Path,
) -> Path:
    """Execute the exact `model/sql/org-strings.sql` logic on pinned docspec to recover L2 variants per bag."""
    from congress_api.retention.provenance import run_job

    job_scratch = scratch_dir / "org_strings_only"
    job_scratch.mkdir(parents=True, exist_ok=True)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    inputs = [
        {
            "name": "appearance_records_resolved",
            "kind": "parquet",
            "path": str(witnesses_path.resolve()),
        }
    ]
    steps = [
        {
            "name": "org_strings",
            "sql": (root / "model" / "sql" / "org-strings.sql").read_text(encoding="utf-8"),
            "materialize": True,
        }
    ]
    outputs = [
        {
            "name": "org_strings",
            "path": str(out_parquet.resolve()),
            "sql": (
                "SELECT string_key, l2_text, display_text, bag_key, bag_text, "
                "appearance_count, raw_texts "
                "FROM org_strings ORDER BY appearance_count DESC, string_key ASC"
            ),
        }
    ]
    run_job(job_scratch, engine, inputs=inputs, steps=steps, outputs=outputs, queries=[])
    return out_parquet


def run_build_and_sample(
    *,
    witnesses_path: Path,
    out_dir: Path,
    planner_sample_path: Path,
    engine_config_path: Path | None = None,
    sample_size: int = 150,
    seed: int = 20261122,
) -> dict[str, Any]:
    """Run real-archive `build_org_entities`, exclude the 60 planner groups, and draw 150 fresh multi-string bags."""
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import build_org_entities

    root = _repo_root()
    cfg_path = engine_config_path or Path(
        os.environ.get("DOCSPEC_JOB_CONFIG") or (root / ".cache" / "local-runtime" / "runtime.json")
    )
    engine = NativeDatasets.from_config(str(cfg_path))

    out_dir = out_dir.resolve()
    release_dir = out_dir / "release"
    scratch_dir = out_dir / "scratch"
    shutil.rmtree(release_dir, ignore_errors=True)
    shutil.rmtree(scratch_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[ac4] Running build_org_entities on {witnesses_path} ...", file=sys.stderr, flush=True)
    build_res = build_org_entities(
        appearance_records_resolved=witnesses_path,
        engine=engine,
        output=release_dir,
        scratch=scratch_dir,
        release_label="ac4-real-archive",
        root=root,
    )

    org_strings_pq = release_dir / "org_strings.parquet"
    if not org_strings_pq.is_file():
        raise FileNotFoundError(f"Expected build_org_entities output {org_strings_pq}")

    # Load org_strings.parquet and group by bag_key to isolate true multi-string bag_keys.
    os_table = pq.read_table(org_strings_pq)
    by_bag: dict[str, dict[str, Any]] = {}
    for row in os_table.to_pylist():
        bk = str(row["bag_key"])
        entry = by_bag.setdefault(
            bk,
            {
                "bag_key": bk,
                "bag_text": row["bag_text"],
                "l2_variants": [],
                "raw_texts": [],
                "string_keys": [],
                "total_mentions": 0,
            },
        )
        entry["l2_variants"].append(
            {
                "string_key": row["string_key"],
                "l2_text": row["l2_text"],
                "display_text": row["display_text"],
                "appearance_count": int(row["appearance_count"]),
                "raw_texts": list(row["raw_texts"] or []),
            }
        )
        entry["string_keys"].append(row["string_key"])
        entry["total_mentions"] += int(row["appearance_count"])
        for rt in row["raw_texts"] or []:
            if rt not in entry["raw_texts"]:
                entry["raw_texts"].append(rt)

    all_multi_bags = [g for g in by_bag.values() if len(g["l2_variants"]) >= 2]

    # Map published organizations & distinct witness counts per bag_key.
    orgs_table = pq.read_table(
        release_dir / "organizations.parquet",
        columns=["org_id", "display_name", "kind", "taxonomy_parent", "taxonomy_category", "appearance_count", "bag_keys", "string_keys"],
    )
    org_by_bag: dict[str, dict[str, Any]] = {}
    taxonomy_parent_counts: Counter[str] = Counter()
    taxonomy_cat_counts: Counter[str] = Counter()
    for o in orgs_table.to_pylist():
        taxonomy_parent_counts[str(o.get("taxonomy_parent") or "UNCLASSIFIED")] += 1
        taxonomy_cat_counts[str(o.get("taxonomy_category") or "UNCLASSIFIED")] += 1
        for bk in o.get("bag_keys") or []:
            org_by_bag[str(bk)] = {
                "org_id": o["org_id"],
                "display_name": o["display_name"],
                "kind": o["kind"],
                "taxonomy_parent": o["taxonomy_parent"],
                "taxonomy_category": o["taxonomy_category"],
                "org_appearance_count": int(o["appearance_count"]),
            }

    # Exclude all groups matching the 60 planner fuzzy_bag_groups_sample_L2.txt sets.
    planner_sets = _load_planner_l2_groups(planner_sample_path)
    planner_exact_frozen = {frozenset(s) for s in planner_sets}
    eligible: list[dict[str, Any]] = []
    excluded_planner_bags: list[str] = []

    for g in all_multi_bags:
        l2_set = {v["l2_text"].strip().casefold() for v in g["l2_variants"] if v.get("l2_text")}
        is_planner = frozenset(l2_set) in planner_exact_frozen or any(
            len(l2_set & ps) >= 2 for ps in planner_sets
        )
        if is_planner:
            excluded_planner_bags.append(g["bag_key"])
            continue
        org_meta = org_by_bag.get(g["bag_key"], {})
        enriched = {
            **g,
            "org_id": org_meta.get("org_id"),
            "display_name": org_meta.get("display_name"),
            "kind": org_meta.get("kind"),
            "taxonomy_parent": org_meta.get("taxonomy_parent"),
            "taxonomy_category": org_meta.get("taxonomy_category"),
            "appearance_count": org_meta.get("org_appearance_count") or g["total_mentions"],
        }
        eligible.append(enriched)

    # Deterministic stratification by appearance_count terciles (high / medium / low).
    eligible.sort(key=lambda x: (-int(x["appearance_count"]), x["bag_key"]))
    n_elig = len(eligible)
    if n_elig < sample_size:
        raise ValueError(f"Only {n_elig} eligible fresh multi-string bag groups < sample_size={sample_size}")

    t1 = n_elig // 3
    t2 = (2 * n_elig) // 3
    tiers = [
        ("high_appearances", eligible[:t1]),
        ("medium_appearances", eligible[t1:t2]),
        ("low_appearances", eligible[t2:]),
    ]
    rng = random.Random(seed)
    per_tier = sample_size // len(tiers)
    remainder = sample_size % len(tiers)

    sampled: list[dict[str, Any]] = []
    for idx, (tier_name, pool) in enumerate(tiers):
        k = per_tier + (1 if idx < remainder else 0)
        chosen = rng.sample(pool, k) if len(pool) >= k else list(pool)
        for item in chosen:
            item["stratum"] = tier_name
            sampled.append(item)

    # Attach sample witness appearances from witness_organizations + witnesses.parquet for raw context.
    sampled_bags = {item["bag_key"] for item in sampled}
    wo_table = pq.read_table(
        release_dir / "witness_organizations.parquet",
        columns=["witness_key", "field", "bag_key", "string_key", "raw_text"],
    )
    wkeys_by_bag: dict[str, dict[str, dict[str, Any]]] = {bk: {} for bk in sampled_bags}
    wanted_wkeys: set[str] = set()
    for row in wo_table.to_pylist():
        bk = str(row["bag_key"])
        if bk not in sampled_bags:
            continue
        wk = str(row["witness_key"])
        bag_w = wkeys_by_bag[bk]
        if wk not in bag_w and len(bag_w) < 12:
            bag_w[wk] = {"witness_key": wk, "field": row["field"], "raw_text": row["raw_text"], "string_key": row["string_key"]}
            wanted_wkeys.add(wk)

    w_meta: dict[str, dict[str, Any]] = {}
    w_table = pq.read_table(
        witnesses_path,
        columns=["witness_key", "name", "position", "organization", "on_behalf_of", "location", "witness_type", "event_id"],
    )
    for row in w_table.to_pylist():
        wk = str(row["witness_key"])
        if wk in wanted_wkeys:
            w_meta[wk] = {
                "name": row.get("name"),
                "position": row.get("position"),
                "organization": row.get("organization"),
                "on_behalf_of": row.get("on_behalf_of"),
                "location": row.get("location"),
                "witness_type": row.get("witness_type"),
                "event_id": row.get("event_id"),
            }

    for item in sampled:
        bk = item["bag_key"]
        samples: list[dict[str, Any]] = []
        seen_raw_loc: set[tuple[str | None, str | None]] = set()
        for wk, link_info in wkeys_by_bag[bk].items():
            meta = w_meta.get(wk, {})
            key = (link_info.get("raw_text"), meta.get("location"))
            if key in seen_raw_loc and len(samples) >= 4:
                continue
            seen_raw_loc.add(key)
            samples.append({**link_info, **meta})
            if len(samples) >= 6:
                break
        item["witness_samples"] = samples

    sampled.sort(key=lambda x: (-int(x["appearance_count"]), x["bag_key"]))
    sample_path = out_dir / "sample_150_bag_groups.jsonl"
    with sample_path.open("w", encoding="utf-8") as fh:
        for idx, item in enumerate(sampled, start=1):
            rec = {"sample_index": idx, **item}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    build_stats = {
        "witnesses_path": str(witnesses_path),
        "witness_rows": pq.read_metadata(witnesses_path).num_rows,
        "organizations_count": orgs_table.num_rows,
        "distinct_org_strings": os_table.num_rows,
        "distinct_bags": len(by_bag),
        "multi_string_bags_total": len(all_multi_bags),
        "excluded_planner_sample_groups": len(excluded_planner_bags),
        "eligible_fresh_multi_string_bags": len(eligible),
        "sampled_count": len(sampled),
        "sampled_tiers": dict(Counter(item["stratum"] for item in sampled)),
        "build_invariants": build_res["invariants"],
        "org_fuzzy_candidate_stats": build_res["stats"],
        "taxonomy_parent_counts": dict(taxonomy_parent_counts.most_common()),
        "taxonomy_category_counts": dict(taxonomy_cat_counts.most_common()),
        "sample_path": str(sample_path),
    }
    stats_path = out_dir / "build_stats.json"
    stats_path.write_text(json.dumps(build_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(build_stats, indent=2), flush=True)
    return build_stats


def _render_ac4_prompt(group: dict[str, Any]) -> str:
    l2_lines = "\n".join(
        f"  - [{v['appearance_count']}x] l2={v['l2_text']!r} | raw_samples={v['raw_texts'][:3]}"
        for v in group.get("l2_variants", [])
    )
    w_lines = "\n".join(
        f"  - field={w.get('field')} | raw={w.get('raw_text')!r} | loc={w.get('location')!r} | pos={w.get('position')!r} | type={w.get('witness_type')!r}"
        for w in group.get("witness_samples", [])[:6]
    )
    return (
        "You are auditing organization entity resolution token-bag automatic merges (ct-6him AC #4).\n"
        "All normalized L2 strings listed below share the EXACT SAME sorted non-stopword token bag "
        "(order/punctuation/stopword differences only, trailing state/city stripped when guarded) and were auto-merged into ONE organization.\n\n"
        "Decide whether merging these strings into a SINGLE organization entity is:\n"
        "- `valid_merge`: same real-world organization (word order, comma/of/at/and variation, trailing location, minor punctuation/apostrophe differences).\n"
        "- `wrong_merge`: genuinely DIFFERENT organizations accidentally colliding under the same word bag "
        "(e.g., 'Virginia Council' vs another state if ever conflated, unrelated anagrams like 'American Health Care' vs 'Health Care America' referencing distinct entities, "
        "different divisions/chapters, or location-stripping bug collapsing two distinct places/groups).\n\n"
        f"Group bag_key={group['bag_key']} | total_appearances={group['appearance_count']} | stratum={group.get('stratum')}\n"
        f"Merged L2 Variants ({len(group.get('l2_variants', []))}):\n{l2_lines}\n\n"
        f"Sample Witness Appearance Contexts:\n{w_lines}\n\n"
        "Output ONLY JSON matching OrgBagMergeVerdict: {\"verdict\": \"valid_merge\"|\"wrong_merge\", \"rationale\": \"<=200 chars\"}."
    )


def run_adjudicate_150(
    *,
    out_dir: Path,
    workers: int = 8,
    timeout_s: float = 90.0,
    codex_reasoning: str = "low",
    gemini_model: str = "gemini-4-carbon-low",
) -> dict[str, Any]:
    """Run cached 3-family SOTA review on all 150 sampled fresh multi-string bag groups."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from congress_docmeta.v7.factory.cache import SixTupleCache
    from congress_docmeta.v7.factory.runners import RunnerConfig, extract_json_payload, run_three_family_parallel

    out_dir = out_dir.resolve()
    sample_path = out_dir / "sample_150_bag_groups.jsonl"
    groups = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    cfg = RunnerConfig(
        codex_reasoning_effort=codex_reasoning,
        gemini_model=gemini_model,
        timeout_s=timeout_s,
        max_workers=3,
    )
    cache_path = out_dir / "ac4_cache.sqlite"
    families = ("claude", "codex", "gemini")

    def _parse_verdict(raw: str) -> dict[str, Any]:
        _, obj = extract_json_payload(raw)
        if not isinstance(obj, dict) or obj.get("verdict") not in {"valid_merge", "wrong_merge"}:
            raise ValueError(f"Invalid verdict payload: {obj!r}")
        rat = str(obj.get("rationale") or "").strip()[:240] or "evaluated"
        return {"verdict": obj["verdict"], "rationale": rat}

    results: dict[int, dict[str, Any]] = {}
    with SixTupleCache(cache_path) as cache:
        def _eval_one(g: dict[str, Any]) -> dict[str, Any]:
            prompt = _render_ac4_prompt(g)
            input_text = json.dumps(
                {
                    "bag_key": g["bag_key"],
                    "l2_texts": [v["l2_text"] for v in g["l2_variants"]],
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            fam_runs = run_three_family_parallel(
                input_text=input_text,
                prompt_text=prompt,
                schema=AC4_SCHEMA,
                codebook_version="org-ac4-v1",
                cache=cache,
                families=families,
                config=cfg,
                slice_spec="org_ac4_bag_group",
                stage="org_ac4_review",
                parse_fn=_parse_verdict,
            )
            verdicts: dict[str, str] = {}
            rationales: dict[str, str] = {}
            for fam, r in fam_runs.items():
                if r.ok and r.parsed:
                    verdicts[fam] = str(r.parsed["verdict"])
                    rationales[fam] = str(r.parsed["rationale"])
                else:
                    verdicts[fam] = "MISSING"
                    rationales[fam] = str(r.error or "error")
            n_wrong = sum(1 for v in verdicts.values() if v == "wrong_merge")
            n_valid = sum(1 for v in verdicts.values() if v == "valid_merge")
            consensus = "wrong_merge" if n_wrong >= 2 else ("valid_merge" if n_valid >= 2 else "uncertain")
            unanimous = len({v for v in verdicts.values() if v != "MISSING"}) == 1 and len([v for v in verdicts.values() if v != "MISSING"]) == 3
            return {
                "sample_index": g["sample_index"],
                "bag_key": g["bag_key"],
                "stratum": g.get("stratum"),
                "appearance_count": g["appearance_count"],
                "display_name": g.get("display_name"),
                "l2_texts": [v["l2_text"] for v in g["l2_variants"]],
                "verdicts": verdicts,
                "rationales": rationales,
                "consensus": consensus,
                "unanimous": unanimous,
                "has_any_wrong_vote": n_wrong >= 1,
            }

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            fmap = {pool.submit(_eval_one, g): idx for idx, g in enumerate(groups)}
            done = 0
            for fut in as_completed(fmap):
                rec = fut.result()
                results[fmap[fut]] = rec
                done += 1
                if done % 15 == 0 or rec["has_any_wrong_vote"]:
                    print(
                        f"[ac4] {done}/{len(groups)} bag={rec['bag_key']} consensus={rec['consensus']} votes={rec['verdicts']}",
                        file=sys.stderr,
                        flush=True,
                    )

        cache_stats = cache.stats()

    ordered = [results[i] for i in range(len(groups))]
    consensus_counts = Counter(r["consensus"] for r in ordered)
    any_wrong_flagged = [r for r in ordered if r["has_any_wrong_vote"]]
    splits = [r for r in ordered if not r["unanimous"]]
    flagged_for_md = [r for r in ordered if r["has_any_wrong_vote"] or not r["unanimous"]]

    report = {
        "total_sampled": len(ordered),
        "consensus_counts": dict(consensus_counts),
        "unanimous_valid": sum(1 for r in ordered if r["consensus"] == "valid_merge" and r["unanimous"]),
        "unanimous_wrong": sum(1 for r in ordered if r["consensus"] == "wrong_merge" and r["unanimous"]),
        "splits_or_missing": len(splits),
        "any_wrong_vote_count": len(any_wrong_flagged),
        "ac4_gate_max_wrong": 3,
        "ac4_passed": consensus_counts.get("wrong_merge", 0) <= 3 and consensus_counts.get("uncertain", 0) == 0,
        "flagged_groups": any_wrong_flagged,
        "cache_stats": cache_stats,
    }
    report_path = out_dir / "ac4_150_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# Org Entities Phase 1 — AC #4 Fresh 150-Group Stratified Audit",
        "",
        f"- **Sampled multi-string bag groups:** `{len(ordered)}` (excluded 60 planner sample groups)",
        f"- **Consensus valid_merge:** `{consensus_counts.get('valid_merge', 0)}` (unanimous: `{report['unanimous_valid']}`)",
        f"- **Consensus wrong_merge:** `{consensus_counts.get('wrong_merge', 0)}` (AC #4 threshold: `<= 3` -> **{'PASS' if report['ac4_passed'] else 'NEEDS REVIEW'}**)",
        f"- **Flagged (any wrong_merge vote or non-unanimous):** `{len(flagged_for_md)}`",
        "",
        "## Flagged / Disagreed Groups (Review First)",
        "",
    ]
    if not flagged_for_md:
        md_lines.append("All 150 groups were **3/3 unanimous `valid_merge`**.")
    else:
        for r in flagged_for_md:
            md_lines.extend(
                [
                    f"### #{r['sample_index']} `{r['bag_key']}` ({r['stratum']}, {r['appearance_count']} appearances) — consensus=`{r['consensus']}`",
                    f"- **Variants:** {r['l2_texts']}",
                    f"- **Votes:** `{r['verdicts']}`",
                    *[f"- `{fam}`: {rat}" for fam, rat in r["rationales"].items()],
                    "",
                ]
            )
    md_lines.extend(
        [
            "## All 150 Sampled Multi-String Bag Groups",
            "",
            "| # | Bag Key | Stratum | Apps | Consensus | Votes (C/X/G) | L2 Variants |",
            "| :--- | :--- | :--- | ---: | :--- | :--- | :--- |",
        ]
    )
    for r in ordered:
        v = r["verdicts"]
        votes = f"{v.get('claude', '?')[0]}/{v.get('codex', '?')[0]}/{v.get('gemini', '?')[0]}"
        variants_str = " || ".join(r["l2_texts"])[:160].replace("|", "\\|")
        md_lines.append(
            f"| {r['sample_index']} | `{r['bag_key']}` | {r['stratum']} | {r['appearance_count']} | `{r['consensus']}` | `{votes}` | {variants_str} |"
        )
    md_path = out_dir / "ac4_150_review.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return {"report": report, "report_path": str(report_path), "review_md_path": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Real-archive Org Entities Phase 1 AC #4 audit tool.")
    p.add_argument("--stage", required=True, choices=["build-and-sample", "adjudicate-150"])
    p.add_argument("--witnesses", type=Path, default=DEFAULT_WITNESSES)
    p.add_argument("--planner-sample", type=Path, default=DEFAULT_PLANNER_SAMPLE)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--engine-config", type=Path, default=None)
    p.add_argument("--sample-size", type=int, default=150)
    p.add_argument("--seed", type=int, default=20261122)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--codex-reasoning", type=str, default="low")
    p.add_argument("--gemini-model", type=str, default="gemini-4-carbon-low")
    args = p.parse_args(argv)

    if args.stage == "build-and-sample":
        run_build_and_sample(
            witnesses_path=args.witnesses,
            out_dir=args.out_dir,
            planner_sample_path=args.planner_sample,
            engine_config_path=args.engine_config,
            sample_size=args.sample_size,
            seed=args.seed,
        )
        return 0
    res = run_adjudicate_150(
        out_dir=args.out_dir,
        workers=args.workers,
        timeout_s=args.timeout,
        codex_reasoning=args.codex_reasoning,
        gemini_model=args.gemini_model,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
