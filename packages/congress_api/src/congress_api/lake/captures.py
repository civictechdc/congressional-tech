"""Versioned receipt mapping. Python selects files; native SQL interprets rows."""
from hashlib import sha256
import json
from pathlib import Path

from congress_api.retention.provenance import parquet_output, run_job, json_input
from congress_api.lake.receipt_metadata import get, lit as literal


# These are observed producer vocabularies, not fuzzy success guesses. New values
# require a mapping version and fixture before they can enter the lake.
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
    'record_sha', 'http_status', 'attempt_status', 'complete', 'context_url',
    'member_path', 'expansion', 'h_content_disposition', 'retry_after', 'retrieved_at',
    'sha256', 'bytes', 'media_type', 'fidelity', 'sniffed_format', 'sniff_version',
    'intact', 'stored_suffix', 'stored_md5', 'stored_bytes', 'recovery_category',
    'original_url', 'recovered_url', 'match_basis', 'evidence_sha256', 'imported_at',
    'writer_job', 'writer_commit']


def first(*values):
    return 'coalesce(' + ','.join(values) + ')'


def integer(value, *path):
    return f'try_cast(json_as_text({value},' + ','.join(literal(p) for p in path) + ') AS BIGINT)'


def stamp(*values):
    return 'try_cast(' + first(*values) + ' AS TIMESTAMP WITH TIME ZONE)'


def fetch_time(value):
    fields = [get(value, p) for p in (
        'retrieved_at', 'captured_at', 'observed_at', 'parent_retrieved_at', '_retrieved_at')]
    return stamp(*fields, get(value, 'capture_date'))


def compact_counter(counter, *, engine, work):
    from congress_api.lake.receipt_metadata import compact
    return compact(counter=counter,engine=engine,work=work)


