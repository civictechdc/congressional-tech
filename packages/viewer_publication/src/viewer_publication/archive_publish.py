"""Native archive transport below the one maintained model publication path.

Model pinning, completeness, profile preparation and early-skip ordering belong
to the caller. This module accepts pinned actual model artifacts, never a passed
flag or an injectable model-policy implementation. Reader probes are external.
"""
from base64 import b64decode
from hashlib import md5,sha256
import json
import os
from pathlib import Path
import re
from time import perf_counter
from urllib.parse import urlsplit

from viewer_publication.archive_gate import gate_and_flip,validate_receipt
from viewer_publication.archive_format import release_identity
from viewer_publication.client import require_publication_client
from viewer_publication.receipt_pins import (PREFIX,receipt_list,read_receipt_list,
    write_input_receipts,kept_receipt_keys)

POINTER='viewer-publications/manifest.json'
STATUS='viewer-publications/status.json'
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


def input_digest(*,receipt_keys,provenance,profile,entity_digests):
    """Hash semantic inputs only; snapshots and run fields never enter this API."""
    if not isinstance(profile,dict) or not profile:
        raise ValueError('Input identity requires the semantic model profile')
    if entity_digests!={}:raise ValueError('Reference entity digests must be empty in phase one')
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
    identity=[keys,[[key,pinned[key]] for key in sorted(pinned)],{},profile]
    return sha256(_encoded(identity)).hexdigest()


class NativeArchiveStore:
    """Adapt receipt metadata and release assets to native create-only uploads.

    Metadata GET/LIST remains in the injected SDK. The same get/keys interface
    supports receipt_pins.kept_receipt_keys in the separate maintenance job.
    """
    def __init__(self,*,client,engine,bucket,work):
        require_publication_client(client)
        if not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):
            raise ValueError('Invalid archive bucket')
        if not getattr(engine,'remote',None) or not callable(getattr(engine,'create_file',None)):
            raise ValueError('Publication requires an explicitly configured remote native engine')
        self.client,self.engine,self.bucket=client,engine,bucket
        self.work=Path(work);self.serial=0
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
    def upload_file(self,key,source,facts,*,content_type):
        key=self._key(key)
        source=Path(source)
        _sha(facts['sha256'])
        if (not isinstance(facts['md5'],str) or re.fullmatch('[a-f0-9]{32}',facts['md5']) is None
                or type(facts['size']) is not int or facts['size']<0):
            raise ValueError('Native upload requires exact file facts')
        self.serial+=1
        destination='s3://'+self.bucket+'/'+key
        spec=dict(source=str(source.resolve()),destination=destination,sha256=facts['sha256'],
            md5=facts['md5'],size=facts['size'],content_type=content_type,cache_control=IMMUTABLE)
        path=self.work/f'cx_upload_{self.serial:06d}.json'
        path.write_bytes(_encoded(spec))
        result=self.engine.create_file(path)
        if (not isinstance(result,dict) or result.get('result') not in {'created','already_exists'}
                or any(result.get(name)!=spec[name] for name in ['destination','sha256','md5','size'])):
            raise ValueError('Native upload returned no matching acknowledged outcome')
        return result['result']
    def create(self,key,body,*,content_type,content_md5,cache_control):
        self._key(key)
        if cache_control!=IMMUTABLE or not isinstance(body,bytes) or len(body)>CONTROL_BYTES:
            raise ValueError('Invalid immutable archive metadata')
        checksum=b64decode(content_md5,validate=True).hex()
        if len(checksum)!=32:raise ValueError('Invalid Content-MD5')
        self.serial+=1
        source=self.work/f'cx_control_{self.serial:06d}.bin';source.write_bytes(body)
        outcome=self.upload_file(key,source,dict(sha256=sha256(body).hexdigest(),md5=checksum,size=len(body)),content_type=content_type)
        if outcome=='already_exists' and self.get(key)!=body:
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
        with Path(evidence).open('xb') as destination:
            destination.write(raw);destination.flush();os.fsync(destination.fileno())
    etag=response.get('ETag')
    if not isinstance(etag,str) or not etag.strip():raise ValueError('Live archive pointer has no ETag')
    if evidence is not None:
        proof=dict(etag=etag,sha256=sha256(raw).hexdigest(),bytes=len(raw))
        with Path(evidence).with_suffix('.response.json').open('xb') as destination:
            destination.write(_encoded(proof));destination.flush();os.fsync(destination.fileno())
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


