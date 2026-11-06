"""Normal MCP entry points over retained PDF, statement and caption evidence."""
import asyncio
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil
import sys

import duckdb
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.caption_reader import cue_rows
from congressional_explorer_mcp.citations import caption_source_id, text_citation
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import encoded, literal, prepare
from congressional_explorer_mcp.server import create_server
from conftest import manifest, replace_rows
from test_body_reader import local_archive_server, make_pdf_bytes


def hearing_release(tmp_path,phase2,origin):
    root=tmp_path/'release'
    shutil.copytree(phase2.parent,root)
    pdf=make_pdf_bytes(['Official transcript page one.','Witness statement on page two.'])
    html=b'<html><body><p>Prepared witness statement with original wording.</p></body></html>'
    vtt=b'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\ncue-a\n00:00:01.000 --> 00:00:02.000 align:start\nFirst complete caption.\n\n00:00:03.000 --> 00:00:04.000\nSecond caption.\n'
    playlist=b'#EXTM3U\n#EXTINF:4.0,\nsegment.vtt\n#EXT-X-ENDLIST\n'
    incomplete=b'#EXTM3U\n#EXTINF:4.0,\nsegment.vtt\n#EXTINF:4.0,\nmissing.vtt\n#EXT-X-ENDLIST\n'
    payloads=[pdf,html,vtt,playlist,incomplete,b'1\n00:00:01,000 --> 00:00:02,000\nSRT source.\n',
        b'<tt><body><p begin="1s" end="2s">TTML first<br/>second.</p></body></tt>',
        b'#EXTM3U\n#EXTINF:4.0,\nsegment.vtt\n#EXTINF:4.0,\nsegment.vtt\n#EXT-X-ENDLIST\n']
    shas=[sha256(b).digest() for b in payloads]
    def documents(rows):
        for i,fmt in enumerate(['pdf','html']):
            rows[i].update(format=fmt,hidden=False,meeting_keys=['334136','101'],witness_keys=['appearance-1'] if i==0 else ['appearance-1','appearance-2'],document_kind=['witness-testimony'])
    replace_rows(root,'list',documents)
    def details(rows):
        for i,fmt in enumerate(['pdf','html']):
            rows[i].update(saved_body=shas[i],saved_suffix='.pdf' if fmt=='pdf' else '',saved_media_type='application/pdf' if fmt=='pdf' else 'text/html',saved_bytes=len(payloads[i]))
    replace_rows(root,'detail',details)
    with duckdb.connect() as db:
        def write(name,sql):
            old=root/f'{name}.parquet'
            if old.exists():
                old.rename(root/f'{name}-prior.parquet')
            db.execute(f'COPY ({sql}) TO {literal(old)} (FORMAT PARQUET)')
        prior=lambda name:literal(root/f'{name}-prior.parquet')
        write('meetings',f'''SELECT * EXCLUDE(event) REPLACE(event AS event_id,
            CASE WHEN event IN (101,104) THEN [struct_pack(source:='printed_hearing',package_id:='CHRG-118hhrg1',list_row:=0,formats:=['pdf'],video_key:=NULL::VARCHAR,language:=NULL::VARCHAR,production:=NULL::VARCHAR)]
            WHEN event=334136 THEN [struct_pack(source:='printed_hearing',package_id:='CHRG-118hhrg1',list_row:=0,formats:=['pdf'],video_key:=NULL::VARCHAR,language:=NULL::VARCHAR,production:=NULL::VARCHAR),
              struct_pack(source:='committee_transcript',package_id:=NULL::VARCHAR,list_row:=1,formats:=['html'],video_key:=NULL::VARCHAR,language:=NULL::VARCHAR,production:=NULL::VARCHAR)]
            ELSE [] END AS transcripts)
            FROM read_parquet({prior('meetings')}),unnest([101,102,103,104,105,106,107,334136,338785]) e(event) WHERE event_id=118001''')
        write('recordings',f'''SELECT 'senate:complete' AS video_key,[338785::BIGINT] AS event_ids,
            [struct_pack(body:=unhex('{shas[3].hex()}'),suffix:='',format:='m3u8',language:='en',production:='live')] AS tracks
            UNION ALL SELECT 'senate:incomplete',[102::BIGINT],[struct_pack(body:=unhex('{shas[4].hex()}'),suffix:='',format:='m3u8',language:='en',production:='live')]
            UNION ALL SELECT 'youtube:direct',[101::BIGINT],[struct_pack(body:=unhex('{shas[2].hex()}'),suffix:='',format:='vtt',language:='en',production:='asr')]
            UNION ALL SELECT 'youtube:unmatched',[]::BIGINT[],[struct_pack(body:=unhex('{shas[2].hex()}'),suffix:='',format:='vtt',language:='en',production:='asr')]
            UNION ALL SELECT 'youtube:srt',[105::BIGINT],[struct_pack(body:=unhex('{shas[5].hex()}'),suffix:='',format:='srt',language:='en',production:='caption')]
            UNION ALL SELECT 'youtube:ttml',[106::BIGINT],[struct_pack(body:=unhex('{shas[6].hex()}'),suffix:='',format:='ttml',language:='en',production:='caption')]
            UNION ALL SELECT 'senate:overlap',[107::BIGINT],[struct_pack(body:=unhex('{shas[7].hex()}'),suffix:='',format:='m3u8',language:='en',production:='live')]''')
        write('recording_matches',f'''SELECT * REPLACE(NULL::BIGINT AS event_id,'CHRG-context' AS package_id,
            'senate:complete' AS video_key,[struct_pack(event_id:=334136::BIGINT,basis:='print_agreement',scope:='package_context')] AS meeting_links)
            FROM read_parquet({prior('recording_matches')})''')
        write('witnesses',f'''SELECT * REPLACE(334136::BIGINT AS event_id) FROM read_parquet({prior('witnesses')})''')
        # Use the published selected-text shape as a witness passage, including an ambiguous source association.
        write('detail',f'''SELECT *,
          CASE WHEN row_number() OVER()=2 THEN 'Prepared witness statement with original wording.' ELSE NULL END AS selected_text,
          struct_pack(selector:='rdfa:content:encoded',reader_version:='published-reader-v1',
            text_sha256:='{sha256(b'Prepared witness statement with original wording.').hexdigest()}',text_available:=true) AS main_content
          FROM read_parquet({prior('detail')})''')
    (root/'caption_resources.parquet').unlink()
    resources=[]
    for video,idx in [('senate:complete',3),('senate:incomplete',4),('senate:overlap',7)]:
        base='https://www.senate.gov/'+video.split(':')[1]+'/'
        for ordinal,(url,body,fmt) in enumerate([('track.m3u8',shas[idx],'m3u8'),('segment.vtt',shas[2],'vtt')]+
            ([('missing.vtt',None,None)] if idx==4 else [('segment.vtt',shas[2],'vtt')] if idx==7 else [])):
            resources.append(dict(video_key=video,track_body=shas[idx],ordinal=ordinal,source_url=base+url,
                declared_uri=url if ordinal else None,body=body,suffix='' if body else None,format=fmt,parser_version='fixture-playlist-v1',status='retained' if body else 'missing'))
    pq.write_table(pa.Table.from_pylist(resources),root/'caption_resources.parquet')
    # Prior files are test construction inputs, never release tables.
    for path in root.glob('*-prior.parquet'):
        path.unlink()
    selected=prepare(tmp_path/'selected',manifest(root),archive_origin=origin)
    return selected,payloads,shas


