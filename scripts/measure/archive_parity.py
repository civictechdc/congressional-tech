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
    if value.get('version')!=1:
        raise ValueError('Missing version-1 parity descriptor')
    base=path.parent
    paths,selector=oracle_inputs(base,value.get('oracle',{}))
    candidate=value.get('candidate',{})
    release_paths,manifest=release_inputs(base,candidate)
    paths.update(release_paths)
    members=pinned_file(base,candidate.get('source_members'))
    if set(pq.read_schema(members).names)!=MEMBER_COLUMNS:
        raise ValueError('Source-member sidecar must have the agreed seven columns')
    paths['source_members']=str(members)
    for name,pin in value.get('cause_relations',{}).items():
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
    return dict(base=base,descriptor=value,paths=paths,manifest=manifest,selector=selector,
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
    limits['scratch_bytes']=min(limits['scratch_bytes'],2<<30)
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


def producer_inputs(base, candidate, manifest):
    """Native writer hashes and explicit sort bind private rows to public rows."""
    job_path=pinned_file(base,candidate.get('build_job'))
    result_path=pinned_file(base,candidate.get('build_result'))
    job=json.loads(job_path.read_text());result=json.loads(result_path.read_text())
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
        if order[:3]!=['filename','document_date','first_captured'] or len(order)!=4 or order[-1] not in {'doc_key','document_id'}:
            raise ValueError('Public rows need the explicit document sort')
        if spec['sql'].strip().lower()!='select * from '+relation:
            raise ValueError('Public writer must consume the agreed ordered relation')
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
    columns=','.join('"'+name+'"' for name in LIST_COLUMNS+DETAIL_COLUMNS)
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
    value['cause_relations']={}
    for group in ['oracle','provenance']:
        for item in value[group].values():item['path']=str((template.parent/item['path']).resolve())
    output=work/'parity-inputs.json';output.write_text(json.dumps(value,indent=2)+'\n')
    return output


def validate_layout(loaded, *, engine, work):
    """Check multiplicities and source keys; never infer physical row order."""
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS
    import pyarrow.parquet as pq
    value=loaded['descriptor'];base=loaded['base'];candidate=value['candidate'];paths=loaded['paths']
    job,result=producer_inputs(base,candidate,loaded['manifest'])
    rows=pinned_file(base,candidate.get('document_rows'))
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
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    inputs=[dict(name=name,kind='parquet',path=paths[name]) for name in ['release_list','release_detail','source_members','document_rows']]
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
        "SELECT count(*) AS errors FROM (SELECT source_id FROM source_members GROUP BY source_id HAVING count(*)<>1)",
        "SELECT CASE WHEN count(*)=0 OR min(list_row)=0 AND max(list_row)=count(*)-1 THEN 0 ELSE 1 END AS errors FROM document_rows"]
    reports=run_job(work,engine,inputs=inputs,steps=[],outputs=[],queries=[dict(name='checks',sql=' UNION ALL '.join(checks))])
    if any(row['errors'] for row in reports['checks']):
        raise ValueError('Public/private row values, multiplicity or source membership disagree')


def field_rows(table, doc, scalars, arrays=(), *, subject="''"):
    branches=[f"SELECT {doc} AS doc,'{field}' AS field,{subject} AS subject,cast({value} AS VARCHAR) AS value FROM {table}" for field,value in scalars.items()]
    branches += [f"SELECT {doc} AS doc,'{field}' AS field,{subject} AS subject,cast(unnest({value}) AS VARCHAR) AS value FROM {table}" for field,value in arrays]
    return 'SELECT DISTINCT * FROM ('+' UNION ALL '.join(branches)+') WHERE value IS NOT NULL'