def write_status(client,*,bucket,status):
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


def _seed_evidence(result,manifest,profile,listed):
    expected={key:profile[key] for key in
        ['kind','label','display_only','catalog_id','generation','input_files']}
    origin=manifest.get('origin')
    if (not isinstance(origin,dict) or set(origin)!=set(expected)|{'gaps'}
            or any(origin.get(key)!=value for key,value in expected.items())
            or not isinstance(origin['gaps'],list)
            or any(not isinstance(gap,str) or not gap.strip() for gap in origin['gaps'])):
        raise ValueError('Seed manifest origin differs from its pinned input profile')
    def report(name):
        matches=[query for query in result['queries'] if query['name']==name]
        if len(matches)!=1 or not isinstance(matches[0].get('data'),list):
            raise ValueError('Missing or duplicate native seed evidence: '+name)
        return matches[0]['data']
    checks=report('seed_invariants')
    if (len(checks)!=1 or not isinstance(checks[0],dict) or not checks[0]
            or any(type(value) is not int or value!=0 for value in checks[0].values())):
        raise ValueError('Native seed invariants did not pass')
    rows=report('seed_reconciliation')
    if (len(rows)!=1 or not isinstance(rows[0],dict) or set(rows[0])!={'input_docs','listed','merged_duplicates','excluded'}
            or any(type(value) is not int or value<0 for value in rows[0].values())):
        raise ValueError('Invalid native seed reconciliation')
    counts=rows[0]
    if (counts['input_docs']!=profile['document_rows'] or counts['listed']!=listed
            or counts['listed']+counts['merged_duplicates']+counts['excluded']!=counts['input_docs']):
        raise ValueError('Seed source documents do not reconcile with listed, merged and excluded documents')
    if counts['excluded']*100>counts['input_docs']*3:
        raise ValueError('Seed data-gap exclusions exceed three percent of its source documents')
    reasons=set();excluded=0
    exclusion_rows=report('seed_exclusions')
    for row in exclusion_rows:
        if (not isinstance(row,dict) or set(row)!={'reason','count'}
                or not isinstance(row['reason'],str) or not row['reason'].strip() or row['reason'] in reasons
                or type(row['count']) is not int or row['count']<1):
            raise ValueError('Invalid native seed exclusion reason counts')
        reasons.add(row['reason']);excluded+=row['count']
    if excluded!=counts['excluded']:raise ValueError('Seed exclusion reasons do not reconcile')
    samples=report('seed_spot_checks');seen=set()
    fields={'filename_matches','format_matches','source_page_matches','meeting_matches'}
    sample_count=min(50,listed)
    if len(samples)!=sample_count:raise ValueError('Seed requires fifty native spot checks')
    for row in samples:
        if (not isinstance(row,dict) or set(row)!=fields|{'source_row'}
                or type(row['source_row']) is not int or not 0<=row['source_row']<profile['document_rows']
                or row['source_row'] in seen or any(row[name] is not True for name in fields)):
            raise ValueError('Native seed spot check did not match its source')
        seen.add(row['source_row'])
    if seen!=set(range(sample_count)):raise ValueError('Seed spot check ordinals are incomplete')
    return dict(seed_reconciliation=counts,seed_exclusions=exclusion_rows)


def _candidate(release,manifest_pin,result_pin,*,input_record,receipt_keys):
    """Check actual model metadata; C5 verifies each transferred asset in one read.

    Release identity remains the archive_format producer's identity. This stage
    rechecks its pinned bytes and native export facts, not a second model formula.
    """
    if Path(manifest_pin['path']).resolve()!=(release/'manifest.json').resolve():
        raise ValueError('Pinned manifest is outside the candidate release')
    manifest,raw=_read_pinned_json(manifest_pin)
    result,_=_read_pinned_json(result_pin)
    if 'error' in result or not isinstance(result.get('outputs'),list) or not isinstance(result.get('queries'),list):
        raise ValueError('Native model result is incomplete or failed')
    seed=input_record['profile'].get('kind')=='seed_v5'
    if seed:
        from viewer_publication.archive_seed_profile import validate_seed_inputs
        profile=validate_seed_inputs(input_record,receipt_keys)
    else:
        if isinstance(manifest.get('origin'),dict) and (manifest['origin'].get('kind')=='seed_v5'
                or manifest['origin'].get('display_only') is True):
            raise ValueError('Seed manifest requires its pinned seed profile')
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
    if listed==0:raise ValueError('An empty document list cannot be published')
    admission=_seed_evidence(result,manifest,profile,listed) if seed else {}
    return manifest,raw,release_id,admission


