"""Transport primitives, BLAKE3 checksums, and Arrow IPC encoding."""
import json
from pathlib import Path
from typing import Any

import blake3
import pyarrow as pa
import pyarrow.parquet as pq

from .models import PRODUCER_PARQUET_ROW_GROUP_SIZE
from .schema import native_storage_schema


def blake3_hex(data: bytes | bytearray | memoryview) -> str:
    """Compute the 64-character lowercase hex BLAKE3 digest of ``data`` in memory."""
    return blake3.blake3(bytes(data)).hexdigest()


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
