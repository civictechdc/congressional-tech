"""Real publication adapter and maintained SDK against a bounded S3 protocol fake."""
from contextlib import contextmanager
from hashlib import md5, sha256
import http.server
import json
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from congress_shared.storage import R2Config, connect_r2
from viewer_publication import archive_multipart as multipart
from viewer_publication.archive_publish import NativeArchiveStore

pytestmark=pytest.mark.loopback

BUCKET='publication-fixture'
KEY='viewer-publications/releases/'+'a'*64+'/search_index.sqlite'


class Native:
    remote='explicit'
    def create_file(self, spec):
        raise AssertionError('Large asset reached whole-buffer native upload')


class Protocol:
    def __init__(self):
        self.events=[];self.uploads={};self.objects={};self.serial=0;self.mode=None;self.on_part=None;self.on_head=None
    def headers(self, handler, status, raw=b'', etag=None, size=None):
        handler.send_response(status)
        handler.send_header('Content-Length',str(len(raw) if size is None else size))
        handler.send_header('Connection','close')
        if etag is not None:handler.send_header('ETag',etag)
        handler.end_headers()
        if handler.command!='HEAD':handler.wfile.write(raw)
    def request(self, handler):
        path=urlsplit(handler.path);query=parse_qs(path.query,keep_blank_values=True)
        key=path.path.removeprefix('/'+BUCKET+'/')
        assert path.path.startswith('/'+BUCKET+'/viewer-publications/releases/')
        operation=(handler.command,key,dict(query));self.events.append(operation)
        remaining=int(handler.headers.get('Content-Length','0'))
        digest=md5();sha=sha256();size=0;small=[]
        upload=self.uploads.get(query.get('uploadId',[None])[0])
        while remaining:
            block=handler.rfile.read(min(65536,remaining));assert block
            remaining-=len(block);size+=len(block);digest.update(block);sha.update(block)
            if handler.command=='PUT':
                upload['sha'].update(block);upload['md5'].update(block)
            else:small.append(block)
        if handler.command=='HEAD':
            if self.on_head:self.on_head()
            value=self.objects.get(key)
            if value is None:return self.headers(handler,404)
            return self.headers(handler,200,etag=value['etag'],size=value['size'])
        if handler.command=='DELETE':
            if self.mode=='abort-error':return self.headers(handler,500,b'<Error><Code>InternalError</Code></Error>')
            self.uploads.pop(query['uploadId'][0],None)
            return self.headers(handler,204)
        if handler.command=='POST' and 'uploads' in query:
            self.serial+=1;uid='owned-upload-'+str(self.serial)
            assert handler.headers.get('Content-Type')=='application/vnd.sqlite3'
            assert handler.headers.get('Cache-Control')=='public,max-age=31536000,immutable'
            self.uploads[uid]=dict(parts=[],sha=sha256(),md5=md5())
            return self.headers(handler,200,('<InitiateMultipartUploadResult><UploadId>'+uid+'</UploadId></InitiateMultipartUploadResult>').encode())
        if handler.command=='PUT':
            assert size<=multipart.PART_BYTES
            from base64 import b64encode
            assert handler.headers.get('Content-MD5')==b64encode(digest.digest()).decode()
            if self.on_part:self.on_part(len(upload['parts'])+1)
            if self.mode in ('part-error','abort-error'):return self.headers(handler,500,b'<Error><Code>InternalError</Code></Error>')
            upload['parts'].append(dict(size=size,md5=digest.digest()))
            etag='"'+('0'*32 if self.mode=='part-etag' else digest.hexdigest())+'"'
            if self.mode=='malformed-etag':etag='"'+etag+'"'
            return self.headers(handler,200,etag=etag)
        assert handler.command=='POST' and handler.headers.get('If-None-Match')=='*'
        if self.mode in ('complete-error','complete-conflict','embedded-error'):
            status={'complete-error':500,'complete-conflict':409,'embedded-error':200}[self.mode]
            return self.headers(handler,status,b'<Error><Code>InternalError</Code><Message>synthetic</Message></Error>')
        parts=upload['parts'];leading=[p['size'] for p in parts[:-1]]
        assert all(n==multipart.PART_BYTES and n>=5<<20 for n in leading)
        etag='"'+md5(b''.join(p['md5'] for p in parts)).hexdigest()+'-'+str(len(parts))+'"'
        value=dict(size=sum(p['size'] for p in parts),etag=etag,sha256=upload['sha'].hexdigest(),md5=upload['md5'].hexdigest(),parts=[p['size'] for p in parts])
        if self.mode in ('matching-race','different-race'):
            self.objects[key]=value if self.mode=='matching-race' else dict(value,etag='"'+'0'*32+'-2"')
            return self.headers(handler,412,b'<Error><Code>PreconditionFailed</Code></Error>')
        assert key not in self.objects,'Adapter attempted to overwrite a published object'
        self.objects[key]=value;self.uploads.pop(query['uploadId'][0])
        if self.mode=='lost-completion':
            handler.connection.shutdown(socket.SHUT_RDWR);handler.connection.close();handler.close_connection=True;return
        return self.headers(handler,200,('<CompleteMultipartUploadResult><ETag>'+etag+'</ETag></CompleteMultipartUploadResult>').encode())


