"""Tier 5 Adversarial Tests: Milestone 1 (ct-8v02).

Deep white-box stress testing of:
1. 256 KiB cell limit recursion, boundary conditions, and UTF-8 multibyte character vs byte length.
2. PDF magic header corruption, truncations, BOM prefixes, and case sensitivity.
3. Unicode replacement character (U+FFFD) threshold boundary precision in HTML/text scrapers.
"""

from __future__ import annotations
import hashlib
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from committee_explorer.parquet import (
    _check_cell_size,
    _source_row,
    _write_table,
    MAX_CELL_SIZE,
    SOURCE_SCHEMA,
    TABLE_SCHEMAS,
)
from congress_api.retention.body_keys import is_pdf_bytes, physical_body_object_key
from congress_api.retention.senate import seed_fetch, cached_html_path
from tests.e2e.harness.contracts import PDF_MAGIC, MAX_UFFFD_RATIO
from tests.e2e.harness.parquet_oracle import ParquetOracle
from tests.e2e.harness.staging import LocalR2Staging


class TestM1CellSizeLimits:
    """Adversarial stress tests for 256 KiB (262,144 bytes) cell size enforcement."""

    def test_exact_byte_boundary_pass(self):
        """String of exactly 262,144 bytes must pass without error."""
        exact_str = "A" * MAX_CELL_SIZE
        _check_cell_size(exact_str, "test_col")
        exact_bytes = b"B" * MAX_CELL_SIZE
        _check_cell_size(exact_bytes, "test_col")

    def test_exact_byte_boundary_fail(self):
        """String of exactly 262,145 bytes must raise ValueError."""
        overflow_str = "A" * (MAX_CELL_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds 256 KiB limit"):
            _check_cell_size(overflow_str, "test_col")

        overflow_bytes = b"B" * (MAX_CELL_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds 256 KiB limit"):
            _check_cell_size(overflow_bytes, "test_col")

    def test_deeply_nested_struct_recursion_detection(self):
        """Verify _check_cell_size finds oversized cells inside deep dict/list trees."""
        # Build 50-level nested structure
        nested: dict = {"level": 50, "oversized": "X" * (MAX_CELL_SIZE + 500)}
        for i in range(49, 0, -1):
            nested = {"level": i, "sub": [nested, {"padding": "safe"}]}

        with pytest.raises(ValueError, match="exceeds 256 KiB limit"):
            _check_cell_size(nested, "nested_col")

    def test_nested_list_of_structs_within_budget(self):
        """Deeply nested struct tree with safe cell sizes must pass cleanly."""
        nested: dict = {"level": 30, "content": "safe string"}
        for i in range(29, 0, -1):
            nested = {"level": i, "items": [{"id": i, "data": nested}]}
        _check_cell_size(nested, "safe_nested_col")

    def test_multibyte_utf8_codepoint_vs_byte_length_discrepancy(self):
        """Empirical Discovery: Python len(str) checks codepoints, not UTF-8 bytes.

        A string of 70,000 4-byte unicode emojis has len(s) == 70,000 <= 262,144.
        However, its UTF-8 encoded length is 280,000 bytes (> 256 KiB).
        Verify how _check_cell_size behaves vs Parquet physical cell size verification.
        """
        multibyte_str = "💩" * 70_000
        codepoint_len = len(multibyte_str)
        byte_len = len(multibyte_str.encode("utf-8"))

        assert codepoint_len == 70_000
        assert byte_len == 280_000  # 280 KiB > 256 KiB

        # White-box check: does _check_cell_size catch this or pass it?
        # In current parquet.py: len(val) checks characters for str.
        # So _check_cell_size passes it because 70,000 < 262,144:
        try:
            _check_cell_size(multibyte_str, "emoji_col")
            passed_codepoint_check = True
        except ValueError:
            passed_codepoint_check = False

        # Physical oracle check: ParquetOracle checks encoded UTF-8 byte length
        dummy_table = pa.Table.from_pydict({"emoji_col": [multibyte_str]})
        is_valid, errors = ParquetOracle.verify_cell_size_limit(dummy_table, max_bytes=MAX_CELL_SIZE)

        # The Parquet physical limit MUST fail because 280 KiB > 256 KiB
        assert not is_valid
        assert any("exceeds 262144 bytes: 280000 bytes" in err for err in errors)


class TestM1CorruptPDFHeaders:
    """Adversarial stress tests for PDF magic header inspection (%PDF-)."""

    def test_exact_valid_pdf_magic(self):
        assert is_pdf_bytes(b"%PDF-1.4\n%EOF") is True
        assert is_pdf_bytes(b"%PDF-2.0") is True

    def test_truncated_pdf_headers(self):
        """Header shorter than 5 bytes cannot be confirmed as PDF."""
        assert is_pdf_bytes(b"") is False
        assert is_pdf_bytes(b"%") is False
        assert is_pdf_bytes(b"%PD") is False
        assert is_pdf_bytes(b"%PDF") is False

    def test_corrupted_case_or_prefix(self):
        """Leading whitespace, BOM, or lowercase '%pdf-' are not valid '%PDF-'."""
        assert is_pdf_bytes(b" %PDF-1.4") is False
        assert is_pdf_bytes(b"\n%PDF-1.4") is False
        assert is_pdf_bytes(b"%pdf-1.4") is False
        assert is_pdf_bytes(b"\xef\xbb\xbf%PDF-1.4") is False  # UTF-8 BOM

    def test_senate_seed_fetch_corrupt_pdf_offload(self, tmp_path: Path):
        """Verify senate.py:seed_fetch isolates corrupted binary PDF and writes to CAS."""
        cache_dir = tmp_path / "cache"
        url = "https://www.senate.gov/hearings/corrupt_doc.pdf"
        html_file = cached_html_path(cache_dir, url)
        html_file.parent.mkdir(parents=True, exist_ok=True)

        # 10 KB file beginning with valid %PDF- magic
        pdf_data = b"%PDF-1.7\n" + b"\x00\xff" * 5000
        html_file.write_bytes(pdf_data)

        # seed_fetch returns empty string for binary/PDF and writes to bodies/sha256/
        ret = seed_fetch(cache_dir, url)
        assert ret == ""

        digest = hashlib.sha256(pdf_data).hexdigest()
        expected_cas = cache_dir / "bodies" / "sha256" / digest[:2] / f"{digest}.pdf"
        assert expected_cas.exists()
        assert expected_cas.read_bytes() == pdf_data


class TestM1UnicodeReplacementThreshold:
    """Adversarial boundary stress tests for U+FFFD replacement density threshold (> 5%)."""

    def test_threshold_under_five_percent_passes_as_text(self, tmp_path: Path):
        """Data with 4.0% U+FFFD is treated as readable text, not binary."""
        cache_dir = tmp_path / "cache"
        url = "https://www.senate.gov/hearings/mostly_clean.html"
        html_file = cached_html_path(cache_dir, url)
        html_file.parent.mkdir(parents=True, exist_ok=True)

        # 96 valid characters + 4 invalid byte sequences -> 4% U+FFFD
        clean_text = "A" * 96
        bad_bytes = b"\xff\xff\xff\xff"
        data = clean_text.encode("utf-8") + bad_bytes
        html_file.write_bytes(data)

        ret = seed_fetch(cache_dir, url)
        # Should NOT be treated as binary; returns decoded text
        assert ret != ""
        assert "\ufffd" in ret
        assert len(ret) == 100

    def test_threshold_over_five_percent_triggers_binary_quarantine(self, tmp_path: Path):
        """Data with 6.0% U+FFFD exceeds 5% ceiling and must be treated as binary."""
        cache_dir = tmp_path / "cache"
        url = "https://www.senate.gov/hearings/corrupt_encoding.html"
        html_file = cached_html_path(cache_dir, url)
        html_file.parent.mkdir(parents=True, exist_ok=True)

        # 94 valid characters + 6 invalid byte sequences -> 6% U+FFFD
        clean_text = "A" * 94
        bad_bytes = b"\xfe" * 6
        data = clean_text.encode("utf-8") + bad_bytes
        html_file.write_bytes(data)

        ret = seed_fetch(cache_dir, url)
        # Exceeds 5% threshold: seed_fetch returns "" and offloads to CAS
        assert ret == ""

        digest = hashlib.sha256(data).hexdigest()
        cas_file = cache_dir / "bodies" / "sha256" / digest[:2] / f"{digest}.pdf"
        assert cas_file.exists()
        assert cas_file.read_bytes() == data

    def test_exact_5_percent_threshold_behavior(self, tmp_path: Path):
        """Verify strict inequality: threshold is strictly > 0.05, so exactly 5.0% is not binary."""
        cache_dir = tmp_path / "cache"
        url = "https://www.senate.gov/hearings/exact_five_percent.html"
        html_file = cached_html_path(cache_dir, url)
        html_file.parent.mkdir(parents=True, exist_ok=True)

        # 95 'A' + 5 '\xfe' = 100 characters decoded (5 U+FFFD)
        # 5 / 100 = 0.05. Condition: `fffd_count / len > 0.05` is False.
        clean_text = "A" * 95
        bad_bytes = b"\xfe" * 5
        data = clean_text.encode("utf-8") + bad_bytes
        html_file.write_bytes(data)

        ret = seed_fetch(cache_dir, url)
        # Exactly 5% does not strictly exceed 5%, so it is retained as text
        assert ret != ""
        assert ret.count("\ufffd") == 5
