"""Native old-index oracle comparison; never use derived rows as ingest input."""
import json
from pathlib import Path

import pyarrow.parquet as pq

from congress_api.retention.provenance import parquet_output, run_job


RULES = {
    'secondary_duplicates': 'Remove only a file/retained-file row duplicating a capture body on the same line and context whose non-null stored size and location agree with the target; preserve contradictions and other occurrences.',
    'http_status': 'A missing old status may be restored. Every changed or lost non-null status remains an owner gate, including possible old per-attempt/provider facts.',
    'retrieved_at': 'Compare equivalent UTC instants. Only a missing old time restored to a valid new time is accepted; invalid, lost or conflicting times remain owner gates.',
    'family_run': 'Compare old family and source_file directly with family and run_id. Missing values may be restored; never strip ci/ or invent a family equivalence.',
    'member_path': 'Compare original_path only for a capture with the exact archive_members pointer component. Retained file local paths do not establish member names.',
    'body_location': 'Compare each recorded old physical body_key with the key derived from the new body SHA and stored_suffix, defaulting the legacy suffix to .gz. Noncanonical or conflicting locations are not normalized away.',
    'storage': 'Missing stored_bytes may be enriched. Non-null sizes must survive. Stored SHA-256 is distinct from MD5 and is not a target column.',
    'bodiless_pointer': 'Only old metadata plus null body SHA plus pointer [] maps to the new no-body null pointer. Missing context restoration is qualified by that same source shape.',
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


def compare_old(evidence, old_index, *, engine, work):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    old_schema, new_schema = pq.read_schema(old_index), pq.read_schema(evidence)
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
        if not old:
            cols.append('capture_index')
        return 'SELECT '+','.join(cols)+' FROM '+('old_input' if old else 'new_input')
    old_order = ','.join('"'+f+'"' for f in old_schema.names)
    steps = [dict(name='old_numbered',sql=f'SELECT *,row_number() OVER (ORDER BY {old_order}) AS old_row FROM old_input'),
        dict(name='old_facts',sql=projection(old_schema,True).replace('FROM old_input',',old_row FROM old_numbered')),
        dict(name='new_values',sql=projection(new_schema)),
        dict(name='secondary_duplicates',sql='''SELECT o.old_row FROM old_facts o
            WHERE o.reference_kind IN ('file','retained-file') AND EXISTS (
              SELECT 1 FROM old_facts c WHERE c.receipt_key=o.receipt_key
                AND c.receipt_line=o.receipt_line AND c.body_sha=o.body_sha
                AND (c.context_url IS NOT DISTINCT FROM o.context_url)
                AND c.reference_kind IN ('capture','embedded'))
            AND EXISTS (SELECT 1 FROM new_values n WHERE n.receipt_key=o.receipt_key
                AND n.receipt_line=o.receipt_line AND n.body_sha=o.body_sha
                AND (n.context_url IS NOT DISTINCT FROM o.context_url)
                AND (o.stored_bytes IS NULL OR o.stored_bytes IS NOT DISTINCT FROM n.stored_bytes)
                AND (o.body_key IS NULL OR o.body_key IS NOT DISTINCT FROM n.body_key))'''),
        dict(name='old_values',sql='SELECT * FROM old_facts WHERE old_row NOT IN (SELECT old_row FROM secondary_duplicates)')]
    occurrence_keys='receipt_key,receipt_line,body_sha,pointer'
    occurrence_order='context_url,bytes,media_type,fidelity,http_status,try_cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),stored_bytes,family,run_id,member_path,body_key'
    steps.extend([
        dict(name='old_normalized',sql=f'''SELECT *,row_number() OVER (
            PARTITION BY {occurrence_keys} ORDER BY {occurrence_order},old_row) AS occurrence
            FROM old_values'''),
        dict(name='new_facts',sql=f'''SELECT *,row_number() OVER (
            PARTITION BY {occurrence_keys} ORDER BY {occurrence_order},capture_index) AS occurrence
            FROM new_values''')])
    join = '''o.receipt_key=n.receipt_key AND o.receipt_line=n.receipt_line
        AND (o.body_sha IS NOT DISTINCT FROM n.body_sha)
        AND (o.pointer IS NOT DISTINCT FROM n.pointer) AND o.occurrence=n.occurrence'''
    stable = ' OR '.join(f'(o."{k}" IS DISTINCT FROM n."{k}")'
                         for k in ('bytes','media_type','fidelity'))
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
    unexpected = f'''({stable}) OR ((o.context_url IS DISTINCT FROM n.context_url)
        AND NOT (o.qualified_bodiless AND o.context_url IS NULL))
        OR (o.family IS NOT NULL AND (o.family IS DISTINCT FROM n.family))
        OR (o.run_id IS NOT NULL AND (o.run_id IS DISTINCT FROM n.run_id))
        OR (o.member_path IS NOT NULL AND (o.member_path IS DISTINCT FROM n.member_path))
        OR (o.body_key IS NOT NULL AND (o.body_key IS DISTINCT FROM n.body_key))
        OR (o.stored_bytes IS NOT NULL AND (o.stored_bytes IS DISTINCT FROM n.stored_bytes))
        OR (o.http_status IS NOT NULL AND (o.http_status IS DISTINCT FROM n.http_status))
        OR {unexplained_time}'''
    expected = f'''(o.http_status IS NULL AND n.http_status IS NOT NULL)
        OR {restored_time}
        OR (o.stored_bytes IS NULL AND n.stored_bytes IS NOT NULL)
        OR (o.qualified_bodiless AND o.context_url IS NULL AND n.context_url IS NOT NULL)
        OR (o.family IS NULL AND n.family IS NOT NULL)
        OR (o.run_id IS NULL AND n.run_id IS NOT NULL)'''
    fact_values=[]
    for name in ('reference_kind','context_url','bytes','stored_bytes','media_type','fidelity','http_status',
                 'family','run_id','member_path','body_key','original_path','resolution','outcome'):
        kind='BIGINT' if name in {'bytes','stored_bytes','http_status'} else 'VARCHAR'
        fact_values.extend(f'cast({side}."{name}" AS {kind}) AS "{label}_{name}"'
                           for side,label in [('o','old'),('n','new')])
    fact_values=','.join(fact_values)
    steps += [dict(name='matched',sql=f'''SELECT o.old_row,n.receipt_key,n.receipt_line,n.capture_index,
        n.body_sha,n.pointer,{fact_values},
        cast(o.retrieved_at AS VARCHAR) AS old_retrieved_at,
        cast(n.retrieved_at AS VARCHAR) AS new_retrieved_at,
        {time_reason} AS retrieved_at_reason,
        ({unexpected}) AS unexplained,({expected}) AS expected_change
        FROM old_normalized o JOIN new_facts n ON {join}'''),
        dict(name='old_only',sql=f'SELECT o.old_row FROM old_normalized o LEFT ANTI JOIN new_facts n ON {join}'),
        dict(name='new_only',sql=f'SELECT n.* FROM new_facts n LEFT ANTI JOIN old_normalized o ON {join}')]
    # Shared native sorts and joins execute once for all exports and counts.
    for step in steps:
        if step['name'] in {'old_numbered','old_facts','new_values','secondary_duplicates',
                            'old_normalized','new_facts','matched','old_only','new_only'}:
            step['materialize']=True
    outputs = [parquet_output(work,'old-only',
        'SELECT o.* FROM old_numbered o JOIN old_only m ON o.old_row=m.old_row',['old_row']),
        parquet_output(work,'new-only','SELECT * FROM new_only',
                       ['receipt_key','receipt_line','capture_index']),
        parquet_output(work,'changed-fields',
            'SELECT * FROM matched WHERE unexplained OR expected_change',
            ['old_row','receipt_key','receipt_line','capture_index'])]
    query = '''SELECT (SELECT count(*) FROM old_numbered) AS old_rows,
        (SELECT count(*) FROM new_values) AS new_rows,
        (SELECT count(*) FROM secondary_duplicates) AS secondary_duplicates,
        (SELECT count(*) FROM old_only) AS old_only,
        (SELECT count(*) FROM new_only) AS new_only,
        (SELECT count(*) FROM matched WHERE unexplained) AS unexplained,
        (SELECT count(*) FROM matched WHERE expected_change AND NOT unexplained) AS expected_changes,
        (SELECT count(*) FROM matched) AS matched'''
    result = run_job(work,engine,inputs=[
        dict(name='old_input',kind='parquet',path=str(Path(old_index).resolve())),
        dict(name='new_input',kind='parquet',path=str(Path(evidence).resolve()))],
        steps=steps,outputs=outputs,queries=[dict(name='counts',sql=query)])['counts'][0]
    result['owner_gate'] = bool(result['old_only'] or result['new_only'] or result['unexplained'])
    result['rules'] = RULES
    result['coverage'] = dict(COVERAGE,available_old_fields=old_schema.names)
    (work/'comparison.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result
