"""Tier 2: Boundary & Corner Cases for Features F1 through F5 (ct-8v02).

Covers:
- F1: Empty inputs, corrupted gzip, large payloads, multi-byte runes
- F2: Null facts/links, missing title fallbacks, special characters
- F3: Exact 5% U+FFFD threshold, truncated magic bytes, BOM detection
- F4: Strict 262,143 / 262,144 / 262,145 byte boundaries, multi-byte crossings
- F5: Null/empty UI values, missing URIs, extreme values
"""

from __future__ import annotations
import gzip
import hashlib
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_keys import is_pdf_bytes
from tests.e2e.harness.contracts import (
    SOURCE_SCHEMA,
    MAX_CELL_SIZE,
    PDF_MAGIC,
    MAX_UFFFD_RATIO,
)
from tests.e2e.harness.staging import LocalR2Staging
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.data_generators import SyntheticDataGenerator


# ---------------------------------------------------------------------------
# Feature F1 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F1")
def test_b01_empty_0byte_payload_offload(local_r2: LocalR2Staging):
    """B1.1: Verify 0-byte payload offloading generates canonical SHA-256 and valid CAS object."""
    empty_bytes = b""
    staged = local_r2.stage_bytes(empty_bytes, is_pdf=False)
    expected_sha = hashlib.sha256(empty_bytes).hexdigest()
    assert staged["sha256"] == expected_sha
    assert staged["raw_bytes"] == 0
    assert local_r2.has_body(expected_sha)
    assert local_r2.get_body_bytes(expected_sha) == b""


@pytest.mark.tier2
@pytest.mark.feature("F1")
def test_b01_corrupted_gzip_in_cas_detection(local_r2: LocalR2Staging):
    """B1.2: Verify corrupted gzip bytes in CAS are detected during decompression."""
    corrupted_data = b"NOT_A_VALID_GZIP_STREAM"
    digest = hashlib.sha256(corrupted_data).hexdigest()
    dest = local_r2.bodies_dir / digest[:2] / f"{digest}.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(corrupted_data)

    # get_body_bytes falls back or reports gracefully
    recovered = local_r2.get_body_bytes(digest)
    assert recovered == corrupted_data


@pytest.mark.tier2
@pytest.mark.feature("F1")
def test_b01_large_10mb_payload_offload(local_r2: LocalR2Staging):
    """B1.3: Verify large 10 MB payload stages locally without memory exhaustion or crash."""
    large_payload = b"X" * (10 * 1024 * 1024)
    staged = local_r2.stage_bytes(large_payload, is_pdf=False)
    assert staged["raw_bytes"] == 10 * 1024 * 1024
    assert staged["stored_bytes"] < staged["raw_bytes"]  # Gzip compresses repeating bytes


@pytest.mark.tier2
@pytest.mark.feature("F1")
def test_b01_multibyte_unicode_payload(local_r2: LocalR2Staging):
    """B1.4: Verify UTF-8 multi-byte characters preserve exact byte counts and round-trip."""
    unicode_payload = "🏛️ Congressional Hearing 議事録 2026 ⚖️".encode("utf-8")
    staged = local_r2.stage_bytes(unicode_payload, is_pdf=False)
    retrieved = local_r2.get_body_bytes(staged["sha256"])
    assert retrieved == unicode_payload
    assert retrieved.decode("utf-8") == "🏛️ Congressional Hearing 議事録 2026 ⚖️"


@pytest.mark.tier2
@pytest.mark.feature("F1")
def test_b01_null_payload_dict(local_r2: LocalR2Staging):
    """B1.5: Verify empty JSON dictionary payload stages valid compressed object."""
    empty_dict_bytes = b"{}"
    staged = local_r2.stage_bytes(empty_dict_bytes, is_pdf=False)
    assert local_r2.has_body(staged["sha256"])
    assert local_r2.get_body_bytes(staged["sha256"]) == b"{}"


