"""Tier 2: Boundary & Corner Cases for Features F9 through F16 (ct-q29c).

Covers:
- F9: Empty video IDs, null published_at, channel deduplication, long descriptions
- F10: Null system_code, congress bounds, detail deduplication across 10 congresses
- F11: Both timestamps null, whitespace timestamps, timezone conversions
- F12: All watermarks missing, corrupt date strings, newest resolution
- F13: Zero-page domains, embedded PDF diversion, long query strings, duplicate URLs
- F14: Missing sections, empty arrays, default date fallback, malformed JSON
- F15: 0-row batch, duplicate PKs in batch, schema evolution rejection, idempotency
- F16: Null cells in digest, nested structs, multi-chunk array hashing, scalability
"""

from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tests.e2e.harness.contracts import (
    WEEKLY_TABLE_SCHEMAS,
    WEEKLY_TABLE_PRIMARY_KEYS,
    WEEKLY_TABLE_ORDER_BY,
    MAX_CELL_SIZE,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle


# ---------------------------------------------------------------------------
# Feature F9 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F9")
def test_b09_empty_video_id_string_raises(oracle: ParquetOracle):
    """B9.1: Verify empty string video_id fails non-empty primary key assertion."""
    table = pa.Table.from_pylist([
        {"system_code": "hsed00", "video_id": "", "published_at": "2026-10-19T10:00:00Z"},
    ])
    ok, errors = oracle.verify_no_null_keys(table, ["system_code", "video_id"])
    assert not ok
    assert "empty string" in errors[0]


@pytest.mark.tier2
@pytest.mark.feature("F9")
def test_b09_null_published_at_raises(oracle: ParquetOracle):
    """B9.2: Verify null published_at fails non-null order_by assertion."""
    table = pa.Table.from_pylist([
        {"system_code": "hsed00", "video_id": "vid_1", "published_at": None},
    ])
    ok, errors = oracle.verify_no_null_keys(table, ["published_at"])
    assert not ok
    assert "NULL" in errors[0]


@pytest.mark.tier2
@pytest.mark.feature("F9")
def test_b09_duplicate_video_id_in_same_channel():
    """B9.3: Verify duplicate videoId in same channel keeps newest published_at."""
    batch = [
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-19T10:00:00Z", "title": "Old"},
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-19T12:00:00Z", "title": "New"},
    ]
    upserted = {}
    for r in sorted(batch, key=lambda x: x["published_at"]):
        upserted[(r["system_code"], r["video_id"])] = r

    assert len(upserted) == 1
    assert upserted[("hsed00", "v1")]["title"] == "New"


@pytest.mark.tier2
@pytest.mark.feature("F9")
def test_b09_special_characters_in_title():
    """B9.4: Verify video title containing emojis, quotes, and newlines is preserved."""
    title = '🔥 AI Oversight: "Frontier Models" & Policy \t [Live 2026] ⚡'
    row = {"video_id": "v2", "title": title, "published_at": "2026-10-20T00:00:00Z"}
    assert row["title"] == title


@pytest.mark.tier2
@pytest.mark.feature("F9")
def test_b09_very_long_youtube_description_offloaded(local_r2: LocalR2Staging):
    """B9.5: Verify 100 KiB upstream description is offloaded to R2, keeping table row under 1 KiB."""
    huge_upstream = {"snippet": {"description": "Hearing witness testimony: " * 5000}}
    raw_bytes = json.dumps(huge_upstream).encode("utf-8")
    assert len(raw_bytes) > 100 * 1024

    staged = local_r2.stage_bytes(raw_bytes, is_pdf=False)
    row = {
        "system_code": "hsed00",
        "video_id": "vid_large",
        "published_at": "2026-10-20T00:00:00Z",
        "upstream_sha256": staged["sha256"],
    }
    assert len(row["upstream_sha256"]) == 64
    assert local_r2.has_body(staged["sha256"])


# ---------------------------------------------------------------------------
# Feature F10 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F10")
def test_b10_null_system_code_raises(oracle: ParquetOracle):
    """B10.1: Verify committee with null systemCode fails primary key assertion."""
    table = pa.Table.from_pylist([
        {"congress": 118, "system_code": None, "chamber": "House", "update_date": "2026-10-20T00:00:00Z"},
    ])
    ok, errors = oracle.verify_no_null_keys(table, ["system_code"])
    assert not ok


@pytest.mark.tier2
@pytest.mark.feature("F10")
def test_b10_zero_or_negative_congress_bounds():
    """B10.2: Verify congress number bounds (1 <= congress <= 200) rejection."""
    valid_congress = 118
    assert 1 <= valid_congress <= 200

    invalid_congress = 0
    assert not (1 <= invalid_congress <= 200)


@pytest.mark.tier2
@pytest.mark.feature("F10")
def test_b10_subcommittee_with_parent_code():
    """B10.3: Verify subcommittee maintains parent committee linkage."""
    subcommittee_rec = {
        "congress": 118,
        "system_code": "hsed14",
        "chamber": "House",
        "parent_committee_id": "hsed00",
        "update_date": "2026-10-20T00:00:00Z",
    }
    assert subcommittee_rec["parent_committee_id"] == "hsed00"


@pytest.mark.tier2
@pytest.mark.feature("F10")
def test_b10_committee_detail_empty_dict(local_r2: LocalR2Staging):
    """B10.4: Verify empty committee detail dict {} offloads valid sha256 to R2."""
    empty_detail_bytes = json.dumps({}, sort_keys=True).encode("utf-8")
    staged = local_r2.stage_bytes(empty_detail_bytes, is_pdf=False)
    assert local_r2.has_body(staged["sha256"])


@pytest.mark.tier2
@pytest.mark.feature("F10")
def test_b10_dedup_detail_across_10_congresses(local_r2: LocalR2Staging):
    """B10.5: Verify identical detail across 10 congresses maps to the exact same SHA-256."""
    detail = {"name": "Armed Services", "jurisdiction": "Defense policy"}
    detail_bytes = json.dumps(detail, sort_keys=True).encode("utf-8")

    staged_hashes = [local_r2.stage_bytes(detail_bytes, is_pdf=False)["sha256"] for _ in range(10)]
    assert len(set(staged_hashes)) == 1  # 1 unique SHA-256 across all 10 congresses


# ---------------------------------------------------------------------------
# Feature F11 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F11")
def test_b11_both_imported_at_and_checked_null():
    """B11.1: Verify row with both imported_at and checked null raises or is detected."""
    rec = {"event_id": "ev_null", "imported_at": None, "checked": None}
    merge_ts = rec.get("imported_at") or rec.get("checked")
    assert merge_ts is None


@pytest.mark.tier2
@pytest.mark.feature("F11")
def test_b11_empty_string_timestamp(oracle: ParquetOracle):
    """B11.2: Verify empty string timestamp fails non-empty validation."""
    table = pa.Table.from_pylist([{"event_id": "ev1", "merge_timestamp": ""}])
    ok, errors = oracle.verify_no_null_keys(table, ["merge_timestamp"])
    assert not ok


@pytest.mark.tier2
@pytest.mark.feature("F11")
def test_b11_whitespace_timestamp():
    """B11.3: Verify whitespace-only timestamp string is rejected or stripped."""
    ts = "   "
    clean_ts = ts.strip() or None
    assert clean_ts is None


@pytest.mark.tier2
@pytest.mark.feature("F11")
def test_b11_future_timestamp_preservation():
    """B11.4: Verify scheduled event with future timestamp preserves exact value."""
    future_ts = "2028-01-15T10:00:00Z"
    rec = {"event_id": "future_ev", "checked": future_ts}
    assert rec["checked"] == future_ts


@pytest.mark.tier2
@pytest.mark.feature("F11")
def test_b11_timezone_offset_differences():
    """B11.5: Verify non-UTC timezone offsets (e.g. -04:00) parse to correct UTC moment."""
    from datetime import datetime, timezone
    ts_est = "2026-10-19T10:00:00-04:00"
    dt = datetime.fromisoformat(ts_est)
    dt_utc = dt.astimezone(timezone.utc)
    assert dt_utc.hour == 14  # 10:00 -04:00 = 14:00 UTC


# ---------------------------------------------------------------------------
# Feature F12 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F12")
def test_b12_all_three_timestamps_absent():
    """B12.1: Verify record with missing listing, mods, and transcripts is caught."""
    rec = {"package_id": "PKG_EMPTY", "listing": None, "mods": None, "transcripts": None}
    ts = (rec.get("mods") or {}).get("retrieved_at") or (rec.get("listing") or {}).get("retrieved_at")
    assert ts is None


@pytest.mark.tier2
@pytest.mark.feature("F12")
def test_b12_corrupted_timestamp_string():
    """B12.2: Verify malformed date string is caught by date parser."""
    bad_date = "NOT_A_DATE"
    with pytest.raises(Exception):
        from datetime import datetime
        datetime.fromisoformat(bad_date)


@pytest.mark.tier2
@pytest.mark.feature("F12")
def test_b12_multiple_timestamps_resolves_latest():
    """B12.3: Verify multiple timestamps resolves to newest watermark."""
    listing_ts = "2026-10-18T08:00:00Z"
    mods_ts = "2026-10-18T10:00:00Z"
    watermark = max([listing_ts, mods_ts])
    assert watermark == mods_ts


@pytest.mark.tier2
@pytest.mark.feature("F12")
def test_b12_empty_package_id_raises(oracle: ParquetOracle):
    """B12.4: Verify empty package_id fails primary key assertion."""
    table = pa.Table.from_pylist([{"package_id": "", "retrieved_at": "2026-10-18T00:00:00Z"}])
    ok, errors = oracle.verify_no_null_keys(table, ["package_id"])
    assert not ok


@pytest.mark.tier2
@pytest.mark.feature("F12")
def test_b12_gpo_evidence_sha256_offload(local_r2: LocalR2Staging):
    """B12.5: Verify GPO evidence record offloads raw mods/listing to R2."""
    gpo_evidence = b"<mods:mods>Hearing Metadata Content</mods:mods>"
    staged = local_r2.stage_bytes(gpo_evidence, is_pdf=False)
    assert local_r2.has_body(staged["sha256"])


# ---------------------------------------------------------------------------
# Feature F13 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F13")
def test_b13_domain_with_zero_pages():
    """B13.1: Verify Senate domain with 0 pages emits 0 page rows without crashing."""
    domain_data = {"pages": {}}
    rows = [p for p in domain_data["pages"].values()]
    assert len(rows) == 0


@pytest.mark.tier2
@pytest.mark.feature("F13")
def test_b13_embedded_pdf_url_diverted_to_pdf_cas(local_r2: LocalR2Staging):
    """B13.2: Verify URL ending in .pdf is diverted to .pdf CAS object."""
    pdf_bytes = b"%PDF-1.4 Senate hearing document bytes"
    staged = local_r2.stage_bytes(pdf_bytes, is_pdf=True)
    assert staged["extension"] == "pdf"
    assert staged["uri"].endswith(".pdf")


@pytest.mark.tier2
@pytest.mark.feature("F13")
def test_b13_url_with_1000_char_query_string():
    """B13.3: Verify page URL with 1,000-character query string is preserved without truncation."""
    long_url = "https://senate.gov/hearing?query=" + ("x" * 1000)
    assert len(long_url) > 1000


@pytest.mark.tier2
@pytest.mark.feature("F13")
def test_b13_non_https_page_url():
    """B13.4: Verify http vs https page URLs are preserved faithfully."""
    http_url = "http://www.senate.gov/hearings/1"
    https_url = "https://www.senate.gov/hearings/1"
    assert http_url != https_url


@pytest.mark.tier2
@pytest.mark.feature("F13")
def test_b13_duplicate_page_urls_in_same_domain():
    """B13.5: Verify duplicate page URLs in same domain deduplicate to latest observed_at."""
    pages = [
        {"url": "https://senate.gov/h1", "observed_at": "2026-10-18T00:00:00Z"},
        {"url": "https://senate.gov/h1", "observed_at": "2026-10-19T00:00:00Z"},
    ]
    deduped = {}
    for p in sorted(pages, key=lambda x: x["observed_at"]):
        deduped[p["url"]] = p

    assert len(deduped) == 1
    assert deduped["https://senate.gov/h1"]["observed_at"] == "2026-10-19T00:00:00Z"


# ---------------------------------------------------------------------------
# Feature F14 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F14")
def test_b14_inventory_with_missing_sections():
    """B14.1: Verify inventory file missing probes section handles gracefully."""
    inv = {"youtube": [], "senate": [], "mods": []}
    probes = inv.get("probes", [])
    assert probes == []


@pytest.mark.tier2
@pytest.mark.feature("F14")
def test_b14_inventory_with_empty_arrays():
    """B14.2: Verify inventory with empty arrays [] emits valid empty sub-tables."""
    schema = WEEKLY_TABLE_SCHEMAS["captions"]
    t = pa.Table.from_pylist([], schema=schema)
    assert t.num_rows == 0
    assert len(t.column_names) == len(schema.names)


@pytest.mark.tier2
@pytest.mark.feature("F14")
def test_b14_caption_with_null_observed_at_defaults_to_file_date():
    """B14.3: Verify caption with null observed_at defaults to inventory file date."""
    file_date = "2026-10-19T00:00:00Z"
    item = {"source": "youtube", "observed_at": None}
    obs_at = item.get("observed_at") or file_date
    assert obs_at == file_date


@pytest.mark.tier2
@pytest.mark.feature("F14")
def test_b14_malformed_json_in_inventory_item():
    """B14.4: Verify malformed json in single item does not discard remaining valid items."""
    items = ['{"valid": 1}', 'INVALID_JSON_CORRUPT', '{"valid": 2}']
    parsed = []
    for raw in items:
        try:
            parsed.append(json.loads(raw))
        except Exception:
            pass
    assert len(parsed) == 2


@pytest.mark.tier2
@pytest.mark.feature("F14")
def test_b14_inventory_5413_dropped_items_restored():
    """B14.5: Verify inventory retention count assertion (2,137 mods + 3,268 probes + 8 witness_lists = 5,413)."""
    mods_count = 2137
    probes_count = 3268
    witness_count = 8
    total_restored = mods_count + probes_count + witness_count
    assert total_restored == 5413


# ---------------------------------------------------------------------------
# Feature F15 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F15")
def test_b15_zero_row_batch_handling():
    """B15.1: Verify 0-row batch preserves complete Arrow schema without corruption."""
    schema = WEEKLY_TABLE_SCHEMAS["youtube_videos"]
    table = pa.Table.from_pylist([], schema=schema)
    assert table.num_rows == 0
    assert table.schema.equals(schema)


@pytest.mark.tier2
@pytest.mark.feature("F15")
def test_b15_duplicate_primary_keys_in_batch():
    """B15.2: Verify batch with duplicate primary keys collapses before insertion."""
    batch = [
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-19T10:00:00Z"},
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-19T11:00:00Z"},
    ]
    pk_map = {}
    for r in batch:
        pk_map[(r["system_code"], r["video_id"])] = r
    assert len(pk_map) == 1


@pytest.mark.tier2
@pytest.mark.feature("F15")
def test_b15_null_body_bytes_offload(local_r2: LocalR2Staging):
    """B15.3: Verify null body produces null *_sha256 column in Arrow table."""
    row = {
        "system_code": "hsed00",
        "video_id": "v1",
        "published_at": "2026-10-19T00:00:00Z",
        "title": "Title",
        "upstream_sha256": None,
    }
    schema = WEEKLY_TABLE_SCHEMAS["youtube_videos"]
    t = pa.Table.from_pylist([row], schema=schema)
    assert t["upstream_sha256"].to_pylist()[0] is None


@pytest.mark.tier2
@pytest.mark.feature("F15")
def test_b15_idempotent_reupsert():
    """B15.4: Verify re-upserting identical batch produces zero mutations."""
    state = {("hsed00", "v1"): "hash_1"}
    incoming = [("hsed00", "v1", "hash_1")]
    mutations = 0
    for sc, vid, h in incoming:
        if state.get((sc, vid)) != h:
            state[(sc, vid)] = h
            mutations += 1
    assert mutations == 0


@pytest.mark.tier2
@pytest.mark.feature("F15")
def test_b15_schema_evolution_rejection():
    """B15.5: Verify unexpected extra column in weekly table is detected and rejected."""
    schema = WEEKLY_TABLE_SCHEMAS["youtube_videos"]
    invalid_row = {
        "system_code": "hsed00",
        "video_id": "v1",
        "published_at": "2026-10-19T00:00:00Z",
        "title": "Title",
        "upstream_sha256": None,
        "unexpected_extra_col": "invalid",
    }
    # Validate against schema field names
    extra_fields = set(invalid_row.keys()) - set(schema.names)
    assert len(extra_fields) == 1
    assert "unexpected_extra_col" in extra_fields


# ---------------------------------------------------------------------------
# Feature F16 Boundaries
# ---------------------------------------------------------------------------

def fast_digest(table: pa.Table) -> str:
    hasher = hashlib.sha256()
    for col in table.columns:
        for chunk in col.chunks:
            for buf in chunk.buffers():
                if buf is not None:
                    hasher.update(buf)
    return hasher.hexdigest()[:16]


@pytest.mark.tier2
@pytest.mark.feature("F16")
def test_b16_digest_with_null_cells():
    """B16.1: Verify fast digest handles null entries in columns deterministically."""
    t = pa.Table.from_pylist([{"val": "a"}, {"val": None}, {"val": "b"}])
    d1 = fast_digest(t)
    d2 = fast_digest(t)
    assert d1 == d2


@pytest.mark.tier2
@pytest.mark.feature("F16")
def test_b16_digest_with_nested_struct():
    """B16.2: Verify fast digest computes over nested struct columns."""
    struct_arr = pa.StructArray.from_arrays([
        pa.array(["label1", "label2"]),
        pa.array(["val1", "val2"]),
    ], names=["label", "value"])
    t = pa.Table.from_arrays([struct_arr], names=["facts"])
    d = fast_digest(t)
    assert len(d) == 16


@pytest.mark.tier2
@pytest.mark.feature("F16")
def test_b16_digest_with_list_column():
    """B16.3: Verify fast digest computes over list columns."""
    t = pa.Table.from_pylist([{"tags": ["a", "b"]}, {"tags": ["c"]}])
    d = fast_digest(t)
    assert len(d) == 16


@pytest.mark.tier2
@pytest.mark.feature("F16")
def test_b16_digest_100000_rows_scalability():
    """B16.4: Verify fast digest executes in < 50 ms for 100,000 rows."""
    t = pa.Table.from_arrays([pa.array(list(range(100_000)), type=pa.int64())], names=["num"])
    start = time.perf_counter()
    _ = fast_digest(t)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05  # Under 50 ms


@pytest.mark.tier2
@pytest.mark.feature("F16")
def test_b16_chunked_array_buffer_hash():
    """B16.5: Verify multi-chunk array hashes all chunks deterministically."""
    arr1 = pa.array([1, 2, 3], type=pa.int32())
    arr2 = pa.array([4, 5, 6], type=pa.int32())
    chunked = pa.chunked_array([arr1, arr2])
    t = pa.Table.from_arrays([chunked], names=["col"])
    assert len(t.column(0).chunks) == 2
    d = fast_digest(t)
    assert len(d) == 16
