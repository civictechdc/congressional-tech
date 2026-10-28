"""Whole-receipt bounded backfill scheduling and guard scope precede the driver."""
import importlib

import pytest


@pytest.fixture
def backfill():
    return importlib.import_module('congress_api.lake.capture_backfill')


def source(name,byte_count,items,**more):
    return dict(key='receipts/documents/2026-10-28/'+name+'.jsonl.gz',
        source_rows=1,uncompressed_bytes=byte_count,list_items=items,
        expected_captures=1,max_line_bytes=byte_count,max_line_items=items,**more)


def test_whole_receipts_heaviest_batch_first_and_deterministic(backfill):
    counts=[source('a',70,2),source('b',20,8),source('c',20,2),source('d',10,1)]
    files=[dict(key=row['key'],path='/input/'+str(i)+'.gz') for i,row in enumerate(counts)]
    plan=backfill.make_plan(files,counts,byte_target=100,item_target=10)
    assert plan==backfill.make_plan(files[::-1],counts[::-1],byte_target=100,item_target=10)
    actual=[key for batch in plan['batches'] for key in batch['receipt_keys']]
    assert sorted(actual)==sorted(row['key'] for row in counts) and len(actual)==len(set(actual))
    weights=[]
    for batch in plan['batches']:
        assert batch['uncompressed_bytes']<=100 and batch['list_items']<=10
        assert batch['source_kind']=='receipt-files' and not batch['oversized_receipt']
        weights.append(max(batch['uncompressed_bytes']*10,batch['list_items']*100))
    assert weights==sorted(weights,reverse=True)


def test_heaviest_indivisible_receipt_is_explicit_singleton(backfill):
    counts=[source('huge',500,30),source('small',10,1)]
    plan=backfill.make_plan([dict(key=r['key'],path='/input/'+str(i)+'.gz') for i,r in enumerate(counts)],counts,byte_target=100,item_target=10)
    first=plan['batches'][0]
    assert first['receipt_keys']==[counts[0]['key']]
    assert first['oversized_receipt'] is True
    assert first['uncompressed_bytes']==500 and first['list_items']==30
    assert len(plan['batches'])==2


def test_prepared_stage_stays_whole_and_source_backends_never_mix(backfill):
    counts=[source(str(i),10,1) for i in range(5)]
    files=[dict(key=counts[0]['key'],path='/input/zero.gz'),dict(key=counts[1]['key'],path='/input/one.gz'),
        dict(key=counts[2]['key'],path='/input/two.gz'),
        dict(key=counts[3]['key'],prepared_stage='/accepted/once'),
        dict(key=counts[4]['key'],prepared_stage='/accepted/once')]
    plan=backfill.make_plan(files,counts,byte_target=100,item_target=10)
    by_kind={batch['source_kind']:batch for batch in plan['batches']}
    assert set(by_kind)=={'receipt-files','prepared-stage'}
    assert by_kind['receipt-files']['receipt_keys']==[counts[0]['key'],counts[1]['key'],counts[2]['key']]
    assert by_kind['prepared-stage']['receipt_keys']==[counts[3]['key'],counts[4]['key']]
    assert by_kind['prepared-stage']['prepared_stage']=='/accepted/once'


@pytest.mark.parametrize('change',[
    'missing_count','extra_count','duplicate_count','duplicate_inventory','negative_bytes',
    'bool_items','zero_rows','expected_exceeds_items','bad_key','two_backends','counter',
])
def test_bad_source_scope_or_cost_refuses_before_work(backfill,change):
    counts=[source('a',10,1)];files=[dict(key=counts[0]['key'],path='/input/a.gz')]
    if change=='missing_count':counts=[]
    elif change=='extra_count':counts.append(source('extra',1,1))
    elif change=='duplicate_count':counts.append(dict(counts[0]))
    elif change=='duplicate_inventory':files.append(dict(files[0]))
    elif change=='negative_bytes':counts[0]['uncompressed_bytes']=-1
    elif change=='bool_items':counts[0]['list_items']=True
    elif change=='zero_rows':counts[0]['source_rows']=0
    elif change=='expected_exceeds_items':counts[0]['expected_captures']=2
    elif change=='bad_key':files[0]['key']=counts[0]['key']='outside.gz'
    elif change=='counter':files[0].pop('path')
    elif change=='two_backends':files[0].update(path='/raw.gz',prepared_stage='/accepted')
    with pytest.raises(ValueError):backfill.make_plan(files,counts,byte_target=100,item_target=10)


@pytest.mark.parametrize('value',[0,-1,True,1.5])
def test_bad_batch_targets_refuse(backfill,value):
    counts=[source('a',1,1)]
    with pytest.raises(ValueError):backfill.make_plan([dict(key=counts[0]['key'])],counts,byte_target=value,item_target=10)


def test_every_existing_private_guard_has_an_explicit_receipt_scope(backfill):
    from congress_api.lake.captures import capture_checks
    scopes=backfill.receipt_local_check_scopes(capture_checks())
    assert list(scopes)==[check['name'] for check in capture_checks()]
    assert scopes==dict(positions=('receipt_key','receipt_line'),
        reference_shapes=('receipt_key','receipt_line'),invalid=('receipt_key','receipt_line'),
        secondary=('receipt_key','receipt_line','body_key','body_sha'),
        list_facts=('receipt_key','receipt_line','list_ordinal'),missing=('receipt_key',))
    with pytest.raises(ValueError):
        backfill.receipt_local_check_scopes(capture_checks()+[dict(name='unclassified',sql='SELECT 1')])
