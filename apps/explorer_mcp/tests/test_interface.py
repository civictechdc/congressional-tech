"""Compact discovery, selective entity reads, date qualification and bounded batch access."""
import asyncio
from copy import deepcopy
import json
import shutil
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.models import ExplorerError, MAX_BYTES
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import encoded, prepare, resolve
from congressional_explorer_mcp.server import create_server
from test_reader import edited_release


def test_compact_discovery_and_freshness_use_retained_metadata(selection):
    selected = deepcopy(selection)
    selected['publication'] = dict(published_at='2026-11-06T12:00:00Z', basis='release pointer observed during preparation')
    for item in selected['manifest']['files']:
        if item['name'] == 'bills.parquet':
            item['coverage'].update(source_updated_at='2026-11-05T09:23:00Z', source_update_basis='congress_bills.update_date',
                                    date_start='2025-01-03', date_end='2025-10-02')
        if item['name'] == 'rosters.parquet':
            item['coverage'].update(congress_start=119, congress_end=119, gaps=['Earlier Congresses unavailable'])
    with_reader = Reader(selected)
    try:
        # These paths do not execute SQL or construct the unscoped relationship response.
        with_reader.db.close()
        overview = with_reader.overview({})
        status = with_reader.dataset_status({})
        assert status['release_id'] == selected['release_id'] and status['published_at'] == selected['publication']['published_at']
        assert status['collections']['bills']['source_updated_at'] == '2026-11-05T09:23:00Z'
        assert status['collections']['bills']['observed_bounds']['date_end'] == '2025-10-02'
        roster = status['collections']['rosters']
        assert roster['source_updated_at'] is None and roster['source_update_status'].startswith('unavailable')
        assert roster['observed_bounds']['congress_start'] == 119 and roster['gaps'] == ['Earlier Congresses unavailable']
        assert len(encoded(overview)) < 2000
    finally:
        with_reader.close()
    with_reader = Reader(selection)
    try:
        assert with_reader.dataset_status({})['published_at'] is None
        assert len(encoded(overview)) < len(encoded(with_reader.dataset_info({}))) // 5
        focused = with_reader.dataset_info({'table': 'bills'})
        assert 'relationships' not in focused and 'floor_votes' in focused['columns']
        assert focused['entity_response']['default_mode'] == 'detail'
    finally:
        with_reader.close()


def test_entity_summary_and_exact_fields_do_not_decode_omitted_lists(reader):
    reader.db.execute('CREATE TEMP TABLE _bill AS FROM bills')
    reader.db.execute('''CREATE OR REPLACE VIEW bills AS SELECT * REPLACE (
        (SELECT list(struct_pack(bill_id:='119-s-'||i,title:=repeat('x',60),relationship_types:=['Companion bill']))
         FROM range(500) t(i)) AS related_bills, NULL::VARCHAR AS policy_area) FROM _bill''')
    full = reader.get_entity(dict(table='bills', id='119-hr-1'))
    compact = reader.get_entity(dict(table='bills', id='119-hr-1', mode='summary'))
    exact = reader.get_entity(dict(table='bills', id='119-hr-1', fields=['policy_area', 'related_bills']))
    assert compact['rows'][0]['bill_id'] == exact['rows'][0]['bill_id'] == '119-hr-1'
    assert compact['rows'][0]['policy_area'] is None
    assert exact['rows'][0]['related_bills'] == full['rows'][0]['related_bills']
    assert exact['rows'][0]['policy_area'] is None
    assert len(encoded(compact)) < len(encoded(full)) // 10
    with pytest.raises(ExplorerError, match='Unknown published field.*imaginary'):
        reader.get_entity(dict(table='bills', id='119-hr-1', fields=['imaginary']))
    reader.db.execute('CREATE OR REPLACE VIEW bills AS SELECT * REPLACE (repeat(title,20000) AS title) FROM _bill')
    # Column selection happens in SQL before the per-row byte check.
    assert reader.get_entity(dict(table='bills', id='119-hr-1', fields=['policy_area']))['rows'][0]['bill_id'] == '119-hr-1'
    with pytest.raises(ExplorerError, match='128 KiB'):
        reader.get_entity(dict(table='bills', id='119-hr-1'))


