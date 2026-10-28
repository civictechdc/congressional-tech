"""Oracle comparison retains evidence while releasing consumed native tables."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.capture_comparison import compare_old
from docspec_client.client import NativeDatasets


def test_comparison_completes_with_bounded_native_memory(tmp_path):
    config = json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    limits = json.loads(Path(config['limits']).read_text())
    limits.update(memory_bytes=192 << 20, scratch_bytes=256 << 20,
                  batch_rows=32, max_batch_bytes=1 << 20, max_metadata_bytes=1 << 20)
    limit_path = tmp_path/'limits.json'
    limit_path.write_text(json.dumps(limits))
    config.update(limits=str(limit_path), workspace=str(tmp_path/'workspace'), timeout_seconds=120)
    config_path = tmp_path/'runtime.json'
    config_path.write_text(json.dumps(config))
    count = 2048
    rows = [dict(receipt_key='receipts/documents/2026-10-20/large-contexts.gz',
                 receipt_line=index + 1, pointer_json='["body"]',
                 context_url='https://example.org/' + str(index) + '/' + 'x'*8192,
                 bytes=100, stored_bytes=42, media_type='application/pdf',
                 fidelity='exact-bytes', http_status=200,
                 retrieved_at='2026-10-20T00:00:00Z') for index in range(count)]
    old = tmp_path/'old.parquet'
    new = tmp_path/'new.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256='a'*64, reference_kind='capture') for row in rows]), old)
    pq.write_table(pa.Table.from_pylist([
        dict(row, sha256=bytes.fromhex('a'*64), capture_index=0,
             reference_kind='capture') for row in rows]), new)
    result = compare_old(new, old, engine=NativeDatasets.from_config(config_path),
                         work=tmp_path/'comparison')
    assert result['old_rows'] == result['new_rows'] == result['matched'] == count
    assert result['old_only'] == result['new_only'] == result['secondary_duplicates'] == 0
    assert result['unexplained'] == result['expected_changes'] == 0
    assert result['owner_gate'] is False
    for name in ('old-only', 'new-only', 'expected-new-only',
                 'unexplained-new-only', 'changed-fields'):
        assert pq.read_metadata(tmp_path/'comparison'/(name + '.parquet')).num_rows == 0
