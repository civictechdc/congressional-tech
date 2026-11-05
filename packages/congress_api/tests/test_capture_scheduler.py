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
from congress_api.models.archive_profile import build_capture_profile
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


def test_reviewed_house_xml_targets_keep_failed_probes_out_of_record_production(tmp_path):
    from capture_qualification_helpers import write_qualified_bytes
    from congress_api.cli.fetch_meetings import run_meeting_fetchers
    from congress_api.lake import capture_staging, committee_records

    base = "https://docs.house.gov/meetings/RU/RU00/20250521"
    wrong_url = f"{base}/118455/HMTG-119-RU00-20250521.xml"
    failed_url = f"{base}/118300/HMKP-119-RU00-20250521.xml"
    good_url = f"{base}/118300/HMTG-119-RU00-20250521.xml"
    doc_url = f"{base}/118300/BILLS-119-7-M000312-Amdt-7.pdf"
    body = (
        '<committee-meeting meeting-id="HMTG118300" update-date="2025-05-22T20:22:01.820">'
        '<meeting-documents><meeting-document type="CA"><filename-metadata><amdt-num>7</amdt-num>'
        f'</filename-metadata><files><file doc-url="{doc_url}"/></files>'
        '</meeting-document></meeting-documents></committee-meeting>'
    ).encode()
    wrong_body = body.replace(b'118300', b'118455')
    access_wall = b'<html>access denied</html>'
    xml = {'content-type': 'application/xml'}
    refused = Adapter({failed_url: (200, wrong_body, xml), good_url: (200, access_wall, {})})
    accepted = Adapter({good_url: (200, body, xml)})
    raw = tmp_path / 'raw'
    options = dict(store=BodyStore(LocalAdapter(raw)), identity=IDENTITY, direct=refused,
                   resolve=lambda _: ['8.8.8.8'], pace=lambda *_: None)
    with pytest.raises(ValueError, match='does not identify event 118300'):
        run_meeting_fetchers(**options, house_xml_targets=[dict(event_id='118300', url=wrong_url)])
    assert refused.calls == []
    result = run_meeting_fetchers(**options, provider=accepted, house_xml_targets=[
        dict(event_id='118300', url=failed_url), dict(event_id='118300', url=good_url)
    ])
    assert refused.calls == [failed_url, good_url]
    assert accepted.calls == [good_url]
    probes = [probe for item in result['house_xml_targets'] for probe in item['probes']]
    assert [(p['http_status'], p['outcome'], p['error_type']) for p in probes] == [
        (200, 'request_failed', 'wrong_event_body'),
        (200, 'request_failed', 'invalid_meeting_xml'),
        (200, 'stored', None),
    ]
    files = []
    for key in result['receipt_keys']:
        source = raw / key
        qualified = tmp_path / 'receipts' / source.name
        files.append(dict(key=key, path=str(qualified),
                          qualification=write_qualified_bytes(qualified, source.read_bytes())))
    native = engine()
    capture_path = capture_staging.stage_captures(
        files, engine=native, work=tmp_path / 'capture-stage'
    ) / 'captures.parquet'
    captures = pq.read_table(capture_path).to_pylist()
    assert {r['sha256'].hex(): r['outcome'] for r in captures} == {
        hashlib.sha256(wrong_body).hexdigest(): 'request_failed',
        hashlib.sha256(access_wall).hexdigest(): 'request_failed',
        hashlib.sha256(body).hexdigest(): 'stored',
    }
    staged = committee_records.stage(captures=capture_path, engine=native,
                                     work=tmp_path / 'records-stage', local_root=raw)
    [record] = pq.read_table(staged['records']).to_pylist()
    assert record['event_id'] == '118300'
    assert [(r['ordinal'], r['number'], r['bill'], r['url']) for r in record['records']] == [
        (0, '7', None, doc_url)
    ]


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
        'https://fixture.test/z':(200,b'z',{})},request_budget=2)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/end']
    assert result['requests']==2 and result['stop_reason']=='request_budget'


def test_scheduler_caps_direct_entities_at_measured_capacity(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],
        {'https://fixture.test/a':(200,b'bounded fixture',{})},byte_budget=2**32,spool_budget=2**31)
    assert adapter.limits[0]==16*1024**2
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
    from congress_api.acquisition.admission import Admission
    root=release(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)])
    direct=Adapter({'https://fixture.test/a':(403,b'denied',{})})
    provider=Adapter({'https://fixture.test/a':(200,b'publisher bytes',{})})
    result=run_capture(load(root,tmp_path/'read'),engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=14,byte_budget=2**30,spool_budget=2**30,store=BodyStore(LocalAdapter(tmp_path/'raw')),
        identity=IDENTITY,direct=direct,provider=provider,provider_cost=1,admission=Admission(tmp_path/'admission.sqlite',14,1),discover=fixture_discover,resolve=lambda _:['8.8.8.8'],archive_limits=LIMITS,pace=lambda *_:None)
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


@pytest.mark.parametrize(('status','data','jobs'), [(202,b'<html><a href="/b">challenge</a></html>',0),
    (200,b'',0),(200,b'<html><a href="/b">b</a></html>',1)])
def test_discovery_runs_only_on_a_document(tmp_path,status,data,jobs):
    """A 202 or empty page is a failed attempt (writer outcome), so its links are never followed."""
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{
        'https://fixture.test/a':(status,data,{'content-type':'text/html'}),
        'https://fixture.test/b':(200,b'<html>b</html>',{'content-type':'text/html'})},max_discovery_jobs=1)
    assert result['discovery_jobs']==jobs
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/b'][:1+jobs]


