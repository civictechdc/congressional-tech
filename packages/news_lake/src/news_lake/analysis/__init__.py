"""Analysis: the baseline clusterer, labels, C5 export, C8 selection, C9 views."""
from news_lake.analysis.bridges import (
    ENTITY_ROOTS_SCHEMA,
    SELECTED_MENTIONS_SCHEMA,
    SURVIVOR_ITEMS_SCHEMA,
    entity_roots_arrow,
    entity_roots_rows,
    selected_mentions_arrow,
    selected_mentions_rows,
    survivor_items_arrow,
    survivor_items_rows,
)
from news_lake.analysis.cluster import cluster, normalize_text, text_group_key
from news_lake.analysis.export import export_release
from news_lake.analysis.labels import classify
from news_lake.analysis.selection import select_runs
from news_lake.analysis.views import coverage_daily, politician_articles

__all__ = [
    'ENTITY_ROOTS_SCHEMA',
    'SELECTED_MENTIONS_SCHEMA',
    'SURVIVOR_ITEMS_SCHEMA',
    'classify',
    'cluster',
    'coverage_daily',
    'entity_roots_arrow',
    'entity_roots_rows',
    'export_release',
    'normalize_text',
    'politician_articles',
    'select_runs',
    'selected_mentions_arrow',
    'selected_mentions_rows',
    'survivor_items_arrow',
    'survivor_items_rows',
    'text_group_key',
]
