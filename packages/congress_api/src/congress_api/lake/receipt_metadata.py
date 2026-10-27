"""Narrow receipt facts before expanding bodies; payload bytes stay in raw."""
from pathlib import Path
from hashlib import sha256
import json

import pyarrow.parquet as pq

from congress_api.retention.provenance import field, struct, list_of, run_job, file_pin, parquet_output, json_input
from congress_api.retention.body_store import validate_key


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
    # C1 can expose Utf8View; this private shape always stores ordinary Utf8.
    return 'named_struct('+','.join(lit(k)+','+(f'cast({v} AS VARCHAR)'
        if SCALARS.get(k,'str')=='str' else v) for k,v in fields.items())+')'


def scalar_json(value,name,kind):
    if kind=='int':return f'try_cast(json_as_text({value},{lit(name)}) AS BIGINT)'
    return get(value,name,kind=kind)


def counter_file(counter):
    """Raw counters are qualified single files, never implicit datasets."""
    path=Path(counter).resolve()
    if not path.is_file():
        raise ValueError('A validated counter must be a single local file')
    return path


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


def metadata_plan(*,counter=None,files=None,receipt_keys=None):
    """Build shared native narrowing steps without exporting intermediate rows.

    Record lists and prior attempts are narrowed independently before joining.
    In particular, neither a complete page body nor a prior response body is
    repeated once per capture. Intermediate order is immaterial; the target
    mapping orders by its unique receipt positions.
    """
    steps=[]
    def step(name,sql,**options):steps.append(dict(name=name,sql=sql,**options))
    if counter is not None:
        counter=counter_file(counter)
        schema=pq.read_schema(counter)
        required={'__receipt_key','__receipt_line','__raw_line','__type_conflicts',
                  '__receipt_family','record','captures','file_references'}
        if not required.issubset(schema.names):
            raise ValueError('Counter is not the validated typed/raw receipt reader result')
        inputs=[dict(name='source',kind='parquet',path=str(Path(counter).resolve()))]
        selected=(' WHERE __receipt_key IN ('+','.join(lit(key) for key in receipt_keys)+')'
                  if receipt_keys else ' WHERE false') if receipt_keys is not None else ''
        if '__line_shape' in schema.names:
            step('counter','SELECT * FROM source'+selected)
        else:
            step('counter',"""SELECT *,CASE WHEN left(ltrim(json_get_json(__raw_line,'record')),1)='['
                THEN 'record:array' ELSE 'record:object' END AS __line_shape FROM source"""+selected)
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
            '_ingest_error_json':get(raw,*prefix,'error',kind='json')}
    def root_json(name,kind='object'):
        value=get('__raw_line',name,kind='json')
        if validated and '__field_paths' in root_names:
            label=json.dumps([name],separators=(',',':'))+'#'+kind
            return f'''CASE WHEN __field_paths IS NULL OR array_has(__field_paths,{lit(label)})
                THEN {value} ELSE cast(NULL AS VARCHAR) END'''
        return value
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
    step('metadata_records','SELECT * FROM object_records UNION ALL SELECT * FROM list_records')
    root_prior=root_json('prior_attempts','array')
    step('root_prior_sources',f'''SELECT __receipt_key AS receipt_key,__receipt_line AS receipt_line,
        cast(-1 AS BIGINT) AS record_index,{root_prior} AS prior_json
        FROM counter WHERE {root_prior} IS NOT NULL''')
    step('prior_sources','''SELECT receipt_key,receipt_line,record_index,prior_json FROM metadata_records
        UNION ALL SELECT * FROM root_prior_sources''')
    step('prior_entries','''SELECT receipt_key,receipt_line,record_index,
        unnest(json_get_array(prior_json)) AS prior_value,
        unnest(range(0,cast(coalesce(json_length(prior_json),0) AS BIGINT))) AS prior_index FROM prior_sources''')
    prior={n:scalar_json('prior_value',n,k) for n,k in SCALARS.items()}
    step('prior_metadata',f'''SELECT receipt_key,receipt_line,record_index,
        json_get_json(json_array(array_agg({obj(prior)} ORDER BY prior_index)),0) AS prior_json
        FROM prior_entries GROUP BY receipt_key,receipt_line,record_index''',materialize=True,
        release_after=['prior_entries','prior_sources','root_prior_sources'])
    final_meta={n:'get_field(r.metadata,'+lit(n)+')' for n in metadata}
    final_meta['_ingest_prior_attempts_json']='p.prior_json'
    step('small_records',f'''SELECT r.receipt_key,r.receipt_line,r.record_index,r.is_list,
        {obj(final_meta)} AS metadata FROM metadata_records r LEFT JOIN prior_metadata p
        USING(receipt_key,receipt_line,record_index)''',materialize=True,
        release_after=['object_records','list_entries','list_records','metadata_records'])
    step('record_objects',"SELECT receipt_key,receipt_line,make_array(metadata) AS record_values FROM small_records WHERE NOT is_list")
    step('record_lists',"""SELECT receipt_key,receipt_line,
        array_agg(metadata ORDER BY record_index) AS record_values
        FROM small_records WHERE is_list GROUP BY receipt_key,receipt_line""")
    step('record_metadata','SELECT * FROM record_objects UNION ALL SELECT * FROM record_lists',
        materialize=True,release_after=['record_objects','record_lists','small_records'])
    roots={n:typed(n,kind) for n,kind in sorted(SCALARS.items())}
    roots.update(_ingest_prior_attempts_json='p.prior_json',
                 _ingest_recovery_json=root_json('recovery_evidence'),
                 _ingest_writer_json=root_json('writer'))
    # Headers can be top-level on new lines, with case-preserving field names
    # absent from an older typed counter. Keep their small raw fragments once.
    roots.update({name:get('__raw_line',field,kind='json') for name,field in [
        ('_ingest_headers_json','response_headers'),
        ('_ingest_header_items_json','response_header_items'),
        ('_ingest_other_headers_json','headers')]})
    roots['_ingest_record_sha']="""CASE WHEN __receipt_family='congress/meetings'
        THEN encode(sha256(json_canonical(coalesce(nullif(json_get_json(__raw_line,'record','meeting'),'null'),
            nullif(json_get_json(__raw_line,'record'),'null')))),'hex') END"""
    step('root_metadata',f'''SELECT c.__receipt_key AS receipt_key,c.__receipt_line AS receipt_line,
        {obj(roots)} AS line,__line_shape='record:array' AS record_is_list,
        json_get_json(__raw_line,'captures') AS caps_json,
        json_get_json(__raw_line,'file_references') AS refs_json FROM counter c LEFT JOIN prior_metadata p
        ON c.__receipt_key=p.receipt_key AND c.__receipt_line=p.receipt_line AND p.record_index=-1''',
        materialize=True,release_after=['counter','source','prior_metadata'])
    locator='''arrow_cast(named_struct('key',receipt_key,'line',receipt_line),
        'Struct("key": Utf8, "line": Int64)')'''
    sql=f'''SELECT get_field({locator},'key') AS __receipt_key,get_field({locator},'line') AS __receipt_line,
        r.line,r.caps_json,r.refs_json,m.record_values,r.record_is_list FROM root_metadata r
        LEFT JOIN record_metadata m USING(receipt_key,receipt_line)'''
    if counter is not None and receipt_keys==[]:
        # An explicit empty work list retains the same schema without building
        # record unions or reading receipt payloads.
        nulls={n:f"cast(NULL AS { {'str':'VARCHAR','int':'BIGINT','bool':'BOOLEAN'}[kind] })"
               for n,kind in SCALARS.items()}
        empty_record={n:nulls.get(n,'cast(NULL AS VARCHAR)') for n in final_meta}
        empty_root={n:nulls.get(n,'cast(NULL AS VARCHAR)') for n in roots}
        list_shape="__line_shape='record:array'" if '__line_shape' in schema.names else (
            "CASE WHEN left(ltrim(json_get_json(__raw_line,'record')),1)='[' THEN true ELSE false END")
        steps=[dict(name='root_metadata',sql="SELECT __receipt_key AS receipt_key,"+
            "__receipt_line AS receipt_line,* EXCEPT(__receipt_key,__receipt_line) FROM source WHERE false")]
        sql=f'''SELECT get_field({locator},'key') AS __receipt_key,get_field({locator},'line') AS __receipt_line,
            {obj(empty_root)} AS line,json_get_json(__raw_line) AS caps_json,
            json_get_json(__raw_line) AS refs_json,
            CASE WHEN __raw_line IS NOT NULL THEN make_array({obj(empty_record)}) END AS record_values,
            {list_shape} AS record_is_list FROM root_metadata'''
    return dict(inputs=inputs,steps=steps,sql=sql)


