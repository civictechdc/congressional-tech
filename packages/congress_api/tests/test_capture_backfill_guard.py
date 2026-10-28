"""The final public-table gate preserves legitimate repeated observations."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


KEYS=['receipts/documents/2026-10-28/a.jsonl.gz','receipts/documents/2026-10-28/b.jsonl.gz']
COUNTS=[dict(key=key,expected_captures=1,source_rows=1) for key in KEYS]


def rows():
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    result=[]
    for key in KEYS:
        row=dict.fromkeys(f['name'] for f in schema['fields'])
        row.update(receipt_key=key,receipt_line=1,capture_index=0,run_id='run',mode='fetch',outcome='stored',
            family='documents',requested_url='https://example.org/shared',url='https://example.org/shared',
            http_status=200,complete=True,sha256=b'a'*32,bytes=10,stored_suffix='.gz',stored_bytes=5,
            stored_md5=b'm'*16,fidelity='exact-bytes')
        result.append(row)
    return result


def source(tmp_path,values):
    declared=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    types={'int':pa.int32(),'long':pa.int64(),'boolean':pa.bool_(),'timestamptz':pa.timestamp('us','UTC'),
        'fixed[32]':pa.binary(),'fixed[16]':pa.binary(),'string':pa.string()}
    schema=pa.schema([(f['name'],types[f['type']]) for f in declared['fields']])
    path=tmp_path/'captures.parquet';pq.write_table(pa.Table.from_pylist(values,schema=schema),path)
    return path


def check(tmp_path,values,counts=COUNTS):
    from congress_api.lake.capture_backfill_guard import validate_generation
    return validate_generation(engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'guard',pin=source(tmp_path,values),counts=counts)


def rejected(tmp_path,values,reason,counts=COUNTS):
    from congress_api.lake.capture_backfill_guard import GenerationViolation
    with pytest.raises(GenerationViolation) as error:check(tmp_path,values,counts)
    report=error.value.report
    assert report['status']=='rejected' and report['violations']>0
    violations=pq.read_table(report['violations_path']).to_pylist()
    assert reason in {r['reason'] for r in violations}
    assert Path(report['facts_path']).is_file()
    assert not (tmp_path/'guard/validated.json').exists()
    assert not (tmp_path/'guard/published.json').exists()
    return violations,pq.read_table(report['facts_path']).to_pylist()


def test_valid_repeated_observations_and_prior_completeness_are_not_conflicts(tmp_path):
    values=rows();values[1].update(http_status=404,outcome='request_failed',complete=True,
        media_type='application/xml')
    report=check(tmp_path,values)
    assert report['status']=='validated' and report['violations']==0
    assert (report['rows'],report['receipts'],report['expected_rows'],report['expected_receipts'])==(2,2,2,2)
    assert pq.read_metadata(report['violations_path']).num_rows==0
    assert pq.read_metadata(report['facts_path']).num_rows==0


def test_different_urls_and_physical_suffixes_can_share_decoded_bytes(tmp_path):
    values=rows();values[1].update(url='https://other.test/body',stored_suffix='',stored_bytes=10,stored_md5=b'z'*16)
    assert check(tmp_path,values)['status']=='validated'


@pytest.mark.parametrize('change',[
    dict(receipt_line=0),dict(capture_index=-1),dict(receipt_key=None),dict(run_id=None),dict(family=None),
    dict(mode='replay'),dict(outcome='invented'),dict(http_status=99),dict(http_status=600),
    dict(bytes=-1),dict(stored_bytes=-1),dict(sha256=b'a'*31),dict(stored_md5=b'm'*15),
    dict(evidence_sha256=b'e'*31),dict(stored_suffix='.unknown'),dict(fidelity='invented'),
])
def test_public_domain_violations_export_exact_rows(tmp_path,change):
    values=rows();values[0].update(change)
    _,facts=rejected(tmp_path,values,'public_domain')
    assert any(all(row[k]==value for k,value in change.items()) for row in facts)


def test_duplicate_primary_keys_export_every_occurrence(tmp_path):
    values=rows();values.append(dict(values[0]))
    counts=[dict(key=KEYS[0],expected_captures=2),dict(key=KEYS[1],expected_captures=1)]
    _,facts=rejected(tmp_path,values,'duplicate_pk',counts)
    assert len([r for r in facts if r['receipt_key']==KEYS[0]])==2


def test_missing_receipts_are_named_without_invented_capture_facts(tmp_path):
    violations,facts=rejected(tmp_path,rows()[:1],'missing_receipt')
    assert any(v['receipt_key']==KEYS[1] for v in violations)
    assert all(r['receipt_key']!=KEYS[1] for r in facts)


def test_extra_receipts_export_all_actual_facts(tmp_path):
    values=rows();values.append(dict(values[0],receipt_key='receipts/documents/2026-10-28/extra.jsonl.gz'))
    _,facts=rejected(tmp_path,values,'unexpected_receipt')
    assert any(r['receipt_key'].endswith('/extra.jsonl.gz') for r in facts)


def test_independent_per_receipt_and_total_counts_are_both_gates(tmp_path):
    counts=[dict(key=KEYS[0],expected_captures=2),dict(key=KEYS[1],expected_captures=1)]
    violations,_=rejected(tmp_path,rows(),'receipt_count',counts)
    assert 'total_count' in {v['reason'] for v in violations}


@pytest.mark.parametrize('change,reason',[
    (dict(bytes=11),'decoded_bytes_conflict'),
    (dict(stored_bytes=6),'stored_bytes_conflict'),
    (dict(stored_md5=b'n'*16),'stored_md5_conflict'),
    (dict(stored_suffix=None,stored_bytes=6),'stored_bytes_conflict'),
])
def test_cross_receipt_body_conflicts_export_both_sides(tmp_path,change,reason):
    values=rows();values[1].update(change)
    _,facts=rejected(tmp_path,values,reason)
    assert {r['receipt_key'] for r in facts}==set(KEYS)


def test_null_metadata_is_not_a_conflicting_observation(tmp_path):
    values=rows();values[1].update(bytes=None,stored_bytes=None,stored_md5=None)
    assert check(tmp_path,values)['status']=='validated'
