"""An early check can skip setup, never supply write authority."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import publication_preflight as preflight
import viewer_release_identity as identity


def record(value):
    raw=preflight.encoded(value)
    return {'value':value,'raw':raw,'etag':'v1','modified':'time','sha256':hashlib.sha256(raw).hexdigest()}


def fixture(accepted=None):
    full={'version':1,'implementation':'code','dependencies':'runtime','publisher_version':10}
    source=record({'catalog_id':'b'*32,'generation':'a'*32})
    manifest=record({'source_manifest':source['value'],'info':{'catalog_id':'b'*32},'files':{'filenames':{'sha256':'f'},'groups':{'sha256':'g'}}})
    recovery=record({'version':1,'catalog_id':'b'*32,'rows':1,'entries':1,'recoveries':[],'sources':[],'groups':[]})
    path='releases/'+'c'*32+'/'+'d'*32+'/viewer-v2/recovery-status.json'
    manifest_path='releases/'+'e'*32+'/manifest.json'
    pointer=record({'catalog_id':'b'*32,'publisher_version':10,'source_manifest':source['value'],'manifest':manifest_path,'full_release_inputs':full,
        'recovery':{'path':path,'bytes':len(recovery['raw']),'sha256':recovery['sha256']},
        'recovery_inputs':{'raw_manifest_sha256':source['sha256'],'viewer_manifest_sha256':manifest['sha256'],'files':{'filenames':'f','groups':'g'},'full_release_inputs':full,
            'accepted':{'present':accepted is not None,'sha256':hashlib.sha256(preflight.encoded(accepted['recoveries'] if accepted else [])).hexdigest()}}})
    class Reader:
        def __init__(self):
            self.data={'indexes/catalog.json':source,preflight.PREFIX+'manifest.json':pointer,preflight.ACCEPTED:record(accepted) if accepted is not None else None,
                preflight.PREFIX+manifest_path:manifest,preflight.PREFIX+path:recovery}
            self.calls=[];self.public_calls=[];self.after_public=None
        def read(self,key,**kwargs):
            assert not key.endswith(('.parquet','.bin'))
            self.calls.append(key)
            return deepcopy(self.data[key])
        def public(self,key,**kwargs):
            self.public_calls.append(key)
            result=self.data[preflight.PREFIX+key]['raw'],'*'
            if self.after_public:self.after_public(key)
            return result
    return Reader(),full


@pytest.mark.parametrize('accepted',[None,{'version':1,'recoveries':[]}])
def test_exact_noop_reads_only_bounded_control_and_never_grants_write_authority(accepted):
    reader,full=fixture(accepted)
    result=preflight.preflight(reader,full,publisher_version=10)
    assert result['status']=='unchanged' and result['write_authority'] is False
    assert result['publication_writes']==0 and result['table_reads']==0
    assert len(reader.calls)==8 and len(reader.public_calls)==2


@pytest.mark.parametrize('change',['builder','runtime','review','source','mapping_absence','mapping_same_count'])
def test_changed_inputs_take_validated_preparation_without_tables_or_writes(change):
    reader,full=fixture({'version':1,'recoveries':[{'original_url':'original','kind':'pdf'}]})
    if change in ('builder','review'):full=dict(full,implementation='changed-'+change)
    elif change=='runtime':full=dict(full,dependencies='changed')
    elif change=='source':reader.data['indexes/catalog.json']=record({'catalog_id':'other'})
    elif change=='mapping_absence':reader.data[preflight.ACCEPTED]=None
    else:reader.data[preflight.ACCEPTED]=record({'version':1,'recoveries':[{'original_url':'original','kind':'doc'}]})
    result=preflight.preflight(reader,full,publisher_version=10)
    assert result['status']=='preparation_required' and result['write_authority'] is False
    assert len(reader.calls)==3 and reader.public_calls==[]


@pytest.mark.parametrize('key',['indexes/catalog.json',preflight.ACCEPTED,preflight.PREFIX+'manifest.json'])
def test_advance_before_final_freshness_reads_refuses_noop(key):
    reader,full=fixture()
    def advance(path):
        if path=='manifest.json':
            if reader.data[key] is None:reader.data[key]=record({'version':1,'recoveries':[]})
            else:reader.data[key]['etag']='advanced'
    reader.after_public=advance
    with pytest.raises(ValueError,match='advanced during observation'):
        preflight.preflight(reader,full,publisher_version=10)


@pytest.mark.parametrize('raw,length,limit',[ (b'123',4,8),(b'1234',3,8),(b'123456789',None,8),(b'{}',9,8)])
def test_bounded_control_body_closes_for_bad_length_or_limit(raw,length,limit):
    class Response(io.BytesIO):
        headers={} if length is None else {'Content-Length':str(length)}
    response=Response(raw)
    with pytest.raises(ValueError):preflight.bounded(response,limit)
    assert response.closed


def test_source_hashes_reuse_only_unchanged_custody_and_docs_do_not_invalidate(tmp_path,monkeypatch):
    path=tmp_path/'apps/site/scripts/filename_helper.py';path.parent.mkdir(parents=True);path.write_text('one')
    original=identity.hashlib.file_digest;calls=[]
    def digest(stream,*a,**k):calls.append(stream.name);return original(stream,*a,**k)
    monkeypatch.setattr(identity.hashlib,'file_digest',digest)
    before=identity.source_files(tmp_path);assert identity.source_files(tmp_path)==before and len(calls)==1
    (tmp_path/'README.md').write_text('unrelated docs')
    assert identity.source_files(tmp_path)==before and len(calls)==1
    stat=path.stat();path.write_text('two');os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert identity.source_files(tmp_path)!=before and len(calls)==2


def test_locked_and_installed_runtime_share_one_fingerprint(tmp_path,monkeypatch):
    (tmp_path/'.python-version').write_text(identity.platform.python_version())
    (tmp_path/'uv.lock').write_text('version = 1\n[[package]]\nname = "pyarrow"\nversion = "25.0.1"\n')
    def version(name):
        if name=='pyarrow':return '25.0.1'
        raise identity.importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(identity.importlib.metadata,'version',version)
    assert identity.installed_runtime()==identity.locked_runtime(tmp_path)


def test_stdlib_sigv4_matches_maintained_botocore_without_sdk_at_runtime(monkeypatch):
    import botocore.auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
    now=datetime(2026,10,18,12,30,tzinfo=timezone.utc)
    request=preflight.sigv4_request('a'*32,'indexes/catalog.json','FAKEACCESS','fake-secret',now)
    monkeypatch.setattr(botocore.auth,'get_current_datetime',lambda:now)
    expected=AWSRequest(method='GET',url=request.full_url)
    botocore.auth.S3SigV4Auth(Credentials('FAKEACCESS','fake-secret'),'s3','auto').add_auth(expected)
    assert request.get_header('Authorization')==expected.headers['Authorization']
    assert request.method=='GET'


def test_early_cli_imports_without_site_packages_and_workflow_keeps_fresh_write_path():
    result=subprocess.run([sys.executable,'-S',str(ROOT/'scripts/publication_preflight.py'),'--help'],capture_output=True,text=True,check=True)
    assert '--report' in result.stdout
    import yaml
    workflow=yaml.safe_load((ROOT/'.github/workflows/publish-filename-viewer.yml').read_text())
    steps=workflow['jobs']['publish']['steps']
    early=next(i for i,s in enumerate(steps) if s.get('id')=='preflight')
    setup=next(i for i,s in enumerate(steps) if s.get('uses')=='./.github/actions/setup-python-project')
    assert early<setup and 'preparation_required' in steps[setup]['if'] and "github.event_name == 'push'" in steps[setup]['if']
    assert next(s for s in steps if s.get('id')=='prepare')['if'].find('preparation_required')>=0
    publication=next(s for s in steps if s.get('name')=='Publish accepted preparation')
    assert '--artifact-id' in publication['run'] and '--resume --resume-descriptor' in publication['run']


@pytest.mark.parametrize('key,kind',[
    ('indexes/catalog.json','manifest'),(preflight.PREFIX+'manifest.json','manifest'),
    (preflight.ACCEPTED,'accepted'),(preflight.PREFIX+'releases/'+'a'*32+'/manifest.json','manifest'),
    (preflight.PREFIX+'releases/'+'a'*32+'/'+'b'*32+'/viewer-v2/recovery-status.json','recovery')])
def test_signed_fixed_get_surface_matches_botocore_across_utc_day_boundary(monkeypatch,key,kind):
    import botocore.auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
    from datetime import timedelta
    now=datetime(2026,10,18,1,30,tzinfo=timezone(timedelta(hours=3)))
    request=preflight.sigv4_request('a'*32,key,'FAKEACCESS','fake-secret',now)
    monkeypatch.setattr(botocore.auth,'get_current_datetime',lambda:now.astimezone(timezone.utc))
    expected=AWSRequest(method='GET',url=request.full_url)
    botocore.auth.S3SigV4Auth(Credentials('FAKEACCESS','fake-secret'),'s3','auto').add_auth(expected)
    assert request.get_header('Authorization')==expected.headers['Authorization']
    assert request.get_header('X-amz-date')=='20261017T223000Z'
    assert request.get_header('X-amz-content-sha256')==hashlib.sha256(b'').hexdigest()
    assert request.full_url=='https://'+'a'*32+'.r2.cloudflarestorage.com/'+preflight.BUCKET+'/'+key
    assert request.method=='GET' and request.data is None and preflight.object_kind(key)==kind


@pytest.mark.parametrize('key',['../indexes/catalog.json','/indexes/catalog.json','indexes/catalog.json?x=1',
    'indexes/catalog.json#fragment','viewer-publications/releases/'+'A'*32+'/manifest.json',
    'viewer-publications/releases/'+'a'*32+'/filenames.parquet','raw/secret','viewer-publications/accepted.json'])
def test_adapter_refuses_unlisted_key_before_request_or_signing(key):
    reader=preflight.ReadOnlyR2('a'*32,'FAKEACCESS','fake-secret',public_url='https://congressional-viewer-data.mdeeb.workers.dev/')
    with pytest.raises(ValueError,match='allowlist'):reader.read(key)
    with pytest.raises(ValueError,match='allowlist'):reader.public(key)
    assert reader.requests==0


def test_adapter_refuses_wrong_kind_optional_source_naive_time_and_unsafe_headers():
    reader=preflight.ReadOnlyR2('a'*32,'FAKEACCESS','fake-secret',public_url='https://congressional-viewer-data.mdeeb.workers.dev/')
    with pytest.raises(ValueError,match='kind'):reader.read(preflight.ACCEPTED)
    with pytest.raises(ValueError,match='absent'):reader.read('indexes/catalog.json',optional=True)
    with pytest.raises(ValueError,match='timezone'):preflight.sigv4_request('a'*32,'indexes/catalog.json','FAKEACCESS','secret',datetime(2026,10,18))
    with pytest.raises(ValueError,match='credentials'):preflight.sigv4_request('a'*32,'indexes/catalog.json','FAKE\nACCESS','secret')
    with pytest.raises(ValueError,match='endpoint'):preflight.ReadOnlyR2('a'*32,'FAKEACCESS','secret',public_url='https://other.example/')
    assert reader.requests==0


@pytest.mark.parametrize('status',[301,302,303,307,308,403,404,429,503])
def test_http_errors_close_body_and_never_retry_or_follow_redirect(status,monkeypatch):
    import urllib.error
    reader=preflight.ReadOnlyR2('a'*32,'FAKEACCESS','fake-secret',public_url='https://congressional-viewer-data.mdeeb.workers.dev/')
    calls=[];body=io.BytesIO(b'failure')
    def fail(request,**kwargs):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url,status,'failure',{'Location':'https://elsewhere.example/'},body)
    monkeypatch.setattr(reader.opener,'open',fail)
    with pytest.raises(urllib.error.HTTPError):reader.read('indexes/catalog.json')
    assert body.closed and len(calls)==1 and reader.requests==1
    assert preflight.NoRedirects().redirect_request(None,None,status,None,None,'https://elsewhere.example/') is None


def test_optional_not_found_is_only_nonfatal_private_http_error(monkeypatch):
    import urllib.error
    reader=preflight.ReadOnlyR2('a'*32,'FAKEACCESS','fake-secret',public_url='https://congressional-viewer-data.mdeeb.workers.dev/')
    body=io.BytesIO(b'not found')
    def missing(request,**kwargs):raise urllib.error.HTTPError(request.full_url,404,'absent',{},body)
    monkeypatch.setattr(reader.opener,'open',missing)
    assert reader.read(preflight.ACCEPTED,kind='accepted',optional=True) is None
    assert body.closed and reader.requests==1


def test_locked_ijson_version_participates_in_runtime_identity(tmp_path,monkeypatch):
    (tmp_path/'.python-version').write_text(identity.platform.python_version())
    lock=tmp_path/'uv.lock'
    lock.write_text('version = 1\n[[package]]\nname = "ijson"\nversion = "3.6.0"\n')
    before=identity.locked_runtime(tmp_path)
    lock.write_text(lock.read_text().replace('3.6.0','3.6.1'))
    assert before!=identity.locked_runtime(tmp_path)


def native_fixture():
    reader, full = fixture()
    source = record(dict(version=2, selection=dict(key='indexes/native-manifests/selected.json', sha256='a'*64, bytes=50)))
    selected_identity = dict(selector_sha256=source['sha256'], selected_ref=source['value']['selection'])
    roots = dict(sources={'sha256':'source'},components={'sha256':'components'},browse={'sha256':'browse'})
    pointer = reader.data[preflight.PREFIX+'manifest.json']['value']
    pointer['source_manifest'], pointer['source_identity'] = source['value'], selected_identity
    manifest = record(dict(version=6, source_manifest=source['value'],source_identity=selected_identity,roots=roots,
                          info=dict(catalog_id='b'*32,rows=1,entries=1)))
    reader.data['indexes/catalog.json'] = source
    reader.data[preflight.PREFIX+pointer['manifest']] = manifest
    recovery = record(dict(version=2,catalog_id='b'*32,rows=1,entries=1,source_identity=selected_identity,
                           accepted=[],recoveries=[],sources=[],groups=[]))
    reader.data[preflight.PREFIX+pointer['recovery']['path']] = recovery
    pointer['recovery'].update(bytes=len(recovery['raw']),sha256=recovery['sha256'])
    pointer['recovery_inputs'].update(version=2,raw_manifest_sha256=source['sha256'],
        viewer_manifest_sha256=manifest['sha256'],source_identity=selected_identity,roots=roots)
    del pointer['recovery_inputs']['files']
    reader.data[preflight.PREFIX+'manifest.json'] = record(pointer)
    return reader,full


def test_native_noop_uses_only_control_reads_with_exact_stable_identity():
    reader,full = native_fixture()
    result = preflight.preflight(reader,full,publisher_version=10)
    assert result['status']=='unchanged' and result['table_reads']==result['publication_writes']==0
    assert len(reader.calls)==8 and len(reader.public_calls)==2


@pytest.mark.parametrize('which',['selector_hash','pointer_identity','roots','recovery_identity'])
def test_native_noop_refuses_mixed_control_bindings(which):
    reader,full = native_fixture()
    pointer = reader.data[preflight.PREFIX+'manifest.json']['value']
    if which=='pointer_identity':
        pointer['source_identity'] = dict(selector_sha256='wrong')
    elif which=='roots':
        pointer['recovery_inputs']['roots'] = {'different':True}
    elif which=='recovery_identity':
        key=preflight.PREFIX+pointer['recovery']['path']
        value=reader.data[key]['value'];value['source_identity']={'different':True};reader.data[key]=record(value)
        pointer['recovery'].update(bytes=len(reader.data[key]['raw']),sha256=reader.data[key]['sha256'])
    else:
        key=preflight.PREFIX+pointer['manifest'];value=deepcopy(reader.data[key]['value'])
        value['source_identity']['selector_sha256']='wrong';reader.data[key]=record(value)
        pointer['source_identity']=value['source_identity'];pointer['recovery_inputs']['source_identity']=value['source_identity']
        pointer['recovery_inputs']['viewer_manifest_sha256']=reader.data[key]['sha256']
    reader.data[preflight.PREFIX+'manifest.json']=record(pointer)
    with pytest.raises(ValueError,match='identity|catalog differs'):
        preflight.preflight(reader,full,publisher_version=10)
