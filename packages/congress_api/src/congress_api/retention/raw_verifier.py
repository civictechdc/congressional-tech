"""Raw inventory checks. Native SQL owns joins; storage adapters only LIST and GET."""
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import secrets

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.tables import table_input
from congress_api.retention.body_store import BODY
from congress_api.retention.provenance import (field, parquet_output, parquet_records,
                                               file_pin, run_job)

D1_CAPTURE_SCHEMA = pa.schema([
    ('sha256', pa.binary(32)),
    ('stored_suffix', pa.string()),
    ('stored_bytes', pa.int64()),
    ('stored_md5', pa.binary(16)),
    ('receipt_key', pa.string()),
    ('receipt_line', pa.int64()),
    ('capture_index', pa.int32()),
])


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


def verify(store, *, captures, receipts, previous, engine, work, checked_at, seed=None, full_rehash=False):
    """Stage reports and accepted verification records; never repair or upload implicitly."""
    if type(full_rehash) is not bool:
        raise ValueError('full_rehash must be an explicit boolean')
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
    old_native=isinstance(captures,dict) and 'inputs' in captures
    d1_native=isinstance(captures,dict) and not old_native and (
        captures.get('kind')=='native_table' or 'metadata_location' in captures)
    if old_native:
        schema=captures['schema']
        capture_inputs=captures['inputs']
        capture_identity=captures['identity']
    elif d1_native:
        pin={k:captures.get(k) for k in ('metadata_location','table_uuid','snapshot','schema_id')}
        schema=D1_CAPTURE_SCHEMA
        capture_inputs=[table_input('old',pin)]
        capture_identity=hashlib.sha256(json.dumps(pin,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    else:
        capture_path=Path(captures['path'] if isinstance(captures,dict) else captures)
        schema=pq.read_schema(capture_path)
        capture_inputs=[dict(name='old',kind='parquet',path=str(capture_path.resolve()))]
        capture_identity=file_pin(capture_path)['sha256']
    def column(name, kind='VARCHAR'):
        if name not in schema.names:
            return f'cast(NULL AS {kind})'
        value='"'+name+'"'
        field_type=schema.field(name).type
        if name in {'sha256','stored_sha256','stored_md5'} and (
                pa.types.is_binary(field_type) or pa.types.is_fixed_size_binary(field_type)):
            value=f"lower(encode({value},'hex'))"
        return value
    sha=column('sha256')
    suffix=f"coalesce({column('stored_suffix')},'.gz')"
    derived=f"CASE WHEN regexp_like({sha},'^[a-f0-9]{{64}}$') THEN concat('bodies/sha256/',substr({sha},1,2),'/',{sha},{suffix}) END"
    index_key=f"coalesce({column('body_key')},{derived})"
    entry={'Struct':[field(n,t) for n,t in dict(body_key='Utf8',sha256='Utf8',stored_suffix='Utf8',
        stored_md5='Utf8',stored_sha256='Utf8',stored_bytes='Int64',bytes='Int64').items()]}
    receipt_schema={n:{'List':field('item',entry)} for n in ('captures','file_references')}
    verify_schema=dict(key='Utf8',size='Int64',etag='Utf8',sha256_verified='Boolean',
        stored_sha256='Utf8',checked_at='Utf8',job='Utf8')
    inputs=[json_input('listing',listing_files,dict(key='Utf8',size='Int64',etag='Utf8')),
            json_input('receipts',receipts,receipt_schema),json_input('previous',previous,verify_schema)]
    inputs+=capture_inputs
    steps=[]
    def step(name,sql,materialize=False):
        steps.append(dict(name=name,sql=sql,materialize=materialize))
    if old_native:step('old',captures['sql'])
    step('listed','SELECT key,size,etag FROM listing',True)
    step('index_refs',f"SELECT {index_key} AS key,{column('stored_bytes','BIGINT')} AS size,{column('stored_md5')} AS md5,{column('stored_sha256')} AS stored_sha256,{column('receipt_key')} AS receipt_key,{column('receipt_line','BIGINT')} AS receipt_line,{column('pointer_json')} AS pointer_json FROM old",True)
    step('receipt_entries',"""SELECT __source_key AS receipt_key,__source_line AS receipt_line,
        unnest(array_concat(coalesce(captures,make_array()),coalesce(file_references,make_array()))) AS c FROM receipts""")
    step('receipt_refs',"""SELECT coalesce(c['body_key'],CASE WHEN regexp_like(c['sha256'],'^[a-f0-9]{64}$') THEN concat('bodies/sha256/',substr(c['sha256'],1,2),'/',c['sha256'],coalesce(c['stored_suffix'],'.gz')) END) AS key,c['stored_bytes'] AS size,c['stored_md5'] AS md5,c['stored_sha256'] AS stored_sha256,receipt_key,receipt_line FROM receipt_entries""",True)
    step('all_refs','SELECT key,size,md5 FROM index_refs UNION ALL SELECT key,size,md5 FROM receipt_refs')
    step('refs',"SELECT key,min(size) AS size,min(md5) AS md5,count(DISTINCT size)>1 OR count(DISTINCT md5)>1 AS conflicting FROM all_refs WHERE key IS NOT NULL GROUP BY key")
    step('ranked_previous',"SELECT *,row_number() OVER(PARTITION BY key ORDER BY checked_at DESC,__source_key DESC,__source_line DESC) AS ranking FROM previous WHERE key LIKE 'bodies/%'")
    step('verified','SELECT key,size,etag,sha256_verified,stored_sha256,checked_at FROM ranked_previous WHERE ranking=1',True)
    step('expected',"""SELECT coalesce(r.key,v.key) AS key,r.size,r.md5,r.conflicting,
        r.key IS NOT NULL AS has_capture,v.key IS NOT NULL AS has_verification,
        v.size AS verified_size,v.etag AS verified_etag,v.sha256_verified,
        v.stored_sha256 AS previous_stored_sha256,v.checked_at AS previous_checked_at
        FROM refs r FULL OUTER JOIN verified v ON r.key=v.key""")
    step('compared',"""SELECT coalesce(l.key,e.key) AS key,l.size,l.etag,
        e.key IS NOT NULL AS referenced,l.key IS NULL AS missing,
        coalesce(e.has_capture,false) AS has_capture,coalesce(e.has_verification,false) AS has_verification,
        coalesce(e.conflicting,false) OR (e.size IS NOT NULL AND l.size<>e.size)
        OR (e.verified_size IS NOT NULL AND l.size<>e.verified_size)
        OR (e.verified_etag IS NOT NULL AND l.etag<>e.verified_etag)
        OR (e.md5 IS NOT NULL AND l.etag<>e.md5) AS mismatch,
        coalesce(e.sha256_verified,false) AS sha256_verified,
        e.verified_size,e.verified_etag,e.previous_stored_sha256,e.previous_checked_at
        FROM listed l FULL OUTER JOIN expected e ON l.key=e.key""",True)
    step('sample',f"SELECT key,size,etag FROM listed ORDER BY sha256('{seed}' || key),key LIMIT 25")
    step('orphans','SELECT key,size,etag FROM compared WHERE NOT has_capture AND NOT missing')
    work_sql=(
        "SELECT key,size,etag FROM compared WHERE NOT missing AND NOT (sha256_verified AND verified_size=size AND verified_etag=etag AND coalesce(regexp_like(previous_stored_sha256,'^[a-f0-9]{64}$'),false))"
        if full_rehash else
        'SELECT key,size,etag FROM compared WHERE NOT has_capture AND NOT has_verification AND NOT missing UNION SELECT key,size,etag FROM sample'
    )
    step('work',work_sql)
    step('digest_facts',"""SELECT key,receipt_key,receipt_line,min(stored_sha256) AS receipt_stored_sha256,
        min(size) AS receipt_stored_bytes,count(DISTINCT stored_sha256) AS hashes,count(DISTINCT size) AS sizes
        FROM receipt_refs WHERE key IS NOT NULL AND stored_sha256 IS NOT NULL GROUP BY key,receipt_key,receipt_line""")
    step('digest_totals',"""SELECT key,count(DISTINCT stored_sha256) AS key_hashes
        FROM receipt_refs WHERE key IS NOT NULL GROUP BY key""")
    step('digest_evidence',"""SELECT r.*,t.key_hashes,i.pointer_json,i.stored_sha256 AS old_stored_sha256,
        i.size AS old_stored_bytes,i.receipt_key IS NOT NULL AS indexed,
        i.receipt_key IS NOT NULL AND ((i.stored_sha256 IS DISTINCT FROM r.receipt_stored_sha256)
        OR (r.receipt_stored_bytes IS NOT NULL AND (i.size IS DISTINCT FROM r.receipt_stored_bytes))) AS candidate
        FROM digest_facts r JOIN digest_totals t ON r.key=t.key LEFT JOIN index_refs i
        ON i.key=r.key AND i.receipt_key=r.receipt_key AND i.receipt_line=r.receipt_line""")
    inventory=work/'inventory';inventory.mkdir()
    reports=run_job(inventory,engine,inputs=inputs,steps=steps,
        outputs=[output('baseline',work/'baseline.parquet','SELECT * FROM compared WHERE NOT missing'),
                 output('anomalies',work/'anomalies.parquet','SELECT * FROM compared WHERE missing OR mismatch'),
                 output('work',work/'work.parquet','SELECT * FROM work'),
                 output('orphans',work/'orphans.parquet','SELECT * FROM orphans'),
                 output('digest-evidence',work/'digest-evidence.parquet','SELECT * FROM digest_evidence',('key','receipt_key','receipt_line','pointer_json'))],
        queries=[dict(name='counts',sql="SELECT count(*) AS listed,count(*) FILTER(WHERE etag LIKE '%-%') AS multipart FROM listed"),
                 dict(name='issues',sql='SELECT count(*) FILTER(WHERE missing) AS missing,count(*) FILTER(WHERE mismatch AND NOT missing) AS mismatches FROM compared'),
                 dict(name='orphans',sql='SELECT count(*) AS orphans FROM orphans'),
                 dict(name='capture_rows',sql='SELECT count(*) AS rows FROM index_refs')])
    if old_native and reports['capture_rows'][0]['rows']!=captures['expected_rows']:
        raise ValueError('Selected capture source count differs from pinned manifest')
    counts=dict(reports['counts'][0],**reports['issues'][0],**reports['orphans'][0])
    checks=work/'checked.jsonl.gz'
    checked=errors=0
    with gzip.open(checks,'wt',encoding='utf-8') as out:
        for row in parquet_records(work/'work.parquet'):
            measured=check_body(store,row,checked_at=checked_at)
            checked+=1
            errors+=not measured['sha256_verified']
            out.write(json.dumps(measured,separators=(',',':'))+'\n')
    # Only this last job can qualify a receipt assertion against measured bytes.
    final=work/'final';final.mkdir()
    fresh_schema=dict(verify_schema,error='Utf8')
    fresh="""c.sha256_verified IS TRUE AND c.error IS NULL AND c.size=b.size AND c.etag=b.etag
        AND regexp_like(c.stored_sha256,'^[a-f0-9]{64}$')"""
    prior="""b.sha256_verified IS TRUE AND b.verified_size=b.size AND b.verified_etag=b.etag
        AND regexp_like(b.previous_stored_sha256,'^[a-f0-9]{64}$')"""
    final_steps=[dict(name='measured_sources',sql=f"""SELECT b.*,c.key IS NOT NULL AS checked,
        c.stored_sha256 AS fresh_stored_sha256,c.checked_at AS fresh_checked_at,
        coalesce(({fresh}),false) AS fresh_usable,coalesce(({prior}),false) AS prior_usable
        FROM baseline b LEFT JOIN checked c ON b.key=c.key"""),
        dict(name='measurements',sql="""SELECT *,
            fresh_usable AND prior_usable AND fresh_stored_sha256<>previous_stored_sha256 AS measurement_conflict,
            CASE WHEN fresh_usable THEN fresh_stored_sha256
                 WHEN prior_usable AND NOT checked THEN previous_stored_sha256 END AS measured_stored_sha256,
            CASE WHEN fresh_usable THEN fresh_checked_at ELSE previous_checked_at END AS checked_at,
            CASE WHEN fresh_usable THEN 'current_read' WHEN prior_usable AND NOT checked THEN 'prior_verification' END AS evidence_source
            FROM measured_sources""",materialize=True),
        dict(name='qualified_evidence',sql="""SELECT r.*,m.size,m.etag,m.checked_at,m.evidence_source,
            m.measured_stored_sha256,m.measurement_conflict,
            (r.hashes<>1 OR r.sizes>1 OR r.key_hashes>1
             OR NOT coalesce(regexp_like(r.receipt_stored_sha256,'^[a-f0-9]{64}$'),false)
             OR coalesce(m.measurement_conflict,false)
             OR (m.measured_stored_sha256 IS NOT NULL AND (r.receipt_stored_sha256<>m.measured_stored_sha256
                 OR (r.receipt_stored_bytes IS NOT NULL AND r.receipt_stored_bytes<>m.size)))) AS conflicting
            FROM digest_evidence r LEFT JOIN measurements m ON r.key=m.key""",materialize=True),
        dict(name='digest_conflicts',sql="""SELECT *,CASE WHEN measurement_conflict THEN 'contradictory_measurements'
            WHEN hashes<>1 OR sizes>1 OR key_hashes>1 THEN 'conflicting_receipt_assertions'
            ELSE 'receipt_measurement_mismatch' END AS reason FROM qualified_evidence WHERE conflicting"""),
        dict(name='digest_repairs',sql="""SELECT DISTINCT key,receipt_key,receipt_line,pointer_json,old_stored_sha256,
            measured_stored_sha256 AS stored_sha256,size AS stored_bytes,
            receipt_stored_sha256,receipt_stored_bytes,measured_stored_sha256,true AS sha256_verified,
            size,etag,checked_at,evidence_source FROM qualified_evidence
            WHERE candidate AND NOT conflicting AND measured_stored_sha256 IS NOT NULL"""),
        dict(name='unmeasured',sql="SELECT *,'unmeasured' AS status FROM qualified_evidence WHERE candidate AND NOT conflicting AND measured_stored_sha256 IS NULL"),
        dict(name='accepted',sql=f"""SELECT key,size,etag,
            fresh_usable OR sha256_verified AS sha256_verified,
            CASE WHEN fresh_usable THEN fresh_stored_sha256 ELSE previous_stored_sha256 END AS stored_sha256,
            '{stamp.astimezone(timezone.utc).isoformat()}' AS checked_at,'raw-verifier' AS job
            FROM measurements WHERE NOT has_verification OR fresh_usable""")]
    result_counts=run_job(final,engine,inputs=[
        dict(name='baseline',kind='parquet',path=str((work/'baseline.parquet').resolve())),
        dict(name='digest_evidence',kind='parquet',path=str((work/'digest-evidence.parquet').resolve())),
        json_input('checked',[dict(key='checked',path=str(checks.resolve()))],fresh_schema)],steps=final_steps,
        outputs=[output('accepted',work/'accepted.parquet','SELECT * FROM accepted'),
                 output('measurement-conflicts',work/'measurement-conflicts.parquet','SELECT * FROM measurements WHERE measurement_conflict'),
                 output('digest-conflicts',work/'digest-conflicts.parquet','SELECT * FROM digest_conflicts',('key','receipt_key','receipt_line','pointer_json')),
                 output('digest-repairs',work/'digest-repairs.parquet','SELECT * FROM digest_repairs',('key','receipt_key','receipt_line','pointer_json','old_stored_sha256')),
                 output('unmeasured-digests',work/'unmeasured-digests.parquet','SELECT * FROM unmeasured',('key','receipt_key','receipt_line','pointer_json'))],
        queries=[dict(name='counts',sql="""SELECT (SELECT count(*) FROM digest_conflicts) AS digest_conflicts,
            (SELECT count(*) FROM digest_repairs) AS digest_repairs,
            (SELECT count(*) FROM unmeasured) AS unmeasured_candidates,
            (SELECT count(*) FROM accepted) AS accepted_records,
            (SELECT count(*) FROM measurements WHERE measurement_conflict) AS measurement_conflicts""")])['counts'][0]
    counts.update(result_counts)
    records=work/'verification.jsonl'
    valid=not counts['missing'] and not counts['mismatches'] and not counts['digest_conflicts'] and not counts['measurement_conflicts'] and not errors
    counts['candidate_records']=counts['accepted_records']
    if not valid:counts['accepted_records']=0
    result=dict(counts,checked=checked,content_errors=errors,valid=bool(valid),records=str(records),
                full_rehash=full_rehash,capture_identity=capture_identity)
    if valid:
        with records.open('x',encoding='utf-8') as out:
            for row in parquet_records(work/'accepted.parquet'):
                out.write(json.dumps(row,separators=(',',':'))+'\n')
        result['records_sha256']=file_pin(records)['sha256']
        result['provenance_key']='provenance/verification/'+stamp.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+seed[:16]+'.jsonl'
    (work/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
