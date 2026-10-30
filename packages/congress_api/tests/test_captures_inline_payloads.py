"""Finite retained payloads stay distinct from acquisition descriptors."""
from copy import deepcopy
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from test_captures_ingest import ingest

CASES=json.loads((Path(__file__).resolve().parents[3]/'model/fixtures/captures-inline-payloads.json').read_text())
PAYLOADS=CASES[:-1]


@pytest.mark.parametrize('case',PAYLOADS,ids=[c['id'] for c in PAYLOADS])
def test_demonstrated_inline_payload_survives_positive_marker(tmp_path,case):
    record=case['record']
    stage=ingest(tmp_path,[dict(record=record),dict(record=dict(record,http_status=200))],
                 key=case['source']['receipt_key'])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['saved-record','saved-record']
    assert [r['http_status'] for r in rows]==[None,200]
    assert all(r['sha256'] is None and r['bytes'] is None for r in rows)


@pytest.mark.parametrize('case',PAYLOADS,ids=[c['id'] for c in PAYLOADS])
def test_inline_payload_preserves_failures_and_requires_its_finite_shape(tmp_path,case):
    record=case['record']
    missing=deepcopy(record)
    if case['id']=='committee-detail-captured':missing['detail']={}
    elif case['id']=='meeting-event-captured':missing['meeting']={}
    else:missing['event']='unlisted-audit-event'
    rows=[dict(record=dict(record,http_status=404)),
          dict(record=dict(record,outcome='failed',http_status=200)),
          dict(record=dict(record,outcome='request_failed',http_status=200)),
          dict(record=dict(record,mode='fetch',http_status=200)),dict(record=missing),
          dict(record=dict(record,error='request failed')),
          dict(record=dict(record,error_type='ValueError')),
          dict(record=record,error='outer request failed'),
          dict(record=dict(record,http_status=301)),dict(record=dict(record,http_status=302))]
    stage=ingest(tmp_path,rows,key=case['source']['receipt_key'])
    actual=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in actual]==['failed','failed','request_failed']+['failed']*7
    assert all(r['sha256'] is None for r in actual)


@pytest.mark.parametrize('case',PAYLOADS,ids=[c['id'] for c in PAYLOADS])
def test_inline_payload_does_not_bypass_unknown_acquisition_vocabulary(tmp_path,case):
    with pytest.raises(ValueError,match='unknown.*outcome'):
        ingest(tmp_path,[dict(record=dict(case['record'],outcome='unreviewed-success'))],
               key=case['source']['receipt_key'])
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


def test_mods_descriptor_does_not_establish_inline_payload_custody(tmp_path):
    case=CASES[-1]
    stage=ingest(tmp_path,[dict(record=case['record'])],key=case['source']['receipt_key'])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['outcome']=='reference'
    assert row['sha256'] is None and row['bytes'] is None


def test_mods_descriptor_requires_exact_finite_shape_and_preserves_failures(tmp_path):
    case=CASES[-1]
    record=case['record']
    missing=deepcopy(record);missing.pop('etag')
    rows=[missing,dict(record,package_id=''),dict(record,sha256='not-a-digest'),
          dict(record,bytes=0),dict(record,bytes=-1),dict(record,bytes='45043'),
          dict(record,url='https://www.govinfo.gov/metadata/pkg/OTHER/mods.xml'),
          dict(record,xml='<mods/>'),dict(record,http_status=404),
          dict(record,outcome='failed'),dict(record,error='request failed')]
    stage=ingest(tmp_path,[dict(record=r) for r in rows],key=case['source']['receipt_key'])
    actual=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in actual]==['failed']*len(rows)
    assert all(r['sha256'] is None and r['bytes'] is None for r in actual)


@pytest.mark.parametrize('scope',['family','filename'])
def test_mods_descriptor_does_not_generalize_beyond_registered_scope(tmp_path,scope):
    case=CASES[-1]
    key=case['source']['receipt_key']
    if scope=='family':key=key.replace('govinfo/mods','documents')
    else:key=key.replace('assemble-20260930','download-unreviewed')
    stage=ingest(tmp_path,[dict(record=case['record'])],key=key)
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['outcome']=='failed' and row['sha256'] is None
