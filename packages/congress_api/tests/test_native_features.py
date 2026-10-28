"""Integration tests for ct-13cn, ct-dmca, ct-gziq, ct-sb0s, ct-egpe, and ct-nc7l."""
from pathlib import Path
import json
import os
import shutil

import pyarrow as pa
import pytest

from native_test_helpers import NativeCITestClient as NativeDatasets, NewsCITestClient as DocSpecClient
from testing_fakes import SelectorStore, MemoryStore
from congress_api.retention.native_features import (
    attach_occurrence_receipts,
    backfill_scalar_group,
    evolve_catalog_schema,
    inspect_catalog_changes,
    map_locators_to_occurrences,
    read_occurrence_receipts,
    refresh_catalog_join,
    refresh_catalog_observation_summary,
)


def _binary():
    from docspec_client import resolve_docspec_binary
    try:
        candidate = resolve_docspec_binary()
    except FileNotFoundError:
        candidate = None
    if not candidate or not Path(candidate).is_file():
        pytest.skip("Set DOCSPEC_BINARY to the qualified maintained CLI")
    return str(candidate)


def test_ct_13cn_inspect_catalog_changes_preserves_duplicates_nulls_and_affected_keys(tmp_path):
    from collections import Counter

    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("source_id", pa.string(), nullable=False),
            pa.field("body_key", pa.string(), nullable=True),
        ])
        initial_rows = [
            {"source_id": "src-1", "body_key": "body-a"},
            {"source_id": "src-2", "body_key": None},
            {"source_id": "src-3", "body_key": "body-c"},
            {"source_id": "src-dup", "body_key": "body-dup"},
            {"source_id": "src-dup", "body_key": "body-dup"},
        ]
        initial = pa.Table.from_pylist(initial_rows, schema=schema)
        pin1 = native.run_table(
            initial, dataset="catalog_sources", operation="op-1", definition="v1"
        )
        replacements = pa.Table.from_pylist(
            [
                {"source_id": "src-2", "body_key": "body-b-recovered"},
                {"source_id": "src-4", "body_key": "body-d"},
                {"source_id": "src-dup", "body_key": "body-dup"},
                {"source_id": "src-dup", "body_key": "body-dup"},
                {"source_id": "src-dup", "body_key": "body-dup"},
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

        # 1. Compare identity="occurrences" vs identity="values" and verify against Counter multiset oracle
        report_occ = inspect_catalog_changes(
            native,
            pin1,
            pin2,
            identity="occurrences",
            key_column="source_id",
            allow_full_fallback=False,
        )
        report_val = inspect_catalog_changes(
            native,
            pin1,
            pin2,
            identity="values",
            key_column="source_id",
            allow_full_fallback=False,
        )
        assert report_occ["path"] == "forward_changes"
        assert report_val["path"] == "forward_changes"
        assert report_occ["changed_keys"] == ["src-2", "src-3", "src-4", "src-dup"]
        assert report_val["changed_keys"] == ["src-2", "src-3", "src-4", "src-dup"]

        # Under identity="occurrences", replacing src-dup (2 copies -> 3 copies) removes the 2 old occurrences
        # and adds the 3 new occurrences (total 9 row-occurrence transitions); under identity="values",
        # multiset difference emits only the +1 net copy (total 5 value transitions)!
        assert len(report_occ["changed_occurrences"]) == report_occ["added_rows"] + report_occ["removed_rows"] == 9
        assert report_val["added_rows"] + report_val["removed_rows"] == 5
        assert len(report_val["changed_occurrences"]) < len(report_occ["changed_occurrences"])

        canon = lambda r: json.dumps(r, sort_keys=True, separators=(",", ":"))
        before_multiset = Counter(canon(r) for r in native.read_arrow(pin1).to_pylist())
        after_multiset = Counter(canon(r) for r in native.read_arrow(pin2).to_pylist())
        expected_val_added = after_multiset - before_multiset
        expected_val_removed = before_multiset - after_multiset
        actual_val_added = Counter(canon(r) for r in report_val["added_records"])
        actual_val_removed = Counter(canon(r) for r in report_val["removed_records"])
        assert actual_val_added == expected_val_added
        assert actual_val_removed == expected_val_removed
        # Explicitly verify null body_key in removed_records and duplicate multiplicity in added_records
        assert any(r["source_id"] == "src-2" and r["body_key"] is None for r in report_val["removed_records"])
        assert sum(1 for r in report_occ["added_records"] if r["source_id"] == "src-dup") == 3
        assert sum(1 for r in report_val["added_records"] if r["source_id"] == "src-dup") == 1

        # 2. Verify duplicate receipt multiset difference on group="evidence"
        loc_map = map_locators_to_occurrences(native, pin2, locator_column="source_id")
        pin3 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="op-3",
            base_pin=pin2,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[("src-4", "receipt:dup"), ("src-4", None)],
        )
        pin4 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="op-4",
            base_pin=pin3,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[("src-4", "receipt:dup"), ("src-4", "receipt:dup"), ("src-4", None)],
        )
        ev_diff = inspect_catalog_changes(native, pin3, pin4, group="evidence", allow_full_fallback=False)
        assert ev_diff["evidence_changed"] is True
        assert ev_diff["added_rows"] == 1
        assert ev_diff["removed_rows"] == 0
        assert ev_diff["added_records"][0]["evidence"] == "receipt:dup"

        # 3. Missing history / forced full fallback refusal when allow_full_fallback=False
        with pytest.raises(ValueError, match="refused full comparison fallback"):
            inspect_catalog_changes(
                native, pin1, pin2, allow_full_fallback=False, force_full=True
            )

        # 4. Same-pin comparison skips payload work and reports 0 differences.
        same = inspect_catalog_changes(native, pin2, pin2, key_column="source_id")
        assert same["path"] == "unchanged"
        assert same["added_rows"] == 0 and same["removed_rows"] == 0
        assert same["read_bytes"] == 0 and same["returned_bytes"] == 0


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


