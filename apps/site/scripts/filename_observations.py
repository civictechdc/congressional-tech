"""Lossless, bounded reads of nested observations alongside the full Parquet.

Repeated observations share a dictionary entry. Each block contains JSON with
null struct fields omitted; the schema restores them on read. Large individual
values span independently compressed parts instead of increasing decode size.
"""
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
    """Check every value using a disk dictionary, decoding each block once."""
    import sqlite3
    import tempfile
    from pathlib import Path

    fields = [field.name for field in source.schema_arrow.field('source_occurrences').type.value_type]
    if index['fields'] != fields:
        raise ValueError('Observation schema changed.')

    def read_block(name, block):
        pieces = []
        with (output / f'{name}.bin').open('rb') as stream:
            for offset, size, decoded in block['parts']:
                stream.seek(offset)
                pieces.append(pa.decompress(stream.read(size), decoded, codec='brotli').to_pybytes())
        values = json.loads(b''.join(pieces))
        if len(values) != block['count']:
            raise ValueError('Observation block count mismatch.')
        return values

    def canonical(value):
        # Match the browser's schema restoration, preserving null observations,
        # list order, duplicates, and null versus empty field values.
        return json_bytes(None if value is None else
                          {field: value[field] for field in fields if value.get(field) is not None})

    with tempfile.TemporaryDirectory(prefix='observation-check-') as folder:
        db = sqlite3.connect(str(Path(folder) / 'values.sqlite'))
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; '
                             'PRAGMA cache_size=-8192; '
                             'CREATE TABLE observations(id INTEGER PRIMARY KEY,value BLOB NOT NULL);')
            count = 0
            for block in index['observations']['blocks']:
                if block['start'] != count:
                    raise ValueError('Observation dictionary is not contiguous.')
                values = read_block('observations', block)
                db.executemany('INSERT INTO observations VALUES (?,?)',
                               ((count + i, canonical(value)) for i, value in enumerate(values)))
                count += len(values)
            if count != index['observations']['rows']:
                raise ValueError('Observation dictionary row count mismatch.')

            def reference_rows():
                start = 0
                for block in index['references']['blocks']:
                    if block['start'] != start:
                        raise ValueError('Observation references are not contiguous.')
                    yield from read_block('observation-rows', block)
                    start += block['count']

            references = reference_rows()
            sentinel = object()
            checked = 0
            for batch in source.iter_batches(batch_size=128, columns=['source_occurrences']):
                for expected in batch.column(0).to_pylist():
                    refs = next(references, sentinel)
                    if refs is sentinel or (expected is None) != (refs is None):
                        raise ValueError('Observation publication changed source values.')
                    if expected is not None:
                        if len(refs) != len(expected):
                            raise ValueError('Observation publication changed source values.')
                        for ref, value in zip(refs, expected, strict=True):
                            if type(ref) is not int or ref < 0:
                                raise ValueError('Invalid observation reference.')
                            stored = db.execute('SELECT value FROM observations WHERE id=?', (ref,)).fetchone()
                            if stored is None or stored[0] != canonical(value):
                                raise ValueError('Observation publication changed source values.')
                    checked += 1
                    if checked % 65536 == 0:
                        print(f'Verified source observations: {checked:,}', flush=True)
            if next(references, sentinel) is not sentinel or checked != index['references']['rows']:
                raise ValueError('Unexpected observation row count.')
        finally:
            db.close()
