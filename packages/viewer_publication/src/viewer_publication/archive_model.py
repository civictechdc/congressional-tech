"""Application-owned policy inputs and native SQL for raw-derived releases."""
import json
from pathlib import Path

from congress_api.retention.provenance import json_input,list_of

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
    'filename_parameters':dict(priority='Int64',parameter='Utf8'),
    'import_runs':dict(run_id='Utf8',date='Utf8'),
    'credential_parameters':dict(parameter='Utf8'),
    'recovery_kinds':dict(category='Utf8',match_basis='Utf8',kind='Utf8',import_category='Utf8'),
    'capture_scope':dict(family='Utf8',patterns=list_of('Utf8'),exclusions=list_of('Utf8')),
}


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
        inputs.append(json_input(directory,name,value,**fields))
    return inputs


def grouping_steps(*,node_limit=10_000_000,root=ROOT,review_edges=False):
    """Join narrow source/body memberships through the one native graph step.

    Inputs are source_files, source_endpoints (with the shared normalized
    endpoint_key), source_directories, publisher_links, and body_fingerprints.
    """
    steps=[dict(name='fingerprints',sql='SELECT body_sha,max(fingerprint) AS fingerprint FROM body_fingerprints GROUP BY body_sha',materialize=True)]
    for name in ['endpoint-bodies','fingerprint-candidates','ambiguous-endpoints','edition-bodies',
                 'rendition-members','valid-rendition-members','source-edges']:
        steps.append(dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True))
    if review_edges:
        steps[-1]['sql']+=' UNION SELECT left_node,right_node FROM body_review_edges'
    steps.append(dict(name='source_components',components=dict(sql='SELECT left_node,right_node FROM source_edges',
        left='left_node',right='right_node',node_limit=node_limit)))
    steps.append(dict(name='source_labels',sql="SELECT f.source_id,c.component FROM source_files f JOIN source_components c ON c.node='s:'||f.source_id",materialize=True))
    return steps


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
        'good-fetches','capture-locators','body-signals','locator-signals','placeholders','record-roles',
        'page-contexts','link-inputs']
    return [writer_admission_step(root=root)]+[dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=name not in ('capture-evidence',))
        for name in names]


def evidence_checks():
    """Expose current prefix checks for admission and the full invariant report."""
    from congress_api.lake.readings import writer_admission_conflict_sql
    return dict(conflicting_writer_formats='(SELECT n FROM ('+writer_admission_conflict_sql()+') writer_conflicts)',
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


def _sql_steps(names,*,root=ROOT):
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/(name+'.sql')).read_text(),materialize=True) for name in names]


def admission_steps(*,prelude=(),root=ROOT):
    """Use the full model's maintained input prefix before accepting a skip."""
    from viewer_publication.archive_provenance import current_steps
    from viewer_publication.archive_model_profile import completeness_steps
    return list(prelude)+current_steps(root=root)+evidence_steps(root=root)+source_steps(root=root)+completeness_steps(root=root)


