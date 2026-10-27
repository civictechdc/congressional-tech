"""Author input fixtures, then let the native engine join versioned policy data."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]


@pytest.mark.parametrize('duplicate', [False, True])
def test_recovery_registry_keeps_categories_and_refuses_unknown_or_duplicate(duplicate, tmp_path):
    cases = json.loads((ROOT / 'model/fixtures/recovery-kind-cases.json').read_text())
    registry = json.loads((ROOT / 'model/registries/recovery-kinds.json').read_text())
    registered = {(row['category'], row['match_basis']) for row in registry}
    sampled = {(row['category'], None if row['category'] else row['match_basis'])
               for row in cases if row['expected_kind'] is not None}
    assert registered == sampled
    for case in cases:
        if case['expected_kind'] is None:
            continue
        assert case['receipt_key'].startswith('receipts/') and case['receipt_line'] > 0
        assert case['mode'] == 'retained_import'
        assert case['body_hex'] is None or len(case['body_hex']) == 64
    if duplicate:
        registry += [registry[0]]
    # These are small authored test inputs, not an application export path.
    for name, rows, columns in [('cases', cases, ['id', 'category', 'match_basis']),
                                 ('registry', registry, ['category', 'match_basis', 'kind', 'import_category'])]:
        schema = pa.schema([pa.field(name, pa.string()) for name in columns])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp_path / (name + '.parquet'))
    spec = dict(scratch=str(tmp_path / 'native'), inputs=[dict(name=name, kind='parquet',
        path=str(tmp_path / (name + '.parquet'))) for name in ['cases', 'registry']], outputs=[],
        steps=[dict(name='classified', sql='''SELECT f.id,CASE WHEN f.category IS NOT NULL THEN c.kind ELSE b.kind END AS kind,
            CASE WHEN f.category IS NOT NULL THEN CASE WHEN c.kind IS NOT NULL THEN f.category END ELSE b.import_category END AS import_category
            FROM cases f LEFT JOIN registry c ON f.category=c.category
            LEFT JOIN registry b ON f.category IS NULL AND f.match_basis=b.match_basis''')],
        queries=[dict(name='values', sql='SELECT DISTINCT id,kind,import_category FROM classified ORDER BY id'),
                 dict(name='duplicates', sql='''SELECT count(*) AS violations FROM
                     (SELECT category,match_basis FROM registry GROUP BY category,match_basis HAVING count(*)>1)'''),
                 dict(name='invalid_shape', sql='SELECT count(*) AS violations FROM registry WHERE (category IS NULL)=(match_basis IS NULL)'),
                 dict(name='unknown', sql='SELECT count(*) AS violations FROM classified WHERE kind IS NULL')])
    path = tmp_path / 'job.json'
    path.write_text(json.dumps(spec))
    result = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']).run_job(path)
    values = {query['name']: query['data'] for query in result['queries']}
    assert values['values'] == [dict(id=case['id'], kind=case['expected_kind'], import_category=case['expected_import_category']) for case in sorted(cases, key=lambda row: row['id'])]
    assert values['duplicates'] == [dict(violations=int(duplicate))]
    assert values['invalid_shape'] == [dict(violations=0)]
    assert values['unknown'] == [dict(violations=1)], 'a known basis never masks an unknown category'
