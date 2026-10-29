"""Final public-only generation checks after mandatory receipt-local guards."""
import json
from pathlib import Path

from congress_api.lake.captures import PK
from congress_api.lake.tables import table_input
from congress_api.retention.body_store import validate_key
from congress_api.retention.provenance import json_input,parquet_output,run_job


class GenerationViolation(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__('Capture generation rejected; complete violations: '+report['violations_path'])


def validate_generation(*,engine,work,pin,counts):
    """Check one finished public table and export every offending key and row.

    Counts are independent per-receipt metadata, not reconstructed raw facts.
    Fixed native scans and narrow grouped tables cost O(N+R) expected grouping
    work; diagnostic ordering costs O(V log V). No wide per-capture aggregate is
    built. Receipt-local private guards remain mandatory in every batch.

    Completeness cannot be inferred from final outcome here: DM6.1 preserves a
    recorded prior-body value ahead of the older-line derivation, and the public
    table carries neither attempt nor recorded-value flags. Those checks stay
    with the receipt-local mapping; legitimate observations are never collapsed.
    """
    expected=[];seen=set()
    if not isinstance(counts,list):raise ValueError('Expected receipt counts must be explicit metadata')
    for row in counts:
        if (not isinstance(row,dict) or not isinstance(row.get('key'),str)
                or not row['key'].startswith('receipts/') or row['key'] in seen
                or type(row.get('expected_captures')) is not int or row['expected_captures']<0):
            raise ValueError('Expected receipt counts need unique raw keys and nonnegative integer counts')
        validate_key(row['key']);seen.add(row['key'])
        expected.append(dict(receipt_key=row['key'],expected_captures=row['expected_captures']))
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    schema=json.loads((Path(__file__).resolve().parents[5]/'model/lake/captures.schema.json').read_text())
    required=' OR '.join('c."'+f['name']+'" IS NULL' for f in schema['fields'] if f['required'])
    domains=required+r""" OR c.receipt_line<1 OR c.capture_index<0
        OR c.receipt_key NOT LIKE 'receipts/%' OR c.receipt_key='receipts/'
        OR regexp_like(c.receipt_key,'(^|/)[.]{1,2}(/|$)|//') OR strpos(c.receipt_key,chr(92))>0
        OR trim(c.run_id)='' OR trim(c.family)=''
        OR c.mode NOT IN ('fetch','retained_import')
        OR c.outcome NOT IN ('stored','unchanged','failed','retry_later','size_limit','request_failed','reference','saved-record')
        OR (c.http_status IS NOT NULL AND (c.http_status<100 OR c.http_status>599))
        OR c.bytes<0 OR c.stored_bytes<0
        OR (c.sha256 IS NOT NULL AND length(encode(c.sha256,'hex'))<>64)
        OR (c.stored_md5 IS NOT NULL AND length(encode(c.stored_md5,'hex'))<>32)
        OR (c.evidence_sha256 IS NOT NULL AND length(encode(c.evidence_sha256,'hex'))<>64)
        OR (c.stored_suffix IS NOT NULL AND c.stored_suffix NOT IN ('','.gz','.pdf'))
        OR (c.fidelity IS NOT NULL AND c.fidelity NOT IN ('exact-bytes','saved-text','saved-record','retained-file'))"""
    keycols=','.join('c.'+k for k in PK)
    same_pk=' AND '.join('(c.'+k+' IS NOT DISTINCT FROM p.'+k+')' for k in PK)
    steps=[
        dict(name='per_receipt',sql='SELECT receipt_key,count(*) AS actual_captures FROM captures GROUP BY receipt_key',materialize=True),
        dict(name='totals',sql='''SELECT (SELECT coalesce(sum(actual_captures),0) FROM per_receipt) AS rows,
            (SELECT count(*) FROM per_receipt) AS receipts,
            (SELECT coalesce(sum(expected_captures),0) FROM expected) AS expected_rows,
            (SELECT count(*) FROM expected) AS expected_receipts''',materialize=True),
        dict(name='population',sql='''SELECT coalesce(e.receipt_key,a.receipt_key) AS receipt_key,
            CASE WHEN a.actual_captures IS NULL THEN 'missing_receipt' WHEN e.expected_captures IS NULL
            THEN 'unexpected_receipt' ELSE 'receipt_count' END AS reason,
            e.expected_captures AS expected_count,a.actual_captures AS actual_count
            FROM expected e FULL OUTER JOIN per_receipt a ON e.receipt_key=a.receipt_key
            WHERE e.receipt_key IS NULL OR a.receipt_key IS NULL OR e.expected_captures<>a.actual_captures''',materialize=True),
        dict(name='duplicate_keys',sql='SELECT '+','.join(PK)+' FROM captures GROUP BY '+','.join(PK)+' HAVING count(*)>1',materialize=True),
        dict(name='body_sizes',sql='''SELECT sha256 FROM captures WHERE sha256 IS NOT NULL
            GROUP BY sha256 HAVING min(bytes)<>max(bytes)''',materialize=True),
        dict(name='physical_facts',sql='''SELECT sha256,coalesce(stored_suffix,'.gz') AS physical_suffix,
            min(stored_bytes)<>max(stored_bytes) AS size_conflict,
            min(encode(stored_md5,'hex'))<>max(encode(stored_md5,'hex')) AS md5_conflict
            FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256,coalesce(stored_suffix,'.gz')
            HAVING min(stored_bytes)<>max(stored_bytes)
                OR min(encode(stored_md5,'hex'))<>max(encode(stored_md5,'hex'))''',materialize=True),
        dict(name='bad_capture_keys',sql=f'''SELECT 'public_domain' AS reason,{keycols} FROM captures c WHERE {domains}
            UNION ALL SELECT 'duplicate_pk' AS reason,{keycols} FROM captures c JOIN duplicate_keys p ON {same_pk}
            UNION ALL SELECT 'decoded_bytes_conflict' AS reason,{keycols} FROM captures c JOIN body_sizes b ON c.sha256=b.sha256
            UNION ALL SELECT 'stored_bytes_conflict' AS reason,{keycols} FROM captures c JOIN physical_facts p
                ON c.sha256=p.sha256 AND coalesce(c.stored_suffix,'.gz')=p.physical_suffix WHERE p.size_conflict
            UNION ALL SELECT 'stored_md5_conflict' AS reason,{keycols} FROM captures c JOIN physical_facts p
                ON c.sha256=p.sha256 AND coalesce(c.stored_suffix,'.gz')=p.physical_suffix WHERE p.md5_conflict''',materialize=True),
        dict(name='violations',sql='''SELECT DISTINCT reason,receipt_key,receipt_line,capture_index,
            cast(NULL AS BIGINT) AS expected_count,cast(NULL AS BIGINT) AS actual_count FROM bad_capture_keys
            UNION ALL SELECT reason,receipt_key,cast(NULL AS INT) AS receipt_line,
                cast(NULL AS INT) AS capture_index,expected_count,actual_count FROM population
            UNION ALL SELECT 'total_count' AS reason,cast(NULL AS VARCHAR) AS receipt_key,
                cast(NULL AS INT) AS receipt_line,cast(NULL AS INT) AS capture_index,
                expected_rows AS expected_count,rows AS actual_count
                FROM totals WHERE rows<>expected_rows''',materialize=True),
        dict(name='violating_capture_keys',sql=f'''SELECT {','.join(PK)} FROM bad_capture_keys
            UNION SELECT {keycols} FROM captures c JOIN population p ON c.receipt_key IS NOT DISTINCT FROM p.receipt_key''',materialize=True)]
    result=run_job(work,engine,inputs=[table_input('captures',pin),json_input(work,'expected',expected,
        receipt_key='Utf8',expected_captures='Int64')],steps=steps,outputs=[
        parquet_output(work,'violations','SELECT * FROM violations',['reason',*PK]),
        # Diagnostic-only ordinal keeps exact duplicate facts exportable without
        # treating their invalid public PK as a unique writer ordering key.
        parquet_output(work,'violating-captures',f'''SELECT row_number() OVER (ORDER BY {keycols}) AS diagnostic_row,c.*
            FROM captures c LEFT SEMI JOIN violating_capture_keys p ON {same_pk}''',['diagnostic_row'])],
        queries=[dict(name='summary',sql='''SELECT t.*,
                (SELECT count(*) FROM violations) AS violations FROM totals t''')])
    report=dict(result['summary'][0],work=str(work),violations_path=str(work/'violations.parquet'),
        facts_path=str(work/'violating-captures.parquet'))
    report['status']='rejected' if report['violations'] else 'validated'
    if report['violations']:raise GenerationViolation(report)
    return report