def test_ct_dmca_raw_storage_evolve_state_schema_and_scalar_backfill(tmp_path):
    from congress_api.retention.raw_archive import LEGACY_STATE_SCHEMA as STATE_SCHEMA
    from congress_api.retention.raw_storage import RawStorage

    binary = _binary()
    store = SelectorStore()
    prior_schema = pa.schema([
        f for f in STATE_SCHEMA if f.name not in {"next_attempt_at", "links_scanned"}
    ])
    with NativeDatasets(binary, tmp_path / "ws") as native:
        owner = RawStorage(store, native, state_schema=prior_schema)
        seed_states = pa.Table.from_pylist(
            [
                {
                    "url": "https://example.gov/a.pdf",
                    "outcome": "saved",
                    "attempts": 1,
                    "body_key": "bodies/a.gz",
                },
                {
                    "url": "https://example.gov/b.pdf",
                    "outcome": "failed",
                    "attempts": 2,
                    "body_key": None,
                },
            ],
            schema=prior_schema,
        )
        snap1 = owner.publish(owner.prepare(owner.snapshot(), operation="seed-v1", states=seed_states))
        next_owner, prepared = owner.evolve_state_schema(
            snap1,
            operation="state-v2",
            next_schema=STATE_SCHEMA,
            scalar_backfill={
                "group": "state_scalars",
                "group_definition": "raw-state-scalars-v1",
                "fields": [{"id": 1, "name": "has_body", "expression": "body_key IS NOT NULL"}],
            },
            continuous={"optimistic_rounds": 2, "fence_millis": 1000},
            correction={"id": "state-corr-1", "reason": "bind url and body_key"},
        )
        snap2 = next_owner.publish(prepared)
        # Old snapshot remains readable with its original 11-column schema
        assert snap1.states().equals(seed_states)
        # Evolved snapshot exposes the full 13-column STATE_SCHEMA with links_scanned=False default
        evolved_rows = snap2.states().to_pylist()
        assert [r["links_scanned"] for r in evolved_rows] == [False, False]
        assert [r["next_attempt_at"] for r in evolved_rows] == [None, None]
        # Historical rows report __docspec_supplied_* == False
        supplied_a = snap2.state_supplied("https://example.gov/a.pdf")
        supplied_cols = sorted(k for k in supplied_a if k.startswith("__docspec_supplied_"))
        assert len(supplied_cols) == 2 and all(supplied_a[k] is False for k in supplied_cols)
        # Live selected state leaf pin directly references the release containing both evolved source and state_scalars
        leaf_info = next(iter(prepared["leaves"].values()))
        bf_pin = leaf_info["backfill"]["pin"]
        _, leaf_ref = next(next_owner.state_routes.leaf_items(snap2.manifest["state"]["root"]))
        assert leaf_ref["release"] == bf_pin
        assert bf_pin["dataset"]["groups"]["source"]["objects"] == (
            leaf_info["evolved_pin"]["dataset"]["groups"]["source"]["objects"]
        )
        scalars = native.read_arrow(leaf_ref["release"], group="state_scalars").to_pylist()
        assert [r["has_body"] for r in scalars] == [True, False]

        # Post-evolution update with an explicit None for next_attempt_at proves omission (False) vs explicit null (True)
        post_states = pa.Table.from_pylist(
            [
                {
                    "url": "https://example.gov/c.pdf",
                    "outcome": "failed",
                    "attempts": 1,
                    "body_key": None,
                    "next_attempt_at": None,
                    "links_scanned": False,
                },
            ],
            schema=STATE_SCHEMA,
        )
        snap3 = next_owner.publish(next_owner.prepare(snap2, operation="state-v3", states=post_states))
        supplied_a_after = snap3.state_supplied("https://example.gov/a.pdf")
        supplied_c_after = snap3.state_supplied("https://example.gov/c.pdf")
        assert supplied_a_after["next_attempt_at"] is None and supplied_c_after["next_attempt_at"] is None
        assert all(supplied_a_after[k] is False for k in supplied_cols)
        assert all(supplied_c_after[k] is True for k in supplied_cols)


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


# -- ct-9few: ChangeDescriptor field names (fallback / evidence_refs_changed) ------------