def publish_candidate(*,client,engine,bucket,work,release,manifest_pin,result_pin,
                      input_record,receipt_keys,pointer,expected_etag,public_origin,contract,canary,measured_release_id=None):
    """Upload a pinned model candidate and use the existing reader gates and CAS.

    The caller owns actual model planning, completeness and early skip. This stage
    accepts actual pinned native artifacts. Only external storage/engine and reader
    probe adapters are injected; no model or admission policy callback is accepted.
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
        store=NativeArchiveStore(client=client,engine=engine,bucket=bucket,work=Path(work)/'uploads')
        receipt_keys=sorted(set(receipt_keys))
        digest=input_digest(receipt_keys=receipt_keys,provenance=input_record['provenance'],
            profile=input_record['profile'],entity_digests=input_record['entity_digests'])
        if input_record.get('input_digest')!=digest:raise ValueError('Input record semantic identity differs')
        manifest,raw,release_id,admission=_candidate(Path(release),manifest_pin,result_pin,
            input_record=input_record,receipt_keys=receipt_keys)
        if measured_release_id is not None:
            if input_record['profile'].get('kind')!='seed_v5' or _sha(measured_release_id)!=release_id:
                raise ValueError('Measured site targets identify a different seed release')
        status.update(admission)
        if input_record['profile'].get('kind')=='seed_v5':
            status.update(input_kind='seed_v5',label=input_record['profile']['label'],display_only=True)
        status.update(release_id=release_id,rows={item['name']:item['rows'] for item in manifest['files']},
            bytes=sum(item['size'] for item in manifest['files']))
        if release_id==live:
            write_input_receipts(store,release_id,digest,input_record,receipt_keys)
            status['status']='release_unchanged'
            return dict(status)
        contract_receipt=contract(release_id=release_id,release=Path(release),manifest=manifest)
        validate_receipt(contract_receipt,release_id=release_id,name='contract',manifest_origin=manifest.get('origin'))
        write_input_receipts(store,release_id,digest,input_record,receipt_keys)
        def uploaded_canary():
            begin=perf_counter();prefix=PREFIX+release_id+'/'
            for item in manifest['files']:
                store.upload_file(prefix+item['name'],Path(release)/item['name'],item,
                    content_type='application/vnd.apache.parquet' if item['name'].endswith('.parquet') else 'application/json')
            store.upload_file(prefix+'manifest.json',manifest_pin['path'],
                dict(sha256=sha256(raw).hexdigest(),md5=md5(raw).hexdigest(),size=len(raw)),content_type='application/json')
            status['durations']['upload']=perf_counter()-begin
            return canary(release_id=release_id,public_origin=public_origin.rstrip('/'),manifest=manifest)
        begin=perf_counter()
        transfer=gate_and_flip(client,bucket=bucket,release_id=release_id,previous_release_id=live,expected_etag=expected_etag,
            contract=lambda:contract_receipt,canary=uploaded_canary,manifest_origin=manifest.get('origin'))
        if not isinstance(transfer.etag,str) or not transfer.etag.strip():
            status.update(live_release=None,live_release_basis='unacknowledged_pointer_write')
            raise ValueError('Publication requires an acknowledged pointer ETag')
        status['durations']['gates_and_flip']=perf_counter()-begin
        status.update(status='published',live_release=release_id,live_release_basis='conditional_flip_acknowledged')
        return dict(status)
    except BaseException as error:
        failure=error;status['error_type']=type(error).__name__
        raise
    finally:
        status['durations']['total']=perf_counter()-started
        try:write_status(client,bucket=bucket,status=status)
        except BaseException:
            if failure is None:raise
            failure.add_note('Archive status update also failed')
