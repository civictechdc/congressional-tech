"""Archive transport below the one maintained model publication path.

Model pinning, completeness, profile preparation and early-skip ordering belong
to the caller. This module accepts pinned actual model artifacts, never a passed
flag or an injectable model-policy implementation. Reader probes are external.
"""
from base64 import b64decode
import fcntl
from hashlib import md5,sha256
from io import BytesIO
import json
from pathlib import Path
import re
from time import perf_counter
from urllib.parse import urlsplit

from congress_api.retention.derived_files import copy_checked
from congress_shared.custody import custody_identity,write_atomic_bytes
from . import archive_multipart
from congress_shared.storage import single_put_md5
from viewer_publication.archive_gate import gate_and_flip,validate_receipt
from viewer_publication.archive_format import release_identity
from viewer_publication.client import require_publication_client
from viewer_publication.archive_comparison_acceptance import require_comparison
from viewer_publication.release_gate import client_reader,fetch_release,require_release_gates
from viewer_publication.receipt_pins import (PREFIX,receipt_list,read_receipt_list,
    write_input_receipts,kept_receipt_keys)

POINTER='viewer-publications/manifest.json'
STATUS='viewer-publications/status.json'
SPICY_PINS='viewer-publications/pins/spicy-generations.json'
IMMUTABLE='public,max-age=31536000,immutable'
# Control objects are small metadata, never release assets. Bound SDK readback.
CONTROL_BYTES=32<<20
DIGEST=re.compile('[0-9a-f]{64}')


def _encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _sha(value):
    if not isinstance(value,str) or DIGEST.fullmatch(value) is None:
        raise ValueError('Expected lowercase SHA-256')
    return value


def _status_code(error):
    response=getattr(error,'response',{})
    return response.get('ResponseMetadata',{}).get('HTTPStatusCode')


def _read(client,bucket,key):
    response=client.get_object(Bucket=bucket,Key=key)
    body=response['Body']
    try:
        size=response['ContentLength']
        if type(size) is not int or size<0 or size>CONTROL_BYTES:
            raise ValueError('Archive control object exceeds the metadata allowance')
        value=body.read(size+1)
        if len(value)!=size:raise ValueError('Archive control object size changed')
        return value,response
    finally:
        body.close()


def _valid_entity_digests(entity_digests):
    if not isinstance(entity_digests,dict):
        raise ValueError('Reference entity digests must be a mapping or empty in phase one')
    for key,value in entity_digests.items():
        if not isinstance(key,str) or not key.strip() or not isinstance(value,str) or DIGEST.fullmatch(value) is None:
            raise ValueError('Reference entity digests must be 64-char hex or empty in phase one')
    return {key:entity_digests[key] for key in sorted(entity_digests)}


def write_spicy_generations(client,*,bucket,generations):
    """Write the pinned union of (family, digest) pairs for spicy-regs retention."""
    require_publication_client(client)
    pairs=sorted({(item['family'],_sha(item['digest'])) if isinstance(item,dict) else (item[0],_sha(item[1])) for item in generations})
    payload=dict(version=1,generations=[dict(family=family,digest=digest) for family,digest in pairs])
    raw=_encoded(payload)
    client.put_object(Bucket=bucket,Key=SPICY_PINS,Body=raw,ContentLength=len(raw),
        ContentType='application/json',CacheControl='no-store')
    return payload


def _collect_spicy_generations(client,store,bucket,*,live,previous,candidate_digests):
    pairs={(family,digest) for family,digest in candidate_digests.items()}
    try:
        existing_raw,_=_read(client,bucket,SPICY_PINS)
        existing=json.loads(existing_raw)
        for item in existing.get('generations',[]):
            if isinstance(item,dict) and isinstance(item.get('family'),str) and DIGEST.fullmatch(str(item.get('digest',''))):
                pairs.add((item['family'],item['digest']))
    except Exception as error:
        if _status_code(error)!=404:raise
    for release_id in [r for r in (live,previous) if r is not None]:
        for key in store.keys(PREFIX+release_id+'/inputs/'):
            if key.endswith('.json') and '/inputs/receipts/' not in key:
                record=json.loads(store.get(key))
                for family,digest in (record.get('entity_digests') or {}).items():
                    if isinstance(family,str) and isinstance(digest,str) and DIGEST.fullmatch(digest):
                        pairs.add((family,digest))
    return sorted(pairs)


