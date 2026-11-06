"""Complete verified body/cue search, incremental reuse, recovery and immutable selection."""
import asyncio
from copy import deepcopy
from hashlib import sha256, md5
import json
from pathlib import Path
import shutil
import sys
import zlib

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congressional_explorer_mcp.index_builder import build
from congressional_explorer_mcp.models import ExplorerError, TextSearch
from congressional_explorer_mcp.release import encoded, prepare
from congressional_explorer_mcp.text_index import TextIndex, source_data_id, extraction_definition, connect, inflate, MAX_PASSAGE_BYTES
from conftest import CURRENT, manifest, replace_rows
from test_body_reader import local_archive_server, make_pdf_bytes


def source_fixture(tmp_path, origin, routes):
    root = tmp_path / 'release'
    shutil.copytree(CURRENT, root)
    payloads = [make_pdf_bytes(['First page common wording', 'Secret cobalt pineapple appropriation evidence']),
        b'<html><body><p>Body-only parliamentary glacier testimony.</p></body></html>', b'', b'corrupt PDF',
        b'Undated substantive memorandum', b'unsupported ZIP', b'Suspect chronology control']
    formats = ['pdf', 'html', 'text', 'pdf', 'text', 'zip', 'text']
    bodies = [sha256(value).digest() for value in payloads]
    for body, value in zip(bodies, payloads):
        routes[f'/bodies/sha256/{body.hex()[:2]}/{body.hex()}'] = value
    def listed(rows):
        for index, row in enumerate(rows):
            row.update(filename=f'Metadata-{index}', title=f'Unrelated title {index}', format=formats[index], hidden=False,
                committee_keys=['hsif00'] if index == 0 else ['ssfi00'], witness_keys=['appearance-1'] if index == 1 else [],
                document_kind=['witness-statement'] if index == 1 else ['document'])
        import datetime
        rows[0]['document_date'] = datetime.date(2024, 5, 1)
        rows[6]['document_date'] = datetime.date(2303, 5, 4)
    replace_rows(root, 'list', listed)
    def details(rows):
        for index, row in enumerate(rows):
            row.update(saved_body=bodies[index], saved_suffix='', saved_bytes=len(payloads[index]), saved_media_type='text/plain')
    replace_rows(root, 'detail', details)
    detail = pq.read_table(root / 'detail.parquet')
    detail = detail.append_column('document_date_status', pa.array(['accepted', 'accepted', None, None, None, None, 'suspect'], pa.string()))
    pq.write_table(detail, root / 'detail.parquet')
    caption = b'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v Alice>Caption-only amber satellite observation.\n'
    caption_body = sha256(caption).digest()
    routes[f'/bodies/sha256/{caption_body.hex()[:2]}/{caption_body.hex()}'] = caption
    tracks_type = pa.list_(pa.struct([('body', pa.binary()), ('suffix', pa.string()), ('format', pa.string()), ('language', pa.string()), ('production', pa.string())]))
    pq.write_table(pa.table({'video_key': ['youtube:search'], 'event_ids': [[118001]],
        'tracks': pa.array([[dict(body=caption_body, suffix='', format='vtt', language='en', production='publisher')]], tracks_type)}), root / 'recordings.parquet')
    selected = prepare(tmp_path / 'selected', manifest(root), archive_origin=origin)
    return root, selected, bodies


def attach(root, selected, output, report, target):
    value = deepcopy(selected['manifest'])
    data = output.read_bytes()
    value['files'].append(dict(name='search_index.sqlite', sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(),
                              size=len(data), rows=0, producer='verified-corpus-text-index', coverage=report['coverage']))
    value['text_index'] = dict(version=1, source_data_id=report['source_data_id'], definition=report['definition']['sha256'], coverage=report['coverage'])
    value['release_id'] = sha256(encoded([1, [[item[key] for key in ('name', 'sha256', 'size', 'rows')] for item in value['files']]])).hexdigest()
    (root / 'manifest.json').write_bytes(encoded(value))
    return prepare(target, root / 'manifest.json', archive_origin=selected['archive_origin'])


