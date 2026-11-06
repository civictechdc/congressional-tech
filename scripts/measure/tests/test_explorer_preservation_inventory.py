"""Migration evidence must expose missing values and cannot overclaim parity."""

import json

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from measure.explorer_preservation_inventory import (
    csv_profile, decision_acceptance, decision_source_acceptance, identity, issue_accounting, native_input_comparison,
    parquet_profile, row_ledgers,
)


def test_profile_distinguishes_missing_empty_and_nested_occurrences(tmp_path):
    path = tmp_path / "materials.parquet"
    schema = pa.schema([("name", pa.string()), ("files", pa.list_(pa.struct([("url", pa.string())])))])
    pq.write_table(pa.Table.from_pylist([
        {"name": None, "files": None}, {"name": "", "files": []},
        {"name": "x", "files": [{"url": None}, {"url": ""}, {"url": "u"}]},
    ], schema=schema), path)
    result = parquet_profile(path)
    assert result["rows"] == 3
    assert result["fields"]["name"] == dict(type="string", values=3, null=1, empty=1)
    assert result["fields"]["files[].url"] == dict(type="string", values=3, null=1, empty=1)


def test_csv_missing_cell_is_not_an_explicit_empty_string(tmp_path):
    path = tmp_path / "facts.csv"
    path.write_text("a,b\n1,\n2\n")
    assert csv_profile(path)["fields"]["b"] == dict(type="CSV string", values=2, null=1, empty=1)


def test_wrong_input_bytes_are_refused(tmp_path):
    path = tmp_path / "file"
    path.write_text("changed")
    with pytest.raises(ValueError, match="digest mismatch"):
        identity(path, "0" * 64)


def test_relocated_input_is_same_but_changed_selector_is_not():
    selected = dict(captures=dict(snapshot=1, table_uuid="a"),
                    spicy_regs=dict(path="old", sha256="a", size=1),
                    recording_decision_files=[dict(path="a", key="key", sha256="b", size=2)])
    candidate = dict(captures=dict(snapshot=1, table_uuid="b"),
                     spicy_regs=dict(path="new", sha256="a", size=1),
                     recording_decision_files=[dict(path="b", key="key", sha256="b", size=2)])
    result = native_input_comparison(selected, candidate)
    assert not result["captures"]["same"]
    assert result["spicy_regs"]["same"] and result["recording_decision_files"]["same"]
    assert not result["readings"]["same"]


@pytest.mark.parametrize("wrong", [None, "verdict", "note", "missing_note"])
def test_all_decision_values_detect_a_planted_wrong_verdict(tmp_path, wrong):
    path = tmp_path / "decisions.jsonl"
    record = dict(id="id", subject_kind="package", subject_id="pkg", verdict="found",
                  video_refs=["v", "https://x"], note=None if wrong == "missing_note" else "review", supersedes=None)
    path.write_text(json.dumps(record) + "\n")
    rows = [dict(source_ref="recording_decisions:id", basis="curated", subject_kind="package", subject_id="pkg",
                 decision="no_video_found" if wrong == "verdict" else "found", video_key="youtube:v", url=None,
                 note="review | disputed by invented" if wrong == "note" else "review", status="decided"),
            dict(source_ref="recording_decisions:id", basis="curated", subject_kind="package", subject_id="pkg",
                 decision="found", video_key=None, url="https://x", note="review", status="decided")]
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / "recording_matches.parquet")
    with duckdb.connect() as db:
        result = decision_acceptance(db, path, tmp_path)
    assert result["accepted"] is (wrong is None)
    assert result["decisions"] == ({"different_or_missing": 1} if wrong else {"preserved": 1})


def test_row_ledger_preserves_duplicate_rows_and_flags_partial_material(tmp_path):
    old, new, out = (tmp_path / name for name in ("old", "new", "out"))
    for path in (old, new, out):
        path.mkdir()
    def write(root, name, rows, schema=None):
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), root / (name + ".parquet"))
    write(old, "meetings", [dict(id="m", source_ids=["s"])])
    write(old, "sources", [dict(id="s", identifier_value="a|b|c|1", identifier_scheme="congress.gov:record", url="https://u")])
    write(old, "committees", [dict(id="c", committee_code="hsru00")])
    schema = pa.schema([("id", pa.string()), ("recording_url", pa.string()), ("files", pa.list_(pa.struct([("url", pa.string())])))])
    write(old, "materials", [dict(id="same", recording_url=None, files=[dict(url="https://u"), dict(url="https://missing")]),
                             dict(id="same", recording_url=None, files=[])], schema)
    write(old, "issues", [dict(id="i")])
    write(new, "meetings", [dict(event_id=1)])
    write(new, "sources", [dict(url="https://u")])
    write(new, "videos", [dict(video_key="youtube:v")])
    write(new, "committees", [dict(system_code="hsru00")])
    with duckdb.connect() as db:
        result = row_ledgers(db, old, new, out)
    assert result["materials"]["dispositions"] == {"some_url_present_values_unverified": 1, "no_native_material_url": 1}
    assert result["materials"]["rows"] == 2
    assert result["issues"]["dispositions"] == {"retained_issue_history_requires_equivalence_review": 1}
    assert result["witnesses"]["owner"] == "ct-x78c"


def test_source_only_decision_fields_are_checked_even_when_native_verdict_matches(tmp_path):
    overrides = tmp_path / "hearing_video_overrides.csv"
    overrides.write_text("package_id,verdict,video_ids,channel,lock,note\np,found,v,@c,yes,n\n")
    (tmp_path / "meeting_recordings_found.csv").write_text("event_id,recording,found_by,note\n")
    path = tmp_path / "decisions.jsonl"
    record = dict(subject_kind="package", subject_id="p", verdict="found", video_refs=["v"],
                  channel="@c", lock="yes", note="n", found_by=None,
                  origin=dict(path="hearing_video_overrides.csv", sha256=identity(overrides)["sha256"]))
    path.write_text(json.dumps(record) + "\n")
    assert decision_source_acceptance(path, tmp_path)["accepted"]
    record["lock"] = None
    path.write_text(json.dumps(record) + "\n")
    result = decision_source_acceptance(path, tmp_path)
    assert not result["accepted"] and result["gaps"][0]["fields"] == ["lock"]


def test_adjudicated_issues_are_not_treated_as_current_coverage_or_discarded(tmp_path):
    pq.write_table(pa.Table.from_pylist([
        dict(title="Sources disagree about label", status="dismissed"),
        dict(title="Sources disagree about title", status="open"),
        dict(title="This recording has no verified meeting association.", status="open"),
        dict(title="Legacy House state omits alternate file URLs and source ownership", status="open"),
    ]), tmp_path / "issues.parquet")
    pq.write_table(pa.Table.from_pylist([dict(provider="curated-issue-decisions", retained_sha256="sha", retained_uri="body")]), tmp_path / "sources.parquet")
    with duckdb.connect() as db:
        result = issue_accounting(db, tmp_path)
    assert result["rows"] == 4
    assert {v["disposition"] for v in result["classes"]} == {"historical_adjudication_retained", "historical_conflict_alternatives_retained", "association_gap_requires_native_reconciliation", "source_shape_gap_requires_native_reconciliation"}
    assert result["adjudication_sources"] == dict(rows=1, distinct_body_digests=1, retained_locators=1)
