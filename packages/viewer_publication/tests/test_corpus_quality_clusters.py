"""Offline unit tests for `viewer_publication.corpus_quality.tail_clusters`."""
from __future__ import annotations

import json

import pytest

from viewer_publication.corpus_quality.core import CorpusDocRow
from viewer_publication.corpus_quality.stratified_sampler import (
    build_stratified_audit_packet,
    release_gate_summary,
)
from viewer_publication.corpus_quality.tail_clusters import (
    discover_tail_clusters,
    select_tail_population,
)


def _make_row(
    idx: int,
    *,
    filename: str,
    p12_text: str,
    source_url: str | None = None,
    host: str | None = None,
    fmt: str = "pdf",
    document_kind: tuple[str, ...] = (),
    reading_status: str | None = None,
    v6_route: str | None = None,
    disposition: str | None = None,
    zero_llm_source: str | None = None,
    docmeta_primary_kind: str | None = None,
    grammar_lock_source: str | None = None,
    docmeta_status: str | None = None,
    docmeta_json: str | None = None,
    strict_v4_valid: bool | None = None,
    is_alias: bool = False,
) -> CorpusDocRow:
    lk = f"{idx:016x}"
    sha = f"{idx:064x}"
    return CorpusDocRow(
        link_key_hex=lk,
        list_row=idx,
        doc_key=f"doc-{idx}",
        saved_body_hex=sha,
        effective_body_sha_hex=sha,
        filename=filename,
        format=fmt,
        effective_format=fmt,
        source_url=source_url,
        host=host,
        document_kind=document_kind,
        reading_status=reading_status,
        p12_text=p12_text,
        disposition=disposition,
        v6_route=v6_route,
        zero_llm_source=zero_llm_source,
        docmeta_primary_kind=docmeta_primary_kind,
        grammar_lock_source=grammar_lock_source,
        docmeta_status=docmeta_status,
        docmeta_json=docmeta_json,
        strict_v4_valid=strict_v4_valid,
        is_alias=is_alias,
    )


