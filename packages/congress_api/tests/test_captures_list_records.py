"""Owner-decided list records retain each item's facts and source ordinal."""
import gzip
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from capture_qualification_helpers import created_qualifications
from test_captures_ingest import body,ingest,STAMP
from test_captures_root_objects import minimal_counter


def test_caption_negative_report_preserves_all_655_bodiless_items(tmp_path):
    counts=[('candidate_live_and_archive_manifests_not_found',88),('request_or_parse_error',1),
        ('stream_present_no_separate_subtitle_track_embedded_not_checked',558),
        ('subtitle_playlist_found_needs_capture',4),('unsupported_or_placeholder_player',4)]
    records=[dict(player_url=f'https://fixture.test/player/{index}/{item}',
        legacy=dict(kind='none',characters='0'),parsed_player=['committee',str(item)],
        checked_at=STAMP,manifests=[dict(status_code=404,url='https://fixture.test/manifest')],
        outcome=outcome) for index,(outcome,count) in enumerate(counts) for item in range(count)]
    run='raw-source-backfill-20260928/captions/recovery/senate-legacy-negatives/report.json'
    source=dict(source_file=run,mode=None,outcome=None,complete=None,requested_url=None,url=None,record=records)
    stage=ingest(tmp_path,[source])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert len(rows)==655 and [r['capture_index'] for r in rows]==list(range(655))
    assert len({(r['receipt_key'],r['receipt_line'],r['capture_index']) for r in rows})==655
    assert [r['outcome'] for r in rows]==['failed']*88+['request_failed']+['failed']*566
    assert [r['complete'] for r in rows]==[True]*88+[False]+[True]*566
    assert {r['run_id'] for r in rows}=={run} and {r['mode'] for r in rows}=={'fetch'}
    assert all(r[name] is None for r in rows for name in ('http_status','retrieved_at','sha256','url','requested_url'))
    assert json.loads((stage/'ingested-receipts.json').read_text())['source_counts']==dict(rows=1,receipts=1)
    evidence=pq.read_table(stage/'capture-evidence.parquet')
    assert evidence['record_is_list'].to_pylist()==[True]*655
    assert evidence['source_record_count'].to_pylist()==[655]*655
    assert evidence['source_record_index'].to_pylist()==list(range(655))
    assert evidence.schema.field('record_is_list').type==pa.bool_()
    assert evidence.schema.field('source_record_count').type==pa.int64()
    assert evidence.schema.field('source_record_index').type==pa.int64()
    assert not {'record_is_list','source_record_count','source_record_index'} & set(rows[0])
    with gzip.open(tmp_path/'input/receipt.gz','rt') as stream:assert json.loads(stream.read())==source


def test_item_facts_precede_root_fallback_only_for_list_records(tmp_path):
    root=dict(mode='fetch',outcome='request_failed',complete=False,http_status=503,
        requested_url='https://fixture.test/root-request',url='https://fixture.test/root',retrieved_at=STAMP)
    items=[dict(mode='fetch',outcome='saved',complete=True,http_status=200,
        requested_url='https://fixture.test/a-request',url='https://fixture.test/a',
        captured_at='2026-10-18T00:00:00Z'),
        dict(mode='retained_import',outcome='request_or_parse_error',complete=False,status_code=404,
            _url='https://fixture.test/b',observed_at='2026-10-19T00:00:00Z'),{}]
    source=dict(root,record=items)
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['capture_index'] for r in rows]==[0,1,2]
    assert [(r['mode'],r['outcome'],r['http_status'],r['complete']) for r in rows]==[
        ('fetch','failed',200,True),('retained_import','request_failed',404,False),('fetch','retry_later',503,False)]
    assert [r['url'] for r in rows]==['https://fixture.test/a','https://fixture.test/b',root['url']]
    assert [r['requested_url'] for r in rows]==['https://fixture.test/a-request','https://fixture.test/b',root['requested_url']]
    assert [r['retrieved_at'].isoformat() for r in rows]==[
        '2026-10-18T00:00:00+00:00','2026-10-19T00:00:00+00:00','2026-10-20T12:34:56+00:00']
    with gzip.open(tmp_path/'input/receipt.gz','rt') as stream:assert json.loads(stream.read())==source


def test_body_reference_ordinals_and_entry_facts_keep_selected_item_binding(tmp_path):
    stage=ingest(tmp_path,[dict(http_status=503,complete=False,url='https://fixture.test/root',
        record=[dict(url='https://fixture.test/a',http_status=200,complete=True,outcome='saved'),
                dict(url='https://fixture.test/b',status_code=404,complete=False,outcome='request_failed')],
        captures=[body(pointer=['1','content','body'],complete=True,retrieved_at=STAMP),
                  body(pointer=[0,'content','body'])])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['capture_index'],r['url'],r['http_status'],r['complete'],r['outcome']) for r in rows]==[
        (0,'https://fixture.test/b',404,True,'request_failed'),(1,'https://fixture.test/a',200,True,'stored')]
    assert rows[0]['retrieved_at'].isoformat()=='2026-10-20T12:34:56+00:00'


