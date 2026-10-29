"""Read-only E4 comparison. Policy witnesses explain individual differences.

The catalog pair is the oracle. Candidate fields come from the release; source
membership and ID inputs come from pinned, nonpublished model relations.
"""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import sys

from congress_api.retention.provenance import parquet_output, run_job, json_input, list_of, file_pin
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[2]
ORACLE_CATALOG = '469ef1ebf6864739a2c8a4c096defcc0'
ORACLE_GENERATION = '596f08fa2dbf4875bb8da7dc94e33847'
MEMBER_COLUMNS = {'document_id','list_row','source_id','body_key','effective_filename','source_url','member_path'}

MEMBER_CHECKS=['SELECT count(*) AS errors FROM (SELECT source_id FROM source_members GROUP BY source_id HAVING count(DISTINCT json_array(document_id,list_row,body_key,effective_filename,source_url))<>1)', 'SELECT count(*) AS errors FROM (SELECT document_id,list_row,source_id,body_key,effective_filename,source_url,member_path FROM source_members GROUP BY document_id,list_row,source_id,body_key,effective_filename,source_url,member_path HAVING count(*)>1)']


def pinned_file(base, pin):
    if not isinstance(pin,dict) or not isinstance(pin.get('path'),str):
        raise ValueError('Missing file pin')
    path=(base/pin['path']).resolve()
    if not path.is_file():
        raise ValueError('Missing pinned file: '+str(path))
    if not isinstance(pin.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',pin['sha256']):
        raise ValueError('Missing SHA-256 file pin: '+str(path))
    if path.stat().st_size!=pin.get('size'):
        raise ValueError('Pinned file size differs: '+str(path))
    with path.open('rb') as stream:
        if file_digest(stream,'sha256').hexdigest()!=pin['sha256']:
            raise ValueError('Pinned file digest differs: '+str(path))
    return path


def oracle_inputs(base, oracle):
    """The F0 sidecar producer and comparator verify the same oracle."""
    import pyarrow.parquet as pq
    selector_path=pinned_file(base,oracle.get('selector'))
    selector=json.loads(selector_path.read_text())
    if selector.get('catalog_id')!=ORACLE_CATALOG or selector.get('generation')!=ORACLE_GENERATION:
        raise ValueError('The oracle must be the agreed pinned catalog pair, never F0')
    paths={}
    for name in ['documents','filenames']:
        source=pinned_file(base,oracle.get(name))
        expected=selector['files'][name]
        if oracle[name]['sha256']!=expected['sha256'] or oracle[name]['size']!=expected['bytes']:
            raise ValueError('Oracle pair differs from its selector: '+name)
        if pq.ParquetFile(source).metadata.num_rows!=expected['rows']:
            raise ValueError('Oracle rows differ: '+name)
        paths['oracle_'+name]=str(source)
        receipt_path=pinned_file(base,oracle.get(name+'_receipt'))
        receipt=json.loads(receipt_path.read_text())
        if receipt.get('key')!=expected['key'] or receipt.get('identity',{}).get('sha256')!=expected['sha256']:
            raise ValueError('Oracle receipt differs: '+name)
    return paths,selector


def release_inputs(base,candidate):
    import pyarrow.parquet as pq
    paths={}
    if candidate.get('kind') not in {'model','f0'} or not isinstance(candidate.get('release'),str):
        raise ValueError('Missing candidate kind or immutable release location')
    release=(base/candidate['release']).resolve()
    manifest_path=release/'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Missing candidate manifest')
    if sha256(manifest_path.read_bytes()).hexdigest()!=candidate.get('manifest_sha256'):
        raise ValueError('Candidate manifest digest differs')
    manifest=json.loads(manifest_path.read_text())
    if candidate['kind']=='f0' and (manifest.get('origin',{}).get('kind')!='converted_catalog'
            or manifest['origin'].get('catalog_id')!=ORACLE_GENERATION):
        raise ValueError('F0 candidate lacks the pinned converter origin')
    if candidate['kind']=='model' and manifest.get('origin',{}).get('kind')=='converted_catalog':
        raise ValueError('F0 cannot claim model qualification')
    names=set()
    for item in manifest['files']:
        name=item['name']
        if Path(name).name!=name or name in names:
            raise ValueError('Invalid or duplicate release filename')
        names.add(name)
        source=pinned_file(release,dict(path=name,sha256=item['sha256'],size=item['size']))
        if name.endswith('.parquet') and pq.ParquetFile(source).metadata.num_rows!=item['rows']:
            raise ValueError('Candidate file rows differ: '+name)
        if name.endswith('.parquet'):
            paths['release_'+name.removesuffix('.parquet')]=str(source)
    required={'list.parquet','detail.parquet','links.parquet','urls.parquet','sources.parquet','recoveries.parquet'}
    if not required<=names:
        raise ValueError('Missing required public candidate files')
    identity=[manifest['schema_version'],[[f['name'],f['sha256'],f['size'],f['rows']] for f in manifest['files']]]
    if sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()!=manifest['release_id']:
        raise ValueError('Candidate release identity differs')
    return paths,manifest


def load_descriptor(path):
    """Verify selectors and bytes before registering any native relation."""
    import pyarrow.parquet as pq
    path=Path(path).resolve()
    value=json.loads(path.read_text())
    if type(value.get('version')) is not int or value['version']!=1:
        raise ValueError('Missing version-1 parity descriptor')
    base=path.parent
    paths,selector=oracle_inputs(base,value.get('oracle',{}))
    candidate=value.get('candidate',{})
    scope=value['oracle'].get('scope','full')
    if scope not in {'full','source_evidence'} or candidate.get('kind')=='f0' and scope!='full':
        raise ValueError('Oracle scope must be full, or source_evidence for a real model slice')
    release_paths,manifest=release_inputs(base,candidate)
    paths.update(release_paths)
    members=pinned_file(base,candidate.get('source_members'))
    if set(pq.read_schema(members).names)!=MEMBER_COLUMNS:
        raise ValueError('Source-member sidecar must have the agreed seven columns')
    paths['source_members']=str(members)
    paths['document_rows']=str(pinned_file(base,candidate.get('document_rows')))
    for name,pin in value.get('cause_relations',{}).items():
        if name in paths or name.startswith('b7_'):
            raise ValueError('Cause metadata cannot replace a reserved input: '+name)
        source=pinned_file(base,pin)
        if not set(pin.get('required_columns',[]))<=set(pq.read_schema(source).names):
            raise ValueError('Cause relation lacks its declared columns: '+name)
        if not re.fullmatch('[a-z_]+',name):
            raise ValueError('Invalid canonical relation name')
        paths[name]=str(source)
    provenance=value.get('provenance',{})
    paths['owner_decisions']=str(pinned_file(base,provenance.get('owner_decisions')))
    b7=pinned_file(base,provenance.get('b7_manifest'))
    b7_manifest=json.loads(b7.read_text())
    for pin in b7_manifest['files']:
        pinned_file(b7.parent,pin)
    for pin in b7_manifest['artifacts']:
        if pin['path'] in {'owner-records.parquet','ready-imports.parquet','source-time-minima.parquet','recovery-decisions.parquet'}:
            source=pinned_file(b7.parent,pin)
            paths['b7_'+Path(pin['path']).stem.replace('-','_')]=str(source)
    return dict(base=base,oracle_scope=scope,descriptor=value,paths=paths,manifest=manifest,selector=selector,
        descriptor_sha256=sha256(path.read_bytes()).hexdigest())


def restricted_runtime(config, directory, *, threads):
    """Use the qualified binary; tighten parallelism and scratch admission."""
    config=Path(config).resolve()
    value=json.loads(config.read_text())
    if any(key in value for key in ['remote','credentials']):
        raise ValueError('Comparison requires the explicitly pinned local runtime')
    limits=json.loads((config.parent/value['limits']).read_text())
    if threads>limits['compute_threads'] or threads<1:
        raise ValueError('Comparison cannot widen compute admission')
    limits['compute_threads']=threads
    limits['scratch_bytes']=min(limits['scratch_bytes'],8<<30)
    limits['batch_rows']=min(limits['batch_rows'],1024)
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'limits.json').write_text(json.dumps(limits,indent=2)+'\n')
    value['binary']=str((config.parent/value['binary']).resolve())
    value['limits']=str(directory/'limits.json')
    value['workspace']=str(directory/'unused-lifecycle')
    result=directory/'runtime.json'
    result.write_text(json.dumps(value,indent=2)+'\n')
    return result


def legacy_date(alias='d'):
    token=f'array_element({alias}.date_token,1)'
    return f"CASE WHEN cardinality({alias}.date_token)=1 THEN try_cast(CASE WHEN regexp_like({token},'^[0-9]{{8}}$') THEN concat(substr({token},1,4),'-',substr({token},5,2),'-',substr({token},7,2)) ELSE {token} END AS DATE) END"


def approved_order(items, fields):
    """The pinned native writer must preserve the agreed ASC / NULLS LAST sort."""
    return (isinstance(items,list) and len(items)==len(fields) and all(
        isinstance(item,dict) and set(item)<={'field','direction','nulls'}
        and item.get('field')==name and item.get('direction','asc')=='asc'
        and item.get('nulls','nulls_last')=='nulls_last'
        for item,name in zip(items,fields)))


def producer_inputs(base, candidate, manifest):
    """Native writer hashes and explicit sort bind private rows to public rows."""
    job_path=pinned_file(base,candidate.get('build_job'))
    result_path=pinned_file(base,candidate.get('build_result'))
    job=json.loads(job_path.read_text());result=json.loads(result_path.read_text())
    if candidate['kind']=='model':
        pinned_file(base,candidate.get('producer_profile'))
        checks=[query for query in job.get('queries',[]) if query.get('name')=='profile_completeness']
        reports=[query for query in result.get('queries',[]) if query.get('name')=='profile_completeness']
        if len(checks)!=1 or len(reports)!=1:
            raise ValueError('Model producer requires its native profile completeness check')
        rows=reports[0].get('data')
        if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or not rows[0]
                or any(type(count) is not int or count!=0 for count in rows[0].values())):
            raise ValueError('Model producer profile completeness counts must all be zero integers')
    specs={item['name']:item for item in job['outputs']}
    actual={item['name']:item for item in result['outputs']}
    for item in manifest['files']:
        if not item['name'].endswith('.parquet'):
            continue
        name=item['name']
        if name not in specs or name not in actual or any(item[k]!=actual[name][k] for k in ('sha256','size','rows')):
            raise ValueError('Public release differs from its pinned native producer: '+name)
    for name,relation in [('list.parquet','ordered'),('detail.parquet','details')]:
        spec=specs[name]
        order=[item['field'] for item in spec['settings']['order_by']]
        if len(order)!=4 or order[-1] not in {'doc_key','document_id'} or not approved_order(spec['settings']['order_by'],['filename','document_date','first_captured',order[-1]]):
            raise ValueError('Public rows need the explicit document sort')
        if spec['sql'].strip().lower()!='select * from '+relation:
            raise ValueError('Public writer must consume the agreed ordered relation')
    for name in ['sources.parquet','recoveries.parquet']:
        if not approved_order(specs[name]['settings']['order_by'],['list_row','ordinal']):
            raise ValueError('Attachment writer order differs from its public ranges')
    ordered=next((item for item in job['steps'] if item['name']=='ordered'),{})
    compact=re.sub(r'\s+','',ordered.get('sql','')).lower()
    last=specs['list.parquet']['settings']['order_by'][-1]['field']
    if f'row_number()over(orderbyfilename,document_datenullslast,first_capturednullslast,{last})-1' not in compact:
        raise ValueError('Producer lacks the explicit unique row-number order')
    return job,result


