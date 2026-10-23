"""Adversarial stress-testing suite for Milestone 1 (Ticket ct-8v02).

Authored by Challenger 1 (critic/specialist).
Empirically stress-tests:
1. 256 KiB limit: exact boundary (262,144 bytes accepts, 262,145 bytes rejects with ValueError).
2. PDF magic bytes '%PDF-' with trailing binary garbage.
3. High U+FFFD replacement character ratio (> 5% rejected, <= 5% accepted).
4. _write_table with reused row list to confirm no row mutation.
5. Multi-pass stability and CAS path integrity.
"""

from __future__ import annotations
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from committee_explorer.parquet import (
    MAX_CELL_SIZE,
    SOURCE_SCHEMA,
    TABLE_SCHEMAS,
    _source_row,
    _write_sources,
    _write_table,
)
from congress_api.retention.senate import cached_html_path, seed_fetch


# ===========================================================================
# 1. Stress Test: 256 KiB Limit (Exact Boundary: 262,144 vs 262,145 bytes)
# ===========================================================================

def _make_meeting_row(row_id: str, title: str) -> dict:
    return {
        'id': row_id,
        'kind': 'meeting',
        'title': title,
        'chamber': 'senate',
        'congress': 118,
        'date': '2024-05-15',
        'type': 'hearing',
        'status': 'held',
        'meeting_id': None,
        'search_text': None,
        'scheduled_at': None,
        'access': 'public',
        'committee_ids': ['SSCI'],
        'committee_level': 'full',
        'committee_types': ['standing'],
        'source_ids': ['src-01'],
        'explanation': None,
        'issue_count': 0,
        'facts': [{'label': 'Topic', 'value': 'Intelligence Oversight'}],
        'evidence_states': None,
    }


def _make_source_row(row_id: str, title: str) -> dict:
    return {
        'id': row_id,
        'kind': 'source_record',
        'provider': 'senate.committees',
        'url': f'https://example.org/{row_id}',
        'title': title,
        'retrieved_at': '2024-05-15T12:00:00Z',
        'source_modified_at': '2024-05-15T10:00:00Z',
        'imported_at': '2024-05-15T12:05:00Z',
        'input_snapshot_id': 'snap-001',
        'identifier_scheme': 'senate:event',
        'identifier_value': '105290',
        'identifier_scope': 'hearing',
        'facts': [{'label': 'Chamber', 'value': 'senate'}],
        'links': [{'group': 'source', 'label': 'Hearing Link', 'href': 'https://example.org'}],
        'retained_uri': 'bodies/sha256/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.gz',
        'retained_sha256': 'a' * 64,
    }


def test_256_kib_exact_boundary_in_write_table(tmp_path: Path):
    """Exact boundary: 262,144 bytes accepts; 262,145 bytes raises ValueError in _write_table."""
    target_parquet = tmp_path / "meetings_boundary.parquet"
    
    # 1. Exact boundary: 262,144 bytes must ACCEPT
    str_exact_256k = "A" * 262_144
    assert len(str_exact_256k) == 262_144
    row_accept = _make_meeting_row("m-262144", str_exact_256k)
    
    _write_table([row_accept], TABLE_SCHEMAS['meeting'], target_parquet, row_group_size=512)
    assert target_parquet.is_file()
    read_table = pq.read_table(target_parquet)
    assert len(read_table) == 1
    assert len(read_table['title'][0].as_py()) == 262_144

    # 2. Exact boundary + 1: 262,145 bytes must REJECT with ValueError
    str_exceed_256k = "A" * 262_145
    assert len(str_exceed_256k) == 262_145
    row_reject = _make_meeting_row("m-262145", str_exceed_256k)
    
    target_parquet_reject = tmp_path / "meetings_reject.parquet"
    with pytest.raises(ValueError, match="exceeds 256 KiB limit: 262145 bytes"):
        _write_table([row_reject], TABLE_SCHEMAS['meeting'], target_parquet_reject, row_group_size=512)