def test_qualified_new_writer_header_precedence_stays_line_owned(tmp_path):
    stage=ingest(tmp_path,[dict(writer=dict(job='capture',commit='a'*40),
        response_headers={'content-disposition':'qualified-root'},record=[
            dict(response_headers={'content-disposition':'legacy-a'}),
            dict(response_headers={'content-disposition':'legacy-b'})])])
    assert pq.read_table(stage/'captures.parquet')['h_content_disposition'].to_pylist()==['qualified-root']*2


def test_conflicting_duplicate_counter_facts_within_one_list_item_still_refuse(tmp_path):
    from congress_api.lake.captures import stage_captures
    key='receipts/documents/2026-10-20/duplicate.gz'
    counter=minimal_counter(tmp_path,[(key,dict(record=[dict(url=url)],captures=[]))
        for url in ('https://fixture.test/a','https://fixture.test/b')],False)
    with pytest.raises(ValueError,match='list record conflicting facts'):
        stage_captures([dict(key=key)],validated_counter=counter,
            source_qualifications=created_qualifications(counter),
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'stage')
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


@pytest.mark.parametrize('other_complete',[False,True])
def test_cutoff_isolation_keeps_other_record_items_out_of_the_inference(tmp_path,other_complete):
    stage=ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/same',http_status=200,outcome='saved')]*2,
        captures=[dict(body(pointer=[0,'content','body'],complete=False),bytes=64<<20),
                  body(pointer=[1,'content','body'],complete=other_complete)])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['size_limit','stored']
    assert [r['complete'] for r in rows]==[False,other_complete]


def test_expansion_isolation_keeps_members_with_their_selected_record_item(tmp_path):
    stage=ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/same')]*2,captures=[
        body(pointer=[0,'content','body']),
        body(pointer=[0,'archive_members',0,'body'],member_path='inside.pdf'),
        body(pointer=[1,'content','body'])])])
    assert pq.read_table(stage/'captures.parquet')['expansion'].to_pylist()==['expanded',None,None]


@pytest.mark.parametrize('primary',['captures','file_references'])
@pytest.mark.parametrize('counter',[False,True])
def test_mixed_primary_ordinals_stay_stable_and_bodiless_items_append(tmp_path,primary,counter):
    from congress_api.lake.captures import stage_captures
    source=dict(record=[dict(url='https://fixture.test/a',http_status=200,outcome='saved'),
        dict(url='https://fixture.test/b',http_status=404,outcome='request_or_parse_error')],
        captures=[],file_references=[])
    source[primary]=[body(pointer=[0,'content','body']),body(pointer=['0','another','body'])]
    if counter:
        key='receipts/documents/2026-10-20/mixed.gz'
        path=minimal_counter(tmp_path,[(key,source)],False)
        stage=stage_captures([dict(key=key)],validated_counter=path,
            source_qualifications=created_qualifications(path),
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'stage')
    else:stage=ingest(tmp_path,[source])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['capture_index'],r['url'],r['http_status'],r['outcome'],r['complete']) for r in rows]==[
        (0,'https://fixture.test/a',200,'stored',True),
        (1,'https://fixture.test/a',200,'stored',True),
        (2,'https://fixture.test/b',404,'request_failed',False)]
    assert rows[0]['sha256']==rows[1]['sha256'] and rows[2]['sha256'] is None
    evidence=pq.read_table(stage/'capture-evidence.parquet')
    assert evidence['record_is_list'].to_pylist()==[True]*3
    assert evidence['source_record_count'].to_pylist()==[2]*3
    assert evidence['source_record_index'].to_pylist()==[0,0,1]
    assert evidence['reference_kind'].to_pylist()==['capture' if primary=='captures' else 'file']*2+['line']
    assert json.loads((stage/'ingested-receipts.json').read_text())['source_counts']==dict(rows=1,receipts=1)


def test_multiple_unreferenced_items_append_in_record_order_after_primary_rows(tmp_path):
    source=dict(record=[dict(url=f'https://fixture.test/{i}') for i in range(4)],captures=[
        body(pointer=[2,'content','body']),body(pointer=['2','another','body'])])
    stage=ingest(tmp_path,[source]);rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['capture_index'] for r in rows]==[0,1,2,3,4]
    assert [r['url'] for r in rows]==['https://fixture.test/2']*2+[
        'https://fixture.test/0','https://fixture.test/1','https://fixture.test/3']
    assert pq.read_table(stage/'capture-evidence.parquet')['source_record_index'].to_pylist()==[2,2,0,1,3]
    with gzip.open(tmp_path/'input/receipt.gz','rt') as stream:assert json.loads(stream.read())==source


def test_secondary_storage_reference_does_not_replace_an_unreferenced_item_row(tmp_path):
    stage=ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/a'),dict(url='https://fixture.test/b')],
        captures=[body(pointer=[0,'content','body'])],
        file_references=[body(pointer=[1,'content','body'],stored_bytes=42)])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [(r['capture_index'],r['url'],r['stored_bytes']) for r in rows]==[
        (0,'https://fixture.test/a',42),(1,'https://fixture.test/b',None)]
    assert rows[0]['sha256'] is not None and rows[1]['sha256'] is None
