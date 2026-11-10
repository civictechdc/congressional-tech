"""Application-owned policy inputs and native SQL for raw-derived releases."""
import hashlib
import json
import re
from pathlib import Path

from congress_api.lake.receipt_metadata import document_status_sql,empty_body_sql
from congress_api.retention.provenance import json_input,list_of,struct
from viewer_publication.archive_format import NULL_MEETING_DOCUMENT_REFERENCES, SPICY_PRODUCER_FAMILIES

ROOT=Path(__file__).parents[4]
REGISTRIES={
    'file_shapes':dict(id='Utf8',pattern='Utf8'),
    'page_signals':dict(id='Utf8',kind='Utf8',pattern='Utf8',number='Int64'),
    'formats':dict(id='Utf8',kind='Utf8',value='Utf8',rank='Int32'),
    'publisher_kinds':dict(id='Utf8',basis='Utf8',pattern='Utf8',document_kind='Utf8'),
    'display_facts':dict(id='Utf8',field='Utf8',label='Utf8'),
    'committee_codes':dict(id='Utf8',code='Utf8',system_code='Utf8',chamber='Utf8'),
    'recheck_intervals':dict(id='Utf8',family='Utf8',min_age_days='Int64',max_age_days='Int64',interval_seconds='Int64'),
    'url_rules':dict(id='Utf8',kind='Utf8',host_pattern='Utf8',pattern='Utf8',replacement='Utf8',decoder='Utf8'),
    'archive_layouts':dict(id='Utf8',container_pattern='Utf8',member_pattern='Utf8',published_prefix='Utf8'),
    'filename_parameters':dict(priority='Int64',parameter='Utf8'),
    'import_runs':dict(run_id='Utf8',date='Utf8'),
    'credential_parameters':dict(parameter='Utf8'),
    'recovery_kinds':dict(category='Utf8',match_basis='Utf8',kind='Utf8',import_category='Utf8'),
    'capture_scope':dict(family='Utf8',patterns=list_of('Utf8'),exclusions=list_of('Utf8')),
    'meeting_sources':dict(id='Utf8',kind='Utf8',source='Utf8',priority='Int64'),
    'appearance_observation_exclusions':dict(source='Utf8',receipt_key='Utf8',receipt_line='Int64',capture_index='Int64',run_id='Utf8',reason='Utf8',evidence='Utf8'),
    'meeting_status_conflicts':dict(event_id='Int64',held_date='Utf8',publisher_status='Utf8',evidence='Utf8'),
    'bill_package_evidence':dict(id='Utf8',package_id='Utf8',pdf_sha='Utf8',source_urls=list_of('Utf8'),
        package_disposition='Utf8',rejected_package_ids=list_of('Utf8'),excluded_measure_keys=list_of('Utf8'),
        supported_measure_keys=list_of('Utf8'),evidence='Utf8'),
    'saved_name_decisions':dict(body_sha='Utf8',decision='Utf8',official_name='Utf8',committee_name='Utf8',evidence='Utf8'),
    'recording_sources':dict(id='Utf8',kind='Utf8',provider='Utf8',pattern='Utf8',key_template='Utf8',format='Utf8',default_language='Utf8',default_production='Utf8'),
}

MEETING_RECORD_FIELDS=dict(
    record_sha_hex='Utf8',
    parser_version='Utf8',
    status='Utf8',
    error_type='Utf8',
    source='Utf8',
    meetings=list_of(struct(
        event_id='Utf8',
        chamber='Utf8',
        congress='Int32',
        session='Int32',
        updated='Utf8',
        title='Utf8',
        meeting_date='Utf8',
        meeting_type='Utf8',
        status='Utf8',
        sittings=list_of(struct(start='Utf8',end='Utf8',room='Utf8',building='Utf8',address='Utf8')),
        committees=list_of(struct(system_code='Utf8',name='Utf8',chamber='Utf8',role='Utf8')),
        subject_keys=list_of('Utf8'),
        transcript_jackets=list_of('Utf8'),
        videos=list_of(struct(video_key='Utf8',url='Utf8',title='Utf8')),
        document_urls=list_of('Utf8'),
        document_references=list_of(struct(collection='Utf8',ordinal='Int32',url='Utf8',role='Utf8',
            format='Utf8',description='Utf8',name='Utf8')),
        collection_states=struct(
            sittings='Utf8',
            committees='Utf8',
            subject_keys='Utf8',
            transcript_jackets='Utf8',
            videos='Utf8',
            document_urls='Utf8',
        ),
        access='Utf8',
        access_basis='Utf8',
        not_held='Boolean',
        title_key='Utf8',
        reschedule_candidate='Boolean',
    )),
)

APPEARANCE_RECORD_FIELDS=dict(
    record_sha_hex='Utf8',
    parser_version='Utf8',
    status='Utf8',
    error_type='Utf8',
    source='Utf8',
    event_id='Int64',
    package_id='Utf8',
    declared_base='Utf8',
    collection_state='Utf8',
    context_url='Utf8',
    appearances=list_of(struct(
        source_locator='Utf8',
        name_key='Utf8',
        name='Utf8',
        honorific='Utf8',
        given='Utf8',
        middle='Utf8',
        family='Utf8',
        suffix='Utf8',
        position='Utf8',
        organization='Utf8',
        on_behalf_of='Utf8',
        location='Utf8',
        panel='Utf8',
        panel_order='Int32',
        display_order='Int32',
        witness_type='Utf8',
        testified='Boolean',
        bioguide_id='Utf8',
        document_links=list_of('Utf8'),
    )),
    held_dates=list_of('Utf8'),
    title='Utf8',
    created='Utf8',
)

RECORDING_DECISION_FIELDS=dict(id='Utf8',subject_kind='Utf8',subject_id='Utf8',verdict='Utf8',video_refs=list_of('Utf8'),
    note='Utf8',disputed_by='Utf8',decided_at='Utf8',supersedes='Utf8')

# Dependency order: matches read videos, coverage reads matches.
EXPLORER_TABLES=[
    ('videos','entity-videos',['video_key'],['handle','system_code']),
    ('channels','entity-channels',['handle'],['system_code','role','mapping_basis']),
    ('recording_matches','entity-recording-matches',['match_id'],['subject_kind','basis','decision','recording_scope','status',
        'meeting_links.list.item.basis','meeting_links.list.item.scope']),
    ('committee_records','entity-committee-records',['record_key'],['kind','sponsor_bioguide','amendment_type']),
    ('meeting_coverage','entity-meeting-coverage',['event_id','aspect'],['aspect','state','basis','reason']),
]

SPICY_SCHEMAS={
    'spicy_committees':dict(
        system_code='Utf8',name='Utf8',chamber='Utf8',committee_type='Utf8',
        parent_system_code='Utf8',website_url='Utf8',is_current='Boolean',
        history=list_of(struct(officialName='Utf8',startDate='Utf8',endDate='Utf8')),
    ),
    'spicy_members':dict(
        bioguide_id='Utf8',name_first='Utf8',name_last='Utf8',
        lis_id='Utf8',opensecrets_id='Utf8',govtrack_id='Utf8',
        icpsr_id='Utf8',wikidata_id='Utf8',fec_ids=list_of('Utf8'),
    ),
    'spicy_member_terms':dict(
        bioguide_id='Utf8',term_type='Utf8',term_state='Utf8',
        term_district='Int32',term_party='Utf8',term_start='Utf8',term_end='Utf8',
    ),
    'spicy_committee_assignments':dict(
        congress='Int32',session='Utf8',chamber='Utf8',is_subcommittee='Boolean',
        parent_system_code='Utf8',committee_name='Utf8',system_code='Utf8',
        bioguide_id='Utf8',name_last='Utf8',name_first='Utf8',
        position='Utf8',rank='Int32',party='Utf8',
        # Source labels of the 113th-118th directory seats (ss-ehci); empty on chamber-file rows.
        congress_basis='Utf8',edition_date='Utf8',source_granule='Utf8',source_line='Utf8',
        position_basis='Utf8',printed_entry='Utf8',entry_label='Utf8',
    ),
    'spicy_congress_bills':dict(
        bill_id='Utf8',title='Utf8',short_title='Utf8',
        sponsor_bioguide_id='Utf8',introduced_date='Utf8',
        latest_action_date='Utf8',latest_action_text='Utf8',
        stage='Utf8',policy_area='Utf8',subjects=list_of('Utf8'),update_date='Utf8',update_date_including_text='Utf8',
        public_law_number='Utf8',cosponsor_count='Int32',
        related_bills=list_of(struct(
            bill_type='Utf8',congress='Utf8',latest_action_date='Utf8',
            latest_action_text='Utf8',number='Utf8',
            relationship_details=list_of(struct(identifiedBy='Utf8',type='Utf8')),
            title='Utf8',
        )),
    ),
    'spicy_bill_committees':dict(
        bill_id='Utf8',system_code='Utf8',
    ),
    'spicy_bill_committee_activities':dict(
        bill_id='Utf8',system_code='Utf8',activity_name='Utf8',
        activity_date='Utf8',occurrence='Int32',
    ),
    'spicy_cbo_cost_estimates':dict(
        bill_id='Utf8',publication_id='Utf8',pub_date='Utf8',description='Utf8',
    ),
    'spicy_amendments':dict(
        amendment_id='Utf8',purpose='Utf8',sponsor_bioguide_id='Utf8',
        latest_action_date='Utf8',latest_action_text='Utf8',
        amended_bill_id='Utf8',amended_amendment_id='Utf8',
    ),
    'spicy_bill_vote_references':dict(
        bill_id='Utf8',congress='Int32',chamber='Utf8',session='Int32',roll_number='Int32',
    ),
    'spicy_roll_call_votes':dict(
        vote_id='Utf8',bill_id='Utf8',congress='Int32',chamber='Utf8',
        session='Int32',roll_number='Int32',vote_day='Utf8',
        question='Utf8',result='Utf8',yea='Int32',nay='Int32',
        documents=list_of(struct(congress='Int32',type='Utf8',number='Utf8')),
    ),
    'spicy_nominations':dict(
        congress='Int32',number='Int32',part_number='Utf8',
        description='Utf8',organization='Utf8',received_date='Utf8',
        latest_action_date='Utf8',latest_action_text='Utf8',update_date='Utf8',
        hearings_json='Utf8',
        committee_activities=list_of(struct(system_code='Utf8',activities=list_of(struct(name='Utf8',date='Utf8')))),
    ),
}


from viewer_publication.legislative_data import ACTION_SCHEMA, BALLOT_SCHEMA, VOTE_EXTRA, detail_exports
SPICY_SCHEMAS['spicy_bill_vote_references'].update(congress='Utf8',session='Utf8',roll_number='Utf8',action_index='Int64',date='Utf8',full_action_name='Utf8')
SPICY_SCHEMAS['spicy_bill_actions']=ACTION_SCHEMA
SPICY_SCHEMAS['spicy_member_votes']=BALLOT_SCHEMA
SPICY_SCHEMAS['spicy_roll_call_votes'].update(VOTE_EXTRA)
SPICY_SCHEMAS['spicy_roll_call_votes'].update(congress='Utf8',session='Utf8',roll_number='Utf8',yea='Int64',nay='Int64')
# Preserve the full source document reference, including its names and titles.
SPICY_SCHEMAS['spicy_roll_call_votes']['documents']=list_of(struct(congress='Int64',name='Utf8',number='Utf8',short_title='Utf8',title='Utf8',type='Utf8'))

CHANNEL_DIRECTORY=Path('packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv')


def channel_directory_rows(root=ROOT):
    """One row per curated handle. The CSV stays the one authority: youtube-fetch depends on its row order."""
    import csv
    rows=[]
    with (Path(root)/CHANNEL_DIRECTORY).open(newline='') as source:
        for row in csv.DictReader(source):
            ids=json.loads(row['channel_ids'] or '{}')
            for role,handles in (('primary',[row['handle']]),('secondary',row['secondary'].split(';')),('member',row['member_channels'].split(';'))):
                rows += [dict(handle=handle,channel_id=ids.get(handle),system_code=row['systemCode'],committee_label=row['committee'],role=role)
                    for handle in map(str.strip,handles) if handle]
    return rows


def _hex_sha(value,index):
    if isinstance(value,(bytes,bytearray)):
        return bytes(value).hex()
    if isinstance(value,str) and value:
        return value.lower()
    return hashlib.sha256(f'record:{index}'.encode()).hexdigest()


def _default_entity_version(selected_versions,source,fallback):
    if isinstance(selected_versions,str) and selected_versions:
        return selected_versions
    if isinstance(selected_versions,dict) and source in selected_versions and isinstance(selected_versions[source],str) and selected_versions[source]:
        return selected_versions[source]
    return fallback


def _normalize_meeting_rows(rows,selected_versions=None):
    normalized=[]
    for idx,raw in enumerate(rows):
        row=dict(raw)
        record_sha_hex=row.get('record_sha_hex') or _hex_sha(row.get('record_sha'),idx)
        source=row.get('source')
        meetings=[]
        for m in (row.get('meetings') or ()):
            item=dict(m)
            if item.get('event_id') is not None:
                item['event_id']=str(item['event_id'])
            sittings=[]
            for s in (item.get('sittings') or ()):
                sd=dict(s)
                if sd.get('room') is None and sd.get('place') is not None:
                    sd['room']=sd['place']
                sittings.append({k:sd.get(k) for k in ('start','end','room','building','address')})
            item['sittings']=sittings
            item['committees']=[{k:dict(c).get(k) for k in ('system_code','name','chamber','role')} for c in (item.get('committees') or ())]
            item['subject_keys']=list(item.get('subject_keys') or [])
            item['transcript_jackets']=[str(x) for x in (item.get('transcript_jackets') or [])]
            videos=[]
            for v in (item.get('videos') or ()):
                vd=dict(v)
                videos.append(dict(
                    video_key=vd.get('video_key'),
                    url=vd.get('url'),
                    title=vd.get('title') if vd.get('title') is not None else vd.get('name'),
                ))
            item['videos']=videos
            item['document_urls']=[str(u) for u in (item.get('document_urls') or []) if u is not None]
            cs=dict(item.get('collection_states') or {})
            item['collection_states']={
                k:cs.get(k)
                for k in ('sittings','committees','subject_keys','transcript_jackets','videos','document_urls')
            }
            meetings.append(item)
        normalized.append(dict(
            record_sha_hex=record_sha_hex,
            parser_version=row.get('parser_version') or _default_entity_version(selected_versions,source,'meeting-v1'),
            status=row.get('status','completed'),
            error_type=row.get('error_type'),
            source=source,
            meetings=meetings,
        ))
    return normalized