def test_hearing_tools_transcript_paging_cues_dossier_and_passage_roundtrips(tmp_path,phase2):
    routes={}
    with local_archive_server(routes) as (origin,requests):
        selected,payloads,shas=hearing_release(tmp_path,phase2,origin)
        for i,(payload,digest) in enumerate(zip(payloads,shas)):
            routes[f'/bodies/sha256/{digest.hex()[:2]}/{digest.hex()}{".pdf" if i==0 else ""}']=payload
        mcp=create_server(selected,data_dir=tmp_path/'selected')
        async def run():
            async with Client(mcp) as client:
                async def call(name,**kwargs):
                    return (await client.call_tool(name,kwargs)).data
                tools={t.name for t in await client.list_tools()}
                assert {'get_transcript','get_hearing_bundle','resolve_citation'}<=tools
                # Printed and committee text remain distinct; the caption link keeps package scope.
                inventory=await call('get_transcript',event_id=334136)
                assert {r['kind'] for r in inventory['rows']}=={'official','committee','captions'}
                caption=next(r for r in inventory['rows'] if r['kind']=='captions')
                assert caption['association_scope']=='package_context'
                official=next(r for r in inventory['rows'] if r['kind']=='official')
                pdf=await call('get_transcript',**official['reference'],page=2,max_chars=18)
                assert pdf['text']=='Witness statement '
                assert pdf['next_offset']==18 and pdf['citation']['witness_key']=='appearance-1'
                assert (await call('resolve_citation',citation=pdf['citation']))['text']==pdf['text']
                bad=deepcopy(pdf['citation']);bad['saved_body']='ff'*32
                assert (await call('resolve_citation',citation=bad))['state']=='different_source'
                bad=deepcopy(pdf['citation']);bad['source']['link_key']='00'*8
                assert (await call('resolve_citation',citation=bad))['state']=='unavailable'
                bad=deepcopy(pdf['citation']);bad['source']['release_id']='ff'*32
                assert (await call('resolve_citation',citation=bad))['state']=='unavailable'
                # The current witness rule and exact recording observation survive the one-call dossier.
                bundle=await call('get_hearing_bundle',event_id=334136,limit=1)
                witnesses=bundle['sections']['witnesses']
                assert all(w['superseded_by'] is None for w in witnesses['rows'])
                assert witnesses['has_more']
                continued=await call('get_hearing_bundle',**witnesses['next'])
                assert continued['sections']['witnesses']['rows'][0]['witness_key']!=witnesses['rows'][0]['witness_key']
                observation=bundle['sections']['recordings']['rows'][0]
                assert observation['event_id'] is None and observation['meeting_links'][0]['scope']=='package_context'
                assert observation['source_ref']=='fixture'
                assert len(encoded(bundle))<=128<<10
                sparse=await call('get_hearing_bundle',event_id=103)
                assert sparse['sections']['official_transcripts']['state']=='unknown'
                assert sparse['sections']['witnesses']['rows']==[]
                transcript_only=await call('get_transcript',event_id=104)
                assert [r['kind'] for r in transcript_only['rows']]==['official']
                assert (await call('get_transcript',**transcript_only['rows'][0]['reference'],page=1))['text']=='Official transcript page one.'
                # event338785 shape: a playlist omitted by the historical transcript list remains discoverable.
                inventory=await call('get_transcript',event_id=338785,kind='captions')
                ref=inventory['rows'][0]['reference']
                first=await call('get_transcript',**ref,limit=1)
                assert first['coverage']=='complete_snapshot' and first['has_more']
                cue=first['rows'][0]
                assert cue['start_seconds']==1 and cue['mpeg_start_seconds']==11
                assert cue['identifier']=='cue-a' and cue['settings']=='align:start'
                assert (await call('resolve_citation',citation=cue['citation']))['text']=='First complete caption.'
                snippet=deepcopy(cue['citation'])
                snippet['location'].update(offset=6,length=8)
                snippet['text_sha256']=sha256(b'complete').hexdigest()
                assert (await call('resolve_citation',citation=snippet))['text']=='complete'
                second=await call('get_transcript',**ref,limit=1,cursor=first['next_cursor'])
                assert second['rows'][0]['text']=='Second caption.' and not second['has_more']
                skipped=await call('get_transcript',**ref,offset=1,limit=1)
                assert skipped['rows']==second['rows']
                # Missing declarations survive and do not turn a readable segment into a complete track.
                broken=(await call('get_transcript',event_id=102))['rows'][0]['reference']
                partial=await call('get_transcript',**broken)
                assert partial['state']=='partial' and partial['coverage']=='partial'
                assert partial['missing_resource_count']==1 and partial['missing_resources'][0]['ordinal']==2
                # Direct captions need no playlist map; transcript-only selection reads via the same body reader.
                direct=next(r for r in (await call('get_transcript',event_id=101))['rows'] if r['kind']=='captions')
                assert (await call('get_transcript',**direct['reference']))['rows'][1]['text']=='Second caption.'
                direct_source=dict(release_id=selected['release_id'],kind='captions',video_key='youtube:unmatched',
                    source_id=caption_source_id('youtube:unmatched',shas[2].hex(),'en','asr'))
                direct_citation=text_citation(dict(reference=direct_source,saved_body=shas[2].hex(),reader_version='archive-cues-v1'),
                    dict(kind='caption_cue',resource_ordinal=0,cue_index=0,segment_body=shas[2].hex(),start='00:00:01.000',end='00:00:02.000'),
                    'First complete caption.')
                unmatched=await call('resolve_citation',citation=direct_citation)
                assert unmatched['state']=='resolved' and 'event_id' not in unmatched['source']
                for event,expected in [(105,'SRT source.'),(106,'TTML first\nsecond.')]:
                    ref=(await call('get_transcript',event_id=event))['rows'][0]['reference']
                    timed=await call('get_transcript',**ref)
                    assert timed['rows'][0]['text']==expected
                    assert (await call('resolve_citation',citation=timed['rows'][0]['citation']))['text']==expected
                overlapping=(await call('get_transcript',event_id=107))['rows'][0]['reference']
                overlapping=await call('get_transcript',**overlapping)
                assert [r['resource_ordinal'] for r in overlapping['rows']]==[1,1,2,2]
                assert [r['mpeg_start_seconds'] for r in overlapping['rows']]==[11,13,11,13]
                assert (await call('resolve_citation',citation=overlapping['rows'][2]['citation']))['text']=='First complete caption.'
                committee=next(r for r in (await call('get_transcript',event_id=334136))['rows'] if r['kind']=='committee')
                statement=await call('get_document',query=dict(**committee['document_reference'],section='selected_text',offset=9,max_chars=17))
                assert statement['citation']['witness_key'] is None and statement['citation']['witness_attribution']=='ambiguous'
                assert (await call('resolve_citation',citation=statement['citation']))['text']==statement['text']
                forged=deepcopy(statement['citation']);forged['witness_key']='unrelated-occurrence'
                assert (await call('resolve_citation',citation=forged))['state']=='unavailable'
                for invalid in ('338784.9', True, 338785.0):
                    bad=await client.call_tool('get_transcript',dict(event_id=invalid),raise_on_error=False)
                    assert bad.is_error
        asyncio.run(run())
        assert requests and all(path.startswith('/bodies/sha256/') for path in requests)


