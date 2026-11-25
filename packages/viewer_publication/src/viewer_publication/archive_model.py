"""Application-owned policy inputs and native SQL for raw-derived releases."""
import hashlib
import json
import re
from pathlib import Path

from congress_api.lake.receipt_metadata import document_status_sql,empty_body_sql
from congress_api.retention.provenance import json_input,list_of,struct
from viewer_publication.archive_format import NULL_LAKE_MEETING_DOCUMENT_REFERENCES, NULL_MEETING_DOCUMENT_REFERENCES, SPICY_PRODUCER_FAMILIES

ROOT=Path(__file__).parents[4]
REGISTRIES={
    'unusable_downloads':dict(body_sha='Utf8',reason='Utf8',evidence='Utf8'),
    'file_shapes':dict(id='Utf8',pattern='Utf8'),
    'page_signals':dict(id='Utf8',kind='Utf8',pattern='Utf8',number='Int64'),
    'title_rules':dict(id='Utf8',kind='Utf8',pattern='Utf8'),
    'title_overrides':dict(link_key='Utf8',title='Utf8',replaces='Utf8',evidence='Utf8'),
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
    'recovered_file_roles':dict(original_url='Utf8',body_sha='Utf8',role='Utf8',evidence='Utf8',equivalent_body_sha='Utf8'),
    'recording_sources':dict(id='Utf8',kind='Utf8',provider='Utf8',pattern='Utf8',key_template='Utf8',format='Utf8',default_language='Utf8',default_production='Utf8'),
    'congressional_commissions':dict(id='Utf8',name='Utf8',pattern='Utf8',created_by='Utf8',members_serve='Utf8',citation_status='Utf8'),
    'historical_witness_keys':dict(old_key='Utf8',status='Utf8',basis='Utf8',occasion='Utf8',source='Utf8',record_sha='Utf8',source_locator='Utf8',target_occasion='Utf8',evidence='Utf8'),
    'person_decisions':dict(decision_id='Utf8',policy_version='Utf8',action='Utf8',kind='Utf8',witness_key='Utf8',target_key='Utf8',candidate_digest='Utf8',evidence='Utf8'),
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
        rank='Utf8',
        credentials='Utf8',
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
    # The print's own MODS committee codes (congCommittee authorityId) and committee members (congMember role
    # COMMMEMBER, bioGuideId): read by the committee opening-statement rule (ct-kw85, witness_member_committees).
    committees=list_of('Utf8'),
    committee_members=list_of('Utf8'),
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
        bioguide_id='Utf8',name_first='Utf8',name_middle='Utf8',name_last='Utf8',name_suffix='Utf8',
        name_nickname='Utf8',name_official_full='Utf8',
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
        nomination_id='Utf8',
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
SPICY_SCHEMAS['spicy_roll_call_votes']['documents']=list_of(struct(congress='Int64',name='Utf8',nomination_id='Utf8',number='Utf8',short_title='Utf8',title='Utf8',type='Utf8'))

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
            committees=[str(c) for c in row.get('committees') or ()],
            committee_members=[str(m) for m in row.get('committee_members') or ()],
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


RECOVERED_FILE_ROLES=('source_page','edition','same_document','undecided')


def _validate_recovered_file_roles(rows):
    """One reviewed role per (dead link, recovered body), the key of a provenance recovery decision (ct-u9y4):
    a misspelled role would act as no review, and a repeated pair would make the role ambiguous."""
    roles={}
    for row in rows:
        pair=(row.get('original_url'),row.get('body_sha'))
        if (not isinstance(pair[0],str) or not pair[0] or not isinstance(pair[1],str) or re.fullmatch('[0-9a-f]{64}',pair[1]) is None
                or pair in roles or row.get('role') not in RECOVERED_FILE_ROLES or not row.get('evidence')):
            raise ValueError('Invalid or duplicate reviewed recovered file role: '+str(pair))
        roles[pair]=row['role']
    paired=set()
    for row in rows:
        if 'equivalent_body_sha' not in row:
            continue
        original,body,peer=row['original_url'],row['body_sha'],row['equivalent_body_sha']
        pair,other=(original,body),(original,peer)
        if (not isinstance(peer,str) or body==peer or roles[pair]!='same_document'
                or roles.get(other)!='same_document' or pair in paired or other in paired):
            raise ValueError('Invalid or duplicate reviewed recovery equivalence: '+str(pair))
        paired.update((pair,other))


def _validate_title_overrides(rows):
    """Hand corrections (title design Q3): one per document link key, each naming its title, the title it replaced and its
    evidence, so a later rule change can show a correction is stale (titles.sql applies them first)."""
    keys=set()
    for row in rows:
        key=row.get('link_key')
        if (set(row)!={'link_key','title','replaces','evidence'} or not isinstance(key,str) or re.fullmatch('[0-9a-f]{16}',key) is None
                or key in keys or any(not isinstance(row[k],str) or not row[k].strip() or row[k]!=row[k].strip() for k in ('title','evidence'))
                or row['replaces'] is not None and not isinstance(row['replaces'],str)):
            raise ValueError('Invalid or duplicate title override: '+str(key))
        keys.add(key)


def _validate_historical_witness_keys(rows):
    seen=set()
    for row in rows:
        key=row.get('old_key');status=row.get('status')
        unamb=status=='unambiguous'
        if (not isinstance(key,str) or re.fullmatch('[0-9a-f]{16}',key) is None or key in seen
                or status not in ('unambiguous','unresolved')
                or (row.get('basis')=='occurrence' if unamb else row.get('basis') is None) is False
                or not row.get('occasion') or not row.get('source') or not row.get('evidence')
                or re.fullmatch('[0-9a-f]{64}',str(row.get('record_sha'))) is None
                or not row.get('source_locator')
                or (bool(row.get('target_occasion')) != unamb)):
            raise ValueError('Invalid or duplicate reviewed historical witness key: '+str(key))
        seen.add(key)


def _validate_person_decisions(rows):
    seen=set()
    for row in rows:
        did=row.get('decision_id');action=row.get('action');kind=row.get('kind')
        if (not isinstance(did,str) or not did.strip() or did in seen
                or action not in ('accepted','rejected','revoked')
                or (action!='revoked' and kind not in ('merge','split','hide'))
                or not row.get('policy_version') or not row.get('evidence')):
            raise ValueError('Invalid or duplicate reviewed person decision: '+str(did))
        seen.add(did)


def _validate_unusable_downloads(rows):
    _refuse_ambiguous_reviews(rows,'download decision','body_sha','body_sha',lambda row: not row.get('reason'))


REVIEWED_REGISTRIES={'unusable_downloads':_validate_unusable_downloads,
    'bill_package_evidence':_validate_bill_evidence,'saved_name_decisions':_validate_saved_name_decisions,
    'recovered_file_roles':_validate_recovered_file_roles,'title_overrides':_validate_title_overrides,
    'historical_witness_keys':_validate_historical_witness_keys,'person_decisions':_validate_person_decisions}


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
    if recovered_copies:
        # A verified equivalent copy can later become a real file. Join the two body nodes only
        # when both are eligible recovered-copy matches for this exact original source.
        steps[-1]['sql']+=""" UNION SELECT 'b:'||e.body_sha,'b:'||s.body_sha
          FROM recovered_copy_links e JOIN recovered_copy_links s
          ON e.source_id=s.source_id AND e.equivalent_shown_body_sha=s.body_sha
          WHERE e.equivalent_shown_body_sha IS NOT NULL"""
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
        'house-floor-feed-readings','page-contexts','link-inputs']
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


# A title that is only format, size and download words, checked apart from the title-rules
# link_word entries that the title rule uses: delete a small vocabulary and every non-letter, and
# nothing may remain. "PDF (48.1 MB)" and "Download XML (6KB)" are generic; "Overview" is not.
# A title with no letter in any script is no title, whatever its length (review finding 7: that class
# came only from the rule's own link_word_no_name pattern).
GENERIC_TITLE_SQL="""(o.title IS NOT NULL AND (NOT regexp_like(o.title,'\\p{L}') OR regexp_like(o.title,'[A-Za-z]') AND regexp_replace(lower(o.title),
 '(download|view|click|here|link|pdf|zip|xml|html?|docx?|txt|json|csv|xlsx?|pptx?|kb|mb|gb|bytes?)|[^a-z]','','g')=''))"""

# Listed documents whose title is a link word by the title-rules registry (the rule titles use)
# or by GENERIC_TITLE_SQL (an independent small vocabulary): either one refuses the release.
# The 64-character bound is the rule's (source-annotations-pages.sql): a longer page title that
# starts like a link word is a real title ("Click Here: Accessible Federal Technolog… | Senate
# Committee On Aging", a 2022 hearing).
GENERIC_TITLES_SQL=f"""SELECT DISTINCT o.doc_key,o.title FROM ordered o
 LEFT JOIN (SELECT pattern FROM title_rules WHERE kind='link_word') g
  ON length(o.title)<=64 AND regexp_like(regexp_replace(trim(o.title),'\\s+',' ','g'),g.pattern)
 WHERE g.pattern IS NOT NULL OR {GENERIC_TITLE_SQL}"""

# ct-m878, refusing: no address a landing-URL rule matches is a published document's saved address
# (judged on the published rows by the registry, apart from the role step); every landing page
# that names a saved file is an unsaved address of the document that took it; and no landing-URL
# address the fold never admitted (a role other than wrapper, no name, a last segment that is no
# GovInfo ID) is lost: the last count starts from the members, not landing_pages, so it sees what the
# rule left out (review finding 3). An error page or an unread page (no role) at such an address is
# no landing page by the general role rules, which url_state and the reading counts see, so it is
# not counted. Its lookup keys come from the same rows through lookup_extra. A
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
  JOIN document_members m ON regexp_like(m.source_url,r.pattern) AND m.record_role<>'error_response'
  LEFT ANTI JOIN landing_pages l ON l.source_id=m.source_id) d
  LEFT ANTI JOIN source_rows s ON s.url=d.url) AS lost_landing_addresses""")


# ct-u9y4 item 4, refusing (owner, 2026-11-11). 25 documents whose recovered files' text differs, and 93 whose text the
# model cannot read (PDFs), shipped in 77673bfb8fcf with only a report (recovery_documents_with_several_files); the
# 56 unrelated documents under one dead link of 619db5f9e08e were of that kind. A document holding several recovered
# files needs every one reviewed (recovered-file-roles.json) unless their text is equal (one document, DM 7.5); and a
# review may not take every file from its link (all a page or editions), which would leave the link's key no file.
# Only the bodies of documents with several files are grouped: one row per (document, body) first, never a grouped
# count(DISTINCT) (AGENTS.md).
RECOVERED_FILE_INVARIANTS=dict(name='recovered_file_invariants',sql="""SELECT
 (SELECT count(*) FROM (
  SELECT b.component FROM (SELECT component,body_sha,bool_and(role IS NOT NULL) AS reviewed FROM saved_recoveries GROUP BY component,body_sha) b
  LEFT JOIN fingerprints f ON f.body_sha=b.body_sha GROUP BY b.component
  HAVING count(*)>1 AND (count(f.fingerprint)<count(*) OR min(f.fingerprint)<>max(f.fingerprint)) AND NOT bool_and(b.reviewed))) AS several_files_unreviewed,
 (SELECT count(*) FROM (SELECT original_url FROM final_recovery_attachments GROUP BY original_url
  HAVING bool_and(coalesce(role IN ('source_page','edition'),false)))) AS links_without_a_file""")
# Reviewed roles that name no recovery of this build (metadata, as saved_name_decisions_unused).
RECOVERED_FILE_ROLES_UNUSED=dict(name='recovered_file_roles_unused',sql="""SELECT count(*) AS entries FROM recovered_file_roles v
 LEFT ANTI JOIN final_recovery_attachments r ON r.original_url=v.original_url AND r.body_sha=v.body_sha""")


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
  SELECT g.source_id,c.original_url,c.body_sha,bool_or(r.list_row IS NOT NULL OR coalesce(v.role IN ('source_page','edition'),false)) AS moved
  FROM merged g JOIN current_recoveries c ON c.original_url=g.source_url
  LEFT JOIN recovery_documents r ON r.list_row=g.list_row AND r.original_url=c.original_url AND encode(r.body,'hex')=c.body_sha
  -- ct-u9y4: the dead page's own capture is accounted by its address (addressed), an edition by its own row.
  LEFT JOIN recovered_file_roles v ON v.original_url=c.original_url AND v.body_sha=c.body_sha
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


# No transcript_headings input: no print has a transcript read, so the transcript decides nothing (ct-sfra).
TRANSCRIPT_HEADINGS_UNAVAILABLE = """SELECT arrow_cast(NULL,'FixedSizeBinary(32)') AS record_sha,
 cast(NULL AS VARCHAR) AS parser_version,cast(NULL AS VARCHAR) AS status,cast(NULL AS VARCHAR) AS error_type,
 cast(NULL AS VARCHAR) AS source,array_slice(make_array(named_struct('kind',cast(NULL AS VARCHAR),'name',cast(NULL AS VARCHAR),
 'family',cast(NULL AS VARCHAR),'given',cast(NULL AS VARCHAR),'style',cast(NULL AS VARCHAR),'line',cast(NULL AS INT))),1,0) AS entries
 WHERE false"""


def transcript_steps(*,root=ROOT):
    """ct-sfra: the MODS rows the print's own transcript decides, its entries for their prints, and what it says of each
    row; the capture predicates are the transcript_headings producer's own."""
    from congress_api.lake.transcript_headings import GOOD_FETCH_CAPTURE_SQL,TRANSCRIPT_ADDRESS,TRANSCRIPT_CAPTURE_SQL
    entries=((Path(root)/'model/sql/witness-transcript-entries.sql').read_text()
        .replace('{{TRANSCRIPT_ADDRESS}}',TRANSCRIPT_ADDRESS).replace('{{GOOD_FETCH}}',GOOD_FETCH_CAPTURE_SQL)
        .replace('{{TRANSCRIPT_CAPTURE}}',TRANSCRIPT_CAPTURE_SQL))
    return _sql_steps(['name-fold','witness-transcript-rows'],root=root)+[
        dict(name='witness_transcript_entries',sql=entries,materialize=True)]+_sql_steps(['witness-transcript-facts'],root=root)


def selected_record_step(table,record_input,*,root=ROOT):
    """The one version selection each record table's readers share, in both dialects' place."""
    sql=(Path(root)/'model/sql/selected-records.sql').read_text().replace('{{TABLE}}',table).replace('{{INPUT}}',record_input)
    return dict(name='selected_'+table,sql=sql,materialize=True)


def meeting_steps(*,root=ROOT,has_document_references=True):
    """Select once, merge once, then resolve: CTEs are inlined per reader, so these must be steps."""
    steps=_sql_steps(['meeting-records-observed','meeting-records-ranked','meeting-records-current',
        'congress-gov-meeting-history','congress-gov-retained-items','meeting-records-merged'],root=root)
    if not has_document_references:
        steps[0]['sql']=steps[0]['sql'].replace("m['document_references'] AS document_references",
            NULL_LAKE_MEETING_DOCUMENT_REFERENCES + " AS document_references")
    return steps+[dict(name='meetings_resolved',sql=(Path(root)/'model/sql/meeting-records-resolved.sql').read_text(),materialize=True)]


def meeting_detail_steps(*,root=ROOT):
    """Bind individual receipts before selecting event-specific read observations."""
    return _sql_steps(['congress-gov-routes','meeting-detail-evidence','meeting-detail-ranked',
        'meeting-detail-observations'],root=root)


def meeting_records_have_document_references(path):
    import pyarrow.parquet as pq
    schema=pq.read_schema(path)
    return schema.field('meetings').type.value_type.get_field_index('document_references') >= 0


def appearance_records_have_rank_credentials(value,*,root=ROOT):
    if value is None or isinstance(value,(list,tuple)):
        return True
    if isinstance(value,dict) and any(
            old in str(value.get('metadata_location') or '')
            for old in ('appearance_records_mvp_20261105','appearance_records_committees_20261111')):
        return False
    parquet_path=value.get('path') if isinstance(value,dict) and value.get('kind')=='parquet' else (value if isinstance(value,(str,Path)) else None)
    if parquet_path is not None and Path(parquet_path).is_file():
        import pyarrow.parquet as pq
        schema=pq.read_schema(parquet_path)
        if 'appearances' not in schema.names:
            return False
        elem=schema.field('appearances').type.value_type
        return elem.get_field_index('rank') >= 0 and elem.get_field_index('credentials') >= 0
    if isinstance(value,dict) and value.get('kind')=='native_table':
        meta_loc=value.get('metadata_location') or ''
        meta_path=Path(meta_loc) if meta_loc and not meta_loc.startswith(('s3://','http://','https://')) else None
        if meta_path is not None and meta_path.is_file():
            meta=json.loads(meta_path.read_text())
            sid=value.get('schema_id',meta.get('current-schema-id'))
            schemas=meta.get('schemas') or []
            chosen=next((s for s in schemas if s.get('schema-id')==sid),schemas[-1] if schemas else meta)
        else:
            chosen=json.loads((Path(root)/'model/lake/appearance-records.schema.json').read_text())
        app_field=next((f for f in chosen.get('fields',()) if f.get('name')=='appearances'),None)
        elem_fields={f.get('name') for f in ((app_field or {}).get('type') or {}).get('element',{}).get('fields',())}
        return {'rank','credentials'}<=elem_fields
    return True


EMPTY_RECORDINGS_SQL="""SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)') AS event_ids,
 array_slice(make_array(named_struct('body',arrow_cast(NULL,'FixedSizeBinary(32)'),'suffix',cast(NULL AS VARCHAR),'format',cast(NULL AS VARCHAR),
  'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0) AS tracks,cast(NULL AS VARCHAR) AS recording_scope WHERE false"""
