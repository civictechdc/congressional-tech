"""Lossless, bounded reads of nested observations alongside the full Parquet.

Repeated observations share a dictionary entry. Each block contains JSON with
null struct fields omitted; the schema restores them on read. Large individual
values span independently compressed parts instead of increasing decode size.
"""
import hashlib
import json
from contextlib import closing
from filename_resources import owned_resources
import sqlite3
import tempfile
from pathlib import Path

from filename_budget import (DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, bounded_batches,
                             failure_receipt, json_chunks, maximum, python_estimate, refuse)
from filename_json_stream import ObservationCounts, block_items, decoded_json_default

import pyarrow as pa

BLOCK_BYTES = 1024 * 1024


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


class ObservationSequence:
    """A repeatable typed sequence whose parts never join the whole Arrow list."""
    def __init__(self, length, batches):
        if type(length) is not int or length < 0 or not callable(batches):
            raise ValueError('Invalid typed observation sequence')
        self.length, self.batches = length, batches

    def __len__(self): return self.length


def observation_rows(source, *, policy, metrics, stage):
    def rows():
        if hasattr(source, 'observation_rows'):
            yield from source.observation_rows()
            return
        for batch in bounded_batches(source, columns=['source_occurrences'], batch_rows=128,
                                     policy=policy, stage=stage, metrics=metrics, python_values=False):
            for scalar in batch.column(0):
                yield scalar.values if scalar.is_valid else None
    for values in rows():
        if values is not None:
            # References, not converted observations, remain for the whole row.
            estimate = 64 + 48 * len(values)
            if estimate > policy.row_python_estimate:
                refuse(stage, 'reference-list Python estimate', estimate, policy.row_python_estimate)
            maximum(metrics, 'max_reference_list_python_estimate', estimate)
        yield values


def observation_values(values, *, policy, metrics, stage):
    if values is None:
        return
    batches = values.batches() if isinstance(values, ObservationSequence) else (values,)
    count = 0
    for batch in batches:
        if not isinstance(batch, pa.Array):
            raise TypeError('Observation parts must be typed Arrow arrays')
        if batch.nbytes > policy.row_arrow_bytes:
            refuse(stage, 'observation part Arrow bytes', batch.nbytes, policy.row_arrow_bytes)
        maximum(metrics, 'max_observation_part_arrow_bytes', batch.nbytes)
        for position in range(len(batch)):
            count += 1
            if count > len(values):
                raise ValueError('Typed observation sequence length differs')
            yield observation_value(batch, position, policy=policy, metrics=metrics, stage=stage)
    if count != len(values):
        raise ValueError('Typed observation sequence length differs')


def observation_value(values, index, *, policy, metrics, stage):
    one = pa.RecordBatch.from_arrays([values.slice(index, 1)], names=['observation'])
    estimate = python_estimate(one)
    if estimate > policy.row_python_estimate:
        refuse(stage, 'single-observation Python/JSON estimate', estimate, policy.row_python_estimate)
    maximum(metrics, 'max_python_json_estimate', estimate)
    maximum(metrics, 'max_observation_python_estimate', estimate)
    return values[index].as_py()


