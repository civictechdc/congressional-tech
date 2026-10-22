"""Neutral DocSpec transport shared by application domain packages.

This package owns process custody, loopback readiness, bounded deadlines,
streaming reads, producer-input retention and Arrow schema restoration. It
contains no congressional-tech domain policy.
"""
from .docspec import (
    ARROW_STREAM_MIME,
    QUALIFIED_DOCSPEC_RUNTIME,
    SUPPORTED_PLATFORMS,
    VALID_UPDATE_MERGE_STRATEGIES,
    NativeDatasets,
    application_schema,
    blake3_hex,
    build_export_policy,
    build_export_spec,
    build_ipc_run_spec,
    build_ipc_update_spec,
    build_update_merge_spec,
    cleanup_safe,
    encode_arrow_ipc_stream,
    facet_summary,
    native_storage_schema,
    parse_export_pin,
    producer_input_entry,
    restore_application_schema,
)
from .docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    Host,
    acquire_host,
)

__all__ = [
    'ARROW_STREAM_MIME',
    'QUALIFIED_DOCSPEC_RUNTIME',
    'SUPPORTED_PLATFORMS',
    'VALID_UPDATE_MERGE_STRATEGIES',
    'NativeDatasets',
    'application_schema',
    'blake3_hex',
    'build_export_policy',
    'build_export_spec',
    'build_ipc_run_spec',
    'build_ipc_update_spec',
    'build_update_merge_spec',
    'cleanup_safe',
    'encode_arrow_ipc_stream',
    'facet_summary',
    'native_storage_schema',
    'parse_export_pin',
    'producer_input_entry',
    'restore_application_schema',
    'REQUIRED_LOOPBACK_CAPABILITIES',
    'ArrowResponse',
    'DocSpecFailure',
    'Host',
    'acquire_host',
]