F0_SOURCE_STEP=dict(name='e4_source_evidence',sql='SELECT document_id,source_id,body_key,filename,source_url FROM legacy_filenames',materialize=True)


def prepare_f0(template, *, engine, work):
    """Replay the pinned converter relation, preserving its explicit row order."""
    from copy import deepcopy
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS
    template=Path(template).resolve();value=json.loads(template.read_text())
    paths,selector=oracle_inputs(template.parent,value['oracle'])
    candidate=dict(value['candidate'],kind='f0')
    release_paths,manifest=release_inputs(template.parent,candidate)
    job,result=producer_inputs(template.parent,candidate,manifest)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    inputs=deepcopy(job['inputs'])
    for item in inputs:
        if item['name'] in {'legacy_documents','legacy_filenames'}:
            item['path']=paths['oracle_'+item['name'].removeprefix('legacy_')]
    columns=','.join(LIST_COLUMNS+DETAIL_COLUMNS)
    outputs=[parquet_output(work,'source_members',
        'SELECT f.document_id,o.list_row,f.source_id,f.body_key,f.filename AS effective_filename,f.source_url,cast(NULL AS VARCHAR) AS member_path FROM e4_source_evidence f JOIN ordered o ON f.document_id=o.doc_key',
        ['list_row','source_id']),
        parquet_output(work,'document_rows',f'SELECT list_row,doc_key AS document_id,{columns} FROM details',['list_row'])]
    run_job(work,engine,inputs=inputs,steps=[F0_SOURCE_STEP,*job['steps']],outputs=outputs)
    def pin(path):return dict(path=str(path.resolve()),**file_pin(path))
    for name in ['build_job','build_result']:
        candidate[name]=dict(candidate[name],path=str((template.parent/candidate[name]['path']).resolve()))
    value['candidate']=dict(candidate,release=str((template.parent/candidate['release']).resolve()),
        source_members=pin(work/'source_members.parquet'),document_rows=pin(work/'document_rows.parquet'),
        layout_job=pin(work/'job.json'),layout_result=pin(work/'result.json'))
    captures=next(item for item in job['inputs'] if item['name']=='legacy_captures')
    capture_path=Path(captures['path']).resolve()
    value['cause_relations']=dict(catalog_capture_metadata=dict(pin(capture_path),required_columns=['body_key','bytes','media_type']))
    value['oracle']['scope']='full'
    for group,names in [('oracle',['selector','documents','filenames','documents_receipt','filenames_receipt']),('provenance',['owner_decisions','b7_manifest'])]:
        for name in names:
            item=value[group][name];item['path']=str((template.parent/item['path']).resolve())
    output=work/'parity-inputs.json';output.write_text(json.dumps(value,indent=2)+'\n')
    return output


def validate_layout(loaded, *, engine, work):
    """Check multiplicities and source keys; never infer physical row order."""
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS
    import pyarrow.parquet as pq
    value=loaded['descriptor'];base=loaded['base'];candidate=value['candidate'];paths=loaded['paths']
    job,result=producer_inputs(base,candidate,loaded['manifest'])
    rows=Path(paths['document_rows'])
    if set(pq.read_schema(rows).names)!=set(['document_id','list_row',*LIST_COLUMNS,*DETAIL_COLUMNS]):
        raise ValueError('Private document rows need exactly the agreed public columns and IDs')
    paths['document_rows']=str(rows)
    if candidate['kind']=='f0':
        layout=json.loads(pinned_file(base,candidate.get('layout_job')).read_text())
        result=json.loads(pinned_file(base,candidate.get('layout_result')).read_text())
        if layout['steps']!=[F0_SOURCE_STEP,*job['steps']]:
            raise ValueError('F0 row layout must replay the original native producer steps')
        # Only the two oracle copies may move. Other native producer inputs must match.
        for old,new in zip(job['inputs'],layout['inputs'],strict=True):
            if old['name'] in {'legacy_documents','legacy_filenames'}:
                if dict(old,path=new['path'])!=new or new['path']!=paths['oracle_'+old['name'].removeprefix('legacy_')]:
                    raise ValueError('F0 replay selected another oracle input')
            elif old!=new:raise ValueError('F0 replay changed a producer input')
        job=layout
    specs={Path(item['path']).name:item for item in job['outputs']}
    actual={item['name']:item for item in result['outputs']}
    for key in ['source_members','document_rows']:
        source=Path(paths[key]);spec=specs.get(source.name)
        if spec is None or spec['name'] not in actual or any(actual[spec['name']][k]!=candidate[key][k] for k in ['sha256','size']):
            raise ValueError('Private evidence differs from its pinned native producer')
    row_spec=specs[rows.name]
    columns=','.join('"'+name+'"' for name in LIST_COLUMNS+DETAIL_COLUMNS)
    expected=[f'SELECT list_row,doc_key AS document_id,{columns} FROM details',
              f"SELECT list_row,encode(document_id,'hex') AS document_id,{columns} FROM details"]
    compact=lambda sql:re.sub(r'\s+','',re.sub(r'"([a-z_]+)"',r'\1',sql)).lower()
    if compact(row_spec['sql']) not in {compact(sql) for sql in expected} or not approved_order(row_spec['settings']['order_by'],['list_row']):
        raise ValueError('Private document projection lineage must preserve the ordered details row')
    if candidate['kind']=='f0':
        member_spec=specs[Path(paths['source_members']).name]
        expected='SELECT f.document_id,o.list_row,f.source_id,f.body_key,f.filename AS effective_filename,f.source_url,cast(NULL AS VARCHAR) AS member_path FROM e4_source_evidence f JOIN ordered o ON f.document_id=o.doc_key'
        if compact(member_spec['sql'])!=compact(expected):
            raise ValueError('F0 source projection lineage differs from ordered documents')
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    inputs=[dict(name='input_'+name if name in {'source_members','document_rows'} else name,kind='parquet',path=paths[name]) for name in ['release_list','release_detail','release_sources','release_recoveries','source_members','document_rows']]
    steps=[dict(name=name,sql='SELECT * FROM input_'+name,materialize=True,release_after=['input_'+name]) for name in ['source_members','document_rows']]
    checks=[]
    for table,cols in [('list',LIST_COLUMNS),('detail',DETAIL_COLUMNS)]:
        columns=','.join('"'+name+'"' for name in cols)
        checks.append(f"SELECT count(*) AS errors FROM (SELECT {columns},sum(sign) FROM (SELECT {columns},1 AS sign FROM release_{table} UNION ALL SELECT {columns},-1 AS sign FROM document_rows) GROUP BY {columns} HAVING sum(sign)<>0)")
    checks += ["SELECT count(*) AS errors FROM (SELECT list_row FROM document_rows GROUP BY list_row HAVING count(*)<>1)",
        "SELECT count(*) AS errors FROM (SELECT document_id FROM document_rows GROUP BY document_id HAVING count(*)<>1)",
        "SELECT count(*) AS errors FROM document_rows WHERE list_row IS NULL OR list_row<0 OR NOT coalesce(regexp_like(document_id,'^[0-9a-f]{64}$'),false)",
        "SELECT count(*) AS errors FROM source_members m LEFT ANTI JOIN document_rows d ON m.list_row=d.list_row AND m.document_id=d.document_id",
        "SELECT count(*) AS errors FROM document_rows d LEFT ANTI JOIN source_members m ON m.list_row=d.list_row",
        "SELECT count(*) AS errors FROM source_members WHERE source_id IS NULL OR NOT regexp_like(source_id,'^[0-9a-f]{64}$') OR (body_key IS NOT NULL AND NOT regexp_like(body_key,'^bodies/sha256/[0-9a-f]{2}/[0-9a-f]{64}[.]gz$'))",
        "SELECT CASE WHEN count(*)=0 OR min(list_row)=0 AND max(list_row)=count(*)-1 THEN 0 ELSE 1 END AS errors FROM document_rows"]
    checks.extend(MEMBER_CHECKS)
    for table,prefix in [('sources','src'),('recoveries','rec')]:
        steps.append(dict(name=table+'_counts',sql=f"SELECT list_row,count(*) AS n,min(ordinal) AS lo,max(ordinal) AS hi,count(DISTINCT ordinal) AS unique_ordinals FROM release_{table} GROUP BY list_row",materialize=True))
        steps.append(dict(name=table+'_bounds',sql=f'SELECT *,sum(n) OVER(ORDER BY list_row ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)-n AS start FROM {table}_counts',materialize=True))
        checks.append(f"SELECT count(*) AS errors FROM document_rows d LEFT JOIN {table}_bounds b USING(list_row) WHERE d.{prefix}_len<>coalesce(b.n,0) OR d.{prefix}_start<>coalesce(b.start,0) OR coalesce(b.lo,0)<>0 OR coalesce(b.hi,-1)<>coalesce(b.n,0)-1 OR coalesce(b.unique_ordinals,0)<>coalesce(b.n,0)")
        checks.append(f'SELECT count(*) AS errors FROM {table}_counts c LEFT ANTI JOIN document_rows d USING(list_row)')
    reports=run_job(work,engine,inputs=inputs,steps=steps,outputs=[],queries=[dict(name='check_'+str(i),sql=sql) for i,sql in enumerate(checks)])
    if any(row['errors'] for rows in reports.values() for row in rows):
        raise ValueError('Public/private row values, membership or attachment ranges disagree')


