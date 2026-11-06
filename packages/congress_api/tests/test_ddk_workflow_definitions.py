"""Admit standard metadata and check selected meanings against maintained owners.

These tests do not execute acquisition, native storage or publication. Scalar
subset checks do not establish complete output shape or workflow acceptance.
"""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tomllib
from urllib.parse import unquote, urlsplit

from ddk.catalog import build_catalog
from ddk.core import check_project


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "model/ddk-workflows"
PROJECT = DEFINITIONS / "project.ddk.json"
SEMANTICS = "https://congressional-tech.org/ddk/workflow-semantics/v1"


def document(path):
    return json.loads(path.read_text())


def datasets(workflow):
    return {row["id"]: row for row in document(DEFINITIONS / workflow / "datasets.odcs.json")["schema"]}


def properties(dataset):
    return {row["name"]: row for row in dataset["properties"]}


def literal_assignment(path, name):
    """Read an inert source constant without importing an acquiring script."""
    for statement in ast.parse(path.read_text()).body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    raise AssertionError(f"Missing literal source constant {name} in {path}")


def test_maintained_core_and_catalog_admit_declared_interfaces_only():
    report = check_project(PROJECT, permitted_roots=[ROOT])
    assert report["decision"] == "passed", report
    assert not report["operationalErrors"]
    built = build_catalog(PROJECT, permitted_roots=[ROOT])
    assert built["decision"] == "passed", built
    catalog = built["metadata"]["catalog"]
    assert len(catalog["products"]) == 4
    assert len(catalog["datasets"]) == 28
    for name in ("versions", "sources", "representations", "releases", "selections", "runs", "checks"):
        assert catalog[name] == [], f"Semantic metadata must not assert observed {name}"
    for path in DEFINITIONS.glob("*/components/*.ddk.json"):
        component = document(path)
        assert "implementation" not in component
        assert component["extensions"][SEMANTICS]["executionStatus"] == "interface_only"
        assert component["extensions"][SEMANTICS]["runtimeBinding"] == "unqualified"


def test_owner_links_remain_local_and_do_not_duplicate_physical_schemas():
    for path in DEFINITIONS.glob("*/datasets.odcs.json"):
        data = document(path)
        assert data["status"] == "draft"
        for dataset in data["schema"]:
            assert dataset["authoritativeDefinitions"]
            for link in dataset["authoritativeDefinitions"]:
                parsed = urlsplit(link["url"])
                assert not parsed.scheme and not parsed.netloc
                target = (path.parent / unquote(parsed.path)).resolve()
                assert target.is_relative_to(ROOT) and target.is_file(), link
            for prop in dataset["properties"]:
                assert "physicalType" not in prop and "physicalName" not in prop
                assert prop["logicalType"] in {"string", "integer", "number", "boolean", "date", "timestamp"}
        assert "servers" not in data


def test_news_record_denominator_and_scalar_subset_follow_actual_schema_owner():
    from news_lake.contract.records import SCHEMA

    declared = datasets("news")
    retained = {
        value["x-iceberg"]["table"].removeprefix("news.").replace("_", "-"): (kind, value)
        for kind, value in SCHEMA["$defs"].items() if "x-iceberg" in value
    }
    assert set(declared) == set(retained) | {"fetch-outcomes", "politician-articles", "coverage-daily"}
    for name, (kind, owner) in retained.items():
        subset = properties(declared[name])
        assert set(subset) <= set(owner["properties"])
        assert {name for name, value in subset.items() if value.get("required")} <= set(owner["required"])
        assert declared[name]["authoritativeDefinitions"][0]["url"].endswith(f"#/$defs/{kind}")
        for field, value in subset.items():
            if "enum" in value:
                assert {row["value"] for row in value["enum"]} == set(owner["properties"][field]["enum"])
    assert properties(declared["fetch-outcomes"])["metadata_only"]["logicalType"] == "boolean"
    # The actual input owner remains stricter than the scalar catalog subset:
    # metadata-only captures cannot claim retained payload fields.
    from news_lake.contract.records import validate_shape
    from news_lake.contract.errors import ContractError
    import pytest

    capture = {"kind": "capture", "id": "00000000-0000-0000-0000-000000000001",
               "recorded_at": "2026-11-06T00:00:00Z", "observed_at": "2026-11-06T00:00:00Z",
               "provider": "rss", "request_url": "https://example.org/feed", "access": "metadata_only",
               "status": "succeeded"}
    assert validate_shape(capture) == capture
    with pytest.raises(ContractError):
        validate_shape({**capture, "payload_uri": "s3://raw/forbidden"})
    with pytest.raises(ContractError):
        validate_shape({**capture, "rights_basis": None})