def _normalize_appearance_rows(rows,selected_versions=None):
    normalized=[]
    for idx,raw in enumerate(rows):
        row=dict(raw)
        record_sha_hex=row.get('record_sha_hex') or _hex_sha(row.get('record_sha'),idx)
        source=row.get('source')
        top_event_id=row.get('event_id')
        top_package_id=row.get('package_id')
        top_context_url=row.get('context_url') or row.get('page_url') or row.get('source_url')
        appearances=[]
        for idx_a,a in enumerate(row.get('appearances') or (),start=1):
            item=dict(a)
            if top_event_id is None and item.get('event_id') is not None:
                top_event_id=item['event_id']
            if top_package_id is None and item.get('package_id') is not None:
                top_package_id=item['package_id']
            if top_context_url is None and item.get('page_url') is not None:
                top_context_url=item['page_url']
            if item.get('panel') is not None:
                item['panel']=str(item['panel'])
            raw_links=item.get('document_links')
            if raw_links is None:
                raw_links=item.get('document_urls') or []
            doc_links=list(raw_links)
            for extra_urls in ('statement_urls','bio_urls','truth_urls','answer_urls','supplement_urls'):
                if item.get(extra_urls):
                    doc_links.extend(item[extra_urls])
            item['source_locator']=str(item.get('source_locator') or f"{source or 'appearance'}:witness[{idx_a}]")
            item['document_links']=[str(u) for u in doc_links if u is not None]
            appearances.append(item)
        parsed_event_id=None
        if top_event_id is not None and str(top_event_id).strip()!='':
            parsed_event_id=int(top_event_id)
        normalized.append(dict(
            record_sha_hex=record_sha_hex,
            parser_version=row.get('parser_version') or _default_entity_version(selected_versions,source,'appearance-v1'),
            status=row.get('status','completed'),
            error_type=row.get('error_type'),
            source=source,
            event_id=parsed_event_id,
            package_id=str(top_package_id) if top_package_id is not None else None,
            declared_base=str(row['declared_base']) if row.get('declared_base') is not None else None,
            collection_state=str(row['collection_state']) if row.get('collection_state') is not None else None,
            context_url=str(top_context_url) if top_context_url is not None else None,
            appearances=appearances,
            held_dates=[str(d) for d in row.get('held_dates') or ()],
            title=str(row['title']) if row.get('title') is not None else None,
            created=str(row['created']) if row.get('created') is not None else None,
        ))
    return normalized


# Every family an entity file cites; archive_format owns which file reads which family.
SPICY_FAMILIES=frozenset().union(*SPICY_PRODUCER_FAMILIES.values())
SPICY_DIGEST=re.compile('[0-9a-f]{64}')


def spicy_generations(value):
    """Exactly one stated generation digest per family the entity files read; none is ever derived here."""
    if not isinstance(value,dict) or set(value)!=SPICY_FAMILIES or any(
            not isinstance(digest,str) or SPICY_DIGEST.fullmatch(digest) is None for digest in value.values()):
        raise ValueError('spicy-regs input must state a generation digest for each of '+', '.join(sorted(SPICY_FAMILIES)))
    return dict(sorted(value.items()))


def _normalize_related_bill_row(raw):
    item=dict(raw)
    if item.get('bill_id') and not (item.get('congress') and item.get('bill_type') and item.get('number')):
        parts=str(item['bill_id']).strip().split('-',2)
        if len(parts)==3:
            item.setdefault('congress',parts[0])
            item.setdefault('bill_type',parts[1])
            item.setdefault('number',parts[2])
    if 'relationship_details' not in item:
        item['relationship_details']=[
            dict(identifiedBy=None,type=str(t))
            for t in (item.get('relationship_types') or ()) if t is not None
        ]
    return {
        k:(list(item.get('relationship_details') or []) if k=='relationship_details' else item.get(k))
        for k in ('bill_type','congress','latest_action_date','latest_action_text','number','relationship_details','title')
    }


def _nomination_activities(raw):
    """Decode the pinned committee groups without changing their order or dates."""
    try:
        groups=json.loads(raw) if isinstance(raw,str) else raw
    except ValueError:
        return None
    if not isinstance(groups,list):
        return None

    def supplied_text(value):
        return value if isinstance(value,str) else None

    def group(item):
        if not isinstance(item,dict):
            return dict(system_code=supplied_text(item),activities=None)
        code=item.get('systemCode',item.get('system_code'))
        activities=item.get('activities')
        return dict(system_code=supplied_text(code),activities=[
            dict(name=supplied_text(a.get('name')),date=supplied_text(a.get('date')))
            if isinstance(a,dict) else dict(name=None,date=None)
            for a in activities
        ] if isinstance(activities,list) else None)

    return [group(item) for item in groups]


def _nomination_input(directory, name, value, schema):
    if isinstance(value,list):
        source_rows=iter(value)
    elif isinstance(value,dict) and value.get('kind')=='parquet' and isinstance(value.get('path'),str):
        import pyarrow.parquet as pq
        source=pq.ParquetFile(value['path'])
        columns=[k for k in (*schema,'committees_json') if k in source.schema_arrow.names]
        source_rows=(row for batch in source.iter_batches(columns=columns) for row in batch.to_pylist())
    else:
        raise ValueError('Unsupported spicy-regs table input: '+name)

    def records():
        for item in source_rows:
            row={k:item.get(k) for k in schema}
            for field in ('congress','number'):
                raw=row[field]
                row[field]=int(raw) if raw is not None else None
            row['committee_activities']=_nomination_activities(item.get('committees_json'))
            yield row

    return json_input(directory,name,records(),**schema)


def _prepare_spicy_inputs(scratch,spicy_regs,include_entities):
    """Stage the spicy-regs tables; the returned digests are exactly the generations the input states.

    Without spicy-regs input only a release without entity files may proceed; its spicy
    tables are empty and it names no generation (DM8: absent is unavailable, never empty).
    """
    spicy_dir=scratch/'spicy'
    spicy_dir.mkdir(parents=True,exist_ok=True)
    if spicy_regs is None:
        if include_entities:raise ValueError('Entity files require pinned spicy-regs generations')
        return [json_input(spicy_dir,name,[],**schema) for name,schema in SPICY_SCHEMAS.items()],None
    if not isinstance(spicy_regs,dict) or set(spicy_regs)!={'generations','tables'}:
        raise ValueError('spicy-regs input requires exactly its generations and tables')
    generations=spicy_generations(spicy_regs['generations'])
    tables=spicy_regs['tables']
    if not isinstance(tables,dict) or set(tables)!=set(SPICY_SCHEMAS):
        raise ValueError('spicy-regs input must state every table: '+', '.join(sorted(SPICY_SCHEMAS)))
    inputs=[]
    for name,schema in SPICY_SCHEMAS.items():
        value=tables[name]
        if name=='spicy_nominations':
            inputs.append(_nomination_input(spicy_dir,name,value,schema))
        elif isinstance(value,list):
            rows=[]
            for r in value:
                row={k:(r.get(k) if r.get(k) is not None or not (isinstance(kind,dict) and 'List' in kind) else [])
                     for k,kind in schema.items()}
                if name in ('spicy_roll_call_votes','spicy_bill_vote_references'):
                    for field in ('congress','session','roll_number'):
                        if row[field] is not None: row[field]=str(row[field])
                if name=='spicy_congress_bills':
                    row['related_bills']=[_normalize_related_bill_row(rb) for rb in (row.get('related_bills') or ()) if isinstance(rb,dict)]
                rows.append(row)
            inputs.append(json_input(spicy_dir,name,rows,**schema))
        elif isinstance(value,dict) and value.get('kind')=='parquet' and isinstance(value.get('path'),str):
            inputs.append(dict(name=name,kind='parquet',path=value['path']))
        else:
            raise ValueError('Unsupported spicy-regs table input: '+name)
    return inputs,generations


def registry_inputs(directory,*,root=ROOT):
    """Serialize policy records only; native SQL performs every policy join."""
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False)
    inputs=[]
    for name,fields in REGISTRIES.items():
        path=Path(root)/'model/registries'/(name.replace('_','-')+'.json')
        value=json.loads(path.read_text())
        if name=='capture_scope':
            if not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1:
                raise ValueError('Unsupported capture scope registry')
            value=value.get('entries')
        if not isinstance(value,list) or any(not isinstance(row,dict) for row in value):
            raise ValueError('Registry must contain records: '+name)
        REVIEWED_REGISTRIES.get(name,lambda rows:None)(value)
        inputs.append(json_input(directory,name,value,**fields))
    return inputs


def _refuse_ambiguous_reviews(rows,label,sha_field,key,invalid):
    """Refuse ambiguous reviewed decisions before native policy selection: one row per lowercase sha256 body,
    each with evidence and valid by its registry's own rule."""
    bodies=set()
    for row in rows:
        sha=row.get(sha_field)
        if (not isinstance(sha,str) or re.fullmatch('[0-9a-f]{64}',sha) is None or sha in bodies
                or not row.get('evidence') or invalid(row)):
            raise ValueError(f'Invalid or duplicate reviewed {label}: '+str(row.get(key)))
        bodies.add(sha)


def _validate_bill_evidence(rows):
    ids=set()
    def invalid(row):
        disposition=row.get('package_disposition')
        bad=(not row.get('id') or row['id'] in ids or not row.get('source_urls')
             or disposition not in ('support','withhold')
             or (disposition=='support') != bool(row.get('package_id'))
             or any(not isinstance(row.get(field),list) or any(not isinstance(v,str) or not v for v in row[field])
                    for field in ('source_urls','rejected_package_ids','excluded_measure_keys','supported_measure_keys'))
             or bool(set(row['excluded_measure_keys']) & set(row['supported_measure_keys'])))
        ids.add(row.get('id'))
        return bad
    _refuse_ambiguous_reviews(rows,'bill evidence','pdf_sha','id',invalid)


def _validate_saved_name_decisions(rows):
    """A mistyped decision would act as undecided (saved-name-standing.sql), and a decision is met only by a
    name the review read: each side records one name or a ' | ' list of names."""
    names=lambda value:isinstance(value,str) and all(name and name.strip()==name and '|' not in name for name in value.split(' | '))
    _refuse_ambiguous_reviews(rows,'name decision','body_sha','body_sha',lambda row:row.get('decision') not in
        ('official','committee','undecided','neither') or not names(row.get('official_name')) or not names(row.get('committee_name')))


REVIEWED_REGISTRIES={'bill_package_evidence':_validate_bill_evidence,'saved_name_decisions':_validate_saved_name_decisions}


def grouping_steps(*,node_limit=10_000_000,root=ROOT,review_edges=False,recovered_copies=False):
    """Join narrow source/body memberships through the one native graph step.

    Inputs are source_files, source_endpoints (with the shared normalized
    endpoint_key), source_directories, publisher_links, and body_fingerprints;
    body_review_edges and recovered_copy_links when those are asked for.
    """
    steps=[dict(name='fingerprints',sql='SELECT body_sha,max(fingerprint) AS fingerprint FROM body_fingerprints GROUP BY body_sha',materialize=True)]
    for name in ['endpoint-bodies','fingerprint-candidates','ambiguous-endpoints','edition-bodies',
                 'rendition-members','valid-rendition-members','source-edges']:
        steps.append(dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True))
    if review_edges:
        steps[-1]['sql']+=' UNION SELECT left_node,right_node FROM body_review_edges'
    steps.append(dict(name='source_components',components=dict(sql='SELECT left_node,right_node FROM source_edges',
        left='left_node',right='right_node',node_limit=node_limit)))
    labels="SELECT f.source_id,c.component FROM source_files f JOIN source_components c ON c.node='s:'||f.source_id"
    if not recovered_copies:
        return steps+[dict(name='source_labels',sql=labels,materialize=True)]
    # DM 7.5: a recovered copy's original link, a bodiless singleton, moves into the one document
    # that holds its body as a real file. Never an edge: a link copying bodies of two documents
    # would bridge them (an edition never joins another), so such a link keeps its own document.
    return steps+[dict(name='graph_labels',sql=labels,materialize=True),
        dict(name='recovered_copy_members',sql="""SELECT r.source_id,min(g.component) AS component
            FROM (SELECT DISTINCT source_id,body_sha FROM recovered_copy_links) r
            JOIN source_files s ON s.body_sha=r.body_sha AND s.is_real_file JOIN graph_labels g ON g.source_id=s.source_id
            GROUP BY r.source_id HAVING min(g.component)=max(g.component)""",materialize=True),
        dict(name='source_labels',sql="""SELECT g.source_id,coalesce(m.component,g.component) AS component
            FROM recovered_copy_members m RIGHT JOIN graph_labels g ON m.source_id=g.source_id""",materialize=True)]


def source_steps(*,root=ROOT):
    """Derive source grain and addresses from classified fetches and originals."""
    steps=[dict(name='filename_captures',sql='SELECT * FROM capture_evidence')]
    for name,file in [('filename_inputs','filename-inputs'),('effective_filenames','effective-filenames'),
                      ('capture_source_names','capture-source-names'),('source_url_inputs','source-url-inputs')]:
        steps.append(dict(name=name,sql=(Path(root)/'model/sql'/(file+'.sql')).read_text(),materialize=True))
    # Reuse the maintained URL policy before references acquire a source ID.
    normalize=(Path(root)/'model/sql/url-normalized.sql').read_text().replace('url_inputs','source_url_inputs')
    keys=(Path(root)/'model/sql/url-keys.sql').read_text().replace('url_inputs','source_url_inputs').replace('url_normalized','source_url_normalized')
    steps += [dict(name='source_url_normalized',sql=normalize,materialize=True),
              dict(name='source_url_keys',sql=keys,materialize=True)]
    for name in ('source-reference-targets','source-body-urls','capture-sources','capture-source-contexts','source-files','source-addresses','source-directories'):
        step=dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True)
        steps.append(step)
    steps.append(dict(name='good_fetch_contexts',sql="SELECT receipt_key,receipt_line,capture_index,sha256,context_url,member_path FROM good_fetches",materialize=True))
    return steps


