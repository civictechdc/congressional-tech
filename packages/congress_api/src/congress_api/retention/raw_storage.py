"""Coherent raw capture/state selection over immutable native source candidates.

DocSpec owns records, versions and completed work. The application selects exact
completed native pins through one conditional root; losing candidates remain
unselected. Captures append as ordered batches. Only changed URL-state leaves
are reconstructed, and a full leaf splits locally through immutable routing.
"""
from copy import deepcopy
from hashlib import sha256
import json

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.partition_routing import RoutingPages, split_partition, key_hash
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_capture_pages import CapturePages
from congress_api.retention.raw_values import capture_table, ordered_captures, state_table, NATIVE_CAPTURE_SCHEMA
from congress_api.retention.write_recovery import reconcile_lost_acknowledgment

RAW_KEY = 'indexes/raw.json'
STATE_ORDER = '_state_order'
STATE_NATIVE_SCHEMA = pa.schema([pa.field(STATE_ORDER, pa.int64(), nullable=False), *STATE_SCHEMA])
CAPTURE_BATCH_ROWS = 1000
CAPTURE_BATCH_BYTES = 16 << 20
DELIVERY_ENTRIES = 128
SELECTOR_BYTES = 1 << 20



class RawSnapshot:
    def __init__(self, owner, manifest, version, delivery=None):
        self.owner, self.manifest, self.version = owner, manifest, version
        self.delivery = delivery

    def captures(self):
        tables = []
        for entry in self.owner.capture_pages.entries(self.manifest['captures']['head']):
            stored = self.owner._read_table(entry['release'], entry['rows'],
                schema=NATIVE_CAPTURE_SCHEMA, max_rows=self.owner.max_capture_rows,
                max_bytes=self.owner.max_capture_bytes, decoded_bytes=entry['decoded_bytes'])
            expected = list(range(entry['first_order'], entry['first_order'] + entry['rows']))
            if sorted(stored['_capture_order'].to_pylist()) != expected:
                raise ValueError('Selected capture batch order mismatch')
            tables.append(ordered_captures(stored))
        result = pa.concat_tables(tables) if tables else pa.Table.from_pylist([], schema=CAPTURE_SCHEMA)
        if len(result) != self.manifest['captures']['rows']:
            raise ValueError('Selected capture count mismatch')
        return result

    def receipt_keys(self):
        return {key for entry in self.owner.capture_pages.entries(self.manifest['captures']['head'])
                for key in entry['receipt_keys']}

    def states(self):
        tables = [self.owner._read_states(value) for _, value in
                  self.owner.state_routes.leaf_items(self.manifest['state']['root'])]
        if not tables:
            return pa.Table.from_pylist([], schema=STATE_SCHEMA)
        combined = pa.concat_tables(tables)
        order = combined[STATE_ORDER]
        if (order.null_count or pc.count_distinct(order).as_py() != len(combined)
                or sorted(order.to_pylist()) != list(range(self.manifest['state']['rows']))):
            raise ValueError('Selected URL-state order or count mismatch')
        return combined.take(pc.sort_indices(order)).select(STATE_SCHEMA.names).cast(STATE_SCHEMA)

    def state(self, url):
        _, reference = self.owner.state_routes.lookup(self.manifest['state']['root'], url)
        if reference is None:
            return None
        table = self.owner._read_states(reference)
        selected = table.filter(pc.equal(table['url'], url)).select(STATE_SCHEMA.names)
        return selected.to_pylist()[0] if len(selected) else None


