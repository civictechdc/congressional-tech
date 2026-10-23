"""Filename metadata writing, build orchestration, reindexing, and lifecycle execution."""
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, nullcontext
from itertools import islice
import json
from multiprocessing import get_context
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import pyarrow as pa
import pyarrow.parquet as pq

from house_naming import __version__
from congress_api.retention import raw_progress as progress
from congress_api.retention.capture_metadata import restore_body_results, restore_readings
from congress_api.retention.catalog_cache import LocalStore, result_checkpoint
import congress_api.retention.catalog_publication as catalog_publication
from congress_api.retention.catalog_staging import ParquetRows, WorkingCatalog
from congress_api.retention.catalog_validation import CatalogBuildResult
from congress_api.retention.document_evidence import (
    apply_response_role,
    body_evidence_key,
    cached_body_fields,
    enrich_document_covers,
    enrich_sources,
    evidence_fingerprint,
    read_retained_body,
)
from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
from congress_api.retention.index.builder import publish_local_result, write_document_indexes
from congress_api.retention.index.document_sources import DocumentSources
from congress_api.retention.index.metadata import (
    collect_names,
    parser_fingerprint,
    refresh_response_metadata,
    validated_body_readings,
)
from congress_api.retention.index.records import read_document_sources
from congress_api.retention.index.schemas import (
    AVAILABILITY_FIELDS,
    BODY_FIELDS,
    COVER_FIELDS,
    EVIDENCE_FIELDS,
    FAMILIES,
    SOURCE_CONTEXT_FIELDS,
    SOURCE_SCHEMA,
    compact,
    extract,
    fill_document_kind,
    metadata_type,
    restore_filename_kind,
)


