"""Compare standard declarations with independently retained native invariants."""
import json
from pathlib import Path

import pytest
import duckdb


ROOT = Path(__file__).parents[3]


def test_captured_definitions_keep_original_bytes_and_refuse_changed_interpretation(tmp_path):
    import shutil
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_catalog import capture_definitions, captured_catalog_options

    source_root = tmp_path/'source'
    shutil.copytree(ROOT/'model/ddk', source_root/'model/ddk')
    project = capture_definitions(tmp_path/'captured', root=source_root)
    (source_root/'model/ddk/archive.odcs.json').write_text('{}')
    options = captured_catalog_options(project)
    first = assemble_catalog(project, **options)
    assert first.report['decision'] == 'passed', first.local_report
    second = assemble_catalog(project, disclosure_policy=project.parent/'public-disclosure.json', **options)
    assert second.report['decision'] == 'passed', second.local_report
    assert first.local_catalog['datasets'] == second.local_catalog['datasets']
    with pytest.raises(FileExistsError):
        capture_definitions(project.parent)
    source = project.parent/'implementations/archive_catalog.py'
    source.write_bytes(source.read_bytes()+b'\n# changed interpretation\n')
    with pytest.raises(ValueError, match='captured source'):
        captured_catalog_options(project)


@pytest.fixture(scope='module', params=['local', 'public'])
def admitted_catalog(request, tmp_path_factory):
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    options = {}
    permitted_roots = [ROOT]
    if request.param == 'public':
        project = json.loads((ROOT / 'model/ddk/project.ddk.json').read_text())
        definitions = json.loads((ROOT / 'model/ddk/archive.odcs.json').read_text())
        product = json.loads((ROOT / 'model/ddk/archive.odps.json').read_text())
        datasets = [item for item in project['artifacts'].values() if item['kind'] == 'dataset']
        # Only dataset-root metadata is public. Writer checks must still use
        # every private field and identity from this single captured assembly.
        policy = dict(identifiers=[project['id'], project['catalog']['id'],
            definitions['id'], product['id'], ArchiveRelationshipProfileV1.identity['id'],
            *[item['catalogId'] for item in datasets]],
            definitionFields={item['catalogId']: [[]] for item in datasets})
        directory = tmp_path_factory.mktemp('public-definition-scope')
        path = directory / 'policy.json'
        path.write_text(json.dumps(policy))
        options['disclosure_policy'] = path
        permitted_roots.append(directory)
    result = assemble_catalog(ROOT / 'model/ddk/project.ddk.json', permitted_roots=permitted_roots,
                              relationship_profile=ArchiveRelationshipProfileV1(), **options)
    assert result.report['decision'] == 'passed', result.local_report
    assert result.catalog['audience'] == request.param
    if request.param == 'public':
        public = result.catalog['extensions']['urn:ddk:catalog:assembly']['datasetDefinitions']
        assert public and all(not item.get('properties') for item in public.values())
        assert result.catalog['identities'] == []
    return result


def test_standard_declarations_preserve_every_retained_native_invariant(admitted_catalog):
    from viewer_publication.archive_catalog import publication_checks
    from viewer_publication.archive_format import CORE_RELATIONS

    retained = json.loads((ROOT / 'docs/replacement-ddk/native-profile.json').read_text())
    published = {item['name'] for item in retained['graph']['outputs']
                 if item['scope'] == 'public_release'}
    auxiliary = {name.removesuffix('.parquet') for name in published} - CORE_RELATIONS.keys()
    expected = next(item['sql'] for item in retained['graph']['queries']
                    if item['id'] == 'relationship_invariants')
    reports, _bindings = publication_checks(admitted_catalog, auxiliary, published)
    actual, = reports
    assert actual['name'] == 'relationship_invariants'

    def expressions(sql):
        with duckdb.connect(config={'enable_external_access': False, 'threads': 1}) as parser:
            parsed = json.loads(parser.execute('SELECT json_serialize_sql(?)', [sql]).fetchone()[0])
        assert not parsed['error'], parsed
        selected = parsed['statements'][0]['node']['select_list']
        assert len({item['alias'] for item in selected}) == len(selected)

        def meaning(value):
            if isinstance(value, dict):
                return {key: meaning(item) for key, item in value.items() if key != 'query_location'}
            if isinstance(value, list):
                return [meaning(item) for item in value]
            return value

        return {item['alias']: meaning(item) for item in selected}

    expected_checks = expressions(expected)
    expected_checks.update(expressions('''SELECT
        (SELECT count(*) FROM url_state_export WHERE "capture_disposition" IS NULL) AS null_url_state_capture_disposition,
        (SELECT count(*) FROM url_state_export WHERE "capture_reason" IS NULL) AS null_url_state_capture_reason'''))
    # Preserve the frozen predicates while checking completed exports instead
    # of producer views. All domain-reference expressions stay unchanged.
    output_for_relation = {CORE_RELATIONS.get(name.removesuffix('.parquet'),
                            name.removesuffix('.parquet') + '_export'): name for name in published}

    def completed_export(value):
        if isinstance(value, dict):
            if value.get('type') == 'BASE_TABLE':
                value['table_name'] = output_for_relation[value['table_name']]
                value['schema_name'] = 'outputs'
            for item in value.values():
                completed_export(item)
        elif isinstance(value, list):
            for item in value:
                completed_export(item)

    for name, expression in expected_checks.items():
        if (name.startswith('null_') or (name.startswith('invalid_') and name.endswith('_key'))
                or name == 'duplicate_document_key'):
            completed_export(expression)
    assert expressions(actual['sql']) == expected_checks