def mapping_steps(*, existing=False):
    steps = []
    def step(name, sql, materialize=False):
        steps.append(dict(name=name, sql=sql, materialize=materialize))

    skip = (' WHERE __receipt_key NOT IN (SELECT DISTINCT receipt_key FROM existing_captures)'
            if existing else '')
    skip += (' AND ' if skip else ' WHERE ')+'__receipt_key IN (SELECT receipt_key FROM selected_receipts)'
    step('lines','SELECT __receipt_key AS receipt_key,__receipt_line AS receipt_line,'
        'line,caps_json,refs_json,record_json FROM receipts'+skip)
    record='record_json'
    step('lists',f"SELECT *,{get('caps_json',kind='array')} AS caps,{get('refs_json',kind='array')} AS refs FROM lines")
    step('primary_entries', '''SELECT receipt_key,receipt_line,line,
        CASE WHEN coalesce(array_length(caps),0)>0 THEN 'capture'
             WHEN coalesce(array_length(refs),0)>0 THEN 'file' ELSE 'line' END AS reference_kind,
        unnest(CASE WHEN coalesce(array_length(caps),0)>0 THEN caps
                    WHEN coalesce(array_length(refs),0)>0 THEN refs
                    ELSE make_array(cast(NULL AS VARCHAR)) END) AS entry,
        {record} AS record_value,
        unnest(range(0,cast(greatest(coalesce(array_length(caps),0),
            CASE WHEN coalesce(array_length(caps),0)>0 THEN 0
                 ELSE greatest(coalesce(array_length(refs),0),1) END) AS BIGINT))) AS capture_index
        FROM lists'''.format(record=record))
    step('secondary_entries', '''SELECT receipt_key,receipt_line,unnest(refs) AS entry
        FROM lists WHERE coalesce(array_length(caps),0)>0''')
    step('secondary', f'''SELECT receipt_key,receipt_line,{get('entry','body_key')} AS body_key,
        {get('entry','sha256')} AS sha,max({integer('entry','stored_bytes')}) AS stored_bytes,
        max({get('entry','stored_md5')}) AS stored_md5,
        max({get('entry','stored_suffix')}) AS stored_suffix,
        count(DISTINCT {integer('entry','stored_bytes')}) AS size_variants,
        count(DISTINCT {get('entry','stored_md5')}) AS md5_variants
        FROM secondary_entries GROUP BY receipt_key,receipt_line,
        {get('entry','body_key')},{get('entry','sha256')}''')
    step('enriched', f'''SELECT p.*,s.stored_bytes AS secondary_bytes,
        s.stored_md5 AS secondary_md5,s.stored_suffix AS secondary_suffix,
        {get('p.entry','sha256')} AS body_sha
        FROM primary_entries p LEFT JOIN secondary s
        ON p.receipt_key=s.receipt_key AND p.receipt_line=s.receipt_line
        AND {get('p.entry','body_key')}=s.body_key AND {get('p.entry','sha256')}=s.sha''')
    # List-valued records keep the receipt's grain. A body pointer selects its
    # source record; a line without bodies uses its first record for line facts.
    pointer_index = first(get('entry', 'pointer', 0,kind='int'),
        f'try_cast({get("entry","pointer",0)} AS BIGINT)',
        get('entry', 'pointer', 1,kind='int'),
        f'try_cast({get("entry","pointer",1)} AS BIGINT)', '0')
    step('records', f'''SELECT *,CASE WHEN left(ltrim(record_value),1)='['
        THEN array_element({get('record_value',kind='array')},cast({pointer_index} AS BIGINT)+1)
        ELSE record_value END AS record FROM enriched''')
    step('header_entries', f'''SELECT receipt_key,receipt_line,capture_index,
        unnest(coalesce({get('line','response_header_items',kind='array')},
                        {get('record','response_header_items',kind='array')},
                        {get(get('record','_ingest_header_items_json'),kind='array')},
                        {get('record','headers',kind='array')},
                        {get(get('record','_ingest_other_headers_json'),kind='array')})) AS item FROM records''')
    step('item_headers', '''SELECT receipt_key,receipt_line,capture_index,
        max(CASE WHEN lower(json_get_str(item,'name'))='content-disposition'
            THEN json_get_str(item,'value') END) AS item_disposition,
        max(CASE WHEN lower(json_get_str(item,'name'))='retry-after'
            THEN json_get_str(item,'value') END) AS item_retry
        FROM header_entries GROUP BY receipt_key,receipt_line,capture_index''')
    def both(*path, kind='str'):
        return first(get('line', *path, kind=kind), get('record', *path, kind=kind))
    def num(*path):
        return first(integer('line', *path), integer('record', *path))
    recovery = first(both('recovery_evidence', kind='json'),get('record','_ingest_recovery_json'))
    association = first(get('record','source_associations',0,kind='json'),get(get('record','_ingest_assoc_json'),0,kind='json'))
    root_headers = first(get('line','response_headers',kind='json'),
                         get('record','_ingest_headers_json'),get('record','response_headers',kind='json'))
    headers = first(root_headers,get('record','_ingest_other_headers_json'),
                    get('record', 'headers', kind='json'))
    step('facts', f'''SELECT r.*,h.item_disposition,h.item_retry,{recovery} AS recovery,
        {association} AS association,{headers} AS headers,
        {both('mode')} AS raw_mode,{both('outcome')} AS raw_outcome,
        {first(integer('line','http_status'),integer('line','status_code'),integer('record','http_status'),integer('record','status_code'))} AS line_status,
        {first(fetch_time('entry'),fetch_time('line'),fetch_time('record'))} AS fetched,
        {first(get('line','family'),get('record','family'),"regexp_replace(receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\\1')")} AS line_family,
        {first(get('entry','family'),get('line','family'),get('record','family'),"regexp_replace(receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\\1')")} AS entry_family,
        {first(get('line','run_id'),get('line','source_file'),get('record','source_file'))} AS source_run,
        {first(get('line','requested_url'),get('record','requested_url'),get('record','_url'),get('record','url'),get('line','url'),get('record','final_url'),get('record','resolved_url'),get('record','source_url'))} AS requested,
        {first(get('line','url'),get('record','url'),get('record','_url'),get('record','final_url'),get('record','resolved_url'),get('record','source_url'))} AS final_url
        FROM records r LEFT JOIN item_headers h USING(receipt_key,receipt_line,capture_index)''')
    modes = ','.join(literal(v) for v in sorted(LEGACY_MODES))
    outcomes = ','.join(literal(v) for v in sorted(LEGACY_OUTCOMES))
    # Ordinary old labels describe content/inspection, not transfer success.
    # Status and body presence decide those rows; explicit transfer failures keep
    # their distinct incomplete/retry meaning.
    transfer = {'retry_later','request_failed','size_limit','stored','unchanged','failed',
                'archive_throttled','exception','request_or_parse_error','resource_limit','timeout'}
    cases = ' '.join('WHEN '+literal(k)+' THEN '+literal(v if k in transfer else 'derive')
                     for k,v in LEGACY_OUTCOMES.items())
    step('mapped', f'''SELECT *,
        CASE WHEN raw_mode='retained_import' OR recovery IS NOT NULL
             OR {get('association','original_url')} IS NOT NULL THEN 'retained_import'
             ELSE 'fetch' END AS capture_mode,
        CASE raw_outcome {cases} ELSE 'derive' END AS mapped_outcome,
        (raw_mode IS NOT NULL AND raw_mode NOT IN ({modes})) AS unknown_mode,
        (raw_outcome IS NOT NULL AND raw_outcome NOT IN ({outcomes})) AS unknown_outcome,
        {first(integer('entry','attempt'), "CASE WHEN json_get_str(entry,'pointer',0)='prior_attempts' THEN coalesce(try_cast(json_as_text(entry,'pointer',1) AS BIGINT),0)+1 ELSE 0 END")} AS attempt,
        {first(integer('entry','bytes'),integer('entry','size'))} AS body_bytes,
        json_canonical({first(get('entry','pointer',kind='json'),get('entry','pointer_json'))}) AS pointer_json,
        {get('entry','body_key')} AS body_key
        FROM facts''')
    attempt_status = first(integer('entry','http_status'), integer('entry','status_code'),
        f"CASE WHEN attempt>0 THEN coalesce(json_get_int(json_get_json(json_get_json(line,'prior_attempts'),attempt-1),'http_status'),json_get_int(json_get_json(coalesce(json_get_str(record,'_ingest_prior_attempts_json'),json_get_json(record,'prior_attempts')),attempt-1),'http_status')) ELSE line_status END")
    final_complete = first(get('entry','complete',kind='bool'),
        "CASE WHEN attempt=0 THEN coalesce(json_get_bool(line,'complete'),json_get_bool(record,'complete')) END",
        "NOT (coalesce(body_bytes,0)=67108864 OR mapped_outcome IN ('size_limit','request_failed'))")
    explicit_complete = first(get('entry','complete',kind='bool'),
        "CASE WHEN attempt=0 THEN coalesce(json_get_bool(line,'complete'),json_get_bool(record,'complete')) END")
    top_level = "json_get_str(entry,'member_path') IS NULL AND position('archive_members' IN coalesce(pointer_json,''))=0"
    legacy_cutoff = f'''(bool_or(attempt=0 AND body_bytes=67108864 AND ({top_level})
        AND ({explicit_complete}) IS FALSE) OVER (PARTITION BY receipt_key,receipt_line))
        AND NOT coalesce(bool_or(attempt=0 AND ({top_level}) AND ({explicit_complete}) IS TRUE)
            OVER (PARTITION BY receipt_key,receipt_line),false)
        AND capture_mode='fetch' AND json_get_str(line,'mode') IS NULL
        AND (raw_outcome IS NULL OR raw_outcome IN ('saved','captured','complete','html','html_body','pdf','retained'))
        AND coalesce(json_get_str(line,'error_type'),json_get_str(record,'error_type'),
            json_get_json(line,'error'),json_get_json(record,'error'),json_get_str(record,'_ingest_error_json')) IS NULL'''
    source_sha = "arrow_cast(decode(json_get_str(line,'_ingest_record_sha'),'hex'), 'FixedSizeBinary(32)')"
    retry = first(get('headers','retry-after'), get('headers','Retry-After'), 'item_retry')
    columns = dict(
        receipt_key='receipt_key', receipt_line='cast(receipt_line AS INT)',
        capture_index='cast(capture_index AS INT)', run_id='source_run', mode='capture_mode',
        outcome=f"""CASE WHEN line_status IN (429,503) OR {retry} IS NOT NULL THEN 'retry_later'
            WHEN line_status=304 THEN 'unchanged'
            WHEN mapped_outcome<>'derive' THEN mapped_outcome
            WHEN {legacy_cutoff} THEN 'size_limit'
            WHEN body_sha IS NOT NULL AND (line_status BETWEEN 200 AND 299 OR line_status IS NULL)
            THEN 'stored' ELSE 'failed' END""",
        family='entry_family', requested_url='requested', url='final_url',
        record_sha=f"CASE WHEN line_family='congress/meetings' AND body_sha IS NULL THEN {source_sha} ELSE arrow_cast(NULL,'FixedSizeBinary(32)') END",
        http_status='cast(line_status AS INT)', attempt_status=f'cast({attempt_status} AS INT)',
        complete=final_complete,
        context_url=first(get('entry','context_url'), 'final_url'),
        member_path=first(get('entry','member_path'),
            "CASE WHEN position('archive_members' IN coalesce(pointer_json,''))>0 AND reference_kind='capture' THEN json_get_str(entry,'original_path') END"),
        expansion=first(get('entry','expansion'),
            "CASE WHEN coalesce(json_length(record,'archive_members'),json_get_int(record,'_ingest_archive_member_count'),json_get_int(line,'archive_member_count'),0)>0 AND position('archive_members' IN coalesce(pointer_json,''))=0 THEN 'expanded' END"),
        h_content_disposition=first(get('headers','content-disposition'), get('headers','Content-Disposition'),'item_disposition'),
        retry_after=f"CASE WHEN try_cast({retry} AS BIGINT) IS NOT NULL THEN to_timestamp_micros(cast(extract(epoch FROM fetched)*1000000 AS BIGINT)+try_cast({retry} AS BIGINT)*1000000) ELSE try_cast({retry} AS TIMESTAMP WITH TIME ZONE) END",
        retrieved_at='fetched', sha256="arrow_cast(decode(body_sha,'hex'),'FixedSizeBinary(32)')", bytes='body_bytes',
        media_type=get('entry','media_type'), fidelity=get('entry','fidelity'),
        sniffed_format=get('entry','sniffed_format'), sniff_version=get('entry','sniff_version'),
        intact=first(get('entry','intact',kind='bool'),
            "CASE WHEN fetched>=cast('2026-10-01' AS TIMESTAMP WITH TIME ZONE) AND raw_outcome IN ('saved','invalid_document') AND attempt=0 THEN raw_outcome='saved' END"),
        stored_suffix=first(get('entry','stored_suffix'), 'secondary_suffix', literal('.gz')),
        stored_md5="arrow_cast(decode(coalesce(json_get_str(entry,'stored_md5'),secondary_md5),'hex'),'FixedSizeBinary(16)')",
        stored_bytes=first(integer('entry','stored_bytes'), 'secondary_bytes'),
        recovery_category=get('recovery','acquisition','prior_access_category'),
        original_url="CASE WHEN capture_mode='retained_import' THEN coalesce(json_get_str(recovery,'original_url'),json_get_str(association,'original_url')) END",
        recovered_url="CASE WHEN capture_mode='retained_import' THEN coalesce(json_get_str(recovery,'acquisition','recovered_url'),final_url) END",
        match_basis="CASE WHEN capture_mode='retained_import' THEN coalesce(json_get_str(recovery,'match_basis'),json_get_str(association,'basis')) END",
        evidence_sha256="arrow_cast(decode(json_get_str(recovery,'acquisition','evidence_sha256'),'hex'),'FixedSizeBinary(32)')",
        imported_at="CASE WHEN capture_mode='retained_import' THEN coalesce(try_cast(json_get_str(recovery,'imported_at') AS TIMESTAMP WITH TIME ZONE),try_cast(array_element(regexp_match(receipt_key,'/(\\d{4}-\\d{2}-\\d{2})/'),1) AS TIMESTAMP WITH TIME ZONE)) END",
        writer_job=get('line','writer','job'), writer_commit=get('line','writer','commit'))
    # C1's source positions are required, while the older Parquet counter's
    # schema declared them optional. Bind the same required lake key schema for
    # both inputs using Arrow's maintained nested-type cast, without changing
    # values or substituting a value for a missing locator.
    locator = '''arrow_cast(named_struct('key',receipt_key,'line',cast(receipt_line AS INT),
        'index',cast(capture_index AS INT)),
        'Struct("key": Utf8, "line": Int32, "index": Int32)')'''
    for name,member in [('receipt_key','key'),('receipt_line','line'),('capture_index','index')]:
        columns[name] = f"get_field({locator},'{member}')"
    for name in ('retrieved_at', 'retry_after', 'imported_at'):
        columns[name] = f"arrow_cast({columns[name]}, 'Timestamp(Microsecond, Some(\"UTC\"))')"
    step('capture_facts', 'SELECT '+','.join(f'{columns[k]} AS "{k}"' for k in COLUMNS)
         + ',reference_kind,pointer_json,body_key,unknown_mode,unknown_outcome FROM mapped')
    return steps