def normalization(loaded, *, directory):
    """Project the old consumer and actual new release into comparable facts."""
    from congress_api.retention.index.schemas import MEDIA_FORMATS,EMPTY_BODY_DIGEST
    from viewer_publication.archive_format import EMPTY_STRINGS
    paths=loaded['paths'];kind=loaded['descriptor']['candidate']['kind']
    inputs=[dict(name=name,kind='parquet',path=path) for name,path in paths.items()
            if name.startswith('oracle_') or name.startswith('release_') or name in {'source_members','document_rows'} or name.startswith('b7_')]
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
        AND ((regexp_like({status},'(^|,)2') AND (NOT regexp_like({status},'(^|,)[0-9]{{3}}(,|$)') OR regexp_like({status},'(^|,)2[0-9]{{2}}(,|$)'))
             OR (coalesce(cardinality(f.http_status),0)=0 AND f.body_format=make_array('pdf'))))"""
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
        dict(name='old_times',sql="SELECT document_id,min(cast(try_cast(t AS TIMESTAMP WITH TIME ZONE) AT TIME ZONE 'America/New_York' AS DATE)) AS first_captured FROM (SELECT document_id,unnest(state_retrieved_at) AS t FROM oracle_documents) GROUP BY document_id",materialize=True),
        dict(name='old_wide',sql='''SELECT d.document_id,d.filename,d.source_url,d.source_link_label,d.body_key,
            d.state_retrieved_at,d.date_token,d.document_kind,d.document_family,d.congress,d.format,
            d.measure_references,d.member_bioguide_id,d.hearing_package_id,d.committee_code,d.date_token_candidates,
            t.first_captured FROM oracle_documents d LEFT JOIN old_times t USING(document_id)''',materialize=True),
        dict(name='identity_sources',sql="""SELECT 'old' AS side,document_id AS doc,source_id,body_key,filename,source_url FROM oracle_filenames
            UNION ALL SELECT 'new',cast(list_row AS VARCHAR),source_id,body_key,effective_filename,source_url FROM source_members""",materialize=True),
    ]
    from viewer_publication.archive_format import LIST_COLUMNS,DETAIL_COLUMNS
    from viewer_publication.archive_release import _meeting_keys
    steps.append(dict(name='new_wide',sql='SELECT cast(list_row AS VARCHAR) AS doc,* FROM document_rows',materialize=True))
    steps.append(dict(name='old_meetings',sql=f'''SELECT DISTINCT document_id AS doc,cast(unnest({_meeting_keys('source_url')}) AS VARCHAR) AS meeting_key FROM oracle_documents
        UNION SELECT document_id,cast(try_cast(regexp_replace(unnest(source_meeting_id),'^(HHRG|HMKP|HMTG)-?','') AS BIGINT) AS VARCHAR) FROM oracle_documents''',materialize=True))
    if kind=='f0':
        new_ids="SELECT 'new' AS side,cast(s.list_row AS VARCHAR) AS doc,s.document_id,g.body_keys,g.source_ids FROM (SELECT DISTINCT document_id,list_row FROM source_members) s JOIN old_identity_groups g USING(document_id)"
    else:
        new_ids=f"""SELECT 'new' AS side,cast(list_row AS VARCHAR) AS doc,min(document_id) AS document_id,
            coalesce(array_sort(array_agg(DISTINCT body_key) FILTER(WHERE body_key IS NOT NULL)),{EMPTY_STRINGS}) AS body_keys,
            array_sort(array_agg(DISTINCT source_id)) AS source_ids FROM source_members GROUP BY list_row"""
    steps.append(dict(name='identity_documents',sql="SELECT 'old' AS side,document_id AS doc,document_id,body_keys,source_ids FROM old_identity_groups UNION ALL "+new_ids,materialize=True))
    # Nullable attributes remain absent facts; no fabricated date, label or body.
    scalar_old=dict(filename='filename',title='source_link_label[1]',saved_body='body_key',
        first_captured='first_captured',
        date_kind="CASE WHEN cardinality(state_retrieved_at)>0 THEN 'captured' ELSE 'unknown' END",
        document_date=legacy_date('old_wide'),document_date_source=f"CASE WHEN {legacy_date('old_wide')} IS NOT NULL THEN 'filename' END",
        saved_kind="'original'",hidden="'false'")
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
        'document_date_source','in_archive_since','removed_on','review_note','review_decided_at','package_id']}
    new_scalars['saved_body']="CASE WHEN saved_body IS NOT NULL THEN 'bodies/sha256/'||substr(encode(saved_body,'hex'),1,2)||'/'||encode(saved_body,'hex')||'.gz' END"
    new_arrays=[(name,name) for name in ['document_kind','document_family','committee_keys','chambers','meeting_keys','measure_keys','bioguide_ids','witness_keys','version_keys']]
    new_parts=[field_rows('new_wide','doc',new_scalars,new_arrays),
        field_rows('new_bodies','doc',dict(body_keys='body_key'),subject='body_key'),
        field_rows('public_body_links','doc',dict(body_link='body_key'),subject='body_key'),
        field_rows('source_members','cast(list_row AS VARCHAR)',dict(files='effective_filename'),subject='json_array(body_key,source_url)'),
        field_rows('release_sources','cast(list_row AS VARCHAR)',{'source.url':'url','source.listed_on':'listed_on','source.link_text':'link_text','source.member_path':'member_path','source.doc_type':'doc_type','source.posted':'posted','source.first_seen':'first_seen'},subject='url')]
    # Display folds compare the maintained registry's facts, not private parser
    # internals the new site never receives.
    display=json.loads((ROOT/'model/registries/display-facts.json').read_text())
    for row in display:
        name=row['field']
        old_parts.append(field_rows('oracle_documents','document_id',{},[('facts',name)],subject="'"+name+"'"))
    old_parts += ["""SELECT d.document_id AS doc,'alternates' AS field,(regexp_match(f.body_key,'([a-f0-9]{64})'))[1] AS subject,f.format[1] AS value
        FROM oracle_documents d JOIN oracle_filenames f USING(document_id)
        WHERE f.body_key IS NOT NULL AND f.body_key<>d.body_key AND f.format[1]<>d.format[1]"""]
    new_parts += ["SELECT doc,'facts' AS field,f['field'] AS subject,f['value'] AS value FROM (SELECT doc,unnest(facts) AS f FROM new_wide)",
        "SELECT doc,'alternates' AS field,encode(a['body'],'hex') AS subject,a['format'] AS value FROM (SELECT doc,unnest(alternates) AS a FROM new_wide)",
        "SELECT cast(list_row AS VARCHAR) AS doc,'recoveries' AS field,encode(body,'hex') AS subject,json_array(kind,encode(body,'hex'),recovered_url,cast(imported_at AS VARCHAR),identity_note) AS value FROM release_recoveries"]
    steps += [dict(name='old_fields',sql=' UNION '.join(old_parts)),dict(name='new_fields',sql=' UNION '.join(new_parts))]
    if kind=='f0':
        steps.append(dict(name='witnesses',sql="SELECT cast(NULL AS VARCHAR) AS old_doc,cast(NULL AS VARCHAR) AS new_doc,cast(NULL AS VARCHAR) AS subject,cast(NULL AS VARCHAR) AS fact,cast(NULL AS VARCHAR) AS evidence_ref WHERE false"))
    return inputs,steps


F0_PREDICATES={
    'f0_dates': """(d.field='first_captured' AND d.direction='removed' AND n.first_captured IS NULL)
        OR (d.field='date_kind' AND n.date_kind='unknown' AND d.value IN ('captured','unknown'))
        OR (d.field='in_archive_since' AND d.direction='removed' AND n.in_archive_since IS NULL)""",
    'f0_format_alternates': """d.direction='removed' AND ((d.field='format' AND d.value<>lower(o.format[1]) AND n.format=lower(o.format[1]))
        OR (d.field='alternates' AND coalesce(cardinality(n.alternates),0)=0))""",
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
        min(source_link_label[1]) AS link_text,min(source_page_url[1]) AS listed_on FROM oracle_filenames
        WHERE source_url IS NOT NULL GROUP BY document_id,source_url''',materialize=True),
        dict(name='f0_body_target',sql='SELECT body_key,cast(min(list_row) AS VARCHAR) AS doc FROM source_members WHERE body_key IS NOT NULL GROUP BY body_key',materialize=True),
        dict(name='f0_cause_proofs',sql=' UNION ALL '.join(branches),materialize=True)]


def _text(key):
    return "json_get_str(fact,'" + key + "')"


def _bool(key):
    return "json_get_bool(fact,'" + key + "')"


def _int(key):
    return "json_get_int(fact,'" + key + "')"


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
        f"({_bool('complete')}=false OR {_text('record_role')}='damaged' OR {_text('reading_status')} IN ('failed','missing') OR {_text('xml_kind')}='feed')"),
    'recovery_independent_fetch': (['body_keys','files'], 'added',
        f"{_text('mode')}='fetch' AND {_bool('complete')} AND {_int('http_status')} BETWEEN 200 AND 299 AND {_text('outcome')} IN ('stored','unchanged') AND {_text('recovery_original_url')} IS NOT NULL"),
    'direct_provider_same_text': (['body_keys','files'], 'added',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('receipt_key')}={_text('other_receipt_key')} AND {_int('receipt_line')}={_int('other_receipt_line')} AND {_int('attempt')}<>{_int('other_attempt')}"),
    'eot_webharvest_attachment': (['recoveries'], 'added',
        f"regexp_like({_text('original_url')},'^https?://([^/]+[.])?veterans[.]house[.]gov/') AND regexp_like({_text('recovered_url')},'^https?://([^/]+[.])?webharvest[.]gov/')"),
    'publisher_link_kind': (['document_kind'], 'added',
        f"{_int('filename_kind_count')}=0 AND {_text('publisher_kind')}=value AND {_text('link_basis')}='saved_page'"),
    'capture_header_names': (['filename','files'], 'added',
        f"{_text('name_basis')}='content_disposition' AND {_text('header_filename')}=value"),
    'saved_text_exact_twins': (['body_keys','files','saved_body'], 'removed',
        f"{_text('fingerprint')} IS NOT NULL AND {_text('fingerprint')}={_text('other_fingerprint')} AND {_text('source_url')}={_text('other_source_url')} AND {_text('fidelity')}='saved_text' AND {_text('other_fidelity')}='exact'"),
    'govinfo_same_stem_groups': (['body_keys','files'], 'added',
        f"{_text('group_id')} IS NOT NULL AND ({_text('group_kind')}='same_stem' OR ({_text('group_kind')}='publisher' AND regexp_like({_text('source_url')},'^https?://([^/]+[.])?govinfo[.]gov/')))"),
    'old_placeholder_xml': (['body_keys','files'], 'removed',
        f"{_text('record_role')}='error_response' AND {_text('format')}='html' AND {_int('distinct_contexts')}>100 AND regexp_like({_text('source_url')},'^https?://docs[.]house[.]gov/.*[.]xml([?#]|$)')"),
    'link_label_provenance': (['title','source.link_text','source.listed_on'], 'added',
        f"{_text('label_basis')}='saved_page' AND {_text('link_text')}=value"),
    'capture_dates': (['first_captured','in_archive_since','date_kind'], 'removed',
        f"{_text('retrieved_at')} IS NULL AND {_bool('is_import_run')} AND {_text('old_time_basis')}='import_run'"),
    'govinfo123_fetch': (['first_captured','body_keys','files'], 'added',
        f"{_text('match_basis')}='direct_official_package' AND {_text('mode')}='fetch' AND {_text('requested_url')}={_text('url')} AND {_text('url')}={_text('original_url')} AND regexp_like({_text('url')},'^https?://([^/]+[.])?govinfo[.]gov/') AND {_bool('publisher_requested')} AND {_int('http_status')}=200 AND {_bool('complete')} AND {_text('outcome')}='stored' AND {_text('retrieved_at')} IS NOT NULL"),
    'b7_owner_recoveries': (['recoveries','recovery.kind','recovery.imported_at'], 'added',
        f"{_text('stage')}='raw-recoveries-owner-32c13ffa' AND {_text('decision_id')} IS NOT NULL AND {_text('kind')}='requested_content_in_official_hearing' AND {_text('source_time_basis')}='earliest_matching_fetch'"),
}


def cause_steps(*, f0=False):
    branches = []
    for cause, (fields, direction, predicate) in CAUSES.items():
        scope = ','.join("'" + name + "'" for name in fields)
        branches.append(f"""SELECT DISTINCT difference_id,'{cause}' AS cause,evidence_ref
            FROM observed_differences WHERE field IN ({scope}) AND direction='{direction}'
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
        dict(name='aligned_pairs',sql='''SELECT old_doc,new_doc FROM exact_pairs UNION
            SELECT o.doc,n.doc FROM old_anchors o JOIN new_anchors n ON o.anchor=n.anchor
            WHERE NOT EXISTS(SELECT 1 FROM exact_pairs p WHERE p.old_doc=o.doc)
               OR NOT EXISTS(SELECT 1 FROM exact_pairs p WHERE p.new_doc=n.doc)''',materialize=True),
    ]


