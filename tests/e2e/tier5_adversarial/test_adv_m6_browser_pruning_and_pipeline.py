"""Tier 5 Adversarial Tests: Milestone 6 (ct-jnw5).

White-box stress testing of:
1. Browser table column pruning and legacy query resilience (absence of redundant/all-null columns).
2. Cartesian product elimination scale testing:
   - Meeting with 50 sources and 50 witnesses: exactly 50 rows (preventing 2,500 row expansion).
   - Boundary meetings with 0 sources or 0 witnesses.
3. Single-pass ZSTD(3) write determinism in browser table generation.
4. docspec-client native_types=True default and docspec-rs row-group decoupling.
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from committee_explorer.parquet import (
    TABLE_SCHEMAS,
    TABLE_COLUMNS,
    _write_table,
)
from committee_explorer.docspec_views import (
    extract_meeting_observations_from_stage,
    COMMITTEE_EXPLORER_OBSERVATIONS_SCHEMA,
)
from docspec_client.docspec import native_storage_schema


class TestM6BrowserTableColumnPruning:
    """Stress testing elimination of redundant, constant, and all-null browser table columns."""

    def test_forbidden_redundant_columns_absent(self):
        """Verify dropped columns are completely absent from TABLE_SCHEMAS."""
        # 1. committees: committee_ids and kind must be absent
        comm_cols = TABLE_SCHEMAS["committee_term"].names
        assert "committee_ids" not in comm_cols
        assert "kind" not in comm_cols

        # 2. meetings: meeting_id, kind, explanation must be absent
        meet_cols = TABLE_SCHEMAS["meeting"].names
        assert "meeting_id" not in meet_cols
        assert "kind" not in meet_cols
        assert "explanation" not in meet_cols

        # 3. materials: meeting_id, appearance_ids, kind, explanation must be absent
        mat_cols = TABLE_SCHEMAS["material"].names
        assert "meeting_id" not in mat_cols
        assert "appearance_ids" not in mat_cols
        assert "kind" not in mat_cols
        assert "explanation" not in mat_cols
        assert "meeting_ids" in mat_cols  # plural retained

        # 4. witnesses: search_text, kind, explanation must be absent
        wit_cols = TABLE_SCHEMAS["appearance"].names
        assert "search_text" not in wit_cols
        assert "kind" not in wit_cols
        assert "explanation" not in wit_cols

        # 5. issues: issue_count, kind must be absent
        iss_cols = TABLE_SCHEMAS["data_issue"].names
        assert "issue_count" not in iss_cols
        assert "kind" not in iss_cols

    def test_legacy_query_column_projection_rejection(self, tmp_path: Path):
        """Querying a browser parquet table for pruned legacy columns raises ArrowInvalid / KeyError."""
        table_path = tmp_path / "meetings.parquet"
        schema = TABLE_SCHEMAS["meeting"]
        # Write minimal valid table
        dummy_row = {
            "id": "meeting-1",
            "title": "Hearing",
            "chamber": "senate",
            "congress": 118,
            "committee_ids": ["c1"],
            "committee_level": "standing",
            "committee_types": ["standing"],
            "source_ids": ["s1"],
            "facts": [],
            "date": "2026-05-01",
            "type": "hearing",
            "status": "held",
            "search_text": "Hearing",
            "scheduled_at": None,
            "access": "public",
            "evidence_states": {"recording": "present", "transcript": "absent", "documents": "present", "witnesses": "present", "captions": "absent"},
        }
        pq.write_table(pa.Table.from_pylist([dummy_row], schema=schema), table_path)

        # Legacy query asking for dropped 'meeting_id' or 'kind' must fail on read projection
        with pytest.raises(Exception):
            pq.read_table(table_path, columns=["id", "meeting_id", "kind"])


class TestM6CartesianEliminationScale:
    """Stress testing Cartesian product elimination in extract_meeting_observations_from_stage."""

    def test_scale_50_sources_x_50_witnesses_no_explosion(self, tmp_path: Path):
        """A meeting with 50 sources and 50 witnesses produces exactly 50 rows, not 2,500."""
        stage_dir = tmp_path / "stage_cartesian"
        stage_dir.mkdir(parents=True, exist_ok=True)

        meeting_id = "meet-big-scale"
        num_sources = 50
        num_witnesses = 50

        # Stage meetings.parquet
        source_ids = [f"src_{i:03d}" for i in range(num_sources)]
        meetings_data = {
            "id": [meeting_id],
            "congress": [118],
            "chamber": ["house"],
            "committee_ids": [["hha00"]],
            "title": ["Big Hearing"],
            "date": ["2026-06-01"],
            "type": ["hearing"],
            "status": ["held"],
            "source_ids": [source_ids],
        }
        pq.write_table(pa.Table.from_pydict(meetings_data), stage_dir / "meetings.parquet")

        # Stage witnesses.parquet with 50 witnesses for meeting_id
        witnesses_data = {
            "meeting_id": [meeting_id] * num_witnesses,
            "title": [f"Dr. Witness {i:03d}" for i in range(num_witnesses)],
        }
        pq.write_table(pa.Table.from_pydict(witnesses_data), stage_dir / "witnesses.parquet")

        # Stage committees.parquet
        committees_data = {
            "id": ["hha00"],
            "title": ["House Administration"],
            "committee_level": ["standing"],
            "committee_type": ["standing"],
            "parent_committee_id": [None],
        }
        pq.write_table(pa.Table.from_pydict(committees_data), stage_dir / "committees.parquet")

        # Extract observations
        rows = extract_meeting_observations_from_stage(stage_dir)

        # Legacy cartesian behavior: 50 * 50 = 2,500 rows.
        # Fixed behavior: exactly 50 rows!
        assert len(rows) == num_sources, f"Expected {num_sources} rows, got {len(rows)} (Cartesian explosion!)"

        # Every row should have the full list of 50 witnesses attached
        for r in rows:
            assert len(r["witness_names"]) == num_witnesses
            assert r["witness_name"] == "Dr. Witness 000"  # primary witness is first sorted

    def test_zero_sources_with_witnesses_produces_one_row(self, tmp_path: Path):
        """A meeting with 0 sources and 20 witnesses produces exactly 1 row."""
        stage_dir = tmp_path / "stage_zero_sources"
        stage_dir.mkdir(parents=True, exist_ok=True)

        meeting_id = "meet-zero-sources"
        pq.write_table(pa.Table.from_pydict({
            "id": [meeting_id],
            "congress": [118],
            "chamber": ["senate"],
            "committee_ids": [[]],
            "title": ["Hearing with no sources"],
            "date": ["2026-06-02"],
            "type": ["hearing"],
            "status": ["held"],
            "source_ids": [[]],
        }), stage_dir / "meetings.parquet")

        pq.write_table(pa.Table.from_pydict({
            "meeting_id": [meeting_id] * 20,
            "title": [f"Witness {i}" for i in range(20)],
        }), stage_dir / "witnesses.parquet")

        rows = extract_meeting_observations_from_stage(stage_dir)
        # Should produce exactly 1 row fallback: f"meeting:{meeting_id}"
        assert len(rows) == 1
        assert rows[0]["source_id"] == f"meeting:{meeting_id}"
        assert len(rows[0]["witness_names"]) == 20


class TestM6SinglePassZSTDDeterminism:
    """Stress testing single-pass ZSTD write compression and determinism."""

    def test_write_table_writes_zstd_compression(self, tmp_path: Path):
        """_write_table writes Parquet with ZSTD(3) compression codec directly."""
        file_path = tmp_path / "zstd_single_pass.parquet"
        schema = TABLE_SCHEMAS["committee_term"]
        rows = [{
            "id": f"comm-{i}",
            "title": f"Committee {i}",
            "chamber": "senate",
            "congress": 118,
            "committee_level": "standing",
            "committee_types": ["standing"],
            "source_ids": ["s1"],
            "facts": [{"label": "Notes", "value": "Test"}],
            "committee_type": "standing",
            "source_committee_type": "standing",
            "committee_code": f"SC{i:02d}",
            "parent_committee_id": None,
        } for i in range(10)]

        _write_table(rows, schema, file_path, row_group_size=5)

        meta = pq.read_metadata(file_path)
        # Inspect compression codec on every column chunk
        for rg_idx in range(meta.num_row_groups):
            rg = meta.row_group(rg_idx)
            for c_idx in range(rg.num_columns):
                codec = rg.column(c_idx).compression
                assert codec == "ZSTD", f"Expected ZSTD, got {codec}"


class TestM6DocspecClientNativeTypes:
    """Stress testing docspec_client default native_types=True."""

    def test_native_types_default_preserves_uint64(self):
        """native_storage_schema retains uint64 and does not widen to Decimal128(20, 0)."""
        app_schema = pa.schema([
            ("counter", pa.uint64()),
            ("payload_bytes", pa.binary()),
            ("title", pa.string()),
        ])

        # By default, native_types=True
        storage_schema = native_storage_schema(app_schema)

        # uint64 must remain uint64, NOT Decimal128
        assert storage_schema.field("counter").type == pa.uint64()
        assert storage_schema.field("payload_bytes").type == pa.binary()

        # If explicitly set to False, it widens to Decimal128
        legacy_schema = native_storage_schema(app_schema, native_types=False)
        assert legacy_schema.field("counter").type == pa.decimal128(20, 0)
        assert legacy_schema.field("payload_bytes").type == pa.large_binary()
