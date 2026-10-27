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
from docspec_client.models import DocSpecFailure
from congress_api.models.raw_fetch import Transfer
from congress_api.archive_profile import build_capture_profile
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
    project=Path(__file__).resolve().parents[3]
    profile=build_capture_profile(engine_revision=engine().source_revision,
        url_normalized_sql=(project/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(project/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((project/'model/registries/url-rules.json').read_text()))
    (root/'capture_profile.json').write_text(json.dumps(profile))
    pq.write_table(pa.Table.from_pylist([],schema=pa.schema([('canonical_url',pa.string()),
        ('variant_url',pa.string())])),root/'url_variants.parquet')
    write_manifest(root)
    # Finite authored identity adapter: this checks scheduler joins, not E's
    # normalization algorithm or its registry qualification. Unknown URLs have
    # no key and therefore refuse the native identity contract.
    pairs=[('https://fixture.test/'+name,'fixture:'+name) for name in
        ['a','b','c','z','new','queue','old','cut','future','good','pending','missing','child','end']]
    pairs.extend([('https://fixture.test/a%20b.pdf','fixture:space-alias'),
                  ('https://fixture.test/a b.pdf','fixture:space-alias'),
                  ('https://outside.example/a','outside:a')])
    values=','.join("('"+url+"','"+key+"')" for url,key in pairs)
    (root/'fixture-url-keys.sql').write_text('SELECT i.input_id,i.url,f.url_key FROM url_inputs i LEFT JOIN (VALUES '+values+') f(url,url_key) ON i.url=f.url')
    return root


def write_manifest(root):
    files=[]
    for name in ['url_state.parquet','capture_scope.json','capture_profile.json','url_variants.parquet']:
        data=(root/name).read_bytes()
        files.append(dict(name=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data),
            rows=pq.read_metadata(root/name).num_rows if name.endswith('parquet') else None))
    identity=hashlib.sha256(json.dumps([1,[[f[k] for k in ('name','sha256','size','rows')] for f in files]],
        separators=(',',':')).encode()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(dict(schema_version=1,release_id=identity,files=files)))


ASOF='2026-10-28T00:00:00Z'
IDENTITY=dict(job='capture-scheduler-fixture',commit='a'*40,lockfile_digest='b'*64)
LIMITS=ZipLimits(max_archive_bytes=1024,max_member_bytes=1024,max_total_bytes=2048,
                 max_members=8,max_directory_bytes=1024)


def load(root,work):
    from congress_api.acquisition.capture_scheduler import load_release
    selected=load_release(release_root=root,work=work)
    return selected


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


def fixture_discover(body,parser):
    from congress_api.parsers.archive_readings import read_page
    return read_page(body,parser)


def run_fixture(tmp_path,rows,responses,**options):
    from congress_api.acquisition.capture_scheduler import run_capture
    root=release(tmp_path,rows)
    selected=load(root,tmp_path/'read')
    adapter=Adapter(responses)
    options.setdefault('discover',fixture_discover)
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


def test_provider_fallback_keeps_both_attempts_and_budget_accounting(tmp_path):
    from congress_api.acquisition.capture_scheduler import run_capture
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)])
    direct=Adapter({'https://fixture.test/a':(403,b'denied',{})})
    provider=Adapter({'https://fixture.test/a':(200,b'publisher bytes',{})})
    result=run_capture(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=14,byte_budget=2**30,spool_budget=2**30,store=BodyStore(LocalAdapter(tmp_path/'raw')),
        identity=IDENTITY,direct=direct,provider=provider,discover=fixture_discover,resolve=lambda _:['8.8.8.8'],archive_limits=LIMITS,pace=lambda *_:None)
    assert result['requests']==2 and result['fetched_bytes']==len(b'deniedpublisher bytes')
    [receipt]=list((tmp_path/'raw').rglob('*.jsonl.gz'))
    with gzip.open(receipt,'rt') as source:line=json.loads(source.readline())
    assert line['http_status']==200 and len(line['captures'])==2
    assert line['prior_attempts'][0]['http_status']==403
    assert {capture['attempt'] for capture in line['captures']}=={0,1}
    assert result['spool_reserved_bound']<=result['budgets']['spool']
    assert not list((tmp_path/'capture').rglob('*.body'))


