"""Count actual native calls before/after alias coalescing on one fixed fixture."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import types

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
from congress_api.retention.docspec import NativeDatasets

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('routed_fixture', HERE / 'measure_routed.py')
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
BASELINE = '2a45bca'
SOURCE = 'packages/congress_api/src/congress_api/retention/catalog_dependency_storage.py'


class CountedNative(NativeDatasets):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.run_calls = 0
    def run_table(self, table, **kwargs):
        self.run_calls += 1
        return super().run_table(table, **kwargs)


def case(cls, binary, output, max_rows, max_bytes):
    output.mkdir()
    limits = output / 'limits.json'
    limits.write_text(json.dumps(dict(compute_threads=2, memory_bytes=512 << 20,
        scratch_bytes=256 << 20, batch_rows=8, max_batch_bytes=4 << 20, max_metadata_bytes=8 << 20)))
    native = CountedNative(binary, output / 'workspace', limits=limits)
    objects = LocalStore(output / 'objects')
    rows = fixture.fixture(10)
    def owner():
        return cls(native=native, store=objects, namespace='native-call-proof',
                   source_schema=fixture.SCHEMA, max_rows=max_rows, max_bytes=max_bytes)
    first = owner().prepare(None, replacements=rows)
    adoption_calls = native.run_calls
    native.run_calls = 0
    second = owner().prepare(first, deletions=[index.source_identity(rows[2])])
    correction_calls = native.run_calls
    # Check every retained source field through a cold owner after measurement.
    selected = owner().selected(second)
    expected = fixture.pa.Table.from_pylist([row for i, row in enumerate(rows) if i != 2], schema=fixture.SCHEMA).to_pylist()
    actual = [selected.source(index.source_identity(row)) for i, row in enumerate(rows) if i != 2]
    assert actual == expected
    assert selected.source(index.source_identity(rows[2])) is None
    (output / 'before.json').write_text(json.dumps(first, indent=2) + '\n')
    (output / 'after.json').write_text(json.dumps(second, indent=2) + '\n')
    return dict(input_sources=len(rows), max_rows=max_rows, max_arrow_bytes=max_bytes,
                adoption_run_calls=adoption_calls, correction_run_calls=correction_calls,
                all_source_fields_equal=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    baseline_source = subprocess.check_output(['git', 'show', f'{BASELINE}:{SOURCE}'])
    baseline = types.ModuleType('baseline_catalog_storage')
    baseline.__package__ = 'congress_api.retention'
    exec(compile(baseline_source, f'{BASELINE}:{SOURCE}', 'exec'), baseline.__dict__)
    results = {}
    for name, rows, size in [('small-test', 4, 1 << 20), ('configured', 8192, 64 << 20)]:
        results[name] = {}
        for arm, cls in [('before', baseline.CatalogDependencyStorage), ('after', CatalogDependencyStorage)]:
            results[name][arm] = case(cls, args.binary, args.output / f'{name}-{arm}', rows, size)
    summary = dict(baseline=BASELINE, baseline_storage_sha256=sha256(baseline_source).hexdigest(),
        candidate_storage_sha256=sha256(Path(__import__(
            'congress_api.retention.catalog_dependency_storage', fromlist=['__file__']).__file__).read_bytes()).hexdigest(),
        native_binary_sha256=sha256(args.binary.read_bytes()).hexdigest(), results=results,
        scope='Actual local native Run calls, same 13-source adoption and one bridge deletion. No remote cost, throughput or production adoption claim.')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
