"""Retained raw imports reach the actual publisher, site reader and scheduler."""
import gzip
from hashlib import md5,sha256
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec,versions
from congress_api.retention.provenance import file_pin,parquet_output,run_job,write_records
from docspec_client.client import NativeDatasets
from test_archive_controller import Runtime as NativeTransport
from test_archive_publish import Store
from test_archive_publish_job import publish_spec,remote_config

ROOT=Path(__file__).parents[3]
STAMP='2026-10-27T12:00:00Z'


def accepted_campaign_import(tmp_path,*,writer,store,source,body,raw):
    """Feed pinned native metadata and an actual body receipt to acceptance."""
    from corpus_recovery.campaign import import_candidate
    target=source['original_url'];candidate=source['recovered_url']
    operation_name=sha256(target.encode()).hexdigest()[:16]
    request_root=tmp_path/('acceptance-'+operation_name);request_root.mkdir()
    metadata=request_root/'metadata.json'
    metadata.write_text(json.dumps(dict(target=dict(url=target,document='REPORT-1',version='2019'),
        candidate=dict(url=candidate,document='REPORT-1',version='2019'))))
    def pin(path):return dict(path=str(path),sha256=file_pin(path)['sha256'])
    def identity(pointer):return dict(source=pin(metadata),source_url='https://publisher.test/native-record.json',
        record_pointer=pointer,url_field='url',identifier_fields=dict(document='document',version='version'),
        required_fields=['document','version'],reviewed_by='authored test metadata',reviewed_at=STAMP)
    targets=request_root/'targets.parquet';candidates=request_root/'candidates.parquet'
    pq.write_table(pa.Table.from_pylist([dict(target_url=target)]),targets)
    pq.write_table(pa.Table.from_pylist([dict(target_url=target,candidate_url=candidate)]),candidates)
    descriptor=request_root/'campaign.json';descriptor.write_text(json.dumps(dict(version=1,campaign_id='journey',
        requirement='historical_exact',tables=dict(targets=pin(targets),candidates=pin(candidates)),
        target_table='targets',candidate_table='candidates')))
    from corpus_recovery.reconcile import import_retained
    source_key,_=import_retained(writer,source)
    request=request_root/'request.json';request.write_text(json.dumps(dict(target=identity('/target'),
        candidate=identity('/candidate'),body=pin(body),receipt=pin(raw/source_key),
        relationship='recovered_document',decided_at=STAMP,decided_by='authored test acceptance')))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        imported=import_candidate(descriptor,request,output=tmp_path/'accepted-operations'/operation_name,engine=engine,writer=writer,store=store)
    assert imported['status']=='accepted'
    return imported


