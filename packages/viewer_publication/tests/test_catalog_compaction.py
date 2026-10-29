"""Readings and review compaction remain available to their kept CLI consumers."""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from viewer_publication import compact_readings,compact_review_rows


def test_compact_readings_shards(tmp_path: Path):
    readings_dir = tmp_path / "shards"
    readings_dir.mkdir()

    # Create 5 small reading shards with some duplicate keys
    for shard_idx in range(5):
        rows = [
            {
                "body_key": f"bodies/sha256/ab/{i:04d}.gz",
                "parser_fingerprint": "v1_parser",
                "status": "completed",
                "raw_leaf": f"leaf_{i}_{shard_idx}",
            }
            for i in range(20)
        ]
        shard_path = readings_dir / f"shard_{shard_idx:03d}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), shard_path)

    out_dir = tmp_path / "compacted_readings"
    result = compact_readings(readings_dir, out_dir, max_files=2, row_group_size=16384)

    assert result["num_files"] in (1, 2)
    assert result["total_rows"] == 20  # Deduplicated across shards
    for f in result["files"]:
        meta = pq.read_metadata(f)
        assert meta.num_row_groups == 1


def test_compact_readings_empty_shards(tmp_path: Path):
    readings_dir = tmp_path / "empty_shards"
    readings_dir.mkdir()

    schema = pa.schema([
        ("retained_page_id", pa.string()),
        ("reading_id", pa.string()),
        ("raw_leaf", pa.string()),
    ])
    for i in range(3):
        pq.write_table(pa.Table.from_pylist([], schema=schema), readings_dir / f"empty_{i}.parquet")

    out_file = tmp_path / "compacted_empty.parquet"
    result = compact_readings(readings_dir, out_file)
    assert result["total_rows"] == 0
    assert Path(result["files"][0]).is_file()


def test_compact_review_rows(tmp_path: Path):
    in_file = tmp_path / "raw_review.parquet"
    out_file = tmp_path / "compacted_review.parquet"

    rows = [
        {
            "id": f"rev_{i}",
            "url": f"https://example.com/{i}",
            "canonical_url": f"https://example.com/{i}",  # 100% == url (dropped)
            "record_json": '{"dummy": "boilerplate"}',     # Dropped
            "sha256": "0" * 64,
            "congress": 118,
            "chamber": "House",
            "title": f"Review {i}",
            "format": "pdf",
            "http_status": 200,
            "all_null_field": None,                       # Dropped
        }
        for i in range(50)
    ]
    pq.write_table(pa.Table.from_pylist(rows), in_file)

    compacted = compact_review_rows(in_file, out_file, row_group_size=16384)
    assert "record_json" not in compacted.schema.names
    assert "canonical_url" not in compacted.schema.names
    assert "all_null_field" not in compacted.schema.names
    assert "url" in compacted.schema.names
    assert "sha256" in compacted.schema.names
    assert "title" in compacted.schema.names
    assert len(compacted) == 50

    meta = pq.read_metadata(out_file)
    assert meta.num_row_groups == 1
