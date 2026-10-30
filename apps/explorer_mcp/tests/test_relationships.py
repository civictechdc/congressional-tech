"""Discover native semantics without a second MCP registry or SQL planner."""
from copy import deepcopy

import pytest

from congressional_explorer_mcp.models import ExplorerError, MAX_BYTES
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT


def test_discovery_uses_producer_definitions_and_stays_bounded(reader):
    info = reader.dataset_info({})
    assert info['relationships_version'] == 1
    assert len(encoded(info)) < MAX_BYTES
    table = reader.dataset_info({'table': 'witnesses'})
    assert table['identity']['fields'] == ['witness_key']
    assert 'witness_submitted_documents' in table['incoming']
    assert 'witness_transcript_documents' in table['outgoing']
    assert reader.dataset_info({'table': 'rosters'})['scope'] == ['Current-Congress seats only; spicy-regs keeps no roster history']
    relation = reader.dataset_info({'relationship': 'witness_submitted_documents'})
    assert relation['source']['fields'] == ['witness_keys[]']
    assert 'own document URLs' in relation['meaning']
    assert reader.dataset_info({'relationship': 'witness_transcript_documents'})['source']['fields'] == ['package_id']
    assert reader.dataset_info({'recipe': 'committee_roster'})['parameters'][1]['name'] == 'congress'
    with pytest.raises(ExplorerError, match='Choose one'):
        reader.dataset_info({'table': 'list', 'recipe': 'bill_documents'})
    with pytest.raises(ExplorerError, match='Unknown relationship'):
        reader.dataset_info({'relationship': 'made_up'})


def test_future_relationships_are_visible_without_mcp_changes(reader):
    original = reader.selection['controls']['schema']
    schema = deepcopy(original)
    schema['relationships'].append(dict(id='future_relation', source=dict(table='future_data', fields=['future_field']),
        target=dict(external='future publisher'), meaning='Future metadata authored by the producer'))
    reader.selection['controls']['schema'] = schema
    try:
        assert reader.dataset_info({'relationship': 'future_relation'})['available']
        assert 'future_relation' in reader.dataset_info({'table': 'future_data'})['outgoing']
        schema['relationships'][-1]['target'] = dict(table='unpublished_future_table', fields=['id'])
        assert reader.dataset_info({'relationship': 'future_relation'})['missing_tables'] == ['unpublished_future_table']
        schema['padding'] = 'x' * MAX_BYTES
        with pytest.raises(ExplorerError, match='selector'):
            reader.dataset_info({'table': 'schema'})
    finally:
        reader.selection['controls']['schema'] = original


def test_old_release_does_not_reconstruct_relationships(tmp_path):
    selected = prepare(tmp_path, CURRENT/'manifest.json')
    reader = Reader(selected)
    try:
        info = reader.dataset_info({})
        assert info['relationships_version'] is None
        assert info['relationship_metadata'] == 'not published in this release'
        assert info['relationships'] == [] and info['recipes'] == []
        with pytest.raises(ExplorerError, match='no published relationship metadata'):
            reader.dataset_info({'recipe': 'bill_documents'})
    finally:
        reader.close()


def test_every_recipe_executes_and_has_the_declared_result_grain(reader):
    expected = dict(bill_documents=1, hearing_documents=1, witness_documents=1, witness_transcripts=0,
                    committee_roster=1, nomination_transcripts=1, bill_votes=1, nomination_votes=1,
                    recording_tracks=1, document_editions=1)
    for item in reader.dataset_info({})['recipes']:
        recipe = reader.dataset_info({'recipe': item['id']})
        params = ['appearance-1' if p['name']=='witness_key' else p['example'] for p in recipe['parameters']]
        result = reader.query_sql({'sql': recipe['sql'], 'parameters': params})
        assert not result['truncated']
        assert len(result['rows']) == expected[recipe['id']], (recipe['id'], result['rows'])


def test_nested_lists_do_not_multiply_votes_or_document_editions(reader):
    # Two unrelated nested lists must not enter a vote query's FROM clause.
    reader.db.execute('CREATE TEMP VIEW vote_fixture AS SELECT * REPLACE(array_concat(amendments,amendments) AS amendments) FROM bills')
    recipe = reader.dataset_info({'recipe': 'bill_votes'})
    sql = recipe['sql'].replace('FROM bills b', 'FROM vote_fixture b')
    assert len(reader.query_sql({'sql': sql, 'parameters': ['119-hr-1']})['rows']) == 1
    # Several shared keys still mean one other edition.
    reader.db.execute('CREATE TEMP VIEW edition_fixture AS SELECT list_row,filename,document_date,[\'a\',\'b\'] AS version_keys FROM "list" WHERE list_row IN (0,1)')
    recipe = reader.dataset_info({'recipe': 'document_editions'})
    sql = recipe['sql'].replace('"list"', 'edition_fixture')
    assert len(reader.query_sql({'sql': sql, 'parameters': [0]})['rows']) == 1


def test_unknown_version_preserves_sql_and_table_access(reader):
    original = reader.selection['controls']['schema']
    schema = deepcopy(original)
    schema.update(relationships_version=2, relationships={'unknown': 'shape'}, recipes={'also': 'unknown'})
    reader.selection['controls']['schema'] = schema
    try:
        info = reader.dataset_info({})
        assert info['relationship_metadata'] == 'unsupported version'
        assert info['relationships'] == []
        assert reader.dataset_info({'table': 'bills'})['available']
        assert reader.query_sql({'sql': 'SELECT 1 AS value'})['rows'] == [{'value': 1}]
        with pytest.raises(ExplorerError, match='unsupported relationship metadata version'):
            reader.dataset_info({'relationship': 'document_meetings'})
    finally:
        reader.selection['controls']['schema'] = original


def test_transcript_participation_does_not_claim_submitted_documents(reader):
    transcript = reader.dataset_info({'recipe': 'witness_transcripts'})
    submitted = reader.dataset_info({'recipe': 'witness_documents'})
    assert reader.query_sql({'sql': transcript['sql'], 'parameters': ['appearance-2']})['rows'][0]['filename'] == 'Hearing excerpt.pdf'
    assert reader.query_sql({'sql': submitted['sql'], 'parameters': ['appearance-2']})['rows'] == []
    assert reader.query_sql({'sql': transcript['sql'], 'parameters': ['appearance-1']})['rows'] == []
    assert reader.query_sql({'sql': submitted['sql'], 'parameters': ['appearance-1']})['rows'][0]['filename'] == 'Agenda.pdf'


def test_missing_published_table_is_unavailable_not_empty(tmp_path, phase2):
    import shutil
    from conftest import manifest
    root = tmp_path/'sparse'
    shutil.copytree(phase2.parent, root)
    (root/'witnesses.parquet').unlink()
    selection = prepare(tmp_path/'selected', manifest(root))
    reader = Reader(selection)
    try:
        assert not reader.dataset_info({'table': 'witnesses'})['available']
        assert reader.dataset_info({'relationship': 'witness_submitted_documents'})['missing_tables'] == ['witnesses']
        assert not reader.dataset_info({'recipe': 'witness_documents'})['available']
        assert reader.dataset_info({'recipe': 'bill_documents'})['available']
    finally:
        reader.close()
