"""Compare standard declarations with independently retained native invariants."""
import json
from pathlib import Path

import pytest
import duckdb


ROOT = Path(__file__).parents[3]


@pytest.fixture(scope='module')
def admitted_catalog():
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    result = assemble_catalog(ROOT / 'model/ddk/project.ddk.json', permitted_roots=[ROOT],
                              relationship_profile=ArchiveRelationshipProfileV1())
    assert result.report['decision'] == 'passed', result.local_report
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