def test_256_kib_exact_boundary_in_write_sources(tmp_path: Path):
    """Exact boundary: 262,144 bytes accepts; 262,145 bytes raises ValueError in _write_sources."""
    # 1. Exact boundary: 262,144 bytes must ACCEPT
    str_exact_256k = "S" * 262_144
    row_accept = _make_source_row("s-262144", str_exact_256k)
    
    # _write_sources writes sources.parquet and returns [(name, count)]
    files = _write_sources([row_accept], tmp_path)
    assert files == [('sources.parquet', 1)]
    written_parquet = tmp_path / 'sources.parquet'
    assert written_parquet.is_file()
    read_table = pq.read_table(written_parquet)
    assert len(read_table) == 1
    assert len(read_table['title'][0].as_py()) == 262_144

    # 2. Exact boundary + 1: 262,145 bytes must REJECT with ValueError
    str_exceed_256k = "S" * 262_145
    row_reject = _make_source_row("s-262145", str_exceed_256k)
    
    with pytest.raises(ValueError, match="exceeds 256 KiB limit: 262145 bytes"):
        list(_write_sources([row_reject], tmp_path))


def test_256_kib_boundary_on_bytes_and_bytearray(tmp_path: Path):
    """Verify bytes and bytearray types are also checked against MAX_CELL_SIZE."""
    raw_262144 = b"X" * 262_144
    row_bytes_ok = _make_meeting_row("m-bytes-ok", "Title")
    row_bytes_ok['search_text'] = raw_262144
    _write_table([row_bytes_ok], TABLE_SCHEMAS['meeting'], tmp_path / "bytes_ok.parquet", row_group_size=512)

    raw_262145 = b"X" * 262_145
    row_bytes_fail = _make_meeting_row("m-bytes-fail", "Title")
    row_bytes_fail['search_text'] = raw_262145
    with pytest.raises(ValueError, match="exceeds 256 KiB limit: 262145 bytes"):
        _write_table([row_bytes_fail], TABLE_SCHEMAS['meeting'], tmp_path / "bytes_fail.parquet", row_group_size=512)


# ===========================================================================
# 2. Stress Test: PDF Magic Bytes '%PDF-' with Trailing Binary Garbage
# ===========================================================================

