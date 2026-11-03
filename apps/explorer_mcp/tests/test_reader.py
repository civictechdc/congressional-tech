import json
import shutil

import duckdb
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.models import ExplorerError, MAX_BYTES
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT, REPO, manifest


def test_all_tables_and_nested_fields_are_available(reader):
    info = reader.dataset_info({})
    assert not info['missing_entities']
    # Identity comes from the release's schema; the reader keeps no second map.
    declared = {f['name'].removesuffix('.parquet'): f['identity']['fields'] for f in
                json.loads((REPO / 'model/registries/release-schema.json').read_text())['files']
                if f['identity']['scope'] == 'published identifier' and f['name'] not in ('links.parquet', 'retired_links.parquet')}
    assert info['entity_keys'] == declared
    assert declared.keys() <= info['tables'].keys()
    assert info['tables']['rosters']['rows'] == 1
    assert reader.dataset_info({'table': 'bills'})['columns']['floor_votes'].startswith('STRUCT')
    assert reader.dataset_info({'table': 'capture_scope'}) == {'version': 1, 'entries': []}
    assert reader.query_sql({'sql': 'FROM future_data'})['rows'] == [
        {'future_field': 'new published column', 'amount': '42.123456789012345678'}]
    assert reader.query_sql({'sql': "SELECT name,cross_ids.fec AS fec,terms[1].district AS district FROM members"})['rows'] == [
        {'name': 'Sam Example', 'fec': ['H1', 'H2'], 'district': 1}]
    assert reader.query_sql({'sql': 'SELECT bill_id,floor_votes[1].yea AS yea,amendments[1].purpose AS purpose FROM bills'})['rows'] == [
        {'bill_id': '119-hr-1', 'yea': 220, 'purpose': 'Add transit safety'}]


def test_documents_view_holds_one_copy_of_each_column_on_keyed_detail(tmp_path):
    # Older releases pair list and detail; newer detail files also repeat list's columns.
    root = tmp_path / 'release'
    shutil.copytree(CURRENT, root)
    listed = pq.read_table(root / 'list.parquet')
    detail = pq.read_table(root / 'detail.parquet')
    for name in listed.column_names:
        detail = detail.append_column(name, listed[name])
    pq.write_table(detail, root / 'detail.parquet')
    keyed = Reader(prepare(tmp_path / 'keyed', manifest(root)))
    old = Reader(prepare(tmp_path / 'old', CURRENT / 'manifest.json'))
    try:
        assert list(keyed.schemas['documents']) == list(old.schemas['documents'])
        assert keyed.query_sql({'sql': 'SELECT filename FROM documents ORDER BY list_row'})['rows'] == \
            old.query_sql({'sql': 'SELECT filename FROM documents ORDER BY list_row'})['rows']
    finally:
        keyed.close()
        old.close()


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
    assert {'congress', 'document_date', 'document_date_source', 'first_captured', 'date_kind',
            'document_kind', 'saved_kind', 'hidden'} <= result['rows'][0].keys()
    assert all(not r['hidden'] for r in result['rows'])


def test_witness_appearances_and_recorded_tracks(reader):
    found = reader.search_entities({'table':'witnesses','text':'alex smith'})['rows']
    assert [r['witness_key'] for r in found] == ['appearance-1','appearance-2']
    assert reader.get_entity({'table':'witnesses','id':'appearance-2','section':'documents'})['rows'] == []
    assert [r['bill_id'] for r in reader.search_entities({'table':'bills','text':'One Big Beautiful Bill'})['rows']] == ['119-hr-1']
    assert reader.search_entities({'table':'rosters','filters':{'congress':119,'rank':3}})['rows'][0]['bioguide_id'] == 'A000001'
    recording = reader.search_entities({'table':'recordings','text':'youtube:abc'})['rows'][0]
    assert recording['tracks'][0]['saved_url'] == 'https://archive.example/bodies/sha256/55/'+'55'*32+'.gz'
    with pytest.raises(ExplorerError,match='scalar.*bill_id'):
        reader.search_entities({'table':'bills','filters':{'floor_votes':'bad'}})
    with pytest.raises(ExplorerError,match='scalar.*witness_key'):
        reader.search_entities({'table':'witnesses','filters':{'record_sha':'bad'}})
    with pytest.raises(ExplorerError,match='Unknown filter field.*bill_id'):
        reader.search_entities({'table':'bills','filters':{'congress':119}})