EMPTY_RECORDING_PAGE_VIDEO_EVENTS_SQL="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS VARCHAR) AS video_key,cast(NULL AS BIGINT) AS event_id,cast(NULL AS INT) AS route_priority,cast(NULL AS VARCHAR) AS link_rule,cast(NULL AS VARCHAR) AS match_note WHERE false"
EMPTY_RECORDING_PAGE_EVENT_LINKS_SQL="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS BIGINT) AS event_id,cast(NULL AS DATE) AS meeting_date,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS title_words WHERE false"
RECORDING_MATCH_STOPWORDS_SQL="""SELECT make_array(
 '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
 'hearing','hearings','subcommittee','committee','house','united','states','congress','washington','full','open','closed','public',
 'session','examine','examining','review','oversight','part','http','https','www','gov','html','htm','aspx','events','event','calendar',
 'eventsingle','eventid','democrats','republicans','markups','markup','business','meeting','entitled','legislative','office'
) AS sw"""
RECORDING_TOPIC_STOPWORDS_SQL="""SELECT make_array(
 '','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that',
 'hearing','subcommittee','committee','house','senate','united','state','congres','congressional','washington',
 'full','open','closed','public','session','examine','examining','examination','review','reviewing','oversight','part',
 'http','www','gov','html','htm','aspx','event','calendar','eventsingle','eventid','democrat','democratic','republican',
 'markup','busines','meeting','entitled','titled','legislative','legislation','office','virtual','hybrid','remote','joint','select','special',
 'field','live','stream','livestream','video','webcast','archived','archive','member','day','pending','variou','measure','bill','one','draft','discussion',
 'act','title','code','amend','purpose','other','certain','relating','provide','direct','secretary','department','agency','administration','federal','national',
 'american','america','fiscal','year','budget','request','prioritie','priority','perspective','stakeholder','update','statu','future','current'
) AS words,
make_array('january','february','march','april','may','june','july','august','september','october','november','december') AS full_m,
make_array('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec') AS abbr_m"""
VIDEO_KEY_ALIASES_SQL="""WITH raw_meeting_videos AS (
 SELECT m.event_id,m.video_url AS url,m.explicit_key,
  min(regexp_replace((regexp_match(m.video_url,rs.pattern))[1],'^(.+)$',rs.key_template)) AS extracted_key
 FROM recording_url_sources rs
 RIGHT JOIN (
  SELECT event_id,v['url'] AS video_url,nullif(trim(v['video_key']),'') AS explicit_key
  FROM (SELECT event_id,unnest(videos) AS v FROM meetings_resolved WHERE videos IS NOT NULL)
 ) m ON m.video_url IS NOT NULL AND regexp_like(m.video_url,rs.pattern)
 GROUP BY m.event_id,m.video_url,m.explicit_key
)
SELECT extracted_key AS alias_key,min(explicit_key) AS canonical_key
FROM raw_meeting_videos
WHERE extracted_key IS NOT NULL AND explicit_key IS NOT NULL AND extracted_key<>explicit_key
GROUP BY extracted_key"""


def known_meetings_sql(document_relation='normalized'):
    return f"""SELECT k.event_id,r.meeting_date,r.not_held,r.meeting_type,r.title,r.committees,
 coalesce(arrow_cast(r.subject_keys,'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys
FROM meetings_resolved r
RIGHT JOIN (
 SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM {document_relation} WHERE meeting_keys IS NOT NULL
 UNION
 SELECT DISTINCT event_id FROM meetings_resolved WHERE event_id IS NOT NULL
) k ON r.event_id=k.event_id
WHERE k.event_id IS NOT NULL"""


RECORDING_PAGE_EVENT_LINKS_SQL="""WITH raw_links AS (
 SELECT DISTINCT page_body,event_id FROM (
  SELECT vp.page_body,
   try_cast(coalesce(
    (regexp_match(l.target_url,'(?i)docs[.]house[.]gov/[^\\s"''<>]*[?&]eventid=0*(1[0-9]{5})\\b'))[1],
    (regexp_match(l.target_url,'(?i)congress[.]gov/event/[0-9]+(?:st|nd|rd|th)?(?:-congress)?/house-event/0*(1[0-9]{5})\\b'))[1]
   ) AS BIGINT) AS event_id
  FROM recording_video_pages vp
  JOIN resolved_link_targets l ON l.page_body=vp.page_body
  WHERE l.target_url IS NOT NULL
   AND regexp_like(l.target_url,'(?i)(?:docs[.]house[.]gov/[^\\s"''<>]*[?&]eventid=|congress[.]gov/event/[0-9]+(?:st|nd|rd|th)?(?:-congress)?/house-event/)0*1[0-9]{5}\\b')
 ) x WHERE event_id IS NOT NULL
), meeting_words AS (
 SELECT m.event_id,m.meeting_date,
  array_distinct(array_except(
   string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')),'[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{1,2}\\b',' ','g')),' '),
   sw.sw
  )) AS title_words
 FROM meetings_resolved m
 CROSS JOIN recording_match_stopwords sw
 WHERE m.event_id IS NOT NULL
)
SELECT l.page_body,l.event_id,mw.meeting_date,
 coalesce(arrow_cast(mw.title_words,'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS title_words
FROM meeting_words mw
RIGHT JOIN raw_links l ON mw.event_id=l.event_id"""
RECORDING_PAGE_MEETINGS_SQL="""WITH raw_routes AS (
 SELECT vp.page_body,unnest(pf.named_meetings) AS event_id,
  cast(0 AS INT) AS route_priority,
  cast('page_named_meeting' AS VARCHAR) AS link_rule,
  cast('page_named_meeting' AS VARCHAR) AS match_note
 FROM recording_video_pages vp JOIN page_facts pf ON pf.body_sha=vp.body_sha
 WHERE pf.status='completed' AND pf.named_meetings IS NOT NULL
 UNION ALL
 SELECT DISTINCT vps.page_body,try_cast(a.meeting_key AS BIGINT) AS event_id,
  cast(1 AS INT) AS route_priority,
  cast('source_annotation' AS VARCHAR) AS link_rule,
  cast('source_annotation' AS VARCHAR) AS match_note
 FROM recording_page_sources vps JOIN source_annotation_addresses a ON a.source_id=vps.source_id
 WHERE try_cast(a.meeting_key AS BIGINT) IS NOT NULL
 UNION ALL
 SELECT vp.page_body,s.event_id,
  cast(2 AS INT) AS route_priority,
  cast('senate_page' AS VARCHAR) AS link_rule,
  cast('senate_page' AS VARCHAR) AS match_note
 FROM recording_video_pages vp JOIN senate_page_meeting_links s ON s.record_sha_hex=vp.page_body
 UNION ALL
 SELECT page_body,event_id,
  CASE link_rule
   WHEN 'house_doc_link' THEN cast(3 AS INT)
   WHEN 'house_title_words' THEN cast(4 AS INT)
   WHEN 'house_title_and_full_words' THEN cast(5 AS INT)
   WHEN 'house_text_head_strong' THEN cast(6 AS INT)
   WHEN 'house_single_day_title' THEN cast(7 AS INT)
   WHEN 'house_single_day_generic' THEN cast(8 AS INT)
   ELSE cast(9 AS INT)
  END AS route_priority,
  link_rule,
  match_note
 FROM house_page_meeting_links
), ranked AS (
 SELECT page_body,event_id,route_priority,link_rule,match_note,
  row_number() OVER (PARTITION BY page_body,event_id ORDER BY route_priority ASC,match_note ASC) AS rn
 FROM raw_routes
 WHERE event_id IS NOT NULL
)
SELECT page_body,event_id,route_priority,link_rule,match_note
FROM ranked
WHERE rn=1"""
RECORDING_PAGE_VIDEO_EVENTS_SQL="""SELECT DISTINCT pvl.page_body,pvl.extracted_key AS video_key,pm.event_id,
 pm.route_priority,pm.link_rule,pm.match_note
FROM recording_page_meetings pm JOIN recording_video_links pvl ON pvl.page_body=pm.page_body
WHERE pvl.extracted_key IS NOT NULL AND pm.event_id IS NOT NULL"""


