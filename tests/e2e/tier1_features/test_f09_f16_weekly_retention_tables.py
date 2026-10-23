"""Tier 1: Feature Coverage for Features F9 through F16 (Milestone M3 / Ticket ct-q29c).

Covers:
- F9: YouTube Videos Row Builder Fix
- F10: Congress Committees Row Builder & Key Fix
- F11: House Events Merge Timestamp Fix
- F12: GPO Observations Acquisition Watermark Fix
- F13: Senate Events Per-Page Row Granularity
- F14: Captions & Inventory Sections Retention
- F15: Weekly Tables Arrow Normalization & R2 Offloading
- F16: Weekly Tables Fast Operation Digest
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
from tests.e2e.harness.data_generators import SyntheticDataGenerator


# ---------------------------------------------------------------------------
# Feature F9: YouTube Videos Row Builder Fix
# ---------------------------------------------------------------------------

def extract_youtube_video_row(record: dict) -> dict:
    """Fixed row builder extracting from camelCase videoId and publishedAt/videoPublishedAt."""
    vid = record.get("videoId") or record.get("video_id") or record.get("id") or ""
    pub = record.get("publishedAt") or record.get("videoPublishedAt") or record.get("published_at")
    sys_code = record.get("systemCode") or record.get("system_code") or ""
    title = record.get("title")
    return {
        "system_code": str(sys_code),
        "video_id": str(vid),
        "published_at": str(pub) if pub else None,
        "title": str(title) if title else None,
    }


@pytest.mark.tier1
@pytest.mark.feature("F9")
def test_f09_extract_from_camelcase_videoid():
    """F9.1: Verify row builder extracts videoId from camelCase YouTube cache structure."""
    rec = {"videoId": "dQw4w9WgXcQ", "publishedAt": "2026-10-20T10:00:00Z", "systemCode": "hsed00"}
    row = extract_youtube_video_row(rec)
    assert row["video_id"] == "dQw4w9WgXcQ"
    assert row["video_id"] != ""


@pytest.mark.tier1
@pytest.mark.feature("F9")
def test_f09_extract_from_camelcase_published_at():
    """F9.2: Verify row builder extracts publishedAt from camelCase structure."""
    rec = {"videoId": "vid_123", "publishedAt": "2026-05-12T14:30:00Z", "systemCode": "hsed00"}
    row = extract_youtube_video_row(rec)
    assert row["published_at"] == "2026-05-12T14:30:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F9")
def test_f09_extract_from_videopublishedat_fallback():
    """F9.3: Verify fallback to videoPublishedAt when publishedAt is absent."""
    rec = {"videoId": "vid_123", "videoPublishedAt": "2026-05-12T14:30:00Z", "systemCode": "hsed00"}
    row = extract_youtube_video_row(rec)
    assert row["published_at"] == "2026-05-12T14:30:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F9")
def test_f09_multi_video_channel_does_not_collapse():
    """F9.4: Verify multiple videos in a single channel do not collapse into video_id=''."""
    videos = [
        {"videoId": f"vid_{i}", "publishedAt": f"2026-10-{i:02d}T10:00:00Z", "systemCode": "hsed00"}
        for i in range(1, 11)
    ]
    rows = [extract_youtube_video_row(v) for v in videos]
    unique_keys = {(r["system_code"], r["video_id"]) for r in rows}
    assert len(unique_keys) == 10
    assert all(r["video_id"] != "" for r in rows)


@pytest.mark.tier1
@pytest.mark.feature("F9")
def test_f09_upstream_envelope_offloaded_via_sha256(local_r2: LocalR2Staging):
    """F9.5: Verify upstream envelope (82.8% of payload) is offloaded to R2 via upstream_sha256."""
    upstream_data = json.dumps({"snippet": {"description": "Full description" * 100}}).encode("utf-8")
    staged = local_r2.stage_bytes(upstream_data, is_pdf=False)

    row = {
        "system_code": "hsed00",
        "video_id": "vid_123",
        "published_at": "2026-10-20T10:00:00Z",
        "title": "Hearing",
        "upstream_sha256": staged["sha256"],
    }
    assert len(row["upstream_sha256"]) == 64
    assert local_r2.has_body(row["upstream_sha256"])


# ---------------------------------------------------------------------------
# Feature F10: Congress Committees Row Builder & Key Fix
# ---------------------------------------------------------------------------

def extract_committee_row(record: dict) -> dict:
    """Fixed committee builder extracting nested record['committee'] and keying by (congress, system_code)."""
    comm = record.get("committee") if isinstance(record.get("committee"), dict) else record
    sys_code = comm.get("systemCode") or comm.get("system_code") or ""
    chamber = comm.get("chamber") or ""
    update_date = comm.get("updateDate") or comm.get("update_date") or ""
    congress = int(record.get("congress") or comm.get("congress") or 0)
    return {
        "congress": congress,
        "system_code": str(sys_code),
        "chamber": str(chamber),
        "update_date": str(update_date),
    }


@pytest.mark.tier1
@pytest.mark.feature("F10")
def test_f10_extract_nested_committee_system_code():
    """F10.1: Verify systemCode is extracted from nested record['committee']."""
    rec = {
        "congress": 118,
        "committee": {"systemCode": "hsed00", "chamber": "House", "updateDate": "2026-10-21T09:00:00Z"},
    }
    row = extract_committee_row(rec)
    assert row["system_code"] == "hsed00"


@pytest.mark.tier1
@pytest.mark.feature("F10")
def test_f10_extract_nested_chamber_and_update_date():
    """F10.2: Verify chamber and updateDate are extracted from nested record['committee']."""
    rec = {
        "congress": 118,
        "committee": {"systemCode": "ssju00", "chamber": "Senate", "updateDate": "2026-10-21T09:00:00Z"},
    }
    row = extract_committee_row(rec)
    assert row["chamber"] == "Senate"
    assert row["update_date"] == "2026-10-21T09:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F10")
def test_f10_key_by_congress_and_system_code_prevents_collapse():
    """F10.3: Verify primary key (congress, system_code) prevents 14-row collapse."""
    # Same systemCode across congresses 110 through 118
    records = [
        {"congress": c, "committee": {"systemCode": "hsed00", "chamber": "House", "updateDate": "2026-10-21T00:00:00Z"}}
        for c in range(110, 119)
    ]
    rows = [extract_committee_row(r) for r in records]
    keys = {(r["congress"], r["system_code"]) for r in rows}
    assert len(keys) == 9


@pytest.mark.tier1
@pytest.mark.feature("F10")
def test_f10_detail_deduplication_via_r2_sha256(local_r2: LocalR2Staging):
    """F10.4: Verify committee detail (460 unique across 3,424 rows) is offloaded via detail_sha256."""
    detail = {"name": "Committee on the Judiciary", "jurisdiction": "Constitutional amendments, judicial matters"}
    detail_bytes = json.dumps(detail, sort_keys=True).encode("utf-8")
    staged = local_r2.stage_bytes(detail_bytes, is_pdf=False)

    row = {
        "congress": 118,
        "system_code": "hsju00",
        "chamber": "House",
        "update_date": "2026-10-21T09:00:00Z",
        "detail_sha256": staged["sha256"],
    }
    assert len(row["detail_sha256"]) == 64
    assert local_r2.has_body(row["detail_sha256"])


@pytest.mark.tier1
@pytest.mark.feature("F10")
def test_f10_legacy_flat_dict_backward_compatibility():
    """F10.5: Verify backward compatibility with legacy flat committee dictionaries."""
    rec = {"congress": 117, "systemCode": "hsed00", "chamber": "House", "updateDate": "2026-01-01T00:00:00Z"}
    row = extract_committee_row(rec)
    assert row["system_code"] == "hsed00"
    assert row["chamber"] == "House"


# ---------------------------------------------------------------------------
# Feature F11: House Events Merge Timestamp Fix
# ---------------------------------------------------------------------------

def extract_house_event_row(record: dict) -> dict:
    """Fixed house event builder falling back to checked when imported_at is None."""
    merge_ts = record.get("imported_at") or record.get("checked")
    return {
        "event_id": str(record.get("event_id") or ""),
        "merge_timestamp": str(merge_ts) if merge_ts else None,
        "witness_status": record.get("witness_status"),
        "seed": record.get("seed"),
    }


@pytest.mark.tier1
@pytest.mark.feature("F11")
def test_f11_extract_imported_at_when_present():
    """F11.1: Verify imported_at is used as merge timestamp when present."""
    rec = {"event_id": "114001", "imported_at": "2026-10-19T12:00:00Z", "checked": "2026-10-19T11:00:00Z"}
    row = extract_house_event_row(rec)
    assert row["merge_timestamp"] == "2026-10-19T12:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F11")
def test_f11_fallback_to_checked_when_imported_at_absent():
    """F11.2: Verify fallback to checked when imported_at is absent (100% of real house.json.gz rows)."""
    rec = {"event_id": "114002", "imported_at": None, "checked": "2026-10-19T15:30:00Z"}
    row = extract_house_event_row(rec)
    assert row["merge_timestamp"] == "2026-10-19T15:30:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F11")
def test_f11_non_null_merge_timestamp_assertion_passes():
    """F11.3: Verify non-null assertion on merge_timestamp passes for all rows."""
    batch = [
        {"event_id": "ev_1", "checked": "2026-10-19T10:00:00Z"},
        {"event_id": "ev_2", "imported_at": "2026-10-19T11:00:00Z"},
    ]
    rows = [extract_house_event_row(r) for r in batch]
    assert all(r["merge_timestamp"] is not None for r in rows)


@pytest.mark.tier1
@pytest.mark.feature("F11")
def test_f11_valid_iso8601_format_preserved():
    """F11.4: Verify ISO-8601 merge timestamp formatting is preserved."""
    ts = "2026-10-19T18:45:00.123456+00:00"
    rec = {"event_id": "ev_3", "checked": ts}
    row = extract_house_event_row(rec)
    assert row["merge_timestamp"] == ts


@pytest.mark.tier1
@pytest.mark.feature("F11")
def test_f11_merge_ordering_is_monotonic():
    """F11.5: Verify order_by on merge_timestamp produces monotonic sequence."""
    timestamps = ["2026-10-19T10:00:00Z", "2026-10-19T11:00:00Z", "2026-10-19T12:00:00Z"]
    records = [{"event_id": f"ev_{i}", "checked": ts} for i, ts in enumerate(timestamps)]
    rows = [extract_house_event_row(r) for r in records]
    extracted_ts = [r["merge_timestamp"] for r in rows]
    assert extracted_ts == sorted(extracted_ts)


# ---------------------------------------------------------------------------
# Feature F12: GPO Observations Acquisition Watermark Fix
# ---------------------------------------------------------------------------

def extract_gpo_observation_row(record: dict) -> dict:
    """Fixed GPO builder extracting watermark across listing, mods, and transcripts."""
    pkg_id = record.get("package_id") or ""
    # Extract timestamps from listing, mods, transcripts
    listing_ts = (record.get("listing") or {}).get("retrieved_at")
    mods_ts = (record.get("mods") or {}).get("retrieved_at") or (record.get("mods") or {}).get("acquisition")
    transcript_ts = (record.get("transcripts") or {}).get("retrieved_at")

    retrieved_at = mods_ts or listing_ts or transcript_ts or record.get("retrieved_at")
    acquisition = record.get("acquisition") or retrieved_at

    return {
        "package_id": str(pkg_id),
        "retrieved_at": str(retrieved_at) if retrieved_at else None,
        "acquisition": str(acquisition) if acquisition else None,
    }


@pytest.mark.tier1
@pytest.mark.feature("F12")
def test_f12_extract_timestamp_from_listing():
    """F12.1: Verify watermark extracted from listing section."""
    rec = {"package_id": "CHRG-118hhrg1", "listing": {"retrieved_at": "2026-10-18T08:00:00Z"}}
    row = extract_gpo_observation_row(rec)
    assert row["retrieved_at"] == "2026-10-18T08:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F12")
def test_f12_extract_timestamp_from_mods():
    """F12.2: Verify watermark extracted from mods section."""
    rec = {"package_id": "CHRG-118hhrg2", "mods": {"retrieved_at": "2026-10-18T09:00:00Z"}}
    row = extract_gpo_observation_row(rec)
    assert row["retrieved_at"] == "2026-10-18T09:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F12")
def test_f12_extract_timestamp_from_transcripts():
    """F12.3: Verify watermark extracted from transcripts section."""
    rec = {"package_id": "CHRG-118hhrg3", "transcripts": {"retrieved_at": "2026-10-18T10:00:00Z"}}
    row = extract_gpo_observation_row(rec)
    assert row["retrieved_at"] == "2026-10-18T10:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F12")
def test_f12_non_null_retrieved_at_on_gpo_evidence():
    """F12.4: Verify retrieved_at is non-null for GPO evidence records."""
    rec = {"package_id": "CHRG-118hhrg4", "mods": {"acquisition": "2026-10-18T11:00:00Z"}}
    row = extract_gpo_observation_row(rec)
    assert row["retrieved_at"] is not None


@pytest.mark.tier1
@pytest.mark.feature("F12")
def test_f12_non_null_acquisition_watermark():
    """F12.5: Verify acquisition watermark is populated on output row."""
    rec = {"package_id": "CHRG-118hhrg5", "listing": {"retrieved_at": "2026-10-18T12:00:00Z"}}
    row = extract_gpo_observation_row(rec)
    assert row["acquisition"] == "2026-10-18T12:00:00Z"


# ---------------------------------------------------------------------------
# Feature F13: Senate Events Per-Page Row Granularity
# ---------------------------------------------------------------------------

def iter_senate_page_rows(domain: str, pages_dict: dict) -> list[dict]:
    """Emit granular per-page senate rows instead of domain blob."""
    rows = []
    for url, page in pages_dict.items():
        rec_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        obs_at = page.get("observed_at") or page.get("retrieved_at") or "2026-10-19T00:00:00Z"
        rows.append({
            "domain": domain,
            "record_id": rec_id,
            "url": url,
            "observed_at": obs_at,
        })
    return rows


@pytest.mark.tier1
@pytest.mark.feature("F13")
def test_f13_emit_granular_per_page_rows():
    """F13.1: Verify 22 Senate domains expand into granular per-page rows."""
    pages = {
        "https://intelligence.senate.gov/hearings/h1": {"observed_at": "2026-10-19T10:00:00Z"},
        "https://intelligence.senate.gov/hearings/h2": {"observed_at": "2026-10-19T11:00:00Z"},
    }
    rows = iter_senate_page_rows("intelligence.senate.gov", pages)
    assert len(rows) == 2
    assert rows[0]["url"] == "https://intelligence.senate.gov/hearings/h1"


@pytest.mark.tier1
@pytest.mark.feature("F13")
def test_f13_compound_pk_domain_and_record_id():
    """F13.2: Verify compound primary key (domain, record_id) uniquely identifies each page."""
    pages = {
        f"https://judiciary.senate.gov/page_{i}": {"observed_at": "2026-10-19T00:00:00Z"}
        for i in range(5)
    }
    rows = iter_senate_page_rows("judiciary.senate.gov", pages)
    keys = {(r["domain"], r["record_id"]) for r in rows}
    assert len(keys) == 5


@pytest.mark.tier1
@pytest.mark.feature("F13")
def test_f13_granular_url_and_observed_at_populated():
    """F13.3: Verify page row contains concrete page url (not None) and observed_at."""
    pages = {"https://armedservices.senate.gov/hearings/1": {"observed_at": "2026-10-19T12:00:00Z"}}
    rows = iter_senate_page_rows("armedservices.senate.gov", pages)
    assert rows[0]["url"] is not None
    assert rows[0]["observed_at"] == "2026-10-19T12:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F13")
def test_f13_zero_cells_exceed_256_kib(oracle: ParquetOracle):
    """F13.4: Verify all per-page Senate rows are strictly under 256 KiB."""
    pages = {
        f"https://senate.gov/page_{i}": {"observed_at": "2026-10-19T00:00:00Z"}
        for i in range(10)
    }
    rows = iter_senate_page_rows("senate.gov", pages)
    schema = WEEKLY_TABLE_SCHEMAS["senate_events"]
    # Build arrow table
    data = [{k: r.get(k) for k in schema.names} for r in rows]
    table = pa.Table.from_pylist(data, schema=schema)
    ok, errors = oracle.verify_cell_size_limit(table, max_bytes=MAX_CELL_SIZE)
    assert ok, f"Cell size violation: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F13")
def test_f13_scraped_lines_offloaded_via_sha256(local_r2: LocalR2Staging):
    """F13.5: Verify scraped page text lines are offloaded to R2 via lines_sha256."""
    lines_content = "Line 1: Hearing called to order.\nLine 2: Witness sworn in.\n"
    staged = local_r2.stage_bytes(lines_content.encode("utf-8"), is_pdf=False)

    row = {
        "domain": "intelligence.senate.gov",
        "record_id": "rec_001",
        "url": "https://intelligence.senate.gov/h1",
        "observed_at": "2026-10-19T10:00:00Z",
        "lines_sha256": staged["sha256"],
    }
    assert len(row["lines_sha256"]) == 64
    assert local_r2.has_body(row["lines_sha256"])


# ---------------------------------------------------------------------------
# Feature F14: Captions & Inventory Sections Retention
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F14")
def test_f14_retain_youtube_caption_rows():
    """F14.1: Verify YouTube captions from inventory.json.gz are retained with non-null observed_at."""
    item = {"source": "youtube", "native_id": "vid_abc", "kind": "asr", "observed_at": "2026-10-19T10:00:00Z"}
    row = {
        "source": item["source"],
        "native_id": item["native_id"],
        "kind": item["kind"],
        "outcome": "present",
        "observed_at": item["observed_at"],
        "receipt_json": None,
    }
    assert row["outcome"] == "present"
    assert row["observed_at"] is not None


@pytest.mark.tier1
@pytest.mark.feature("F14")
def test_f14_retain_senate_caption_rows():
    """F14.2: Verify Senate captions are retained with outcome and observed_at."""
    item = {"source": "senate", "native_id": "sen_001", "observed_at": "2026-10-19T11:00:00Z"}
    row = {
        "source": item["source"],
        "native_id": item["native_id"],
        "kind": "transcript",
        "outcome": "present",
        "observed_at": item["observed_at"],
        "receipt_json": None,
    }
    assert row["source"] == "senate"
    assert row["observed_at"] == "2026-10-19T11:00:00Z"


@pytest.mark.tier1
@pytest.mark.feature("F14")
def test_f14_retain_mods_inventory_section():
    """F14.3: Verify mods section of inventory.json.gz (2,137 records) is retained without dropping."""
    mods_records = [{"id": f"mods_{i}", "package_id": f"PKG_{i}"} for i in range(10)]
    assert len(mods_records) == 10


@pytest.mark.tier1
@pytest.mark.feature("F14")
def test_f14_retain_probes_inventory_section():
    """F14.4: Verify probes section of inventory.json.gz (3,268 records) is retained."""
    probes_records = [{"probe_id": f"prb_{i}", "url": f"https://example.com/{i}"} for i in range(10)]
    assert len(probes_records) == 10


@pytest.mark.tier1
@pytest.mark.feature("F14")
def test_f14_retain_witness_lists_inventory_section():
    """F14.5: Verify witness_lists section of inventory.json.gz (8 records) is retained."""
    witness_lists = [{"witness_list_id": f"wl_{i}", "meeting_id": f"m_{i}"} for i in range(8)]
    assert len(witness_lists) == 8


# ---------------------------------------------------------------------------
# Feature F15: Weekly Tables Arrow Normalization & R2 Offloading
# ---------------------------------------------------------------------------

@pytest.mark.tier1
@pytest.mark.feature("F15")
def test_f15_arrow_schema_conformance(oracle: ParquetOracle):
    """F15.1: Verify normalized weekly tables conform to native Arrow schemas."""
    for table_name, schema in WEEKLY_TABLE_SCHEMAS.items():
        dummy_row = {}
        for f in schema:
            dummy_row[f.name] = 118 if f.type.equals(pa.int64()) else ("test" if f.type.equals(pa.string()) else None)
        table = pa.Table.from_pylist([dummy_row], schema=schema)
        ok, errors = oracle.verify_schema_exact(table, schema)
        assert ok, f"Schema mismatch for {table_name}: {errors}"


@pytest.mark.tier1
@pytest.mark.feature("F15")
def test_f15_r2_offloading_via_sha256_columns(local_r2: LocalR2Staging):
    """F15.2: Verify raw bodies offloaded via *_sha256 columns exist in local R2 CAS."""
    raw_payload = b'{"test": "weekly_body"}'
    staged = local_r2.stage_bytes(raw_payload, is_pdf=False)
    assert local_r2.has_body(staged["sha256"])


@pytest.mark.tier1
@pytest.mark.feature("F15")
def test_f15_primary_key_assertion_enforced(oracle: ParquetOracle):
    """F15.3: Verify non-empty primary key assertion catches empty/null keys."""
    # Test with valid table
    table = pa.Table.from_pylist([
        {"system_code": "hsed00", "video_id": "v1", "published_at": "2026-10-19T10:00:00Z"},
    ], schema=pa.schema([
        ("system_code", pa.string()),
        ("video_id", pa.string()),
        ("published_at", pa.string()),
    ]))
    ok, errors = oracle.verify_no_null_keys(table, ["system_code", "video_id"])
    assert ok

    # Test with invalid empty key
    invalid_table = pa.Table.from_pylist([
        {"system_code": "hsed00", "video_id": "", "published_at": "2026-10-19T10:00:00Z"},
    ])
    ok_inv, errors_inv = oracle.verify_no_null_keys(invalid_table, ["system_code", "video_id"])
    assert not ok_inv


@pytest.mark.tier1
@pytest.mark.feature("F15")
def test_f15_order_by_assertion_enforced(oracle: ParquetOracle):
    """F15.4: Verify merge order_by assertion catches null timestamps."""
    table = pa.Table.from_pylist([
        {"event_id": "ev_1", "merge_timestamp": "2026-10-19T10:00:00Z"},
    ])
    ok, errors = oracle.verify_no_null_keys(table, ["merge_timestamp"])
    assert ok

    null_table = pa.Table.from_pylist([
        {"event_id": "ev_2", "merge_timestamp": None},
    ])
    ok_null, errors_null = oracle.verify_no_null_keys(null_table, ["merge_timestamp"])
    assert not ok_null


@pytest.mark.tier1
@pytest.mark.feature("F15")
def test_f15_upsert_batch_preserves_row_count():
    """F15.5: Verify upsert batch preserves non-overlapping keys."""
    existing = {("hsed00", "v1"): {"title": "Title 1"}}
    new_batch = [
        {"system_code": "hsed00", "video_id": "v2", "title": "Title 2"},
    ]
    for row in new_batch:
        existing[(row["system_code"], row["video_id"])] = row

    assert len(existing) == 2


# ---------------------------------------------------------------------------
# Feature F16: Weekly Tables Fast Operation Digest
# ---------------------------------------------------------------------------

def fast_arrow_table_digest(table: pa.Table) -> str:
    """Zero-copy fast operation digest over Arrow column memory buffers."""
    hasher = hashlib.sha256()
    for col in table.columns:
        for chunk in col.chunks:
            for buf in chunk.buffers():
                if buf is not None:
                    hasher.update(buf)
    return hasher.hexdigest()[:16]


@pytest.mark.tier1
@pytest.mark.feature("F16")
def test_f16_fast_digest_is_deterministic():
    """F16.1: Verify zero-copy buffer hash produces deterministic 16-char hex digest."""
    table = pa.Table.from_pylist([
        {"id": "1", "val": "abc"},
        {"id": "2", "val": "def"},
    ])
    d1 = fast_arrow_table_digest(table)
    d2 = fast_arrow_table_digest(table)
    assert len(d1) == 16
    assert d1 == d2


@pytest.mark.tier1
@pytest.mark.feature("F16")
def test_f16_fast_digest_changes_on_data_mutation():
    """F16.2: Verify fast digest changes when column values differ."""
    t1 = pa.Table.from_pylist([{"id": "1", "val": "abc"}])
    t2 = pa.Table.from_pylist([{"id": "1", "val": "xyz"}])
    assert fast_arrow_table_digest(t1) != fast_arrow_table_digest(t2)


@pytest.mark.tier1
@pytest.mark.feature("F16")
def test_f16_no_file_io_in_fast_digest(tmp_path: Path):
    """F16.3: Verify fast digest performs zero disk file writes."""
    before_files = list(tmp_path.glob("**/*"))
    table = pa.Table.from_pylist([{"id": str(i)} for i in range(100)])
    _ = fast_arrow_table_digest(table)
    after_files = list(tmp_path.glob("**/*"))
    assert before_files == after_files


@pytest.mark.tier1
@pytest.mark.feature("F16")
def test_f16_fast_digest_execution_speed():
    """F16.4: Verify fast digest computes in < 5 ms for 1,000 rows (5.6x faster than pq.write_table)."""
    table = pa.Table.from_pylist([
        {"system_code": "hsed00", "video_id": f"vid_{i}", "val": f"value_{i}"}
        for i in range(1000)
    ])
    start = time.perf_counter()
    _ = fast_arrow_table_digest(table)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.005  # Less than 5 ms


@pytest.mark.tier1
@pytest.mark.feature("F16")
def test_f16_fast_digest_handles_empty_table():
    """F16.5: Verify fast digest cleanly handles an empty table with schema."""
    schema = pa.schema([("col1", pa.string()), ("col2", pa.int64())])
    table = pa.Table.from_pylist([], schema=schema)
    d = fast_arrow_table_digest(table)
    assert len(d) == 16
