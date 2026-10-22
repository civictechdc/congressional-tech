"""Coherent raw capture/state selection over immutable native source candidates.

DocSpec owns records, versions and completed work. The application selects exact
completed native pins through one conditional root; losing candidates remain
unselected. Captures append as ordered batches. Only changed URL-state leaves
are reconstructed, and a full leaf splits locally through immutable routing.
"""
from copy import deepcopy
import base64
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.body_keys import (
    body_key_digest,
    body_object_digest,
    is_pdf_bytes,
    is_pdf_format,
    physical_body_object_key,
    quarantine_body_key,
)
from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.partition_routing import RoutingPages, split_partition, key_hash
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_capture_pages import CapturePages
from congress_api.retention.raw_changes import RawChanges
from congress_api.retention.raw_state_routes import StateRoutes, summarize, schedule_basis
from congress_api.retention.raw_values import capture_table, ordered_captures, NATIVE_CAPTURE_SCHEMA
from congress_api.retention.write_recovery import reconcile_lost_acknowledgment

DEFAULT_ACCEPTED_FILES_PATH = (
    Path(__file__).resolve().parents[5]
    / 'apps'
    / 'site'
    / 'src'
    / 'data'
    / 'deferred-body-reviews'
    / 'accepted-files.json'
)


class ExcludedBodyError(PermissionError, ValueError):
    """Raised when a deferred-body review exclusion blocks ingest or publication."""

    def __init__(self, sha256_hex, *, body_key=None, quarantine_key=None):
        self.sha256 = sha256_hex
        self.body_key = body_key or f'bodies/sha256/{sha256_hex[:2]}/{sha256_hex}.gz'
        self.quarantine_key = quarantine_key or quarantine_body_key(sha256_hex)
        super().__init__(
            f'Excluded body SHA-256 {sha256_hex} blocked by deferred-body gate '
            f'(quarantine: {self.quarantine_key})'
        )


def _extract_excluded_digests(item):
    digests = set()
    if isinstance(item, str):
        digest = body_object_digest(item.lower())
        if digest:
            digests.add(digest)
        return digests
    if not isinstance(item, dict):
        return digests
    decision = item.get('decision')
    # In accepted-files.json (--deferred list), rows without an explicit "accept" decision
    # or with decision == "exclude" supply excluded sha256 / body_key values.
    if decision in (None, 'exclude'):
        for field in ('sha256', 'body_key', 'stored_sha256'):
            raw_val = item.get(field)
            if isinstance(raw_val, str):
                digest = body_object_digest(raw_val.lower())
                if digest:
                    digests.add(digest)
    zip_check = item.get('zip_Check') or {}
    for member in zip_check.get('members') or ():
        if isinstance(member, dict) and (decision == 'exclude' or member.get('decision') in (None, 'exclude')):
            for field in ('sha256', 'body_key'):
                raw_val = member.get(field)
                if isinstance(raw_val, str):
                    digest = body_object_digest(raw_val.lower())
                    if digest:
                        digests.add(digest)
    for member in item.get('members') or ():
        digests.update(_extract_excluded_digests(member))
    return digests


def load_excluded_body_hashes(source=None):
    """Load excluded SHA-256 digests from accepted-files.json or an explicit collection."""
    if source is None:
        source = DEFAULT_ACCEPTED_FILES_PATH
        if not source.is_file():
            return frozenset()
    if isinstance(source, (set, frozenset, list, tuple)):
        digests = set()
        for item in source:
            digests.update(_extract_excluded_digests(item))
        return frozenset(digests)
    if isinstance(source, Path):
        if not source.is_file():
            raise FileNotFoundError(f'Deferred-body exclusion file not found: {source}')
        payload = json.loads(source.read_text(encoding='utf-8'))
    elif isinstance(source, str):
        path = Path(source)
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8'))
        else:
            payload = json.loads(source)
    elif isinstance(source, (bytes, bytearray)):
        payload = json.loads(bytes(source).decode('utf-8'))
    elif isinstance(source, dict):
        payload = source
    else:
        raise ValueError('Unsupported excluded body hash source')

    if isinstance(payload, list):
        excluded = set()
        for item in payload:
            excluded.update(_extract_excluded_digests(item))
        return frozenset(excluded)

    excluded = set()
    for raw_digest in payload.get('excluded_sha256') or ():
        excluded.update(_extract_excluded_digests(raw_digest))
    for entry in payload.get('files') or payload.get('deferred') or ():
        excluded.update(_extract_excluded_digests(entry))
    return frozenset(excluded)


def enforce_body_ingest_gate(
    store,
    key_or_sha256,
    data=None,
    *,
    excluded_hashes=None,
    content_type_or_format=None,
    is_pdf=None,
    quarantine=True,
):
    """Block excluded SHA-256 digests and optionally quarantine their payload."""
    digest = body_object_digest(key_or_sha256)
    if digest is None and isinstance(data, (bytes, bytearray, memoryview)):
        digest = sha256(bytes(data)).hexdigest()
    if digest is None:
        raise ValueError(f'Invalid retained body key or SHA-256 digest: {key_or_sha256!r}')
    active = (
        load_excluded_body_hashes(excluded_hashes)
        if excluded_hashes is not None and not isinstance(excluded_hashes, frozenset)
        else excluded_hashes
    )
    if active is None:
        store_exclusions = getattr(store, 'excluded_body_hashes', None) if store is not None else None
        active = (
            load_excluded_body_hashes(store_exclusions)
            if store_exclusions is not None and not isinstance(store_exclusions, frozenset)
            else (store_exclusions or frozenset())
        )
    if digest in active:
        pdf_flag = (
            is_pdf
            if is_pdf is not None
            else (
                is_pdf_bytes(data)
                if isinstance(data, (bytes, bytearray, memoryview))
                else is_pdf_format(content_type_or_format)
            )
        )
        q_key = quarantine_body_key(digest, is_pdf=bool(pdf_flag))
        if quarantine and data is not None and store is not None and hasattr(store, 'put'):
            raw_bytes = bytes(data)
            if pdf_flag:
                if raw_bytes[:2] == b'\x1f\x8b':
                    try:
                        raw_bytes = gzip.decompress(raw_bytes)
                    except OSError:
                        pass
                store.put(q_key, raw_bytes, immutable=True)
            else:
                compressed = (
                    raw_bytes
                    if raw_bytes[:2] == b'\x1f\x8b'
                    else gzip.compress(raw_bytes, compresslevel=1, mtime=0)
                )
                store.put(q_key, compressed, immutable=True)
        raise ExcludedBodyError(
            digest,
            body_key=f'bodies/sha256/{digest[:2]}/{digest}.gz',
            quarantine_key=q_key,
        )
    return digest