def retained_model(tmp_path):
    """Use the common raw writer and all three real lake producers."""
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    from congress_api.retention.receipt_writer import ReceiptWriter
    from corpus_recovery.reconcile import import_retained
    from congress_api.models.raw_fetch import FetchAttempt,FetchResult
    from congress_api.lake import readings,filenames
    from congress_api.lake.captures import stage_captures
    seed=tmp_path/'seed';seed.mkdir();_,digest,html=real_model_spec(seed)
    raw=seed/'raw';store=BodyStore(LocalAdapter(raw))
    writer=ReceiptWriter(store,identity=dict(job='journey',commit='a'*40,lockfile_digest='b'*64),
        run_id='journey',write_date='2026-10-27',archive_limits=None)
    names=['exact','wrong','withdrawn','requested','current','alias','live']
    urls={name:'https://docs.house.gov/meetings/TEST/20261027/'+name+'.html' for name in names}
    urls['stream']='https://docs.house.gov/meetings/TEST/20261027/stream.mp4'
    urls['caption']='https://www-senate-gov-media-srs.akamaized.net/hls/event.vtt'
    for name,url in urls.items():
        writer.write(FetchResult(FetchAttempt(url,url,STAMP,'direct',404,None,{},(),True,None)),
            family='senate/captions' if name=='caption' else 'documents')
    body=tmp_path/'recovered.html';html=html.replace(b'<body>',b'<body class="field-name-body">');body.write_bytes(html);digest=sha256(html).hexdigest()
    decisions=[];requirements=[];producer_keys=[]
    for name,requirement,kind in [('exact','historical_exact','recovered_document'),
            ('wrong','historical_exact','official_updated_revision_available'),
            ('withdrawn','historical_exact','recovered_document'),
            ('requested','requested_content','requested_content_in_official_hearing'),
            ('current','current_official_counterpart','official_updated_revision_available'),
            ('alias','historical_exact','recovered_document'),
            ('live','historical_exact','recovered_document')]:
        source=dict(original_url=urls[name],recovered_url='https://retained.test/'+name+'.html',
            body_path=str(body),body_sha256=digest,retrieved_at='2019-10-01T12:00:00Z',
            media_type='text/html',category=kind,match_basis='verified_archive_capture',
            imported_at=STAMP,evidence_sha256='e'*64)
        if name in ('exact','live'):
            imported=accepted_campaign_import(tmp_path,writer=writer,store=store,source=source,body=body,raw=raw)
            producer_keys.append(imported['provenance_key'])
        else:import_retained(writer,source)
        row=dict(id=name,original_url=urls[name],recovered_url=source['recovered_url'],recovered_filename=None,
            body_sha256=digest,kind=kind,match_basis=source['match_basis'],evidence_sha256='e'*64,
            identity_note='Authored identity fixture',decided_by='fixture',decided_at=STAMP,supersedes=None,
            recovery_record_version=2,target_requirement=requirement,acceptance_status='accepted',
            acceptance_policy='recovery-identity-v1',qualification_sha256='f'*64)
        if name=='alias':row['original_url']=urls[name]+'?different=literal'
        if name not in ('exact','live'):decisions.append(row)
        requirements.append(dict(original_url=urls[name],target_requirement=requirement,acceptance_policy='recovery-identity-v1',
            refresh_policy='refresh_live' if name=='live' else 'historical_only'))
    decisions.append(dict(next(row for row in decisions if row['id']=='withdrawn'),id='withdrawal',kind='rejected',acceptance_status='rejected',supersedes='withdrawn'))
    provenance_key,_=write_records(store,'recoveries',decisions,timestamp='journey')
    producer_keys.append(provenance_key)
    recovery_files=[dict(key=key,path=str(raw/key)) for key in producer_keys]
    keys=sorted(path.relative_to(raw).as_posix() for path in (raw/'receipts').rglob('*.jsonl.gz'))
    work=tmp_path/'rebuilt';work.mkdir();selected=[]
    for index,key in enumerate(keys):
        path=raw/key;qualification=work/(str(index)+'-pin.json')
        qualification.write_text(json.dumps(dict(path=str(path),**file_pin(path),producer='fixture raw writer')))
        selected.append(dict(key=key,path=str(path),qualification=str(qualification)))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        captures=stage_captures(selected,engine=engine,work=work/'capture-stage')/'captures.parquet'
        inventory=work/'inventory';inventory.mkdir()
        run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
            parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            max(stored_bytes) AS stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256,stored_suffix""",['body_sha','physical_key'])])
        pages=readings.stage_once(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,
            engine=engine,work=work/'reading-stage',decided_at=STAMP)
        names=filenames.stage(captures=captures,recovery_files=recovery_files,
            engine=engine,work=work/'filename-stage',decided_at=STAMP)
    requirements_path=work/'requirements.parquet';pq.write_table(pa.Table.from_pylist(requirements),requirements_path)
    parsers,catalog=versions()
    model=dict(version=1,engine_config=os.environ['DOCSPEC_JOB_CONFIG'],parser_versions=parsers,catalog_version=catalog,
        output=str(tmp_path/'release'),scratch=str(tmp_path/'model'),recovery_files=[dict(row,**file_pin(row['path'])) for row in recovery_files],
        recovery_requirements=dict(path=str(requirements_path),**file_pin(requirements_path),acceptance_policy='recovery-identity-v1'))
    for name,path in [('captures',captures),('readings',pages['readings']),('filename_readings',names['readings'])]:
        model[name]=dict(kind='parquet',path=str(path),**file_pin(path))
    return model,raw,keys,producer_keys,urls


class JourneyStore(Store):
    def list_objects_v2(self,*,Bucket,Prefix,**kwargs):
        return dict(Contents=[dict(Key=key,ETag=md5(value).hexdigest()) for key,value in sorted(self.objects.items()) if key.startswith(Prefix)],IsTruncated=False)


def serve_store(store):
    """Expose only the actual selected pointer and published/raw object bytes."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            key=urlsplit(self.path).path.lstrip('/');data=store.objects.get(key)
            if data is None:
                self.send_response(404);self.send_header('Cache-Control','no-store');self.end_headers();return
            start=0;end=len(data)-1;status=200
            if value:=self.headers.get('Range'):
                start,end=map(int,value.removeprefix('bytes=').split('-'));status=206
            self.send_response(status)
            self.send_header('Content-Length',str(end-start+1))
            self.send_header('Cache-Control','no-store' if key.endswith('/manifest.json') and '/releases/' not in key else 'public,max-age=31536000,immutable')
            self.send_header('Access-Control-Allow-Origin','*');self.send_header('Accept-Ranges','bytes')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{len(data)}')
            self.end_headers();self.wfile.write(data[start:end+1])
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    return server,'http://127.0.0.1:'+str(server.server_port)