def _compact(*,engine,work,counter=None,files=None,receipt_keys=None,destination=None):
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    plan=metadata_plan(counter=counter,files=files,receipt_keys=receipt_keys)
    destination=Path(destination) if destination is not None else work/'receipt-metadata.parquet'
    output=parquet_output(work,'receipt-metadata',plan['sql'],['__receipt_key','__receipt_line'])
    output['path']=str(destination.resolve())
    result=run_job(work,engine,inputs=plan['inputs'],steps=plan['steps'],outputs=[output],queries=[
        dict(name='source_counts',sql='SELECT count(*) AS rows,count(DISTINCT receipt_key) AS receipts FROM root_metadata'),
        dict(name='receipt_keys',sql='SELECT DISTINCT receipt_key FROM root_metadata ORDER BY receipt_key')])
    actual=pq.read_metadata(destination).num_rows
    if actual!=result['source_counts'][0]['rows']:
        raise ValueError('Receipt metadata projection changed the source line population')
    return destination,result['source_counts'][0],[row['receipt_key'] for row in result['receipt_keys']]


def producer(engine):
    return dict(sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                source_revision=engine.source_revision,binary_sha256=engine.binary_sha256)


def source_pins(counter=None,files=None):
    if counter is not None:
        paths=[counter_file(counter)]
    else:
        paths=sorted({Path(item['path']).resolve() for item in files})
    if not paths:
        raise ValueError('Receipt metadata requires pinned source files')
    return [dict(path=str(path),**file_pin(path)) for path in paths]


