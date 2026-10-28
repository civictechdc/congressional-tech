"""Versioned narrow receipt index. Native SQL interprets retained raw evidence."""
from hashlib import sha256
import json
from pathlib import Path

from congress_api.retention.provenance import parquet_output, run_job, json_input, file_pin
from congress_api.lake.receipt_metadata import get, lit as literal, obj, projection, scalar, SCALARS, RECOVERY, DOWNLOAD_HEADERS


LEGACY_OUTCOMES = {
    'archive_throttled': 'retry_later', 'available': 'derive',
    'build-complete': 'derive', 'candidate_live_and_archive_manifests_not_found': 'failed',
    'captured': 'derive', 'complete': 'derive', 'detail_refused': 'failed',
    'empty': 'derive', 'empty_response': 'derive', 'error': 'failed',
    'error_or_unrecognized_html': 'derive', 'exception': 'request_failed',
    'excluded_media': 'failed', 'html': 'derive', 'html_body': 'derive',
    'http_error': 'failed', 'invalid_document': 'derive',
    'no_declared_webvtt': 'derive', 'no_english_webvtt': 'derive',
    'no_explicit_download_or_pdf_embed': 'derive', 'no_valid_master': 'derive',
    'not_found': 'failed', 'original_not_in_package': 'failed', 'pdf': 'derive',
    'publisher_placeholder': 'derive', 'request_failed': 'request_failed',
    'request_or_parse_error': 'request_failed', 'resource_limit': 'size_limit',
    'retained': 'derive', 'retained_pdf_not_html': 'derive',
    'retained_valid_master': 'derive', 'retry_later': 'retry_later',
    'saved': 'derive', 'server_error': 'failed', 'size_limit': 'size_limit',
    'stream_present_no_separate_subtitle_track_embedded_not_checked': 'derive',
    'subtitle_playlist_found_needs_capture': 'derive', 'timeout': 'request_failed',
    'unsupported_or_placeholder_player': 'derive', 'unverified': 'derive',
    'stored': 'stored', 'unchanged': 'unchanged', 'failed': 'failed',
}
LEGACY_MODES = {
    'fetch', 'retained_import', 'replay', 'native_live', 'import', 'native',
    'dated_archive_live_retrieval', 'zyte', 'additive-cached-replay',
    'cache_reference', 'wayback',
    'Replay verified captures with current parser; --limit 0 forbids additional downloads',
}
PK = ['receipt_key', 'receipt_line', 'capture_index']
COLUMNS = [*PK, 'run_id', 'mode', 'outcome', 'family', 'requested_url', 'url',
    'context_url', 'member_path', 'h_content_disposition', 'http_status', 'complete', 'retrieved_at',
    'sha256', 'bytes', 'media_type', 'fidelity', 'sniffed_format', 'sniff_version',
    'intact', 'expansion', 'stored_suffix', 'stored_bytes',
    'stored_md5', 'recovery_category', 'original_url', 'recovered_url', 'match_basis',
    'evidence_sha256', 'imported_at', 'writer_job', 'writer_commit']


def current_version():
    """The existing mapping identity shared by ingest and daily admission."""
    return sha256(Path(__file__).read_bytes()+(Path(__file__).parent/'receipt_metadata.py').read_bytes()).hexdigest()


def first(*values):
    return 'coalesce(' + ','.join(values) + ')'


def stamp(*values):
    return 'try_cast(' + first(*values) + ' AS TIMESTAMP WITH TIME ZONE)'


def metadata_field(value, name):
    return f"get_field({value},{literal(name)})"


def fetch_time(value, getter=get):
    fields = [getter(value, p) for p in (
        'retrieved_at', 'captured_at', 'observed_at', 'parent_retrieved_at', '_retrieved_at')]
    return stamp(*fields, getter(value, 'capture_date'))