def test_document_identity_hidden_reviews_sources_and_recoveries(reader):
    found = reader.search_documents({'measure_key':'119-hr-1','text':'agenda'})['rows']
    assert len(found) == 1
    assert found[0]['hidden'] is False
    doc = reader.get_document(found[0]['reference'])['rows'][0]
    assert doc['primary_source_url'] == 'https://fixture.test/agenda.pdf'
    assert doc['alternates'][0]['saved_url'].endswith('12'*32+'.gz')
    source = reader.get_document(dict(**doc['reference'],section='sources'))['rows'][0]
    assert source['url'] == 'https://fixture.test/agenda.pdf'
    assert not reader.search_documents({'text':'Hidden.pdf'})['rows']
    hidden = reader.search_documents({'text':'Hidden.pdf','include_hidden':True})['rows'][0]
    assert hidden['hidden'] is True
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
        # This release's schema states no identity: the reader does not invent one.
        info = reader.dataset_info({})
        assert info['entity_keys'] == {} and info['missing_entities'] == []
        assert info['entity_identity'] == 'not published in this release'
        with pytest.raises(ExplorerError,match='no published identity'):
            reader.search_entities({'table':'committees'})
        with pytest.raises(ExplorerError,match='no single identifier'):
            reader.get_entity({'table':'committees','id':'hsif00'})
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


def test_retired_keys_redirect_or_explain_their_removal(tmp_path):
    root = tmp_path / 'release'
    shutil.copytree(CURRENT, root)
    live = pq.read_table(root / 'links.parquet').to_pylist()[0]
    with duckdb.connect() as db:
        db.execute(f"""COPY (SELECT * FROM (VALUES
            (unhex('aaaaaaaaaaaaaaaa'),unhex('{live['link_key'].hex()}'),'{'d'*64}','old.pdf',NULL::BLOB[]),
            (unhex('bbbbbbbbbbbbbbbb'),NULL::BLOB,'{'e'*64}','gone.pdf',[unhex('{live['link_key'].hex()}')])) v(link_key,successor_key,last_release_id,last_filename,address_versions))
            TO '{root / 'retired_links.parquet'}' (FORMAT PARQUET)""")
    reader = Reader(prepare(tmp_path / 'selection', manifest(root)))
    try:
        release = reader.release_id
        redirected = reader.get_document(dict(link_key='aa' * 8, release_id=release))
        assert redirected['redirected_from'] == 'aa' * 8
        assert redirected['rows'][0]['list_row'] == live['list_row']
        with pytest.raises(ExplorerError, match=f'no longer in the archive; it was last published as "gone.pdf" in release eeeeeeeeeeee; other versions at the same address: {live["link_key"].hex()}'):
            reader.get_document(dict(link_key='bb' * 8, release_id=release))
        with pytest.raises(ExplorerError, match='absent or ambiguous'):
            reader.get_document(dict(link_key='cc' * 8, release_id=release))
        with pytest.raises(ExplorerError, match='another release'):  # references stay bound to one release
            reader.get_document(dict(link_key='aa' * 8, release_id='0' * 64))
    finally:
        reader.close()


def edited_release(phase2, tmp_path, *, drop=(), schema=None, files=()):
    """A copy of the phase 2 fixture with files dropped or added and its schema edited."""
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    (root / 'manifest.json').unlink()
    for name in drop:
        (root / name).unlink()
    for name, table in files:
        pq.write_table(table, root / name)
    if schema:
        value = json.loads((root / 'schema.json').read_text())
        schema(value)
        (root / 'schema.json').write_text(json.dumps(value))
    return Reader(prepare(tmp_path / 'selection', manifest(root)))


def test_a_new_keyed_table_reaches_its_documents_from_the_schema_alone(phase2, tmp_path):
    import pyarrow as pa
    listed = pq.read_table(phase2.parent / 'list.parquet')
    keys = pa.array([['x-1'] if i == 0 else [] for i in range(listed.num_rows)], pa.list_(pa.string()))
    def declare(schema):
        schema['files'].append(dict(name='x.parquet', columns=[dict(name='x_id', type='string', meaning='A new entity')],
            identity=dict(fields=['x_id'], scope='published identifier', validation='fixture', kind='primary_key')))
        schema['relationships'].append(dict(id='document_x', source=dict(table='list', fields=['x_keys[]']),
            target=dict(table='x', fields=['x_id']), meaning='Fixture'))
    reader = edited_release(phase2, tmp_path, schema=declare, files=[('list.parquet', listed.append_column('x_keys', keys)),
        ('x.parquet', pa.table({'x_id': ['x-1', 'x-2'], 'name': ['First x', 'Second x']}))])
    try:
        assert reader.dataset_info({})['entity_keys']['x'] == ['x_id']
        assert reader.get_entity({'table': 'x', 'id': 'x-1'})['rows'] == [{'x_id': 'x-1', 'name': 'First x'}]
        assert [r['filename'] for r in reader.get_entity({'table': 'x', 'id': 'x-1', 'section': 'documents'})['rows']] == ['Agenda.pdf']
        assert reader.get_entity({'table': 'x', 'id': 'x-2', 'section': 'documents'})['rows'] == []
        assert [r['x_id'] for r in reader.search_entities({'table': 'x', 'text': 'second'})['rows']] == ['x-2']
    finally:
        reader.close()


def test_a_declared_table_missing_from_the_release_is_unavailable_not_empty(phase2, tmp_path):
    reader = edited_release(phase2, tmp_path, drop=['meeting_coverage.parquet'])
    try:
        assert reader.dataset_info({})['missing_entities'] == ['meeting_coverage']
        for call in (lambda: reader.search_entities({'table': 'meeting_coverage'}),
                     lambda: reader.search_entities({'table': 'meeting_coverage', 'filters': {'event_id': 118001}})):
            with pytest.raises(ExplorerError, match='not published'):
                call()
    finally:
        reader.close()


