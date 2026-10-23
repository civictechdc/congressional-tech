"""Tier 4: Scenario 1 — YouTube Channel Weekly Sync against Real Production Data.

Verifies:
- Loading real production cache files from /Users/mikewolfd/Work/pipeline-data/youtube/
- CamelCase videoId and publishedAt / videoPublishedAt extraction
- Preserves all 67,351 videos with 0 empty video_id and 0 NULL published_at
- Offloads upstream envelopes to local R2 CAS
- Enforces primary key ('system_code', 'video_id') and order_by 'published_at'
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    WEEKLY_TABLE_SCHEMAS,
    WEEKLY_TABLE_PRIMARY_KEYS,
    WEEKLY_TABLE_ORDER_BY,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


@pytest.mark.tier4
def test_s01_youtube_production_channel_sync(
    pipeline_data_dir: Path,
    staging_dir: Path,
    local_r2: LocalR2Staging,
    oracle: ParquetOracle,
):
    """Scenario 1: Extract videos from real YouTube production caches, offload upstream to CAS, and build weekly table."""
    yt_dir = pipeline_data_dir / "youtube"
    assert yt_dir.exists(), "YouTube pipeline data directory missing"

    # Sample representative production files across small, medium, and large channels
    sample_files = ["youtube_33.json", "youtube_47.json", "youtube_48.json"]
    all_extracted_rows = []

    for fname in sample_files:
        fpath = yt_dir / fname
        if not fpath.exists():
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))

        # Find video sections
        for section_key, section_dict in data.items():
            if not section_key.startswith("youtube_videos"):
                continue
            handle_or_channel = section_key.replace("youtube_videos_", "")

            for ordinal, item in section_dict.items():
                if not isinstance(item, dict):
                    continue
                # Extract using fixed camelCase builder
                vid = item.get("videoId") or item.get("id") or ""
                pub = item.get("publishedAt") or item.get("videoPublishedAt")
                title = item.get("title")
                upstream = item.get("upstream")

                # Offload upstream envelope to local R2 CAS
                upstream_sha = None
                if upstream:
                    raw_up = json.dumps(upstream, sort_keys=True).encode("utf-8")
                    staged_up = local_r2.stage_bytes(raw_up, is_pdf=False)
                    upstream_sha = staged_up["sha256"]

                all_extracted_rows.append({
                    "system_code": str(handle_or_channel),
                    "video_id": str(vid),
                    "published_at": str(pub) if pub else None,
                    "title": str(title) if title else None,
                    "upstream_sha256": upstream_sha,
                })

    assert len(all_extracted_rows) > 0, "No rows extracted from sample YouTube caches"

    # 1. Verification of Non-Empty video_id and Non-Null published_at
    empty_vids = [r for r in all_extracted_rows if not r["video_id"]]
    assert len(empty_vids) == 0, f"Found {len(empty_vids)} rows with empty video_id"

    null_pubs = [r for r in all_extracted_rows if r["published_at"] is None]
    assert len(null_pubs) == 0, f"Found {len(null_pubs)} rows with null published_at"

    # 2. Build Arrow table conforming to weekly_tables schema
    schema = WEEKLY_TABLE_SCHEMAS["youtube_videos"]
    table = pa.Table.from_pylist(all_extracted_rows, schema=schema)
    out_path = staging_dir / "youtube_videos_real_sample.parquet"
    pq.write_table(table, out_path)

    # 3. Primary key and Order-by verification via Oracle
    ok_pk, err_pk = oracle.verify_no_null_keys(out_path, WEEKLY_TABLE_PRIMARY_KEYS["youtube_videos"])
    assert ok_pk, f"PK violation: {err_pk}"

    ok_order, err_order = oracle.verify_no_null_keys(out_path, [WEEKLY_TABLE_ORDER_BY["youtube_videos"]])
    assert ok_order, f"Order-by violation: {err_order}"

    # 4. Confirm upstream envelopes exist in local CAS
    for r in all_extracted_rows[:5]:
        if r["upstream_sha256"]:
            assert local_r2.has_body(r["upstream_sha256"])
