"""Measure catalog lookup work separately from native engine transport costs.

Growth diagnostics use an Arrow transport recorder. A separate small local case
executes actual maintained native Runs and exact-pin reads, retaining its files.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependencies import affected_sources
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.docspec import NativeDatasets

SCHEMA = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS)])


def fixture(unrelated):
    def row(name, body):
        return dict(body_key=body, filename=name, source_url='https://example.gov/' + name,
                    media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved'])
    return [row('a.pdf', 'A'), row('b.pdf', 'B'), row('a.pdf', 'B'), *[
        row(f'{i}.pdf', f'unrelated-{i}') for i in range(unrelated)]]


class Objects:
    def __init__(self):
        self.values = {}
        self.read_bytes = self.read_calls = self.write_bytes = self.write_calls = 0
    def read(self, key):
        value = self.values.get(key)
        self.read_calls += 1
        self.read_bytes += len(value or b'')
        return value
    def put(self, key, value, *, immutable=False):
        if key in self.values and self.values[key] != value:
            raise ValueError('Conflicting immutable fixture metadata')
        self.values[key] = value
        self.write_calls += 1
        self.write_bytes += len(value)


class ArrowTransport:
    """Test transport only; no native file, CPU, memory or I/O cost is measured."""
    def __init__(self):
        self.tables = {}
        self.reset()
    def reset(self):
        self.read_rows = self.read_bytes = self.read_calls = self.submitted_rows = self.submitted_bytes = 0
    def run_table(self, table, *, dataset, operation, definition):
        if dataset in self.tables and not self.tables[dataset].equals(table):
            raise ValueError('Conflicting fixture candidate')
        self.tables[dataset] = table
        self.submitted_rows += len(table)
        self.submitted_bytes += table.nbytes
        return {'dataset_key': dataset}
    @contextmanager
    def source_batches(self, pin):
        table = self.tables[pin['dataset_key']]
        self.read_rows += len(table)
        self.read_bytes += table.nbytes
        self.read_calls += 1
        yield table.to_reader()


def owner(native, objects):
    return CatalogDependencyStorage(native=native, store=objects, namespace='catalog-proof',
                                    source_schema=SCHEMA, max_rows=4, max_bytes=1 << 20)


def growth(unrelated):
    native, objects = ArrowTransport(), Objects()
    rows = fixture(unrelated)
    selected = owner(native, objects).prepare(None, replacements=rows)
    native.reset()
    objects.read_bytes = objects.read_calls = objects.write_bytes = objects.write_calls = 0
    changed = owner(native, objects).prepare(selected, deletions=[index.source_identity(rows[2])])
    measured = dict(unrelated_sources=unrelated, source_records_in_closed_old_scope=3,
        source_records_in_closed_new_scope=2, native_partition_calls=native.read_calls,
        native_partition_arrow_rows=native.read_rows, native_partition_arrow_bytes=native.read_bytes,
        submitted_arrow_rows=native.submitted_rows, submitted_arrow_bytes=native.submitted_bytes,
        metadata_reads=objects.read_calls, metadata_read_bytes=objects.read_bytes,
        metadata_put_calls=objects.write_calls, metadata_put_bytes=objects.write_bytes)
    # Offline exhaustive reference runs after capturing changed-path metrics.
    after = owner(native, objects).selected(changed)
    expected = pa.Table.from_pylist([row for i, row in enumerate(rows) if i != 2], schema=SCHEMA).to_pylist()
    actual = [after.source(index.source_identity(row)) for i, row in enumerate(rows) if i != 2]
    assert actual == expected
    assert after.source(index.source_identity(rows[2])) is None
    measured['all_source_fields_equal_offline_reference'] = True
    measured['growth_metric_scope'] = 'Application partition calls and Arrow payload sizes using a transport recorder; excludes native engine and physical I/O costs.'
    return measured


def actual_native(binary, output):
    output.mkdir()
    limits = output / 'limits.json'
    limits.write_text(json.dumps(dict(compute_threads=2, memory_bytes=512 << 20,
        scratch_bytes=256 << 20, batch_rows=2, max_batch_bytes=4 << 20, max_metadata_bytes=8 << 20)))
    native = NativeDatasets(binary, output / 'workspace', limits=limits)
    store = LocalStore(output / 'objects')
    rows = fixture(0)
    first = owner(native, store).prepare(None, replacements=rows)
    second = owner(native, store).prepare(first, deletions=[index.source_identity(rows[2])])
    fresh = owner(NativeDatasets(binary, output / 'workspace', limits=limits), LocalStore(output / 'objects'))
    before = fresh.selected(first)
    scope = affected_sources(before, deletions=[index.source_identity(rows[2])])
    after = fresh.selected(second)
    assert set(scope.after) == {index.source_identity(row) for row in rows[:2]}
    assert after.source(index.source_identity(rows[2])) is None
    assert before.source(index.source_identity(rows[2])) is not None
    assert [after.order(index.source_identity(row)) for row in rows[:2]] == [0, 1]
    (output / 'before.json').write_text(json.dumps(first, indent=2) + '\n')
    (output / 'after.json').write_text(json.dumps(second, indent=2) + '\n')
    inventory = lambda: {str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest()
                         for path in output.rglob('*') if path.is_file()}
    retained = inventory()
    assert fresh.prepare(first, deletions=[index.source_identity(rows[2])]) == second
    assert inventory() == retained
    return dict(exact_old_new_roots=True, old_source_retained=True, source_order_preserved=True,
                fresh_domain_owner=True, native_cli_process_per_call=True, completed_retry_files_unchanged=True,
                scope='Local native storage only; this is not a fresh-host or production custody claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    measured = [growth(size) for size in (10, 1000)]
    assert all(case['native_partition_arrow_rows'] < 100 for case in measured)
    summary = dict(growth=measured, native_case=actual_native(args.binary, args.output / 'native'),
                   production_adoption=False, native_binary_sha256=sha256(args.binary.read_bytes()).hexdigest())
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
