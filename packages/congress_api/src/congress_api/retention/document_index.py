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