def test_ct_9few_descriptor_uses_serialized_field_names_and_reports_forced_fallback(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([pa.field("source_id", pa.string(), nullable=False)])
        initial = pa.Table.from_pylist(
            [{"source_id": "a"}, {"source_id": "b"}], schema=schema
        )
        pin1 = native.run_table(
            initial, dataset="catalog_sources", operation="op-1", definition="v1"
        )
        replacement = pa.Table.from_pylist(
            [{"source_id": "a"}], schema=schema
        )
        pin2 = native.update_table(
            replacement,
            dataset="catalog_sources",
            operation="op-2",
            definition="v1",
            base=pin1["id"],
            keys=["source_id"],
        )
        # The serialized descriptor uses `fallback` (ComparisonFallback, snake_case),
        # never `fallback_reason`.
        with native.changes_batches(pin1, pin2, force_full=True) as (descriptor, _):
            assert descriptor["fallback"] == "forced"
            assert "fallback_reason" not in descriptor
            assert descriptor["path"] == "full"
        # inspect_catalog_changes surfaces the real reason instead of None.
        report = inspect_catalog_changes(
            native, pin1, pin2, allow_full_fallback=True
        )
        assert report["path"] in {"forward_changes", "full"}
        if report["path"] == "full":
            assert isinstance(report["fallback_reason"], str)
            assert report["fallback_reason"]
        # Same-pin streams carry no fallback at all.
        same = inspect_catalog_changes(native, pin2, pin2)
        assert same["fallback_reason"] is None
        assert same["path"] == "unchanged"


def test_ct_9few_receipt_update_sets_evidence_changed_flag(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("locator", pa.string(), nullable=False),
            pa.field("document_id", pa.string(), nullable=False),
        ])
        source = pa.Table.from_pylist(
            [{"locator": "receipt:[\"h\",1]", "document_id": "doc-1"}], schema=schema
        )
        pin1 = native.run_table(
            source, dataset="catalog_sources", operation="src-1", definition="v1"
        )
        loc_map = map_locators_to_occurrences(native, pin1, locator_column="locator")
        pin2 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="ev-1",
            base_pin=pin1,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[("receipt:[\"h\",1]", "review:approved")],
        )
        # ComparisonEffects serializes `evidence_refs_changed`; the Python report
        # must reflect receipt changes instead of a permanently False flag.
        report = inspect_catalog_changes(native, pin1, pin2)
        assert report["evidence_changed"] is True


# -- ct-x0nk: setup-native-runtime descriptor/credential validation ----------------------


