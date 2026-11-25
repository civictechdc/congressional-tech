"""Unit tests for independent bidirectional org fuzzy raw check (ct-6him AC #5)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "org_fuzzy_raw_check",
    ROOT / "scripts/measure/org_fuzzy_raw_check.py",
)
check = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(check)


def _stage_clean_parquet_release(tmp_path: Path) -> Path:
    rel = tmp_path / "release"
    rel.mkdir(parents=True)

    witnesses = [
        {
            "witness_key": "w_her_1",
            "organization": "The Heritage Foundation",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Senior Fellow",
            "witness_type": "Non-Governmental",
            "event_id": 1001,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_her_2",
            "organization": "Heritage Foundation",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Vice President",
            "witness_type": "Non-Governmental",
            "event_id": 1002,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_doe_1",
            "organization": "U.S. Department of Energy",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Deputy Secretary",
            "witness_type": "Government - Federal",
            "event_id": 1001,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_doe_2",
            "organization": "Department of Energy",
            "on_behalf_of": None,
            "location": None,
            "position": "Assistant Secretary",
            "witness_type": "Government - Federal",
            "event_id": None,
            "package_id": "CHRG-118hhrg50001",
            "superseded_by": None,
        },
        {
            "witness_key": "w_doe_3",
            "organization": "U.S. Department of Energy, Washington, DC",
            "on_behalf_of": None,
            "location": "Washington, D.C.",
            "position": "Under Secretary",
            "witness_type": "Government - Federal",
            "event_id": 1001,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_afl_1",
            "organization": "AFL-CIO",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "President",
            "witness_type": "Non-Governmental",
            "event_id": 1002,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_afl_2",
            "organization": "AFL_CIO",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Policy Director",
            "witness_type": "Non-Governmental",
            "event_id": 1002,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_cc_1",
            "organization": "U.S. Chamber of Commerce",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Chief Economist",
            "witness_type": "Non-Governmental",
            "event_id": 1002,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_cc_2",
            "organization": "Chamber of Commerce of the United States",
            "on_behalf_of": None,
            "location": "Washington, DC",
            "position": "Executive Vice President",
            "witness_type": "Non-Governmental",
            "event_id": 1002,
            "package_id": None,
            "superseded_by": None,
        },
        # Legitimate state split: must NOT trigger Direction 2 missed merge
        {
            "witness_key": "w_vcc",
            "organization": "Virginia Council of Churches",
            "on_behalf_of": None,
            "location": "Richmond, VA",
            "position": "Executive Director",
            "witness_type": "Non-Governmental",
            "event_id": 1003,
            "package_id": None,
            "superseded_by": None,
        },
        {
            "witness_key": "w_wvcc",
            "organization": "West Virginia Council of Churches",
            "on_behalf_of": None,
            "location": "Charleston, WV",
            "position": "Executive Director",
            "witness_type": "Non-Governmental",
            "event_id": 1003,
            "package_id": None,
            "superseded_by": None,
        },
    ]
    witness_orgs = [
        {"witness_key": "w_her_1", "org_id": "org_heritage"},
        {"witness_key": "w_her_2", "org_id": "org_heritage"},
        {"witness_key": "w_doe_1", "org_id": "org_doe"},
        {"witness_key": "w_doe_2", "org_id": "org_doe"},
        {"witness_key": "w_doe_3", "org_id": "org_doe"},
        {"witness_key": "w_afl_1", "org_id": "org_afl"},
        {"witness_key": "w_afl_2", "org_id": "org_afl"},
        {"witness_key": "w_cc_1", "org_id": "org_uschamber"},
        {"witness_key": "w_cc_2", "org_id": "org_uschamber"},
        {"witness_key": "w_vcc", "org_id": "org_vcc"},
        {"witness_key": "w_wvcc", "org_id": "org_wvcc"},
    ]
    orgs = [
        {"org_id": "org_heritage", "canonical_name": "The Heritage Foundation"},
        {"org_id": "org_doe", "canonical_name": "U.S. Department of Energy"},
        {"org_id": "org_afl", "canonical_name": "AFL-CIO"},
        {"org_id": "org_uschamber", "canonical_name": "U.S. Chamber of Commerce"},
        {"org_id": "org_vcc", "canonical_name": "Virginia Council of Churches"},
        {"org_id": "org_wvcc", "canonical_name": "West Virginia Council of Churches"},
    ]
    meetings = [
        {
            "event_id": 1001,
            "committees": [{"system_code": "hsif03"}],
            "transcripts": [{"package_id": "CHRG-118hhrg50001"}],
        },
        {
            "event_id": 1002,
            "committees": [{"system_code": "hswm00"}],
            "transcripts": [],
        },
        {
            "event_id": 1003,
            "committees": [{"system_code": "ssju00"}],
            "transcripts": [],
        },
    ]
    committees = [
        {"system_code": "hsif00", "name": "House Committee on Energy and Commerce"},
        {"system_code": "hsif03", "name": "Subcommittee on Energy"},
        {"system_code": "hswm00", "name": "House Committee on Ways and Means"},
        {"system_code": "ssju00", "name": "Senate Committee on the Judiciary"},
    ]

    pq.write_table(pa.Table.from_pylist(witnesses), rel / "witnesses.parquet")
    pq.write_table(pa.Table.from_pylist(witness_orgs), rel / "witness_organizations.parquet")
    pq.write_table(pa.Table.from_pylist(orgs), rel / "organizations.parquet")
    pq.write_table(pa.Table.from_pylist(meetings), rel / "meetings.parquet")
    pq.write_table(pa.Table.from_pylist(committees), rel / "committees.parquet")
    return rel


def test_valid_homogeneous_merges_and_legitimate_splits_pass_cleanly(tmp_path):
    rel = _stage_clean_parquet_release(tmp_path)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"

    report = check.main([
        "--release", str(rel),
        "--verify-planted",
        "--output", str(out_json),
        "--output-md", str(out_md),
    ])

    assert report["status"] == "passed"
    assert report["flag_count"] == 0
    assert report["direction1_flag_count"] == 0
    assert report["direction2_flag_count"] == 0
    assert report["counts"]["read_linked_appearances"] == 11
    assert report["counts"]["unread_records_total"] == 0
    assert report["counts"]["legitimate_splits_verified"] >= 1
    assert report["plants"]["virginia_west_virginia_merge"]["caught"] is True
    assert report["plants"]["conflicting_metadata_overmerge"]["caught"] is True
    assert report["plants"]["acronym_collision_overmerge"]["caught"] is True
    assert report["plants"]["missed_punctuation_suffix_merge"]["caught"] is True
    assert out_json.is_file()
    assert out_md.is_file()
    assert "Virginia Council of Churches" not in [f.get("raw_strings") for f in report["flags"]]


def test_standalone_verify_planted_flag_works_without_release(tmp_path):
    out = tmp_path / "planted.json"
    report = check.main(["--verify-planted", "--output", str(out)])
    assert report["status"] == "passed"
    assert report["plants"]["baseline_clean"]["passed"] is True
    assert report["plants"]["virginia_west_virginia_merge"]["caught"] is True
    assert report["plants"]["conflicting_metadata_overmerge"]["caught"] is True
    assert report["plants"]["acronym_collision_overmerge"]["caught"] is True
    assert report["plants"]["missed_punctuation_suffix_merge"]["caught"] is True
    saved = json.loads(out.read_text())
    assert saved["plants"]["virginia_west_virginia_merge"]["caught"] is True


def test_planted_virginia_west_virginia_and_geo_scope_overmerges_are_flagged():
    witnesses = [
        {"witness_key": "w1", "organization": "Virginia Council of Churches", "location": "Richmond, VA"},
        {"witness_key": "w2", "organization": "West Virginia Council of Churches", "location": "Charleston, WV"},
        {"witness_key": "w3", "organization": "Ohio Dental Association", "location": "Columbus, OH"},
        {"witness_key": "w4", "organization": "Oregon Dental Association", "location": "Salem, OR"},
        {"witness_key": "w5", "organization": "North Texas Food Bank", "location": "Dallas, TX"},
        {"witness_key": "w6", "organization": "South Texas Food Bank", "location": "McAllen, TX"},
        {"witness_key": "w7", "organization": "National Council of Churches", "location": "Washington, DC"},
        {"witness_key": "w8", "organization": "World Council of Churches", "location": "New York, NY"},
        {"witness_key": "w9", "organization": "Kansas City Board of Trade", "location": "Kansas City, MO"},
        {"witness_key": "w10", "organization": "Kansas Board of Trade", "location": "Topeka, KS"},
        {"witness_key": "w11", "organization": "IBEW Local 103", "location": "Boston, MA"},
        {"witness_key": "w12", "organization": "IBEW Local 26", "location": "Lanham, MD"},
    ]
    links = [
        {"witness_key": "w1", "org_id": "bad_va_wv"},
        {"witness_key": "w2", "org_id": "bad_va_wv"},
        {"witness_key": "w3", "org_id": "bad_oh_or"},
        {"witness_key": "w4", "org_id": "bad_oh_or"},
        {"witness_key": "w5", "org_id": "bad_n_s_tx"},
        {"witness_key": "w6", "org_id": "bad_n_s_tx"},
        {"witness_key": "w7", "org_id": "bad_nat_world"},
        {"witness_key": "w8", "org_id": "bad_nat_world"},
        {"witness_key": "w9", "org_id": "bad_kc_ks"},
        {"witness_key": "w10", "org_id": "bad_kc_ks"},
        {"witness_key": "w11", "org_id": "bad_local"},
        {"witness_key": "w12", "org_id": "bad_local"},
    ]
    res = check.evaluate(witnesses, links, max_flags=None)
    flagged_orgs = {f["org_id"]: f["kind"] for f in res["flags"] if f["direction"] == "direction1_overmerge"}
    assert flagged_orgs == {
        "bad_va_wv": "scope_or_state_conflict",
        "bad_oh_or": "scope_or_state_conflict",
        "bad_n_s_tx": "scope_or_state_conflict",
        "bad_nat_world": "scope_or_state_conflict",
        "bad_kc_ks": "scope_or_state_conflict",
        "bad_local": "scope_or_state_conflict",
    }


def test_planted_metadata_acronym_and_low_trigram_overmerges_are_flagged():
    witnesses = [
        # Disjoint state + federal vs state official position on distinct strings with moderate trigram cos (~0.82)
        {
            "witness_key": "m1",
            "organization": "University of Washington",
            "location": "Seattle, WA",
            "position": "State Higher Education Director",
            "witness_type": "Government - State",
            "committee": "Senate Committee on Health, Education, Labor, and Pensions",
        },
        {
            "witness_key": "m2",
            "organization": "Washington University",
            "location": "St. Louis, MO",
            "position": "U.S. Federal Commissioner",
            "witness_type": "Government - Federal",
            "committee": "Senate Committee on Health, Education, Labor, and Pensions",
        },
        # Acronym collision across expansions
        {
            "witness_key": "a1",
            "organization": "American Heart Association (AHA)",
            "location": "Dallas, TX",
            "position": "Chief Science Officer",
            "committee": "House Committee on Energy and Commerce",
        },
        {
            "witness_key": "a2",
            "organization": "American Hospital Association (AHA)",
            "location": "Chicago, IL",
            "position": "President",
            "committee": "House Committee on Energy and Commerce",
        },
        # Unrelated boilerplate-inflated pair
        {
            "witness_key": "b1",
            "organization": "American Medical Association",
            "committee": "House Committee on Energy and Commerce",
        },
        {
            "witness_key": "b2",
            "organization": "American Marketing Association",
            "committee": "House Committee on Energy and Commerce",
        },
        # Unrelated low-trigram pair
        {
            "witness_key": "u1",
            "organization": "National Wildlife Federation",
        },
        {
            "witness_key": "u2",
            "organization": "National Rifle Association",
        },
    ]
    links = [
        {"witness_key": "m1", "org_id": "bad_meta"},
        {"witness_key": "m2", "org_id": "bad_meta"},
        {"witness_key": "a1", "org_id": "bad_aha"},
        {"witness_key": "a2", "org_id": "bad_aha"},
        {"witness_key": "b1", "org_id": "bad_boiler"},
        {"witness_key": "b2", "org_id": "bad_boiler"},
        {"witness_key": "u1", "org_id": "bad_lowcos"},
        {"witness_key": "u2", "org_id": "bad_lowcos"},
    ]
    res = check.evaluate(witnesses, links, max_flags=None)
    flagged = {f["org_id"]: f["kind"] for f in res["flags"] if f["direction"] == "direction1_overmerge"}
    assert flagged == {
        "bad_meta": "metadata_context_conflict",
        "bad_aha": "acronym_collision",
        "bad_boiler": "low_trigram_similarity",
        "bad_lowcos": "low_trigram_similarity",
    }


def test_direction2_missed_merges_vs_legitimate_splits():
    witnesses = [
        # True missed merge 1: corporate suffix + punctuation miss
        {
            "witness_key": "d1",
            "organization": "Pacific Maritime Safety Institute",
            "location": "Seattle, WA",
            "position": "Executive Director",
            "committee": "House Committee on Transportation and Infrastructure",
        },
        {
            "witness_key": "d2",
            "organization": "Pacific Maritime Safety Institute, Inc.",
            "location": "Seattle, WA",
            "position": "Director of Policy",
            "committee": "House Committee on Transportation and Infrastructure",
        },
        # True missed merge 2: typo miss with same committee
        {
            "witness_key": "t1",
            "organization": "Agricultural Marketing Service, USDA",
            "position": "Administrator",
            "committee": "House Committee on Agriculture",
        },
        {
            "witness_key": "t2",
            "organization": "Agricultural Marketing Serivce, USDA",
            "position": "Deputy Administrator",
            "committee": "House Committee on Agriculture",
        },
        # Legitimate split 1: high Dice (~0.892) but VA vs WV state conflict
        {
            "witness_key": "s1",
            "organization": "Virginia Council of Churches",
            "location": "Richmond, VA",
            "committee": "Senate Committee on the Judiciary",
        },
        {
            "witness_key": "s2",
            "organization": "West Virginia Council of Churches",
            "location": "Charleston, WV",
            "committee": "Senate Committee on the Judiciary",
        },
        # Legitimate split 2: identical generic string but disjoint non-DC state locations + tiers
        {
            "witness_key": "g1",
            "organization": "Department of Transportation",
            "location": "Richmond, VA",
            "witness_type": "Government - State",
        },
        {
            "witness_key": "g2",
            "organization": "Department of Transportation",
            "location": "Austin, TX",
            "witness_type": "Government - State",
        },
        # Legitimate split 3: conflicting legal entity suffixes (Inc. vs LLC)
        {
            "witness_key": "l1",
            "organization": "Blue Ridge Energy Partners, Inc.",
            "location": "Charlotte, NC",
        },
        {
            "witness_key": "l2",
            "organization": "Blue Ridge Energy Partners, LLC",
            "location": "Charlotte, NC",
        },
    ]
    links = [
        {"witness_key": "d1", "org_id": "o_pmsi_a"},
        {"witness_key": "d2", "org_id": "o_pmsi_b"},
        {"witness_key": "t1", "org_id": "o_ams_a"},
        {"witness_key": "t2", "org_id": "o_ams_b"},
        {"witness_key": "s1", "org_id": "o_vcc"},
        {"witness_key": "s2", "org_id": "o_wvcc"},
        {"witness_key": "g1", "org_id": "o_dot_va"},
        {"witness_key": "g2", "org_id": "o_dot_tx"},
        {"witness_key": "l1", "org_id": "o_br_inc"},
        {"witness_key": "l2", "org_id": "o_br_llc"},
    ]
    res = check.evaluate(witnesses, links, max_flags=None)
    assert res["direction1_flag_count"] == 0
    assert res["direction2_flag_count"] == 2
    missed_pairs = {frozenset(f["org_ids"]) for f in res["flags"]}
    assert missed_pairs == {
        frozenset({"o_pmsi_a", "o_pmsi_b"}),
        frozenset({"o_ams_a", "o_ams_b"}),
    }
    assert res["counts"]["legitimate_splits_verified"] == 3


def test_unread_records_are_completely_named_and_categorized():
    witnesses = [
        {"witness_key": None, "organization": "Acme Corp", "source": "mods", "source_locator": "mods:witness[1]"},
        {"witness_key": "w_blank", "organization": "   ", "on_behalf_of": None},
        {"witness_key": "w_sup", "organization": "Superseded Org", "superseded_by": "w_canon"},
        {"witness_key": "w_unmatched", "organization": "Unlinked Think Tank"},
        {"witness_key": "w_placeholder", "organization": "Self"},
        {"witness_key": "w_linked_blank", "organization": ""},
        {"witness_key": "w_valid", "organization": "Valid Institute"},
        {"witness_key": "w_trunc", "organization": "Truncated Org"},
    ]
    links = [
        {"witness_key": "w_linked_blank", "org_id": "o_blank"},
        {"witness_key": "w_valid", "org_id": "o_valid"},
        {"witness_key": "", "org_id": "o_orphan_wk"},
        {"witness_key": "w_null_oid", "org_id": None},
        {"witness_key": "w_ghost", "org_id": "o_missing"},
    ]
    orgs = [
        {"org_id": "o_valid", "canonical_name": "Valid Institute"},
        {"org_id": "o_blank", "canonical_name": None},
    ]

    res = check.evaluate(witnesses, links, orgs, limit=7, max_unread_summary=3)
    unread = res["unread_records"]
    assert unread["total_unread"] == len(unread["records"]) == 11
    assert len(unread["summary"]) == 3
    assert unread["by_reason"] == {
        "blank_org_text": 1,
        "dangling_witness_org_link_missing_org": 1,
        "dangling_witness_org_link_missing_witness": 1,
        "linked_blank_org_text": 1,
        "null_or_blank_witness_key": 1,
        "orphan_linkage_null_org_id": 1,
        "orphan_linkage_null_witness_key": 1,
        "superseded_unlinked": 1,
        "truncated": 1,
        "unmatched_in_witness_organizations": 2,
    }
    by_wk = {(r["witness_key"], r["reason"]): r for r in unread["records"]}
    assert by_wk[(None, "null_or_blank_witness_key")]["source_locator"] == "mods:witness[1]"
    assert by_wk[("w_placeholder", "unmatched_in_witness_organizations")]["is_placeholder"] is True
    assert by_wk[("w_unmatched", "unmatched_in_witness_organizations")]["is_placeholder"] is False
    assert by_wk[("w_trunc", "truncated")]["raw_organization_preview"] == "Truncated Org"


def test_empty_inputs_nested_appearances_and_on_behalf_of_linkage():
    empty_res = check.evaluate([], [], [])
    assert empty_res["status"] == "passed"
    assert empty_res["flag_count"] == 0
    assert empty_res["unread_records"]["total_unread"] == 0

    nested_appearances = [
        {
            "source": "mods",
            "record_sha": b"\xab" * 32,
            "package_id": "CHRG-118shrg123",
            "event_id": None,
            "appearances": [
                {
                    "witness_key": "app_1",
                    "source_locator": "mods:witness[1]",
                    "organization": "Virginia Department of Health",
                    "on_behalf_of": "National Governors Association",
                    "location": "Richmond, VA",
                    "position": "Commissioner",
                },
                {
                    "witness_key": "app_2",
                    "source_locator": "mods:witness[2]",
                    "organization": "West Virginia Department of Health",
                    "on_behalf_of": "National Governors Association",
                    "location": "Charleston, WV",
                    "position": "Commissioner",
                },
            ],
        },
    ]
    # Link both via `on_behalf_of` role (identical valid merge) + link `organization` separately
    links = [
        {"witness_key": "app_1", "org_id": "org_nga", "role": "on_behalf_of"},
        {"witness_key": "app_2", "org_id": "org_nga", "role": "on_behalf_of"},
        {"witness_key": "app_1", "org_id": "org_va_dh", "role": "organization"},
        {"witness_key": "app_2", "org_id": "org_wv_dh", "role": "organization"},
    ]
    res = check.evaluate(nested_appearances, links)
    assert res["status"] == "passed"
    assert res["flag_count"] == 0
    assert res["counts"]["read_linked_appearances"] == 4
    assert res["counts"]["legitimate_splits_verified"] == 1


def test_fail_on_flags_exits_nonzero(tmp_path):
    w = [
        {"witness_key": "x1", "organization": "Virginia Council of Churches"},
        {"witness_key": "x2", "organization": "West Virginia Council of Churches"},
    ]
    wo = [
        {"witness_key": "x1", "org_id": "bad"},
        {"witness_key": "x2", "org_id": "bad"},
    ]
    wp = tmp_path / "w.json"
    wop = tmp_path / "wo.json"
    out = tmp_path / "out.json"
    wp.write_text(json.dumps(w))
    wop.write_text(json.dumps(wo))

    with pytest.raises(SystemExit) as exc:
        check.main(["--witnesses", str(wp), "--witness-organizations", str(wop), "--output", str(out), "--fail-on-flags"])
    assert exc.value.code == 1
    assert json.loads(out.read_text())["flags_by_kind"] == {"scope_or_state_conflict": 1}


def test_disjoint_committee_domains_aliases_and_orgs_witness_keys_fallback():
    witnesses = [
        # Acronym + matching initialism YET disjoint committee jurisdictions (`transportation` vs `energy_environment`)
        {
            "witness_key": "k1",
            "organization": "AMA",
            "state": "OH",
            "address": "13515 Yarmouth Dr, Pickerington, OH",
            "title": "President",
            "subcommittee": "House Subcommittee on Highways and Transit",
            "package_id": "CHRG-118hhrg90001",
        },
        {
            "witness_key": "k2",
            "organization": "American Medical Association",
            "state": "IL",
            "address": "330 N Wabash Ave, Chicago, IL",
            "title": "Board Chair",
            "package_id": "CHRG-118hhrg90002",
        },
        # Single-string ambiguous generic org diverging across states/tiers -> lead
        {
            "witness_key": "k3",
            "organization": "Department of Health",
            "location": "Richmond, VA",
            "position": "State Health Officer",
            "witness_type": "Government - State",
        },
        {
            "witness_key": "k4",
            "organization": "Department of Health",
            "location": "Austin, TX",
            "position": "State Health Officer",
            "witness_type": "Government - State",
        },
    ]
    orgs = [
        {"org_id": "org_ama_bad", "witness_keys": ["k1", "k2"]},
        {"org_id": "org_doh_ambig", "witness_keys": ["k3", "k4"]},
    ]
    detail = [
        {"package_id": "CHRG-118hhrg90001", "committee_keys": ["hspw00"]},
        {"package_id": "CHRG-118hhrg90002", "committee_keys": ["hsif00"]},
    ]
    committees = [
        {"system_code": "hspw00", "name": "House Committee on Transportation and Infrastructure"},
        {"system_code": "hsif00", "name": "House Committee on Energy and Commerce"},
    ]

    res = check.evaluate(witnesses, org_rows=orgs, detail_rows=detail, committee_rows=committees, max_flags=None)
    assert res["direction1_flag_count"] == 1
    flag = res["flags"][0]
    assert flag["kind"] == "metadata_context_conflict"
    assert flag["org_id"] == "org_ama_bad"
    assert any("disjoint_committee_domains" in c for c in flag["conflicts"])
    assert any("disjoint_witness_states" in c for c in flag["conflicts"])
    assert res["lead_count"] == 1
    assert res["leads"][0]["org_id"] == "org_doh_ambig"

