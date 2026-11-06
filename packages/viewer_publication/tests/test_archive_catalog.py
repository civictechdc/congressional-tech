"""Compare standard declarations with independently retained native invariants."""
import json
from pathlib import Path

import pytest
import duckdb


ROOT = Path(__file__).parents[3]


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
    actual, = publication_checks(admitted_catalog, auxiliary, published)
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
    # Catalog order carries no meaning. Every retained expression survives;
    # the current policy-bound capture shape adds exactly two required fields.
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
