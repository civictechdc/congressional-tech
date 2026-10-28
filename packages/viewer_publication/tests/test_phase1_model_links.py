"""Literal S1 link expectations bind repair and endpoint resolution SQL."""
import json
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_native_links_keep_context_base_member_and_split_positions(tmp_path):
    from viewer_publication.archive_model import link_steps,registry_inputs
    cases=json.loads((ROOT/'model/fixtures/s1-model-cases.json').read_text())['links']
    rows=[dict(id=c['id'],page_body='same-page',context_url=c['context'],member_path=c.get('member_path'),
        base_href=c.get('base'),href=c['href'],link_index=0,text='Publisher label',group_path='item/1',doc_type=None,
        add_date=None,publish_date=None,remove_date=None) for c in cases if 'href' in c]
    rows.extend([dict(rows[0],id='three',href='https://fixture.test/a.pdfhttps://fixture.test/b.xmlhttps://fixture.test/c.txt'),
        dict(rows[0],id='query',href='https://fixture.test/page?next=https://other.test/a.pdf'),
        dict(rows[0],id='archive',href='https://web.archive.org/web/20261001000000/https://fixture.test/a.pdf')])
    retained=['https://www.gpo.gov/fdsys/pkg/BILLS-115s585'+version+'/xml/BILLS-115s585'+version+'.xml' for version in ['rfh','es']]
    rows.append(dict(rows[0],id='retained-concat',href=''.join(retained)))
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'link_inputs',rows,id='Utf8',page_body='Utf8',context_url='Utf8',member_path='Utf8',
        base_href='Utf8',href='Utf8',link_index='Int64',text='Utf8',group_path='Utf8',doc_type='Utf8',add_date='Utf8',publish_date='Utf8',remove_date='Utf8'))
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=link_steps(),outputs=[],queries=[dict(name='targets',sql='SELECT id,target_url,target_member_path,split_position,link_index,text FROM resolved_links ORDER BY id,split_position')])
    expected=[]
    for c in cases:
        if 'href' not in c:continue
        for i,target in enumerate(c['expected']):
            expected.append(dict(id=c['id'],target_url=target['context_url'] if isinstance(target,dict) else target,
                target_member_path=target['member_path'] if isinstance(target,dict) else None,
                split_position=i,link_index=0,text='Publisher label'))
    for id,targets in [('three',['https://fixture.test/a.pdf','https://fixture.test/b.xml','https://fixture.test/c.txt']),
                       ('query',['https://fixture.test/page?next=https://other.test/a.pdf']),
                       ('archive',['https://web.archive.org/web/20261001000000/https://fixture.test/a.pdf'])]:
        expected.extend(dict(id=id,target_url=url,target_member_path=None,split_position=i,link_index=0,text='Publisher label') for i,url in enumerate(targets))
    expected.extend(dict(id='retained-concat',target_url=url,target_member_path=None,split_position=i,link_index=0,text='Publisher label') for i,url in enumerate(retained))
    assert result['targets']==sorted(expected,key=lambda x:(x['id'],x['split_position']))
