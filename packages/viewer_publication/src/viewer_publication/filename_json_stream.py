"""Read one exact JSON array item at a time from independently compressed parts."""
from decimal import Decimal
import io
import hashlib
import struct
import tempfile

import ijson
import pyarrow as pa

from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, maximum, refuse


class ObservationCounts:
    """Owned process-local count handoff; never reconstruct reference sidecars."""
    def __init__(self, source):
        self.source, self.rows = source, 0
        self.stream = tempfile.TemporaryFile()
        self.sealed = False
        self.digest = hashlib.sha256()

    def __enter__(self): return self
    def __exit__(self, *args): self.stream.close()

    def append(self, value):
        if self.sealed: raise ValueError('Observation counts already sealed')
        if type(value) is not int or not 0 <= value < 2**64:
            raise ValueError('Invalid observation count')
        raw = struct.pack('<Q', value)
        self.stream.write(raw); self.digest.update(raw); self.rows += 1

    def seal(self, source_rows):
        if self.rows != source_rows: raise ValueError('Observation count/source rows differ')
        self.stream.flush(); self.sealed = True

    def values(self, source):
        if source is not self.source or not self.sealed:
            raise ValueError('Observation counts do not cover this source')
        self.stream.seek(0)
        actual = hashlib.sha256()
        for _ in range(self.rows):
            raw = self.stream.read(8)
            if len(raw) != 8: raise ValueError('Observation counts are incomplete')
            actual.update(raw)
            yield struct.unpack('<Q', raw)[0]
        if self.stream.read(1): raise ValueError('Observation counts have trailing bytes')
        if actual.digest() != self.digest.digest(): raise ValueError('Observation counts changed after construction')


class PartReader(io.RawIOBase):
    def __init__(self, path, block, policy, metrics):
        super().__init__()
        parts = block['parts']
        if type(block['count']) is not int or block['count'] < 1 or not isinstance(parts, list) or not parts:
            raise ValueError('Invalid observation block')
        for part in parts:
            if (not isinstance(part, (list, tuple)) or len(part) != 3 or
                    any(type(value) is not int for value in part) or
                    part[0] < 0 or not 1 <= part[1] <= 2 * 1024**2 or not 1 <= part[2] <= 1024**2):
                raise ValueError('Invalid observation part')
        total = sum(part[2] for part in parts)
        if total > policy.logical_json_bytes + 2:
            refuse('JSON reconstruction', 'logical block bytes', total, policy.logical_json_bytes + 2)
        self.parts = iter(parts); self.buffer = memoryview(b''); self.position = 0
        self.first = True
        self.metrics, self.stream = metrics, path.open('rb')

    def readable(self): return True

    def readinto(self, target):
        if not target: return 0
        if self.position == len(self.buffer):
            part = next(self.parts, None)
            if part is None: return 0
            offset, size, decoded = part
            self.stream.seek(offset); encoded = self.stream.read(size)
            if len(encoded) != size: raise ValueError('Incomplete observation part')
            self.buffer = memoryview(pa.decompress(encoded, decoded, codec='brotli')); self.position = 0
            if len(self.buffer) != decoded: raise ValueError('Observation part length differs')
            if self.first and self.buffer[0] != ord('['): raise ValueError('Observation block must be a JSON array')
            self.first = False
            self.metrics['decoded_parts'] = self.metrics.get('decoded_parts', 0) + 1
            maximum(self.metrics, 'max_decoded_part_bytes', decoded)
        count = min(len(target), len(self.buffer) - self.position)
        target[:count] = self.buffer[self.position:self.position + count]; self.position += count
        return count

    def close(self):
        if not self.closed:
            self.buffer = memoryview(b'')
            if hasattr(self, 'stream'): self.stream.close()
        super().close()


def block_items(path, block, *, policy=DEFAULT_DECODED_POLICY, metrics=None):
    metrics = metrics if metrics is not None else {}
    count = 0
    with PartReader(path, block, policy, metrics) as stream:
        # Default numeric mode preserves arbitrary-size integers. Decimal tokens
        # become floats only when canonicalized, matching stdlib json.loads.
        for value in ijson.items(stream, 'item', use_float=False):
            count += 1
            if count > block['count']: raise ValueError('Observation block count mismatch')
            yield value
    if count != block['count']: raise ValueError('Observation block count mismatch')


def decoded_json_default(value):
    if isinstance(value, Decimal): return float(value)
    raise TypeError(f'Unsupported decoded JSON value: {type(value).__name__}')