def _load_setup_module():
    import importlib.util
    path = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "setup-native-runtime.py"
    spec = importlib.util.spec_from_file_location("setup_native_runtime_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ct_x0nk_artifact_descriptor_accepts_only_exact_contracts():
    setup = _load_setup_module()
    sha = "a" * 64
    good = setup.artifact_descriptor(json.dumps({
        "version": 1, "platform": "linux-amd64", "source_revision": "b" * 40,
        "bucket": "qualified-runtime-bucket",
        "key": f"runtime/docspec/{'b' * 40}/linux-amd64/{sha}/docspec",
        "bytes": 1024, "sha256": sha,
    }))
    assert good["build_features"] == ["remote"]
    for bad in [
        {},  # missing required fields
        {"version": 2, "platform": "linux-amd64", "source_revision": "b" * 40,
         "bucket": "qualified-runtime-bucket", "key": "x", "bytes": 1, "sha256": sha},
        {"version": 1, "platform": "darwin-arm64", "source_revision": "b" * 40,
         "bucket": "qualified-runtime-bucket", "key": "k", "bytes": 1, "sha256": sha},
        {"version": 1, "platform": "linux-amd64", "source_revision": "short",
         "bucket": "qualified-runtime-bucket", "key": "k", "bytes": 1, "sha256": sha},
        {"version": 1, "platform": "linux-amd64", "source_revision": "b" * 40,
         "bucket": "Bad_Bucket", "key": "k", "bytes": 1, "sha256": sha},
        {"version": 1, "platform": "linux-amd64", "source_revision": "b" * 40,
         "bucket": "qualified-runtime-bucket", "key": "mismatched/key", "bytes": 1,
         "sha256": sha},
        {"version": 1, "platform": "linux-amd64", "source_revision": "b" * 40,
         "bucket": "qualified-runtime-bucket", "bytes": 1, "sha256": sha},
        {"version": 1, "platform": "linux-amd64", "source_revision": "b" * 40,
         "bucket": "qualified-runtime-bucket",
         "key": f"runtime/docspec/{'b' * 40}/linux-amd64/{sha}/docspec",
         "bytes": 1, "sha256": sha, "build_features": ["test-util"]},
    ]:
        with pytest.raises(setup.SetupFailure):
            setup.artifact_descriptor(json.dumps(bad))


def test_ct_x0nk_engine_credentials_require_exactly_the_three_secrets():
    setup = _load_setup_module()
    good = setup.engine_credentials(json.dumps({
        "DOCSPEC_CATALOG_TOKEN": "t", "DOCSPEC_S3_ACCESS_KEY_ID": "a",
        "DOCSPEC_S3_SECRET_ACCESS_KEY": "s",
    }))
    assert set(good) == {
        "DOCSPEC_CATALOG_TOKEN", "DOCSPEC_S3_ACCESS_KEY_ID", "DOCSPEC_S3_SECRET_ACCESS_KEY"
    }
    for bad in [
        {},
        {"DOCSPEC_CATALOG_TOKEN": "t"},
        {"DOCSPEC_CATALOG_TOKEN": "t", "DOCSPEC_S3_ACCESS_KEY_ID": "a",
         "DOCSPEC_S3_SECRET_ACCESS_KEY": "s", "EXTRA": "x"},
        {"DOCSPEC_CATALOG_TOKEN": "", "DOCSPEC_S3_ACCESS_KEY_ID": "a",
         "DOCSPEC_S3_SECRET_ACCESS_KEY": "s"},
    ]:
        with pytest.raises(setup.SetupFailure):
            setup.engine_credentials(json.dumps(bad))


# -- ct-13cn: Production caller integration, field-group metrics & fallback refusal --------


def _make_catalog_source(name, body=None, **values):
    from congress_api.retention import document_index as index
    row = {
        **dict(
            body_key=body,
            filename=name,
            source_url="https://example.gov/" + name,
            media_type=["application/pdf"],
            http_status=["200"],
            capture_outcome=["saved"],
        ),
        **values,
    }
    for field in index.SOURCE_SCHEMA:
        if field.name not in row:
            row[field.name] = [] if pa.types.is_list(field.type) else None
    return row


def test_ct_13cn_field_group_metrics_backend_capabilities_and_fallback_refusal(tmp_path):
    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        schema = pa.schema([
            pa.field("source_id", pa.string(), nullable=False),
            pa.field("body_key", pa.string(), nullable=True),
        ])
        pin0 = native.run_table(
            pa.Table.from_pylist(
                [{"source_id": "src-unrel", "body_key": "body-unrel"}],
                schema=schema,
            ),
            dataset="catalog_sources",
            operation="op-0",
            definition="v1",
        )
        pin1 = native.update_table(
            pa.Table.from_pylist(
                [
                    {"source_id": "src-1", "body_key": "body-1"},
                    {"source_id": "src-2", "body_key": "body-2"},
                ],
                schema=schema,
            ),
            dataset="catalog_sources",
            operation="op-1",
            definition="v1",
            base=pin0["id"],
            keys=["source_id"],
        )
        pin2 = native.update_table(
            pa.Table.from_pylist(
                [{"source_id": "src-2", "body_key": "body-2-updated"}],
                schema=schema,
            ),
            dataset="catalog_sources",
            operation="op-2",
            definition="v1",
            base=pin1["id"],
            keys=["source_id"],
        )
        loc_map = map_locators_to_occurrences(native, pin2, locator_column="source_id")
        pin3 = attach_occurrence_receipts(
            native,
            dataset="catalog_sources",
            operation="op-3",
            base_pin=pin2,
            definition="v1",
            locator_to_occurrences=loc_map,
            receipts=[("src-2", "review:verified")],
        )

        report = inspect_catalog_changes(
            native, pin1, pin3, key_column="source_id", allow_full_fallback=False
        )
        assert report["path"] == "forward_changes"
        assert report["read_bytes"] > 0
        assert report["returned_bytes"] > 0
        assert report["backend_capability"] == "source_group"
        assert report["remote_supported"] is True
        assert report["unchanged_files_reused"] >= 1

        fgs = report["field_groups"]
        assert set(fgs.keys()) == {"source", "occurrences", "inputs", "evidence"}
        assert fgs["source"]["backend_capability"] == "source_group"
        assert fgs["source"]["remote_supported"] is True
        assert fgs["source"]["read_bytes"] > 0
        assert fgs["source"]["returned_bytes"] > 0

        for local_fg in ("occurrences", "inputs", "evidence"):
            assert fgs[local_fg]["backend_capability"] == "local_only"
            assert fgs[local_fg]["local_supported"] is True
            assert fgs[local_fg]["remote_supported"] is False
            assert fgs[local_fg]["read_bytes"] > 0
            assert fgs[local_fg]["returned_bytes"] > 0

        # Direct per-group inspection on local succeeds for occurrences, inputs, and evidence
        ev_report = inspect_catalog_changes(native, pin1, pin3, group="evidence")
        assert ev_report["backend_capability"] == "local_only"
        assert ev_report["remote_supported"] is False
        assert ev_report["added_rows"] == 1
        assert ev_report["read_bytes"] > 0

        in_report = inspect_catalog_changes(native, pin1, pin3, group="inputs")
        assert in_report["backend_capability"] == "local_only"
        assert in_report["added_rows"] >= 1
        assert in_report["read_bytes"] > 0

        # Unbounded fallback refusal when force_full=True and allow_full_fallback=False / allow_fallback=False
        with pytest.raises(ValueError, match="refused full comparison fallback"):
            inspect_catalog_changes(
                native, pin1, pin2, allow_full_fallback=False, force_full=True
            )
        with pytest.raises(ValueError, match="refused full comparison fallback"):
            inspect_catalog_changes(
                native, pin1, pin2, allow_fallback=False, force_full=True
            )

        # Remote R2 capability guard rejects local-only field groups with 400 remote_unsupported
        native.remote = {"endpoint": "https://r2.example.invalid"}
        try:
            for local_fg in ("occurrences", "inputs", "evidence"):
                with pytest.raises(ValueError, match="400 remote_unsupported"):
                    inspect_catalog_changes(native, pin1, pin3, group=local_fg)
        finally:
            native.remote = None


def test_ct_13cn_production_dependency_callers_consume_certified_changes_at_1x_and_10x_scale(tmp_path):
    """affected_sources and CatalogDependencyStorage.prepare consume /changes without full-table diffs."""
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_dependencies import (
        affected_sources,
        dependency_tables,
    )
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from test_catalog_dependencies import SelectedDependencies

    binary = _binary()
    source_schema = pa.schema([*index.SOURCE_SCHEMA, ("capture_outcome", index.STRINGS)])

    scale_metrics = {}
    for label, unrelated_count in (("1x", 20), ("10x", 200)):
        with NativeDatasets(binary, tmp_path / f"ws-{label}") as native:
            a = _make_catalog_source("a.pdf", "body-A")
            b = _make_catalog_source("b.pdf", "body-B")
            bridge = _make_catalog_source("a.pdf", "body-B")
            unrelated = [
                _make_catalog_source(f"u-{i}.pdf", f"body-U-{i}")
                for i in range(unrelated_count)
            ]
            # Write unrelated corpus in op-0 so its parquet file is separate from the active component
            unrel_table, _ = dependency_tables(unrelated, source_schema, first_order=0)
            pin0 = native.run_table(
                unrel_table,
                dataset=f"dep_sources_{label}",
                operation="op-0",
                definition="v1",
            )
            comp_table_1, _ = dependency_tables(
                [a, b, bridge], source_schema, first_order=unrelated_count
            )
            pin1 = native.update_table(
                comp_table_1,
                dataset=f"dep_sources_{label}",
                operation="op-1",
                definition="v1",
                base=pin0["id"],
                keys=["source_id"],
            )

            # Update a's filename_origins and delete bridge via native update_table
            a_updated = {**a, "filename_origins": ["corrected-label"]}
            rep_table, _ = dependency_tables(
                [a_updated], source_schema, first_order=unrelated_count
            )
            del_table = pa.Table.from_pylist(
                [{"source_id": index.source_identity(bridge)}],
                schema=pa.schema([pa.field("source_id", pa.string(), nullable=False)]),
            )
            pin2 = native.update_table(
                rep_table,
                dataset=f"dep_sources_{label}",
                operation="op-2",
                definition="v1",
                base=pin1["id"],
                keys=["source_id"],
                deletions=del_table,
            )

            initial_rows = [*unrelated, a, b, bridge]
            # 1. Direct affected_sources production caller with before_pin/after_pin
            selected = SelectedDependencies(initial_rows)
            scope = affected_sources(
                selected,
                native=native,
                before_pin=pin1,
                after_pin=pin2,
                key_column="source_id",
                allow_full_fallback=False,
            )
            try:
                assert scope.change_report is not None
                assert scope.change_report["path"] == "forward_changes"
                assert scope.change_report["unchanged_files_reused"] >= 1
                assert set(scope.before) == {
                    index.source_identity(r) for r in (a, b, bridge)
                }
                assert set(scope.after) == {
                    index.source_identity(r) for r in (a_updated, b)
                }
                assert scope.after[index.source_identity(a)]["filename_origins"] == [
                    "corrected-label"
                ]
                # Unrelated rows were never read by the dependency closure!
                assert scope.sources_read == 3
                assert not any(
                    key == index.source_identity(u)
                    for u in unrelated
                    for kind, key in selected.reads
                    if kind == "source"
                )
                scale_metrics[label] = {
                    "read_bytes": scope.change_report["read_bytes"],
                    "returned_bytes": scope.change_report["returned_bytes"],
                    "unchanged_files_reused": scope.change_report["unchanged_files_reused"],
                    "sources_read": scope.sources_read,
                    "aliases_read": scope.aliases_read,
                }
            finally:
                scope.close()

            # 2. Same-pin no-op short-circuits with 0 reads
            noop_selected = SelectedDependencies(initial_rows)
            noop_scope = affected_sources(
                noop_selected,
                native=native,
                before_pin=pin2,
                after_pin=pin2,
                key_column="source_id",
                allow_full_fallback=False,
            )
            try:
                assert noop_scope.change_report["path"] == "unchanged"
                assert noop_scope.change_report["read_bytes"] == 0
                assert noop_scope.change_report["returned_bytes"] == 0
                assert noop_scope.sources_read == 0
                assert noop_scope.aliases_read == 0
                assert noop_selected.reads == []
            finally:
                noop_scope.close()

            # 3. Default CatalogDependencyStorage.prepare and inspect_operator_status production callers
            #    (both without and with explicit before_pin/after_pin)
            if label == "1x":
                from congress_api.retention.native_capacity import inspect_operator_status
                op_status = inspect_operator_status(
                    native,
                    f"dep_sources_{label}",
                    allow_insufficient_capacity=True,
                )
                assert op_status["latest_changes"] is not None
                assert op_status["latest_changes"]["path"] == "forward_changes"
                assert op_status["latest_changes"]["added_rows"] == 1
                assert op_status["latest_changes"]["removed_rows"] == 2

                store = MemoryStore()
                storage = CatalogDependencyStorage(
                    native=native,
                    store=store,
                    namespace="dep-storage-1x",
                    source_schema=source_schema,
                    max_rows=64,
                    max_bytes=1 << 20,
                )
                adopted = storage.prepare(None, replacements=initial_rows)
                assert storage.last_refresh_summary is not None
                assert storage.last_refresh_summary["metrics"]["read_bytes"] > 0

                # Standard production prepare() without before_pin/after_pin kwargs invokes both
                # extract_pin_changes (ct-13cn) and summarize_alias_leaf (ct-gziq) automatically!
                prepared_std = storage.prepare(
                    adopted,
                    replacements=[a_updated],
                    deletions=[index.source_identity(bridge)],
                )
                assert storage.last_change_report is not None
                assert storage.last_change_report["path"] == "forward_changes"
                assert storage.last_change_report["identity"] == "values"
                assert storage.last_refresh_summary is not None

                # Also verify explicit before_pin/after_pin pin-driven prepare()
                prepared = storage.prepare(
                    adopted,
                    before_pin=pin1,
                    after_pin=pin2,
                    key_column="source_id",
                    allow_full_fallback=False,
                )
                assert prepared == prepared_std
                assert storage.last_change_report is not None
                assert storage.last_change_report["path"] == "forward_changes"
                reader = storage.selected(prepared)
                try:
                    assert reader.source(index.source_identity(bridge)) is None
                    assert reader.source(index.source_identity(a))[
                        "filename_origins"
                    ] == ["corrected-label"]
                finally:
                    reader.close()

    # Delta read_bytes, returned_bytes, and closure reads are identical at 1x and 10x unrelated scale!
    assert scale_metrics["1x"]["returned_bytes"] == scale_metrics["10x"]["returned_bytes"]
    assert scale_metrics["1x"]["sources_read"] == scale_metrics["10x"]["sources_read"] == 3
    assert scale_metrics["1x"]["aliases_read"] == scale_metrics["10x"]["aliases_read"]
    assert scale_metrics["1x"]["read_bytes"] == scale_metrics["10x"]["read_bytes"]


# -- ct-gziq: Production consumer integration, joins/aggregates & 1x/10x scale -------------


def test_ct_gziq_production_consumers_and_join_aggregate_edge_cases(tmp_path):
    """Test SourceObservationStorage, CatalogDependencyStorage, and NativeCatalogDependencies refresh consumers."""
    from contextlib import closing
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_dependencies import (
        NativeCatalogDependencies,
        _encoded_alias,
        affected_sources,
        dependency_tables,
    )
    from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.retention.source_observations import (
        SCHEMA as OBS_SCHEMA,
        SourceObservationStorage,
        SourceObservationTrace,
    )

    binary = _binary()
    with NativeDatasets(binary, tmp_path / "ws") as native:
        store = MemoryStore()
        obs_owner = SourceObservationStorage(
            native=native,
            store=store,
            namespace="obs-prod",
            max_rows=4,
            max_bytes=1 << 20,
        )
        with closing(WorkingCatalog(tmp_path / "trace.sqlite")) as work:
            trace = SourceObservationTrace(work)
            trace(dict(receipt_key="page-1", receipt_line=1, kind="event", value="7", access="read"))
            trace(dict(receipt_key="meeting-1", receipt_line=1, kind="event", value="7", access="write"))
            root = obs_owner.prepare(None, trace)

        # Standard SourceObservationStorage.prepare automatically ran refresh_catalog_observation_summary!
        assert obs_owner.last_refresh_summary is not None
        assert obs_owner.last_refresh_summary["metrics"]["native_phase_metrics"]["bytes_written"] > 0

        # Incremental SourceObservationStorage.prepare automatically runs both inspect_catalog_changes
        # and refresh_catalog_observation_summary, including multi-partition (kind == 'members') aliases!
        with closing(WorkingCatalog(tmp_path / "trace-inc.sqlite")) as work:
            trace2 = SourceObservationTrace(work)
            for idx in range(12):
                trace2(dict(receipt_key=f"page-{idx}", receipt_line=1, kind="event", value="7", access="read"))
            root2 = obs_owner.prepare(root, trace2)
        assert obs_owner.last_change_report is not None
        assert obs_owner.last_change_report["path"] == "forward_changes"
        alias_key = 'read:dependency:["event","7"]'
        _, obs_leaf = obs_owner.members.routes.lookup(root2, alias_key)
        assert obs_leaf["kind"] == "members" and obs_leaf["count"] == 12
        summary = obs_owner.summarize_alias(
            root2, alias_key, dataset="obs_leaf_summary", operation="sum-leaf-1"
        )
        assert summary is not None
        assert len(summary["partition_pins"]) > 1
        assert summary["counts"][alias_key] == {
            "total_rows": 12,
            "distinct_observations": 12,
        }
        assert summary["metrics"]["read_bytes"] > 0
        assert summary["metrics"]["written_bytes"] > 0
        assert summary["metrics"]["provider_requests"] == 2 * len(summary["partition_pins"])
        assert summary["metrics"]["spill_bytes"] == 0

        # Multi-partition (kind == 'members') alias in CatalogDependencyStorage.summarize_alias_leaf
        source_schema = pa.schema([*index.SOURCE_SCHEMA, ("capture_outcome", index.STRINGS)])
        dep_owner = CatalogDependencyStorage(
            native=native,
            store=MemoryStore(),
            namespace="multi-part-dep",
            source_schema=source_schema,
            max_rows=4,
            max_bytes=1 << 20,
        )
        shared_rows = [_make_catalog_source(f"doc-{i}.pdf", "shared-body-multi") for i in range(16)]
        dep_sel = dep_owner.prepare(None, replacements=shared_rows)
        shared_alias = ("body", "shared-body-multi")
        _, dep_leaf = dep_owner.aliases.lookup(dep_sel["alias_root"], _encoded_alias(shared_alias))
        assert dep_leaf["kind"] == "members" and dep_leaf["count"] == 16
        dep_sum = dep_owner.summarize_alias_leaf(
            dep_sel, shared_alias, dataset="dep_multi_sum", operation="dms-1"
        )
        assert dep_sum is not None
        assert len(dep_sum["partition_pins"]) > 1
        assert dep_sum["counts"][_encoded_alias(shared_alias)] == {
            "total_rows": 16,
            "distinct_observations": 16,
        }
        assert dep_sum["metrics"]["provider_requests"] == 2 * len(dep_sum["partition_pins"])

        # 2. Append, correction, delete, duplicate keys, and affected old/new groups
        p0 = native.run_table(
            pa.Table.from_pylist(
                [
                    {"alias": "pkg:hr-1", "observation": "receipt:[\"r1\",1]"},
                    {"alias": "pkg:hr-1", "observation": "receipt:[\"r1\",1]"},  # duplicate row
                    {"alias": "pkg:hr-1", "observation": "receipt:[\"r1\",2]"},
                ],
                schema=OBS_SCHEMA,
            ),
            dataset="obs_mutations",
            operation="m-0",
            definition="v1",
        )
        p1 = native.update_table(
            pa.Table.from_pylist(
                [
                    {"alias": "pkg:old-group", "observation": "receipt:[\"r2\",1]"},
                    {"alias": "pkg:delete-me", "observation": "receipt:[\"r3\",1]"},
                ],
                schema=OBS_SCHEMA,
            ),
            dataset="obs_mutations",
            operation="m-1",
            definition="v1",
            base=p0["id"],
            keys=["alias", "observation"],
        )
        s1 = obs_owner.summarize_pin(
            p1, dataset="obs_mutations_sum", operation="ms-1", mode="full"
        )
        assert s1["counts"] == {
            "pkg:hr-1": {"total_rows": 3, "distinct_observations": 2},
            "pkg:old-group": {"total_rows": 1, "distinct_observations": 1},
            "pkg:delete-me": {"total_rows": 1, "distinct_observations": 1},
        }

        # Incremental: append to pkg:hr-1, move r2 from pkg:old-group to pkg:new-group, delete pkg:delete-me
        p2 = native.update_table(
            pa.Table.from_pylist(
                [
                    {"alias": "pkg:hr-1", "observation": "receipt:[\"r1\",3]"},
                    {"alias": "pkg:new-group", "observation": "receipt:[\"r2\",1]"},
                ],
                schema=OBS_SCHEMA,
            ),
            dataset="obs_mutations",
            operation="m-2",
            definition="v1",
            base=p1["id"],
            keys=["alias", "observation"],
            deletions=pa.Table.from_pylist(
                [
                    {"alias": "pkg:old-group", "observation": "receipt:[\"r2\",1]"},
                    {"alias": "pkg:delete-me", "observation": "receipt:[\"r3\",1]"},
                ],
                schema=OBS_SCHEMA,
            ),
        )
        s2 = obs_owner.summarize_pin(
            p2,
            dataset="obs_mutations_sum",
            operation="ms-2",
            base_pin=s1["pin"],
            prior_source_pin=p1,
            mode="incremental",
        )
        assert s2["counts"] == {
            "pkg:hr-1": {"total_rows": 4, "distinct_observations": 3},
            "pkg:new-group": {"total_rows": 1, "distinct_observations": 1},
        }
        assert s2["metrics"]["input_unchanged_files_reused"] >= 1

        # 3. Join cardinality (many_to_one, one_to_one, many_to_many) and null key handling
        source_schema = pa.schema([*index.SOURCE_SCHEMA, ("capture_outcome", index.STRINGS)])
        a = _make_catalog_source("a.pdf", "body-A")
        b = _make_catalog_source("b.pdf", "body-B")
        bridge = _make_catalog_source("a.pdf", "body-B")
        src_table, alias_table = dependency_tables([a, b, bridge], source_schema, first_order=10)
        src_pin = native.run_table(src_table, dataset="cat_src", operation="cs-1", definition="v1")
        alias_pin = native.run_table(alias_table, dataset="cat_alias", operation="ca-1", definition="v1")

        dep_reader = NativeCatalogDependencies(
            native=native,
            source_schema=source_schema,
            locate_source=lambda k: src_pin,
            locate_alias=lambda al: [alias_pin],
        )
        try:
            alias_sum = dep_reader.summarize_alias_pin(
                alias_pin, dataset="cat_alias_sum", operation="cas-1", mode="full"
            )
            assert alias_sum["counts"]['["body","body-B"]'] == {
                "total_rows": 2,
                "distinct_observations": 2,
            }
            joined = dep_reader.join_alias_sources(
                alias_pin,
                src_pin,
                dataset="cat_alias_joined",
                operation="caj-1",
                mode="full",
                cardinality="many_to_one",
            )
            assert len(joined["rows"]) == len(alias_table)
            # Transitive closure remains in affected_sources in catalog_dependencies.py
            closure = affected_sources(
                dep_reader, deletions=[index.source_identity(bridge)]
            )
            try:
                assert set(closure.before) == {
                    index.source_identity(r) for r in (a, b, bridge)
                }
            finally:
                closure.close()
        finally:
            dep_reader.close()

        # Null-key matching ('never' vs 'equal') and many_to_many join cardinality
        left_schema = pa.schema([
            pa.field("join_key", pa.string(), nullable=True),
            pa.field("left_val", pa.string(), nullable=False),
        ])
        right_schema = pa.schema([
            pa.field("join_key", pa.string(), nullable=True),
            pa.field("right_val", pa.string(), nullable=False),
        ])
        left_pin = native.run_table(
            pa.Table.from_pylist(
                [
                    {"join_key": "k1", "left_val": "L1"},
                    {"join_key": "k1", "left_val": "L2"},
                    {"join_key": None, "left_val": "L-null"},
                ],
                schema=left_schema,
            ),
            dataset="join_left",
            operation="jl-1",
            definition="v1",
        )
        right_pin = native.run_table(
            pa.Table.from_pylist(
                [
                    {"join_key": "k1", "right_val": "R1"},
                    {"join_key": "k1", "right_val": "R2"},
                    {"join_key": None, "right_val": "R-null"},
                ],
                schema=right_schema,
            ),
            dataset="join_right",
            operation="jr-1",
            definition="v1",
        )
        join_fields = [
            {"side": "left", "field": "join_key", "name": "join_key"},
            {"side": "left", "field": "left_val", "name": "left_val"},
            {"side": "right", "field": "right_val", "name": "right_val"},
        ]
        j_never = refresh_catalog_join(
            native,
            dataset="join_out_never",
            operation="jon-1",
            left_pin=left_pin,
            right_pin=right_pin,
            keys=["join_key"],
            fields=join_fields,
            nulls="never",
            cardinality="many_to_many",
        )
        rows_never = native.read_arrow(j_never["pin"]).to_pylist()
        assert len(rows_never) == 4  # 2x2 for 'k1'; NULL never matches NULL

        j_equal = refresh_catalog_join(
            native,
            dataset="join_out_equal",
            operation="joe-1",
            left_pin=left_pin,
            right_pin=right_pin,
            keys=["join_key"],
            fields=join_fields,
            nulls="equal",
            cardinality="many_to_many",
        )
        rows_equal = native.read_arrow(j_equal["pin"]).to_pylist()
        assert len(rows_equal) == 5  # 2x2 for 'k1' + 1x1 for NULL == NULL


def test_ct_gziq_refresh_observation_summary_1x_and_10x_unrelated_scale(tmp_path):
    """Measure full and incremental refresh reads/writes, requests, spill, and file reuse at 1x and 10x scale."""
    from congress_api.retention.catalog_dependencies import summarize_alias_observations

    binary = _binary()
    obs_schema = pa.schema([
        pa.field("alias", pa.string(), nullable=False),
        pa.field("observation", pa.string(), nullable=False),
    ])
    scale_results = {}
    for label, unrelated_groups in (("1x", 50), ("10x", 500)):
        with NativeDatasets(binary, tmp_path / f"ws-refresh-{label}") as native:
            unrelated_rows = [
                {"alias": f"pkg:unrel-{i}", "observation": f"receipt:[\"u\",{i}]"}
                for i in range(unrelated_groups)
            ]
            src0 = native.run_table(
                pa.Table.from_pylist(unrelated_rows, schema=obs_schema),
                dataset=f"obs_{label}",
                operation="op-0",
                definition="v1",
            )
            full0 = summarize_alias_observations(
                native,
                src0,
                dataset=f"sum_{label}",
                operation="sum-full-0",
                mode="full",
            )
            # Step 1: add pkg:target in its own incremental partition
            src1 = native.update_table(
                pa.Table.from_pylist(
                    [
                        {"alias": "pkg:target", "observation": "receipt:[\"t\",1]"},
                        {"alias": "pkg:target", "observation": "receipt:[\"t\",2]"},
                    ],
                    schema=obs_schema,
                ),
                dataset=f"obs_{label}",
                operation="op-1",
                definition="v1",
                base=src0["id"],
                keys=["alias", "observation"],
            )
            inc1 = summarize_alias_observations(
                native,
                src1,
                dataset=f"sum_{label}",
                operation="sum-inc-1",
                base_pin=full0["pin"],
                prior_source_pin=src0,
                mode="incremental",
            )
            assert inc1["counts"]["pkg:target"] == {
                "total_rows": 2,
                "distinct_observations": 2,
            }
            assert len(inc1["counts"]) == unrelated_groups + 1

            # Step 2: incremental update touches only pkg:target; the unrelated base file is reused!
            delta = pa.Table.from_pylist(
                [{"alias": "pkg:target", "observation": "receipt:[\"t\",3]"}],
                schema=obs_schema,
            )
            src2 = native.update_table(
                delta,
                dataset=f"obs_{label}",
                operation="op-2",
                definition="v1",
                base=src1["id"],
                keys=["alias", "observation"],
            )
            inc2 = summarize_alias_observations(
                native,
                src2,
                dataset=f"sum_{label}",
                operation="sum-inc-2",
                base_pin=inc1["pin"],
                prior_source_pin=src1,
                mode="incremental",
            )
            assert inc2["counts"]["pkg:target"] == {
                "total_rows": 3,
                "distinct_observations": 3,
            }
            assert len(inc2["counts"]) == unrelated_groups + 1
            assert inc2["metrics"]["unchanged_files_reused"] >= 1
            assert inc2["metrics"]["input_unchanged_files_reused"] >= 1
            assert inc2["metrics"]["provider_requests"] == 2
            assert inc2["metrics"]["spill_bytes"] == 0
            scale_results[label] = {
                "full": full0["metrics"],
                "incremental": inc2["metrics"],
            }

    # Incremental read_bytes and written_bytes are bounded by the 1-row delta and independent of 1x vs 10x unrelated groups!
    assert (
        scale_results["1x"]["incremental"]["read_bytes"]
        == scale_results["10x"]["incremental"]["read_bytes"]
    )
    assert (
        scale_results["1x"]["incremental"]["written_bytes"]
        == scale_results["10x"]["incremental"]["written_bytes"]
    )
    assert (
        scale_results["10x"]["full"]["read_bytes"]
        > scale_results["1x"]["full"]["read_bytes"]
    )
    assert (
        scale_results["10x"]["incremental"]["read_bytes"]
        < scale_results["10x"]["full"]["read_bytes"]
    )