class RawStorage:
    def __init__(self, store, native, *, max_state_rows=8192, max_state_bytes=16 << 20,
                 max_capture_rows=CAPTURE_BATCH_ROWS, max_capture_bytes=CAPTURE_BATCH_BYTES):
        self.store, self.native = store, native
        self.max_state_rows, self.max_state_bytes = max_state_rows, max_state_bytes
        self.max_capture_rows, self.max_capture_bytes = max_capture_rows, max_capture_bytes
        if min(max_state_rows, max_state_bytes, max_capture_rows, max_capture_bytes) < 1:
            raise ValueError("Raw storage budgets must be positive")
        self.capture_pages = CapturePages(store)
        self.state_routes = RoutingPages(store, 'raw-state-v1')
        self.delivery_routes = RoutingPages(store, 'raw-deliveries-v1')
        self.basis = dict(values='raw-native-v1', routing='sha256-utf8-prefix-v1',
                          max_state_rows=max_state_rows, max_state_bytes=max_state_bytes,
                          max_capture_rows=max_capture_rows, max_capture_bytes=max_capture_bytes)

    def _empty(self):
        return dict(version=1, basis=deepcopy(self.basis), captures=dict(head=None, rows=0),
                    state=dict(root=None, rows=0), deliveries=None)

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
        with self.native.source_batches(pin) as reader:
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
        return self._read_table(reference['release'], reference['rows'],
            schema=STATE_NATIVE_SCHEMA, max_rows=self.max_state_rows,
            max_bytes=self.max_state_bytes, decoded_bytes=reference['decoded_bytes'])

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

    def _candidate(self, kind, table, *, operation, prefix, base_id):
        identity = sha256(encoded([operation, kind, prefix, base_id])).hexdigest()
        dataset = 'raw-' + kind + '-' + identity
        return self.native.run_table(table, dataset=dataset, operation='initial', definition='raw-native-v1')

    def prepare(self, base, *, operation, captures=None, states=None):
        """Prepare exact bounded candidates; expose no independent native latest."""
        if base.owner is not self:
            raise ValueError('Raw base belongs to another storage owner')
        if not isinstance(operation, str) or not operation:
            raise ValueError('A stable raw operation identity is required')
        updates = state_table(states) if states is not None and len(states) else None
        if updates is not None and any(not isinstance(url, str) or not url for url in updates['url'].to_pylist()):
            raise ValueError('Download state needs nonempty URL keys')
        incoming = capture_table(captures, first_order=0) if captures is not None and len(captures) else None
        request = self._request_digest(incoming, updates)
        delivery_key, delivery_prefix, deliveries = self._delivery(base.manifest['deliveries'], operation)
        previous_delivery = deliveries.get(delivery_key)
        if previous_delivery:
            if previous_delivery['request'] != request:
                raise ValueError('Published raw operation has a different request')
            return dict(base=base, manifest=base.manifest, data=encoded(base.manifest),
                        changed=False, already_applied=True, delivery=previous_delivery)
        base_id = sha256(encoded(base.manifest)).hexdigest()
        manifest = deepcopy(base.manifest)
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
        if updates is not None:
            affected, old, row_prefixes = {}, {}, {}
            for row in updates.to_pylist():
                prefix, reference = self.state_routes.lookup(base.manifest['state']['root'], row['url'])
                row_prefixes[row['url']] = prefix
                if prefix not in affected:
                    prior = (self._read_states(reference) if reference else
                             pa.Table.from_pylist([], schema=STATE_NATIVE_SCHEMA))
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
                replacement[row['url']] = {STATE_ORDER: ordinal, **row}
            selected_root = manifest['state']['root']
            grouped = {prefix: [] for prefix in affected}
            for url, row in replacement.items():
                grouped[row_prefixes[url]].append(row)
            for prefix, (_, prior) in affected.items():
                rows = grouped[prefix]
                rows.sort(key=lambda row: row[STATE_ORDER])
                table = pa.Table.from_pylist(rows, schema=STATE_NATIVE_SCHEMA)
                if table.equals(prior):
                    continue
                leaves = {}
                for child, part in split_partition(table, key='url', prefix=prefix,
                        max_rows=self.max_state_rows, max_bytes=self.max_state_bytes):
                    leaves[child] = (dict(release=self._candidate('state', part, operation=operation,
                                          prefix=child, base_id=base_id), rows=len(part),
                                          decoded_bytes=pa.Table.from_pylist(part.to_pylist(), schema=STATE_NATIVE_SCHEMA).nbytes) if len(part) else None)
                selected_root = self.state_routes.replace(selected_root, prefix, leaves)
            manifest['state'] = dict(root=selected_root, rows=next_order)
        delivery = dict(request=request, capture_rows=len(incoming) if incoming is not None else 0,
                        first_order=base.manifest['captures']['rows'])
        if manifest != base.manifest:
            manifest['deliveries'] = self._select_delivery(manifest['deliveries'], delivery_prefix,
                                                          {**deliveries, delivery_key: delivery})
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
