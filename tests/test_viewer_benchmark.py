"""The benchmark must not qualify changed values or mismatched browser evidence."""
from copy import deepcopy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/measure'))
spec = importlib.util.spec_from_file_location('viewer_benchmark', ROOT / 'scripts/measure/benchmark_viewer_publication.py')
benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)


def browser():
    return {'status': 'complete', 'repetitions': 5, 'runtime': {'platform': 'linux', 'browser': 'exact'},
            'loader_hashes': {'loader': 'exact'}, 'bundle_sha256': 'bundle', 'cache_condition': 'fresh',
            'inputs': {name: 'exact' for name in ('catalog_id', 'source_manifest', 'review_identity_sha256',
                'review_descriptor', 'review_data_sha256', 'accepted_sha256', 'recovery_sha256',
                'cases_sha256', 'cases', 'expected')},
            'samples': [{'case_id': 'detail', 'milliseconds': value, 'result_sha256': 'exact'} for value in [9, 8, 10, 7, 9]]}


def test_browser_gate_checks_each_case_latency_and_exact_values():
    reference = browser(); candidate = deepcopy(reference)
    assert benchmark.compare_browser(reference, candidate)['qualified']
    candidate['samples'][-1]['milliseconds'] = 12
    assert not benchmark.compare_browser(reference, candidate)['qualified']
    candidate['samples'][-1]['result_sha256'] = 'changed'
    assert benchmark.compare_browser(reference, candidate)['reason'] == 'browser_result_values_differ'


def test_browser_gate_refuses_changed_review_pins_cases_and_runtime():
    reference = browser()
    for key in ('review_data_sha256', 'cases_sha256', 'accepted_sha256', 'source_manifest'):
        candidate = deepcopy(reference); candidate['inputs'][key] = 'changed'
        assert not benchmark.compare_browser(reference, candidate)['qualified']
    candidate = deepcopy(reference); candidate['runtime']['browser'] = 'different'
    assert not benchmark.compare_browser(reference, candidate)['qualified']


def test_short_or_failed_browser_runs_cannot_qualify():
    reference = browser(); candidate = deepcopy(reference); candidate['repetitions'] = 2
    assert not benchmark.compare_browser(reference, candidate)['qualified']
    assert not benchmark.compare_browser(reference, None)['qualified']


def test_only_reencoded_filename_bytes_may_change():
    reference = {'worker': {'manifest': {'source_manifest': {'catalog_id': 'same'}, 'files': {
        'documents': {'path': 'docs.parquet'}, 'filenames': {'path': 'names.parquet'}}},
        'inventory': {'docs.parquet': {'sha256': 'a'}, 'names.parquet': {'sha256': 'b'},
                      'ids/aa.bin': {'sha256': 'id'}, 'review-binding.json': {'sha256': 'review'}}}}
    candidate = deepcopy(reference); candidate['worker']['inventory']['names.parquet']['sha256'] = 'compressed'
    assert benchmark.compare_outputs(reference, candidate)
    candidate['worker']['inventory']['docs.parquet']['sha256'] = 'changed-archive'
    assert not benchmark.compare_outputs(reference, candidate)
    candidate['worker']['inventory']['ids/aa.bin']['sha256'] = 'changed-id'
    assert not benchmark.compare_outputs(reference, candidate)
    candidate = deepcopy(reference); candidate['worker']['inventory']['review-binding.json']['sha256'] = 'changed-review'
    assert not benchmark.compare_outputs(reference, candidate)


def test_exact_gate_requires_source_archive_bytes_and_filename_value_verification():
    facts = {'bytes': 10, 'sha256': 'source', 'rows': 2}
    worker = {'manifest': {'source_manifest': {'files': {'documents': facts}},
        'files': {'documents': dict(facts, path='docs.parquet', encoding={'mode': 'source_passthrough', 'source_sha256': 'source'})}},
        'inventory': {'docs.parquet': {'bytes': 10, 'sha256': 'source'}},
        'timings': {'documents_copy': dict(facts, verification_method='complete_sha256_bytes'),
                    'filenames_repack': {'exact_equal': True}}}
    assert benchmark.exact_table_verification(worker)
    for where, key, changed in [('documents_copy', 'sha256', 'changed'), ('documents_copy', 'rows', 3),
                                ('documents_copy', 'verification_method', 'sample'),
                                ('filenames_repack', 'exact_equal', False)]:
        candidate = deepcopy(worker); candidate['timings'][where][key] = changed
        assert not benchmark.exact_table_verification(candidate)
    candidate = deepcopy(worker); candidate['manifest']['files']['documents']['encoding']['mode'] = 'reencoded'
    assert not benchmark.exact_table_verification(candidate)
    for missing in (False, True):
        candidate = deepcopy(worker)
        if missing: del candidate['inventory']['docs.parquet']
        else: candidate['inventory']['docs.parquet']['sha256'] = 'altered'
        assert not benchmark.exact_table_verification(candidate)


def test_moved_browser_runner_resolves_loaders_and_server_before_browser_launch(tmp_path):
    import json
    import os
    import shutil
    import subprocess

    import pytest

    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the browser runner path check')
    # Replace only third-party browser/build dependencies. Execute the real JS
    # entrypoint, loader hashing, path resolution, spawn, and receipt handling.
    preload = tmp_path / 'dependencies.cjs'
    preload.write_text('''
const Module = require('node:module');
const original = Module._load;
Module._load = function(name, ...rest) {
  if (name === 'esbuild') return {version: 'fixture', build: async options => {
    if (!require('node:fs').existsSync(options.stdin.resolveDir + '/filename-catalog.mjs')) throw Error('bad resolveDir');
    require('node:fs').writeFileSync(options.outfile, 'fixture');
  }};
  if (name === 'playwright/package.json') return {version: 'fixture'};
  if (name === 'playwright') return {chromium: {launch: async () => {throw Error('PATHS_REACHED_BROWSER');}}};
  return original.call(this, name, ...rest);
};
''')
    python = tmp_path / 'server-check'
    python.write_text(f'''#!{sys.executable}
from pathlib import Path
import json,sys
expected=Path({str(ROOT)!r})/'scripts/measure/viewer_benchmark_server.py'
assert Path(sys.argv[1]) == expected and expected.is_file(), sys.argv
print(json.dumps({{"server_path_verified":True}}),flush=True)
''')
    python.chmod(0o755)
    output = tmp_path / 'output'
    result = subprocess.run([node, '--require', str(preload),
                             str(ROOT / 'scripts/measure/benchmark_viewer_browser.mjs'),
                             '--publication', str(tmp_path), '--output', str(output),
                             '--review-data', str(tmp_path / 'reviews.json'), '--repeats', '2',
                             '--python', str(python)], cwd=tmp_path,
                            env={**os.environ, 'NODE_OPTIONS': ''}, capture_output=True, text=True)
    receipt = json.loads((output / 'browser-receipt.json').read_text())
    assert result.returncode == 1  # Deliberate stop before any browser launch.
    assert 'PATHS_REACHED_BROWSER' in receipt['error'], receipt
    assert len(receipt['loader_hashes']) == 5
    assert receipt['inputs']['server_path_verified']
