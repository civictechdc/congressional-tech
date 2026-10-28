"""One body read supplies byte format and page evidence, including wrong MIME hints."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings
from congress_api.retention.parser_worker import ParserWorker
from docspec_client.client import NativeDatasets


@pytest.mark.parametrize('body,stored_gzip,expected',[
    (b'<html><body><p>'+b'Evidence '*2000+b'</p><a href="report.pdf">PDF</a></body></html>',False,'html'),
    (b'<html><body>'+b'Evidence '*2000+b'</body></html>',True,'html'),
    (b'{"title":"A report","url":"https://fixture.test/file.pdf","padding":"'+b'x'*12000+b'"}',False,'json'),
    (b'<?xml version="1.0"?><record><title>'+b'Evidence '*2000+b'</title></record>',False,'xml'),
],ids=['html','gzip-html','json','xml'])
@pytest.mark.parametrize('retry',[False,True])
def test_one_source_open_emits_sniff_and_actual_page_reading(tmp_path,body,stored_gzip,expected,retry):
    stored=gzip.compress(body,mtime=0) if stored_gzip else body
    source=tmp_path/'source';source.write_bytes(stored)
    wrapper=tmp_path/'observe.py'
    wrapper.write_text('''import json,sys
from congress_api.lake.readings import parse_once_payload
from pathlib import Path
def run(payload):
    source=json.loads(payload)['path'];log=Path(source+'.opens')
    def observe(event,args):
        if event=='open' and str(args[0])==source:
            with log.open('a') as stream:stream.write('open\\n')
    sys.addaudithook(observe)
    result=parse_once_payload(payload)
    marker=Path(__file__).with_suffix('.retry')
    if marker.exists():
        marker.unlink();raise RuntimeError('fixture parser crash after source read')
    result['observed_source_opens']=len(log.read_text().splitlines())
    return result
''')
    if retry:wrapper.with_suffix('.retry').touch()
    versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']}
    payload=json.dumps(dict(path=str(source),cache=str(tmp_path/'bytes'),stored_bytes=len(stored),stored_gzip=stored_gzip,
        versions=versions,known_format=None,skip_parsers=[])).encode()
    with ParserWorker('readings','fixture',str(wrapper)+':run',timeout_seconds=15,memory_bytes=512<<20,max_input_bytes=65536) as worker:
        outcome=worker.parse('body',payload)
    assert outcome['status']=='completed'
    result=outcome['value']
    assert result['observed_source_opens']==1 and result['read_bytes']==len(stored)
    assert [(row['parser'],row['status']) for row in result['rows']]==[('sniff','completed'),(expected,'completed')]
    assert result['rows'][0]['format']==expected
    assert all(row['parser_version']==versions[row['parser']] for row in result['rows'])


def test_native_once_worklist_reuses_writer_facts_and_parses_duplicate_body_once(tmp_path):
    from congress_api.lake.readings import stage_once
    raw=tmp_path/'raw';raw.mkdir()
    body=b'<html><body><p>Retained evidence</p><a href="a.pdf">PDF</a></body></html>'
    digest=hashlib.sha256(body).digest();key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    path=raw/key;path.parent.mkdir(parents=True);path.write_bytes(body)
    caption=bytes.fromhex('e'*64)
    captures=tmp_path/'captures.parquet'
    schema=pa.schema([('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),('fidelity',pa.string()),('sniffed_format',pa.string()),('sniff_version',pa.string()),('intact',pa.bool_())])
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest,bytes=len(body),media_type='application/pdf',fidelity='exact-bytes')]*2+
        [dict(sha256=caption,bytes=100,media_type='text/vtt',fidelity='saved-text')],schema=schema),captures)
    inventory=tmp_path/'inventory.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,relative_path=key,stored_bytes=len(body),stored_gzip=False)],
        schema=pa.schema([('body_sha',pa.binary(32)),('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64()),('stored_gzip',pa.bool_())])),inventory)
    result=stage_once(captures=captures,body_inventory=inventory,local_root=raw,work=tmp_path/'stage',
        decided_at='2026-10-27T12:00:00Z',engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    assert pq.ParquetFile(result['work_list']).metadata.num_rows==1
    rows=pq.read_table(result['readings']).to_pylist()
    assert len(rows)==2 and {r['parser'] for r in rows}=={'html','sniff'}
    assert next(r for r in rows if r['parser']=='sniff')['format']=='html'
    admitted=pq.read_table(result['body_admissions']).to_pylist()
    assert admitted==[dict(body_sha=caption,format='vtt',basis='writer_format')]
    assert result['read_bytes']==len(body) and result['pending_reads']==0
    assert not any((tmp_path/'stage/body-bytes').iterdir())


def _review_inputs(tmp_path,*,available=True,metadata=None):
    body=b'<html><body><p>'+b'Evidence '*2000+b'</p></body></html>'
    digest=hashlib.sha256(body).digest();key='bodies/sha256/'+digest.hex()[:2]+'/'+digest.hex()
    raw=tmp_path/'raw';raw.mkdir()
    source=raw/key
    if available:source.parent.mkdir(parents=True);source.write_bytes(body)
    captures=tmp_path/'captures.parquet'
    schema=pa.schema([('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),('fidelity',pa.string()),
        ('sniffed_format',pa.string()),('sniff_version',pa.string()),('intact',pa.bool_())])
    values=metadata or [dict(bytes=len(body),media_type='text/html',fidelity='exact-bytes')]
    pq.write_table(pa.Table.from_pylist([dict(sha256=digest,**row) for row in values],schema=schema),captures)
    inventory=tmp_path/'inventory.parquet'
    items=[dict(body_sha=digest,physical_key=key,relative_path=key,stored_bytes=len(body),stored_gzip=False)] if available else []
    pq.write_table(pa.Table.from_pylist(items,schema=pa.schema([('body_sha',pa.binary(32)),('physical_key',pa.string()),
        ('relative_path',pa.string()),('stored_bytes',pa.int64()),('stored_gzip',pa.bool_())])),inventory)
    return dict(captures=captures,body_inventory=inventory,local_root=raw,
        decided_at='2026-10-27T12:00:00Z',engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])),source,len(body)


@pytest.mark.parametrize(('outcome','durable'),[('crash',False),('crash',True),('read_exit',False),('response_error',False)])
def test_combined_stage_cleans_actual_cached_bytes_after_final_failure(tmp_path,outcome,durable):
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    args,source,stored_size=_review_inputs(tmp_path)
    wrapper=tmp_path/'terminal.py'
    wrapper.write_text('''import json,os,sys
from pathlib import Path
from congress_api.lake.readings import parse_once_payload
from congress_api.retention.parser_worker import reading_input
def run(payload,mode):
    request=json.loads(payload);source=request['path'];log=Path(source+'.opens')
    def observe(event,args):
        if event=='open' and str(args[0])==source:
            with log.open('a') as stream:stream.write('open\\n')
    sys.addaudithook(observe)
    result=parse_once_payload(payload)
    size=sum(path.stat().st_size for path in Path(request['cache']).glob('*.bin'))
    with Path(source+'.cached').open('a') as stream:stream.write(str(size)+'\\n')
    if mode=='crash':raise RuntimeError('fixture crash after filling the cache')
    if mode=='read_exit':
        with reading_input():os._exit(12)
    return dict(result,read_error='fixture_pending',rows=[])
def crash(payload):return run(payload,'crash')
def read_exit(payload):return run(payload,'read_exit')
def response_error(payload):return run(payload,'response_error')
''')
    def worker(parser,version,callable_path,**bounds):
        return ParserWorker(parser,version,str(wrapper)+':'+outcome,**bounds)
    raw=tmp_path/'durable'
    extra=dict(unreadable_store=BodyStore(LocalAdapter(raw))) if durable else {}
    result=readings.stage_once(**args,work=tmp_path/'stage',worker_factory=worker,**extra)
    cache=tmp_path/'stage/body-bytes'
    assert cache.exists() and list(cache.iterdir())==[]
    cached=[int(value) for value in Path(str(source)+'.cached').read_text().splitlines()]
    assert cached==[stored_size]*(2 if outcome=='crash' else 1)
    assert Path(str(source)+'.opens').read_text().splitlines()==['open']
    assert pq.ParquetFile(result['readings']).metadata.num_rows==0
    if outcome=='crash':
        assert result['unreadable']==1 and result['pending_reads']==0
        assert result['unreadable_pending'] is not durable
        path=raw/result['unreadable_key'] if durable else Path(result['unreadable_path'])
        record=json.loads(path.read_text())
        assert record['parser']=='readings' and record['parser_version']==result['parser_version']
        if not durable:
            with pytest.raises(ValueError,match='unreadable.*import'):
                readings.append(result,engine=object(),work=tmp_path/'append',catalog_root=tmp_path/'catalog',table={})
            assert not (tmp_path/'append').exists() and not (tmp_path/'catalog').exists()
    else:
        assert result['pending_reads']==1 and result['unreadable']==0
        assert result['unreadable_key'] is None


def test_combined_failure_version_covers_explicit_worker_policy_not_leaf_facts():
    versions={parser:readings.current_version(parser) for parser in ['sniff','html','xml','json']}
    policy=readings.worker_limits()
    baseline=readings.bundle_version(versions,policy=policy)
    for name in ['memory_bytes','timeout_seconds','max_input_bytes','max_output_bytes']:
        changed=dict(policy);changed[name]=policy[name]*2
        assert readings.bundle_version(versions,policy=changed)!=baseline
    assert {parser:readings.current_version(parser) for parser in versions}==versions
    assert readings.bundle_version(dict(reversed(list(versions.items()))),policy=policy)==baseline


def test_combined_stage_refuses_a_mixed_sniff_pin_before_creating_work(tmp_path):
    work=tmp_path/'must-not-exist'
    with pytest.raises(ValueError,match='sniff.*version|version.*sniff'):
        readings.stage_once(captures=tmp_path/'unused',body_inventory=tmp_path/'unused',local_root=tmp_path,
            work=work,decided_at='2026-10-27T12:00:00Z',engine=object(),sniff_version='old')
    assert not work.exists()


@pytest.mark.parametrize('proof',['fidelity','bytes'])
def test_writer_admission_requires_nonnull_proof_on_every_capture(tmp_path,proof):
    rows=([dict(bytes=100,media_type='text/vtt',fidelity='saved-text'),
           dict(bytes=100,media_type='text/vtt',fidelity=None)] if proof=='fidelity' else
          [dict(bytes=0,media_type='application/octet-stream',fidelity=None),
           dict(bytes=None,media_type='application/octet-stream',fidelity=None)])
    args,_,_=_review_inputs(tmp_path,available=False,metadata=rows)
    result=readings.stage_once(**args,work=tmp_path/'stage')
    assert pq.ParquetFile(result['body_admissions']).metadata.num_rows==0
    assert pq.ParquetFile(result['work_list']).metadata.num_rows==1
    assert pq.ParquetFile(result['readings']).metadata.num_rows==0
    assert result['pending_reads']==1 and result['unreadable']==0


def test_shared_writer_admission_step_requires_positive_uniform_evidence(tmp_path):
    from congress_api.retention.provenance import json_input,run_job
    def capture(body,**values):
        return dict(dict(body_hex=body*64,bytes=100,media_type='text/vtt',fidelity='saved-text'),**values)
    rows=[capture('a',bytes=0,media_type=None,fidelity=None),
        capture('b'),capture('c',media_type='application/vnd.apple.mpegurl'),
        capture('d',media_type='application/x-mpegurl'),
        capture('e'),capture('e',fidelity=None),
        capture('f',bytes=0,media_type='application/octet-stream',fidelity=None),
        capture('f',bytes=None,media_type='application/octet-stream',fidelity=None),
        capture('1'),capture('1',media_type='application/vnd.apple.mpegurl'),
        capture('2',fidelity='exact-bytes'),capture('3'),capture('3',media_type=None)]
    inputs=[json_input(tmp_path,'facts',rows,body_hex='Utf8',bytes='Int64',media_type='Utf8',fidelity='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='captures',sql="SELECT decode(body_hex,'hex') AS sha256,* EXCLUDE(body_hex) FROM facts"),
            readings.writer_admission_step()],outputs=[],queries=[dict(name='admitted',sql="SELECT encode(body_sha,'hex') AS body,format,basis FROM body_admissions ORDER BY body")])
    assert result['admitted']==[dict(body=body*64,format=format,basis='writer_format')
        for body,format in [('a','empty'),('b','vtt'),('c','m3u8'),('d','m3u8')]]


def test_writer_admission_cannot_override_a_current_byte_format(tmp_path):
    args,_,_=_review_inputs(tmp_path,available=False,metadata=[dict(bytes=100,media_type='text/vtt',
        fidelity='saved-text',sniffed_format='html',sniff_version=readings.current_version('sniff'))])
    work=tmp_path/'stage'
    with pytest.raises(ValueError,match='Conflicting.*metadata'):
        readings.stage_once(**args,work=work)
    assert not (work/'parsed').exists()
