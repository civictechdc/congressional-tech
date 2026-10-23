"""Backward-compatibility shim for congress_api.retention.document_index.

All symbols have moved to focused submodules under congress_api.retention.index.
"""
import sys
import types
from congress_api.retention.index import *  # noqa: F401, F403
from congress_api.retention.index import __all__
from congress_api.retention import raw_progress as progress
from congress_api.retention.index import (
    bipartite,
    builder,
    document_sources,
    lifecycle,
    metadata,
    records,
    schemas,
    sources,
)

# Re-exports for historical root tests and source_observations
from house_naming import Engine, __version__, document_families
from house_naming.values import filename_metadata as flatten
from house_naming.extraction import QUERY
import pyarrow.parquet as pq
from congress_api.parsers.document_links import http_url, feed_link
from congress_api.retention.document_evidence import (
    evidence_fingerprint,
    read_retained_body,
    body_evidence_key,
    cached_body_fields,
    enrich_sources,
    enrich_document_covers,
    response_failed,
    apply_response_role,
)

_SUBMODULES = (
    bipartite,
    builder,
    document_sources,
    lifecycle,
    metadata,
    records,
    schemas,
    sources,
)


class _CompatibilityShim(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for submod in _SUBMODULES:
            if hasattr(submod, name):
                setattr(submod, name, value)


sys.modules[__name__].__class__ = _CompatibilityShim