def select_oracle_scope(loaded, *, engine, work):
    """Select actual slice evidence natively; retain each old component in full."""
    paths=loaded['paths'];work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    names=['oracle_documents','oracle_filenames','capture_sources','current_recoveries']
    if any(name not in paths for name in names):
        raise ValueError('Slice oracle selection requires canonical captures and recoveries')
    inputs=[dict(name=name,kind='parquet',path=paths[name]) for name in names]
    document_columns,file_columns=oracle_columns()
    file_sql=','.join('f."'+name+'"' for name in sorted(file_columns))
    columns=','.join('"'+name+'"' for name in sorted(file_columns))
    document_sql=','.join('array_slice(d."source_link_label",1,1) AS "source_link_label"' if name=='source_link_label' else 'd."'+name+'"' for name in sorted(document_columns))
    steps=[dict(name='slice_evidence',sql="""SELECT * FROM (
        SELECT CASE WHEN body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha||'.gz' END AS body_key,source_url FROM capture_sources
        UNION SELECT CASE WHEN body_sha256 IS NOT NULL THEN 'bodies/sha256/'||substr(body_sha256,1,2)||'/'||body_sha256||'.gz' END,original_url FROM current_recoveries)
        WHERE body_key IS NOT NULL OR source_url IS NOT NULL""",materialize=True),
        # A narrow key pass plus a filtered metadata pass avoids sorting every
        # wide old row. Keep the single-use key projection lazy and small join
        # inputs first so materialized inputs do not build a catalog-sized hash.
        # Hash joins are O(F + E) expected; only S selected rows
        # reach the metadata export and its O(S log S) output sort.
        dict(name='oracle_file_keys',sql='SELECT document_id,body_key,source_url FROM oracle_filenames'),
        dict(name='touched_documents',sql="""SELECT DISTINCT f.document_id FROM slice_evidence e JOIN oracle_file_keys f
            ON (f.body_key IS NOT DISTINCT FROM e.body_key) AND (f.source_url IS NOT DISTINCT FROM e.source_url)""",materialize=True,release_after=['oracle_file_keys']),
        dict(name='scoped_files',sql=f"""SELECT {file_sql},e.body_key IS NOT NULL OR e.source_url IS NOT NULL AS covered
            FROM touched_documents t JOIN oracle_filenames f USING(document_id) LEFT JOIN slice_evidence e
            ON (f.body_key IS NOT DISTINCT FROM e.body_key) AND (f.source_url IS NOT DISTINCT FROM e.source_url)""",materialize=True,
            release_after=['oracle_filenames','slice_evidence','touched_documents']),
        dict(name='scope_coverage',sql='SELECT document_id,count(*) AS files,count(*) FILTER(WHERE covered) AS covered FROM scoped_files GROUP BY document_id',materialize=True)]
    outputs=[parquet_output(work,'oracle-filenames','SELECT '+columns+' FROM scoped_files',['document_id','source_id']),
        parquet_output(work,'oracle-documents',f'SELECT {document_sql} FROM scope_coverage c JOIN oracle_documents d USING(document_id)',['document_id']),
        parquet_output(work,'scope-gaps','SELECT document_id,source_id,body_key,filename,source_url FROM scoped_files WHERE NOT covered',['document_id','source_id'])]
    total=loaded['selector']['files']['documents']['rows']
    reports=run_job(work,engine,inputs=inputs,steps=steps,outputs=outputs,queries=[dict(name='scope',sql=f"""SELECT
        count(*) AS selected_documents,coalesce(sum(files),0) AS selected_files,{total}-count(*) AS outside_documents,
        count(*) FILTER(WHERE files<>covered) AS partial_documents,coalesce(sum(files-covered),0) AS missing_files FROM scope_coverage"""),
        dict(name='examples',sql='SELECT document_id,files,covered FROM scope_coverage WHERE files<>covered ORDER BY document_id LIMIT 3')])
    scope=dict(reports['scope'][0],kind='source_evidence',examples=reports['examples'],
        job=dict(path=str(work/'job.json'),**file_pin(work/'job.json')),
        result=dict(path=str(work/'result.json'),**file_pin(work/'result.json')))
    # These are native-selected intermediate files, never a replacement oracle.
    # The original pair and native job/result pins remain in the final report.
    paths['oracle_documents']=str(work/'oracle-documents.parquet')
    paths['oracle_filenames']=str(work/'oracle-filenames.parquet')
    (work/'scope.json').write_text(json.dumps(scope,indent=2)+'\n')
    return scope


def field_rows(table, doc, scalars, arrays=(), *, subject="''"):
    branches=[f"SELECT {doc} AS doc,'{field}' AS field,{subject} AS subject,cast({value} AS VARCHAR) AS value FROM {table}" for field,value in scalars.items()]
    branches += [f"SELECT {doc} AS doc,'{field}' AS field,{subject} AS subject,cast(unnest({value}) AS VARCHAR) AS value FROM {table}" for field,value in arrays]
    return 'SELECT * FROM ('+' UNION ALL '.join(branches)+') WHERE value IS NOT NULL'


def oracle_columns(display=None):
    if display is None:display=json.loads((ROOT/'model/registries/display-facts.json').read_text())
    document_columns={'document_id','filename','source_url','source_link_label','body_key','body_keys',
        'state_retrieved_at','date_token','document_kind','document_family','congress','format',
        'measure_references','member_bioguide_id','hearing_package_id','committee_code','date_token_candidates','source_meeting_id'}
    document_columns.update(row['field'] for row in display)
    file_columns={'document_id','source_id','body_key','filename','source_url','http_status','capture_outcome',
        'response_usable','response_body_complete','body_format','format','media_type','source_page_url','source_link_label','source_paths'}
    return document_columns,file_columns


