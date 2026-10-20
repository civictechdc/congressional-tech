"""Adapters turn fetched provider payloads into contract-valid records.

They import the contract (shape validation, shared namespaces) and never
hand-build Iceberg rows. Live HTTP wiring is deferred: adapters consume
FetchOutcome objects and fixture bytes.
"""
from news_lake.adapters.common import (
    FetchOutcome,
    build_capture,
    item_id_for,
    outlet_for_domain,
)
from news_lake.adapters.cursors import Page, PageDrain
from news_lake.adapters.gdelt import GdeltAdapter
from news_lake.adapters.mediacloud import MediaCloudAdapter
from news_lake.adapters.rss import RssAdapter, extract_text, publication_from_feed

__all__ = [
    'FetchOutcome',
    'GdeltAdapter',
    'MediaCloudAdapter',
    'Page',
    'PageDrain',
    'RssAdapter',
    'build_capture',
    'extract_text',
    'item_id_for',
    'outlet_for_domain',
    'publication_from_feed',
]