def store_public_body(store, data, *, content_type_or_format=None, excluded_hashes=None):
    """Store a public body (.pdf uncompressed, non-PDF .gz) while preserving logical .gz body_key."""
    raw_bytes = bytes(data)
    digest = sha256(raw_bytes).hexdigest()
    logical_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    pdf_flag = is_pdf_bytes(raw_bytes) or is_pdf_format(content_type_or_format)
    enforce_body_ingest_gate(
        store,
        logical_key,
        raw_bytes,
        excluded_hashes=excluded_hashes,
        content_type_or_format=content_type_or_format,
        is_pdf=pdf_flag,
        quarantine=True,
    )
    physical_key = physical_body_object_key(logical_key, content_type_or_format, is_pdf=pdf_flag)
    if pdf_flag:
        if hasattr(store, 'put_pdf_body'):
            store.put_pdf_body(physical_key, raw_bytes)
        else:
            store.put(physical_key, raw_bytes, immutable=True)
        return dict(
            body_key=logical_key,
            physical_key=physical_key,
            sha256=digest,
            bytes=len(raw_bytes),
            stored_sha256=digest,
            stored_bytes=len(raw_bytes),
            is_pdf=True,
        )
    compressed = gzip.compress(raw_bytes, compresslevel=1, mtime=0)
    store.put(physical_key, compressed, immutable=True)
    return dict(
        body_key=logical_key,
        physical_key=physical_key,
        sha256=digest,
        bytes=len(raw_bytes),
        stored_sha256=sha256(compressed).hexdigest(),
        stored_bytes=len(compressed),
        is_pdf=False,
    )


def migrate_pdf_bodies_to_uncompressed(store, *, keys=None, delete_gzip=False, excluded_hashes=None):
    """Idempotently decompress retained PDF bodies (and ZIP-member PDFs) to bodies/sha256/<xx>/<sha256>.pdf."""
    from congress_api.retention.archive_members import ArchiveReadError, ZipLimits, is_office_zip, iter_archive_members

    active_exclusions = (
        load_excluded_body_hashes(excluded_hashes)
        if excluded_hashes is not None
        else load_excluded_body_hashes(getattr(store, 'excluded_body_hashes', frozenset()))
    )
    candidate_keys = list(keys) if keys is not None else sorted(store.keys('bodies/sha256/'))
    migrated_pdfs = []
    migrated_zip_member_pdfs = []
    already_present = []
    skipped_non_pdf = []
    excluded_skipped = []

    def _object_exists(target_key):
        if hasattr(store, 'version'):
            try:
                if store.version(target_key) != 'missing':
                    return True
            except Exception:
                pass
        return store.read(target_key) is not None

    for key in candidate_keys:
        digest = body_key_digest(key)
        if digest is None:
            continue
        if digest in active_exclusions:
            excluded_skipped.append(key)
            continue
        pdf_key = physical_body_object_key(key, is_pdf=True)
        if _object_exists(pdf_key):
            already_present.append(pdf_key)
            if delete_gzip and hasattr(store, 'delete'):
                store.delete(key)
            continue
        compressed = store.read(key)
        if compressed is None:
            continue
        raw_bytes = gzip.decompress(compressed) if compressed[:2] == b'\x1f\x8b' else compressed
        if sha256(raw_bytes).hexdigest() != digest:
            raise ValueError(f'Retained body checksum mismatch during PDF migration: {key}')
        if is_pdf_bytes(raw_bytes):
            if hasattr(store, 'put_pdf_body'):
                store.put_pdf_body(pdf_key, raw_bytes)
            else:
                store.put(pdf_key, raw_bytes, immutable=True)
            migrated_pdfs.append(pdf_key)
            if delete_gzip and hasattr(store, 'delete'):
                store.delete(key)
            continue
        if raw_bytes.startswith((b'PK\x03\x04', b'PK\x05\x06')) and not is_office_zip(raw_bytes, limits=ZipLimits()):
            try:
                for member in iter_archive_members(raw_bytes, archive_path=key, limits=ZipLimits()):
                    if member.data is not None and is_pdf_bytes(member.data):
                        member_digest = sha256(member.data).hexdigest()
                        if member_digest in active_exclusions:
                            excluded_skipped.append(f'bodies/sha256/{member_digest[:2]}/{member_digest}.gz')
                            continue
                        member_pdf_key = physical_body_object_key(member_digest, is_pdf=True)
                        if _object_exists(member_pdf_key):
                            if member_pdf_key not in already_present:
                                already_present.append(member_pdf_key)
                            continue
                        if hasattr(store, 'put_pdf_body'):
                            store.put_pdf_body(member_pdf_key, member.data)
                        else:
                            store.put(member_pdf_key, member.data, immutable=True)
                        migrated_zip_member_pdfs.append(member_pdf_key)
                        migrated_pdfs.append(member_pdf_key)
            except ArchiveReadError:
                pass
        skipped_non_pdf.append(key)

    return dict(
        migrated_pdfs=migrated_pdfs,
        migrated_zip_member_pdfs=migrated_zip_member_pdfs,
        already_present=already_present,
        skipped_non_pdf=skipped_non_pdf,
        excluded_skipped=excluded_skipped,
    )

RAW_KEY = 'indexes/raw.json'
STATE_ORDER = '_state_order'
STATE_KEY_FIELD = '_state_key'
STATE_KEY_SHA256_FIELD = 'state_key_sha256'
STATE_BUCKET_COUNT = 64

def state_key(url):
    return 'null:' if url is None else 'url:' + url

def state_key_sha256(url):
    """Return a deterministic 64-byte lowercase hex SHA-256 of ``state_key(url)`` (< 128B for Parquet stats)."""
    return sha256(state_key(url).encode('utf-8')).hexdigest()

from .docspec import PartitionSpec, UpdateMergeSpec, UpdateMergeStrategy, apply_update_merge_spec

STATE_PARTITION_SPEC = PartitionSpec.bucket(STATE_KEY_SHA256_FIELD, STATE_BUCKET_COUNT)

STATE_MERGE_SPEC = UpdateMergeSpec(
    order_by='checked_at',
    columns={
        'outcome': UpdateMergeStrategy.REPLACE,
        'attempts': UpdateMergeStrategy.MAX,
        'http_status': UpdateMergeStrategy.REPLACE,
        'error': UpdateMergeStrategy.REPLACE,
        'checked_at': UpdateMergeStrategy.MAX,
        'next_attempt_at': UpdateMergeStrategy.REPLACE,
        'body_key': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'sha256': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'media_type': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'fidelity': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'retrieved_at': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'receipt_key': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'receipt_line': UpdateMergeStrategy.LATEST_OR_BACKFILL,
        'links_scanned': UpdateMergeStrategy.SET_UNION,
    },
)

STATE_NATIVE_SCHEMA = pa.schema([pa.field(STATE_ORDER, pa.int64(), nullable=False),
                               pa.field(STATE_KEY_FIELD, pa.string(), nullable=False), *STATE_SCHEMA])
STATE_PARTITIONED_SCHEMA = pa.schema([
    pa.field(STATE_ORDER, pa.int64(), nullable=False),
    pa.field(STATE_KEY_FIELD, pa.string(), nullable=False),
    pa.field(STATE_KEY_SHA256_FIELD, pa.string(), nullable=False),
    *STATE_SCHEMA,
])