def normalization(loaded, *, directory):
    """Project the old consumer and actual new release into comparable facts."""
    from congress_api.retention.index.schemas import MEDIA_FORMATS,EMPTY_BODY_DIGEST
    from viewer_publication.archive_format import EMPTY_STRINGS
    paths=loaded['paths'];kind=loaded['descriptor']['candidate']['kind']
    inputs=[dict(name=name,kind='parquet',path=path) for name,path in paths.items()
            if name.startswith('oracle_') or name.startswith('release_') or name in {'source_members','document_rows'} or name.startswith('b7_') or name in loaded['descriptor'].get('cause_relations',{})]
    inputs += [json_input(directory,'legacy_media',[dict(media=k,format=v) for k,v in MEDIA_FORMATS.items()],media='Utf8',format='Utf8')]
    committee=json.loads((ROOT/'model/registries/committee-codes.json').read_text())
    inputs.append(json_input(directory,'committee_codes',committee,code='Utf8',system_code='Utf8',chamber='Utf8'))
    inputs.append(json_input(directory,'difference_records',loaded['descriptor'].get('difference_records',[]),
        difference_id='Utf8',classification='Utf8',rule_ref='Utf8',note='Utf8',raw_signal='Utf8'))
    allowed=','.join("'"+f+"'" for f in sorted(set(MEDIA_FORMATS.values())-{'html','binary'}))
    status="coalesce(array_to_string(f.http_status,','),'')"
    old_real=f"""f.body_key IS NOT NULL AND NOT regexp_like(f.body_key,'/{EMPTY_BODY_DIGEST}([.]gz)?$')
        AND NOT (coalesce(cardinality(f.response_usable),0)=1 AND f.response_usable[1]='false')
        AND NOT (coalesce(cardinality(f.response_body_complete),0)=1 AND f.response_body_complete[1]='false')
        AND (coalesce(cardinality(f.capture_outcome),0)=0 OR (cardinality(f.capture_outcome)=1 AND f.capture_outcome[1]='saved'))
        AND cardinality(formats)>0 AND cardinality(array_except(formats,make_array({allowed})))=0
        AND ((regexp_like({status},'(^|,)2') AND (array_has(f.response_usable,'true') OR NOT regexp_like({status},'(^|,)[0-9]{{3}}(,|$)') OR regexp_like({status},'(^|,)2[0-9]{{2}}(,|$)'))
             OR (coalesce(cardinality(f.http_status),0)=0 AND f.body_format=make_array('pdf'))))"""
    metadata='catalog_capture_metadata' in loaded['paths']
    steps=[
        dict(name='old_media',sql="""SELECT source_id,array_agg(DISTINCT coalesce(m.format,lower(trim(split_part(f.media,';',1))))) AS media_formats
            FROM (SELECT source_id,unnest(media_type) AS media FROM oracle_filenames) f
            LEFT JOIN legacy_media m ON lower(trim(split_part(f.media,';',1)))=m.media GROUP BY source_id""",materialize=True),
        dict(name='old_source_formats',sql=f'''SELECT f.document_id,f.source_id,f.body_key,f.filename,f.source_url,
            f.http_status,f.capture_outcome,f.response_usable,f.response_body_complete,f.body_format,
            CASE WHEN coalesce(cardinality(f.body_format),0)>0 THEN f.body_format ELSE coalesce(m.media_formats,{EMPTY_STRINGS}) END AS formats
            FROM oracle_filenames f LEFT JOIN old_media m USING(source_id)''',materialize=True),
        dict(name='old_identity_sources',sql=f'SELECT f.document_id,f.source_id,CASE WHEN coalesce(({old_real}),false) THEN f.body_key END AS id_body_key FROM old_source_formats f',materialize=True),
        dict(name='old_identity_groups',sql=f'''SELECT document_id,coalesce(array_sort(array_agg(DISTINCT id_body_key) FILTER(WHERE id_body_key IS NOT NULL)),{EMPTY_STRINGS}) AS body_keys,
            array_sort(array_agg(DISTINCT source_id)) AS source_ids FROM old_identity_sources GROUP BY document_id''',materialize=True),
        dict(name='old_documents',sql='SELECT document_id AS doc FROM oracle_documents',materialize=True),
        dict(name='new_documents',sql='SELECT cast(list_row AS VARCHAR) AS doc FROM document_rows',materialize=True),
        dict(name='old_anchors',sql="SELECT DISTINCT document_id AS doc,json_array(body_key,source_url) AS anchor,source_id AS identity_anchor FROM oracle_filenames",materialize=True),
        dict(name='new_anchors',sql="SELECT DISTINCT cast(list_row AS VARCHAR) AS doc,json_array(body_key,source_url) AS anchor,source_id AS identity_anchor FROM source_members",materialize=True),
        dict(name='old_bodies',sql='SELECT document_id AS doc,unnest(body_keys) AS body_key FROM oracle_documents',materialize=True),
        dict(name='new_bodies',sql='SELECT DISTINCT cast(list_row AS VARCHAR) AS doc,body_key FROM source_members WHERE body_key IS NOT NULL',materialize=True),
        dict(name='body_map',sql="""SELECT DISTINCT body_key,substr((regexp_match(body_key,'([a-f0-9]{64})'))[1],1,16) AS prefix FROM (SELECT body_key FROM old_bodies UNION SELECT body_key FROM new_bodies)""",materialize=True),
        dict(name='public_body_links',sql="SELECT cast(l.list_row AS VARCHAR) AS doc,b.body_key FROM release_links l JOIN body_map b ON encode(l.link_key,'hex')=b.prefix",materialize=True),
        dict(name='old_committees',sql='''SELECT DISTINCT d.document_id AS doc,c.system_code FROM
            (SELECT document_id,unnest(committee_code) AS code FROM oracle_documents) d JOIN committee_codes c
            ON upper(d.code)=upper(c.code) OR (right(c.code,2)='00' AND upper(d.code)=upper(substr(c.code,1,length(c.code)-2)))''',materialize=True),
        dict(name='old_times',sql="SELECT document_id,min(cast(to_char(arrow_cast(try_cast(t AS TIMESTAMP),'Timestamp(Microsecond, Some(\"UTC\"))') AT TIME ZONE 'America/New_York','%Y-%m-%d') AS DATE)) AS first_captured FROM (SELECT document_id,unnest(state_retrieved_at) AS t FROM oracle_documents) GROUP BY document_id",materialize=True),
        dict(name='old_wide',sql='''SELECT d.document_id,d.filename,d.source_url,d.source_link_label,d.body_key,
            d.state_retrieved_at,d.date_token,d.document_kind,d.document_family,d.congress,d.format,
            d.measure_references,d.member_bioguide_id,d.hearing_package_id,d.committee_code,d.date_token_candidates,
            t.first_captured FROM oracle_documents d LEFT JOIN old_times t USING(document_id)''',materialize=True),
        dict(name='identity_sources',sql="""SELECT 'old' AS side,document_id AS doc,source_id,body_key,filename,source_url FROM oracle_filenames
            UNION ALL SELECT 'new',cast(list_row AS VARCHAR),source_id,body_key,effective_filename,source_url FROM source_members""",materialize=True),
    ]
    if metadata:
        steps.insert(0,dict(name='old_capture_metadata',sql='SELECT body_key,max(bytes) AS bytes,max(media_type) AS media_type FROM catalog_capture_metadata WHERE body_key IS NOT NULL GROUP BY body_key',materialize=True))
        wide=next(step for step in steps if step['name']=='old_wide')
        wide['sql']=wide['sql'].replace('t.first_captured FROM',"t.first_captured,m.bytes AS saved_bytes,coalesce(m.media_type,CASE WHEN d.format[1]='pdf' THEN 'application/pdf' ELSE 'application/octet-stream' END) AS saved_media_type FROM")
        wide['sql']+=' LEFT JOIN old_capture_metadata m ON d.body_key=m.body_key'
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS,legacy_meeting_keys
    steps.append(dict(name='new_wide',sql='SELECT cast(list_row AS VARCHAR) AS doc,* FROM document_rows',materialize=True))
    steps.append(dict(name='old_meetings',sql=f'''SELECT DISTINCT document_id AS doc,cast(unnest({legacy_meeting_keys('source_url')}) AS VARCHAR) AS meeting_key FROM oracle_documents
        UNION SELECT document_id,cast(try_cast(regexp_replace(unnest(source_meeting_id),'^(HHRG|HMKP|HMTG)-?','') AS BIGINT) AS VARCHAR) FROM oracle_documents''',materialize=True))
    if kind=='f0':
        new_ids="SELECT 'new' AS side,cast(s.list_row AS VARCHAR) AS doc,s.document_id,g.body_keys,g.source_ids FROM (SELECT DISTINCT document_id,list_row FROM source_members) s JOIN old_identity_groups g USING(document_id)"
    else:
        if {'capture_sources','record_roles'}<=set(loaded['descriptor'].get('cause_relations',{})):
            real_step=dict(name='model_real_sources',sql='SELECT DISTINCT c.source_id FROM capture_sources c JOIN record_roles r USING(receipt_key,receipt_line,capture_index) WHERE r.is_real_file',materialize=True)
            index=next(i for i,step in enumerate(steps) if step['name']=='new_bodies')
            steps.insert(index,real_step)
            next(step for step in steps if step['name']=='new_bodies')['sql']='SELECT DISTINCT cast(m.list_row AS VARCHAR) AS doc,m.body_key FROM source_members m JOIN model_real_sources r USING(source_id) WHERE m.body_key IS NOT NULL'
            body='CASE WHEN r.source_id IS NOT NULL THEN m.body_key END'
            table='source_members m LEFT JOIN model_real_sources r USING(source_id)'
        else:
            body='m.body_key';table='source_members m'
        new_ids=f"""SELECT 'new' AS side,cast(m.list_row AS VARCHAR) AS doc,min(m.document_id) AS document_id,
            coalesce(array_sort(array_agg(DISTINCT {body}) FILTER(WHERE {body} IS NOT NULL)),{EMPTY_STRINGS}) AS body_keys,
            array_sort(array_agg(DISTINCT m.source_id)) AS source_ids FROM {table} GROUP BY m.list_row"""
    steps.append(dict(name='identity_documents',sql="SELECT 'old' AS side,document_id AS doc,document_id,body_keys,source_ids FROM old_identity_groups UNION ALL "+new_ids,materialize=True))
    # Nullable attributes remain absent facts; no fabricated date, label or body.
    scalar_old=dict(filename='filename',title='source_link_label[1]',saved_body='body_key',
        first_captured='first_captured',
        date_kind="CASE WHEN cardinality(state_retrieved_at)>0 THEN 'captured' ELSE 'unknown' END",
        document_date=legacy_date('old_wide'),document_date_source=f"CASE WHEN {legacy_date('old_wide')} IS NOT NULL THEN 'filename' END",
        saved_kind="'original'",hidden="'false'",saved_suffix="CASE WHEN body_key IS NULL THEN NULL WHEN regexp_like(body_key,'[.]pdf$') THEN '.pdf' WHEN regexp_like(body_key,'[.]gz$') THEN '.gz' ELSE '' END")
    if metadata:scalar_old.update(saved_bytes='saved_bytes',saved_media_type='saved_media_type')
    old_arrays=[(name,name) for name in ['document_kind','document_family','congress','format','measure_references','member_bioguide_id','hearing_package_id']]
    old_arrays=[({'measure_references':'measure_keys','member_bioguide_id':'bioguide_ids','hearing_package_id':'package_id'}.get(k,k),v) for k,v in old_arrays]
    old_parts=[field_rows('old_wide','document_id',scalar_old,old_arrays),
        field_rows('old_bodies','doc',dict(body_keys='body_key',body_link='body_key'),subject='body_key'),
        field_rows('oracle_filenames','document_id',dict(files='filename'),subject='json_array(body_key,source_url)'),
        field_rows('old_committees','doc',dict(committee_keys='system_code',chambers="CASE substr(system_code,1,1) WHEN 'h' THEN 'house' WHEN 's' THEN 'senate' WHEN 'j' THEN 'joint' END")),
        field_rows('old_meetings','doc',dict(meeting_keys='meeting_key')),
        field_rows('oracle_filenames','document_id',dict(**{'source.url':'source_url'}),
            [('source.listed_on','source_page_url'),('source.link_text','source_link_label'),('source.member_path','source_paths')],subject="coalesce(source_url,'')")]
    new_scalars={name:name for name in ['filename','title','format','congress','document_date','first_captured','date_kind','saved_kind','hidden',
        'document_date_source','in_archive_since','removed_on','review_note','review_decided_at','package_id','saved_suffix','saved_media_type','saved_bytes']}
    new_scalars['saved_body']="CASE WHEN saved_body IS NOT NULL THEN 'bodies/sha256/'||substr(encode(saved_body,'hex'),1,2)||'/'||encode(saved_body,'hex')||'.gz' END"
    new_arrays=[(name,name) for name in ['document_kind','document_family','committee_keys','chambers','meeting_keys','measure_keys','bioguide_ids','witness_keys','version_keys']]
    new_parts=[field_rows('new_wide','doc',new_scalars,new_arrays),
        field_rows('new_bodies','doc',dict(body_keys='body_key'),subject='body_key'),
        field_rows('public_body_links','doc',dict(body_link='body_key'),subject='body_key'),
        field_rows('source_members','cast(list_row AS VARCHAR)',dict(files='effective_filename'),subject='json_array(body_key,source_url)'),
        field_rows('release_sources','cast(list_row AS VARCHAR)',{'source.url':'url','source.listed_on':'listed_on','source.link_text':'link_text','source.member_path':'member_path','source.doc_type':'doc_type','source.posted':'posted','source.first_seen':'first_seen','source.is_saved':'is_saved'},subject='url')]
    old_parts.append(field_rows('oracle_filenames f JOIN old_wide d ON f.document_id=d.document_id','f.document_id',{'source.is_saved':'f.source_url=d.source_url'},subject="coalesce(f.source_url,'')"))
    # Display folds compare the maintained registry's facts, not private parser
    # internals the new site never receives.
    display=json.loads((ROOT/'model/registries/display-facts.json').read_text())
    for row in display:
        name=row['field']
        old_parts.append(field_rows('old_wide','document_id',{},[('facts',name)],subject="'"+name+"'"))
    old_parts += ["""SELECT d.document_id AS doc,'alternates' AS field,(regexp_match(f.body_key,'([a-f0-9]{64})'))[1] AS subject,f.format[1] AS value
        FROM old_wide d JOIN oracle_filenames f USING(document_id)
        WHERE f.body_key IS NOT NULL AND f.body_key<>d.body_key AND f.format[1]<>d.format[1]"""]
    if metadata:
        old_parts.extend([f"SELECT d.document_id AS doc,'{field}' AS field,(regexp_match(f.body_key,'([a-f0-9]{{64}})'))[1] AS subject,cast({expression} AS VARCHAR) AS value FROM old_wide d JOIN oracle_filenames f USING(document_id) LEFT JOIN old_capture_metadata m ON f.body_key=m.body_key WHERE f.body_key IS NOT NULL AND f.body_key<>d.body_key AND f.format[1]<>d.format[1]"
            for field,expression in [('alternate.suffix',"CASE WHEN regexp_like(f.body_key,'[.]pdf$') THEN '.pdf' WHEN regexp_like(f.body_key,'[.]gz$') THEN '.gz' ELSE '' END"),('alternate.bytes','m.bytes')]])
    new_parts.extend([f"SELECT doc,'{field}' AS field,encode(a['body'],'hex') AS subject,cast(a['{column}'] AS VARCHAR) AS value FROM (SELECT doc,unnest(alternates) AS a FROM new_wide)" for field,column in [('alternate.suffix','suffix'),('alternate.bytes','size')]])
    new_parts.extend([f"SELECT cast(list_row AS VARCHAR) AS doc,'recovery.{column}' AS field,encode(body,'hex') AS subject,json_array(cast({column} AS VARCHAR)) AS value FROM release_recoveries" for column in ['kind','recovered_url','imported_at','identity_note','suffix','bytes']])
    new_parts += ["SELECT doc,'facts' AS field,f['field'] AS subject,f['value'] AS value FROM (SELECT doc,unnest(facts) AS f FROM new_wide)",
        "SELECT doc,'alternates' AS field,encode(a['body'],'hex') AS subject,a['format'] AS value FROM (SELECT doc,unnest(alternates) AS a FROM new_wide)",
        "SELECT cast(list_row AS VARCHAR) AS doc,'recoveries' AS field,encode(body,'hex') AS subject,encode(body,'hex') AS value FROM release_recoveries"]
    from viewer_publication.archive_format import _lookup_steps
    steps.append(dict(name='old_lookup_sources',sql='SELECT DISTINCT document_id AS list_row,source_url AS url FROM oracle_filenames WHERE source_url IS NOT NULL',materialize=True))
    lookup=_lookup_steps('old_lookup_sources')
    names={step['name']:'old_'+step['name'] for step in lookup}
    for step in lookup:
        for before,after in names.items():step['sql']=re.sub(r'\b'+before+r'\b',after,step['sql'])
        step['name']=names[step['name']]
    steps+=lookup
    old_parts.append(field_rows('old_url_keys','list_row',dict(url_lookup="encode(lookup_key,'hex')")))
    new_parts.append(field_rows('release_urls','cast(list_row AS VARCHAR)',dict(url_lookup="encode(lookup_key,'hex')")))
    if kind=='f0':steps+=f0_proof_steps(loaded['manifest']['release_id'])[:-1]
    steps += [dict(name='old_fields',sql='SELECT * FROM ('+' UNION ALL '.join(old_parts)+') WHERE value IS NOT NULL'),dict(name='new_fields',sql='SELECT * FROM ('+' UNION ALL '.join(new_parts)+') WHERE value IS NOT NULL')]
    if kind=='model':
        steps += [dict(name='old_evidence_sources',sql='SELECT document_id AS doc,source_id,body_key,filename,source_url FROM oracle_filenames',materialize=True),
            dict(name='new_evidence_sources',sql='SELECT cast(list_row AS VARCHAR) AS doc,source_id,body_key,effective_filename AS filename,source_url FROM source_members',materialize=True)]
    if kind=='f0':
        steps.append(dict(name='witnesses',sql="SELECT cast(NULL AS VARCHAR) AS old_doc,cast(NULL AS VARCHAR) AS new_doc,cast(NULL AS VARCHAR) AS subject,cast(NULL AS VARCHAR) AS fact,cast(NULL AS VARCHAR) AS evidence_ref WHERE false"))
    # Each original wide file is parsed once by this consumer. All downstream
    # joins reuse only browser fields and the identity evidence they need.
    document_columns,file_columns=oracle_columns(display)
    for step in steps:
        step['sql']=step['sql'].replace('oracle_documents','old_catalog').replace('oracle_filenames','old_file_rows')
    steps=[dict(name=name,sql='SELECT '+','.join(('array_slice("source_link_label",1,1) AS "source_link_label"' if name=='old_catalog' and c=='source_link_label' else '"'+c+'"') for c in sorted(columns))+' FROM '+source,materialize=True,release_after=[source])
        for name,source,columns in [('old_catalog','oracle_documents',document_columns),('old_file_rows','oracle_filenames',file_columns)]]+steps
    return inputs,steps


