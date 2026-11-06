"""Native selected-caption resource mapping, including redirects and missing declarations."""
import os
from pathlib import Path

from congress_api.retention.provenance import run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_caption_resources_keep_root_order_redirects_repeats_and_missing_children(tmp_path):
    root="arrow_cast(decode(repeat('ab',32),'hex'),'FixedSizeBinary(32)')"
    child="arrow_cast(decode(repeat('cd',32),'hex'),'FixedSizeBinary(32)')"
    steps=[
        dict(name='recording_tracks',sql=f'''SELECT 'senate:fixture' AS video_key,
          make_array(named_struct('body',{root},'source_url','https://www.senate.gov/fixture/track.m3u8',
            'suffix','.gz','format','m3u8')) AS resources''',materialize=True),
        dict(name='selected_playlist_records',sql=f'''SELECT {root} AS record_sha,'pinned-reader' AS parser_version,
          'completed' AS status,make_array('segment.vtt','missing.vtt','segment.vtt') AS segments''',materialize=True),
        dict(name='recording_fetch_candidates',sql=f'''SELECT {child} AS sha256,'.gz' AS suffix,'text' AS body_format,
          'https://www.senate.gov/fixture/redirected.vtt' AS fetch_url,'https://www.senate.gov/fixture/segment.vtt' AS redirected_from,
          cast('2026-11-01' AS TIMESTAMP) AS retrieved_at,'new' AS receipt_key,cast(0 AS INT) AS receipt_line,cast(0 AS INT) AS capture_index
          UNION ALL SELECT {root},'.gz','vtt','https://www.senate.gov/fixture/segment.vtt',cast(NULL AS VARCHAR),
          cast('2026-10-01' AS TIMESTAMP) AS retrieved_at,'old' AS receipt_key,cast(0 AS INT) AS receipt_line,cast(0 AS INT) AS capture_index''',materialize=True),
        *[dict(name=name.replace('-','_'),sql=(ROOT/'model/sql'/f'{name}.sql').read_text(),materialize=True)
          for name in ('caption-resource-requests','caption-resources')],
    ]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        rows=run_job(tmp_path,engine,inputs=[],steps=steps,outputs=[],queries=[dict(name='resources',sql='''SELECT ordinal,
          source_url,declared_uri,encode(body,'hex') AS body,format,status,parser_version FROM caption_resources ORDER BY ordinal''')])['resources']
    assert [r['ordinal'] for r in rows]==[0,1,2,3]
    assert [r['status'] for r in rows]==['retained','retained','missing','retained']
    assert [r['body'] for r in rows]==['ab'*32,'cd'*32,None,'cd'*32]
    assert rows[1]['source_url']=='https://www.senate.gov/fixture/segment.vtt'
    assert rows[2]['declared_uri']=='missing.vtt'
    assert rows[1]['format']=='vtt'
    assert all(r['parser_version']=='pinned-reader' for r in rows)