def _build_synthetic_corpus() -> tuple[list[CorpusDocRow], list[CorpusDocRow]]:
    """Build candidate and baseline synthetic slices covering clean rows + 4 distinct tail clusters."""
    clean_rows = [
        _make_row(
            1,
            filename="CHRG-118hhrg54321.pdf",
            p12_text=(
                "OVERSIGHT OF FEDERAL INFRASTRUCTURE PROGRAMS\n"
                "HEARING BEFORE THE COMMITTEE ON TRANSPORTATION AND INFRASTRUCTURE\n"
                "HOUSE OF REPRESENTATIVES\nONE HUNDRED EIGHTEENTH CONGRESS\n"
                "There was zero margin for error in the bridge engineering analysis discussed by the panel. "
                * 8
            ),
            source_url="https://www.govinfo.gov/content/pkg/CHRG-118hhrg54321/pdf/CHRG-118hhrg54321.pdf",
            host="www.govinfo.gov",
            document_kind=("published-hearing",),
            disposition="upstream_spicydocs",
            v6_route="zero_llm_complete",
            zero_llm_source="spicydocs_govinfo_hearing",
            docmeta_primary_kind="hearing_transcript",
            docmeta_status="usable",
            docmeta_json='{"status":"usable","primary_kind":"hearing_transcript"}',
            strict_v4_valid=True,
        ),
        _make_row(
            2,
            filename="HHRG-118-JU00-TTF-DoeJ-20240501.pdf",
            p12_text="TRUTH IN TESTIMONY DISCLOSURE FORM\nWitness Name: Jane Doe\nClause 2(g)(5)",
            source_url="https://docs.house.gov/meetings/JU/JU00/20240501/117001/HHRG-118-JU00-TTF-DoeJ-20240501.pdf",
            host="docs.house.gov",
            document_kind=("testimony-disclosure",),
            v6_route="zero_llm_complete",
            zero_llm_source="zero_llm_truth_in_testimony_disclosure",
            docmeta_primary_kind="truth_in_testimony_disclosure",
            docmeta_status="usable",
            docmeta_json='{"status":"usable","primary_kind":"truth_in_testimony_disclosure"}',
            strict_v4_valid=True,
        ),
        # Alias row should be skipped by default so SHA duplicates never inflate cluster counts
        _make_row(
            3,
            filename="dup_other.pdf",
            p12_text="Unmapped duplicate alias text",
            document_kind=("other",),
            is_alias=True,
        ),
    ]

    # Cluster A (6 docs in both baseline & candidate): -Bio- upload slot containing TTF Disclosure forms
    ttf_in_bio_rows = [
        _make_row(
            100 + i,
            filename=f"HHRG-118-IF00-Bio-Witness{i}-2024061{i}.pdf",
            p12_text=(
                "TRUTH IN TESTIMONY DISCLOSURE FORM\n"
                "Instructions for Completing the Truth in Testimony Disclosure Form\n"
                f"Witness Name: Dr. Witness {i}\n"
                "Position/Title: Senior Fellow\n"
                "1. Please list any entity you are representing: [x] Nongovernmental Entity\n"
                "2. Federal grants or contracts received since October 1, 2021: [ ] Yes [x] No\n"
                "Clause 2(g)(5) of Rule XI of the Rules of the House of Representatives."
            ),
            source_url=(
                f"https://docs.house.gov/meetings/IF/IF00/2024061{i}/11720{i}/"
                f"HHRG-118-IF00-Bio-Witness{i}-2024061{i}.pdf"
            ),
            host="docs.house.gov",
            fmt="pdf",
            document_kind=("witness-biography",),
            v6_route="deterministic_enriched_open_kind",
        )
        for i in range(1, 7)
    ]

    # Cluster B (6 docs in candidate, 5 in baseline): Unmapped formal Hearing Notice PDFs (new cover:* candidate)
    hearing_notice_rows = [
        _make_row(
            200 + i,
            filename=f"2025-03-1{i}_subcommittee_hearing_notice.pdf",
            p12_text=(
                "ONE HUNDRED NINETEENTH CONGRESS\n"
                "CONGRESS OF THE UNITED STATES\n"
                "HOUSE OF REPRESENTATIVES\n"
                "COMMITTEE ON SMALL BUSINESS\n"
                "SUBCOMMITTEE ON ECONOMIC GROWTH, TAX, AND CAPITAL ACCESS\n"
                "NOTICE OF SUBCOMMITTEE HEARING\n"
                f"DATE: Wednesday, March 1{i}, 2025\n"
                "TIME: 10:00 A.M.\n"
                "PLACE: 2360 Rayburn House Office Building\n"
                f"SUBJECT: Examining Main Street Capital Access Part {i}\n"
                "The Subcommittee will meet to hear testimony from invited witnesses."
            ),
            source_url=f"https://smallbusiness.house.gov/uploadedfiles/2025-03-1{i}_subcommittee_hearing_notice.pdf",
            host="smallbusiness.house.gov",
            fmt="pdf",
            document_kind=(),
            v6_route="deterministic_enriched_open_kind",
        )
        for i in range(1, 7)
    ]

    # Cluster C (8 docs in candidate vs 1 in baseline -> EMERGENT SPIKE!): New Committee HTML CMS Nav Wrapper
    vet_titles = (
        "Bad Paper and Bureaucracy in Discharge Reviews",
        "Purchase History in the Veteran Readiness Program",
        "Delivering Modern Healthcare to Rural Clinics",
        "Solutions to Prevent Veteran Homelessness",
        "PACT Act Disability Claims Processing Technology",
        "Radiation Exposure Legacy Effects on Families",
        "Addressing the Veteran Foreclosure Crisis",
        "GI Bill Educational Assistance Oversight",
    )
    cms_wrapper_rows = [
        _make_row(
            300 + i,
            filename=f"event-veterans-hearing-{i}",
            p12_text=(
                "Stay Up To Date\n"
                "Opportunities\n"
                "Whistleblower\n"
                "Submit Your Story\n"
                "MENU\n"
                f'"{vet_titles[i - 1]}"\n'
                f"Date: 04.1{i}.26\n"
                "Time: 10:15 AM\n"
                "Location: 360 Cannon Building"
            ),
            source_url=f"https://veterans.house.gov/events/hearings/event-veterans-hearing-{i}",
            host="veterans.house.gov",
            fmt="html",
            document_kind=("other",),
            v6_route="llm_open_extraction",
        )
        for i in range(1, 9)
    ]

    # Cluster D (4 docs in candidate, 0 in baseline): Untriaged Senate WAF Refusal HTML pages
    waf_rows = [
        _make_row(
            400 + i,
            filename=f"download-hearing-doc-{i}.pdf",
            p12_text=(
                "Request Not Accepted - Security Risk Detected\n"
                f"Reference ID: 18.94c21102.1710000{i}\n"
                "Your request could not be processed by the security firewall."
            ),
            source_url=f"https://www.judiciary.senate.gov/download/2025/04/hearing-doc-{i}",
            host="www.judiciary.senate.gov",
            fmt="html",
            document_kind=(),
        )
        for i in range(1, 5)
    ]

    candidate = clean_rows + ttf_in_bio_rows + hearing_notice_rows + cms_wrapper_rows + waf_rows
    baseline = clean_rows + ttf_in_bio_rows + hearing_notice_rows[:5] + cms_wrapper_rows[:1]
    return candidate, baseline