def test_explorer_families_by_their_published_keys(reader):
    assert reader.get_entity({'table': 'videos', 'id': 'youtube:free'})['rows'][0]['handle'] == '@AgRepublicans'
    assert reader.get_entity({'table': 'channels', 'id': '@AgRepublicans'})['rows'][0]['committee_label'] == 'Agriculture'
    assert reader.get_entity({'table': 'committee_records', 'id': 'rec-1'})['rows'][0]['kind'] == 'amendment'
    assert [r['match_id'] for r in reader.search_entities({'table': 'recording_matches', 'filters': {'decision': 'linked'}})['rows']] == ['a']
    assert reader.search_entities({'table': 'meeting_coverage', 'filters': {'event_id': 118001}})['rows'] == [
        {'event_id': 118001, 'aspect': 'recording', 'state': 'present'}]
    with pytest.raises(ExplorerError, match='no single identifier'):
        reader.get_entity({'table': 'meeting_coverage', 'id': 118001})
    assert [r['record_key'] for r in reader.search_entities({'table': 'committee_records', 'text': 'voice vote'})['rows']] == ['rec-1']
    assert [r['handle'] for r in reader.search_entities({'table': 'channels', 'text': 'agriculture'})['rows']] == ['@AgRepublicans']
    with pytest.raises(ExplorerError, match='no published identity'):
        reader.search_entities({'table': 'links'})


# Tables whose rows carry no display text; a new table must be added here or gain a searchable column.
NO_TEXT = {'url_state', 'url_variants', 'meeting_coverage'}


def test_every_entity_table_is_text_searchable_or_explicitly_not(reader):
    from congressional_explorer_mcp.reader import TEXT_FIELDS
    schema = json.loads((REPO / 'model/registries/release-schema.json').read_text())
    columns = {f['name'].removesuffix('.parquet'): {c['name'] for c in f['columns']} for f in schema['files']}
    for table in reader.dataset_info({})['entity_keys']:
        assert bool(columns[table] & set(TEXT_FIELDS)) != (table in NO_TEXT), table


def test_upstream_relations_are_published_as_stated(reader, tmp_path, phase2):
    published = json.loads((REPO / 'model/registries/release-schema.json').read_text())['upstream_relations']
    info = reader.dataset_info({})
    assert [u['id'] for u in info['upstream_relations']] == [u['id'] for u in published]
    assert len(published) == 7
    one = reader.dataset_info({'relationship': 'member_votes'})
    assert {k: one[k] for k in ('family', 'table', 'key_columns', 'joins', 'row_meaning', 'limits')} == \
        {k: published[2][k] for k in ('family', 'table', 'key_columns', 'joins', 'row_meaning', 'limits')}
    assert one['upstream'] is True and one['missing_tables'] == []
    old = Reader(prepare(tmp_path / 'old', CURRENT / 'manifest.json'))
    try:
        assert old.dataset_info({})['upstream_relations'] == 'not published in this release'
    finally:
        old.close()


def test_document_dates_carry_their_basis(reader):
    row = reader.search_documents({'limit': 1})['rows'][0]
    assert {'document_date', 'document_date_source', 'first_captured', 'date_kind'} <= row.keys()


@pytest.mark.parametrize('shape', ['row_position_detail', 'retired_links'])
def test_document_address_tables_are_never_entities(phase2, tmp_path, shape):
    # Releases 448651e7 and c94bfedc key detail by list_row; links is still a document address, read by get_document.
    files = []
    def edit(schema):
        if shape == 'row_position_detail':
            detail = next(f for f in schema['files'] if f['name'] == 'detail.parquet')
            detail['identity'] = dict(fields=['list_row'], scope='release', validation='fixture', kind='row_position')
        else:
            schema['files'].append(dict(name='retired_links.parquet', columns=[],
                identity=dict(fields=['link_key'], scope='published identifier', validation='fixture', kind='primary_key')))
            schema['relationships'].append(dict(id='retired_link_successor', source=dict(table='retired_links', fields=['successor_key']),
                target=dict(table='links', fields=['link_key']), meaning='Fixture'))
    if shape == 'retired_links':
        import pyarrow as pa
        files = [('retired_links.parquet', pa.table({'link_key': [b'\xaa' * 8], 'successor_key': [None]}, schema=pa.schema(
            [('link_key', pa.binary()), ('successor_key', pa.binary())])))]
    reader = edited_release(phase2, tmp_path, schema=edit, files=files)
    try:
        keys = reader.dataset_info({})['entity_keys']
        assert not {'links', 'retired_links'} & keys.keys() and 'meetings' in keys
        with pytest.raises(ExplorerError, match='no published identity'):
            reader.search_entities({'table': 'links'})
    finally:
        reader.close()