def test_old_release_playlist_fallback_and_missing_table_states(tmp_path,phase2):
    with local_archive_server({}) as (origin,_):
        selected,_,_=hearing_release(tmp_path,phase2,origin)
        selected['tables'].pop('caption_resources')
        selected['tables'].pop('meeting_coverage')
        with_reader=Reader(selected)
        try:
            bundle=with_reader.get_hearing_bundle(dict(event_id=334136,include=['coverage']))
            assert bundle['sections']['coverage']['state']=='unavailable'
            source=with_reader.transcript_inventory(dict(event_id=338785))['rows'][0]
            page=with_reader.caption_resource_page(dict(query=dict(**source['reference']),source=dict(source,release_id=selected['release_id'])))
            assert not page['available'] and 'not published' in page['reason']
        finally:
            with_reader.close()


def test_caption_parsers_preserve_cue_occurrences_and_refuse_invalid_timing():
    assert [r['text'] for r in cue_rows('1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n2\n00:00:03,000 --> 00:00:04,000\nFirst','srt')]==['First','First']
    assert list(cue_rows('<tt><body><div><p begin="1s" end="2s">Test</p></div></body></tt>','ttml'))[0]['start_seconds']==1
    assert list(cue_rows('<tt><body><p begin="1s" end="2s">First<br/>Second <span>third</span> fourth</p></body></tt>','ttml'))[0]['text']=='First\nSecond third fourth'
    with pytest.raises(ValueError,match='before'):
        list(cue_rows('WEBVTT\n\n00:00:03.000 --> 00:00:02.000\nInvalid','vtt'))
    with pytest.raises(ValueError,match='unseparated'):
        list(cue_rows('WEBVTT\n00:00:01.000 --> 00:00:02.000\nInvalid','vtt'))


