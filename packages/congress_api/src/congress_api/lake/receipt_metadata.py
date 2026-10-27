"""Narrow receipt facts before expanding bodies; payload bytes stay in raw."""
from pathlib import Path
import json

import pyarrow.parquet as pq

from congress_api.retention.provenance import field, struct, list_of, run_job, file_pin, parquet_output


STRINGS = ('source_file','run_id','mode','outcome','family','requested_url','url','_url',
    'final_url','resolved_url','source_url','retrieved_at','captured_at','observed_at',
    'parent_retrieved_at','_retrieved_at','capture_date','error_type')
NUMBERS = ('http_status','status_code')
BOOLS = ('complete',)
HEADERS = ('content-type','content-length','content-disposition','content-encoding','etag',
           'last-modified','retry-after','date','cache-control','accept-ranges')
SCALARS = {**dict.fromkeys(STRINGS,'str'),**dict.fromkeys(NUMBERS,'int'),**dict.fromkeys(BOOLS,'bool')}


def lit(value):return "'"+str(value).replace("'","''")+"'"


def get(value,*path,kind='str'):
    expression=f'json_get_{kind}({value}'+(' ,'+','.join(str(p) if isinstance(p,int) else lit(p) for p in path) if path else '')+')'
    return f"nullif({expression},'null')" if kind=='json' else expression


def obj(fields):
    return 'named_struct('+','.join(lit(k)+','+v for k,v in fields.items())+')'


def scalar_json(value,name,kind):
    if kind=='int':return f'try_cast(json_as_text({value},{lit(name)}) AS BIGINT)'
    return get(value,name,kind=kind)


def source_schema():
    scalars={**dict.fromkeys(STRINGS,'Utf8'),**dict.fromkeys(NUMBERS,'Int64'),**dict.fromkeys(BOOLS,'Boolean')}
    headers=struct(**dict.fromkeys(HEADERS,'Utf8'))
    evidence=struct(original_url='Utf8',imported_at='Utf8',match_basis='Utf8',acquisition=struct(
        prior_access_category='Utf8',recovered_url='Utf8',evidence_sha256='Utf8',body_path='Utf8'))
    prior=list_of(struct(**scalars))
    record=struct(**scalars,response_headers=headers,headers=headers,recovery_evidence=evidence,
        source_associations=list_of(struct(original_url='Utf8',basis='Utf8',imported_at='Utf8')),
        response_header_items=list_of(struct(name='Utf8',value='Utf8')),prior_attempts=prior)
    roots={**scalars, 'record':record,'captures':list_of(struct(sha256='Utf8')),
        'file_references':list_of(struct(sha256='Utf8')),'response_headers':headers,
        'recovery_evidence':evidence,'prior_attempts':prior,
        'writer':struct(job='Utf8',commit='Utf8',lockfile_digest='Utf8')}
    return dict(fields=[field(k,v) for k,v in roots.items()],metadata={})