@contextmanager
def protocol():
    state=Protocol()
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_HEAD(self):state.request(self)
        def do_POST(self):state.request(self)
        def do_PUT(self):state.request(self)
        def do_DELETE(self):state.request(self)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=connect_r2(R2Config(endpoint_url=f'http://127.0.0.1:{server.server_port}',access_key_id='synthetic-access',secret_access_key='synthetic-secret',
        retries={'total_max_attempts':1},connect_timeout=1,read_timeout=2))
    try:yield state,client
    finally:client.close();server.shutdown();server.server_close();thread.join()


@pytest.fixture
def asset(tmp_path,monkeypatch):
    # Keep ordinary fault cases small; a separate test crosses the real64MiB dispatch threshold.
    monkeypatch.setattr(multipart,'THRESHOLD',8<<20)
    path=tmp_path/'index.sqlite'
    with path.open('wb') as stream:
        stream.write(b'A'*(8<<20));stream.write(b'bounded-final-part')
    return path,facts(path)


def facts(path):
    with path.open('rb') as stream:digest=__import__('hashlib').file_digest(stream,'sha256').hexdigest()
    with path.open('rb') as stream:checksum=__import__('hashlib').file_digest(stream,'md5').hexdigest()
    return dict(size=path.stat().st_size,sha256=digest,md5=checksum)


def store(tmp_path,client,name='first'):
    return NativeArchiveStore(client=client,engine=Native(),bucket=BUCKET,work=tmp_path/name,asset_journal=tmp_path/'assets.json')


def upload(adapter,asset):
    path,identity=asset
    return adapter.upload_file(KEY,path,identity,content_type='application/vnd.sqlite3')


def journal(tmp_path):return json.loads((tmp_path/'assets.json').read_text())['assets'][KEY]


def test_real_threshold_upload_and_metadata_only_continuation(tmp_path,monkeypatch):
    path=tmp_path/'index.sqlite'
    with path.open('wb') as stream:
        for _ in range(8):stream.write(b'Q'*(8<<20))
        stream.write(b'last')
    asset=(path,facts(path))
    with protocol() as (remote,client):
        assert upload(store(tmp_path,client),asset)=='created'
        actual=remote.objects[KEY]
        assert actual['sha256']==asset[1]['sha256'] and actual['md5']==asset[1]['md5']
        assert actual['parts']==[8<<20]*8+[4]
        entry=journal(tmp_path)
        assert entry['phase']=='acknowledged' and entry['transport']['etag']==actual['etag'].strip('"')
        assert json.loads((tmp_path/'assets.json').read_text())['version']==2
        assert entry['upload']['stage']=='completed'
        opened=Path.open
        def no_payload(path,*args,**kwargs):
            if path==asset[0]:raise AssertionError('Acknowledged payload reopened')
            return opened(path,*args,**kwargs)
        monkeypatch.setattr(Path,'open',no_payload)
        assert upload(store(tmp_path,client,'resume'),asset)=='already_exists'
        assert remote.serial==1


@pytest.mark.parametrize('wrong',['sha256','md5','size'])
def test_local_facts_refuse_before_remote_write(tmp_path,asset,wrong):
    path,identity=asset;identity=dict(identity)
    identity[wrong]='0'*len(identity[wrong]) if wrong!='size' else identity['size']+1
    with protocol() as (remote,client):
        with pytest.raises(ValueError,match='identity|size changed'):
            upload(store(tmp_path,client),(path,identity))
        assert not remote.events


