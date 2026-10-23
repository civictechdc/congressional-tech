"""Test harness for opaque-box E2E testing of Epic ct-4t6s."""
from .contracts import (
    SOURCE_SCHEMA,
    BROWSER_TABLE_SCHEMAS,
    WEEKLY_TABLE_SCHEMAS,
    RAW_ARCHIVE_SCHEMAS,
    CANONICAL_CATALOG_SCHEMAS,
    MAX_CELL_SIZE,
    PDF_MAGIC,
    MAX_UFFFD_RATIO,
)
from .staging import LocalR2Staging
from .parquet_oracle import ParquetOracle
from .data_generators import SyntheticDataGenerator

__all__ = [
    "SOURCE_SCHEMA",
    "BROWSER_TABLE_SCHEMAS",
    "WEEKLY_TABLE_SCHEMAS",
    "RAW_ARCHIVE_SCHEMAS",
    "CANONICAL_CATALOG_SCHEMAS",
    "MAX_CELL_SIZE",
    "PDF_MAGIC",
    "MAX_UFFFD_RATIO",
    "LocalR2Staging",
    "ParquetOracle",
    "SyntheticDataGenerator",
]
