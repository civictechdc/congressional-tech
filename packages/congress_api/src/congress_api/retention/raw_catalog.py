"""Rebuild the paired document tables from retained receipts and source bodies.

The published filename table is the reusable inventory. New receipts add facts;
explicit repair replays parent evidence. Code changes preserve saved metadata. Document-body
inspection is opt-in. Preserve prior tables before replacement.
Immutable table pairs publish together through one conditional selector update.
Readers validate the selected files and their matching catalog_id values.
"""

from hashlib import sha256
from contextlib import ExitStack
from functools import partial
import shutil
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention import raw_progress as progress
from congress_api.retention.source_inputs import add_source, collect_source_inputs
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.catalog_publication import read_catalog, publish_catalog
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
from congress_api.retention.catalog_cache import (
    capture_digest, capture_digest_matches, source_fingerprint,
)
from congress_api.retention.raw_archive import CAPTURES_KEY, CAPTURE_SCHEMA, STATE_KEY, STATE_SCHEMA, decode_table
from congress_api.retention.catalog_availability import annotate_availability
from congress_api.retention.catalog_lineage import refresh_lineage_pair, replay_discovery

FILENAMES = "indexes/document-filenames.parquet"
DOCUMENTS = "indexes/documents.parquet"
SOURCE_LINEAGE_VERSION = '1'


def rebuild_catalog(store, captures=None, *, seeds=(), workers=4, repair=False, inspect_bodies=False,
                    body_readings=()):
    """Publish derived tables; explicitly supplied PDF readings refresh only their bodies."""
    with TemporaryDirectory(prefix="raw-catalog-") as directory:
        root = Path(directory)
        (root / "indexes").mkdir()
        working = WorkingCatalog(root / "working.sqlite")
        try:
            return rebuild_catalog_in_directory(store, captures, seeds=seeds, workers=workers,
                                    repair=repair, inspect_bodies=inspect_bodies,
                                    working=working, root=root, body_readings=body_readings)
        finally:
            working.close()


def rebuild_catalog_in_directory(store, captures=None, *, working, root, seeds=(), workers=4,
                                 repair=False, inspect_bodies=False, body_readings=()):
    """Build into an explicitly caller-owned durable workspace and open SQLite state."""
    return _rebuild_catalog(store, captures, seeds=seeds, workers=workers, repair=repair,
        inspect_bodies=inspect_bodies, working=working, root=Path(root),
        body_readings=index.validated_body_readings(body_readings))


def _rebuild_catalog(store, captures, *, seeds, workers, repair, inspect_bodies, working, root,
                     body_readings):
    with ExitStack() as owners:
        return _rebuild_catalog_owned(store, captures, seeds=seeds, workers=workers,
            repair=repair, inspect_bodies=inspect_bodies, working=working, root=root,
            body_readings=body_readings, owners=owners)


