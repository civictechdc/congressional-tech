"""Seed publication proves its own inputs without claiming a raw rebuild."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_archive_publish import Store,Native,candidate,encoded,pin
from test_archive_seed_profile import arguments
from viewer_publication.archive_publish import input_digest,publish_candidate
from viewer_publication.archive_seed_profile import seed_profile_record


def seed(root):
    artifacts,manifest=candidate(root,rows=96)
    profile=seed_profile_record(**dict(arguments(),document_rows=100))['profile']
    manifest['origin']={key:profile[key] for key in
        ['kind','label','display_only','catalog_id','generation','input_files']}
    manifest['origin']['gaps']=['v5 has no recovery import events']
    path=Path(artifacts['manifest_pin']['path']);path.write_bytes(encoded(manifest))
    artifacts['manifest_pin']=pin(path)
    reports=[dict(name='seed_invariants',data=[dict(missing_required=0,bad_ids=0)]),
        dict(name='seed_reconciliation',data=[dict(input_docs=100,listed=96,merged_duplicates=1,excluded=3)]),
        dict(name='seed_exclusions',data=[dict(reason='seed_missing_format',count=3)]),
        dict(name='seed_spot_checks',data=[dict(source_row=i,filename_matches=True,format_matches=True,
            source_page_matches=True,meeting_matches=True) for i in range(50)])]
    path=Path(artifacts['result_pin']['path']);result=json.loads(path.read_text());result['queries']=reports
    path.write_bytes(encoded(result));artifacts['result_pin']=pin(path)
    record=dict(profile=profile,snapshots={},provenance=[],entity_digests={},run={'job':'seed-fixture'})
    record['input_digest']=input_digest(receipt_keys=[],provenance=[],profile=profile,entity_digests={})
    return artifacts,manifest,record


def publish(root,artifacts,record,*,keys=()):
    store=Store();native=Native(store);contexts=[]
    def passed(**context):
        contexts.append(context)
        return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    result=publish_candidate(client=store,engine=native,bucket='derived-fixture',work=root/'publish',
        **artifacts,input_record=record,receipt_keys=list(keys),pointer=None,expected_etag=None,
        public_origin='https://archive.example.test',contract=passed,canary=passed)
    return result,store,native,contexts


def test_seed_uses_same_gates_pointer_and_empty_canonical_receipt_evidence(tmp_path):
    artifacts,manifest,record=seed(tmp_path)
    result,store,native,contexts=publish(tmp_path,artifacts,record)
    assert result['status']=='published' and result['label']==record['profile']['label']
    assert result['display_only'] is True and result['input_kind']=='seed_v5'
    assert result['seed_reconciliation']==dict(input_docs=100,listed=96,merged_duplicates=1,excluded=3)
    assert len(contexts)==2 and all(context['manifest']['origin']==manifest['origin'] for context in contexts)
    assert json.loads(store.objects['viewer-publications/status.json'])['label']==record['profile']['label']
    from viewer_publication.archive_publish import matching_live_input,NativeArchiveStore
    from viewer_publication.receipt_pins import kept_input_records
    reader=NativeArchiveStore(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'read')
    found=matching_live_input(reader,release_id=result['release_id'],digest=record['input_digest'])
    assert found['snapshots']=={} and found['provenance']==[]
    entries,_=kept_input_records(reader,[result['release_id']])
    assert len(entries)==1 and entries[0]['receipt_keys']==[]


@pytest.mark.parametrize('change',['origin','capture','raw_guard','invariant_bool','missing_guard',
    'source_count','listed_count','excluded_count','duplicate_reason','sample_missing','sample_mismatch',
    'sample_duplicate','raw_receipts','raw_snapshots','raw_provenance','bad_gaps'])
def test_seed_refuses_bad_evidence_before_input_upload_or_pointer(tmp_path,change):
    artifacts,manifest,record=seed(tmp_path)
    result_path=Path(artifacts['result_pin']['path']);result=json.loads(result_path.read_text())
    by_name={query['name']:query for query in result['queries']};keys=[]
    if change=='origin':manifest['origin']['generation']='6'*32
    elif change=='capture':manifest['origin']['display_only']=False
    elif change=='raw_guard':result['queries']=[dict(name=name,data=[dict(violation=0)])
        for name in ['invariants','model_invariants','url_state_invariants','profile_completeness']]
    elif change=='invariant_bool':by_name['seed_invariants']['data'][0]['bad_ids']=False
    elif change=='missing_guard':result['queries'].pop(0)
    elif change=='source_count':by_name['seed_reconciliation']['data'][0]['input_docs']=53
    elif change=='listed_count':by_name['seed_reconciliation']['data'][0]['listed']=50
    elif change=='excluded_count':by_name['seed_exclusions']['data'][0]['count']=2
    elif change=='duplicate_reason':by_name['seed_exclusions']['data']=[dict(reason='same',count=1),dict(reason='same',count=2)]
    elif change=='sample_missing':by_name['seed_spot_checks']['data'].pop()
    elif change=='sample_mismatch':by_name['seed_spot_checks']['data'][4]['meeting_matches']=False
    elif change=='sample_duplicate':by_name['seed_spot_checks']['data'][4]=deepcopy(by_name['seed_spot_checks']['data'][3])
    elif change=='raw_receipts':keys=['receipts/documents/not-seed.jsonl.gz']
    elif change=='raw_snapshots':record['snapshots']={'captures':{'snapshot':1}}
    elif change=='bad_gaps':manifest['origin']['gaps']=[None]
    else:record['provenance']=[dict(key='provenance/reviews/a.jsonl.gz',etag='etag')]
    record['input_digest']=input_digest(receipt_keys=keys,provenance=record['provenance'],profile=record['profile'],entity_digests={})
    path=Path(artifacts['manifest_pin']['path']);path.write_bytes(encoded(manifest));artifacts['manifest_pin']=pin(path)
    result_path.write_bytes(encoded(result));artifacts['result_pin']=pin(result_path)
    store=Store();native=Native(store)
    with pytest.raises(ValueError):
        publish_candidate(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'publish',
            **artifacts,input_record=record,receipt_keys=keys,pointer=None,expected_etag=None,
            public_origin='https://archive.example.test',contract=lambda **context:pytest.fail('bad seed reached reader'),
            canary=lambda **context:pytest.fail('bad seed reached canary'))
    assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects


def test_retention_keeps_seed_without_reading_present_day_model_definitions(tmp_path):
    from test_archive_maintenance import Store as RetentionStore,NOW,LIVE
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.receipt_pins import write_input_receipts
    _,_,record=seed(tmp_path);store=RetentionStore();store.live=dict(release_id=LIVE)
    write_input_receipts(store,LIVE,record['input_digest'],record,[])
    result=maintain_releases(store,now=NOW)
    assert len(result['kept_inputs'])==1 and result['kept_inputs'][0]['snapshots']=={}
    assert store.deleted==[] and all(count==1 for count in store.reads.values())


def test_small_seed_samples_each_listed_document_and_keeps_merged_rows_separate(tmp_path):
    artifacts,manifest,record=seed(tmp_path)
    manifest['files'][0]['rows']=3
    from viewer_publication.archive_format import release_identity
    manifest['release_id']=release_identity(1,manifest['files'])
    path=Path(artifacts['manifest_pin']['path']);path.write_bytes(encoded(manifest));artifacts['manifest_pin']=pin(path)
    path=Path(artifacts['result_pin']['path']);result=json.loads(path.read_text())
    result['outputs'][0]['rows']=3
    for query in result['queries']:
        if query['name']=='seed_reconciliation':query['data']=[dict(input_docs=100,listed=3,merged_duplicates=97,excluded=0)]
        elif query['name']=='seed_exclusions':query['data']=[]
        elif query['name']=='seed_spot_checks':query['data']=query['data'][:3]
    path.write_bytes(encoded(result));artifacts['result_pin']=pin(path)
    published,_,_,_=publish(tmp_path,artifacts,record)
    assert published['status']=='published' and published['rows']['list.parquet']==3


def test_seed_data_gap_exclusions_above_three_percent_refuse_before_effects(tmp_path):
    artifacts,manifest,record=seed(tmp_path)
    manifest['files'][0]['rows']=95
    from viewer_publication.archive_format import release_identity
    manifest['release_id']=release_identity(1,manifest['files'])
    path=Path(artifacts['manifest_pin']['path']);path.write_bytes(encoded(manifest));artifacts['manifest_pin']=pin(path)
    path=Path(artifacts['result_pin']['path']);result=json.loads(path.read_text());result['outputs'][0]['rows']=95
    for query in result['queries']:
        if query['name']=='seed_reconciliation':query['data']=[dict(input_docs=100,listed=95,merged_duplicates=1,excluded=4)]
        elif query['name']=='seed_exclusions':query['data']=[dict(reason='seed_missing_format',count=4)]
    path.write_bytes(encoded(result));artifacts['result_pin']=pin(path)
    store=Store();native=Native(store)
    with pytest.raises(ValueError,match='three percent'):
        publish_candidate(client=store,engine=native,bucket='derived-fixture',work=tmp_path/'publish',
            **artifacts,input_record=record,receipt_keys=[],pointer=None,expected_etag=None,
            public_origin='https://archive.example.test',contract=lambda **_:pytest.fail('Excluded seed reached reader'),
            canary=lambda **_:pytest.fail('Excluded seed reached canary'))
    assert native.calls==[] and 'viewer-publications/manifest.json' not in store.objects