def test_select_tail_population_reasons_and_exclusions() -> None:
    candidate, _ = _build_synthetic_corpus()
    anomaly_row = _make_row(
        999,
        filename="broken_docmeta.pdf",
        p12_text="Valid body text with broken docmeta schema payload " * 6,
        document_kind=("committee-report",),
        v6_route="zero_llm_complete",
        zero_llm_source="spicydocs_govinfo_report",
        docmeta_primary_kind="committee_report",
        docmeta_status="usable",
        docmeta_json='{"status":"usable"}',
        strict_v4_valid=False,
    )
    tail_rows, reasons = select_tail_population([*candidate, anomaly_row])
    selected_keys = {r.link_key_hex for r in tail_rows}

    # Clean rows (1, 2) and alias row (3) must NOT be selected
    assert f"{1:016x}" not in selected_keys
    assert f"{2:016x}" not in selected_keys
    assert f"{3:016x}" not in selected_keys

    # -Bio- row without deterministic lock is selected for ambiguous_upload_slot + open_extraction_tail
    bio_reasons = reasons[f"{101:016x}"]
    assert "ambiguous_upload_slot" in bio_reasons
    assert "open_extraction_tail" in bio_reasons

    # Unmapped hearing notice is selected for unmapped_document_kind
    assert "unmapped_document_kind" in reasons[f"{201:016x}"]

    # WAF block row is selected via page-signals.json (`senate_waf_block`) even without reading_status set
    assert "error_response_candidate" in reasons[f"{401:016x}"]

    # Schema-invalid docmeta row is selected for docmeta_anomaly
    assert reasons[f"{999:016x}"] == ("docmeta_anomaly",)