F0_PREDICATES={
    'f0_dates': """(d.field='first_captured' AND d.direction='removed' AND n.first_captured IS NULL)
        OR (d.field='date_kind' AND n.date_kind='unknown' AND d.value IN ('captured','unknown'))
        OR (d.field='in_archive_since' AND d.direction='removed' AND n.in_archive_since IS NULL)""",
    'f0_format_alternates': """d.direction='removed' AND ((d.field='format' AND d.value<>lower(o.format[1]) AND n.format=lower(o.format[1]))
        OR (d.field IN ('alternates','alternate.suffix','alternate.bytes') AND coalesce(cardinality(n.alternates),0)=0))""",
    'f0_recoveries': "d.direction='removed' AND d.field IN ('recoveries','recovery.kind','recovery.imported_at') AND n.rec_len=0",
    'f0_source_context_fold': """d.direction='removed' AND (
        (d.field='source.member_path' AND NOT EXISTS(SELECT 1 FROM release_sources s WHERE cast(s.list_row AS VARCHAR)=d.new_doc AND s.member_path IS NOT NULL))
        OR (d.field='source.link_text' AND s.link_text=x.link_text)
        OR (d.field='source.listed_on' AND s.listed_on=x.listed_on)
        OR (d.field IN ('source.link_text','source.listed_on','source.url') AND d.subject='' AND NOT EXISTS(
            SELECT 1 FROM release_sources s WHERE cast(s.list_row AS VARCHAR)=d.new_doc AND s.url=d.value)))""",
    'f0_scalar_fold': """d.direction='removed' AND ((d.field='congress' AND cardinality(o.congress)<>1 AND n.congress IS NULL)
        OR (d.field='package_id' AND n.package_id IS NULL))""",
    'f0_display_facts': "d.direction='removed' AND d.field='facts' AND coalesce(cardinality(n.facts),0)=0",
    'f0_connections': """d.direction='removed' AND ((d.field='measure_keys' AND cardinality(n.measure_keys)=0)
        OR (d.field='bioguide_ids' AND cardinality(n.bioguide_ids)=0)
        OR (d.field='witness_keys' AND cardinality(n.witness_keys)=0)
        OR (d.field='version_keys' AND cardinality(n.version_keys)=0)
        OR (d.field='meeting_keys' AND NOT array_has(n.meeting_keys,d.value)))""",
    'f0_shared_body_link': "d.direction='removed' AND d.field='body_link' AND p.doc=t.doc AND cast(d.new_doc AS INT)>cast(t.doc AS INT)",
}

def f0_proof_steps(release_id):
    """Converter-only explanations require its exact observable operation."""
    source="""FROM differences d JOIN old_wide o ON d.old_doc=o.document_id JOIN new_wide n ON d.new_doc=n.doc
        LEFT JOIN f0_first_context x ON x.old_doc=d.old_doc AND x.subject=d.subject
        LEFT JOIN release_sources s ON cast(s.list_row AS VARCHAR)=d.new_doc AND s.url=d.subject
        LEFT JOIN f0_body_target t ON t.body_key=d.value
        LEFT JOIN public_body_links p ON p.body_key=d.value AND p.doc=t.doc"""
    predicates=F0_PREDICATES
    branches=[f"SELECT d.difference_id,'{cause}' AS cause,'F0:{release_id}' AS evidence_ref {source} WHERE ({predicate})"
              for cause,predicate in predicates.items()]
    return [dict(name='f0_first_context',sql='''SELECT document_id AS old_doc,source_url AS subject,
        min(source_link_label[1]) AS link_text,min(source_page_url[1]) AS listed_on FROM old_file_rows
        WHERE source_url IS NOT NULL GROUP BY document_id,source_url''',materialize=True),
        dict(name='f0_body_target',sql='SELECT body_key,cast(min(list_row) AS VARCHAR) AS doc FROM source_members WHERE body_key IS NOT NULL GROUP BY body_key',materialize=True),
        dict(name='f0_cause_proofs',sql=' UNION ALL '.join(branches),materialize=True)]


def _text(key):
    return "json_get_str(fact,'" + key + "')"


def _bool(key):
    return "json_get_bool(fact,'" + key + "')"


def _int(key):
    return "json_get_int(fact,'" + key + "')"


RECOVERY_FIELDS=['recoveries','recovery.kind','recovery.recovered_url','recovery.imported_at','recovery.identity_note','recovery.suffix','recovery.bytes']


def recovery_value_matches():
    values={'recoveries':'body_sha',**{'recovery.'+name:'expected_'+name for name in ['kind','recovered_url','imported_at','identity_note','suffix','bytes']}}
    return '('+' OR '.join("(field='"+field+"' AND value="+_text(key)+')' for field,key in values.items())+')'


# These are explanations of observed changes, not admission/grouping rules.
# Every branch has an explicit field scope and direction. A receipt/reading or
# canonical model witness is required; a changed document alone proves nothing.
CAUSES = {
    'non_document_roles': (['document','body_keys','files'], 'removed',
        f"{_text('record_role')} IN ('caption','source_record','playlist','api','envelope')"),
    'listing_pages': (['document','body_keys','files'], 'removed', f"{_text('record_role')}='listing'"),
    'soft_error_wrapper_senate': (['body_keys','files'], 'removed',
        f"{_text('record_role')} IN ('error_response','wrapper') AND {_text('format')}='html'"),
    'real_web_untyped': (['body_keys','files'], 'added',
        f"{_text('record_role')}='document' AND {_bool('is_real_file')} AND ({_text('format')}='html' OR {_text('format')} IS NULL)"),
    'incomplete_damaged_failed_feed': (['body_keys','files'], 'removed',
        f"({_bool('complete')}=false OR {_text('record_role')}='damaged' OR {_text('reading_status')} IN ('failed','missing','error','size_limit','unreadable') OR {_text('xml_kind')}='feed')"),
    'recovery_independent_fetch': (['body_keys','files'], 'added',
        f"{_text('mode')}='fetch' AND {_bool('complete')} AND {_int('http_status')} BETWEEN 200 AND 299 AND {_text('outcome')} IN ('stored','unchanged') AND {_text('recovery_original_url')} IS NOT NULL"),
    'direct_provider_same_text': (['body_keys','files'], 'added',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('receipt_key')}={_text('other_receipt_key')} AND {_int('receipt_line')}={_int('other_receipt_line')} AND {_int('attempt')}<>{_int('other_attempt')}"),
    'eot_webharvest_attachment': (RECOVERY_FIELDS, 'added',
        f"regexp_like({_text('original_url')},'^https?://([^/]+[.])?veterans[.]house[.]gov/') AND regexp_like({_text('recovered_url')},'^https?://([^/]+[.])?webharvest[.]gov/') AND {recovery_value_matches()}"),
    'publisher_link_kind': (['document_kind'], 'added',
        f"{_int('filename_kind_count')}=0 AND {_text('publisher_kind')}=value AND {_text('link_basis')}='saved_page'"),
    'capture_header_names': (['filename','files'], ['added','removed'],
        f"{_text('name_basis')}='content_disposition' AND ((direction='added' AND {_text('header_filename')}=value) OR (direction='removed' AND {_text('header_filename')}<>value))"),
    'saved_text_exact_twins': (['body_keys','files','saved_body'], 'removed',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('source_url')}={_text('other_source_url')} AND {_text('fidelity')}='saved-text' AND {_text('other_fidelity')}='exact-bytes'"),
    'govinfo_same_stem_groups': (['body_keys','files'], 'added',
        f"{_text('group_id')} IS NOT NULL AND ({_text('group_kind')}='same_stem' OR ({_text('group_kind')}='publisher' AND regexp_like({_text('source_url')},'^https?://([^/]+[.])?govinfo[.]gov/')))"),
    'old_placeholder_xml': (['body_keys','files'], 'removed',
        f"{_text('record_role')}='error_response' AND {_text('format')}='html' AND {_int('distinct_contexts')}>100 AND regexp_like({_text('source_url')},'^https?://docs[.]house[.]gov/.*[.]xml([?#]|$)')"),
    'link_label_provenance': (['title','source.link_text','source.listed_on'], 'added',
        f"{_text('label_basis')}='saved_page' AND ((field='source.listed_on' AND {_text('listed_on')}=value) OR (field<>'source.listed_on' AND {_text('link_text')}=value))"),
    'capture_dates': (['first_captured','in_archive_since','date_kind'], 'removed',
        f"{_text('retrieved_at')} IS NULL AND {_bool('is_import_run')} AND {_text('old_time_basis')}='import_run'"),
    'govinfo123_fetch': (['first_captured','body_keys','files'], 'added',
        f"{_text('match_basis')}='direct_official_package' AND {_text('mode')}='fetch' AND {_text('requested_url')}={_text('url')} AND {_text('url')}={_text('original_url')} AND regexp_like({_text('url')},'^https?://([^/]+[.])?govinfo[.]gov/') AND {_bool('publisher_requested')} AND {_int('http_status')}=200 AND {_bool('complete')} AND {_text('outcome')}='stored' AND {_text('retrieved_at')} IS NOT NULL"),
    'b7_owner_recoveries': (RECOVERY_FIELDS, 'added',
        f"{_text('stage')}='raw-recoveries-owner-32c13ffa' AND {_text('decision_id')} IS NOT NULL AND {recovery_value_matches()}"),
}


