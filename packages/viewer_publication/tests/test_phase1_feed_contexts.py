"""Feed listings supply no publisher context; ordinary listings still do."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


def test_feed_and_sitemap_roles_do_not_supply_link_context(tmp_path):
    # These are the roles already settled by DM7.3. Context construction reuses
    # them, including URL-classified sitemaps, rather than detecting feeds again.
    cases=[('rss','xml','listing'),('atom','xml','listing'),('sitemap','xml','listing'),
        ('ordinary','html','listing'),('mods','xml','source_record'),('page','html','document')]
    fetches=[dict(receipt_key='r',receipt_line=i,capture_index=0,body_hex=f'{i:064x}',
        context_url='https://fixture.test/'+name,member_path=None,retrieved_at='2026-10-28T00:00:00Z')
        for i,(name,_,_) in enumerate(cases,1)]
    inputs=[json_input(tmp_path,'fetch_rows',fetches,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',
        body_hex='Utf8',context_url='Utf8',member_path='Utf8',retrieved_at='Utf8'),
        json_input(tmp_path,'record_roles',[dict(receipt_key='r',receipt_line=i,capture_index=0,format=kind,record_role=role)
            for i,(_,kind,role) in enumerate(cases,1)],receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',format='Utf8',record_role='Utf8')]
    steps=[dict(name='good_fetches',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM fetch_rows"),
        dict(name='page_facts',sql="SELECT sha256 AS body_sha,'completed' AS status FROM good_fetches"),
        dict(name='placeholders',sql='SELECT sha256 FROM good_fetches WHERE false'),
        dict(name='page_contexts',sql=(Path(__file__).parents[3]/'model/sql/page-contexts.sql').read_text())]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps,outputs=[],queries=[dict(name='contexts',sql='SELECT context_url FROM page_contexts ORDER BY context_url')])
    assert result['contexts']==[dict(context_url='https://fixture.test/'+name) for name in ['mods','ordinary','page']]
