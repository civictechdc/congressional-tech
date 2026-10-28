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
    schema=pa.schema([('sha256',pa.binary(32)),('bytes',pa.int64()),('media_type',pa.string()),('fidelity',pa.string())])
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