def recording_match_prep_steps(*,videos_relation='videos_export',include_stopwords=False):
    """Materialize reusable recording-match sub-relations once per step so entity-recording-matches.sql
    evaluates no CTE more than once (AGENTS.md: a CTE runs once per reference)."""
    steps=[]
    if include_stopwords:
        steps.append(dict(name='recording_match_stopwords',sql=RECORDING_MATCH_STOPWORDS_SQL,materialize=True))
    steps += [
        dict(name='recording_topic_stopwords',sql=RECORDING_TOPIC_STOPWORDS_SQL,materialize=True),
        dict(name='recording_publisher_match_rows',sql="""WITH publisher AS (
         SELECT event_id,unnest(videos) AS v FROM meetings_resolved
        )
        SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(p.event_id AS VARCHAR) AS subject_id,
         p.event_id,cast(NULL AS VARCHAR) AS package_id,
         coalesce(a.canonical_key,p.v['video_key']) AS video_key,p.v['url'] AS url,
         cast('publisher_link' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
         cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
         cast(NULL AS VARCHAR) AS note,cast('meetings.videos' AS VARCHAR) AS source_ref
        FROM video_key_aliases a
        RIGHT JOIN publisher p ON a.alias_key=p.v['video_key']""",materialize=True),
        dict(name='recording_page_video_facts',sql=f"""SELECT DISTINCT
         video_key,pub_date,v_parent,
         coalesce(
          CASE WHEN v_iso IS NOT NULL THEN try_cast(v_iso[1] AS DATE) END,
          CASE WHEN v_mdy IS NOT NULL THEN try_cast(v_mdy[3]||'-'||lpad(v_mdy[1],2,'0')||'-'||lpad(v_mdy[2],2,'0') AS DATE) END,
          CASE WHEN v_spc IS NOT NULL THEN try_cast(v_spc[3]||'-'||v_spc[1]||'-'||v_spc[2] AS DATE) END,
          CASE WHEN v_ymd8 IS NOT NULL THEN try_cast(v_ymd8[1]||'-'||v_ymd8[2]||'-'||v_ymd8[3] AS DATE) END,
          CASE WHEN v_mdy6 IS NOT NULL THEN try_cast('20'||v_mdy6[3]||'-'||v_mdy6[1]||'-'||v_mdy6[2] AS DATE) END,
          CASE WHEN v_full IS NOT NULL THEN try_cast(v_full[3]||'-'||lpad(cast(array_position(full_m,lower(v_full[1])) AS VARCHAR),2,'0')||'-'||lpad(v_full[2],2,'0') AS DATE) END,
          CASE WHEN v_abbr IS NOT NULL THEN try_cast(v_abbr[3]||'-'||lpad(cast(array_position(abbr_m,substr(lower(v_abbr[1]),1,3)) AS VARCHAR),2,'0')||'-'||lpad(v_abbr[2],2,'0') AS DATE) END
         ) AS v_date,
         is_markup_video,is_roundtable_video,is_hearing_or_markup_video,
         has_explicit_event_id_in_title,is_generic_video_title,has_explicit_topic,
         says_subcommittee,says_full_committee,v_acronym,
         video_words,topic_v_words,topic_vd_words
        FROM (
         SELECT
          v.video_key,
          try_cast(v.published_at AS DATE) AS pub_date,
          CASE WHEN v.system_code IS NOT NULL AND trim(v.system_code)<>'' THEN
           (CASE WHEN substr(lower(trim(v.system_code)),1,4)='jsec' THEN 'jjec' ELSE substr(lower(trim(v.system_code)),1,4) END)
          END AS v_parent,
          tsw.full_m,tsw.abbr_m,
          regexp_match(coalesce(v.title,''),'\\b(20[0-3][0-9]-[0-9]{{2}}-[0-9]{{2}})\\b') AS v_iso,
          regexp_match(coalesce(v.title,''),'\\b([0-9]{{1,2}})[/.-]([0-9]{{1,2}})[/.-](20[0-3][0-9])\\b') AS v_mdy,
          regexp_match(coalesce(v.title,''),'\\b([01][0-9])\\s+([0-3][0-9])\\s+(20[0-3][0-9])\\b') AS v_spc,
          regexp_match(coalesce(v.title,''),'\\b(20[0-3][0-9])([01][0-9])([0-3][0-9])\\b') AS v_ymd8,
          regexp_match(coalesce(v.title,''),'^\\s*([01][0-9])([0-3][0-9])([0-3][0-9])\\b') AS v_mdy6,
          regexp_match(coalesce(v.title,''),'(?i)\\b(January|February|March|April|May|June|July|August|September|October|November|December)\\s+([0-9]{{1,2}}),?\\s+(20[0-3][0-9])\\b') AS v_full,
          regexp_match(coalesce(v.title,''),'(?i)\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?\\s+([0-9]{{1,2}}),?\\s+(20[0-3][0-9])\\b') AS v_abbr,
          v.title IS NOT NULL AND regexp_like(v.title,'(?i)\\b(markup|organizational\\s+meeting|subcommittee\\s+assignments)\\b') AS is_markup_video,
          v.title IS NOT NULL AND regexp_like(v.title,'(?i)\\bround[- ]?tables?\\b') AS is_roundtable_video,
          v.title IS NOT NULL AND regexp_like(v.title,'(?i)\\b(hearing|markup)\\b') AS is_hearing_or_markup_video,
          v.title IS NOT NULL AND regexp_like(v.title,'(?i)(?:\\bevent\\s*id|\\bid)\\s*[=:#]\\s*0*[0-9]{{5,6}}\\b') AS has_explicit_event_id_in_title,
          v.title IS NULL
           OR cardinality(array_distinct(array_except(
               string_to_array(trim(regexp_replace(regexp_replace(lower(v.title),'[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{{1,2}}\\b',' ','g')),' '),
               sw.sw
              )))=0
           OR (
            NOT regexp_like(
             regexp_replace(lower(v.title),'\\b(?:pending\\s+legislation|various\\s+measures|legislation)\\b','','g'),
             '\\b(?:hearing|hearings|markup|mark-?up|meeting|session)\\s+(?:on|of|to|for|regarding|concerning|about|titled|entitled)\\s+[a-z0-9]'
            )
            AND NOT (
             regexp_like(lower(v.title),'\\s+[-–—]\\s+[a-z]')
             AND NOT regexp_like(lower(v.title),'\\s+[-–—]\\s+(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[.]?\\s+[0-9]|eventid|part\\s+[0-9]|full\\s+committee|subcommittee|the\\s+subcommittee|oversight|legislative|hearing|markup|live)')
            )
            AND (
             regexp_like(trim(v.title),'(?i)^(?:(?:oversight|legislative|public|full\\s+committee|subcommittee|joint|budget|democratic|republican|virtual|hybrid|live)\\s+)*(?:(?:hearing|markup|mark-?up|business\\s+meeting)\\s*(?:\\||[-–—:])\\s*)?(?:(?:the\\s+)?(?:select\\s+)?subcommittee\\s+on\\s+[^:|–—]+|[^:|–—]+\\s+subcommittee|full\\s+committee)(?:\\s*(?:oversight|legislative|public|joint|budget|business)?\\s*(?:hearing|markup|mark-?up|meeting))?(?:\\s*[-–—:,]?\\s*(?:eventid\\s*=\\s*[0-9]+|[0-9]{{1,2}}[./-][0-9]{{1,2}}[./-][0-9]{{2,4}}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[.]?\\s+[0-9]{{1,2}},?\\s+[0-9]{{4}}))*\\s*:?$')
             OR cardinality(array_distinct(array_except(
                 string_to_array(trim(regexp_replace(regexp_replace(
                  regexp_replace(lower(v.title),'(?i)\\b(?:[0-9]{{1,2}}[./:-][0-9]{{1,2}}[./:-][0-9]{{2,4}}|[0-9]{{1,2}}:[0-9]{{2}}\\s*(?:am|pm)|eventid\\s*=\\s*[0-9]+|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[.]?\\s+[0-9]{{1,2}},?\\s+[0-9]{{4}}|part\\s+[0-9]+|full\\s+committee|subcommittee|joint|field|virtual|hybrid|oversight|legislative|public|democratic|republican|business|meeting|markup|mark-?up|hearing|hearings|pending\\s+legislation|various\\s+measures|live)\\b',' ','g'),
                  '[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{{1,2}}\\b',' ','g')),' '),
                 sw.sw
                )))=0
            )
           ) AS is_generic_video_title,
          coalesce(v.duration_seconds,0)>=900
           AND NOT regexp_like(coalesce(v.title,''),'(?i)^\\s*(?:[0-9./-]+\\s*[-:]?\\s*)?(?:(?:subcommittee\\s+on\\s+[a-z0-9 ,&''-]+|[a-z0-9 ,&''-]+\\s+(?:subcommittee|committee)|full\\s+committee)\\s*)?(?:[-|–—:]\\s*)?(?:(?:public|open|legislative|oversight|field|joint|virtual|hybrid|remote)\\s+)*(?:hearing|markup|meeting|live\\s*stream|webcast)(?:\\s*:\\s*pending\\s+legislation)?(?:\\s+[0-9./:-]+\\s*(?:am|pm)?)?\\s*$')
           AND NOT regexp_like(coalesce(v.title,''),'(?i):\\s*pending\\s+legislation\\s*$')
           AND regexp_like(coalesce(v.title,''),'(?i)(?:[:“"”]|\\b(?:hearing|round[- ]?table|forum|briefing)\\s+(?:on|to|re|into|examining|reviewing|assessing)\\b)') AS has_explicit_topic,
          regexp_like(coalesce(v.title,''),'(?i)(?:\\bsubcommittee\\b|\\bo\\s*&\\s*i\\b)') AS says_subcommittee,
          regexp_like(coalesce(v.title,''),'(?i)(?:\\bfull\\s+(?:committee|cmte)\\b|\\bbefore\\s+the\\s+(?:house|senate)\\s+(?:committee\\s+on\\s+)?[a-z &''-]+\\s+committee\\b)')
           AND NOT regexp_like(coalesce(v.title,''),'(?i)\\bsubcommittee\\b') AS says_full_committee,
          (regexp_match(regexp_replace(coalesce(v.title,''),'\\b(?:HEARING|MARKUP|FULL|OPEN|PUBLIC|HYBRID|REMOTE|SELECT|JOINT|HOUSE|SENATE|PART|SUB|AND|THE|FOR|WITH|FROM)\\b',' ','g'),'\\b([A-Z]{{3,6}})\\b'))[1] AS v_acronym,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(v.title,'')),'[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{{1,2}}\\b',' ','g')),' '),
           sw.sw
          )) AS video_words,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(v.title,'')),'[^a-z0-9]+',' ','g'),'\\b(?:[a-z0-9]{{1,2}}|(?:fy)?20[0-9]{{2}}|fy[0-9]{{2}})\\b',' ','g'),'\\b([a-z0-9]{{3,}})s\\b','$1','g')),' '),
           tsw.words
          )) AS topic_v_words,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(v.title,'')||' '||coalesce(v.source_description,'')),'[^a-z0-9]+',' ','g'),'\\b(?:[a-z0-9]{{1,2}}|(?:fy)?20[0-9]{{2}}|fy[0-9]{{2}})\\b',' ','g'),'\\b([a-z0-9]{{3,}})s\\b','$1','g')),' '),
           tsw.words
          )) AS topic_vd_words
         FROM (SELECT DISTINCT video_key FROM recording_page_video_events WHERE video_key IS NOT NULL) k
         JOIN {videos_relation} v ON v.video_key=k.video_key
         CROSS JOIN recording_match_stopwords sw
         CROSS JOIN recording_topic_stopwords tsw
        ) r""",materialize=True),
        dict(name='recording_page_video_stated_overlaps',sql=f"""SELECT
         s.video_key,
         array_sort(array_distinct(array_agg(s.stated_id))) AS stated_event_ids,
         array_sort(array_distinct(array_agg(s.stated_id) FILTER (WHERE m.event_id IS NOT NULL AND NOT coalesce(m.not_held,false)))) AS held_event_ids,
         max(CASE WHEN m.event_id IS NOT NULL THEN cast(1 AS BIGINT) ELSE cast(0 AS BIGINT) END)=1 AS has_known_stated_meeting,
         max(coalesce(cast(cardinality(array_intersect(
          s.video_words,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(m.title,'')||' '||coalesce(array_to_string(m.subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{{1,2}}\\b',' ','g')),' '),
           sw.sw
          ))
         )) AS BIGINT),cast(0 AS BIGINT))) AS max_stated_overlap
        FROM (
         SELECT pf.video_key,pf.video_words,vs.stated_id
         FROM recording_page_video_facts pf
         JOIN (SELECT video_key,unnest(stated_event_ids) AS stated_id FROM {videos_relation}) vs ON pf.video_key=vs.video_key
         WHERE vs.stated_id IS NOT NULL
        ) s
        LEFT JOIN known_meetings m ON m.event_id=s.stated_id
        CROSS JOIN recording_match_stopwords sw
        GROUP BY s.video_key""",materialize=True),
        dict(name='recording_page_meeting_committees',sql="""SELECT event_id,
         array_distinct(array_agg(CASE WHEN substr(code,1,4)='jsec' THEN 'jjec' ELSE substr(code,1,4) END)) AS parent_codes,
         bool_or(regexp_like(code,'00$')) AS has_full,
         bool_or(NOT regexp_like(code,'00$')) AS has_sub,
         bool_or(substr(code,1,2) IN ('hl','ht','sl','sc','sp','jc','jj','js')) AS has_select
        FROM (
         SELECT mc.event_id,lower(trim(mc.c['system_code'])) AS code
         FROM (
          SELECT p.event_id,unnest(m.committees) AS c
          FROM (SELECT DISTINCT event_id FROM recording_page_video_events WHERE event_id IS NOT NULL) p
          JOIN known_meetings m ON m.event_id=p.event_id
          WHERE NOT coalesce(m.not_held,false) AND m.committees IS NOT NULL
         ) mc
         WHERE mc.c['system_code'] IS NOT NULL AND trim(mc.c['system_code'])<>''
        )
        GROUP BY event_id""",materialize=True),
        dict(name='recording_page_match_rows',sql="""WITH page_meeting_raw AS (
         SELECT m.event_id,m.meeting_date,m.meeting_type,m.title,m.subject_keys,
          mc.parent_codes,coalesce(mc.has_full,false) AS has_full,coalesce(mc.has_sub,false) AS has_sub,coalesce(mc.has_select,false) AS has_select,
          sw.sw AS match_sw,tsw.words AS topic_sw,tsw.full_m,tsw.abbr_m,
          regexp_match(coalesce(m.title,''),'\\b(20[0-3][0-9]-[0-9]{2}-[0-9]{2})\\b') AS m_iso,
          regexp_match(coalesce(m.title,''),'\\b([0-9]{1,2})[/.-]([0-9]{1,2})[/.-](20[0-3][0-9])\\b') AS m_mdy,
          regexp_match(coalesce(m.title,''),'(?i)\\b(January|February|March|April|May|June|July|August|September|October|November|December)\\s+([0-9]{1,2}),?\\s+(20[0-3][0-9])\\b') AS m_full,
          regexp_match(coalesce(m.title,''),'(?i)\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?\\s+([0-9]{1,2}),?\\s+(20[0-3][0-9])\\b') AS m_abbr
         FROM recording_page_meeting_committees mc
         RIGHT JOIN (
          SELECT m.event_id,m.meeting_date,m.meeting_type,m.title,m.subject_keys
          FROM (SELECT DISTINCT event_id FROM recording_page_video_events WHERE event_id IS NOT NULL) p
          JOIN known_meetings m ON m.event_id=p.event_id
          WHERE NOT coalesce(m.not_held,false)
         ) m ON mc.event_id=m.event_id
         CROSS JOIN recording_match_stopwords sw
         CROSS JOIN recording_topic_stopwords tsw
        ), page_meeting_facts AS (
         SELECT event_id,meeting_date,parent_codes,has_full,has_sub,has_select,
          lower(coalesce(meeting_type,''))='markup'
           OR regexp_like(coalesce(title,''),'(?i)\\b(markup|business\\s+meeting|organizational|subcommittee\\s+assignments)\\b') AS is_markup_meeting,
          regexp_like(coalesce(meeting_type,'')||' '||coalesce(title,''),'(?i)\\bround[- ]?tables?\\b') AS is_roundtable_meeting,
          regexp_like(coalesce(title,''),'(?i)\\bfield\\s+hearing\\b') AS is_field_hearing,
          coalesce(
           CASE WHEN m_iso IS NOT NULL THEN try_cast(m_iso[1] AS DATE) END,
           CASE WHEN m_mdy IS NOT NULL THEN try_cast(m_mdy[3]||'-'||lpad(m_mdy[1],2,'0')||'-'||lpad(m_mdy[2],2,'0') AS DATE) END,
           CASE WHEN m_full IS NOT NULL THEN try_cast(m_full[3]||'-'||lpad(cast(array_position(full_m,lower(m_full[1])) AS VARCHAR),2,'0')||'-'||lpad(m_full[2],2,'0') AS DATE) END,
           CASE WHEN m_abbr IS NOT NULL THEN try_cast(m_abbr[3]||'-'||lpad(cast(array_position(abbr_m,substr(lower(m_abbr[1]),1,3)) AS VARCHAR),2,'0')||'-'||lpad(m_abbr[2],2,'0') AS DATE) END
          ) AS m_title_date,
          regexp_replace(regexp_replace(lower(regexp_replace(coalesce(title,''),'(?i)\\b(?:the|and|for|with|from|into|over|under|upon|to|in|on|at|by|a|an|of)\\b',' ','g')),'\\b([a-z])[a-z]*\\s*','$1','g'),'[^a-z]','','g')
           ||' '||regexp_replace(regexp_replace(lower(regexp_replace(coalesce(title,''),'(?i)\\b(?:the|and|for|with|from|into|over|under|upon|to|in|on|at|by|a|an)\\b',' ','g')),'\\b([a-z])[a-z]*\\s*','$1','g'),'[^a-z]','','g') AS m_initials,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')||' '||coalesce(array_to_string(subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\\b[a-z0-9]{1,2}\\b',' ','g')),' '),
           match_sw
          )) AS meeting_words,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2}|(?:hr|hres|hjres|hconres|s|sres|sjres|sconres)?[0-9]+)\\b',' ','g'),'\\b([a-z0-9]{3,})s\\b','$1','g')),' '),
           topic_sw
          )) AS topic_m_title_words,
          array_distinct(array_except(
           string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(lower(coalesce(title,'')||' '||coalesce(array_to_string(subject_keys,' '),'')),'[^a-z0-9]+',' ','g'),'\\b(?:[a-z0-9]{1,2}|(?:fy)?20[0-9]{2}|fy[0-9]{2})\\b',' ','g'),'\\b([a-z0-9]{3,})s\\b','$1','g')),' '),
           topic_sw
          )) AS topic_m_words
         FROM page_meeting_raw
        ), page_meeting_candidates AS (
         SELECT p.page_body,p.video_key,p.event_id,p.route_priority,p.link_rule,p.match_note,
          mf.meeting_date,mf.parent_codes,mf.has_full,mf.has_sub,mf.has_select,
          mf.is_markup_meeting,mf.is_roundtable_meeting,mf.is_field_hearing,mf.m_title_date,mf.m_initials,
          mf.meeting_words,mf.topic_m_words,mf.topic_m_title_words
         FROM page_meeting_facts mf
         JOIN recording_page_video_events p ON p.event_id=mf.event_id
         WHERE p.video_key IS NOT NULL AND p.event_id IS NOT NULL
        ), page_evaluated AS (
         SELECT pm.page_body,pm.event_id,pm.video_key,pm.route_priority,pm.link_rule,pm.match_note,
          pm.is_markup_meeting,pm.is_roundtable_meeting,pm.is_field_hearing,
          pm.meeting_date,pm.parent_codes,pm.has_full,pm.has_sub,pm.has_select,
          pm.m_title_date,pm.m_initials,
          cardinality(pm.topic_m_title_words) AS m_title_word_n,
          pv.video_key IS NOT NULL AS has_video,
          coalesce(pv.is_markup_video,false) AS is_markup_video,
          coalesce(pv.is_roundtable_video,false) AS is_roundtable_video,
          coalesce(pv.is_hearing_or_markup_video,false) AS is_hearing_or_markup_video,
          coalesce(pv.has_explicit_event_id_in_title,false) AS has_explicit_event_id_in_title,
          coalesce(pv.is_generic_video_title,true) AS is_generic_video_title,
          pv.pub_date,pv.v_date,pv.v_parent,
          coalesce(pv.has_explicit_topic,false) AS has_explicit_topic,
          coalesce(pv.says_subcommittee,false) AS says_subcommittee,
          coalesce(pv.says_full_committee,false) AS says_full_committee,
          pv.v_acronym,
          coalesce(cast(cardinality(pv.topic_v_words) AS BIGINT),cast(0 AS BIGINT)) AS v_word_n,
          coalesce(arrow_cast(sv.stated_event_ids,'List(Int64)'),arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS stated_event_ids,
          coalesce(sv.has_known_stated_meeting,false) AS has_known_stated_meeting,
          coalesce(sv.max_stated_overlap,cast(0 AS BIGINT)) AS max_stated_overlap,
          CASE WHEN sv.stated_event_ids IS NOT NULL THEN coalesce(array_has(arrow_cast(sv.stated_event_ids,'List(Int64)'),pm.event_id),false) ELSE false END AS states_this_event,
          CASE WHEN sv.held_event_ids IS NOT NULL THEN cardinality(array_except(arrow_cast(sv.held_event_ids,'List(Int64)'),make_array(pm.event_id)))>0 ELSE false END AS states_other_held_event,
          cast(cardinality(array_intersect(
           coalesce(arrow_cast(pv.video_words,'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')),
           pm.meeting_words
          )) AS BIGINT) AS video_meeting_overlap,
          cast(cardinality(array_intersect(
           coalesce(arrow_cast(pv.topic_v_words,'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')),
           pm.topic_m_words
          )) AS BIGINT) AS shared_v_words,
          cast(cardinality(array_intersect(
           coalesce(arrow_cast(pv.topic_vd_words,'List(Utf8)'),arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')),
           pm.topic_m_words
          )) AS BIGINT) AS shared_vd_words
         FROM recording_page_video_stated_overlaps sv
         RIGHT JOIN (
          recording_page_video_facts pv
          RIGHT JOIN page_meeting_candidates pm ON pv.video_key=pm.video_key
         ) ON sv.video_key=pm.video_key
        ), page_disambiguated AS (
         SELECT e.*,
          min(e.event_id) OVER (PARTITION BY e.page_body,e.video_key)<>max(e.event_id) OVER (PARTITION BY e.page_body,e.video_key) AS multi_event_source_page,
          max(e.video_meeting_overlap) OVER (PARTITION BY e.page_body,e.video_key) AS max_page_video_overlap
         FROM page_evaluated e
        ), page_kept AS (
         -- Reject committee-page embeds whose own hearing identity (date, committee, event ID, kind, or title)
         -- contradicts the held hearing they would attach to (ct-414r, ct-9vwc).
         SELECT e.event_id,e.video_key,e.page_body,e.match_note,
          min(e.page_body) OVER (PARTITION BY e.video_key,e.event_id) AS min_page_body,
          row_number() OVER (PARTITION BY e.video_key,e.event_id ORDER BY e.route_priority ASC,e.page_body ASC) AS rn
         FROM page_disambiguated e
         WHERE (NOT e.is_markup_video OR e.is_markup_meeting)
          AND NOT (e.is_roundtable_video AND NOT e.is_roundtable_meeting)
          AND NOT (e.is_roundtable_meeting AND e.is_hearing_or_markup_video AND NOT e.is_roundtable_video)
          AND NOT (
           e.multi_event_source_page
           AND NOT e.is_generic_video_title
           AND e.video_meeting_overlap=0
           AND e.max_page_video_overlap>0
          )
          AND NOT (
           cardinality(e.stated_event_ids)>0
           AND NOT array_has(e.stated_event_ids,e.event_id)
           AND NOT e.is_generic_video_title
           AND (
            (e.video_meeting_overlap=0 AND e.max_stated_overlap>=2)
            OR (e.video_meeting_overlap<=1 AND e.max_stated_overlap>=4)
            OR (e.link_rule IN ('house_title_words','house_title_and_full_words','house_text_head_strong','house_text_head_weak','house_single_day_title','house_single_day_generic')
             AND e.video_meeting_overlap=0
             AND (
              e.has_explicit_event_id_in_title
              OR (e.has_known_stated_meeting AND e.max_stated_overlap>0)
             ))
           )
          )
          AND NOT (
           e.link_rule='house_text_head_weak'
           AND NOT e.is_generic_video_title
           AND e.video_meeting_overlap=0
          )
          AND (
           NOT e.has_video OR (
            (e.pub_date IS NULL OR e.meeting_date IS NULL OR e.pub_date>=e.meeting_date-INTERVAL '30' DAY OR e.states_this_event)
            AND (e.v_date IS NULL OR e.meeting_date IS NULL OR e.v_date=e.meeting_date
             OR (e.m_title_date IS NOT NULL AND e.v_date=e.m_title_date)
             OR e.states_this_event
             OR (e.shared_v_words>=2 AND NOT e.states_other_held_event
              AND ((e.v_date>=e.meeting_date-INTERVAL '14' DAY AND e.v_date<=e.meeting_date+INTERVAL '14' DAY)
               OR substr(cast(e.v_date AS VARCHAR),6,5)=substr(cast(e.meeting_date AS VARCHAR),6,5))))
            AND NOT (e.states_other_held_event AND NOT e.states_this_event
             AND (NOT e.is_generic_video_title OR e.has_explicit_event_id_in_title OR (e.v_date IS NOT NULL AND e.meeting_date IS NOT NULL AND e.v_date<>e.meeting_date))
             AND e.shared_v_words<2)
            AND (e.v_parent IS NULL OR e.parent_codes IS NULL OR array_has(e.parent_codes,e.v_parent) OR e.has_select OR e.states_this_event OR e.shared_v_words>=2)
            AND (e.states_this_event OR e.parent_codes IS NULL OR e.has_select OR e.shared_vd_words>=2
             OR NOT ((e.has_full AND NOT e.has_sub AND NOT e.is_field_hearing AND e.says_subcommittee)
              OR (e.has_sub AND NOT e.has_full AND e.says_full_committee)))
            AND (e.states_this_event OR NOT e.has_explicit_topic OR e.v_word_n<2 OR e.m_title_word_n<2 OR e.shared_vd_words>0
             OR (e.v_acronym IS NOT NULL AND strpos(e.m_initials,lower(e.v_acronym))>0))
           )
          )
        )
        SELECT DISTINCT cast('event' AS VARCHAR) AS subject_kind,cast(e.event_id AS VARCHAR) AS subject_id,
         e.event_id,cast(NULL AS VARCHAR) AS package_id,e.video_key,cast(NULL AS VARCHAR) AS url,
         cast('committee_page' AS VARCHAR) AS basis,cast('linked' AS VARCHAR) AS decision,cast(100 AS SMALLINT) AS score,
         cast('unknown' AS VARCHAR) AS recording_scope,cast('asserted' AS VARCHAR) AS status,
         CASE WHEN e.page_body<>e.min_page_body THEN e.match_note||' [via committee_page:'||e.page_body||']'
          ELSE e.match_note END AS note,
         'committee_page:'||e.min_page_body AS source_ref
        FROM page_kept e
        WHERE e.rn=1""",materialize=True),
        dict(name='recording_linked_packages',sql="""SELECT DISTINCT l.package_id
        FROM (SELECT event_id FROM recording_publisher_match_rows UNION SELECT event_id FROM recording_page_match_rows) p
        JOIN meeting_transcript_links l ON p.event_id=l.event_id""",materialize=True),
    ]
    return steps