def test_explicit_cutoff_list_and_duplicate_state_refusal(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=1),
        dict(requested_url='https://fixture.test/z',attempts=1)])
    selected=load(root,tmp_path/'read')
    result=plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,request_budget=10,
        cutoff_urls=['https://fixture.test/z','https://fixture.test/z'])
    assert [row['requested_url'] for row in pq.read_table(result['queue']).to_pylist()]==[
        'https://fixture.test/z','https://fixture.test/a']
    other=tmp_path/'other';other.mkdir()
    root=release(other,[dict(requested_url='https://fixture.test/a',attempts=0)]*2)
    with pytest.raises((ValueError,DocSpecFailure),match='duplicate|unique|order'):
        plan_queue(load(root,tmp_path/'duplicate-read'),engine=engine(),work=tmp_path/'duplicate-plan',as_of=ASOF,request_budget=10)


def test_discovery_failure_does_not_change_stored_capture_outcome(tmp_path):
    def reject(*_):return dict(status='error',error_type='invalid_page')
    result,_,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],
        {'https://fixture.test/a':(200,b'<html>page</html>',{})},discover=reject)
    assert result['captures']==1 and result['discovery_errors']==[dict(url='https://fixture.test/a',reason='invalid_page')]
    with gzip.open(next(raw.rglob('*.jsonl.gz')),'rt') as source:
        assert json.loads(source.readline())['outcome']=='stored'


def test_discovery_budget_and_cycles_terminate_without_index_state(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{
        'https://fixture.test/a':(200,b'<html><a href="/b">b</a></html>',{}),
        'https://fixture.test/b':(200,b'<html><a href="/a">a</a><a href="/c">c</a></html>',{})},max_discovery_jobs=1)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/b']
    assert result['stop_reason']=='discovery_job_budget' and result['discovery_jobs']==1


def test_byte_and_spool_budget_refuse_before_adapters(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{},spool_budget=1024)
    assert not adapter.calls and result['stop_reason']=='byte_or_spool_budget'


def test_scheduler_cli_has_no_replay_or_raw_index_mode(tmp_path):
    from congress_api.cli.capture_schedule import main
    with pytest.raises(SystemExit):main(['--replay'])
    with pytest.raises(SystemExit):main(['--raw-index','indexes/raw.json'])


class PublicResponse:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def raise_for_status(self):pass
    def iter_content(self,chunk_size):yield self.data


class PublicSession:
    def __init__(self,root):self.root=root;self.calls=[]
    def get(self,url,**options):
        self.calls.append((url,options))
        name=url.rsplit('/',1)[1]
        if name=='current.json':
            manifest=json.loads((self.root/'manifest.json').read_text())
            return PublicResponse(json.dumps(dict(release_id=manifest['release_id'])).encode())
        return PublicResponse((self.root/name).read_bytes())


def test_public_pointer_is_pinned_once_and_inputs_are_verified(tmp_path):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[])
    session=PublicSession(root)
    selected=load_release(pointer='https://public.fixture/viewer-publications/current.json',
        session=session,work=tmp_path/'download')
    assert len(session.calls)==6
    assert sum(url.endswith('current.json') for url,_ in session.calls)==1
    assert all(options['allow_redirects'] is False for _,options in session.calls)
    assert Path(selected['state']).read_bytes()==(root/'url_state.parquet').read_bytes()


def test_cli_preview_uses_local_release_without_opening_raw_storage(tmp_path,capsys):
    from congress_api.cli.capture_schedule import main
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)])
    main(['--release-root',str(root),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--request-budget','20','--byte-budget','1073741824','--spool-budget','1073741824',
        '--as-of',ASOF,'--work',str(tmp_path/'preview')])
    result=json.loads(capsys.readouterr().out)
    assert result['apply'] is False and result['counts']['queue']==1
    assert not (tmp_path/'preview/capture').exists()


def test_seed_loader_keeps_jsonl_pointer_and_refuses_credential_urls(tmp_path):
    from congress_api.acquisition.capture_seeds import inventories
    path=tmp_path/'meetings.jsonl.gz'
    with gzip.open(path,'wt') as stream:
        stream.write(json.dumps(dict(documents=[['statement','label','https://fixture.test/a']]))+'\n')
    [row]=list(inventories([path]))
    assert row==dict(url='https://fixture.test/a',source=path.name,pointer='["documents",0,2]')
    with gzip.open(path,'wt') as stream:stream.write(json.dumps(dict(url='https://fixture.test/a?token=secret'))+'\n')
    with pytest.raises(ValueError,match='Credential'):list(inventories([path]))


