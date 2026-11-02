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
from native_test_helpers import compatible_entry


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
    payload=json.dumps(dict(path=str(source),body_sha=hashlib.sha256(body).hexdigest(),cache=str(tmp_path/'bytes'),stored_bytes=len(stored),
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
    pq.write_table(pa.Table.from_pylist([dict(body_sha=digest,physical_key=key,relative_path=key,stored_bytes=len(body))],
        schema=pa.schema([('body_sha',pa.binary(32)),('physical_key',pa.string()),('relative_path',pa.string()),('stored_bytes',pa.int64())])),inventory)
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
    items=[dict(body_sha=digest,physical_key=key,relative_path=key,stored_bytes=len(body))] if available else []
    pq.write_table(pa.Table.from_pylist(items,schema=pa.schema([('body_sha',pa.binary(32)),('physical_key',pa.string()),
        ('relative_path',pa.string()),('stored_bytes',pa.int64())])),inventory)
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


def fixture_registry(path, entries):
    path.write_text(json.dumps(dict(version=2, entries=entries)))
    return path


def test_combined_plan_settles_bodies_on_registry_covered_older_rows(tmp_path):
    # Defect guarded: a plan that still joins existing rows on e.parser_version=<current pin>
    # re-reads every body whose rows sit at a covered older pin.
    from congress_api.retention.provenance import run_job, parquet_output
    args, _, _ = _review_inputs(tmp_path)
    staged = readings.stage_once(**args, work=tmp_path / 'first')
    versions = {p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}
    old = tmp_path / 'old'
    run_job(old, args['engine'], inputs=[dict(name='r', kind='parquet', path=str(staged['readings']))], steps=[],
        queries=[], outputs=[parquet_output(old, 'readings', "SELECT * EXCLUDE(parser_version),concat(parser,'-old') AS parser_version FROM r", readings.PK)])
    relabelled = old / 'readings.parquet'
    assert {r['parser_version'] for r in pq.read_table(relabelled).to_pylist()} == {'sniff-old', 'html-old'}
    covered = fixture_registry(tmp_path / 'covered.json', [compatible_entry(p, p + '-old', versions[p]) for p in versions])
    empty = fixture_registry(tmp_path / 'empty.json', [])
    assert readings.plan(**args, parser=None, existing=relabelled, registry=covered, work=tmp_path / 'with')['work_items'] == 0
    assert readings.plan(**args, parser=None, existing=relabelled, registry=empty, work=tmp_path / 'without')['work_items'] == 1


def _bodies_inputs(tmp_path, bodies, *, gzip_stored=False):
    """Local inventory and captures for these bodies under suffixless keys, stored plain or gzip
    (as R2 stores Content-Encoding: gzip objects). The inventory names no encoding."""
    raw = tmp_path / 'raw'
    rows, items = [], []
    for body in bodies:
        digest = hashlib.sha256(body).digest(); key = 'bodies/sha256/' + digest.hex()[:2] + '/' + digest.hex()
        stored = gzip.compress(body, mtime=0) if gzip_stored else body
        (raw / key).parent.mkdir(parents=True, exist_ok=True); (raw / key).write_bytes(stored)
        rows.append(dict(sha256=digest, bytes=len(body), media_type='application/json', fidelity='exact-bytes'))
        items.append(dict(body_sha=digest, physical_key=key, relative_path=key, stored_bytes=len(stored)))
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('sha256', pa.binary(32)), ('bytes', pa.int64()), ('media_type', pa.string()),
        ('fidelity', pa.string()), ('sniffed_format', pa.string()), ('sniff_version', pa.string()), ('intact', pa.bool_())])), captures)
    inventory = tmp_path / 'inventory.parquet'
    pq.write_table(pa.Table.from_pylist(items, schema=pa.schema([('body_sha', pa.binary(32)), ('physical_key', pa.string()),
        ('relative_path', pa.string()), ('stored_bytes', pa.int64())])), inventory)
    return dict(captures=captures, body_inventory=inventory, local_root=raw, decided_at='2026-11-02T00:00:00Z',
        engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))


def _outcome(staged):
    rows = sorted(json.dumps(row, default=str, sort_keys=True) for row in pq.read_table(staged['readings']).to_pylist())
    decisions = Path(staged['work_list']).parent / 'parsed/unreadable.jsonl'
    reasons = sorted((d['body_sha256'], d['reason']) for d in map(json.loads, decisions.read_text().splitlines())) if decisions.exists() else []
    return rows, reasons


def test_large_page_bodies_get_the_same_reading_on_every_re_read(tmp_path):
    # ct-61ys: an outcome decided by sampled RSS flipped between memory_limit and completed.
    # The largest body that may parse and one just over the bound, each re-read three times.
    near = json.dumps([dict(id=i, title='Hearing record ' + str(i), url=f'https://example.test/{i}.pdf') for i in range(15000)]).encode()
    over = b'[' + b' ' * readings.PAGE_PARSE_MAX_BYTES + b'0]'
    args = _bodies_inputs(tmp_path, [near, over])
    outcomes = [_outcome(readings.stage_once(**args, work=tmp_path / f'run{i}')) for i in range(3)]
    assert outcomes[0] == outcomes[1] == outcomes[2]
    rows, reasons = outcomes[0]
    assert reasons == [(hashlib.sha256(over).hexdigest(), 'memory_limit')]
    assert any('"parser": "json"' in row and '"status": "completed"' in row for row in rows)