@pytest.mark.parametrize('mode',['part-error','part-etag','malformed-etag','source-replace','source-append'])
def test_part_or_custody_failure_aborts_only_owned_attempt(tmp_path,asset,mode):
    with protocol() as (remote,client):
        remote.mode=mode
        if mode.startswith('source-'):
            def change(number):
                if number==1:
                    if mode=='source-replace':
                        replacement=asset[0].with_suffix('.replacement');replacement.write_bytes(b'changed');replacement.replace(asset[0])
                    else:
                        with asset[0].open('ab') as stream:stream.write(b'changed')
            remote.on_part=change
        with pytest.raises(Exception):upload(store(tmp_path,client),asset)
        assert not remote.objects and not remote.uploads
        assert journal(tmp_path)['upload']['stage']=='aborted'
        assert not any(method=='POST' and 'uploadId' in query for method,key,query in remote.events)
        assert sum(method=='DELETE' for method,key,query in remote.events)==1


@pytest.mark.parametrize('mode',['complete-error','complete-conflict','embedded-error','lost-completion'])
def test_unknown_completion_is_not_retried_and_is_reconciled(tmp_path,asset,monkeypatch,mode):
    with protocol() as (remote,client):
        remote.mode=mode
        with pytest.raises(Exception):upload(store(tmp_path,client),asset)
        assert journal(tmp_path)['phase']=='started' and journal(tmp_path)['upload']['stage']=='completing'
        assert sum(method=='POST' and 'uploadId' in query for method,key,query in remote.events)==1
        if mode=='lost-completion':
            opened=Path.open
            def no_payload(path,*args,**kwargs):
                if path==asset[0]:raise AssertionError('Committed payload reopened')
                return opened(path,*args,**kwargs)
            monkeypatch.setattr(Path,'open',no_payload)
            assert upload(store(tmp_path,client,'resume'),asset)=='already_exists'
            assert remote.serial==1
        else:
            remote.mode=None
            assert upload(store(tmp_path,client,'resume'),asset)=='created'
            assert remote.serial==2 and sum(method=='DELETE' for method,key,query in remote.events)==1
        assert journal(tmp_path)['phase']=='acknowledged'


@pytest.mark.parametrize('mode,accepted',[('matching-race',True),('different-race',False)])
def test_completion_conflict_requires_exact_head(tmp_path,asset,mode,accepted):
    with protocol() as (remote,client):
        remote.mode=mode
        if accepted:assert upload(store(tmp_path,client),asset)=='already_exists'
        else:
            with pytest.raises(ValueError,match='identity changed'):upload(store(tmp_path,client),asset)
        assert not remote.uploads
        assert journal(tmp_path)['phase']==('acknowledged' if accepted else 'started')


@pytest.mark.parametrize('damage',['remote-missing','remote-etag','local-custody','transport-plan'])
def test_acknowledged_identity_damage_never_retransmits(tmp_path,asset,damage):
    with protocol() as (remote,client):
        upload(store(tmp_path,client),asset)
        if damage=='remote-missing':remote.objects.clear()
        elif damage=='remote-etag':remote.objects[KEY]['etag']='"'+'0'*32+'-2"'
        elif damage=='local-custody':asset[0].touch()
        else:
            path=tmp_path/'assets.json';value=json.loads(path.read_text());value['assets'][KEY]['transport']['part_md5'][0]='0'*32;path.write_text(json.dumps(value))
        before=len(remote.events)
        with pytest.raises(Exception):upload(store(tmp_path,client,'resume'),asset)
        assert all(method=='HEAD' for method,key,query in remote.events[before:])
        assert remote.serial==1


def test_v1_native_acknowledgement_keeps_its_identity_after_threshold_change(tmp_path,asset,monkeypatch):
    path,identity=asset
    from congress_shared.custody import custody_identity
    (tmp_path/'assets.json').write_text(json.dumps(dict(version=1,bucket=BUCKET,assets={KEY:dict(
        facts=dict(identity,content_type='application/vnd.sqlite3'),source=dict(path=str(path.resolve()),custody=list(custody_identity(path))),phase='acknowledged')})))
    with protocol() as (remote,client):
        remote.objects[KEY]=dict(size=identity['size'],etag='"'+identity['md5']+'"')
        assert upload(store(tmp_path,client),asset)=='already_exists'
        assert remote.serial==0 and json.loads((tmp_path/'assets.json').read_text())['version']==1


