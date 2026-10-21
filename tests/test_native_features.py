"""Integration tests for ct-13cn, ct-dmca, ct-gziq, ct-sb0s, ct-egpe, and ct-nc7l."""
from pathlib import Path
import os
import shutil

import pyarrow as pa
import pytest

from congress_api.retention.docspec import NativeDatasets
from congress_api.retention.native_features import (
    attach_occurrence_receipts,
    backfill_scalar_group,
    evolve_catalog_schema,
    inspect_catalog_changes,
    map_locators_to_occurrences,
    read_occurrence_receipts,
    refresh_catalog_observation_summary,
)


def _binary():
    candidate = (
        os.environ.get("DOCSPEC_BINARY")
        or shutil.which("docspec")
        or "/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec"
    )
    if not candidate or not Path(candidate).is_file():
        pytest.skip("Set DOCSPEC_BINARY to the qualified maintained CLI")
    return candidate


def test_ct_13cn_inspect_catalog_changes_preserves_duplicates_nulls_and_affected_keys(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("source_id", pa.string(), nullable=False),
            pa.field("body_key", pa.string(), nullable=True),
        ])
        initial = pa.Table.from_pylist(
            [
                {"source_id": "src-1", "body_key": "body-a"},
                {"source_id": "src-2", "body_key": None},
                {"source_id": "src-3", "body_key": "body-c"},
            ],
            schema=schema,
        )
        pin1 = native.run_table(
            initial, dataset="catalog_sources", operation="op-1", definition="v1"
        )
        replacements = pa.Table.from_pylist(
            [
                {"source_id": "src-2", "body_key": "body-b-recovered"},
                {"source_id": "src-4", "body_key": "body-d"},
            ],
            schema=schema,
        )
        deletions = pa.Table.from_pylist(
            [{"source_id": "src-3"}],
            schema=pa.schema([pa.field("source_id", pa.string(), nullable=False)]),
        )
        pin2 = native.update_table(
            replacements,
            dataset="catalog_sources",
            operation="op-2",
            definition="v1",
            base=pin1["id"],
            keys=["source_id"],
            deletions=deletions,
        )

        report = inspect_catalog_changes(
            native,
            pin1,
            pin2,
            key_column="source_id",
            allow_full_fallback=False,
        )
        assert report["path"] == "forward_changes"
        assert report["added_rows"] == 2
        assert report["removed_rows"] == 2
        assert report["changed_keys"] == ["src-2", "src-3", "src-4"]

        # Same-pin comparison skips payload work and reports 0 differences.
        same = inspect_catalog_changes(native, pin2, pin2, key_column="source_id")
        assert same["path"] == "unchanged"
        assert same["added_rows"] == 0 and same["removed_rows"] == 0


def test_ct_dmca_schema_evolution_and_scalar_backfill_without_source_rewrite(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("body_key", pa.string(), nullable=True),
        ])
        initial = pa.Table.from_pylist(
            [
                {"document_id": "doc-1", "body_key": "bodies/sha256/aa/11.gz"},
                {"document_id": "doc-2", "body_key": None},
            ],
            schema=schema,
        )
        pin1 = native.run_table(
            initial, dataset="catalog_docs", operation="admit-1", definition="v1"
        )
        source_files_before = [
            obj["path"]
            for obj in pin1["dataset"]["groups"]["source"]["objects"]
            if obj["path"].endswith(".parquet")
        ]

        # 1. Metadata-only compatible field addition with default value
        evolved = evolve_catalog_schema(
            native,
            dataset="catalog_docs",
            operation="schema-add-review-state",
            base_pin=pin1,
            definition="v1",
            next_definition="v2",
            fields=[
                {"id": 1, "name": "document_id"},
                {"id": 2, "name": "body_key"},
            ],
            additions=[
                {"name": "review_status", "data_type": "string", "default": "pending"}
            ],
        )
        pin2 = evolved["pin"]
        # Old pin1 remains readable with its original 2-column schema; pin2 has review_status='pending'
        assert native.read_arrow(pin1).to_pylist() == [
            {"document_id": "doc-1", "body_key": "bodies/sha256/aa/11.gz"},
            {"document_id": "doc-2", "body_key": None},
        ]
        assert native.read_arrow(pin2).to_pylist() == [
            {
                "document_id": "doc-1",
                "body_key": "bodies/sha256/aa/11.gz",
                "review_status": "pending",
                "__docspec_supplied_3": False,
            },
            {
                "document_id": "doc-2",
                "body_key": None,
                "review_status": "pending",
                "__docspec_supplied_3": False,
            },
        ]

        # 2. Row-local scalar backfill + dependency correction + continuous backfill
        bf = backfill_scalar_group(
            native,
            dataset="catalog_docs",
            operation="bf-body-flags-1",
            base_pin=pin2,
            definition="v2",
            group="enrichment",
            group_definition="enrichment-v1",
            fields=[
                {"id": 1, "name": "has_body", "expression": "body_key IS NOT NULL"},
            ],
            continuous={"optimistic_rounds": 2, "fence_millis": 1000},
            correction={
                "id": "corr-1",
                "fields": [1, 2],
                "reason": "bind document_id alongside body_key",
            },
        )
        pin3 = bf["pin"]
        assert bf["correction"]["request"]["id"] == "corr-1"
        # Source data files were never rewritten by schema evolution or scalar backfill!
        source_files_after = [
            obj["path"]
            for obj in pin3["dataset"]["groups"]["source"]["objects"]
            if obj["path"].endswith(".parquet")
        ]
        assert source_files_after == source_files_before
        enriched = native.read_arrow(pin3, group="enrichment").to_pylist()
        assert [row["has_body"] for row in enriched] == [True, False]