def recordings_export_sql(*,root=ROOT,explorer_inputs=False):
    """Derive published recordings.event_ids from recording_matches_export when Explorer inputs are present (ct-yizl)."""
    if explorer_inputs:
        return (Path(root)/'model/sql/entity-recordings-matched.sql').read_text()
    return 'SELECT * FROM recordings_entity'
# A sitting Member acting officially is published as witness_type member_appearance, and a committee member's own
# opening statement as member_statement (ct-kw85): the archive's classification replaces the source's for those rows,
# whose own value stays in the appearance record. The print's own transcript decides who appeared (ct-sfra,
# witness_transcript_facts): a sitting Member's statement it does not seat at the table is a member_statement, and a
# record entry of someone it does seat (and the occasion lists nowhere else) is a witness.
WITNESSES_SQL=('SELECT r.witness_key,r.occasion,r.source,r.record_sha,r.source_locator,r.context_key,r.event_id,r.package_id,r.page_url,'
    'r.name,r.rank,r.credentials,r.position,r.organization,r.on_behalf_of,r.location,r.panel,r.panel_order,r.display_order,'
    "CASE WHEN m.outcome='member' AND t.statement_only THEN 'member_statement' WHEN m.outcome='member' THEN 'member_appearance' "
    "WHEN m.outcome='statement' THEN 'member_statement' WHEN t.promote THEN NULL ELSE r.witness_type END AS witness_type,"
    'r.testified,r.bioguide_id,p.superseded_by,m.matched_bioguide_id,m.match_basis,wp.person_key,'
    'r.listing_status,r.last_listed_on,r.unlisted_since,r.unlisted_by_record_sha '
    'FROM witness_people wp RIGHT JOIN (witness_transcript_facts t RIGHT JOIN (witness_members m RIGHT JOIN '
    '(witness_precedence p RIGHT JOIN appearance_records_resolved r ON p.witness_key=r.witness_key) '
    'ON m.witness_key=r.witness_key) ON t.witness_key=r.witness_key) ON wp.witness_key=r.witness_key')


def appearance_steps(*,root=ROOT,has_rank_credentials=True):
    """Witness URLs, their keys, then the resolved appearances (one owner for the full and frozen builds), and which
    of them are sitting Members of Congress (ct-kw85), after precedence and read only by the exports."""
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
        dict(name='appearance_ranked_sources',sql=(Path(root)/'model/sql/appearance-ranked-sources.sql').read_text(),materialize=True),
        dict(name='congress_gov_witness_history',sql=(Path(root)/'model/sql/congress-gov-witness-history.sql').read_text(),materialize=True),
        dict(name='congress_gov_witness_items',sql=(Path(root)/'model/sql/congress-gov-witness-items.sql').read_text() if has_rank_credentials else
            (Path(root)/'model/sql/congress-gov-witness-items.sql').read_text()
            .replace("nullif(trim(a['rank']),'') AS rank,","cast(NULL AS VARCHAR) AS rank,")
            .replace("nullif(trim(a['credentials']),'') AS credentials,","cast(NULL AS VARCHAR) AS credentials,"),materialize=True),
        dict(name='congress_gov_retained_witnesses',sql=(Path(root)/'model/sql/congress-gov-retained-witnesses.sql').read_text(),materialize=True),
        dict(name='appearance_occurrences',sql=(Path(root)/'model/sql/appearance-occurrences.sql').read_text() if has_rank_credentials else
            (Path(root)/'model/sql/appearance-occurrences.sql').read_text()
            .replace("nullif(trim(a['rank']),'') AS rank,","cast(NULL AS VARCHAR) AS rank,")
            .replace("nullif(trim(a['credentials']),'') AS credentials,","cast(NULL AS VARCHAR) AS credentials,"),materialize=True),
        dict(name='appearance_records_resolved',sql=(Path(root)/'model/sql/appearance-records-resolved.sql').read_text(),materialize=True)]+_sql_steps(
        ['witness-precedence'],root=root)+transcript_steps(root=root)+_sql_steps(['witness-key-map-fresh','witness-key-map',
         'member-terms','witness-member-facts','witness-member-names','witness-member-candidates','witness-member-rows',
         'witness-member-mentions','witness-member-seats','witness-member-tiers','witness-member-decisions'],root=root)+[
        # The pinned rosters as a step: the rosters export and the committee check read the one result.
        dict(name='roster_seats',sql=(Path(root)/'model/sql/entity-rosters.sql').read_text(),materialize=True)]+_sql_steps(
        ['witness-member-committees','witness-members',
         'witness-person-facts','witness-people','entity-people','person-aliases-fresh','person-aliases'],root=root)


ORG_DECISION_FIELDS=dict(id='Utf8',subject='Utf8',verdict='Utf8',object='Utf8',
    note='Utf8',reviewer='Utf8',decided_at='Utf8',supersedes='Utf8')
ORG_TAXONOMY_FIELDS=dict(id='Utf8',label='Utf8',parent_id='Utf8',parent_label='Utf8',
    org_kind='Utf8',priority='Int64',pattern='Utf8')
ORG_ORGANIZATIONS_FIELDS=dict(org_id='Utf8',display_name='Utf8',kind='Utf8',
    taxonomy_parent='Utf8',taxonomy_category='Utf8',parent_org_id='Utf8',
    appearance_count='Int64',bag_keys=list_of('Utf8'),string_keys=list_of('Utf8'),
    anchor='Utf8',has_conflict='Boolean')
ORG_REDIRECTS_FIELDS=dict(old_org_id='Utf8',org_id='Utf8',event='Utf8',release='Utf8')
ORG_WITNESS_ORGS_FIELDS=dict(witness_key='Utf8',field='Utf8',org_id='Utf8',
    bag_key='Utf8',string_key='Utf8',raw_text='Utf8')


def org_entity_inputs(scratch,*,org_decision_files=(),prior_org_release=None,release_label='current',refspec=None,root=ROOT):
    """Prepare native engine inputs for organization entity resolution (ct-6him, ct-w34j)."""
    from congress_api.retention.provenance import field
    from viewer_publication.refspec_inputs import refspec_model_inputs
    work=Path(scratch)/'org_entities'
    work.mkdir(parents=True,exist_ok=True)
    taxonomy_raw=json.loads((Path(root)/'model/registries/ban-park-you-org-taxonomy.json').read_text())['categories']
    taxonomy_rows=[{key:entry.get(key) for key in ORG_TAXONOMY_FIELDS} for entry in taxonomy_raw]
    inputs=[
        json_input(work,'ban_park_you_org_taxonomy',taxonomy_rows,**ORG_TAXONOMY_FIELDS),
        json_input(work,'org_release_meta',[dict(release=str(release_label))],release='Utf8'),
    ]
    refspec_inputs,_pin=refspec_model_inputs(refspec,work)
    inputs += refspec_inputs
    if org_decision_files:
        normalized_files=[
            dict(entry) if isinstance(entry,dict)
            else dict(key=Path(entry).name,path=str(Path(entry).resolve()))
            for entry in org_decision_files
        ]
        inputs.append(dict(
            name='org_decisions',
            kind='json_lines',
            files=normalized_files,
            schema=dict(fields=[field(k,v) for k,v in ORG_DECISION_FIELDS.items()],metadata={}),
        ))
    else:
        inputs.append(json_input(work,'org_decisions',[],**ORG_DECISION_FIELDS))
    prior_map={}
    if isinstance(prior_org_release,dict):
        prior_map=dict(prior_org_release)
    elif prior_org_release is not None:
        prior_dir=Path(prior_org_release).resolve()
        if not prior_dir.exists():
            raise FileNotFoundError(f'Missing prior org release directory: {prior_dir}')
        prior_map={
            'prior_organizations':prior_dir/'organizations.parquet',
            'prior_organization_redirects':prior_dir/'organization_redirects.parquet',
            'prior_witness_organizations':prior_dir/'witness_organizations.parquet',
        }
    for name,fields in [
        ('prior_organizations',ORG_ORGANIZATIONS_FIELDS),
        ('prior_organization_redirects',ORG_REDIRECTS_FIELDS),
        ('prior_witness_organizations',ORG_WITNESS_ORGS_FIELDS),
    ]:
        source=prior_map.get(name)
        if isinstance(source,dict):
            inputs.append(dict(source,name=name))
        elif source is not None and Path(source).is_file():
            inputs.append(dict(name=name,kind='parquet',path=str(Path(source).resolve())))
        else:
            inputs.append(json_input(work,name,[],**fields))
    return inputs