def link_steps(*,root=ROOT):
    """Resolve each literal href once per body/address context, retaining attribution."""
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True)
        for name in ['link-contexts','link-literals','link-parts','link-targets','link-errors','resolved-links']]


def evidence_steps(*,root=ROOT):
    """Join pinned parser facts and physical evidence before source/link expansion."""
    from congress_api.lake.readings import writer_admission_step
    names=['pinned-readings','sniff-observations','sniff-conflicts','sniff-facts','page-facts','verification-conflicts','storage-verifications','copy-verifications','body-evidence','capture-evidence',
        'good-archive-containers','good-fetches','good-fetch-keys','capture-locators','body-signals','locator-signals','placeholders','archive-bodies','segment-captures','record-roles',
        'page-contexts','link-inputs']
    # good_fetches is a filter over retained capture_evidence; a second copy costs 1.3 GB of scratch.
    steps=[writer_admission_step(root=root)]+[dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=name!='good-fetches')
        for name in names]
    # A good fetch is a document response: 2xx other than 202 with a non-empty body. Counted
    # once beside good_fetches so the late invariant report does not keep it alive.
    steps.insert(names.index('good-fetches')+2,dict(name='non_document_good_fetches',materialize=True,
        sql=f'''SELECT count(*) AS n FROM good_fetches WHERE (sha256 IS NOT NULL
            AND {empty_body_sql("encode(sha256,'hex')",'bytes')}) OR NOT {document_status_sql('http_status')}'''))
    return steps


# Why a listed document publishes with a blank filename (ct-yf1c), one row per blank document.
# Its captures are read through the candidate set of blank bodies only. A body that any capture
# names (by URL, requested URL, context address or disposition: capture_sources.filename) has no
# reason; otherwise the published address decides: none, a query URL whose parameters name no file
# (EPW/SBC Files.Serve with no final URL), or a bare host. A NULL reason refuses the release.
BLANK_FILENAMES_SQL="""WITH blank AS (
 SELECT doc_key,body_hex,source_url FROM ordered WHERE filename=''
), seen AS (
 SELECT b.doc_key,bool_or(coalesce(c.filename,'')<>'') AS named,
  min(coalesce(c.context_url,c.url)) AS address,
  bool_and(strpos(coalesce(c.context_url,c.url,''),'?')>0) AS all_queries
 FROM blank b JOIN capture_sources c ON c.body_sha=b.body_hex GROUP BY b.doc_key
)
SELECT b.doc_key,CASE WHEN coalesce(s.named,false) THEN NULL
 WHEN coalesce(s.address,b.source_url) IS NULL OR trim(coalesce(s.address,b.source_url))='' THEN 'no_address'
 WHEN coalesce(s.all_queries,strpos(b.source_url,'?')>0) THEN 'query_names_no_file'
 WHEN regexp_like(coalesce(s.address,b.source_url),'^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]*/*(#.*)?$') THEN 'host_only' END AS reason
FROM blank b LEFT JOIN seen s ON s.doc_key=b.doc_key"""


# A title that is only format, size and download words, checked apart from the page-signals
# link_word registry that the title rule uses: delete a small vocabulary and every non-letter, and
# nothing may remain. "PDF (48.1 MB)" and "Download XML (6KB)" are generic; "Overview" is not.
GENERIC_TITLE_SQL="""(o.title IS NOT NULL AND regexp_like(o.title,'[A-Za-z]') AND regexp_replace(lower(o.title),
 '(download|view|click|here|link|pdf|zip|xml|html?|docx?|txt|json|csv|xlsx?|pptx?|kb|mb|gb|bytes?)|[^a-z]','','g')='')"""

# Listed documents whose title is a link word by the page-signals registry (the rule titles use)
# or by GENERIC_TITLE_SQL (an independent small vocabulary): either one refuses the release.
# The 64-character bound is the rule's (source-annotations-pages.sql): a longer page title that
# starts like a link word is a real title ("Click Here: Accessible Federal Technolog… | Senate
# Committee On Aging", a 2022 hearing).
GENERIC_TITLES_SQL=f"""SELECT DISTINCT o.doc_key,o.title FROM ordered o
 LEFT JOIN (SELECT pattern FROM page_signals WHERE kind='link_word') g
  ON length(o.title)<=64 AND regexp_like(regexp_replace(trim(o.title),'\\s+',' ','g'),g.pattern)
 WHERE g.pattern IS NOT NULL OR {GENERIC_TITLE_SQL}"""

# ct-m878, refusing: no address a landing-URL rule matches is a published document's saved address
# (judged on the published rows by the registry, apart from the role step); every landing page
# that names a saved file is an unsaved address of the document that took it; and no landing-URL
# address the fold never admitted (a role other than wrapper, no name, a last segment that is no
# GovInfo ID) is lost: the last count starts from the members, not landing_pages, so it sees what the
# rule left out (review finding 3). Its lookup keys come from the same rows through lookup_extra. A
# page naming no file is metadata unplaced_landing_pages.
LANDING_PAGE_INVARIANTS=dict(name='landing_page_invariants',sql="""SELECT
 (SELECT count(*) FROM (SELECT pattern FROM page_signals WHERE kind='landing_url') r
  JOIN source_rows s ON regexp_like(s.url,r.pattern) WHERE s.is_saved) AS saved_landing_addresses,
 (SELECT count(*) FROM (
  SELECT DISTINCT d.document_id,c.context_url AS url FROM landing_pages l
  JOIN capture_source_contexts c ON c.source_id=l.source_id JOIN document_identities d ON d.component=l.component
  WHERE c.outcome NOT IN ('reference','saved-record') AND c.context_url IS NOT NULL) w
  LEFT ANTI JOIN (SELECT doc_key,url FROM source_rows WHERE member_path IS NULL AND NOT is_saved) h
  ON h.doc_key=w.document_id AND h.url=w.url) AS unaddressed_landing_pages,
 (SELECT count(*) FROM (SELECT DISTINCT m.source_url AS url FROM (SELECT pattern FROM page_signals WHERE kind='landing_url') r
  JOIN document_members m ON regexp_like(m.source_url,r.pattern) LEFT ANTI JOIN landing_pages l ON l.source_id=m.source_id) d
  LEFT ANTI JOIN source_rows s ON s.url=d.url) AS lost_landing_addresses""")


# Owner, 2026-11-02 ("don't lose signal"): every recovered-copy link moved into a published document
# (recovered_copy_members) keeps, on that document, its address (sources), its link key (links), its
# lookup address and every recovery row of its URL, and each value its own annotation gives: shown
# by the document, filled into it, or, where the copy differs, kept on the link's annotation, which
# the address row proves is a member. One row per merged link; lost_* flags are signal not found.
# Decision exceptions are needed only by the final loss checks. Joining here
# would repeat that table through all five references to merged.
MERGED_RECOVERY_SQL="""WITH merged AS (
 SELECT m.source_id,dm.source_url,nullif(dm.filename,'') AS filename,a.title,a.congress,a.filename_date,a.package_id,
  a.document_kind,a.document_family,a.committee_keys,a.chambers,a.meeting_keys,a.measure_keys,a.bioguide_ids,a.facts,
  o.list_row,o.filename AS o_filename,o.title AS o_title,o.congress AS o_congress,o.document_date AS o_date,o.package_id AS o_package,
  o.document_kind AS o_kind,o.document_family AS o_family,o.committee_keys AS o_committees,o.chambers AS o_chambers,
  o.meeting_keys AS o_meetings,o.measure_keys AS o_measures,o.bioguide_ids AS o_bioguides,o.facts AS o_facts,
  nullif(s.filename,'') AS c_filename,coalesce(sa.reading_title,sa.listing_title) AS c_title,sa.congress AS c_congress,
  coalesce(sa.filename_date,sa.content_date) AS c_date,sa.package_id AS c_package,sa.document_kind AS c_kind,
  sa.document_family AS c_family,sa.facts AS c_facts,dm.component
 FROM recovered_copy_members m JOIN document_members dm ON dm.source_id=m.source_id
 JOIN source_annotations a ON a.source_id=m.source_id
 JOIN document_identities d ON d.component=dm.component JOIN ordered o ON o.doc_key=d.document_id
 JOIN saved_files s ON s.component=dm.component AND s.saved_rank=1 JOIN source_annotations sa ON sa.source_id=s.source_id
), addressed AS (
 SELECT DISTINCT g.source_id FROM merged g JOIN source_rows r ON r.list_row=g.list_row AND r.url=g.source_url
), keyed AS (
 SELECT DISTINCT g.source_id FROM merged g JOIN links k ON k.list_row=g.list_row
  AND encode(k.link_key,'hex')=substr(encode(sha256('url:'||g.source_url),'hex'),1,16)
), looked_up AS (
 SELECT DISTINCT g.source_id FROM merged g JOIN lookup_sources u ON u.list_row=g.list_row AND u.url=g.source_url
), recovered AS (
 SELECT source_id,count(*) FILTER (WHERE NOT moved) AS unmoved FROM (
  SELECT g.source_id,c.original_url,c.body_sha,bool_or(r.list_row IS NOT NULL) AS moved
  FROM merged g JOIN current_recoveries c ON c.original_url=g.source_url
  LEFT JOIN recovery_rows r ON r.list_row=g.list_row AND r.original_url=c.original_url AND encode(r.body,'hex')=c.body_sha
  GROUP BY g.source_id,c.original_url,c.body_sha) GROUP BY source_id
)
SELECT g.* EXCLUDE(component),bd.id AS bill_decision_id,bd.rejected_package_ids,bd.excluded_measure_keys,
 a.source_id IS NULL AS lost_address,k.source_id IS NULL AS lost_link,u.source_id IS NULL AS lost_lookup,
 coalesce(r.unmoved,1)>0 AS lost_recovery,
 g.filename IS NOT NULL AND coalesce(g.o_filename,'')='' AS lost_filename,
 g.title IS NOT NULL AND g.o_title IS NULL AS lost_title,
 g.congress IS NOT NULL AND g.o_congress IS NULL AS lost_congress,
 g.filename_date IS NOT NULL AND g.o_date IS NULL AS lost_date,
 g.package_id IS NOT NULL AND g.o_package IS NULL
  AND NOT coalesce(array_has(bd.rejected_package_ids,g.package_id),false) AS lost_package,
 coalesce(array_length(g.document_kind),0)>0 AND coalesce(array_length(g.o_kind),0)=0 AS lost_kind,
 coalesce(array_length(g.document_family),0)>0 AND coalesce(array_length(g.o_family),0)=0 AS lost_family,
 coalesce(array_length(g.facts),0)>0 AND coalesce(array_length(g.o_facts),0)=0 AS lost_facts,
 coalesce(array_length(g.committee_keys),0)>0 AND NOT coalesce(array_has_all(g.o_committees,g.committee_keys),false) AS lost_committees,
 coalesce(array_length(g.chambers),0)>0 AND NOT coalesce(array_has_all(g.o_chambers,g.chambers),false) AS lost_chambers,
 coalesce(array_length(g.meeting_keys),0)>0 AND NOT coalesce(array_has_all(g.o_meetings,g.meeting_keys),false) AS lost_meetings,
 coalesce(array_length(g.measure_keys),0)>0 AND NOT coalesce(array_has_all(
  array_concat(g.o_measures,coalesce(bd.excluded_measure_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),
  g.measure_keys),false) AS lost_measures,
 coalesce(array_length(g.bioguide_ids),0)>0 AND NOT coalesce(array_has_all(g.o_bioguides,g.bioguide_ids),false) AS lost_bioguides
FROM document_bill_decisions bd RIGHT JOIN (
 recovered r RIGHT JOIN (looked_up u RIGHT JOIN (keyed k RIGHT JOIN (addressed a RIGHT JOIN merged g
 ON a.source_id=g.source_id) ON k.source_id=g.source_id) ON u.source_id=g.source_id) ON r.source_id=g.source_id
) ON bd.component=g.component"""
LOST_FLAGS=['address','link','lookup','recovery','filename','title','congress','date','package','kind','family','facts',
    'committees','chambers','meetings','measures','bioguides']
# Per field: merged links whose value fills a field the copy itself lacks, and links whose value
# differs from the one shown, which stays on the link's annotation (evidence source_annotations,
# tied to the document by source_members) as the alternate.
_MERGED_FIELDS=[('filename','filename','c_filename','o_filename'),('title','title','c_title','o_title'),
    ('congress','congress','c_congress','o_congress'),('document_date','filename_date','c_date','o_date'),
    ('package_id','package_id','c_package','o_package')]
_MERGED_LISTS=[('document_kind','document_kind','c_kind','o_kind'),('document_family','document_family','c_family','o_family'),
    ('facts','facts','c_facts','o_facts')]
MERGED_RECOVERY_FIELDS=dict(name='merged_recovery_fields',sql='SELECT count(*) AS merged_links,count(DISTINCT list_row) AS merged_documents,'+','.join(
    f"count(*) FILTER (WHERE {own} IS NULL AND {link} IS NOT NULL AND {shown}={link}) AS {name}_filled,"
    f"count(*) FILTER (WHERE {shown} IS NOT NULL AND {link} IS NOT NULL AND {shown}<>{link}) AS {name}_conflicting"
    for name,link,own,shown in _MERGED_FIELDS)+','+','.join(
    f"count(*) FILTER (WHERE coalesce(array_length({own}),0)=0 AND coalesce(array_length({link}),0)>0) AS {name}_filled,"
    f"count(*) FILTER (WHERE coalesce(array_length({shown}),0)>0 AND coalesce(array_length({link}),0)>0 AND {shown}<>{link}) AS {name}_conflicting"
    for name,link,own,shown in _MERGED_LISTS)
    +f' FROM ({MERGED_RECOVERY_SQL}) g')

# Both names (owner, 2026-11-02): compare every completed, nonempty linked value with the effective
# per-field choice. A different value is a triage row with the choice's own name/URL (which can be a
# linked name) and the other name/URL (evidence filename_conflicts.parquet). Fills/conflicts count.
_NAME_FIELDS=[('filename_date','cast(o.filename_date AS VARCHAR)','cast(l.filename_date AS VARCHAR)','filled_date'),
    ('congress','cast(o.congress AS VARCHAR)','cast(l.congress AS VARCHAR)','filled_congress'),
    ('document_kind',"array_to_string(array_sort(o.document_kind),',')","array_to_string(array_sort(l.document_kind),',')",'filled_kind'),
    ('document_family',"array_to_string(array_sort(o.document_family),',')","array_to_string(array_sort(l.document_family),',')",'filled_family'),
    ('committee_code',"array_to_string(array_sort(o.committee_code),',')","array_to_string(array_sort(l.committee_code),',')",'filled_committee')]