def test_single_put_entity_boundary_is_admitted_when_resources_fit(tmp_path):
    single_put=5*1024**3
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],
        {'https://fixture.test/a':(200,b'virtual large binary boundary',{'content-type':'application/octet-stream'})},
        byte_budget=single_put*14,spool_budget=single_put*4)
    assert adapter.limits==[single_put]
    assert result['spool_reserved_bound']<=result['budgets']['spool']


@pytest.mark.parametrize('unsafe',['/unsafe?token=secret','/unsafe?%74oken=secret','//user:secret@fixture.test/unsafe'])
def test_unsafe_discovered_target_is_refused_without_aborting_other_work(tmp_path,unsafe):
    data=('<html><a href="'+unsafe+'">unsafe link</a></html>').encode()
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url='https://fixture.test/z',attempts=1)],{
        'https://fixture.test/a':(200,data,{'content-type':'text/html'}),
        'https://fixture.test/z':(200,b'valid other capture',{})})
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/z']
    assert result['captures']==2 and result['discovery_refused']==1
    assert 'secret' not in json.dumps(result)
    for path in raw.rglob('*.jsonl.gz'):
        with gzip.open(path,'rt') as source:
            assert 'secret' not in source.read()


def test_every_reviewed_cutoff_has_a_native_disposition(tmp_path):
    future=datetime(2027,1,1,tzinfo=timezone.utc)
    cutoffs=['https://fixture.test/good','https://fixture.test/pending','https://fixture.test/future',
        'https://outside.example/a','https://fixture.test/missing']
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url=cutoffs[0],attempts=1),dict(requested_url=cutoffs[1],attempts=1),
        dict(requested_url=cutoffs[2],attempts=1,next_attempt_at=future),
        dict(requested_url=cutoffs[3],attempts=1)],{
        'https://fixture.test/a':(200,b'queue',{}),'https://fixture.test/good':(200,b'complete cutoff',{})},
        request_budget=8,cutoff_urls=cutoffs)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/good']
    rows={row['requested_url']:row for row in result['cutoffs']}
    assert set(rows)==set(cutoffs)
    assert rows[cutoffs[0]]['disposition']=='attempted' and rows[cutoffs[0]]['complete'] is True
    assert rows[cutoffs[1]]['reason']=='request_budget'
    assert rows[cutoffs[2]]['reason']=='not_due' and rows[cutoffs[2]]['next_attempt_at'].startswith('2027-01-01')
    assert rows[cutoffs[3]]['reason']=='outside_capture_scope'
    assert rows[cutoffs[4]]['reason']=='not_in_release'


def test_future_seed_alias_does_not_bypass_shared_url_identity(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a%20b.pdf',attempts=1,
        next_attempt_at=datetime(2027,1,1,tzinfo=timezone.utc))])
    seed=tmp_path/'seeds.json'
    seed.write_text(json.dumps(dict(url='https://fixture.test/a b.pdf')))
    result=plan_queue(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'plan',as_of=ASOF,
        request_budget=20,seed_inventories=[seed])
    assert pq.read_table(result['queue']).num_rows==0


def test_attempted_alias_is_not_scheduled_again(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a%20b.pdf',attempts=0)])
    attempted=tmp_path/'attempted.jsonl.gz'
    with gzip.open(attempted,'wt') as out:out.write(json.dumps(dict(url='https://fixture.test/a b.pdf'))+'\n')
    result=plan_queue(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'plan',as_of=ASOF,
        request_budget=20,attempted=attempted)
    assert pq.read_table(result['queue']).num_rows==0


def test_missing_shared_url_definition_refuses_before_native_planning(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    selected=load(release(tmp_path,[]),tmp_path/'read')
    selected['url_keys_sql']=tmp_path/'missing-shared-url-keys.sql'
    with pytest.raises(ValueError,match='url_key'):
        plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,request_budget=20)
    assert not (tmp_path/'plan').exists()


def test_discovery_uses_one_bounded_shared_worker_per_format(tmp_path):
    from congress_api.acquisition.capture_scheduler import run_capture,read_discovery_payload
    instances=[]
    class Worker:
        def __init__(self,parser,version,callable_path,**limits):
            self.calls=[];self.closed=False;self.limits=limits;instances.append(self)
            assert parser=='html' and len(version)==64
            assert callable_path=='congress_api.acquisition.capture_scheduler:read_discovery_payload'
            assert limits['timeout_seconds']>0 and limits['memory_bytes']>0 and limits['max_input_bytes']>0
        def __enter__(self):return self
        def __exit__(self,*_):self.closed=True
        def parse(self,input_id,payload):
            self.calls.append(input_id)
            return dict(status='completed',value=read_discovery_payload(payload))
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)])
    adapter=Adapter({'https://fixture.test/a':(200,b'<html><a href="/b">b</a></html>',{}),
                     'https://fixture.test/b':(200,b'<html>second page</html>',{})})
    result=run_capture(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=100,byte_budget=2**30,spool_budget=2**30,store=BodyStore(LocalAdapter(tmp_path/'raw')),
        identity=IDENTITY,direct=adapter,resolve=lambda _:['8.8.8.8'],archive_limits=LIMITS,
        pace=lambda *_:None,worker_factory=Worker)
    assert result['captures']==2 and len(instances)==1
    assert len(instances[0].calls)==2 and instances[0].closed


