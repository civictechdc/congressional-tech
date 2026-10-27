"""Native old-index oracle comparison; never use derived rows as ingest input."""
import json
from pathlib import Path

import pyarrow.parquet as pq

from congress_api.retention.provenance import parquet_output, run_job


RULES = {
    'secondary_duplicates': 'Only a file/retained-file row duplicating a capture body on the same line and context is removed; storage facts are enriched by ingest.',
    'http_status': 'Restore missing HTTP statuses, including bodiless lines; status_code is HTTP, capture_status and meetingStatus are not.',
    'retrieved_at': 'Compare equivalent UTC instants unchanged. Accept only a missing old time restored to a valid new time; lost, conflicting, or invalid times require owner review. Ingest uses each entry fetch time before enclosing line times, then capture_date; checked_at, started_at and content dates are excluded.',
    'outcome_mode': 'Translate the versioned old vocabulary; classify the 2026-10-15 recovery run by its source associations.',
    'complete': 'Completeness belongs to its own attempt; a cut-off body cannot borrow the final retry success.',
    'storage': 'Enrich creating storage metadata; stored_md5 and stored_suffix are new, stored_sha256 is not a target column.',
    'bodiless_context': 'A bodiless target row retains its line URL even when the old metadata row omitted context.',
    'old_only': 'Every remaining old-only row is an owner gate. No inferred capture row or automatic dismissal is permitted.',
    'occurrences': 'Match repeated capture facts one-to-one after secondary-reference normalization; identical body/pointer facts never collapse capture multiplicity.',
}


def compare_old(evidence, old_index, *, engine, work):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    old_schema, new_schema = pq.read_schema(old_index), pq.read_schema(evidence)
    def value(schema, name, kind='VARCHAR'):
        return '"'+name+'"' if name in schema.names else f'cast(NULL AS {kind})'
    def projection(schema, old=False):
        sha = value(schema,'sha256')
        sha = f'lower({sha})' if old else f'encode({sha},\'hex\')'
        pointer = value(schema,'pointer_json')
        fields = ['receipt_key','receipt_line']
        cols = [f'"{k}"' for k in fields]
        cols += [f'{sha} AS body_sha', f'json_canonical({pointer}) AS pointer',
                 value(schema,'reference_kind')+' AS reference_kind']
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
                AND c.reference_kind IN ('capture','embedded'))'''),
        dict(name='old_values',sql='SELECT * FROM old_facts WHERE old_row NOT IN (SELECT old_row FROM secondary_duplicates)')]
    occurrence_keys='receipt_key,receipt_line,body_sha,pointer'
    occurrence_order='context_url,bytes,media_type,fidelity,http_status,retrieved_at,stored_bytes'
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
        AND NOT (o.body_sha IS NULL AND o.context_url IS NULL))
        OR (o.stored_bytes IS NOT NULL AND (o.stored_bytes IS DISTINCT FROM n.stored_bytes))
        OR (o.http_status IS NOT NULL AND (o.http_status IS DISTINCT FROM n.http_status))
        OR {unexplained_time}'''
    expected = f'''(o.http_status IS NULL AND n.http_status IS NOT NULL)
        OR {restored_time}
        OR (o.stored_bytes IS NULL AND n.stored_bytes IS NOT NULL)
        OR (o.body_sha IS NULL AND o.context_url IS NULL AND n.context_url IS NOT NULL)'''
    steps += [dict(name='matched',sql=f'''SELECT o.old_row,n.receipt_key,n.receipt_line,n.capture_index,
        cast(o.retrieved_at AS VARCHAR) AS old_retrieved_at,
        cast(n.retrieved_at AS VARCHAR) AS new_retrieved_at,
        {time_reason} AS retrieved_at_reason,
        ({unexpected}) AS unexplained,({expected}) AS expected_change
        FROM old_normalized o JOIN new_facts n ON {join}'''),
        dict(name='old_only',sql=f'SELECT o.old_row FROM old_normalized o LEFT ANTI JOIN new_facts n ON {join}'),
        dict(name='new_only',sql=f'SELECT n.* FROM new_facts n LEFT ANTI JOIN old_normalized o ON {join}')]
    outputs = [parquet_output(work,'old-only',
        'SELECT o.* FROM old_numbered o JOIN old_only m ON o.old_row=m.old_row',['old_row']),
        parquet_output(work,'new-only','SELECT * FROM new_only',
                       ['receipt_key','receipt_line','capture_index']),
        parquet_output(work,'changed-fields',
            'SELECT * FROM matched WHERE unexplained OR expected_change',
            ['old_row','receipt_key','receipt_line','capture_index'])]
    query = '''SELECT (SELECT count(*) FROM old_input) AS old_rows,
        (SELECT count(*) FROM new_input) AS new_rows,
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
    (work/'comparison.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result