def _write_descriptor(root,*,engine,definition,source,outputs,keys,batch_size):
    if definition!=producer(engine):
        raise ValueError('Receipt metadata producer changed during projection')
    files=[dict(path=path.relative_to(root).as_posix(),**file_pin(path),
                rows=pq.read_metadata(path).num_rows) for path in sorted(outputs)]
    descriptor=dict(version=2,kind='receipt-metadata',producer=definition,source=source,
        selection=dict(receipt_keys=keys,receipt_batch_size=batch_size),
        rows=sum(item['rows'] for item in files),receipts=len(keys),files=files)
    (root/'metadata.json').write_text(json.dumps(descriptor,indent=2,sort_keys=True)+'\n')


def compact(*,engine,work,counter=None,files=None):
    """Project a direct receipt set or one counter to one pinned Parquet file."""
    root=Path(work).resolve()
    definition=producer(engine)
    source=source_pins(counter,files)
    destination,counts,keys=_compact(engine=engine,work=root,counter=counter,files=files)
    _write_descriptor(root,engine=engine,definition=definition,source=source,
                      outputs=[destination],keys=keys,batch_size=None)
    return destination


def compact_counter(counter,*,engine,work,receipt_keys=None,receipt_batch_size=64):
    """Orchestrate bounded filename lists; native jobs interpret and export rows.

    Each batch filters keys before JSON extraction. A giant individual receipt
    can still exceed native limits. Without Parquet predicate pruning, B batches
    can scan O(B*N) source rows; no application row join/export replaces that scan.
    """
    if type(receipt_batch_size) is not int or not 1<=receipt_batch_size<=1024:
        raise ValueError('Receipt batch size must be an integer from 1 to 1024')
    counter=counter_file(counter)
    if receipt_keys is not None:
        receipt_keys=list(receipt_keys)
        if len(receipt_keys)!=len(set(receipt_keys)):
            raise ValueError('Receipt selection requires unique keys')
        for key in receipt_keys:
            validate_key(key)
            if not key.startswith('receipts/'):
                raise ValueError('Receipt selection requires receipt keys')
    root=Path(work).resolve();root.mkdir(parents=True,exist_ok=False)
    definition=producer(engine);source=source_pins(counter=counter)
    selection=root/'selection';selection.mkdir()
    inputs=[dict(name='source',kind='parquet',path=str(Path(counter).resolve()))]
    where=''
    if receipt_keys is not None:
        inputs.append(json_input(selection,'requested',[dict(receipt_key=key) for key in receipt_keys],receipt_key='Utf8'))
        where=' WHERE __receipt_key IN (SELECT receipt_key FROM requested)'
    queries=[dict(name='keys',sql='SELECT __receipt_key AS receipt_key,count(*) AS rows FROM source'+where+
                  ' GROUP BY __receipt_key ORDER BY __receipt_key')]
    if receipt_keys is not None:
        queries.append(dict(name='missing',sql='''SELECT r.receipt_key FROM requested r LEFT ANTI JOIN source s
            ON r.receipt_key=s.__receipt_key LIMIT 1'''))
    result=run_job(selection,engine,inputs=inputs,steps=[],outputs=[],queries=queries)
    if result.get('missing'):
        raise ValueError('Requested receipt key is not present in counter')
    keys=[row['receipt_key'] for row in result['keys']]
    for key in keys:
        validate_key(key)
        if not key.startswith('receipts/'):
            raise ValueError('Counter contains an invalid receipt key')
    parts=root/'parts';parts.mkdir();jobs=root/'jobs';jobs.mkdir()
    batches=[keys[index:index+receipt_batch_size] for index in range(0,len(keys),receipt_batch_size)] or [[]]
    outputs=[];projected=0
    for index,batch in enumerate(batches):
        output,counts,actual_keys=_compact(counter=counter,engine=engine,work=jobs/f'batch-{index:06}',
            receipt_keys=batch,destination=parts/f'part-{index:06}.parquet')
        if actual_keys!=batch:
            raise ValueError('Receipt metadata batch changed its source key population')
        outputs.append(output);projected+=counts['rows']
    if projected!=sum(row['rows'] for row in result['keys']):
        raise ValueError('Receipt metadata batches changed the source line population')
    _write_descriptor(root,engine=engine,definition=definition,source=source,
                      outputs=outputs,keys=keys,batch_size=receipt_batch_size)
    return parts


