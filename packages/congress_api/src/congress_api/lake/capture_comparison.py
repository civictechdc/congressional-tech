"""Native old-index oracle comparison; never use derived rows as ingest input."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.body_store import validate_key
from congress_api.lake.receipt_metadata import record_pointer_index,COMPARISON_WITNESSES
from congress_api.retention.provenance import json_input,parquet_output,run_job


RULES = {
    'secondary_duplicates': 'Remove only a file/retained-file row duplicating a capture body on the same line and context whose non-null stored size and location agree with the target; preserve contradictions and other occurrences.',
    'http_status': 'A missing old status may be restored. An old per-entry status may change to the final line/item status only when both explicit receipt facts independently match their respective sides; other changes and losses remain owner gates.',
    'retrieved_at': 'Compare equivalent UTC instants. Only a missing old time restored to a valid new time is accepted; invalid, lost or conflicting times remain owner gates.',
    'family_run': 'Compare old family and source_file directly with family and run_id. Missing values may be restored. Only the five measured family pairs are accepted with their exact receipt-family fallback or explicit record-family witness. Never strip ci/ or generalize the pairs.',
    'member_path': 'Compare original_path only for a capture with the exact archive_members pointer component. Retained file local paths do not establish member names.',
    'body_location': 'Compare each recorded old physical body_key with the key derived from the new body SHA and stored_suffix, defaulting the legacy suffix to .gz. Noncanonical or conflicting locations are not normalized away.',
    'storage': 'Missing stored_bytes may be enriched. An old digest_verified resolver size may become null only on a body reference whose creating entry explicitly has no stored-size fact. Every other non-null size must survive. Stored SHA-256 is distinct from MD5 and is not a target column.',
    'bodiless_pointer': 'Only old metadata plus null body SHA plus pointer [] maps to the new no-body null pointer. Saved-record fidelity may become null only for that shape with a retained-object receipt witness. Missing context may be restored only from the mapped final URL, with its receipt witness.',
    'source_list_items': 'Only a new bodiless line row with a true source-list proof, list length greater than one, a valid distinct item ordinal appearing once after independently decoding primary pointer coverage, and an old row on the same receipt line is an expected restoration. Preserve and gate every unproved new-only row.',
    'old_only': 'Every remaining old-only row is an owner gate; preserve all original columns. No automatic dismissal or invented capture row.',
    'occurrences': 'Match repeated receipt/body/pointer facts one-to-one; keep multiplicity after qualified secondary normalization.',
    'coverage': 'The oracle does not independently establish new mode, completeness, outcome priorities, endpoint/header/sniff/writer facts or recovery fields. Report those gaps; qualify them with receipt and rebuild tests.',
}
COVERAGE = dict(
    matched_by=['receipt_key','receipt_line','sha256','pointer_json','occurrence'],
    compared=['bytes','stored_bytes','media_type','fidelity','context_url','http_status',
              'retrieved_at','family','run_id','member_path','body_key'],
    not_compared=['capture_index','mode','complete','outcome','requested_url','url',
        'h_content_disposition','stored_md5','sniffed_format','sniff_version','intact',
        'expansion','writer_job','writer_commit','recovery_category','original_url',
        'recovered_url','match_basis','evidence_sha256','imported_at'],
    unqualified_old_fields=['resolution','capture_date','source_line','stored_sha256',
                            'original_path outside archive captures'])


def compare_old(evidence, old_index, *, engine, work, receipt_keys=None):
    """Compare one retained evidence file or an explicit set of whole batches.

    The native union precedes every occurrence rank and is materialized once.
    An explicit new-receipt scope never narrows the old oracle population.
    Python checks only file schemas and bounded receipt metadata, not rows.
    """
    paths=evidence if isinstance(evidence,list) else [evidence]
    if not paths or any(not isinstance(path,(str,Path)) for path in paths):
        raise ValueError('Comparison requires a nonempty evidence path list')
    paths=[Path(path).resolve() for path in paths]
    if len(paths)!=len(set(paths)):
        raise ValueError('Comparison evidence paths must be unique')
    schemas=[pq.read_schema(path) for path in paths]
    new_schema=schemas[0]
    if any(not schema.equals(new_schema,check_metadata=True) for schema in schemas[1:]):
        raise ValueError('Comparison evidence schemas must exactly match')
    if receipt_keys is not None:
        if (not isinstance(receipt_keys,list) or not receipt_keys
                or any(not isinstance(key,str) or not key.startswith('receipts/') for key in receipt_keys)
                or len(receipt_keys)!=len(set(receipt_keys))):
            raise ValueError('Comparison receipt scope requires unique receipt keys')
        for key in receipt_keys:validate_key(key)
        receipt_keys=sorted(receipt_keys)
    old_schema=pq.read_schema(old_index)
    common_names=['receipt_key','receipt_line','body_sha','pointer','reference_kind','qualified_bodiless',
        'family','run_id','member_path','body_key','original_path','resolution','outcome',
        'context_url','bytes','stored_bytes','media_type','fidelity','http_status','retrieved_at']
    new_names=common_names+['capture_index','record_is_list','source_record_count','source_record_index',*COMPARISON_WITNESSES,'occurrence']
    integers={'receipt_line','bytes','stored_bytes','http_status','old_row','capture_index',
              'source_record_count','source_record_index'}
    booleans={'qualified_bodiless','record_is_list'}
    integers.update(name for name,kind in COMPARISON_WITNESSES.items() if kind=='Int64')
    booleans.update(name for name,kind in COMPARISON_WITNESSES.items() if kind=='Boolean')
    strings=set(common_names)-integers-booleans
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    inputs=[dict(name='old_input',kind='parquet',path=str(Path(old_index).resolve()))]
    inputs.extend(dict(name='new_part_'+str(index),kind='parquet',path=str(path))
                  for index,path in enumerate(paths))
    steps=[dict(name='new_input',sql=' UNION ALL '.join(
        'SELECT * FROM new_part_'+str(index) for index in range(len(paths))),materialize=True)]
    new_input='new_input'
    if receipt_keys is not None:
        inputs.append(json_input(work,'comparison_receipts',
            [dict(receipt_key=key) for key in receipt_keys],receipt_key='Utf8'))
        steps.append(dict(name='new_selected',sql='''SELECT n.* FROM comparison_receipts s
            RIGHT SEMI JOIN new_input n ON n.receipt_key=s.receipt_key'''))
        new_input='new_selected'
    excluded='''SELECT n.receipt_key,count(*) AS rows FROM comparison_receipts s
        RIGHT ANTI JOIN new_input n ON n.receipt_key=s.receipt_key
        GROUP BY n.receipt_key ORDER BY n.receipt_key''' if receipt_keys is not None else '''
        SELECT receipt_key,cast(0 AS BIGINT) AS rows FROM new_input WHERE false'''
    steps.extend([
        dict(name='input_totals',sql='SELECT count(*) AS rows FROM new_input',materialize=True),
        dict(name='excluded_receipts',sql=excluded,materialize=True)])
    def value(schema, name, kind='VARCHAR'):
        return '"'+name+'"' if name in schema.names else f'cast(NULL AS {kind})'
    def projection(schema, old=False):
        sha = value(schema,'sha256')
        sha = f'lower({sha})' if old else f"encode({sha},'hex')"
        raw_pointer = f'json_canonical({value(schema,"pointer_json")})'
        kind = value(schema,'reference_kind')
        bodiless = f"coalesce({kind}='metadata' AND {sha} IS NULL AND {raw_pointer}='[]',false)" if old else 'false'
        pointer = f'CASE WHEN {bodiless} THEN cast(NULL AS VARCHAR) ELSE {raw_pointer} END' if old else raw_pointer
        cols = ['receipt_key','receipt_line',f'{sha} AS body_sha',f'{pointer} AS pointer',
                f'{kind} AS reference_kind',f'{bodiless} AS qualified_bodiless',
                value(schema,'family')+' AS family',
                value(schema,'source_file' if old else 'run_id')+' AS run_id']
        if old:
            member = (f"CASE WHEN {kind}='capture' AND coalesce(array_has(json_get_array("
                      f"{raw_pointer}),'\"archive_members\"'),false) THEN {value(schema,'original_path')} END")
            location = value(schema,'body_key')
        else:
            member = value(schema,'member_path')
            location = (f"CASE WHEN {sha} IS NOT NULL THEN concat('bodies/sha256/',substr({sha},1,2),'/',"
                        f"{sha},coalesce({value(schema,'stored_suffix')},'.gz')) END")
        cols += [member+' AS member_path',location+' AS body_key',
                 value(schema,'original_path')+' AS original_path',
                 value(schema,'resolution')+' AS resolution',value(schema,'outcome')+' AS outcome']
        for name in ('context_url','bytes','stored_bytes','media_type','fidelity','http_status','retrieved_at'):
            kind = 'BIGINT' if name in {'bytes','stored_bytes','http_status'} else 'VARCHAR'
            cols.append(value(schema,name,kind)+' AS "'+name+'"')
        if old:cols.append('old_row')
        else:
            cols.append('capture_index')
            witness_types={'Boolean':('BOOLEAN',pa.types.is_boolean),'Int64':('BIGINT',pa.types.is_integer),
                           'Utf8':('VARCHAR',lambda kind:pa.types.is_string(kind) or pa.types.is_large_string(kind))}
            for name,kind,valid in [('record_is_list','BOOLEAN',pa.types.is_boolean),
                    ('source_record_count','BIGINT',pa.types.is_integer),
                    ('source_record_index','BIGINT',pa.types.is_integer),
                    *((name,*witness_types[kind]) for name,kind in COMPARISON_WITNESSES.items())]:
                expression=(value(schema,name,kind) if name in schema.names and valid(schema.field(name).type)
                            else f'cast(NULL AS {kind})')
                cols.append(expression+' AS '+name)
        names=common_names+(['old_row'] if old else new_names[len(common_names):-1])
        plain=[f'arrow_cast(cast("{name}" AS VARCHAR),\'Utf8\') AS "{name}"' if name in strings
               else '"'+name+'"' for name in names]
        return 'SELECT '+','.join(plain)+' FROM (SELECT '+','.join(cols)+' FROM '+('old_numbered' if old else new_input)+')'
    old_order = ','.join('"'+f+'"' for f in old_schema.names)
    # Keep the small count/scope results instead of the consumed union. Release
    # its dependent view too, so no surviving plan holds the original buffers.
    source_names=['new_input',*('new_part_'+str(i) for i in range(len(paths)))]
    if receipt_keys is not None:source_names+=['new_selected','comparison_receipts']
    steps += [dict(name='new_values',sql=projection(new_schema),release_after=source_names),
        dict(name='new_totals',sql='SELECT count(*) AS rows FROM new_values',materialize=True),
        dict(name='old_plain',sql='SELECT '+','.join(
            f'arrow_cast("{f.name}",\'Utf8\') AS "{f.name}"' if pa.types.is_string(f.type) or pa.types.is_large_string(f.type)
            else '"'+f.name+'"' for f in old_schema)+' FROM old_input'),
        dict(name='old_numbered',sql=f'SELECT *,row_number() OVER (ORDER BY {old_order}) AS old_row FROM old_plain',
             release_after=['old_input','old_plain']),
        dict(name='old_totals',sql='SELECT count(*) AS rows FROM old_numbered',materialize=True),
        dict(name='old_facts',sql=projection(old_schema,True)),
        # Filtering only matching views preserves the original '=' treatment of
        # NULL locators and SHA values. Unmatched source rows remain in the oracle.
        dict(name='old_file_keys',sql='''SELECT old_row,receipt_key,receipt_line,body_sha,context_url,stored_bytes,body_key
            FROM old_facts WHERE reference_kind IN ('file','retained-file')
            AND receipt_key IS NOT NULL AND receipt_line IS NOT NULL AND body_sha IS NOT NULL''',materialize=True),
        dict(name='old_secondary_keys',sql='''SELECT receipt_key,receipt_line,body_sha,context_url FROM old_facts
            WHERE reference_kind IN ('capture','embedded') AND receipt_key IS NOT NULL
            AND receipt_line IS NOT NULL AND body_sha IS NOT NULL'''),
        dict(name='new_secondary_keys',sql='''SELECT receipt_key,receipt_line,body_sha,context_url,stored_bytes,body_key
            FROM new_values WHERE receipt_key IS NOT NULL
            AND receipt_line IS NOT NULL AND body_sha IS NOT NULL'''),
        dict(name='secondary_duplicates',sql='''SELECT o.old_row FROM old_file_keys o
            LEFT SEMI JOIN old_secondary_keys c ON
                (c.receipt_key IS NOT DISTINCT FROM o.receipt_key)
                AND (c.receipt_line IS NOT DISTINCT FROM o.receipt_line)
                AND (c.body_sha IS NOT DISTINCT FROM o.body_sha)
                AND (c.context_url IS NOT DISTINCT FROM o.context_url)
            LEFT SEMI JOIN new_secondary_keys n ON
                (n.receipt_key IS NOT DISTINCT FROM o.receipt_key)
                AND (n.receipt_line IS NOT DISTINCT FROM o.receipt_line)
                AND (n.body_sha IS NOT DISTINCT FROM o.body_sha)
                AND (n.context_url IS NOT DISTINCT FROM o.context_url)
                AND (o.stored_bytes IS NULL OR o.stored_bytes IS NOT DISTINCT FROM n.stored_bytes)
                AND (o.body_key IS NULL OR o.body_key IS NOT DISTINCT FROM n.body_key)''',
             release_after=['old_file_keys','old_secondary_keys','new_secondary_keys']),
        # Both old_row columns come from row_number(), so neither is NULL.
        # A normal anti join permits the key-only side to be the build; NOT IN
        # forces a wide, null-aware build and one oversized unmatched batch.
        dict(name='old_values',sql='''SELECT o.* FROM secondary_duplicates d RIGHT ANTI JOIN old_facts o
            ON o.old_row=d.old_row''')]
    occurrence_keys='receipt_key,receipt_line,body_sha,pointer'
    occurrence_order='context_url,bytes,media_type,fidelity,http_status,try_cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),stored_bytes,family,run_id,member_path,body_key'
    # The old list metadata represents item zero. Restored child facts must
    # follow that item even when their URLs sort before its URL.
    source_item_order="""CASE WHEN reference_kind='line' AND body_sha IS NULL AND pointer IS NULL
        AND record_is_list IS TRUE AND source_record_count>1
        AND source_record_index>=0 AND source_record_index<source_record_count
        THEN source_record_index END"""
    checked_index="CASE WHEN record_is_list IS TRUE AND reference_kind IN ('capture','embedded','file','retained-file') THEN "+record_pointer_index('pointer')+" ELSE source_record_index END"
    steps.extend([
        dict(name='old_normalized',sql=f'''SELECT *,row_number() OVER (
            PARTITION BY {occurrence_keys} ORDER BY {occurrence_order},old_row) AS occurrence
            FROM old_values'''),
        dict(name='source_ordinals',sql=f'''SELECT receipt_key AS proof_receipt_key,
            receipt_line AS proof_receipt_line,{checked_index} AS proof_record_index,
            count(*) AS source_ordinal_occurrences FROM new_values
            GROUP BY receipt_key,receipt_line,{checked_index}''',materialize=True),
        dict(name='new_facts',sql=f'''SELECT *,row_number() OVER (
            PARTITION BY {occurrence_keys} ORDER BY {source_item_order},{occurrence_order},capture_index) AS occurrence
            FROM new_values''')])
    # The retained fact Parquets are not lifecycle ReleasePins, so the native
    # changes endpoint cannot address them. Use its signed-grouping shape in
    # this job, with application-only restoration classification afterward.
    # Invalid locators stay separate across sides, preserving unmatched NULLs.
    keys=occurrence_keys+',occurrence,invalid_side'
    payload=[n for n in common_names if n not in occurrence_keys.split(',')]+[
        'old_row','capture_index','record_is_list','source_record_count','source_record_index',*COMPARISON_WITNESSES]
    def tagged(side,table):
        available=set(common_names+(['old_row'] if side=='old' else new_names[len(common_names):]))
        columns=[]
        for name in payload:
            kind='BIGINT' if name in integers else 'BOOLEAN' if name in booleans else 'VARCHAR'
            expression=f'cast("{name}" AS {kind})' if name in available else f'cast(NULL AS {kind})'
            if name not in integers|booleans:expression=f'arrow_cast({expression},\'Utf8\')'
            columns.append(expression+' AS "'+name+'"')
        return f'''SELECT {occurrence_keys},occurrence,
            CASE WHEN receipt_key IS NULL OR receipt_line IS NULL THEN '{side}' END AS invalid_side,
            '{side}' AS side,'''+','.join(columns)+' FROM '+table
    def record(side,names):
        fields=[]
        for name in names:
            if name in occurrence_keys.split(',') or name=='occurrence':expression=name
            else:
                aggregate='bool_or' if name in booleans else 'max'
                expression=f'{aggregate}(CASE WHEN side=\'{side}\' THEN "{name}" END)'
            fields.extend(["'"+name+"'",expression])
        return 'named_struct('+','.join(fields)+')'
    steps.extend([
        dict(name='tagged_facts',sql=tagged('old','old_normalized')+' UNION ALL '+tagged('new','new_facts')),
        dict(name='paired',sql=f'''SELECT {keys},
            sum(CASE WHEN side='old' THEN 1 ELSE 0 END) AS old_n,
            sum(CASE WHEN side='new' THEN 1 ELSE 0 END) AS new_n,
            {record('old',common_names+['old_row','occurrence'])} AS o,
            {record('new',new_names)} AS n FROM tagged_facts GROUP BY {keys}''',materialize=True,
            release_after=['tagged_facts','old_normalized','new_facts','old_values','old_facts','new_values']),
        dict(name='paired_totals',sql='''SELECT coalesce(sum(CASE WHEN old_n>0 AND new_n>0 THEN 1 ELSE 0 END),0)
            AS matched FROM paired''',materialize=True)])
    stable = ' OR '.join(f'(o."{k}" IS DISTINCT FROM n."{k}")'
                         for k in ('bytes','media_type'))
    def proven(sql):return 'coalesce(('+sql+'),false)'
    restored_fidelity=proven("o.qualified_bodiless AND n.body_sha IS NULL AND n.reference_kind='line' AND o.fidelity='saved-record' AND n.fidelity IS NULL AND n.source_retained_record IS TRUE")
    restored_context=proven('o.context_url IS NULL AND n.context_url IS NOT NULL AND n.source_context_from_final IS TRUE')
    restored_status=proven('(o.http_status IS DISTINCT FROM n.http_status) AND o.http_status BETWEEN 100 AND 599 AND n.http_status BETWEEN 100 AND 599 AND o.http_status=n.source_entry_status AND n.http_status=n.source_final_status')
    restored_storage=proven("o.stored_bytes IS NOT NULL AND n.stored_bytes IS NULL AND o.resolution='digest_verified' AND n.body_sha IS NOT NULL AND n.reference_kind IN ('capture','embedded','file','retained-file') AND n.source_creating_size_absent IS TRUE")
    receipt_family="regexp_replace(n.receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\\1')"
    family_pairs=[('govinfo/mods','govinfo/transcript-html'),('govinfo/transcript-html','govinfo/mods'),
                  ('house/witness-xml','house/meeting-xml'),('senate/players','senate/captions')]
    pairs=' OR '.join("(o.family='"+old+"' AND n.family='"+new+"')" for old,new in family_pairs)
    restored_family=proven("(n.source_family_basis='receipt' AND n.family="+receipt_family+' AND ('+pairs+")) OR (o.family='documents' AND n.family='committee-reports' AND n.source_family_basis='record' AND "+receipt_family+"='documents')")
    old_time='try_cast(o.retrieved_at AS TIMESTAMP WITH TIME ZONE)'
    new_time='try_cast(n.retrieved_at AS TIMESTAMP WITH TIME ZONE)'
    invalid_old=f'(o.retrieved_at IS NOT NULL AND {old_time} IS NULL)'
    invalid_new=f'(n.retrieved_at IS NOT NULL AND {new_time} IS NULL)'
    restored_time=f'(o.retrieved_at IS NULL AND {new_time} IS NOT NULL)'
    changed_time=f'({old_time} IS DISTINCT FROM {new_time})'
    unexplained_time=f'({invalid_old} OR {invalid_new} OR ({changed_time} AND NOT {restored_time}))'
    time_reason=f'''CASE WHEN {invalid_old} THEN 'invalid_old_timestamp'
        WHEN {invalid_new} THEN 'invalid_new_timestamp'
        WHEN NOT {changed_time} THEN 'unchanged'
        WHEN {restored_time} THEN 'missing_time_restored'
        WHEN n.retrieved_at IS NULL THEN 'timestamp_lost'
        ELSE 'timestamp_changed' END'''
    unexpected = f'''({stable}) OR ((o.fidelity IS DISTINCT FROM n.fidelity) AND NOT {restored_fidelity})
        OR ((o.context_url IS DISTINCT FROM n.context_url) AND NOT {restored_context})
        OR (o.family IS NOT NULL AND (o.family IS DISTINCT FROM n.family) AND NOT {restored_family})
        OR (o.run_id IS NOT NULL AND (o.run_id IS DISTINCT FROM n.run_id))
        OR (o.member_path IS NOT NULL AND (o.member_path IS DISTINCT FROM n.member_path))
        OR (o.body_key IS NOT NULL AND (o.body_key IS DISTINCT FROM n.body_key))
        OR (o.stored_bytes IS NOT NULL AND (o.stored_bytes IS DISTINCT FROM n.stored_bytes) AND NOT {restored_storage})
        OR (o.http_status IS NOT NULL AND (o.http_status IS DISTINCT FROM n.http_status) AND NOT {restored_status})
        OR {unexplained_time}'''
    expected = f'''(o.http_status IS NULL AND n.http_status IS NOT NULL)
        OR {restored_time}
        OR (o.stored_bytes IS NULL AND n.stored_bytes IS NOT NULL)
        OR {restored_fidelity} OR {restored_context} OR {restored_status} OR {restored_storage} OR {restored_family}
        OR (o.family IS NULL AND n.family IS NOT NULL)
        OR (o.run_id IS NULL AND n.run_id IS NOT NULL)'''
    fact_values=[]
    for name in ('reference_kind','context_url','bytes','stored_bytes','media_type','fidelity','http_status',
                 'family','run_id','member_path','body_key','original_path','resolution','outcome'):
        kind='BIGINT' if name in {'bytes','stored_bytes','http_status'} else 'VARCHAR'
        fact_values.extend(f'cast({side}."{name}" AS {kind}) AS "{label}_{name}"'
                           for side,label in [('o','old'),('n','new')])
    fact_values=','.join(fact_values)
    steps += [dict(name='old_only',sql='SELECT o.old_row AS old_row FROM paired WHERE old_n>0 AND new_n=0'),
        dict(name='old_source_lines',sql='SELECT DISTINCT receipt_key AS old_source_key,receipt_line AS old_source_line FROM old_numbered',materialize=True),
        # Build the small unmatched-key side; preserve every original column
        # before releasing the full numbered old population.
        dict(name='old_only_records',sql='''SELECT o.* FROM old_only m JOIN old_numbered o
            ON o.old_row=m.old_row''',materialize=True,release_after=['old_numbered','old_only']),
        dict(name='matched_all',sql=f'''SELECT o.old_row AS old_row,n.receipt_key AS receipt_key,
        n.receipt_line AS receipt_line,n.capture_index AS capture_index,
        n.body_sha AS body_sha,n.pointer AS pointer,{fact_values},
        cast(o.retrieved_at AS VARCHAR) AS old_retrieved_at,
        cast(n.retrieved_at AS VARCHAR) AS new_retrieved_at,
        {time_reason} AS retrieved_at_reason,
        ({unexpected}) AS unexplained,({expected}) AS expected_change
        FROM paired WHERE old_n>0 AND new_n>0'''),
        dict(name='matched',sql='SELECT * FROM matched_all WHERE unexplained OR expected_change',
             release_after=['matched_all']),
        dict(name='new_only',sql='SELECT '+','.join('n."'+name+'" AS "'+name+'"' for name in new_names)+
             ' FROM paired WHERE new_n>0 AND old_n=0',release_after=['paired'])]
    # Source proof is carried only by the receipt-derived private evidence.
    # A key or URL resemblance alone cannot establish a collapsed source item.
    steps.extend([
        dict(name='new_only_proof',sql='''SELECT n.*,coalesce(
            n.reference_kind='line' AND n.body_sha IS NULL AND n.pointer IS NULL
            AND n.record_is_list IS TRUE AND n.source_record_count>1
            AND n.source_record_index>=0 AND n.source_record_index<n.source_record_count
            AND q.source_ordinal_occurrences=1 AND o.old_source_key IS NOT NULL,false)
            AS expected_source_list_item FROM old_source_lines o RIGHT JOIN (
            source_ordinals q RIGHT JOIN new_only n
            ON n.receipt_key=q.proof_receipt_key AND n.receipt_line=q.proof_receipt_line
            AND n.source_record_index=q.proof_record_index)
            ON n.receipt_key=o.old_source_key AND n.receipt_line=o.old_source_line''',materialize=True,
             release_after=['new_only','source_ordinals','old_source_lines']),
        dict(name='new_only_classified',sql="""SELECT *,CASE WHEN expected_source_list_item
            THEN 'source_list_item_restored' ELSE 'unexplained_new_row' END AS reason
            FROM new_only_proof""",materialize=True,release_after=['new_only_proof'])])
    # Shared native sorts and joins execute once for all exports and counts.
    for step in steps:
        if step['name'] in {'old_numbered','old_facts','new_values','secondary_duplicates',
                            'matched','old_only','new_only'}:
            step['materialize']=True
    # Retain one wide input per side; plain projections stay as views.
    # Single-use views consume their producer once.
    # Number and narrow the old oracle before retaining the new-side payload.
    first_names={'old_plain','old_numbered','old_totals','old_facts'}
    steps=[step for step in steps if step['name'] in first_names]+[
        step for step in steps if step['name'] not in first_names]
    for step in steps:
        if step['name'] in {'old_facts','new_values','old_file_keys','old_only','new_only'}:
            step['materialize']=False
    outputs = [parquet_output(work,'old-only',
        'SELECT * FROM old_only_records',['old_row']),
        parquet_output(work,'new-only','SELECT * FROM new_only_classified',
                       ['receipt_key','receipt_line','capture_index']),
        parquet_output(work,'expected-new-only','SELECT * FROM new_only_classified WHERE expected_source_list_item',
                       ['receipt_key','receipt_line','capture_index']),
        parquet_output(work,'unexplained-new-only','SELECT * FROM new_only_classified WHERE NOT expected_source_list_item',
                       ['receipt_key','receipt_line','capture_index']),
        parquet_output(work,'changed-fields',
            'SELECT * FROM matched WHERE unexplained OR expected_change',
            ['old_row','receipt_key','receipt_line','capture_index'])]
    query = '''SELECT (SELECT rows FROM old_totals) AS old_rows,
        (SELECT rows FROM new_totals) AS new_rows,
        (SELECT count(*) FROM secondary_duplicates) AS secondary_duplicates,
        (SELECT count(*) FROM old_only_records) AS old_only,
        (SELECT count(*) FROM new_only_classified) AS new_only,
        (SELECT count(*) FROM new_only_classified WHERE expected_source_list_item) AS expected_new_only,
        (SELECT count(*) FROM new_only_classified WHERE NOT expected_source_list_item) AS unexplained_new_only,
        (SELECT count(*) FROM matched WHERE unexplained) AS unexplained,
        (SELECT count(*) FROM matched WHERE expected_change AND NOT unexplained) AS expected_changes,
        (SELECT matched FROM paired_totals) AS matched'''
    native=run_job(work,engine,inputs=inputs,steps=steps,outputs=outputs,queries=[
        dict(name='counts',sql=query),
        dict(name='input_new_rows',sql='SELECT rows FROM input_totals'),
        dict(name='excluded_new_receipts',sql='SELECT * FROM excluded_receipts ORDER BY receipt_key')])
    result=native['counts'][0]
    result['owner_gate'] = bool(result['old_only'] or result['unexplained_new_only'] or result['unexplained'])
    result['rules'] = RULES
    result['coverage'] = dict(COVERAGE,available_old_fields=old_schema.names)
    result['scope']=dict(receipt_keys=receipt_keys,input_new_rows=native['input_new_rows'][0]['rows'],
        excluded_new_receipts=native['excluded_new_receipts'])
    (work/'comparison.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result