def test_an_undeclared_output_cannot_escape_native_checks(admitted_catalog):
    from viewer_publication.archive_catalog import publication_checks

    with pytest.raises(ValueError, match='lack admitted dataset definitions: undeclared.parquet'):
        publication_checks(admitted_catalog, set(), ['list.parquet', 'undeclared.parquet'])


def test_unknown_required_semantics_do_not_create_native_check_definitions():
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_catalog import publication_checks

    result = assemble_catalog(ROOT / 'model/ddk/project.ddk.json', permitted_roots=[ROOT])
    assert result.report['decision'] != 'passed'
    with pytest.raises(ValueError, match='require admitted local DDK declarations'):
        publication_checks(result, set(), ['list.parquet'])


@pytest.mark.parametrize('rows, expected_required, expected_unique', [
    (['A000001', 'B000002'], 0, 0),
    (['A000001', None], 1, 1),
    (['A000001', 'A000001'], 0, 1),
    (['A000001', 'A000001', None], 1, 2),
])
def test_bound_native_columns_detect_nulls_and_duplicate_keys(admitted_catalog, rows,
                                                             expected_required, expected_unique):
    """Read the actual generated report expressions and plant wrong output values."""
    from viewer_publication.archive_catalog import publication_checks

    reports, bindings = publication_checks(admitted_catalog, {'members'}, ['members.parquet'])
    report, = reports
    required, = [item for item in bindings if item['facet'] == 'required'
                 and item['paths'] == (({'field': 'bioguide_id'},),)]
    unique, = [item for item in bindings if item['facet'] == 'key_unique']
    for binding in (required, unique):
        assert binding['dataset'] == 'members'
        assert binding['paths'] == (({'field': 'bioguide_id'},),)
        assert binding['output'] == 'members.parquet'
        assert binding['report'] == report['name']
    with duckdb.connect(config={'enable_external_access': False, 'threads': 1}) as database:
        database.execute('CREATE SCHEMA outputs')
        database.execute('CREATE TABLE outputs."members.parquet"(bioguide_id VARCHAR)')
        database.executemany('INSERT INTO outputs."members.parquet" VALUES (?)', [(value,) for value in rows])
        parsed = json.loads(database.execute('SELECT json_serialize_sql(?)', [report['sql']]).fetchone()[0])
        assert not parsed['error']
        select = parsed['statements'][0]['node']
        expressions = {item['alias']: item for item in select['select_list']}
        select['select_list'] = [expressions[item['column']] for item in (required, unique)]
        query = database.execute('SELECT json_deserialize_sql(?)', [json.dumps(parsed)]).fetchone()[0]
        assert database.execute(query).fetchone() == (expected_required, expected_unique)


def test_binding_scope_preserves_composite_keys_and_excludes_unpublished_outputs(admitted_catalog):
    from viewer_publication.archive_catalog import publication_checks

    _reports, bindings = publication_checks(admitted_catalog, {'rosters'}, ['rosters.parquet'])
    assert {item['output'] for item in bindings} == {'rosters.parquet'}
    key, = [item for item in bindings if item['facet'] == 'key_unique']
    not_null, = [item for item in bindings if item['facet'] == 'key_not_null']
    assert key['paths'] == (({'field': 'congress'},), ({'field': 'system_code'},), ({'field': 'bioguide_id'},))
    assert key['column'] == 'invalid_rosters_key'
    assert not_null['paths'] == key['paths'] and not_null['column'] == key['column']
    assert all('passed' not in item and 'status' not in item for item in bindings)


