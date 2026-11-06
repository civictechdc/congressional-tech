"""Characterize the existing native request without native execution or row reads.

The retained preparation inventory predates the builder extraction. It records
the incumbent SQL, shared steps, outputs and checks, not replacement acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[3]


@pytest.fixture
def incumbent_request(tmp_path):
    inventory = json.loads((ROOT / 'docs/replacement-ddk/native-profile.json').read_text())
    bindings = {binding['name']: binding['original_table_pin']
                for binding in inventory['exact_native_bindings']}
    # Non-lake input paths are intentionally absent. This proof renders the
    # request only; source admission and actual schemas require native acceptance.
    inputs = [dict(name=item['name'], **bindings[item['name']]) if item['name'] in bindings else
              dict(name=item['name'], kind='parquet', path=str(tmp_path / 'unopened' / (item['name'] + '.parquet')))
              for item in inventory['all_inputs']]
    steps = [deepcopy(item['specification']) for item in inventory['graph']['steps']]
    prefix = next(index for index, step in enumerate(steps) if step['name'] == 'link_contexts')
    prepared = dict(inputs=inputs, steps=steps[:prefix], scratch=tmp_path / 'scratch',
                    evidence=tmp_path / 'scratch/evidence', capture_profile=dict(version=1),
                    parser_versions=inventory['source_request']['parser_versions'],
                    catalog_version=inventory['source_request']['catalog_version'],
                    include_entities=True, explorer_inputs=True, has_document_references=True,
                    entity_digests=inventory['spicy_regs']['generations'])
    return inventory, prepared


def test_full_plan_preserves_incumbent_pins_sql_steps_exports_and_checks(tmp_path, incumbent_request, monkeypatch):
    from docspec_client.client import NativeDatasets
    import pyarrow.parquet as pq
    from viewer_publication.archive_model import plan_prepared_release

    def no_execution(*args, **kwargs):
        pytest.fail('Request construction must not open input rows or submit a native job')

    monkeypatch.setattr(NativeDatasets, 'run_job', no_execution)
    monkeypatch.setattr(pq, 'read_schema', no_execution)
    monkeypatch.setattr(pq, 'read_table', no_execution)
    inventory, prepared = incumbent_request
    before = deepcopy(prepared)
    output = tmp_path / 'release'
    job, schema, diagnostics = plan_prepared_release(prepared, output=output)

    assert prepared == before, 'Rendering must not append export steps to the prepared prefix'
    assert not output.exists() and not prepared['scratch'].exists()
    assert job['inputs'] == prepared['inputs']
    for binding in inventory['exact_native_bindings']:
        assert next(item for item in job['inputs'] if item['name'] == binding['name']) == {
            'name': binding['name'], **binding['original_table_pin']}
    assert job['steps'] == [item['specification'] for item in inventory['graph']['steps']]
    assert [(item['name'], item['sql'], item['settings']) for item in job['outputs']] == [
        (item['name'], item['sql'], item['settings']) for item in inventory['graph']['outputs']]
    assert job['queries'] == [dict(name=item['id'], sql=item['sql']) for item in inventory['graph']['queries']]
    assert {'invariants', *(item['name'] for item in diagnostics)} == {
        'invariants', 'model_invariants', 'url_state_invariants', 'profile_completeness',
        'entity_profile_completeness', 'relationship_invariants', 'explorer_invariants'}
    public = {item['name'] for item in inventory['graph']['outputs'] if item['scope'] == 'public_release'}
    assert {item['name'] for item in schema['files'] if item['available']} == public
    assert [item['name'] for item in job['outputs'][:6]] == [
        'list.parquet', 'detail.parquet', 'links.parquet', 'urls.parquet', 'sources.parquet', 'recoveries.parquet']
    assert next(item for item in job['outputs'] if item['name'] == 'document_rows.parquet')['sql'].endswith(' FROM details')
    assert next(item for item in job['outputs'] if item['name'] == 'detail.parquet')['sql'] == 'SELECT * FROM details'
    second, second_schema, second_diagnostics = plan_prepared_release(prepared, output=output)
    assert (second, second_schema, second_diagnostics) == (job, schema, diagnostics)


@pytest.mark.parametrize('defect', ['missing_relation', 'duplicate_relation', 'invalid_sql'])
def test_invalid_complete_plan_refuses_before_creating_work_or_submitting(tmp_path, incumbent_request, defect):
    from viewer_publication.archive_model import plan_prepared_release

    _inventory, prepared = incumbent_request
    if defect == 'missing_relation':
        prepared['steps'][0]['sql'] = 'SELECT * FROM not_an_admitted_native_input'
        expected = 'unavailable relations'
    elif defect == 'duplicate_relation':
        prepared['steps'][0]['name'] = prepared['inputs'][0]['name']
        expected = 'Duplicate model relation'
    else:
        prepared['steps'][0]['sql'] = 'SELECT * FROM ('
        expected = 'Cannot parse model SQL dependencies'
    with pytest.raises(ValueError, match=expected):
        plan_prepared_release(prepared, output=tmp_path / 'release')
    assert not (tmp_path / 'release').exists() and not prepared['scratch'].exists()


def test_incumbent_executor_submits_the_same_single_request(tmp_path, incumbent_request):
    from viewer_publication.archive_model import build_prepared_release, plan_prepared_release

    _inventory, prepared = incumbent_request
    output = tmp_path / 'release'
    expected, _schema, _diagnostics = plan_prepared_release(prepared, output=output)
    prepared['scratch'].mkdir()
    submitted = []

    def stop_after_submission(path):
        submitted.append(json.loads(Path(path).read_text()))
        raise RuntimeError('No native job is run by this request characterization')

    with pytest.raises(RuntimeError, match='No native job'):
        build_prepared_release(prepared, engine=SimpleNamespace(run_job=stop_after_submission), output=output)
    assert submitted == [expected]
    assert json.loads((prepared['scratch'] / 'job.json').read_text()) == expected
    assert not (prepared['scratch'] / 'result.json').exists()
    assert not (output / 'manifest.json').exists()