def model_witness_steps(available, *, restrict_differences=False):
    """Join canonical facts in SQL; absent evidence is explicit, never a zero proof."""
    missing=set(CAUSES)
    empty="SELECT cast(NULL AS VARCHAR) AS old_doc,cast(NULL AS VARCHAR) AS new_doc,cast(NULL AS VARCHAR) AS subject,cast(NULL AS VARCHAR) AS fact,cast(NULL AS VARCHAR) AS evidence_ref WHERE false"
    keys={'receipt_key','receipt_line','capture_index'}
    requirements={'capture_sources':keys|{'source_id','body_sha','filename','source_url','import_date'},
        'capture_evidence':keys|{'format','mode','complete','http_status','outcome','url','requested_url','retrieved_at','fidelity','member_path','h_content_disposition'},
        'record_roles':keys|{'record_role','is_real_file'},
        'page_facts':{'body_sha','status','fingerprint','error_type'}}
    if any(not cols<=available.get(name,set()) for name,cols in requirements.items()):
        return [dict(name='witnesses',sql=empty)],sorted(missing)
    steps=[dict(name='e4_source_observations',sql="""SELECT s.source_id,s.body_sha,s.filename,s.source_url,s.import_date,
        c.receipt_key,c.receipt_line,c.capture_index,c.format,c.mode,c.complete,c.http_status,c.outcome,c.url,c.requested_url,
        c.retrieved_at,c.fidelity,c.member_path,c.h_content_disposition,r.record_role,r.is_real_file,
        p.status AS reading_status,encode(p.fingerprint,'hex') AS fingerprint,p.error_type
        FROM capture_sources s JOIN capture_evidence c USING(receipt_key,receipt_line,capture_index)
        JOIN record_roles r USING(receipt_key,receipt_line,capture_index)
        LEFT JOIN page_facts p ON encode(p.body_sha,'hex')=s.body_sha""",materialize=True),
        dict(name='e4_source_contexts',sql='SELECT body_sha,count(DISTINCT source_url) AS distinct_contexts FROM e4_source_observations GROUP BY body_sha',materialize=True),
        dict(name='e4_evidence_sources',sql="SELECT 'old' AS side,* FROM old_evidence_sources UNION ALL SELECT 'new',* FROM new_evidence_sources",materialize=True),
        dict(name='e4_observations',sql="""SELECT m.side,m.doc,m.body_key,c.*,x.distinct_contexts FROM e4_evidence_sources m
            LEFT JOIN e4_source_observations c ON c.body_sha=(regexp_match(m.body_key,'([0-9a-f]{64})'))[1]
            AND c.source_url IS NOT DISTINCT FROM m.source_url
            LEFT JOIN e4_source_contexts x USING(body_sha)""",materialize=True)]
    branches=[]
    def branch(table, facts, *, subject, condition='true', evidence="receipt_key||':'||cast(receipt_line AS VARCHAR)||':'||cast(capture_index AS VARCHAR)"):
        # json_array uses the maintained engine encoder once; strip only its
        # outer brackets to retain the object's exact scalar JSON types.
        fields=','.join("'"+name+"',"+expr for name,expr in facts.items())
        selected=table
        if restrict_differences:
            selected+=f" JOIN differences ON ((side='old' AND doc=differences.old_doc) OR (side='new' AND doc=differences.new_doc)) AND differences.subject=({subject})"
        branches.append(f"SELECT CASE WHEN side='old' THEN doc END AS old_doc,CASE WHEN side='new' THEN doc END AS new_doc,subject,substr(encoded,2,length(encoded)-2) AS fact,evidence_ref FROM (SELECT side,doc,{subject} AS subject,json_array(named_struct({fields})) AS encoded,{evidence} AS evidence_ref FROM {selected} WHERE {condition})")
    facts={k:k for k in ['record_role','is_real_file','format','mode','complete','http_status','outcome','url','requested_url','fidelity','source_url','receipt_key','receipt_line','reading_status','distinct_contexts','error_type','fingerprint']}
    facts.update(retrieved_at='cast(retrieved_at AS VARCHAR)',is_import_run='import_date IS NOT NULL',
        old_time_basis="CASE WHEN import_date IS NOT NULL AND retrieved_at IS NULL THEN 'import_run' END",
        xml_kind="CASE WHEN format='xml' AND record_role='listing' THEN 'feed' END",
        name_basis="CASE WHEN member_path IS NULL AND disposition_filename(h_content_disposition)=filename THEN 'content_disposition' END",
        header_filename='disposition_filename(h_content_disposition)')
    for subject in ["body_key","json_array(body_key,source_url)","coalesce(source_url,'')"]:
        branch('e4_observations',facts,subject=subject)
    # Empty-subject witnesses address scalar fields. Non-document/listing facts
    # cannot explain a whole lost document unless every source supports it.
    scalar=dict(facts,record_role="CASE WHEN count_real=0 AND count_unknown=0 THEN record_role END")
    steps.append(dict(name='e4_scalar_observations',sql="""SELECT *,sum(CASE WHEN is_real_file THEN 1 ELSE 0 END) OVER(PARTITION BY side,doc) AS count_real,
        sum(CASE WHEN record_role IS NULL THEN 1 ELSE 0 END) OVER(PARTITION BY side,doc) AS count_unknown FROM e4_observations""",materialize=True))
    branch('e4_scalar_observations',scalar,subject="''")
    missing-=set(['non_document_roles','listing_pages','soft_error_wrapper_senate','real_web_untyped',
        'incomplete_damaged_failed_feed','capture_header_names','old_placeholder_xml','capture_dates'])
    if {'source_id','body_sha','format','group_kind','group_id'}<=available.get('valid_rendition_members',set()):
        steps.append(dict(name='e4_group_observations',sql='SELECT o.*,g.group_kind,g.group_id FROM e4_observations o JOIN valid_rendition_members g ON o.source_id=g.source_id AND o.body_sha=g.body_sha',materialize=True))
        for subject in ['body_key','json_array(body_key,source_url)']:
            branch('e4_group_observations',dict(source_url='source_url',group_kind='group_kind',group_id='group_id'),subject=subject)
        missing.remove('govinfo_same_stem_groups')
    steps.append(dict(name='e4_twin_observations',sql="""SELECT a.*,b.fingerprint AS other_fingerprint,b.source_url AS other_source_url,b.fidelity AS other_fidelity
        FROM e4_observations a JOIN e4_source_observations b ON a.source_url=b.source_url AND a.fingerprint=b.fingerprint
        WHERE a.fidelity='saved-text' AND b.fidelity='exact-bytes' AND a.body_sha<>b.body_sha""",materialize=True))
    for subject in ['body_key','json_array(body_key,source_url)',"''"]:
        branch('e4_twin_observations',{key:key for key in ['fingerprint','source_url','fidelity','other_fingerprint','other_source_url','other_fidelity']},subject=subject)
    missing.remove('saved_text_exact_twins')
    recovery_cols={'id','original_url','body_sha256','kind','recovered_url','recovered_filename','decided_at','identity_note'}
    if recovery_cols<=available.get('current_recoveries',set()):
        steps.append(dict(name='e4_recovery_observations',sql="""SELECT o.*,r.original_url AS recovery_original_url,r.recovered_url,r.kind,r.id AS decision_id,r.body_sha256
            FROM e4_observations o JOIN current_recoveries r ON o.source_url=r.original_url AND o.body_sha=r.body_sha256""",materialize=True))
        for subject in ['body_key','json_array(body_key,source_url)']:
            branch('e4_recovery_observations',{key:key for key in ['mode','complete','http_status','outcome','recovery_original_url']},subject=subject)
        missing.remove('recovery_independent_fetch')
        steps.append(dict(name='e4_recovery_documents',sql="""SELECT m.side,m.doc,r.* FROM e4_evidence_sources m JOIN current_recoveries r ON m.source_url=r.original_url""",materialize=True))
        branch('e4_recovery_documents',dict(original_url='original_url',recovered_url='recovered_url',body_sha='body_sha256',expected_kind='json_array(kind)',expected_recovered_url='json_array(recovered_url)',expected_identity_note='json_array(identity_note)'),subject='body_sha256',evidence="'provenance/recoveries:'||id")
        missing.remove('eot_webharvest_attachment')
        if {'b7_recovery_decisions','b7_ready_imports','b7_source_time_minima'}<=set(available):
            steps.append(dict(name='e4_b7_active',sql='SELECT a.* FROM b7_recovery_decisions a LEFT ANTI JOIN b7_recovery_decisions b ON a.id=b.supersedes',materialize=True))
            steps.append(dict(name='e4_b7_recoveries',sql="""SELECT r.*,a.kind AS approved_kind,a.recovered_url AS approved_recovered_url,a.identity_note AS approved_identity_note,
                to_char(arrow_cast(try_cast(coalesce(t.retrieved_at,i.retrieved_at) AS TIMESTAMP),'Timestamp(Microsecond, Some("UTC"))') AT TIME ZONE 'America/New_York','%Y-%m-%d') AS approved_imported_at,
                i.stored_suffix AS approved_suffix,cast(i.bytes AS VARCHAR) AS approved_bytes
                FROM e4_recovery_documents r JOIN e4_b7_active a ON r.id=a.id AND r.original_url=a.original_url AND r.body_sha256=a.body_sha256
                LEFT JOIN b7_ready_imports i ON r.original_url=i.original_url AND r.body_sha256=i.body_sha256
                LEFT JOIN b7_source_time_minima t ON r.original_url=t.original_url AND r.body_sha256=t.body_sha256""",materialize=True))
            branch('e4_b7_recoveries',dict(stage="'raw-recoveries-owner-32c13ffa'",decision_id='id',body_sha='body_sha256',
                **{'expected_'+name:'json_array(approved_'+name+')' for name in ['kind','recovered_url','identity_note']},
                **{'expected_'+name:'CASE WHEN approved_'+name+' IS NOT NULL THEN json_array(approved_'+name+') END' for name in ['imported_at','suffix','bytes']}),
                subject='body_sha256',evidence="'raw-recoveries-owner-32c13ffa:'||id")
            missing.remove('b7_owner_recoveries')
    if {'source_id','page_body','context_url','text','doc_type','link_index'}<=available.get('publisher_links',set()):
        steps.append(dict(name='e4_link_observations',sql='SELECT o.*,p.page_body,p.context_url AS listed_on,p.text AS link_text,p.link_index FROM e4_observations o JOIN publisher_links p USING(source_id)',materialize=True))
        branch('e4_link_observations',dict(label_basis="'saved_page'",link_text='link_text',listed_on='listed_on'),subject='source_url',evidence="'page:'||page_body||':'||cast(link_index AS VARCHAR)")
        missing.remove('link_label_provenance')
    annotations={'source_filename_readings':{'source_id','status','document_kind'},
        'source_annotation_publisher':{'source_id','document_kind','listing_title'},
        'new_wide':{'doc','list_row','filename','saved_body'},
        'release_sources':{'list_row','url','member_path','is_saved'}}
    if all(fields<=available.get(name,set()) for name,fields in annotations.items()):
        steps.append(dict(name='e4_saved_annotations',sql="""SELECT o.*,p.document_kind AS publisher_kinds,p.listing_title,
            cast(CASE WHEN f.status='completed' THEN coalesce(cardinality(f.document_kind),0) ELSE 0 END AS BIGINT) AS filename_kind_count
            FROM e4_observations o JOIN new_wide n ON o.side='new' AND o.doc=n.doc
            JOIN release_sources a ON a.list_row=n.list_row AND a.is_saved AND a.url=o.source_url
                AND (a.member_path IS NOT DISTINCT FROM o.member_path)
            JOIN source_filename_readings f ON o.source_id=f.source_id JOIN source_annotation_publisher p ON o.source_id=p.source_id
            WHERE o.body_sha=encode(n.saved_body,'hex') AND o.filename=n.filename""",materialize=True))
        steps.append(dict(name='e4_publisher_kinds',sql='SELECT *,unnest(publisher_kinds) AS publisher_kind FROM e4_saved_annotations',materialize=True))
        branch('e4_publisher_kinds',dict(filename_kind_count='filename_kind_count',publisher_kind='publisher_kind',link_basis="'saved_page'"),subject="''",evidence="'model:source_annotation_publisher:'||source_id")
        missing.remove('publisher_link_kind')
        if {'source_id','title'}<=available.get('source_annotations',set()):
            steps.append(dict(name='e4_publisher_titles',sql='SELECT o.*,a.title AS effective_title FROM e4_saved_annotations o JOIN source_annotations a USING(source_id)',materialize=True))
            branch('e4_publisher_titles',dict(label_basis="'saved_page'",link_text='listing_title'),subject="''",condition='listing_title=effective_title',evidence="'model:source_annotation_publisher:'||source_id")
    # The official-package proof needs its retained raw association flag; no URL
    # inference substitutes for the owner's publisher_requested condition.
    official={'publisher_requested','match_basis','original_url'}
    if official<=available.get('capture_evidence',set()):
        steps.append(dict(name='e4_official_observations',sql='SELECT o.*,c.publisher_requested,c.match_basis,c.original_url FROM e4_observations o JOIN capture_evidence c USING(receipt_key,receipt_line,capture_index)',materialize=True))
        for subject in ['body_key','json_array(body_key,source_url)',"''"]:
            branch('e4_official_observations',{key:key for key in ['publisher_requested','match_basis','original_url','mode','complete','http_status','outcome','url','requested_url','retrieved_at']},subject=subject)
        missing.remove('govinfo123_fetch')
    # D1's narrowed surface deliberately has no provider-attempt history. The
    # cause stays visible as unavailable instead of fabricating retry matches.
    steps.append(dict(name='witnesses',sql=' UNION '.join(branches),materialize=True))
    return steps,sorted(missing)