def test_full_body_caption_filters_and_actual_stdio(tmp_path):
    routes = {}
    with local_archive_server(routes) as (origin, requests):
        root, selected, bodies = source_fixture(tmp_path, origin, routes)
        output = root / 'search_index.sqlite'
        report = build(selected, tmp_path / 'work', output)
        assert report['state'] == 'complete' and report['pending_bodies'] == 0
        assert {row['state'] for row in report['coverage']['by_source_kind']} >= {'indexed', 'empty', 'unreadable', 'excluded: unsupported format zip'}
        selected = attach(root, selected, output, report, tmp_path / 'indexed')
        index = TextIndex(selected)
        phrase = 'Secret cobalt pineapple'
        row = index.search(TextSearch(text=phrase))['rows'][0]
        assert phrase in row['text'] and row['location']['page'] == 2
        assert row['citation']['text_sha256'] == sha256(row['text'].encode()).hexdigest()
        assert index.search(TextSearch(text=phrase, committee_key='hsif00', date_from='2024-01-01', date_to='2024-12-31'))['rows']
        assert not index.search(TextSearch(text=phrase, committee_key='ssfi00'))['rows']
        assert not index.search(TextSearch(text=phrase, date_from='2025-01-01'))['rows']
        testimony = index.search(TextSearch(text='parliamentary glacier', document_type='witness-statement', witness_key='appearance-1'))
        assert testimony['rows'] and testimony['rows'][0]['citation']['witness_attribution'] == 'source_association'
        assert not index.search(TextSearch(text='parliamentary glacier', speaker='Alice'))['rows']
        caption = index.search(TextSearch(text='amber satellite', source_kind='caption', speaker='Alice'))['rows'][0]
        assert caption['location']['cue_index'] == 0 and caption['location']['resource_ordinal'] == 0
        assert caption['location']['segment_body'] == caption['saved_body']
        assert caption['speaker_labels'] == ['Alice'] and caption['citation']['witness_key'] is None
        assert row['citation']['backend']['name'] == 'pypdf'
        assert index.resolve({'citation':row['citation']})['text'] == row['text']
        assert index.resolve({'citation':caption['citation']})['text'] == caption['text']
        planted=deepcopy(row['citation']);planted['text_sha256']='0'*64
        assert index.resolve({'citation':planted})['state'] == 'different_source'
        assert not index.search(TextSearch(text='Suspect chronology'))['rows']
        assert index.search(TextSearch(text='Suspect chronology', include_suspect=True))['rows']
        before = len(requests)
        async def run():
            transport = StdioTransport(sys.executable, ['-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(tmp_path / 'indexed')], keep_alive=False)
            async with Client(transport) as client:
                query = dict(text=phrase, committee_key='hsif00')
                result = (await client.call_tool('search_text', {'query': query})).data
                assert result['rows'][0]['text'] == row['text']
                metadata_search = (await client.call_tool('search_documents', {'query': {'text': phrase}})).data
                assert metadata_search['rows'] == []
                location = row['location']
                body = (await client.call_tool('get_document', {'query': dict(row['reference'], section='text', page=location['page'], offset=location['offset'], max_chars=location['length'])})).data
                assert body['text'] == row['text']
        asyncio.run(run())
        # Search and normal get_document reuse the same immutable verified reading.
        assert len(requests) == before


def test_incremental_changed_retired_and_recovery_reuse(tmp_path, monkeypatch):
    routes = {}
    with local_archive_server(routes) as (origin, requests):
        root, selected, bodies = source_fixture(tmp_path, origin, routes)
        work = tmp_path / 'work'
        import congressional_explorer_mcp.index_builder as builder
        frozen_definition=extraction_definition()
        # Fault injection changes a callable, not the pinned on-disk builder definition.
        monkeypatch.setattr(builder,'extraction_definition',lambda:frozen_definition)
        consume = builder._consume
        def interrupt(*args):
            raise RuntimeError('interrupted after durable extraction')
        monkeypatch.setattr(builder, '_consume', interrupt)
        link=pq.read_table(root/'detail.parquet')['link_key'][0].as_py().hex()
        with pytest.raises(RuntimeError, match='durable extraction'):
            build(selected, work, limit=1,only_sources=['document:'+link])
        fetched = len(requests)
        assert list(work.glob('*.pages.gz'))
        monkeypatch.setattr(builder, '_consume', consume)
        first = build(selected, work, root / 'search_index.sqlite')
        assert first['recovered_completions'] == 1
        assert len(requests) < fetched + len(bodies) + 1
        snapshot = (root / 'search_index.sqlite').read_bytes()
        # Same complete input does no source work.
        count = len(requests)
        unchanged = build(selected, work)
        assert unchanged['processed_bodies'] == 0 and len(requests) == count
        second_root = tmp_path / 'new-release'
        shutil.copytree(root, second_root)
        (second_root / 'search_index.sqlite').unlink()
        changed = b'Replacement ultraviolet mango evidence'
        changed_body = sha256(changed).digest()
        routes[f'/bodies/sha256/{changed_body.hex()[:2]}/{changed_body.hex()}'] = changed
        def change(rows):
            rows[0].update(saved_body=changed_body, saved_bytes=len(changed), saved_suffix='', saved_media_type='text/plain')
            rows.pop()
        replace_rows(second_root, 'detail', change)
        replace_rows(second_root, 'list', lambda rows: (rows[0].update(format='text'), rows.pop()))
        links = pq.read_table(second_root / 'links.parquet')
        import pyarrow.compute as pc
        pq.write_table(links.filter(pc.less(links['list_row'], 6)), second_root / 'links.parquet')
        newer = prepare(tmp_path / 'new-selected', manifest(second_root), archive_origin=origin)
        second = build(newer, work, second_root / 'search_index.sqlite')
        assert second['reference_changes']['changed'] == 1 and second['reference_changes']['retired'] == 1
        assert second['processed_bodies'] == 1 and len(requests) == count + 1
        assert (root / 'search_index.sqlite').read_bytes() == snapshot
        newer = attach(second_root, newer, second_root / 'search_index.sqlite', second, tmp_path / 'new-indexed')
        assert TextIndex(newer).search(TextSearch(text='ultraviolet mango'))['rows']
        assert not TextIndex(newer).search(TextSearch(text='Secret cobalt pineapple'))['rows']
        assert not TextIndex(newer).search(TextSearch(text='Suspect chronology', include_suspect=True))['rows']


def test_partial_and_definition_mismatch_cannot_publish(tmp_path):
    routes = {}
    with local_archive_server(routes) as (origin, requests):
        root, selected, _ = source_fixture(tmp_path, origin, routes)
        with pytest.raises(ExplorerError, match='definition differs'):
            build(selected, tmp_path / 'wrong', expected_definition='0' * 64)
        assert not requests and not (tmp_path / 'wrong').exists()
        with pytest.raises(ExplorerError, match='partial indexing run'):
            build(selected, tmp_path / 'partial', root / 'search_index.sqlite', limit=1)
        assert not (root / 'search_index.sqlite').exists()
        result = build(selected, tmp_path / 'partial')
        assert result['state'] == 'complete'


def test_source_binding_and_bounded_compressed_passages(tmp_path):
    routes = {}
    with local_archive_server(routes) as (origin, _):
        root, selected, _ = source_fixture(tmp_path, origin, routes)
        report = build(selected, tmp_path / 'work', root / 'search_index.sqlite')
        selected = attach(root, selected, root / 'search_index.sqlite', report, tmp_path / 'indexed')
        selected['manifest']['files'][0]['coverage']['gaps'].append('Changed source meaning')
        with pytest.raises(ExplorerError, match='different source data'):
            TextIndex(selected)
    with pytest.raises(ExplorerError, match='decoded limit'):
        inflate(zlib.compress(b'a' * (MAX_PASSAGE_BYTES + 1)))


def test_retryable_body_read_stays_pending_then_resumes_without_flag(tmp_path):
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,bodies=source_fixture(tmp_path,origin,routes)
        path=f'/bodies/sha256/{bodies[1].hex()[:2]}/{bodies[1].hex()}'
        payload=routes.pop(path)
        link=pq.read_table(root/'detail.parquet')['link_key'][1].as_py().hex()
        with pytest.raises(ExplorerError,match='still retryable'):
            build(selected,tmp_path/'work',only_sources=['document:'+link])
        with connect(tmp_path/'work/work.sqlite') as db:
            assert db.execute("SELECT count(*) FROM bodies WHERE state='retryable'").fetchone()[0]==1
        assert requests.count(path)==3
        routes[path]=payload
        result=build(selected,tmp_path/'work',only_sources=['document:'+link])
        assert result['processed_bodies']==1 and requests.count(path)==4
        assert result['state']=='partial'
        assert build(selected,tmp_path/'work',root/'search_index.sqlite')['state']=='complete'


def test_playlist_coverage_and_shared_body_eligibility_are_independent(tmp_path):
    from congressional_explorer_mcp.citations import caption_source_id
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        recording=pq.read_table(root/'recordings.parquet').to_pylist()[0]
        direct=recording['tracks'][0];body=direct['body']
        good=b'#EXTM3U\n#EXTINF:2,\none.vtt\n#EXTINF:2,\nmissing.vtt\n#EXTINF:2,\nbad.vtt\n#EXT-X-ENDLIST\n'
        bad=b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:2,\none.vtt\n#EXT-X-ENDLIST\n'
        malformed=b'WEBVTT\n\ninvalid timing\n'
        good_body,bad_body,malformed_body=[sha256(value).digest() for value in (good,bad,malformed)]
        for digest,value in ((good_body,good),(bad_body,bad),(malformed_body,malformed)):
            routes[f'/bodies/sha256/{digest.hex()[:2]}/{digest.hex()}']=value
        # Invalid playlist deliberately precedes the direct source sharing its child.
        recording['tracks']=[dict(direct,body=bad_body,format='m3u8'),direct,dict(direct,body=good_body,format='m3u8')]
        schema=pq.read_table(root/'recordings.parquet').schema
        pq.write_table(pa.Table.from_pylist([recording],schema=schema),root/'recordings.parquet')
        resources=[]
        def resource(track,ordinal,uri,digest,fmt,state='retained'):
            resources.append(dict(video_key='youtube:search',track_body=track,ordinal=ordinal,declared_uri=uri,
                                  body=digest,suffix='',format=fmt,status=state))
        resource(bad_body,0,None,bad_body,'m3u8');resource(bad_body,1,'one.vtt',body,'vtt')
        resource(good_body,0,None,good_body,'m3u8');resource(good_body,1,'one.vtt',body,'vtt')
        resource(good_body,2,'missing.vtt',None,'vtt','missing');resource(good_body,3,'bad.vtt',malformed_body,'vtt')
        resource_schema=pa.schema([('video_key',pa.string()),('track_body',pa.binary()),('ordinal',pa.int64()),
          ('declared_uri',pa.string()),('body',pa.binary()),('suffix',pa.string()),('format',pa.string()),('status',pa.string())])
        pq.write_table(pa.Table.from_pylist(resources,schema=resource_schema),root/'caption_resources.parquet')
        selected=prepare(tmp_path/'with-resources',manifest(root),archive_origin=origin)
        report=build(selected,tmp_path/'work',root/'search_index.sqlite')
        selected=attach(root,selected,root/'search_index.sqlite',report,tmp_path/'indexed')
        result=TextIndex(selected).search(TextSearch(text='amber satellite',source_kind='caption'))
        bad_id=caption_source_id('youtube:search',bad_body.hex(),'en','publisher')
        good_id=caption_source_id('youtube:search',good_body.hex(),'en','publisher')
        assert result['rows'] and all(row['reference']['source_id']!=bad_id for row in result['rows'])
        good_hit=next(row for row in result['rows'] if row['reference']['source_id']==good_id)
        coverage=good_hit['caption_resource_coverage']
        assert coverage['archive_state']=='partial' and coverage['publisher_snapshot']=='closed' and coverage['endlist'] is True
        assert coverage['missing_resources']==1 and coverage['unreadable_resources']==1
        assert requests.count(f'/bodies/sha256/{body.hex()[:2]}/{body.hex()}')==1


def test_phrase_verification_and_keyset_pagination(tmp_path):
    routes={}
    with local_archive_server(routes) as (origin,_):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        report=build(selected,tmp_path/'work',root/'search_index.sqlite')
        selected=attach(root,selected,root/'search_index.sqlite',report,tmp_path/'indexed')
        index=TextIndex(selected)
        assert index.search(TextSearch(text='cobalt appropriation',match='all'))['rows']
        assert not index.search(TextSearch(text='cobalt appropriation',match='phrase'))['rows']
        complete=index.search(TextSearch(text='evidence observation testimony',match='any',include_suspect=True,limit=100))
        query=dict(text='evidence observation testimony',match='any',include_suspect=True,limit=1)
        rows=[]
        page=index.search(TextSearch(**query));rows+=page['rows']
        while page['has_more']:
            page=index.search(TextSearch(**query,cursor=page['next_cursor']));rows+=page['rows']
        assert [(row['source_key'],row['location']) for row in rows]==[(row['source_key'],row['location']) for row in complete['rows']]


def test_coverage_keeps_distinct_source_dispositions(tmp_path):
    from congressional_explorer_mcp.text_index import initialize
    from congressional_explorer_mcp.index_builder import coverage
    with connect(tmp_path/'coverage.sqlite') as db:
        initialize(db)
        for key,reason in [('a','unavailable: absent body'),('b','excluded: unsupported binary')]:
            db.execute('INSERT INTO sources VALUES(?,NULL,?,?,?,?)',[key,'document','{}','source',reason])
        result=coverage(db,'source')['by_source_kind']
        assert {item['state']:item['count'] for item in result}=={'unavailable: absent body':1,'excluded: unsupported binary':1}


def test_association_changes_reseed_without_reopening_unchanged_bodies(tmp_path,monkeypatch):
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        build(selected,tmp_path/'work')
        before=len(requests)
        import congressional_explorer_mcp.index_builder as builder
        original=builder.qualify_caption_sources
        old=extraction_definition()
        def changed_association(db,identity):
            return original(db,identity)
        monkeypatch.setattr(builder,'qualify_caption_sources',changed_association)
        current=extraction_definition()
        assert current['association_definition']!=old['association_definition']
        assert current['body_definitions']==old['body_definitions']
        report=build(selected,tmp_path/'work')
        assert report['processed_bodies']==0 and len(requests)==before
        assert report['definition']['association_definition']==current['association_definition']


def test_cache_retirement_does_not_invalidate_body_readings(monkeypatch):
    from congressional_explorer_mcp import body_reader
    before=extraction_definition()
    def changed_cache(*args,**kwargs):
        raise AssertionError('Index extraction must not use the disposable body cache')
    monkeypatch.setattr(body_reader,'_write_cached_pages',changed_cache)
    assert extraction_definition()==before


def test_digest_refusal_cannot_become_successful_unreadable_coverage(tmp_path):
    routes={}
    with local_archive_server(routes) as (origin,_):
        root,selected,bodies=source_fixture(tmp_path,origin,routes)
        route=f'/bodies/sha256/{bodies[1].hex()[:2]}/{bodies[1].hex()}'
        correct=routes[route];routes[route]=b'wrong bytes at a trusted archive address'
        link=pq.read_table(root/'detail.parquet')['link_key'][1].as_py().hex()
        with pytest.raises(ExplorerError,match='still refused'):
            build(selected,tmp_path/'work',only_sources=['document:'+link])
        with connect(tmp_path/'work/work.sqlite') as db:
            assert db.execute("SELECT count(*) FROM body_failures WHERE category='refused'").fetchone()[0]==1
        routes[route]=correct
        assert build(selected,tmp_path/'work',only_sources=['document:'+link])['processed_bodies']==1


def test_freeze_generations_prune_and_restore_reappearing_readings(tmp_path):
    import congressional_explorer_mcp.index_storage as storage
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,bodies=source_fixture(tmp_path,origin,routes)
        work=tmp_path/'durable'
        output=root/'search_index.sqlite'
        first=build(selected,work,output,snapshot_mode='freeze')
        original=storage.facts(output)
        assert not (work/'work.sqlite').exists()
        assert storage.historical(work)[0]['facts']==original
        # A clone must be a new inode and independent before any next-generation write.
        storage.prepare_work(work,mode='freeze')
        assert (work/'work.sqlite').stat().st_ino!=output.stat().st_ino
        assert storage.facts(output)==original
        replacement=tmp_path/'replacement';shutil.copytree(root,replacement)
        (replacement/'search_index.sqlite').unlink()
        payload=b'Changed generation orchid evidence';body=sha256(payload).digest()
        routes[f'/bodies/sha256/{body.hex()[:2]}/{body.hex()}']=payload
        def changes(rows):
            rows[0].update(saved_body=body,saved_bytes=len(payload));rows.pop()
        replace_rows(replacement,'detail',changes)
        replace_rows(replacement,'list',lambda rows:(rows[0].update(format='text'),rows.pop()))
        import pyarrow.compute as pc
        links=pq.read_table(replacement/'links.parquet')
        pq.write_table(links.filter(pc.less(links['list_row'],6)),replacement/'links.parquet')
        next_selection=prepare(tmp_path/'next',manifest(replacement),archive_origin=origin)
        count=len(requests)
        second=build(next_selection,work,replacement/'search_index.sqlite',snapshot_mode='freeze')
        assert second['reference_changes']['changed']==1 and second['reference_changes']['retired']==1
        assert len(requests)==count+1 and storage.facts(output)==original
        with connect(replacement/'search_index.sqlite',readonly=True) as db:
            assert not db.execute("SELECT 1 FROM bodies WHERE json_extract(target,'$.saved_body')=?",[bodies[0].hex()]).fetchone()
            assert not db.execute('SELECT 1 FROM sources WHERE seen<>?',[second['source_data_id']]).fetchone()
        # The earlier immutable owner supplies expensive readings when references return.
        count=len(requests)
        reappeared=build(selected,work,tmp_path/'reappeared.sqlite',snapshot_mode='freeze')
        assert reappeared['restored_historical_bodies']==2 and len(requests)==count
        assert storage.facts(output)==original
        assert build(selected,work,tmp_path/'reappeared.sqlite',snapshot_mode='freeze')['reused_snapshot']


def test_freeze_recovers_both_rename_and_link_interruption(tmp_path,monkeypatch):
    import congressional_explorer_mcp.index_storage as storage
    report=dict(source_data_id='a'*64,definition={'sha256':'d'*64})
    work=tmp_path/'durable';work.mkdir();(work/'work.sqlite').write_bytes(b'closed verified SQLite bytes')
    output=tmp_path/'accepted.sqlite'
    recover=storage.recover
    monkeypatch.setattr(storage,'recover',lambda work:(_ for _ in ()).throw(RuntimeError('before rename')))
    with pytest.raises(RuntimeError,match='before rename'):storage.freeze(work,output,report)
    assert (work/'freeze-intent.json').exists() and (work/'work.sqlite').exists()
    monkeypatch.setattr(storage,'recover',recover)
    link=storage.os.link
    monkeypatch.setattr(storage.os,'link',lambda *args:(_ for _ in ()).throw(RuntimeError('before link')))
    with pytest.raises(RuntimeError,match='before link'):recover(work)
    assert not (work/'work.sqlite').exists() and (work/'freeze-intent.json').exists()
    monkeypatch.setattr(storage.os,'link',link);recover(work)
    assert output.read_bytes()==b'closed verified SQLite bytes'
    assert not (work/'freeze-intent.json').exists()
    storage.prepare_work(work,mode='freeze')
    (work/'work.sqlite').write_bytes(b'new generation')
    assert output.read_bytes()==b'closed verified SQLite bytes'
    (work/'work.sqlite').unlink()
    accepted=Path(storage.historical(work)[0]['path']);accepted.chmod(0o600);accepted.write_bytes(b'changed custody')
    with pytest.raises(ExplorerError,match='custody changed'):storage.prepare_work(work,mode='freeze')


def test_unsupported_cow_refuses_before_existing_snapshot_mutation(tmp_path,monkeypatch):
    import congressional_explorer_mcp.index_storage as storage
    monkeypatch.setattr(storage,'_qualified_devices',set())
    def unsupported(*args):raise OSError('unsupported clone')
    monkeypatch.setattr(storage,'_native_clone',unsupported)
    with pytest.raises(ExplorerError,match='unavailable'):storage.preflight(tmp_path)
    assert not (tmp_path/'work.sqlite').exists()


def test_pdf_only_runtime_drift_preserves_markup_readings(tmp_path,monkeypatch):
    from congressional_explorer_mcp import large_body_reader
    before=extraction_definition()
    pdf=deepcopy(large_body_reader.large_pdf_definition())
    pdf['sha256']='1'*64
    for tool in pdf['facts']['tools'].values():
        if tool.get('available'):
            tool.update(executable='/another/qualified/platform/tool',sha256='2'*64)
    monkeypatch.setattr(large_body_reader,'large_pdf_definition',lambda:pdf)
    after=extraction_definition()
    assert before['body_definitions']['html']==after['body_definitions']['html']
    assert before['body_definitions']['xml']==after['body_definitions']['xml']
    assert before['body_definitions']['pdf']!=after['body_definitions']['pdf']
    assert before['sha256']!=after['sha256'] and before['policy_sha256']==after['policy_sha256']


def test_hard_killed_pdf_scratch_is_parent_owned(tmp_path,monkeypatch):
    import congressional_explorer_mcp.index_builder as builder
    frozen=extraction_definition()
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        work=tmp_path/'work';scratch=work/'active-pdf'
        child=builder._run_child
        def killed(command,**kwargs):
            script='from pathlib import Path; import time; p=Path('+repr(str(scratch))+'); p.mkdir(); (p/"source.pdf.partial").write_bytes(b"disposable"); time.sleep(30)'
            return child([sys.executable,'-c',script],timeout=.3,memory_mb=768)
        monkeypatch.setattr(builder,'extraction_definition',lambda:frozen)
        monkeypatch.setattr(builder,'_run_child',killed)
        link=pq.read_table(root/'detail.parquet')['link_key'][0].as_py().hex()
        with pytest.raises(ExplorerError,match='still refused'):
            build(selected,work,only_sources=['document:'+link])
        assert not scratch.exists()
        with connect(work/'work.sqlite') as db:
            assert db.execute("SELECT count(*) FROM bodies WHERE state='refused'").fetchone()[0]==1
        assert not requests


def test_normal_indexed_windows_cross_fragments_pages_and_resolve(tmp_path):
    from congressional_explorer_mcp.reader import Reader
    from contextlib import closing
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        text='first '+('orchid text '*8000)+' final'
        payload=('<html><body><p>'+text+'</p></body></html>').encode()
        body=sha256(payload).digest();routes[f'/bodies/sha256/{body.hex()[:2]}/{body.hex()}']=payload
        replace_rows(root,'detail',lambda rows:rows[1].update(saved_body=body,saved_bytes=len(payload)))
        selected=prepare(tmp_path/'new-selected',manifest(root),archive_origin=origin)
        report=build(selected,tmp_path/'work',root/'search_index.sqlite')
        selected=attach(root,selected,root/'search_index.sqlite',report,tmp_path/'indexed')
        with closing(Reader(selected)) as reader:
            links=pq.read_table(root/'detail.parquet')['link_key']
            count=len(requests)
            chunk=reader.indexed_document_text(dict(release_id=selected['release_id'],link_key=links[1].as_py().hex(),section='text',page=1,offset=63000,max_chars=8000))
            assert len(chunk['text'])==8000 and chunk['raw_bytes_fetched']==0
            assert reader.resolve_index_citation({'citation':chunk['citation']})['text']==chunk['text']
            cross=reader.indexed_document_text(dict(release_id=selected['release_id'],link_key=links[0].as_py().hex(),section='text',offset=20,max_chars=40))
            assert '\n\n' in cross['text'] and cross['citation']['location']['page'] is None
            assert reader.resolve_index_citation({'citation':cross['citation']})['text']==cross['text']
            assert len(requests)==count
        bad=deepcopy(selected);bad['manifest']['text_index']['definition']='0'*64
        with pytest.raises(ExplorerError,match='completion evidence'):
            TextIndex(bad).search(TextSearch(text='orchid'))


def test_html_aliases_share_the_qualified_markup_definition():
    from congressional_explorer_mcp.index_builder import _key
    definition=extraction_definition()['body_definitions']
    target=dict(saved_body='a'*64,saved_suffix='',format='html')
    keys=[_key(dict(target,format=fmt),definition,'document') for fmt in ('html','htm','xhtml')]
    changed=dict(definition,html='b'*64)
    assert all(_key(dict(target,format=fmt),changed,'document')!=key for fmt,key in zip(('html','htm','xhtml'),keys))


def test_retained_caption_page_preserves_cues_cursor_and_zero_raw_reads(tmp_path):
    from congressional_explorer_mcp.reader import Reader
    from congressional_explorer_mcp.hearing_models import TranscriptQuery
    from congressional_explorer_mcp.citations import caption_source_id
    from contextlib import closing
    routes={}
    with local_archive_server(routes) as (origin,requests):
        root,selected,_=source_fixture(tmp_path,origin,routes)
        payload=b'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\nfirst\n00:00:01.000 --> 00:00:02.000 align:start\nOne retained cue\n\nsecond\n00:00:03.000 --> 00:00:04.000\nTwo retained cues\n'
        body=sha256(payload).digest();routes[f'/bodies/sha256/{body.hex()[:2]}/{body.hex()}']=payload
        table=pq.read_table(root/'recordings.parquet');values=table.to_pylist();values[0]['tracks'][0]['body']=body
        pq.write_table(pa.Table.from_pylist(values,schema=table.schema),root/'recordings.parquet')
        selected=prepare(tmp_path/'new-selected',manifest(root),archive_origin=origin)
        report=build(selected,tmp_path/'work',root/'search_index.sqlite')
        selected=attach(root,selected,root/'search_index.sqlite',report,tmp_path/'indexed')
        identity=caption_source_id('youtube:search',body.hex(),'en','publisher')
        reference=dict(release_id=selected['release_id'],event_id=118001,kind='captions',source_id=identity)
        target=dict(release_id=selected['release_id'],reference=reference,saved_body=body.hex(),format='vtt',video_key='youtube:search')
        count=len(requests)
        with closing(Reader(selected)) as reader:
            query=TranscriptQuery(event_id=118001,kind='captions',source_id=identity,limit=1)
            first=reader.indexed_caption_text(dict(source=target,query=query.model_dump()))
            assert first['rows'][0]['identifier']=='first' and first['rows'][0]['settings']=='align:start'
            assert first['rows'][0]['mpeg_start_seconds']==11 and first['has_more']
            next_query=query.model_copy(update=dict(cursor=first['next_cursor']))
            second=reader.indexed_caption_text(dict(source=target,query=next_query.model_dump()))
            assert second['rows'][0]['cue_index']==1 and not second['has_more']
            assert reader.resolve_index_citation({'citation':second['rows'][0]['citation']})['text']=='Two retained cues'
            context_target=dict(target,reference=dict(reference,event_id=118999),association_scope='package_context',provenance=dict(scope='package_context'))
            context_query=query.model_copy(update=dict(event_id=118999,limit=2))
            context_page=reader.indexed_caption_text(dict(source=context_target,query=context_query.model_dump()))
            assert context_page['source']['association_scope']=='package_context' and context_page['rows'][0]['citation']['source']['event_id']==118999
            citation=context_page['rows'][0]['citation']
            assert reader.resolve_index_citation({'citation':citation})['state']=='not_indexed'
            assert reader.resolve_index_citation({'citation':citation,'source':context_target})['state']=='resolved'
            assert not TextIndex(selected).search(TextSearch(text='retained',source_kind='caption',date_from='2300-01-01'))['rows']
        assert len(requests)==count
