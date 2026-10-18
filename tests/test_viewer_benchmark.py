"""The benchmark must not qualify changed values or mismatched browser evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('viewer_benchmark', ROOT / 'scripts/benchmark_viewer_publication.py')
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