def org_entity_steps(*,root=ROOT):
    """Materialized Phase 1 organization entity resolution steps (ct-6him)."""
    sql_dir=Path(root)/'model/sql'
    return [
        dict(name='org_strings',sql=(sql_dir/'org-strings.sql').read_text(),materialize=True),
        dict(name='org_registry_resolved_orgs',sql=r"""WITH successor_counts AS (
 SELECT original,min(successor) AS successor,count(*) AS cnt
 FROM refspec_current_successors
 GROUP BY original
), single_successors AS (
 SELECT original,successor
 FROM successor_counts
 WHERE cnt=1
)
SELECT
 o.resource_iri AS orig_iri,
 o.fr_id AS orig_fr_id,
 o.name AS orig_name,
 trim(regexp_replace(
  regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(lower(o.name),'&',' and ','g'),
     '\([^)]*\)',' ','g'
    ),
    '[^a-z0-9]+',' ','g'
   ),
   '\b(the|u s|us|united states|of america)\b',' ','g'
  ),
  '\s+',' ','g'
 )) AS orig_norm_key,
 o.short_name AS orig_short_name,
 CASE WHEN o.short_name IS NOT NULL AND o.short_name=upper(o.short_name) THEN o.short_name ELSE NULL END AS orig_upper_short,
 coalesce(s.successor,o.resource_iri) AS resolved_iri,
 t.fr_id,
 t.name,
 t.parent
FROM refspec_organizations o
LEFT JOIN single_successors s ON o.resource_iri=s.original
JOIN refspec_organizations t ON t.resource_iri=coalesce(s.successor,o.resource_iri)""",materialize=True),
        dict(name='org_registry_raw_keys',sql=r"""WITH fr_expanded AS (
 SELECT
  'fr_agency:'||cast(fr_id AS VARCHAR) AS anchor,
  fr_id,
  resolved_iri AS fr_resource,
  'same' AS fr_relation,
  'fr:'||cast(orig_fr_id AS VARCHAR) AS evidence_id,
  name AS canonical_name,
  parent AS parent_fr_iri,
  unnest(make_array(
   named_struct(
    'match_key',orig_norm_key,
    'key_kind','name',
    'raw_acronym',cast(NULL AS VARCHAR),
    'key_priority',1
   ),
   CASE WHEN regexp_like(
    orig_norm_key,
    '^.+? (department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard)$'
   ) THEN named_struct(
    'match_key',regexp_replace(
     orig_norm_key,
     '^(.+?) (department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard)$',
     '\2 of \1'
    ),
    'key_kind','inverted_name',
    'raw_acronym',cast(NULL AS VARCHAR),
    'key_priority',2
   ) END,
   CASE WHEN orig_short_name IS NOT NULL AND length(trim(orig_short_name))>0 THEN named_struct(
    'match_key',trim(regexp_replace(
     regexp_replace(
      regexp_replace(
       regexp_replace(
        regexp_replace(lower(orig_short_name),'&',' and ','g'),
        '\([^)]*\)',' ','g'
       ),
       '[^a-z0-9]+',' ','g'
      ),
      '\b(the|u s|us|united states|of america)\b',' ','g'
     ),
     '\s+',' ','g'
    )),
    'key_kind','short_name',
    'raw_acronym',orig_upper_short,
    'key_priority',4
   ) END
  )) AS kv
 FROM org_registry_resolved_orgs
)
SELECT
 kv['match_key'] AS match_key,
 kv['key_kind'] AS key_kind,
 kv['raw_acronym'] AS raw_acronym,
 anchor,fr_id,fr_resource,fr_relation,evidence_id,canonical_name,parent_fr_iri,
 kv['key_priority'] AS key_priority
FROM fr_expanded
WHERE kv IS NOT NULL AND length(kv['match_key'])>0
UNION ALL
SELECT
 trim(regexp_replace(
  regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(lower(a.name_key),'&',' and ','g'),
     '\([^)]*\)',' ','g'
    ),
    '[^a-z0-9]+',' ','g'
   ),
   '\b(the|u s|us|united states|of america)\b',' ','g'
  ),
  '\s+',' ','g'
 )) AS match_key,
 'alias' AS key_kind,
 cast(NULL AS VARCHAR) AS raw_acronym,
 coalesce('fr_agency:'||cast(r.fr_id AS VARCHAR),'refspec_target:'||a.target) AS anchor,
 r.fr_id,
 r.resolved_iri AS fr_resource,
 coalesce(a.fr_relation,'same') AS fr_relation,
 a.alias_id AS evidence_id,
 coalesce(r.name,initcap(a.name_key)) AS canonical_name,
 r.parent AS parent_fr_iri,
 3 AS key_priority
FROM refspec_aliases a
LEFT JOIN org_registry_resolved_orgs r ON r.orig_iri=a.fr_resource
WHERE coalesce(r.resolved_iri,a.target) IS NOT NULL""",materialize=True),
        dict(name='org_registry_keys',sql="""WITH filtered AS (
 SELECT *
 FROM org_registry_raw_keys
 WHERE length(match_key)>0
  AND (key_kind<>'short_name' OR (length(match_key)>=3 AND match_key NOT IN ('usa','ihs','hope','cia')))
), grouped AS (
 SELECT
  match_key,
  min(anchor) AS min_anchor,
  max(anchor) AS max_anchor,
  (array_agg(key_kind ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS key_kind,
  (array_agg(raw_acronym ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS raw_acronym,
  (array_agg(anchor ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS anchor,
  (array_agg(fr_id ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS fr_id,
  (array_agg(fr_resource ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS fr_resource,
  (array_agg(fr_relation ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS fr_relation,
  (array_agg(evidence_id ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS evidence_id,
  (array_agg(canonical_name ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS canonical_name,
  (array_agg(parent_fr_iri ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS parent_fr_iri,
  (array_agg(key_priority ORDER BY key_priority ASC,coalesce(fr_id,999999999) ASC,evidence_id ASC))[1] AS key_priority
 FROM filtered
 GROUP BY match_key
)
SELECT
 match_key,key_kind,raw_acronym,anchor,fr_id,fr_resource,
 fr_relation,evidence_id,canonical_name,parent_fr_iri,key_priority
FROM grouped
WHERE min_anchor=max_anchor""",materialize=True),
        dict(name='org_registry_segments',sql=r"""WITH raw_text_pieces AS (
 SELECT
  os.string_key,
  os.bag_key,
  trim(regexp_replace(raw_text,'\([^)]*\)',' ','g')) AS cleaned_text
 FROM (
  SELECT string_key,bag_key,unnest(raw_texts) AS raw_text
  FROM org_strings
 ) os
 WHERE raw_text IS NOT NULL AND length(trim(raw_text))>0
), clause_pieces AS (
 SELECT
  string_key,
  bag_key,
  trim(regexp_replace(
   clause,
   '(?:,\s*(?:and\s+)?|\s+and\s+)former(?:ly)?\b.*$',
   '',
   'i'
  )) AS active_clause
 FROM (
  SELECT
   string_key,
   bag_key,
   trim(unnest(string_to_array(
    regexp_replace(
     regexp_replace(cleaned_text,'\s+accompanied by\s+',';','gi'),
     ':',
     ';',
     'g'
    ),
    ';'
   ))) AS clause
  FROM raw_text_pieces
 ) c
 WHERE length(trim(clause))>0
  AND NOT regexp_like(trim(clause),'^(?:and\s+)?former(?:ly)?\b','i')
), split_pieces AS (
 SELECT DISTINCT
  string_key,
  bag_key,
  trim(unnest(array_append(string_to_array(active_clause,','),active_clause))) AS raw_seg
 FROM clause_pieces
 WHERE length(active_clause)>0
), normalized_segments AS (
 SELECT
  string_key,
  bag_key,
  raw_seg,
  trim(regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(
      regexp_replace(lower(raw_seg),'&',' and ','g'),
      '\([^)]*\)',' ','g'
     ),
     '[^a-z0-9]+',' ','g'
    ),
    '\b(the|u s|us|united states|of america)\b',' ','g'
   ),
   '\s+',' ','g'
  )) AS norm_key,
  trim(regexp_replace(
   regexp_replace(
    raw_seg,
    '^(?:the\s+|u\.?s\.?\s+|united states(?:\s+of america)?\s+)+',
    '',
    'gi'
   ),
   '[.\s]+$',
   ''
  )) AS raw_acronym_candidate,
  (
   (
    regexp_like(
     regexp_replace(lower(trim(raw_seg)),'^the\s+',''),
     '^(state|commonwealth|county|town|village|borough|parish) of [a-z]+|^city of [a-z]+'
    )
    AND NOT regexp_like(regexp_replace(lower(trim(raw_seg)),'^the\s+',''),'^(city|district) of washington|^district of columbia')
   )
   OR regexp_like(
    lower(trim(raw_seg)),
    '\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming)\s+(environmental protection agency|epa|department|agency|bureau|commission|board|authority)\b'
   )
  ) AS is_nonfederal_seg
 FROM split_pieces
 WHERE raw_seg IS NOT NULL AND length(trim(raw_seg))>0
), flagged AS (
 SELECT
  string_key,bag_key,raw_seg,norm_key,raw_acronym_candidate,
  bool_or(is_nonfederal_seg) OVER (PARTITION BY string_key) AS has_nonfederal
 FROM normalized_segments
)
SELECT string_key,bag_key,raw_seg,norm_key,raw_acronym_candidate
FROM flagged
WHERE NOT has_nonfederal AND length(norm_key)>0""",materialize=True),
        dict(name='org_registry_matches',sql=(sql_dir/'org-registry-matches.sql').read_text(),materialize=True),
        dict(name='org_bag_registry_matches',sql="""WITH bag_anchor_stats AS (
 SELECT
  m.bag_key,
  m.anchor,
  min(m.fr_id) AS fr_id,
  min(m.fr_resource) AS fr_resource,
  min(CASE WHEN m.fr_relation='same' THEN 0 ELSE 1 END) AS rel_rank,
  min(m.evidence_id) AS evidence_id,
  min(m.canonical_name) AS canonical_name,
  min(m.parent_fr_iri) AS parent_fr_iri,
  sum(s.appearance_count) AS total_apps
 FROM org_registry_matches m
 JOIN org_strings s ON s.string_key=m.string_key
 GROUP BY m.bag_key,m.anchor
), ranked AS (
 SELECT
  bag_key,anchor,fr_id,fr_resource,evidence_id,canonical_name,parent_fr_iri,
  row_number() OVER (
   PARTITION BY bag_key
   ORDER BY rel_rank ASC,total_apps DESC,coalesce(fr_id,999999999) ASC,anchor ASC
  ) AS rn
 FROM bag_anchor_stats
)
SELECT bag_key,anchor,fr_id,fr_resource,evidence_id,canonical_name,parent_fr_iri
FROM ranked
WHERE rn=1""",materialize=True),
        dict(name='org_raw_strings',sql="""SELECT DISTINCT string_key,l2_text,bag_key,unnest(raw_texts) AS raw_text
FROM org_strings""",materialize=True),
        dict(name='org_witness_mentions',sql="""WITH mentions AS (
 SELECT witness_key,m['field'] AS field,m['raw_text'] AS raw_text
 FROM (
  SELECT witness_key,
   unnest(make_array(
    named_struct('field','organization','raw_text',nullif(trim(organization),'')),
    named_struct('field','on_behalf_of','raw_text',nullif(trim(on_behalf_of),''))
   )) AS m
  FROM appearance_records_resolved
 )
 WHERE m['raw_text'] IS NOT NULL
)
SELECT m.witness_key,m.field,m.raw_text,s.string_key,s.l2_text,s.bag_key
FROM org_raw_strings s
JOIN mentions m ON m.raw_text=s.raw_text""",materialize=True),
        dict(name='org_bags',sql="""WITH bag_ranked AS (
 SELECT
  bag_key,string_key,l2_text,display_text,tokens,appearance_count,
  sum(appearance_count) OVER (PARTITION BY bag_key) AS bag_appearances,
  row_number() OVER (PARTITION BY bag_key ORDER BY appearance_count DESC,string_key ASC) AS rn
 FROM org_strings
)
SELECT
 bag_key,string_key,l2_text,display_text,tokens,
 cast(bag_appearances AS BIGINT) AS appearance_count
FROM bag_ranked
WHERE rn=1""",materialize=True),
        dict(name='org_token_df',sql="""SELECT token,cast(count(*) AS BIGINT) AS df
FROM (SELECT unnest(tokens) AS token FROM org_bags WHERE cardinality(tokens)>0)
GROUP BY token""",materialize=True),
        dict(name='org_bag_rarest',sql="""WITH exploded AS (
 SELECT b.bag_key,b.string_key,b.l2_text,b.display_text,b.tokens,b.appearance_count,
  unnest(b.tokens) AS token
 FROM org_bags b
 WHERE cardinality(b.tokens)>0
), ranked AS (
 SELECT e.*,t.df,
  row_number() OVER (PARTITION BY e.bag_key ORDER BY t.df ASC,e.token ASC) AS rn,
  cast(floor(cast(cardinality(e.tokens) AS DOUBLE)*0.25) AS BIGINT)+1 AS prefix_len
 FROM org_token_df t
 JOIN exploded e ON e.token=t.token
 WHERE t.df>=2
)
SELECT bag_key,string_key,l2_text,display_text,tokens,appearance_count,
 token AS rarest_token,df AS rarest_df
FROM ranked
WHERE rn<=prefix_len""",materialize=True),
        dict(name='org_fuzzy_block_stats',sql="""WITH bag_cnt AS (
 SELECT cast(count(*) AS BIGINT) AS distinct_bags FROM org_bags
), indexed_cnt AS (
 SELECT cast(count(*) AS BIGINT) AS indexed_bags FROM (SELECT DISTINCT bag_key FROM org_bag_rarest)
), token_blocks AS (
 SELECT rarest_token,cast(count(*) AS BIGINT) AS bucket_size
 FROM org_bag_rarest
 GROUP BY rarest_token
), agg AS (
 SELECT
  cast(coalesce(max(bucket_size),0) AS BIGINT) AS max_bucket_size,
  cast(coalesce(sum(bucket_size*(bucket_size-1)/2),0) AS BIGINT) AS raw_blocked_pairs
 FROM token_blocks
)
SELECT b.distinct_bags,i.indexed_bags,a.max_bucket_size,a.raw_blocked_pairs
FROM bag_cnt b
CROSS JOIN indexed_cnt i
CROSS JOIN agg a""",materialize=True),
        dict(name='org_decisions_current',sql=(sql_dir/'org-decisions-current.sql').read_text(),materialize=True),
        dict(name='org_fuzzy_pairs',sql=(sql_dir/'org-fuzzy-pairs.sql').read_text(),materialize=True),
        dict(name='org_prior_anchor_map',sql="""WITH unmerged AS (
 SELECT
  'o:'||substr(encode(sha256('org-v1bag:'||bag_key),'hex'),1,16) AS org_node,
  'b:'||bag_key AS bag_node
 FROM org_bags
), prior_bags AS (
 SELECT DISTINCT
  po.org_id,
  unnest(po.bag_keys) AS bag_key
 FROM prior_organizations po
 WHERE po.org_id IS NOT NULL AND po.bag_keys IS NOT NULL
), prior_mapped AS (
 SELECT DISTINCT
  'o:'||pb.org_id AS org_node,
  'b:'||b.bag_key AS bag_node
 FROM org_bags b
 JOIN prior_bags pb ON pb.bag_key=b.bag_key
)
SELECT org_node,bag_node FROM unmerged
UNION
SELECT org_node,bag_node FROM prior_mapped""",materialize=True),
        dict(name='org_edges',sql="""WITH bag_loops AS (
 SELECT 'b:'||bag_key AS left_node,'b:'||bag_key AS right_node
 FROM org_bags
), witness_loops AS (
 SELECT DISTINCT
  d.subject_node AS left_node,
  d.subject_node AS right_node
 FROM org_decisions_current d
 WHERE d.subject_kind='witness'
  AND d.resolution_status IN ('live','remapped')
  AND d.subject_node IS NOT NULL
  AND d.verdict IN ('same','different')
), same_decisions AS (
 SELECT
  d.subject_node,
  d.object_kind,
  d.object_key,
  d.object_node
 FROM org_decisions_current d
 LEFT JOIN org_bags b ON d.object_kind='bag' AND b.bag_key=d.object_key
 WHERE d.verdict='same'
  AND d.resolution_status IN ('live','remapped')
  AND d.subject_node IS NOT NULL
  AND d.object_node IS NOT NULL
  AND (d.object_kind<>'bag' OR b.bag_key IS NOT NULL)
), same_edges AS (
 SELECT subject_node AS left_node,object_node AS right_node
 FROM same_decisions
), active_org_nodes AS (
 SELECT DISTINCT object_node
 FROM same_decisions
 WHERE object_kind='org'
), org_target_edges AS (
 SELECT pm.org_node AS left_node,pm.bag_node AS right_node
 FROM active_org_nodes a
 JOIN org_prior_anchor_map pm ON pm.org_node=a.object_node
), registry_edges AS (
 SELECT 'b:'||bag_key AS left_node,'r:'||anchor AS right_node
 FROM org_bag_registry_matches
)
SELECT left_node,right_node FROM bag_loops
UNION ALL
SELECT left_node,right_node FROM witness_loops
UNION ALL
SELECT left_node,right_node FROM same_edges
UNION ALL
SELECT left_node,right_node FROM org_target_edges
UNION ALL
SELECT left_node,right_node FROM registry_edges""",materialize=True),
        dict(name='org_components',components=dict(
            sql='SELECT left_node,right_node FROM org_edges',
            left='left_node',
            right='right_node',
            node_limit=10_000_000,
        )),
        dict(name='org_decisions_conflicts',sql="""WITH diff_rows AS (
 SELECT
  d.id AS decision_id,d.subject,d.object,d.note,d.reviewer,d.decided_at,
  d.subject_node,
  coalesce(pm.bag_node,d.object_node) AS resolved_object_node
 FROM org_decisions_current d
 LEFT JOIN org_prior_anchor_map pm ON d.object_node=pm.org_node
 WHERE d.verdict='different'
  AND d.subject_node IS NOT NULL
  AND d.object_node IS NOT NULL
)
SELECT DISTINCT
 r.decision_id,
 c1.component AS conflict_component,
 r.subject,
 r.object,
 r.subject_node,
 r.resolved_object_node AS object_node,
 r.note,
 r.reviewer,
 r.decided_at
FROM diff_rows r
JOIN org_components c1 ON c1.node=r.subject_node
JOIN org_components c2 ON c2.node=r.resolved_object_node
WHERE c1.component=c2.component""",materialize=True),
        dict(name='org_resolved_mentions',sql="""WITH conflicted_components AS (
 SELECT DISTINCT conflict_component FROM org_decisions_conflicts
), witness_active AS (
 SELECT
  subject_key AS witness_key,
  bool_or(verdict='same') AS has_same,
  array_agg(object_node) FILTER (WHERE verdict='different' AND object_node IS NOT NULL) AS diff_objs
 FROM org_decisions_current
 WHERE subject_kind='witness'
  AND resolution_status IN ('live','remapped')
  AND subject_key IS NOT NULL
  AND verdict IN ('same','different')
 GROUP BY subject_key
), witness_mentions_ranked AS (
 SELECT
  m.witness_key,m.field,m.raw_text,m.string_key,m.l2_text,m.bag_key,
  row_number() OVER (PARTITION BY m.witness_key ORDER BY CASE m.field WHEN 'organization' THEN 1 ELSE 2 END) AS field_rank
 FROM org_witness_mentions m
), mention_nodes AS (
 SELECT
  r.witness_key,r.field,r.raw_text,r.string_key,r.l2_text,r.bag_key,
  CASE
   WHEN r.field_rank=1 AND wa.witness_key IS NOT NULL
    AND (coalesce(wa.has_same,false) OR array_has(coalesce(wa.diff_objs,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')),'b:'||r.bag_key))
    THEN 'w:'||r.witness_key
   ELSE 'b:'||r.bag_key
  END AS raw_node
 FROM witness_active wa
 RIGHT JOIN witness_mentions_ranked r ON r.witness_key=wa.witness_key
), joined AS (
 SELECT
  mn.witness_key,mn.field,mn.raw_text,mn.string_key,mn.l2_text,mn.bag_key,mn.raw_node,
  coalesce(oc.component,mn.raw_node) AS component,
  (cc.conflict_component IS NOT NULL) AS has_conflict
 FROM conflicted_components cc
 RIGHT JOIN (
  org_components oc
  RIGHT JOIN mention_nodes mn ON mn.raw_node=oc.node
 ) ON cc.conflict_component=coalesce(oc.component,mn.raw_node)
)
SELECT
 witness_key,field,raw_text,string_key,l2_text,bag_key,raw_node,
 CASE WHEN has_conflict THEN raw_node ELSE component END AS group_key,
 has_conflict
FROM joined""",materialize=True),
        dict(name='org_group_anchors',sql="""WITH group_base AS (
 SELECT group_key,bool_or(has_conflict) AS has_conflict
 FROM org_resolved_mentions
 GROUP BY group_key
), node_anchors AS (
 SELECT DISTINCT
  m.group_key,
  CASE
   WHEN m.raw_node LIKE 'w:%' AND m.group_key LIKE 'w:%' THEN 'witness:'||substr(m.raw_node,3)
   ELSE 'bag:'||m.bag_key
  END AS anchor,
  CASE
   WHEN m.raw_node LIKE 'w:%' AND m.group_key LIKE 'w:%' THEN 5
   ELSE 4
  END AS tier,
  m.has_conflict
 FROM org_resolved_mentions m
), clean_comp_decisions AS (
 SELECT DISTINCT
  c_sub.component AS group_key,
  CASE WHEN d.object LIKE 'wikidata:%' THEN 'wikidata:'||d.object_key ELSE 'decision:'||d.id END AS anchor,
  CASE WHEN d.object LIKE 'wikidata:%' THEN 2 ELSE 3 END AS tier
 FROM org_decisions_current d
 JOIN org_components c_sub ON c_sub.node=d.subject_node
 JOIN org_components c_obj ON c_obj.node=d.object_node AND c_obj.component=c_sub.component
 WHERE d.verdict='same'
  AND d.resolution_status IN ('live','remapped')
  AND d.subject_node IS NOT NULL
  AND d.object_node IS NOT NULL
), registry_comp_anchors AS (
 SELECT DISTINCT
  c.component AS group_key,
  m.anchor,
  1 AS tier
 FROM org_bag_registry_matches m
 JOIN org_components c ON c.node='r:'||m.anchor
), comp_anchors AS (
 SELECT group_key,anchor,tier FROM registry_comp_anchors
 UNION ALL
 SELECT group_key,anchor,tier FROM clean_comp_decisions
), all_candidates AS (
 SELECT na.group_key,na.anchor,na.tier,na.has_conflict FROM node_anchors na
 UNION ALL
 SELECT ca.group_key,ca.anchor,ca.tier,false AS has_conflict
 FROM comp_anchors ca
 JOIN group_base gb ON gb.group_key=ca.group_key
 WHERE NOT gb.has_conflict
), ranked AS (
 SELECT
  group_key,anchor,
  bool_or(has_conflict) OVER (PARTITION BY group_key) AS has_conflict,
  row_number() OVER (PARTITION BY group_key ORDER BY tier ASC,anchor ASC) AS rn
 FROM all_candidates
)
SELECT
 group_key,
 anchor,
 substr(encode(sha256('org-v1'||anchor),'hex'),1,16) AS org_id,
 has_conflict
FROM ranked
WHERE rn=1""",materialize=True),
        dict(name='organizations',sql=(sql_dir/'organizations.sql').read_text(),materialize=True),
        dict(name='organization_ids',sql="""WITH bag_ids AS (
 SELECT o.org_id,'bag' AS scheme,unnest(o.bag_keys) AS value
 FROM organizations o
 WHERE o.bag_keys IS NOT NULL
), bag_ev AS (
 SELECT org_id,scheme,value,'bag:'||value AS evidence
 FROM bag_ids
), registry_evidence AS (
 SELECT anchor,min('refspec:'||evidence_id) AS evidence
 FROM org_bag_registry_matches
 GROUP BY anchor
), anchor_ids AS (
 SELECT
  o.org_id,
  split_part(o.anchor,':',1) AS scheme,
  substr(o.anchor,length(split_part(o.anchor,':',1))+2) AS value,
  coalesce(re.evidence,o.anchor) AS evidence
 FROM organizations o
 LEFT JOIN registry_evidence re ON re.anchor=o.anchor
), decision_ids AS (
 SELECT DISTINCT
  ga.org_id,
  CASE WHEN d.object LIKE 'wikidata:%' THEN 'wikidata' ELSE 'decision' END AS scheme,
  CASE WHEN d.object LIKE 'wikidata:%' THEN d.object_key ELSE d.id END AS value,
  'decision:'||d.id AS evidence
 FROM org_group_anchors ga
 JOIN org_components c_sub ON c_sub.component=ga.group_key
 JOIN org_decisions_current d ON d.subject_node=c_sub.node
 JOIN org_components c_obj ON c_obj.node=d.object_node AND c_obj.component=ga.group_key
 WHERE NOT ga.has_conflict
  AND d.verdict='same'
  AND d.resolution_status IN ('live','remapped')
), all_ids AS (
 SELECT org_id,scheme,value,evidence FROM bag_ev
 UNION ALL
 SELECT org_id,scheme,value,evidence FROM anchor_ids
 UNION ALL
 SELECT org_id,scheme,value,evidence FROM decision_ids
)
SELECT org_id,scheme,value,min(evidence) AS evidence
FROM all_ids
GROUP BY org_id,scheme,value""",materialize=True),
        dict(name='witness_organizations',sql="""WITH anchored_mentions AS (
 SELECT
  m.witness_key,m.field,a.org_id,a.anchor,a.has_conflict,
  m.bag_key,m.string_key,m.raw_text
 FROM org_group_anchors a
 JOIN org_resolved_mentions m ON m.group_key=a.group_key
), with_str_match AS (
 SELECT
  am.*,
  rm.string_key AS matched_string_key,
  rm.anchor AS str_anchor,
  rm.evidence_id AS str_evidence_id
 FROM org_registry_matches rm
 RIGHT JOIN anchored_mentions am ON rm.string_key=am.string_key
)
SELECT
 ws.witness_key,
 ws.field,
 ws.org_id,
 ws.bag_key,
 ws.string_key,
 ws.raw_text,
 CASE
  WHEN NOT ws.has_conflict AND ws.matched_string_key IS NOT NULL AND ws.str_anchor=ws.anchor THEN 'registry'
  WHEN NOT ws.has_conflict AND brm.bag_key IS NOT NULL AND brm.anchor=ws.anchor THEN 'token_bag'
  WHEN ws.anchor LIKE 'wikidata:%' OR ws.anchor LIKE 'decision:%' THEN 'decision'
  WHEN ws.anchor LIKE 'witness:%' THEN 'witness'
  ELSE 'token_bag'
 END AS method,
 1.0 AS score,
 CASE
  WHEN NOT ws.has_conflict AND ws.matched_string_key IS NOT NULL AND ws.str_anchor=ws.anchor THEN 'refspec:'||ws.str_evidence_id
  WHEN NOT ws.has_conflict AND brm.bag_key IS NOT NULL AND brm.anchor=ws.anchor THEN 'bag:'||ws.bag_key||'->'||brm.evidence_id
  WHEN ws.anchor LIKE 'wikidata:%' OR ws.anchor LIKE 'decision:%' OR ws.anchor LIKE 'witness:%' THEN ws.anchor
  ELSE 'bag:'||ws.bag_key
 END AS evidence
FROM org_bag_registry_matches brm
RIGHT JOIN with_str_match ws ON brm.bag_key=ws.bag_key""",materialize=True),
        dict(name='org_priors_fresh',sql="""WITH live_orgs AS (
 SELECT org_id FROM organizations
), gone_orgs AS (
 SELECT po.org_id AS old_org_id
 FROM live_orgs lo
 RIGHT ANTI JOIN prior_organizations po ON lo.org_id=po.org_id
 WHERE po.org_id IS NOT NULL
), old_spellings AS (
 SELECT DISTINCT org_id AS old_org_id,raw_text
 FROM prior_witness_organizations
 WHERE org_id IS NOT NULL AND raw_text IS NOT NULL
), cur_spellings AS (
 SELECT raw_text,org_id,min(bag_key) AS bag_key
 FROM witness_organizations
 WHERE raw_text IS NOT NULL AND org_id IS NOT NULL AND bag_key IS NOT NULL
 GROUP BY raw_text,org_id
), inherited_distinct AS (
 SELECT
  g.old_org_id,
  cs.org_id AS target_org_id,
  os.raw_text,
  min(cs.bag_key) AS bag_key
 FROM gone_orgs g
 JOIN old_spellings os ON os.old_org_id=g.old_org_id
 JOIN cur_spellings cs ON cs.raw_text=os.raw_text
 GROUP BY g.old_org_id,cs.org_id,os.raw_text
), inherited_counts AS (
 SELECT
  old_org_id,
  target_org_id,
  count(*) AS inherited_spellings,
  min(bag_key) AS min_bag_key
 FROM inherited_distinct
 GROUP BY old_org_id,target_org_id
), ranked_targets AS (
 SELECT
  ic.old_org_id,
  ic.target_org_id,
  count(*) OVER (PARTITION BY ic.old_org_id) AS target_count,
  row_number() OVER (
   PARTITION BY ic.old_org_id
   ORDER BY ic.inherited_spellings DESC,coalesce(o.bag_keys[1],ic.min_bag_key) ASC,ic.target_org_id ASC
  ) AS rn
 FROM inherited_counts ic
 JOIN organizations o ON o.org_id=ic.target_org_id
)
SELECT
 r.old_org_id,
 r.target_org_id AS org_id,
 CASE WHEN r.target_count=1 THEN 'merged' ELSE 'split_from' END AS event,
 rm.release
FROM ranked_targets r
CROSS JOIN org_release_meta rm
WHERE r.rn=1""",materialize=True),
        dict(name='organization_redirects',sql=(sql_dir/'org-priors.sql').read_text(),materialize=True),
        dict(name='org_review_queue',sql="""WITH bag_to_org AS (
 SELECT DISTINCT m.bag_key,a.org_id
 FROM org_group_anchors a
 JOIN org_resolved_mentions m ON m.group_key=a.group_key
 WHERE m.raw_node='b:'||m.bag_key
), fuzzy_items AS (
 SELECT
  cast('fuzzy_pair' AS VARCHAR) AS queue_kind,
  fp.bag_key_a,
  fp.bag_key_b,
  oa.org_id AS org_id_a,
  ob.org_id AS org_id_b,
  fp.string_key_a,
  fp.string_key_b,
  fp.display_text_a,
  fp.display_text_b,
  fp.l2_text_a,
  fp.l2_text_b,
  fp.jaccard,
  fp.lev_ratio,
  fp.rarest_token,
  fp.rarest_df,
  fp.appearance_count_a,
  fp.appearance_count_b,
  fp.combined_appearances,
  cast(NULL AS VARCHAR) AS conflict_decision_id,
  cast(NULL AS VARCHAR) AS conflict_component,
  cast(NULL AS VARCHAR) AS conflict_note
 FROM org_fuzzy_pairs fp
 LEFT JOIN bag_to_org oa ON oa.bag_key=fp.bag_key_a
 LEFT JOIN bag_to_org ob ON ob.bag_key=fp.bag_key_b
 WHERE oa.org_id IS NULL OR ob.org_id IS NULL OR oa.org_id<>ob.org_id
), conflict_items AS (
 SELECT
  cast('decision_conflict' AS VARCHAR) AS queue_kind,
  CASE WHEN c.subject_node LIKE 'b:%' THEN substr(c.subject_node,3) ELSE c.subject_node END AS bag_key_a,
  CASE WHEN c.object_node LIKE 'b:%' THEN substr(c.object_node,3) ELSE c.object_node END AS bag_key_b,
  oa.org_id AS org_id_a,
  ob.org_id AS org_id_b,
  cast(NULL AS VARCHAR) AS string_key_a,
  cast(NULL AS VARCHAR) AS string_key_b,
  c.subject AS display_text_a,
  c.object AS display_text_b,
  cast(NULL AS VARCHAR) AS l2_text_a,
  cast(NULL AS VARCHAR) AS l2_text_b,
  cast(NULL AS DOUBLE) AS jaccard,
  cast(NULL AS DOUBLE) AS lev_ratio,
  cast(NULL AS VARCHAR) AS rarest_token,
  cast(NULL AS BIGINT) AS rarest_df,
  cast(NULL AS BIGINT) AS appearance_count_a,
  cast(NULL AS BIGINT) AS appearance_count_b,
  cast(0 AS BIGINT) AS combined_appearances,
  c.decision_id AS conflict_decision_id,
  c.conflict_component,
  c.note AS conflict_note
 FROM org_decisions_conflicts c
 LEFT JOIN bag_to_org oa ON oa.bag_key=substr(c.subject_node,3) AND c.subject_node LIKE 'b:%'
 LEFT JOIN bag_to_org ob ON ob.bag_key=substr(c.object_node,3) AND c.object_node LIKE 'b:%'
)
SELECT * FROM conflict_items
UNION ALL
SELECT * FROM fuzzy_items""",materialize=True),
    ]