def test_chronological_search_obeys_published_date_status(phase2, tmp_path):
    listed = pq.read_table(phase2.parent / 'list.parquet')
    dates = listed['document_date'].to_pylist()
    import datetime
    dates[:4] = [datetime.date(1901, 3, 2), datetime.date(2021, 3, 17), datetime.date(2303, 5, 4), None]
    listed = listed.set_column(listed.schema.get_field_index('document_date'), 'document_date', pa.array(dates, pa.date32()))
    filenames = listed['filename'].to_pylist()
    filenames[:4] = [f'Chronological control {i}' for i in range(4)]
    listed = listed.set_column(listed.schema.get_field_index('filename'), 'filename', pa.array(filenames))
    hidden = listed['hidden'].to_pylist()
    hidden[:4] = [False] * 4
    listed = listed.set_column(listed.schema.get_field_index('hidden'), 'hidden', pa.array(hidden))
    detail = pq.read_table(phase2.parent / 'detail.parquet')
    detail = detail.append_column('document_date_status', pa.array(['accepted', 'accepted', 'suspect', *[None] * (detail.num_rows - 3)], pa.string()))
    reader = edited_release(phase2, tmp_path, files=[('list.parquet', listed), ('detail.parquet', detail)])
    query = dict(text='Chronological control')
    try:
        def positions(**extra):
            return [row['list_row'] for row in reader.search_documents(dict(query, **extra))['rows']]
        assert positions() == [0, 1, 2, 3]
        assert positions(sort='recent') == [1, 0]
        assert positions(sort='oldest') == [0, 1]
        assert positions(sort='recent', include_suspect=True, include_undated=True) == [2, 1, 0, 3]
        first = reader.search_documents(dict(query, sort='recent', limit=1))
        second = reader.search_documents(dict(query, sort='recent', limit=1, cursor=first['next_cursor']))
        assert [row['list_row'] for row in second['rows']] == [0]
        suspect = reader.search_documents(dict(query, sort='recent', include_suspect=True))['rows'][0]
        assert suspect['document_date'] == '2303-05-04' and suspect['document_date_status'] == 'suspect'
        exact = reader.get_document(suspect['reference'])['rows'][0]
        assert exact['document_date'] == '2303-05-04'
        assert reader.query_sql({'sql': "SELECT document_date FROM documents WHERE document_date=DATE '2303-05-04'"})['rows']
    finally:
        reader.close()


def test_older_release_chronology_preserves_literal_dates_and_reports_limit(reader):
    result = reader.search_documents(dict(sort='recent', include_undated=True))
    assert 'unavailable' in result['date_qualification'] and len(result['rows']) == 6
    assert reader.get_entity(dict(table='bills', id='119-hr-1', mode='summary'))['rows'][0]['bill_id'] == '119-hr-1'


def test_publication_date_retained_from_pointer_and_exact_pinned_manifest(tmp_path, phase2, monkeypatch):
    manifest = json.loads(phase2.read_bytes())
    release_id = manifest['release_id']
    root = tmp_path / 'published'
    shutil.copytree(phase2.parent, root / 'releases' / release_id)
    pointer = dict(release_id=release_id, published_at='2026-11-06T12:00:00Z')
    (root / 'manifest.json').write_bytes(encoded(pointer))
    selected = prepare(tmp_path / 'selected', root / 'manifest.json')
    assert selected['publication']['published_at'] == pointer['published_at']
    # An unchanged reprepare retains observed publication metadata too.
    assert prepare(tmp_path / 'selected', root / 'manifest.json')['publication'] == selected['publication']
    url = f'https://archive.example/viewer-publications/releases/{release_id}/manifest.json'
    reads = []
    def control(location):
        reads.append(location)
        return manifest if location == url else pointer
    monkeypatch.setattr('congressional_explorer_mcp.release.control', control)
    metadata = {}
    resolve(url, publication_metadata=metadata)
    assert reads == [url, 'https://archive.example/viewer-publications/manifest.json']
    assert metadata['published_at'] == pointer['published_at']
    pointer['release_id'] = '0' * 64
    metadata = {}
    resolve(url, publication_metadata=metadata)
    assert metadata == {}, 'A different selected release cannot supply this release publication date'


