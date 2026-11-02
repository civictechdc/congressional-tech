"""Address provenance is one publisher tuple; URL packages precede filename facts."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).parents[3]


def test_source_listing_selects_one_earliest_address_compatible_tuple(tmp_path):
    addresses=[dict(component='top',source_id=s,url='https://files.test/report.pdf',member_path=None,first_fetched='2026-10-22T12:00:00Z') for s in ['source-a','source-b']]
    addresses += [dict(component='member',source_id='member',url=url,member_path=path,first_fetched='2026-10-22T12:00:00Z')
        for url,path in [('https://files.test/package.zip','a/report.pdf'),('https://files.test/package.zip','b/report.pdf'),('https://other.test/package.zip','a/report.pdf')]]
    addresses += [dict(component='redirect',source_id='redirect',url='https://actual.test/report.pdf',member_path=None,first_fetched='2026-10-22T12:00:00Z')]
    def link(source,page,label,target_key,target_member=None,day=20):
        return dict(source_id=source,context_url='https://pages.test/'+page,context='https://pages.test/'+page,page_body=page,
            first_good_at=f'2026-10-{day}T12:00:00Z',link_index=0,split_position=0,text=label,doc_type='type-'+label,
            add_date=f'2026-10-{day-1}',url_key=target_key,target_member_path=target_member)
    links=[link('source-a','page-a','Zlabel','files.test/report.pdf'),
           link('source-b','page-z','Alabel','files.test/report.pdf',day=21),
           link('member','member-a','Aonly','files.test/package.zip','a/report.pdf'),
           link('member','container','Container','files.test/package.zip',day=21),
           link('redirect','redirect','Redirect','requested.test/old.pdf')]
    inputs=[json_input(tmp_path,'document_addresses',addresses,component='Utf8',source_id='Utf8',url='Utf8',member_path='Utf8',first_fetched='Utf8'),
        json_input(tmp_path,'saved_files',[dict(component=c,source_id=s,saved_rank=1) for c,s in [('top','source-a'),('member','member'),('redirect','redirect')]],component='Utf8',source_id='Utf8',saved_rank='Int64'),
        json_input(tmp_path,'document_identities',[dict(component=c,document_id='id:'+c) for c in ['top','member','redirect']],component='Utf8',document_id='Utf8'),
        json_input(tmp_path,'publisher_links',links,source_id='Utf8',context_url='Utf8',context='Utf8',page_body='Utf8',first_good_at='Utf8',link_index='Int64',split_position='Int64',text='Utf8',doc_type='Utf8',add_date='Utf8',url_key='Utf8',target_member_path='Utf8'),
        json_input(tmp_path,'model_url_keys',[dict(url=url,url_key=url.removeprefix('https://'),error=None) for url in sorted({row['url'] for row in addresses})],url='Utf8',url_key='Utf8',error='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='source_input',sql=(ROOT/'model/sql/document-source-input.sql').read_text(),materialize=True)],outputs=[],queries=[
            dict(name='sources',sql='SELECT url,member_path,listed_on,link_text,doc_type,cast(posted AS VARCHAR) AS posted FROM source_input ORDER BY url,member_path')])
    assert result['sources']==[
        dict(url='https://actual.test/report.pdf',member_path=None,listed_on='https://pages.test/redirect',link_text='Redirect',doc_type='type-Redirect',posted='2026-10-19'),
        dict(url='https://files.test/package.zip',member_path='a/report.pdf',listed_on='https://pages.test/member-a',link_text='Aonly',doc_type='type-Aonly',posted='2026-10-19'),
        dict(url='https://files.test/package.zip',member_path='b/report.pdf',listed_on='https://pages.test/container',link_text='Container',doc_type='type-Container',posted='2026-10-20'),
        dict(url='https://files.test/report.pdf',member_path=None,listed_on='https://pages.test/page-a',link_text='Zlabel',doc_type='type-Zlabel',posted='2026-10-19'),
        dict(url='https://other.test/package.zip',member_path='a/report.pdf',listed_on=None,link_text=None,doc_type=None,posted=None)]


def test_document_package_uses_member_url_order_before_saved_filename_fallback(tmp_path):
    inputs=[json_input(tmp_path,'saved_files',[dict(component='document',source_id=s,saved_rank=i) for i,s in enumerate(['saved','second','third'],1)]+[dict(component='fallback',source_id='only-filename',saved_rank=1)],component='Utf8',source_id='Utf8',saved_rank='Int64'),
        json_input(tmp_path,'source_annotation_addresses',[
            dict(source_id='saved',package_id='PUBLISHER-PACKAGE',publisher=True),
            dict(source_id='second',package_id='CHRG-119hhrg22222',publisher=False),
            dict(source_id='third',package_id='CHRG-119hhrg33333',publisher=False)],source_id='Utf8',package_id='Utf8',publisher='Boolean'),
        json_input(tmp_path,'source_annotations',[dict(source_id='saved',package_id='FILENAME-PACKAGE'),dict(source_id='only-filename',package_id='FILENAME-ONLY')],source_id='Utf8',package_id='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='document_packages',sql=(ROOT/'model/sql/document-packages.sql').read_text(),materialize=True)],outputs=[],queries=[dict(name='packages',sql='SELECT * FROM document_packages ORDER BY component')])
    assert result['packages']==[dict(component='document',package_id='CHRG-119hhrg22222'),dict(component='fallback',package_id=None)]


def test_document_removals_use_each_pages_latest_timestamp_and_require_all_removed(tmp_path):
    from congress_api.retention.provenance import json_input, run_job
    from docspec_client.client import NativeDatasets
    import os
    page = 'https://docs.house.gov/meetings/AA/AA00/20261001/123456/HHRG-119-AA00-20261001.xml'
    rows = []
    def add(component, stamp, removed, context=page):
        rows.append(dict(source_id=str(len(rows)), component=component,
                         context_url=context, last_good_at=stamp, remove_date=removed))
    add('removed', '2026-01-01T12:00:00Z', '2026-01-02')
    add('readded', '2026-01-01T12:00:00Z', '2026-01-02')
    add('readded', '2026-02-01T12:00:00Z', None)
    add('tied', '2026-03-01T12:00:00Z', '2026-02-02')
    add('tied', '2026-03-01T07:00:00-05:00', '2026-02-01')
    add('tied-readd', '2026-03-01T12:00:00Z', '2026-02-01')
    add('tied-readd', '2026-03-01T12:00:00Z', None)
    add('unknown-time', None, '2026-01-02')
    add('two-pages', '2026-03-01T12:00:00Z', '2026-02-01')
    add('two-pages', '2026-02-01T12:00:00Z', None, page.replace('123456', '123457'))
    add('unrelated', '2026-03-01T12:00:00Z', '2026-02-01', 'https://fixture.test/meeting.xml')
    add(None, '2026-03-01T12:00:00Z', '2026-02-03')
    inputs = [json_input(tmp_path, 'appearances', rows, source_id='Utf8', component='Utf8',
                        context_url='Utf8', last_good_at='Utf8', remove_date='Utf8')]
    steps = [dict(name='document_members', sql='SELECT source_id,component FROM appearances'),
             dict(name='publisher_links', sql='''SELECT * EXCLUDE(component,last_good_at),
                 cast(last_good_at AS TIMESTAMP WITH TIME ZONE) AS last_good_at FROM appearances'''),
             dict(name='document_removals', sql=(ROOT/'model/sql/document-removals.sql').read_text())]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result = run_job(tmp_path/'job', engine, inputs=inputs, steps=steps, outputs=[],
                         queries=[dict(name='removed', sql='SELECT * FROM document_removals')])
    assert {(row['component'], row['removed_on']) for row in result['removed']} == {
        ('removed', '2026-01-02'), ('tied', '2026-02-01'), (None, '2026-02-03')}


def test_saved_file_order_picks_the_body_then_a_named_addressed_source_of_it(tmp_path):
    """A NULL-address unnamed source fetched later never names the saved body when a named one exists."""
    members=[dict(component='xml',source_id='unnamed',body_sha='b'*64,filename='',source_url=None,format='xml',
                  exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='xml',source_id='named',body_sha='b'*64,filename='BILLS-119hr1ih.xml',
                  source_url='https://www.govinfo.gov/content/pkg/BILLS-119hr1ih/xml/BILLS-119hr1ih.xml',format='xml',
                  exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True),
             # Two bodies: the later one wins on order, even though only the earlier one is named.
             dict(component='pdf',source_id='later',body_sha='c'*64,filename='',source_url='https://x.test/a/?a=Files.Serve',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='pdf',source_id='earlier',body_sha='d'*64,filename='a.pdf',source_url='https://x.test/a.pdf',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True)]
    inputs=[json_input(tmp_path,'members',members,component='Utf8',source_id='Utf8',body_sha='Utf8',filename='Utf8',
                       source_url='Utf8',format='Utf8',exact_bytes='Boolean',first_fetched='Utf8',is_real_file='Boolean'),
            json_input(tmp_path,'formats',[dict(id='pdf',kind='preference',value='pdf',rank=1),dict(id='xml',kind='preference',value='xml',rank=3)],
                       id='Utf8',kind='Utf8',value='Utf8',rank='Int32')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='document_members',sql="SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM members"),
               dict(name='saved_files',sql=(ROOT/'model/sql/saved-files.sql').read_text(),materialize=True)],outputs=[],
        queries=[dict(name='saved',sql='SELECT component,source_id,body_sha FROM saved_files WHERE saved_rank=1 ORDER BY component')])
    assert result['saved']==[dict(component='pdf',source_id='later',body_sha='c'*64),
                             dict(component='xml',source_id='named',body_sha='b'*64)]
