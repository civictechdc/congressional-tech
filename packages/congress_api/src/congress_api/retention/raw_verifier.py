"""Raw inventory checks. Native SQL owns joins; storage adapters only LIST and GET."""
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import secrets

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_store import BODY
from congress_api.retention.provenance import (field, parquet_output, parquet_records,
                                               file_pin, run_job as execute_job)


def selected_captures(storage):
    """Select exact source TablePins from the old index without exporting its rows."""
    from congress_api.retention.raw_values import NATIVE_CAPTURE_SCHEMA
    snapshot=storage.snapshot()
    inputs=[]
    selects=[]
    for number,entry in enumerate(storage.capture_pages.entries(snapshot.manifest['captures']['head'])):
        name=f'old_source_{number:06d}'
        pin=entry['release']['dataset']['groups']['source']
        inputs.append(dict(name=name,kind='iceberg',pin=pin))
        selects.append('SELECT '+','.join('"'+f.name+'"' for f in NATIVE_CAPTURE_SCHEMA)+' FROM '+name)
    if not selects:
        raise ValueError('Selected old capture index has no source batches')
    return dict(inputs=inputs,sql=' UNION ALL '.join(selects),schema=NATIVE_CAPTURE_SCHEMA,
                expected_rows=snapshot.manifest['captures']['rows'],identity=snapshot.identity)


def json_input(name, files, columns):
    return dict(name=name,kind='json_lines',files=files,
                schema=dict(fields=[field(k,v) for k,v in columns.items()],metadata={}))


def stage_json(path, rows):
    with gzip.open(path,'wt',encoding='utf-8',newline='\n') as out:
        for row in rows:
            out.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n')
    return [dict(key=path.name,path=str(path.resolve()))]


def output(name, path, sql, order=('key',)):
    return parquet_output(path.parent.resolve(),name,sql,list(order))


def run_job(engine, work, *, inputs, steps, outputs, queries):
    work.mkdir(parents=True,exist_ok=True)
    return execute_job(work.resolve(),engine,inputs=inputs,
        steps=[dict(name=n,sql=sql,materialize=False) for n,sql in steps],outputs=outputs,queries=queries)


class _HashedReader:
    def __init__(self, source):
        self.source,self.md5,self.sha,self.size=source,hashlib.md5(),hashlib.sha256(),0

    def read(self, size=-1):
        data=self.source.read(min(size,1024**2) if size>=0 else 1024**2)
        self.md5.update(data)
        self.sha.update(data)
        self.size+=len(data)
        return data


def check_body(store, listing, *, checked_at):
    """Read selected bytes once; decode only the stored representation's gzip layer."""
    key=listing['key']
    match=BODY.fullmatch(key)
    result=dict(key=key,size=listing['size'],etag=listing['etag'],sha256_verified=False,
                checked_at=checked_at,job='raw-verifier',stored_sha256=None,error=None)
    if not match or match[1]!=match[2][:2]:
        return dict(result,error='invalid_body_key')
    try:
        response=store.get(key)
        with closing(response['Body']) as stream:
            hashed=_HashedReader(stream)
            zipped=key.endswith('.gz') or response.get('ContentEncoding')=='gzip'
            entity=gzip.GzipFile(fileobj=hashed) if zipped else hashed
            digest=hashlib.sha256()
            try:
                while chunk:=entity.read(1024**2):
                    digest.update(chunk)
            finally:
                if zipped:
                    entity.close()
            etag=response['ETag'].strip('"')
            error=('listing_changed' if etag!=listing['etag'] or hashed.size!=listing['size']
                   or response['ContentLength']!=hashed.size else
                   'stored_md5_mismatch' if re.fullmatch('[a-fA-F0-9]{32}',etag)
                   and hashed.md5.hexdigest()!=etag.lower() else
                   'identity_mismatch' if digest.hexdigest()!=match[2] else None)
            return dict(result,stored_sha256=hashed.sha.hexdigest(),sha256_verified=error is None,error=error)
    except (OSError,EOFError,ValueError) as error:
        return dict(result,error=type(error).__name__)