def validate_metadata(path,engine=None):
    """Validate generated metadata pins/version without reopening raw sources."""
    path=Path(path).resolve();root=path.parent
    descriptor=json.loads((root/'metadata.json').read_text())
    if descriptor.get('version')!=2 or descriptor.get('kind')!='receipt-metadata':
        raise ValueError('Unsupported receipt metadata descriptor')
    producer=descriptor.get('producer',{})
    if producer.get('sha256')!=sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Receipt metadata producer does not match current definition')
    if engine is not None and any(producer.get(name)!=getattr(engine,name)
                                   for name in ('source_revision','binary_sha256')):
        raise ValueError('Receipt metadata runtime does not match current engine')
    size=descriptor.get('selection',{}).get('receipt_batch_size')
    if path.is_dir() and (type(size) is not int or not 1<=size<=1024):
        raise ValueError('Invalid receipt metadata batch bound')
    files=descriptor.get('files',[])
    if not files or [item['path'] for item in files]!=sorted(item['path'] for item in files):
        raise ValueError('Receipt metadata files must be explicitly sorted')
    actual=sorted(path.iterdir()) if path.is_dir() else [path]
    declared=[];rows=0
    for item in files:
        relative=Path(item['path']);part=root/relative
        if relative.is_absolute() or '..' in relative.parts or part.is_symlink() or not part.resolve().is_relative_to(root):
            raise ValueError('Unsafe receipt metadata part path')
        if file_pin(part)!={key:item[key] for key in ('sha256','size')}:
            raise ValueError('Receipt metadata part pin changed')
        count=pq.read_metadata(part).num_rows
        if count!=item['rows']:
            raise ValueError('Receipt metadata part row count changed')
        declared.append(part);rows+=count
    if declared!=actual or rows!=descriptor.get('rows'):
        raise ValueError('Receipt metadata part inventory changed')
    keys=descriptor.get('selection',{}).get('receipt_keys',[])
    if len(keys)!=len(set(keys)) or len(keys)!=descriptor.get('receipts'):
        raise ValueError('Receipt metadata receipt-key count changed')
    return descriptor
