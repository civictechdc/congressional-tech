"""Only completed dedicated feed readings add context to XML listings."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


def test_feed_and_sitemap_roles_do_not_supply_link_context(tmp_path):
    # These are the roles already settled by DM7.3. Context construction reuses
    # them, including URL-classified sitemaps, rather than detecting feeds again.
    cases=[('rss','xml','listing'),('atom','xml','listing'),('sitemap','xml','listing'),
        ('ordinary','html','listing'),('mods','xml','source_record'),('page','html','document'),
        ('floor','xml','listing'),('floor-native-error','xml','listing'),
        ('floor-partial','xml','listing'),('floor-error','xml','listing'),
        ('floor-placeholder','xml','listing'),('other-derived','xml','listing')]
    derived={
        'floor': ('house_floor_feed','completed'),
        'floor-native-error': ('house_floor_feed','completed'),
        'floor-partial': ('house_floor_feed','partial'),
        'floor-error': ('house_floor_feed','error'),
        'floor-placeholder': ('house_floor_feed','completed'),
        'other-derived': ('html_metadata','completed'),
    }
    fetches=[dict(receipt_key='r',receipt_line=i,capture_index=0,body_hex=f'{i:064x}',
        context_url='https://fixture.test/'+name,member_path=None,retrieved_at='2026-10-28T00:00:00Z')
        for i,(name,_,_) in enumerate(cases,1)]
    inputs=[json_input(tmp_path,'fetch_rows',fetches,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',
        body_hex='Utf8',context_url='Utf8',member_path='Utf8',retrieved_at='Utf8'),
        json_input(tmp_path,'record_roles',[dict(receipt_key='r',receipt_line=i,capture_index=0,format=kind,record_role=role)
            for i,(_,kind,role) in enumerate(cases,1)],receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',format='Utf8',record_role='Utf8'),
        json_input(tmp_path,'derived_rows',[
            dict(body_hex=f'{i:064x}',parser=derived[name][0],status=derived[name][1])
            for i,(name,_,_) in enumerate(cases,1) if name in derived],
            body_hex='Utf8',parser='Utf8',status='Utf8')]
    root=Path(__file__).parents[3]/'model/sql'
    steps=[dict(name='good_fetches',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM fetch_rows"),
        dict(name='page_facts',sql="""SELECT sha256 AS body_sha,
            CASE WHEN context_url='https://fixture.test/floor-native-error' THEN 'error' ELSE 'completed' END AS status
            FROM good_fetches"""),
        dict(name='selected_readings',sql="SELECT decode(body_hex,'hex') AS body_sha,parser,status FROM derived_rows"),
        dict(name='house_floor_feed_readings',sql=(root/'house-floor-feed-readings.sql').read_text(),materialize=True),
        dict(name='placeholders',sql="SELECT sha256 FROM good_fetches WHERE context_url='https://fixture.test/floor-placeholder'"),
        dict(name='page_contexts',sql=(root/'page-contexts.sql').read_text())]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result=run_job(tmp_path,engine,inputs=inputs,steps=steps,outputs=[],
            queries=[dict(name='contexts',sql='SELECT context_url FROM page_contexts ORDER BY context_url')])
    # A feed can supply context despite its generic XML reading failing. Partial
    # and failed feeds, other derived parsers, and placeholders cannot. The floor
    # row present in both discovery branches must still yield exactly one context.
    assert result['contexts']==[dict(context_url='https://fixture.test/'+name)
        for name in ['floor','floor-native-error','mods','ordinary','page']]