def cause_steps(*, f0=False):
    branches = []
    for cause, (fields, direction, predicate) in CAUSES.items():
        scope = ','.join("'" + name + "'" for name in fields)
        directions=direction if isinstance(direction,list) else [direction]
        direction_sql=','.join("'"+name+"'" for name in directions)
        branches.append(f"""SELECT DISTINCT difference_id,'{cause}' AS cause,evidence_ref
            FROM observed_differences WHERE field IN ({scope}) AND direction IN ({direction_sql})
            AND evidence_ref IS NOT NULL AND length(evidence_ref)>0 AND ({predicate})""")
    if f0:
        branches.append('SELECT difference_id,cause,evidence_ref FROM f0_cause_proofs')
    return [dict(name='known_causes',sql=' UNION ALL '.join(branches),materialize=True)]


def alignment_steps():
    # Exact evidence sets avoid expanding unchanged editions sharing an address.
    # Remaining edges are many-to-many; worst-case output is O(old × new) per
    # anchor. Report its fanout rather than hide rows or choose an arbitrary mate.
    return [
        dict(name='old_signatures',sql="SELECT doc,json_array(array_sort(array_agg(DISTINCT identity_anchor))) AS signature FROM old_anchors GROUP BY doc",materialize=True),
        dict(name='new_signatures',sql="SELECT doc,json_array(array_sort(array_agg(DISTINCT identity_anchor))) AS signature FROM new_anchors GROUP BY doc",materialize=True),
        dict(name='exact_pairs',sql='SELECT o.doc AS old_doc,n.doc AS new_doc FROM old_signatures o JOIN new_signatures n ON o.signature=n.signature',materialize=True),
        dict(name='unmatched_old_anchors',sql='SELECT o.* FROM old_anchors o LEFT ANTI JOIN exact_pairs p ON p.old_doc=o.doc',materialize=True),
        dict(name='unmatched_new_anchors',sql='SELECT n.* FROM new_anchors n LEFT ANTI JOIN exact_pairs p ON p.new_doc=n.doc',materialize=True),
        dict(name='aligned_pairs',sql='''SELECT old_doc,new_doc FROM exact_pairs UNION
            SELECT o.doc,n.doc FROM unmatched_old_anchors o JOIN new_anchors n ON o.anchor=n.anchor
            UNION SELECT o.doc,n.doc FROM old_anchors o JOIN unmatched_new_anchors n ON o.anchor=n.anchor''',materialize=True),
    ]


def decision_ready(*, unclassified, derived_only, invalid_ids, missing_evidence, invalid_records=0):
    return not any((unclassified, derived_only, invalid_ids, missing_evidence, invalid_records))


def id_inputs(alias):
    return f"""CASE WHEN coalesce(array_length({alias}.body_keys),0)>0
        THEN json_array('bodies',array_sort(array_distinct({alias}.body_keys)))
        ELSE json_array('sources',array_sort(array_distinct({alias}.source_ids))) END"""


def comparison_steps(*, f0_release=None, witness_step=None):
    steps = alignment_steps()
    steps.append(dict(name='identity_input_changes',sql=f'''SELECT p.old_doc,p.new_doc,
        o.document_id AS old_id,n.document_id AS new_id,{id_inputs('o')} AS old_inputs,{id_inputs('n')} AS new_inputs
        FROM aligned_pairs p JOIN identity_documents o ON o.side='old' AND o.doc=p.old_doc
        JOIN identity_documents n ON n.side='new' AND n.doc=p.new_doc
        WHERE ({id_inputs('o')}) IS DISTINCT FROM ({id_inputs('n')})''',materialize=True))
    steps += [
        dict(name='old_values',sql='SELECT DISTINCT p.old_doc,p.new_doc,f.field,f.subject,f.value FROM aligned_pairs p JOIN old_fields f ON p.old_doc=f.doc',materialize=True),
        dict(name='new_values',sql='SELECT DISTINCT p.old_doc,p.new_doc,f.field,f.subject,f.value FROM aligned_pairs p JOIN new_fields f ON p.new_doc=f.doc',materialize=True),
        dict(name='delta_values',sql='''SELECT o.old_doc,o.new_doc,o.field,o.subject,o.value,'removed' AS direction
            FROM old_values o LEFT ANTI JOIN new_values n ON o.old_doc=n.old_doc AND o.new_doc=n.new_doc
                AND o.field=n.field AND o.subject=n.subject AND o.value=n.value
            UNION ALL SELECT n.old_doc,n.new_doc,n.field,n.subject,n.value,'added' FROM new_values n
            LEFT ANTI JOIN old_values o ON o.old_doc=n.old_doc AND o.new_doc=n.new_doc
                AND o.field=n.field AND o.subject=n.subject AND o.value=n.value
            UNION ALL SELECT d.doc AS old_doc,cast(NULL AS VARCHAR) AS new_doc,'document' AS field,'' AS subject,d.doc AS value,'removed' AS direction FROM old_documents d
                WHERE NOT EXISTS(SELECT 1 FROM aligned_pairs p WHERE p.old_doc=d.doc)
            UNION ALL SELECT cast(NULL AS VARCHAR) AS old_doc,d.doc AS new_doc,'document' AS field,'' AS subject,d.doc AS value,'added' AS direction FROM new_documents d
                WHERE NOT EXISTS(SELECT 1 FROM aligned_pairs p WHERE p.new_doc=d.doc)''',materialize=True),
        dict(name='differences',sql="SELECT DISTINCT encode(sha256(json_array(old_doc,new_doc,field,subject,value,direction)),'hex') AS difference_id,* FROM delta_values",materialize=True),
        dict(name='observed_differences',sql='''SELECT d.*,w.fact,w.evidence_ref FROM differences d LEFT JOIN witnesses w
            ON (w.old_doc IS NULL OR w.old_doc=d.old_doc) AND (w.new_doc IS NULL OR w.new_doc=d.new_doc)
            AND w.subject=d.subject AND (w.old_doc IS NOT NULL OR w.new_doc IS NOT NULL)''',materialize=True),
    ]
    if witness_step is not None:
        index=next(i for i,step in enumerate(steps) if step['name']=='observed_differences')
        steps.insert(index,witness_step)
    if f0_release:
        steps += f0_proof_steps(f0_release)[-1:]
    steps += cause_steps(f0=bool(f0_release))
    steps += [
        dict(name='unexplained',sql='SELECT d.* FROM differences d LEFT ANTI JOIN known_causes c ON d.difference_id=c.difference_id',materialize=True),
        dict(name='classified',sql='''SELECT u.*,r.classification,r.rule_ref,r.note,r.raw_signal FROM unexplained u
            LEFT JOIN difference_records r ON u.difference_id=r.difference_id''',materialize=True),
        dict(name='source_identity_errors',sql="""SELECT DISTINCT side,doc,'source_id' AS identity,source_id AS declared,
            encode(sha256(json_array(body_key,filename,source_url)),'hex') AS computed
            FROM identity_sources WHERE source_id IS DISTINCT FROM encode(sha256(json_array(body_key,filename,source_url)),'hex')""",materialize=True),
        dict(name='document_identity_errors',sql="""SELECT side,doc,'document_id' AS identity,document_id AS declared,
            encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex') AS computed FROM identity_documents
            WHERE document_id IS DISTINCT FROM encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex')""",materialize=True),
    ]
    return steps