def decision_ready(*, unclassified, derived_only, invalid_ids, missing_evidence, invalid_records=0):
    return not any((unclassified, derived_only, invalid_ids, missing_evidence, invalid_records))


def id_inputs(alias):
    return f"""CASE WHEN coalesce(array_length({alias}.body_keys),0)>0
        THEN json_array('bodies',array_sort(array_distinct({alias}.body_keys)))
        ELSE json_array('sources',array_sort(array_distinct({alias}.source_ids))) END"""


def comparison_steps(*, f0_release=None):
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
    if f0_release:
        steps += f0_proof_steps(f0_release)
    steps += cause_steps(f0=bool(f0_release))
    steps += [
        dict(name='unexplained',sql='SELECT d.* FROM differences d LEFT ANTI JOIN known_causes c ON d.difference_id=c.difference_id',materialize=True),
        dict(name='classified',sql='''SELECT u.*,r.classification,r.rule_ref,r.note,r.raw_signal FROM unexplained u
            LEFT JOIN difference_records r ON u.difference_id=r.difference_id''',materialize=True),
        dict(name='source_identity_errors',sql="""SELECT side,doc,'source_id' AS identity,source_id AS declared,
            encode(sha256(json_array(body_key,filename,source_url)),'hex') AS computed
            FROM identity_sources WHERE source_id IS DISTINCT FROM encode(sha256(json_array(body_key,filename,source_url)),'hex')""",materialize=True),
        dict(name='document_identity_errors',sql="""SELECT side,doc,'document_id' AS identity,document_id AS declared,
            encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex') AS computed FROM identity_documents
            WHERE document_id IS DISTINCT FROM encode(sha256(CASE WHEN array_length(body_keys)>0 THEN json_array('bodies',array_sort(array_distinct(body_keys)))
            ELSE json_array('sources',array_sort(array_distinct(source_ids))) END),'hex')""",materialize=True),
    ]
    return steps


