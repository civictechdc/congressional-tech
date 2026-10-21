"""Neutral DocSpec transport shared by application domain packages.

This package owns process custody, loopback readiness, bounded deadlines,
streaming reads, producer-input retention and Arrow schema restoration. It
contains no congressional-tech domain policy.
"""
from .docspec import (
    QUALIFIED_DOCSPEC_RUNTIME,
    SUPPORTED_PLATFORMS,
    NativeDatasets,
    cleanup_safe,
    native_storage_schema,
    producer_input_entry,
)
from .docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    Host,
    acquire_host,
)

__all__ = [
    'QUALIFIED_DOCSPEC_RUNTIME',
    'SUPPORTED_PLATFORMS',
    'NativeDatasets',
    'cleanup_safe',
    'native_storage_schema',
    'producer_input_entry',
    'REQUIRED_LOOPBACK_CAPABILITIES',
    'ArrowResponse',
    'DocSpecFailure',
    'Host',
    'acquire_host',
]