def test_compatibility_scalar_fields_are_subset_of_real_output_tables():
    from committee_explorer.parquet import TABLE_SCHEMAS, SOURCE_SCHEMA
    from committee_meeting.publication import PublicationManifest

    declared = datasets("committee-compatibility")
    actual = {name.replace("_", "-"): set(schema.names) for name, schema in TABLE_SCHEMAS.items()}
    actual["sources"] = set(SOURCE_SCHEMA.names)
    actual["manifest"] = set(PublicationManifest.model_fields)
    assert set(declared) == set(actual)
    for name, dataset in declared.items():
        assert set(properties(dataset)) <= actual[name]
    component = document(DEFINITIONS / "committee-compatibility/components/export-parquet.ddk.json")
    assert component["parameters"]["properties"]["format"]["enum"] == ["parquet"]


def test_retired_json_export_is_rejected_by_maintained_call_check(tmp_path):
    copied = tmp_path / "definitions"
    shutil.copytree(DEFINITIONS, copied)
    design_path = copied / "committee-compatibility/workflow.ddk.json"
    design = document(design_path)
    design["steps"]["export"]["arguments"]["format"]["literal"] = "json"
    design_path.write_text(json.dumps(design))
    report = check_project(copied / "project.ddk.json", permitted_roots=[tmp_path])
    assert report["decision"] == "failed"
    failures = [row for row in report["checks"] if row["status"] == "failed"]
    assert any(row["group"] == "core.calls" for row in failures), failures


def test_youtube_semantics_keep_unknown_and_original_source_fields():
    from youtube_api.models import YoutubePlaylistItem
    from youtube_api.interpretation import availability_facts, source_time

    incoming = {"snippet": {"resourceId": {"videoId": "v"}, "publishedAt": "2025-01-01T00:00:00Z"},
                "newPublisherField": {"preserve": True}}
    assert YoutubePlaylistItem.model_validate(incoming).source_dict() == incoming
    row = {"publishedAt": incoming["snippet"]["publishedAt"], "caption": False}
    assert source_time(row, basis="playlist_added").instant is not None
    assert source_time(row, basis="video_publication").instant is None
    assert availability_facts(row, evaluated_at=datetime(2026, 11, 6, tzinfo=timezone.utc)).captions.status == "unknown"
    declared = datasets("youtube")
    video = properties(declared["videos"])
    assert not video["videoPublishedAt"]["required"] and not video["caption"]["required"]
    assert {row["value"] for row in properties(declared["caption-index"])["kind"]["enum"]} == {"manual", "auto", "none"}
    # These are explicitly source-owned cache meanings, without an authored
    # native schema or executable storage binding. Prose is not an API.
    assert declared["videos"]["authoritativeDefinitions"][0]["url"].endswith(
        "youtube_api/fetch/youtube_event_fetcher.py#parse_video_details"
    )
    assert all("physicalType" not in field for field in video.values())
    component = document(DEFINITIONS / "youtube/components/capture-channels.ddk.json")
    assert "implementation" not in component
    assert component["extensions"][SEMANTICS]["runtimeBinding"] == "unqualified"


def test_inflation_grid_and_series_use_maintained_names_and_distinct_units():
    sources = ROOT / "apps/inflation_gsheets/src/sources"
    months = literal_assignment(sources / "bls.py", "MONTH_ORDER")
    fred = literal_assignment(sources / "fred.py", "FRED_SERIES")
    declared = datasets("inflation")
    grid = properties(declared["historical-grid"])
    assert list(grid) == ["year", *months]
    assert grid["year"]["required"]
    for month in months:
        assert not grid[month]["required"] and "index level" in grid[month]["description"]
    combined = properties(declared["inflation-table"])
    assert list(combined) == ["date", "bls_yoy", *fred, "adobe", "pricestats", "aggregate"]
    assert all(not value["required"] for name, value in combined.items() if name != "date")
    assert "not an official" in combined["aggregate"]["description"]
    assert "policy remains unresolved" in declared["inflation-table"]["description"]


def test_bounded_census_binds_current_declared_console_entrypoints():
    census = document(DEFINITIONS / "source-entrypoints.json")
    scripts = {}
    for path in [ROOT / "pyproject.toml", *ROOT.glob("packages/*/pyproject.toml"), *ROOT.glob("apps/*/pyproject.toml")]:
        for command, target in tomllib.loads(path.read_text()).get("project", {}).get("scripts", {}).items():
            scripts[command] = target.split(":", 1)[0]
    listed = {command: row["module"] for row in census["console_scripts"] for command in row["commands"]}
    assert listed == scripts
    assert census["scope"]["file_count"] <= census["scope"]["bounds"]["max_files"]
    assert census["scope"]["source_bytes_read"] <= census["scope"]["bounds"]["max_source_bytes"]
    for row in census["entries"]:
        assert (ROOT / row["path"]).is_file(), row["path"]
        assert row["owner"] and row["replacement_status"] == "unverified"
