"""Political news lake: record contract, Iceberg storage boundary, offline
adapters, identity decisions, and release-scoped analysis views."""
from news_lake.analysis import (
    classify,
    coverage_daily,
    export_release,
    politician_articles,
    select_runs,
)
from news_lake.contract import check_corpus, parse_jsonl, validate_shape
from news_lake.identity import apply_decisions
from news_lake.storage import DocSpecClient, DocSpecLake, DocSpecNewsViews

__all__ = [
    'DocSpecClient',
    'DocSpecLake',
    'DocSpecNewsViews',
    'apply_decisions',
    'check_corpus',
    'classify',
    'coverage_daily',
    'export_release',
    'parse_jsonl',
    'politician_articles',
    'select_runs',
    'validate_shape',
]