RELEASE_AFTER={
    'old_source_formats':['old_media'],
    'old_identity_sources':['old_source_formats'],
    'old_identity_groups':['old_identity_sources'],
    'old_meetings':['old_catalog'],
    'identity_documents':['old_identity_groups'],
    'public_body_links':['body_map'],
    'aligned_pairs':['old_signatures','new_signatures','exact_pairs','unmatched_old_anchors','unmatched_new_anchors','old_anchors','new_anchors'],
    'source_identity_errors':['identity_sources'],
    'document_identity_errors':['identity_documents','model_real_sources'],
    'old_values':['old_fields','old_file_rows','old_committees','old_bodies','old_times','old_meetings','old_capture_metadata','old_url_keys','old_lookup_keys_full','old_lookup_sources','old_lookup_parts','old_lookup_hosts','old_lookup_paths','old_lookup_values'],
    'new_values':['new_fields','new_bodies','source_members'],
    'delta_values':['old_values','new_values','old_documents','new_documents'],
    'differences':['delta_values'],
    'observed_differences':['witnesses'],
    'f0_cause_proofs':['old_wide','new_wide','f0_first_context','f0_body_target','public_body_links'],
    'known_causes':['f0_cause_proofs'],
}


def compare_relations(inputs, *, engine, work, missing_evidence=0, prelude=(), f0_release=None, witness_step=None):
    work = Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    outputs = [parquet_output(work,name,sql,order) for name,sql,order in [
        ('differences','SELECT * FROM differences',['difference_id']),
        ('explained','SELECT * FROM known_causes',['difference_id','cause','evidence_ref']),
        ('unexplained','SELECT * FROM classified',['difference_id']),
        ('alignment','SELECT * FROM aligned_pairs',['old_doc','new_doc']),
        ('identity-errors','SELECT * FROM source_identity_errors UNION ALL SELECT * FROM document_identity_errors',['side','doc','identity']),
        ('identity-input-changes','SELECT * FROM identity_input_changes',['old_doc','new_doc']),
    ]]
    queries = [dict(name='failure_causes',sql="SELECT json_get_str(o.fact,'format') AS format,json_get_str(o.fact,'error_type') AS error_type,count(DISTINCT c.difference_id) AS differences FROM known_causes c JOIN observed_differences o ON c.difference_id=o.difference_id AND c.evidence_ref=o.evidence_ref WHERE c.cause='incomplete_damaged_failed_feed' GROUP BY json_get_str(o.fact,'format'),json_get_str(o.fact,'error_type') ORDER BY format,error_type"),dict(name='counts',sql='''SELECT (SELECT count(*) FROM differences) AS differences,
        (SELECT count(*) FROM unexplained) AS unexplained,
        (SELECT count(*) FROM classified WHERE classification IS NULL) AS unclassified,
        (SELECT count(*) FROM classified WHERE classification='derived_only_fact') AS derived_only,
        (SELECT count(*) FROM difference_records r WHERE classification IS NULL
            OR classification NOT IN ('rule_change','old_pipeline_error','derived_only_fact')
            OR note IS NULL OR length(trim(note))=0
            OR (classification='rule_change' AND (rule_ref IS NULL OR length(trim(rule_ref))=0))
            OR NOT EXISTS(SELECT 1 FROM unexplained u WHERE u.difference_id=r.difference_id))
            +(SELECT count(*) FROM (SELECT difference_id FROM difference_records GROUP BY difference_id HAVING count(*)>1)) AS invalid_records,
        (SELECT count(*) FROM source_identity_errors)+(SELECT count(*) FROM document_identity_errors) AS invalid_ids,
        (SELECT count(*) FROM aligned_pairs) AS aligned_pairs,
        (SELECT count(*) FROM identity_input_changes) AS id_inputs_changed'''),
        dict(name='identity_examples',sql='SELECT * FROM identity_input_changes ORDER BY old_doc,new_doc LIMIT 3'),
        dict(name='examples',sql='''SELECT * FROM (SELECT c.cause,d.*,c.evidence_ref,
            row_number() OVER(PARTITION BY cause ORDER BY d.difference_id,c.evidence_ref) AS example
            FROM known_causes c JOIN differences d ON c.difference_id=d.difference_id) WHERE example<=3 ORDER BY cause,example'''),
        dict(name='clusters',sql='''SELECT field,direction,classification,count(*) AS differences,
            count(*) FILTER(WHERE raw_signal IS NOT NULL AND length(raw_signal)>0) AS with_raw_signal
            FROM classified GROUP BY field,direction,classification ORDER BY differences DESC,field,direction''')]
    names=[*CAUSES,*([*F0_PREDICATES] if f0_release else [])]
    registry=' UNION ALL '.join("SELECT '"+name+"' AS cause" for name in names)
    queries.append(dict(name='causes',sql=f'''SELECT r.cause,coalesce(c.differences,0) AS differences,'field_differences' AS unit FROM ({registry}) r
        LEFT JOIN (SELECT cause,count(DISTINCT difference_id) AS differences FROM known_causes GROUP BY cause) c USING(cause)
        UNION ALL SELECT 'document_id_inputs_changed',count(*),'document_pairs' FROM identity_input_changes ORDER BY cause'''))
    core=comparison_steps(f0_release=f0_release,witness_step=witness_step)
    # ID checks consume wide source evidence before the large field comparison.
    errors=[step for step in core if step['name'] in {'source_identity_errors','document_identity_errors'}]
    core=[step for step in core if step not in errors]
    index=next(i for i,step in enumerate(core) if step['name']=='identity_input_changes')+1
    core[index:index]=errors
    job_steps=[*prelude,*core]
    names={item['name'] for item in [*inputs,*job_steps]}
    for step in job_steps:
        released=set(step.get('release_after',[]))|set(RELEASE_AFTER.get(step['name'],[]))
        if released:step['release_after']=sorted(released&names)
    reports=run_job(work,engine,inputs=inputs,steps=job_steps,outputs=outputs,queries=queries)
    counts=reports['counts'][0]
    ready=decision_ready(**{key:counts[key] for key in ['unclassified','derived_only','invalid_ids','invalid_records']},missing_evidence=missing_evidence)
    result=dict(version=1,status='complete' if ready else 'incomplete',decision_ready=ready,
        counts=dict(counts,missing_evidence=missing_evidence),causes=reports['causes'],examples=reports['examples'],
        identity_examples=reports['identity_examples'],clusters=reports['clusters'],failure_causes=reports['failure_causes'])
    (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def compare_descriptor(descriptor, *, engine_config, work):
    loaded=load_descriptor(descriptor)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    parallel=NativeDatasets.from_config(restricted_runtime(engine_config,work/'comparison-runtime',threads=4))
    validate_layout(loaded,engine=parallel,work=work/'layout-validation')
    scope=None
    if loaded['oracle_scope']=='source_evidence':
        scope=select_oracle_scope(loaded,engine=parallel,work=work/'scope')
        if scope['partial_documents']:
            result=dict(version=1,status='incomplete',decision_ready=False,scope_comparison_ready=False,model_qualified=False,
                candidate_kind='model',release_id=loaded['manifest']['release_id'],scope=scope,
                reason='Selected inputs do not cover every source of a touched old component; field comparison was not run.',
                counts=dict(differences=None,unexplained=None,unclassified=None,invalid_ids=None,missing_evidence=scope['missing_files']),
                causes=[dict(cause=name,differences=None,evidence_status='unavailable') for name in [*CAUSES,'document_id_inputs_changed']],
                oracle=loaded['selector'],descriptor_sha256=loaded['descriptor_sha256'])
            (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
            return result
    staging=work/'inputs';staging.mkdir()
    inputs,steps=normalization(loaded,directory=staging)
    kind=loaded['descriptor']['candidate']['kind']
    missing=[];witness=None
    missing_coverage=[] if 'catalog_capture_metadata' in loaded['paths'] else ['saved_bytes','saved_media_type','alternate.bytes']
    if kind=='model':
        import pyarrow.parquet as pq
        available={name:set(pq.read_schema(path).names) for name,path in loaded['paths'].items() if name in loaded['descriptor'].get('cause_relations',{}) or name.startswith('b7_')}
        available['new_wide']=set(pq.read_schema(loaded['paths']['document_rows']).names)|{'doc'}
        available['release_sources']=set(pq.read_schema(loaded['paths']['release_sources']).names)
        witness_steps,missing=model_witness_steps(available,restrict_differences=True)
        witness=witness_steps.pop()
        steps+=witness_steps
    result=compare_relations(inputs,engine=parallel,work=work/'result',prelude=steps,
        missing_evidence=len(missing)+len(missing_coverage),f0_release=loaded['manifest']['release_id'] if kind=='f0' else None,witness_step=witness)
    for row in result['causes']:
        row['evidence_status']='unavailable' if row['cause'] in missing else 'available'
        if row['cause'] in missing:row['differences']=None
    result.update(candidate_kind=kind,model_qualified=kind=='model' and result['decision_ready'],missing_causes=missing,missing_coverage=missing_coverage,release_id=loaded['manifest']['release_id'],
        oracle=loaded['selector'],descriptor_sha256=loaded['descriptor_sha256'])
    if scope is not None:
        result.update(scope=scope,scope_comparison_ready=result['decision_ready'],decision_ready=False,model_qualified=False,status='incomplete',
            reason='This comparison covers a declared source-evidence slice, not the full oracle population.')
    (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare-f0','compare'])
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    args=parser.parse_args()
    if not args.runtime:parser.error('An explicitly pinned local runtime is required')
    if args.operation=='prepare-f0':
        work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
        engine=NativeDatasets.from_config(restricted_runtime(args.runtime,work/'runtime',threads=4))
        output=prepare_f0(args.inputs,engine=engine,work=work/'layout')
        print(output)
        return 0
    result=compare_descriptor(args.inputs,engine_config=args.runtime,work=args.work)
    print(json.dumps(result,indent=2))
    return 0 if result['decision_ready'] else 1


if __name__=='__main__':
    raise SystemExit(main())
