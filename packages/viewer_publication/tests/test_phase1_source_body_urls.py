"""Compact native distinct URL values before a hash join retains their buffers."""
import json
import os
from pathlib import Path
import re

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets


def test_native_body_url_build_compacts_aggregate_backing_before_retention(tmp_path):
    from viewer_publication.archive_model import source_steps
    config = json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    limits = json.loads(Path(config['limits']).read_text())
    limits.update(memory_bytes=1 << 30, scratch_bytes=256 << 20, max_batch_bytes=8 << 20)
    (tmp_path/'limits.json').write_text(json.dumps(limits))
    config.update(limits=str(tmp_path/'limits.json'), workspace=str(tmp_path/'workspace'), timeout_seconds=90)
    (tmp_path/'runtime.json').write_text(json.dumps(config))
    inputs = [json_input(tmp_path, 'source_url_keys', [], url='Utf8', url_key='Utf8', error='Utf8'),
              json_input(tmp_path, 'source_reference_targets', [],
                         url_key='Utf8', body_sha='Utf8', filename='Utf8', source_url='Utf8')]
    count = 196608
    body = 'a' * 64
    # Generate actual values in native SQL. Multiple aggregate output batches
    # otherwise retain the same large backing buffers in the hash build.
    steps = [dict(name='capture_source_names', materialize=True, sql=f'''
        SELECT id AS receipt_line,rpad('https://fixture.test/'||cast(id AS VARCHAR),512,'x') AS source_url,
        decode('{body}','hex') AS sha256,'stored' AS outcome,cast(NULL AS VARCHAR) AS member_path,
        '{body}' AS body_sha,'one.pdf' AS filename FROM (SELECT unnest(range(0,{count})) AS id)''')]
    source = source_steps()
    steps += [step for step in source if step['name'] == 'source_body_urls']
    target = next(step['sql'] for step in source if step['name'] == 'capture_sources')
    with NativeDatasets.from_config(tmp_path/'runtime.json') as engine:
        result = run_job(tmp_path/'job', engine, inputs=inputs, steps=steps, outputs=[], queries=[
            dict(name='plan', sql='EXPLAIN '+target),
            dict(name='measured', sql='EXPLAIN ANALYZE VERBOSE '+target)])
    retained = next(step for step in steps if step['name'] == 'source_body_urls')
    assert retained['materialize'] is True
    assert retained['sql'].strip() == 'SELECT DISTINCT source_url FROM capture_source_names WHERE sha256 IS NOT NULL'
    plan = next(row['plan'] for row in result['plan'] if row['plan_type'] == 'physical_plan')
    assert 'AggregateExec:' not in plan
    assert 'StreamingTableExec: partition_sizes=1, projection=[source_url]' in plan
    measured = next(row['plan'] for row in result['measured'] if row['plan_type'] == 'Plan with Metrics')
    build = next(line for line in measured.splitlines()
                 if 'HashJoinExec:' in line and 'on=[(source_url@' in line)
    value, suffix = re.search(r'build_mem_used=([\d.]+)\s*([KMB]?)', build).groups()
    displayed_bytes = float(value) * {'': 1, 'K': 1000, 'M': 1000000, 'B': 1000000000}[suffix]
    # Native display rounds this byte-count gauge; the margin is deliberately
    # wider than its display precision. The corpus inline build charged 9.73GB.
    assert displayed_bytes < 128 << 20, build
    assert next(row['plan'] for row in result['measured'] if row['plan_type'] == 'Output Rows') == str(count)
