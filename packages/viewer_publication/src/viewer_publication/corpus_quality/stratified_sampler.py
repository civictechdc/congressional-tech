"""Seeded multi-stratum acceptance sampler and release-gate helper (`corpus_quality.stratified_sampler`).

Repurposes the 20-stratum corpus audit pattern into a reusable, fresh-seed
acceptance sampler keyed canonically on `(link_key_hex, saved_body_hex)`.
Samples both core corpus strata and dynamic anomaly strata fed by
`provenance_validator`, `tfidf_drift`, and `tail_clusters`.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import re
from typing import Any

from viewer_publication.corpus_quality.core import CorpusDocRow, QualityFinding

_UUID_STEM_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.[a-z0-9]{1,6})?$",
    re.I,
)
_GPO_HEADER_RE = re.compile(
    r"(?:U\.S\. GOVERNMENT (?:PRINTING|PUBLISHING) OFFICE|VerDate\s+\w+\s+\d{2},\s+\d{4}|Jkt\s+\d{6})",
    re.I,
)

CORE_STRATA_ORDER: tuple[str, ...] = (
    "upstream_spicydocs_bills_hearings",
    "zero_llm_synthesized_docmeta",
    "cold_r2_hydrated",
    "unwrapped_warc_arc",
    "bare_uuid_html",
    "gpo_transcript",
    "clerk_bio_slot_override",
    "clerk_statement",
    "non_usable_or_stub",
    "open_extraction_tail",
)


@dataclass(frozen=True, slots=True)
class SampledAuditItem:
    """Single sampled document in a stratified acceptance-audit packet."""

    stratum: str
    link_key_hex: str
    saved_body_hex: str
    list_row: int
    filename: str
    format: str | None
    effective_format: str | None
    source_url: str | None
    document_kind: tuple[str, ...]
    docmeta_primary_kind: str | None
    disposition: str | None
    v6_route: str | None
    congress: int | None
    committee_keys: tuple[str, ...]
    tail_cluster_id: str | None = None
    finding_codes: tuple[str, ...] = ()
    p12_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stratum": self.stratum,
            "link_key_hex": self.link_key_hex,
            "saved_body_hex": self.saved_body_hex,
            "list_row": self.list_row,
            "filename": self.filename,
            "format": self.format,
            "effective_format": self.effective_format,
            "source_url": self.source_url,
            "document_kind": list(self.document_kind),
            "docmeta_primary_kind": self.docmeta_primary_kind,
            "disposition": self.disposition,
            "v6_route": self.v6_route,
            "congress": self.congress,
            "committee_keys": list(self.committee_keys),
            "tail_cluster_id": self.tail_cluster_id,
            "finding_codes": list(self.finding_codes),
            "p12_excerpt": self.p12_excerpt,
        }


@dataclass(frozen=True, slots=True)
class StratifiedAuditPacket:
    """Seeded multi-stratum audit packet covering core and dynamic anomaly strata."""

    seed: int
    total_rows: int
    per_stratum: int
    strata_population_counts: dict[str, int]
    strata_sampled_counts: dict[str, int]
    items: tuple[SampledAuditItem, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "total_rows": self.total_rows,
            "per_stratum": self.per_stratum,
            "strata_population_counts": dict(self.strata_population_counts),
            "strata_sampled_counts": dict(self.strata_sampled_counts),
            "sample_size": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }


def _canonical_rank_digest(seed: int, row: CorpusDocRow) -> str:
    payload = f"{seed}:{row.link_key_hex}:{row.saved_body_hex}".encode("utf-8")
    return sha256(payload).hexdigest()


def assign_core_stratum(row: CorpusDocRow) -> str:
    """Assign a document to its primary mutually-exclusive core audit stratum."""
    disp = (row.disposition or "").lower()
    route = (row.v6_route or "").lower()
    fn = row.filename or ""
    fn_lower = fn.lower()
    eff_fmt = (row.effective_format or row.format or "").lower()

    if disp == "upstream_spicydocs" or route == "upstream_spicydocs" or row.package_id is not None:
        return "upstream_spicydocs_bills_hearings"
    if route in {"zero_llm_complete", "zero_llm_synthesized_docmeta"} or row.zero_llm_source is not None:
        return "zero_llm_synthesized_docmeta"
    if disp in {"cold_r2_hydrated", "cold_r2_metadata_only"} or route == "cold_r2_metadata_only":
        return "cold_r2_hydrated"
    if disp == "warc_unwrapped" or (row.format or "").lower() == "other":
        return "unwrapped_warc_arc"
    if eff_fmt == "html" and _UUID_STEM_RE.match(fn):
        return "bare_uuid_html"
    if row.docmeta_status in {"ocr_unreadable", "stub_or_blank", "error_or_block"} or route == "deterministic_triage_non_usable":
        return "non_usable_or_stub"
    if "-bio-" in fn_lower:
        return "clerk_bio_slot_override"
    if fn.startswith("CHRG-") or _GPO_HEADER_RE.search(row.p12_text[:1500]):
        return "gpo_transcript"
    if "-wstate-" in fn_lower or "-sd00" in fn_lower or row.docmeta_primary_kind in {
        "witness_statement",
        "member_opening_statement",
    }:
        return "clerk_statement"
    return "open_extraction_tail"


def _row_to_item(
    row: CorpusDocRow,
    stratum: str,
    *,
    tail_cluster_id: str | None,
    finding_codes: tuple[str, ...],
    max_excerpt_chars: int,
) -> SampledAuditItem:
    return SampledAuditItem(
        stratum=stratum,
        link_key_hex=row.link_key_hex,
        saved_body_hex=row.saved_body_hex,
        list_row=row.list_row,
        filename=row.filename,
        format=row.format,
        effective_format=row.effective_format,
        source_url=row.source_url,
        document_kind=row.document_kind,
        docmeta_primary_kind=row.docmeta_primary_kind,
        disposition=row.disposition,
        v6_route=row.v6_route,
        congress=row.congress,
        committee_keys=row.committee_keys,
        tail_cluster_id=tail_cluster_id,
        finding_codes=finding_codes,
        p12_excerpt=(row.p12_text or "")[:max_excerpt_chars],
    )


def build_stratified_audit_packet(
    rows: Sequence[CorpusDocRow],
    *,
    seed: int,
    per_stratum: int = 10,
    findings: Sequence[QualityFinding] = (),
    tail_report: Any = None,
    include_top_tail_clusters: int = 3,
    max_excerpt_chars: int = 600,
    excluded_link_keys: Collection[str] = (),
) -> StratifiedAuditPacket:
    """Build a fresh-seed stratified audit packet over core and dynamic anomaly strata.

    Sampling is deterministic for a given `seed` and canonical `(link_key_hex, saved_body_hex)`
    identities, independent of input row order.
    """
    if per_stratum < 1:
        raise ValueError(f"per_stratum must be >= 1, got {per_stratum}")

    excluded = set(excluded_link_keys)
    by_link: dict[str, CorpusDocRow] = {}
    for row in rows:
        if row.link_key_hex and row.link_key_hex not in excluded:
            by_link.setdefault(row.link_key_hex, row)

    row_finding_codes: dict[str, list[str]] = {}
    findings_by_stratum: dict[str, list[CorpusDocRow]] = {}
    for f in findings:
        if not f.link_key_hex or f.link_key_hex not in by_link:
            continue
        row = by_link[f.link_key_hex]
        row_finding_codes.setdefault(f.link_key_hex, []).append(f.code)
        cat_stratum = f"anomaly:{f.category}"
        findings_by_stratum.setdefault(cat_stratum, []).append(row)

    row_to_cluster: dict[str, str] = {}
    tail_strata: dict[str, list[CorpusDocRow]] = {}
    if tail_report is not None:
        raw_map = getattr(tail_report, "row_to_cluster", None)
        if isinstance(raw_map, dict):
            row_to_cluster = dict(raw_map)
        clusters = getattr(tail_report, "clusters", ()) or ()
        spike_rows: list[CorpusDocRow] = []
        top_clusters = list(clusters)[: max(0, include_top_tail_clusters)]
        for cl in clusters:
            if getattr(cl, "is_emergent_spike", False):
                for lk in getattr(cl, "member_link_keys", ()):
                    if lk in by_link:
                        spike_rows.append(by_link[lk])
        if spike_rows:
            tail_strata["tail_cluster:emergent_spike"] = spike_rows
        for cl in top_clusters:
            cid = getattr(cl, "cluster_id", "unknown")
            members = [by_link[lk] for lk in getattr(cl, "member_link_keys", ()) if lk in by_link]
            if members:
                tail_strata[f"tail_cluster:{cid}"] = members

    core_buckets: dict[str, list[CorpusDocRow]] = {s: [] for s in CORE_STRATA_ORDER}
    for row in by_link.values():
        core_buckets[assign_core_stratum(row)].append(row)

    all_strata: list[tuple[str, list[CorpusDocRow]]] = []
    for s in CORE_STRATA_ORDER:
        if core_buckets[s]:
            all_strata.append((s, core_buckets[s]))
    for s in sorted(findings_by_stratum):
        # Deduplicate by link_key_hex before ranking
        dedup = list({r.link_key_hex: r for r in findings_by_stratum[s]}.values())
        all_strata.append((s, dedup))
    for s in sorted(tail_strata):
        dedup = list({r.link_key_hex: r for r in tail_strata[s]}.values())
        all_strata.append((s, dedup))

    population_counts: dict[str, int] = {}
    sampled_counts: dict[str, int] = {}
    items: list[SampledAuditItem] = []

    for stratum_name, bucket in all_strata:
        population_counts[stratum_name] = len(bucket)
        ranked = sorted(
            bucket,
            key=lambda r: (_canonical_rank_digest(seed, r), r.link_key_hex, r.saved_body_hex),
        )
        chosen = ranked[:per_stratum]
        sampled_counts[stratum_name] = len(chosen)
        for row in chosen:
            fcodes = tuple(sorted(set(row_finding_codes.get(row.link_key_hex, ()))))
            items.append(
                _row_to_item(
                    row,
                    stratum_name,
                    tail_cluster_id=row_to_cluster.get(row.link_key_hex),
                    finding_codes=fcodes,
                    max_excerpt_chars=max_excerpt_chars,
                )
            )

    return StratifiedAuditPacket(
        seed=seed,
        total_rows=len(rows),
        per_stratum=per_stratum,
        strata_population_counts=population_counts,
        strata_sampled_counts=sampled_counts,
        items=tuple(items),
    )


def release_gate_summary(
    packet: StratifiedAuditPacket,
    findings: Sequence[QualityFinding],
    *,
    max_errors: int = 0,
) -> dict[str, Any]:
    """Evaluate a release gate from findings severity counts and sampled packet coverage."""
    sev_counts = Counter(f.severity for f in findings)
    cat_counts = Counter(f.category for f in findings)
    error_count = int(sev_counts.get("error", 0))
    return {
        "passed": error_count <= max_errors,
        "max_errors": max_errors,
        "error_count": error_count,
        "warning_count": int(sev_counts.get("warning", 0)),
        "info_count": int(sev_counts.get("info", 0)),
        "findings_by_category": dict(sorted(cat_counts.items())),
        "sampled_strata_count": len(packet.strata_sampled_counts),
        "sampled_items_count": len(packet.items),
    }
