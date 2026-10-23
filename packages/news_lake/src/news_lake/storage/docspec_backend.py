"""Backward-compatibility shim for news_lake.storage.docspec.

Under CS300 Capstone Audit (ct-0bce), the 3,928-LOC docspec_backend.py has been
decomposed into the structured subpackage `news_lake.storage.docspec`:
- `news_lake.storage.docspec.schema`
- `news_lake.storage.docspec.client`
- `news_lake.storage.docspec.compaction`
- `news_lake.storage.docspec.lake`
- `news_lake.storage.docspec.incremental`
- `news_lake.storage.docspec.views`
- `news_lake.storage.docspec.export`

This module re-exports all public symbols to preserve backward compatibility
for existing consumers and test suites.
"""
from news_lake.storage.docspec import (
    APPEND_UPDATE_KEYS,
    AppendCollisionError,
    DEFAULT_COMPACT_FILE_THRESHOLD,
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    DEFINITION,
    DocSpecClient,
    DocSpecFailure,
    DocSpecLake,
    DocSpecNewsViews,
    IncrementalBridgeMixin,
    _DocSpecDatasetManager,
    application_schema,
    build_c5_export_policy,
    content_digest,
    dataset_id_for,
    export_authorized,
    kind_arrow_schema,
    merge_upsert_batch,
    native_storage_schema,
    pin_group,
    pin_metadata,
    pin_metadata_path,
    pin_objects,
    pin_rows,
    pin_snapshot,
    pin_version,
    records_to_arrow,
    restore_application_schema,
    sanitize_id,
    table_records,
    upsert_merge_spec_for_kind,
    version_ref,
)

__all__ = [
    'APPEND_UPDATE_KEYS',
    'AppendCollisionError',
    'DEFAULT_COMPACT_FILE_THRESHOLD',
    'DEFAULT_COMPACT_TARGET_FILE_BYTES',
    'DEFAULT_LIFECYCLE_COMPACT_INTERVAL',
    'DEFINITION',
    'DocSpecClient',
    'DocSpecFailure',
    'DocSpecLake',
    'DocSpecNewsViews',
    'IncrementalBridgeMixin',
    '_DocSpecDatasetManager',
    'application_schema',
    'build_c5_export_policy',
    'content_digest',
    'dataset_id_for',
    'export_authorized',
    'kind_arrow_schema',
    'merge_upsert_batch',
    'native_storage_schema',
    'pin_group',
    'pin_metadata',
    'pin_metadata_path',
    'pin_objects',
    'pin_rows',
    'pin_snapshot',
    'pin_version',
    'records_to_arrow',
    'restore_application_schema',
    'sanitize_id',
    'table_records',
    'upsert_merge_spec_for_kind',
    'version_ref',
]