class Blocks:
    def __init__(self, path, row_limit=None, *, policy=DEFAULT_DECODED_POLICY, metrics=None):
        self.path, self.row_limit = path, row_limit
        self.policy, self.metrics = policy, metrics if metrics is not None else {}
        self.stream = path.open('wb')
        self.blocks, self.pending = [], []
        self.pending_bytes, self.rows = 2, 0

    def append(self, value):
        self.append_encoded(b''.join(json_chunks(value, policy=self.policy, metrics=self.metrics)))

    def append_encoded(self, value):
        if self.pending and (self.pending_bytes + len(value) + 1 > BLOCK_BYTES or
                             self.row_limit and len(self.pending) >= self.row_limit):
            self.flush()
        self.pending.append(value)
        self.pending_bytes += len(value) + 1

    def flush(self):
        if not self.pending:
            return
        parts, pending = [], bytearray()
        def emit(piece):
            encoded = pa.compress(piece, codec='brotli').to_pybytes()
            offset = self.stream.tell(); self.stream.write(encoded)
            parts.append([offset, len(encoded), len(piece)])
        # Keep one compressed-part staging buffer, never join the logical block.
        def pieces():
            yield b'['
            for index, value in enumerate(self.pending):
                if index: yield b','
                yield value
            yield b']'
        for piece in pieces():
            view = memoryview(piece)
            for start in range(0, len(view), BLOCK_BYTES):
                portion = view[start:start + BLOCK_BYTES]
                while portion:
                    size = min(BLOCK_BYTES - len(pending), len(portion))
                    pending.extend(portion[:size]); portion = portion[size:]
                    if len(pending) == BLOCK_BYTES:
                        emit(pending); pending.clear()
        if pending: emit(pending)
        self.blocks.append(dict(start=self.rows, count=len(self.pending), parts=parts))
        self.rows += len(self.pending)
        self.pending, self.pending_bytes = [], 2

    def close(self):
        if self.stream.closed:
            return dict(rows=self.rows, blocks=self.blocks)
        try:
            self.flush()
        except BaseException as error:
            try:
                self.stream.close()
            except BaseException as cleanup:
                error.add_note(f'Block stream close also failed: {cleanup}')
            raise
        self.stream.close()
        return dict(rows=self.rows, blocks=self.blocks)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is None:
            self.close()
        else:
            # Abort never flushes a logical block that did not finish.
            self.pending.clear()
            try:
                self.stream.close()
            except BaseException as cleanup:
                error.add_note(f'Block abort close also failed: {cleanup}')


def publish_observations(source, output, *, counts=None, policy=DEFAULT_DECODED_POLICY, metrics=None):
    metrics = metrics if metrics is not None else {}
    try:
        with owned_resources() as owned:
            counts = counts or owned.enter_context(ObservationCounts(source))
            return _publish_observations(source, output, owned, counts, policy, metrics)
    except DecodedBudgetExceeded as error:
        failure_receipt(output, error, policy, metrics)
        raise


def _publish_observations(source, output, owned, counts, policy, metrics):
    fields = [field.name for field in source.schema_arrow.field('source_occurrences').type.value_type]
    observations = owned.enter_context(Blocks(output / 'observations.bin', policy=policy, metrics=metrics))
    references = owned.enter_context(Blocks(output / 'observation-rows.bin', row_limit=1024, policy=policy, metrics=metrics))
    temporary = owned.enter_context(tempfile.TemporaryDirectory(prefix='observation-identities-'))
    identities = sqlite3.connect(str(Path(temporary) / 'identities.sqlite'))
    owned.callback(identities.close)
    identities.executescript(f'PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-{policy.sqlite_cache_kib}; '
                            'CREATE TABLE identities(digest BLOB PRIMARY KEY,id INTEGER NOT NULL) WITHOUT ROWID;')
    count = 0
    for values in observation_rows(source, policy=policy, metrics=metrics, stage='observations'):
        refs = None if values is None else []
        for observation in observation_values(values, policy=policy, metrics=metrics, stage='observations'):
            compact = None if observation is None else {key: value for key, value in observation.items() if value is not None}
            encoded = b''.join(json_chunks(compact, policy=policy, metrics=metrics))
            metrics['observation_serializations'] = metrics.get('observation_serializations', 0) + 1
            identity = hashlib.sha256(encoded).digest()
            row = identities.execute('SELECT id FROM identities WHERE digest=?', (identity,)).fetchone()
            if row is None:
                row = (count,); identities.execute('INSERT INTO identities VALUES (?,?)', (identity, count)); count += 1
                observations.append_encoded(encoded)
            refs.append(row[0])
            del observation, compact, encoded
        references.append(refs); counts.append(len(values) if values is not None else 0)
    counts.seal(getattr(getattr(source, 'metadata', None), 'num_rows', counts.rows))
    metrics['dedup_entries'] = count
    metrics['dedup_sqlite_cache_bytes'] = policy.sqlite_cache_kib * 1024
    metrics['dedup_disk_bytes'] = identities.execute('PRAGMA page_count').fetchone()[0] * identities.execute('PRAGMA page_size').fetchone()[0]
    identities.close()  # No identity lookups remain during full readback.
    index = dict(version=1, fields=fields, max_part_bytes=BLOCK_BYTES,
                 observations=observations.close(), references=references.close())
    verify_observations(source, output, index, policy=policy, metrics=metrics)
    (output / 'observation-index.json').write_bytes(json_bytes(index))
    return index


