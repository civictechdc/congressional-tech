"""Only named domain vocabularies are excluded from acquisition outcomes."""
import importlib.util
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest

from congress_api.lake import captures,receipt_metadata
from test_captures_ingest import body,ingest
from test_captures_narrow import NARROW_COLUMNS


PROVIDER='receipts/external/provider-responses/2026-09-29/assemble-20260930.jsonl.gz'
TIMES=['2026-09-29T11:10:03.041021+00:00','2026-09-29T11:10:04.671901+00:00',
       '2026-09-29T11:10:06.760155+00:00']


def provider_item(index,outcome):
    # Acquisition fields and lookup values are reduced from real line489.
    # URLs/body identities are synthetic; result is the retained domain label.
    return dict(outcome=outcome,url=f'https://fixture.test/lookup/{index}',receipt=dict(
        result='unresolved_response',http_status=200,body_complete=True,
        retrieved_at=TIMES[index],url=f'https://fixture.test/source/{index}'))


def test_provider_line489_uses_receipt_facts_and_preserves_each_item(tmp_path):
    items=[provider_item(0,'captured_original_page'),provider_item(1,'captured_original_page'),
           provider_item(2,'original_body_unresolved')]
    stage=ingest(tmp_path,[dict(http_status=404,complete=False,retrieved_at='2020-01-01T00:00:00Z',
        record=items,captures=[body(pointer=[0,'receipt','body']),body(pointer=[1,'receipt','body'])])],key=PROVIDER)
    table=pq.read_table(stage/'captures.parquet');rows=table.to_pylist()
    assert table.schema.names==NARROW_COLUMNS and len(table.schema)==34
    assert len(receipt_metadata.source_schema()['fields'])==24
    assert [(r['receipt_line'],r['capture_index']) for r in rows]==[(1,0),(1,1),(1,2)]
    assert [r['http_status'] for r in rows]==[200,200,200]
    assert [r['complete'] for r in rows]==[True,True,True]
    assert [r['outcome'] for r in rows]==['stored','stored','failed']
    assert [r['retrieved_at'].isoformat() for r in rows]==TIMES
    assert [r['url'] for r in rows]==[f'https://fixture.test/source/{i}' for i in range(3)]
    assert [r['sha256'] is not None for r in rows]==[True,True,False]
    assert pq.read_table(stage/'capture-evidence.parquet')['source_record_index'].to_pylist()==[0,1,2]


@pytest.mark.parametrize('case',['wrong_family','daily_name','unknown_provider','unknown_vote',
                               'line_domain','unknown_receipt'])
def test_unrecognized_values_outside_the_named_domain_scope_refuse(tmp_path,case):
    key=PROVIDER;item=provider_item(0,'captured_original_page');line=dict(record=[item])
    if case=='wrong_family':key=PROVIDER.replace('external/provider-responses','documents')
    elif case=='daily_name':key=PROVIDER.replace('assemble-20260930','download-20260930')
    elif case=='unknown_provider':item['outcome']='unreviewed_provider_classification'
    elif case=='unknown_vote':item=dict(kind='vote',outcome='unreviewed_vote');line=dict(record=[item])
    elif case=='line_domain':line=dict(outcome='captured_original_page',record=[{}])
    else:item['receipt']['outcome']='unreviewed_fetch_outcome'
    with pytest.raises(ValueError,match='unknown.*outcome'):ingest(tmp_path,[line],key=key)
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


def test_known_acquisition_outcome_keeps_its_priority_even_for_vote_items(tmp_path):
    stage=ingest(tmp_path,[dict(outcome='failed',http_status=404,record=[dict(
        kind='vote',outcome='stored',http_status=200,url='https://fixture.test/acquired',
        receipt=dict(outcome='failed',http_status=503))],captures=[body(pointer=[0,'body'])])])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert (row['outcome'],row['http_status'],row['url'])==('stored',200,'https://fixture.test/acquired')


def test_domain_registry_bytes_are_part_of_the_mapping_identity(tmp_path):
    root=Path(captures.__file__).resolve().parents[5]
    relative=Path('model/registries/receipt-domain-outcomes.json')
    for source in (Path(captures.__file__),Path(receipt_metadata.__file__),root/relative):
        target=tmp_path/source.resolve().relative_to(root)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    copied=tmp_path/Path(captures.__file__).resolve().relative_to(root)
    spec=importlib.util.spec_from_file_location('copied_domain_capture_mapping',copied)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    before=module.current_version()
    registry=tmp_path/relative;registry.write_bytes(registry.read_bytes()+b'\n')
    assert module.current_version()!=before