def test_a_receipt_refused_for_a_local_path_fails_only_its_item(tmp_path,monkeypatch):
    from congress_api.retention import receipt_writer
    from congress_api.retention.receipt_privacy import LocalPathRefused
    original=receipt_writer.ReceiptWriter.write
    def write(self,result,**options):
        if result.final.requested_url.endswith('/a'):
            raise LocalPathRefused('Public receipt carries a local path at source_file')
        return original(self,result,**options)
    monkeypatch.setattr(receipt_writer.ReceiptWriter,'write',write)
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url='https://fixture.test/b',attempts=0)],{
        'https://fixture.test/a':(200,b'%PDF-1.7\n%%EOF a',{}),'https://fixture.test/b':(200,b'%PDF-1.7\n%%EOF b',{})})
    assert result['captures']==1 and result['stop_reason']=='queue_empty'
    assert dict(url='https://fixture.test/a',reason='local_path_in_receipt') in result['refusals']


def test_discovery_budget_and_cycles_terminate_without_index_state(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{
        'https://fixture.test/a':(200,b'<html><a href="/b">b</a></html>',{}),
        'https://fixture.test/b':(200,b'<html><a href="/a">a</a><a href="/c">c</a></html>',{})},max_discovery_jobs=1)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/b']
    assert result['stop_reason']=='queue_empty' and result['discovery_jobs']==1


def test_byte_and_spool_budget_refuse_before_adapters(tmp_path):
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{},spool_budget=1024)
    assert not adapter.calls and result['stop_reason']=='byte_or_spool_budget'


def test_scheduler_cli_has_no_replay_or_raw_index_mode(tmp_path):
    from congress_api.cli.capture_schedule import main
    with pytest.raises(SystemExit):main(['--replay'])
    with pytest.raises(SystemExit):main(['--raw-index','indexes/raw.json'])
    with pytest.raises(SystemExit):main(['--seed-inventory','pipeline-data/meeting-inventory/house.json.gz'])


def test_b14_meeting_fetchers_and_url_state_capture_emit_stored_md5_and_suffix(tmp_path):
    from congress_api.cli.fetch_meetings import run_meeting_fetchers
    from congress_api.acquisition.capture_scheduler import run_capture

    house_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<committee-meeting meeting-type="HHRG" event-id="118001" congress="118">'
        b'<committees><committee-name id="IF00">Energy</committee-name></committees>'
        b'<meeting-details><meeting-date><calendar-date>2026-10-10</calendar-date></meeting-date>'
        b'<meeting-title>Hearing</meeting-title></meeting-details></committee-meeting>'
    )
    witness_xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<witness-list event-id="118001"><witness><witness-name>Jane Doe</witness-name></witness></witness-list>'
    )
    mods_xml = (Path(__file__).resolve().parent / 'fixtures/gpo_metadata/CHRG-113hhrg21122.xml').read_bytes()
    congress_list = json.dumps({
        'committeeMeetings': [{
            'eventId': '118001',
            'chamber': 'House',
            'congress': 118,
            'updateDate': '2026-10-10T00:00:00Z',
            'url': 'https://api.congress.gov/v3/committee-meeting/118/house/118001?format=json',
        }],
        'pagination': {'count': 1, 'next': None},
    }).encode('utf-8')
    congress_detail = json.dumps({
        'committeeMeeting': {
            'eventId': '118001',
            'chamber': 'House',
            'congress': 118,
            'title': 'Hearing',
            'date': '2026-10-10T14:00:00Z',
            'updateDate': '2026-10-10T00:00:00Z',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy'}],
        }
    }).encode('utf-8')

    responses = {
        'https://api.congress.gov/v3/committee-meeting/118/house?format=json&limit=250&offset=0&fromDateTime=2026-10-01T00%3A00%3A00Z&toDateTime=2026-10-15T00%3A00%3A00Z': (
            200, congress_list, {'content-type': 'application/json'}
        ),
        'https://api.congress.gov/v3/committee-meeting/118/house/118001?format=json': (
            200, congress_detail, {'content-type': 'application/json'}
        ),
        'https://www.govinfo.gov/metadata/pkg/CHRG-113hhrg21122/mods.xml': (
            200, mods_xml, {'content-type': 'application/xml'}
        ),
        'https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-118-IF00-20261010.xml': (
            200, house_xml, {'content-type': 'application/xml'}
        ),
        'https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-118-IF00-WList-20261010.xml': (
            200, witness_xml, {'content-type': 'application/xml'}
        ),
        'https://www.banking.senate.gov/hearings/test-hearing': (
            200, b'<html><head><title>Hearing</title></head><body><h1>Hearing</h1></body></html>', {'content-type': 'text/html'}
        ),
    }

    store = BodyStore(LocalAdapter(tmp_path / 'b14-raw'))
    adapter = Adapter(responses)
    b14_summary = run_meeting_fetchers(
        store=store,
        identity=IDENTITY,
        direct=adapter,
        resolve=lambda _: ['8.8.8.8'],
        pace=lambda *_: None,
        api_key='test-api-key',
        congress_endpoints=[{
            'endpoint': 'https://api.congress.gov/v3/committee-meeting/118/house',
            'from_date_time': '2026-10-01T00:00:00Z',
            'to_date_time': '2026-10-15T00:00:00Z',
        }],
        congress_detail_urls=['https://api.congress.gov/v3/committee-meeting/118/house/118001'],
        gpo_packages=['CHRG-113hhrg21122'],
        house_meetings=[{
            'eventId': '118001',
            'congress': 118,
            'chamber': 'House',
            'date': '2026-10-10T14:00:00Z',
            'committees': [{'systemCode': 'hsif00', 'name': 'Energy'}],
            'meetingDocuments': [{
                'url': 'https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-118-IF00-20261010.xml'
            }],
        }],
        senate_urls=['https://www.banking.senate.gov/hearings/test-hearing'],
    )
    assert len(b14_summary['receipt_keys']) == 6
    b14_lines = []
    for path in (tmp_path / 'b14-raw').rglob('*.jsonl.gz'):
        with gzip.open(path, 'rt') as stream:
            b14_lines.extend(map(json.loads, stream))
    assert len(b14_lines) == 6
    for line in b14_lines:
        assert line['mode'] == 'fetch' and line['outcome'] == 'stored'
        for cap in line['captures']:
            assert cap['stored_md5'] and cap['stored_suffix'] in {'.gz', '.pdf', ''}

    # Also verify url_state.parquet capture produces stored_md5 and stored_suffix with zero old-index reads
    cap_root = release(
        tmp_path,
        [dict(requested_url='https://fixture.test/doc.pdf', attempts=0)],
    )
    cap_store = BodyStore(LocalAdapter(tmp_path / 'cap-raw'))
    cap_adapter = Adapter({'https://fixture.test/doc.pdf': (200, b'%PDF-1.7\nbody\n%%EOF', {'content-type': 'application/pdf'})})
    cap_res = run_capture(
        load(cap_root, tmp_path / 'cap-read'),
        engine=engine(),
        work=tmp_path / 'cap-work',
        as_of=ASOF,
        request_budget=14,
        byte_budget=2**30,
        spool_budget=2**30,
        store=cap_store,
        identity=IDENTITY,
        direct=cap_adapter,
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
    )
    assert cap_res['captures'] == 1
    assert 'raw_index' not in json.dumps(cap_res)
    [cap_receipt] = list((tmp_path / 'cap-raw').rglob('*.jsonl.gz'))
    with gzip.open(cap_receipt, 'rt') as stream:
        cap_line = json.loads(stream.readline())
    assert cap_line['captures'][0]['stored_md5']
    assert cap_line['captures'][0]['stored_suffix'] == ''


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
    url='https://fixture.test/a'
    root=release(tmp_path,[dict(requested_url=url,attempts=0)])
    cutoff_file=tmp_path/'reviewed.json'
    cutoff_file.write_text(json.dumps([url]))
    args=['--release-root',str(root),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--request-budget','20','--byte-budget','1073741824','--spool-budget','1073741824',
        '--as-of',ASOF,'--work',str(tmp_path/'preview'),'--cutoff-urls',str(cutoff_file)]
    main(args)
    result=json.loads(capsys.readouterr().out)
    assert result['apply'] is False and result['counts']['queue']==1
    assert not (tmp_path/'preview/capture').exists()
    selection=json.loads((tmp_path/'preview/selection.json').read_text())
    assert selection['cutoff_urls']==result['reviewed_cutoff_urls']==[url]
    assert selection['release']['release_id']==result['release_id']
    cutoff_file.write_text(json.dumps(['https://fixture.test/b']))
    with pytest.raises(ValueError,match='Continuation reviewed cutoff input changed'):
        main(args)


