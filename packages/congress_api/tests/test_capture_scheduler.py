"""F2: public release work, bounded raw capture and no legacy index authority."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from congress_api.models.raw_fetch import Transfer
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import BodyStore, LocalAdapter


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def release(tmp_path, rows, *, entries=None):
    root=tmp_path/'release';root.mkdir()
    schema=pa.schema([('requested_url',pa.string()),('attempts',pa.int32()),
        ('last_attempt',pa.timestamp('us',tz='UTC')),('last_status',pa.int16()),
        ('last_outcome',pa.string()),('last_good_at',pa.timestamp('us',tz='UTC')),
        ('next_attempt_at',pa.timestamp('us',tz='UTC'))])
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),root/'url_state.parquet')
    policy=dict(version=1,entries=entries if entries is not None else [dict(family='documents',
        patterns=[r'https://fixture\.test/[^#]*'],exclusions=[])])
    (root/'capture_scope.json').write_text(json.dumps(policy))
    files=[]
    for name in ['url_state.parquet','capture_scope.json']:
        data=(root/name).read_bytes()
        files.append(dict(name=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data),rows=len(rows) if name.endswith('parquet') else None))
    identity=hashlib.sha256(json.dumps([1,[[f['name'],f['sha256'],f['size'],f['rows']] for f in files]],separators=(',',':')).encode()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(dict(schema_version=1,release_id=identity,files=files)))
    return root


ASOF='2026-10-28T00:00:00Z'
IDENTITY=dict(job='capture-scheduler-fixture',commit='a'*40,lockfile_digest='b'*64)
LIMITS=ZipLimits(max_archive_bytes=1024,max_member_bytes=1024,max_total_bytes=2048,
                 max_members=8,max_directory_bytes=1024)


def load(root,work):
    from congress_api.acquisition.capture_scheduler import load_release
    return load_release(release_root=root,work=work)


def test_native_queue_priority_seeds_and_future_schedule(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    future=datetime(2027,1,1,tzinfo=timezone.utc)
    root=release(tmp_path,[
        dict(requested_url='https://fixture.test/old',attempts=2,next_attempt_at=datetime(2026,1,1,tzinfo=timezone.utc)),
        dict(requested_url='https://fixture.test/cut',attempts=1,last_outcome='size_limit'),
        dict(requested_url='https://fixture.test/queue',attempts=0),
        dict(requested_url='https://fixture.test/future',attempts=1,next_attempt_at=future)])
    seed=tmp_path/'seeds.json.gz'
    with gzip.open(seed,'wt') as out:json.dump({'documents':[['letter','a','https://fixture.test/new'],
        ['letter','future','https://fixture.test/future']]},out)
    selected=load(root,tmp_path/'download')
    result=plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,
        request_budget=20,seed_inventories=[seed])
    rows=pq.read_table(result['queue']).to_pylist()
    assert [r['requested_url'] for r in rows]==['https://fixture.test/new','https://fixture.test/queue',
        'https://fixture.test/cut','https://fixture.test/old']
    assert result['counts']['due']==4 and result['counts']['queue']==2
    assert 'raw_index' not in json.dumps(result)


def test_release_files_and_empty_policy_fail_closed(tmp_path):
    from congress_api.acquisition.capture_scheduler import CapturePolicy, plan_queue
    root=release(tmp_path,[],entries=[])
    selected=load(root,tmp_path/'read')
    with pytest.raises(ValueError,match='empty|scope'):
        CapturePolicy(selected['scope'],resolve=lambda _:['8.8.8.8']).require_capture()
    (root/'capture_scope.json').write_text('{}')
    with pytest.raises(ValueError,match='identity|hash|size'):
        load(root,tmp_path/'changed')


class Adapter:
    def __init__(self,responses):self.responses=responses;self.calls=[];self.limits=[]
    def hop(self,url,destination,*,limit,headers):
        self.calls.append(url);self.limits.append(limit)
        status,data,headers=self.responses[url]
        data=data[:limit]
        destination.write_bytes(data)
        return Transfer(destination,url,status,headers,True,sha256=hashlib.sha256(data).hexdigest(),size=len(data))


def run_fixture(tmp_path,rows,responses,**options):
    from congress_api.acquisition.capture_scheduler import run_capture
    root=release(tmp_path,rows)
    selected=load(root,tmp_path/'read')
    adapter=Adapter(responses)
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    result=run_capture(selected,engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=options.pop('request_budget',100),byte_budget=options.pop('byte_budget',2**30),
        spool_budget=options.pop('spool_budget',2**30),store=store,identity=IDENTITY,
        direct=adapter,provider=None,resolve=lambda _:['8.8.8.8'],
        archive_limits=LIMITS,pace=lambda *_:None,**options)
    return result,adapter,tmp_path/'raw'


def test_discovered_queue_preempts_old_due_and_creates_only_raw(tmp_path):
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url='https://fixture.test/z',attempts=1)],{
        'https://fixture.test/a':(200,b'<html><body><a href="/child">file</a></body></html>',{'content-type':'text/html'}),
        'https://fixture.test/child':(200,b'%PDF-1.7\n%%EOF',{'content-type':'application/pdf'}),
        'https://fixture.test/z':(404,b'gone',{})})
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/child','https://fixture.test/z']
    assert result['requests']==3 and result['captures']==3 and len(result['receipts'])==3
    assert all(p.parts[len(raw.parts)] in {'bodies','receipts'} for p in raw.rglob('*') if p.is_file())
    assert not list((tmp_path/'capture').rglob('*.body'))
    lines=[]
    for path in raw.rglob('*.jsonl.gz'):
        with gzip.open(path,'rt') as stream:lines.extend(map(json.loads,stream))
    assert all(row['mode']=='fetch' and row['writer']==IDENTITY for row in lines)
    assert all(capture['stored_md5'] for row in lines for capture in row['captures'])


def test_request_budget_counts_redirects_and_preserves_prior_evidence(tmp_path):
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url='https://fixture.test/z',attempts=0)],{
        'https://fixture.test/a':(302,b'',{'location':'/end'}),
        'https://fixture.test/end':(200,b'entity',{}),
        'https://fixture.test/z':(200,b'z',{})},request_budget=7)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/end']
    assert result['requests']==2 and result['stop_reason']=='request_budget'


def test_budget_allows_more_than_64mib_without_a_large_fixture(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],
        {'https://fixture.test/a':(200,b'bounded fixture',{})},byte_budget=2**32,spool_budget=2**31)
    assert adapter.limits[0]>64*1024**2
    assert result['fetched_bytes']==len(b'bounded fixture')


def test_scope_registry_refuses_credentials_private_addresses_and_traps():
    from congress_api.acquisition.capture_scheduler import CapturePolicy
    path=Path(__file__).resolve().parents[3]/'model/registries/capture-scope.json'
    policy=CapturePolicy(path,resolve=lambda _:['8.8.8.8'])
    assert policy('https://docs.house.gov/meetings/IF/IF00/20261027/118000/HMTG-119-IF00-Wstate-A.pdf')
    assert policy('https://www.govinfo.gov/content/pkg/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345.pdf')
    assert not policy('https://docs.house.gov/meetings/a.pdf?api_key=secret')
    assert not policy('https://www.foreign.senate.gov/hearings/month/2026-01')
    assert not policy('https://unrelated.example/file.pdf')
    private=CapturePolicy(path,resolve=lambda _:['127.0.0.1'])
    assert not private('https://docs.house.gov/meetings/a.pdf')