def test_batch_independent_errors_pages_and_response_budget(selection, monkeypatch):
    calls = []
    def body(target, query, **kwargs):
        calls.append(query.model_dump())
        text = ('é' * 15000)[query.offset:query.offset + query.max_chars]
        return dict(release_id=target['release_id'], reference=target['reference'], text=text,
                    rows=[dict(text=text)], next_offset=query.offset + len(text) if query.offset + len(text) < 15000 else None,
                    has_more=query.offset + len(text) < 15000)
    monkeypatch.setattr('congressional_explorer_mcp.body_reader.read_document_body', body)
    async def run():
        async with Client(create_server(selection)) as client:
            async def call(name, query):
                return (await client.call_tool(name, dict(query=query))).data
            found = await call('search_documents', {'limit': 2})
            one, two = [row['reference'] for row in found['rows']]
            text = dict(two, section='text', max_chars=100)
            items = [one, dict(one, link_key='0' * 16), dict(one, release_id='0' * 64), text]
            result = await call('get_documents', dict(items=items))
            assert [item['status'] for item in result['items']] == ['ok', 'error', 'error', 'ok']
            assert result['items'][0]['result'] == await call('get_document', one)
            assert result['items'][3]['result'] == await call('get_document', text)
            assert 'absent or ambiguous' in result['items'][1]['error']
            assert 'another release' in result['items'][2]['error']
            continuation = result['items'][3]['next_query']
            assert continuation['offset'] == 100 and continuation['link_key'] == two['link_key']
            assert (await call('get_documents', dict(items=[continuation])))['items'][0]['result']['next_offset'] == 200
            # Independently sized outputs exceed one aggregate response, not one item's cap.
            large = dict(two, section='text', max_chars=15000)
            budget = await call('get_documents', dict(items=[large] * 4))
            assert len(encoded(budget)) <= MAX_BYTES
            assert any(item['status'] == 'deferred' for item in budget['items'])
            retry = next(item['next_query'] for item in budget['items'] if item['status'] == 'deferred')
            assert (await call('get_document', retry))['text'] == 'é' * 15000
            bad = await client.call_tool('get_documents', {'query': {'items': [one] * 11}}, raise_on_error=False)
            assert bad.is_error
            # Work admission occurs before invoking the body reader.
            monkeypatch.setattr('congressional_explorer_mcp.body_reader.MAX_BODY_BYTES', 1)
            before = len(calls)
            deferred = await call('get_documents', dict(items=[text, text]))
            assert [item['status'] for item in deferred['items']] == ['deferred', 'deferred']
            assert len(calls) == before
    asyncio.run(run())


def test_interface_through_actual_stdio(tmp_path, phase2):
    selected = prepare(tmp_path, phase2)
    async def run():
        transport = StdioTransport(sys.executable, ['-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(tmp_path)], keep_alive=False)
        async with Client(transport) as client:
            assert (await client.call_tool('get_overview')).data['release_id'] == selected['release_id']
            status = (await client.call_tool('get_dataset_status')).data
            assert status['published_at'] is None and status['collections']['bills']['source_updated_at'] is None
            focused = (await client.call_tool('get_dataset_info', {'table': 'bills'})).data
            assert 'floor_votes' in focused['columns'] and 'relationships' not in focused
            compact = (await client.call_tool('get_entity', {'query': {'table': 'bills', 'id': '119-hr-1', 'mode': 'summary'}})).data
            assert 'related_bills' not in compact['rows'][0]
            document = (await client.call_tool('search_documents', {'query': {'sort': 'recent', 'limit': 1}})).data
            assert 'unavailable' in document['date_qualification']
            batch = (await client.call_tool('get_documents', {'query': {'items': [document['rows'][0]['reference']]}})).data
            assert batch['items'][0]['status'] == 'ok'
            for query, expected in [({'sql': 'SELECT FROM'}, 'Parser Error'),
                ({'sql': 'SELECT imaginary_column FROM bills'}, 'imaginary_column'),
                ({'sql': 'SELECT * FROM imaginary_table'}, 'imaginary_table'),
                ({'sql': 'SELECT ? AS n'}, 'parameters: 1'),
                ({'sql': 'SELECT ?::INTEGER AS n', 'parameters': ['bad']}, 'Conversion Error')]:
                error = await client.call_tool('query_sql', {'query': query}, raise_on_error=False)
                assert error.is_error and expected in error.content[0].text
            assert (await client.call_tool('query_sql', {'query': {'sql': 'SELECT ? AS n', 'parameters': [7]}})).data['rows'] == [{'n': 7}]
    asyncio.run(run())
