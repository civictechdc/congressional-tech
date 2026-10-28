"""Explicit, pinned repairs for the temporary old capture index and missing raw keys."""
from copy import deepcopy
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_store import create_stored
from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.provenance import file_pin,parquet_output,run_job
from congress_api.retention.raw_verifier import check_body


LOCATOR=('receipt_key','receipt_line','pointer_json')


def prepare_repair(captures,repairs,*,engine,work,expected):
    native=isinstance(captures,dict)
    identity=captures['identity'] if native else file_pin(captures)['sha256']
    if identity!=expected:
        raise ValueError('Capture selection changed before repair preparation')
    schema=captures['schema'] if native else pq.read_schema(captures)
    if '_capture_order' not in schema.names or schema.field('_capture_order').type!=pa.int64():
        raise ValueError('Repair requires an explicit Int64 observation order')
    if not all(name in schema.names for name in (*LOCATOR,'stored_sha256','stored_bytes')):
        raise ValueError('Repair input lacks exact old capture locators')
    proof={'receipt_stored_sha256','receipt_stored_bytes','measured_stored_sha256',
           'sha256_verified','size','etag','checked_at','evidence_source'}
    if not proof.issubset(pq.read_schema(repairs).names):
        raise ValueError('Measured stored-byte evidence is required for repair')
    work=Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    inputs=captures['inputs'] if native else [dict(name='old',kind='parquet',path=str(Path(captures).resolve()))]
    inputs=[*inputs,dict(name='repairs',kind='parquet',path=str(Path(repairs).resolve()))]
    steps=[dict(name='old',sql=captures['sql'])] if native else []
    sha='stored_sha256'
    binary=pa.types.is_binary(schema.field(sha).type) or pa.types.is_fixed_size_binary(schema.field(sha).type)
    corrected_sha=("arrow_cast(decode(c.stored_sha256,'hex'),'FixedSizeBinary(32)')"
                   if pa.types.is_fixed_size_binary(schema.field(sha).type) else
                   "decode(c.stored_sha256,'hex')" if binary else 'c.stored_sha256')
    if 'body_key' in schema.names:
        key='o.body_key'
    else:
        original="lower(encode(o.sha256,'hex'))" if binary else 'o.sha256'
        key=f"concat('bodies/sha256/',substr({original},1,2),'/',{original},'.gz')"
    match=' AND '.join('('+value+')' for value in
        [f'{key}=c.key',*[f'o."{name}" IS NOT DISTINCT FROM c."{name}"' for name in LOCATOR]])
    projection=[]
    for name in schema.names:
        expression=(f'coalesce({corrected_sha},o.stored_sha256)' if name=='stored_sha256' else
                    'coalesce(c.stored_bytes,o.stored_bytes)' if name=='stored_bytes' else f'o."{name}"')
        projection.append(expression+' AS "'+name+'"')
    unchanged=[name for name in schema.names if name not in {'stored_sha256','stored_bytes'}]
    fields=','.join('"'+name+'"' for name in unchanged)
    qualified="""sha256_verified IS TRUE AND regexp_like(stored_sha256,'^[a-f0-9]{64}$')
        AND stored_sha256=measured_stored_sha256 AND stored_sha256=receipt_stored_sha256
        AND stored_bytes IS NOT NULL AND stored_bytes>=0 AND size=stored_bytes
        AND (receipt_stored_bytes IS NULL OR receipt_stored_bytes=size)
        AND etag IS NOT NULL AND etag<>'' AND try_cast(checked_at AS TIMESTAMP WITH TIME ZONE) IS NOT NULL
        AND evidence_source IN ('current_read','prior_verification')"""
    steps += [dict(name='measured_repairs',sql=f"""SELECT key,receipt_key,receipt_line,pointer_json,
        stored_sha256,stored_bytes,etag,CASE WHEN ({qualified}) THEN cast(0 AS BIGINT)
        ELSE cast(1 AS BIGINT) END AS invalid_measurement FROM repairs""",materialize=True),
        dict(name='evidence',sql="""SELECT key,receipt_key,receipt_line,pointer_json,
        min(stored_sha256) AS stored_sha256,min(stored_bytes) AS stored_bytes,
        count(DISTINCT stored_sha256) AS hashes,count(DISTINCT stored_bytes) AS sizes,
        count(DISTINCT etag) AS etags,
        sum(invalid_measurement) AS invalid_measurements
        FROM measured_repairs GROUP BY key,receipt_key,receipt_line,pointer_json"""),
        dict(name='fixes',sql="SELECT * FROM evidence WHERE invalid_measurements=0 AND hashes=1 AND sizes=1 AND etags=1"),
        dict(name='patched',sql='SELECT '+','.join(projection)+' FROM old o LEFT JOIN fixes c ON '+match),
        dict(name='changed',sql='SELECT '+','.join(projection)+' FROM old o JOIN fixes c ON '+match+
             f' WHERE (o.stored_sha256 IS DISTINCT FROM {corrected_sha}) OR (c.stored_bytes IS NOT NULL AND (o.stored_bytes IS DISTINCT FROM c.stored_bytes))'),
        ]
    exports=[parquet_output(work,'corrected','SELECT * FROM patched',['_capture_order']),
             parquet_output(work,'changed','SELECT * FROM changed',['_capture_order'])]
    exports[0]['settings']['columns']=schema.names
    reports=run_job(work,engine,inputs=inputs,steps=steps,outputs=exports,queries=[dict(name='audit',sql=f"""SELECT
        (SELECT count(*) FROM old) AS before_rows,(SELECT count(*) FROM patched) AS after_rows,
        (SELECT count(*) FROM evidence)-(SELECT count(*) FROM fixes) AS ambiguous,
        (SELECT count(*) FROM changed) AS changed,
        (SELECT count(*) FROM fixes c LEFT ANTI JOIN old o ON {match}) AS unmatched,
        (SELECT count(*) FROM old WHERE _capture_order IS NULL OR _capture_order<0) AS invalid_order,
        (SELECT count(DISTINCT _capture_order) FROM old) AS distinct_order,
        (SELECT count(*) FROM (SELECT {fields} FROM old EXCEPT ALL SELECT {fields} FROM patched)) AS lost,
        (SELECT count(*) FROM (SELECT {fields} FROM patched EXCEPT ALL SELECT {fields} FROM old)) AS added""")])
    audit=reports['audit'][0]
    if (audit['ambiguous'] or audit['unmatched'] or audit['invalid_order']
            or audit['before_rows']!=audit['after_rows'] or audit['distinct_order']!=audit['before_rows']
            or audit['lost'] or audit['added']):
        raise ValueError('Ambiguous repair evidence or changed unrelated capture facts')
    if native and audit['before_rows']!=captures['expected_rows']:
        raise ValueError('Selected capture count differs from its pinned manifest')
    if not native and file_pin(captures)['sha256']!=expected:
        raise ValueError('Capture selection changed during repair preparation')
    output=work/'corrected.parquet'
    manifest=dict(version=1,kind='native' if native else 'flat',expected=expected,output=str(output),
        output_pin=file_pin(output),changed=str(work/'changed.parquet'),changed_pin=file_pin(work/'changed.parquet'),
        repairs_pin=file_pin(repairs),audit=audit)
    (work/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def load_repair(work):
    work=Path(work).resolve()
    manifest=json.loads((work/'manifest.json').read_text())
    if manifest.get('version')!=1 or manifest.get('kind') not in {'flat','native'}:
        raise ValueError('Invalid repair stage')
    for name in ('output','changed'):
        path=Path(manifest[name]).resolve()
        if path.parent!=work or file_pin(path)!=manifest[name+'_pin']:
            raise ValueError('Repair stage changed after preparation')
    return manifest


def apply_flat(work,captures):
    manifest=load_repair(work)
    if manifest['kind']!='flat':
        raise ValueError('Repair stage belongs to the native old index')
    captures=Path(captures)
    with captures.with_suffix(captures.suffix+'.repair.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if file_pin(captures)['sha256']!=manifest['expected']:
            raise ValueError('Capture selection changed after preparation')
        fd,temporary=tempfile.mkstemp(dir=captures.parent)
        try:
            with os.fdopen(fd,'wb') as out,Path(manifest['output']).open('rb') as source:
                shutil.copyfileobj(source,out,1024**2)
                out.flush()
                os.fsync(out.fileno())
            if file_pin(temporary)!=manifest['output_pin']:
                raise ValueError('Repair stage changed during replacement')
            os.chmod(temporary,captures.stat().st_mode & 0o777)
            if file_pin(captures)['sha256']!=manifest['expected']:
                raise ValueError('Capture selection changed during replacement')
            os.replace(temporary,captures)
            directory=os.open(captures.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return manifest['audit']


def apply_native(work,storage):
    """Replace bounded selected references, preserve counts and CAS the same selector."""
    from congress_api.retention.raw_storage import RawSnapshot
    from congress_api.retention.raw_values import NATIVE_CAPTURE_SCHEMA
    manifest=load_repair(work)
    base=storage.snapshot()
    if manifest['kind']!='native' or base.identity!=manifest['expected']:
        raise ValueError('Native capture selection changed after preparation')
    operation='stored-digest-repair-'+manifest['output_pin']['sha256'][:24]
    selected=deepcopy(base.manifest)
    head=None
    rows=0
    with pq.ParquetFile(manifest['output']) as source:
        for batch in source.iter_batches(batch_size=storage.max_capture_rows):
            table=pa.Table.from_batches([batch]).cast(NATIVE_CAPTURE_SCHEMA)
            for _,part in storage._capture_batches(table):
                first=part['_capture_order'][0].as_py()
                if first!=rows:
                    raise ValueError('Repair capture order is not contiguous')
                pin=storage._candidate('captures',part,operation=operation,prefix=str(first),base_id=base.identity)
                entry=dict(release=pin,rows=len(part),
                           decoded_bytes=pa.Table.from_pylist(part.to_pylist(),schema=NATIVE_CAPTURE_SCHEMA).nbytes,
                           first_order=first,receipt_keys=sorted(set(part['receipt_key'].drop_null().to_pylist())))
                head=storage.capture_pages.append(head,[entry])
                rows+=len(part)
    if rows!=base.manifest['captures']['rows']:
        raise ValueError('Repair cannot append or remove capture observations')
    selected['captures']['head']=head
    with pq.ParquetFile(manifest['changed']) as source:
        for number,batch in enumerate(source.iter_batches(batch_size=storage.max_capture_rows)):
            current=RawSnapshot(storage,selected,base.version)
            selected['bodies']=storage._prepare_bodies(current,pa.Table.from_batches([batch]),
                                                       operation=f'{operation}-bodies-{number}',base_id=base.identity)
    load_repair(work)
    data=encoded(selected)
    result=storage.publish(dict(base=base,manifest=selected,data=data,changed=selected!=base.manifest,
                                already_applied=False,delivery=None))
    return dict(identity=result.identity,**manifest['audit'])


def restore_missing(store,key,source,*,expected_stored_sha256):
    """Only owner-supplied exact stored bytes may restore an absent physical key."""
    source=Path(source)
    pin=file_pin(source)
    if pin['sha256']!=expected_stored_sha256:
        raise ValueError('Restoration source checksum differs from its pinned stored bytes')
    with source.open('rb') as stream:
        md5=hashlib.file_digest(stream,'md5').hexdigest()
    class Source:
        def get(self,unused):
            return dict(Body=source.open('rb'),ContentLength=pin['size'],ETag=md5)
    measured=check_body(Source(),dict(key=key,size=pin['size'],etag=md5),
                        checked_at=datetime.now(timezone.utc).isoformat())
    if not measured['sha256_verified'] or measured['stored_sha256']!=expected_stored_sha256:
        raise ValueError('Restoration source identity or checksum differs from its raw key')
    with source.open('rb') as stream:
        return create_stored(store.adapter,key,stream,'application/gzip' if key.endswith('.gz') else 'application/octet-stream',
                             expected_md5=md5,expected_size=pin['size'])