def test_discover_tail_clusters_separates_templates_and_detects_spikes() -> None:
    candidate, baseline = _build_synthetic_corpus()
    report = discover_tail_clusters(
        candidate,
        baseline_rows=baseline,
        min_cluster_size=3,
        jaccard_threshold=0.35,
        exemplars_per_cluster=4,
        spike_min_delta=5,
        spike_min_ratio=2.0,
    )

    assert report.total_input_rows == len(candidate)
    assert report.target_tail_rows == 24
    assert report.clustered_rows == 24
    assert len(report.clusters) == 4
    assert len(report.row_to_cluster) == 24

    by_host = {cl.dominant_hosts[0][0]: cl for cl in report.clusters}
    assert set(by_host) == {
        "veterans.house.gov",
        "docs.house.gov",
        "smallbusiness.house.gov",
        "www.judiciary.senate.gov",
    }

    # 1. Veterans HTML CMS wrapper cluster: 1 -> 8 spike + CMS wrapper candidate
    cms_cl = by_host["veterans.house.gov"]
    assert cms_cl.row_count == 8
    assert cms_cl.baseline_count == 1
    assert cms_cl.growth_delta == 7
    assert cms_cl.is_emergent_spike is True
    assert cms_cl.layout_profile.dominant_shape_bucket == "cms_html_chrome"
    assert cms_cl.recommendation_kind == "new_error_or_wrapper_signal_candidate"
    assert cms_cl.suggested_rule_target == "page-signals:cms_navigation_chrome"
    assert len(cms_cl.exemplar_link_keys) == 4
    cms_phrases = " ".join(p.phrase for p in cms_cl.top_phrases)
    assert any(tok in cms_phrases for tok in ("whistleblower", "stay up", "submit your story"))

    # 2. Clerk -Bio- TTF cluster: no spike (6 -> 6), existing document_cover:testimony-disclosure match
    ttf_cl = by_host["docs.house.gov"]
    assert ttf_cl.row_count == 6
    assert ttf_cl.baseline_count == 6
    assert ttf_cl.growth_delta == 0
    assert ttf_cl.is_emergent_spike is False
    assert ttf_cl.layout_profile.dominant_shape_bucket == "checkbox_disclosure_form"
    assert ttf_cl.recommendation_kind == "existing_cover_rule_matches"
    assert ttf_cl.suggested_rule_target == "document_cover:testimony-disclosure"
    assert ttf_cl.partial_cover_matches.get("document_cover:testimony-disclosure", 0) == 6

    # 3. Small Business Hearing Notice cluster: emergent `cover:hearing-notice` rule candidate
    hn_cl = by_host["smallbusiness.house.gov"]
    assert hn_cl.row_count == 6
    assert hn_cl.baseline_count == 5
    assert hn_cl.is_emergent_spike is False
    assert hn_cl.recommendation_kind == "new_cover_rule_candidate"
    assert hn_cl.suggested_rule_target == "cover:hearing-notice"

    # 4. Judiciary WAF block cluster: existing `page-signals:senate_waf_block` match + untriaged error warning
    waf_cl = by_host["www.judiciary.senate.gov"]
    assert waf_cl.row_count == 4
    assert waf_cl.baseline_count == 0
    assert waf_cl.recommendation_kind == "existing_page_signal_matches"
    assert waf_cl.suggested_rule_target == "page-signals:senate_waf_block"

    finding_codes = {f.code for f in report.findings}
    assert "tail_cluster_emergent_spike" in finding_codes
    assert "tail_cluster_unapplied_cover_rule" in finding_codes
    assert "tail_cluster_untriaged_error_or_wrapper" in finding_codes
    assert "tail_cluster_new_rule_candidate" in finding_codes


def test_order_invariance_json_roundtrip_and_sampler_integration() -> None:
    candidate, baseline = _build_synthetic_corpus()
    rep_fwd = discover_tail_clusters(candidate, baseline_rows=baseline, min_cluster_size=3)
    rep_rev = discover_tail_clusters(list(reversed(candidate)), baseline_rows=list(reversed(baseline)), min_cluster_size=3)

    assert rep_fwd.to_dict() == rep_rev.to_dict()
    serialized = json.dumps(rep_fwd.to_dict())
    unpacked = json.loads(serialized)
    assert unpacked["cluster_count"] == 4
    assert unpacked["emergent_spike_count"] == 1

    # Verify seamless integration with `stratified_sampler.build_stratified_audit_packet`
    packet = build_stratified_audit_packet(
        candidate,
        seed=20261116,
        per_stratum=3,
        findings=rep_fwd.findings,
        tail_report=rep_fwd,
        include_top_tail_clusters=2,
    )
    assert "tail_cluster:emergent_spike" in packet.strata_sampled_counts
    assert "anomaly:tail_cluster" in packet.strata_sampled_counts
    assert any(k.startswith("tail_cluster:tail-001-") for k in packet.strata_sampled_counts)
    assert any(item.tail_cluster_id is not None for item in packet.items)

    gate = release_gate_summary(packet, rep_fwd.findings, max_errors=0)
    assert gate["passed"] is True
    assert gate["error_count"] == 0
    assert gate["warning_count"] >= 3


