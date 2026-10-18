"""Decoded preparation admission; source bytes remain untouched on refusal."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

MiB = 1024**2


class DecodedBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class DecodedPolicy:
    native_batch_rows: int = 128
    batch_arrow_bytes: int = 4 * MiB
    row_arrow_bytes: int = 16 * MiB
    batch_python_estimate: int = 32 * MiB
    row_python_estimate: int = 128 * MiB
    logical_json_bytes: int = 32 * MiB
    sqlite_cache_kib: int = 8192

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError('Decoded preparation budgets must be positive integers')


DEFAULT_DECODED_POLICY = DecodedPolicy()


def maximum(metrics, name, value):
    metrics[name] = max(metrics.get(name, 0), value)


def refuse(stage, quantity, observed, limit):
    raise DecodedBudgetExceeded(f'{stage}: {quantity} {observed} exceeds decoded preparation limit {limit}; '
                               'source retained, no partial publication is accepted')


def python_estimate(batch):
    # Admission accounting, not an engine heap measurement. Payload expansion
    # covers Unicode/escaping copies; explicit containers also cover empty or
    # mostly-null nested structs whose Arrow buffers can be very small.
    def containers(column):
        kind = column.type
        if pa.types.is_struct(kind):
            names = sum(128 + 4 * len(field.name) for field in kind)
            return len(column) * (64 + names) + sum(containers(column.field(i)) for i in range(len(kind)))
        if pa.types.is_list(kind) or pa.types.is_large_list(kind):
            start, stop = column.offsets[0].as_py(), column.offsets[-1].as_py()
            values = column.values.slice(start, stop - start)
            return len(column) * 64 + len(values) * 8 + containers(values)
        if pa.types.is_fixed_size_list(kind):
            values = column.values.slice(column.offset * kind.list_size, len(column) * kind.list_size)
            return len(column) * 64 + len(values) * 8 + containers(values)
        return 0
    cells = 64 + sum(128 + 4 * len(name) for name in batch.schema.names)
    return batch.nbytes * 16 + batch.num_rows * cells + sum(containers(column) for column in batch.columns)


def bounded_batches(source, *, columns=None, batch_rows=8192, policy=DEFAULT_DECODED_POLICY,
                    stage='preparation', metrics=None):
    metrics = metrics if metrics is not None else {}
    batch_rows = min(batch_rows, policy.native_batch_rows)
    def admitted(batch):
        estimate = python_estimate(batch)
        if batch.num_rows == 1:
            if batch.nbytes > policy.row_arrow_bytes:
                refuse(stage, 'single-row Arrow bytes', batch.nbytes, policy.row_arrow_bytes)
            if estimate > policy.row_python_estimate:
                refuse(stage, 'single-row Python/JSON estimate', estimate, policy.row_python_estimate)
            if batch.nbytes > policy.batch_arrow_bytes or estimate > policy.batch_python_estimate:
                metrics['oversized_rows_admitted'] = metrics.get('oversized_rows_admitted', 0) + 1
        elif (batch.nbytes > min(policy.batch_arrow_bytes, policy.row_arrow_bytes) or
              estimate > min(policy.batch_python_estimate, policy.row_python_estimate)):
            middle = batch.num_rows // 2
            yield from admitted(batch.slice(0, middle))
            yield from admitted(batch.slice(middle))
            return
        maximum(metrics, 'max_batch_arrow_bytes', batch.nbytes)
        maximum(metrics, 'max_admitted_buffer_bytes', batch.get_total_buffer_size())
        maximum(metrics, 'max_python_json_estimate', estimate)
        yield batch
    metadata = getattr(source, 'metadata', None)
    if metadata is None:
        # An already-decoded in-memory provider has no physical file admission.
        for batch in source.iter_batches(batch_size=batch_rows, columns=columns):
            yield from admitted(batch)
        return
    for group in range(metadata.num_row_groups):
        planned = plan_native_rows(metadata.row_group(group), columns=columns, batch_rows=batch_rows,
                                   policy=policy, metrics=metrics)
        for batch in source.iter_batches(batch_size=planned, columns=columns, row_groups=[group], use_threads=False):
            maximum(metrics, 'max_native_batch_arrow_bytes', batch.nbytes)
            maximum(metrics, 'max_native_batch_buffer_bytes', batch.get_total_buffer_size())
            maximum(metrics, 'max_native_batch_rows', len(batch))
            yield from admitted(batch)


def plan_native_rows(group, *, columns=None, batch_rows=8192, policy=DEFAULT_DECODED_POLICY, metrics=None):
    """Plan from mean selected chunk bytes per row; not an allocation bound."""
    metrics = metrics if metrics is not None else {}
    selected = None if columns is None else tuple(columns)
    size = 0
    for index in range(group.num_columns):
        column = group.column(index)
        if selected is None or any(column.path_in_schema == prefix or
                column.path_in_schema.startswith(prefix + '.') for prefix in selected):
            size += column.total_uncompressed_size
    maximum(metrics, 'max_physical_group_bytes', size)
    rows = max(1, min(batch_rows, policy.native_batch_rows,
                      policy.batch_arrow_bytes * group.num_rows // max(1, size)))
    maximum(metrics, 'max_planned_native_rows', rows)
    metrics['min_planned_native_rows'] = min(metrics.get('min_planned_native_rows', rows), rows)
    return rows


def open_parquet(path):
    """Open an owned reader with bounded read buffering and no parallel readahead."""
    return pq.ParquetFile(path, pre_buffer=False, buffer_size=64 * 1024)


class ArrowStager:
    """Coalesce admitted batches without copying; logical bytes are not RSS."""
    def __init__(self, writer, schema, *, row_group_size=8192, policy=DEFAULT_DECODED_POLICY,
                 metrics=None, stage='output'):
        self.writer, self.schema = writer, schema
        self.row_group_size, self.policy, self.stage = row_group_size, policy, stage
        self.metrics = metrics if metrics is not None else {}
        self.pending, self.size, self.rows = [], 0, 0

    def append(self, batch):
        if not len(batch): return
        if len(batch) == 1 and batch.nbytes > self.policy.row_arrow_bytes:
            refuse(self.stage, 'single output-row Arrow bytes', batch.nbytes, self.policy.row_arrow_bytes)
        if len(batch) > 1 and (batch.nbytes > min(self.policy.batch_arrow_bytes, self.policy.row_arrow_bytes) or
                               len(batch) > self.row_group_size):
            middle = len(batch) // 2
            self.append(batch.slice(0, middle)); self.append(batch.slice(middle))
            return
        if self.pending and (self.size + batch.nbytes > self.policy.batch_arrow_bytes or
                             self.rows + len(batch) > self.row_group_size):
            self.flush()
        self.pending.append(batch); self.size += batch.nbytes; self.rows += len(batch)
        maximum(self.metrics, f'max_{self.stage}_staged_arrow_bytes', self.size)
        # An admitted oversized single row gets its own output group.
        if self.size >= self.policy.batch_arrow_bytes or self.rows >= self.row_group_size:
            self.flush()

    def flush(self):
        if not self.pending: return
        table = pa.Table.from_batches(self.pending, schema=self.schema)
        maximum(self.metrics, f'max_{self.stage}_staged_buffer_bytes', table.get_total_buffer_size())
        self.writer.write_table(table, row_group_size=self.row_group_size)
        self.pending, self.size, self.rows = [], 0, 0


def json_chunks(value, *, policy=DEFAULT_DECODED_POLICY, default=None, metrics=None):
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=default)
    size = 0
    for piece in encoder.iterencode(value):
        encoded = piece.encode('utf-8'); size += len(encoded)
        if size > policy.logical_json_bytes:
            refuse('JSON serialization', 'logical value bytes', size, policy.logical_json_bytes)
        yield encoded
    if metrics is not None:
        metrics['serialized_values'] = metrics.get('serialized_values', 0) + 1
        maximum(metrics, 'max_serialized_value_bytes', size)


def failure_receipt(folder, error, policy, metrics):
    folder = Path(folder)
    value = {'status': 'refused', 'error_type': type(error).__name__, 'error': str(error),
             'policy': asdict(policy), 'metrics': metrics, 'source_preserved': True,
             'partial_publication_accepted': False}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'preparation-memory-failure.json').write_text(json.dumps(value, indent=2) + '\n')
    except BaseException as cleanup:
        error.add_note(f'Memory refusal receipt also failed: {cleanup}')