def admission_checks(*,parser_versions,catalog_version,root=ROOT):
    """Check current pinned inputs without exporting public release files."""
    from viewer_publication.archive_model_profile import completeness_checks
    from congress_api.lake.readings import bundle_version,worker_limits
    checks=','.join(sql+' AS '+name for name,sql in evidence_checks().items())
    return [dict(name='model_invariants',sql='SELECT '+checks)]+completeness_checks(
        catalog_version=catalog_version,readings_version=bundle_version(parser_versions,policy=worker_limits()),root=root)


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
                         unreadable_files=(),variant_files=(),root=ROOT):
    """Freeze current input selectors and the shared prefix in fresh private scratch."""
    from viewer_publication.archive_format import _settings
    from viewer_publication.archive_model_profile import profile_record
    scratch=Path(scratch).resolve();scratch.mkdir(parents=True,exist_ok=False)
    evidence=scratch/'evidence';evidence.mkdir()
    inputs=registry_inputs(scratch/'registries',root=root)
    data_inputs=[dict(value,name=name) if isinstance(value,dict) else
        dict(name=name,kind='parquet',path=str(Path(value).resolve())) for name,value in
        [('captures',captures),('readings',readings),('filename_readings',filename_readings)]]
    inputs += data_inputs
    inputs.append(json_input(scratch,'parser_versions',[dict(parser=p,version=v) for p,v in sorted(parser_versions.items())],parser='Utf8',version='Utf8'))
    # Provenance is immutable input data; JSON columns with heterogeneous values
    # are projected once by the native reader before policy joins.
    from viewer_publication.archive_provenance import provenance_inputs
    provenance,prelude=provenance_inputs(scratch/'provenance',recovery_files=recovery_files,review_files=review_files)
    inputs += provenance
    verification_schema=dict(key='Utf8',size='Int64',intact='Boolean',sha256_verified='Boolean',checked_at='Utf8')
    if verification_files:
        from congress_api.retention.provenance import field
        inputs.append(dict(name='verification_records',kind='json_lines',files=list(verification_files),schema=dict(fields=[field(k,v) for k,v in verification_schema.items()],metadata={})))
    else:inputs.append(json_input(scratch,'verification_records',[],**verification_schema))
    inputs.append(json_input(scratch,'url_state_meeting_dates',[],requested_url='Utf8',meeting_date='Date32'))
    variant_fields={name:'Utf8' for name in ['id','canonical_url','variant_url','basis','decided_at','supersedes']}
    if variant_files:
        from congress_api.retention.provenance import field
        inputs.append(dict(name='url_variant_records',kind='json_lines',files=list(variant_files),schema=dict(fields=[field(k,v) for k,v in variant_fields.items()],metadata={})))
    else:inputs.append(json_input(scratch,'url_variant_records',[],**variant_fields))
    prelude += [dict(name='url_variants',sql='SELECT DISTINCT canonical_url,variant_url FROM url_variant_records r WHERE NOT EXISTS(SELECT 1 FROM url_variant_records s WHERE s.supersedes=r.id)',materialize=True)]
    unreadable_fields=dict(id='Utf8',body_sha256='Utf8',record_sha='Utf8',parser='Utf8',parser_version='Utf8',supersedes='Utf8')
    if unreadable_files:
        from congress_api.retention.provenance import field
        inputs.append(dict(name='unreadable_records',kind='json_lines',files=list(unreadable_files),schema=dict(fields=[field(k,v) for k,v in unreadable_fields.items()],metadata={})))
    else:inputs.append(json_input(scratch,'unreadable_records',[],**unreadable_fields))
    prelude += [dict(name='active_unreadable',sql='SELECT u.* FROM unreadable_records u WHERE NOT EXISTS(SELECT 1 FROM unreadable_records s WHERE s.supersedes=u.id)',materialize=False)]
    from congress_api.models.archive_profile import build_capture_profile
    capture_profile=build_capture_profile(engine_revision=engine.source_revision,
        url_normalized_sql=(Path(root)/'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(Path(root)/'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((Path(root)/'model/registries/url-rules.json').read_text()))
    from congress_api.retention.provenance import file_pin
    selectors={item['name']:dict(item) if item['kind']=='native_table' else dict(kind='parquet',path=item['path'],**file_pin(item['path'])) for item in data_inputs}
    model_profile=profile_record(parser_versions=parser_versions,catalog_version=catalog_version,
        engine_revision=engine.source_revision,runtime_pins=dict(platform=engine.platform,build_features=list(engine.build_features),
            binary_sha256=engine.binary_sha256,limits=json.loads(engine.limits.read_text())),
        lake_versions={name:dict(schema_sha256=file_pin(Path(root)/'model/lake'/(name.replace('_','-')+'.schema.json'))['sha256']) for name in ['captures','readings','filename_readings']},
        snapshots=selectors,writer_settings=dict(schema_version=1,whole=_settings('whole',['list_row']),
            ranged=_settings('ranged',['list_row']),lookup=_settings('lookup',['link_key'])),root=root)
    (scratch/'profile.json').write_text(json.dumps(model_profile,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    return dict(inputs=inputs,prelude=prelude,steps=admission_steps(prelude=prelude,root=root),
        profile=model_profile,capture_profile=capture_profile,scratch=scratch,evidence=evidence,
        parser_versions=dict(parser_versions),catalog_version=catalog_version)


def build_release(*,captures,readings,filename_readings,parser_versions,catalog_version,
                  engine,output,scratch,recovery_files=(),review_files=(),verification_files=(),
                  unreadable_files=(),variant_files=(),root=ROOT):
    """Prepare inputs once and run the document model's maintained full job."""
    prepared=prepare_model_inputs(captures=captures,readings=readings,filename_readings=filename_readings,
        parser_versions=parser_versions,catalog_version=catalog_version,engine=engine,scratch=scratch,
        recovery_files=recovery_files,review_files=review_files,verification_files=verification_files,
        unreadable_files=unreadable_files,variant_files=variant_files,root=root)
    return build_prepared_release(prepared,engine=engine,output=output,root=root)


def build_prepared_release(prepared,*,engine,output,root=ROOT):
    """Continue one prepared plan through grouping and the shared native exporter."""
    from viewer_publication.archive_format import _execute,_settings,EMPTY_STRINGS,TS,_empty_struct,LIST_COLUMNS,DETAIL_COLUMNS
    from viewer_publication.archive_annotations import annotation_steps
    from viewer_publication.archive_provenance import attachment_steps,body_review_steps
    scratch=prepared['scratch'];evidence=prepared['evidence'];output=Path(output).resolve()
    inputs=prepared['inputs'];capture_profile=prepared['capture_profile']
    parser_versions=prepared['parser_versions'];catalog_version=prepared['catalog_version']
    steps=list(prepared['steps'])+link_steps(root=root)
    steps += [dict(name='url_inputs',sql=(Path(root)/'model/sql/model-url-inputs.sql').read_text(),materialize=True)]
    steps += _sql_steps(['url-normalized'],root=root)
    steps += [dict(name='model_url_keys',sql=(Path(root)/'model/sql/url-keys.sql').read_text(),materialize=True)]
    steps += _sql_steps(['source-endpoints','copy-url-keys','publisher-links'],root=root)
    steps += [dict(name='resolved_link_targets',sql="SELECT DISTINCT page_body,context_url,member_path,target_url,cast(NULL AS VARCHAR) AS target_member_path FROM resolved_links WHERE target_member_path IS NULL",materialize=True)]
    steps += [dict(name='body_fingerprints',sql="SELECT encode(body_sha,'hex') AS body_sha,encode(fingerprint,'hex') AS fingerprint FROM page_facts WHERE status='completed'",materialize=True)]
    steps += body_review_steps(root=root)+grouping_steps(root=root,review_edges=True)
    steps += [dict(name='recovery_original_keys',sql="SELECT r.recovery_id,k.url_key FROM model_recovery_rows r JOIN model_url_keys k ON r.original_url=k.url WHERE k.error IS NULL",materialize=True),
        dict(name='component_members',sql='SELECT l.component,f.* FROM source_labels l JOIN source_files f USING(source_id)',materialize=True)]
    steps += attachment_steps(root=root)+_sql_steps(['initial-document-link-keys'],root=root)
    from viewer_publication.archive_reviews import duplicate_steps,application_steps
    steps += duplicate_steps(root=root)
    steps += [dict(name='review_components',components=dict(sql='SELECT left_node,right_node FROM duplicate_component_edges',left='left_node',right='right_node',node_limit=10_000_000))]
    steps += _sql_steps(['final-source-labels','final-recovery-attachments','document-link-keys'],root=root)
    steps += annotation_steps(catalog_version=catalog_version,root=root)
    steps += _sql_steps(['document-members','document-bodies','document-identities','saved-files','document-alternates',
        'document-version-keys','document-versions','document-metadata','document-addresses','saved-recoveries','document-removals','document-packages'],root=root)
    steps += [dict(name='base_normalized',sql=(Path(root)/'model/sql/document-normalized.sql').read_text()+' UNION ALL '+(Path(root)/'model/sql/document-recovery-normalized.sql').read_text(),materialize=True)]
    from viewer_publication.archive_model_profile import completeness_checks
    from congress_api.lake.readings import bundle_version,worker_limits
    steps += application_steps(root=root)
    steps += [dict(name='normalized',sql="""SELECT n.* EXCLUDE(title,document_kind,hidden,review_note,review_decided_at,removed_on),
        coalesce(r.title_override,n.title) AS title,coalesce(r.kind_override,n.document_kind) AS document_kind,
        coalesce(r.hidden,false) AS hidden,r.note AS review_note,r.decided_at AS review_decided_at,x.removed_on
        FROM document_removals x RIGHT JOIN (review_overrides r RIGHT JOIN
            (document_identities d JOIN base_normalized n ON n.doc_key=d.document_id)
            ON d.component=r.component) ON d.component=x.component""",materialize=True),
        dict(name='source_input',sql=(Path(root)/'model/sql/document-source-input.sql').read_text(),materialize=True),
        dict(name='recovery_input',sql=(Path(root)/'model/sql/document-recovery-input.sql').read_text(),materialize=True)]
    empty_meetings=f"""WITH keys AS (SELECT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered)
        SELECT DISTINCT event_id,cast(NULL AS VARCHAR) AS chamber,cast(NULL AS VARCHAR) AS title,cast(NULL AS DATE) AS meeting_date,
        cast(NULL AS VARCHAR) AS meeting_type,cast(NULL AS SMALLINT) AS session,cast(NULL AS VARCHAR) AS status,
        {_empty_struct(start=TS,end=TS,place='cast(NULL AS VARCHAR)')} AS sittings,
        {_empty_struct(system_code='cast(NULL AS VARCHAR)',role='cast(NULL AS VARCHAR)')} AS committees,
        {EMPTY_STRINGS} AS subject_keys,{_empty_struct(package_id='cast(NULL AS VARCHAR)',list_row='cast(NULL AS INT)')} AS transcripts,
        {_empty_struct(name='cast(NULL AS VARCHAR)',url='cast(NULL AS VARCHAR)',video_key='cast(NULL AS VARCHAR)')} AS videos
        FROM keys WHERE event_id IS NOT NULL"""
    from viewer_publication.archive_url_state import url_state_steps,url_state_diagnostics
    steps += url_state_steps(root=root)
    auxiliary=[('meetings',empty_meetings,['event_id'],['chamber','meeting_type','status']),
        ('url_state','SELECT * FROM url_state',['requested_url'],['last_outcome']),
        ('url_variants','SELECT * FROM url_variants',['canonical_url','variant_url'],[])]
    extra=[dict(name='document_rows.parquet',path=str(evidence/'document_rows.parquet'),sql='SELECT list_row,doc_key AS document_id,'+','.join(LIST_COLUMNS+DETAIL_COLUMNS)+' FROM details',settings=_settings('whole',['list_row'])),
        dict(name='source_members.parquet',path=str(evidence/'source_members.parquet'),sql="""SELECT DISTINCT o.doc_key AS document_id,o.list_row,
        m.source_id,CASE WHEN m.body_sha IS NOT NULL THEN 'bodies/sha256/'||substr(m.body_sha,1,2)||'/'||m.body_sha||'.gz' END AS body_key,
        m.filename AS effective_filename,m.source_url,c.member_path
        FROM document_members m JOIN document_identities d ON m.component=d.component JOIN ordered o ON d.document_id=o.doc_key
        LEFT JOIN capture_source_contexts c ON m.source_id=c.source_id""",settings=_settings('whole',['document_id','source_id','member_path']))]
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
        'rendition_members':['group_kind','group_id','source_id','body_sha'],
        'edition_bodies':['body_sha'],
        'fingerprint_candidates':['body_sha'],
        'fingerprints':['body_sha']}
    page_facts_export = """SELECT r.* FROM (
        SELECT r.body_sha,min(r.format) AS format FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
        WHERE r.parser='sniff' GROUP BY r.body_sha
    ) s JOIN (
        SELECT r.* FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
        WHERE r.parser IN ('html','xml','json')
    ) r ON r.body_sha=s.body_sha AND r.parser=s.format"""
    fingerprints_export = """SELECT encode(r.body_sha,'hex') AS body_sha,max(encode(r.fingerprint,'hex')) AS fingerprint
    FROM (
        SELECT r.body_sha,min(r.format) AS format FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
        WHERE r.parser='sniff' GROUP BY r.body_sha
    ) s JOIN (
        SELECT r.* FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
        WHERE r.parser IN ('html','xml','json')
    ) r ON r.body_sha=s.body_sha AND r.parser=s.format
    WHERE r.status='completed'
    GROUP BY encode(r.body_sha,'hex')"""
    capture_sources_export = """SELECT
        k.source_id,k.receipt_key,k.receipt_line,k.capture_index,
        s.body_sha,s.filename,s.source_url,k.context_url,k.member_path,
        s.format,s.is_real_file,s.record_role,
        arrow_cast(c.retrieved_at,'Timestamp(Microsecond, Some("UTC"))') AS retrieved_at,
        cast(s.in_archive_since AS DATE) AS import_date,
        k.outcome,c.http_status
    FROM capture_source_contexts k
    JOIN source_files s ON k.source_id=s.source_id
    JOIN captures c ON k.receipt_key=c.receipt_key AND k.receipt_line=c.receipt_line AND k.capture_index=c.capture_index"""
    extra += [dict(name=name+'.parquet',path=str(evidence/(name+'.parquet')),
        sql=("SELECT r.*,r.body_sha AS body_sha256,d.decided_at,d.recovered_url,d.identity_note FROM current_recoveries r LEFT JOIN remaining_recovery_decisions d ON r.decision_id=d.id" if name=='current_recoveries' else page_facts_export if name=='page_facts' else fingerprints_export if name=='fingerprints' else capture_sources_export if name=='capture_sources' else 'SELECT * FROM '+name),settings=_settings('whole',keys)) for name,keys in causes.items()]
    prefix_checks=','.join(sql+' AS '+name for name,sql in evidence_checks().items())
    manifest=_execute(inputs,steps,output=output,scratch=scratch,engine=engine,
        lookup_extra="SELECT o.list_row,a.url FROM source_addresses a JOIN document_members m ON a.source_id=m.source_id JOIN document_identities d ON m.component=d.component JOIN ordered o ON d.document_id=o.doc_key WHERE m.is_real_file",
        metadata_queries=[input_receipts_query(),probe_selectors_query(root=root)],origin=dict(kind='model',gaps=[]),content_files={'capture_profile.json':capture_profile},auxiliary=auxiliary,extra_outputs=extra,
        capture_scope=json.loads((Path(root)/'model/registries/capture-scope.json').read_text()),
        diagnostics=[dict(name='model_invariants',sql=f"""SELECT {prefix_checks},
            (SELECT count(*) FROM model_url_keys WHERE error IS NOT NULL) AS invalid_url_keys,
            (SELECT count(*) FROM recovery_attachment_diagnostics) AS invalid_recovery_attachments,
            (SELECT count(*) FROM body_review_key_conflicts) AS body_key_collisions,
            (SELECT count(*) FROM document_link_key_conflicts) AS review_key_collisions,
            (SELECT count(*) FROM review_value_diagnostics) AS invalid_review_values,
            (SELECT CASE WHEN count(*)=0 THEN 1 ELSE 0 END FROM ordered) AS empty_document_list,
            (SELECT count(*) FROM (SELECT unnest(alternates) AS alt FROM document_alternates) WHERE alt['size'] IS NULL) AS missing_alternate_sizes""")]+url_state_diagnostics()+completeness_checks(catalog_version=catalog_version,readings_version=bundle_version(parser_versions,policy=worker_limits()),root=root))
    return manifest