def compare_relations(inputs, *, engine, work, missing_evidence=0, prelude=(), f0_release=None):
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
    queries = [dict(name='counts',sql='''SELECT (SELECT count(*) FROM differences) AS differences,
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
    reports = run_job(work,engine,inputs=inputs,steps=[*prelude,*comparison_steps(f0_release=f0_release)],outputs=outputs,queries=queries)
    counts=reports['counts'][0]
    ready=decision_ready(**{key:counts[key] for key in ['unclassified','derived_only','invalid_ids','invalid_records']},missing_evidence=missing_evidence)
    result=dict(version=1,status='complete' if ready else 'incomplete',decision_ready=ready,
        counts=dict(counts,missing_evidence=missing_evidence),causes=reports['causes'],examples=reports['examples'],
        identity_examples=reports['identity_examples'],clusters=reports['clusters'])
    (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def compare_descriptor(descriptor, *, engine_config, work):
    loaded=load_descriptor(descriptor)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    parallel=NativeDatasets.from_config(restricted_runtime(engine_config,work/'comparison-runtime',threads=4))
    validate_layout(loaded,engine=parallel,work=work/'layout-validation')
    staging=work/'inputs';staging.mkdir()
    inputs,steps=normalization(loaded,directory=staging)
    kind=loaded['descriptor']['candidate']['kind']
    if kind!='f0':
        raise ValueError('Model cause projections must be bound before model qualification')
    result=compare_relations(inputs,engine=parallel,work=work/'result',prelude=steps,
        f0_release=loaded['manifest']['release_id'])
    result.update(candidate_kind=kind,model_qualified=False,release_id=loaded['manifest']['release_id'],
        oracle=loaded['selector'],descriptor_sha256=loaded['descriptor_sha256'])
    (work/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
