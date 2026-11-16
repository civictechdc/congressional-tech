from __future__ import annotations

from dataclasses import dataclass
import json
import random

import pytest

from viewer_publication.corpus_quality.core import CorpusDocRow, QualityFinding
from viewer_publication.corpus_quality.stratified_sampler import (
    assign_core_stratum,
    build_stratified_audit_packet,
    release_gate_summary,
)


def _row(
    idx: int,
    *,
    filename: str = "doc.pdf",
    fmt: str = "pdf",
    effective_format: str | None = None,
    package_id: str | None = None,
    disposition: str | None = None,
    v6_route: str | None = None,
    zero_llm_source: str | None = None,
    docmeta_status: str | None = "usable",
    docmeta_primary_kind: str | None = None,
    p12_text: str = "Sample hearing text.",
) -> CorpusDocRow:
    return CorpusDocRow(
        link_key_hex=f"{idx:016x}",
        list_row=idx,
        saved_body_hex=f"{idx:064x}",
        package_id=package_id,
        filename=filename,
        format=fmt,
        effective_format=effective_format or fmt,
        disposition=disposition,
        v6_route=v6_route,
        zero_llm_source=zero_llm_source,
        docmeta_status=docmeta_status,
        docmeta_primary_kind=docmeta_primary_kind,
        p12_text=p12_text,
        congress=118,
        committee_keys=("hsif00",),
    )


@dataclass(frozen=True)
class _FakeCluster:
    cluster_id: str
    row_count: int
    is_emergent_spike: bool
    member_link_keys: tuple[str, ...]


@dataclass(frozen=True)
class _FakeTailReport:
    clusters: tuple[_FakeCluster, ...]
    row_to_cluster: dict[str, str]


def test_assign_core_stratum_covers_all_core_buckets() -> None:
    assert assign_core_stratum(_row(1, package_id="BILLS-118hr1ih")) == "upstream_spicydocs_bills_hearings"
    assert assign_core_stratum(_row(2, v6_route="zero_llm_complete")) == "zero_llm_synthesized_docmeta"
    assert assign_core_stratum(_row(3, disposition="cold_r2_hydrated")) == "cold_r2_hydrated"
    assert assign_core_stratum(_row(4, disposition="warc_unwrapped", fmt="other")) == "unwrapped_warc_arc"
    assert (
        assign_core_stratum(
            _row(5, filename="550e8400-e29b-41d4-a716-446655440000", fmt="html", effective_format="html")
        )
        == "bare_uuid_html"
    )
    assert assign_core_stratum(_row(6, docmeta_status="ocr_unreadable")) == "non_usable_or_stub"
    assert assign_core_stratum(_row(7, filename="HHRG-118-IF00-Bio-SmithJ-20230510.pdf")) == "clerk_bio_slot_override"
    assert assign_core_stratum(_row(8, filename="CHRG-118hhrg52001.pdf")) == "gpo_transcript"
    assert assign_core_stratum(_row(9, filename="HHRG-118-IF00-Wstate-DoeJ-20230510.pdf")) == "clerk_statement"
    assert assign_core_stratum(_row(10, filename="whitepaper.pdf")) == "open_extraction_tail"


def test_build_packet_is_order_independent_and_seed_sensitive() -> None:
    rows = [_row(i, filename=f"doc_{i}.pdf") for i in range(1, 31)]
    shuffled = list(rows)
    random.Random(99).shuffle(shuffled)

    pkt_a = build_stratified_audit_packet(rows, seed=20261117, per_stratum=5)
    pkt_b = build_stratified_audit_packet(shuffled, seed=20261117, per_stratum=5)
    pkt_c = build_stratified_audit_packet(rows, seed=20261118, per_stratum=5)

    assert [i.link_key_hex for i in pkt_a.items] == [i.link_key_hex for i in pkt_b.items]
    assert [i.link_key_hex for i in pkt_a.items] != [i.link_key_hex for i in pkt_c.items]
    assert pkt_a.strata_population_counts["open_extraction_tail"] == 30
    assert pkt_a.strata_sampled_counts["open_extraction_tail"] == 5


def test_build_packet_includes_dynamic_anomaly_and_tail_cluster_strata() -> None:
    rows = [
        _row(1, filename="HHRG-118-IF00-Bio-SmithJ-20230510.pdf"),
        _row(2, filename="HHRG-118-IF00-Bio-JonesA-20230510.pdf"),
        _row(3, filename="tail_a.pdf"),
        _row(4, filename="tail_b.pdf"),
        _row(5, filename="excluded.pdf"),
    ]
    findings = [
        QualityFinding(
            code="TFIDF_LABEL_CONTRADICTION",
            severity="warning",
            category="label_contradiction",
            link_key_hex=rows[0].link_key_hex,
            filename=rows[0].filename,
        ),
        QualityFinding(
            code="MISSING_PROVENANCE_COMMITTEE",
            severity="error",
            category="provenance",
            link_key_hex=rows[1].link_key_hex,
            filename=rows[1].filename,
        ),
    ]
    tail_report = _FakeTailReport(
        clusters=(
            _FakeCluster(
                cluster_id="tail-001-spike",
                row_count=2,
                is_emergent_spike=True,
                member_link_keys=(rows[2].link_key_hex, rows[3].link_key_hex),
            ),
        ),
        row_to_cluster={
            rows[2].link_key_hex: "tail-001-spike",
            rows[3].link_key_hex: "tail-001-spike",
        },
    )

    pkt = build_stratified_audit_packet(
        rows,
        seed=20261117,
        per_stratum=5,
        findings=findings,
        tail_report=tail_report,
        excluded_link_keys={rows[4].link_key_hex},
    )

    assert "anomaly:label_contradiction" in pkt.strata_sampled_counts
    assert "anomaly:provenance" in pkt.strata_sampled_counts
    assert "tail_cluster:emergent_spike" in pkt.strata_sampled_counts
    assert "tail_cluster:tail-001-spike" in pkt.strata_sampled_counts
    assert all(item.link_key_hex != rows[4].link_key_hex for item in pkt.items)

    spike_items = [i for i in pkt.items if i.stratum == "tail_cluster:emergent_spike"]
    assert len(spike_items) == 2
    assert all(i.tail_cluster_id == "tail-001-spike" for i in spike_items)

    # JSON serializable
    serialized = json.dumps(pkt.to_dict())
    assert "tail-001-spike" in serialized

    gate_fail = release_gate_summary(pkt, findings, max_errors=0)
    assert gate_fail["passed"] is False
    assert gate_fail["error_count"] == 1
    assert gate_fail["warning_count"] == 1

    gate_pass = release_gate_summary(pkt, [findings[0]], max_errors=0)
    assert gate_pass["passed"] is True


def test_build_packet_rejects_invalid_per_stratum() -> None:
    with pytest.raises(ValueError):
        build_stratified_audit_packet([], seed=20261117, per_stratum=0)