def input_digest(*,receipt_keys,provenance,profile,entity_digests):
    """Hash semantic inputs only; snapshots and run fields never enter this API."""
    if not isinstance(profile,dict) or not profile:
        raise ValueError('Input identity requires the semantic model profile')
    entities=_valid_entity_digests(entity_digests)
    keys=list(receipt_keys)
    receipt_list(keys)
    keys=sorted(set(keys))
    pinned={}
    for item in provenance:
        key,etag=item['key'],item['etag']
        if (not isinstance(key,str) or not key.startswith('provenance/') or
                any(part in {'','.','..'} for part in key.split('/')) or
                any(char in key for char in '\\%?#') or not isinstance(etag,str) or not etag):
            raise ValueError('Input identity requires provenance keys and ETags')
        if key in pinned and pinned[key]!=etag:raise ValueError('Conflicting pinned provenance ETags')
        pinned[key]=etag
    identity=[keys,[[key,pinned[key]] for key in sorted(pinned)],entities,profile]
    return sha256(_encoded(identity)).hexdigest()


class NativeArchiveStore:
    """Adapt receipt metadata and release assets to qualified create-only uploads.

    Metadata GET/LIST remains in the injected SDK. The same get/keys interface
    supports receipt_pins.kept_receipt_keys in the separate maintenance job.
    """
    def __init__(self,*,client,engine,bucket,work,comparison_acceptance=None,asset_journal=None):
        require_comparison(comparison_acceptance)
        self.comparison_acceptance=comparison_acceptance
        require_publication_client(client)
        if not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):
            raise ValueError('Invalid archive bucket')
        if not getattr(engine,'remote',None) or not callable(getattr(engine,'create_file',None)):
            raise ValueError('Publication requires an explicitly configured remote native engine')
        self.client,self.engine,self.bucket=client,engine,bucket
        self.work=Path(work);self.serial=0
        self.asset_journal=Path(asset_journal) if asset_journal is not None else None
        self.work.mkdir(parents=True,exist_ok=False)
    @staticmethod
    def _key(key):
        if (not isinstance(key,str) or re.fullmatch(re.escape(PREFIX)+'[a-f0-9]{64}/.+',key) is None
                or any(part in {'','.','..'} for part in key.split('/'))
                or any(char in key for char in '\\%?#') or any(ord(char)<32 for char in key)):
            raise ValueError('Archive asset destination must stay inside one release prefix')
        return key
    def get(self,key):
        self._key(key)
        return _read(self.client,self.bucket,key)[0]
    def keys(self,prefix):
        self._key(prefix+'x')
        token=None
        while True:
            request=dict(Bucket=self.bucket,Prefix=prefix)
            if token is not None:request['ContinuationToken']=token
            page=self.client.list_objects_v2(**request)
            for item in page.get('Contents',[]):
                key=self._key(item['Key'])
                if not key.startswith(prefix):raise ValueError('Archive listing escaped its requested prefix')
                yield key
            if not page.get('IsTruncated'):return
            next_token=page.get('NextContinuationToken')
            if not next_token or next_token==token:raise ValueError('Archive listing did not advance')
            token=next_token
    def upload_file(self,key,source,facts,*,content_type,_bind_source=True):
        require_comparison(self.comparison_acceptance)
        key=self._key(key)
        source=Path(source)
        _sha(facts['sha256'])
        if (not isinstance(facts['md5'],str) or re.fullmatch('[a-f0-9]{32}',facts['md5']) is None
                or type(facts['size']) is not int or facts['size']<0):
            raise ValueError('Publication upload requires exact file facts')
        if self.asset_journal is not None or facts['size']>=archive_multipart.THRESHOLD:
            return self._resumable_upload(key,source,facts,content_type=content_type,
                bind_source=_bind_source or facts['size']>=archive_multipart.THRESHOLD)
        return self._transfer_file(key,source,facts,content_type=content_type)

    def _remote_asset_identity(self,key,facts,transport=None):
        if not callable(getattr(self.client,'head_object',None)):
            raise ValueError('Publication continuation requires metadata-only asset HEAD')
        metadata=self.client.head_object(Bucket=self.bucket,Key=key)
        if transport is not None and transport['kind']=='multipart':
            archive_multipart.require_plan(transport,facts['size'])
            observed=metadata.get('ETag')
            if isinstance(observed,str) and observed.startswith('"') and observed.endswith('"'):
                observed=observed[1:-1]
            matches=observed==transport['etag']
        else:
            matches=single_put_md5(metadata.get('ETag'))==facts['md5']
        if metadata.get('ContentLength')!=facts['size'] or not matches:
            raise ValueError('Remote publication asset identity changed: '+key)

    def _resumable_upload(self,key,source,facts,*,content_type,bind_source):
        # Retained local stage files have one owner. Persist their exact inode
        # custody through transfer; a restart checks custody before opening
        # any payload, then verifies the immutable object's HEAD identity.
        path=self.asset_journal or self.work/'multipart-assets.json';path.parent.mkdir(parents=True,exist_ok=True)
        expected={name:facts[name] for name in ('sha256','md5','size')}
        expected['content_type']=content_type
        local=dict(path=str(source.resolve()),custody=list(custody_identity(source))) if bind_source else None
        if local is not None and local['custody'][2]!=facts['size']:
            raise ValueError('Local publication asset size changed: '+key)
        def require_local():
            if bind_source and local['custody']!=list(custody_identity(source)):
                raise ValueError('Local publication asset changed during transfer: '+key)
        with path.with_suffix(path.suffix+'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if path.is_symlink():raise ValueError('Unsafe publication asset journal')
            state=dict(version=1,bucket=self.bucket,assets={})
            if path.exists():
                if path.stat().st_size>CONTROL_BYTES:raise ValueError('Publication asset journal is oversized')
                try:state=json.loads(path.read_text())
                except ValueError as error:raise ValueError('Corrupt publication asset journal') from error
                if (not isinstance(state,dict) or set(state)!={'version','bucket','assets'} or state['version'] not in (1,2)
                        or state['bucket']!=self.bucket or not isinstance(state['assets'],dict)):
                    raise ValueError('Publication asset journal identity changed')
            def save():write_atomic_bytes(path,_encoded(state),fsync_dir=True)
            def upgrade():
                if state['version']==1:
                    for entry in state['assets'].values():
                        if not isinstance(entry,dict) or set(entry)!={'facts','source','phase'}:
                            raise ValueError('Corrupt publication asset journal entry')
                        entry.update(transport=dict(kind='single_put'),upload=None)
                    state['version']=2
            saved=state['assets'].get(key)
            if saved is not None:
                fields={'facts','source','phase'}|({'transport','upload'} if state['version']==2 else set())
                if (not isinstance(saved,dict) or set(saved)!=fields
                        or saved['facts']!=expected or saved['source']!=local
                        or saved['phase'] not in ('started','acknowledged')):
                    raise ValueError('Local publication asset identity changed: '+key)
                transport=saved.get('transport',dict(kind='single_put'))
                attempt=saved.get('upload')
                if transport==dict(kind='single_put'):
                    if attempt is not None:raise ValueError('Invalid single-PUT publication journal')
                else:
                    archive_multipart.require_plan(transport,facts['size'])
                    if attempt is not None and (not isinstance(attempt,dict) or set(attempt)!={'id','stage'}
                            or not isinstance(attempt['id'],str) or not 1<=len(attempt['id'])<=4096
                            or attempt['stage'] not in {'uploading','completing','completed','aborted','closed'}):
                        raise ValueError('Invalid publication multipart attempt')
                try:self._remote_asset_identity(key,facts,transport)
                except Exception as error:
                    if (_status_code(error)!=404 or saved['phase']=='acknowledged'
                            or attempt is not None and attempt['stage'] in {'completed','closed'}):raise
                    # The previous outcome was unknown and HEAD proves no object
                    # is visible yet. A later completion still must be create-only.
                    if attempt is not None:
                        archive_multipart.abort_attempt(self.client,self.bucket,key,attempt)
                        saved['upload']=dict(attempt,stage='aborted');save()
                else:
                    require_local()
                    if attempt is not None and attempt['stage'] not in {'completed','aborted','closed'}:
                        # HEAD can match an earlier competing upload while our
                        # failed attempt still owns unfinished parts. Close only
                        # that retained upload ID; abort never deletes the object.
                        archive_multipart.abort_attempt(self.client,self.bucket,key,attempt)
                        saved['upload']=dict(attempt,stage='closed');save()
                    if saved['phase']!='acknowledged':
                        saved['phase']='acknowledged';save()
                    return 'already_exists'
            else:
                saved=dict(facts=expected,source=local,phase='started')
                if state['version']==2:saved.update(transport=dict(kind='single_put'),upload=None)
                state['assets'][key]=saved;save()
            if facts['size']>=archive_multipart.THRESHOLD:
                require_publication_client(self.client)
                if any(not callable(getattr(self.client,name,None)) for name in
                        ('create_multipart_upload','upload_part','complete_multipart_upload','abort_multipart_upload')):
                    raise ValueError('Large publication assets require the conditional multipart SDK')
                if saved.get('transport',{}).get('kind')!='multipart':
                    transport=archive_multipart.plan_file(source,facts,custody=tuple(local['custody']))
                    upgrade();saved.update(transport=transport,upload=None);save()
                    # A new journal can encounter a matching object from an
                    # earlier publisher. Verify its planned transport identity
                    # before sending another full asset; creation stays conditional.
                    try:self._remote_asset_identity(key,facts,transport)
                    except Exception as error:
                        if _status_code(error)!=404:raise
                    else:
                        require_local()
                        saved['phase']='acknowledged';save()
                        return 'already_exists'
                def record(attempt):
                    saved['upload']=attempt;save()
                require_comparison(self.comparison_acceptance)
                outcome=archive_multipart.transfer(self.client,bucket=self.bucket,key=key,source=source,
                    facts=facts,plan=saved['transport'],content_type=content_type,cache_control=IMMUTABLE,record=record,
                    custody=tuple(local['custody']))
            else:
                outcome=self._transfer_file(key,source,facts,content_type=content_type)
            require_local()
            self._remote_asset_identity(key,facts,saved.get('transport'))
            saved['phase']='acknowledged';save()
            return outcome

    def _transfer_file(self,key,source,facts,*,content_type):
        self.serial+=1
        destination='s3://'+self.bucket+'/'+key
        spec=dict(source=str(source.resolve()),destination=destination,sha256=facts['sha256'],
            md5=facts['md5'],size=facts['size'],content_type=content_type,cache_control=IMMUTABLE)
        path=self.work/f'cx_upload_{self.serial:06d}.json'
        path.write_bytes(_encoded(spec))
        require_comparison(self.comparison_acceptance)
        result=self.engine.create_file(path)
        if (not isinstance(result,dict) or result.get('result') not in {'created','already_exists'}
                or any(result.get(name)!=spec[name] for name in ['destination','sha256','md5','size'])):
            raise ValueError('Native upload returned no matching acknowledged outcome')
        return result['result']
    def create(self,key,body,*,content_type,content_md5,cache_control):
        require_comparison(self.comparison_acceptance)
        self._key(key)
        if cache_control!=IMMUTABLE or not isinstance(body,bytes) or len(body)>CONTROL_BYTES:
            raise ValueError('Invalid immutable archive metadata')
        checksum=b64decode(content_md5,validate=True).hex()
        if len(checksum)!=32:raise ValueError('Invalid Content-MD5')
        self.serial+=1
        source=self.work/f'cx_control_{self.serial:06d}.bin';source.write_bytes(body)
        outcome=self.upload_file(key,source,dict(sha256=sha256(body).hexdigest(),md5=checksum,size=len(body)),content_type=content_type,_bind_source=False)
        if outcome=='already_exists' and self.asset_journal is None and self.get(key)!=body:
            label='input record' if re.search('/inputs/[a-f0-9]{64}[.]json$',key) else 'receipt list'
            raise ValueError('Existing '+label+' differs from the requested exact bytes')


def read_pointer(client,*,bucket,evidence=None):
    """Read the outgoing pointer once; the caller retains both value and ETag."""
    require_publication_client(client)
    try:raw,response=_read(client,bucket,POINTER)
    except Exception as error:
        if _status_code(error)==404:return None,None
        raise
    if evidence is not None:
        held=copy_checked(BytesIO(raw),evidence,size=len(raw),key='archive outgoing pointer')
    etag=response.get('ETag')
    if not isinstance(etag,str) or not etag.strip():raise ValueError('Live archive pointer has no ETag')
    if evidence is not None:
        proof=_encoded(dict(etag=etag,sha256=held['sha256'],bytes=held['bytes']))
        copy_checked(BytesIO(proof),Path(evidence).with_suffix('.response.json'),
            size=len(proof),key='archive outgoing pointer response')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('Invalid archive pointer shape')
    legacy=(type(value.get('version')) in (int,str) and str(value['version'])=='1'
        and type(value.get('publisher_version')) in (int,str) and str(value['publisher_version'])=='10'
        and isinstance(value.get('catalog_id'),str) and bool(value['catalog_id'])
        and isinstance(value.get('manifest'),str) and bool(value['manifest'])
        and 'release_id' not in value and 'previous_release_id' not in value)
    if legacy:return None,etag
    if 'release_id' not in value:raise ValueError('Unknown archive pointer shape')
    _sha(value['release_id'])
    if value.get('previous_release_id') is not None:_sha(value['previous_release_id'])
    return value,etag


def matching_live_input(store,*,release_id,digest):
    """Read one exact input record, after the caller's native completeness gate.

    Searching by its content-addressed key covers any identity of the live release
    without a growing LIST plus per-input GET loop. Physical/run fields are kept.
    """
    key=PREFIX+_sha(release_id)+'/inputs/'+_sha(digest)+'.json'
    try:raw=store.get(key)
    except Exception as error:
        if _status_code(error)==404:return None
        raise
    record=json.loads(raw)
    keys=read_receipt_list(record['receipt_keys_sha256'],store.get(
        PREFIX+release_id+'/inputs/receipts/'+record['receipt_keys_sha256']+'.json.gz'))
    actual=input_digest(receipt_keys=keys,provenance=record['provenance'],
        profile=record['profile'],entity_digests=record['entity_digests'])
    if actual!=digest or record.get('input_digest')!=digest:
        raise ValueError('Live input record differs from its semantic identity')
    return record


def write_status(client,*,bucket,status,comparison_acceptance=None):
    """Conditionally write the fixed no-store control object, without retry."""
    require_publication_client(client)
    try:
        _,response=_read(client,bucket,STATUS)
    except Exception as error:
        if _status_code(error)!=404:raise
        condition={'IfNoneMatch':'*'}
    else:
        etag=response.get('ETag')
        if not isinstance(etag,str) or not etag.strip():raise ValueError('Archive status has no ETag')
        condition={'IfMatch':etag}
    raw=_encoded(status)
    if status.get('status')!='failed':require_comparison(comparison_acceptance)
    return client.put_object(Bucket=bucket,Key=STATUS,Body=raw,ContentLength=len(raw),
        ContentType='application/json',CacheControl='no-store',**condition)


def _read_pinned_json(pin):
    path=Path(pin['path']);_sha(pin['sha256'])
    if type(pin['size']) is not int or not 0<=pin['size']<=CONTROL_BYTES or path.is_symlink():
        raise ValueError('Invalid pinned model control artifact')
    with path.open('rb') as source:raw=source.read(pin['size']+1)
    if len(raw)!=pin['size'] or sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('Pinned model control artifact changed')
    return json.loads(raw),raw


def _candidate(release,manifest_pin,result_pin,*,input_record,receipt_keys):
    """Check actual model metadata; transfer adapters verify known asset identities.

    Release identity remains the archive_format producer's identity. This stage
    rechecks its pinned bytes and native export facts, not a second model formula.
    """
    if Path(manifest_pin['path']).resolve()!=(release/'manifest.json').resolve():
        raise ValueError('Pinned manifest is outside the candidate release')
    manifest,raw=_read_pinned_json(manifest_pin)
    result,_=_read_pinned_json(result_pin)
    if 'error' in result or not isinstance(result.get('outputs'),list) or not isinstance(result.get('queries'),list):
        raise ValueError('Native model result is incomplete or failed')
    if (isinstance(input_record.get('profile'),dict) and input_record['profile'].get('kind')=='seed_v5') or (
            isinstance(manifest.get('origin'),dict) and (manifest['origin'].get('kind')=='seed_v5'
            or manifest['origin'].get('display_only') is True)):
        raise ValueError('Seed manifest requires its pinned seed profile')
    if isinstance(manifest.get('origin'),dict) and manifest['origin'].get('kind')=='converted_catalog':
        # A converted legacy catalog skips the unique document-key check (its
        # documents can share a saved body); it is a parity fixture, never a release.
        raise ValueError('A converted catalog is a parity fixture and is never published')
    for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']:
        checks=[entry for entry in result['queries'] if entry['name']==name]
        if (len(checks)!=1 or len(checks[0]['data'])!=1 or not checks[0]['data'][0]
                or any(type(value) is not int or value!=0 for value in checks[0]['data'][0].values())):
            raise ValueError('Native model check did not pass: '+name)
    release_id=_sha(manifest['release_id'])
    if manifest.get('schema_version')!=1 or not isinstance(manifest.get('files'),list):
        raise ValueError('Invalid archive manifest')
    names=set();listed=0
    for item in manifest['files']:
        name=item['name'];_sha(item['sha256'])
        if (not isinstance(name,str) or not name or name in names or '/' in name or '\\' in name
                or name in {'.','..','manifest.json'} or any(c in name for c in '%?#') or any(ord(c)<32 for c in name)):
            raise ValueError('Invalid candidate file name')
        if (not isinstance(item['md5'],str) or re.fullmatch('[a-f0-9]{32}',item['md5']) is None
                or type(item['rows']) is not int or item['rows']<0
                or type(item['size']) is not int or item['size']<0):
            raise ValueError('Invalid candidate file facts')
        names.add(name)
        if name=='list.parquet':listed+=item['rows']
        source=release/name
        if not source.is_file() or source.is_symlink():raise ValueError('Missing or unsafe candidate asset')
        if name.endswith('.parquet'):
            exports=[entry for entry in result['outputs'] if entry['name']==name]
            if len(exports)!=1 or any(exports[0][key]!=item[key] for key in ['sha256','md5','size','rows']):
                raise ValueError('Candidate differs from the native export result')
    if release_identity(manifest['schema_version'],manifest['files'])!=release_id:
        raise ValueError('Candidate release identity differs from its content metadata')
    index_policy=(input_record.get('profile') or {}).get('text_index')
    if index_policy is not None or manifest.get('text_index'):
        from viewer_publication.archive_text_index import validate_attachment
        validate_attachment(manifest,release,index_policy.get('definition') if index_policy else None)
    if listed==0:raise ValueError('An empty document list cannot be published')
    return manifest,raw,release_id,{}


def publish_candidate(*,client,engine,bucket,work,release,manifest_pin,result_pin,
                      input_record,receipt_keys,pointer,expected_etag,public_origin,contract,canary,measured_release_id=None,comparison_acceptance=None,asset_journal=None,
                      base_release=None,release_causes=None,link_history_dirs=(),first_release=False,automatic_captures=None,
                      selected_pointer_reconciled=False):
    """Upload a pinned model candidate and use the existing reader gates and CAS.

    The caller owns actual model planning, completeness and early skip. This stage
    accepts actual pinned native artifacts. Only external storage/engine and reader
    probe adapters are injected; no model or admission policy callback is accepted.
    Gates 1 and 2 (release_gate) compare the candidate with `base_release`, the
    fetched copy of the pinned live release, before any contract, upload or flip.
    """
    require_publication_client(client)
    started=perf_counter();failure=None
    status=dict(status='failed',input_digest=input_record.get('input_digest'),release_id=None,
        live_release=None,live_release_basis='unknown',rows={},bytes=0,durations={})
    try:
        origin=urlsplit(public_origin)
        if origin.scheme!='https' or not origin.netloc or origin.username or origin.password or origin.query or origin.fragment:
            raise ValueError('Production canary requires an HTTPS public origin without credentials')
        live=_sha(pointer['release_id']) if pointer is not None else None
        if ((expected_etag is not None and (not isinstance(expected_etag,str) or not expected_etag.strip())) or
                (live is not None and expected_etag is None)):
            raise ValueError('Outgoing pointer and ETag must be pinned together')
        status.update(live_release=live,live_release_basis='pinned_at_start')
        require_comparison(comparison_acceptance)
        store=NativeArchiveStore(client=client,engine=engine,bucket=bucket,work=Path(work)/'uploads',comparison_acceptance=comparison_acceptance,asset_journal=asset_journal)
        receipt_keys=sorted(set(receipt_keys))
        digest=input_digest(receipt_keys=receipt_keys,provenance=input_record['provenance'],
            profile=input_record['profile'],entity_digests=input_record['entity_digests'])
        if input_record.get('input_digest')!=digest:raise ValueError('Input record semantic identity differs')
        manifest,raw,release_id,admission=_candidate(Path(release),manifest_pin,result_pin,
            input_record=input_record,receipt_keys=receipt_keys)
        if measured_release_id is not None:
            if _sha(measured_release_id)!=release_id:
                raise ValueError('Measured site targets identify a different release')
        status.update(admission)
        status.update(release_id=release_id,rows={item['name']:item['rows'] for item in manifest['files']},
            bytes=sum(item['size'] for item in manifest['files']))
        if release_id==live:
            write_input_receipts(store,release_id,digest,input_record,receipt_keys)
            if input_record['entity_digests']:
                previous=pointer.get('previous_release_id') if pointer else None
                pairs=_collect_spicy_generations(client,store,bucket,live=live,previous=previous,candidate_digests=input_record['entity_digests'])
                write_spicy_generations(client,bucket=bucket,generations=pairs)
            status['status']='release_unchanged'
            if selected_pointer_reconciled:status['live_release_basis']='selected_pointer_reconciled'
            return dict(status)
        if live is not None:
            if first_release:raise ValueError('A first release cannot replace a live release')
            if base_release is None:raise ValueError('Gates 1 and 2 require the fetched live release')
            fetch_release(client_reader(client,bucket,live),live,base_release)
        elif not first_release:
            # A missing or legacy-format pointer is not proof that nothing was published:
            # the gates would check nothing. Only an explicit, recorded bootstrap may proceed.
            raise ValueError('No live release to compare with; a first release must be declared (first_release)')
        else:
            # The declaration is checked, not trusted: no other release may exist under the
            # prefix (this candidate's own objects from an interrupted attempt are allowed).
            token=None
            while True:
                request=dict(Bucket=bucket,Prefix=PREFIX)
                if token is not None:request['ContinuationToken']=token
                page=client.list_objects_v2(**request)
                # Only engine releases count (PREFIX + 64-hex id); legacy viewer files under the same
                # prefix and this candidate's own objects from an interrupted attempt do not.
                if any(re.match(re.escape(PREFIX)+'[a-f0-9]{64}/',item['Key']) and not item['Key'].startswith(PREFIX+release_id+'/')
                       for item in page.get('Contents',[])):
                    raise ValueError('first_release declared, but releases already exist under '+PREFIX)
                token=page.get('NextContinuationToken')
                if not page.get('IsTruncated') or not token:break
            status['first_release']=True
        automatic=None
        if automatic_captures is not None and live is not None:
            # ct-ud0b: unattended nightly publication. The live receipt set comes from the live
            # release's own input records; raw lines are read from the raw bucket, never the model.
            from viewer_publication.receipt_pins import kept_input_records
            from viewer_publication.release_gate import automatic_causes
            entries,_=kept_input_records(store,[live])
            held={key for entry in entries for key in entry['receipt_keys']}
            def read_receipt(key):
                body=client.get_object(Bucket=bucket,Key=key)['Body']
                try:return body.read()
                finally:body.close()
            automatic=lambda report:automatic_causes(report,base_release,Path(release),engine=engine,
                captures=automatic_captures,live_receipt_keys=held,read_receipt=read_receipt,work=Path(work)/'automatic')
        require_release_gates(Path(base_release) if live is not None else None,Path(release),release_causes,
            report_path=Path(work)/'release-gate.json',history=link_history_dirs,automatic=automatic)
        status['release_gates']='passed'
        contract_receipt=contract(release_id=release_id,release=Path(release),manifest=manifest)
        validate_receipt(contract_receipt,release_id=release_id,name='contract',manifest_origin=manifest.get('origin'))
        write_input_receipts(store,release_id,digest,input_record,receipt_keys)
        def uploaded_canary():
            begin=perf_counter();prefix=PREFIX+release_id+'/'
            for item in manifest['files']:
                store.upload_file(prefix+item['name'],Path(release)/item['name'],item,
                    content_type=('application/vnd.apache.parquet' if item['name'].endswith('.parquet')
                                  else 'application/vnd.sqlite3' if item['name'].endswith('.sqlite') else 'application/json'))
            store.upload_file(prefix+'manifest.json',manifest_pin['path'],
                dict(sha256=sha256(raw).hexdigest(),md5=md5(raw).hexdigest(),size=len(raw)),content_type='application/json')
            if input_record['entity_digests']:
                previous=pointer.get('previous_release_id') if pointer else None
                pairs=_collect_spicy_generations(client,store,bucket,live=live,previous=previous,candidate_digests=input_record['entity_digests'])
                write_spicy_generations(client,bucket=bucket,generations=pairs)
            status['durations']['upload']=perf_counter()-begin
            return canary(release_id=release_id,public_origin=public_origin.rstrip('/'),manifest=manifest)
        begin=perf_counter()
        transfer=gate_and_flip(client,bucket=bucket,release_id=release_id,previous_release_id=live,expected_etag=expected_etag,
            contract=lambda:contract_receipt,canary=uploaded_canary,manifest_origin=manifest.get('origin'),comparison_acceptance=comparison_acceptance)
        if not isinstance(transfer.etag,str) or not transfer.etag.strip():
            status.update(live_release=None,live_release_basis='unacknowledged_pointer_write')
            raise ValueError('Publication requires an acknowledged pointer ETag')
        status['durations']['gates_and_flip']=perf_counter()-begin
        status.update(status='published',live_release=release_id,live_release_basis=(
            'selected_pointer_reconciled' if transfer.reconciled else 'conditional_flip_acknowledged'))
        return dict(status)
    except BaseException as error:
        failure=error;status['error_type']=type(error).__name__
        raise
    finally:
        status['durations']['total']=perf_counter()-started
        try:write_status(client,bucket=bucket,status=status,comparison_acceptance=comparison_acceptance)
        except BaseException:
            if failure is None:raise
            failure.add_note('Archive status update also failed')