def write_filename_metadata(
    root,
    source_rows,
    *,
    workers=4,
    previous=None,
    metadata=None,
    read_body=None,
    oversized_bodies=(),
    cache_store=None,
    reuse_results=True,
    inspect_bodies=False,
    working=None,
    previous_documents=None,
    publication_snapshot=None,
    output_root=None,
    body_readings=(),
    retained_body_readings=None,
):
    """Interpret supplied source rows; optional body readings are explicit overrides."""
    body_readings = validated_body_readings(body_readings)
    if working is None:
        with (
            TemporaryDirectory(prefix="filename-working-") as directory,
            ExitStack() as owners,
        ):
            working = WorkingCatalog(Path(directory) / "working.sqlite")
            try:
                local_store = LocalStore(root)
                snapshot = publication_snapshot or owners.enter_context(
                    catalog_publication.read_catalog(local_store)
                )
                staged = Path(directory) / "output"
                (staged / "indexes").mkdir(parents=True)
                result = write_filename_metadata(
                    root,
                    source_rows,
                    workers=workers,
                    previous=previous,
                    metadata=metadata,
                    read_body=read_body,
                    oversized_bodies=oversized_bodies,
                    cache_store=cache_store,
                    reuse_results=reuse_results,
                    inspect_bodies=inspect_bodies,
                    working=working,
                    previous_documents=previous_documents,
                    output_root=staged,
                    body_readings=body_readings.values(),
                    retained_body_readings=retained_body_readings,
                )
                return publish_local_result(
                    root, staged / "indexes/document-filenames.parquet", result, snapshot
                )
            finally:
                working.close()
    started = time.monotonic()
    previous_schema = (
        (
            previous.schema_arrow
            if isinstance(previous, pq.ParquetFile)
            else previous.schema
        )
        if previous is not None
        else None
    )

    def previous_batches(columns=None):
        in_pytest = "PYTEST_CURRENT_TEST" in os.environ
        bsize = 256 if in_pytest else 16384
        if isinstance(previous, pq.ParquetFile):
            return previous.iter_batches(
                columns=columns, batch_size=bsize, use_threads=not in_pytest
            )
        return (previous.select(columns) if columns else previous).to_batches(
            max_chunksize=bsize
        )

    progress.report("prepare_filename_inputs")
    if (root / "indexes/captures.parquet").exists():
        source_rows = recover_sources(
            source_rows,
            pq.ParquetFile(root / "indexes/captures.parquet"),
            read_receipt=lambda key: (root / key).read_bytes(),
            working=working,
        )
        metadata = {
            **(metadata or {}),
            "retained_recovery_fingerprint": recovery_fingerprint(),
        }
    inputs = working.mapping("filename_inputs")

    def row_schema(columns):
        return pa.schema(
            [
                (
                    name,
                    SOURCE_SCHEMA.field(name).type
                    if name in SOURCE_SCHEMA.names
                    else metadata_type(name),
                )
                for name in columns
            ]
        )

    rows = ParquetRows((output_root or root) / "filename-rows", row_schema)
    bodies, names = working.mapping("filename_bodies"), working.mapping("filename_names")
    fingerprint = parser_fingerprint()
    progress.report("reuse_cached_metadata")
    cache_store = cache_store or LocalStore(root)
    cached = working.mapping("filename_results")
    body_fingerprint = evidence_fingerprint()
    if not inspect_bodies and previous_schema is not None:
        # A metadata-only update preserves earlier content readings. Replacing
        # their reader version without actually reading the files loses evidence.
        body_fingerprint = (previous_schema.metadata or {}).get(
            b"body_evidence_fingerprint", body_fingerprint.encode()
        ).decode()
    reuse_bodies = reuse_results or not inspect_bodies
    body_cache = working.mapping("body_results")
    payload = (
        cache_store.read("indexes/processing/bodies.parquet")
        if reuse_results and retained_body_readings is None
        else None
    )
    if payload:
        cached_file = pq.ParquetFile(pa.BufferReader(payload))
        for batch in cached_file.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                key = (row.pop("reader"), row.pop("body_key"))
                body_cache[key] = {
                    field: value for field, value in row.items() if value is not None
                }
    del payload
    selected_capture_readings = working.mapping("selected_capture_readings")
    if retained_body_readings is not None:
        for reading in retained_body_readings:
            if reading.get("reader") is not None:
                # Legacy per-reader results precede old catalog fields, including
                # completed negative readings. Capture facts fill remaining gaps.
                restore_readings((reading,), body_cache)
            else:
                selected_capture_readings.setdefault(reading["body_key"], reading)
    source_fields = (
        set(SOURCE_SCHEMA.names)
        | SOURCE_CONTEXT_FIELDS
        | AVAILABILITY_FIELDS
        | {"capture_outcome"}
    )
    reuse_names = (
        previous is not None
        and reuse_results
        and "document_kind_source" in previous_schema.names
    )
    filename_fields = (
        (
            set(previous_schema.names)
            - source_fields
            - {"source_id", "document_id", "format", "document_kind_source"}
            - EVIDENCE_FIELDS
            - BODY_FIELDS
        )
        if reuse_names
        else set()
    )
    if previous is not None and (reuse_names or reuse_bodies):
        selected = (
            filename_fields
            | {
                "filename",
                "source_url",
                "recovered_filename",
                "document_kind_source",
            }
            if reuse_names
            else set()
        )
        if reuse_bodies:
            selected |= BODY_FIELDS | {"body_key"}
        # Restore filename and body results together from one projected scan.
        for batch in previous_batches(sorted(selected & set(previous_schema.names))):
            for row in batch.to_pylist():
                if reuse_bodies and (key := body_evidence_key(row)):
                    body_cache.setdefault(key, cached_body_fields(row, key))
                if (
                    not reuse_names
                    or row.get("filename") is None
                    or row.get("recovered_filename")
                ):
                    continue  # Recovered names depend on the current URL evidence.
                restore_filename_kind(row)
                cached.setdefault(
                    (row["filename"], row["source_url"]),
                    {
                        key: row[key]
                        for key in filename_fields
                        if row[key] is not None
                    },
                )
    if retained_body_readings is not None:
        restore_readings(selected_capture_readings.values(), body_cache)
    elif reuse_results:
        # Capture already inspected these bytes before releasing them. Preserve
        # published/legacy readings first, then admit newly completed results.
        restore_body_results(cache_store, body_cache)
    for key, reading in body_readings.items():
        fields = {
            name: value
            for name, value in reading.items()
            if name in BODY_FIELDS and value is not None
        }
        # Replace just these explicitly chosen results, including a deliberate
        # empty cover. Do not let old XML facts or an earlier citation resurface.
        body_cache[("xml", key)] = {}
        body_cache[("document", key)] = {
            name: value for name, value in fields.items() if name not in COVER_FIELDS
        }
        body_cache[("cover", key)] = {
            name: value for name, value in fields.items() if name in COVER_FIELDS
        }
    checkpoint_bodies = (
        result_checkpoint(
            cache_store,
            "bodies",
            body_fingerprint,
            ("reader", "body_key"),
            body_cache,
        )
        if retained_body_readings is None
        else lambda **kwargs: None
    )
    columns = set()
    pending_count = 0
    progress.report(
        "inspect_document_contents", completed=0, unit="distinct_body_attempts"
    )

    def interpret(key):
        if key not in cached:
            cached[key] = extract(key)
        return cached[key]

    deferred_bodies = working.mapping("deferred_bodies")
    attempted_bodies = working.mapping("attempted_bodies")
    supplied_reader = read_body or (lambda key: read_retained_body(root, key))

    def inspect_body(key):
        if not inspect_bodies:
            return None
        checkpoint_bodies()
        if key in oversized_bodies or key in deferred_bodies:
            return None  # Missing bytes retry next run; known size limits stay skipped.
        data = supplied_reader(key)
        if data is None:
            deferred_bodies[key] = True
        attempted_bodies[key] = True
        progress.report(
            "inspect_document_contents",
            completed=len(attempted_bodies),
            unit="distinct_body_attempts",
        )
        return data

    recovered_urls = working.mapping("recovered_urls", set)
    shared_body_fields = working.mapping("shared_body_fields")
    executor = (
        ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"))
        if workers > 1
        else nullcontext()
    )
    try:
        # Discover shared facts while consuming the source stream. Keep a single
        # immutable spool: later aliases may supply evidence to earlier rows.
        with executor as pool:
            source_rows = iter(source_rows)
            while records := list(islice(source_rows, 256)):
                records = [dict(row) for row in records]
                keys = list(
                    dict.fromkeys(
                        (row["filename"], row["source_url"]) for row in records
                    )
                )
                pending = [key for key in keys if key not in cached]
                parsed = (
                    pool.map(extract, pending, chunksize=128)
                    if pool is not None
                    else map(extract, pending)
                )
                for key, fields in zip(pending, parsed):
                    cached[key] = fields
                pending_count += len(pending)
                for row in records:
                    if row.get("body_key") in body_readings:
                        for name in BODY_FIELDS:
                            row.pop(name, None)
                    key = (row["filename"], row["source_url"])
                    inputs[key] = True
                    fields = cached[key]
                    columns.update(fields)
                    row.update(fields)
                    columns.update(
                        key
                        for key, value in row.items()
                        if key
                        in SOURCE_CONTEXT_FIELDS
                        | AVAILABILITY_FIELDS
                        | {
                            "capture_outcome",
                            "record_role",
                            "source_record_type",
                            "source_record_identifier",
                        }
                        and value
                    )
                    if row["body_key"]:
                        bodies[row["body_key"]] = True
                    if row["filename"]:
                        names[row["filename"]] = True
                enrich_sources(
                    records,
                    read_body=inspect_body,
                    extract=interpret,
                    cached=body_cache,
                    urls=recovered_urls,
                    shared_body_fields=shared_body_fields,
                )
                for row in records:
                    fill_document_kind(row)
                enrich_document_covers(
                    records, read_body=inspect_body, cached=body_cache
                )
                for row in records:
                    rows.append(row)
                progress.report(
                    "extract_filenames", completed=pending_count, unit="filenames"
                )
        # These source/recovery pages have been consumed. The spool is the only
        # remaining row stream; caches contain shared facts, not duplicate rows.
        del source_rows
        for name in ("recovery_result", "recovery_rows"):
            working.drop_table(name)
    finally:
        if inspect_bodies:
            checkpoint_bodies(force=True)
    input_count = len(inputs)
    if any(key not in bodies for key in body_readings):
        raise ValueError("Selected PDF reading has no supplied retained source row")
    if body_readings and not inspect_bodies:
        # Explicit empty covers must survive future ordinary updates; otherwise
        # old immutable capture readings could repopulate a cleared citation.
        checkpoint_bodies(force=True)
    rows_without_body = 0
    reading_provenance = (
        json.loads(
            (previous_schema.metadata or {}).get(b"body_reading_overrides", b"{}")
        )
        if previous_schema is not None and reuse_bodies
        else {}
    )
    reading_provenance.update(
        {key: row["parser_fingerprint"] for key, row in body_readings.items()}
    )

    def finalized_rows():
        nonlocal rows_without_body
        progress.report(
            "finalize_metadata", completed=0, total=len(rows), unit="source_rows"
        )
        completed = 0
        for records in rows.batches():
            enrich_sources(
                records,
                read_body=lambda key: None,
                extract=interpret,
                cached=body_cache,
                urls=recovered_urls,
                initialize_roles=False,
                shared_body_fields=shared_body_fields,
            )
            enrich_document_covers(
                records, read_body=lambda key: None, cached=body_cache
            )
            refresh_response_metadata(root, records)
            for row in records:
                apply_response_role(row)
                columns.update(
                    key
                    for key, value in row.items()
                    if isinstance(value, list) and key not in SOURCE_SCHEMA.names
                )
                if row["body_key"] and row["body_key"] not in bodies:
                    raise ValueError(
                        "Filename table does not cover every selected retained body"
                    )
                if row["filename"] and row["filename"] not in names:
                    raise ValueError("Filename table does not cover every known spelling")
                rows_without_body += row["body_key"] is None
                yield row
            completed += len(records)
            progress.report(
                "finalize_metadata",
                completed=completed,
                total=len(rows),
                unit="source_rows",
            )
        cached.clear()
        body_cache.clear()
        selected_capture_readings.clear()
        shared_body_fields.clear()

    def output_schema():
        if columns & set(SOURCE_SCHEMA.names):
            raise ValueError(
                "Extracted metadata conflicts with source locator columns"
            )
        return pa.schema(
            [
                *SOURCE_SCHEMA,
                *[(name, metadata_type(name)) for name in sorted(columns)],
            ],
            metadata={
                "format_version": "5",
                "house_naming_version": __version__,
                "house_naming_fingerprint": fingerprint,
                "body_evidence_fingerprint": body_fingerprint,
                "deferred_body_reads": str(len(deferred_bodies)),
                "body_inspection": str(inspect_bodies).lower(),
                **(metadata or {}),
                **(
                    {
                        "body_reading_overrides": json.dumps(
                            reading_provenance, sort_keys=True
                        )
                    }
                    if reading_provenance
                    else {}
                ),
            },
        )

    destination = (output_root or root) / "indexes/document-filenames.parquet"
    document_stats = write_document_indexes(
        destination,
        finalized_rows(),
        output_schema,
        working=working,
        previous=previous,
        previous_documents=previous_documents,
        reuse_groups=reuse_results,
    )
    return CatalogBuildResult(
        rows=len(rows),
        **document_stats,
        distinct_bodies=len(bodies),
        distinct_filenames=len(names),
        rows_without_retained_body=rows_without_body,
        parser_inputs=input_count,
        parsed_inputs=pending_count,
        **({"refreshed_body_readings": len(body_readings)} if body_readings else {}),
        output=str(destination),
        output_bytes=destination.stat().st_size,
        elapsed_seconds=round(time.monotonic() - started),
        validation=getattr(document_stats, "validation", None),
    )