def test_single_cluster_and_empty_inputs() -> None:
    empty_rep = discover_tail_clusters([])
    assert empty_rep.target_tail_rows == 0
    assert empty_rep.clusters == ()

    candidate, _ = _build_synthetic_corpus()
    # Keep clean rows + only the 6 Hearing Notice tail docs -> single cluster contrast against clean background
    single_slice = [r for r in candidate if r.list_row < 10 or (200 < r.list_row < 210)]
    single_rep = discover_tail_clusters(single_slice, min_cluster_size=3)
    assert len(single_rep.clusters) == 1
    cl = single_rep.clusters[0]
    assert cl.row_count == 6
    assert len(cl.top_phrases) > 0

    with pytest.raises(ValueError, match="min_cluster_size"):
        discover_tail_clusters(single_slice, min_cluster_size=0)
    with pytest.raises(ValueError, match="jaccard_threshold"):
        discover_tail_clusters(single_slice, jaccard_threshold=0.0)


def test_empty_containers_separated_by_disposition_and_format() -> None:
    scan_pdfs = [
        _make_row(
            500 + i,
            filename=f"scanned_exhibit_{i}.pdf",
            p12_text="",
            source_url=f"https://oversight.house.gov/wp-content/uploads/2025/02/scanned_exhibit_{i}.pdf",
            host="oversight.house.gov",
            fmt="pdf",
            disposition="sraw_p12",
            v6_route="deterministic_triage_non_usable",
            zero_llm_source="triage_ocr_unreadable",
            docmeta_status="ocr_unreadable",
        )
        for i in range(1, 6)
    ]
    cold_zips = [
        _make_row(
            600 + i,
            filename=f"hearing_packet_{i}.zip",
            p12_text="",
            source_url=f"https://docs.house.gov/meetings/GO/GO00/2025020{i}/11800{i}/hearing_packet_{i}.zip",
            host="docs.house.gov",
            fmt="zip",
            disposition="cold_r2_metadata_only",
            v6_route="deterministic_triage_non_usable",
            zero_llm_source="cold_r2_triage_skipped_zip_container",
            docmeta_status="stub_or_blank",
        )
        for i in range(1, 5)
    ]
    rep = discover_tail_clusters([*scan_pdfs, *cold_zips], min_cluster_size=3)
    assert len(rep.clusters) == 2
    exts = {cl.dominant_extensions[0][0]: cl for cl in rep.clusters}
    assert exts["pdf"].row_count == 5
    assert exts["zip"].row_count == 4
    assert exts["pdf"].recommendation_kind == "new_error_or_wrapper_signal_candidate"
    assert exts["pdf"].suggested_rule_target == "page-signals:empty_or_scan_only_container"


def test_qfr_and_emergent_cohesive_template_recommendations() -> None:
    qfr_rows = [
        _make_row(
            700 + i,
            filename=f"post_hearing_qa_{i}.pdf",
            p12_text=(
                "SENATE SELECT COMMITTEE ON INTELLIGENCE\n"
                f"Post-Hearing Questions for the Record — Panel {i}\n"
                f"Question {i}: Please describe the agency cyber incident reporting timeline.\n"
                f"Answer {i}: The agency reports critical incidents within 72 hours of detection."
            ),
            source_url=f"https://www.intelligence.senate.gov/sites/default/files/documents/qfr_{i}.pdf",
            host="www.intelligence.senate.gov",
            fmt="pdf",
            document_kind=(),
            v6_route="deterministic_enriched_open_kind",
        )
        for i in range(1, 6)
    ]
    bespoke_grid_rows = [
        _make_row(
            800 + i,
            filename=f"subcommittee_allocation_table_{i}.pdf",
            p12_text=(
                "SUBCOMMITTEE 302B DISCRETIONARY ALLOCATION LEDGER\n"
                f"Account | FY2025 Enacted | FY2026 Mark {i} | Delta\n"
                f"Defense0{i} | $849,000 | $86{i},500 | +1.{i}%\n"
                f"NonDef0{i} | $710,000 | $71{i},200 | +0.{i}%"
            ),
            source_url=f"https://appropriations.house.gov/sites/evo-subsites/tables/alloc_{i}.pdf",
            host="appropriations.house.gov",
            fmt="pdf",
            document_kind=(),
            v6_route="deterministic_enriched_open_kind",
        )
        for i in range(1, 6)
    ]
    rep = discover_tail_clusters([*qfr_rows, *bespoke_grid_rows], min_cluster_size=4)
    assert len(rep.clusters) == 2
    by_host = {cl.dominant_hosts[0][0]: cl for cl in rep.clusters}

    # Note: `document_cover.qfr_fields` already matches explicit QFR headings with Question/Answer markers!
    qfr_cl = by_host["www.intelligence.senate.gov"]
    assert qfr_cl.layout_profile.dominant_shape_bucket == "qa_or_qfr_packet"
    assert qfr_cl.layout_profile.qa_marker_rate == 1.0
    assert qfr_cl.suggested_rule_target in {"document_cover:questions-and-answers", "cover:questions-and-answers"}

    # Bespoke 302(b) table grid is NOT in document_cover.py -> triggers emergent cover candidate!
    grid_cl = by_host["appropriations.house.gov"]
    assert grid_cl.layout_profile.dominant_shape_bucket == "table_or_tally_grid"
    assert grid_cl.recommendation_kind == "new_cover_rule_candidate"
    assert grid_cl.suggested_rule_target is not None
    assert grid_cl.suggested_rule_target.startswith("cover:emergent-")