@pytest.fixture
def captured_rule_job(admitted_catalog):
    from types import SimpleNamespace
    from viewer_publication.archive_catalog import ASSEMBLY, native_catalog_mapping, publication_checks
    from viewer_publication.archive_format import CORE_RELATIONS

    frozen = json.loads((ROOT / 'docs/replacement-ddk/native-profile.json').read_text())
    outputs = frozen['graph']['outputs']
    job = dict(inputs=[], steps=[item['specification'] for item in frozen['graph']['steps']],
        outputs=[dict(name=item['name'], sql=item['sql'], settings=item['settings']) for item in outputs])
    mapping = native_catalog_mapping(admitted_catalog, job,
        private_outputs=[item['name'] for item in outputs if item['scope'] != 'public_release'])
    auxiliary = {name.removesuffix('.parquet') for name in mapping['outputs']} - CORE_RELATIONS.keys()
    job['queries'], _bindings = publication_checks(admitted_catalog, auxiliary, mapping['outputs'])
    catalog = admitted_catalog.local_catalog
    context = SimpleNamespace(production={'alias': mapping['production']},
        datasets=catalog['extensions'][ASSEMBLY]['datasetDefinitions'], identities=catalog['identities'],
        inputs=mapping['inputs'], outputs=mapping['outputs'], out_of_catalog=mapping['out_of_catalog'])
    return context, job


def test_profile_reproduces_original_rules_without_execution(captured_rule_job):
    from types import MappingProxyType, SimpleNamespace
    from viewer_publication.archive_catalog import _verified_native_rule_records

    context, job = captured_rule_job
    bindings = _verified_native_rule_records(context, job)
    assert bindings
    assert {item['facet'] for item in bindings} == {'required', 'key_unique', 'key_not_null'}
    assert {item['output'] for item in bindings} == set(context.outputs)
    assert all(set(item) == {'dataset', 'output', 'facet', 'paths', 'report', 'column'} for item in bindings)

    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, list):
            return tuple(freeze(item) for item in value)
        return value

    frozen_context = SimpleNamespace(**{key: freeze(value) for key, value in vars(context).items()})
    assert _verified_native_rule_records(frozen_context, freeze(job)) == bindings
    reloaded = SimpleNamespace(**json.loads(json.dumps(vars(context), sort_keys=True)))
    assert _verified_native_rule_records(reloaded, json.loads(json.dumps(job, sort_keys=True))) == bindings


@pytest.mark.parametrize('defect', [None, 'changed_binding', 'changed_job_bytes', 'changed_pin'])
def test_maintained_native_rule_capture_binds_exact_saved_metadata(admitted_catalog, captured_rule_job, tmp_path, defect):
    """Exercise the installed DDK metadata API; no native execution is claimed."""
    from hashlib import sha256
    from ddk.catalog_access import CatalogError
    from ddk.catalog_managed_jobs import managed_job_definition
    from ddk.catalog_native_rules import native_rule_artifact
    from viewer_publication.archive_catalog import ArchiveNativeRuleProfileV1

    context, job = captured_rule_job
    mapping = dict(production=context.production['alias'], inputs=context.inputs, outputs=context.outputs,
                   out_of_catalog=context.out_of_catalog)
    profile = ArchiveNativeRuleProfileV1()
    original = json.dumps(job, sort_keys=True, separators=(',', ':')).encode()
    artifact = native_rule_artifact(admitted_catalog, original, native_rule_profile=profile, **mapping)
    assert artifact['job']['sha256'] == sha256(original).hexdigest()
    assert artifact['bindings'] and all('passed' not in item for item in artifact['bindings'])
    if defect == 'changed_binding':
        artifact['bindings'][0]['column'] = 'invented_zero_counter'
    elif defect == 'changed_job_bytes':
        artifact['job']['bytes_base64'] = 'e30='
    raw = json.dumps(artifact, sort_keys=True, separators=(',', ':')).encode()
    path = tmp_path/'native-rules.json'
    path.write_bytes(raw)
    pin = dict(path=str(path), sha256=sha256(raw).hexdigest())
    if defect == 'changed_pin':
        pin['sha256'] = '0'*64
    if defect is not None:
        with pytest.raises(CatalogError):
            managed_job_definition(admitted_catalog, native_rules=pin, native_rule_profile=profile, **mapping)
        return
    identity = managed_job_definition(admitted_catalog, native_rules=pin, native_rule_profile=profile, **mapping)
    assert identity != managed_job_definition(admitted_catalog, **mapping)
    assert managed_job_definition(admitted_catalog, native_rules=json.loads(json.dumps(pin)),
        native_rule_profile=ArchiveNativeRuleProfileV1(), **mapping) == identity


