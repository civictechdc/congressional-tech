"""Owner-decided list records retain each item's facts and source ordinal."""
import gzip
import json
import os

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