def compact(*,engine,work,counter=None,files=None):
    """Export one small metadata row per source line through the native job.

    Record lists and prior attempts are narrowed independently before joining.
    In particular, neither a complete page body nor a prior response body is
    repeated once per capture. Intermediate order is immaterial; the target
    mapping orders by its unique receipt positions.
    """
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    steps=[]
    def step(name,sql,**options):steps.append(dict(name=name,sql=sql,**options))
    if counter is not None:
        schema=pq.read_schema(counter)
        required={'__receipt_key','__receipt_line','__raw_line','__type_conflicts',
                  '__receipt_family','record','captures','file_references'}
        if not required.issubset(schema.names):
            raise ValueError('Counter is not the validated typed/raw receipt reader result')
        inputs=[dict(name='source',kind='parquet',path=str(Path(counter).resolve()))]
        if '__line_shape' in schema.names:
            step('counter','SELECT * FROM source')
        else:
            step('counter',"""SELECT *,CASE WHEN left(ltrim(json_get_json(__raw_line,'record')),1)='['
                THEN 'record:array' ELSE 'record:object' END AS __line_shape FROM source""")
        record_type=schema.field('record').type
        record_names=set(record_type.names)
        root_names=set(schema.names)
        validated=True
    else:
        arrow=source_schema()
        inputs=[dict(name='source',kind='json_lines',files=files,schema=arrow)]
        step('counter',f'''SELECT *,__source_key AS __receipt_key,__source_line AS __receipt_line,
            regexp_replace(__source_key,'^receipts/(.*)/[^/]+/[^/]+$','\\1') AS __receipt_family,
            CASE WHEN left(ltrim(json_get_json(__raw_line,'record')),1)='['
                 THEN 'record:array' ELSE 'record:object' END AS __line_shape FROM source''')
        record_names={f['name'] for f in next(f for f in arrow['fields'] if f['name']=='record')['data_type']['Struct']}
        root_names={f['name'] for f in arrow['fields']}
        validated=False
    def typed(name,kind,*,record=False):
        names=record_names if record else root_names
        raw='__raw_line'
        path=('record',name) if record else (name,)
        fallback=(f'try_cast(json_as_text({raw},'+','.join(lit(p) for p in path)+') AS BIGINT)'
                  if kind=='int' else get(raw,*path,kind=kind))
        nulltype={'str':'VARCHAR','int':'BIGINT','bool':'BOOLEAN'}[kind]
        value=('get_field(record,'+lit(name)+')' if record else '"'+name+'"') if name in names else f'cast(NULL AS {nulltype})'
        if name not in names:return fallback
        if not validated:return f'coalesce({value},{fallback})'
        # Only the qualified counter carries its exact type-conflict census.
        # Missing scalar values are genuine nulls unless a typed path conflicted.
        path_json=json.dumps(list(path),separators=(',',':'))
        conflict='array_has(__type_conflicts,'+lit(path_json)+')'
        return f'CASE WHEN {conflict} THEN {fallback} ELSE {value} END'
    def fragments(raw,prefix=()):
        return {'_ingest_headers_json':get(raw,*prefix,'response_headers',kind='json'),
            '_ingest_other_headers_json':get(raw,*prefix,'headers',kind='json'),
            '_ingest_header_items_json':get(raw,*prefix,'response_header_items',kind='json'),
            '_ingest_recovery_json':get(raw,*prefix,'recovery_evidence',kind='json'),
            '_ingest_assoc_json':get(raw,*prefix,'source_associations',kind='json'),
            '_ingest_error_json':get(raw,*prefix,'error',kind='json'),
            '_ingest_archive_member_count':f'json_length({raw},'+','.join(lit(p) for p in (*prefix,'archive_members'))+')'}
    metadata={n:typed(n,k,record=True) for n,k in SCALARS.items()}
    metadata.update(fragments('__raw_line',('record',)))
    step('object_records',f'''SELECT __receipt_key AS receipt_key,__receipt_line AS receipt_line,
        cast(0 AS BIGINT) AS record_index,false AS is_list,{obj(metadata)} AS metadata,
        json_get_json(__raw_line,'record','prior_attempts') AS prior_json
        FROM counter WHERE __line_shape<>'record:array' ''')
    step('list_entries','''SELECT __receipt_key AS receipt_key,__receipt_line AS receipt_line,
        unnest(json_get_array(__raw_line,'record')) AS record_value,
        unnest(range(0,cast(coalesce(json_length(__raw_line,'record'),0) AS BIGINT))) AS record_index
        FROM counter WHERE __line_shape='record:array' ''')
    list_meta={n:scalar_json('record_value',n,k) for n,k in SCALARS.items()}
    list_meta.update(fragments('record_value'))
    step('list_records',f'''SELECT receipt_key,receipt_line,record_index,true AS is_list,
        {obj(list_meta)} AS metadata,json_get_json(record_value,'prior_attempts') AS prior_json FROM list_entries''')
    step('records','SELECT * FROM object_records UNION ALL SELECT * FROM list_records')
    step('prior_entries','''SELECT receipt_key,receipt_line,record_index,
        unnest(json_get_array(prior_json)) AS prior_value,
        unnest(range(0,cast(coalesce(json_length(prior_json),0) AS BIGINT))) AS prior_index FROM records''')
    prior={n:scalar_json('prior_value',n,k) for n,k in SCALARS.items()}
    step('prior_metadata',f'''SELECT receipt_key,receipt_line,record_index,
        json_get_json(json_array(array_agg({obj(prior)} ORDER BY prior_index)),0) AS prior_json
        FROM prior_entries GROUP BY receipt_key,receipt_line,record_index''')
    final_meta={n:'get_field(r.metadata,'+lit(n)+')' for n in metadata}
    final_meta['_ingest_prior_attempts_json']='p.prior_json'
    step('small_records',f'''SELECT r.receipt_key,r.receipt_line,r.record_index,r.is_list,
        {obj(final_meta)} AS metadata FROM records r LEFT JOIN prior_metadata p
        USING(receipt_key,receipt_line,record_index)''')
    step('record_objects',"SELECT receipt_key,receipt_line,json_get_json(json_array(metadata),0) AS record_json FROM small_records WHERE NOT is_list")
    step('record_lists',"""SELECT receipt_key,receipt_line,
        json_get_json(json_array(array_agg(metadata ORDER BY record_index)),0) AS record_json
        FROM small_records WHERE is_list GROUP BY receipt_key,receipt_line""")
    step('record_metadata','SELECT * FROM record_objects UNION ALL SELECT * FROM record_lists')
    roots={n:'"'+n+'"' for n in sorted(root_names) if n in {*SCALARS,'response_headers','recovery_evidence','prior_attempts','writer'}}
    roots['_ingest_record_sha']="""CASE WHEN __receipt_family='congress/meetings'
        THEN encode(sha256(json_canonical(coalesce(nullif(json_get_json(__raw_line,'record','meeting'),'null'),
            nullif(json_get_json(__raw_line,'record'),'null')))),'hex') END"""
    step('root_metadata',f'''SELECT __receipt_key AS receipt_key,__receipt_line AS receipt_line,
        json_get_json(json_array({obj(roots)}),0) AS line,
        json_get_json(__raw_line,'captures') AS caps_json,
        json_get_json(__raw_line,'file_references') AS refs_json FROM counter''')
    destination=work/'receipt-metadata.parquet'
    sql='''SELECT r.receipt_key AS __receipt_key,r.receipt_line AS __receipt_line,
        r.line,r.caps_json,r.refs_json,m.record_json FROM root_metadata r
        LEFT JOIN record_metadata m USING(receipt_key,receipt_line)'''
    result=run_job(work,engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(work,'receipt-metadata',sql,['__receipt_key','__receipt_line'])],queries=[
        dict(name='source_counts',sql='SELECT count(*) AS rows,count(DISTINCT __receipt_key) AS receipts FROM counter')])
    actual=pq.read_metadata(destination).num_rows
    if actual!=result['source_counts'][0]['rows']:
        raise ValueError('Receipt metadata projection changed the source line population')
    (work/'metadata.json').write_text(json.dumps(dict(version=1,rows=actual,
        source=result['source_counts'][0],file=file_pin(destination)),indent=2)+'\n')
    return destination
