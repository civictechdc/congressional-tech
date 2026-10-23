"""Explicit one-time adoption of investigated legacy Arrow checkpoints.

Local SQLite is temporary sorting space only. It contains no retained lifecycle
or application selection. Native completed candidates survive interruption; one
conditional raw selector publishes the complete prepared archive. The caller
retains and reviews exact input hashes, including any orphan receipt repairs,
before calling this boundary. Normal Archive startup never calls it.
"""
from copy import deepcopy
from hashlib import sha256, file_digest
from itertools import chain
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.partition_routing import key_hash
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, LEGACY_CAPTURE_SCHEMA
from congress_api.retention.raw_storage import BODY_FIELDS, BODY_SCHEMA, DELIVERY_ENTRIES, STATE_ORDER, STATE_KEY_FIELD, SELECTOR_BYTES, state_key
from congress_api.retention.raw_values import NATIVE_CAPTURE_SCHEMA, ORDER as CAPTURE_ORDER, capture_table
from congress_api.retention.raw_state_routes import summarize


def _digest(path):
    with Path(path).open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def _blob(row, schema):
    table = pa.Table.from_pylist([row], schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes(), table.nbytes


def _stage(db, kind, key, row, schema, order, *, replace=False):
    payload, size = _blob(row, schema)
    verb = 'INSERT OR REPLACE' if replace else 'INSERT'
    try:
        db.execute(f'{verb} INTO rows VALUES (?,?,?,?,?,?)',
                   (kind, key, key_hash(key), order, payload, size))
    except sqlite3.IntegrityError as error:
        raise ValueError('Duplicate investigated state URL') from error


def _leaves(db, kind, schema, max_rows, max_bytes, prefix=''):
    """Sort on disk and load at most one bounded native leaf at a time."""
    where = 'kind=? AND digest>=? AND digest<?'
    parameters = (kind, prefix, prefix + 'g')
    count, size = db.execute(f'SELECT count(*),coalesce(sum(bytes),0) FROM rows WHERE {where}', parameters).fetchone()
    if not count:
        return
    if count > max_rows or size > max_bytes:
        if count == 1:
            raise ValueError('A single adoption row exceeds the decoded-byte budget')
        if len(prefix) == 64:
            raise ValueError('SHA-256 collision exceeds the adoption partition budget')
        for char in '0123456789abcdef':
            yield from _leaves(db, kind, schema, max_rows, max_bytes, prefix + char)
        return
    batches = []
    for (payload,) in db.execute(f'SELECT payload FROM rows WHERE {where} ORDER BY ordinal,key', parameters):
        batches.extend(pa.ipc.open_stream(payload).read_all().to_batches())
    table = pa.Table.from_batches(batches, schema=schema)
    canonical = pa.Table.from_pylist(table.to_pylist(), schema=schema)
    if canonical.nbytes > max_bytes:
        raise ValueError('Adoption leaf exceeds its decoded-byte budget')
    yield prefix, canonical


def _qualified_candidate(storage, kind, table, *, operation, prefix, base_id):
    """Compare each bounded native result before retaining it for selection."""
    pin = storage._candidate(kind, table, operation=operation, prefix=prefix, base_id=base_id)
    capture = kind == 'captures'
    actual = storage._read_table(pin, len(table), schema=table.schema,
        max_rows=storage.max_capture_rows if capture else storage.max_state_rows,
        max_bytes=storage.max_capture_bytes if capture else storage.max_state_bytes,
        decoded_bytes=table.nbytes)
    order = CAPTURE_ORDER if capture else STATE_ORDER if kind == 'state' else 'key'
    if not actual.sort_by(order).equals(table.sort_by(order), check_metadata=True):
        raise ValueError(f'Adoption native values differ from investigated input: {kind}')
    return pin


def adopt_tables(storage, *, paths, sha256s, operation, filename_version=None,
                 before_publish=None, source_pins=None):
    """Adopt exact reviewed capture/state Parquet inputs, with one final CAS.

    Recreate sorting scratch on any host to resume. Candidate identities depend
    on the exact frozen inputs and operation; completed native Run calls reuse
    their native releases. There is no pending journal or local workspace copy.
    Row/Arrow-byte limits bound each admitted native table, not total process
    memory or the native reader's transport buffers.

    An explicit ``readings`` JSONL input qualifies the complete retained reading
    inventory in the same selection. Capture/state-only adoption preserves raw
    values but leaves body-reading qualification absent, so recurring readers
    cannot silently treat a missing inventory as empty.

    This lower-level local-input helper does not establish remote source
    authority. Operational adoption uses adopt_archive's source-version checks;
    supplied source pins also bind its completed delivery request here.
    """
    if not isinstance(operation, str) or not operation:
        raise ValueError('A stable adoption operation identity is required')
    if set(paths) not in ({'captures', 'state'}, {'captures', 'state', 'readings'}) or set(sha256s) != set(paths):
        raise ValueError('Adoption requires exact capture/state and optional explicit reading input pins')
    paths = {name: Path(path).resolve() for name, path in paths.items()}
    for name, path in paths.items():
        if _digest(path) != sha256s[name]:
            raise ValueError(f'Investigated adoption input digest changed: {name}')
    request_inputs = dict(inputs=sha256s, basis=storage.basis, filename_version=filename_version)
    if source_pins is not None:
        from .raw_adoption_inputs import raw_source_pins
        request_inputs['source_pins'] = raw_source_pins(source_pins)
    request = sha256(encoded(request_inputs)).hexdigest()
    base = storage.snapshot()
    completed = base.completed_delivery(operation)
    if completed is not None:
        if completed['request_id'] != request:
            raise ValueError('Completed adoption operation has different inputs')
        return type(base)(storage, base.manifest, base.version, completed)
    if base.version is not None:
        raise ValueError('Adoption requires an unselected native raw root')
    with pq.ParquetFile(paths['captures']) as captures, pq.ParquetFile(paths['state']) as states:
        if (not (captures.schema_arrow.equals(LEGACY_CAPTURE_SCHEMA, check_metadata=False)
                 or captures.schema_arrow.equals(CAPTURE_SCHEMA, check_metadata=False))
                or not states.schema_arrow.equals(storage.state_schema, check_metadata=True)):
            raise ValueError('Investigated adoption schemas differ from the frozen raw basis')
        # Retained immutable refs use the same bounded cache policy as catalog
        # adoption. A long one-time import does not cache all routing history.
        for pages in (storage.capture_pages, storage.state_routes, storage.delivery_routes,
                      storage.body_routes, storage.changes):
            pages.objects.max_cache_entries = 32
        with TemporaryDirectory(prefix='raw-adoption-') as scratch, sqlite3.connect(Path(scratch) / 'sort.sqlite') as db:
            db.execute('PRAGMA temp_store=FILE')
            db.execute('PRAGMA cache_size=-8192')
            db.execute('CREATE TABLE rows(kind TEXT,key TEXT,digest TEXT,ordinal INTEGER,payload BLOB,bytes INTEGER,PRIMARY KEY(kind,key))')
            db.execute('CREATE INDEX route ON rows(kind,digest)')
            manifest = deepcopy(base.manifest)
            if 'readings' in paths:
                from .raw_reading_inventory import stage_inventory
                stage_inventory(storage, db, paths['readings'])
            # Validate all input state keys and single-row budgets before any
            # remote candidate is prepared. Extras retain their Arrow types.
            ordinal = 0
            for batch in states.iter_batches(batch_size=min(256, storage.max_state_rows)):
                for row in batch.to_pylist():
                    key = state_key(row['url'])
                    native = {STATE_ORDER: ordinal, STATE_KEY_FIELD: key, **row}
                    _stage(db, 'state', key, native, storage.state_native_schema, ordinal)
                    storage._adjust_state_counts(manifest['state_counts'], row, 1)
                    ordinal += 1
            manifest['state']['rows'] = ordinal
            if db.execute("SELECT 1 FROM rows WHERE kind='state' AND bytes>? LIMIT 1", (storage.max_state_bytes,)).fetchone():
                raise ValueError('A single adoption row exceeds the decoded-byte budget')
            position, head, pending = 0, None, []
            for source in captures.iter_batches(batch_size=storage.max_capture_rows):
                incoming = capture_table(pa.Table.from_batches([source]), first_order=position)
                for _, batch in storage._capture_batches(incoming):
                    canonical = pa.Table.from_pylist(batch.to_pylist(), schema=NATIVE_CAPTURE_SCHEMA)
                    pin = _qualified_candidate(storage, 'captures', canonical, operation=operation,
                                               prefix=str(position), base_id=request)
                    receipts = sorted({key for key in canonical['receipt_key'].to_pylist() if key})
                    pending.append(dict(release=pin, rows=len(canonical), decoded_bytes=canonical.nbytes,
                                        receipt_keys=receipts, first_order=position))
                    if len(pending) == 64:
                        head = storage.capture_pages.append(head, pending)
                        pending = []
                    for row in canonical.to_pylist():
                        for receipt in [row['receipt_key']] if row['receipt_key'] else []:
                            key = key_hash('receipt:' + receipt)
                            db.execute('INSERT OR IGNORE INTO rows VALUES (?,?,?,?,?,?)',
                                       ('receipt', key, key_hash(key), 0, b'', 0))
                        if row['body_key']:
                            info = {name: row[name] for name in BODY_FIELDS}
                            key = 'body:' + row['body_key']
                            existing = db.execute("SELECT payload FROM rows WHERE kind='body' AND key=?", (key,)).fetchone()
                            if existing is None or row['sha256']:
                                _stage(db, 'body', key, dict(key=key, **info), BODY_SCHEMA, position, replace=True)
                            if row['sha256']:
                                key = 'sha:' + row['sha256']
                                _stage(db, 'body', key, dict(key=key, **info), BODY_SCHEMA, position, replace=True)
                    position += len(canonical)
            if pending:
                head = storage.capture_pages.append(head, pending)
            manifest['captures'] = dict(head=head, rows=position)
            manifest['filename_version'] = filename_version
            for kind, schema, routes, native_kind in (
                    ('state', storage.state_native_schema, storage.state_routes, 'state'),
                    ('body', BODY_SCHEMA, storage.body_routes, 'bodies')):
                def references():
                    for prefix, table in _leaves(db, kind, schema, storage.max_state_rows, storage.max_state_bytes):
                        pin = _qualified_candidate(storage, native_kind, table, operation=operation,
                                                   prefix=prefix, base_id=request)
                        reference = dict(release=pin, rows=len(table), decoded_bytes=table.nbytes)
                        if kind == 'state':
                            reference['schedule'] = summarize(table.to_pylist())
                        yield prefix, reference
                stream = iter(references())
                first = next(stream, None)
                root = routes.replace_stream(None, '', chain([first], stream)) if first is not None else None
                if kind == 'state':
                    manifest['state']['root'] = root
                else:
                    count = db.execute("SELECT count(*) FROM rows WHERE kind='body' AND key LIKE 'body:%'").fetchone()[0]
                    manifest['bodies'] = dict(root=root, count=count)
            if 'readings' in paths:
                from .raw_reading_inventory import select_inventory
                manifest['readings'] = dict(root=select_inventory(storage, db), qualified=True)
            delivery = dict(request=request, request_id=request, capture_rows=position, first_order=0, result=None)
            # This directory contains completed delivery/receipt membership only.
            # Native completion remains exclusively owned by DocSpec.
            key = key_hash('delivery:' + operation)
            db.execute('INSERT INTO rows VALUES (?,?,?,?,?,?)', ('receipt', key, key_hash(key), 0, b'', 0))
            membership_schema = pa.schema([('key', pa.string())])
            for key, in db.execute("SELECT key FROM rows WHERE kind='receipt'"):
                _stage(db, 'membership', key, dict(key=key), membership_schema, 0)
            def memberships():
                for prefix, table in _leaves(db, 'membership', membership_schema, DELIVERY_ENTRIES, 1 << 19):
                    yield prefix, dict(entries={key: delivery for key in table['key'].to_pylist()})
            manifest['deliveries'] = storage.delivery_routes.replace_stream(None, '', memberships())
            urls = (pa.ipc.open_stream(payload).read_all()['url'][0].as_py() for payload, in
                    db.execute("SELECT payload FROM rows WHERE kind='state' ORDER BY ordinal"))
            from .raw_reading_inventory import inventory_references
            manifest['change'] = storage.changes.put(base, manifest, urls,
                reading_parts=inventory_references(db) if 'readings' in paths else ())
            data = encoded(manifest)
            if len(data) > SELECTOR_BYTES:
                raise ValueError('Raw adoption selector exceeds the byte budget')
            # Recheck retained inputs before selecting the archive. A changed
            # source can leave only unselected native candidates, never a root.
            for name, path in paths.items():
                if _digest(path) != sha256s[name]:
                    raise ValueError(f'Investigated adoption input digest changed: {name}')
            if before_publish is not None:
                before_publish()
            return storage.publish(dict(base=base, manifest=manifest, data=data,
                                        changed=True, delivery=delivery))


def adopt_archive(storage, *, paths, sha256s, operation, directory, filename_version=None,
                  source_pins=None):
    """Compose exact source reading preparation with the maintained bounded owner.

    Capture/state files and hashes are the caller's investigated inputs. Reading
    inputs come only from the same store's exact legacy cache and immutable parts.
    No LegacyArchiveSeed reconstruction or compatibility writer is involved.
    Remote storage requires exact source pins. Local fixture inputs may omit
    them and therefore establish no remote source authority. Version checks
    detect drift; legacy writers must remain quiescent through final cutover.
    """
    if set(paths) != {'captures', 'state'} or set(sha256s) != set(paths):
        raise ValueError('Complete raw adoption requires investigated capture/state inputs')
    if not isinstance(operation, str) or not operation:
        raise ValueError('A stable adoption operation identity is required')
    from .raw_adoption_inputs import raw_source_pins, verify_raw_sources
    source_pins = raw_source_pins(source_pins)
    if source_pins is None and getattr(storage.store, 'bucket', None) is not None:
        raise ValueError('Operational raw adoption requires exact capture/state source pins')
    for name, path in paths.items():
        if _digest(path) != sha256s[name]:
            raise ValueError(f'Investigated adoption input digest changed: {name}')
    base = storage.snapshot()
    completed = base.completed_delivery(operation)
    if base.version is not None and completed is None:
        raise ValueError('Adoption requires an unselected native raw root')
    if completed is None:
        verify_raw_sources(storage.store, source_pins)
    from .raw_adoption_inputs import prepare_reading_input, verify_reading_sources
    reading_path, receipt = prepare_reading_input(storage.store, directory=directory)
    if completed is None:
        verify_reading_sources(storage.store, receipt)
    def before_publish():
        verify_reading_sources(storage.store, receipt)
        verify_raw_sources(storage.store, source_pins)
    return adopt_tables(storage, paths={**paths, 'readings': reading_path},
        sha256s={**sha256s, 'readings': receipt['input']['sha256']}, operation=operation,
        filename_version=filename_version, source_pins=source_pins,
        before_publish=before_publish)
