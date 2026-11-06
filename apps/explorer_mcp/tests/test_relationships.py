"""Discover native semantics without a second MCP registry or SQL planner."""

import pytest

from congressional_explorer_mcp.models import ExplorerError, MAX_BYTES
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.reader import Reader


def test_discovery_uses_admitted_definitions_and_stays_bounded(reader):
    info = reader.dataset_info({})
    assert info['metadata_format'] == 'ddk.catalog/0.1'
    assert info['catalog_checking'] == 'passed'
    assert len(encoded(info)) < MAX_BYTES
    table = reader.dataset_info({'table': 'witnesses'})
    assert any(item['kind'] == 'key' and item['fields'][0]['path'] == [{'field': 'witness_key'}]
               for item in table['identities'])
    assert 'urn:congressional-tech:archive:relationship:witness_submitted_documents' in table['incoming']
    assert 'urn:congressional-tech:archive:relationship:witness_transcript_documents' in table['outgoing']
    assert 'any Congress without roster rows' in reader.dataset_info({'table': 'rosters'})['definition']['description']
    assert reader.dataset_info({'relationship': 'urn:congressional-tech:archive:relationship:roster_committee'})['scopeDescription'] == \
        'rosters.congress (Congresses populated in the pinned committee_assignments snapshot)'
    relation = reader.dataset_info({'relationship': 'urn:congressional-tech:archive:relationship:witness_submitted_documents'})
    assert relation['source']['paths'] == [[{'field': 'witness_keys'}, {'each': True}]]
    assert 'own document URLs' in relation['meaning']
    assert reader.dataset_info({'relationship': 'urn:congressional-tech:archive:relationship:witness_transcript_documents'})['source']['paths'] == [[{'field': 'package_id'}]]
    recipe = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:committee_roster'})
    assert recipe['parameterOrder'] == ['system_code', 'congress']
    assert recipe['parameters']['properties']['congress']['type'] == 'integer'
    with pytest.raises(ExplorerError, match='Choose one'):
        reader.dataset_info({'table': 'list', 'recipe': 'urn:congressional-tech:archive:recipe:bill_documents'})
    with pytest.raises(ExplorerError, match='Unknown relationship'):
        reader.dataset_info({'relationship': 'made_up'})


def test_future_relationships_are_visible_without_mcp_changes(phase2, tmp_path):
    import shutil
    from conftest import REPO, manifest
    from catalog_fixtures import assemble_catalog_fixture
    identifier = 'urn:test:reader:relationship:future_relation'
    def change(project):
        project['catalog']['relationships'].append(dict(id=identifier,
            source=dict(dataset='future-data', paths=[[{'field': 'future_field'}]]),
            target=dict(dataset='committees', paths=[[{'field': 'system_code'}]]),
            match='equal', cardinality='many_to_one', scope='same_release', resolution='unresolved_allowed',
            nulls='reject', meaning='Future metadata authored by the producer'))
    definitions = tmp_path/'future-definitions'
    definitions.mkdir()
    artifacts = assemble_catalog_fixture(REPO, definitions, change_project=change)
    root = tmp_path/'release'
    shutil.copytree(phase2.parent, root)
    shutil.copytree(artifacts, root, dirs_exist_ok=True)
    reader = Reader(prepare(tmp_path/'selected', manifest(root)))
    try:
        assert reader.dataset_info({'relationship': identifier})['available']
        assert identifier in reader.dataset_info({'table': 'future_data'})['outgoing']
        reader.selection['controls']['catalog.ddk']['padding'] = 'x' * MAX_BYTES
        with pytest.raises(ExplorerError, match='selector'):
            reader.dataset_info({'table': 'catalog.ddk'})
    finally:
        reader.close()



def test_every_recipe_executes_and_has_the_declared_result_grain(reader):
    expected = dict(bill_documents=1, bill_hearing_transcripts=1, hearing_documents=1, hearing_dossier=1,
                    witness_documents=1, witness_transcripts=1, witness_by_any_key=1,
                    committee_roster=1, nomination_transcripts=1, bill_votes=1, nomination_votes=1,
                    recording_tracks=1, document_editions=1, meeting_recordings=1, channel_unmatched_videos=1, coverage_counts=1)
    doc_recipes = {'urn:congressional-tech:archive:recipe:bill_documents', 'urn:congressional-tech:archive:recipe:bill_hearing_transcripts', 'urn:congressional-tech:archive:recipe:hearing_documents',
                   'urn:congressional-tech:archive:recipe:witness_documents', 'urn:congressional-tech:archive:recipe:witness_transcripts', 'urn:congressional-tech:archive:recipe:nomination_transcripts'}
    for item in reader.dataset_info({})['recipes']:
        recipe = reader.dataset_info({'recipe': item['id']})
        params = [recipe['parameters']['properties'][name]['examples'][0] for name in recipe['parameterOrder']]
        result = reader.query_sql({'sql': recipe['sql'], 'parameters': params})
        assert not result['truncated']
        assert len(result['rows']) == expected[recipe['id'].rsplit(':',1)[-1]], (recipe['id'], result['rows'])
        if item['id'] == 'urn:congressional-tech:archive:recipe:witness_by_any_key':
            earlier = reader.query_sql({'sql': recipe['sql'], 'parameters': ['old-appearance-1']})
            assert [(row['witness_key'], row['old_key'], row['status']) for row in earlier['rows']] == [
                ('appearance-1', 'old-appearance-1', 'unambiguous')]
        if item['id'] in doc_recipes:
            assert 'NOT coalesce(l.hidden,false)' in recipe['sql']
            row = result['rows'][0]
            assert 'link_key' in row and 'title' in row
            assert len(row['link_key']) == 16 and row['link_key'] == row['link_key'].lower()
        if item['id'] == 'urn:congressional-tech:archive:recipe:hearing_dossier':
            dossier = result['rows'][0]
            assert [w['witness_key'] for w in dossier['witnesses']] == ['appearance-1']
            assert [d['filename'] for d in dossier['documents']] == ['Agenda.pdf']
            assert len(dossier['documents'][0]['link_key']) == 16
            assert dossier['recordings'] == []