def verify_observations(source, output, index, *, policy=DEFAULT_DECODED_POLICY, metrics=None):
    """Check every value using a disk dictionary, decoding each block once."""
    metrics = metrics if metrics is not None else {}
    fields = [field.name for field in source.schema_arrow.field('source_occurrences').type.value_type]
    if index['fields'] != fields:
        raise ValueError('Observation schema changed.')

    def read_block(name, block):
        return block_items(output / f'{name}.bin', block, policy=policy, metrics=metrics)

    def canonical(value):
        # Match the browser's schema restoration, preserving null observations,
        # list order, duplicates, and null versus empty field values.
        restored = None if value is None else {field: value[field] for field in fields if value.get(field) is not None}
        return b''.join(json_chunks(restored, policy=policy, default=decoded_json_default))

    with owned_resources() as resources:
        folder = resources.enter_context(tempfile.TemporaryDirectory(prefix='observation-check-'))
        db = sqlite3.connect(str(Path(folder) / 'values.sqlite'))
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; '
                             f'PRAGMA cache_size=-{policy.sqlite_cache_kib}; '
                             'CREATE TABLE observations(id INTEGER PRIMARY KEY,value BLOB NOT NULL);')
            count = 0
            for block in index['observations']['blocks']:
                if block['start'] != count:
                    raise ValueError('Observation dictionary is not contiguous.')
                with closing(read_block('observations', block)) as values:
                    for value in values:
                        db.execute('INSERT INTO observations VALUES (?,?)', (count, canonical(value))); count += 1
            if count != index['observations']['rows']:
                raise ValueError('Observation dictionary row count mismatch.')

            def reference_rows():
                start = 0
                for block in index['references']['blocks']:
                    if block['start'] != start:
                        raise ValueError('Observation references are not contiguous.')
                    yield from read_block('observation-rows', block)
                    start += block['count']

            references = resources.enter_context(closing(reference_rows()))
            sentinel = object()
            checked = 0
            for expected in observation_rows(source, policy=policy, metrics=metrics, stage='observation verification'):
                refs = next(references, sentinel)
                if refs is sentinel or (expected is None) != (refs is None):
                    raise ValueError('Observation publication changed source values.')
                if expected is not None:
                    if not isinstance(refs, list) or len(refs) != len(expected):
                        raise ValueError('Observation publication changed source values.')
                    for ref, value in zip(refs, observation_values(expected, policy=policy, metrics=metrics,
                                                 stage='observation verification'), strict=True):
                        if type(ref) is not int or ref < 0:
                            raise ValueError('Invalid observation reference.')
                        metrics['verification_lookups'] = metrics.get('verification_lookups', 0) + 1
                        stored = db.execute('SELECT value FROM observations WHERE id=?', (ref,)).fetchone()
                        if stored is None or stored[0] != canonical(value):
                            raise ValueError('Observation publication changed source values.')
                        del value, stored
                checked += 1
                if checked % 65536 == 0:
                    print(f'Verified source observations: {checked:,}', flush=True)
            if next(references, sentinel) is not sentinel or checked != index['references']['rows']:
                raise ValueError('Unexpected observation row count.')
        finally:
            db.close()