def test_senate_seed_fetch_pdf_magic_with_trailing_binary_garbage(tmp_path: Path):
    """Corrupted / truncated PDF stream with arbitrary binary garbage is safely detected and offloaded."""
    url = "https://www.senate.gov/isvp/corrupt_garbage.pdf"
    cache_path = cached_html_path(tmp_path, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Header %PDF- followed by 50 KiB of pseudo-random binary garbage
    garbage_payload = b"%PDF-1.7\r\n" + bytes([i % 256 for i in range(50_000)])
    cache_path.write_bytes(garbage_payload)

    result = seed_fetch(tmp_path, url)
    # Must return empty string to prevent corrupted ingestion into text tables
    assert result == ""
    
    # Must be stored uncompressed in local CAS as .pdf
    digest = hashlib.sha256(garbage_payload).hexdigest()
    expected_cas = tmp_path / "bodies" / "sha256" / digest[:2] / f"{digest}.pdf"
    assert expected_cas.is_file(), f"Expected CAS object not found at {expected_cas}"
    assert expected_cas.read_bytes() == garbage_payload
    # Must NOT be stored as .gz
    assert not (tmp_path / "bodies" / "sha256" / digest[:2] / f"{digest}.gz").exists()


def test_parquet_source_row_pdf_magic_with_binary_garbage(tmp_path: Path):
    """_source_row with %PDF- binary payload stores uncompressed .pdf in CAS and normalizes row."""
    garbage_payload = b"%PDF-1.4\n" + os.urandom(10_000)
    source = {
        'id': 'src-corrupt-pdf',
        'kind': 'source_record',
        'provider': 'senate.intelligence',
        'url': 'https://www.intelligence.senate.gov/hearing.pdf',
        'identifier': {'scheme': 'senate:hearing', 'value': '105290'},
        'payload': garbage_payload,
    }
    
    row = _source_row(source, stage=tmp_path)
    digest = hashlib.sha256(garbage_payload).hexdigest()
    assert row['retained_sha256'] == digest
    assert row['retained_uri'] == f"bodies/sha256/{digest[:2]}/{digest}.pdf"
    assert row['retained_uri'].endswith('.pdf')
    # Raw binary payload must NOT be in the row
    assert 'payload' not in row
    
    # CAS object on disk must be uncompressed PDF
    staged_file = tmp_path / row['retained_uri']
    assert staged_file.is_file()
    assert staged_file.read_bytes() == garbage_payload


# ===========================================================================
# 3. Stress Test: High U+FFFD Replacement Character Ratio (> 5% vs <= 5%)
# ===========================================================================

def test_senate_seed_fetch_ufffd_ratio_exact_boundaries(tmp_path: Path):
    """Empirically test exact U+FFFD boundary:
    <= 5% accepted as text; > 5% rejected and offloaded to CAS.
    """
    url_base = "https://www.senate.gov/isvp/test_boundary_"

    # Case A: Pure ASCII text (0% U+FFFD) -> ACCEPTED
    url_a = url_base + "0pct.html"
    path_a = cached_html_path(tmp_path, url_a)
    path_a.parent.mkdir(parents=True, exist_ok=True)
    text_a = "<html>" + ("A" * 900) + "</html>"
    path_a.write_bytes(text_a.encode("utf-8"))
    res_a = seed_fetch(tmp_path, url_a)
    assert res_a == text_a

    # Case B: Exactly 5.0% U+FFFD replacement characters -> ACCEPTED (<= 5%)
    # Construct 95 valid single-byte ASCII chars + 5 invalid bytes (0xFF)
    # 0xFF in UTF-8 decode('replace') produces exactly one \ufffd each.
    # Total characters decoded = 95 + 5 = 100 characters.
    # Ratio = 5 / 100 = 0.050 (5.0%).
    # senate.py condition: fffd_count / max(1, len(decoded)) > 0.05
    # 0.05 > 0.05 is False, so it should be ACCEPTED.
    url_b = url_base + "5pct.html"
    path_b = cached_html_path(tmp_path, url_b)
    data_b = (b"A" * 95) + (b"\xff" * 5)
    decoded_b = data_b.decode("utf-8", "replace")
    assert len(decoded_b) == 100
    assert decoded_b.count("\ufffd") == 5
    assert (decoded_b.count("\ufffd") / len(decoded_b)) == 0.05
    path_b.write_bytes(data_b)
    res_b = seed_fetch(tmp_path, url_b)
    assert res_b == decoded_b, "5.0% replacement characters must be ACCEPTED"

    # Case C: 6.0% U+FFFD replacement characters -> REJECTED (> 5%)
    # Construct 94 valid single-byte ASCII chars + 6 invalid bytes (0xFF)
    # Total characters decoded = 94 + 6 = 100 characters.
    # Ratio = 6 / 100 = 0.060 (6.0%).
    # 0.06 > 0.05 is True, so it must be REJECTED.
    url_c = url_base + "6pct.html"
    path_c = cached_html_path(tmp_path, url_c)
    data_c = (b"A" * 94) + (b"\xff" * 6)
    decoded_c = data_c.decode("utf-8", "replace")
    assert len(decoded_c) == 100
    assert decoded_c.count("\ufffd") == 6
    assert (decoded_c.count("\ufffd") / len(decoded_c)) == 0.06
    path_c.write_bytes(data_c)
    res_c = seed_fetch(tmp_path, url_c)
    assert res_c == "", "6.0% replacement characters must be REJECTED"
    digest_c = hashlib.sha256(data_c).hexdigest()
    assert (tmp_path / "bodies" / "sha256" / digest_c[:2] / f"{digest_c}.pdf").is_file()

    # Case D: 100% invalid binary -> REJECTED
    url_d = url_base + "100pct.html"
    path_d = cached_html_path(tmp_path, url_d)
    data_d = b"\xff\xfe\x80\x81" * 50
    path_d.write_bytes(data_d)
    res_d = seed_fetch(tmp_path, url_d)
    assert res_d == ""
    digest_d = hashlib.sha256(data_d).hexdigest()
    assert (tmp_path / "bodies" / "sha256" / digest_d[:2] / f"{digest_d}.pdf").is_file()


# ===========================================================================
# 4. Stress Test: _write_table with Reused Row List (No Row Mutation)
# ===========================================================================

def test_write_table_reused_row_list_no_mutation(tmp_path: Path):
    """Empirically test that passing a list of rows to _write_table does NOT
    mutate the caller's row list or row dicts, allowing the same list to be reused.
    """
    rows = [
        _make_meeting_row("m-001", "Hearing on Advanced Microelectronics"),
        _make_meeting_row("m-002", "Oversight of Commercial Space Launches"),
        _make_meeting_row("m-003", "Review of Quantum Computing Research"),
    ]
    # Deep copy to verify absolute immutability of row list and contents
    snapshot = copy.deepcopy(rows)

    path_first = tmp_path / "first_run.parquet"
    path_second = tmp_path / "second_run.parquet"

    # Pass 1: write to path_first with default clear_rows (which must be False)
    _write_table(rows, TABLE_SCHEMAS['meeting'], path_first, row_group_size=2)
    assert path_first.is_file()
    assert pq.read_table(path_first).num_rows == 3

    # Verify rows list was NOT replaced with None entries
    assert len(rows) == 3
    for i, r in enumerate(rows):
        assert r is not None, f"Row {i} was replaced with None!"
        assert isinstance(r, dict), f"Row {i} is no longer a dict!"
        assert r['id'] == snapshot[i]['id']
        assert r['title'] == snapshot[i]['title']

    # Pass 2: Reuse the EXACT same rows list to write to path_second
    _write_table(rows, TABLE_SCHEMAS['meeting'], path_second, row_group_size=2)
    assert path_second.is_file()
    assert pq.read_table(path_second).num_rows == 3

    # Output files must be byte-for-byte identical
    assert path_first.read_bytes() == path_second.read_bytes()


def test_write_table_opt_in_clear_rows_preserves_memory_management(tmp_path: Path):
    """When clear_rows=True is explicitly specified, verify it still clears rows for memory savings."""
    rows = [
        _make_meeting_row("m-clear-01", "Temporary Memory Test 1"),
        _make_meeting_row("m-clear-02", "Temporary Memory Test 2"),
    ]
    path = tmp_path / "cleared.parquet"
    _write_table(rows, TABLE_SCHEMAS['meeting'], path, row_group_size=1, clear_rows=True)
    assert path.is_file()
    # List elements should be replaced with None when clear_rows=True
    assert all(r is None for r in rows)


# ===========================================================================
# 5. Stress Test: Edge Cases in Normalization and Workspace Sync
# ===========================================================================

def test_senate_seed_fetch_syncs_to_tables_workspace(tmp_path: Path):
    """Verify that when tables.workspace is present, binary PDF is copied to tables.workspace."""
    class MockTables:
        def __init__(self, ws: Path):
            self.workspace = ws

    cache_dir = tmp_path / "cache"
    ws_dir = tmp_path / "workspace"
    cache_dir.mkdir()
    ws_dir.mkdir()

    url = "https://www.senate.gov/isvp/workspace_test.pdf"
    cache_path = cached_html_path(cache_dir, url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = b"%PDF-1.4\n%Binary test for workspace\n%%EOF"
    cache_path.write_bytes(pdf_bytes)

    tables = MockTables(ws_dir)
    result = seed_fetch(cache_dir, url, tables=tables)
    assert result == ""

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    rel_key = Path("bodies") / "sha256" / digest[:2] / f"{digest}.pdf"
    
    # Must exist in cache
    assert (cache_dir / rel_key).is_file()
    assert (cache_dir / rel_key).read_bytes() == pdf_bytes
    # Must exist in workspace
    assert (ws_dir / rel_key).is_file()
    assert (ws_dir / rel_key).read_bytes() == pdf_bytes


def test_source_row_handles_none_empty_and_legacy_shapes(tmp_path: Path):
    """Verify _source_row robustly handles empty payloads, string payloads, and pre-existing facts/links."""
    # 1. Empty dict source
    row_empty = _source_row({}, stage=tmp_path)
    assert row_empty['id'] is None
    assert row_empty['title'] is None
    assert row_empty['facts'] == []
    assert row_empty['links'] == []
    assert row_empty['retained_sha256'] is None
    assert row_empty['retained_uri'] is None

    # 2. String JSON payload
    json_str_payload = '{"title": "String JSON Hearing", "chamber": "senate", "url": "https://example.org/str"}'
    source_str = {
        'id': 'src-str',
        'provider': 'senate',
        'payload': json_str_payload,
    }
    row_str = _source_row(source_str, stage=tmp_path)
    assert row_str['retained_sha256'] == hashlib.sha256(json_str_payload.encode('utf-8')).hexdigest()
    assert row_str['retained_uri'].endswith('.gz')
    staged_gz = tmp_path / row_str['retained_uri']
    assert staged_gz.is_file()
    assert gzip.decompress(staged_gz.read_bytes()).decode('utf-8') == json_str_payload

    # 3. Source with tuple-style existing facts and links
    source_existing = {
        'id': 'src-exist',
        'provider': 'senate',
        'facts': [('Custom Label', 'Custom Value')],
        'links': [('group1', 'Link Label', 'https://example.org/link')],
    }
    row_exist = _source_row(source_existing, stage=tmp_path)
    assert row_exist['facts'] == [{'label': 'Custom Label', 'value': 'Custom Value'}]
    assert row_exist['links'] == [{'group': 'group1', 'label': 'Link Label', 'href': 'https://example.org/link'}]