def test_nested_lists_do_not_multiply_votes_or_document_editions(reader):
    # Two unrelated nested lists must not enter a vote query's FROM clause.
    reader.db.execute('CREATE TEMP VIEW vote_fixture AS SELECT * REPLACE(array_concat(amendments,amendments) AS amendments) FROM bills')
    recipe = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:bill_votes'})
    sql = recipe['sql'].replace('FROM bills b', 'FROM vote_fixture b')
    assert len(reader.query_sql({'sql': sql, 'parameters': ['119-hr-1']})['rows']) == 1
    # Several shared keys still mean one other edition.
    reader.db.execute('CREATE TEMP VIEW edition_fixture AS SELECT list_row,filename,document_date,[\'a\',\'b\'] AS version_keys FROM "list" WHERE list_row IN (0,1)')
    recipe = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:document_editions'})
    sql = recipe['sql'].replace('"list"', 'edition_fixture')
    assert len(reader.query_sql({'sql': sql, 'parameters': [0]})['rows']) == 1



def test_transcript_participation_does_not_claim_submitted_documents(reader):
    transcript = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:witness_transcripts'})
    submitted = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:witness_documents'})
    assert reader.query_sql({'sql': transcript['sql'], 'parameters': ['appearance-2']})['rows'][0]['filename'] == 'Hearing excerpt.pdf'
    assert reader.query_sql({'sql': submitted['sql'], 'parameters': ['appearance-2']})['rows'] == []
    assert reader.query_sql({'sql': submitted['sql'], 'parameters': ['appearance-1']})['rows'][0]['filename'] == 'Agenda.pdf'
    # appearance-1 has no package_id; the MODS row it supersedes carries the transcript's package.
    via_superseded = reader.query_sql({'sql': transcript['sql'], 'parameters': ['appearance-1']})['rows']
    assert [(r['witness_key'], r['filename']) for r in via_superseded] == [('appearance-1', 'Hearing excerpt.pdf')]
    assert reader.query_sql({'sql': transcript['sql'], 'parameters': ['mods-appearance-1']})['rows'][0]['filename'] == 'Hearing excerpt.pdf'
    assert reader.query_sql({'sql': transcript['sql'], 'parameters': ['0001497931f99cd1']})['rows'] == []


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
        assert reader.dataset_info({'relationship': 'urn:congressional-tech:archive:relationship:witness_submitted_documents'})['missing_tables'] == ['witnesses']
        assert not reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:witness_documents'})['available']
        assert reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:bill_documents'})['available']
    finally:
        reader.close()


def test_bill_transcripts_deduplicate_paths_and_keep_supporting_meetings(tmp_path, linked_transcripts):
    reader = Reader(prepare(tmp_path, linked_transcripts))
    try:
        recipe = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:bill_hearing_transcripts'})
        assert recipe['available']
        assert 'urn:congressional-tech:archive:recipe:bill_hearing_transcripts' in reader.dataset_info({'table': 'meetings'})['recipes']
        result = reader.query_sql({'sql': recipe['sql'], 'parameters': ['119-hr-1']})
        assert [(r['list_row'], r['meeting_ids']) for r in result['rows']] == [(1, [118001, 118002]), (2, [118001])]
        assert not result['truncated']
        assert reader.search_documents({'measure_key': '119-hr-1', 'document_kind': 'published-hearing'})['rows'] == []
        assert reader.query_sql({'sql': recipe['sql'], 'parameters': ['119-hr-999']})['rows'] == []
        limited = reader.query_sql({'sql': recipe['sql'], 'parameters': ['119-hr-1'], 'limit': 1})
        assert limited['truncated'] and limited['rows'] == result['rows'][:1]
        reader.db.execute('CREATE TEMP VIEW oversized_titles AS SELECT * REPLACE(repeat(\'x\',140000) AS title) FROM "list"')
        with pytest.raises(ExplorerError, match='128 KiB'):
            reader.query_sql({'sql': recipe['sql'].replace('"list"', 'oversized_titles'), 'parameters': ['119-hr-1']})
    finally:
        reader.close()


def test_bill_transcript_recipe_missing_meetings_is_unavailable(tmp_path, linked_transcripts):
    import shutil
    import duckdb
    from conftest import manifest
    root = tmp_path / 'sparse'
    shutil.copytree(linked_transcripts.parent, root)
    (root / 'meetings.parquet').unlink()
    reader = Reader(prepare(tmp_path / 'selected', manifest(root)))
    try:
        recipe = reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:bill_hearing_transcripts'})
        assert not recipe['available'] and recipe['missing_tables'] == ['meetings']
        with pytest.raises(duckdb.Error, match='meetings'):
            reader.query_sql({'sql': recipe['sql'], 'parameters': ['119-hr-1']})
        assert reader.dataset_info({'recipe': 'urn:congressional-tech:archive:recipe:bill_documents'})['available']
    finally:
        reader.close()
