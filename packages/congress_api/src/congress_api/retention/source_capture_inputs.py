"""Exact raw batch references for retained source-observation replay.

RawStorage owns capture rows and immutable native pins. This owner only retains
which bounded raw batch and ordinal supplied each interpreted observation.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa

from .catalog_dependencies import DependencyGap
from .immutable_metadata import MetadataObjects, encoded
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .source_observations import observation_id, receipt_locator


def capture_input(reference, order):
    if type(order) is not int or order < 0:
        raise ValueError('Source capture input requires a nonnegative ordinal')
    return 'native:' + encoded(dict(batch=reference, order=order)).decode()


def read_capture_input(value):
    if not isinstance(value, str) or not value.startswith('native:'):
        raise DependencyGap('Source observation has no retained exact raw batch; qualify its receipt inputs')
    body = json.loads(value[len('native:'):])
    if capture_input(body['batch'], body['order']) != value:
        raise ValueError('Noncanonical source capture input')
    return body


class SourceCaptureInputs:
    def __init__(self, store):
        self.objects = MetadataObjects(store, 'source-capture-inputs-v1', max_cache_entries=4)

    def attach(self, trace, entry, captures, *, _reference=None):
        """Attach a batch read by RawSnapshot.capture_batch to its observations."""
        if not captures.schema.equals(NATIVE_CAPTURE_SCHEMA, check_metadata=True):
            raise ValueError('Source capture input requires the exact raw logical schema')
        orders = captures['_capture_order'].to_pylist()
        if orders != list(range(entry['first_order'], entry['first_order'] + entry['rows'])):
            raise ValueError('Source capture input ordinal/count differs from the raw batch')
        reference = _reference if _reference is not None else self.objects.put(dict(version=1, entry=entry))
        prefix = 'native:{"batch":' + encoded(reference).decode() + ',"order":'
        rkeys = captures['receipt_key'].to_pylist()
        rlines = captures['receipt_line'].to_pylist()
        for rkey, rline, order in zip(rkeys, rlines, orders):
            trace(dict(receipt_key=rkey, receipt_line=rline, kind='capture',
                       value=f'{prefix}{order}}}', access='write'))
        return reference

    def changed(self, snapshot, change, trace):
        """Yield only appended exact batches from one durable raw change."""
        entries = list(snapshot.changed_capture_batches(change))
        if self.objects.supports_batch_put and len(entries) > 1:
            refs = []
            uploads = []
            for entry in entries:
                ref, digest, key, raw = self.objects.prepare_put(dict(version=1, entry=entry))
                refs.append(ref)
                uploads.append((digest, key, raw))
            self.objects.put_batch(uploads)
            for entry, ref in zip(entries, refs):
                table = snapshot.capture_batch(entry)
                self.attach(trace, entry, table, _reference=ref)
                yield table
            return
        for entry in entries:
            table = snapshot.capture_batch(entry)
            self.attach(trace, entry, table)
            yield table

    def copy(self, storage, root, observations, trace):
        """Carry immutable raw input edges into a complete observation replay."""
        for observation in observations:
            key, line = receipt_locator(observation)
            trace.register(key, line)
            for edge in storage.members.values(root, observation):
                dependency, access = json.loads(edge)
                kind, value = json.loads(dependency[len('dependency:'):])
                if kind == 'capture' and access == 'write':
                    read_capture_input(value)
                    trace(dict(receipt_key=key, receipt_line=line, kind=kind, value=value, access=access))

    def tables(self, storage, root, observations, snapshot):
        """Read each needed raw pin once, retaining only exact requested inputs.

        The disposable index holds ordinals and references, never capture payloads.
        Native payload buffering stays within the selected raw batch bounds.
        """
        with TemporaryDirectory(prefix='source-capture-inputs-') as directory, closing(
                sqlite3.connect(Path(directory) / 'inputs.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE inputs(ordinal INTEGER PRIMARY KEY,batch TEXT,observation TEXT); '
                'CREATE INDEX batch_inputs ON inputs(batch,ordinal);')
            for observation in observations:
                for edge in storage.members.values(root, observation):
                    dependency, access = json.loads(edge)
                    kind, value = json.loads(dependency[len('dependency:'):])
                    if kind != 'capture' or access != 'write':
                        continue
                    body = read_capture_input(value)
                    reference = encoded(body['batch']).decode()
                    previous = db.execute('SELECT batch,observation FROM inputs WHERE ordinal=?',
                                          (body['order'],)).fetchone()
                    if previous is not None and previous != (reference, observation):
                        raise ValueError('One source capture ordinal names conflicting retained inputs')
                    db.execute('INSERT OR IGNORE INTO inputs VALUES (?,?,?)',
                               (body['order'], reference, observation))
            for reference, in db.execute('SELECT batch FROM inputs GROUP BY batch ORDER BY min(ordinal)'):
                body = self.objects.read(json.loads(reference))
                if body.get('version') != 1:
                    raise ValueError('Unknown retained source capture input format')
                table = snapshot.capture_batch(body['entry'])
                positions = []
                for position, row in enumerate(table.select(
                        ['receipt_key', 'receipt_line', '_capture_order']).to_pylist()):
                    expected = db.execute('SELECT observation FROM inputs WHERE batch=? AND ordinal=?',
                                          (reference, row['_capture_order'])).fetchone()
                    if expected is not None:
                        if expected[0] != observation_id(row['receipt_key'], row['receipt_line']):
                            raise ValueError('Retained raw capture receipt locator differs from its source owner')
                        positions.append(position)
                expected, = db.execute('SELECT count(*) FROM inputs WHERE batch=?', (reference,)).fetchone()
                if len(positions) != expected:
                    raise ValueError('Retained raw batch omits requested source capture ordinals')
                yield table.take(pa.array(positions, type=pa.int64()))