def test_seed_loader_keeps_jsonl_pointer_and_refuses_credential_urls(tmp_path):
    from congress_api.acquisition.capture_seeds import inventories
    path=tmp_path/'meetings.jsonl.gz'
    with gzip.open(path,'wt') as stream:
        stream.write(json.dumps(dict(documents=[['statement','label','https://fixture.test/a']]))+'\n')
    [row]=list(inventories([path]))
    assert row==dict(url='https://fixture.test/a',source=path.name,pointer='["documents",0,2]')
    with gzip.open(path,'wt') as stream:stream.write(json.dumps(dict(url='https://fixture.test/a?token=secret'))+'\n')
    with pytest.raises(ValueError,match='Credential'):list(inventories([path]))


def test_large_budget_keeps_measured_entity_capacity(tmp_path):
    single_put=5*1024**3
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],
        {'https://fixture.test/a':(200,b'virtual large binary boundary',{'content-type':'application/octet-stream'})},
        byte_budget=single_put*14,spool_budget=single_put*4)
    assert adapter.limits==[16<<20]
    assert result['spool_reserved_bound']<=result['budgets']['spool']


@pytest.mark.parametrize('unsafe',['/unsafe?token=secret','/unsafe?%74oken=secret','//user:secret@fixture.test/unsafe','mailto:info@fixture.test?subject=Hello','javascript:void(0)','tel:+12022252171'])
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
        'https://outside.example/a','https://fixture.test/missing','https://fixture.test/retained']
    result,adapter,_=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0),
        dict(requested_url=cutoffs[0],attempts=1),dict(requested_url=cutoffs[1],attempts=1),
        dict(requested_url=cutoffs[2],attempts=1,next_attempt_at=future),
        dict(requested_url=cutoffs[3],attempts=1),
        dict(requested_url=cutoffs[5],attempts=1,last_outcome='stored',last_status=200,next_attempt_at=future)],{
        'https://fixture.test/a':(200,b'queue',{}),'https://fixture.test/good':(200,b'complete cutoff',{})},
        request_budget=2,cutoff_urls=cutoffs)
    assert adapter.calls==['https://fixture.test/a','https://fixture.test/good']
    rows={row['requested_url']:row for row in result['cutoffs']}
    assert set(rows)==set(cutoffs)
    assert rows[cutoffs[0]]['disposition']=='attempted' and rows[cutoffs[0]]['complete'] is True
    assert rows[cutoffs[0]]['candidate_url']==cutoffs[0] and rows[cutoffs[0]]['receipt_key'] in result['receipts']
    assert rows[cutoffs[1]]['reason']=='request_budget'
    assert rows[cutoffs[2]]['reason']=='not_due' and rows[cutoffs[2]]['next_attempt_at'].startswith('2027-01-01')
    assert rows[cutoffs[3]]['reason']=='outside_capture_scope'
    assert rows[cutoffs[4]]['reason']=='not_in_release'
    retained=rows[cutoffs[5]]
    assert (retained['disposition'],retained['reason'],retained['retained_outcome'],retained['retained_http_status'])==(
        'retained','not_due','stored',200)


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