def mapping_steps():
    steps=[]
    def step(name,sql,**options):
        steps.append(dict(name=name,sql=sql,**options))
    # One shared source projection feeds the independent item and reference
    # branches. Items are parsed once, before scalar lookup by source/item ID.
    step('item_entries', """SELECT source_row_id,receipt_key,receipt_line,
        unnest(record_items) AS item,
        unnest(range(0,cast(record_count AS BIGINT))) AS item_index
        FROM lines WHERE record_is_list""")
    paths=[(name,) for name in SCALARS]+list(RECOVERY.values())+DOWNLOAD_HEADERS+[('error',)]
    slots=projection('item',paths)
    item_fields={name:scalar(slots[(name,)],kind) for name,kind in SCALARS.items()}
    item_fields.update({name:scalar(slots[path],'str') for name,path in RECOVERY.items()})
    item_fields['h_content_disposition']=first(*(scalar(slots[path],'str') for path in DOWNLOAD_HEADERS))
    item_fields['error_present']=get(slots[('error',)],kind='json')+' IS NOT NULL'
    step('items','SELECT source_row_id,receipt_key,receipt_line,item_index,'+
        ','.join(value+' AS i_'+name for name,value in item_fields.items())+' FROM item_entries',materialize=True)
    step('reference_lists', """SELECT * EXCEPT(record_items),
        CASE WHEN coalesce(array_length(caps),0)>0 THEN 'capture'
             WHEN coalesce(array_length(refs),0)>0 THEN 'file' ELSE 'line' END AS reference_kind,
        CASE WHEN coalesce(array_length(caps),0)>0 THEN caps
             WHEN coalesce(array_length(refs),0)>0 THEN refs
             ELSE array_repeat(cast(NULL AS VARCHAR),cast(greatest(coalesce(record_count,0),1) AS BIGINT)) END AS primary_refs,
        CASE WHEN coalesce(array_length(caps),0)>0 THEN refs ELSE make_array(cast(NULL AS VARCHAR)) END AS storage_refs
        FROM lines""")
    step('reference_counts', """SELECT * EXCEPT(caps,refs),array_length(primary_refs) AS primary_count,
        CASE WHEN record_is_list AND reference_kind<>'line' THEN coalesce(record_count,0) ELSE 0 END AS placeholder_count,
        CASE WHEN coalesce(array_length(caps),0)>0 THEN coalesce(array_length(refs),0) ELSE 0 END AS storage_count
        FROM reference_lists""")
    step('entries', """SELECT source_row_id,receipt_key,receipt_line,line,record,record_is_list,reference_kind,
        primary_count,placeholder_count,cast(record_count AS BIGINT) AS source_record_count,invalid_lists,
        unnest(array_concat(array_concat(primary_refs,array_repeat(cast(NULL AS VARCHAR),cast(placeholder_count AS BIGINT))),
            CASE WHEN storage_count>0 THEN storage_refs ELSE make_array() END)) AS entry,
        unnest(range(0,cast(primary_count+placeholder_count+storage_count AS BIGINT))) AS ordinal FROM reference_counts""")
    pointer_index=first(get('entry','pointer',0,kind='int'),f'try_cast({get("entry","pointer",0)} AS BIGINT)',
        get('entry','pointer',1,kind='int'),f'try_cast({get("entry","pointer",1)} AS BIGINT)','0')
    step('entry_positions',f"""SELECT *,ordinal>=primary_count+placeholder_count AS is_secondary,
        ordinal>=primary_count AND ordinal<primary_count+placeholder_count AS is_placeholder,
        cast(CASE WHEN record_is_list THEN CASE WHEN ordinal>=primary_count AND ordinal<primary_count+placeholder_count
            THEN ordinal-primary_count WHEN reference_kind='line' THEN ordinal
            ELSE cast({pointer_index} AS BIGINT) END ELSE 0 END AS BIGINT) AS selected_record_index FROM entries""")
    # One shared literal entry bundle; only scalar values and its small pointer
    # remain after this step. No original body, prior or header object is read.
    strings=('sha256','body_key','family','context_url','member_path','original_path',
        'media_type','fidelity','sniffed_format','sniff_version','expansion','stored_suffix',
        'stored_md5','pointer_json','retrieved_at','captured_at','observed_at',
        'parent_retrieved_at','_retrieved_at','capture_date')
    kinds={**dict.fromkeys(strings,'str'),**dict.fromkeys(('bytes','size','attempt','stored_bytes'),'int'),
           **dict.fromkeys(('complete','intact'),'bool'),'pointer':'json'}
    entry_slots=projection('entry',[(name,) for name in kinds])
    step('entry_facts','SELECT * EXCEPT(entry),'+','.join(
        scalar(entry_slots[(name,)],kind)+' AS e_'+name for name,kind in kinds.items())+' FROM entry_positions')
    step('selected_records',"""SELECT e.* EXCEPT(source_row_id,reference_kind),
        CASE WHEN is_placeholder THEN 'line' ELSE e.reference_kind END AS reference_kind,
        CASE WHEN is_placeholder OR e.reference_kind='line' THEN selected_record_index ELSE 0 END AS list_ordinal,
        ordinal AS capture_index,"""+','.join('i.i_'+name for name in item_fields)+"""
        FROM entry_facts e LEFT JOIN items i ON e.source_row_id=i.source_row_id
        AND (e.receipt_key IS NOT DISTINCT FROM i.receipt_key)
        AND (e.receipt_line IS NOT DISTINCT FROM i.receipt_line)
        AND e.selected_record_index=i.item_index AND e.record_is_list AND NOT e.is_secondary""")
    list_record={name:first('i_'+name,metadata_field('record',name)) for name in item_fields}
    list_record['error_present']="(coalesce(i_error_present,false) OR "+metadata_field('record','error_present')+')'
    step('records','SELECT * EXCEPT(record,'+','.join('i_'+name for name in item_fields)+'),'+
        obj(list_record)+' AS record FROM selected_records')
    def item_first(line,record):
        return f'CASE WHEN record_is_list THEN {first(record,line)} ELSE {line} END'
    def both(name):
        line,record=metadata_field('line',name),metadata_field('record',name)
        return item_first(first(line,record),record)
    step('facts',f"""SELECT *,{both('mode')} AS raw_mode,{both('outcome')} AS raw_outcome,
        {item_first(first(metadata_field('line','http_status'),metadata_field('line','status_code'),metadata_field('record','http_status'),metadata_field('record','status_code')),first(metadata_field('record','http_status'),metadata_field('record','status_code')))} AS line_status,
        {first(fetch_time('',lambda _,p:'e_'+p),item_first(first(fetch_time('line',metadata_field),fetch_time('record',metadata_field)),fetch_time('record',metadata_field)))} AS fetched,
        {first('e_family',both('family'),"regexp_replace(receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\\1')")} AS entry_family,
        {item_first(first(metadata_field('line','run_id'),metadata_field('line','source_file'),metadata_field('record','source_file')),first(metadata_field('record','run_id'),metadata_field('record','source_file')))} AS source_run,
        {item_first(first(metadata_field('line','requested_url'),metadata_field('record','requested_url'),metadata_field('record','_url'),metadata_field('record','url'),metadata_field('line','url'),metadata_field('record','final_url'),metadata_field('record','resolved_url'),metadata_field('record','source_url')),first(metadata_field('record','requested_url'),metadata_field('record','_url'),metadata_field('record','url'),metadata_field('record','final_url'),metadata_field('record','resolved_url'),metadata_field('record','source_url')))} AS requested,
        {item_first(first(metadata_field('line','url'),metadata_field('record','url'),metadata_field('record','_url'),metadata_field('record','final_url'),metadata_field('record','resolved_url'),metadata_field('record','source_url')),first(metadata_field('record','url'),metadata_field('record','_url'),metadata_field('record','final_url'),metadata_field('record','resolved_url'),metadata_field('record','source_url')))} AS final_url
        FROM records""")
    modes=','.join(literal(v) for v in sorted(LEGACY_MODES))
    outcomes=','.join(literal(v) for v in sorted(LEGACY_OUTCOMES))
    transfer={'retry_later','request_failed','size_limit','stored','unchanged','failed',
              'archive_throttled','exception','request_or_parse_error','resource_limit','timeout'}
    cases=' '.join('WHEN '+literal(k)+' THEN '+literal(v if k in transfer else 'derive') for k,v in LEGACY_OUTCOMES.items())
    recovery_names=[name for name in RECOVERY if name.startswith('recovery_')]
    recovery_present=' OR '.join(both(name)+' IS NOT NULL' for name in recovery_names)
    step('mapped',f"""SELECT *,
        CASE WHEN raw_mode='retained_import' AND {both('association_basis')}='direct_official_package'
             AND requested={both('association_original')} AND final_url=requested THEN 'fetch'
             WHEN raw_mode='retained_import' OR {recovery_present}
             OR {both('association_original')} IS NOT NULL THEN 'retained_import' ELSE 'fetch' END AS capture_mode,
        CASE raw_outcome {cases} ELSE 'derive' END AS mapped_outcome,
        raw_mode IS NOT NULL AND raw_mode NOT IN ({modes}) AS unknown_mode,
        raw_outcome IS NOT NULL AND raw_outcome NOT IN ({outcomes}) AS unknown_outcome,
        e_sha256 AS body_sha,coalesce(e_bytes,e_size) AS body_bytes,
        json_canonical(coalesce(e_pointer,e_pointer_json)) AS pointer_json,
        e_body_key AS body_key FROM facts""")
    # Pointers can prefix a source record number before the attempt path.
    prior_index=first(*(f"CASE WHEN json_get_str(pointer_json,{i})='prior_attempts' THEN coalesce(json_get_int(pointer_json,{i+1}),try_cast(json_get_str(pointer_json,{i+1}) AS BIGINT),0)+1 END" for i in (0,1,2)),'0')
    step('attempts',f"""SELECT *,coalesce(e_attempt,{prior_index}) AS attempt,
        e_member_path IS NULL AND NOT coalesce(array_has(json_get_array(pointer_json),'\"archive_members\"'),false) AS top_level
        FROM mapped""")
    recorded=first('e_complete',"CASE WHEN attempt=0 THEN "+both('complete')+' END')
    step('decisions',f"""SELECT *,{recorded} AS recorded_complete,
        {first(recorded,"NOT(coalesce(body_bytes,0)=67108864 OR mapped_outcome IN ('size_limit','request_failed'))")} AS capture_complete,
        capture_mode='fetch' AND get_field(line,'mode') IS NULL
        AND (raw_outcome IS NULL OR raw_outcome IN ('saved','captured','complete','html','html_body','pdf','retained'))
        AND {both('error_type')} IS NULL AND NOT coalesce(get_field(line,'error_present'),false)
        AND NOT coalesce(get_field(record,'error_present'),false) AS cutoff_eligible
        FROM attempts""")
    columns=dict(receipt_key='receipt_key',receipt_line='receipt_line',capture_index='capture_index',
        run_id='source_run',mode='capture_mode',
        outcome="CASE WHEN line_status IN (429,503) THEN 'retry_later' WHEN line_status=304 THEN 'unchanged' WHEN mapped_outcome<>'derive' THEN mapped_outcome WHEN body_sha IS NOT NULL AND (line_status BETWEEN 200 AND 299 OR line_status IS NULL) THEN 'stored' ELSE 'failed' END",
        family='entry_family',requested_url='requested',url='final_url',
        context_url=first('e_context_url','final_url'),
        member_path=first('e_member_path',"CASE WHEN NOT top_level AND reference_kind='capture' THEN e_original_path END"),
        h_content_disposition=first(metadata_field('line','h_content_disposition'),metadata_field('record','h_content_disposition')),
        http_status='cast(line_status AS INT)',complete='capture_complete',retrieved_at='fetched',
        sha256="arrow_cast(decode(body_sha,'hex'),'FixedSizeBinary(32)')",bytes='body_bytes',
        media_type='e_media_type',fidelity='e_fidelity',sniffed_format='e_sniffed_format',
        sniff_version='e_sniff_version',intact="CASE WHEN get_field(line,'writer_job') IS NOT NULL AND get_field(line,'writer_commit') IS NOT NULL THEN e_intact END",expansion='e_expansion',
        stored_suffix='e_stored_suffix',stored_bytes='e_stored_bytes',stored_md5='e_stored_md5',
        recovery_category=both('recovery_category'),
        original_url="CASE WHEN capture_mode='retained_import' THEN "+first(both('recovery_original'),both('association_original'))+' END',
        recovered_url="CASE WHEN capture_mode='retained_import' THEN "+first(both('recovery_url'),'final_url')+' END',
        match_basis="CASE WHEN capture_mode='retained_import' THEN "+first(both('recovery_basis'),both('association_basis'))+' END',
        evidence_sha256="arrow_cast(decode("+both('recovery_sha')+",'hex'),'FixedSizeBinary(32)')",
        imported_at="CASE WHEN capture_mode='retained_import' THEN coalesce(try_cast("+both('recovery_imported')+" AS TIMESTAMP WITH TIME ZONE),try_cast(array_element(regexp_match(receipt_key,'/(\\d{4}-\\d{2}-\\d{2})/'),1) AS TIMESTAMP WITH TIME ZONE)) END",
        writer_job=metadata_field('line','writer_job'),writer_commit=metadata_field('line','writer_commit'))
    diagnostics=['reference_kind','pointer_json','body_key','unknown_mode','unknown_outcome',
                 'is_secondary','list_ordinal','selected_record_index','body_sha','attempt','top_level','cutoff_eligible','invalid_lists',
                 'record_is_list','source_record_count','is_placeholder','primary_count']
    flags=dict(cutoff_candidate='attempt=0 AND top_level AND body_bytes=67108864 AND recorded_complete IS FALSE',
        completed_final='attempt=0 AND top_level AND recorded_complete IS TRUE')
    step('scalar_rows','SELECT '+','.join(f'{columns[name]} AS "{name}"' for name in COLUMNS)+
         ','+','.join(diagnostics)+','+','.join(value+' AS '+name for name,value in flags.items())+' FROM decisions',materialize=True)
    step('secondary',"""SELECT receipt_key,receipt_line,body_key,body_sha,
        max(stored_bytes) AS secondary_bytes,max(stored_md5) AS secondary_md5,max(stored_suffix) AS secondary_suffix,
        count(DISTINCT stored_bytes) AS size_variants,count(DISTINCT stored_md5) AS md5_variants,
        count(DISTINCT stored_suffix) AS suffix_variants
        FROM scalar_rows WHERE is_secondary GROUP BY receipt_key,receipt_line,body_key,body_sha""")
    step('enriched',"""SELECT p.*,s.secondary_bytes,s.secondary_md5,s.secondary_suffix
        FROM secondary s RIGHT JOIN scalar_rows p
        ON p.receipt_key=s.receipt_key AND p.receipt_line=s.receipt_line
        AND p.body_key=s.body_key AND p.body_sha=s.body_sha
        WHERE NOT p.is_secondary""")
    step('item_references',"""SELECT *,bool_or(NOT is_placeholder AND reference_kind IN ('capture','file'))
        OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_primary_reference FROM enriched""")
    step('retained_items',"""SELECT * FROM item_references WHERE NOT is_placeholder OR NOT has_primary_reference""")
    step('windowed',"""SELECT *,
        sum(CASE WHEN is_placeholder THEN 1 ELSE 0 END) OVER (PARTITION BY receipt_key,receipt_line
            ORDER BY selected_record_index,capture_index ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS appended_index,
        bool_or(cutoff_candidate) OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_cutoff,
        bool_or(completed_final) OVER (PARTITION BY receipt_key,receipt_line,selected_record_index) AS has_completed_final,
        bool_or(body_sha IS NOT NULL AND NOT top_level) OVER
            (PARTITION BY receipt_key,receipt_line,selected_record_index,attempt,context_url) AS has_member FROM retained_items""")
    final={name:name for name in COLUMNS}
    final.update(stored_suffix="coalesce(stored_suffix,secondary_suffix,'.gz')",
        stored_bytes='coalesce(stored_bytes,secondary_bytes)',
        stored_md5="arrow_cast(decode(coalesce(stored_md5,secondary_md5),'hex'),'FixedSizeBinary(16)')",
        outcome="CASE WHEN cutoff_eligible AND has_cutoff AND NOT coalesce(has_completed_final,false) AND outcome NOT IN ('retry_later','unchanged') THEN 'size_limit' ELSE outcome END",
        expansion="coalesce(expansion,CASE WHEN top_level AND has_member THEN 'expanded' END)")
    locator='arrow_cast(named_struct(\'key\',receipt_key,\'line\',cast(receipt_line AS INT),\n        \'index\',cast(CASE WHEN is_placeholder THEN primary_count+appended_index-1 ELSE capture_index END AS INT)), \'Struct("key": Utf8, "line": Int32, "index": Int32)\')'
    for name,member in zip(PK,['key','line','index']):
        final[name]=f"get_field({locator},'{member}')"
    for name in ('retrieved_at','imported_at'):
        final[name]=f"arrow_cast({final[name]}, 'Timestamp(Microsecond, Some(\"UTC\"))')"
    public_diagnostics=['reference_kind','pointer_json','body_key','unknown_mode','unknown_outcome']
    step('capture_facts','SELECT '+','.join(f'{final[name]} AS "{name}"' for name in COLUMNS)+
        ','+','.join(public_diagnostics)+',record_is_list,source_record_count,selected_record_index AS source_record_index FROM windowed',materialize=True)
    return steps


