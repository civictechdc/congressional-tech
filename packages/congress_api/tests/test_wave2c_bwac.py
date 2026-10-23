"""Comprehensive Wave 2C (ct-bwac) verification suite."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
import pyarrow as pa
import pytest

from docspec_client import (
    AggregateSpec,
    ConnectedComponentsTransform,
    ConnectedEdgeSpec,
    PartitionFieldSpec,
    PartitionSpec,
    PartitionTransformSpec,
    SortColumn,
    SortDirection,
    UpdateMergeSpec,
    UpdateMergeStrategy,
    apply_update_merge_spec,
)
from congress_api.acquisition.recovery_queue import completed_from_tables, plan_recovery
from congress_api.retention import catalog_scope, catalog_staging, document_index as index
from congress_api.retention.catalog_dependency_storage import (
    ALIAS_PARTITION_SPEC,
    ALIASES_PARTITION_SPEC,
    DEPENDENCY_BUCKET_COUNT,
    DEPENDENCY_SOURCE_MERGE_SPEC,
    SOURCE_PARTITION_SPEC,
    SOURCES_PARTITION_SPEC,
    SOURCE_URL_PARTITION_SPEC,
    SOURCE_URL_SHA256_FIELD,
    CatalogDependencyStorage,
    source_url_sha256,
)
from congress_api.retention.catalog_memberships import (
    ALIAS_KEY_SHA256_FIELD,
    MEMBERSHIP_BUCKET_COUNT,
    MEMBERSHIP_MERGE_SPEC,
    MEMBERSHIP_PARTITION_SPEC,
    MEMBERSHIPS_PARTITION_SPEC,
    CatalogMemberships,
    alias_key_sha256,
    with_alias_key_sha256,
)
from congress_api.retention.document_recovery import recover_sources
from congress_api.retention.native_features import (
    prepare_source_component_table,
    refresh_connected_components,
)
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA, Archive
from congress_api.retention.raw_schemas import (
    LEGACY_CAPTURE_SCHEMA,
    LEGACY_STATE_SCHEMA,
    prepare_state_table,
    with_derived_body_keys,
)
from congress_api.retention.raw_storage import (
    STATE_BUCKET_COUNT,
    STATE_KEY_SHA256_FIELD,
    STATE_MERGE_SPEC,
    STATE_PARTITION_SPEC,
    STATE_PARTITIONED_SCHEMA,
    RawStorage,
    _merge_states,
    state_key_sha256,
)
from corpus_recovery.inventory import scan_receipt_history
from testing_fakes import MemoryStore


class _FakeModernNative:
    """In-memory mock of a Wave 2 docspec server supporting partition_by, merge, and connected_components."""

    def __init__(self):
        self.runs = []
        self.updates = []
        self.refreshes = []
        self.tables = {}
        self._next_id = 1

    def hash_input(self, path):
        from pathlib import Path
        return {"digest": sha256(Path(path).read_bytes()).hexdigest()}

    def run_table(self, table, *, dataset, operation, definition="test", partition_by=None):
        norm_part = PartitionSpec.normalize(partition_by)
        pin_id = f"pin-{self._next_id}"
        self._next_id += 1
        pin = {
            "id": pin_id,
            "verified": True,
            "manifest": {"path": f"manifests/{pin_id}.json", "digest": "0" * 64, "bytes": 128},
            "dataset": {"dataset": dataset, "version": pin_id, "definition": definition, "groups": {"source": {"rows": len(table)}}},
            "partition_by": norm_part,
        }
        self.runs.append({"dataset": dataset, "operation": operation, "partition_by": norm_part, "pin": pin})
        self.tables[pin_id] = table
        return pin

    def update_table(self, table, *, dataset, operation, definition="test", base, keys, merge=None, deletions=None):
        norm_merge = UpdateMergeSpec.normalize(merge)
        base_id = base["id"] if isinstance(base, dict) else base
        existing = self.tables[base_id]
        merged_table = apply_update_merge_spec(
            existing,
            table,
            keys=keys,
            merge=norm_merge,
            deletions=deletions,
        )
        pin_id = f"pin-{self._next_id}"
        self._next_id += 1
        pin = {
            "id": pin_id,
            "verified": True,
            "manifest": {"path": f"manifests/{pin_id}.json", "digest": "0" * 64, "bytes": 128},
            "dataset": {"dataset": dataset, "version": pin_id, "definition": definition, "groups": {"source": {"rows": len(merged_table)}}},
            "merge": norm_merge,
        }
        self.updates.append(
            {
                "dataset": dataset,
                "operation": operation,
                "base": base_id,
                "keys": list(keys),
                "merge": norm_merge,
                "pin": pin,
            }
        )
        self.tables[pin_id] = merged_table
        return pin

    def plan_refresh(self, request):
        transform = request["transform"]
        src_pin_id = transform["input"]["version"]
        src_table = self.tables[src_pin_id]
        return {
            "mode": request.get("mode", "full"),
            "transform": transform,
            "read_bytes": src_table.nbytes,
        }

    def refresh(self, request):
        self.refreshes.append(request)
        transform = request["transform"]
        assert transform["kind"] == "connected_components"
        src_pin_id = transform["input"]["version"]
        src_table = self.tables[src_pin_id]
        rows = src_table.to_pylist()
        uf = index.BipartiteUnionFind()
        for idx, row in enumerate(rows):
            uf.union_row(idx, row)
        out_rows = []
        for members in uf.components():
            comp_rows = [rows[i] for i in members]
            comp_rows.sort(key=lambda r: (r["priority_rank"], r["source_id"]))
            winner = comp_rows[0]
            bodies = sorted({r["connectable_body_key"] for r in comp_rows if r.get("connectable_body_key")})
            sids = sorted({r["source_id"] for r in comp_rows if r.get("source_id")})
            doc_id = index.compute_document_id(bodies, sids)
            out_rows.append(
                {
                    transform["document_id_column"]: doc_id,
                    "primary_source_id": winner["source_id"],
                    "primary_filename": winner.get("filename"),
                    "primary_source_url": winner.get("source_url"),
                    "primary_body_key": winner.get("body_key"),
                    "source_ids": sids,
                    "body_keys": sorted({r["body_key"] for r in comp_rows if r.get("body_key")}),
                    "source_urls": sorted({r["source_url"] for r in comp_rows if r.get("source_url")}),
                    "filenames": sorted({r["filename"] for r in comp_rows if r.get("filename")}),
                    "member_count": len(comp_rows),
                }
            )
        out_table = pa.Table.from_pylist(out_rows)
        pin_id = f"pin-{self._next_id}"
        self._next_id += 1
        pin = {
            "id": pin_id,
            "verified": True,
            "manifest": {"path": f"manifests/{pin_id}.json", "digest": "0" * 64, "bytes": 128},
            "dataset": {"dataset": request["dataset"], "version": pin_id, "definition": request["definition"], "groups": {"source": {"rows": len(out_table)}}},
        }
        self.tables[pin_id] = out_table
        return pin


def test_requirement_1_partition_and_update_merge_and_connected_components_specs():
    # PartitionSpec builders and serde format
    b_spec = PartitionSpec.bucket("state_key_sha256", 64)
    assert dict(b_spec) == {
        "column": "state_key_sha256",
        "transform": {"kind": "bucket", "num_buckets": 64},
    }
    assert PartitionSpec.identity("family") == {
        "column": "family",
        "transform": {"kind": "identity"},
    }
    assert PartitionSpec.truncate("url", 16) == {
        "column": "url",
        "transform": {"kind": "truncate", "width": 16},
    }
    with pytest.raises(ValueError, match="integer in 1..=4096"):
        PartitionTransformSpec.bucket(0)

    # UpdateMergeSpec builders and serde format
    m_spec = UpdateMergeSpec(
        order_by="checked_at",
        columns={
            "body_key": UpdateMergeStrategy.LATEST_OR_BACKFILL,
            "attempts": UpdateMergeStrategy.MAX,
            "links_scanned": UpdateMergeStrategy.SET_UNION,
        },
    )
    assert m_spec.to_dict() == {
        "order_by": "checked_at",
        "columns": {
            "body_key": "latest_or_backfill",
            "attempts": "max",
            "links_scanned": "set_union",
        },
    }
    with pytest.raises(ValueError, match="Invalid UpdateMergeStrategy"):
        UpdateMergeSpec(columns={"body_key": "invalid_strategy"})

    # ConnectedComponentsTransform builder and serde format
    cc = ConnectedComponentsTransform(
        entity_key="source_id",
        edges=[
            ConnectedEdgeSpec("canonical_key", "canonical_key"),
            ConnectedEdgeSpec("connectable_body_key", "connectable_body_key"),
        ],
        component_id_column="document_id",
        order_by=[
            SortColumn("priority_rank", SortDirection.ASC),
            SortColumn("source_id", SortDirection.ASC),
        ],
        outputs=[
            AggregateSpec.first_value("source_id", name="primary_source_id"),
            AggregateSpec.collect_set("source_id", name="source_ids"),
            AggregateSpec.count("source_id", name="member_count"),
        ],
    )
    cc_dict = cc.to_dict()
    assert cc_dict["kind"] == "connected_components"
    assert cc_dict["row_key"] == "source_id"
    assert cc_dict["document_id_column"] == "document_id"
    assert len(cc_dict["edges"]) == 2
    assert cc_dict["order_by"][0] == {"column": "priority_rank", "direction": "asc"}
    assert SortColumn.normalize({"field": "priority_rank", "direction": "asc"}) == {
        "column": "priority_rank",
        "direction": "asc",
    }


def test_requirement_2_sha256_keys_bucket_partitioning_and_merge_states():
    # Long URL (> 128 bytes) produces fixed 64-byte SHA-256 hex digest (< 128 bytes)
    long_url = "https://docs.house.gov/meetings/IF/IF14/20260515/118001/" + ("very-long-segment-" * 20) + "document.pdf"
    assert len(long_url.encode("utf-8")) > 300
    s_hash = state_key_sha256(long_url)
    a_hash = alias_key_sha256(("endpoint", ("document.pdf", long_url)))
    u_hash = source_url_sha256(long_url)
    for digest in (s_hash, a_hash, u_hash):
        assert len(digest) == 64
        assert len(digest.encode("utf-8")) == 64 < 128

    assert STATE_PARTITION_SPEC == {
        "column": STATE_KEY_SHA256_FIELD,
        "transform": {"kind": "bucket", "num_buckets": STATE_BUCKET_COUNT},
    }
    assert MEMBERSHIP_PARTITION_SPEC == {
        "column": ALIAS_KEY_SHA256_FIELD,
        "transform": {"kind": "bucket", "num_buckets": MEMBERSHIP_BUCKET_COUNT},
    }

    # Verify _merge_states preserves retained body_key on later HTTP failure and handles out-of-order timestamps
    initial_saved = {
        "url": long_url,
        "family": "documents",
        "body_key": "bodies/sha256/aa/" + ("a" * 64) + ".gz",
        "sha256": "a" * 64,
        "media_type": "application/pdf",
        "fidelity": "exact-bytes",
        "retrieved_at": "2026-05-01T10:00:00Z",
        "outcome": "saved",
        "checked_at": "2026-05-01T10:00:00Z",
        "next_attempt_at": None,
        "http_status": 200,
        "attempts": 1,
        "links_scanned": True,
    }
    later_failure = {
        "url": long_url,
        "family": "documents",
        "body_key": None,
        "sha256": None,
        "media_type": None,
        "fidelity": None,
        "retrieved_at": None,
        "outcome": "http_error",
        "checked_at": "2026-05-02T10:00:00Z",
        "next_attempt_at": "2026-05-03T10:00:00Z",
        "http_status": 503,
        "attempts": 2,
        "links_scanned": False,
    }
    merged_fwd = _merge_states([initial_saved], [later_failure]).to_pylist()
    merged_rev = _merge_states([later_failure], [initial_saved]).to_pylist()
    assert len(merged_fwd) == 1
    row = merged_fwd[0]
    assert row["state_key_sha256"] == s_hash
    # Newer status/outcome wins, but body_key/sha256/media_type are preserved via LATEST_OR_BACKFILL!
    assert row["outcome"] == "http_error"
    assert row["http_status"] == 503
    assert row["body_key"] == initial_saved["body_key"]
    assert (row["sha256"].hex() if isinstance(row["sha256"], bytes) else row["sha256"]) == initial_saved["sha256"]
    assert row["media_type"] == "application/pdf"
    assert row["attempts"] == 2
    assert row["links_scanned"] is True
    # Out-of-order arrival produces the exact same merged row
    assert merged_rev == merged_fwd

    # Verify CatalogMemberships and CatalogDependencyStorage partitioned table helpers
    native = _FakeModernNative()
    dep_storage = CatalogDependencyStorage(
        native=native,
        store=None,
        namespace="test-cat",
        source_schema=index.SOURCE_SCHEMA,
        max_rows=100,
        max_bytes=1 << 20,
    )
    src_pin_1 = dep_storage.prepare_partitioned_sources(
        [
            {"source_id": "src-1", "source_order": 0, "source_url": long_url, "body_key": initial_saved["body_key"], "document_id": "doc-1"},
        ]
    )
    assert native.runs[-1]["partition_by"] == [dict(SOURCE_PARTITION_SPEC)]
    src_pin_2 = dep_storage.prepare_partitioned_sources(
        [
            {"source_id": "src-1", "source_order": 2, "source_url": long_url, "body_key": initial_saved["body_key"], "document_id": "doc-2"},
            {"source_id": "src-2", "source_order": 1, "source_url": "https://example.gov/b.pdf", "body_key": None, "document_id": "doc-3"},
        ],
        base_pin=src_pin_1,
    )
    updated_rows = native.tables[src_pin_2["id"]].to_pylist()
    assert len(updated_rows) == 2
    assert next(r for r in updated_rows if r["source_id"] == "src-1")["document_id"] == "doc-2"

    alias_pin_1 = dep_storage.prepare_partitioned_aliases(
        [{"alias": json.dumps(["body", initial_saved["body_key"]]), "source_id": "src-1"}]
    )
    assert native.runs[-1]["partition_by"] == [dict(MEMBERSHIP_PARTITION_SPEC)]
    assert ALIAS_KEY_SHA256_FIELD in native.tables[alias_pin_1["id"]].schema.names

    # Verify CatalogMemberships.prepare alias and CatalogDependencyStorage._write_sources / _write_aliases pass partition_by when base is None
    dep_store = MemoryStore()
    dep_storage_routed = CatalogDependencyStorage(
        native=native,
        store=dep_store,
        namespace="test-cat-routed",
        source_schema=index.SOURCE_SCHEMA,
        max_rows=100,
        max_bytes=1 << 20,
    )
    mem_pin = dep_storage_routed.memberships.prepare(
        native,
        [{"alias": json.dumps(["body", initial_saved["body_key"]]), "source_id": "src-1"}],
    )
    assert native.runs[-1]["partition_by"] == [dict(MEMBERSHIPS_PARTITION_SPEC)]
    assert mem_pin["partition_by"] == [dict(MEMBERSHIPS_PARTITION_SPEC)]

    from congress_api.retention.catalog_dependencies import dependency_tables
    src_leaf_tbl, alias_leaf_tbl = dependency_tables(
        [{"body_key": initial_saved["body_key"], "filename": "doc.pdf", "source_url": long_url}],
        index.SOURCE_SCHEMA,
    )
    dep_storage_routed._write_sources(src_leaf_tbl)
    assert native.runs[-1]["partition_by"] == [dict(SOURCES_PARTITION_SPEC)]
    dep_storage_routed._write_aliases(alias_leaf_tbl)
    assert native.runs[-1]["partition_by"] == [dict(ALIASES_PARTITION_SPEC)]

    # Verify production RawStorage.prepare and Archive.apply preserve body_key, MAX(attempts), and SET_UNION(links_scanned)
    from contextlib import contextmanager
    @contextmanager
    def _fake_source_batches(pin, *, schema=None, columns=None):
        tbl = native.tables[pin["id"]]
        if schema is not None:
            cols = [pa.array([r.get(f.name) for r in tbl.to_pylist()], type=f.type) for f in schema]
            tbl = pa.Table.from_arrays(cols, schema=schema)
        yield tbl.to_reader()
    native.source_batches = _fake_source_batches

    def _make_raw_store():
        s = MemoryStore()
        def _put_index_selector(key, data, *, expected_version):
            old = s.read(key)
            version = sha256(old).hexdigest() if old is not None else None
            if version != expected_version:
                raise RuntimeError("Concurrent raw selection")
            return s.put(key, data, immutable=False)
        s.put_index_selector = _put_index_selector
        return s

    empty_captures = pa.Table.from_pylist([], schema=CAPTURE_SCHEMA)
    raw_store = _make_raw_store()
    raw_storage = RawStorage(raw_store, native)
    snap_0 = raw_storage.snapshot()
    prep_1 = raw_storage.prepare(
        snap_0,
        operation="op-1",
        captures=empty_captures,
        states=prepare_state_table([initial_saved]),
    )
    assert native.runs[-1]["partition_by"] == [dict(STATE_PARTITION_SPEC)]
    snap_1 = raw_storage.publish(prep_1)
    prep_2 = raw_storage.prepare(
        snap_1,
        operation="op-2",
        captures=empty_captures,
        states=prepare_state_table([later_failure]),
    )
    snap_2 = raw_storage.publish(prep_2)
    state_rows_2 = with_derived_body_keys(snap_2.states()).to_pylist()
    assert len(state_rows_2) == 1
    assert state_rows_2[0]["outcome"] == "http_error"
    assert state_rows_2[0]["http_status"] == 503
    assert state_rows_2[0]["body_key"] == initial_saved["body_key"]
    assert (state_rows_2[0]["sha256"].hex() if isinstance(state_rows_2[0]["sha256"], bytes) else state_rows_2[0]["sha256"]) == initial_saved["sha256"]
    assert state_rows_2[0]["attempts"] == 2
    assert state_rows_2[0]["links_scanned"] is True

    # Out-of-order state arrival in RawStorage.prepare
    raw_store_rev = _make_raw_store()
    raw_storage_rev = RawStorage(raw_store_rev, native)
    snap_rev_1 = raw_storage_rev.publish(
        raw_storage_rev.prepare(
            raw_storage_rev.snapshot(),
            operation="op-rev-1",
            captures=empty_captures,
            states=prepare_state_table([later_failure]),
        )
    )
    snap_rev_2 = raw_storage_rev.publish(
        raw_storage_rev.prepare(
            snap_rev_1,
            operation="op-rev-2",
            captures=empty_captures,
            states=prepare_state_table([initial_saved]),
        )
    )
    assert with_derived_body_keys(snap_rev_2.states()).to_pylist() == state_rows_2

    # Production Archive.apply preserves body_key, MAX(attempts), and SET_UNION(links_scanned)
    archive = Archive(raw_store, "run-fwd", storage=raw_storage)
    archive.apply({"download_state": initial_saved, "record": {}, "captures": []})
    archive.apply({"download_state": later_failure, "record": {}, "captures": []})
    arch_state = archive.state[long_url]
    assert arch_state["outcome"] == "http_error"
    assert arch_state["http_status"] == 503
    assert arch_state["body_key"] == initial_saved["body_key"]
    assert arch_state["sha256"] == initial_saved["sha256"]
    assert arch_state["attempts"] == 2
    assert arch_state["links_scanned"] is True

    archive_rev = Archive(raw_store_rev, "run-rev", storage=raw_storage_rev)
    archive_rev.apply({"download_state": later_failure, "record": {}, "captures": []})
    archive_rev.apply({"download_state": initial_saved, "record": {}, "captures": []})
    assert archive_rev.state[long_url] == arch_state


def test_requirement_3_unified_union_find_and_connected_components_transform(tmp_path):
    # 1. Shared 404 / HTML / empty bodies must NEVER collapse unrelated URLs into a giant component
    shared_404_body = "bodies/sha256/44/" + ("4" * 64) + ".gz"
    valid_pdf_body = "bodies/sha256/11/" + ("1" * 64) + ".gz"
    row_404_a = {
        "body_key": shared_404_body,
        "filename": "a.pdf",
        "source_url": "https://docs.house.gov/meetings/IF/IF00/20260101/1/a.pdf",
        "http_status": ["404"],
        "media_type": ["text/html"],
        "capture_outcome": ["http_error"],
    }
    row_404_b = {
        "body_key": shared_404_body,
        "filename": "b.pdf",
        "source_url": "https://docs.house.gov/meetings/IF/IF00/20260101/2/b.pdf",
        "http_status": ["404"],
        "media_type": ["text/html"],
        "capture_outcome": ["http_error"],
    }
    assert index.connectable_body_key(row_404_a) is None
    assert index.connectable_body_key(row_404_b) is None

    # Two distinct URLs sharing a valid saved PDF body DO connect
    row_pdf_1 = {
        "body_key": valid_pdf_body,
        "filename": "statement.pdf",
        "source_url": "https://docs.house.gov/meetings/IF/IF00/20260101/1/statement.pdf",
        "http_status": ["200"],
        "media_type": ["application/pdf"],
        "capture_outcome": ["saved"],
        "document_kind": ["witness-statement"],
        "source_witness_name": ["Jane Doe"],
    }
    row_pdf_2 = {
        "body_key": valid_pdf_body,
        "filename": "statement-mirror.pdf",
        "source_url": "https://www.congress.gov/119/meeting/statement.pdf",
        "http_status": ["200"],
        "media_type": ["application/pdf"],
        "capture_outcome": ["saved"],
    }
    assert index.connectable_body_key(row_pdf_1) == valid_pdf_body

    # 2. Verify source_priority_rank strictly preserves source_priority_key order
    candidates = [row_pdf_1, row_pdf_2, row_404_a, row_404_b]
    for r in candidates:
        index.normalize_source_row(r)
    by_tuple_key = sorted(candidates, key=index.source_priority_key, reverse=True)
    by_rank_str = sorted(candidates, key=lambda r: (index.source_priority_rank(r), r["source_id"]))
    assert [r["source_id"] for r in by_rank_str] == [r["source_id"] for r in by_tuple_key]

    # 3. Verify identical grouping across document_index, catalog_staging, catalog_scope, and ConnectedComponentsTransform
    import copy
    rows_mem, _, docs_mem, _ = index.prepare_document_indexes(copy.deepcopy(candidates), index.SOURCE_SCHEMA)
    mem_doc_ids = {r["source_id"]: r["document_id"] for r in rows_mem}
    # 404 rows stay in separate components; valid PDF rows share one component
    assert mem_doc_ids[row_404_a["source_id"]] != mem_doc_ids[row_404_b["source_id"]]
    assert mem_doc_ids[row_pdf_1["source_id"]] == mem_doc_ids[row_pdf_2["source_id"]]

    staged_dest = tmp_path / "document-filenames.parquet"
    index.write_document_indexes(staged_dest, copy.deepcopy(candidates), index.SOURCE_SCHEMA)
    import pyarrow.parquet as pq
    staged_rows = pq.read_table(staged_dest).to_pylist()
    staged_doc_ids = {r["source_id"]: r["document_id"] for r in staged_rows}
    assert staged_doc_ids == mem_doc_ids

    native = _FakeModernNative()
    cc_res = catalog_scope.refresh_scope_connected_components(native, copy.deepcopy(candidates))
    assert isinstance(cc_res["spec"]["transform"]["input"]["manifest"], dict)
    assert cc_res["spec"]["transform"]["input"]["manifest"]["path"].startswith("manifests/pin-")
    cc_rows = native.tables[cc_res["pin"]["id"]].to_pylist()
    cc_doc_ids = {
        sid: comp_row["document_id"]
        for comp_row in cc_rows
        for sid in comp_row["source_ids"]
    }
    assert cc_doc_ids == mem_doc_ids
    pdf_comp = next(c for c in cc_rows if c["document_id"] == mem_doc_ids[row_pdf_1["source_id"]])
    assert pdf_comp["primary_source_id"] == row_pdf_1["source_id"]


def test_requirement_4_table_backed_capture_state_and_recovery_without_jsonl_gz(tmp_path):
    url_pdf = "https://www.govinfo.gov/content/pkg/CHRG-119shrg1/pdf/CHRG-119shrg1.pdf"
    url_zip = "https://www.govinfo.gov/content/pkg/CHRG-119shrg1.zip"
    body_key = "bodies/sha256/22/" + ("2" * 64) + ".gz"

    captures_table = pa.Table.from_pylist(
        [
            {
                "family": "documents",
                "capture_date": "2026-05-10",
                "source_file": "ci/run-1",
                "source_line": None,
                "receipt_key": "receipts/documents/2026-05-10/download-run-1-000001.jsonl.gz",
                "receipt_line": 1,
                "reference_kind": "capture",
                "pointer_json": '["content","body"]',
                "context_url": url_pdf,
                "body_key": body_key,
                "sha256": "2" * 64,
                "bytes": 1024,
                "stored_sha256": "3" * 64,
                "stored_bytes": 512,
                "fidelity": "exact-bytes",
                "media_type": "application/pdf",
                "retrieved_at": "2026-05-10T12:00:00+00:00",
                "http_status": 200,
                "resolution": "saved",
                "original_path": None,
            }
        ],
        schema=LEGACY_CAPTURE_SCHEMA,
    )
    states_table = pa.Table.from_pylist(
        [
            {
                "url": url_pdf,
                "family": "documents",
                "body_key": body_key,
                "sha256": "2" * 64,
                "media_type": "application/pdf",
                "fidelity": "exact-bytes",
                "retrieved_at": "2026-05-10T12:00:00+00:00",
                "outcome": "saved",
                "checked_at": "2026-05-10T12:00:00+00:00",
                "next_attempt_at": None,
                "http_status": 200,
                "attempts": 1,
                "links_scanned": True,
            },
            {
                "url": url_zip,
                "family": "documents",
                "body_key": None,
                "sha256": None,
                "media_type": None,
                "fidelity": None,
                "retrieved_at": "2026-05-10T12:00:00+00:00",
                "outcome": "retry_later",
                "checked_at": "2026-05-10T12:00:00+00:00",
                "next_attempt_at": "2026-05-10T12:05:00+00:00",
                "http_status": 202,
                "attempts": 1,
                "links_scanned": False,
            },
        ],
        schema=LEGACY_STATE_SCHEMA,
    )

    def forbid_receipt_read(key):
        raise AssertionError(f"Unexpected .jsonl.gz receipt scan for {key}")

    # 1. load_raw_capture_state reads directly from tables without touching .jsonl.gz
    loaded = index.load_raw_capture_state(
        captures=captures_table,
        states=states_table,
        read_receipt=forbid_receipt_read,
    )
    assert loaded["source"] == "table"
    assert loaded["outcomes"][url_pdf] == "saved"
    assert loaded["outcomes"][url_zip] == "retry_later"

    # 2. retained_records with states/fetch_outcomes reads directly from tables
    records = list(
        index.retained_records(
            captures_table,
            read_receipt=forbid_receipt_read,
            states=states_table,
        )
    )
    assert len(records) == 1
    rec, rec_rows, rec_ctx = records[0]
    assert rec["url"] == url_pdf
    assert rec["http_status"] == 200
    assert rec["outcome"] == "saved"
    assert len(rec_rows) == 1

    # 3. refresh_response_metadata reads directly from tables without .jsonl.gz files on disk
    target_rows = [{"body_key": body_key, "filename": "CHRG-119shrg1.pdf", "source_url": url_pdf}]
    index.refresh_response_metadata(
        tmp_path,
        target_rows,
        captures=captures_table,
        states=states_table,
    )
    assert target_rows[0]["response_usable"] == ["true"]
    assert target_rows[0]["response_body_complete"] == ["true"]

    # 4. recover_sources recovers body_key and response facts from tables without calling read_receipt
    unlinked = [{"body_key": None, "filename": "CHRG-119shrg1.pdf", "source_url": url_pdf}]
    recovered_mem = recover_sources(
        unlinked,
        captures_table,
        read_receipt=forbid_receipt_read,
        states=states_table,
    )
    assert len(recovered_mem) == 1
    assert recovered_mem[0]["body_key"] == body_key
    assert recovered_mem[0]["http_status"] == ["200"]
    assert recovered_mem[0]["media_type"] == ["application/pdf"]

    work = catalog_staging.WorkingCatalog(tmp_path / "recover-table.sqlite")
    try:
        recovered_disk = list(
            recover_sources(
                [{"body_key": None, "filename": "CHRG-119shrg1.pdf", "source_url": url_pdf}],
                captures_table,
                read_receipt=forbid_receipt_read,
                states=states_table,
                working=work,
            )
        )
        assert recovered_disk == recovered_mem
    finally:
        work.close()

    # 5. scan_receipt_history and plan_recovery read directly from tables without scanning .jsonl.gz
    history = scan_receipt_history(
        captures=captures_table,
        states=states_table,
        read_receipt=forbid_receipt_read,
    )
    assert history[url_pdf]["source"] == "table"
    assert history[url_pdf]["attempts"] == 1
    assert history[url_pdf]["latest_state"]["outcome"] == "saved"

    now = datetime(2026, 5, 10, 12, 10, 0, tzinfo=timezone.utc)
    campaign = [{"url": url_pdf}, {"url": url_zip}]
    plan = plan_recovery(campaign, [states_table], now)
    assert plan["due"] == [url_zip]
    assert plan["finished"] == [url_pdf]
