"""The production source-count query deduplicates cheaply under native limits."""
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets

from test_captures_ingest import body,ingest


def test_actual_d1_source_count_sql_preserves_counts_with_a_bounded_memory_budget(tmp_path):
    from congress_api.retention.provenance import run_job
    stage=ingest(tmp_path/'ordinary',[dict(captures=[body()])])
    accepted=json.loads((stage/'ingested-receipts.json').read_text())
    assert accepted['source_counts']==dict(rows=1,receipts=1)
    job=json.loads((stage/'job.json').read_text())
    source_counts=next(step for step in job['steps'] if step['name']=='source_counts')
    runtime=json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    limits=json.loads(Path(runtime['limits']).read_text())
    limits.update(compute_threads=4,memory_bytes=128<<20,max_batch_bytes=64<<20)
    limits_path=tmp_path/'limits.json';limits_path.write_text(json.dumps(limits))
    runtime.update(limits=str(limits_path),workspace=str(tmp_path/'native-workspace'))
    runtime_path=tmp_path/'runtime.json';runtime_path.write_text(json.dumps(runtime))
    work=tmp_path/'bounded';work.mkdir()
    fixture=dict(name='scalar_rows',materialize=True,sql="""SELECT
        concat('receipts/documents/2026-10-28/',cast(a.value % 4 AS VARCHAR),'.gz') AS receipt_key,
        a.value AS receipt_line,false AS is_secondary,cast(0 AS BIGINT) AS list_ordinal
        FROM generate_series(1,4096) a CROSS JOIN generate_series(1,32) b
        UNION ALL SELECT 'excluded-secondary' AS receipt_key,0 AS receipt_line,true AS is_secondary,0 AS list_ordinal
        UNION ALL SELECT 'excluded-list-ordinal' AS receipt_key,0 AS receipt_line,false AS is_secondary,1 AS list_ordinal""")
    counts=run_job(work,NativeDatasets.from_config(runtime_path),inputs=[],
        steps=[fixture,source_counts],outputs=[],
        queries=[dict(name='counts',sql='SELECT * FROM source_counts')])
    assert counts['counts']==[dict(rows=4096,receipts=4)]
