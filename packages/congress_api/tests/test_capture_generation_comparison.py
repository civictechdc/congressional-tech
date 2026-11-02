"""ct-5f3e: a rebuilt capture generation is compared with the last one, every column both ways."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

KEY = 'receipts/documents/2026-10-28/a.jsonl.gz'


def table(tmp_path, name, change=None, extra=None):
    declared = json.loads((Path(__file__).resolve().parents[3] / 'model/lake/captures.schema.json').read_text())
    types = {'int': pa.int32(), 'long': pa.int64(), 'boolean': pa.bool_(), 'timestamptz': pa.timestamp('us', 'UTC'),
             'fixed[32]': pa.binary(), 'fixed[16]': pa.binary(), 'string': pa.string()}
    rows = []
    for index in range(3):
        row = dict.fromkeys(f['name'] for f in declared['fields'])
        row.update(receipt_key=KEY, receipt_line=1, capture_index=index, run_id='run', mode='fetch', outcome='stored',
                   family='documents', requested_url='https://example.org/a', http_status=200, complete=True,
                   sha256=bytes([index]) * 32, bytes=10, mapping_version='a' * 64)
        rows.append(row)
    if change:
        rows[1].update(change)
    rows += extra or []
    path = tmp_path / (name + '.parquet')
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([(f['name'], types[f['type']]) for f in declared['fields']])), path)
    return path


def compare(tmp_path, change, expected=None, extra=None):
    tmp_path.mkdir(parents=True)
    from congress_api.lake.capture_comparison import compare_generations
    return compare_generations(table(tmp_path, 'old'), table(tmp_path, 'new', change, extra),
                               engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                               work=tmp_path / 'work', expected=expected, receipt_keys=[KEY])


def test_one_eligibility_change_is_reported_by_value_and_refused_unless_expected(tmp_path):
    from congress_api.lake.capture_comparison import GenerationChange
    with pytest.raises(GenerationChange) as error:
        compare(tmp_path / 'refused', dict(complete=None))
    report = error.value.report
    assert report['rows'] == 3 and report['changes']['complete'] == 1 and report['changes']['good_fetch'] == 1
    assert sum(report['changes'].values()) == 2
    assert ['complete', 'true', None, 1] in report['pairs'] and ['good_fetch', 'true', 'false', 1] in report['pairs']
    assert {tuple(u[:3]) for u in report['unexpected']} == {('complete', 'true', None), ('good_fetch', 'true', 'false')}
    expected = dict(pairs=[['complete', 'true', None, 1], ['good_fetch', 'true', 'false', 1]], only_old=0, only_new=0)
    assert compare(tmp_path / 'accepted', dict(complete=None), expected)['status'] == 'accepted'
    # A wrong count is refused too.
    expected['pairs'][0][3] = 2
    with pytest.raises(GenerationChange):
        compare(tmp_path / 'count', dict(complete=None), expected)


def test_mapping_versions_are_reported_and_new_rows_refused(tmp_path):
    from congress_api.lake.capture_comparison import GenerationChange
    report = compare(tmp_path / 'version', dict(mapping_version='b' * 64))
    assert report['pairs'] == [['mapping_version', 'a' * 64, 'b' * 64, 1]] and report['status'] == 'accepted'
    with pytest.raises(GenerationChange) as error:
        extra = dict(receipt_key=KEY, receipt_line=2, capture_index=0, run_id='run', mode='fetch', family='documents')
        compare(tmp_path / 'new-row', None, extra=[extra])
    assert error.value.report['unexpected'] == [['only_new', 0, 1]]