def stage_captures(files, *, engine, work, existing=None, counter=None):
    """Create immutable local staging, refusing unknown vocabularies or lost bodies.

    Table appends are a separate explicit engine operation. A failed native read
    leaves no accepted receipt-key list, so that receipt remains work on retry.
    """
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    mapping_digest = sha256(Path(__file__).read_bytes()+(Path(__file__).parent/'receipt_metadata.py').read_bytes()).hexdigest()
    keys = [f['key'] for f in files]
    if len(keys) != len(set(keys)) or any(not k.startswith('receipts/') for k in keys):
        raise ValueError('Receipt inventory needs unique raw receipt keys')
    if counter is None:
        from congress_api.lake.receipt_metadata import compact
        counter=compact(files=files,engine=engine,work=work/'receipt-metadata')
    inputs = [dict(name='receipts',kind='parquet',path=str(Path(counter).resolve()))]
    inputs.append(json_input(work,'selected_receipts',[dict(receipt_key=k) for k in keys],
                             receipt_key='Utf8'))
    if existing is not None:
        inputs.append(dict(name='existing_captures', kind='parquet', path=str(Path(existing).resolve())))
    checks = [dict(name='positions',sql='''SELECT receipt_key,receipt_line,'invalid source locator' AS reason
              FROM lines WHERE receipt_key IS NULL OR receipt_line IS NULL OR receipt_line<1 LIMIT 1'''),
        dict(name='invalid', sql='''SELECT receipt_key,receipt_line,
        CASE WHEN unknown_mode THEN 'unknown mode' ELSE 'unknown outcome' END AS reason
        FROM capture_facts WHERE unknown_mode OR unknown_outcome LIMIT 1'''),
        dict(name='secondary', sql='''SELECT s.receipt_key,s.receipt_line,'secondary body not represented' AS reason
        FROM secondary s LEFT ANTI JOIN primary_entries p
        ON s.receipt_key=p.receipt_key AND s.receipt_line=p.receipt_line
        AND s.body_key=json_get_str(p.entry,'body_key') AND s.sha=json_get_str(p.entry,'sha256')
        WHERE s.sha IS NOT NULL UNION ALL
        SELECT receipt_key,receipt_line,'secondary storage conflict' AS reason FROM secondary
        WHERE size_variants>1 OR md5_variants>1 LIMIT 1'''),
        dict(name='list_facts',sql='''SELECT receipt_key,receipt_line,'list record conflicting facts' AS reason
            FROM (SELECT receipt_key,receipt_line,unnest(json_get_array(record_value)) AS item
                  FROM primary_entries WHERE reference_kind='line' AND left(ltrim(record_value),1)='[')
            GROUP BY receipt_key,receipt_line HAVING
                count(DISTINCT coalesce(json_get_str(item,'url'),json_get_str(item,'requested_url')))>1
                OR count(DISTINCT coalesce(json_get_int(item,'http_status'),json_get_int(item,'status_code')))>1
                OR count(DISTINCT coalesce(json_get_str(item,'retrieved_at'),json_get_str(item,'captured_at'),json_get_str(item,'observed_at')))>1
            LIMIT 1''')]
    results = run_job(work, engine, inputs=inputs,
        steps=mapping_steps(existing=existing is not None),
        outputs=[parquet_output(work, 'capture-evidence', 'SELECT * FROM capture_facts', PK)],
        queries=checks)
    for name in ('positions','invalid', 'secondary', 'list_facts'):
        if results[name]:
            row = results[name][0]
            raise ValueError(f"{row['reason']}: {row['receipt_key']}:{row['receipt_line']}")
    final = work/'export'
    final.mkdir()
    accepted = run_job(final, engine,
        inputs=[dict(name='facts', kind='parquet', path=str(work/'capture-evidence.parquet'))],
        steps=[], outputs=[parquet_output(work, 'captures',
            'SELECT '+','.join('"'+c+'"' for c in COLUMNS)+' FROM facts', PK)],
        queries=[dict(name='counts', sql='SELECT count(*) AS rows,count(DISTINCT receipt_key) AS receipts FROM facts'),
                 dict(name='receipts',sql='SELECT DISTINCT receipt_key FROM facts ORDER BY receipt_key')])
    if mapping_digest != sha256(Path(__file__).read_bytes()+(Path(__file__).parent/'receipt_metadata.py').read_bytes()).hexdigest():
        raise ValueError('Receipt mapping changed while staging; accepted inventory was not written')
    (work/'ingested-receipts.json').write_text(json.dumps(dict(version=1,
        mapping_digest=mapping_digest, receipt_keys=[r['receipt_key'] for r in accepted['receipts']]), indent=2)+'\n')
    return work
