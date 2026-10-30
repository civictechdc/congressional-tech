import json
import duckdb
import pytest

from congressional_explorer_mcp.models import ExplorerError, ENTITY_KEYS, MAX_BYTES
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT


def test_all_tables_and_nested_fields_are_available(reader):
    info = reader.dataset_info({})
    assert not info['missing_entities']
    assert set(ENTITY_KEYS) <= info['tables'].keys()
    assert info['tables']['rosters']['rows'] == 1
    assert reader.dataset_info({'table': 'bills'})['columns']['floor_votes'].startswith('STRUCT')
    assert reader.dataset_info({'table': 'capture_scope'}) == {'version': 1, 'entries': []}
    assert reader.query_sql({'sql': 'FROM future_data'})['rows'] == [
        {'future_field': 'new published column', 'amount': '42.123456789012345678'}]
    assert reader.query_sql({'sql': "SELECT name,cross_ids.fec AS fec,terms[1].district AS district FROM members"})['rows'] == [
        {'name': 'Sam Example', 'fec': ['H1', 'H2'], 'district': 1}]
    assert reader.query_sql({'sql': 'SELECT bill_id,floor_votes[1].yea AS yea,amendments[1].purpose AS purpose FROM bills'})['rows'] == [
        {'bill_id': '119-hr-1', 'yea': 220, 'purpose': 'Add transit safety'}]


def test_native_sql_joins_friendly_sql_and_parameters(reader):
    result = reader.query_sql({'sql': '''WITH selected AS (FROM bills WHERE bill_id=?)
        SELECT b.bill_id,m.title AS hearing,w.name,d.filename,c.name AS committee
        FROM selected b JOIN meetings m ON list_contains(m.subject_keys,b.bill_id)
        JOIN witnesses w ON w.event_id=m.event_id
        JOIN documents d ON list_contains(d.witness_keys,w.witness_key)
        JOIN committees c ON list_contains(d.committee_keys,c.system_code)''', 'parameters': ['119-hr-1']})
    assert result['rows'] == [dict(bill_id='119-hr-1', hearing='Transportation infrastructure hearing',
        name='Alex Smith', filename='Agenda.pdf', committee='Energy and Commerce')]
    assert reader.query_sql({'sql': 'SELECT list_transform([1,2],lambda x:x+1) AS numbers'})['rows'] == [{'numbers': [2, 3]}]
    assert reader.query_sql({'sql': 'SELECT ? AS input', 'parameters': ["'; DROP TABLE bills; --"]})['rows'][0]['input'].startswith("';")


@pytest.mark.parametrize('table,key', [('meetings',118001),('witnesses','appearance-1'),('recordings','youtube:abc'),
    ('committees','hsif00'),('members','A000001'),('bills','119-hr-1'),('nominations','119-pn-730-2')])
def test_entity_to_documents(reader, table, key):
    assert reader.get_entity({'table':table,'id':key})['rows']
    result = reader.get_entity({'table':table,'id':key,'section':'documents'})
    assert [r['filename'] for r in result['rows']] == ['Agenda.pdf']
    assert result['rows'][0]['saved_url'].endswith('.gz')


def test_witness_appearances_and_recorded_tracks(reader):
    found = reader.search_entities({'table':'witnesses','text':'alex smith'})['rows']
    assert [r['witness_key'] for r in found] == ['appearance-1','appearance-2']
    assert reader.get_entity({'table':'witnesses','id':'appearance-2','section':'documents'})['rows'] == []
    assert reader.search_entities({'table':'rosters','filters':{'congress':119,'rank':3}})['rows'][0]['bioguide_id'] == 'A000001'
    recording = reader.search_entities({'table':'recordings','text':'youtube:abc'})['rows'][0]
    assert recording['tracks'][0]['saved_url'] == 'https://archive.example/bodies/sha256/55/'+'55'*32+'.gz'
    with pytest.raises(ExplorerError,match='scalar'):
        reader.search_entities({'table':'bills','filters':{'floor_votes':'bad'}})