def test_a_suffixless_gzip_stored_json_body_is_sniffed_and_read_by_its_hash(tmp_path):
    # Owner decision: 187 json and 24 bundle bodies are gzip objects under suffixless keys. A
    # suffix (or inventory flag) rule sniffed them as 'other' and left json unread.
    body = json.dumps(dict(title='Hearing', url='https://example.test/a.pdf')).encode()
    staged = readings.stage_once(**_bodies_inputs(tmp_path, [body], gzip_stored=True), work=tmp_path / 'stage')
    rows = {row['parser']: row for row in pq.read_table(staged['readings']).to_pylist()}
    assert rows['sniff']['format'] == 'json' and rows['json']['status'] == 'completed'


def test_the_single_parser_reader_uses_the_same_hash_rule(tmp_path):
    body = json.dumps(dict(title='Hearing')).encode()
    args = _bodies_inputs(tmp_path, [body], gzip_stored=True)
    staged = readings.stage(**args, work=tmp_path / 'sniff', parser='sniff')
    assert [row['format'] for row in pq.read_table(staged['readings']).to_pylist()] == ['json']


def test_bytes_that_hash_to_neither_form_are_a_mismatch():
    import io
    body = b'{"a": 1}'
    with pytest.raises(OSError, match='decoded_sha_mismatch'):
        readings._storage_gzip(io.BytesIO(gzip.compress(b'other', mtime=0)), hashlib.sha256(body).hexdigest(),
                               raw_io=__import__('contextlib').nullcontext)
    # A literal gzip body (a .gz download) stored plain is plain storage: its own bytes hash to it.
    literal = gzip.compress(body, mtime=0)
    assert readings._storage_gzip(io.BytesIO(literal), hashlib.sha256(literal).hexdigest(),
                                  raw_io=__import__('contextlib').nullcontext) is False


def test_registry_selection_runs_with_no_existing_readings(tmp_path, monkeypatch):
    # A first run has no readings table. The empty stand-in must have the lake columns, since
    # a recompute set reads them (html's re-read set reads `fingerprint`). Defect guarded: a
    # hand-built empty relation with `fingerprint_hex` failed "No field named fingerprint".
    import congress_api.parsers.archive_readings as reader
    monkeypatch.setattr(reader, 'HTML_REREAD_SQL', 'SELECT body_sha FROM {readings} WHERE fingerprint IS NULL', raising=False)
    entry = compatible_entry('html', 'html-old', readings.current_version('html'))
    registry = fixture_registry(tmp_path / 'registry.json', [entry])
    args, _, _ = _review_inputs(tmp_path)
    assert readings.plan(**args, parser=None, existing=None, registry=registry, work=tmp_path / 'plan')['work_items'] == 1


def test_a_capture_with_no_stored_size_is_read_locally_and_verified_by_hash(tmp_path):
    # Assembly receipts record a copy (stored_suffix '.gz') but no stored_bytes. Defect guarded:
    # the captured-copies inventory dropped them, so they stayed pending forever (spec-run D2).
    raw = tmp_path / 'raw'
    good = json.dumps(dict(title='Hearing record')).encode()
    wrong = json.dumps(dict(title='Expected body')).encode()
    rows = []
    for body, stored in ((good, gzip.compress(good, mtime=0)), (wrong, b'{"title":"different bytes"}')):
        digest = hashlib.sha256(body).digest(); key = 'bodies/sha256/' + digest.hex()[:2] + '/' + digest.hex() + '.gz'
        (raw / key).parent.mkdir(parents=True, exist_ok=True); (raw / key).write_bytes(stored)
        rows.append(dict(sha256=digest, bytes=len(body), media_type='application/json', fidelity='exact-bytes',
                         stored_suffix='.gz', stored_bytes=None, stored_md5=None))
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('sha256', pa.binary(32)), ('bytes', pa.int64()),
        ('media_type', pa.string()), ('fidelity', pa.string()), ('stored_suffix', pa.string()), ('stored_bytes', pa.int64()),
        ('stored_md5', pa.binary(16)), ('sniffed_format', pa.string()), ('sniff_version', pa.string()), ('intact', pa.bool_())])), captures)
    staged = readings.stage_once(captures=captures, body_inventory=None, captured_copies=True, local_root=raw,
        work=tmp_path / 'stage', decided_at='2026-11-02T00:00:00Z', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    read = {(row['body_sha'].hex(), row['parser'], row['status']) for row in pq.read_table(staged['readings']).to_pylist()}
    assert read == {(hashlib.sha256(good).hexdigest(), 'sniff', 'completed'), (hashlib.sha256(good).hexdigest(), 'json', 'completed')}
    # The file that does not hash to its body is not read, and stays pending.
    assert staged['pending_reads'] == 1