# Expand the five comparisons after one joined pass; UNION branches would
# re-plan the same two input scans once per field. Keep every linked occurrence.
FILENAME_CONFLICTS_SQL="""SELECT source_id,comparison['field'] AS field,
 comparison['shown_value'] AS shown_value,comparison['shown_name'] AS shown_name,comparison['shown_url'] AS shown_url,
 comparison['other_value'] AS other_value,other_name,other_url
 FROM (SELECT o.source_id,l.requested_filename AS other_name,l.requested_url AS other_url,
 unnest(make_array(""" + ','.join(
    f"named_struct('field','{name}','shown_value',{shown},'shown_name',o.{name}_name,"
    f"'shown_url',o.{name}_url,'other_value',{other})"
    for name,shown,other,_filled in _NAME_FIELDS) + """)) AS comparison
 FROM source_linked_filename_readings l JOIN source_filename_readings o USING(source_id)) compared
 WHERE nullif(comparison['shown_value'],'') IS NOT NULL
 AND nullif(comparison['other_value'],'') IS NOT NULL
 AND comparison['shown_value']<>comparison['other_value']"""
# A qualified linked date can supersede an ineligible shown alias. Retain that
# shown disagreement too, unless reference association has made the same shown
# pair available to the ordinary linked comparison (capture-sources.sql).
FILENAME_CONFLICTS_SQL += """ UNION ALL
 SELECT o.source_id,'filename_date' AS field,cast(o.filename_date AS VARCHAR) AS shown_value,
 o.filename_date_name AS shown_name,o.filename_date_url AS shown_url,
 cast(o.shown_filename_date AS VARCHAR) AS other_value,o.filename AS other_name,o.source_url AS other_url
 FROM source_filename_readings o
 WHERE o.shown_status='completed' AND o.shown_filename_date IS NOT NULL
 AND o.filename_date IS NOT NULL AND o.filename_date<>o.shown_filename_date
 AND NOT EXISTS (SELECT 1 FROM source_linked_filename_readings l
  WHERE l.source_id=o.source_id AND l.requested_filename=o.filename AND l.requested_url=o.source_url)"""
FILENAME_BOTH_NAMES=dict(name='filename_both_names',sql='SELECT count(*) FILTER (WHERE linked_filename IS NOT NULL) AS sources_with_two_names,'+','.join(
    f'count(*) FILTER (WHERE {filled}) AS {name}_filled' for name,_,_,filled in _NAME_FIELDS)+','+','.join(
    f"(SELECT count(*) FROM filename_conflicts c WHERE c.field='{name}') AS {name}_conflicting" for name,_,_,_ in _NAME_FIELDS)
    +' FROM source_filename_readings')

# Documents whose saved body carries names that state different kinds (saved-name-conflicts.sql,
# ct-yuf0): how many a committee name leads, how many are two official names of different kinds with
# no committee name to settle them (a reading would), and how many official names outside the House
# meeting-document slots lead against a committee name: a printed hearing or vote record the rule
# settles, a body the review decided official, or one left to saved-file order (ct-h8dr).
SAVED_NAME_KINDS=dict(name='saved_name_kinds',sql="""SELECT count(*) AS documents,
 count(*) FILTER (WHERE NOT official_leads) AS committee_name_leads,
 count(*) FILTER (WHERE official_leads AND committee_agrees) AS official_name_leads_with_committee_agreement,
 count(*) FILTER (WHERE official_leads AND NOT committee_speaks) AS official_names_disagree_unsettled,
 count(*) FILTER (WHERE official_leads AND NOT official_slot AND committee_speaks AND NOT committee_agrees) AS other_official_name_leads_contradicted,
 count(*) FILTER (WHERE official_slot AND committee_speaks AND NOT committee_agrees) AS slot_name_leads_contradicted
 FROM saved_name_conflicts""")
# The case the name rule forbids, as model invariant contradicted_official_saved_names: a House
# meeting-document slot name leading a document against a committee name that states another kind.
# The generic House name also gives way, but not where the review left a body undecided, so it is
# not counted here.
CONTRADICTED_OFFICIAL_SAVED_NAMES_SQL="SELECT count(*) FROM saved_name_conflicts WHERE official_slot AND committee_speaks AND NOT committee_agrees"
# Reviewed name decisions (saved-name-decisions.json) whose body is no document's saved body: a newer
# fetch moved the document to other bytes, and its names fall back to the rules until it is reviewed again.
SAVED_NAME_DECISIONS_UNUSED=dict(name='saved_name_decisions_unused',sql="""SELECT count(*) AS entries
 FROM saved_name_decisions v LEFT ANTI JOIN (SELECT body_sha FROM saved_files WHERE saved_rank=1) s ON s.body_sha=v.body_sha""")
# Reviewed name decisions whose saved body leads under none of the names the review read (review finding 2):
# a newer copy under an unread name of the decided class, or a third name saved-file order chose for an
# undecided body. The decision needs a new read. The registry (about 90 rows) is the hash build side.
SAVED_NAME_DECISIONS_UNMET=dict(name='saved_name_decisions_unmet',sql="""SELECT count(*) AS entries
 FROM saved_name_decisions v JOIN (SELECT body_sha,filename FROM saved_files WHERE saved_rank=1) s ON s.body_sha=v.body_sha
 WHERE NOT array_has(string_to_array(v.official_name||' | '||v.committee_name,' | '),s.filename)""")

# Meeting-record doc-url literals that are no http(s) address get no URL key (model-url-inputs.sql)
# and so cannot reach invalid_url_keys; this counts them instead of refusing the release.
UNRESOLVED_MEETING_DOCUMENT_URLS=dict(name='unresolved_meeting_document_urls',sql="""SELECT count(*) AS urls
 FROM (SELECT DISTINCT url FROM meeting_document_urls) d LEFT ANTI JOIN model_url_keys k ON k.url=d.url""")


def evidence_checks():
    """Expose current prefix checks for admission and the full invariant report."""
    from congress_api.lake.readings import writer_admission_conflict_sql
    return dict(
        non_document_good_fetches='(SELECT n FROM non_document_good_fetches)',
        conflicting_writer_formats='(SELECT n FROM ('+writer_admission_conflict_sql()+') writer_conflicts)',
        conflicting_sniffs='(SELECT count(*) FROM sniff_conflicts)',
        conflicting_original_sizes='(SELECT count(*) FROM (SELECT sha256 FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING count(DISTINCT bytes)>1))',
        conflicting_verifications='(SELECT count(*) FROM verification_conflicts)',
        invalid_recoveries='(SELECT count(*) FROM recovery_diagnostics WHERE is_fatal)',
        duplicate_recovery_kind_selectors='''(SELECT count(*) FROM (
            SELECT category AS selector FROM recovery_kinds WHERE category IS NOT NULL AND match_basis IS NULL
            GROUP BY category HAVING count(*)>1 UNION ALL
            SELECT match_basis AS selector FROM recovery_kinds WHERE match_basis IS NOT NULL AND category IS NULL
            GROUP BY match_basis HAVING count(*)>1) duplicate_selectors)''',
        invalid_recovery_kind_selectors='''(SELECT count(*) FROM recovery_kinds
            WHERE (category IS NULL)=(match_basis IS NULL)
            OR (category IS NOT NULL AND trim(category)='')
            OR (match_basis IS NOT NULL AND trim(match_basis)='')
            OR kind IS NULL OR trim(kind)='')''')


def entity_track_checks():
    """Check track bodies, playlist readings and one published label per body."""
    return dict(
        empty_body_tracks=f'''(SELECT count(*) FROM recording_track_candidates
            WHERE {empty_body_sql("encode(sha256,'hex')",'cast(NULL AS BIGINT)')})''',
        segment_tracks="""(SELECT count(*) FROM
            (SELECT unnest(tracks) AS t FROM recording_tracks) r
            WHERE r.t['body'] IN (SELECT sha256 FROM recording_segment_bodies))""",
        unread_track_playlists=f"""(SELECT count(DISTINCT f.sha256) FROM recording_fetch_candidates f
            WHERE f.playlist_candidate
            AND lower(encode(f.sha256,'hex')) NOT IN ({explorer_settled_sql('playlist_records')}))""",
        duplicate_track_bodies="""(SELECT count(*) FROM (
            SELECT video_key,t['body'] FROM (SELECT video_key,unnest(tracks) AS t FROM recording_tracks)
            GROUP BY video_key,t['body'] HAVING count(*)>1))""",
    )


# Declared page metadata per html document (ct-93zs); readings selected inside a candidate join.
PAGE_METADATA_STEPS=[
    'html-metadata-readings','page-metadata-documents','page-metadata-values','page-dates','page-descriptions',
    'document-page-contexts','document-page-context-counts','document-page-context-ranked',
    'page-metadata-field-counts','document-page-metadata-entries','document-page-metadata-sizes',
    'document-page-metadata',
]


def _sql_steps(names,*,root=ROOT):
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True) for name in names]


def url_normalized_steps(*,root=ROOT):
    """Normalize only the literals source_url_normalized has not; copy its rows for the rest (ct-6v77 R8).

    Both apply url-normalized.sql, whose bytes the capture profile pins, and each policy row depends on its
    literal and url_rules alone. So the text is split where its literal set ends and the policy CTEs after
    that run unchanged over the remaining literals. url_literals is a step because both halves read it."""
    text=(Path(root)/'model/sql/url-normalized.sql').read_text()
    literals,cut,policy=text.partition('\n), first_matches AS (')
    if not cut or 'WITH literals AS (' not in literals or not policy.endswith('\nSELECT * FROM base_keys\n'):
        raise ValueError('url-normalized.sql no longer has the literal set and final select this split expects')
    split=literals[literals.index('WITH literals AS ('):]+"""
)
SELECT l.url,s.url IS NOT NULL AS reused,s.error,s.still_wrapped,s.base_key
FROM source_url_normalized s RIGHT JOIN literals l ON s.url=l.url"""
    normalize=('WITH literals AS (\n SELECT url FROM url_literals WHERE NOT reused'+cut+policy.rstrip('\n')
        +'\nUNION ALL SELECT url,error,still_wrapped,base_key FROM url_literals WHERE reused')
    return [dict(name='url_literals',sql=split,materialize=True),dict(name='url_normalized',sql=normalize,materialize=True)]


def witness_key_steps(*,root=ROOT):
    """The engine re-runs a CTE at every reference, so the relations document_witness_keys reads more
    than once are materialized first; as one query it set the whole build's peak memory."""
    return _sql_steps(['document-witness-url-keys','document-witness-chrg-components','document-witness-url-matches',
        'document-witness-meeting-witnesses','document-witness-single-meeting-components','document-witness-raw-matches',
        'document-witness-keys'],root=root)


def explorer_settled_sql(table):
    """Settled at the pinned version only: an old version's failure says nothing about the new one."""
    return f"""SELECT lower(encode(record_sha,'hex')) AS sha FROM selected_{table} WHERE status IN ('completed','error','size_limit')
        UNION SELECT lower(coalesce(u.record_sha,u.body_sha256)) FROM active_unreadable u JOIN parser_versions v
         ON v.parser LIKE '{table}.%' AND u.parser_version=v.version WHERE u.parser IN ('{table}',v.parser)"""


PLAYLIST_RECORDS_UNAVAILABLE = """SELECT arrow_cast(NULL,'FixedSizeBinary(32)') AS record_sha,
 cast(NULL AS VARCHAR) AS parser_version,cast(NULL AS VARCHAR) AS status,cast(NULL AS VARCHAR) AS error_type,
 cast(NULL AS VARCHAR) AS source,array_slice(make_array(cast(NULL AS VARCHAR)),1,0) AS segments,
 array_slice(make_array(cast(NULL AS VARCHAR)),1,0) AS playlists WHERE false"""


def selected_record_step(table,record_input,*,root=ROOT):
    """The one version selection each record table's readers share, in both dialects' place."""
    sql=(Path(root)/'model/sql/selected-records.sql').read_text().replace('{{TABLE}}',table).replace('{{INPUT}}',record_input)
    return dict(name='selected_'+table,sql=sql,materialize=True)


def meeting_steps(*,root=ROOT,has_document_references=True):
    """Select once, merge once, then resolve: CTEs are inlined per reader, so these must be steps."""
    steps=_sql_steps(['meeting-records-observed','meeting-records-ranked','meeting-records-current','meeting-records-merged'],root=root)
    if not has_document_references:
        steps[0]['sql']=steps[0]['sql'].replace("m['document_references'] AS document_references",
            NULL_MEETING_DOCUMENT_REFERENCES + " AS document_references")
    return steps+[dict(name='meetings_resolved',sql=(Path(root)/'model/sql/meeting-records-resolved.sql').read_text(),materialize=True)]


def meeting_detail_steps(*,root=ROOT):
    """Bind individual receipts before selecting event-specific read observations."""
    return _sql_steps(['congress-gov-routes','meeting-detail-evidence','meeting-detail-ranked',
        'meeting-detail-observations'],root=root)


def meeting_records_have_document_references(path):
    import pyarrow.parquet as pq
    schema=pq.read_schema(path)
    return schema.field('meetings').type.value_type.get_field_index('document_references') >= 0


EMPTY_RECORDINGS_SQL="""SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS event_ids,
 array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),'format',cast(NULL AS VARCHAR),
  'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks WHERE false"""
WITNESSES_SQL='SELECT r.witness_key,r.occasion,r.source,r.record_sha,r.source_locator,r.context_key,r.event_id,r.package_id,r.page_url,r.name,r.position,r.organization,r.on_behalf_of,r.location,r.panel,r.panel_order,r.display_order,r.witness_type,r.testified,r.bioguide_id,p.superseded_by FROM appearance_records_resolved r LEFT JOIN witness_precedence p ON p.witness_key=r.witness_key'


