"""Rebuild the paired document tables from retained receipts and source bodies.

The published filename table is the reusable inventory. New receipts add facts;
explicit repair replays parent evidence. Code changes preserve saved metadata. Document-body
inspection is opt-in. Preserve prior tables before replacement.
Immutable table pairs publish together through one conditional selector update.
Readers validate the selected files and their matching catalog_id values.
"""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.parsers.source_family import family as source_family
from congress_api.retention import document_index as index
from congress_api.retention import raw_progress as progress
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.catalog_publication import read_catalog, publish_catalog
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.document_recovery import recover_sources, recovery_fingerprint
from congress_api.retention.catalog_cache import (
    capture_digest, capture_digest_matches, source_fingerprint,
)
from congress_api.retention.raw_archive import CAPTURES_KEY, CAPTURE_SCHEMA, decode_table

FILENAMES = "indexes/document-filenames.parquet"
DOCUMENTS = "indexes/documents.parquet"


def rebuild_catalog(store, captures=None, *, seeds=(), workers=4, repair=False, inspect_bodies=False,
                    body_readings=()):
    """Publish derived tables; explicitly supplied PDF readings refresh only their bodies."""
    body_readings = index.validated_body_readings(body_readings)
    with TemporaryDirectory(prefix="raw-catalog-") as directory:
        root = Path(directory)
        (root / "indexes").mkdir()
        working = WorkingCatalog(root / "working.sqlite")
        try:
            return _rebuild_catalog(store, captures, seeds=seeds, workers=workers,
                                    repair=repair, inspect_bodies=inspect_bodies,
                                    working=working, root=root, body_readings=body_readings)
        finally:
            working.close()


