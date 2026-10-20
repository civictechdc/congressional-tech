"""Iceberg storage boundary: catalog, mapping, coordinator, releases, control.

Consumes the contract module for shape validation, routing, and corpus
semantics; storage never re-derives record rules.
"""
import news_lake.storage.arrow_patch  # noqa: F401  (seam; see its docstring)
from news_lake.storage.catalog import Lake
from news_lake.storage.control import ControlError, ControlStore, FencedError
from news_lake.storage.coordinator import CommitError, CrashInjection, Coordinator, Faults
from news_lake.storage.releases import ReleaseError, publish_release, read_release, retire_release

__all__ = [
    'CommitError',
    'ControlError',
    'ControlStore',
    'CrashInjection',
    'FencedError',
    'Faults',
    'Lake',
    'ReleaseError',
    'publish_release',
    'read_release',
    'retire_release',
]
