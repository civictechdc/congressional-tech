"""Per-source metadata comes from pinned typed readings and attributed links."""
from datetime import date
import os

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import filenames
from congress_api.retention.provenance import json_input,list_of,run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import registry_inputs


def test_source_annotations_keep_pins_names_keys_and_publisher_priority(tmp_path):
    from viewer_publication.archive_annotations import annotation_steps
    urls=['https://docs.house.gov/meetings/AG/AG03/20261020/HHRG00123/a.pdf',
          'https://www.govinfo.gov/content/pkg/CHRG-119hhrg55555/html/report.htm',None,
          'https://www.congress.gov/119/meeting/senate/777/dead.pdf']
    sources=[dict(source_id='s'+str(i+1),filename=name,source_url=url,body_sha=body)
        for i,(name,url,body) in enumerate(zip(['a.pdf','b.html','c.pdf','dead.pdf'],urls,['a'*64,'b'*64,'d'*64,None]))]
    rows=[]
    for source in sources:
        row=filenames._reading(source['filename'],source['source_url'],'current')
        if source['source_id']=='s1':
            row.update(document_kind=['committee-report'],document_family=['hearings'],committee_code=['AG03','UNKNOWN'],
                congress=119,filename_date=date(2026,10,20),measure_keys=['119-hr-7'],bioguide_ids=['A000001'],
                package_id='CHRG-119hhrg11111',fields=[dict(field='document_kind',value='committee-report'),
                    dict(field='private_field',value='not public'),dict(field='date_token_candidates',value='20261020'),dict(field='congress',value='119'),
                    dict(field='congress',value='119')])
        rows.append(row)
    rows.append(dict(rows[0],catalog_version='old',document_kind=['wrong-old-kind']))
    filename_path=tmp_path/'filename-readings.parquet'
    pq.write_table(pa.Table.from_pylist(rows,schema=filenames.SCHEMA),filename_path)
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(dict(name='filename_readings',kind='parquet',path=str(filename_path)))
    inputs.append(json_input(tmp_path,'source_files',sources,source_id='Utf8',filename='Utf8',source_url='Utf8',body_sha='Utf8'))
    captures=[dict(source_id=s['source_id'],body_sha=s['body_sha'],context_url=s['source_url'],member_path=None) for s in sources if s['source_url']]
    captures += [dict(source_id='s3',body_sha='d'*64,context_url='https://docs.house.gov/meetings/AG/AG03/20261020/HMKP456/package.zip',member_path='folder/c.pdf'),
                 dict(source_id='mods',body_sha='c'*64,context_url='https://www.govinfo.gov/content/pkg/CHRG-119hhrg55555/mods.xml',member_path=None)]
    inputs.append(json_input(tmp_path,'capture_sources',captures,source_id='Utf8',body_sha='Utf8',context_url='Utf8',member_path='Utf8'))
    pages=[dict(body_hex='a'*64,status='completed',title='Reading title',heading='Heading A',content_date='2026-10-18',named_meetings=[]),
           dict(body_hex='b'*64,status='completed',title='',heading='Heading B',content_date='2026-10-19',named_meetings=[]),
           dict(body_hex='c'*64,status='completed',title='Metadata',heading=None,content_date=None,named_meetings=[999])]
    inputs.append(json_input(tmp_path,'page_inputs',pages,body_hex='Utf8',status='Utf8',title='Utf8',heading='Utf8',content_date='Utf8',named_meetings=list_of('Int64')))
    links=[dict(source_id='s1',doc_type='br',text='Hearing transcript',page_body='page',context='https://publisher.test/index',first_good_at='2026-10-21T12:00:00Z',link_index=0,split_position=0),
           dict(source_id='s2',doc_type='br',text='Hearing transcript',page_body='page',context='https://publisher.test/index',first_good_at='2026-10-21T12:00:00Z',link_index=1,split_position=0),
           dict(source_id='s3',doc_type=None,text='Hearing transcript',page_body='page',context='https://www.congress.gov/119/meeting/house/888',first_good_at='2026-10-21T12:00:00Z',link_index=2,split_position=0),
           dict(source_id='s3',doc_type=None,text='Later label',page_body='other',context='https://publisher.test/later',first_good_at='2026-10-22T12:00:00Z',link_index=0,split_position=0)]
    for row in links:row['context_url']=row['context'];row['context']='endpoint:'+row['context']
    inputs.append(json_input(tmp_path,'publisher_links',links,source_id='Utf8',doc_type='Utf8',text='Utf8',page_body='Utf8',context='Utf8',context_url='Utf8',first_good_at='Utf8',link_index='Int64',split_position='Int64'))
    steps=[dict(name='capture_source_contexts',sql='SELECT * FROM capture_sources'),dict(name='page_facts',sql="SELECT decode(body_hex,'hex') AS body_sha,* EXCLUDE(body_hex),cast(content_date AS DATE) AS day FROM page_inputs")]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+annotation_steps('current'),outputs=[],queries=[
            dict(name='sources',sql='SELECT source_id,document_kind,document_family,congress,package_id,cast(filename_date AS VARCHAR) AS filename_date,cast(content_date AS VARCHAR) AS content_date,title,meeting_keys,measure_keys,bioguide_ids,committee_keys,chambers,facts FROM source_annotations ORDER BY source_id'),
            dict(name='unmapped',sql='SELECT code,count(*) AS n FROM source_annotation_unmapped_committees GROUP BY code ORDER BY code')])
    one,two,three,four=result['sources']
    assert one==dict(source_id='s1',document_kind=['committee-report'],document_family=['hearings'],congress=119,
        package_id='CHRG-119hhrg11111',filename_date='2026-10-20',content_date='2026-10-18',title='Reading title',
        meeting_keys=['123'],measure_keys=['119-hr-7'],bioguide_ids=['A000001'],committee_keys=['hsag03'],chambers=['house'],
        facts=[dict(field='congress',value='119'),dict(field='date_token_candidates',value='2026-10-20'),dict(field='document_kind',value='committee-report')])
    assert two['document_kind']==['legislative-text'] and two['title']=='Heading B'
    assert two['package_id']=='CHRG-119hhrg55555' and two['meeting_keys']==['999']
    assert three['document_kind']==['transcript'] and three['title']=='Hearing transcript'
    assert three['meeting_keys']==['456','888'] and three['chambers']==['house']
    assert four['meeting_keys']==['777'] and four['chambers']==['senate']
    assert four['document_kind']==[] and four['facts']==[]
    assert result['unmapped']==[dict(code='UNKNOWN',n=1)]