def _rebuild_catalog_owned(store, captures, *, seeds, workers, repair, inspect_bodies,
                           working, root, body_readings, owners):
    def read(key):
        data = store.read(key)
        progress.advance('objects_read')
        progress.advance('bytes_read', len(data) if data else 0)
        return data

    progress.report('load_indexes')
    if captures is None:
        data = read(CAPTURES_KEY)
        if data is None:
            raise ValueError("Missing retained capture index")
        captures = decode_table(data)
        del data
    if captures.schema.remove_metadata() != CAPTURE_SCHEMA:
        raise ValueError("Unexpected capture index schema")
    snapshot = owners.enter_context(read_catalog(store, read=read))
    # Verified owned files stay alive through interpretation and archival.
    previous = pq.ParquetFile(snapshot.filenames_path) if snapshot.filenames_path else None
    previous_documents = pq.ParquetFile(snapshot.documents_path) if snapshot.documents_path else None
    meta = (previous.schema_arrow.metadata or {}) if previous is not None else {}
    previous_rows = previous.metadata.num_rows if previous is not None else 0
    if int(meta.get(b"raw_capture_rows", b"0")) > len(captures):
        raise ValueError("Capture index was truncated since the last catalog rebuild")
    all_captures = captures
    capture_rows = len(captures)
    state_bytes = read(STATE_KEY)
    state_digest = sha256(state_bytes or b'').hexdigest()
    state = decode_table(state_bytes) if state_bytes is not None else pa.Table.from_pylist([], schema=STATE_SCHEMA)
    if state.schema.remove_metadata() != STATE_SCHEMA:
        raise ValueError('Unexpected download state schema')
    del state_bytes
    if body_readings:
        present = set(captures.filter(pc.is_in(captures['body_key'], value_set=pa.array(
            sorted(body_readings), type=pa.string())))['body_key'].to_pylist())
        if present != set(body_readings):
            raise ValueError('Selected PDF reading has no retained capture')
    body_limit = 16 * 1024**2
    oversized_bodies = set(captures.filter(pc.greater(captures['bytes'], body_limit))['body_key'].to_pylist())
    seeds = list(seeds)
    seed_digest = sha256(json.dumps(seeds, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    fingerprint = source_fingerprint()
    cursor = int(meta.get(b'raw_capture_rows', b'0'))
    checkpoint = b'raw_capture_rows' in meta or b'capture_digest' in meta
    reusable = (not repair and previous is not None and b'raw_capture_rows' in meta and 0 <= cursor <= capture_rows
                and capture_digest_matches(captures.slice(0, cursor), meta.get(b'capture_digest')))
    if checkpoint and not repair and not reusable:
        raise ValueError('Catalog capture checkpoint digest mismatch or invalid cursor; verify legacy checkpoints '
                         'with their original PyArrow writer, or explicitly rebuild after investigation')
    deferred_sources = set(json.loads(meta.get(b'deferred_source_bodies', b'[]'))) if reusable else set()
    lineage_refresh = reusable and meta.get(b'source_lineage_version') != SOURCE_LINEAGE_VERSION.encode()
    if (reusable and not deferred_sources and not body_readings
            and (not inspect_bodies or meta.get(b'body_inspection') == b'true'
                 and meta.get(b'deferred_body_reads') == b'0')
            and cursor == capture_rows and meta.get(b'seed_digest') == seed_digest.encode()
            and meta.get(b'download_state_digest') == state_digest.encode()
            and meta.get(b'availability_policy') == b'2'
            and previous_documents is not None
            and (previous_documents.schema_arrow.metadata or {}).get(b'catalog_id') == meta.get(b'catalog_id')):
        if lineage_refresh:
            result = refresh_lineage_pair(previous, previous_documents,
                captures, read, root=root, working=working, version=SOURCE_LINEAGE_VERSION)
            return _publish_result(store, root, snapshot, result)
        if snapshot.manifest is None:
            shutil.copyfile(snapshot.filenames_path, root / FILENAMES)
            shutil.copyfile(snapshot.documents_path, root / DOCUMENTS)
            publish_catalog(store, root / FILENAMES, root / DOCUMENTS, previous=snapshot)
        progress.report('catalog_unchanged')
        return {'unchanged': True, 'rows': previous_rows, 'document_rows': previous_documents.metadata.num_rows,
                'catalog_id': meta[b'catalog_id'].decode(), 'raw_capture_rows': capture_rows}
    sources, context = working.mapping("sources"), index.DocumentSources(working=working)
    if reusable:
        pending = captures.slice(0, cursor).filter(pc.is_in(captures.slice(0, cursor)['body_key'],
            value_set=pa.array(sorted(deferred_sources | set(body_readings)), type=pa.string())))
        captures = pa.concat_tables([pending, captures.slice(cursor)])
        del pending

    add = partial(add_source, sources)

    progress.report('restore_previous_source_metadata', total=previous_rows,
                    unit='source_rows')
    if previous is not None:
        restored = 0
        columns = [f for f in previous.schema_arrow.names if f in
                   set(index.SOURCE_SCHEMA.names) | index.SOURCE_CONTEXT_FIELDS | {"capture_outcome"}]
        for batch in previous.iter_batches(columns=columns, batch_size=4096):
            for row in batch.to_pylist():
                # Preserve known source locators and actual response facts. Old
                # flat context has no reliable basis; its exact bytes are archived
                # below, before replacement, instead of guessing a native type.
                add(**{k: v for k, v in row.items() if reusable or k not in index.SOURCE_CONTEXT_FIELDS})
                if reusable:
                    context.add_url(row.get("source_url"), {"source_occurrences": [
                        occurrence for occurrence in row.get("source_occurrences") or []
                        if occurrence.get("source_occurrence_scope") not in (["capture"], ["association"])]})
                for occurrence in row.get("source_occurrences") or []:
                    if reusable:
                        context.restore_association(row.get("source_url"), occurrence)
                    elif occurrence.get("source_document_type_basis") == ["publisher"] or occurrence.get("source_probe_status"):
                        context.add_url(row.get("source_url"), occurrence)
            restored += len(batch)
            progress.report('restore_previous_source_metadata', completed=restored,
                            total=previous_rows, unit='source_rows')

    if lineage_refresh:
        # Backfill discovery relationships once from receipt metadata. Existing
        # filename interpretations, saved bodies and download state stay valid.
        replay_discovery(context, all_captures.slice(0, cursor), read)

    def read_body(key):
        # The archive already records original byte lengths. Do not transfer a
        # known oversized body merely to reject it at the existing read limit.
        if key in oversized_bodies:
            deferred_sources.discard(key)  # A known read limit is not missing data.
            return None
        data = read_retained_body(None, key, read_compressed=read, limit=body_limit)
        if data is None:
            deferred_sources.add(key)
        else:
            deferred_sources.discard(key)
        return data
    # Scoped meeting facts are small receipt metadata, not another saved lookup
    # table. They may be needed by newly arrived XML with only an event number.
    if reusable and len(captures):
        meetings = all_captures.slice(0, cursor)
        meetings = meetings.filter(pc.equal(meetings['family'], 'congress/meetings'))
        for record, _, receipt in index.retained_records(meetings, read):
            context.add_meeting(record, receipt)
        del meetings
    context = index.read_document_sources(captures=captures, read_receipt=read,
                                          read_body=read_body, context=context)

    collect_source_inputs(sources, context, captures, read, working=working, seeds=seeds)
    context.report_statistics()
    context = None
    for name in ("occurrences","occurrence_urls","extra_filters","transfers","meetings","events"):
        working.connection.execute(f"DROP TABLE IF EXISTS {name}")
    progress.report('recover_capture_associations')
    # A newly discovered URL can name an older body. Resolve once against the
    # complete capture inventory instead of doing overlapping recovery passes.
    source_rows = iter(recover_sources(sources.values(), all_captures, read_receipt=read, working=working))
    hearing_captures = all_captures.filter(pc.equal(all_captures['family'], 'congress/hearings'))
    hearing_records = ((record, rows) for record, rows, _ in index.retained_records(hearing_captures, read))
    source_rows = annotate_availability(source_rows, state, hearing_records=hearing_records, working=working)
    # Recovery has finished before this iterator is consumed. Reuse staging
    # pages for interpretation instead of retaining each intermediate corpus.
    for name in ("sources","occurrences","occurrence_urls","extra_filters","transfers","meetings","events","captured",
                 "recovery_rows","recovery_missing","recovery_local","recovery_wanted",
                 "recovery_references","recovery_receipts","recovered","replaced"):
        if name == "recovery_rows" and "recovery_result" not in {
                row[0] for row in working.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            continue  # A no-recovery iterator still owns these input rows.
        working.connection.execute(f"DROP TABLE IF EXISTS {name}")
    context = None
    input_digest = capture_digest(all_captures)
    del all_captures

    # Interpretation now needs only the recovered source rows. Release receipt
    # lookup tables and the capture inventory before filename/PDF processing.
    sources = None
    del captures
    result = index.write_filename_metadata(
        root, source_rows, workers=workers, previous=previous, read_body=read_body,
        oversized_bodies=oversized_bodies, cache_store=store, reuse_results=not repair,
        inspect_bodies=inspect_bodies, working=working, previous_documents=previous_documents,
        body_readings=body_readings.values(),
        metadata={"raw_capture_rows": str(capture_rows), "source_fingerprint": fingerprint,
                  "source_lineage_version": SOURCE_LINEAGE_VERSION,
                  "capture_digest": input_digest, "seed_digest": seed_digest,
                  "download_state_digest": state_digest, "download_state_rows": str(len(state)),
                  "availability_policy": "2",
                  "deferred_source_bodies": json.dumps(sorted(deferred_sources)),
                  "retained_recovery_fingerprint": recovery_fingerprint()},
    )
    return _publish_result(store, root, snapshot, result)


def _publish_result(store, root, snapshot, result):
    progress.report('validate_document_tables')
    from congress_api.retention.catalog_validation import validate_references
    validation = getattr(result, 'validation', None)
    if validation is None:
        validation = validate_references(root / FILENAMES, root / DOCUMENTS,
            validator=index.validate_document_indexes, source_rows=result["rows"], document_rows=result["document_rows"])
    else:
        validation.require(root / FILENAMES, root / DOCUMENTS, validator=index.validate_document_indexes)
    # Retain evidence that exists only in an older generated table, including
    # columns whose original publisher/parser basis can no longer be proved.
    progress.report('archive_previous_tables')
    for label, key, path in (("filenames", FILENAMES, snapshot.filenames_path),
                             ("documents", DOCUMENTS, snapshot.documents_path)):
        if path is not None:
            identity = snapshot.files[label]
            saved = f"catalog-history/sha256/{identity['sha256']}/{Path(key).name}"
            store.put_derived_file(saved, path, expected=identity)
            result[f"previous_{label}_key"] = saved
    progress.report('publish_document_snapshot')
    result.update(publish_catalog(store, root / FILENAMES, root / DOCUMENTS, previous=snapshot, validation=validation))
    return {k: v for k, v in result.items() if k not in ("output", "documents_output")}
