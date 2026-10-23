"""Document index construction, writing, validation, and staging publication."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import raw_progress as progress
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_staging import WorkingCatalog, write_grouped_indexes
from congress_api.retention.catalog_validation import CatalogReferenceCheck
from congress_api.retention.index.bipartite import (
    combine_document_component,
    normalize_source_row,
    source_groups,
)
from congress_api.retention.index.schemas import SOURCE_SCHEMA, STRINGS


def prepare_document_indexes(rows, schema):
    """Keep exact source rows and create one canonical row per document group."""
    progress.report("group_documents", total=len(rows), unit="source_rows")
    for name in (
        "document_kind",
        "filename_document_kind",
        "document_kind_source",
        "document_family",
        "record_role",
        "source_record_type",
    ):
        if name not in schema.names:
            schema = schema.append(pa.field(name, STRINGS))
    # The parser's public metadata keeps both names for compatibility. These
    # tables need only one normalized publication code, alongside raw spelling.
    # Preserve either column if any row actually carries a distinct reading.
    redundant = "publication_code_code"
    if redundant in schema.names and all(
        not row.get(redundant) or row[redundant] == row.get("publication_type")
        for row in rows
    ):
        schema = pa.schema(
            [field for field in schema if field.name != redundant],
            metadata=schema.metadata,
        )
        for row in rows:
            row.pop(redundant, None)
    for row in rows:
        normalize_source_row(row)
    grouping_schema = pa.schema(
        [
            *SOURCE_SCHEMA,
            ("source_resolved_url", STRINGS),
            ("capture_outcome", STRINGS),
            ("body_format", STRINGS),
        ]
    )
    _, groups = source_groups(pa.Table.from_pylist(rows, schema=grouping_schema))
    documents = []
    for members in progress.track(
        groups, "combine_document_metadata", unit="document_groups"
    ):
        sources = [rows[i] for i in members]
        document = combine_document_component(sources, working=None, mutate_sources=True)
        documents.append(document)
    documents.sort(
        key=lambda row: ((row["filename"] or "").casefold(), row["document_id"])
    )
    catalog_id = uuid4().hex
    original = [
        field
        for field in schema
        if field.name not in {"document_id", "source_id", "format"}
    ]
    fields = [
        *original,
        pa.field("source_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("format", STRINGS),
    ]
    metadata = {
        **(schema.metadata or {}),
        b"format_version": b"10",
        b"catalog_id": catalog_id.encode(),
    }
    source_schema = pa.schema(fields, metadata=metadata)
    document_schema = pa.schema(
        [
            *fields,
            *[(name, STRINGS) for name in ("filenames", "source_urls", "body_keys")],
        ],
        metadata={**metadata, b"format_version": b"5"},
    )
    return rows, source_schema, documents, document_schema


def write_document_indexes(
    destination,
    rows,
    schema,
    *,
    working=None,
    previous=None,
    previous_documents=None,
    reuse_groups=True,
    catalog_id=None,
    preserve_columns=False,
    checkpoint_directory=None,
):
    if working is not None:
        return write_grouped_indexes(
            destination,
            rows,
            schema,
            working=working,
            previous=previous,
            previous_documents=previous_documents,
            reuse_groups=reuse_groups,
            catalog_id=catalog_id,
            preserve_columns=preserve_columns,
            checkpoint_directory=checkpoint_directory,
        )
    with TemporaryDirectory(prefix="document-working-") as directory:
        state = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            return write_grouped_indexes(
                destination,
                rows,
                schema,
                working=state,
                previous=previous,
                previous_documents=previous_documents,
                reuse_groups=reuse_groups,
                catalog_id=catalog_id,
                preserve_columns=preserve_columns,
                checkpoint_directory=checkpoint_directory,
            )
        finally:
            state.close()


def validate_document_indexes(
    source_path, document_path, *, source_rows=None, document_rows=None
):
    """Validate the actual paired files before either destination is replaced."""
    readers = ExitStack()
    try:
        source_file = readers.enter_context(pq.ParquetFile(source_path))
        document_file = readers.enter_context(pq.ParquetFile(document_path))
        check = CatalogReferenceCheck(
            source_file.schema_arrow, document_file.schema_arrow
        )
        if (
            source_rows is not None
            and source_file.metadata.num_rows != source_rows
            or document_rows is not None
            and document_file.metadata.num_rows != document_rows
        ):
            raise ValueError("Document/source index references do not match")
        with check:
            for batch in source_file.iter_batches(
                columns=["source_id", "document_id"], batch_size=4096
            ):
                check.add_sources(batch)
            for batch in document_file.iter_batches(
                columns=["source_id", "document_id"], batch_size=4096
            ):
                check.add_documents(batch)
            check.finish()
    except BaseException as error:
        try:
            readers.close()
        except BaseException as cleanup:
            error.add_note(f"Catalog validation reader cleanup also failed: {cleanup}")
        raise
    else:
        readers.close()


def publish_local_result(root, filename_path, result, snapshot):
    """Select staged files and return durable selected paths, preserving legacy roots."""
    from congress_api.retention.catalog_publication import publish_catalog

    selected = publish_catalog(
        LocalStore(root),
        filename_path,
        filename_path.with_name("documents.parquet"),
        previous=snapshot,
        validation=getattr(result, "validation", None),
    )
    return {
        **result,
        **selected,
        "output": str(root / selected["filenames_key"]),
        "documents_output": str(root / selected["documents_key"]),
    }
