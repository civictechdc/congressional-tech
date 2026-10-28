"""Vote.outcome is a domain field, distinct from acquisition outcome."""
import json

import pyarrow.parquet as pq
import pytest

from test_captures_ingest import body,ingest
from test_captures_narrow import NARROW_COLUMNS


VOTE_OUTCOMES=('unknown','agreed','rejected','tied','other')


@pytest.mark.parametrize('vote_outcome',VOTE_OUTCOMES)
def test_list_vote_domain_outcomes_keep_sibling_and_line_acquisition_facts(tmp_path,vote_outcome):
    # Reduced House meeting-XML line14: a vote has no acquisition fields.
    # One sibling reference and its unreferenced vote exercise both list paths.
    vote=dict(kind='vote',outcome=vote_outcome)
    source=[dict(record=[vote,dict(kind='document',url='https://fixture.test/sibling',
                outcome='stored',http_status=200,complete=True)],
            captures=[body(pointer=['1','content','body'],complete=True)]),
        dict(http_status=404,outcome='http_error',complete=False,record=[vote]),
        dict(http_status=200,complete=True,record=[vote],
            captures=[body(pointer=[0,'content','body'],complete=True)])]
    stage=ingest(tmp_path,source,key='receipts/house/meeting-xml/undated/vote-domain.jsonl.gz')
    table=pq.read_table(stage/'captures.parquet');rows=table.to_pylist()
    assert table.schema.names==NARROW_COLUMNS and len(table.schema.names)==34
    assert [(r['receipt_line'],r['capture_index']) for r in rows]==[(1,0),(1,1),(2,0),(3,0)]
    assert len({(r['receipt_key'],r['receipt_line'],r['capture_index']) for r in rows})==4
    assert [r['outcome'] for r in rows]==['stored','failed','failed','stored']
    assert [r['http_status'] for r in rows]==[200,None,404,200]
    assert [r['complete'] for r in rows]==[True,True,False,True]
    assert [r['url'] for r in rows]==['https://fixture.test/sibling',None,None,None]
    assert [r['sha256'] is not None for r in rows]==[True,False,False,True]
    evidence=pq.read_table(stage/'capture-evidence.parquet')
    assert evidence['source_record_index'].to_pylist()==[1,0,0,0]
    assert evidence['source_record_count'].to_pylist()==[2,2,1,1]
    manifest=json.loads((stage/'ingested-receipts.json').read_text())
    assert manifest['source_counts']==dict(receipts=1,rows=3)
    result=json.loads((stage/'result.json').read_text())
    assert next(q['data'] for q in result['queries'] if q['name']=='violations')==[]
    from congress_api.lake.receipt_metadata import source_schema
    assert len(source_schema()['fields'])==24
    assert 'kind' not in {f['name'] for f in source_schema()['fields']}


@pytest.mark.parametrize('case',['line_unknown','non_vote','wrong_case_vote','ordinary_vote'])
def test_vote_discriminator_never_admits_unknown_acquisition_values(tmp_path,case):
    if case=='line_unknown':
        source=dict(outcome='unknown',http_status=200,record=[dict(kind='vote',outcome='agreed')],
            captures=[body(pointer=[0,'content','body'])])
    elif case=='ordinary_vote':source=dict(record=dict(kind='vote',outcome='unknown'))
    else:
        source=dict(http_status=404,outcome='http_error',record=[
            dict(kind='document' if case=='non_vote' else 'Vote',outcome='unknown')])
    with pytest.raises(ValueError,match='unknown.*outcome'):ingest(tmp_path,[source])
    assert not (tmp_path/'stage/ingested-receipts.json').exists()
    assert not (tmp_path/'stage/captures.parquet').exists()


def test_non_vote_list_acquisition_outcomes_keep_own_priority(tmp_path):
    source=dict(http_status=404,outcome='http_error',record=[
        dict(kind='document',outcome='failed',http_status=200,url='https://fixture.test/failed'),
        dict(kind='document',outcome='stored',http_status=200,url='https://fixture.test/stored')],
        captures=[body(pointer=[0,'content','body']),body(pointer=[1,'content','body'])])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['capture_index'],r['outcome'],r['http_status']) for r in rows]==[(0,'failed',200),(1,'stored',200)]
    assert [r['url'] for r in rows]==['https://fixture.test/failed','https://fixture.test/stored']