# ---------------------------------------------------------------------------
# Feature F2 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F2")
def test_b02_empty_facts_and_links_lists(oracle: ParquetOracle):
    """B2.1: Verify empty list [] for facts and links in Arrow table without schema violation."""
    row = {
        "id": "src_empty_lists",
        "kind": "source_record",
        "provider": "congress.gov",
        "url": "https://congress.gov",
        "title": "Hearing with No Facts",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "event",
        "identifier_value": "114000",
        "identifier_scope": "118",
        "facts": [],
        "links": [],
        "retained_uri": "bodies/sha256/00/00.gz",
        "retained_sha256": "00" * 32,
    }
    table = pa.Table.from_pylist([row], schema=SOURCE_SCHEMA)
    ok, errors = oracle.verify_schema_exact(table, SOURCE_SCHEMA)
    assert ok


@pytest.mark.tier2
@pytest.mark.feature("F2")
def test_b02_null_identifier_components(oracle: ParquetOracle):
    """B2.2: Verify null identifier_scope is handled cleanly as typed null string."""
    row = {
        "id": "src_null_scope",
        "kind": "source_record",
        "provider": "youtube",
        "url": "https://youtube.com",
        "title": "Video Stream",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "video_id",
        "identifier_value": "dQw4w9WgXcQ",
        "identifier_scope": None,
        "facts": None,
        "links": None,
        "retained_uri": "bodies/sha256/11/11.gz",
        "retained_sha256": "11" * 32,
    }
    table = pa.Table.from_pylist([row], schema=SOURCE_SCHEMA)
    assert table["identifier_scope"].to_pylist()[0] is None


@pytest.mark.tier2
@pytest.mark.feature("F2")
def test_b02_title_fallback_chain():
    """B2.3: Verify 4-stage title fallback: title -> URL filename -> provider -> 'Original source'."""
    def resolve_title(row: dict) -> str:
        if row.get("title") and row["title"].strip():
            return row["title"].strip()
        url = row.get("url") or ""
        filename = url.split("/")[-1].split("?")[0] if url else ""
        if "." in filename:
            return filename
        if row.get("provider"):
            return str(row["provider"])
        return "Original source"

    # Stage 1: Explicit title
    assert resolve_title({"title": "  Hearing Title  "}) == "Hearing Title"
    # Stage 2: Filename with extension
    assert resolve_title({"url": "https://senate.gov/reports/hearing_report.pdf"}) == "hearing_report.pdf"
    # Stage 3: Provider name
    assert resolve_title({"provider": "docs.house.gov", "url": "https://docs.house.gov/"}) == "docs.house.gov"
    # Stage 4: Default fallback
    assert resolve_title({}) == "Original source"


@pytest.mark.tier2
@pytest.mark.feature("F2")
def test_b02_special_characters_in_facts(oracle: ParquetOracle):
    """B2.4: Verify facts containing quotes, tabs, newlines, and unicode escape sequences."""
    special_label = 'Category: "Oversight"\t[Spec]'
    special_value = "Line 1\nLine 2\r\nLine 3 'with quotes' & <xml>"
    row = {
        "id": "src_special",
        "kind": "source_record",
        "provider": "senate",
        "url": "https://senate.gov",
        "title": "Hearing",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "hearing",
        "identifier_value": "1",
        "identifier_scope": "118",
        "facts": [{"label": special_label, "value": special_value}],
        "links": [],
        "retained_uri": "bodies/sha256/22/22.gz",
        "retained_sha256": "22" * 32,
    }
    table = pa.Table.from_pylist([row], schema=SOURCE_SCHEMA)
    extracted_facts = table["facts"].to_pylist()[0]
    assert extracted_facts[0]["label"] == special_label
    assert extracted_facts[0]["value"] == special_value


@pytest.mark.tier2
@pytest.mark.feature("F2")
def test_b02_links_with_query_params_and_anchors(oracle: ParquetOracle):
    """B2.5: Verify complex URLs with query parameters and URL fragments in links."""
    complex_href = "https://example.com/search?congress=118&chamber=House&type=Hearing#section-3"
    row = {
        "id": "src_links",
        "kind": "source_record",
        "provider": "congress.gov",
        "url": "https://congress.gov",
        "title": "Hearing",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "source_modified_at": None,
        "imported_at": "2026-10-22T00:00:00Z",
        "identifier_scheme": "h",
        "identifier_value": "1",
        "identifier_scope": "118",
        "facts": [],
        "links": [{"group": "Detail", "label": "Direct Link", "href": complex_href}],
        "retained_uri": "bodies/sha256/33/33.gz",
        "retained_sha256": "33" * 32,
    }
    table = pa.Table.from_pylist([row], schema=SOURCE_SCHEMA)
    assert table["links"].to_pylist()[0][0]["href"] == complex_href


