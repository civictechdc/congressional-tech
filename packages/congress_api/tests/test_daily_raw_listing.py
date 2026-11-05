"""Daily reads R2 against an exact-key listing of its candidates, settled before captures move."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest
from botocore.exceptions import ClientError

from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter


STAMP='2026-10-28T12:00:00Z'
TABLES={name:dict(namespace=['archive'],name=name) for name in ['captures','readings','filename_readings']}


def error(code,status,operation):
    return ClientError({'Error':{'Code':code},'ResponseMetadata':{'HTTPStatusCode':status,'HTTPHeaders':{}}},operation)


class Bucket:
    """R2 over a local raw root: HEAD and conditional GET answer from the stored bytes."""
    def __init__(self,root):
        self.root=Path(root);self.absent=set();self.head_override={}
        self.heads=[];self.gets=[];self.puts=[]
        self.meta=SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}),
            events=SimpleNamespace(register_first=lambda *a,**k:None))
    def _data(self,key,operation):
        path=self.root/key
        if key in self.absent or not path.is_file():raise error('404' if operation=='HeadObject' else 'NoSuchKey',404,operation)
        return path.read_bytes()
    def head_object(self,*,Bucket,Key):
        self.heads.append(Key);data=self._data(Key,'HeadObject')
        return dict(dict(ContentLength=len(data),ETag='"'+hashlib.md5(data).hexdigest()+'"'),**self.head_override.get(Key,{}))
    def get_object(self,*,Bucket,Key,IfMatch=None,Range=None):
        self.gets.append(dict(Key=Key,IfMatch=IfMatch,Range=Range));data=self._data(Key,'GetObject')
        md5=hashlib.md5(data).hexdigest()
        if IfMatch is not None and IfMatch.strip('"').lower()!=md5:raise error('PreconditionFailed',412,'GetObject')
        encoding='gzip' if not Key.endswith(('.gz','.pdf')) and data[:2]==b'\x1f\x8b' else None
        if Range is None:
            return dict(Body=io.BytesIO(data),ContentLength=len(data),ETag='"'+md5+'"',ContentEncoding=encoding,
                ResponseMetadata={'HTTPStatusCode':200})
        start,end=map(int,Range[6:].split('-'));end=min(end,len(data)-1);piece=data[start:end+1]
        return dict(Body=io.BytesIO(piece),ContentLength=len(piece),ContentRange=f'bytes {start}-{end}/{len(data)}',
            ETag='"'+md5+'"',ContentEncoding=encoding,ResponseMetadata={'HTTPStatusCode':206})
    def put_object(self,**kwargs):
        self.puts.append(kwargs['Key']);path=self.root/kwargs['Key']
        if kwargs.get('IfNoneMatch')=='*' and path.exists():raise error('PreconditionFailed',412,'PutObject')
        source=kwargs['Body'];data=source if isinstance(source,bytes) else source.read()
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return dict(ETag='"'+hashlib.md5(data).hexdigest()+'"')


def body_key(data):
    digest=hashlib.sha256(data).hexdigest()
    return 'bodies/sha256/'+digest[:2]+'/'+digest


def payload(n):
    return json.dumps(dict(title='Listed input '+str(n),url='https://docs.house.gov/listed'+str(n)+'.json')).encode()


def fixture(tmp_path,payloads,*,unpinned=()):
    """Receipts and bodies written by the maintained writer into a local root that a fake R2 serves.

    Model historical `unpinned` receipts by omitting both stored-byte fields.
    """
    from capture_qualification_helpers import write_qualified_bytes
    from congress_api.models.raw_fetch import BodyFile,FetchAttempt,FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from congress_api.lake import filenames,readings,tables
    from docspec_client.client import NativeDatasets
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    root=tmp_path/'raw';qualifications={}
    class QualifiedAdapter(LocalAdapter):
        def create(self,key,source,**kwargs):
            if key.startswith('receipts/'):
                qualifications[key]=write_qualified_bytes(root/key,source.read());return True
            return super().create(key,source,**kwargs)
    writer=ReceiptWriter(BodyStore(QualifiedAdapter(root)),identity=dict(job='capture',commit='a'*40,lockfile_digest='b'*64),
        run_id='daily',write_date='2026-10-28',archive_limits=None)
    receipts=[]
    for i,data in enumerate(payloads):
        entity=tmp_path/('body'+str(i));entity.write_bytes(data)
        if i in unpinned:BodyStore(LocalAdapter(root)).put(body_key(data),entity,'application/json')
        body=BodyFile(entity,hashlib.sha256(data).hexdigest(),len(data),'application/json',None,None,None)
        url='https://docs.house.gov/listed'+str(i)+'.json'
        key,line=writer.write(FetchResult(FetchAttempt(url,url,STAMP,'direct',200,None,{},(),True,body)),family='documents')
        if i in unpinned:
            assert line['outcome']=='unchanged'
            capture=line['captures'][0]
            del capture['stored_md5'],capture['stored_bytes']
            historical=gzip.compress((json.dumps(line)+'\n').encode(),mtime=0)
            qualifications[key]=write_qualified_bytes(root/key,historical)
        receipts.append(dict(key=key,path=str(root/key),qualification=qualifications[key]))
    assert [r['key'] for r in receipts]==sorted(r['key'] for r in receipts)
    value=dict(work=str(tmp_path/'work'),decided_at=STAMP,catalog_root=str(tmp_path/'catalog'),tables=TABLES,
        receipt_inventory=receipts,max_work_items=10,provenance={kind:[] for kind in ['recoveries','reviews','unreadable']})
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    tables.create_table(engine=engine,work=tmp_path/'create-captures',catalog_root=value['catalog_root'],
        table=TABLES['captures'],schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
    readings.create_table(engine=engine,work=tmp_path/'create-readings',catalog_root=value['catalog_root'],
        table=TABLES['readings'],location=tmp_path/'lake-readings')
    filenames.create_table(engine=engine,work=tmp_path/'create-filenames',catalog_root=value['catalog_root'],
        table=TABLES['filename_readings'],location=tmp_path/'lake-filenames')
    bucket=Bucket(root)
    return value,engine,bucket,BodyStore(R2Adapter(bucket,'bucket'))


def heads(value,engine,work):
    from congress_api.lake import tables
    return tables.resolve_tables(engine=engine,work=work,catalog_root=value['catalog_root'],tables=TABLES)


def append_unread(value,engine,receipts,work):
    """Captures appended by a run that stopped before readings (the 2026-11-04 14:45 head)."""
    from congress_api.lake import capture_staging,tables
    staged=capture_staging.stage_captures(receipts,engine=engine,work=work)
    manifest=json.loads((staged/'ingested-receipts.json').read_text())
    tables.append_rows(staged/'captures.parquet',engine=engine,work=work/'append',catalog_root=value['catalog_root'],
        table=TABLES['captures'],keys=['receipt_key'],definition=manifest['mapping_digest'])


def body_gets(bucket):
    return [get for get in bucket.gets if get['Key'].startswith('bodies/')]


@pytest.mark.parametrize('reuse', ['collision', 'legacy', 'reference', 'legacy-reference',
                                    'legacy-multipart', 'cache'])
def test_reused_body_metadata_survives_receipt_normalization(tmp_path, reuse):
    import base64
    from capture_qualification_helpers import write_qualified_bytes
    from congress_api.lake.capture_staging import stage_captures
    from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
    from congress_api.retention.receipt_writer import ReceiptWriter
    from docspec_client.client import NativeDatasets

    data = payload(0)
    url = 'https://docs.house.gov/listed0.json'
    entity = tmp_path/'body'
    entity.write_bytes(data)
    root = tmp_path/'raw'
    key = body_key(data)
    suffix = '.gz' if 'legacy' in reuse else ''
    physical_key = key + suffix
    physical_path = root/physical_key
    retained = 'reference' in reuse
    if reuse != 'cache':
        # Encode the same entity differently from the writer's attempted gzip.
        physical_path.parent.mkdir(parents=True)
        physical_path.write_bytes(gzip.compress(data, compresslevel=0, mtime=0))

    attempted = []

    class RecordingBucket(Bucket):
        def put_object(self, **kwargs):
            assert kwargs['IfNoneMatch'] == '*'
            if kwargs['Key'] == physical_key:
                attempted.append((kwargs['ContentLength'], base64.b64decode(kwargs['ContentMD5'])))
            return super().put_object(**kwargs)

    bucket = RecordingBucket(root)
    if reuse == 'legacy-multipart':
        bucket.head_override[physical_key] = dict(ETag='"'+'a'*32+'-2"')
    writer = ReceiptWriter(BodyStore(R2Adapter(bucket, 'bucket')),
        identity=dict(job='capture',commit='a'*40,lockfile_digest='b'*64),
        run_id='reuse',write_date='2026-10-28',archive_limits=None)
    body = BodyFile(None if retained else entity, hashlib.sha256(data).hexdigest(), len(data),
                    'application/json', 'json', 'v1', True, stored_suffix=suffix)
    result = FetchResult(FetchAttempt(url,url,STAMP,'direct',200,None,{},(),True,body))
    options = dict(mode='retained_import', recovery_evidence=dict(original_url=url)) if retained else {}
    if reuse == 'cache':
        writer.write(result, family='documents')
        bucket.heads.clear()
        bucket.puts.clear()
        attempted.clear()
        entity.unlink()
    stored = physical_path.read_bytes()
    md5 = hashlib.md5(stored)
    receipt_key, line = writer.write(result, family='documents', **options)
    assert line['outcome'] == 'unchanged'
    if reuse == 'legacy-multipart':
        assert 'stored_md5' not in line['captures'][0]
    else:
        assert line['captures'][0]['stored_md5'] == md5.hexdigest()
    assert line['captures'][0]['stored_bytes'] == len(stored)
    assert physical_path.read_bytes() == stored and not bucket.gets
    if reuse == 'collision':
        assert bucket.heads == [key+'.gz', key]
        assert bucket.puts == [key, receipt_key]
        [(attempted_size, attempted_md5)] = attempted
        assert attempted_size != len(stored) and attempted_md5 != md5.digest()
    else:
        assert bucket.heads == ([] if reuse == 'cache' else [physical_key])
        assert bucket.puts == [receipt_key]

    path = root/receipt_key
    receipt = path.read_bytes()
    qualification = write_qualified_bytes(path, receipt)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        stage = stage_captures([dict(key=receipt_key,path=str(path),qualification=qualification)],
                               engine=engine, work=tmp_path/'stage')
    [row] = pq.read_table(stage/'captures.parquet').to_pylist()
    assert (row['outcome'], row['stored_suffix'], row['stored_bytes'], row['stored_md5']) == (
        'unchanged', suffix, len(stored), None if reuse == 'legacy-multipart' else md5.digest())


def test_unpinned_capture_is_read_through_its_listed_etag_and_listing_covers_only_candidates(tmp_path):
    from congress_api.lake.daily import produce_daily
    payloads=[payload(0),payload(1)]
    value,engine,bucket,store=fixture(tmp_path,payloads,unpinned={0})
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='completed'
    report=result['producerreports']['readings']
    assert report['work_items']==2 and report['read_bytes']>0
    assert report['raw_custody']['listing_etag']==1 and report['raw_custody']['capture_md5']==1
    keys=[body_key(p) for p in payloads]
    assert sorted(bucket.heads)==sorted(keys) and result['raw_listing']==dict(heads=2,absent=[])
    listing=pq.read_table(tmp_path/'work/raw-custody/body-listing.parquet').to_pylist()
    stored={key:(tmp_path/'raw'/key).read_bytes() for key in keys}
    assert listing==[dict(key=k,size=len(stored[k]),etag='"'+hashlib.md5(stored[k]).hexdigest()+'"') for k in sorted(keys)]
    conditions={get['Key']:get['IfMatch'] for get in body_gets(bucket)}
    assert conditions=={k:'"'+hashlib.md5(stored[k]).hexdigest()+'"' for k in keys}
    again=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert again['status']=='completed' and again['producerreports']['readings']['work_items']==0


def test_a_receipt_holding_several_candidate_captures_is_listed_and_read(tmp_path):
    # Production receipts carry many lines; the scoped captures export is ordered by the
    # captures key (receipt_key, receipt_line, capture_index), not by receipt alone.
    from capture_qualification_helpers import write_qualified_bytes
    from congress_api.lake.daily import produce_daily
    payloads=[payload(0),payload(1)]
    value,engine,bucket,store=fixture(tmp_path,payloads,unpinned={0})
    lines=b''.join(gzip.decompress(Path(r['path']).read_bytes()) for r in value['receipt_inventory'])
    key='receipts/documents/2026-10-28/daily-000099.jsonl.gz';path=tmp_path/'raw'/key
    qualification=write_qualified_bytes(path,gzip.compress(lines,mtime=0))
    value['receipt_inventory']=[dict(key=key,path=str(path),qualification=qualification)]
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='completed' and result['new_receipt_keys']==[key]
    assert result['raw_listing']==dict(heads=2,absent=[])
    assert result['producerreports']['readings']['work_items']==2
    scoped=pq.read_table(tmp_path/'work/raw-custody/scoped-captures.parquet',columns=['receipt_key','receipt_line']).to_pylist()
    assert sorted(r['receipt_line'] for r in scoped)==[1,2] and {r['receipt_key'] for r in scoped}=={key}


def test_capture_md5_is_the_read_condition_where_a_capture_recorded_one(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,bucket,store=fixture(tmp_path,[payload(0)])
    key=body_key(payload(0));md5=hashlib.md5((tmp_path/'raw'/key).read_bytes()).hexdigest()
    # The same MD5 in another spelling: no conflict, yet a different conditional string.
    bucket.head_override[key]=dict(ETag='"'+md5.upper()+'"')
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='completed'
    assert result['producerreports']['readings']['raw_custody']['capture_md5']==1
    assert [get['IfMatch'] for get in body_gets(bucket)]==['"'+md5+'"']


def test_planted_wrong_etag_for_a_pinned_body_refuses_before_captures_move(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,bucket,store=fixture(tmp_path,[payload(0)])
    bucket.head_override[body_key(payload(0))]=dict(ETag='"'+'0'*32+'"')
    before=heads(value,engine,tmp_path/'before')
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='raw_custody_required' and result['pins'] is None
    custody=result['producerreports']['readings']
    assert custody['status']=='missing_raw_custody' and custody['md5_conflicts']==1 and custody['conflicts']==1
    assert result['new_receipt_keys']==[] and result['producerreports']['captures']['append'] is None
    assert heads(value,engine,tmp_path/'after')==before and body_gets(bucket)==[]
    assert not (tmp_path/'work/readings').exists()


@pytest.mark.parametrize('where',['fresh','pending'])
def test_a_candidate_absent_from_r2_refuses_before_any_append(tmp_path,where):
    from congress_api.lake.daily import produce_daily
    payloads=[payload(0),payload(1)]
    value,engine,bucket,store=fixture(tmp_path,payloads,unpinned={0})
    if where=='pending':append_unread(value,engine,value['receipt_inventory'][:1],tmp_path/'interrupted')
    bucket.absent.add(body_key(payloads[0]))
    before=heads(value,engine,tmp_path/'before')
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='raw_custody_required' and result['pins'] is None
    custody=result['producerreports']['readings']
    assert custody['missing_pins']==1 and custody['missing_physical']==1 and custody['conflicts']==0
    assert result['raw_listing']['absent']==[body_key(payloads[0])]
    assert result['new_receipt_keys']==[] and result['producerreports']['captures']['append'] is None
    assert heads(value,engine,tmp_path/'after')==before
    assert body_gets(bucket)==[] and not (tmp_path/'work/captures-append').exists()


def test_an_absent_object_of_a_body_already_read_has_no_effect(tmp_path):
    from congress_api.lake.daily import produce_daily
    read,new=payload(0),payload(1)
    # The second receipt refetches the read body; the third is new.
    value,engine,bucket,store=fixture(tmp_path,[read,read,new])
    receipts=value['receipt_inventory']
    first=produce_daily(dict(value,receipt_inventory=receipts[:1]),engine=engine,raw_store=store)
    assert first['status']=='completed'
    bucket.absent.add(body_key(read));bucket.heads.clear();bucket.gets.clear()
    result=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert result['status']=='completed' and result['new_receipt_keys']==[r['key'] for r in receipts[1:]]
    assert bucket.heads==[body_key(new)] and [get['Key'] for get in body_gets(bucket)]==[body_key(new)]
    assert result['producerreports']['readings']['work_items']==1


def test_planted_wrong_size_for_an_unpinned_body_is_refused_at_its_read(tmp_path):
    # No capture size exists to contradict a listed size, so the plan admits it; the
    # conditional read's length check is the guard, and nothing is parsed or appended.
    from congress_api.lake.daily import produce_daily
    value,engine,bucket,store=fixture(tmp_path,[payload(0)],unpinned={0})
    key=body_key(payload(0));size=(tmp_path/'raw'/key).stat().st_size
    bucket.head_override[key]=dict(ContentLength=size+1)
    with pytest.raises(ValueError,match='Pinned raw'):
        produce_daily(value,engine=engine,raw_store=store)
    assert heads(value,engine,tmp_path/'after')['readings']['snapshot'] is None
    assert body_gets(bucket) and all(get['Key']==key for get in body_gets(bucket))


def test_an_unquoted_listed_etag_fails_closed_at_the_read(tmp_path):
    # R2 quotes ETags; R2Adapter.head strips them. A listing built from stripped values
    # would never match the read's response version, so the listing keeps them verbatim.
    from congress_api.lake.daily import produce_daily
    value,engine,bucket,store=fixture(tmp_path,[payload(0)],unpinned={0})
    key=body_key(payload(0));md5=hashlib.md5((tmp_path/'raw'/key).read_bytes()).hexdigest()
    bucket.head_override[key]=dict(ETag=md5)
    with pytest.raises(ValueError,match='Pinned raw response changed'):
        produce_daily(value,engine=engine,raw_store=store)
    assert heads(value,engine,tmp_path/'after')['readings']['snapshot'] is None


def test_receipts_get_only_the_budget_the_pending_backlog_leaves(tmp_path):
    # Head holds B=2 unread bodies (one unpinned), M=3: only one new body may be admitted.
    # The old budget admitted all three, then refused after the append (5 > 3).
    from congress_api.lake.daily import produce_daily
    payloads=[payload(n) for n in range(5)]
    value,engine,bucket,store=fixture(tmp_path,payloads,unpinned={0})
    receipts=value['receipt_inventory'];value['max_work_items']=3
    append_unread(value,engine,receipts[:2],tmp_path/'interrupted')
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='completed'
    assert result['receipt_budget']==dict(selected=3,kept=1,fresh_bodies=1,pending_bodies=2,max_work_items=3)
    assert result['new_receipt_keys']==[receipts[2]['key']]
    assert result['producerreports']['readings']['work_items']==3
    assert sorted(bucket.heads)==sorted(body_key(p) for p in payloads[:3])
    rest=produce_daily(dict(value,work=str(tmp_path/'second')),engine=engine,raw_store=store)
    assert rest['status']=='completed' and rest['new_receipt_keys']==[r['key'] for r in receipts[3:]]


def test_a_backlog_past_the_budget_refuses_before_staging(tmp_path):
    from congress_api.lake.daily import produce_daily
    value,engine,bucket,store=fixture(tmp_path,[payload(n) for n in range(3)])
    receipts=value['receipt_inventory'];value['max_work_items']=1
    append_unread(value,engine,receipts[:2],tmp_path/'interrupted')
    before=heads(value,engine,tmp_path/'before')
    result=produce_daily(value,engine=engine,raw_store=store)
    assert result['status']=='backfill_required' and result['pins'] is None
    assert result['producerreports']['readings']['work_items']==2
    assert heads(value,engine,tmp_path/'after')==before and bucket.heads==[]
    assert not (tmp_path/'work/captures').exists()


def test_head_retries_throttling_and_server_errors_then_gives_up(monkeypatch):
    from congress_api.lake import daily
    sleeps=[];monkeypatch.setattr(daily.time,'sleep',sleeps.append)
    class Flaky:
        def __init__(self,failures):self.failures=list(failures);self.calls=0
        def head_object(self,*,Bucket,Key):
            self.calls+=1
            if self.failures:raise error('SlowDown',self.failures.pop(0),'HeadObject')
            return dict(ContentLength=7,ETag='"'+'a'*32+'"')
    client=Flaky([429,500])
    assert daily._head(client,'bucket','bodies/k')==dict(key='bodies/k',size=7,etag='"'+'a'*32+'"')
    assert client.calls==3 and len(sleeps)==2
    with pytest.raises(ClientError):daily._head(Flaky([503]*daily.HEAD_ATTEMPTS),'bucket','bodies/k')
    with pytest.raises(ClientError):daily._head(Flaky([403]),'bucket','bodies/k')
