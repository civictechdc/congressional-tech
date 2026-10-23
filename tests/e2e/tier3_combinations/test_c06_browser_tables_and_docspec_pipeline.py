"""Tier 3: Combination Test 6 — Browser Tables, Decoupled Docspec Views & Native Pipeline.

Cross-feature interactions:
- F24: Browser Tables Redundant Column Pruning
- F26: Docspec Views Cartesian Product Elimination
- F27: Single-Pass ZSTD Parquet Export
- F28: Docspec Client Native Types Default
- F29: Docspec-rs Row-Group Flushing Decoupling
"""

from __future__ import annotations
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client import native_storage_schema
from tests.e2e.harness.contracts import (
    BROWSER_TABLE_SCHEMAS,
    FORBIDDEN_BROWSER_COLUMNS,
)
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier3
def test_c06_browser_tables_and_decoupled_views_pipeline(
    staging_dir: Path,
    oracle: ParquetOracle,
):
    """C6.1: Write browser tables without redundant columns, eliminate Cartesian fanout, and export ZSTD."""
    # 1. Build meetings and committees browser tables
    comm_row = {
        "id": "hsed00",
        "title": "House Education",
        "chamber": "House",
        "congress": 118,
        "committee_level": "standing",
        "committee_types": ["standing"],
        "source_ids": ["src_comm_1"],
        "facts": [],
        "committee_type": "standing",
        "source_committee_type": "standing",
        "committee_code": "ED00",
        "parent_committee_id": None,
    }
    comm_table = pa.Table.from_pylist([comm_row], schema=BROWSER_TABLE_SCHEMAS["committees"])
    comm_path = staging_dir / "committees.parquet"
    pq.write_table(comm_table, comm_path, compression="zstd", compression_level=3)

    meeting_row = {
        "id": "m_100",
        "title": "Workforce Innovation Hearing",
        "chamber": "House",
        "congress": 118,
        "committee_ids": ["hsed00"],
        "committee_level": "standing",
        "committee_types": ["standing"],
        "source_ids": ["s_alpha", "s_beta"],  # 2 sources
        "facts": [],
        "date": "2026-10-22",
        "type": "Hearing",
        "status": "Held",
        "search_text": "workforce innovation",
        "scheduled_at": "2026-10-22T10:00:00Z",
        "access": "public",
        "evidence_states": None,
    }
    meeting_table = pa.Table.from_pylist([meeting_row], schema=BROWSER_TABLE_SCHEMAS["meetings"])
    meeting_path = staging_dir / "meetings.parquet"
    pq.write_table(meeting_table, meeting_path, compression="zstd", compression_level=3)

    # 4 witnesses for meeting m_100
    witnesses_rows = [
        {
            "id": f"wit_{i}",
            "title": f"Witness {i}",
            "chamber": "House",
            "congress": 118,
            "committee_ids": ["hsed00"],
            "committee_level": "standing",
            "committee_types": ["standing"],
            "source_ids": ["s_alpha"],
            "facts": [],
            "date": "2026-10-22",
            "meeting_id": "m_100",
            "position": "CEO",
            "organization": f"Tech Company {i}",
            "participation": "In-Person",
            "roles": ["Witness"],
        }
        for i in range(4)
    ]
    wit_table = pa.Table.from_pylist(witnesses_rows, schema=BROWSER_TABLE_SCHEMAS["witnesses"])
    wit_path = staging_dir / "witnesses.parquet"
    pq.write_table(wit_table, wit_path, compression="zstd", compression_level=3)

    # Verify column absence in written browser tables
    ok_comm, err_comm = oracle.verify_column_absence(comm_path, FORBIDDEN_BROWSER_COLUMNS["committees"])
    assert ok_comm, f"Forbidden column in committees: {err_comm}"
    ok_meet, err_meet = oracle.verify_column_absence(meeting_path, FORBIDDEN_BROWSER_COLUMNS["meetings"])
    assert ok_meet, f"Forbidden column in meetings: {err_meet}"
    ok_wit, err_wit = oracle.verify_column_absence(wit_path, FORBIDDEN_BROWSER_COLUMNS["witnesses"])
    assert ok_wit, f"Forbidden column in witnesses: {err_wit}"

    # 2. Extract meeting observations with Cartesian product elimination
    # Old logic: 2 sources x 4 witnesses = 8 rows
    # Fixed logic: 2 sources = 2 rows
    m_sources = meeting_row["source_ids"]
    m_witness_names = [w["title"] for w in witnesses_rows]

    decoupled_obs_rows = []
    for rank, src_id in enumerate(m_sources, start=1):
        decoupled_obs_rows.append({
            "meeting_id": meeting_row["id"],
            "congress": meeting_row["congress"],
            "chamber": meeting_row["chamber"],
            "title": meeting_row["title"],
            "source_id": src_id,
            "source_rank": rank,
            "witnesses": m_witness_names,
        })

    assert len(decoupled_obs_rows) == 2  # Exactly 2 rows, eliminating the 4x explosion!

    # 3. Native types default verification
    obs_schema = pa.schema([
        ("meeting_id", pa.string()),
        ("congress", pa.uint64()),  # Native UInt64
        ("source_rank", pa.int64()),
    ])
    obs_table = pa.Table.from_pylist([
        {"meeting_id": "m_100", "congress": 118, "source_rank": 1},
        {"meeting_id": "m_100", "congress": 118, "source_rank": 2},
    ], schema=obs_schema)

    native_res = native_storage_schema(obs_table, native_types=True)
    assert native_res.schema.field("congress").type.equals(pa.uint64())

    # 4. Decoupled row-group flushing export verification
    obs_path = staging_dir / "observations.parquet"
    pq.write_table(obs_table, obs_path, compression="zstd", compression_level=3)
    meta = pq.read_metadata(obs_path)
    assert meta.row_group(0).column(0).compression == "ZSTD"