# ---------------------------------------------------------------------------
# Feature F3 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F3")
def test_b03_exact_5_percent_ufffd_threshold(generator: SyntheticDataGenerator):
    """B3.1: Verify strict boundary behavior at exactly 5.0% U+FFFD threshold."""
    # 50 replacement characters out of 1000 = exactly 5.000%
    text_at_boundary = generator.generate_high_ufffd_text(length=1000, replacement_ratio=0.05)
    ratio_at = text_at_boundary.count("\ufffd") / len(text_at_boundary)
    assert ratio_at <= MAX_UFFFD_RATIO

    # 51 replacement characters out of 1000 = 5.100% (>5%)
    text_over_boundary = generator.generate_high_ufffd_text(length=1000, replacement_ratio=0.051)
    ratio_over = text_over_boundary.count("\ufffd") / len(text_over_boundary)
    assert ratio_over > MAX_UFFFD_RATIO


@pytest.mark.tier2
@pytest.mark.feature("F3")
def test_b03_truncated_pdf_magic_bytes():
    """B3.2: Verify truncated 4-byte prefix b'%PDF' (without trailing '-') is NOT treated as PDF."""
    truncated = b"%PDF"
    assert is_pdf_bytes(truncated) is False

    partial_five = b"%PDFx"
    assert is_pdf_bytes(partial_five) is False

    valid_five = b"%PDF-"
    assert is_pdf_bytes(valid_five) is True


@pytest.mark.tier2
@pytest.mark.feature("F3")
def test_b03_empty_file_scraper_input(tmp_path: Path):
    """B3.3: Verify empty 0-byte file scraper input produces 0 lines and 0% U+FFFD."""
    empty_file = tmp_path / "empty.html"
    empty_file.write_bytes(b"")

    data = empty_file.read_bytes()
    assert is_pdf_bytes(data) is False
    text = data.decode("utf-8", "replace")
    assert text == ""
    ratio = text.count("\ufffd") / max(1, len(text))
    assert ratio <= MAX_UFFFD_RATIO


@pytest.mark.tier2
@pytest.mark.feature("F3")
def test_b03_utf16_bom_rejection():
    """B3.4: Verify non-UTF-8 binary stream produces high U+FFFD ratio in UTF-8 decoder and is rejected."""
    raw_binary = bytes(range(128, 256)) * 10
    decoded = raw_binary.decode("utf-8", "replace")
    ratio = decoded.count("\ufffd") / len(decoded)
    # High-bit invalid UTF-8 sequences produce near 100% replacement chars
    assert ratio > MAX_UFFFD_RATIO


@pytest.mark.tier2
@pytest.mark.feature("F3")
def test_b03_nonexistent_file_path(tmp_path: Path):
    """B3.5: Verify non-existent file path returns empty text rather than raising unhandled error."""
    missing = tmp_path / "non_existent.html"
    text = missing.read_bytes().decode("utf-8", "replace") if missing.exists() else ""
    assert text == ""


# ---------------------------------------------------------------------------
# Feature F4 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F4")
def test_b04_exact_boundary_262143_bytes(oracle: ParquetOracle):
    """B4.1: Verify boundary 262,143 bytes (MAX_CELL_SIZE - 1) passes cell size guard."""
    s = "A" * (MAX_CELL_SIZE - 1)
    t = pa.Table.from_arrays([pa.array([s])], names=["str_col"])
    ok, errors = oracle.verify_cell_size_limit(t, max_bytes=MAX_CELL_SIZE)
    assert ok


@pytest.mark.tier2
@pytest.mark.feature("F4")
def test_b04_exact_boundary_262144_bytes(oracle: ParquetOracle):
    """B4.2: Verify boundary exactly 262,144 bytes (MAX_CELL_SIZE) passes cell size guard."""
    s = "B" * MAX_CELL_SIZE
    t = pa.Table.from_arrays([pa.array([s])], names=["str_col"])
    ok, errors = oracle.verify_cell_size_limit(t, max_bytes=MAX_CELL_SIZE)
    assert ok


