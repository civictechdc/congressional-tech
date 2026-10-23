"""Guarded viewer publication writes, continuation, read-only verification, and catalog compaction."""
from __future__ import annotations
from typing import Any

from viewer_publication.constants import (
    ACCEPTED_KEY,
    BUCKET,
    LIMITS,
    PREFIX,
    PUBLIC_URL,
    PUBLISHER_VERSION,
    USER_AGENT,
)

_LAZY_EXPORTS: dict[str, str] = {
    'CompressionPolicy': 'viewer_publication.filename_compression',
    'ConditionalManifestPublisher': 'viewer_publication.client',
    'Continuation': 'viewer_publication.continuation',
    'ContinuedPublicationClient': 'viewer_publication.client',
    'DEFAULT_CATALOG_ROW_GROUP_SIZE': 'viewer_publication.filename_exports',
    'DEFAULT_COMPRESSION_POLICY': 'viewer_publication.filename_compression',
    'DEFAULT_READING_ROW_GROUP_SIZE': 'viewer_publication.compact_readings',
    'DEFAULT_REVIEW_ROW_GROUP_SIZE': 'viewer_publication.compact_reviews',
    'DurableJournal': 'viewer_publication.continuation',
    'FORBIDDEN_CATALOG_DUPLICATE_DIGESTS': 'viewer_publication.filename_exports',
    'FORBIDDEN_CATALOG_TOP_LEVEL_COLUMNS': 'viewer_publication.filename_exports',
    'GuardedPublicationClient': 'viewer_publication.client',
    'MissingPublicationJournal': 'viewer_publication.continuation',
    'OCCURRENCE_ROW_GROUP_ROWS': 'viewer_publication.filename_exports',
    'VerifiedTransfer': 'viewer_publication.client',
    'compact_catalog_file': 'viewer_publication.filename_exports',
    'compact_catalog_table': 'viewer_publication.filename_exports',
    'compact_readings': 'viewer_publication.compact_readings',
    'compact_review_rows': 'viewer_publication.compact_reviews',
    'deduplicate_catalog_sha_and_body_keys': 'viewer_publication.filename_exports',
    'deduplicate_reading_table': 'viewer_publication.compact_readings',
    'project_source_slice': 'viewer_publication.filename_exports',
    'prune_catalog_null_columns': 'viewer_publication.filename_exports',
    'prune_catalog_top_level_source_columns': 'viewer_publication.filename_exports',
    'prune_review_table': 'viewer_publication.compact_reviews',
    'publish_manifest_pointer': 'viewer_publication.client',
    'require_publication_client': 'viewer_publication.client',
    'scalarize_catalog_columns': 'viewer_publication.filename_exports',
    'sha256': 'viewer_publication.continuation',
    'sort_reading_table': 'viewer_publication.compact_readings',
    'validate_compression': 'viewer_publication.filename_compression',
}

__all__ = [
    'ACCEPTED_KEY',
    'BUCKET',
    'LIMITS',
    'PREFIX',
    'PUBLIC_URL',
    'PUBLISHER_VERSION',
    'USER_AGENT',
    *_LAZY_EXPORTS.keys(),
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        target_mod = _LAZY_EXPORTS[name]
        module = __import__(target_mod, fromlist=[name])
        submod_name = target_mod.split('.')[-1]
        if submod_name in _LAZY_EXPORTS and hasattr(module, submod_name):
            globals()[submod_name] = getattr(module, submod_name)
        val = getattr(module, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