def capture_checks():
    narrow=','.join('"'+name+'"' for name in COLUMNS if name not in PK)
    return [dict(name='positions',sql="""SELECT receipt_key,receipt_line,'invalid source locator' AS reason
        FROM scalar_rows WHERE receipt_key IS NULL OR receipt_line IS NULL OR receipt_line<1 LIMIT 1"""),
        dict(name='reference_shapes',sql="""SELECT receipt_key,receipt_line,'unsupported reference list shape' AS reason
        FROM scalar_rows WHERE invalid_lists LIMIT 1"""),
        dict(name='invalid',sql="""SELECT receipt_key,receipt_line,
        CASE WHEN unknown_mode THEN 'unknown mode' ELSE 'unknown outcome' END AS reason
        FROM scalar_rows WHERE NOT is_secondary AND (unknown_mode OR unknown_outcome) LIMIT 1"""),
        dict(name='secondary',sql="""SELECT s.receipt_key,s.receipt_line,'secondary body not represented' AS reason
        FROM secondary s LEFT ANTI JOIN scalar_rows p ON NOT p.is_secondary
        AND s.receipt_key=p.receipt_key AND s.receipt_line=p.receipt_line
        AND s.body_key=p.body_key AND s.body_sha=p.body_sha WHERE s.body_sha IS NOT NULL
        UNION ALL SELECT receipt_key,receipt_line,'secondary storage conflict' AS reason FROM secondary
        WHERE size_variants>1 OR md5_variants>1 OR suffix_variants>1
        UNION ALL SELECT receipt_key,receipt_line,'primary and secondary storage conflict' AS reason
        FROM enriched WHERE
            (stored_bytes IS NOT NULL AND secondary_bytes IS NOT NULL AND stored_bytes<>secondary_bytes)
            OR (stored_md5 IS NOT NULL AND secondary_md5 IS NOT NULL AND lower(stored_md5)<>lower(secondary_md5))
            OR (stored_suffix IS NOT NULL AND secondary_suffix IS NOT NULL AND stored_suffix<>secondary_suffix)
        LIMIT 1"""),
        dict(name='list_facts',sql=f"""SELECT receipt_key,receipt_line,'list record conflicting facts' AS reason
        FROM (SELECT DISTINCT s.receipt_key,s.receipt_line,s.list_ordinal,{','.join('s.'+c for c in narrow.split(','))}
              FROM scalar_rows s JOIN (
                  SELECT receipt_key,receipt_line,list_ordinal FROM scalar_rows
                  WHERE reference_kind='line' AND NOT is_secondary
                  GROUP BY receipt_key,receipt_line,list_ordinal HAVING count(*)>1
              ) repeated ON (s.receipt_key IS NOT DISTINCT FROM repeated.receipt_key)
                  AND (s.receipt_line IS NOT DISTINCT FROM repeated.receipt_line)
                  AND (s.list_ordinal IS NOT DISTINCT FROM repeated.list_ordinal)
              WHERE s.reference_kind='line' AND NOT s.is_secondary)
        GROUP BY receipt_key,receipt_line,list_ordinal HAVING count(*)>1 LIMIT 1"""),
        dict(name='missing',sql="""SELECT r.receipt_key,cast(0 AS BIGINT) AS receipt_line,
        'selected receipt not present' AS reason FROM selected_receipts r LEFT ANTI JOIN scalar_rows s
        ON r.receipt_key=s.receipt_key LIMIT 1""")]