def _merge_states(existing, incoming, *, merge_spec=STATE_MERGE_SPEC, state_schema=None, deletions=None):
    """Merge URL-state rows keyed by 64-byte ``state_key_sha256`` using ``UpdateMergeSpec(order_by='checked_at')``."""
    existing_rows = existing.to_pylist() if isinstance(existing, pa.Table) else [dict(r) for r in existing]
    incoming_rows = incoming.to_pylist() if isinstance(incoming, pa.Table) else [dict(r) for r in incoming]
    if state_schema is None:
        all_keys = {k for r in existing_rows + incoming_rows for k in r}
        extra_fields = [
            pa.field(k, pa.string(), nullable=True)
            for k in sorted(all_keys - set(STATE_SCHEMA.names) - {STATE_ORDER, STATE_KEY_FIELD, STATE_KEY_SHA256_FIELD})
            if not k.startswith('__docspec_supplied_')
        ]
        # Infer types for common extra test fields like media_type, fidelity, retrieved_at
        state_schema = pa.schema([*STATE_SCHEMA, *extra_fields])
    next_order = max((int(r.get(STATE_ORDER, -1)) for r in existing_rows if r.get(STATE_ORDER) is not None), default=-1) + 1
    order_by_sha = {}
    prepared_existing = []
    for idx, r in enumerate(existing_rows):
        row = dict(r)
        for field in state_schema:
            row.setdefault(field.name, None)
        row.setdefault(STATE_KEY_FIELD, state_key(row.get('url')))
        row.setdefault(STATE_KEY_SHA256_FIELD, state_key_sha256(row.get('url')))
        if STATE_ORDER not in row or row[STATE_ORDER] is None:
            row[STATE_ORDER] = idx
            next_order = max(next_order, idx + 1)
        order_by_sha[row[STATE_KEY_SHA256_FIELD]] = row[STATE_ORDER]
        prepared_existing.append(row)
    prepared_incoming = []
    for r in incoming_rows:
        row = dict(r)
        for field in state_schema:
            row.setdefault(field.name, None)
        row.setdefault(STATE_KEY_FIELD, state_key(row.get('url')))
        sha = row.setdefault(STATE_KEY_SHA256_FIELD, state_key_sha256(row.get('url')))
        if sha in order_by_sha:
            row[STATE_ORDER] = order_by_sha[sha]
        elif STATE_ORDER not in row or row[STATE_ORDER] is None:
            row[STATE_ORDER] = next_order
            order_by_sha[sha] = next_order
            next_order += 1
        prepared_incoming.append(row)
    norm_spec = UpdateMergeSpec.normalize(merge_spec) if merge_spec is not None else {'order_by': None, 'columns': {}}
    active_cols = {
        k: v
        for k, v in norm_spec.get('columns', {}).items()
        if k in state_schema.names
    }
    effective_spec = UpdateMergeSpec(
        order_by=(
            norm_spec.get('order_by')
            if norm_spec.get('order_by') in state_schema.names
            else None
        ),
        columns={STATE_ORDER: UpdateMergeStrategy.MIN, **active_cols},
    )
    part_schema = pa.schema([
        pa.field(STATE_ORDER, pa.int64(), nullable=False),
        pa.field(STATE_KEY_FIELD, pa.string(), nullable=False),
        pa.field(STATE_KEY_SHA256_FIELD, pa.string(), nullable=False),
        *state_schema,
    ])
    return apply_update_merge_spec(
        pa.Table.from_pylist(prepared_existing, schema=part_schema),
        pa.Table.from_pylist(prepared_incoming, schema=part_schema),
        keys=[STATE_KEY_SHA256_FIELD],
        merge=effective_spec,
        deletions=deletions,
    )
CAPTURE_BATCH_ROWS = 1000
CAPTURE_BATCH_BYTES = 16 << 20
DELIVERY_ENTRIES = 128
SELECTOR_BYTES = 1 << 20
BODY_FIELDS = ['body_key', 'sha256', 'bytes', 'stored_sha256', 'stored_bytes']
BODY_SCHEMA = pa.schema([pa.field('key', pa.string(), nullable=False),
                         *(CAPTURE_SCHEMA.field(name) for name in BODY_FIELDS)])



class RawSnapshot:
    def __init__(self, owner, manifest, version, delivery=None):
        self.owner, self.manifest, self.version = owner, manifest, version
        self.delivery = delivery
        self._body_leaf = None

    def capture_batch(self, entry):
        """Read one exact changed batch, retaining stable observation ordinals."""
        stored = self.owner._read_table(entry['release'], entry['rows'],
            schema=NATIVE_CAPTURE_SCHEMA, max_rows=self.owner.max_capture_rows,
            max_bytes=self.owner.max_capture_bytes, decoded_bytes=entry['decoded_bytes'])
        expected = list(range(entry['first_order'], entry['first_order'] + entry['rows']))
        if sorted(stored['_capture_order'].to_pylist()) != expected:
            raise ValueError('Selected capture batch order mismatch')
        return stored.take(pc.sort_indices(stored['_capture_order']))

    def captures(self):
        tables = [ordered_captures(self.capture_batch(entry)) for entry in
                  self.owner.capture_pages.entries(self.manifest['captures']['head'])]
        result = pa.concat_tables(tables) if tables else pa.Table.from_pylist([], schema=CAPTURE_SCHEMA)
        if len(result) != self.manifest['captures']['rows']:
            raise ValueError('Selected capture count mismatch')
        return result

    @property
    def identity(self):
        return sha256(encoded(self.manifest)).hexdigest()

    @property
    def state_counts(self):
        return deepcopy(self.manifest['state_counts'])

    @property
    def body_count(self):
        return self.manifest['bodies']['count']

    def body_info(self, digest):
        _, reference = self.owner.body_routes.lookup(self.manifest['bodies']['root'], 'sha:' + digest)
        if reference is None:
            return None
        identity = reference['release']['id']
        if self._body_leaf is None or self._body_leaf[0] != identity:
            self._body_leaf = identity, self.owner._read_bodies(reference)
        table = self._body_leaf[1]
        selected = table.filter(pc.equal(table['key'], 'sha:' + digest)).select(BODY_FIELDS)
        return selected.to_pylist()[0] if len(selected) else None

    def _reading_inventory(self):
        inventory = self.manifest.get('readings')
        if inventory is not None and (not isinstance(inventory, dict)
                or set(inventory) != {'root', 'qualified'} or type(inventory.get('qualified')) is not bool):
            raise ValueError('Invalid retained reading qualification')
        if inventory is None or not inventory['qualified']:
            raise RuntimeError('Retained reading inventory requires explicit qualification')
        return inventory

    def has_body_reading(self, body_key):
        return self.owner.readings.lookup(self._reading_inventory()['root'], body_key) is not None

    def body_readings(self, body_keys):
        yield from self.owner.readings.rows(self._reading_inventory()['root'], body_keys)

    def completed_delivery(self, operation):
        key, _, entries = self.owner._delivery(self.manifest['deliveries'], 'delivery:' + operation)
        return entries.get(key)

    def state_candidates(self, *, outcomes, now=None, urls=None, invalid_only=False):
        yield from self.owner.state_routes.candidates(self, outcomes=outcomes, now=now, urls=urls, invalid_only=invalid_only)

    def states_for(self, urls):
        groups = {}
        for url in dict.fromkeys(urls):
            _, reference = self.owner.state_routes.lookup(self.manifest['state']['root'], state_key(url))
            if reference is not None:
                identity = reference['release']['id']
                groups.setdefault(identity, (reference, set()))[1].add(url)
        result = {}
        for reference, requested in groups.values():
            for row in self.owner._read_states(reference).select(self.owner.state_schema.names).to_pylist():
                if row['url'] in requested:
                    result[row['url']] = row
        return result

    def iter_states_for(self, urls):
        """Stream exact selected native rows in their immutable state order.

        Requested URLs, routed leaves and output ordering stay on disposable
        SQLite. Only one qualified state leaf is decoded at a time. Native
        order/key fields remain available to callers that stage logical rows.
        """
        from contextlib import closing
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import pickle
        from .catalog_staging import WorkingCatalog
        with TemporaryDirectory(prefix='raw-requested-state-') as directory, closing(
                WorkingCatalog(Path(directory) / 'states.sqlite')) as work:
            db = work.connection
            db.executescript('CREATE TABLE requested(identity TEXT PRIMARY KEY); '
                'CREATE TABLE leaves(identity TEXT PRIMARY KEY,value BLOB); '
                'CREATE TABLE rows(ordinal INTEGER PRIMARY KEY,value BLOB);')
            for url in urls:
                key = state_key(url)
                if not db.execute('INSERT OR IGNORE INTO requested VALUES (?)', (key,)).rowcount:
                    continue
                _, reference = self.owner.state_routes.lookup(self.manifest['state']['root'], key)
                if reference is not None:
                    db.execute('INSERT OR IGNORE INTO leaves VALUES (?,?)',
                               (reference['release']['id'], pickle.dumps(reference)))
            for payload, in db.execute('SELECT value FROM leaves ORDER BY identity'):
                for row in self.owner._read_states(pickle.loads(payload)).to_pylist():
                    if db.execute('SELECT 1 FROM requested WHERE identity=?', (row[STATE_KEY_FIELD],)).fetchone():
                        db.execute('INSERT INTO rows VALUES (?,?)', (row[STATE_ORDER], pickle.dumps(row)))
            for payload, in db.execute('SELECT value FROM rows ORDER BY ordinal'):
                yield pickle.loads(payload)

    def has_receipt(self, key):
        hashed, _, entries = self.owner._delivery(self.manifest['deliveries'], 'receipt:' + key)
        return hashed in entries

    def changes_since(self, identity):
        return self.owner.changes.since(self, identity)

    def changed_capture_batches(self, change):
        return self.owner.capture_pages.entries_since(change['capture_head'], change['capture_start'])

    def changed_reading_parts(self, change):
        return self.owner.changes.reading_parts(change)

    def changed_state_urls(self, change):
        return self.owner.changes.state_urls(change)

    def receipt_keys(self):
        return {key for entry in self.owner.capture_pages.entries(self.manifest['captures']['head'])
                for key in entry['receipt_keys']}

    def states(self):
        tables = [self.owner._read_states(value) for _, value in
                  self.owner.state_routes.leaf_items(self.manifest['state']['root'])]
        if not tables:
            return pa.Table.from_pylist([], schema=self.owner.state_schema)
        combined = pa.concat_tables(tables)
        order = combined[STATE_ORDER]
        if (order.null_count or pc.count_distinct(order).as_py() != len(combined)
                or sorted(order.to_pylist()) != list(range(self.manifest['state']['rows']))):
            raise ValueError('Selected URL-state order or count mismatch')
        return combined.take(pc.sort_indices(order)).select(self.owner.state_schema.names).cast(self.owner.state_schema)

    def state(self, url):
        _, reference = self.owner.state_routes.lookup(self.manifest['state']['root'], state_key(url))
        if reference is None:
            return None
        table = self.owner._read_states(reference)
        mask = pc.is_null(table['url']) if url is None else pc.equal(table['url'], url)
        selected = table.filter(mask).select(self.owner.state_schema.names)
        return selected.to_pylist()[0] if len(selected) else None

    def state_supplied(self, url):
        """Read one URL-state row including native ``__docspec_supplied_*`` provenance flags."""
        _, reference = self.owner.state_routes.lookup(self.manifest['state']['root'], state_key(url))
        if reference is None:
            return None
        with self.owner.native.source_batches(reference['release']) as reader:
            raw_table = pa.Table.from_batches(list(reader), schema=reader.schema)
        mask = pc.is_null(raw_table['url']) if url is None else pc.equal(raw_table['url'], url)
        selected = raw_table.filter(mask)
        return selected.to_pylist()[0] if len(selected) else None