def build(root, inventory_dir, *, workers=4, families=FAMILIES, inspect_bodies=False):
    store = LocalStore(root)
    with (
        catalog_publication.read_catalog(store) as snapshot,
        TemporaryDirectory(prefix="inventory-working-") as directory,
    ):
        working = WorkingCatalog(Path(directory) / "working.sqlite")
        try:
            staged = Path(directory) / "output"
            (staged / "indexes").mkdir(parents=True)
            result = _build(
                root,
                inventory_dir,
                workers=workers,
                families=families,
                inspect_bodies=inspect_bodies,
                working=working,
                output_root=staged,
            )
            return publish_local_result(
                root, staged / "indexes/document-filenames.parquet", result, snapshot
            )
        finally:
            working.close()


def _build(
    root, inventory_dir, *, workers, families, inspect_bodies, working, output_root
):
    names, capture_rows, bodies, known_variants = collect_names(
        root, inventory_dir, families, working=working
    )
    print(
        compact(
            {
                "stage": "names_located",
                "capture_rows": capture_rows,
                "bodies": len(bodies),
                "filename_rows": len(names),
            }
        ),
        flush=True,
    )
    context = read_document_sources(root, context=DocumentSources(working=working))
    sources = (
        dict(
            body_key=body,
            filename=filename,
            source_url=url,
            **context.for_url(url),
            **{k: sorted(v) or None for k, v in origins.items()},
        )
        for (body, filename, url), origins in names.items()
    )
    return dict(
        write_filename_metadata(
            root,
            sources,
            workers=workers,
            inspect_bodies=inspect_bodies,
            working=working,
            output_root=output_root,
        ),
        capture_rows=capture_rows,
        known_inventory_spellings=len(known_variants),
    )


