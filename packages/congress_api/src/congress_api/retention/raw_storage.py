"""Coherent raw capture/state selection over immutable native source candidates.

DocSpec owns records, versions and completed work. The application selects exact
completed native pins through one conditional root; losing candidates remain
unselected. Captures append as ordered batches. Only changed URL-state leaves
are reconstructed, and a full leaf splits locally through immutable routing.
"""
from copy import deepcopy
import base64
from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.partition_routing import RoutingPages, split_partition, key_hash
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_capture_pages import CapturePages
from congress_api.retention.raw_changes import RawChanges
from congress_api.retention.raw_state_routes import StateRoutes, summarize, schedule_basis
from congress_api.retention.raw_values import capture_table, ordered_captures, NATIVE_CAPTURE_SCHEMA
from congress_api.retention.write_recovery import reconcile_lost_acknowledgment

RAW_KEY = 'indexes/raw.json'
STATE_ORDER = '_state_order'
STATE_KEY_FIELD = '_state_key'

def state_key(url):
    return 'null:' if url is None else 'url:' + url

STATE_NATIVE_SCHEMA = pa.schema([pa.field(STATE_ORDER, pa.int64(), nullable=False),
                               pa.field(STATE_KEY_FIELD, pa.string(), nullable=False), *STATE_SCHEMA])
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


class RawStorage:
    def __init__(self, store, native, *, max_state_rows=8192, max_state_bytes=16 << 20,
                 max_capture_rows=CAPTURE_BATCH_ROWS, max_capture_bytes=CAPTURE_BATCH_BYTES,
                 state_schema=STATE_SCHEMA):
        self.store, self.native = store, native
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
            if not reader.schema.equals(schema, check_metadata=False):
                raise ValueError('Unexpected native raw source schema')
            for batch in reader:
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
        identity = sha256(encoded([operation, kind, prefix, base_id])).hexdigest()
        dataset = 'raw-' + kind + '-' + identity
        return self.native.run_table(table, dataset=dataset, operation='initial', definition='raw-native-v1')

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
            for prefix, (_, prior) in affected.items():
                rows = grouped[prefix]
                rows.sort(key=lambda row: row[STATE_ORDER])
                table = pa.Table.from_pylist(rows, schema=self.state_native_schema)
                if table.equals(prior):
                    continue
                leaves = {}
                for child, part in split_partition(table, key=STATE_KEY_FIELD, prefix=prefix,
                        max_rows=self.max_state_rows, max_bytes=self.max_state_bytes):
                    leaves[child] = (dict(release=self._candidate('state', part, operation=operation,
                                          prefix=child, base_id=base_id), rows=len(part),
                                          decoded_bytes=pa.Table.from_pylist(part.to_pylist(), schema=self.state_native_schema).nbytes,
                                          schedule=summarize(part.to_pylist())) if len(part) else None)
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
