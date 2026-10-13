"""Lossless, bounded reads of nested observations alongside the full Parquet.

Repeated observations share a dictionary entry. Each block contains JSON with
null struct fields omitted; the schema restores them on read. Large individual
values span independently compressed parts instead of increasing decode size.
"""
from collections import OrderedDict
import hashlib
import json

import pyarrow as pa

BLOCK_BYTES = 1024 * 1024


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


class Blocks:
    def __init__(self, path, row_limit=None):
        self.path, self.row_limit = path, row_limit
        self.stream = path.open('wb')
        self.blocks, self.pending = [], []
        self.pending_bytes, self.rows = 2, 0

    def append(self, value):
        value = json_bytes(value)
        if self.pending and (self.pending_bytes + len(value) + 1 > BLOCK_BYTES or
                             self.row_limit and len(self.pending) >= self.row_limit):
            self.flush()
        self.pending.append(value)
        self.pending_bytes += len(value) + 1

    def flush(self):
        if not self.pending:
            return
        raw = b'[' + b','.join(self.pending) + b']'
        parts = []
        for start in range(0, len(raw), BLOCK_BYTES):
            piece = raw[start:start + BLOCK_BYTES]
            encoded = pa.compress(piece, codec='brotli').to_pybytes()
            offset = self.stream.tell()
            self.stream.write(encoded)
            parts.append([offset, len(encoded), len(piece)])
        self.blocks.append(dict(start=self.rows, count=len(self.pending), parts=parts))
        self.rows += len(self.pending)
        self.pending, self.pending_bytes = [], 2

    def close(self):
        self.flush()
        self.stream.close()
        return dict(rows=self.rows, blocks=self.blocks)


def publish_observations(source, output):
    fields = [field.name for field in source.schema_arrow.field('source_occurrences').type.value_type]
    observations = Blocks(output / 'observations.bin')
    references = Blocks(output / 'observation-rows.bin', row_limit=1024)
    identities = {}
    for batch in source.iter_batches(batch_size=128, columns=['source_occurrences']):
        for values in batch.column(0).to_pylist():
            refs = None if values is None else []
            for observation in values or []:
                compact = None if observation is None else {key: value for key, value in observation.items() if value is not None}
                identity = hashlib.sha256(json_bytes(compact)).digest()
                if identity not in identities:
                    identities[identity] = len(identities)
                    observations.append(compact)
                refs.append(identities[identity])
            references.append(refs)
    index = dict(version=1, fields=fields, max_part_bytes=BLOCK_BYTES,
                 observations=observations.close(), references=references.close())
    (output / 'observation-index.json').write_bytes(json_bytes(index))
    # Read the written files back, reconstruct every source list, and compare
    # against Arrow. This also checks ordering, nulls, duplicates and locators.
    verify_observations(source, output, index)
    return index


def verify_observations(source, output, index):
    import bisect
    cache = OrderedDict()
    starts = [block['start'] for block in index['observations']['blocks']]

    def read_block(name, block):
        key = (name, block['start'])
        if key not in cache:
            pieces = []
            with (output / f'{name}.bin').open('rb') as stream:
                for offset, size, decoded in block['parts']:
                    stream.seek(offset)
                    pieces.append(pa.decompress(stream.read(size), decoded, codec='brotli').to_pybytes())
            cache[key] = json.loads(b''.join(pieces))
            if len(cache[key]) != block['count']:
                raise ValueError('Observation block count mismatch.')
        cache.move_to_end(key)
        while len(cache) > 8:
            cache.popitem(last=False)
        return cache[key]

    def restore(reference):
        block = index['observations']['blocks'][bisect.bisect_right(starts, reference) - 1]
        value = read_block('observations', block)[reference - block['start']]
        return None if value is None else {field: value.get(field) for field in index['fields']}

    def reconstructed():
        for block in index['references']['blocks']:
            for refs in read_block('observation-rows', block):
                yield None if refs is None else [restore(ref) for ref in refs]

    actual = reconstructed()
    for batch in source.iter_batches(batch_size=128, columns=['source_occurrences']):
        for expected in batch.column(0).to_pylist():
            if next(actual) != expected:
                raise ValueError('Observation publication changed source values.')
    if next(actual, False) is not False:
        raise ValueError('Unexpected trailing observation rows.')