def appearance_steps(*,root=ROOT):
    """Witness URLs, their keys, then the resolved appearances (one owner for the full and frozen builds)."""
    app_url_inputs_sql="""WITH selected_app_records AS (
        SELECT r.record_sha_hex,r.source,nullif(trim(r.declared_base),'') AS declared_base,
            r.context_url,r.appearances
        FROM selected_appearance_records r
        WHERE r.status='completed'
    ), candidate_app_shas AS (
        SELECT DISTINCT record_sha_hex FROM selected_app_records WHERE record_sha_hex IS NOT NULL
    ), distinct_capture_urls AS (
        SELECT DISTINCT encode(c.sha256,'hex') AS record_sha_hex,
            coalesce(c.url,c.requested_url,c.context_url) AS source_url
        FROM captures c
        JOIN candidate_app_shas cas ON encode(c.sha256,'hex')=cas.record_sha_hex
        WHERE c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged')
          AND c.http_status BETWEEN 200 AND 299 AND c.sha256 IS NOT NULL
    ), app_contexts AS (
        SELECT r.record_sha_hex,r.source,r.declared_base,
            coalesce(c.source_url,r.context_url) AS source_url,
            r.appearances
        FROM selected_app_records r
        LEFT JOIN distinct_capture_urls c ON c.record_sha_hex=r.record_sha_hex
    ), with_base AS (
        SELECT source_url,appearances,
            CASE
                WHEN source_url IS NOT NULL AND declared_base IS NOT NULL
                    THEN coalesce(url_resolve(declared_base,source_url),source_url)
                ELSE source_url
            END AS resolved_base
        FROM app_contexts
    ), apps AS (
        SELECT source_url,resolved_base,unnest(appearances) AS app
        FROM with_base WHERE appearances IS NOT NULL
    ), raw_links AS (
        SELECT resolved_base,
            nullif(trim(unnest(coalesce(app['document_links'],arrow_cast(make_array(),'List(Utf8)')))),'') AS raw_link
        FROM apps
    ), raw_urls AS (
        SELECT source_url AS raw_url FROM with_base WHERE source_url IS NOT NULL
        UNION
        SELECT CASE WHEN resolved_base IS NOT NULL THEN coalesce(url_resolve(raw_link,resolved_base),raw_link) ELSE raw_link END AS raw_url
        FROM raw_links WHERE raw_link IS NOT NULL
        UNION
        SELECT raw_link AS raw_url FROM raw_links WHERE raw_link IS NOT NULL
    ), distinct_urls AS (
        SELECT DISTINCT raw_url AS url FROM raw_urls WHERE raw_url IS NOT NULL AND trim(raw_url)<>''
    ) SELECT encode(sha256(json_array(url)),'hex') AS input_id,url FROM distinct_urls"""
    app_normalize=(Path(root)/'model/sql/url-normalized.sql').read_text().replace('url_inputs','appearance_url_inputs')
    app_keys=(Path(root)/'model/sql/url-keys.sql').read_text().replace('url_inputs','appearance_url_inputs').replace('url_normalized','appearance_url_normalized')
    return [dict(name='appearance_url_inputs',sql=app_url_inputs_sql,materialize=True),
        dict(name='appearance_url_normalized',sql=app_normalize,materialize=True),
        dict(name='appearance_url_keys',sql=app_keys,materialize=True),
        dict(name='senate_page_meeting_links',sql=(Path(root)/'model/sql/senate-page-meeting-links.sql').read_text(),materialize=True),
        dict(name='appearance_capture_contexts',sql=(Path(root)/'model/sql/appearance-capture-contexts.sql').read_text(),materialize=True),
        dict(name='appearance_observations',sql=(Path(root)/'model/sql/appearance-observations.sql').read_text(),materialize=True),
        dict(name='appearance_records_resolved',sql=(Path(root)/'model/sql/appearance-records-resolved.sql').read_text(),materialize=True)]+_sql_steps(
        ['witness-precedence','witness-key-current','witness-key-priors','witness-key-map'],root=root)


def package_link_steps(*,root=ROOT):
    """Packages to meetings: the jacket and MODS links, then the ones a raw record justifies (ct-dx22)."""
    return _sql_steps(['appearance-people','package-mods-facts','print-meeting-agreement','meeting-mods-links','meeting-transcript-links','package-meeting-links'],root=root)


def admission_steps(*,prelude=(),root=ROOT):
    """Use the full model's maintained input prefix before accepting a skip."""
    from viewer_publication.archive_provenance import current_steps
    from viewer_publication.archive_model_profile import completeness_steps
    return list(prelude)+current_steps(root=root)+evidence_steps(root=root)+source_steps(root=root)+completeness_steps(root=root)


def admission_checks(*,parser_versions,catalog_version,include_entities=False,root=ROOT):
    """Check current pinned inputs without exporting public release files."""
    from viewer_publication.archive_model_profile import completeness_checks,validate_parser_versions
    validate_parser_versions(parser_versions,require_entities=include_entities)
    checks=','.join(sql+' AS '+name for name,sql in evidence_checks().items())
    return [dict(name='model_invariants',sql='SELECT '+checks)]+completeness_checks(
        catalog_version=catalog_version,
        include_entities=include_entities,
        meeting_records_version=parser_versions.get('meeting_records') if isinstance(parser_versions,dict) else None,
        appearance_records_version=parser_versions.get('appearance_records') if isinstance(parser_versions,dict) else None,
        root=root)


def input_receipts_query():
    """Return actual receipt keys as metadata, never as a zero-count assertion."""
    return dict(name='input_receipts',sql='SELECT DISTINCT receipt_key FROM captures ORDER BY receipt_key')


def probe_selectors_query(*,root=ROOT):
    """Choose one visible saved document using the actual exported detail rows."""
    limit=json.loads((Path(root)/'model/registries/reader-limits.json').read_text())['max_unpacked_bytes']
    if type(limit) is not int or limit<=0:raise ValueError('Invalid reader unpacking limit')
    return dict(name='probe_selectors',sql=f"""SELECT list_row AS saved_row,encode(link_key,'hex') AS link_key
        FROM details WHERE saved_body IS NOT NULL AND saved_bytes>0 AND NOT hidden
        AND (saved_suffix<>'.gz' OR saved_bytes<={limit})
        ORDER BY saved_bytes NULLS LAST,list_row LIMIT 1""")


