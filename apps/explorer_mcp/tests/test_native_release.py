"""The real native producer's release must work through the actual stdio client."""
import asyncio
from pathlib import Path
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest

from congressional_explorer_mcp.models import MAX_BYTES
from congressional_explorer_mcp import TOOL_NAMES
from congressional_explorer_mcp.release import encoded, prepare


def test_native_producer_release_through_stdio(tmp_path, request):
    source = request.config.getoption('--native-fixture-root')
    if source is None:
        pytest.skip('Native integration requires --native-fixture-root from the producer test runner')
    # The build with the five Explorer tables. pytest also creates a "current" symlink; resolve and deduplicate it.
    candidates = {p.resolve() for p in Path(source).glob('test_phase2_entities_*/release-explorer/manifest.json')}
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
            assert {t.name for t in tools} == TOOL_NAMES
            info = await call('get_dataset_info')
            assert info['release_id']==selected['release_id']
            assert len(encoded(info)) < MAX_BYTES
            overview = (await client.call_tool('get_overview')).data
            status = (await client.call_tool('get_dataset_status')).data
            assert overview['release_id'] == status['release_id'] == selected['release_id']
            assert len(encoded(overview)) < len(encoded(info))
            assert 'relationships' not in await call('get_dataset_info', {'table': 'bills'})
            chronological = await call('search_documents', {'sort': 'recent', 'limit': 100})
            assert all(row['document_date_status'] == 'accepted' for row in chronological['rows'])
            if chronological['rows']:
                reference = chronological['rows'][0]['reference']
                batch = await call('get_documents', {'items': [reference]})
                assert batch['items'][0]['result'] == await call('get_document', reference)
            assert 'bill_hearing_transcripts' in {r['id'] for r in info['recipes']}
            assert {'meetings','witnesses','recordings','committees','members','rosters','bills','nominations'} <= info['tables'].keys()
            # ct-x78c: a House list with no meeting-id reaches its meeting through its own document links.
            listed = await call('search_entities', {'table':'witnesses','filters':{'event_id':115538}})
            assert {r['name'] for r in listed['rows'] if r.get('source') in (None, 'house_xml')} >= {'Dr. Jane Smith', 'Dr. Jane Smith Second Panel'}
            # Entity keys, missing tables and upstream relations come from the release's own schema (ct-m104).
            assert info['missing_entities'] == []
            assert {'videos','channels','recording_matches','committee_records','meeting_coverage'} <= info['entity_keys'].keys()
            assert info['upstream_relations'] == native_schema['upstream_relations'] and len(info['upstream_relations']) == 7
            upstream = native_schema['upstream_relations'][0]
            assert {k: v for k, v in (await call('get_dataset_info', {'relationship':upstream['id']})).items()
                    if k in upstream} == upstream
            coverage = await call('get_dataset_info', {'table':'meeting_coverage'})
            assert coverage['identity']['fields'] == ['event_id','aspect'] and coverage['available']
            assert {m['name'] for m in coverage['meanings']} >= {'state','reason'}
            video = await call('get_entity', {'table':'videos','id':'youtube:agHearing01'})
            assert (video['rows'][0]['handle'], video['rows'][0]['stated_event_ids']) == ('@AgRepublicans', [115538])
            curated = await call('search_entities', {'table':'recording_matches','filters':{'basis':'curated'}})
            assert {r['subject_kind']: (r['event_id'], r['url'], r['status']) for r in curated['rows']} == {
                'event': (115538, 'https://example.test/watch', 'decided'),
                'package': (None, 'https://example.test/watch', 'decided'),
            }
            recording_recipe = await call('get_dataset_info', {'recipe':'meeting_recordings'})
            hearing_recipe = await call('get_dataset_info', {'recipe':'hearing_dossier'})
            observations = await sql(recording_recipe['sql'], [115538])
            assert observations == (await sql(hearing_recipe['sql'], [115538]))[0]['recordings']
            assert len({r['match_id'] for r in observations}) == len(observations)
            assert {(r['subject_kind'], r['meeting_links'][0]['scope']) for r in observations if r['basis']=='curated'} == {
                ('event','event'), ('package','package_context')}
            assert all(r['meeting_links'][0]['event_id']==115538 for r in observations)
            record = (await call('search_entities', {'table':'committee_records','filters':{'event_id':115538}}))['rows']
            assert [(r['kind'], r['bill']) for r in record] == [('amendment', 'H.R. 1234')]
            assert (await call('get_entity', {'table':'committee_records','id':record[0]['record_key']}))['rows'] == record
            unmatched = await call('get_dataset_info', {'recipe':'channel_unmatched_videos'})
            assert [r['video_key'] for r in await sql(unmatched['sql'], ['@AgRepublicans'])] == ['youtube:agUpload02']
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
                    # ct-1xt0: one row per transcript package.
                    packages = await sql('SELECT package_id FROM detail WHERE list_contains(?::INTEGER[], list_row)',
                                         [[r['list_row'] for r in rows]])
                    assert len({p['package_id'] for p in packages}) == len(rows) == len(packages)
            found = await call('search_documents', {'witness_key':witness['witness_key']})
            assert found['rows']
            assert all({'document_date_source','first_captured','date_kind'} <= r.keys() for r in found['rows'])
            document = await call('get_document', found['rows'][0]['reference'])
            assert document['rows'][0]['saved_url']
            entities = await call('search_entities', {'table':'witnesses','filters':{'event_id':witness['event_id']}})
            assert any(r['witness_key']==witness['witness_key'] for r in entities['rows'])
            entity = await call('get_entity', {'table':'witnesses','id':witness['witness_key']})
            assert entity['rows'][0]['witness_key']==witness['witness_key']
    asyncio.run(run())