class RawStorage:
    def __init__(self, store, native, *, max_state_rows=8192, max_state_bytes=16 << 20,
                 max_capture_rows=CAPTURE_BATCH_ROWS, max_capture_bytes=CAPTURE_BATCH_BYTES,
                 state_schema=STATE_SCHEMA, excluded_body_hashes=None,
                 deferred_exclusions_path=None):
        self.store, self.native = store, native
        if deferred_exclusions_path is not None:
            self.excluded_body_hashes = load_excluded_body_hashes(deferred_exclusions_path)
        elif excluded_body_hashes is not None:
            self.excluded_body_hashes = load_excluded_body_hashes(excluded_body_hashes)
        else:
            store_exclusions = getattr(store, 'excluded_body_hashes', None)
            self.excluded_body_hashes = (
                load_excluded_body_hashes(store_exclusions)
                if store_exclusions is not None
                else frozenset()
            )
        if (not isinstance(state_schema, pa.Schema) or 'url' not in state_schema.names
                or state_schema.field('url').type != pa.string()
                or {STATE_ORDER, STATE_KEY_FIELD} & set(state_schema.names)):
            raise ValueError('Raw state schema requires a string URL and no reserved ordinal')
        self.state_schema = state_schema
        self.state_native_schema = pa.schema([pa.field(STATE_ORDER, pa.int64(), nullable=False),
            pa.field(STATE_KEY_FIELD, pa.string(), nullable=False), *state_schema])
        self.max_state_rows, self.max_state_bytes = max_state_rows, max_state_bytes
        self.max_capture_rows, self.max_capture_bytes = max_capture_rows, max_capture_bytes
        if min(max_state_rows, max_state_bytes, max_capture_rows, max_capture_bytes) < 1:
            raise ValueError("Raw storage budgets must be positive")
        self.capture_pages = CapturePages(store)
        self.state_routes = StateRoutes(store)
        self.delivery_routes = RoutingPages(store, 'raw-deliveries-v1')
        self.changes = RawChanges(store)
        self.body_routes = RoutingPages(store, 'raw-bodies-v1')
        from congress_api.retention.raw_readings import RawReadings
        self.readings = RawReadings(store)
        self.basis = dict(values='raw-native-v1', routing='sha256-utf8-prefix-v1', state_keys='nullable-url-v1', counts='raw-state-counts-v1', readings='body-part-refs-v1', schedule=schedule_basis(),
                          max_state_rows=max_state_rows, max_state_bytes=max_state_bytes,
                          max_capture_rows=max_capture_rows, max_capture_bytes=max_capture_bytes,
                          state_schema=base64.b64encode(state_schema.serialize()).decode("ascii"))

    def put_body(self, data, *, content_type_or_format=None):
        """Retain a body through the deferred-body exclusion gate and public PDF storage rule."""
        return store_public_body(
            self.store,
            data,
            content_type_or_format=content_type_or_format,
            excluded_hashes=self.excluded_body_hashes,
        )

    def migrate_pdf_bodies(self, *, keys=None, delete_gzip=False):
        """Idempotently migrate retained PDF bodies to uncompressed .pdf objects."""
        return migrate_pdf_bodies_to_uncompressed(
            self.store,
            keys=keys,
            delete_gzip=delete_gzip,
            excluded_hashes=self.excluded_body_hashes,
        )

    @classmethod
    def open(cls, store, native):
        """Reopen an exact selected logical schema; never infer legacy adoption.

        Resource budgets remain the maintained defaults. A selected archive with
        different budgets requires explicit construction with that frozen basis.
        """
        return cls.from_selection(store, native, store.read(RAW_KEY))

    @classmethod
    def from_selection(cls, store, native, raw):
        """Construct a reader for captured exact selector bytes without rereading latest."""
        if raw is None:
            return cls(store, native)
        if len(raw) > SELECTOR_BYTES:
            raise ValueError('Raw selector exceeds the byte budget')
        manifest = json.loads(raw)
        schema_bytes = base64.b64decode(manifest['basis']['state_schema'], validate=True)
        schema = pa.ipc.read_schema(pa.BufferReader(schema_bytes))
        owner = cls(store, native, state_schema=schema)
        if manifest['version'] != 1 or manifest['basis'] != owner.basis:
            raise ValueError('Raw selector basis changed; explicit adoption is required')
        return owner

    def _empty(self):
        return dict(version=1, basis=deepcopy(self.basis), captures=dict(head=None, rows=0),
                    state=dict(root=None, rows=0), bodies=dict(root=None, count=0),
                    deliveries=None, filename_version=None, change=None,
                    state_counts=dict(url_outcomes={}, urls_by_source_family={}, excluded_media_urls=0),
                    readings=dict(root=None, qualified=False))

    @property
    def empty_identity(self):
        """Identity of the proven empty archive under this frozen raw basis."""
        return sha256(encoded(self._empty())).hexdigest()

    def _read_selector(self):
        raw = self.store.read(RAW_KEY)
        version = (getattr(self.store, 'index_etags', {}).get(RAW_KEY)
                   if hasattr(self.store, 'index_etags') else
                   sha256(raw).hexdigest() if raw is not None else None)
        return raw, version

    def snapshot(self):
        raw, version = self._read_selector()
        if raw is None:
            return RawSnapshot(self, self._empty(), version)
        if len(raw) > SELECTOR_BYTES:
            raise ValueError('Raw selector exceeds the byte budget')
        manifest = json.loads(raw)
        if manifest['version'] != 1 or manifest['basis'] != self.basis:
            raise ValueError('Raw selector basis changed; explicit adoption is required')
        return RawSnapshot(self, manifest, version)

    def _read_table(self, pin, rows, *, schema, max_rows, max_bytes, decoded_bytes):
        if (type(rows) is not int or not 0 < rows <= max_rows
                or decoded_bytes is not None and (type(decoded_bytes) is not int
                    or not 0 < decoded_bytes <= max_bytes)):
            raise ValueError('Selected raw leaf exceeds its row or decoded-byte budget')
        if (not pin.get('verified') or pin['dataset']['groups']['source']['rows'] != rows
                or pin['id'] != pin['dataset']['version']):
            raise ValueError('Native raw source pin count or identity mismatch')
        batches, count, size = [], 0, 0
        with self.native.source_batches(pin, schema=schema) as reader:
            supplied_cols = [name for name in reader.schema.names if name.startswith('__docspec_supplied_')]
            logical_reader_schema = (
                pa.schema([f for f in reader.schema if not f.name.startswith('__docspec_supplied_')])
                if supplied_cols else reader.schema
            )
            if not logical_reader_schema.equals(schema, check_metadata=False):
                raise ValueError('Unexpected native raw source schema')
            for batch in reader:
                if supplied_cols:
                    batch = pa.Table.from_batches([batch]).drop(supplied_cols).to_batches()[0]
                if not batch.schema.equals(schema, check_metadata=False):
                    raise ValueError('Unexpected native raw source schema')
                count += len(batch)
                size += batch.nbytes
                if count > rows:
                    raise ValueError('Native raw source row count mismatch')
                # Chunking can add one null-bitmap byte per field per row.
                # This conservative allowance is bounded by the selected rows.
                if size > max_bytes + rows * len(schema):
                    raise ValueError('Native raw source exceeds its decoded-byte budget')
                batches.append(batch)
        if count != rows:
            raise ValueError('Native raw source row count mismatch')
        # Normalize optional all-valid bitmaps: Arrow take and native IPC may
        # allocate these differently for the same logical values. This conversion
        # happens only after bounded accumulation, using the exact raw schema.
        table = pa.Table.from_pylist(pa.Table.from_batches(batches, schema=schema).to_pylist(), schema=schema)
        if table.nbytes > max_bytes or (decoded_bytes is not None and table.nbytes != decoded_bytes):
            raise ValueError('Selected raw decoded-byte count or budget mismatch')
        return table

    def _read_states(self, reference):
        table = self._read_table(reference['release'], reference['rows'],
            schema=self.state_native_schema, max_rows=self.max_state_rows,
            max_bytes=self.max_state_bytes, decoded_bytes=reference['decoded_bytes'])
        order = table[STATE_ORDER]
        if (order.null_count or pc.count_distinct(order).as_py() != len(table)
                or pc.min(order).as_py() < 0):
            raise ValueError('Invalid selected URL-state ordinals')
        return table.take(pc.sort_indices(order))

    def _read_bodies(self, reference):
        return self._read_table(reference['release'], reference['rows'],
            schema=BODY_SCHEMA, max_rows=self.max_state_rows,
            max_bytes=self.max_state_bytes, decoded_bytes=reference['decoded_bytes'])

    def _prepare_bodies(self, base, captures, *, operation, base_id):
        updates = {}
        for row in captures.to_pylist():
            if row['body_key']:
                if self.excluded_body_hashes or getattr(self.store, 'excluded_body_hashes', None):
                    enforce_body_ingest_gate(
                        self.store,
                        row['body_key'],
                        excluded_hashes=self.excluded_body_hashes or None,
                        quarantine=False,
                    )
                info = {name: row[name] for name in BODY_FIELDS}
                key = 'body:' + row['body_key']
                if key not in updates or row['sha256']:
                    updates[key] = dict(key=key, **info)
                if row['sha256']:
                    key = 'sha:' + row['sha256']
                    updates[key] = dict(key=key, **info)
        affected = {}
        for key, row in updates.items():
            prefix, reference = self.body_routes.lookup(base.manifest['bodies']['root'], key)
            if prefix not in affected:
                prior = self._read_bodies(reference) if reference else pa.Table.from_pylist([], schema=BODY_SCHEMA)
                affected[prefix] = (prior, {r['key']: r for r in prior.to_pylist()}, {})
            affected[prefix][2][key] = row
        root, count = base.manifest['bodies']['root'], base.body_count
        for prefix, (prior, rows, changed) in affected.items():
            count += sum(key.startswith('body:') and key not in rows for key in changed)
            # A metadata-only reference must not erase known digest metadata.
            rows.update({key: row for key, row in changed.items()
                         if key not in rows or row['sha256'] or not rows[key]['sha256']})
            table = pa.Table.from_pylist([rows[key] for key in sorted(rows)], schema=BODY_SCHEMA)
            if table.equals(prior.take(pc.sort_indices(prior['key']))):
                continue
            leaves = {}
            for child, part in split_partition(table, key='key', prefix=prefix,
                    max_rows=self.max_state_rows, max_bytes=self.max_state_bytes):
                canonical = pa.Table.from_pylist(part.to_pylist(), schema=BODY_SCHEMA)
                leaves[child] = (dict(release=self._candidate('bodies', canonical, operation=operation,
                    prefix=child, base_id=base_id), rows=len(part), decoded_bytes=canonical.nbytes)
                    if len(part) else None)
            root = self.body_routes.replace(root, prefix, leaves)
        return dict(root=root, count=count)

    def _capture_batches(self, table):
        offset = 0
        while offset < len(table):
            count = min(self.max_capture_rows, len(table) - offset)
            while table.slice(offset, count).nbytes > self.max_capture_bytes:
                if count == 1:
                    raise ValueError('A single capture exceeds the decoded-byte budget')
                count //= 2
            yield offset, table.slice(offset, count).combine_chunks()
            offset += count

    @staticmethod
    def _request_digest(captures, states):
        digest = sha256()
        for table in (captures, states):
            if table is None or not len(table):
                digest.update(b'empty')
                continue
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table.combine_chunks())
            digest.update(sha256(sink.getvalue()).digest())
        return digest.hexdigest()

    def _delivery(self, root, operation):
        key = key_hash(operation)
        prefix, value = self.delivery_routes.lookup(root, key)
        entries = value['entries'] if value else {}
        return key, prefix, entries

    def _select_delivery(self, root, prefix, entries):
        # Only completed application selection evidence, never native lifecycle state.
        def split(current, values):
            if len(values) <= DELIVERY_ENTRIES:
                return {current: dict(entries=values)}
            result = {}
            for char in '0123456789abcdef':
                child = current + char
                subset = {key: value for key, value in values.items() if key_hash(key).startswith(child)}
                if subset:
                    result.update(split(child, subset))
            return result
        return self.delivery_routes.replace(root, prefix, split(prefix, entries))

    @staticmethod
    def _adjust_state_counts(counts, row, delta):
        outcome = row.get('outcome')
        values = dict(url_outcomes='null' if outcome is None else outcome,
                      urls_by_source_family=row.get('family') or 'unknown')
        for name, key in values.items():
            counters = counts[name]
            counters[key] = counters.get(key, 0) + delta
            if counters[key] == 0:
                del counters[key]
            elif counters[key] < 0:
                raise ValueError('Selected raw state counter mismatch')
        if outcome == 'excluded_media':
            counts['excluded_media_urls'] += delta

    def _candidate(self, kind, table, *, operation, prefix, base_id):
        # Keep candidates independent of a previous leaf's native latest. An
        # unselected Update advances that dataset and can make the application's
        # still-selected base stale, even when another raw leaf won publication.
        identity = sha256(encoded([operation, kind, prefix, base_id])).hexdigest()
        dataset = 'raw-' + kind + '-' + identity
        return self.native.run_table(table, dataset=dataset, operation='initial', definition='raw-native-v1')

    def _merge_states(self, existing, incoming, *, merge_spec=STATE_MERGE_SPEC):
        """Merge URL-state rows keyed by 64-byte ``state_key_sha256`` using ``UpdateMergeSpec(order_by='checked_at')``."""
        return _merge_states(
            existing,
            incoming,
            merge_spec=merge_spec,
            state_schema=self.state_schema,
        )

    def prepare_partitioned_state_table(
        self,
        states,
        *,
        dataset='raw-state',
        operation='initial',
        base_pin=None,
        num_buckets=STATE_BUCKET_COUNT,
        merge_spec=STATE_MERGE_SPEC,
    ):
        """Maintain URL state as one bucket-partitioned dataset keyed by 64-byte ``state_key_sha256``."""
        rows = states.to_pylist() if isinstance(states, pa.Table) else [dict(r) for r in states]
        existing_rows = []
        if base_pin is not None and hasattr(self.native, 'source_batches'):
            with self.native.source_batches(base_pin) as reader:
                existing_rows = pa.Table.from_batches(list(reader), schema=reader.schema).to_pylist()
        next_order = max((int(r.get(STATE_ORDER, -1)) for r in existing_rows), default=-1) + 1
        existing_orders = {
            r.get(STATE_KEY_SHA256_FIELD) or state_key_sha256(r.get('url')): int(r.get(STATE_ORDER, idx))
            for idx, r in enumerate(existing_rows)
        }
        prepared = []
        for r in rows:
            row = dict(r)
            for field in self.state_schema:
                row.setdefault(field.name, None)
            row[STATE_KEY_FIELD] = state_key(row.get('url'))
            sha = state_key_sha256(row.get('url'))
            row[STATE_KEY_SHA256_FIELD] = sha
            if sha in existing_orders:
                row[STATE_ORDER] = existing_orders[sha]
            elif STATE_ORDER not in row or row[STATE_ORDER] is None:
                row[STATE_ORDER] = next_order
                existing_orders[sha] = next_order
                next_order += 1
            prepared.append(row)
        part_schema = pa.schema([
            pa.field(STATE_ORDER, pa.int64(), nullable=False),
            pa.field(STATE_KEY_FIELD, pa.string(), nullable=False),
            pa.field(STATE_KEY_SHA256_FIELD, pa.string(), nullable=False),
            *self.state_schema,
        ])
        table = pa.Table.from_pylist(prepared, schema=part_schema)
        partition_by = [PartitionSpec.bucket(STATE_KEY_SHA256_FIELD, num_buckets)]
        active_cols = {
            k: v
            for k, v in (merge_spec or {}).get('columns', {}).items()
            if k in self.state_schema.names
        }
        effective_merge = UpdateMergeSpec(
            order_by=(
                merge_spec.get('order_by')
                if merge_spec and merge_spec.get('order_by') in self.state_schema.names
                else None
            ),
            columns={STATE_ORDER: UpdateMergeStrategy.MIN, **active_cols},
        )
        if base_pin is None:
            import inspect
            if 'partition_by' in inspect.signature(self.native.run_table).parameters:
                return self.native.run_table(
                    table,
                    dataset=dataset,
                    operation=operation,
                    definition='raw-state-partitioned-v1',
                    partition_by=partition_by,
                )
            return self.native.run_table(
                table,
                dataset=dataset,
                operation=operation,
                definition='raw-state-partitioned-v1',
            )
        import inspect
        if hasattr(self.native, 'update_table') and 'merge' in inspect.signature(self.native.update_table).parameters:
            return self.native.update_table(
                table,
                dataset=dataset,
                operation=operation,
                definition='raw-state-partitioned-v1',
                base=base_pin['id'],
                keys=[STATE_KEY_SHA256_FIELD],
                merge=effective_merge,
            )
        merged_full = self._merge_states(existing_rows, prepared, merge_spec=merge_spec)
        return self.native.run_table(
            merged_full,
            dataset=dataset,
            operation=operation,
            definition='raw-state-partitioned-v1',
        )

    def prepare(self, base, *, operation, captures=None, states=None,
                indexed_receipts=(), filename_version=None, request_id=None, delivery_result=None,
                reading_parts=(), qualify_readings=False, replace_readings=()):
        """Prepare exact bounded candidates; expose no independent native latest."""
        if base.owner is not self:
            raise ValueError('Raw base belongs to another storage owner')
        if not isinstance(operation, str) or not operation:
            raise ValueError('A stable raw operation identity is required')
        indexed_receipts = tuple(sorted(set(indexed_receipts)))
        if any(not isinstance(key, str) or not key for key in indexed_receipts):
            raise ValueError('Indexed receipts require nonempty string keys')
        if type(qualify_readings) is not bool:
            raise ValueError('Reading qualification requires an explicit boolean')
        reading_parts = tuple({name: part[name] for name in ('key', 'bytes', 'sha256', 'rows')} for part in reading_parts)
        replace_readings = tuple(sorted(set(replace_readings)))
        changed_state_urls = []
        updates = None
        if states is not None and len(states):
            updates = states if isinstance(states, pa.Table) else pa.Table.from_pylist(states, schema=self.state_schema)
            if (not updates.schema.equals(self.state_schema, check_metadata=False)
                    or pc.count_distinct(updates['url'], mode='all').as_py() != len(updates)):
                raise ValueError('Unexpected state schema or duplicate URL keys')
            updates = updates.cast(self.state_schema)
        incoming = capture_table(captures, first_order=0) if captures is not None and len(captures) else None
        request = sha256(encoded([self._request_digest(incoming, updates),
                                 sorted(indexed_receipts), filename_version, request_id, reading_parts,
                                 qualify_readings, replace_readings])).hexdigest()
        delivery_key, delivery_prefix, deliveries = self._delivery(base.manifest['deliveries'], 'delivery:' + operation)
        previous_delivery = deliveries.get(delivery_key)
        if previous_delivery:
            if previous_delivery['request'] != request:
                raise ValueError('Published raw operation has a different request')
            return dict(base=base, manifest=base.manifest, data=encoded(base.manifest),
                        changed=False, already_applied=True, delivery=previous_delivery)
        base_id = sha256(encoded(base.manifest)).hexdigest()
        manifest = deepcopy(base.manifest)
        if reading_parts or qualify_readings:
            manifest['readings']['root'] = self.readings.prepare(manifest['readings']['root'],
                reading_parts, replace=replace_readings)
            if qualify_readings:
                manifest['readings']['qualified'] = True
        if captures is not None and len(captures):
            additions = capture_table(captures, first_order=manifest['captures']['rows'])
            entries = []
            for offset, batch in self._capture_batches(additions):
                pin = self._candidate('captures', batch, operation=operation,
                                      prefix=str(offset), base_id=base_id)
                receipts = sorted({key for key in batch['receipt_key'].to_pylist() if key})
                entries.append(dict(release=pin, rows=len(batch), decoded_bytes=pa.Table.from_pylist(batch.to_pylist(), schema=NATIVE_CAPTURE_SCHEMA).nbytes, receipt_keys=receipts,
                                    first_order=batch['_capture_order'][0].as_py()))
            manifest['captures']['head'] = self.capture_pages.append(manifest['captures']['head'], entries)
            manifest['captures']['rows'] += len(additions)
        if incoming is not None:
            manifest['bodies'] = self._prepare_bodies(base, incoming, operation=operation, base_id=base_id)
        if filename_version is not None:
            manifest['filename_version'] = filename_version
        if updates is not None:
            affected, old, row_prefixes = {}, {}, {}
            for row in updates.to_pylist():
                prefix, reference = self.state_routes.lookup(base.manifest['state']['root'], state_key(row['url']))
                row_prefixes[row['url']] = prefix
                if prefix not in affected:
                    prior = (self._read_states(reference) if reference else
                             pa.Table.from_pylist([], schema=self.state_native_schema))
                    affected[prefix] = (reference, prior)
                    previous_rows = prior.to_pylist()
                    old.update({r['url']: r for r in previous_rows})
                    row_prefixes.update({r['url']: prefix for r in previous_rows})
            replacement = dict(old)
            next_order = base.manifest['state']['rows']
            for row in updates.to_pylist():
                original = old.get(row['url'])
                ordinal = original[STATE_ORDER] if original is not None else next_order
                if original is None:
                    next_order += 1
                if original is None or {name: original[name] for name in self.state_schema.names} != row:
                    changed_state_urls.append(row['url'])
                    if original is not None:
                        self._adjust_state_counts(manifest['state_counts'], original, -1)
                    self._adjust_state_counts(manifest['state_counts'], row, 1)
                replacement[row['url']] = {STATE_ORDER: ordinal, STATE_KEY_FIELD: state_key(row['url']), **row}
            selected_root = manifest['state']['root']
            grouped = {prefix: [] for prefix in affected}
            for url, row in replacement.items():
                grouped[row_prefixes[url]].append(row)
            for prefix, (reference, prior) in affected.items():
                rows = grouped[prefix]
                rows.sort(key=lambda row: row[STATE_ORDER])
                table = pa.Table.from_pylist(rows, schema=self.state_native_schema)
                if table.equals(prior):
                    continue
                splits = list(split_partition(table, key=STATE_KEY_FIELD, prefix=prefix,
                        max_rows=self.max_state_rows, max_bytes=self.max_state_bytes))
                leaves = {}
                for child, part in splits:
                    if not len(part):
                        leaves[child] = None
                        continue
                    if (
                        reference is not None
                        and reference.get('schema_evolved')
                        and len(splits) == 1
                        and child == prefix
                        and hasattr(self.native, 'update_table')
                    ):
                        from congress_api.retention.native_features import source_schema_fields
                        ref_pin = reference['release']
                        for grp_name, grp_binding in (ref_pin.get('dataset', {}).get('computed') or {}).items():
                            if grp_binding.get('qualification') is not None and hasattr(self.native, 'backfill'):
                                grp_def = grp_binding['definition']
                                ref_pin = self.native.backfill(dict(
                                    dataset=ref_pin['dataset']['dataset'],
                                    operation=f'{operation}-rebind-{grp_name}-{base_id[:12]}',
                                    definition=ref_pin['dataset']['definition'],
                                    base=ref_pin['id'],
                                    group=grp_name,
                                    group_definition=f"{grp_def['definition']}-{operation}",
                                    fields=grp_def['fields'],
                                ))
                        col_order = [f['name'] for f in source_schema_fields(self.native, ref_pin)]
                        prior_by_url = {r['url']: r for r in prior.to_pylist()}
                        delta_rows = [
                            r for r in part.to_pylist()
                            if r['url'] not in prior_by_url or prior_by_url[r['url']] != r
                        ]
                        ordered_schema = pa.schema([self.state_native_schema.field(name) for name in col_order])
                        delta_table = pa.Table.from_pylist(delta_rows, schema=ordered_schema)
                        updated_pin = self.native.update_table(
                            delta_table,
                            dataset=ref_pin['dataset']['dataset'],
                            operation=f'{operation}-{child or "root"}-{base_id[:12]}',
                            definition=ref_pin['dataset']['definition'],
                            base=ref_pin['id'],
                            keys=[STATE_KEY_FIELD],
                        )
                        leaves[child] = dict(
                            release=updated_pin,
                            schema_evolved=True,
                            rows=len(part),
                            decoded_bytes=pa.Table.from_pylist(part.to_pylist(), schema=self.state_native_schema).nbytes,
                            schedule=summarize(part.to_pylist()),
                        )
                    else:
                        leaves[child] = dict(
                            release=self._candidate('state', part, operation=operation, prefix=child, base_id=base_id),
                            rows=len(part),
                            decoded_bytes=pa.Table.from_pylist(part.to_pylist(), schema=self.state_native_schema).nbytes,
                            schedule=summarize(part.to_pylist()),
                        )
                selected_root = self.state_routes.replace(selected_root, prefix, leaves)
            manifest['state'] = dict(root=selected_root, rows=next_order)
        delivery = dict(request=request, request_id=request_id,
                        capture_rows=len(incoming) if incoming is not None else 0,
                        first_order=base.manifest['captures']['rows'], result=delivery_result)
        for receipt in sorted(set(indexed_receipts)):
            key, prefix, entries = self._delivery(manifest['deliveries'], 'receipt:' + receipt)
            if key not in entries:
                manifest['deliveries'] = self._select_delivery(manifest['deliveries'], prefix,
                                                              {**entries, key: delivery})
        if manifest != base.manifest:
            delivery_key, delivery_prefix, deliveries = self._delivery(
                manifest['deliveries'], 'delivery:' + operation)
            manifest['deliveries'] = self._select_delivery(manifest['deliveries'], delivery_prefix,
                                                          {**deliveries, delivery_key: delivery})
        if manifest != base.manifest:
            manifest['change'] = self.changes.put(base, manifest, changed_state_urls, reading_parts=reading_parts)
        data = encoded(manifest)
        if len(data) > SELECTOR_BYTES:
            raise ValueError('Raw selector exceeds the byte budget')
        return dict(base=base, manifest=manifest, data=data, changed=manifest != base.manifest,
                    already_applied=False, delivery=delivery)

    def publish(self, prepared):
        """Select captures and state together, reconciling one exact lost reply."""
        base, data = prepared['base'], prepared['data']
        if base.owner is not self:
            raise ValueError('Raw preparation belongs to another storage owner')
        if (prepared['manifest']['basis'] != self.basis
                or encoded(prepared['manifest']) != data
                or prepared['changed'] != (prepared['manifest'] != base.manifest)):
            raise ValueError('Raw preparation no longer matches its exact selection')
        if not prepared['changed']:
            return RawSnapshot(self, base.manifest, base.version, prepared['delivery'])
        current = self.store.read(RAW_KEY)
        if current != data:
            reconcile_lost_acknowledgment(
                lambda: self.store.put_index_selector(RAW_KEY, data, expected_version=base.version),
                lambda: self.store.read(RAW_KEY), data)
        verified, version = self._read_selector()
        if verified != data:
            raise ValueError('Raw selector readback mismatch')
        return RawSnapshot(self, json.loads(verified), version, prepared['delivery'])

    def evolve_state_schema(self, base, *, operation, next_schema=STATE_SCHEMA,
                            additions=None, write_defaults=None, scalar_backfill=None,
                            continuous=None, correction=None):
        """Evolve selected URL-state leaves to a compatible ``next_schema`` without rewriting source files."""
        from congress_api.retention.catalog_batches import can_read_catalog_schema
        from congress_api.retention.native_features import (
            backfill_scalar_group,
            evolve_catalog_schema,
            source_schema_fields,
        )
        if base.owner is not self:
            raise ValueError('Raw base belongs to another storage owner')
        if not can_read_catalog_schema(self.state_schema, next_schema):
            raise ValueError('Raw state schema evolution requires a compatible nullable extension')
        next_owner = type(self)(
            self.store,
            self.native,
            max_state_rows=self.max_state_rows,
            max_state_bytes=self.max_state_bytes,
            max_capture_rows=self.max_capture_rows,
            max_capture_bytes=self.max_capture_bytes,
            state_schema=next_schema,
        )
        type_map = {
            pa.bool_(): 'boolean',
            pa.int64(): 'long',
            pa.float64(): 'double',
            pa.string(): 'string',
        }
        if additions is None:
            existing = set(self.state_schema.names)
            additions = []
            for field in next_schema:
                if field.name in existing:
                    continue
                if field.type not in type_map:
                    raise ValueError(f'Unsupported native schema evolution type for {field.name!r}')
                spec = dict(name=field.name, data_type=type_map[field.type])
                if field.name == 'links_scanned':
                    spec['default'] = False
                additions.append(spec)
        else:
            additions = [dict(a) for a in additions]

        manifest = deepcopy(base.manifest)
        manifest['basis'] = deepcopy(next_owner.basis)
        selected_root = manifest['state']['root']
        leaf_results = {}
        for prefix, reference in list(self.state_routes.leaf_items(selected_root)):
            pin = reference['release']
            dataset = pin['dataset']['dataset']
            base_def = pin['dataset']['definition']
            next_def = f'{base_def}-{operation}'
            root_fields = source_schema_fields(self.native, pin)
            evolved = evolve_catalog_schema(
                self.native,
                dataset=dataset,
                operation=f'{operation}-schema-{prefix or "root"}',
                base_pin=pin,
                definition=base_def,
                next_definition=next_def,
                fields=root_fields,
                additions=additions,
                write_defaults=write_defaults,
            )
            evolved_pin = evolved['pin']
            backfilled = None
            if scalar_backfill is not None or continuous is not None or correction is not None:
                bf_spec = scalar_backfill or {}
                corr = dict(correction) if correction is not None else None
                if corr is not None and 'fields' not in corr:
                    corr['fields'] = [
                        f['id'] for f in root_fields
                        if f['name'] in {STATE_KEY_FIELD, 'url', 'body_key', 'outcome'}
                    ]
                backfilled = backfill_scalar_group(
                    self.native,
                    dataset=dataset,
                    operation=f'{operation}-backfill-{prefix or "root"}',
                    base_pin=evolved_pin,
                    definition=next_def,
                    group=bf_spec.get('group', 'state_scalars'),
                    group_definition=bf_spec.get('group_definition', f'raw-state-scalars-{operation}'),
                    fields=bf_spec.get(
                        'fields',
                        [dict(id=1, name='has_body', expression='body_key IS NOT NULL')],
                    ),
                    continuous=continuous,
                    correction=corr,
                )
            selected_pin = backfilled['pin'] if backfilled is not None else evolved_pin
            evolved_table = next_owner._read_table(
                selected_pin,
                reference['rows'],
                schema=next_owner.state_native_schema,
                max_rows=next_owner.max_state_rows,
                max_bytes=next_owner.max_state_bytes,
                decoded_bytes=None,
            )
            new_ref = dict(
                reference,
                release=selected_pin,
                evolved_release=evolved_pin,
                schema_evolved=True,
                decoded_bytes=evolved_table.nbytes,
                schedule=summarize(evolved_table.to_pylist()),
            )
            if backfilled is not None:
                new_ref['scalar_release'] = backfilled['pin']
            selected_root = self.state_routes.replace(selected_root, prefix, {prefix: new_ref})
            leaf_results[dataset] = dict(
                prefix=prefix,
                base_pin=pin,
                schema_plan=evolved['plan'],
                evolved_pin=evolved_pin,
                backfill=backfilled,
            )
        manifest['state']['root'] = selected_root
        delivery = dict(
            request=sha256(encoded([operation, next_owner.basis['state_schema']])).hexdigest(),
            request_id=operation,
            capture_rows=0,
            first_order=base.manifest['captures']['rows'],
            result=dict(evolved_leaves=sorted(leaf_results)),
        )
        delivery_key, delivery_prefix, deliveries = self._delivery(
            manifest['deliveries'], 'delivery:' + operation
        )
        manifest['deliveries'] = self._select_delivery(
            manifest['deliveries'], delivery_prefix, {**deliveries, delivery_key: delivery}
        )
        manifest['change'] = self.changes.put(base, manifest, [], reading_parts=())
        data = encoded(manifest)
        next_base = RawSnapshot(next_owner, base.manifest, base.version)
        prepared = dict(
            base=next_base,
            manifest=manifest,
            data=data,
            changed=manifest != base.manifest,
            already_applied=False,
            delivery=delivery,
            leaves=leaf_results,
        )
        return next_owner, prepared
