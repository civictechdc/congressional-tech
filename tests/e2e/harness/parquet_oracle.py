"""Opaque-box Parquet Table Oracle and Verification Utilities.

Performs deterministic inspection of Parquet schema contracts, physical layouts,
cell size ceilings, footer overhead, and compression codecs.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .contracts import MAX_CELL_SIZE


class ParquetOracle:
    """Inspector and validator for Parquet tables and files."""

    @staticmethod
    def load_table(source: Path | str | pa.Table) -> pa.Table:
        if isinstance(source, pa.Table):
            return source
        return pq.read_table(source)

    @staticmethod
    def verify_schema_subset(
        table_or_path: Path | str | pa.Table,
        expected_schema: pa.Schema,
    ) -> tuple[bool, list[str]]:
        """Verify table contains all fields from expected_schema with matching types."""
        table = ParquetOracle.load_table(table_or_path)
        errors: list[str] = []
        for field in expected_schema:
            idx = table.schema.get_field_index(field.name)
            if idx == -1:
                errors.append(f"Missing required field: {field.name}")
                continue
            actual_field = table.schema.field(idx)
            # Check type compatibility
            if not actual_field.type.equals(field.type):
                errors.append(
                    f"Field {field.name} type mismatch: expected {field.type}, got {actual_field.type}"
                )
        return (len(errors) == 0, errors)

    @staticmethod
    def verify_schema_exact(
        table_or_path: Path | str | pa.Table,
        expected_schema: pa.Schema,
    ) -> tuple[bool, list[str]]:
        """Verify table matches expected_schema exactly in field order and names."""
        table = ParquetOracle.load_table(table_or_path)
        errors: list[str] = []
        actual_names = table.schema.names
        expected_names = expected_schema.names
        if actual_names != expected_names:
            errors.append(f"Field names mismatch: expected {expected_names}, got {actual_names}")
        for name in expected_names:
            if name in table.schema.names:
                exp_t = expected_schema.field(name).type
                act_t = table.schema.field(name).type
                if not act_t.equals(exp_t):
                    errors.append(f"Field {name} type mismatch: expected {exp_t}, got {act_t}")
        return (len(errors) == 0, errors)

    @staticmethod
    def verify_column_absence(
        table_or_path: Path | str | pa.Table,
        forbidden_columns: set[str] | frozenset[str],
    ) -> tuple[bool, list[str]]:
        """Verify that none of the forbidden columns are present in the table schema."""
        table = ParquetOracle.load_table(table_or_path)
        found = forbidden_columns.intersection(set(table.schema.names))
        if found:
            return (False, [f"Forbidden column(s) present in schema: {sorted(found)}"])
        return (True, [])

    @staticmethod
    def verify_cell_size_limit(
        table_or_path: Path | str | pa.Table,
        max_bytes: int = MAX_CELL_SIZE,
    ) -> tuple[bool, list[str]]:
        """Verify that no string or binary cell exceeds max_bytes (default 256 KiB)."""
        table = ParquetOracle.load_table(table_or_path)
        errors: list[str] = []
        for col_name in table.column_names:
            col = table[col_name]
            col_type = col.type
            if pa.types.is_string(col_type) or pa.types.is_large_string(col_type):
                for chunk_idx, chunk in enumerate(col.chunks):
                    for row_idx, val in enumerate(chunk):
                        if val.is_valid:
                            raw_s = val.as_py()
                            if isinstance(raw_s, str):
                                byte_len = len(raw_s.encode("utf-8"))
                                if byte_len > max_bytes:
                                    errors.append(
                                        f"Column {col_name} row {row_idx} exceeds {max_bytes} bytes: "
                                        f"{byte_len} bytes (value preview: {raw_s[:60]}...)"
                                    )
                                    return (False, errors)
            elif pa.types.is_binary(col_type) or pa.types.is_large_binary(col_type):
                for chunk_idx, chunk in enumerate(col.chunks):
                    for row_idx, val in enumerate(chunk):
                        if val.is_valid:
                            b_len = len(val.as_buffer())
                            if b_len > max_bytes:
                                errors.append(
                                    f"Column {col_name} binary row {row_idx} exceeds {max_bytes} bytes: {b_len} bytes"
                                )
                                return (False, errors)
        return (True, [])

    @staticmethod
    def verify_row_group_metadata(
        parquet_path: Path | str,
        *,
        min_rg_rows: int | None = None,
        max_rg_rows: int | None = None,
        max_footer_ratio: float | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify Parquet physical row group layout and footer size ratio."""
        path = Path(parquet_path)
        if not path.exists():
            return (False, [f"File not found: {path}"])

        metadata = pq.read_metadata(path)
        errors: list[str] = []
        file_bytes = path.stat().st_size
        num_row_groups = metadata.num_row_groups
        total_rows = metadata.num_rows

        for rg_idx in range(num_row_groups):
            rg = metadata.row_group(rg_idx)
            # Last row group can have fewer rows than min_rg_rows
            if min_rg_rows is not None and rg_idx < num_row_groups - 1:
                if rg.num_rows < min_rg_rows:
                    errors.append(
                        f"Row group {rg_idx} has {rg.num_rows} rows, below minimum {min_rg_rows}"
                    )
            if max_rg_rows is not None:
                if rg.num_rows > max_rg_rows:
                    errors.append(
                        f"Row group {rg_idx} has {rg.num_rows} rows, exceeding maximum {max_rg_rows}"
                    )

        if max_footer_ratio is not None and file_bytes > 0:
            # Estimate metadata bytes from row group offsets or serialize metadata
            metadata_bytes = metadata.serialized_size
            footer_pct = (metadata_bytes / file_bytes) * 100.0
            if footer_pct > max_footer_ratio:
                errors.append(
                    f"Parquet footer overhead is {footer_pct:.2f}% ({metadata_bytes} bytes), "
                    f"exceeding ceiling {max_footer_ratio}%"
                )

        return (len(errors) == 0, errors)

    @staticmethod
    def verify_no_null_keys(
        table_or_path: Path | str | pa.Table,
        key_columns: list[str] | tuple[str, ...],
    ) -> tuple[bool, list[str]]:
        """Verify key columns contain 0 null and 0 empty string values."""
        table = ParquetOracle.load_table(table_or_path)
        errors: list[str] = []
        for col_name in key_columns:
            if col_name not in table.column_names:
                errors.append(f"Key column {col_name} not found in table")
                continue
            col = table[col_name]
            null_count = col.null_count
            if null_count > 0:
                errors.append(f"Key column {col_name} has {null_count} NULL values")
            if pa.types.is_string(col.type):
                empty_count = sum(1 for v in col.to_pylist() if v == "")
                if empty_count > 0:
                    errors.append(f"Key column {col_name} has {empty_count} empty string values")
        return (len(errors) == 0, errors)

    @staticmethod
    def verify_unique_keys(
        table_or_path: Path | str | pa.Table,
        key_columns: list[str] | tuple[str, ...],
    ) -> tuple[bool, list[str]]:
        """Verify compound primary key has zero duplicate rows."""
        table = ParquetOracle.load_table(table_or_path)
        cols = [table[c].to_pylist() for c in key_columns]
        seen: set[tuple[Any, ...]] = set()
        duplicates = 0
        for row in zip(*cols):
            if row in seen:
                duplicates += 1
            else:
                seen.add(row)
        if duplicates > 0:
            return (False, [f"Found {duplicates} duplicate key tuples for key {key_columns}"])
        return (True, [])