def test_missing_selected_profile_refuses_before_native_planning(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    selected=load(release(tmp_path,[]),tmp_path/'read')
    Path(selected['profile']).unlink()
    with pytest.raises(FileNotFoundError):
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


def test_public_profile_identity_is_rechecked_before_native_planning(tmp_path):
    from congress_api.acquisition.capture_scheduler import load_release,plan_queue
    root=release(tmp_path,[])
    selected=load_release(pointer='https://public.fixture/current.json',session=PublicSession(root),work=tmp_path/'read')
    with Path(selected['profile']).open('ab') as profile:profile.write(b' changed')
    with pytest.raises(ValueError,match='identity|size'):
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


def test_concurrent_workers_respect_budgets_and_create_unique_receipts(tmp_path):
    urls=[f'https://fixture.test/doc-{i}.pdf' for i in range(12)]
    rows=[dict(requested_url=u,attempts=0) for u in urls]
    responses={u:(200,f'%PDF-1.7\ncontent-{i}\n%%EOF'.encode(),{'content-type':'application/pdf'}) for i,u in enumerate(urls)}
    result,adapter,raw=run_fixture(tmp_path,rows,responses,workers=4)
    assert result['captures']==12 and result['requests']==12 and len(result['receipts'])==12
    assert len(set(result['receipts']))==12
    assert result['stop_reason']=='queue_empty'
    assert result['spool_reserved_bound']<=result['budgets']['spool']
    assert not list((tmp_path/'capture').rglob('*.body'))


def test_undated_stored_state_has_lower_priority_than_due_failures(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    root=release(tmp_path,[
        dict(requested_url='https://fixture.test/undated-stored',attempts=1,
             last_outcome='stored',next_attempt_at=None),
        dict(requested_url='https://fixture.test/due-failed',attempts=1,
             last_outcome='failed',next_attempt_at=datetime(2026,10,1,tzinfo=timezone.utc)),
    ])
    selected=load(root,tmp_path/'read')
    plan=plan_queue(selected,engine=engine(),work=tmp_path/'plan',as_of=ASOF,request_budget=10)
    rows=pq.read_table(plan['queue']).to_pylist()
    assert [r['requested_url'] for r in rows]==['https://fixture.test/due-failed','https://fixture.test/undated-stored']
    assert [r['priority'] for r in rows]==[2,3]


def test_keyed_states_cache_reused_across_discovery_and_cutoff_report(tmp_path):
    result,adapter,raw=run_fixture(tmp_path,[dict(requested_url='https://fixture.test/a',attempts=0)],{
        'https://fixture.test/a':(200,b'<html><a href="/b">b</a></html>',{'content-type':'text/html'}),
        'https://fixture.test/b':(200,b'%PDF-1.7\n%%EOF',{})},
        cutoff_urls=['https://fixture.test/a'])
    assert result['captures']==2
    cache_file=tmp_path/'capture'/'plan-0'/'keyed_states.parquet'
    assert cache_file.is_file()
    plan1_job=json.loads((tmp_path/'capture'/'plan-1'/'job.json').read_text())
    cutoff_job=json.loads((tmp_path/'capture'/'cutoff-report'/'job.json').read_text())
    assert any(inp['name']=='keyed_states' for inp in plan1_job['inputs'])
    assert not any(inp['name']=='states' for inp in plan1_job['inputs'])
    assert any(inp['name']=='keyed_states' for inp in cutoff_job['inputs'])




def test_campaign_queue_uses_exact_membership_and_feedback(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    from congress_shared.campaign import load_campaign
    targets=['https://fixture.test/eligible','https://fixture.test/satisfied','https://fixture.test/new']
    root=release(tmp_path,[dict(requested_url=url,attempts=0) for url in targets[:2]]+
                 [dict(requested_url='https://fixture.test/unrelated',attempts=0)])
    table=pq.read_table(root/'url_state.parquet')
    for name,values in [('capture_disposition',['eligible','satisfied','eligible']),
                        ('capture_reason',['pending','accepted','pending']),
                        ('capture_decision_id',[None,'decision-1',None])]:
        table=table.append_column(name,pa.array(values,type=pa.string()))
    pq.write_table(table,root/'url_state.parquet')
    requirements=tmp_path/'requirements.parquet'
    pq.write_table(pa.table({'original_url':targets,'target_requirement':['requested_content']*3,
                             'acceptance_policy':['policy']*3}),requirements)
    target=tmp_path/'targets.parquet';candidate=tmp_path/'candidates.parquet'
    pq.write_table(pa.table({'target_url':targets}),target)
    pq.write_table(pa.table({'target_url':pa.array([],type=pa.string()),
                             'candidate_url':pa.array([],type=pa.string())}),candidate)
    profile=json.loads((root/'capture_profile.json').read_text())
    profile.update(version=2,recovery_policy={'acceptance_policy':'policy',
                   'requirements_sha256':hashlib.sha256(requirements.read_bytes()).hexdigest()})
    (root/'capture_profile.json').write_text(json.dumps(profile));write_manifest(root)
    def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    descriptor=tmp_path/'campaign.json'
    descriptor.write_text(json.dumps(dict(version=1,campaign_id='test',requirement='requested_content',
        tables={'targets':pin(target),'candidates':pin(candidate),'requirements':pin(requirements)},
        target_table='targets',candidate_table='candidates')))
    campaign=load_campaign(descriptor)
    result=plan_queue(load(root,tmp_path/'read-campaign'),engine=engine(),work=tmp_path/'campaign-plan',
                      as_of=ASOF,request_budget=10,campaign=campaign)
    assert {row['requested_url'] for row in pq.read_table(result['queue']).to_pylist()} == {targets[0],targets[2]}


def test_pattern_family_does_not_call_dns_resolver(tmp_path):
    from congress_api.acquisition.capture_scheduler import CapturePolicy
    scope_file = tmp_path / 'capture_scope.json'
    scope_file.write_text(json.dumps(dict(
        version=1,
        entries=[dict(
            family='committee_documents',
            patterns=[r'https://(?:[a-z0-9-]+\.)*house\.gov/download/[^#]*'],
            exclusions=[r'.*&download=1$'],
        )],
    )))
    calls = []
    def fail_resolve(host):
        calls.append(host)
        raise OSError('offline')
    policy = CapturePolicy(scope_file, resolve=fail_resolve)
    assert len(policy.digest) == 64
    assert policy.pattern_family('https://selectcommittee.house.gov/download/doc.pdf?download=1') == 'committee_documents'
    assert policy.pattern_family('https://selectcommittee.house.gov/download/doc.pdf&download=1') is None
    assert policy.pattern_family('http://selectcommittee.house.gov/download/doc.pdf') is None
    assert calls == []
    assert policy.family('https://selectcommittee.house.gov/download/doc.pdf?download=1') is None
    assert calls == ['selectcommittee.house.gov']


def test_queue_repairs_amp_download_and_prefers_in_scope_https(tmp_path):
    from congress_api.acquisition.capture_scheduler import plan_queue
    from congress_shared.campaign import load_campaign
    entries = [dict(
        family='committee_documents',
        patterns=[r'https://(?:[a-z0-9-]+\.)*house\.gov/(?:download|files)/[^#]*'],
        exclusions=[r'.*&download=1$'],
    )]
    amp = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'
    good = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'
    http_url = 'http://appropriations.house.gov/files/report.pdf'
    https_url = 'https://appropriations.house.gov/files/report.pdf'

    # 1. Lone &download=1 seed is repaired to ?download=1
    w1 = tmp_path / 'lone_amp'
    w1.mkdir()
    r1 = release(w1, [], entries=entries)
    s1 = w1 / 'seeds.json'
    s1.write_text(json.dumps({'urls': [amp, http_url, https_url]}))
    q1 = plan_queue(load(r1, w1 / 'read'), engine=engine(), work=w1 / 'plan', as_of=ASOF, request_budget=10, seed_inventories=[s1])
    assert {r['requested_url'] for r in pq.read_table(q1['queue']).to_pylist()} == {good, https_url}

    # 2. Existing failed state with &download=1 is substituted by repaired ?download=1 in campaign mode
    w2 = tmp_path / 'campaign_amp'
    w2.mkdir()
    r2 = release(w2, [dict(
        requested_url=amp,
        attempts=1,
        last_status=404,
        last_outcome='http_status',
        next_attempt_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )], entries=entries)
    table = pq.read_table(r2 / 'url_state.parquet')
    for name, values in [('capture_disposition', ['eligible']), ('capture_reason', ['pending']), ('capture_decision_id', [None])]:
        table = table.append_column(name, pa.array(values, type=pa.string()))
    pq.write_table(table, r2 / 'url_state.parquet')
    req = w2 / 'requirements.parquet'
    tgt = w2 / 'targets.parquet'
    cand = w2 / 'candidates.parquet'
    pq.write_table(pa.table({'original_url': [amp], 'target_requirement': ['historical_exact'], 'acceptance_policy': ['policy']}), req)
    pq.write_table(pa.table({'target_url': [amp]}), tgt)
    pq.write_table(pa.table({'target_url': [amp], 'candidate_url': [good]}), cand)
    profile = json.loads((r2 / 'capture_profile.json').read_text())
    profile.update(version=2, recovery_policy={'acceptance_policy': 'policy', 'requirements_sha256': hashlib.sha256(req.read_bytes()).hexdigest()})
    (r2 / 'capture_profile.json').write_text(json.dumps(profile))
    write_manifest(r2)
    def pin(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    desc = w2 / 'campaign.json'
    desc.write_text(json.dumps(dict(
        version=1,
        campaign_id='amp-repair',
        requirement='historical_exact',
        tables={'targets': pin(tgt), 'candidates': pin(cand), 'requirements': pin(req)},
        target_table='targets',
        candidate_table='candidates',
    )))
    q2 = plan_queue(load(r2, w2 / 'read'), engine=engine(), work=w2 / 'plan', as_of=ASOF, request_budget=10, campaign=load_campaign(desc))
    assert [r['requested_url'] for r in pq.read_table(q2['queue']).to_pylist()] == [good]



# Work Item 3: retained-address scenarios (docs/experiments/url-normalization-validation-20261031
# evidence/scheduler-results.json) run against the real capture scope and URL rules.
PROJECT=Path(__file__).resolve().parents[3]
SCOPE_ENTRIES=json.loads((PROJECT/'model/registries/capture-scope.json').read_text())['entries']
AMP='https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'
GOOD='https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'
HTTP='http://docs.house.gov/billsthisweek/20130304/BILLS-113hr933ih.xml'
HTTPS='https://docs.house.gov/billsthisweek/20130304/BILLS-113hr933ih.xml'
WSTATE='https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-118-IF00-Wstate-A.pdf'
GOVINFO='https://www.govinfo.gov/content/pkg/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345.pdf'
RETAINED_ASOF='2026-10-31T23:59:59Z'
PAST=datetime(2026,1,1,tzinfo=timezone.utc)
FUTURE=datetime(2027,1,1,tzinfo=timezone.utc)
AMP_STATE=dict(requested_url=AMP,attempts=0,last_attempt=None,last_status=None,last_outcome=None,last_good_at=None,
    next_attempt_at=None,capture_disposition='eligible',capture_reason='no_satisfying_recovery',capture_decision_id=None)
HTTP_STATES=[dict(requested_url=url,attempts=1,last_attempt=stamp,last_status=200,last_outcome='stored',last_good_at=stamp,
    next_attempt_at=None,capture_disposition='eligible',capture_reason='no_satisfying_recovery',capture_decision_id=None)
    for url,stamp in ((HTTP,datetime(2026,9,29,2,19,12,326567,tzinfo=timezone.utc)),
                      (HTTPS,datetime(2026,10,2,22,40,55,66127,tzinfo=timezone.utc)))]


@pytest.mark.parametrize('budget,fail_replan',[(1,False),(2,False),(2,True)])
def test_reviewed_ashley_download_keeps_discovered_and_attempted_addresses(tmp_path,monkeypatch,budget,fail_replan):
    from congress_api.acquisition import capture_scheduler
    base=AMP.split('&')[0]
    selected=load(release(tmp_path,[dict(requested_url=base,attempts=0)],entries=SCOPE_ENTRIES),tmp_path/'read')
    adapter=Adapter({base:(200,f'<html><body><a href="{AMP}">Download</a></body></html>'.encode(),{}),
                     GOOD:(404,b'not a testimony',{})})
    raw=tmp_path/'raw'
    options=dict(engine=engine(),work=tmp_path/'capture',as_of=ASOF,
        request_budget=budget,byte_budget=1<<28,spool_budget=1<<28,store=BodyStore(LocalAdapter(raw)),
        identity=IDENTITY,direct=adapter,resolve=lambda _:['8.8.8.8'],pace=lambda *_:None,
        archive_limits=LIMITS,discover=fixture_discover,cutoff_urls=[AMP])
    if fail_replan:
        original=capture_scheduler.json_input
        def fail_discovery_input(work,name,records,**fields):
            if name=='discovered-1':
                raise OSError('planted replan input failure')
            return original(work,name,records,**fields)
        monkeypatch.setattr(capture_scheduler,'json_input',fail_discovery_input)
        with pytest.raises(OSError,match='planted replan input failure'):
            capture_scheduler.run_capture(selected,**options)
        result=json.loads((options['work']/'summary.json').read_text())
    else:
        result=capture_scheduler.run_capture(selected,**options)
    [row]=result['cutoffs']
    assert row['requested_url']==row['discovered_url']==AMP
    if budget==1 or fail_replan:
        assert adapter.calls==[base]
        assert row['disposition']=='deferred' and row['reason']==('error' if fail_replan else 'request_budget')
        assert row['candidate_url'] is None and row['receipt_key'] is None
    else:
        assert adapter.calls==[base,GOOD]
        assert row['disposition']=='attempted' and row['candidate_url']==GOOD
        assert (row['outcome'],row['http_status'])==('failed',404)
        with gzip.open(raw/row['receipt_key'],'rt') as source:
            receipt=json.load(source)
        assert receipt['requested_url']==GOOD
        assert [item['url'] for item in receipt['source_context']['observations']]==[AMP]


def _attempted(path,urls):
    with gzip.open(path,'wt') as out:
        for url in urls:out.write(json.dumps(dict(url=url,attempted=True,complete=True,outcome='http_status',
            http_status=404,error_type=None))+'\n')
    return path


def _plan(work,states,seeds=(),*,targets=None,candidates=(),requirements=None,recovery=False,attempted=None,as_of=RETAINED_ASOF):
    """Plan one queue over the real scope; return (queue rows, release id, campaign)."""
    from congress_api.acquisition.capture_scheduler import plan_queue
    from congress_shared.campaign import load_campaign
    work.mkdir(parents=True,exist_ok=True)
    root=release(work,states,entries=SCOPE_ENTRIES)
    campaign=None
    if recovery or targets is not None:
        table=pq.read_table(root/'url_state.parquet')
        for name,default in (('capture_disposition','eligible'),('capture_reason','pending'),('capture_decision_id',None)):
            table=table.append_column(name,pa.array([row.get(name,default) for row in states],type=pa.string()))
        pq.write_table(table,root/'url_state.parquet')
        originals=list(targets or []) if requirements is None else list(requirements)
        req=work/'requirements.parquet'
        pq.write_table(pa.table({'original_url':pa.array(originals,type=pa.string()),
            'target_requirement':pa.array(['historical_exact']*len(originals),type=pa.string()),
            'acceptance_policy':pa.array(['policy']*len(originals),type=pa.string())}),req)
        profile=json.loads((root/'capture_profile.json').read_text())
        profile.update(version=2,recovery_policy={'acceptance_policy':'policy',
            'requirements_sha256':hashlib.sha256(req.read_bytes()).hexdigest()})
        (root/'capture_profile.json').write_text(json.dumps(profile));write_manifest(root)
        if targets is not None:
            tgt=work/'targets.parquet';cand=work/'candidates.parquet'
            pq.write_table(pa.table({'target_url':pa.array(list(targets),type=pa.string())}),tgt)
            pq.write_table(pa.table({'target_url':pa.array([t for t,_ in candidates],type=pa.string()),
                'candidate_url':pa.array([c for _,c in candidates],type=pa.string())}),cand)
            def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            descriptor=work/'campaign.json'
            descriptor.write_text(json.dumps(dict(version=1,campaign_id='work-item-3',requirement='historical_exact',
                tables={'targets':pin(tgt),'candidates':pin(cand),'requirements':pin(req)},
                target_table='targets',candidate_table='candidates')))
            campaign=load_campaign(descriptor)
    seed=work/'seeds.json';seed.write_text(json.dumps({'urls':list(seeds)}))
    selected=load(root,work/'read')
    result=plan_queue(selected,engine=engine(),work=work/'plan',as_of=as_of,request_budget=20,
        seed_inventories=[seed],campaign=campaign,attempted=attempted)
    return pq.read_table(result['queue']).to_pylist(),selected,campaign


def _observed(row):
    return [json.loads(value)[:2] for value in row['observations']]


@pytest.mark.parametrize('name,states,seeds,campaign,expected,observed',[
    ('mixed_amp_seeds',[],[AMP,GOOD],False,[(GOOD,0)],[[AMP,'seeds.json'],[GOOD,'seeds.json']]),
    ('lone_amp_seed',[],[AMP],False,[(GOOD,0)],[[AMP,'seeds.json']]),
    ('existing_bad_state',[AMP_STATE],[GOOD],False,[(GOOD,0)],[[GOOD,'seeds.json']]),
    ('mixed_http_seeds',[],[HTTP,HTTPS],False,[(HTTPS,0)],[[HTTP,'seeds.json'],[HTTPS,'seeds.json']]),
    ('existing_http_states',HTTP_STATES,[],False,[(HTTPS,3)],[[HTTPS,'release']]),
    ('campaign_actual',[AMP_STATE],[GOOD],True,[(GOOD,0)],[[AMP,'campaign'],[GOOD,'seeds.json']]),
    # Same retained inputs; native substitution keeps the repaired address inside campaign membership.
    ('campaign_naive_substitution',[AMP_STATE],[GOOD],True,[(GOOD,0)],[[AMP,'campaign'],[GOOD,'seeds.json']]),
])
def test_retained_address_scenarios(tmp_path,name,states,seeds,campaign,expected,observed):
    rows,selected,_=_plan(tmp_path/name,states,seeds,targets=[AMP] if campaign else None,
        candidates=[(AMP,GOOD)] if campaign else ())
    assert [(row['requested_url'],row['priority']) for row in rows]==expected
    assert all(row['family']=='documents' for row in rows)
    release_source='release:'+selected['release_id']
    assert [[url,'release' if source==release_source else source] for url,source in _observed(rows[0])]==observed


@pytest.mark.parametrize('outcome,status,next_attempt_at,expected',[
    ('stored',200,FUTURE,[]),('failed',404,FUTURE,[]),('stored',200,None,[(GOOD,3)])])
def test_stale_failed_amp_row_does_not_preempt_repair_state(tmp_path,outcome,status,next_attempt_at,expected):
    from congress_api.acquisition.capture_scheduler import cutoff_report
    rows,selected,_=_plan(tmp_path,[
        dict(requested_url=AMP,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=PAST),
        dict(requested_url=GOOD,attempts=1,last_status=status,last_outcome=outcome,next_attempt_at=next_attempt_at)])
    assert [(row['requested_url'],row['priority']) for row in rows]==expected
    if next_attempt_at is not None:
        [report]=cutoff_report(selected,urls=[AMP],attempted=tmp_path/'no-attempts',engine=engine(),
            work=tmp_path/'report',as_of=RETAINED_ASOF,stop_reason='queue_empty')
        assert report['disposition']==('retained' if outcome=='stored' else 'deferred')
        assert (report['reason'],report['state_url'],report['retained_http_status'])==('not_due',GOOD,status)


@pytest.mark.parametrize('target,candidate',[(AMP,GOOD),(WSTATE,GOVINFO)])
def test_satisfied_target_suppresses_its_eligible_candidates(tmp_path,target,candidate):
    rows,_,_=_plan(tmp_path,[
        dict(requested_url=target,attempts=1,last_outcome='stored',capture_disposition='satisfied',
             capture_reason='accepted',capture_decision_id='decision-1'),
        dict(requested_url=candidate,attempts=0)],targets=[target],candidates=[(target,candidate)])
    assert rows==[]


def test_out_of_scope_http_state_moves_to_in_scope_https_seed(tmp_path):
    from congress_api.acquisition.capture_scheduler import cutoff_report
    from congress_api.retention.provenance import json_input
    rows,selected,_=_plan(tmp_path,[dict(requested_url=HTTP,attempts=1,last_status=404,last_outcome='http_status',
        next_attempt_at=PAST)],[HTTPS])
    assert [(row['requested_url'],row['priority']) for row in rows]==[(HTTPS,2)]
    assert _observed(rows[0])==[[HTTPS,'seeds.json']]
    discovery=json_input(tmp_path,'discovery',[dict(href=HTTPS,context=HTTPS,base_href=None)],
        href='Utf8',context='Utf8',base_href='Utf8')
    [report]=cutoff_report(selected,urls=[HTTP],attempted=tmp_path/'no-attempts',engine=engine(),
        work=tmp_path/'report',as_of=RETAINED_ASOF,stop_reason='request_budget',discovery_files=discovery['files'])
    assert (report['disposition'],report['reason'],report['discovered_url'])==('deferred','request_budget',HTTPS)


def test_state_only_repair_keeps_original_address_in_observations(tmp_path):
    rows,selected,_=_plan(tmp_path,[dict(requested_url=AMP,attempts=1,last_status=404,last_outcome='http_status',
        next_attempt_at=PAST)])
    assert [(row['requested_url'],row['priority']) for row in rows]==[(GOOD,2)]
    assert _observed(rows[0])==[[AMP,'release:'+selected['release_id']]]


def test_cross_key_campaign_candidate_is_suppressed_after_attempt(tmp_path):
    from congress_api.acquisition.capture_scheduler import cutoff_report
    states=[dict(requested_url=WSTATE,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=PAST)]
    rows,_,_=_plan(tmp_path/'first',states,targets=[WSTATE],candidates=[(WSTATE,GOVINFO)])
    assert [row['requested_url'] for row in rows]==[GOVINFO]
    attempted=_attempted(tmp_path/'attempted.jsonl.gz',[GOVINFO])
    rows,selected,campaign=_plan(tmp_path/'replan',states,targets=[WSTATE],candidates=[(WSTATE,GOVINFO)],attempted=attempted)
    assert rows==[]
    [report]=cutoff_report(selected,urls=[WSTATE],attempted=attempted,engine=engine(),work=tmp_path/'cutoff',
        as_of=RETAINED_ASOF,stop_reason='queue_empty',campaign=campaign)
    assert report['disposition']=='attempted' and report['http_status']==404


def test_trimmed_space_repair_is_suppressed_after_attempt(tmp_path):
    spaced='https://democrats-science.house.gov/uploads/report.pdf%20'
    trimmed='https://democrats-science.house.gov/uploads/report.pdf'
    states=[dict(requested_url=spaced,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=PAST)]
    rows,_,_=_plan(tmp_path/'first',states)
    assert [row['requested_url'] for row in rows]==[trimmed]
    rows,_,_=_plan(tmp_path/'replan',states,attempted=_attempted(tmp_path/'attempted.jsonl.gz',[trimmed]))
    assert rows==[]


@pytest.mark.parametrize('reuse_keyed_states',[False,True])
def test_reviewed_trimmed_address_reports_its_own_future_retry(tmp_path,reuse_keyed_states):
    from congress_api.acquisition.capture_scheduler import cutoff_report,plan_queue

    trimmed='https://democrats-science.house.gov/uploads/report.pdf'
    observed=trimmed+'%20'
    root=release(tmp_path,[
        dict(requested_url=observed,attempts=1,last_status=404,last_outcome='failed',next_attempt_at=PAST),
        dict(requested_url=trimmed,attempts=1,last_status=503,last_outcome='retry_later',next_attempt_at=FUTURE),
    ],entries=SCOPE_ENTRIES)
    selected=load(root,tmp_path/'read')
    native=engine()
    plan_work=tmp_path/'plan'
    keyed_states=plan_work/'keyed_states.parquet'
    plan=plan_queue(selected,engine=native,work=plan_work,as_of=RETAINED_ASOF,
        request_budget=20,cutoff_urls=[observed],_keyed_states_cache=keyed_states)
    assert pq.read_metadata(plan['queue']).num_rows==0
    assert len(set(pq.read_table(keyed_states,columns=['url_key']).column(0).to_pylist()))==2

    [report]=cutoff_report(selected,urls=[observed],attempted=tmp_path/'no-attempts',
        engine=native,work=tmp_path/'report',as_of=RETAINED_ASOF,stop_reason='queue_empty',
        _keyed_states_cache=keyed_states if reuse_keyed_states else None)
    expected=dict(requested_url=observed,state_url=trimmed,disposition='deferred',reason='not_due',
        retained_http_status=503,retained_outcome='retry_later',candidate_url=None,receipt_key=None)
    assert {name:report[name] for name in expected}==expected
    assert datetime.fromisoformat(report['next_attempt_at'])==FUTURE


@pytest.mark.parametrize('seed,expected',[
    ('https://www.judiciary.senate.gov/404?notfound=download/01/06/2026/benton-sjq',
     'https://www.judiciary.senate.gov/download/01/06/2026/benton-sjq'),
    ('https://www.judiciary.senate.gov/404?notfound=%2Fdownload%2Fbenton%20testimony.pdf#main',
     'https://www.judiciary.senate.gov/download/benton%20testimony.pdf'),
    ('https://www.foreign.senate.gov/download/smith-testimony&download=1',
     'https://www.foreign.senate.gov/download/smith-testimony?download=1'),
])
def test_lone_senate_seed_is_repaired_from_bound_rules(tmp_path,seed,expected):
    rows,_,_=_plan(tmp_path,[],[seed])
    assert [(row['requested_url'],row['priority']) for row in rows]==[(expected,0)]
    assert _observed(rows[0])==[[seed,'seeds.json']]


@pytest.mark.parametrize('next_attempt_at',[None,FUTURE])
def test_stored_html_wrapper_amp_row_is_repaired_once(tmp_path,next_attempt_at):
    wrapper=dict(requested_url=AMP,attempts=1,last_status=200,last_outcome='stored',next_attempt_at=next_attempt_at)
    rows,selected,_=_plan(tmp_path/'eligible',[wrapper],recovery=True)
    assert [(row['requested_url'],row['priority']) for row in rows]==[(GOOD,2)]
    assert _observed(rows[0])==[[AMP,'release:'+selected['release_id']]]
    stored=dict(requested_url=GOOD,attempts=1,last_status=200,last_outcome='stored',next_attempt_at=FUTURE)
    rows,_,_=_plan(tmp_path/'repaired',[wrapper,stored],recovery=True)
    assert rows==[]


def test_campaign_target_without_requirement_is_refused(tmp_path):
    with pytest.raises(ValueError,match='campaign membership'):
        _plan(tmp_path,[dict(AMP_STATE)],targets=[AMP,WSTATE],requirements=[AMP])


def test_address_repair_rules_are_bound_from_the_url_rule_registry():
    from congress_api.acquisition.capture_scheduler import ADDRESS_REPAIR_RULES
    rules={rule['id']:rule for rule in json.loads((PROJECT/'model/registries/url-rules.json').read_text())}
    assert all(rules[name]['kind']=='wrapper' and rules[name]['decoder'] in {'none','percent'} for name in ADDRESS_REPAIR_RULES)
    assert '(?:house|senate)' in rules['download-ampersand-query']['pattern']


def test_static_scope_match_is_shared_and_resolver_free():
    from congress_api.acquisition.fetcher import CaptureScope
    def fail(host):raise AssertionError(host)
    scope=CaptureScope([r'https://fixture\.test/[^#]*'],[r'\.css$'],resolve=fail)
    assert scope.matches_static('https://fixture.test/a.pdf')
    assert not scope.matches_static('https://fixture.test/a.css')
    assert not scope.matches_static('https://user:secret@fixture.test/a.pdf')
    assert not scope.matches_static('http://fixture.test/a.pdf')
    assert not scope.matches_static('https://[::1')


def test_satisfied_row_suppresses_other_spellings_of_its_key(tmp_path):
    variant=GOVINFO.replace('https://www.','https://')
    rows,_,_=_plan(tmp_path,[
        dict(requested_url=GOVINFO,attempts=1,last_outcome='stored',capture_disposition='satisfied',
             capture_reason='accepted',capture_decision_id='decision-1'),
        dict(requested_url=variant,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=PAST)],recovery=True)
    assert rows==[]


def test_failed_first_campaign_candidate_falls_through_to_untried_second_candidate(tmp_path):
    """R3-F2: an already-attempted campaign candidate with its own state row must not starve an untried candidate."""
    cand_a='https://www.govinfo.gov/content/pkg/CHRG-118hhrg00001/pdf/CHRG-118hhrg00001.pdf'
    cand_b='https://www.govinfo.gov/content/pkg/CHRG-118hhrg99999/pdf/CHRG-118hhrg99999.pdf'
    states=[
        dict(requested_url=WSTATE,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=PAST,
             capture_disposition='eligible',capture_reason='no_accepted_recovery',capture_decision_id='d-w'),
        dict(requested_url=cand_a,attempts=1,last_status=404,last_outcome='http_status',next_attempt_at=FUTURE,
             capture_disposition='eligible',capture_reason='no_accepted_recovery',capture_decision_id='d-a'),
    ]
    rows,_,_=_plan(tmp_path,states,targets=[WSTATE],
        candidates=[(WSTATE,cand_a),(WSTATE,cand_b)],requirements=[WSTATE])
    assert [row['requested_url'] for row in rows]==[cand_b]
    assert _observed(rows[0])==[[WSTATE,'campaign']]

