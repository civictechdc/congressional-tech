"""Receipt source types and one native scalar projection; evidence stays in raw."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from congress_api.retention.provenance import field, struct, list_of
from congress_shared.custody import custody_identity


STRINGS = ('source_file','run_id','mode','outcome','family','requested_url','url','_url',
    'final_url','resolved_url','source_url','retrieved_at','captured_at','observed_at',
    'parent_retrieved_at','_retrieved_at','capture_date','error_type')
NUMBERS = ('http_status','status_code')
BOOLS = ('complete',)
SCALARS = {**dict.fromkeys(STRINGS,'str'),**dict.fromkeys(NUMBERS,'int'),**dict.fromkeys(BOOLS,'bool')}
COMPARISON_WITNESSES = dict(source_context_from_final='Boolean',source_retained_record='Boolean',
    source_entry_status='Int64',source_final_status='Int64',
    source_creating_size_absent='Boolean',source_family_basis='Utf8')
DOWNLOAD_HEADERS = [('response_headers','content-disposition'),
                    ('response_headers','Content-Disposition')]
INLINE_PAYLOAD_PATHS = [('detail','systemCode'),('detail','type'),
    ('detail','committeeWebsiteUrl'),('detail','history',0,'officialName'),
    ('detail','reports','count'),('event',),('package_id',),('last_modified',),
    ('observed_at',),('recorded_at',),('rule_version',),('meeting','eventId'),
    ('meeting','congress'),('meeting','date'),('meeting','title'),
    ('meeting','committees',0,'systemCode')]
MODS_DESCRIPTOR_FIELDS = ('package_id','status','url','sha256','bytes','http_status',
    'retrieved_at','etag','http_last_modified')
# Only the recovery leaves consumed by the narrow index are selected in bulk.
RECOVERY = {
    'recovery_original': ('recovery_evidence','original_url'),
    'recovery_imported': ('recovery_evidence','imported_at'),
    'recovery_basis': ('recovery_evidence','match_basis'),
    'recovery_category': ('recovery_evidence','acquisition','prior_access_category'),
    'recovery_url': ('recovery_evidence','acquisition','recovered_url'),
    'recovery_sha': ('recovery_evidence','acquisition','evidence_sha256'),
    'association_original': ('source_associations',0,'original_url'),
    'association_basis': ('source_associations',0,'basis'),
}


def lit(value):
    return "'"+str(value).replace("'","''")+"'"


def get(value,*path,kind='str'):
    expression=f'json_get_{kind}({value}'+(' ,'+','.join(str(p) if isinstance(p,int) else lit(p) for p in path) if path else '')+')'
    return f"nullif({expression},'null')" if kind=='json' else expression



def record_pointer_index(pointer):
    """The first numeric token in the first two canonical pointer components."""
    values=[value for index in (0,1) for value in
        (get(pointer,index,kind='int'),'try_cast('+get(pointer,index)+' AS BIGINT)')]
    return 'coalesce('+','.join(values+['0'])+')'


def obj(fields):
    return 'named_struct('+','.join(lit(k)+','+(f'cast({v} AS VARCHAR)'
        if SCALARS.get(k,'str')=='str' and k!='error_present' else v) for k,v in fields.items())+')'


def counter_file(counter):
    path=Path(counter).resolve()
    if not path.is_file():
        raise ValueError('A validated counter must be a single local file')
    return path


def source_schema():
    scalars={**dict.fromkeys(STRINGS,'Utf8'),**dict.fromkeys(NUMBERS,'Int64'),**dict.fromkeys(BOOLS,'Boolean')}
    return dict(fields=[field(k,v) for k,v in dict(**scalars,
        record=struct(**scalars), captures=list_of(struct(sha256='Utf8')),
        file_references=list_of(struct(sha256='Utf8'))).items()],metadata={})


def projection(raw,paths):
    """A literal, prefix-disjoint C8 bundle and its scalar JSON slots."""
    unique=list(dict.fromkeys(tuple(path) for path in paths))
    expression='json_get_many('+raw+','+lit(json.dumps(unique,separators=(',',':')))+')'
    slots={path:f'array_element({expression},{index+1})' for index,path in enumerate(unique)}
    return slots


def scalar(slot,kind):
    return f'try_cast(json_as_text({slot}) AS BIGINT)' if kind=='int' else get(slot,kind=kind)


def inline_payload_kind(slots):
    """Small content witnesses for three demonstrated object payloads, not body custody."""
    def text(*path):
        return scalar(slots[path],'str')
    def present(*path):
        return "nullif("+text(*path)+",'') IS NOT NULL"
    detail=present('detail','systemCode')+' AND '+present('detail','type')+' AND ('+\
        present('detail','committeeWebsiteUrl')+' OR '+present('detail','history',0,'officialName')+\
        ' OR '+scalar(slots[('detail','reports','count')],'int')+'>=0)'
    audit=text('event')+"='package-outcome' AND "+present('package_id')+' AND '+present('rule_version')
    for name in ('last_modified','observed_at','recorded_at'):
        audit+=' AND try_cast('+text(name)+' AS TIMESTAMP WITH TIME ZONE) IS NOT NULL'
    meeting=' AND '.join([scalar(slots[('meeting','eventId')],'int')+'>0',
        scalar(slots[('meeting','congress')],'int')+'>0',present('meeting','title'),
        present('meeting','committees',0,'systemCode'),
        'try_cast('+text('meeting','date')+' AS TIMESTAMP WITH TIME ZONE) IS NOT NULL'])
    return "CASE WHEN "+detail+" THEN 'committee-detail' WHEN "+audit+\
        " THEN 'package-outcome' WHEN "+meeting+" THEN 'meeting-event' END"


def mods_descriptor_kind(slots,keys):
    """Recognize the qualified descriptor only; its digest is not a captured body."""
    text=lambda name:scalar(slots[(name,)],'str')
    expected='make_array('+','.join(lit(name) for name in sorted(MODS_DESCRIPTOR_FIELDS))+')'
    conditions=[keys+'='+expected,text('status')+"='captured'",
        get(slots[('http_status',)],kind='int')+'=200',get(slots[('bytes',)],kind='int')+'>0',
        "nullif("+text('package_id')+",'') IS NOT NULL",
        'regexp_match('+text('sha256')+",'^[0-9a-f]{64}$') IS NOT NULL",
        text('url')+"=concat('https://www.govinfo.gov/metadata/pkg/',"+text('package_id')+",'/mods.xml')"]
    return 'CASE WHEN '+' AND '.join(conditions)+" THEN 'govinfo-mods' END"


def source_plan(*,counter=None,files=None,receipt_keys=None):
    """Materialize one source projection, retaining list items once before shredding."""
    if counter is not None:
        counter=counter_file(counter)
        schema=pq.read_schema(counter)
        required={'__receipt_key','__receipt_line','__raw_line','__type_conflicts',
                  '__receipt_family','record','captures','file_references'}
        if not required.issubset(schema.names):
            raise ValueError('Counter is not the validated typed/raw receipt reader result')
        inputs=[dict(name='source',kind='parquet',path=str(counter))]
        root_names=set(schema.names)
        record_names=set(schema.field('record').type.names)
        locator='__receipt_key AS receipt_key,__receipt_line AS receipt_line'
        selected=('__receipt_key IN ('+','.join(lit(key) for key in receipt_keys)+')'
                  if receipt_keys else 'false') if receipt_keys is not None else 'true'
    else:
        schema=source_schema()
        inputs=[dict(name='source',kind='json_lines',files=files,schema=schema)]
        root_names={field['name'] for field in schema['fields']}
        record_names=set(SCALARS)
        locator='__source_key AS receipt_key,__source_line AS receipt_line'
        selected='true'
    paths=[prefix+(name,) for prefix in [(),('record',)] for name in SCALARS]
    paths += [prefix+path for prefix in [(),('record',)] for path in RECOVERY.values()]
    paths += [prefix+path for prefix in [(),('record',)] for path in DOWNLOAD_HEADERS]
    paths += [('captures',),('file_references',),('writer','job'),('writer','commit'),('error',),('record','error')]
    paths += [('record',*path) for path in INLINE_PAYLOAD_PATHS]
    paths += [('record',name) for name in MODS_DESCRIPTOR_FIELDS]
    slots=projection('__raw_line',paths)
    def typed(name,kind,record=False):
        path=('record',name) if record else (name,)
        fallback=scalar(slots[path],kind)
        names=record_names if record else root_names
        if name not in names:
            return fallback
        value='get_field(record,'+lit(name)+')' if record else '"'+name+'"'
        if counter is None:
            return f'coalesce({value},{fallback})'
        conflict='array_has(__type_conflicts,'+lit(json.dumps(path,separators=(',',':')))+')'
        return f'CASE WHEN {conflict} THEN {fallback} ELSE {value} END'
    roots={name:typed(name,kind) for name,kind in SCALARS.items()}
    records={name:typed(name,kind,True) for name,kind in SCALARS.items()}
    roots.update(writer_job=scalar(slots[('writer','job')],'str'),
                 writer_commit=scalar(slots[('writer','commit')],'str'))
    roots['h_content_disposition']='CASE WHEN '+roots['writer_job']+' IS NOT NULL AND '+roots['writer_commit']+\
        ' IS NOT NULL THEN coalesce('+','.join(scalar(slots[path],'str') for path in DOWNLOAD_HEADERS)+') END'
    for fields,prefix in ((roots,()),(records,('record',))):
        fields['error_present']=get(slots[prefix+('error',)],kind='json')+' IS NOT NULL'
    for name,path in RECOVERY.items():
        roots[name]=scalar(slots[path],'str')
        records[name]=scalar(slots[('record',)+path],'str')
    records['h_content_disposition']='coalesce('+','.join(
        scalar(slots[('record',)+path],'str') for path in DOWNLOAD_HEADERS)+')'
    records['inline_payload_kind']=inline_payload_kind({path:slots[('record',*path)] for path in INLINE_PAYLOAD_PATHS})
    source_key='__receipt_key' if counter is not None else '__source_key'
    descriptor_keys="CASE WHEN starts_with("+source_key+",'receipts/govinfo/mods/') THEN array_sort(json_object_keys(__raw_line,'record')) END"
    records['descriptor_kind']=mods_descriptor_kind({(name,):slots[('record',name)] for name in MODS_DESCRIPTOR_FIELDS},descriptor_keys)
    # An array conflicts with the typed object record and becomes null. Test
    # its shape without selecting an ordinary object's potentially huge body.
    is_list=("__line_shape='record:array'" if '__line_shape' in root_names else
        "record IS NULL AND json_get_str(__raw_line,'record') IS NULL AND json_length(__raw_line,'record') IS NOT NULL")
    records['line_kind_shape']="CASE WHEN source.record IS NOT NULL THEN 'object' WHEN "+is_list+\
        " AND json_length(__raw_line,'record')=0 THEN 'empty-list' ELSE 'unsupported' END"
    invalid_lists=' OR '.join(
        '('+slots[(name,)]+" IS NOT NULL AND "+slots[(name,)]+"<>'null' AND "+
        get(slots[(name,)],kind='array')+' IS NULL)' for name in ('captures','file_references'))
    sql=f"""SELECT {locator},row_number() OVER () AS source_row_id,{obj(roots)} AS line,{obj(records)} AS record,
        ({invalid_lists}) AS invalid_lists,
        {get(slots[('captures',)],kind='array')} AS caps,
        {get(slots[('file_references',)],kind='array')} AS refs,
        {is_list} AS record_is_list,
        CASE WHEN {is_list} THEN json_get_array(__raw_line,'record') ELSE make_array() END AS record_items
        FROM source WHERE {selected}"""
    sql='SELECT *,array_length(record_items) AS record_count FROM ('+sql+')'
    return dict(inputs=inputs,steps=[dict(name='lines',sql=sql,materialize=True)])


def producer(engine):
    return dict(sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                source_revision=engine.source_revision,binary_sha256=engine.binary_sha256)


def qualification_path(value):
    """Qualification bindings use explicit absolute paths, without traversal."""
    if not isinstance(value,(str,Path)):
        raise ValueError('Source qualification requires an explicit file path')
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Source qualification requires an absolute path without traversal')
    return path


def source_pins(counter=None,files=None,*,qualifications=None):
    """Reuse trusted immutable creation/qualification evidence; never hash source bytes.

    The caller binds a source to an existing authority file. A pathless authority
    relies on that trusted binding and the immutable-artifact protocol, not fresh
    cryptographic verification. Custody checks detect drift after admission.
    """
    if counter is not None:
        counter_file(counter)  # Preserve the single-file counter admission guard.
        paths=[Path(counter)]
    else:
        paths=[Path(item['path']) for item in files or []]
        if qualifications is None:
            qualifications={item['path']:item['qualification'] for item in files or []
                            if 'qualification' in item}
    identities={}
    for path in paths:
        identity=custody_identity(path)  # Check symlinks before resolving the path.
        identities[path.resolve()]=identity
    if not identities:
        raise ValueError('Receipt ingest requires qualified source files')
    bindings={}
    for source,authority in (qualifications or {}).items():
        source=qualification_path(source).resolve()
        if source in bindings:
            raise ValueError('Duplicate source qualification binding')
        bindings[source]=qualification_path(authority)
    if set(bindings)!=set(identities):
        raise ValueError('Source qualifications must exactly bind every selected source file')
    pins=[]
    for path,identity in sorted(identities.items()):
        authority=bindings[path]
        before=custody_identity(authority)
        if before[2]>1024*1024:
            raise ValueError('Source qualification exceeds the metadata size limit')
        with authority.open('rb') as stream:
            data=stream.read(1024*1024+1)
        if len(data)>1024*1024 or custody_identity(authority)!=before:
            raise ValueError('Source qualification changed during admission')
        facts=json.loads(data)
        if (not isinstance(facts,dict) or not isinstance(facts.get('sha256'),str)
                or re.fullmatch('[0-9a-fA-F]{64}',facts['sha256']) is None
                or type(facts.get('size')) is not int or facts['size']<0
                or ('rows' in facts and (type(facts['rows']) is not int or facts['rows']<0))):
            raise ValueError('Invalid source qualification SHA-256, size or rows')
        if 'path' in facts and qualification_path(facts['path']).resolve()!=path:
            raise ValueError('Source qualification path does not match its binding')
        if facts['size']!=identity[2]:
            raise ValueError('Source qualification size does not match its source')
        qualification=dict(path=str(authority.resolve()),sha256=sha256(data).hexdigest(),
            size=len(data),kind='reused_qualification',identity=before)
        qualification.update({key:facts[key] for key in ('rows','note','producer') if key in facts})
        pins.append(dict(path=str(path),sha256=facts['sha256'],size=facts['size'],
                         identity=identity,qualification=qualification))
    recheck_source_pins(pins)
    return pins


def recheck_source_pins(pins):
    """Refuse source or authority drift without opening either source payload."""
    for pin in pins:
        for item in (pin,pin['qualification']):
            if custody_identity(item['path'])!=tuple(item['identity']):
                raise ValueError('Qualified source or authority changed while staging: '+item['path'])