def org_entity_outputs(output_dir,*,include_public=True,include_evidence=True):
    """Build native Parquet output specs for organization tables."""
    from viewer_publication.archive_format import DEFAULT_ROW_GROUP_ROWS,_settings
    out=Path(output_dir)
    review_settings=dict(
        profile='whole',
        row_group_rows=DEFAULT_ROW_GROUP_ROWS,
        order_by=[
            dict(field='queue_kind'),
            dict(field='combined_appearances',descending=True),
            dict(field='bag_key_a'),
            dict(field='bag_key_b'),
            dict(field='conflict_decision_id'),
        ],
        columns=[],
        dictionary_columns=['queue_kind','rarest_token'],
        delta_columns=[],
        key_column=None,
        created_by='docspec archive release v1',
        footer_limit=4 << 20,
    )
    public_specs=[
        ('organizations',['org_id'],['kind','taxonomy_parent','taxonomy_category'],
         'SELECT * FROM organizations'),
        ('organization_ids',['org_id','scheme','value'],['scheme'],
         'SELECT * FROM organization_ids'),
        ('witness_organizations',['witness_key','field'],['field'],
         'SELECT * FROM witness_organizations'),
        ('organization_redirects',['old_org_id'],['event','release'],
         'SELECT * FROM organization_redirects'),
    ]
    evidence_specs=[
        ('org_decisions_conflicts',['decision_id','conflict_component'],[],
         'SELECT * FROM org_decisions_conflicts'),
        ('org_strings',['string_key'],[],
         'SELECT * FROM org_strings'),
    ]
    specs=(public_specs if include_public else [])+(evidence_specs if include_evidence else [])
    outputs=[
        dict(
            name=name+'.parquet',
            path=str(out/(name+'.parquet')),
            sql=sql,
            settings=_settings('whole',order,dictionary=dictionary,footer_limit=4 << 20),
        )
        for name,order,dictionary,sql in specs
    ]
    if include_evidence:
        outputs.append(dict(
            name='org_review_queue.parquet',
            path=str(out/'org_review_queue.parquet'),
            sql='SELECT * FROM org_review_queue',
            settings=review_settings,
        ))
    return outputs


def org_entity_queries():
    """Return `(metadata_queries, diagnostic_queries)` for organization entities."""
    meta=[
        dict(name='org_fuzzy_candidate_stats',sql="""SELECT
 b.distinct_bags,
 b.indexed_bags,
 b.max_bucket_size,
 b.raw_blocked_pairs,
 (SELECT cast(count(*) AS BIGINT) FROM org_fuzzy_pairs) AS qualified_candidate_pairs,
 (SELECT cast(count(*) AS BIGINT) FROM org_review_queue WHERE queue_kind='fuzzy_pair') AS review_queue_pairs,
 (SELECT cast(count(*) AS BIGINT) FROM org_review_queue WHERE queue_kind='decision_conflict') AS decision_conflict_items,
 (SELECT cast(count(*) AS BIGINT) FROM organizations) AS organization_count,
 (SELECT cast(count(DISTINCT witness_key) AS BIGINT) FROM witness_organizations) AS linked_appearances,
 (SELECT cast(count(DISTINCT witness_key) AS BIGINT) FROM appearance_records_resolved) AS total_appearances,
 (SELECT cast(count(*) AS BIGINT) FROM organization_redirects) AS retired_org_ids,
 (SELECT cast(count(*) AS BIGINT) FROM organization_redirects WHERE event='merged') AS retired_merged,
 (SELECT cast(count(*) AS BIGINT) FROM organization_redirects WHERE event='split_from') AS retired_split_from,
 (SELECT cast(count(*) AS BIGINT) FROM organization_redirects WHERE event='restored') AS retired_restored
FROM org_fuzzy_block_stats b"""),
    ]
    diag=[
        dict(name='org_invariants',sql="""SELECT
 (SELECT count(*) FROM (SELECT org_id FROM organizations GROUP BY org_id HAVING count(*)>1)) AS duplicate_org_ids,
 (SELECT count(*) FROM (SELECT o.org_id FROM organizations o RIGHT JOIN witness_organizations w ON o.org_id=w.org_id WHERE o.org_id IS NULL)) AS missing_witness_org_ids,
 (SELECT count(*) FROM (SELECT o.org_id FROM organizations o RIGHT JOIN organization_redirects r ON o.org_id=r.org_id WHERE o.org_id IS NULL)) AS missing_redirect_target_org_ids,
 (SELECT count(*) FROM organizations o JOIN organization_redirects r ON o.org_id=r.old_org_id WHERE r.event<>'restored') AS non_one_hop_redirects,
 (SELECT count(*) FROM (SELECT old_org_id FROM organization_redirects GROUP BY old_org_id HAVING count(*)>1)) AS duplicate_redirect_old_org_ids,
 (SELECT count(*) FROM organizations WHERE has_conflict AND cardinality(bag_keys)>1) AS conflicted_orgs_still_merged,
 (SELECT count(*) FROM (SELECT string_key FROM org_strings GROUP BY string_key HAVING count(*)>1)) AS duplicate_org_strings,
 (SELECT count(*) FROM org_decisions WHERE subject LIKE 'fr_agency:%' OR subject LIKE 'agency_alias:%' OR subject LIKE 'refspec%' OR object LIKE 'fr_agency:%' OR object LIKE 'agency_alias:%' OR object LIKE 'refspec%') AS rejected_org_decision_agency_aliases"""),
    ]
    return meta,diag


def build_org_entities(*,appearance_records_resolved,engine,output,scratch,
                       witness_key_map=None,org_decision_files=(),
                       prior_org_release=None,release_label='current',refspec=None,root=ROOT):
    """Run standalone organization entity resolution over `appearance_records_resolved`."""
    from congress_api.retention.provenance import run_job
    from viewer_publication.archive_model_lifetimes import retire_relations
    scratch=Path(scratch).resolve()
    scratch.mkdir(parents=True,exist_ok=True)
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    def _table_input(name,source):
        if isinstance(source,dict):
            return dict(source,name=name)
        return dict(name=name,kind='parquet',path=str(Path(source).resolve()))
    inputs=[_table_input('appearance_records_resolved',appearance_records_resolved)]
    if witness_key_map is not None:
        inputs.append(_table_input('witness_key_map',witness_key_map))
    else:
        inputs.append(json_input(scratch,'witness_key_map',[],old_key='Utf8',witness_key='Utf8',status='Utf8'))
    inputs += org_entity_inputs(scratch,org_decision_files=org_decision_files,
        prior_org_release=prior_org_release,release_label=release_label,refspec=refspec,root=root)
    steps=org_entity_steps(root=root)
    outputs=org_entity_outputs(output)
    meta,diag=org_entity_queries()
    retired=retire_relations(dict(scratch=str(scratch/'native'),inputs=inputs,steps=steps,outputs=outputs,queries=meta+diag))
    reports=run_job(scratch/'job',engine,inputs=retired['inputs'],steps=retired['steps'],outputs=retired['outputs'],queries=retired['queries'])
    invariants=reports['org_invariants'][0]
    if any(value for value in invariants.values()):
        raise ValueError(f'Organization entity invariant failed: {invariants}')
    return dict(
        output=output,
        outputs={item['name']:Path(item['path']) for item in outputs},
        stats=reports['org_fuzzy_candidate_stats'][0],
        invariants=invariants,
    )


def senate_page_prelim_links_sql(*,root=ROOT):
    """Score senate_page_candidates before package_meeting_links exists so Senate witness rosters corroborate prints (ct-uul8)."""
    text=(Path(root)/'model/sql/senate-page-meeting-links.sql').read_text()
    target='WITH meeting_known_people AS ('
    if target not in text:raise ValueError('senate-page-meeting-links.sql missing expected WITH meeting_known_people AS ( header')
    return text.replace(target,"WITH package_meeting_links AS (SELECT cast(NULL AS VARCHAR) AS package_id,"
        "cast(NULL AS BIGINT) AS event_id,false AS witness_eligible WHERE false), meeting_known_people AS (",1)


def package_link_steps(*,root=ROOT):
    """Packages to meetings: the jacket and MODS links, then the ones a raw record justifies (ct-dx22, ct-uul8)."""
    return _sql_steps(['person-nicknames','appearance-people','person-same-family','person-given-matches',
        'package-mods-facts','senate-page-records','senate-page-candidates'],root=root)+[
        dict(name='senate_page_prelim_links',sql=senate_page_prelim_links_sql(root=root),materialize=True)]+_sql_steps(
        ['print-meeting-agreement','meeting-mods-links','meeting-transcript-links','package-meeting-links'],root=root)


def admission_steps(*,prelude=(),root=ROOT):
    """Use the full model's maintained input prefix before accepting a skip."""
    from viewer_publication.archive_provenance import current_steps
    from viewer_publication.archive_model_profile import completeness_steps
    return list(prelude)+current_steps(root=root)+evidence_steps(root=root)+source_steps(root=root)+completeness_steps(root=root)


