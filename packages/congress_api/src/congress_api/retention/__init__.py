"""Production source-retention helpers, independent of legacy exploration."""

from congress_api.retention.weekly_tables import (
    WEEKLY_TABLE_DEFINITION,
    WEEKLY_TABLE_KEYS,
    WEEKLY_TABLE_MERGES,
    WEEKLY_TABLE_SCHEMAS,
    WeeklyRetentionTables,
)

__all__ = [
    "WEEKLY_TABLE_DEFINITION",
    "WEEKLY_TABLE_KEYS",
    "WEEKLY_TABLE_MERGES",
    "WEEKLY_TABLE_SCHEMAS",
    "WeeklyRetentionTables",
]
