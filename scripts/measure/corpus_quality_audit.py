#!/usr/bin/env python3
"""Offline Corpus Quality, Drift & Dataset Validation CLI (`scripts/measure/corpus_quality_audit.py`).

Unifies `viewer_publication.corpus_quality` (`core`, `provenance_validator`, `tfidf_drift`,
`tail_clusters`, and `stratified_sampler`) into a single deterministic, zero-network
release-audit and dataset QA runner over local Parquet tables.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
import time
from typing import Any

from viewer_publication.corpus_quality.core import (
    CorpusDocRow,
    QualityFinding,
    load_corpus_rows,
)
from viewer_publication.corpus_quality.provenance_validator import (
    validate_dataset_provenance,
)
from viewer_publication.corpus_quality.stratified_sampler import (
    build_stratified_audit_packet,
    release_gate_summary,
)
from viewer_publication.corpus_quality.tail_clusters import discover_tail_clusters
from viewer_publication.corpus_quality.tfidf_drift import (
    detect_host_boilerplate_drift,
    detect_label_contradictions,
)

DEFAULT_AUDIT_SEED = 20261116


def _summarize_contradictions(findings: Sequence[QualityFinding]) -> dict[str, Any]:
    by_code = Counter(f.code for f in findings)
    bio_slot = sum(1 for f in findings if "-bio-" in (f.filename or "").lower())
    wstate_slot = sum(1 for f in findings if "-wstate-" in (f.filename or "").lower())
    sd_slot = sum(1 for f in findings if "-sd" in (f.filename or "").lower())
    return {
        "total_findings": len(findings),
        "by_code": dict(sorted(by_code.items())),
        "bio_slot_contradictions": bio_slot,
        "wstate_slot_contradictions": wstate_slot,
        "sd_slot_contradictions": sd_slot,
    }


def run_corpus_quality_audit(
    tables_dir: str | Path,
    *,
    docmeta_dir: str | Path | None = None,
    base_tables_dir: str | Path | None = None,
    text_parquet: str | Path | None = None,
    body_text_ssot: str | Path | None = None,
    seed: int = DEFAULT_AUDIT_SEED,
    per_stratum: int = 10,
    limit: int | None = None,
    max_errors: int = 0,
) -> dict[str, Any]:
    """Execute the full offline corpus quality & dataset validation suite."""
    t0 = time.perf_counter()
    t_path = Path(tables_dir)
    dm_path = Path(docmeta_dir) if docmeta_dir is not None else None
    base_path = Path(base_tables_dir) if base_tables_dir is not None else None

    t_load0 = time.perf_counter()
    rows: list[CorpusDocRow] = load_corpus_rows(
        t_path,
        docmeta_dir=dm_path,
        text_parquet=text_parquet,
        body_text_ssot=body_text_ssot,
        limit=limit,
        include_text=True,
    )
    baseline_rows: list[CorpusDocRow] | None = (
        load_corpus_rows(base_path, limit=limit, include_text=True)
        if base_path is not None
        else None
    )
    load_sec = round(time.perf_counter() - t_load0, 3)

    # 1. Cross-table provenance, date-trap, Congress-boundary & docmeta_v6_1 conservation gate
    t_prov0 = time.perf_counter()
    prov_report = validate_dataset_provenance(
        t_path,
        docmeta_dir=dm_path,
        rows=rows,
        base_tables_dir=base_path,
        baseline_rows=baseline_rows,
    )
    prov_sec = round(time.perf_counter() - t_prov0, 3)

    # 2. TF-IDF / Dirichlet log-odds label contradiction & host boilerplate drift detectors
    t_nlp0 = time.perf_counter()
    primary_label_source = "docmeta" if dm_path is not None else "published"
    contradiction_findings = detect_label_contradictions(
        rows,
        label_source=primary_label_source,
    )
    published_vs_docmeta: dict[str, Any] | None = None
    if dm_path is not None:
        raw_pub_contradictions = detect_label_contradictions(
            rows,
            label_source="published",
        )
        raw_summary = _summarize_contradictions(raw_pub_contradictions)
        dm_summary = _summarize_contradictions(contradiction_findings)
        published_vs_docmeta = {
            "raw_published": raw_summary,
            "docmeta_v6_1": dm_summary,
            "total_contradictions_delta": dm_summary["total_findings"] - raw_summary["total_findings"],
            "bio_slot_contradictions_resolved": (
                raw_summary["bio_slot_contradictions"] - dm_summary["bio_slot_contradictions"]
            ),
        }

    boilerplate_findings = detect_host_boilerplate_drift(
        rows,
        baseline_rows=baseline_rows,
    )
    nlp_sec = round(time.perf_counter() - t_nlp0, 3)

    # 3. Unmapped-tail & emergent-template structural clustering radar
    t_clust0 = time.perf_counter()
    tail_report = discover_tail_clusters(
        rows,
        baseline_rows=baseline_rows,
    )
    clust_sec = round(time.perf_counter() - t_clust0, 3)

    # 4. Aggregate findings & build fresh-seed multi-stratum acceptance audit packet
    t_samp0 = time.perf_counter()
    all_findings: list[QualityFinding] = [
        *prov_report.findings,
        *contradiction_findings,
        *boilerplate_findings,
        *tail_report.findings,
    ]
    packet = build_stratified_audit_packet(
        rows,
        seed=seed,
        per_stratum=per_stratum,
        findings=all_findings,
        tail_report=tail_report,
    )
    gate = release_gate_summary(packet, all_findings, max_errors=max_errors)
    samp_sec = round(time.perf_counter() - t_samp0, 3)

    v6_routes = Counter(r.v6_route or "<unrouted>" for r in rows)
    dispositions = Counter(r.disposition or "<none>" for r in rows)
    text_populated = sum(1 for r in rows if r.p12_text)

    return {
        "suite_version": "corpus_quality_v1.0",
        "inputs": {
            "tables_dir": str(t_path),
            "docmeta_dir": str(dm_path) if dm_path is not None else None,
            "base_tables_dir": str(base_path) if base_path is not None else None,
            "seed": seed,
            "per_stratum": per_stratum,
            "limit": limit,
        },
        "timings_seconds": {
            "load_rows": load_sec,
            "provenance_validator": prov_sec,
            "tfidf_drift": nlp_sec,
            "tail_clusters": clust_sec,
            "stratified_sampler": samp_sec,
            "total": round(time.perf_counter() - t0, 3),
        },
        "corpus_overview": {
            "total_rows": len(rows),
            "rows_with_p12_text": text_populated,
            "p12_text_coverage_rate": round(text_populated / max(1, len(rows)), 4),
            "v6_route_counts": dict(sorted(v6_routes.items())),
            "disposition_counts": dict(sorted(dispositions.items())),
        },
        "release_gate": gate,
        "provenance_gate_passed": prov_report.passed_gate,
        "provenance": prov_report.to_dict(),
        "tfidf_drift": {
            "primary_label_source": primary_label_source,
            "label_contradictions_summary": _summarize_contradictions(contradiction_findings),
            "published_vs_docmeta_comparison": published_vs_docmeta,
            "boilerplate_drift_count": len(boilerplate_findings),
            "label_contradiction_findings": [f.to_dict() for f in contradiction_findings[:100]],
            "boilerplate_drift_findings": [f.to_dict() for f in boilerplate_findings[:100]],
        },
        "tail_clusters": tail_report.to_dict(),
        "audit_packet_summary": {
            "seed": packet.seed,
            "per_stratum": packet.per_stratum,
            "sample_size": len(packet.items),
            "strata_population_counts": dict(packet.strata_population_counts),
            "strata_sampled_counts": dict(packet.strata_sampled_counts),
        },
        "_audit_packet": packet.to_dict(),
    }


def render_markdown_report(result: Mapping[str, Any]) -> str:
    """Format a structured `run_corpus_quality_audit` result as GitHub-Flavored Markdown."""
    ov = result["corpus_overview"]
    gate = result["release_gate"]
    prov = result["provenance"]
    nlp = result["tfidf_drift"]
    tc = result["tail_clusters"]
    ap = result["audit_packet_summary"]
    timings = result["timings_seconds"]
    inputs = result["inputs"]

    lines: list[str] = [
        "# Corpus Quality & Dataset Validation Report",
        "",
        f"- **Release Gate Status**: **{'PASS' if gate['passed'] else 'FAIL'}** "
        f"(`errors={gate['error_count']}`, `warnings={gate['warning_count']}`, `info={gate['info_count']}`)",
        f"- **Provenance & Conservation Gate**: **{'PASS' if result['provenance_gate_passed'] else 'FAIL'}**",
        f"- **Total Rows Audited**: `{ov['total_rows']:,}` (`p12_text` hydrated on `{ov['rows_with_p12_text']:,}` / `{100.0 * ov['p12_text_coverage_rate']:.2f}%`)",
        f"- **Audit Seed**: `{inputs['seed']}` (`{ap['sample_size']}` sampled items across `{len(ap['strata_sampled_counts'])}` strata)",
        f"- **Runtime**: `{timings['total']:.2f}s` (`load={timings['load_rows']:.2f}s`, `prov={timings['provenance_validator']:.2f}s`, `nlp={timings['tfidf_drift']:.2f}s`, `clusters={timings['tail_clusters']:.2f}s`)",
        "",
        "## 1. Provenance, Boundary & `docmeta_v6_1` Conservation Summary",
        "",
    ]

    dm_cons = prov.get("docmeta_conservation_summary")
    if dm_cons:
        lines.extend(
            [
                "| Conservation Metric | Count / Value |",
                "| :--- | ---: |",
                f"| `detail.parquet` rows | `{dm_cons['detail_rows']:,}` |",
                f"| `completed_no_llm` rows | `{dm_cons['completed_no_llm_rows']:,}` |",
                f"| `llm_queue` rows | `{dm_cons['llm_queue_rows']:,}` |",
                f"| `llm_results` rows | `{dm_cons['llm_results_rows']:,}` |",
                f"| `sha_dup_alias` rows | `{dm_cons['sha_dup_alias_rows']:,}` |",
                f"| Partition sum (`exact={dm_cons['conserved_exact']}`) | `{dm_cons['partition_sum']:,}` |",
                f"| Duplicate `link_key` / `doc_key` | `{dm_cons['duplicate_link_keys']}` / `{dm_cons['duplicate_doc_keys']}` |",
                f"| Orphan rows / `saved_body` mismatches | `{dm_cons['orphan_docmeta_rows']}` / `{dm_cons['saved_body_mismatches']}` |",
                f"| Broken `sha_dup_alias` targets | `{dm_cons['broken_alias_targets']}` |",
                f"| Invalid `strict_v4_valid` / malformed JSON | `{dm_cons['invalid_strict_v4_rows']}` / `{dm_cons['malformed_json_rows']}` |",
                f"| Usable rows missing `primary_kind` | `{dm_cons['null_usable_primary_kind_rows']}` |",
                "",
            ]
        )

    nc = prov["none_committee_summary"]
    dt = prov["date_trap_summary"]
    cb = prov["congress_boundary_summary"]
    hs = prov["hsru00_summary"]
    lines.extend(
        [
            "### Cross-Table Provenance & Trap Metrics",
            f"- **`<NONE>` (`committee_keys = []`)**: `{nc['none_committee_rows']:,}` / `{nc['total_rows']:,}` (`{100.0 * nc['none_committee_rate']:.2f}%`; `{nc['none_on_resolvable_committee_hosts']:,}` on resolvable committee hosts)",
            f"- **`hsru00` Floor Attribution**: `{hs['published_hsru00_only_rows']:,}` published `hsru00`-only rows, `{hs['floor_repo_host_rows']:,}` floor-repo URLs, **`{hs['docmeta_hsru_floor_author_leaks']}`** `docmeta` floor-author leaks",
            f"- **Date Traps Guarded**: `{dt['cms_uploads_folder_rows']:,}` CMS `/uploads/` URLs (`{dt['cms_upload_folder_date_leaks']}` leaks), `{dt['wayback_or_webharvest_wrapped_rows']:,}` Wayback/WebHarvest URLs (`{dt['wayback_crawl_date_leaks']}` leaks), `{dt['senate_download_folder_rows']:,}` Senate download URLs, `{dt['page_metadata_published_time_rows']:,}` `published_time` rows",
            f"- **Congress Boundaries (`house_naming`)**: `{cb['bills_slug_rows_checked']:,}` `BILLS-` slugs checked (`{cb['bills_slug_congress_mismatches']}` mismatches), `{cb['invalid_congress_range_rows']}` out-of-range Congresses, `{cb['jan3_noon_boundary_off_by_one_rows']}` Noon-Jan-3 odd-year off-by-one rows",
            "",
            "## 2. TF-IDF / Log-Odds Label-Contradiction & Boilerplate Drift Radar",
            "",
        ]
    )

    lc_sum = nlp["label_contradictions_summary"]
    lines.append(
        f"- **Primary Label Source (`{nlp['primary_label_source']}`)**: `{lc_sum['total_findings']:,}` high-margin contradictions "
        f"(`-Bio-` slot: `{lc_sum['bio_slot_contradictions']:,}`, `-Wstate-` slot: `{lc_sum['wstate_slot_contradictions']:,}`, `-SD` slot: `{lc_sum['sd_slot_contradictions']:,}`)"
    )
    comp = nlp.get("published_vs_docmeta_comparison")
    if comp:
        lines.append(
            f"- **Raw Published vs `docmeta_v6_1` Delta**: raw published had `{comp['raw_published']['total_findings']:,}` contradictions "
            f"(`{comp['raw_published']['bio_slot_contradictions']:,}` `-Bio-` slot) -> `docmeta_v6_1` has `{comp['docmeta_v6_1']['total_findings']:,}` "
            f"(`{comp['docmeta_v6_1']['bio_slot_contradictions']:,}` `-Bio-` slot; **`{comp['bio_slot_contradictions_resolved']:,}` `-Bio-` slot contradictions resolved**)"
        )
    lines.append(f"- **Host Boilerplate / Soft-Refusal Drift Alerts**: `{nlp['boilerplate_drift_count']:,}`")
    lines.extend(
        [
            "",
            "## 3. Unmapped-Tail & Emergent-Template Clustering",
            "",
            f"- **Tail Population**: `{tc['target_tail_rows']:,}` / `{tc['total_input_rows']:,}` rows (`{tc['clustered_rows']:,}` grouped into `{len(tc['clusters'])}` clusters)",
            "",
        ]
    )

    if tc["clusters"]:
        lines.extend(
            [
                "| Cluster ID | Rows | Recommendation | Suggested Target | Top Header Phrases |",
                "| :--- | ---: | :--- | :--- | :--- |",
            ]
        )
        for c in tc["clusters"][:15]:
            phrases = ", ".join(
                f"`{p['phrase']}`" if isinstance(p, Mapping) else f"`{p}`"
                for p in (c.get("top_phrases") or [])[:4]
            )
            lines.append(
                f"| `{c['cluster_id']}` | `{c['row_count']:,}` | `{c['recommendation_kind']}` | "
                f"`{c.get('suggested_rule_target') or '-'}` | {phrases or '-'} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 4. Seeded Multi-Stratum Acceptance Sample",
            "",
            "| Stratum | Population | Sampled |",
            "| :--- | ---: | ---: |",
        ]
    )
    for st_name, pop_n in ap["strata_population_counts"].items():
        samp_n = ap["strata_sampled_counts"].get(st_name, 0)
        lines.append(f"| `{st_name}` | `{pop_n:,}` | `{samp_n}` |")
    lines.append("")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Corpus Quality, TF-IDF Drift, Tail-Cluster & Provenance Validation Suite."
    )
    parser.add_argument(
        "--tables",
        required=True,
        type=Path,
        help="Path to published release tables directory (detail.parquet, list.parquet, sources.parquet).",
    )
    parser.add_argument(
        "--docmeta-dir",
        default=None,
        type=Path,
        help="Optional directory containing docmeta_v6_1 Parquet sidecars.",
    )
    parser.add_argument(
        "--base-tables",
        default=None,
        type=Path,
        help="Optional baseline published tables directory for drift and spike comparisons.",
    )
    parser.add_argument(
        "--text-parquet",
        default=None,
        type=Path,
        help="Optional Parquet containing extracted p1..p2 / body text.",
    )
    parser.add_argument(
        "--body-text-ssot",
        default=None,
        type=Path,
        help="Optional singular body_text export directory, current.json pointer, or export.parquet.",
    )
    parser.add_argument(
        "--seed",
        default=DEFAULT_AUDIT_SEED,
        type=int,
        help=f"Fresh deterministic seed for stratified acceptance sampling (default: {DEFAULT_AUDIT_SEED}).",
    )
    parser.add_argument(
        "--per-stratum",
        default=10,
        type=int,
        help="Maximum sampled documents per stratum in the audit packet (default: 10).",
    )
    parser.add_argument(
        "--limit",
        default=None,
        type=int,
        help="Optional row limit for fast local smoke runs.",
    )
    parser.add_argument(
        "--max-errors",
        default=0,
        type=int,
        help="Maximum allowed error-severity findings for release_gate pass (default: 0).",
    )
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        help="Return exit code 2 when release_gate.passed is False.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        type=Path,
        help="Optional output path for full structured JSON validation report.",
    )
    parser.add_argument(
        "--output-md",
        default=None,
        type=Path,
        help="Optional output path for Markdown summary report.",
    )
    parser.add_argument(
        "--audit-packet-out",
        default=None,
        type=Path,
        help="Optional output path for the seeded StratifiedAuditPacket JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    full_result = run_corpus_quality_audit(
        args.tables,
        docmeta_dir=args.docmeta_dir,
        base_tables_dir=args.base_tables,
        text_parquet=args.text_parquet,
        body_text_ssot=args.body_text_ssot,
        seed=args.seed,
        per_stratum=args.per_stratum,
        limit=args.limit,
        max_errors=args.max_errors,
    )
    packet_dict = full_result.pop("_audit_packet")

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(full_result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_markdown_report(full_result), encoding="utf-8")

    if args.audit_packet_out is not None:
        args.audit_packet_out.parent.mkdir(parents=True, exist_ok=True)
        args.audit_packet_out.write_text(json.dumps(packet_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary_out = {
        "total_rows": full_result["corpus_overview"]["total_rows"],
        "provenance_gate_passed": full_result["provenance_gate_passed"],
        "release_gate": full_result["release_gate"],
        "timings_seconds": full_result["timings_seconds"],
    }
    print(json.dumps(summary_out, indent=2))

    if args.strict_gate and not full_result["release_gate"]["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