def filename_refresh_inputs(source):
    """Stream retained source evidence separately from filename interpretations.

    Callers pass the original table as previous= when writing so retained body
    readings survive. This helper does not read bodies or change the catalog.
    """
    fields = [
        *[name for name in SOURCE_SCHEMA.names if name in source.schema_arrow.names],
        *sorted(
            (
                SOURCE_CONTEXT_FIELDS
                | AVAILABILITY_FIELDS
                | {
                    "capture_outcome",
                    "record_role",
                    "source_record_type",
                    "source_record_identifier",
                }
            )
            & set(source.schema_arrow.names)
        ),
    ]
    rows = (
        row
        for batch in source.iter_batches(columns=fields)
        for row in batch.to_pylist()
    )
    metadata = {
        key.decode(): value.decode()
        for key, value in (source.schema_arrow.metadata or {}).items()
        if key
        in {
            b"raw_capture_rows",
            b"capture_digest",
            b"seed_digest",
            b"deferred_source_bodies",
            b"source_lineage_version",
            b"source_lineage_overlay",
            b"download_state_digest",
            b"download_state_rows",
            b"availability_policy",
            b"source_fingerprint",
            b"retained_recovery_fingerprint",
        }
    }
    return rows, metadata


def refresh_filename_metadata(root, *, workers=4, inspect_bodies=False, repair=False):
    """Reuse saved interpretations unless explicitly rebuilding; never acquire sources."""
    with catalog_publication.read_catalog(LocalStore(root)) as snapshot:
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        source = pq.ParquetFile(snapshot.filenames_path)
        rows, metadata = filename_refresh_inputs(source)
        return write_filename_metadata(
            root,
            rows,
            workers=workers,
            previous=source,
            reuse_results=not repair,
            inspect_bodies=inspect_bodies,
            publication_snapshot=snapshot,
            previous_documents=pq.ParquetFile(snapshot.documents_path)
            if snapshot.documents_path
            else None,
            metadata=metadata,
        )


def reindex_documents(root):
    """Refresh grouping from one input snapshot and stage its complete replacement."""
    with catalog_publication.read_catalog(LocalStore(root)) as snapshot:
        if snapshot.filenames_path is None:
            raise ValueError("Missing filename index")
        source = pq.ParquetFile(snapshot.filenames_path)
        rows = (
            {key: value for key, value in row.items() if value is not None}
            for batch in source.iter_batches(batch_size=4096)
            for row in batch.to_pylist()
        )
        with TemporaryDirectory(prefix="document-reindex-") as directory:
            path = Path(directory) / "document-filenames.parquet"
            result = dict(
                rows=source.metadata.num_rows,
                **write_document_indexes(path, rows, source.schema_arrow),
            )
            return publish_local_result(root, path, result, snapshot)
