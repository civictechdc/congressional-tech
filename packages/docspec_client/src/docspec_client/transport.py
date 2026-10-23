"""Transport primitives, BLAKE3 checksums, and Arrow IPC encoding."""
import json
from pathlib import Path
import struct
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import blake3 as _blake3_ext
except ImportError:
    _blake3_ext = None

from .models import PRODUCER_PARQUET_ROW_GROUP_SIZE
from .schema import native_storage_schema

_BLAKE3_IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)
_BLAKE3_MSG_PERMUTATION = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)
_BLAKE3_CHUNK_START = 1
_BLAKE3_CHUNK_END = 2
_BLAKE3_PARENT = 4
_BLAKE3_ROOT = 8


def _blake3_rotr32(x: int, n: int) -> int:
    return ((x >> n) | ((x << (32 - n)) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _blake3_g(state: list[int], a: int, b: int, c: int, d: int, mx: int, my: int) -> None:
    state[a] = (state[a] + state[b] + mx) & 0xFFFFFFFF
    state[d] = _blake3_rotr32(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _blake3_rotr32(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b] + my) & 0xFFFFFFFF
    state[d] = _blake3_rotr32(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _blake3_rotr32(state[b] ^ state[c], 7)


def _blake3_round(state: list[int], m: list[int]) -> None:
    _blake3_g(state, 0, 4, 8, 12, m[0], m[1])
    _blake3_g(state, 1, 5, 9, 13, m[2], m[3])
    _blake3_g(state, 2, 6, 10, 14, m[4], m[5])
    _blake3_g(state, 3, 7, 11, 15, m[6], m[7])
    _blake3_g(state, 0, 5, 10, 15, m[8], m[9])
    _blake3_g(state, 1, 6, 11, 12, m[10], m[11])
    _blake3_g(state, 2, 7, 8, 13, m[12], m[13])
    _blake3_g(state, 3, 4, 9, 14, m[14], m[15])


def _blake3_compress(cv: Any, block_words: Any, counter: int, block_len: int, flags: int) -> list[int]:
    state = [
        cv[0], cv[1], cv[2], cv[3],
        cv[4], cv[5], cv[6], cv[7],
        _BLAKE3_IV[0], _BLAKE3_IV[1], _BLAKE3_IV[2], _BLAKE3_IV[3],
        counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF, block_len, flags,
    ]
    m = list(block_words)
    for r in range(7):
        _blake3_round(state, m)
        if r < 6:
            m = [m[i] for i in _BLAKE3_MSG_PERMUTATION]
    for i in range(8):
        state[i] ^= state[i + 8]
        state[i + 8] ^= cv[i]
    return state


def _blake3_chunk_output(chunk_bytes: bytes, chunk_counter: int, flags: int) -> tuple[Any, Any, int, int, int]:
    cv = list(_BLAKE3_IV)
    num_blocks = max(1, (len(chunk_bytes) + 63) // 64)
    for b in range(num_blocks):
        start = b * 64
        block = chunk_bytes[start:start + 64]
        block_len = len(block)
        if block_len < 64:
            block = block + b'\x00' * (64 - block_len)
        words = struct.unpack('<16I', block)
        b_flags = flags
        if b == 0:
            b_flags |= _BLAKE3_CHUNK_START
        if b == num_blocks - 1:
            b_flags |= _BLAKE3_CHUNK_END
            return (cv, words, chunk_counter, block_len, b_flags)
        cv = _blake3_compress(cv, words, chunk_counter, block_len, b_flags)[:8]
    return (cv, (0,) * 16, chunk_counter, 0, flags)


def blake3_hex(data: bytes | bytearray | memoryview) -> str:
    """Compute the 64-character lowercase hex BLAKE3 digest of ``data`` in memory."""
    raw = bytes(data)
    if _blake3_ext is not None:
        return _blake3_ext.blake3(raw).hexdigest()
    num_chunks = max(1, (len(raw) + 1023) // 1024)
    cv_stack: list[list[int]] = []
    for c in range(num_chunks):
        chunk = raw[c * 1024:(c + 1) * 1024]
        out = _blake3_chunk_output(chunk, c, 0)
        if num_chunks == 1:
            words = _blake3_compress(out[0], out[1], out[2], out[3], out[4] | _BLAKE3_ROOT)[:8]
            return struct.pack('<8I', *words).hex()
        cv = _blake3_compress(*out)[:8]
        total_chunks = c + 1
        while (total_chunks & 1) == 0 and (len(cv_stack) > 1 or c + 1 < num_chunks):
            left_cv = cv_stack.pop()
            block_words = tuple(left_cv) + tuple(cv)
            cv = _blake3_compress(_BLAKE3_IV, block_words, 0, 64, _BLAKE3_PARENT)[:8]
            total_chunks >>= 1
        cv_stack.append(cv)
    while len(cv_stack) > 1:
        right_cv = cv_stack.pop()
        left_cv = cv_stack.pop()
        block_words = tuple(left_cv) + tuple(right_cv)
        is_root = len(cv_stack) == 0
        fl = _BLAKE3_PARENT | (_BLAKE3_ROOT if is_root else 0)
        if fl & _BLAKE3_ROOT:
            words = _blake3_compress(_BLAKE3_IV, block_words, 0, 64, fl)[:8]
            return struct.pack('<8I', *words).hex()
        cv_stack.append(_blake3_compress(_BLAKE3_IV, block_words, 0, 64, fl)[:8])
    return ''


def encode_arrow_ipc_stream(table: Any, *, native_types: bool = False) -> bytes:
    """Serialize an Arrow Table, RecordBatch, or RecordBatchReader into an Arrow IPC stream."""
    if isinstance(table, pa.RecordBatch):
        table = pa.Table.from_batches([table])
    elif isinstance(table, pa.RecordBatchReader):
        table = table.read_all()
    if not isinstance(table, pa.Table):
        raise TypeError('encode_arrow_ipc_stream requires a pyarrow.Table, RecordBatch, or RecordBatchReader')
    prepared = table if native_types else native_storage_schema(table)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, prepared.schema) as writer:
        writer.write_table(prepared)
    return sink.getvalue().to_pybytes()


def _write_producer_parquet(
    table: pa.Table,
    path: Path | str,
    *,
    row_group_size: int | None = PRODUCER_PARQUET_ROW_GROUP_SIZE,
    _legacy_row_group_sizing: bool = False,
) -> None:
    """Write producer Parquet inputs with bounded row groups so zero-copy Arrow slices stay within max_batch_bytes."""
    physical = native_storage_schema(table.schema, native_types=False)
    stored = table if physical.equals(table.schema, check_metadata=True) else table.cast(physical, safe=True)
    if row_group_size is None and not _legacy_row_group_sizing:
        if stored.nbytes <= 33_554_432:
            pq.write_table(stored, path, compression='zstd')
            return
        effective_rg = 8192
        target_rg_bytes = 16_000_000
    elif row_group_size is None and _legacy_row_group_sizing:
        if stored.nbytes <= 8_388_608:
            pq.write_table(stored, path, compression='zstd')
            return
        effective_rg = PRODUCER_PARQUET_ROW_GROUP_SIZE
        target_rg_bytes = 1_500_000
    else:
        effective_rg = row_group_size if row_group_size is not None else PRODUCER_PARQUET_ROW_GROUP_SIZE
        target_rg_bytes = 1_500_000
    if stored.num_rows > 1 and stored.nbytes > max(4_000_000, target_rg_bytes):
        avg_row_bytes = max(1, stored.nbytes // stored.num_rows)
        default_step = max(1, min(effective_rg, target_rg_bytes // avg_row_bytes))
        with pq.ParquetWriter(path, physical, compression='zstd') as writer:
            offset = 0
            total_rows = stored.num_rows
            while offset < total_rows:
                step = min(default_step, total_rows - offset)
                chunk = stored.slice(offset, step)
                while step > 1 and chunk.nbytes > target_rg_bytes:
                    step = max(1, step // 2)
                    chunk = stored.slice(offset, step)
                writer.write_table(chunk, row_group_size=step)
                offset += step
        return
    if stored.num_rows > 1 and stored.nbytes > target_rg_bytes:
        avg_row_bytes = max(1, stored.nbytes // stored.num_rows)
        effective_rg = max(1, min(effective_rg, target_rg_bytes // avg_row_bytes))
    pq.write_table(stored, path, compression='zstd', row_group_size=effective_rg)


def producer_input_entry(request_path: Path | str) -> dict[str, Any] | None:
    """Return the producer files referenced by a retained request, with total bytes."""
    try:
        request = json.loads(Path(request_path).read_text())
    except (OSError, ValueError):
        request = None
    if not isinstance(request, dict):
        return None
    paths: list[str] = []
    for value in (request.get('input'),
                  (request.get('replacements') or {}).get('path')
                  if isinstance(request.get('replacements'), dict) else None,
                  (request.get('deletions') or {}).get('path')
                  if isinstance(request.get('deletions'), dict) else None):
        if isinstance(value, str) and value and value not in paths:
            paths.append(value)
    if not paths:
        return None
    files: list[dict[str, Any]] = []
    total = 0
    for path in paths:
        try:
            size: int | None = Path(path).stat().st_size
        except FileNotFoundError:
            size = None
        else:
            if size is not None:
                total += size
        files.append(dict(path=path, bytes=size))
    return dict(input=paths[0], request=str(request_path), bytes=total, files=files)