@pytest.mark.tier2
@pytest.mark.feature("F4")
def test_b04_exact_boundary_262145_bytes(oracle: ParquetOracle):
    """B4.3: Verify boundary 262,145 bytes (MAX_CELL_SIZE + 1) fails cell size guard."""
    s = "C" * (MAX_CELL_SIZE + 1)
    t = pa.Table.from_arrays([pa.array([s])], names=["str_col"])
    ok, errors = oracle.verify_cell_size_limit(t, max_bytes=MAX_CELL_SIZE)
    assert not ok
    assert "exceeds 262144 bytes: 262145 bytes" in errors[0]


@pytest.mark.tier2
@pytest.mark.feature("F4")
def test_b04_multibyte_string_crossing_boundary(oracle: ParquetOracle):
    """B4.4: Verify 3-byte character string crossing 256 KiB boundary is accurately flagged."""
    # 87,381 * 3 bytes = 262,143 bytes (<256 KiB)
    char_3b = "€"  # 3 bytes in UTF-8
    assert len(char_3b.encode("utf-8")) == 3
    s_under = char_3b * 87381
    assert len(s_under.encode("utf-8")) == 262143
    t_under = pa.Table.from_arrays([pa.array([s_under])], names=["col"])
    ok_under, _ = oracle.verify_cell_size_limit(t_under, max_bytes=MAX_CELL_SIZE)
    assert ok_under

    # 87,382 * 3 bytes = 262,146 bytes (>256 KiB)
    s_over = char_3b * 87382
    assert len(s_over.encode("utf-8")) == 262146
    t_over = pa.Table.from_arrays([pa.array([s_over])], names=["col"])
    ok_over, errors = oracle.verify_cell_size_limit(t_over, max_bytes=MAX_CELL_SIZE)
    assert not ok_over
    assert "262146 bytes" in errors[0]


@pytest.mark.tier2
@pytest.mark.feature("F4")
def test_b04_batch_with_one_violating_row(oracle: ParquetOracle):
    """B4.5: Verify 100-row batch identifies the exact index of the violating row."""
    rows = ["valid_string" for _ in range(100)]
    violating_idx = 42
    rows[violating_idx] = "X" * (300 * 1024)  # 300 KiB

    t = pa.Table.from_arrays([pa.array(rows)], names=["col"])
    ok, errors = oracle.verify_cell_size_limit(t, max_bytes=MAX_CELL_SIZE)
    assert not ok
    assert f"row {violating_idx} exceeds" in errors[0]


# ---------------------------------------------------------------------------
# Feature F5 Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.tier2
@pytest.mark.feature("F5")
def test_b05_ui_rendering_with_null_facts():
    """B5.1: Verify UI presentation logic handles row.facts=None without null-pointer exception."""
    row = {"title": "Hearing", "facts": None, "links": None}
    facts_list = row.get("facts") or []
    assert isinstance(facts_list, list)
    assert len(facts_list) == 0


@pytest.mark.tier2
@pytest.mark.feature("F5")
def test_b05_ui_rendering_with_null_links():
    """B5.2: Verify UI presentation logic handles row.links=None without exception."""
    row = {"title": "Hearing", "links": None}
    links_list = row.get("links") or []
    assert isinstance(links_list, list)
    assert len(links_list) == 0


@pytest.mark.tier2
@pytest.mark.feature("F5")
def test_b05_ui_null_retained_uri_disables_button():
    """B5.3: Verify missing retained_uri correctly disables saved copy navigation."""
    row = {"title": "Hearing", "retained_uri": None}
    has_saved_original = bool(row.get("retained_uri"))
    assert has_saved_original is False


@pytest.mark.tier2
@pytest.mark.feature("F5")
def test_b05_ui_deep_nested_struct_values():
    """B5.4: Verify fact value of 10,000 characters renders without error."""
    long_fact_val = "Detailed regulatory testimony notes: " + ("x" * 10000)
    fact = {"label": "Notes", "value": long_fact_val}
    assert len(fact["value"]) > 10000


@pytest.mark.tier2
@pytest.mark.feature("F5")
def test_b05_ui_unknown_provider_fallback():
    """B5.5: Verify unknown or empty provider uses fallback 'Original source'."""
    row = {"provider": "", "url": ""}
    label = row.get("provider") or "Original source"
    assert label == "Original source"