@pytest.mark.parametrize('defect', ['producer_view', 'changed_counter', 'missing_output', 'wrong_projection',
                                  'new_setting', 'duplicate_output', 'duplicate_report', 'other_dataset',
                                  'missing_writer_sql', 'other_writer_relation', 'filtered_writer', 'changed_expression'])
def test_profile_refuses_wrong_original_output_or_rule_mapping(captured_rule_job, defect):
    from copy import deepcopy
    from viewer_publication.archive_catalog import _verified_native_rule_records

    context, original = captured_rule_job
    job = deepcopy(original)
    output = next(item for item in job['outputs'] if item['name'] == 'members.parquet')
    if defect == 'producer_view':
        job['queries'][0]['sql'] = job['queries'][0]['sql'].replace('outputs."members.parquet"', 'members_export')
    elif defect == 'changed_counter':
        job['queries'][0]['sql'] = job['queries'][0]['sql'].replace('count(*)', 'cast(0 AS BIGINT)')
    elif defect == 'missing_output':
        job['outputs'].remove(output)
    elif defect == 'wrong_projection':
        output['settings']['columns'] = ['name']
    elif defect == 'new_setting':
        output['settings']['filter'] = 'bioguide_id IS NOT NULL'
    elif defect == 'duplicate_output':
        job['outputs'].append(deepcopy(output))
    elif defect == 'duplicate_report':
        job['queries'].append(deepcopy(job['queries'][0]))
    elif defect == 'other_dataset':
        context = deepcopy(context)
        context.outputs['members.parquet'] = 'committees'
    elif defect == 'missing_writer_sql':
        del output['sql']
    elif defect == 'other_writer_relation':
        output['sql'] = 'SELECT * FROM other_members'
    elif defect == 'filtered_writer':
        output['sql'] += ' WHERE bioguide_id IS NOT NULL'
    elif defect == 'changed_expression':
        output['sql'] = "SELECT 'A000001' AS bioguide_id FROM members_export"
    with pytest.raises(ValueError, match='Native'):
        _verified_native_rule_records(context, job)


def test_native_mapping_accounts_for_public_private_and_source_members(admitted_catalog):
    from viewer_publication.archive_catalog import native_catalog_mapping

    job = dict(inputs=[dict(name='captures'), dict(name='parameters')],
               outputs=[dict(name='list.parquet'), dict(name='document_rows.parquet'), dict(name='detail.parquet')])
    mapping = native_catalog_mapping(admitted_catalog, job, private_outputs=['document_rows.parquet'])
    assert mapping['production'] == 'archive-model'
    assert mapping['inputs'] == {}
    assert mapping['outputs'] == {'list.parquet': 'list', 'detail.parquet': 'detail'}
    assert [item['name'] for item in mapping['out_of_catalog']['inputs']] == ['captures', 'parameters']
    assert [item['name'] for item in mapping['out_of_catalog']['outputs']] == ['document_rows.parquet']
    assert all(item['reason'] for members in mapping['out_of_catalog'].values() for item in members)
    production, = [item for item in admitted_catalog.local_catalog['productions'] if item['alias'] == 'archive-model']
    assert set(mapping['outputs'].values()) <= set(production['outputs'])


@pytest.mark.parametrize('outputs, private', [
    (['list.parquet', 'unknown.parquet'], []),
    (['list.parquet'], ['absent.parquet']),
    (['list.parquet', 'list.parquet'], []),
    (['list.parquet'], ['list.parquet']),
])
def test_unaccounted_native_output_scope_refuses(admitted_catalog, outputs, private):
    from viewer_publication.archive_catalog import native_catalog_mapping

    with pytest.raises(ValueError, match='output'):
        native_catalog_mapping(admitted_catalog, dict(inputs=[], outputs=[dict(name=name) for name in outputs]),
                               private_outputs=private)