def test_ct_gziq_refresh_catalog_observation_summary_full_and_incremental(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        obs_schema = pa.schema([
            pa.field("alias", pa.string(), nullable=False),
            pa.field("observation", pa.string(), nullable=False),
        ])
        initial = pa.Table.from_pylist(
            [
                {"alias": "pkg:118-hr-1", "observation": "receipt:[\"r1\",1]"},
                {"alias": "pkg:118-hr-1", "observation": "receipt:[\"r1\",1]"},
                {"alias": "pkg:118-hr-1", "observation": "receipt:[\"r1\",2]"},
                {"alias": "pkg:118-s-9", "observation": "receipt:[\"r2\",1]"},
            ],
            schema=obs_schema,
        )
        src1 = native.run_table(
            initial, dataset="source_observations", operation="obs-1", definition="v1"
        )
        full = refresh_catalog_observation_summary(
            native,
            dataset="alias_observation_counts",
            operation="sum-full-1",
            source_pin=src1,
            mode="full",
        )
        pin_full = full["pin"]
        rows_full = {
            r["alias"]: (r["total_rows"], r["distinct_observations"])
            for r in native.read_arrow(pin_full).to_pylist()
        }
        assert rows_full == {
            "pkg:118-hr-1": (3, 2),
            "pkg:118-s-9": (1, 1),
        }

        # Incremental update adds one observation to pkg:118-s-9
        added = pa.Table.from_pylist(
            [{"alias": "pkg:118-s-9", "observation": "receipt:[\"r2\",2]"}],
            schema=obs_schema,
        )
        src2 = native.update_table(
            added,
            dataset="source_observations",
            operation="obs-2",
            definition="v1",
            base=src1["id"],
            keys=["alias", "observation"],
        )
        inc = refresh_catalog_observation_summary(
            native,
            dataset="alias_observation_counts",
            operation="sum-inc-2",
            source_pin=src2,
            base_pin=pin_full,
            mode="incremental",
        )
        rows_inc = {
            r["alias"]: (r["total_rows"], r["distinct_observations"])
            for r in native.read_arrow(inc["pin"]).to_pylist()
        }
        assert rows_inc == {
            "pkg:118-hr-1": (3, 2),
            "pkg:118-s-9": (2, 2),
        }


def test_ct_sb0s_attach_and_read_occurrence_receipts_with_zero_source_rewrites(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("locator", pa.string(), nullable=False),
            pa.field("document_id", pa.string(), nullable=False),
        ])
        source = pa.Table.from_pylist(
            [
                {"locator": "receipt:[\"house\",1]", "document_id": "doc-1"},
                {"locator": "receipt:[\"house\",2]", "document_id": "doc-2"},
            ],
            schema=schema,
        )
        pin1 = native.run_table(
            source, dataset="catalog_sources", operation="src-1", definition="v1"
        )
        loc_map = map_locators_to_occurrences(
            native, pin1, locator_column="locator"
        )
        inv_map = {
            occ: loc for loc, occs in loc_map.items() for occ in occs
        }

        # Attach ordered duplicate receipts and a null receipt without rewriting source
        pin2 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="ev-1",
            base_pin=pin1,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[
                ("receipt:[\"house\",1]", "review:approved:pass-1"),
                ("receipt:[\"house\",1]", "review:approved:pass-2"),
                ("receipt:[\"house\",2]", None),
            ],
        )
        assert pin2["dataset"]["groups"]["source"] == pin1["dataset"]["groups"]["source"]
        attached = read_occurrence_receipts(native, pin2, occurrence_to_locator=inv_map)
        by_loc = {}
        for item in attached:
            by_loc.setdefault(item["locator"], []).append(item["evidence"])
        assert by_loc == {
            "receipt:[\"house\",1]": ["review:approved:pass-1", "review:approved:pass-2"],
            "receipt:[\"house\",2]": [None],
        }

        # Delete receipt on house:2 while replacing house:1
        pin3 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="ev-2",
            base_pin=pin2,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[("receipt:[\"house\",1]", "review:final")],
            deletions=["receipt:[\"house\",2]"],
        )
        assert pin3["dataset"]["groups"]["source"] == pin1["dataset"]["groups"]["source"]
        after_del = read_occurrence_receipts(native, pin3, occurrence_to_locator=inv_map)
        assert [(r["locator"], r["evidence"]) for r in after_del] == [
            ("receipt:[\"house\",1]", "review:final")
        ]


def test_ct_egpe_shared_host_across_archive_and_news_callers(tmp_path):
    """Archive NativeDatasets and news DocSpecClient share one loopback Host on the same workspace."""
    from docspec_client.docspec_host import _hosts
    from news_lake.storage.docspec_backend import DocSpecClient

    binary = _binary()
    ws = tmp_path / "shared-ws"
    with NativeDatasets(binary, ws) as archive_client, DocSpecClient(ws, binary=binary) as news_client:
        t_arch = pa.Table.from_pylist([{"id": "a1", "val": 10}])
        p_arch = archive_client.run_table(
            t_arch, dataset="archive_leaf", operation="arch-1", definition="v1"
        )
        t_news = pa.Table.from_pylist([{"id": "n1", "name": "Outlet 1"}])
        p_news = news_client.run_table(
            t_news, "news_outlets", "news-1"
        )
        # Both callers share the exact same underlying Host instance and child PID!
        assert archive_client._host is news_client._native._host
        assert archive_client._host.owners == 2
        assert (os.getpid(), str(ws.resolve())) in _hosts
        assert archive_client.read_arrow(p_arch).to_pylist() == [{"id": "a1", "val": 10}]
        assert news_client.read_arrow(p_news).to_pylist() == [{"id": "n1", "name": "Outlet 1"}]