@pytest.mark.loopback
def test_retained_import_publish_resume_selected_reader_and_real_queue(tmp_path):
    from viewer_publication.archive_publish_job import load_spec,execute
    from congress_api.acquisition.capture_scheduler import load_release,plan_queue
    model,raw,keys,provenance_keys,urls=retained_model(tmp_path)
    value=publish_spec(tmp_path);remote=remote_config(tmp_path)
    settings=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    base=Path(os.environ['DOCSPEC_JOB_CONFIG']).parent
    for field in ['binary','limits','workspace']:
        if field in settings:settings[field]=str((base/settings[field]).resolve())
    settings.update(remote=str(remote),credentials='/unopened/fixture-credentials.json')
    runtime=tmp_path/'remote-runtime.json';runtime.write_text(json.dumps(settings));model['engine_config']=str(runtime)
    modelpath=Path(value['model_spec']['path']);modelpath.write_text(json.dumps(model))
    value.update(model_spec=dict(path=str(modelpath),**file_pin(modelpath)),receipt_keys=keys,
        provenance=[dict(key=key,etag=md5((raw/key).read_bytes()).hexdigest()) for key in sorted(provenance_keys)],site_dist=str(ROOT/'apps/site/dist'))
    targets=Path(value['targets']['path']);target=json.loads(targets.read_text())
    target['ceilings']={name:10**9 for name in target['ceilings']};targets.write_text(json.dumps(target));value['targets']=dict(path=str(targets),**file_pin(targets))
    specpath=tmp_path/'publish.json';specpath.write_text(json.dumps(value))
    store=JourneyStore()
    for path in raw.rglob('*'):
        if path.is_file():store.objects[path.relative_to(raw).as_posix()]=path.read_bytes()
    bodies={key:dict(path=str(raw/key),stored_sha256=sha256(data).hexdigest(),stored_bytes=len(data))
        for key,data in store.objects.items() if key.startswith('bodies/')}
    bodiespath=tmp_path/'bodies.json';bodiespath.write_text(json.dumps(bodies))
    server,origin=serve_store(store);commands=[];fail_once=True
    class Runtime(NativeTransport):
        def __init__(self,path):
            super().__init__(NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),store)
            self.remote=Path(json.loads(Path(path).read_text())['remote'])
        def __enter__(self):return self
        def __exit__(self,*_):self.native.close()
    def runner(command,**options):
        nonlocal fail_once
        command=list(command);commands.append(command[:3])
        if command[2]=='contract:archive':
            next_release=Path(value['contract_next_release'])
            if not next_release.exists():
                shutil.copytree(model['output'],next_release)
                scope=next_release/'capture_scope.json';scope.write_bytes(scope.read_bytes()+b'\n')
                manifest=json.loads((next_release/'manifest.json').read_text())
                entry=next(e for e in manifest['files'] if e['name']=='capture_scope.json')
                entry.update(**file_pin(scope),md5=md5(scope.read_bytes()).hexdigest())
                from viewer_publication.archive_format import release_identity
                manifest['release_id']=release_identity(1,manifest['files'])
                (next_release/'manifest.json').write_text(json.dumps(manifest))
            command.extend(['--bodies',str(bodiespath)])
        else:
            # Preserve the public command; only its external transport is local.
            command[command.index('--pointer')+1]=origin+'/viewer-publications/manifest.json'
            command[command.index('--raw')+1]=origin+'/'
            command.extend(['--local','true'])
        try:completed=subprocess.run(command,**options,capture_output=True,text=True)
        except subprocess.CalledProcessError as error:
            raise AssertionError(error.stderr) from error
        if fail_once and command[2]=='canary:archive':
            fail_once=False
            raise RuntimeError('lost canary acknowledgment after actual reader passed')
        return completed
    try:
        with pytest.raises(RuntimeError,match='lost canary acknowledgment'):
            execute(load_spec(specpath),runtime_factory=Runtime,storage_factory=lambda **_:store,process_runner=runner)
        resultpath=Path(model['scratch'])/'result.json';before=(resultpath.read_bytes(),resultpath.stat().st_mtime_ns)
        assert 'viewer-publications/manifest.json' not in store.objects
        transfer_count=sum(event[0]=='native' for event in store.events)
        value['resume']=True;specpath.write_text(json.dumps(value))
        result=execute(load_spec(specpath),runtime_factory=Runtime,storage_factory=lambda **_:store,process_runner=runner)
        assert result['status']=='published' and len(commands)==4
        assert sum(event[0]=='native' for event in store.events)==transfer_count
        assert (resultpath.read_bytes(),resultpath.stat().st_mtime_ns)==before
        settled=execute(load_spec(specpath),runtime_factory=Runtime,storage_factory=lambda **_:store,process_runner=runner)
        assert settled['status']=='release_unchanged' and len(commands)==4
        assert (resultpath.read_bytes(),resultpath.stat().st_mtime_ns)==before
        # The site reader selects the actual stored pointer and opens its saved body.
        checked=subprocess.run(['node','--expose-gc','scripts/verify-archive.mjs','--pointer',origin+'/viewer-publications/manifest.json',
            '--raw',origin+'/','--local','true','--targets',str(targets)],cwd=ROOT/'apps/site',check=True,capture_output=True,text=True,timeout=60)
        receipt=json.loads(checked.stdout);assert receipt['savedCopyChecked'] and receipt['releaseId']==result['release_id']
        import requests
        class LocalObjectTransport:
            def get(self,url,**options):return requests.get(origin+urlsplit(url).path,**options)
        selected=load_release(pointer=value['public_origin']+'/viewer-publications/manifest.json',
            session=LocalObjectTransport(),work=tmp_path/'selected')
        states={row['requested_url']:row for row in pq.read_table(selected['state']).to_pylist()}
        requirements=pq.read_table(model['recovery_requirements']['path']).to_pylist()
        assert next(row for row in requirements if row['original_url']==urls['live'])['refresh_policy']=='refresh_live'
        decisions=[json.loads(line) for row in model['recovery_files'] for line in Path(row['path']).read_text().splitlines()]
        assert any(row['original_url']==urls['live'] and row['acceptance_status']=='accepted' for row in decisions)
        expected={'exact':'satisfied','wrong':'eligible','withdrawn':'eligible','requested':'satisfied','current':'satisfied',
            'alias':'eligible','live':'eligible','stream':'excluded','caption':'eligible'}
        assert {name:states[url]['capture_disposition'] for name,url in urls.items()}==expected
        assert all(states[url]['last_status']==404 and states[url]['attempts']==1 for url in urls.values())
        with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
            plan=plan_queue(selected,engine=engine,work=tmp_path/'queue',as_of='2030-10-31T00:00:00Z',request_budget=30)
        queued={row['requested_url'] for row in pq.read_table(plan['queue']).to_pylist()}
        assert queued=={urls[name] for name,disposition in expected.items() if disposition=='eligible'}
    finally:server.shutdown();server.server_close()