def verify(store, *, captures, receipts, previous, engine, work, checked_at, seed=None):
    """Stage reports and accepted verification records; never repair or upload implicitly."""
    work=Path(work)
    work.mkdir(parents=True,exist_ok=False)
    seed=seed or secrets.token_hex(32)
    if not re.fullmatch('[A-Za-z0-9_-]+',seed):
        raise ValueError('Invalid sample seed')
    stamp=datetime.fromisoformat(checked_at.replace('Z','+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Verification time needs a timezone')
    (work/'sample-seed.txt').write_text(seed+'\n')
    listing_files=stage_json(work/'listing.jsonl.gz',store.listing())
    native=isinstance(captures,dict)
    schema=captures['schema'] if native else pq.read_schema(captures)
    def column(name, kind='VARCHAR'):
        if name not in schema.names:
            return f'cast(NULL AS {kind})'
        value='"'+name+'"'
        if name in {'sha256','stored_sha256'} and (pa.types.is_binary(schema.field(name).type) or pa.types.is_fixed_size_binary(schema.field(name).type)):
            value=f"lower(encode({value},'hex'))"
        return value
    index_key=column('body_key')
    if 'body_key' not in schema.names:
        sha=column('sha256')
        index_key=f"concat('bodies/sha256/',substr({sha},1,2),'/',{sha},'.gz')"
    entry={'Struct':[field(n,t) for n,t in dict(body_key='Utf8',sha256='Utf8',stored_suffix='Utf8',
        stored_md5='Utf8',stored_sha256='Utf8',stored_bytes='Int64',bytes='Int64').items()]}
    receipt_schema={n:{'List':field('item',entry)} for n in ('captures','file_references')}
    verify_schema=dict(key='Utf8',size='Int64',etag='Utf8',sha256_verified='Boolean',checked_at='Utf8',job='Utf8')
    inputs=[json_input('listing',listing_files,dict(key='Utf8',size='Int64',etag='Utf8')),
            json_input('receipts',receipts,receipt_schema),json_input('previous',previous,verify_schema)]
    inputs+=captures['inputs'] if native else [dict(name='old',kind='parquet',path=str(Path(captures).resolve()))]
    steps=[('index_refs',f"SELECT {index_key} AS key,{column('stored_bytes','BIGINT')} AS size,{column('stored_sha256')} AS stored_sha256,{column('receipt_key')} AS receipt_key,{column('receipt_line','BIGINT')} AS receipt_line,{column('pointer_json')} AS pointer_json FROM old"),
        ('receipt_entries',"SELECT __source_key AS receipt_key,__source_line AS receipt_line,unnest(captures) AS c FROM receipts UNION ALL SELECT __source_key,__source_line,unnest(file_references) AS c FROM receipts"),
        ('receipt_refs',"""SELECT coalesce(c['body_key'],concat('bodies/sha256/',substr(c['sha256'],1,2),'/',c['sha256'],coalesce(c['stored_suffix'],'.gz'))) AS key,c['stored_bytes'] AS size,c['stored_md5'] AS md5,c['stored_sha256'] AS stored_sha256,receipt_key,receipt_line FROM receipt_entries"""),
        ('all_refs','SELECT key,size,cast(NULL AS VARCHAR) AS md5 FROM index_refs UNION ALL SELECT key,size,md5 FROM receipt_refs'),
        ('refs',"SELECT key,min(size) AS size,min(md5) AS md5,count(DISTINCT size)>1 OR count(DISTINCT md5)>1 AS conflicting FROM all_refs WHERE key IS NOT NULL GROUP BY key"),
        ('ranked_previous','SELECT *,row_number() OVER(PARTITION BY key ORDER BY checked_at DESC,__source_key DESC,__source_line DESC) AS ranking FROM previous'),
        ('verified','SELECT * FROM ranked_previous WHERE ranking=1'),
        ('expected','SELECT coalesce(r.key,v.key) AS key,r.size,r.md5,r.conflicting,v.size AS verified_size,v.etag AS verified_etag,v.sha256_verified FROM refs r FULL OUTER JOIN verified v ON r.key=v.key'),
        ('compared',"""SELECT coalesce(l.key,e.key) AS key,l.size,l.etag,e.key IS NOT NULL AS referenced,l.key IS NULL AS missing,
            coalesce(e.conflicting,false) OR (e.size IS NOT NULL AND l.size<>e.size) OR (e.verified_size IS NOT NULL AND l.size<>e.verified_size)
            OR (e.verified_etag IS NOT NULL AND l.etag<>e.verified_etag) OR (e.md5 IS NOT NULL AND l.etag<>e.md5) AS mismatch,
            coalesce(e.sha256_verified,false) AS sha256_verified FROM listing l FULL OUTER JOIN expected e ON l.key=e.key"""),
        ('sample',f"SELECT key,size,etag FROM listing ORDER BY sha256('{seed}' || key),key LIMIT 25"),
        ('work','SELECT key,size,etag FROM compared WHERE NOT referenced AND NOT missing UNION SELECT key,size,etag FROM sample'),
        ('digest_repairs',"""SELECT i.key,i.receipt_key,i.receipt_line,i.pointer_json,min(r.stored_sha256) AS stored_sha256,
            min(r.size) AS stored_bytes FROM index_refs i JOIN receipt_refs r ON i.key=r.key AND i.receipt_key=r.receipt_key AND i.receipt_line=r.receipt_line
            WHERE r.stored_sha256 IS NOT NULL AND i.stored_sha256 IS DISTINCT FROM r.stored_sha256
            GROUP BY i.key,i.receipt_key,i.receipt_line,i.pointer_json HAVING count(DISTINCT r.stored_sha256)=1""")]
    if native:
        steps.insert(0,('old',captures['sql']))
    reports=run_job(engine,work/'inventory',inputs=inputs,steps=steps,
        outputs=[output('baseline',work/'baseline.parquet','SELECT key,size,etag,sha256_verified FROM compared WHERE NOT missing'),
                 output('anomalies',work/'anomalies.parquet','SELECT * FROM compared WHERE missing OR mismatch'),
                 output('work',work/'work.parquet','SELECT * FROM work'),
                 output('digest-repairs',work/'digest-repairs.parquet','SELECT * FROM digest_repairs')],
        queries=[dict(name='counts',sql="SELECT count(*) AS listed,count(*) FILTER(WHERE etag LIKE '%-%') AS multipart FROM listing"),
                 dict(name='issues',sql='SELECT count(*) FILTER(WHERE missing) AS missing,count(*) FILTER(WHERE mismatch AND NOT missing) AS mismatches FROM compared'),
                 dict(name='repairs',sql='SELECT count(*) AS digest_repairs FROM digest_repairs'),
                 dict(name='capture_rows',sql='SELECT count(*) AS rows FROM old')])
    if native and reports['capture_rows'][0]['rows']!=captures['expected_rows']:
        raise ValueError('Selected capture source count differs from pinned manifest')
    counts=dict(reports['counts'][0],**reports['issues'][0],**reports['repairs'][0])
    checks=work/'checked.jsonl.gz'
    checked=0
    errors=0
    with gzip.open(checks,'wt',encoding='utf-8') as out:
        for row in parquet_records(work/'work.parquet'):
            measured=check_body(store,row,checked_at=checked_at)
            checked+=1
            errors+=not measured['sha256_verified']
            out.write(json.dumps(measured,separators=(',',':'))+'\n')
    records=work/'verification.jsonl'
    valid=not counts['missing'] and not counts['mismatches'] and not errors
    result=dict(counts,checked=checked,content_errors=errors,valid=bool(valid),records=str(records),
                capture_identity=captures['identity'] if native else file_pin(captures)['sha256'])
    if valid:
        # Typed native output is serialized only at the raw-record writer boundary;
        # all matching, winner selection and verification decisions remain native.
        fresh_schema=dict(verify_schema,stored_sha256='Utf8',error='Utf8')
        final=run_job(engine,work/'accepted',inputs=[dict(name='baseline',kind='parquet',path=str((work/'baseline.parquet').resolve())),
            json_input('checked',[dict(key='checked',path=str(checks.resolve()))],fresh_schema)],
            steps=[('accepted',f"SELECT b.key,b.size,b.etag,coalesce(c.sha256_verified,b.sha256_verified) AS sha256_verified,'{stamp.astimezone(timezone.utc).isoformat()}' AS checked_at,'raw-verifier' AS job FROM baseline b LEFT JOIN checked c ON b.key=c.key")],
            outputs=[output('accepted',work/'accepted.parquet','SELECT * FROM accepted')],queries=[])
        with records.open('x',encoding='utf-8') as out:
            for row in parquet_records(work/'accepted.parquet'):
                out.write(json.dumps(row,separators=(',',':'))+'\n')
        with records.open('rb') as source:
            result['records_sha256']=hashlib.file_digest(source,'sha256').hexdigest()
        result['provenance_key']='provenance/verification/'+stamp.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+seed[:16]+'.jsonl'
    (work/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
