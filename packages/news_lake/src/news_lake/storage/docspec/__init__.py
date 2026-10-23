"""DocSpec storage engine subpackage for news_lake.

Decomposed from the monolithic docspec_backend.py (3,928 LOC) under ct-0bce:
- schema.py: Arrow schemas, JSON-to-Arrow conversions, merge specs, C5 export policy.
- client.py: DocSpecClient and DocSpecFailure adapters.
- compaction.py: Shared _DocSpecDatasetManager base class and Parquet compaction helpers.
- lake.py: DocSpecLake coordinator, transaction management, and Iceberg/Arrow ingestion.
- incremental.py: Incremental relational bridge derivation and delta propagation.
- views.py: DocSpecNewsViews, native chained join/aggregate pipelines.
- export.py: C5-authorized native Parquet export execution.
"""
from news_lake.storage.docspec.client import DocSpecClient, DocSpecFailure
from news_lake.storage.docspec.compaction import _DocSpecDatasetManager
from news_lake.storage.docspec.export import export_authorized
from news_lake.storage.docspec.incremental import IncrementalBridgeMixin
from news_lake.storage.docspec.lake import DocSpecLake
from news_lake.storage.docspec.schema import (
    APPEND_UPDATE_KEYS,
    AppendCollisionError,
    DEFAULT_COMPACT_FILE_THRESHOLD,
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    DEFINITION,
    application_schema,
    build_c5_export_policy,
    content_digest,
    dataset_id_for,
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
from news_lake.storage.docspec.views import DocSpecNewsViews

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