def test_large_canopy_pure_lsh_scaling_and_alias_toggle() -> None:
    # Build > 370 distinct micro-templates inside the SAME `pdf:caps_masthead_banner` canopy
    # so `m_count > 350` exercises pure One-Permutation MinHash LSH banding without inverted-index fallback.
    recurring_cluster = [
        _make_row(
            1000 + i,
            filename=f"press_release_{i}.pdf",
            p12_text=(
                "COMMITTEE ON ENERGY AND COMMERCE\n"
                "FOR IMMEDIATE RELEASE\n"
                "MEDIA CONTACT: PRESS OFFICE\n"
                f"WASHINGTON — Committee leaders announced bipartisan field roundtable #{i} on grid reliability."
            ),
            source_url=f"https://energycommerce.house.gov/posts/press-release-{i}.pdf",
            host="energycommerce.house.gov",
            fmt="pdf",
            document_kind=(),
        )
        for i in range(1, 16)
    ]
    def _alpha_tag(n: int, salt: int) -> str:
        val = n * 31 + salt * 997
        chars = []
        for _ in range(5):
            chars.append(chr(ord("a") + (val % 26)))
            val //= 26
        return "".join(chars)

    unique_noise = [
        _make_row(
            2000 + i,
            filename=f"misc_banner_{i}.pdf",
            p12_text=(
                f"{_alpha_tag(i, 1).upper()} {_alpha_tag(i, 2).upper()} {_alpha_tag(i, 3).upper()}\n"
                f"{_alpha_tag(i, 4).upper()} {_alpha_tag(i, 5).upper()} {_alpha_tag(i, 6).upper()}\n"
                f"{_alpha_tag(i, 7)} {_alpha_tag(i, 8)} {_alpha_tag(i, 9)} {_alpha_tag(i, 10)} {_alpha_tag(i, 11)}."
            ),
            source_url=f"https://{_alpha_tag(i, 12)}.example.net/{_alpha_tag(i, 13)}/item_{i}.pdf",
            host=f"{_alpha_tag(i, 12)}.example.net",
            fmt="pdf",
            document_kind=(),
        )
        for i in range(1, 370)
    ]
    alias_row = _make_row(
        9000,
        filename="alias_pr.pdf",
        p12_text=recurring_cluster[0].p12_text,
        document_kind=(),
        is_alias=True,
    )
    all_rows = [*recurring_cluster, *unique_noise, alias_row]

    tail_no_alias, _ = select_tail_population(all_rows, include_aliases=False)
    tail_with_alias, _ = select_tail_population(all_rows, include_aliases=True)
    assert len(tail_with_alias) == len(tail_no_alias) + 1

    rep = discover_tail_clusters(all_rows, min_cluster_size=10, jaccard_threshold=0.35)
    assert len(rep.clusters) == 1
    assert rep.clusters[0].row_count == 15
    assert rep.clusters[0].suggested_rule_target == "cover:press-release"