def test_repaired_bill_filenames_through_stdio(tmp_path, request):
    source = request.config.getoption('--native-fixture-root')
    if source is None:
        pytest.skip('Native integration requires --native-fixture-root from the producer test runner')
    candidates = {p.resolve() for p in Path(source).glob('test_repaired_bill_filename_*/release/manifest.json')}
    assert len(candidates)==1, f'Expected one retained repaired filename fixture, found {len(candidates)}'
    prepare(tmp_path, candidates.pop(), archive_origin='https://archive.example')

    async def run():
        transport = StdioTransport(sys.executable, ['-m','congressional_explorer_mcp.cli','serve',
                                  '--data-dir',str(tmp_path)], keep_alive=False)
        async with Client(transport) as client:
            found = (await client.call_tool('search_documents', {'query':{'limit':20}})).data
            details = {}
            for row in found['rows']:
                document = (await client.call_tool('get_document', {'query':row['reference']})).data
                details[row['filename']] = document['rows'][0]
            return found['rows'], details
    docs, details = asyncio.run(run())
    by_name = {row['filename']: row for row in docs}
    assert by_name['hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf']['document_date'] == '2017-05-23'
    assert by_name['hearing_memo_--_leg_hrg_on_hr_2167_06.23.16.pdf']['document_date'] == '2016-06-23'
    assert by_name['hearing_memo_--_leg_hrg_on_h.r._2199_05.23.2017.pdf']['document_date'] == '2017-05-23'
    assert by_name['hearing_memo_--_leg_hrg_on_hr_2167_06.23.2016.pdf']['document_date'] == '2016-06-23'
    assert not any(str(row.get('document_date', '')).startswith(('2199-', '2167-')) for row in docs)
    for fname, expected_date, expected_source, expected_ref in [
        ('hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf', '2017-05-23', 'meeting', 'hr2199'),
        ('hearing_memo_--_leg_hrg_on_hr_2167_06.23.16.pdf', '2016-06-23', 'meeting', 'hr2167'),
        ('hearing_memo_--_leg_hrg_on_h.r._2199_05.23.2017.pdf', '2017-05-23', 'filename', 'hr2199'),
        ('hearing_memo_--_leg_hrg_on_hr_2167_06.23.2016.pdf', '2016-06-23', 'filename', 'hr2167'),
    ]:
        detail = details[fname]
        assert detail['document_date'] == expected_date
        assert detail['document_date_source'] == expected_source
        facts = {(f['field'], f['value']) for f in detail['facts']}
        assert ('measure_references', expected_ref) in facts
        assert not any(f['field'] == 'date_token_candidates' and f['value'].startswith(('2199-', '2167-')) for f in detail['facts'])


def test_native_html_reader_fixture_through_stdio(tmp_path, request):
    source = request.config.getoption('--native-fixture-root')
    if source is None:
        pytest.skip('Native integration requires --native-fixture-root from the producer test runner')
    candidates = {p.resolve() for p in Path(source).glob('test_shared_html_reader_*/release/manifest.json')}
    assert len(candidates) == 1, f'Expected one retained native HTML reader fixture, found {len(candidates)}'
    selection = prepare(tmp_path, candidates.pop(), archive_origin='https://archive.example')

    async def run():
        transport = StdioTransport(sys.executable, ['-m', 'congressional_explorer_mcp.cli', 'serve',
                                   '--data-dir', str(tmp_path)], keep_alive=False)
        async with Client(transport) as client:
            async def call(name, query):
                return (await client.call_tool(name, query if name == 'get_dataset_info' else {'query': query})).data

            detail = await call('get_dataset_info', {'table': 'detail'})
            release_id = detail['release_id']
            assert release_id == selection['release_id']
            assert {'modified_on', 'page_metadata', 'selected_text'} <= detail['columns'].keys()
            rows = (await call('query_sql', {'sql': """
                SELECT lower(hex(link_key)) AS link_key,modified_on,main_content.outcome AS outcome
                FROM documents WHERE modified_on=DATE '2025-04-01' OR main_content.text_available
                ORDER BY modified_on NULLS LAST
            """}))['rows']
            dated, marked = rows
            assert dated['modified_on'] == '2025-04-01' and marked['outcome'] == 'marked'
            ref = dict(release_id=release_id, link_key=dated['link_key'])
            facts = await call('get_document', dict(ref, section='page_metadata'))
            assert facts['source']['reader_version']
            assert facts['source']['saved_body'] and facts['release_id'] == release_id
            assert any(row['selected'] and row['field'] == 'modified_time' and row['date'] == '2025-04-01'
                       for row in facts['rows'])
            ref['link_key'] = marked['link_key']
            summary = (await call('get_document', ref))['rows'][0]
            assert 'selected_text' not in summary and 'selected_text' in summary['sections']
            parts = []
            offset = 0
            while offset is not None:
                result = await call('get_document', dict(ref, section='selected_text', offset=offset, max_chars=1000))
                assert result['release_id'] == release_id and result['offset'] == offset
                assert result['selector'] == summary['main_content']['selector']
                assert result['reader_version'] == summary['main_content']['reader_version']
                assert len(encoded(result)) < MAX_BYTES
                parts.append(result['text'])
                offset = result['next_offset']
            from hashlib import sha256
            assert sha256(''.join(parts).encode()).hexdigest() == summary['main_content']['text_sha256']

    asyncio.run(run())