def stage_captures(files, *, engine, work, existing=None, validated_counter=None,
                   source_qualifications=None):
    """Create immutable local staging, refusing unknown vocabularies or lost bodies.

    Table appends are a separate explicit engine operation. A failed native read
    leaves no accepted receipt-key list, so that receipt remains work on retry.
    """
    if validated_counter is not None:
        from congress_api.lake.receipt_metadata import counter_file
        counter_file(validated_counter)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    mapping_digest = current_version()
    keys = [f['key'] for f in files]
    if len(keys) != len(set(keys)) or any(not k.startswith('receipts/') for k in keys):
        raise ValueError('Receipt inventory needs unique raw receipt keys')
    if existing is not None:
        from congress_api.lake.receipt_inventory import select_receipts
        files=select_receipts(files,existing,engine=engine,work=work/'inventory')
        keys=[f['key'] for f in files]
    if not files:
        raise ValueError('No missing receipt keys to stage')
    from congress_api.lake.receipt_metadata import source_plan,producer,source_pins,recheck_source_pins
    reader_files=[{k:f[k] for k in ('key','path') if k in f} for f in files]
    sources=source_pins(counter=validated_counter,files=files,qualifications=source_qualifications)
    plan=source_plan(counter=validated_counter,files=reader_files,receipt_keys=keys)
    inputs=plan['inputs']
    steps=plan['steps']
    input_pin=dict(kind='validated-counter' if validated_counter is not None else 'receipt-files',
        producer=producer(engine),sources=sources)
    inputs.append(json_input(work,'selected_receipts',[dict(receipt_key=k) for k in keys],
                             receipt_key='Utf8'))
    mapping=mapping_steps()
    steps+=mapping
    steps.append(dict(name='source_counts',sql='''SELECT count(*) AS rows,count(DISTINCT receipt_key) AS receipts
        FROM (SELECT receipt_key,receipt_line FROM scalar_rows WHERE NOT is_secondary AND list_ordinal=0
              GROUP BY receipt_key,receipt_line)''',materialize=True))
    checks=capture_checks()
    violations=' UNION ALL '.join(f"SELECT {index} AS check_order,v.* FROM ({check['sql']}) v"
                                  for index,check in enumerate(checks))
    stale=['source','lines','selected_receipts']+[
        step['name'] for step in mapping if step['name']!='capture_facts']
    steps.append(dict(name='capture_violations',sql=violations,materialize=True,release_after=stale))
    results = run_job(work, engine, inputs=inputs,
        steps=steps,
        outputs=[parquet_output(work, 'capture-evidence',
            'SELECT * FROM capture_facts WHERE NOT EXISTS (SELECT 1 FROM capture_violations)', PK)],
        queries=[dict(name='violations',sql='''SELECT * FROM capture_violations
            ORDER BY check_order,receipt_key,receipt_line LIMIT 1'''),
            dict(name='source_counts',sql='SELECT * FROM source_counts')])
    if results['violations']:
        row=results['violations'][0]
        raise ValueError(f"{row['reason']}: {row['receipt_key']}:{row['receipt_line']}")
    recheck_source_pins(sources)
    final = work/'export'
    final.mkdir()
    accepted = run_job(final, engine,
        inputs=[dict(name='facts', kind='parquet', path=str(work/'capture-evidence.parquet'))],
        steps=[], outputs=[parquet_output(work, 'captures',
            'SELECT '+','.join('"'+c+'"' for c in COLUMNS)+' FROM facts', PK)],
        queries=[dict(name='counts', sql='SELECT count(*) AS rows,count(DISTINCT receipt_key) AS receipts FROM facts'),
                 dict(name='receipts',sql='SELECT DISTINCT receipt_key FROM facts ORDER BY receipt_key')])
    if mapping_digest != current_version():
        raise ValueError('Receipt mapping changed while staging; accepted inventory was not written')
    input_pin['job']=file_pin(work/'job.json')
    input_pin['selection']=file_pin(work/'selected_receipts.jsonl.gz')
    outputs=json.loads((work/'result.json').read_text())['outputs']+json.loads((final/'result.json').read_text())['outputs']
    recheck_source_pins(sources)
    (work/'ingested-receipts.json').write_text(json.dumps(dict(version=2,
        mapping_digest=mapping_digest,input=input_pin,outputs=outputs,source_counts=results['source_counts'][0],
        engine=dict(source_revision=engine.source_revision,binary_sha256=engine.binary_sha256),
        receipt_keys=[r['receipt_key'] for r in accepted['receipts']]), indent=2)+'\n')
    return work
