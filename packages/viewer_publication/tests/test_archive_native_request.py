"""Characterize current request assembly from a frozen prefix without execution.

The retained preparation inventory predates the builder extraction. It records
the incumbent SQL, shared steps, outputs and checks, not replacement acceptance.
The fixture adds an explicit recovery policy and an unopened requirements input
to that prefix. It does not select production requirements or execute rows.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]


@pytest.fixture(scope='module')
def catalog_result():
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    result = assemble_catalog(ROOT/'model/ddk/project.ddk.json', permitted_roots=[ROOT],
                              relationship_profile=ArchiveRelationshipProfileV1())
    assert result.report['decision'] == 'passed', result.local_report
    return result


@pytest.fixture
def incumbent_request(tmp_path):
    from congress_api.models.archive_profile import build_capture_profile
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
    policy=dict(acceptance_policy='recovery-identity-v1',requirements_sha256='c'*64)
    inputs.append(dict(name='recovery_requirements_input',kind='parquet',path=str(tmp_path/'unopened/requirements.parquet')))
    prepared_steps=steps[:prefix]+[dict(name='recovery_requirements',materialize=True,
        sql='SELECT original_url,target_requirement,acceptance_policy,refresh_policy FROM recovery_requirements_input')]
    profile=build_capture_profile(engine_revision='a'*40,
        url_normalized_sql=(ROOT/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(ROOT/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((ROOT/'model/registries/url-rules.json').read_text()),recovery_policy=policy)
    prepared = dict(inputs=inputs, steps=prepared_steps, scratch=tmp_path / 'scratch',
                    evidence=tmp_path / 'scratch/evidence', capture_profile=profile,recovery_policy=policy,
                    parser_versions=inventory['source_request']['parser_versions'],
                    catalog_version=inventory['source_request']['catalog_version'],
                    include_entities=True, explorer_inputs=True,
                    entity_digests=inventory['spicy_regs']['generations'])
    return inventory, prepared


def test_full_plan_preserves_domain_pins_steps_exports_and_uses_ddk_checks(tmp_path, incumbent_request, catalog_result, monkeypatch):
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
    job, diagnostics = plan_prepared_release(prepared, output=output, catalog_result=catalog_result)

    assert prepared == before, 'Rendering must not append export steps to the prepared prefix'
    assert not output.exists() and not prepared['scratch'].exists()
    assert job['inputs'] == prepared['inputs']
    for binding in inventory['exact_native_bindings']:
        assert next(item for item in job['inputs'] if item['name'] == binding['name']) == {
            'name': binding['name'], **binding['original_table_pin']}
    # Preserve the original work except the explicit policy input and eligibility.
    # Last-reader annotations may move when the policy reads an existing relation.
    affected={'recovery_requirements','url_state','url_state_history','url_state_invariants_step'}
    def unchanged(steps):
        return [{key:value for key,value in step.items() if key!='release_after'}
                for step in steps if step['name'] not in affected]
    baseline=[item['specification'] for item in inventory['graph']['steps']]
    assert unchanged(job['steps']) == unchanged(baseline)
    assert next(step for step in job['steps'] if step['name']=='url_state_history')['sql'] == next(
        step for step in baseline if step['name']=='url_state')['sql']
    assert 'invalid_recovery_requirements' in next(
        step for step in job['steps'] if step['name']=='url_state_invariants_step')['sql']
    assert [(item['name'], item['sql'], item['settings']) for item in job['outputs']] == [
        (item['name'], item['sql'], item['settings']) for item in inventory['graph']['outputs']]
    assert [query for query in job['queries'] if query['name'] != 'relationship_invariants'] == [
        dict(name=item['id'], sql=item['sql']) for item in inventory['graph']['queries']
        if item['id'] != 'relationship_invariants']
    assert {'invariants', *(item['name'] for item in diagnostics)} == {
        'invariants', 'model_invariants', 'url_state_invariants', 'profile_completeness',
        'entity_profile_completeness', 'relationship_invariants', 'explorer_invariants'}
    public = {item['name'] for item in inventory['graph']['outputs'] if item['scope'] == 'public_release'}
    from viewer_publication.archive_catalog import publication_checks, CORE_RELATIONS
    expected_checks, _ = publication_checks(catalog_result,
        {name.removesuffix('.parquet') for name in public}-CORE_RELATIONS.keys(), public)
    assert [query for query in job['queries'] if query['name'] == 'relationship_invariants'] == expected_checks
    assert [item['name'] for item in job['outputs'][:6]] == [
        'list.parquet', 'detail.parquet', 'links.parquet', 'urls.parquet', 'sources.parquet', 'recoveries.parquet']
    assert next(item for item in job['outputs'] if item['name'] == 'document_rows.parquet')['sql'].endswith(' FROM details')
    assert next(item for item in job['outputs'] if item['name'] == 'detail.parquet')['sql'] == 'SELECT * FROM details'
    assert plan_prepared_release(prepared, output=output, catalog_result=catalog_result) == (job, diagnostics)


@pytest.mark.parametrize('defect', ['missing_relation', 'duplicate_relation', 'invalid_sql'])
def test_invalid_complete_plan_refuses_before_creating_work_or_submitting(tmp_path, incumbent_request, catalog_result, defect):
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
        plan_prepared_release(prepared, output=tmp_path / 'release', catalog_result=catalog_result)
    assert not (tmp_path / 'release').exists() and not prepared['scratch'].exists()


def test_blocking_inventory_tracks_the_actual_explorer_scope(tmp_path, incumbent_request, catalog_result):
    from viewer_publication.archive_model import plan_prepared_release

    _inventory, prepared = incumbent_request
    prepared['explorer_inputs'] = False
    job, diagnostics = plan_prepared_release(prepared, output=tmp_path / 'release', catalog_result=catalog_result)
    assert 'explorer_invariants' not in {report['name'] for report in diagnostics}
    assert 'explorer_invariants' not in {report['name'] for report in job['queries']}


@pytest.mark.parametrize('defect',['missing_policy','legacy_profile','different_policy','missing_requirements'])
def test_policy_free_or_mismatched_preparation_refuses_before_rendering(tmp_path,incumbent_request,defect):
    from viewer_publication.archive_model import plan_prepared_release
    _inventory,prepared=incumbent_request
    if defect=='missing_policy':
        del prepared['recovery_policy']
        expected='pinned recovery policy'
    elif defect=='legacy_profile':
        prepared['capture_profile'].pop('recovery_policy')
        prepared['capture_profile']['version']=1
        expected='version 2 capture profile'
    elif defect=='different_policy':
        prepared['capture_profile']['recovery_policy']['requirements_sha256']='d'*64
        expected='bound to its recovery policy'
    else:
        prepared['inputs']=[item for item in prepared['inputs'] if item['name']!='recovery_requirements_input']
        expected='pinned recovery requirements input'
    with pytest.raises(ValueError,match=expected):
        plan_prepared_release(prepared,output=tmp_path/'release',catalog_result=None)
    assert not (tmp_path/'release').exists() and not prepared['scratch'].exists()