def test_failed_abort_retains_owned_id_and_resume_closes_it(tmp_path,asset):
    with protocol() as (remote,client):
        remote.mode='abort-error'
        with pytest.raises(Exception) as caught:upload(store(tmp_path,client),asset)
        assert 'cleanup is unconfirmed' in '\n'.join(caught.value.__notes__)
        assert journal(tmp_path)['upload']['stage']=='uploading' and len(remote.uploads)==1
        remote.mode=None
        assert upload(store(tmp_path,client,'resume'),asset)=='created'
        assert not remote.uploads


def test_declared_part_inventory_refuses_without_source_or_network(tmp_path):
    with protocol() as (remote,client):
        # The inventory check precedes source open; no huge/sparse file is created.
        with pytest.raises(ValueError,match='inventory'):
            multipart.plan_file(tmp_path/'absent',dict(size=multipart.PART_BYTES*(multipart.MAX_PARTS+1)))
        assert not remote.events


def test_new_journal_reuses_exact_preexisting_multipart_asset(tmp_path,asset):
    with protocol() as (remote,client):
        upload(store(tmp_path,client),asset)
        (tmp_path/'assets.json').unlink()
        assert upload(store(tmp_path,client,'new-owner-journal'),asset)=='already_exists'
        assert remote.serial==1 and journal(tmp_path)['phase']=='acknowledged'


def test_sdk_mutation_retries_must_remain_disabled(tmp_path,asset):
    with protocol() as (remote,client):
        client.meta.config.retries['total_max_attempts']=2
        with pytest.raises(ValueError,match='retries must be disabled'):store(tmp_path,client)
        assert not remote.events


@pytest.mark.parametrize('fresh_journal',[False,True])
def test_head_reconciliation_rechecks_source_custody(tmp_path,asset,fresh_journal):
    with protocol() as (remote,client):
        upload(store(tmp_path,client),asset)
        if fresh_journal:(tmp_path/'assets.json').unlink()
        remote.on_head=asset[0].touch
        with pytest.raises(ValueError,match='Local publication asset changed'):
            upload(store(tmp_path,client,'resume'),asset)
        assert remote.serial==1


def test_v2_migration_preserves_other_native_asset_acknowledgements(tmp_path,asset):
    from congress_shared.custody import custody_identity
    small=tmp_path/'old.parquet';small.write_bytes(b'legacy native asset');identity=facts(small)
    key=KEY.replace('search_index.sqlite','list.parquet')
    (tmp_path/'assets.json').write_text(json.dumps(dict(version=1,bucket=BUCKET,assets={key:dict(
        facts=dict(identity,content_type='application/vnd.apache.parquet'),
        source=dict(path=str(small.resolve()),custody=list(custody_identity(small))),phase='acknowledged')})))
    with protocol() as (remote,client):
        remote.objects[key]=dict(size=identity['size'],etag='"'+identity['md5']+'"')
        assert upload(store(tmp_path,client),asset)=='created'
        state=json.loads((tmp_path/'assets.json').read_text())
        assert state['version']==2 and state['assets'][key]['transport']==dict(kind='single_put')
        assert store(tmp_path,client,'old-resume').upload_file(key,small,identity,content_type='application/vnd.apache.parquet')=='already_exists'
        assert remote.serial==1


def test_matching_head_closes_our_unfinished_competing_attempt(tmp_path,asset):
    with protocol() as (remote,client):
        remote.mode='complete-error'
        with pytest.raises(Exception):upload(store(tmp_path,client),asset)
        entry=journal(tmp_path)
        remote.objects[KEY]=dict(size=asset[1]['size'],etag='"'+entry['transport']['etag']+'"')
        remote.mode=None
        assert upload(store(tmp_path,client,'resume'),asset)=='already_exists'
        assert remote.serial==1 and not remote.uploads
        assert journal(tmp_path)['upload']['stage']=='closed'
