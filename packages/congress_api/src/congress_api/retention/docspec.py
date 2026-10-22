"""Compatibility shim: the DocSpec transport now lives in ``docspec_client``.

Archive callers keep this import path. Domain policy (catalog preparation,
capacity receipts, retention planning) remains in ``native_capacity`` and the
archive packages.
"""
from docspec_client.docspec import (
    QUALIFIED_DOCSPEC_RUNTIME,
    SUPPORTED_PLATFORMS,
    AggregateSpec,
    ConnectedComponentsTransform,
    ConnectedEdgeSpec,
    NativeDatasets,
    PartitionFieldSpec,
    PartitionSpec,
    PartitionTransformSpec,
    SortColumn,
    SortDirection,
    UpdateMergeSpec,
    UpdateMergeStrategy,
    apply_update_merge_spec,
    cleanup_safe,
    native_storage_schema,
    producer_input_entry,
)
from docspec_client.docspec_host import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    ArrowResponse,
    DocSpecFailure,
    acquire_host,
)

__all__ = [
    'QUALIFIED_DOCSPEC_RUNTIME',
    'SUPPORTED_PLATFORMS',
    'AggregateSpec',
    'ConnectedComponentsTransform',
    'ConnectedEdgeSpec',
    'NativeDatasets',
    'PartitionFieldSpec',
    'PartitionSpec',
    'PartitionTransformSpec',
    'SortColumn',
    'SortDirection',
    'UpdateMergeSpec',
    'UpdateMergeStrategy',
    'apply_update_merge_spec',
    'cleanup_safe',
    'native_storage_schema',
    'producer_input_entry',
    'REQUIRED_LOOPBACK_CAPABILITIES',
    'ArrowResponse',
    'DocSpecFailure',
    'acquire_host',
]