def prepare_model_inputs(*,captures,readings,filename_readings,parser_versions,catalog_version,
                         engine,scratch,recovery_files=(),review_files=(),verification_files=(),
                         unreadable_files=(),variant_files=(),meeting_records=None,appearance_records=None,
                         spicy_regs=None,include_entities=False,recovery_requirements=None,
                         video_records=None,committee_records=None,recording_decision_files=(),playlist_records=None,
                         historical_recording_matcher=None,prior_links=None,base_retired=None,root=ROOT,registry=None):
    """Freeze current input selectors and the shared prefix in fresh private scratch.

    `registry` names a compatible-versions file other than the checked-in one (tests only).
    prior_links/base_retired (release_gate.prior_links) feed only the retired-key
    ledger; absent, the ledger starts empty. They stay out of the input identity.
    """
    from congress_api.lake import compatible_versions
    from viewer_publication.archive_format import AUXILIARY_ROW_GROUP_ROWS, _settings
    from viewer_publication.archive_model_profile import (expand_parser_version_rows,profile_record,
        readings_bundle_version,runtime_pins,validate_parser_versions)
    include_entities=bool(include_entities or meeting_records is not None or appearance_records is not None or spicy_regs is not None)
    # All or none: an omitted table means unavailable, never empty (DM8).
    explorer_inputs=video_records is not None or committee_records is not None or bool(recording_decision_files)
    if explorer_inputs and (video_records is None or committee_records is None or not recording_decision_files or not include_entities):
        raise ValueError('Explorer tables require entity inputs, video_records, committee_records and recording decisions together')
    validate_parser_versions(parser_versions,require_entities=include_entities,require_explorer=explorer_inputs)
    if playlist_records is not None and (not include_entities or 'playlist_records' not in parser_versions):
        raise ValueError('Playlist records require entity inputs and a pinned playlist_records version')
    scratch=Path(scratch).resolve();scratch.mkdir(parents=True,exist_ok=False)
    evidence=scratch/'evidence';evidence.mkdir()
    inputs=registry_inputs(scratch/'registries',root=root)
    if historical_recording_matcher is not None:
        from viewer_publication.historical_recording_matcher import matcher_input
        inputs.append(matcher_input(scratch,historical_recording_matcher))
    raw_data_inputs=[('captures',captures),('readings',readings),('filename_readings',filename_readings)]
    if meeting_records is not None and not isinstance(meeting_records,(list,tuple)):
        raw_data_inputs.append(('meeting_records',meeting_records))
    if appearance_records is not None and not isinstance(appearance_records,(list,tuple)):
        raw_data_inputs.append(('appearance_records',appearance_records))
    if explorer_inputs:
        raw_data_inputs += [('video_records',video_records),('committee_records',committee_records)]
    if playlist_records is not None:
        raw_data_inputs.append(('playlist_records',playlist_records))
    data_inputs=[dict(value,name=name) if isinstance(value,dict) else
        dict(name=name,kind='parquet',path=str(Path(value).resolve())) for name,value in raw_data_inputs]
    inputs += data_inputs
    inputs.append(json_input(scratch,'parser_versions',expand_parser_version_rows(parser_versions),parser='Utf8',version='Utf8'))
    # Load the registry once; every readings reader goes through the one selection it renders.
    pins={**{p:parser_versions[p] for p in compatible_versions.LEAF_PARSERS},'readings':readings_bundle_version(parser_versions),
          **{p:parser_versions[p] for p in compatible_versions.DERIVED_PARSERS if p in parser_versions}}
    entries=compatible_versions.load_registry(current=pins,path=registry or Path(root)/'model/registries/compatible-versions.json')
    inputs.append(compatible_versions.accepted_versions_input(scratch,entries,pins=pins))
    from viewer_publication.release_gate import ledger_inputs
    inputs += ledger_inputs(scratch/'ledger',prior_links=prior_links,base_retired=base_retired)
    # Provenance is immutable input data; JSON columns with heterogeneous values
    # are projected once by the native reader before policy joins.
    from viewer_publication.archive_provenance import provenance_inputs
    provenance,prelude=provenance_inputs(scratch/'provenance',recovery_files=recovery_files,review_files=review_files)
    prelude[0:0]=compatible_versions.selected_readings_steps(entries,parsers=pins)
    inputs += provenance
    recovery_policy=None
    if recovery_requirements is not None:
        recovery_policy=dict(acceptance_policy=recovery_requirements['acceptance_policy'],
                             requirements_sha256=recovery_requirements['sha256'])
        # Releases created before refresh policy was explicit conservatively keep
        # live refresh eligible. The exact original requirements remain pinned.
        import pyarrow.parquet as pq
        fields=pq.read_schema(recovery_requirements['path']).names
        inputs.append(dict(name='recovery_requirements_input',kind='parquet',path=recovery_requirements['path']))
        refresh='refresh_policy' if 'refresh_policy' in fields else "cast('refresh_live' AS VARCHAR) AS refresh_policy"
        prelude.append(dict(name='recovery_requirements',sql='SELECT original_url,target_requirement,acceptance_policy,'+refresh+' FROM recovery_requirements_input',materialize=True))
    def _record_table_sql(table_name,value,payload_col):
        parquet_path=value.get('path') if isinstance(value,dict) and value.get('kind')=='parquet' else (value if isinstance(value,(str,Path)) else None)
        sha_expr="lower(encode(record_sha,'hex'))"
        status_expr='status'
        error_expr='error_type'
        extra_select=''
        if table_name=='appearance_records':
            extra_select='event_id,package_id,declared_base,collection_state,cast(NULL AS VARCHAR) AS context_url,held_dates,title,created,'
        if parquet_path is not None and Path(parquet_path).is_file():
            import pyarrow as pa
            import pyarrow.parquet as pq
            schema=pq.read_schema(parquet_path)
            if 'record_sha' in schema.names and not (pa.types.is_binary(schema.field('record_sha').type) or pa.types.is_fixed_size_binary(schema.field('record_sha').type)):
                sha_expr='lower(record_sha)'
            if 'status' not in schema.names:
                status_expr="'completed'"
            if 'error_type' not in schema.names:
                error_expr='cast(NULL AS VARCHAR)'
            if table_name=='appearance_records':
                ev_expr='event_id' if 'event_id' in schema.names else 'cast(NULL AS BIGINT) AS event_id'
                pkg_expr='package_id' if 'package_id' in schema.names else 'cast(NULL AS VARCHAR) AS package_id'
                base_expr='declared_base' if 'declared_base' in schema.names else 'cast(NULL AS VARCHAR) AS declared_base'
                cs_expr='collection_state' if 'collection_state' in schema.names else 'cast(NULL AS VARCHAR) AS collection_state'
                ctx_expr='context_url' if 'context_url' in schema.names else 'cast(NULL AS VARCHAR) AS context_url'
                # MODS print facts; an older lake file without them states none.
                held_expr='held_dates' if 'held_dates' in schema.names else "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS held_dates"
                title_expr='title' if 'title' in schema.names else 'cast(NULL AS VARCHAR) AS title'
                created_expr='created' if 'created' in schema.names else 'cast(NULL AS VARCHAR) AS created'
                extra_select=f'{ev_expr},{pkg_expr},{base_expr},{cs_expr},{ctx_expr},{held_expr},{title_expr},{created_expr},'
        return f"SELECT {sha_expr} AS record_sha_hex,parser_version,{status_expr} AS status,{error_expr} AS error_type,source,{extra_select}{payload_col} FROM {table_name}"
    meeting_records_path=meeting_records.get('path') if isinstance(meeting_records,dict) else meeting_records
    has_document_references=(not isinstance(meeting_records_path,(str,Path)) or
        not Path(meeting_records_path).is_file() or meeting_records_have_document_references(meeting_records_path))
    if meeting_records is None or isinstance(meeting_records,(list,tuple)):
        inputs.append(json_input(scratch,'meeting_records_input',_normalize_meeting_rows(meeting_records or (),parser_versions.get('meeting_records')),**MEETING_RECORD_FIELDS))
    else:
        prelude += [dict(name='meeting_records_input',sql=_record_table_sql('meeting_records',meeting_records,'meetings'),materialize=True)]
    if appearance_records is None or isinstance(appearance_records,(list,tuple)):
        inputs.append(json_input(scratch,'appearance_records_input',_normalize_appearance_rows(appearance_records or (),parser_versions.get('appearance_records')),**APPEARANCE_RECORD_FIELDS))
    else:
        prelude += [dict(name='appearance_records_input',sql=_record_table_sql('appearance_records',appearance_records,'appearances'),materialize=True)]
    spicy_inputs,entity_digests=_prepare_spicy_inputs(scratch,spicy_regs,include_entities)
    inputs += spicy_inputs
    def _provenance_input(name,files,fields):
        from congress_api.retention.provenance import field
        if files:return dict(name=name,kind='json_lines',files=list(files),schema=dict(fields=[field(k,v) for k,v in fields.items()],metadata={}))
        return json_input(scratch,name,[],**fields)
    inputs.append(_provenance_input('verification_records',verification_files,dict(key='Utf8',size='Int64',intact='Boolean',sha256_verified='Boolean',checked_at='Utf8')))
    inputs.append(json_input(scratch,'url_state_meeting_dates_input',[],requested_url='Utf8',meeting_date='Date32'))
    inputs.append(_provenance_input('url_variant_records',variant_files,{name:'Utf8' for name in ['id','canonical_url','variant_url','basis','decided_at','supersedes']}))
    prelude += [selected_record_step('meeting_records','meeting_records_input',root=root),
        selected_record_step('appearance_records','appearance_records_input',root=root)]
    prelude += [dict(name='url_variants',sql='SELECT DISTINCT canonical_url,variant_url FROM url_variant_records r WHERE NOT EXISTS(SELECT 1 FROM url_variant_records s WHERE s.supersedes=r.id)',materialize=True)]
    inputs.append(_provenance_input('unreadable_records',unreadable_files,dict(id='Utf8',body_sha256='Utf8',record_sha='Utf8',
        parser='Utf8',parser_version='Utf8',reason='Utf8',decided_at='Utf8',supersedes='Utf8')))
    if explorer_inputs:
        inputs.append(_provenance_input('recording_decision_records',recording_decision_files,RECORDING_DECISION_FIELDS))
        inputs.append(json_input(scratch,'channel_directory',channel_directory_rows(root),handle='Utf8',channel_id='Utf8',system_code='Utf8',committee_label='Utf8',role='Utf8'))
        prelude += [selected_record_step('video_records','video_records',root=root),selected_record_step('committee_records','committee_records',root=root)]
        prelude += [dict(name='active_recording_decisions',sql='SELECT r.* FROM recording_decision_records r WHERE NOT EXISTS(SELECT 1 FROM recording_decision_records s WHERE s.supersedes=r.id)',materialize=True)]
    if include_entities:
        if playlist_records is None:
            prelude.append(dict(name='playlist_records',sql=PLAYLIST_RECORDS_UNAVAILABLE,materialize=True))
        prelude.append(selected_record_step('playlist_records','playlist_records',root=root))
    prelude += [dict(name='active_unreadable',sql='SELECT u.* FROM unreadable_records u WHERE NOT EXISTS(SELECT 1 FROM unreadable_records s WHERE s.supersedes=u.id)',materialize=True)]
    from congress_api.models.archive_profile import build_capture_profile
    capture_profile=build_capture_profile(engine_revision=engine.source_revision,
        url_normalized_sql=(Path(root)/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(Path(root)/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((Path(root)/'model/registries/url-rules.json').read_text()),recovery_policy=recovery_policy)
    from congress_api.retention.provenance import file_pin
    selectors={item['name']:dict(item) if item['kind']=='native_table' else dict(kind='parquet',path=item['path'],**file_pin(item['path'])) for item in data_inputs}
    lake_tables=['captures','readings','filename_readings']+(['meeting_records','appearance_records'] if include_entities else [])+(['video_records','committee_records'] if explorer_inputs else [])
    if playlist_records is not None:lake_tables.append('playlist_records')
    model_profile=profile_record(parser_versions=parser_versions,catalog_version=catalog_version,
        engine_revision=engine.source_revision,runtime_pins=runtime_pins(engine),
        lake_versions={name:dict(schema_sha256=file_pin(Path(root)/'model/lake'/(name.replace('_','-')+'.schema.json'))['sha256']) for name in lake_tables},
        snapshots=selectors,writer_settings=dict(schema_version=1,whole=_settings('whole',['list_row']),
            ranged=_settings('ranged',['list_row']),lookup=_settings('lookup',['link_key']),
            auxiliary_row_group_rows=AUXILIARY_ROW_GROUP_ROWS),root=root,
        recovery_policy=recovery_policy,historical_recording_matcher=historical_recording_matcher)
    (scratch/'profile.json').write_text(json.dumps(model_profile,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    return dict(inputs=inputs,prelude=prelude,steps=admission_steps(prelude=prelude,root=root),
        profile=model_profile,capture_profile=capture_profile,scratch=scratch,evidence=evidence,
        parser_versions=dict(parser_versions),catalog_version=catalog_version,
        include_entities=include_entities,entity_digests=entity_digests,recovery_policy=recovery_policy,explorer_inputs=explorer_inputs,
        has_document_references=has_document_references,
        historical_recording_matcher=historical_recording_matcher is not None)


def build_release(*,captures,readings,filename_readings,parser_versions,catalog_version,
                  engine,output,scratch,recovery_files=(),review_files=(),verification_files=(),
                  unreadable_files=(),variant_files=(),meeting_records=None,appearance_records=None,
                  spicy_regs=None,include_entities=False,recovery_requirements=None,
                  video_records=None,committee_records=None,recording_decision_files=(),playlist_records=None,
                  historical_recording_matcher=None,prior_links=None,base_retired=None,root=ROOT,registry=None):
    """Prepare inputs once and run the document model's maintained full job."""
    prepared=prepare_model_inputs(captures=captures,readings=readings,filename_readings=filename_readings,
        parser_versions=parser_versions,catalog_version=catalog_version,engine=engine,scratch=scratch,
        recovery_files=recovery_files,review_files=review_files,verification_files=verification_files,
        unreadable_files=unreadable_files,variant_files=variant_files,meeting_records=meeting_records,
        appearance_records=appearance_records,spicy_regs=spicy_regs,include_entities=include_entities,
        recovery_requirements=recovery_requirements,video_records=video_records,committee_records=committee_records,
        recording_decision_files=recording_decision_files,playlist_records=playlist_records,
        historical_recording_matcher=historical_recording_matcher,prior_links=prior_links,base_retired=base_retired,root=root,registry=registry)
    return build_prepared_release(prepared,engine=engine,output=output,root=root)


def build_prepared_release(prepared,*,engine,output,root=ROOT):
    """Continue one prepared plan through grouping and the shared native exporter."""
    from viewer_publication.archive_format import _execute,_settings,LIST_COLUMNS,DETAIL_COLUMNS,MEETING_DICTIONARY
    from viewer_publication.archive_annotations import annotation_steps
    from viewer_publication.archive_provenance import RECOVERY_FILE_AGREEMENT,attachment_steps,body_review_steps,recovered_copy_steps
    scratch=prepared['scratch'];evidence=prepared['evidence'];output=Path(output).resolve()
    inputs=prepared['inputs'];capture_profile=prepared['capture_profile']
    parser_versions=prepared['parser_versions'];catalog_version=prepared['catalog_version']
    steps=list(prepared['steps'])+link_steps(root=root)
    steps += _sql_steps(['archive-member-addresses'],root=root)
    # Meetings read only prelude inputs; the documents they list feed URL keys and annotations.
    steps += meeting_steps(root=root,has_document_references=prepared.get('has_document_references',True))+meeting_detail_steps(root=root)+_sql_steps(['meeting-document-urls'],root=root)
    steps += [dict(name='url_inputs',sql=(Path(root)/'model/sql/model-url-inputs.sql').read_text(),materialize=True)]
    steps += url_normalized_steps(root=root)
    steps += [dict(name='model_url_keys',sql=(Path(root)/'model/sql/url-keys.sql').read_text(),materialize=True)]
    steps += _sql_steps(['source-endpoints','copy-url-keys','publisher-links'],root=root)
    steps += [dict(name='resolved_link_targets',sql="SELECT DISTINCT page_body,context_url,member_path,target_url,cast(NULL AS VARCHAR) AS target_member_path FROM resolved_links WHERE target_member_path IS NULL",materialize=True)]
    steps += [dict(name='body_fingerprints',sql="SELECT encode(body_sha,'hex') AS body_sha,encode(fingerprint,'hex') AS fingerprint FROM page_facts WHERE status='completed'",materialize=True)]
    steps += body_review_steps(root=root)+recovered_copy_steps(root=root)+grouping_steps(root=root,review_edges=True,recovered_copies=True)
    steps += [dict(name='recovery_original_keys',sql="SELECT r.recovery_id,k.url_key FROM model_recovery_rows r JOIN model_url_keys k ON r.original_url=k.url WHERE k.error IS NULL",materialize=True),
        dict(name='component_members',sql='SELECT l.component,f.* FROM source_labels l JOIN source_files f USING(source_id)',materialize=True)]
    steps += attachment_steps(root=root)+_sql_steps(['initial-document-link-keys'],root=root)
    from viewer_publication.archive_reviews import duplicate_steps,application_steps
    steps += duplicate_steps(root=root)
    steps += [dict(name='review_components',components=dict(sql='SELECT left_node,right_node FROM duplicate_component_edges',left='left_node',right='right_node',node_limit=10_000_000))]
    steps += _sql_steps(['final-source-labels','final-recovery-attachments','document-link-keys'],root=root)
    steps += annotation_steps(catalog_version=catalog_version,root=root)
    steps += [dict(name='filename_conflicts',sql=FILENAME_CONFLICTS_SQL,materialize=True)]
    steps += _sql_steps(['document-members','archive-container-links','landing-page-files','landing-pages','document-bodies','document-identities','saved-name-standing','saved-files','saved-name-conflicts','document-alternates',
        'document-version-keys','document-versions','document-bill-decisions','document-metadata','document-addresses','saved-recoveries','document-removals','document-packages',
        'document-rendition-titles','recovered-copy-fills','document-filename-facts'],root=root)
    steps += package_link_steps(root=root)
    steps += appearance_steps(root=root)+witness_key_steps(root=root)+[
        dict(name='component_meeting_links',sql=(Path(root)/'model/sql/component-meeting-links.sql').read_text(),materialize=True)]
    steps += [dict(name='base_normalized',sql=(Path(root)/'model/sql/document-normalized.sql').read_text()+' UNION ALL '+(Path(root)/'model/sql/document-recovery-normalized.sql').read_text(),materialize=True)]
    steps += _sql_steps(['document-hearing-date-corrections'],root=root)
    from viewer_publication.archive_model_profile import completeness_checks
    steps += application_steps(root=root)
    steps += _sql_steps(PAGE_METADATA_STEPS,root=root)
    from viewer_publication.archive_format import PAGE_COLUMNS,PAGE_DEFAULTS
    page=','.join(f'coalesce(pm.{c},{PAGE_DEFAULTS[c]}) AS {c}' if c in ('publisher_labels','page_metadata') else f'pm.{c}' for c in PAGE_COLUMNS)
    steps += [dict(name='normalized',sql=f"""SELECT n.* EXCLUDE(title,document_kind,hidden,review_note,review_decided_at,removed_on,document_date,document_date_source),
        coalesce(r.title_override,n.title) AS title,coalesce(r.kind_override,n.document_kind) AS document_kind,
        coalesce(r.hidden,false) AS hidden,r.note AS review_note,r.decided_at AS review_decided_at,x.removed_on,
        CASE WHEN h.doc_key IS NULL THEN n.document_date ELSE h.document_date END AS document_date,
        CASE WHEN h.doc_key IS NULL THEN n.document_date_source ELSE h.document_date_source END AS document_date_source,{page}
        FROM document_page_metadata pm RIGHT JOIN (document_removals x RIGHT JOIN (review_overrides r RIGHT JOIN
            (document_identities d JOIN (document_hearing_date_corrections h RIGHT JOIN base_normalized n ON n.doc_key=h.doc_key)
             ON n.doc_key=d.document_id)
            ON d.component=r.component) ON d.component=x.component) ON pm.doc_key=n.doc_key""",materialize=True),
        dict(name='source_input',sql=(Path(root)/'model/sql/document-source-input.sql').read_text(),materialize=True),
        dict(name='recovery_input',sql=(Path(root)/'model/sql/document-recovery-input.sql').read_text(),materialize=True)]
    url_state_meeting_dates_sql="""SELECT requested_url,cast(meeting_date AS DATE) AS meeting_date FROM url_state_meeting_dates_input
        UNION SELECT a.url AS requested_url,m.meeting_date FROM source_addresses a
            JOIN source_annotation_addresses sa ON a.source_id=sa.source_id
            JOIN meetings_resolved m ON try_cast(sa.meeting_key AS BIGINT)=m.event_id WHERE m.meeting_date IS NOT NULL
        UNION SELECT a.url AS requested_url,cml.meeting_date FROM source_addresses a
            JOIN document_members dm ON a.source_id=dm.source_id
            JOIN component_meeting_links cml ON dm.component=cml.component WHERE cml.meeting_date IS NOT NULL
        UNION SELECT c.requested_url,m.meeting_date FROM (SELECT DISTINCT requested_url FROM captures WHERE requested_url IS NOT NULL) c
            JOIN meetings_resolved m ON m.event_id=coalesce(
                try_cast((regexp_match(c.requested_url,'(?i)/committee-meeting/[0-9]+/[a-z]+/([0-9]+)'))[1] AS BIGINT),
                try_cast((regexp_match(c.requested_url,'(?i)[?&]eventid=([0-9]+)'))[1] AS BIGINT))
            WHERE m.meeting_date IS NOT NULL"""
    steps += [dict(name='url_state_meeting_dates',sql=url_state_meeting_dates_sql,materialize=True)]
    from viewer_publication.archive_url_state import url_state_steps,url_state_diagnostics
    steps += url_state_steps(root=root,recovery_policy=prepared.get('recovery_policy'))
    auxiliary=[('meetings',(Path(root)/'model/sql/entity-meetings.sql').read_text(),['event_id'],MEETING_DICTIONARY)]
    if not prepared.get('include_entities'):
        # Meetings list caption tracks among their transcripts (ct-1i4q); without entities there are none.
        steps += [dict(name='recordings_entity',sql=EMPTY_RECORDINGS_SQL,materialize=True)]
    if prepared.get('include_entities'):
        from congress_api.lake.playlist_records import GOOD_FETCH_CAPTURE_SQL,PLAYLIST_CAPTURE_SQL
        steps += [
            dict(name='recording_url_sources',sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'",materialize=True),
            dict(name='recording_track_formats',sql="SELECT pattern,format,default_language,default_production FROM recording_sources WHERE kind='track_format'",materialize=True),
            dict(name='recording_segment_exclusions',sql="SELECT pattern FROM recording_sources WHERE kind='segment_exclusion'",materialize=True),
            dict(name='recording_link_candidates',sql="SELECT DISTINCT page_body,target_url FROM resolved_link_targets WHERE target_url IS NOT NULL AND regexp_like(target_url,'(?i)(?:youtube|youtu[.]be|senate)')",materialize=True),
            dict(name='recording_video_links',sql="""SELECT DISTINCT l.page_body,
                regexp_replace((regexp_match(l.target_url,rs.pattern))[1],'^(.+)$',rs.key_template) AS extracted_key
                FROM recording_url_sources rs JOIN recording_link_candidates l ON regexp_like(l.target_url,rs.pattern)""",materialize=True),
            dict(name='recording_video_pages',sql="""SELECT DISTINCT page_body,
                arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha
                FROM recording_video_links WHERE page_body IS NOT NULL""",materialize=True),
            dict(name='recording_page_sources',sql="""SELECT DISTINCT c.source_id,c.body_sha AS page_body
                FROM recording_video_pages vp JOIN capture_source_contexts c ON c.body_sha=vp.page_body""",materialize=True),
            dict(name='recording_page_meetings',sql="""SELECT vp.page_body,unnest(pf.named_meetings) AS event_id
                FROM recording_video_pages vp JOIN page_facts pf ON pf.body_sha=vp.body_sha
                WHERE pf.status='completed' AND pf.named_meetings IS NOT NULL
                UNION
                SELECT DISTINCT vps.page_body,try_cast(a.meeting_key AS BIGINT) AS event_id
                FROM recording_page_sources vps JOIN source_annotation_addresses a ON a.source_id=vps.source_id
                WHERE try_cast(a.meeting_key AS BIGINT) IS NOT NULL""",materialize=True),
            dict(name='recording_fetch_candidates',sql=f"""SELECT c.receipt_key,c.receipt_line,c.capture_index,c.sha256,
                coalesce(c.stored_suffix,'.gz') AS suffix,
                coalesce(c.sniffed_format,CASE lower(split_part(c.media_type,';',1)) WHEN 'text/vtt' THEN 'vtt' WHEN 'application/vnd.apple.mpegurl' THEN 'm3u8' WHEN 'application/x-mpegurl' THEN 'm3u8' END) AS body_format,
                coalesce(c.url,c.requested_url,c.context_url) AS fetch_url,
                CASE WHEN c.url<>c.requested_url THEN c.requested_url END AS redirected_from,
                ({PLAYLIST_CAPTURE_SQL}) AS playlist_candidate,
                arrow_cast(try_cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS retrieved_at
                FROM captures c
                WHERE {GOOD_FETCH_CAPTURE_SQL} AND coalesce(c.url,c.requested_url,c.context_url) IS NOT NULL
                 AND regexp_like(coalesce(c.url,c.requested_url,c.context_url),'(?i)(?:youtube|youtu[.]be|senate)')""",materialize=True),
            # Relative URIs use the final playlist address. Collapse repeat captures before
            # unnesting segments, so a repeat fetch does not multiply every listed child.
            dict(name='playlist_segment_urls',sql="""WITH playlist_addresses AS (
                SELECT DISTINCT p.record_sha,f.fetch_url
                FROM (SELECT record_sha FROM selected_playlist_records WHERE status='completed') p
                JOIN recording_fetch_candidates f ON f.sha256=p.record_sha
            )
            SELECT DISTINCT url_resolve(p.uri,a.fetch_url) AS segment_url
            FROM playlist_addresses a JOIN (
                SELECT record_sha,unnest(segments) AS uri FROM selected_playlist_records WHERE status='completed'
            ) p ON p.record_sha=a.record_sha""",materialize=True),
            # The listed URI can redirect. The downloaded bytes are still a segment.
            dict(name='recording_segment_bodies',sql="""SELECT f.sha256
                FROM playlist_segment_urls s JOIN recording_fetch_candidates f ON s.segment_url=f.fetch_url
                UNION SELECT f.sha256 FROM playlist_segment_urls s
                JOIN recording_fetch_candidates f ON s.segment_url=f.redirected_from
                UNION SELECT sha256 FROM placeholders""",materialize=True),
            # A subtitle media playlist lists caption segments. Masters, empty manifests
            # and media playlists of video/audio segments do not supply subtitle tracks.
            dict(name='caption_playlist_bodies',sql="""SELECT record_sha FROM (
                SELECT record_sha,unnest(segments) AS uri FROM selected_playlist_records WHERE status='completed'
                ) s GROUP BY record_sha HAVING bool_and(regexp_like(uri,'(?i)[.](?:vtt|srt|ttml|dfxp)(?:[?#]|$)'))""",materialize=True),
            # Every regex runs once per distinct fetch URL (a third of the fetches), and each registry is the
            # left input of its regex join: a nested-loop join buffers its left input whole, on one partition.
            dict(name='recording_track_candidates',sql="""WITH fetch_urls AS (
                SELECT DISTINCT fetch_url FROM recording_fetch_candidates
            ), matched_keys AS (
                SELECT u.fetch_url,
                 regexp_replace((regexp_match(u.fetch_url,vu.pattern))[1],'^(.+)$',vu.key_template) AS extracted_key,
                 vu.format AS vu_format,
                 vu.default_language AS vu_default_language,
                 vu.default_production AS vu_default_production,vu.id AS rule_id
                FROM recording_url_sources vu
                JOIN fetch_urls u ON regexp_like(u.fetch_url,vu.pattern)
            ), kept_keys AS (
                SELECT * FROM (
                    SELECT k.*,row_number() OVER(PARTITION BY fetch_url,extracted_key ORDER BY
                        vu_default_production IN ('live','archive') DESC,rule_id) AS preference
                    FROM recording_segment_exclusions ex
                    RIGHT ANTI JOIN matched_keys k ON regexp_like(k.fetch_url,ex.pattern)
                ) k WHERE preference=1
            ), url_tracks AS (
                SELECT k.fetch_url,k.extracted_key,k.vu_format,tf.format AS tf_format,
                coalesce(
                 lower(nullif((regexp_match(k.fetch_url,'(?i)[?&](?:t?lang)=([a-z]{2,3}(?:-[a-z0-9]+)?)'))[1],'')),
                 lower(nullif((regexp_match(k.fetch_url,'(?i)/(?:subtitles|captions|cc)/([a-z]{2,3})(?:/|[._-])'))[1],'')),
                 k.vu_default_language,tf.default_language,'en'
                ) AS language,
                coalesce(
                 CASE WHEN regexp_like(k.fetch_url,'(?i)[?&](?:kind|caps)=asr(?:[&#]|$)') THEN 'asr' END,
                 k.vu_default_production,tf.default_production,'caption'
                ) AS production
                FROM recording_track_formats tf
                RIGHT JOIN kept_keys k ON regexp_like(k.fetch_url,tf.pattern)
            )
            SELECT cf.receipt_key,cf.receipt_line,cf.capture_index,cf.sha256,cf.suffix,cf.fetch_url,cf.retrieved_at,
                t.extracted_key,
                coalesce(
                 CASE WHEN cf.body_format IN ('vtt','srt','m3u8','ttml') THEN cf.body_format END,
                 t.tf_format,
                 t.vu_format
                ) AS format,
                t.language,t.production
            FROM recording_segment_bodies b
            RIGHT ANTI JOIN (url_tracks t JOIN recording_fetch_candidates cf ON cf.fetch_url=t.fetch_url)
              ON b.sha256=cf.sha256""",materialize=True),
        ]
        # A step, not only an export: meetings read it to list caption tracks among their transcripts.
        steps += [dict(name='recording_tracks',sql=(Path(root)/'model/sql/recording-tracks.sql').read_text(),materialize=True),
            dict(name='caption_resource_requests',sql=(Path(root)/'model/sql/caption-resource-requests.sql').read_text(),materialize=True),
            dict(name='caption_resources',sql=(Path(root)/'model/sql/caption-resources.sql').read_text(),materialize=True),
            dict(name='recordings_entity',sql=(Path(root)/'model/sql/entity-recordings.sql').read_text(),materialize=True)]
        auxiliary += [
            ('witnesses',WITNESSES_SQL,['occasion','panel_order','display_order','witness_key'],['occasion','source','witness_type','bioguide_id']),
            ('witness_key_map','SELECT old_key,witness_key,status,basis,candidate_keys,occasion,source FROM witness_key_map',['old_key'],['occasion','source','status','basis']),
            ('recordings','SELECT * FROM recordings_entity',['video_key'],['tracks.list.item.suffix','tracks.list.item.format','tracks.list.item.language','tracks.list.item.production']),
            ('caption_resources','SELECT * FROM caption_resources',['video_key','track_body','ordinal'],['suffix','format','status']),
            ('committees',(Path(root)/'model/sql/entity-committees.sql').read_text(),['system_code'],['chamber','committee_type','parent_system_code']),
            ('members',(Path(root)/'model/sql/entity-members.sql').read_text(),['bioguide_id'],['terms.list.item.chamber','terms.list.item.state','terms.list.item.party']),
            ('rosters',(Path(root)/'model/sql/entity-rosters.sql').read_text(),['congress','system_code','rank','bioguide_id'],['system_code','bioguide_id','title','party']),
            ('bills',(Path(root)/'model/sql/entity-bills.sql').read_text(),['bill_id'],['sponsor_bioguide_id','stage','policy_area','committees.list.item','floor_votes.list.item.basis','floor_votes.list.item.chamber','amendments.list.item.sponsor_bioguide_id','committee_activities.list.item.system_code','committee_activities.list.item.activity']),
            ('nominations',(Path(root)/'model/sql/entity-nominations.sql').read_text(),['nomination_id'],['committees.list.item']),
        ]
        auxiliary += list(detail_exports(prepared['entity_digests'],SPICY_SCHEMAS))
    explorer_diagnostics=[]
    if prepared.get('explorer_inputs'):
        steps += _sql_steps(['youtube-cache-bodies','youtube-api-bodies'],root=root)
        auxiliary += [(name,(Path(root)/'model/sql'/(file+'.sql')).read_text(),keys,dictionary) for name,file,keys,dictionary in EXPLORER_TABLES]
        from congress_api.lake.committee_records import CANDIDATE_SQL
        explorer_diagnostics=[dict(name='explorer_invariants',sql=f"""SELECT (SELECT count(*) FROM meeting_coverage_export)-5*(SELECT count(*) FROM meetings_export) AS coverage_row_mismatch,
            (SELECT count(*) FROM meeting_coverage_export WHERE state='present' AND count=0) AS coverage_present_without_rows,
            (SELECT count(*) FROM (SELECT record_sha FROM youtube_cache_bodies UNION SELECT record_sha FROM youtube_api_bodies) b WHERE b.record_sha NOT IN ({explorer_settled_sql('video_records')})) AS unsettled_video_records,
            (SELECT count(*) FROM ({CANDIDATE_SQL}) c WHERE c.record_sha NOT IN ({explorer_settled_sql('committee_records')})) AS unsettled_committee_records""")]
        meta_explorer=[dict(name='videos_in_several_channels',sql="SELECT count(*) AS videos FROM (SELECT v['video_id'] AS video_id FROM (SELECT unnest(r.videos) AS v FROM selected_video_records r JOIN youtube_cache_bodies b ON encode(r.record_sha,'hex')=b.record_sha WHERE r.source='youtube_cache') GROUP BY v['video_id'] HAVING count(DISTINCT v['handle'])>1)")]
    if prepared.get('historical_recording_matcher'):
        from viewer_publication.historical_recording_matcher import SOURCE_FIELDS
        keys=['source_snapshot_sha256','source_record_ordinal']
        columns=','.join((*SOURCE_FIELDS,*keys))
        auxiliary.append(('historical_recording_matches',f'SELECT {columns} FROM historical_recording_matcher_input',keys,[]))
    auxiliary += [('url_state','SELECT * FROM url_state',['requested_url'],['last_outcome']),
        ('url_variants','SELECT * FROM url_variants',['variant_url','canonical_url'],[]),
        ('retired_links',(Path(root)/'model/sql/retired-links.sql').read_text(),['link_key'],[])]
    extra=[dict(name='document_rows.parquet',path=str(evidence/'document_rows.parquet'),sql='SELECT list_row,doc_key AS document_id,'+','.join(LIST_COLUMNS+DETAIL_COLUMNS)+' FROM details',settings=_settings('whole',['list_row'],footer_limit=4 << 20)),
        dict(name='source_members.parquet',path=str(evidence/'source_members.parquet'),sql="""SELECT DISTINCT o.doc_key AS document_id,o.list_row,
        m.source_id,CASE WHEN m.body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(m.body_sha,1,2)||'/'||m.body_sha||'.gz' END AS body_key,
        m.filename AS effective_filename,m.source_url,c.member_path
        FROM document_members m JOIN document_identities d ON m.component=d.component JOIN ordered o ON d.document_id=o.doc_key
        LEFT JOIN capture_source_contexts c ON m.source_id=c.source_id""",settings=_settings('whole',['document_id','source_id','member_path'],footer_limit=4 << 20))]
    causes={
        'capture_evidence':['receipt_key','receipt_line','capture_index'],
        'record_roles':['receipt_key','receipt_line','capture_index'],
        'capture_sources':['source_id','receipt_key','receipt_line','capture_index'],
        'page_facts':['body_sha'],
        'valid_rendition_members':['group_kind','group_id','source_id','body_sha'],
        'publisher_links':['source_id','page_body','context','link_index','split_position','target_member_path'],
        'current_recoveries':['id','original_url','recovered_filename'],
        'source_filename_readings':['source_id'],
        'source_annotation_publisher':['source_id'],
        'source_annotations':['source_id'],
        'document_bill_decisions':['component','id'],
        'rendition_members':['group_kind','group_id','source_id','body_sha'],
        'edition_bodies':['body_sha'],
        'fingerprint_candidates':['body_sha'],
        'fingerprints':['body_sha']}
    extra.append(dict(name='filename_conflicts.parquet',path=str(evidence/'filename_conflicts.parquet'),
        sql='SELECT * FROM filename_conflicts ORDER BY field,source_id,other_url,other_name',
        settings=_settings('whole',['field','source_id','other_url','other_name'],footer_limit=4 << 20)))
    extra += [dict(name=name+'.parquet',path=str(evidence/(name+'.parquet')),
        sql=("SELECT r.*,r.body_sha AS body_sha256,d.decided_at,d.recovered_url,d.identity_note FROM current_recoveries r LEFT JOIN remaining_recovery_decisions d ON r.decision_id=d.id" if name=='current_recoveries' else 'SELECT * FROM '+name),settings=_settings('whole',keys,footer_limit=4 << 20)) for name,keys in causes.items()]
    prefix_checks=','.join(sql+' AS '+name for name,sql in evidence_checks().items())
    entity_invariant_sql=''
    meta_queries=[input_receipts_query(),probe_selectors_query(root=root),
        # The recorded disposition: a ZIP with no expanded contents stays a document, listed here.
        dict(name='unexpanded_zip_documents',sql="SELECT count(*) AS documents FROM ordered WHERE format='zip'"),
        # The recorded disposition (ct-m878): a landing page that names no saved file has no document;
        # its link key retires with a plain notice. Two multi-part GovInfo packages in 619db5f9e08e.
        dict(name='unplaced_landing_pages',sql="SELECT DISTINCT page_url AS url FROM landing_pages WHERE component IS NULL ORDER BY 1"),
        SAVED_NAME_KINDS,SAVED_NAME_DECISIONS_UNUSED,SAVED_NAME_DECISIONS_UNMET,
        # The recorded reason for each blank filename (ct-yf1c); unexplained_blank_filenames refuses the rest.
        dict(name='blank_filename_reasons',sql=f"SELECT reason,count(*) AS documents FROM ({BLANK_FILENAMES_SQL}) r GROUP BY 1 ORDER BY 1"),
        UNRESOLVED_MEETING_DOCUMENT_URLS,MERGED_RECOVERY_FIELDS,RECOVERY_FILE_AGREEMENT,FILENAME_BOTH_NAMES,
        # Main-content outcomes and page-metadata conflicts per release (ct-c5xf D7); unread is a reading gap.
        dict(name='html_main_content',sql="""SELECT main_content['outcome'] AS outcome,count(*) AS documents,
            count(*) FILTER (WHERE description IS NOT NULL) AS described,
            count(*) FILTER (WHERE coalesce(array_length(page_metadata),0)>0) AS with_metadata
            FROM ordered WHERE format='html' GROUP BY 1 ORDER BY 1"""),
        dict(name='page_metadata_conflicts',sql="""SELECT field,count(*) AS documents FROM (
            SELECT list_row,e['field'] AS field FROM (SELECT list_row,unnest(page_metadata) AS e FROM ordered WHERE format='html')
            GROUP BY list_row,e['field'] HAVING min(e['value'])<>max(e['value'])) GROUP BY field ORDER BY field""")]
    if prepared.get('include_entities'):
        entity_invariant_sql=""",
            (SELECT count(*) FROM (
                SELECT DISTINCT unnest(witness_keys) AS witness_key FROM ordered WHERE witness_keys IS NOT NULL
            ) k WHERE NOT EXISTS (SELECT 1 FROM witnesses_export w WHERE w.witness_key=k.witness_key)) AS missing_witness_keys,
            (SELECT count(*) FROM (
                SELECT DISTINCT unnest(committee_keys) AS system_code FROM ordered WHERE committee_keys IS NOT NULL
                UNION
                SELECT DISTINCT cm['system_code'] AS system_code FROM (
                    SELECT unnest(committees) AS cm FROM meetings_export WHERE committees IS NOT NULL
                ) WHERE cm['system_code'] IS NOT NULL
                UNION
                SELECT DISTINCT system_code FROM rosters_export WHERE system_code IS NOT NULL
            ) k WHERE NOT EXISTS (SELECT 1 FROM committees_export c WHERE c.system_code=k.system_code)) AS missing_committee_keys,
            (SELECT count(*) FROM (
                SELECT DISTINCT bioguide_id FROM rosters_export WHERE bioguide_id IS NOT NULL
            ) k WHERE NOT EXISTS (SELECT 1 FROM members_export m WHERE m.bioguide_id=k.bioguide_id)) AS missing_member_keys,
            (SELECT count(*) FROM (
                SELECT event_id,tr['package_id'] AS package_id FROM (
                    SELECT event_id,unnest(transcripts) AS tr FROM meetings_export WHERE transcripts IS NOT NULL)
                WHERE tr['package_id'] IS NOT NULL  -- printed hearings; committee files and captions carry no package
                GROUP BY event_id,tr['package_id'] HAVING count(*)>1
            )) AS duplicate_transcript_packages"""+''.join(f',\n            {sql} AS {name}' for name,sql in entity_track_checks().items())
        meta_queries += [
            dict(name='appearance_name_key_variants',sql="""WITH stripped AS (
                SELECT occasion,name_key,
                    trim(regexp_replace(
                        regexp_replace(
                            ' '||name_key||' ',
                            '(?i)\\s+(?:(?:dr|mr|ms|mrs|miss|hon|the honorable|rep|sen|prof|gen|lt gen|maj gen|brig gen|adm|rear adm|vice adm|col|lt col|maj|capt|lt|cmdr|sgt|rev|fr|rabbi|amb|sec|gov|mayor|judge|justice|esq|phd|md|jd|jr|sr|ii|iii|iv|v|usa|usn|usaf|usmc|uscg|ret)\\s+)+',
                            ' ','g'
                        ),
                        '\\s+(?:[a-z]\\s+)+',' ','g'
                    )) AS base_key
                FROM appearance_records_resolved
                WHERE name_key IS NOT NULL
            )
            SELECT occasion,base_key,min(name_key) AS first_name_key,max(name_key) AS second_name_key,count(DISTINCT name_key) AS variant_count
            FROM stripped
            WHERE base_key<>''
            GROUP BY occasion,base_key
            HAVING count(DISTINCT name_key)>1
            ORDER BY occasion,base_key"""),
            # Not refusing: transcript-linked packages listed as more than one document. Editions share a
            # version key; any other split is listed for reading and for the publish gates (ct-tk10).
            dict(name='split_transcript_packages',sql="""WITH linked AS (
                SELECT DISTINCT tr['package_id'] AS package_id FROM (
                    SELECT unnest(transcripts) AS tr FROM meetings_export WHERE transcripts IS NOT NULL)
            ), listed AS (
                SELECT d.package_id,o.list_row,o.version_keys FROM linked l JOIN details d ON d.package_id=l.package_id
                JOIN ordered o ON o.list_row=d.list_row
            ), split AS (
                SELECT package_id,count(*) AS documents,
                    count(*) FILTER (WHERE coalesce(array_length(version_keys),0)>0) AS versioned
                FROM listed GROUP BY package_id HAVING count(*)>1
            )
            SELECT package_id,documents,CASE WHEN versioned=documents THEN 'editions' ELSE 'unexplained' END AS basis
            FROM split ORDER BY basis,package_id"""),
            dict(name='senate_cards_without_links',sql="""SELECT record_sha_hex,page_url,name_key,name
            FROM appearance_records_resolved
            WHERE source='senate_page' AND coalesce(array_length(document_urls),0)=0
            ORDER BY record_sha_hex,page_url,name_key"""),
        ]
    if prepared.get('explorer_inputs'):meta_queries+=meta_explorer
    manifest=_execute(inputs,steps,output=output,scratch=scratch,engine=engine,
        # A real file's copy URLs, and a landing page's (ct-m878: its request URL too) on the document it names.
        lookup_extra="""SELECT o.list_row,a.url FROM source_addresses a JOIN (
            SELECT source_id,component FROM document_members WHERE is_real_file
            UNION ALL SELECT source_id,component FROM landing_pages WHERE component IS NOT NULL) m ON a.source_id=m.source_id
            JOIN document_identities d ON m.component=d.component JOIN ordered o ON d.document_id=o.doc_key""",
        metadata_queries=meta_queries,origin=dict(kind='model',gaps=[]),content_files={'capture_profile.json':capture_profile},auxiliary=auxiliary,extra_outputs=extra,
        capture_scope=json.loads((Path(root)/'model/registries/capture-scope.json').read_text()),
        entity_digests=prepared.get('entity_digests'),
        diagnostics=[dict(name='model_invariants',sql=f"""SELECT {prefix_checks},
            (SELECT count(*) FROM model_url_keys WHERE error IS NOT NULL) AS invalid_url_keys,
            (SELECT count(*) FROM recovery_attachment_diagnostics) AS invalid_recovery_attachments,
            (SELECT count(*) FROM body_review_key_conflicts) AS body_key_collisions,
            (SELECT count(*) FROM document_link_key_conflicts) AS review_key_collisions,
            (SELECT count(*) FROM review_value_diagnostics) AS invalid_review_values,
            (SELECT count(*) FROM document_bill_decisions bd
                JOIN document_identities d ON bd.component=d.component JOIN ordered o ON d.document_id=o.doc_key
                WHERE o.package_id IS NOT NULL OR coalesce(array_has_any(o.measure_keys,bd.excluded_measure_keys),false)
                    OR NOT coalesce(array_has_all(o.measure_keys,bd.supported_measure_keys),false)) AS invalid_bill_identity_decisions,
            (SELECT CASE WHEN count(*)=0 THEN 1 ELSE 0 END FROM ordered) AS empty_document_list,
            (SELECT count(*) FROM ({GENERIC_TITLES_SQL}) generic) AS generic_titles,
            (SELECT count(*) FROM ({BLANK_FILENAMES_SQL}) r WHERE r.reason IS NULL) AS unexplained_blank_filenames,
            (SELECT count(*) FROM ({MERGED_RECOVERY_SQL}) g WHERE {' OR '.join('lost_'+flag for flag in LOST_FLAGS)}) AS unaccounted_merged_signal,
            (SELECT count(*) FROM saved_files s JOIN saved_files n ON n.component=s.component AND n.body_sha=s.body_sha
                AND coalesce(n.filename,'')<>'' WHERE s.saved_rank=1 AND coalesce(s.filename,'')='') AS saved_unnamed_with_named_sibling,
            ({CONTRADICTED_OFFICIAL_SAVED_NAMES_SQL}) AS contradicted_official_saved_names,
            (SELECT count(*) FROM (SELECT unnest(alternates) AS alt FROM document_alternates) WHERE alt['size'] IS NULL) AS missing_alternate_sizes,
            (SELECT count(*) FROM (
                SELECT cast(m['event_id'] AS BIGINT) AS event_id
                FROM (
                    SELECT unnest(r.meetings) AS m
                    FROM selected_meeting_records r
                    WHERE r.status='completed' AND r.meetings IS NOT NULL
                )
                WHERE m['event_id'] IS NOT NULL AND nullif(trim(m['chamber']),'') IS NOT NULL
                GROUP BY cast(m['event_id'] AS BIGINT)
                HAVING count(DISTINCT CASE
                    WHEN lower(trim(m['chamber'])) IN ('house','h','house of representatives') THEN 'house'
                    WHEN lower(trim(m['chamber'])) IN ('senate','s') THEN 'senate'
                    WHEN lower(trim(m['chamber'])) IN ('joint','j') THEN 'joint'
                    ELSE lower(trim(m['chamber']))
                END)>1
            )) AS multi_chamber_events,
            (SELECT count(*) FROM (
                SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL
            ) k WHERE k.event_id IS NULL OR NOT EXISTS (SELECT 1 FROM meetings_export m WHERE m.event_id=k.event_id)) AS missing_meeting_keys,
            (SELECT count(*) FROM (
                SELECT unnest(transcripts) AS tr FROM meetings_export WHERE transcripts IS NOT NULL
            ) WHERE CASE WHEN tr['source']='captions'
                -- A caption track is a recording's file, named by video_key, never a listed document.
                THEN tr['video_key'] IS NULL OR tr['list_row'] IS NOT NULL
                ELSE tr['list_row'] IS NULL OR tr['list_row']<0 OR tr['list_row']>=(SELECT count(*) FROM ordered) END) AS invalid_transcript_rows,
            (SELECT count(*) FROM url_keys WHERE list_row IS NULL OR list_row<0 OR list_row>=(SELECT count(*) FROM ordered)) AS invalid_url_rows,
            (SELECT count(*) FROM (
                SELECT vk,min(doc_key) AS doc_key
                FROM (SELECT doc_key,unnest(version_keys) AS vk FROM ordered WHERE version_keys IS NOT NULL)
                GROUP BY vk HAVING count(*)<2
            ) single_vk
            LEFT ANTI JOIN (
                SELECT DISTINCT o.doc_key
                FROM (SELECT doc_key,unnest(link_bodies) AS bh FROM ordered WHERE link_bodies IS NOT NULL) o
                JOIN (
                    SELECT target AS prefix FROM current_reviews WHERE verdict='duplicate_of' AND target IS NOT NULL
                    UNION SELECT value_text AS prefix FROM current_reviews WHERE verdict='duplicate_of' AND value_text IS NOT NULL
                    UNION SELECT substr(left_node,3,16) AS prefix FROM body_review_edges WHERE left_node IS NOT NULL
                    UNION SELECT substr(right_node,3,16) AS prefix FROM body_review_edges WHERE right_node IS NOT NULL
                ) rev ON substr(o.bh,1,16)=rev.prefix
            ) merged_docs ON single_vk.doc_key=merged_docs.doc_key) AS single_doc_version_keys{entity_invariant_sql}"""),
            LANDING_PAGE_INVARIANTS]+explorer_diagnostics+url_state_diagnostics()+completeness_checks(
            catalog_version=catalog_version,
            include_entities=bool(prepared.get('include_entities')),
            meeting_records_version=parser_versions.get('meeting_records') if isinstance(parser_versions,dict) else None,
            appearance_records_version=parser_versions.get('appearance_records') if isinstance(parser_versions,dict) else None,
            root=root))
    return manifest