def _rebuild_catalog(store, captures, *, seeds, workers, repair, inspect_bodies, working, root,
                     body_readings):
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
    snapshot = read_catalog(store, read=read)
    previous_bytes = snapshot.filenames
    # Keep compressed input and stream the columns each stage needs. Decoding
    # every nested occurrence here duplicates a multi-gigabyte working set.
    previous = pq.ParquetFile(pa.BufferReader(previous_bytes)) if previous_bytes else None
    # Read both ETags before publication; also retain any unmatched prior pair.
    previous_documents = snapshot.documents
    meta = (previous.schema_arrow.metadata or {}) if previous is not None else {}
    previous_rows = previous.metadata.num_rows if previous is not None else 0
    if int(meta.get(b"raw_capture_rows", b"0")) > len(captures):
        raise ValueError("Capture index was truncated since the last catalog rebuild")
    all_captures = captures
    capture_rows = len(captures)
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
    if (reusable and not deferred_sources and not body_readings
            and (not inspect_bodies or meta.get(b'body_inspection') == b'true'
                 and meta.get(b'deferred_body_reads') == b'0')
            and cursor == capture_rows and meta.get(b'seed_digest') == seed_digest.encode()
            and previous_documents is not None
            and (pq.read_schema(pa.BufferReader(previous_documents)).metadata or {}).get(b'catalog_id') == meta.get(b'catalog_id')):
        if snapshot.manifest is None:
            (root / FILENAMES).write_bytes(previous_bytes)
            (root / DOCUMENTS).write_bytes(previous_documents)
            publish_catalog(store, root / FILENAMES, root / DOCUMENTS, previous=snapshot)
        progress.report('catalog_unchanged')
        return {'unchanged': True, 'rows': previous_rows, 'document_rows': pq.ParquetFile(pa.BufferReader(previous_documents)).metadata.num_rows,
                'catalog_id': meta[b'catalog_id'].decode(), 'raw_capture_rows': capture_rows}
    sources, context = working.mapping("sources"), index.DocumentSources(working=working)
    if reusable:
        pending = captures.slice(0, cursor).filter(pc.is_in(captures.slice(0, cursor)['body_key'],
            value_set=pa.array(sorted(deferred_sources | set(body_readings)), type=pa.string())))
        captures = pa.concat_tables([pending, captures.slice(cursor)])
        del pending

    def add(body_key, filename, source_url, **values):
        key = (body_key, filename, source_url)
        row = sources.setdefault(key, dict(body_key=body_key, filename=filename, source_url=source_url))
        for field, items in values.items():
            if items:
                row[field] = index.merge_values(field, row.get(field), items)
        sources[key] = row
        return row

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

    def link_names(link, receipt=None):
        url = link.get("url")
        if not url:
            return
        context.add_link(link, receipt)
        names = index.url_document_names(url)
        if not names and (name := index.url_filename(url)):
            names = [(name, "url_path")]
        for name, basis in names:
            add(None, name, url, filename_origins=[basis])

    for link in progress.track(seeds, 'read_seed_links', unit='links'):
        link_names(link)
    # First build/repair includes migration receipts; routine updates use new rows.
    # Historical Senate download routing is interpreted by the current owner.
    selected = pc.is_in(captures["family"], value_set=pa.array(index.FAMILIES))
    senate = captures.filter(pc.equal(captures["family"], "senate/pages"))
    downloads = pa.array(sorted({url for url in senate["context_url"].to_pylist()
                                 if url and source_family(url=url) == "documents"}), type=pa.string())
    selected = pc.or_(selected, pc.and_(pc.equal(captures["family"], "senate/pages"),
                                      pc.is_in(captures["context_url"], value_set=downloads)))
    recurring = pc.fill_null(pc.match_substring(captures["receipt_key"], "/download-"), False)
    selected = pc.or_(selected, recurring)
    for record, rows, receipt in index.retained_records(captures.filter(selected), read):
        if isinstance(record, dict):
            for link in record.get("source_context", {}).get("observations", []):
                link_names(link, receipt)
            for link in record.get("links", []):
                link_names(link, receipt)
            context.add_redirect(record, receipt)
            context.add_associations(record, receipt)
        for row in rows:
            is_recurring = "/download-" in (row.get("receipt_key") or "")
            pointer = json.loads(row.get('pointer_json') or '[]')
            member = (len(pointer) == 4 and pointer[0] == 'archive_members'
                      and pointer[2:] == ['content', 'body'])
            if is_recurring and not member and pointer not in ([], ["content", "body"]):
                continue  # Provider transport and prior attempts are not this response.
            observed = index.response_metadata(row, record)
            locator = {k: sorted(v) for k, v in {**receipt, **index.context_values(
                source_capture_file=row.get("source_file"), source_capture_pointer=row.get("pointer_json"),
                source_capture_url=row.get("context_url"), source_occurrence_scope="capture")}.items()}
            observed.update({**locator, "source_occurrences": [locator]})
            owner = index.nearest_record(record, row.get("pointer_json"))
            if owner.get("outcome"):
                observed["capture_outcome"] = [owner["outcome"]]
            if member:
                observed['capture_outcome'] = ['saved' if owner['status'] == 'completed' else owner['status']]
                observed['response_body_complete'] = [str(owner['status'] == 'completed').lower()]
            if row.get("body_key") or is_recurring:
                for name, basis, url, source in index.source_names(row, record) or [(None, None, None, None)]:
                    add(row.get("body_key") or owner.get("retained_body_key"), name, url, filename_origins=[basis] if basis else [],
                        source_paths=[source] if basis in {"retained_path", "archive_member"} else [], **observed)
            elif row.get("context_url"):
                for name, basis in index.url_document_names(row["context_url"]):
                    add(None, name, row["context_url"], filename_origins=[basis], **observed)
        if (any(not row.get("body_key") for row in rows)
                and not (isinstance(record, dict) and "xml_url" in record and "pdf_url" in record)):
            for name, basis, url in index.inventory_names(record):
                add(None, name, url, filename_origins=[basis])
    context.refresh_meeting_context()
    # Metadata-only publisher records can list files with no capture yet.
    progress.report('prepare_source_associations')
    for url, values in context.by_url.items():
        if values.get("source_link_url"):
            for name, basis in index.url_document_names(url) or [(index.url_filename(url), "url_path")]:
                add(None, name, url, filename_origins=[basis] if name else [])
    # Redirect/recovery evidence belongs to its destination's inventory row.
    # Keep it even when its parent metadata arrives in a later capture batch.
    for edges in context.transfers.values():
        for url, values in edges:
            occurrence = {**values, "source_occurrence_scope": ["association"]}
            for name, basis in index.url_document_names(url) or [(index.url_filename(url), "url_path")]:
                add(None, name, url, filename_origins=[basis] if name else [],
                    source_occurrences=[occurrence])

    captured = working.mapping("captured", list)
    for key, row in sources.items():
        body, name, url = key
        if body and url:
            keys = captured[(name, url)]
            keys.append(key)
            captured[(name, url)] = keys
    for key in sources:
        body, name, url = key
        if body is None and (name, url) in captured:
            old = sources.pop(key)
            for target in captured[(name, url)]:
                row = sources[target]
                for field, items in old.items():
                    if isinstance(items, list):
                        row[field] = index.merge_values(field, row.get(field), items)
                sources[target] = row
    for key, row in progress.track(sources.items(), 'associate_source_metadata', unit='source_rows'):
        for field, values in context.for_url(row.get("source_url")).items():
            row[field] = index.merge_values(field, row.get(field), values)
        sources[key] = row
    # Every row now owns its paired source observations. Release parent lookup
    # pages before recovery builds its own indexed working rows.
    context = None
    for name in ("occurrences","occurrence_urls","extra_filters","transfers","meetings","events"):
        working.connection.execute(f"DROP TABLE IF EXISTS {name}")
    progress.report('recover_capture_associations')
    # A newly discovered URL can name an older body. Resolve once against the
    # complete capture inventory instead of doing overlapping recovery passes.
    source_rows = iter(recover_sources(sources.values(), all_captures, read_receipt=read, working=working))
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
    del captures, captured, selected, senate, downloads, recurring
    result = index.write_filename_metadata(
        root, source_rows, workers=workers, previous=previous, read_body=read_body,
        oversized_bodies=oversized_bodies, cache_store=store, reuse_results=not repair,
        inspect_bodies=inspect_bodies, working=working, previous_documents=previous_documents,
        body_readings=body_readings.values(),
        metadata={"raw_capture_rows": str(capture_rows), "source_fingerprint": fingerprint,
                  "capture_digest": input_digest, "seed_digest": seed_digest,
                  "deferred_source_bodies": json.dumps(sorted(deferred_sources)),
                  "retained_recovery_fingerprint": recovery_fingerprint()},
    )
    progress.report('validate_document_tables')
    index.validate_document_indexes(root / FILENAMES, root / DOCUMENTS,
                                    source_rows=result["rows"], document_rows=result["document_rows"])
    # Retain evidence that exists only in an older generated table, including
    # columns whose original publisher/parser basis can no longer be proved.
    progress.report('archive_previous_tables')
    for label, key, data in (("filenames", FILENAMES, previous_bytes),
                             ("documents", DOCUMENTS, previous_documents)):
        if data is not None:
            saved = f"catalog-history/sha256/{sha256(data).hexdigest()}/{Path(key).name}"
            store.put(saved, data, immutable=True)
            result[f"previous_{label}_key"] = saved
    progress.report('publish_document_snapshot')
    result.update(publish_catalog(store, root / FILENAMES, root / DOCUMENTS, previous=snapshot))
    return {k: v for k, v in result.items() if k not in ("output", "documents_output")}
