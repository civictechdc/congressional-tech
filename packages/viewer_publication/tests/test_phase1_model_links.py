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
    boundary=[
        ('member-absolute',dict(member_path='html/page.html',href='https://external.test/file.pdf'),
            'https://external.test/file.pdf',None),
        ('member-base',dict(member_path='html/page.html',base_href='https://external.test/files/',href='file.pdf'),
            'https://external.test/files/file.pdf',None),
        ('member-percent',dict(member_path='html/a%20b.html',base_href=None,href='#section'),
            rows[0]['context_url'],'html/a%20b.html'),
        ('member-encoded',dict(member_path='html/page.html',href='../pdf/a%20b%2520c.pdf?x=1#section'),
            rows[0]['context_url'],'pdf/a b%20c.pdf'),
        ('member-root',dict(member_path='html/page.html',href='/pdf/root.pdf'),
            rows[0]['context_url'],'pdf/root.pdf'),
        ('same-href-invalid-context',dict(context_url='bad base',base_href=None,href='relative.pdf'),None,None),
        ('same-href-valid-context',dict(base_href=None,href='relative.pdf'),
            'https://fixture.test/one/relative.pdf',None),
        ('invalid-repaired-part',dict(href='https://fixture.test/a.pdfhttps://fixture.test/not-a-file'),None,None),
    ]
    rows.extend(dict(rows[0],**dict(changes,id=id)) for id,changes,_,_ in boundary)
    # Duplicate anchors keep separate publisher attribution but share target resolution.
    rows.append(dict(rows[0],id='second-anchor',link_index=9,text='Second publisher label'))
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
    for id,_,url,member in boundary:
        if url is not None:
            expected.append(dict(id=id,target_url=url,target_member_path=member,split_position=0,
                link_index=0,text='Publisher label'))
    expected.append(dict(id='second-anchor',target_url='https://fixture.test/files/report.pdf',target_member_path=None,
        split_position=0,link_index=9,text='Second publisher label'))
    assert result['targets']==sorted(expected,key=lambda x:(x['id'],x['split_position']))
