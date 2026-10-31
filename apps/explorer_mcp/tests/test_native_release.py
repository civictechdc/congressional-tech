"""The real native producer's release must work through the actual stdio client."""
import asyncio
from pathlib import Path
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest

from congressional_explorer_mcp.models import MAX_BYTES
from congressional_explorer_mcp.release import encoded, prepare


def test_native_producer_release_through_stdio(tmp_path, request):
    source = request.config.getoption('--native-fixture-root')
    if source is None:
        pytest.skip('Native integration requires --native-fixture-root from the producer test runner')
    # pytest also creates a "current" symlink; resolve and deduplicate it.
    candidates = {p.resolve() for p in Path(source).glob('test_phase2_entities_*/release/manifest.json')}
    assert len(candidates)==1, f'Expected one retained native phase 2 fixture, found {len(candidates)}'
    selected = prepare(tmp_path, candidates.pop(), archive_origin='https://archive.example')
    assert selected['manifest']['origin']['kind']=='model'
    native_schema = selected['controls']['schema']

    async def run():
        transport = StdioTransport(sys.executable, ['-m','congressional_explorer_mcp.cli','serve',
                                  '--data-dir',str(tmp_path)], keep_alive=False)
        async with Client(transport) as client:
            async def call(name, value=None):
                args = value if name=='get_dataset_info' else {'query':value}
                return (await client.call_tool(name, args or {})).data
            async def sql(text, parameters=()):
                return (await call('query_sql', {'sql':text,'parameters':list(parameters)}))['rows']
            tools = await client.list_tools()
            assert {t.name for t in tools}=={'get_dataset_info','search_documents','get_document','search_entities','get_entity','query_sql'}
            info = await call('get_dataset_info')
            assert info['release_id']==selected['release_id']
            assert len(encoded(info)) < MAX_BYTES
            assert 'bill_hearing_transcripts' in {r['id'] for r in info['recipes']}
            assert {'meetings','witnesses','recordings','committees','members','rosters','bills','nominations'} <= info['tables'].keys()
            for table in native_schema['files']:
                if table['available']:
                    result = await call('get_dataset_info', {'table':table['name'].removesuffix('.parquet')})
                    assert result['identity']==table['identity']
            for relationship in native_schema['relationships']:
                result = await call('get_dataset_info', {'relationship':relationship['id']})
                assert result['source']==relationship['source'] and result['target']==relationship['target']
                assert result['available']==relationship['available']
            witness = (await sql('''SELECT w.witness_key,w.event_id,l.list_row FROM witnesses w
                JOIN "list" l ON list_contains(l.witness_keys,w.witness_key) ORDER BY l.list_row LIMIT 1'''))[0]
            roster = (await sql('SELECT congress,system_code FROM rosters ORDER BY congress,system_code LIMIT 1'))[0]
            parameters = dict(witness, **roster,
                bill_id=(await sql('SELECT bill_id FROM bills ORDER BY bill_id LIMIT 1'))[0]['bill_id'],
                nomination_id=(await sql('SELECT nomination_id FROM nominations ORDER BY nomination_id LIMIT 1'))[0]['nomination_id'])
            for recipe in native_schema['recipes']:
                result = await call('get_dataset_info', {'recipe':recipe['id']})
                assert result['available']
                rows = await sql(result['sql'], [parameters.get(p['name'],p['example']) for p in result['parameters']])
                if recipe['id'] in ('bill_hearing_transcripts','witness_documents','hearing_documents','committee_roster','bill_votes','nomination_votes','recording_tracks'):
                    assert rows, recipe['id']
                if recipe['id'] == 'bill_hearing_transcripts':
                    assert len({r['list_row'] for r in rows}) == len(rows)
                    assert all(r['meeting_ids'] == sorted(set(r['meeting_ids'])) and r['meeting_ids'] for r in rows)
            found = await call('search_documents', {'witness_key':witness['witness_key']})
            assert found['rows']
            document = await call('get_document', found['rows'][0]['reference'])
            assert document['rows'][0]['saved_url']
            entities = await call('search_entities', {'table':'witnesses','filters':{'event_id':witness['event_id']}})
            assert any(r['witness_key']==witness['witness_key'] for r in entities['rows'])
            entity = await call('get_entity', {'table':'witnesses','id':witness['witness_key']})
            assert entity['rows'][0]['witness_key']==witness['witness_key']
    asyncio.run(run())