def test_native_caption_inventory_parity_and_citation_roundtrips(tmp_path,request):
    """A native producer release keeps independent full tracks beside a playlist (review F1)."""
    source=request.config.getoption('--native-fixture-root')
    if source is None:
        pytest.skip('Requires the retained native phase2 producer fixture')
    candidates={p.resolve() for p in Path(source).glob('test_phase2_entities_*/release-explorer/manifest.json')}
    assert len(candidates)==1
    manifest_path=candidates.pop()
    raw=manifest_path.parent.parent/'raw'
    routes={'/'+path.relative_to(raw).as_posix():path.read_bytes() for path in (raw/'bodies/sha256').glob('*/*')}
    native_meetings=pq.read_table(manifest_path.parent/'meetings.parquet').to_pylist()
    expected={(t['video_key'],fmt,t['language'],t['production']) for m in native_meetings if m['event_id']==115538
        for t in m['transcripts'] if t['source']=='captions' for fmt in t['formats']}
    senate_expected={('senate:ag051023','m3u8','en','live'),('senate:ag051023','vtt','en','live'),('senate:ag051023','vtt','es','live')}
    assert {key for key in expected if key[0]=='senate:ag051023'}==senate_expected
    with local_archive_server(routes) as (origin,requests):
        selected=prepare(tmp_path,manifest_path,archive_origin=origin)
        async def run():
            transport=StdioTransport(sys.executable,['-m','congressional_explorer_mcp.cli','serve','--data-dir',str(tmp_path)],keep_alive=False)
            async with Client(transport) as client:
                async def call(name,**args):
                    return (await client.call_tool(name,args)).data
                inventory=await call('get_transcript',event_id=115538,kind='captions',limit=100)
                actual={(row['video_key'],row['format'],row['language'],row['production']) for row in inventory['rows']}
                assert not inventory['has_more']
                assert expected-actual==set()
                assert actual-expected==set()
                assert len(inventory['rows'])==len(expected)
                bodies={row['saved_body'] for row in inventory['rows']}
                segment=b'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:183000\n\n00:00:01.000 --> 00:00:02.000\nSegment cue\n'
                assert sha256(segment).hexdigest() not in bodies
                assert sha256(b'WEBVTT\n\n').hexdigest() not in bodies
                senate_text=set()
                for row in inventory['rows']:
                    assert row['reference']['release_id']==selected['release_id']
                    assert row['source_id']==caption_source_id(row['video_key'],row['saved_body'],row['language'],row['production'])
                    read=await call('get_transcript',**row['reference'],limit=1)
                    assert read['rows']
                    assert read['coverage']==('complete_snapshot' if row['format']=='m3u8' else 'retained_file')
                    passage=read['rows'][0]
                    reopened=await call('resolve_citation',citation=passage['citation'])
                    assert reopened['state']=='resolved'
                    assert reopened['text']==passage['text']
                    if row['video_key']=='senate:ag051023':
                        senate_text.add(passage['text'])
                assert senate_text=={'Segment cue','Independent complete English captions','Pista completa independiente en espanol'}
        asyncio.run(run())
        assert requests and all(path.startswith('/bodies/sha256/') for path in requests)