def admission_checks(*,parser_versions,catalog_version,include_entities=False,carried_html_metadata=0,root=ROOT):
    """Check current pinned inputs without exporting public release files."""
    from viewer_publication.archive_model_profile import completeness_checks,validate_parser_versions
    validate_parser_versions(parser_versions,require_entities=include_entities)
    checks=','.join(sql+' AS '+name for name,sql in evidence_checks().items())
    return [dict(name='model_invariants',sql='SELECT '+checks)]+completeness_checks(
        catalog_version=catalog_version,
        include_entities=include_entities,
        meeting_records_version=parser_versions.get('meeting_records') if isinstance(parser_versions,dict) else None,
        appearance_records_version=parser_versions.get('appearance_records') if isinstance(parser_versions,dict) else None,
        carried_html_metadata=carried_html_metadata,
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
                         unreadable_files=(),variant_files=(),qualification_files=(),meeting_records=None,appearance_records=None,
                         spicy_regs=None,include_entities=False,recovery_requirements=None,
                         video_records=None,committee_records=None,recording_decision_files=(),playlist_records=None,
                         transcript_headings=None,
                         historical_recording_matcher=None,pdf_cover_evidence=None,body_qualifications=None,prior_links=None,base_retired=None,base_release_id=None,
                         carried_html_metadata=0,include_org_entities=False,publish_org_entities=False,org_decision_files=(),
                         prior_org_release=None,org_release_label='current',refspec=None,root=ROOT,registry=None):
    """Freeze current input selectors and the shared prefix in fresh private scratch.

    `registry` names a compatible-versions file other than the checked-in one (tests only).
    prior_links/base_retired (release_gate.prior_links) feed only the retired-key
    ledger; absent, the ledger starts empty. They stay out of the input identity.
    """
    from congress_api.lake import compatible_versions
    from viewer_publication.archive_format import AUXILIARY_ROW_GROUP_ROWS, _settings
    from viewer_publication.archive_model_profile import (expand_parser_version_rows,profile_record,
        readings_bundle_version,runtime_pins,validate_parser_versions)
    if type(carried_html_metadata) is not int or carried_html_metadata<0:
        raise ValueError('carried_html_metadata must be a non-negative integer')
    include_entities=bool(include_entities or meeting_records is not None or appearance_records is not None or spicy_regs is not None)
    publish_org_entities=bool(publish_org_entities)
    include_org_entities=bool(include_org_entities or publish_org_entities)
    if (org_decision_files or prior_org_release is not None) and not include_org_entities:
        raise ValueError('org_decision_files and prior_org_release require include_org_entities=True')
    if include_org_entities and not include_entities:
        raise ValueError('Organization entity tables require include_entities=True')
    # All or none: an omitted table means unavailable, never empty (DM8).
    explorer_inputs=video_records is not None or committee_records is not None or bool(recording_decision_files)
    if explorer_inputs and (video_records is None or committee_records is None or not recording_decision_files or not include_entities):
        raise ValueError('Explorer tables require entity inputs, video_records, committee_records and recording decisions together')
    validate_parser_versions(parser_versions,require_entities=include_entities,require_explorer=explorer_inputs)
    if playlist_records is not None and (not include_entities or 'playlist_records' not in parser_versions):
        raise ValueError('Playlist records require entity inputs and a pinned playlist_records version')
    if transcript_headings is not None and (not include_entities or 'transcript_headings' not in parser_versions):
        raise ValueError('Transcript headings require entity inputs and a pinned transcript_headings version')
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
    if transcript_headings is not None:
        raw_data_inputs.append(('transcript_headings',transcript_headings))
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
    inputs += ledger_inputs(scratch/'ledger',prior_links=prior_links,base_retired=base_retired,base_release_id=base_release_id)
    # Provenance is immutable input data; JSON columns with heterogeneous values
    # are projected once by the native reader before policy joins.
    from viewer_publication.archive_provenance import provenance_inputs
    provenance,prelude=provenance_inputs(scratch/'provenance',recovery_files=recovery_files,review_files=review_files)
    from viewer_publication.pdf_cover_evidence import model_input as pdf_cover_input
    cover_input,cover_step=pdf_cover_input(pdf_cover_evidence,scratch/'pdf-cover')
    inputs.append(cover_input)
    prelude.append(cover_step)
    from congress_api.retention.qualification_facts import model_qualification_input
    qual_sources=[*qualification_files,*([body_qualifications] if body_qualifications is not None else [])]
    qual_input,qual_step=model_qualification_input(qual_sources or None,scratch/'qualifications')
    inputs.append(qual_input)
    prelude.append(qual_step)
    from viewer_publication.refspec_inputs import refspec_profile_pin
    refspec_pin=refspec_profile_pin(refspec)
    if include_org_entities:
        if prior_org_release is None and prior_links is not None:
            prior_parent=Path(prior_links).parent
            siblings={
                name:prior_parent/f'{name}.parquet'
                for name in ('prior_organizations','prior_organization_redirects','prior_witness_organizations')
                if (prior_parent/f'{name}.parquet').is_file()
            }
            if siblings:
                prior_org_release=siblings
        inputs += org_entity_inputs(scratch,org_decision_files=org_decision_files,
            prior_org_release=prior_org_release,release_label=org_release_label,refspec=refspec,root=root)
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
        # The print's own committees and committee members (MODS only; null for other sources). The pinned lake table
        # carries them (schema fields 36-39, imported as a new table: the engine cannot add columns to an existing one);
        # an older local Parquet input without them states none.
        no_committees=("arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS committees,"
                       "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS committee_members,")
        if table_name=='appearance_records':
            has_committees=not (isinstance(value,dict) and value.get('kind')=='native_table'
                                and '/appearance_records_mvp_20261105/' in (value.get('metadata_location') or ''))
            extra_select=('event_id,package_id,declared_base,collection_state,cast(NULL AS VARCHAR) AS context_url,'
                          'held_dates,title,created,'+('committees,committee_members,' if has_committees else no_committees))
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
                committees_expr=('committees,committee_members,' if {'committees','committee_members'}<=set(schema.names)
                                 else no_committees)
                extra_select=f'{ev_expr},{pkg_expr},{base_expr},{cs_expr},{ctx_expr},{held_expr},{title_expr},{created_expr},{committees_expr}'
        return f"SELECT {sha_expr} AS record_sha_hex,parser_version,{status_expr} AS status,{error_expr} AS error_type,source,{extra_select}{payload_col} FROM {table_name}"
    meeting_records_path=meeting_records.get('path') if isinstance(meeting_records,dict) else meeting_records
    has_document_references=(not isinstance(meeting_records_path,(str,Path)) or
        not Path(meeting_records_path).is_file() or meeting_records_have_document_references(meeting_records_path))
    has_rank_credentials=appearance_records_have_rank_credentials(appearance_records,root=root)
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
    if transcript_headings is None:
        prelude.append(dict(name='transcript_headings',sql=TRANSCRIPT_HEADINGS_UNAVAILABLE,materialize=True))
    prelude.append(selected_record_step('transcript_headings','transcript_headings',root=root))
    from congress_api.retention.provenance import active_unreadable_where
    prelude += [dict(name='active_unreadable',sql=f"SELECT u.* FROM unreadable_records u WHERE {active_unreadable_where('unreadable_records','u')}",materialize=True)]
    from congress_api.models.archive_profile import build_capture_profile
    capture_profile=build_capture_profile(engine_revision=engine.source_revision,
        url_normalized_sql=(Path(root)/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(Path(root)/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((Path(root)/'model/registries/url-rules.json').read_text()),recovery_policy=recovery_policy)
    from congress_api.retention.provenance import file_pin
    selectors={item['name']:dict(item) if item['kind']=='native_table' else dict(kind='parquet',path=item['path'],**file_pin(item['path'])) for item in data_inputs}
    if body_qualifications is not None:
        selectors['body_qualifications']={key:body_qualifications[key] for key in ('sha256','size')}
    lake_tables=['captures','readings','filename_readings']+(['meeting_records','appearance_records'] if include_entities else [])+(['video_records','committee_records'] if explorer_inputs else [])
    if playlist_records is not None:lake_tables.append('playlist_records')
    if transcript_headings is not None:lake_tables.append('transcript_headings')
    model_profile=profile_record(parser_versions=parser_versions,catalog_version=catalog_version,
        engine_revision=engine.source_revision,runtime_pins=runtime_pins(engine),
        lake_versions={name:dict(schema_sha256=file_pin(Path(root)/'model/lake'/(name.replace('_','-')+'.schema.json'))['sha256']) for name in lake_tables},
        snapshots=selectors,writer_settings=dict(schema_version=1,whole=_settings('whole',['list_row']),
            ranged=_settings('ranged',['list_row']),lookup=_settings('lookup',['link_key']),
            auxiliary_row_group_rows=AUXILIARY_ROW_GROUP_ROWS),root=root,
        recovery_policy=recovery_policy,historical_recording_matcher=historical_recording_matcher,
        pdf_cover_evidence=pdf_cover_evidence,refspec=refspec_pin,
        include_org_entities=include_org_entities,publish_org_entities=publish_org_entities)
    (scratch/'profile.json').write_text(json.dumps(model_profile,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    return dict(inputs=inputs,prelude=prelude,steps=admission_steps(prelude=prelude,root=root),
        profile=model_profile,capture_profile=capture_profile,scratch=scratch,evidence=evidence,
        parser_versions=dict(parser_versions),catalog_version=catalog_version,
        include_entities=include_entities,entity_digests=entity_digests,recovery_policy=recovery_policy,explorer_inputs=explorer_inputs,
        has_document_references=has_document_references,
        has_rank_credentials=has_rank_credentials,
        historical_recording_matcher=historical_recording_matcher is not None,
        include_org_entities=include_org_entities,
        publish_org_entities=publish_org_entities,
        carried_html_metadata=carried_html_metadata)


def build_release(*,captures,readings,filename_readings,parser_versions,catalog_version,
                  engine,output,scratch,recovery_files=(),review_files=(),verification_files=(),
                  unreadable_files=(),variant_files=(),qualification_files=(),meeting_records=None,appearance_records=None,
                  spicy_regs=None,include_entities=False,recovery_requirements=None,
                  video_records=None,committee_records=None,recording_decision_files=(),playlist_records=None,
                  transcript_headings=None,
                  historical_recording_matcher=None,pdf_cover_evidence=None,body_qualifications=None,prior_links=None,base_retired=None,base_release_id=None,
                  carried_html_metadata=0,include_org_entities=False,publish_org_entities=False,org_decision_files=(),
                  prior_org_release=None,org_release_label='current',refspec=None,root=ROOT,registry=None):
    """Prepare inputs once and run the document model's maintained full job."""
    prepared=prepare_model_inputs(captures=captures,readings=readings,filename_readings=filename_readings,
        parser_versions=parser_versions,catalog_version=catalog_version,engine=engine,scratch=scratch,
        recovery_files=recovery_files,review_files=review_files,verification_files=verification_files,
        unreadable_files=unreadable_files,variant_files=variant_files,qualification_files=qualification_files,meeting_records=meeting_records,
        appearance_records=appearance_records,spicy_regs=spicy_regs,include_entities=include_entities,
        recovery_requirements=recovery_requirements,video_records=video_records,committee_records=committee_records,
        recording_decision_files=recording_decision_files,playlist_records=playlist_records,transcript_headings=transcript_headings,
        historical_recording_matcher=historical_recording_matcher,pdf_cover_evidence=pdf_cover_evidence,
        body_qualifications=body_qualifications,
        prior_links=prior_links,base_retired=base_retired,base_release_id=base_release_id,
        carried_html_metadata=carried_html_metadata,include_org_entities=include_org_entities,
        publish_org_entities=publish_org_entities,org_decision_files=org_decision_files,
        prior_org_release=prior_org_release,org_release_label=org_release_label,refspec=refspec,root=root,registry=registry)
    return build_prepared_release(prepared,engine=engine,output=output,root=root)


#: The lake table's binding in the full model job, whose first step `captures` retains it
#: (the `<name>_input` idiom of `recovery_requirements_input`).
CAPTURES_INPUT='captures_input'


def retained_captures(inputs):
    """Bind the lake `captures` as CAPTURES_INPUT and return the step that retains it as `captures`.

    Every statement that names a lake table reads it again from the object store: 31 statements
    named `captures` 42 times and took 414 s of an 867 s build. Read once into a retained step,
    all of them scan local rows; no model SQL changes. Only the full job does this: the admission
    job and every other caller of the step factories keep their own `captures` binding. Final
    queries read the step, so it lives to the end of the job. The engine holds a step in memory
    while what it retains fits under its ceiling and in scratch otherwise: at about 2.7 GiB of
    Arrow data against a 3 GiB ceiling this step sits at that boundary, so held in memory it
    takes most of the ceiling and sends later steps to scratch, and it moves to scratch itself
    as the table grows.
    """
    return ([dict(item,name=CAPTURES_INPUT) if item['name']=='captures' else item for item in inputs],
        dict(name='captures',sql='SELECT * FROM '+CAPTURES_INPUT,materialize=True))


def build_prepared_release(prepared,*,engine,output,root=ROOT):
    """Continue one prepared plan through grouping and the shared native exporter."""
    from viewer_publication.archive_format import _execute,_settings,LIST_COLUMNS,DETAIL_COLUMNS,MEETING_DICTIONARY
    from viewer_publication.archive_annotations import annotation_steps
    from viewer_publication.archive_provenance import RECOVERY_FILE_AGREEMENT,attachment_steps,body_review_steps,recovered_copy_steps,saved_recoveries_step
    scratch=prepared['scratch'];evidence=prepared['evidence'];output=Path(output).resolve()
    inputs,captures_step=retained_captures(prepared['inputs']);capture_profile=prepared['capture_profile']
    parser_versions=prepared['parser_versions'];catalog_version=prepared['catalog_version']
    steps=[captures_step]+list(prepared['steps'])+link_steps(root=root)
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
    steps += _sql_steps(['document-members','archive-container-links','landing-page-files','landing-page-picks','landing-pages','document-bodies','document-identities','saved-name-standing','saved-files','saved-name-conflicts','document-alternates',
        'document-version-keys','document-versions','document-bill-decisions','document-metadata','document-addresses'],root=root)+[saved_recoveries_step(root=root)]+_sql_steps(['document-removals','document-packages',
        'recovered-copy-fills','document-filename-facts'],root=root)
    steps += package_link_steps(root=root)
    steps += appearance_steps(root=root,has_rank_credentials=prepared.get('has_rank_credentials',True))+witness_key_steps(root=root)+[
        dict(name='component_meeting_links',sql=(Path(root)/'model/sql/component-meeting-links.sql').read_text(),materialize=True)]
    steps += [dict(name='base_normalized',sql=(Path(root)/'model/sql/document-normalized.sql').read_text()+' UNION ALL '+(Path(root)/'model/sql/document-recovery-normalized.sql').read_text(),materialize=True)]
    steps += [dict(name='html_uuid_candidates',sql="SELECT doc_key,component,filename,source_url FROM base_normalized WHERE format='html' AND regexp_like(coalesce(filename,''),'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')",materialize=True)]
    steps += _sql_steps(['titles','gpo-mods-fields','gpo-mods-packages','gpo-mods-granules','landing-page-print-numbers','document-print-numbers','document-hearing-date-corrections','transcript-print-covers','body-cover-kinds','html-uuid-slug-fills'],root=root)
    from viewer_publication.archive_model_profile import completeness_checks
    steps += application_steps(root=root)
    steps += _sql_steps(PAGE_METADATA_STEPS,root=root)
    steps += [dict(name='page_metadata_pointer_repeats',sql="""SELECT count(*) AS n FROM (
        SELECT body_sha,field,path FROM page_metadata_values GROUP BY body_sha,field,path HAVING count(*)>1)""",materialize=True)]
    from viewer_publication.archive_format import PAGE_COLUMNS,PAGE_DEFAULTS
    page=','.join(f'coalesce(pm.{c},{PAGE_DEFAULTS[c]}) AS {c}' if c in ('publisher_labels','page_metadata') else f'pm.{c}' for c in PAGE_COLUMNS)
    # hidden is IS TRUE, not coalesce(..., false): same values, and the column stays required when an
    # engine types it from the optimized plan (test_required_flags.py).
    # A committee's 'transcript' whose own text is a GPO printed hearing's cover is that print (ct-isnv):
    # kind and family published-hearing; verified Tier-1 body covers override empty kinds and ambiguous
    # -Bio-/-SD-/-Wstate- upload slots; a review override still wins for the kind.
    slug_list=lambda column:f"CASE WHEN coalesce(array_length(n.{column}),0)>0 OR uf.doc_key IS NULL THEN n.{column} ELSE uf.{column} END"
    covered=lambda column:f"CASE WHEN ck.doc_key IS NULL THEN {slug_list(column)} ELSE ck.cover_{column} END"
    printed=lambda column:f"CASE WHEN pc.doc_key IS NULL THEN {covered(column)} ELSE array_sort(array_distinct(array_replace_all({covered(column)},'transcript','published-hearing'))) END"
    final_date='CASE WHEN h.doc_key IS NULL THEN n.document_date ELSE h.document_date END'
    final_source='CASE WHEN h.doc_key IS NULL THEN n.document_date_source ELSE h.document_date_source END'
    steps += [dict(name='normalized',sql=f"""SELECT n.* EXCLUDE(filename,own_title,own_title_source,link_title,mods_title,component,document_kind,document_family,congress,hidden,review_note,review_decided_at,removed_on,document_date,document_date_source,facts),
        CASE WHEN uf.doc_key IS NULL THEN n.filename ELSE uf.filename END AS filename,
        t.title,pn.print_number,t.title_source,coalesce(r.kind_override,{printed('document_kind')}) AS document_kind,
        {printed('document_family')} AS document_family,
        coalesce(n.congress,CASE WHEN coalesce({final_source},'')<>'filename'
         AND ({final_date})>=DATE '1935-01-04' AND date_part('year',{final_date})<=2028
         AND (coalesce(n.first_captured,n.in_archive_since) IS NULL OR ({final_date})<=coalesce(n.first_captured,n.in_archive_since)+INTERVAL '365 days')
         AND NOT (cast(date_part('year',{final_date}) AS INT)%2=1 AND substr(cast({final_date} AS VARCHAR),6,5)='01-03')
         THEN cast((cast(date_part('year',{final_date}) AS INT)-CASE WHEN substr(cast({final_date} AS VARCHAR),6,5)<'01-03' THEN 1 ELSE 0 END-1789)/2+1 AS SMALLINT) END) AS congress,
        (r.hidden OR (n.format='html' AND (regexp_like(coalesce(t.title,''),'(?i)^(?:error\\s*[|:-]|page not found\\b|404(?:\\s*[|:-]|\\s+(?:error|page\\s+not\\s+found|not\\s+found)\\b|\\s*$)|not found\\s*[|:-]|file not found\\b)') OR regexp_like(coalesce(pm.description,''),'(?i)^\\s*page not found\\b')))) IS TRUE AS hidden,r.note AS review_note,r.decided_at AS review_decided_at,x.removed_on,
        {final_date} AS document_date,
        {final_source} AS document_date_source,
        CASE WHEN coalesce(array_length(n.facts),0)>0 OR uf.doc_key IS NULL THEN n.facts ELSE uf.facts END AS facts,{page}
        FROM document_print_numbers pn RIGHT JOIN (titles t RIGHT JOIN (document_page_metadata pm RIGHT JOIN (document_removals x RIGHT JOIN (review_overrides r RIGHT JOIN
            (document_identities d JOIN (html_uuid_slug_fills uf RIGHT JOIN (body_cover_kinds ck RIGHT JOIN (transcript_print_covers pc RIGHT JOIN (document_hearing_date_corrections h RIGHT JOIN base_normalized n ON n.doc_key=h.doc_key)
             ON n.doc_key=pc.doc_key) ON n.doc_key=ck.doc_key) ON n.doc_key=uf.doc_key) ON n.doc_key=d.document_id)
            ON d.component=r.component) ON d.component=x.component) ON pm.doc_key=n.doc_key) ON t.doc_key=n.doc_key) ON pn.doc_key=n.doc_key""",materialize=True),
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
    steps += url_state_steps(root=root,recovery_policy=prepared.get('recovery_policy'),include_qualifications=True)
    auxiliary=[]
    if prepared.get('include_entities') or prepared.get('explorer_inputs'):
        steps.append(dict(name='recording_match_stopwords',sql=RECORDING_MATCH_STOPWORDS_SQL,materialize=True))
    if not prepared.get('include_entities'):
        # Meetings list caption tracks among their transcripts (ct-1i4q); without entities there are none.
        steps += [
            dict(name='video_key_aliases',sql="SELECT cast(NULL AS VARCHAR) AS alias_key,cast(NULL AS VARCHAR) AS canonical_key WHERE false",materialize=True),
            dict(name='recording_video_links',sql="SELECT cast(NULL AS VARCHAR) AS page_body,cast(NULL AS VARCHAR) AS extracted_key WHERE false",materialize=True),
            dict(name='recordings_entity',sql=EMPTY_RECORDINGS_SQL,materialize=True),
            dict(name='recordings_export',sql=EMPTY_RECORDINGS_SQL,materialize=True),
            dict(name='retained_caption_tracks',sql="SELECT cast(NULL AS VARCHAR) AS video_key,arrow_cast(NULL,'FixedSizeBinary(32)') AS track_body WHERE false",materialize=True),
            dict(name='recording_page_video_events',sql=EMPTY_RECORDING_PAGE_VIDEO_EVENTS_SQL,materialize=True),
        ]
    if prepared.get('explorer_inputs'):
        steps += _sql_steps(['youtube-cache-bodies','youtube-api-bodies'],root=root)+[
            dict(name='known_meetings',sql=known_meetings_sql('normalized'),materialize=True),
            dict(name='videos_entity',sql=(Path(root)/'model/sql/entity-videos.sql').read_text(),materialize=True),
        ]
        auxiliary += [(name,'SELECT * FROM videos_entity' if name=='videos' else (Path(root)/'model/sql'/(file+'.sql')).read_text(),keys,dictionary)
                      for name,file,keys,dictionary in EXPLORER_TABLES[:3]]
    if prepared.get('include_entities'):
        from congress_api.lake.playlist_records import GOOD_FETCH_CAPTURE_SQL,PLAYLIST_CAPTURE_SQL
        steps += [
            dict(name='recording_url_sources',sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'",materialize=True),
            dict(name='recording_track_formats',sql="SELECT pattern,format,default_language,default_production FROM recording_sources WHERE kind='track_format'",materialize=True),
            dict(name='recording_segment_exclusions',sql="SELECT pattern FROM recording_sources WHERE kind='segment_exclusion'",materialize=True),
            dict(name='video_key_aliases',sql=VIDEO_KEY_ALIASES_SQL,materialize=True),
            dict(name='recording_link_candidates',sql="SELECT DISTINCT page_body,target_url FROM resolved_link_targets WHERE target_url IS NOT NULL AND regexp_like(target_url,'(?i)(?:youtube|youtu[.]be|senate)')",materialize=True),
            dict(name='recording_video_links',sql="""SELECT DISTINCT raw.page_body,
                coalesce(a.canonical_key,raw.extracted_key) AS extracted_key
                FROM video_key_aliases a
                RIGHT JOIN (
                    SELECT l.page_body,
                        regexp_replace((regexp_match(l.target_url,rs.pattern))[1],'^(.+)$',rs.key_template) AS extracted_key
                    FROM recording_url_sources rs JOIN recording_link_candidates l ON regexp_like(l.target_url,rs.pattern)
                ) raw ON a.alias_key=raw.extracted_key""",materialize=True),
            dict(name='recording_video_pages',sql="""SELECT DISTINCT page_body,
                arrow_cast(decode(page_body,'hex'),'FixedSizeBinary(32)') AS body_sha
                FROM recording_video_links WHERE page_body IS NOT NULL""",materialize=True),
            dict(name='recording_page_sources',sql="""SELECT DISTINCT c.source_id,c.body_sha AS page_body
                FROM recording_video_pages vp JOIN capture_source_contexts c ON c.body_sha=vp.page_body""",materialize=True),
            dict(name='recording_page_event_links',sql=RECORDING_PAGE_EVENT_LINKS_SQL,materialize=True),
            dict(name='house_page_meeting_links',sql=(Path(root)/'model/sql/house-page-meeting-links.sql').read_text(),materialize=True),
            dict(name='recording_page_meetings',sql=RECORDING_PAGE_MEETINGS_SQL,materialize=True),
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
            dict(name='retained_caption_tracks',sql="SELECT DISTINCT video_key,track_body FROM caption_resources WHERE status='retained' AND ordinal>0 AND format IN ('vtt','srt','ttml')",materialize=True),
            dict(name='recordings_entity',sql=(Path(root)/'model/sql/entity-recordings.sql').read_text(),materialize=True),
            dict(name='recording_page_video_events',sql=RECORDING_PAGE_VIDEO_EVENTS_SQL,materialize=True)]
        auxiliary += [
            ('recordings',recordings_export_sql(root=root,explorer_inputs=bool(prepared.get('explorer_inputs'))),['video_key'],['tracks.list.item.suffix','tracks.list.item.format','tracks.list.item.language','tracks.list.item.production','recording_scope']),
            ('meetings',(Path(root)/'model/sql/entity-meetings.sql').read_text(),['event_id'],MEETING_DICTIONARY),
            ('witnesses',WITNESSES_SQL,['occasion','panel_order','display_order','witness_key'],['occasion','source','witness_type','bioguide_id','match_basis','listing_status']),
            ('witness_key_map','SELECT old_key,witness_key,status,basis,candidate_keys,occasion,source FROM witness_key_map',['old_key'],['occasion','source','status','basis']),
            ('people','SELECT * FROM entity_people',['person_key'],['grouping_basis']),
            ('person_aliases','SELECT old_person_key,person_key,status,kind,decision_id,last_release_id,candidate_keys FROM person_aliases',['old_person_key'],['status','kind']),
            ('caption_resources','SELECT * FROM caption_resources',['video_key','track_body','ordinal'],['suffix','format','status']),
            ('committees',(Path(root)/'model/sql/entity-committees.sql').read_text(),['system_code'],['chamber','committee_type','parent_system_code']),
            ('members',(Path(root)/'model/sql/entity-members.sql').read_text(),['bioguide_id'],['terms.list.item.chamber','terms.list.item.state','terms.list.item.party']),
            ('rosters','SELECT * FROM roster_seats',['congress','system_code','rank','bioguide_id'],['system_code','bioguide_id','title','party','congress_basis','position_basis','entry_label']),
            ('bills',(Path(root)/'model/sql/entity-bills.sql').read_text(),['bill_id'],['sponsor_bioguide_id','stage','policy_area','committees.list.item','floor_votes.list.item.basis','floor_votes.list.item.chamber','amendments.list.item.sponsor_bioguide_id','committee_activities.list.item.system_code','committee_activities.list.item.activity']),
            ('nominations',(Path(root)/'model/sql/entity-nominations.sql').read_text(),['nomination_id'],['committees.list.item']),
        ]
        auxiliary += list(detail_exports(prepared['entity_digests'],SPICY_SCHEMAS))
    else:
        auxiliary.append(('meetings',(Path(root)/'model/sql/entity-meetings.sql').read_text(),['event_id'],MEETING_DICTIONARY))
    explorer_diagnostics=[]
    if prepared.get('explorer_inputs'):
        steps += recording_match_prep_steps(videos_relation='videos_entity')
        auxiliary += [(name,(Path(root)/'model/sql'/(file+'.sql')).read_text(),keys,dictionary) for name,file,keys,dictionary in EXPLORER_TABLES[3:]]
        from congress_api.lake.committee_records import CANDIDATE_SQL
        explorer_diagnostics=[dict(name='explorer_invariants',sql=rf"""SELECT (SELECT count(*) FROM meeting_coverage_export)-5*(SELECT count(*) FROM meetings_export) AS coverage_row_mismatch,
            (SELECT count(*) FROM meeting_coverage_export WHERE state='present' AND count=0) AS coverage_present_without_rows,
            (SELECT count(*) FROM (SELECT record_sha FROM youtube_cache_bodies UNION SELECT record_sha FROM youtube_api_bodies) b WHERE b.record_sha NOT IN ({explorer_settled_sql('video_records')})) AS unsettled_video_records,
            (SELECT count(*) FROM ({CANDIDATE_SQL}) c WHERE c.record_sha NOT IN ({explorer_settled_sql('committee_records')})) AS unsettled_committee_records,
            (SELECT count(*) FROM videos_export WHERE (title IS NOT NULL AND (title='' OR regexp_like(title,'^\s|\s$'))) OR (source_description IS NOT NULL AND (source_description='' OR regexp_like(source_description,'^\s|\s$')))) AS untrimmed_video_texts,
            ((SELECT count(*) FROM (SELECT video_key,unnest(event_ids) AS event_id FROM recordings_export WHERE event_ids IS NOT NULL) re
              WHERE NOT EXISTS (SELECT 1 FROM (SELECT video_key,status,decision,unnest(meeting_links) AS link FROM recording_matches_export WHERE video_key IS NOT NULL AND meeting_links IS NOT NULL) rm
                WHERE rm.video_key=re.video_key AND rm.link['scope']='event' AND rm.link['event_id']=re.event_id AND rm.status IN ('asserted','claimed','decided') AND coalesce(rm.decision,'') NOT IN ('no_video_found','not_public')))
             + (SELECT count(*) FROM (SELECT DISTINCT video_key,link['event_id'] AS event_id FROM (SELECT video_key,status,decision,unnest(meeting_links) AS link FROM recording_matches_export WHERE video_key IS NOT NULL AND meeting_links IS NOT NULL) WHERE link['scope']='event' AND link['event_id'] IS NOT NULL AND status IN ('asserted','claimed','decided') AND coalesce(decision,'') NOT IN ('no_video_found','not_public')) rm
                WHERE NOT EXISTS (SELECT 1 FROM (SELECT video_key,unnest(event_ids) AS event_id FROM recordings_export WHERE event_ids IS NOT NULL) re
                  WHERE re.video_key=rm.video_key AND re.event_id=rm.event_id))) AS recording_event_link_mismatches,
            (SELECT count(*) FROM (SELECT event_id,tr['video_key'] AS video_key FROM (SELECT event_id,unnest(transcripts) AS tr FROM meetings_export WHERE transcripts IS NOT NULL) WHERE tr['source']='captions') mc
              WHERE NOT EXISTS (SELECT 1 FROM (SELECT video_key,unnest(event_ids) AS event_id FROM recordings_export WHERE event_ids IS NOT NULL) re
                WHERE re.video_key=mc.video_key AND re.event_id=mc.event_id)) AS meeting_caption_link_mismatches""")]
        meta_explorer=[dict(name='videos_in_several_channels',sql="SELECT count(*) AS videos FROM (SELECT v['video_id'] AS video_id FROM (SELECT unnest(r.videos) AS v FROM selected_video_records r JOIN youtube_cache_bodies b ON encode(r.record_sha,'hex')=b.record_sha WHERE r.source='youtube_cache') GROUP BY v['video_id'] HAVING count(DISTINCT v['handle'])>1)")]
    if prepared.get('historical_recording_matcher'):
        from viewer_publication.historical_recording_matcher import SOURCE_FIELDS
        keys=['source_snapshot_sha256','source_record_ordinal']
        columns=','.join((*SOURCE_FIELDS,*keys))
        auxiliary.append(('historical_recording_matches',f'SELECT {columns} FROM historical_recording_matcher_input',keys,[]))
    auxiliary += [('url_state','SELECT * FROM url_state',['requested_url'],['last_outcome']),
        ('url_variants','SELECT * FROM url_variants',['variant_url','canonical_url'],[]),
        ('retired_links',(Path(root)/'model/sql/retired-links.sql').read_text(),['link_key'],[]),
        ('corrections',(Path(root)/'model/sql/corrections.sql').read_text(),['original_url','rejected_body'],[])]
    extra=[dict(name='document_rows.parquet',path=str(evidence/'document_rows.parquet'),sql='SELECT list_row,doc_key AS document_id,'+','.join(LIST_COLUMNS+DETAIL_COLUMNS)+' FROM details',settings=_settings('whole',['list_row'],footer_limit=4 << 20)),
        dict(name='source_members.parquet',path=str(evidence/'source_members.parquet'),sql="""SELECT DISTINCT o.doc_key AS document_id,o.list_row,
        m.source_id,CASE WHEN m.body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(m.body_sha,1,2)||'/'||m.body_sha||'.gz' END AS body_key,
        m.filename AS effective_filename,m.source_url,c.member_path
        FROM document_members m JOIN document_identities d ON m.component=d.component JOIN ordered o ON d.document_id=o.doc_key
        LEFT JOIN capture_source_contexts c ON m.source_id=c.source_id""",settings=_settings('whole',['document_id','source_id','member_path'],footer_limit=4 << 20))]
    org_diagnostics=[]
    org_meta_queries=[]
    if prepared.get('include_org_entities'):
        org_dir=evidence/'org_entities'
        org_dir.mkdir(parents=True,exist_ok=True)
        steps += org_entity_steps(root=root)
        if prepared.get('publish_org_entities'):
            auxiliary += [
                ('organizations','SELECT * FROM organizations',['org_id'],['kind','taxonomy_parent','taxonomy_category']),
                ('organization_ids','SELECT * FROM organization_ids',['org_id','scheme','value'],['scheme']),
                ('witness_organizations','SELECT * FROM witness_organizations',['witness_key','field'],['field']),
                ('organization_redirects','SELECT * FROM organization_redirects',['old_org_id'],['event','release']),
            ]
            extra += org_entity_outputs(org_dir,include_public=False,include_evidence=True)
        else:
            extra += org_entity_outputs(org_dir)
        org_meta_queries,org_diagnostics=org_entity_queries()
    causes={
        'capture_evidence':['receipt_key','receipt_line','capture_index'],
        'record_roles':['receipt_key','receipt_line','capture_index'],
        'capture_sources':['source_id','receipt_key','receipt_line','capture_index'],
        'page_facts':['body_sha'],
        'valid_rendition_members':['group_kind','group_id','source_id','body_sha'],
        'publisher_links':['source_id','page_body','context','link_index','split_position','target_member_path'],
        'recording_video_links':['page_body','extracted_key'],
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
        # The recorded disposition (ct-m878, ct-egoo): a landing page that names no saved file and has no
        # parts has no document; its notice lists nothing. 619db5f9e08e's two (multi-part packages) now list their parts.
        dict(name='unplaced_landing_pages',sql="SELECT DISTINCT page_url AS url FROM landing_pages WHERE component IS NULL ORDER BY 1"),
        SAVED_NAME_KINDS,SAVED_NAME_DECISIONS_UNUSED,SAVED_NAME_DECISIONS_UNMET,
        # The recorded reason for each blank filename (ct-yf1c); unexplained_blank_filenames refuses the rest.
        dict(name='blank_filename_reasons',sql=f"SELECT reason,count(*) AS documents FROM ({BLANK_FILENAMES_SQL}) r GROUP BY 1 ORDER BY 1"),
        UNRESOLVED_MEETING_DOCUMENT_URLS,MERGED_RECOVERY_FIELDS,RECOVERY_FILE_AGREEMENT,RECOVERED_FILE_ROLES_UNUSED,FILENAME_BOTH_NAMES,
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
    meta_queries += org_meta_queries
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
            -- Title corrections live in title-overrides.json (title design Q3); a review title_override is refused, never dropped.
            (SELECT count(*) FROM review_overrides WHERE title_override IS NOT NULL) AS retired_title_reviews,
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
            (SELECT n FROM page_metadata_pointer_repeats) AS duplicate_page_metadata_pointers,
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
            LANDING_PAGE_INVARIANTS,RECOVERED_FILE_INVARIANTS]+explorer_diagnostics+url_state_diagnostics()+org_diagnostics+completeness_checks(
            catalog_version=catalog_version,
            include_entities=bool(prepared.get('include_entities')),
            meeting_records_version=parser_versions.get('meeting_records') if isinstance(parser_versions,dict) else None,
            appearance_records_version=parser_versions.get('appearance_records') if isinstance(parser_versions,dict) else None,
            carried_html_metadata=prepared.get('carried_html_metadata',0),
            root=root))
    return manifest
