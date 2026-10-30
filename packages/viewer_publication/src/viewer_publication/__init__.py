"""Archive release publication, conditional pointer flips, read-only verification, and catalog compaction."""
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
    'ConditionalManifestPublisher': 'viewer_publication.client',
    'DEFAULT_READING_ROW_GROUP_SIZE': 'viewer_publication.compact_readings',
    'DEFAULT_REVIEW_ROW_GROUP_SIZE': 'viewer_publication.compact_reviews',
    'VerifiedTransfer': 'viewer_publication.client',
    'compact_readings': 'viewer_publication.compact_readings',
    'compact_review_rows': 'viewer_publication.compact_reviews',
    'deduplicate_reading_table': 'viewer_publication.compact_readings',
    'prune_review_table': 'viewer_publication.compact_reviews',
    'publish_manifest_pointer': 'viewer_publication.client',
    'require_publication_client': 'viewer_publication.client',
    'sort_reading_table': 'viewer_publication.compact_readings',
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