def test_document_identity_hidden_reviews_sources_and_recoveries(reader):
    found = reader.search_documents({'measure_key':'119-hr-1','text':'agenda'})['rows']
    assert len(found) == 1
    doc = reader.get_document(found[0]['reference'])['rows'][0]
    assert doc['alternates'][0]['saved_url'].endswith('12'*32+'.gz')
    source = reader.get_document(dict(**doc['reference'],section='sources'))['rows'][0]
    assert source['url'] == 'https://fixture.test/agenda.pdf'
    assert not reader.search_documents({'text':'Hidden.pdf'})['rows']
    hidden = reader.search_documents({'text':'Hidden.pdf','include_hidden':True})['rows'][0]
    assert reader.get_document(hidden['reference'])['rows'][0]['review_note'] == 'Superseded by the complete record'
    for title,kind in [('excerpt','requested_content_in_official_hearing'),('substitute','official_substitute')]:
        ref = reader.search_documents({'text':title})['rows'][0]['reference']
        recovery = reader.get_document(dict(**ref,section='recoveries'))['rows'][0]
        assert recovery['kind'] == kind
        assert recovery['identity_note']
        assert recovery['saved_url'].endswith('.gz')
    with pytest.raises(ExplorerError,match='another release'):
        reader.get_document(dict(link_key=doc['reference']['link_key'],release_id='0'*64))


def test_paging_is_complete_and_bound_to_query(reader):
    page = reader.search_documents({'limit':2})
    cursor = page['next_cursor']
    rows = page['rows']
    while page['has_more']:
        page = reader.search_documents({'limit':2,'cursor':page['next_cursor']})
        rows += page['rows']
    assert len(rows) == 6
    assert len({r['reference']['link_key'] for r in rows}) == 6
    with pytest.raises(ExplorerError,match='another release or query'):
        reader.search_documents({'limit':2,'text':'different','cursor':cursor})
    with pytest.raises(ExplorerError,match='Cursor'):
        reader.search_documents({'cursor':'invalid'})


def test_absent_empty_and_unknown_are_distinct(tmp_path):
    reader = Reader(prepare(tmp_path, CURRENT/'manifest.json'))
    try:
        info = reader.dataset_info({})
        assert 'bills' in info['missing_entities']
        assert reader.search_entities({'table':'committees'})['rows'] == []
        assert reader.search_documents({})['rows'][0]['congress'] is None
        assert reader.search_documents({})['rows'][0]['saved_url'] is None
        with pytest.raises(ExplorerError,match='not published'):
            reader.search_entities({'table':'bills'})
    finally:
        reader.close()


@pytest.mark.parametrize('sql', ["CREATE TABLE nope AS SELECT 1", "COPY bills TO '/tmp/never.csv'", 'SET threads=9',
    'INSTALL httpfs', 'LOAD httpfs', "ATTACH '/tmp/never.duckdb'", 'SELECT 1; SELECT 2',
    "SELECT * FROM read_text('/etc/passwd')", "SELECT * FROM read_csv('https://example.com/a.csv')",
    "SELECT * FROM query('CREATE TABLE nope(i INTEGER)')", "SELECT * FROM glob('/etc/*')"])
def test_sql_cannot_modify_or_read_unselected_files(reader, sql):
    with pytest.raises((ExplorerError, duckdb.Error)):
        reader.query_sql({'sql':sql})
    assert reader.query_sql({'sql':'SELECT 1 AS alive'})['rows'] == [{'alive':1}]


def test_raw_binary_types_precision_nulls_and_bounded_results(reader):
    row = reader.query_sql({'sql': "SELECT unhex('00ff') AS raw,hex(unhex('00ff')) AS key,NULL AS unknown,9007199254740993::BIGINT AS large"})
    assert row['rows'] == [{'raw':r'\x00\xFF','key':'00FF','unknown':None,'large':9007199254740993}]
    assert row['columns'][0]['type'] == 'BLOB'
    result = reader.query_sql({'sql':'FROM range(1000)','limit':2})
    assert len(result['rows']) == 2 and result['truncated']
    result = reader.query_sql({'sql':"SELECT repeat('é',12000) AS text FROM range(100)", 'limit':100})
    assert result['truncated'] and len(encoded(result)) < MAX_BYTES
    with pytest.raises(ExplorerError,match='128 KiB'):
        reader.query_sql({'sql':"SELECT repeat('x',140000) AS huge"})
    with pytest.raises(ExplorerError,match='128 columns'):
        reader.query_sql({'sql':'SELECT '+','.join(f'{n} AS col{n}' for n in range(129))})
    assert reader.query_sql({'sql':'SELECT 2 AS alive'})['rows'] == [{'alive':2}]