@pytest.mark.parametrize('change',['sql_hash','engine_revision'])
def test_release_profile_refuses_unqualified_sql_or_engine_before_planning(tmp_path,change):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[])
    path=root/'capture_profile.json';profile=json.loads(path.read_text())
    if change=='sql_hash':profile['sql']['url_keys']['text']+=' -- changed'
    else:profile['engine_revision']='0'*40
    path.write_text(json.dumps(profile));write_manifest(root)
    with pytest.raises(ValueError,match='profile|revision|SQL'):
        selected=load(root,tmp_path/'read')
        plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,request_budget=20)
    assert not (tmp_path/'plan').exists()


def test_public_release_rejects_authored_workspace_identity_override(tmp_path):
    from congress_api.acquisition.capture_scheduler import load_release,plan_queue
    root=release(tmp_path,[])
    selected=load_release(pointer='https://public.fixture/current.json',session=PublicSession(root),work=tmp_path/'read')
    selected['url_keys_sql']=root/'fixture-url-keys.sql'
    with pytest.raises(ValueError,match='public|override'):
        plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,request_budget=20)
    assert not (tmp_path/'plan').exists()


def test_active_release_variant_keeps_future_seed_alias_out_of_queue(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=1,
        next_attempt_at=datetime(2027,1,1,tzinfo=timezone.utc))])
    pq.write_table(pa.Table.from_pylist([dict(canonical_url='https://fixture.test/a',
        variant_url='https://fixture.test/b')]),root/'url_variants.parquet')
    write_manifest(root)
    seed=tmp_path/'seed.json';seed.write_text(json.dumps(dict(url='https://fixture.test/b')))
    result=plan_queue(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'plan',as_of=ASOF,
        request_budget=20,seed_inventories=[seed])
    assert pq.read_table(result['queue']).num_rows==0


def test_actual_parser_worker_discovers_and_captures_local_link(tmp_path):
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{
        'https://fixture.test/a':(200,b'<html><a href="/b">b</a></html>',{'content-type':'text/html'}),
        'https://fixture.test/b':(200,b'%PDF-1.7\n%%EOF',{})},discover=None)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/b']
    assert result['discovery_jobs']==1 and result['discovery_errors']==[]
    assert result['captures']==2 and len(list(raw.rglob('*.jsonl.gz')))==2


def test_public_cli_rejects_authored_override_before_work_or_network(tmp_path):
    from congress_api.cli.capture_schedule import main
    with pytest.raises(SystemExit):
        main(['--pointer','https://public.fixture/current.json','--url-keys-sql',str(tmp_path/'workspace.sql'),
            '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--request-budget','20',
            '--byte-budget','1000','--spool-budget','1000','--work',str(tmp_path/'work')])
    assert not (tmp_path/'work').exists()


@pytest.mark.parametrize('name',['capture_profile.json','url_variants.parquet'])
def test_release_profile_files_are_manifest_verified(tmp_path,name):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[])
    with (root/name).open('ab') as out:out.write(b'changed')
    with pytest.raises(ValueError,match='identity|size'):
        load_release(release_root=root,work=tmp_path/'read')


def test_missing_release_profile_has_no_workspace_fallback(tmp_path):
    from congress_api.acquisition.capture_scheduler import load_release
    root=release(tmp_path,[])
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['files']=[row for row in manifest['files'] if row['name']!='capture_profile.json']
    manifest['release_id']=hashlib.sha256(json.dumps([1,[[row[k] for k in ('name','sha256','size','rows')]
        for row in manifest['files']]],separators=(',',':')).encode()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='scheduler input'):
        load_release(release_root=root,work=tmp_path/'read')
