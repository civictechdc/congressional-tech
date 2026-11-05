"""Address provenance is one publisher tuple; URL packages precede filename facts."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,list_of,run_job
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


def test_document_package_uses_member_url_order_before_any_copys_filename(tmp_path):
    """ct-vq2a: a newer identical copy saved under a plain name keeps the package an earlier copy's
    GovInfo filename named; URL packages still win when filenames name different bills."""
    saved=[dict(component='document',source_id=s,saved_rank=i,first_fetched=f'2026-10-0{i}T12:00:00Z') for i,s in enumerate(['saved','second','third','fourth'],1)]
    saved+=[dict(component='fallback',source_id='only-filename',saved_rank=1,first_fetched='2026-10-01T12:00:00Z'),
            dict(component='copies',source_id='newer-plain',saved_rank=1,first_fetched='2026-10-20T12:00:00Z'),
            dict(component='copies',source_id='later-named',saved_rank=2,first_fetched='2026-10-15T12:00:00Z'),
            dict(component='copies',source_id='earliest-named',saved_rank=3,first_fetched='2026-10-10T12:00:00Z'),
            dict(component='conflict',source_id='bill-5255',saved_rank=1,first_fetched='2026-10-20T12:00:00Z'),
            dict(component='conflict',source_id='bill-5225',saved_rank=2,first_fetched='2026-10-10T12:00:00Z'),
            dict(component='nonbill',source_id='print',saved_rank=1,first_fetched='2026-10-01T12:00:00Z'),
            dict(component='nonbill',source_id='print-as-bill-1',saved_rank=2,first_fetched='2026-10-10T12:00:00Z'),
            dict(component='nonbill',source_id='print-as-bill-2',saved_rank=3,first_fetched='2026-10-20T12:00:00Z'),
            dict(component='none',source_id='plain',saved_rank=1,first_fetched=None)]
    inputs=[json_input(tmp_path,'saved_inputs',saved,component='Utf8',source_id='Utf8',saved_rank='Int64',first_fetched='Utf8'),
        json_input(tmp_path,'source_annotation_addresses',[
            dict(source_id='saved',package_id='PUBLISHER-PACKAGE',publisher=True),
            dict(source_id='second',package_id='BILLS-119hr3ih',publisher=False),
            dict(source_id='third',package_id='BILLS-119hr2ih',publisher=False)],source_id='Utf8',package_id='Utf8',publisher='Boolean'),
        json_input(tmp_path,'source_annotations',[dict(source_id='saved',package_id='BILLS-119hr1ih'),
            dict(source_id='fourth',package_id='BILLS-119hr4ih'),dict(source_id='only-filename',package_id='FILENAME-ONLY'),
            dict(source_id='newer-plain',package_id=None),dict(source_id='later-named',package_id='BILLS-117hr1833rh'),
            dict(source_id='earliest-named',package_id='BILLS-117hr1833ih'),dict(source_id='plain',package_id=None),
            dict(source_id='bill-5255',package_id='BILLS-118hr5255ih'),dict(source_id='bill-5225',package_id='BILLS-118hr5225ih'),
            dict(source_id='print',package_id='CHRG-119hhrg49353'),dict(source_id='print-as-bill-1',package_id='BILLS-119hr1ih'),
            dict(source_id='print-as-bill-2',package_id='BILLS-119hr2ih')],
            source_id='Utf8',package_id='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='saved_files',sql='SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM saved_inputs'),
               dict(name='document_packages',sql=(ROOT/'model/sql/document-packages.sql').read_text(),materialize=True)],outputs=[],queries=[dict(name='packages',sql='SELECT * FROM document_packages ORDER BY component')])
    assert result['packages']==[
        dict(component='conflict',package_id=None,bill_package_conflict=True),
        dict(component='copies',package_id='BILLS-117hr1833ih',bill_package_conflict=False),
        dict(component='document',package_id='BILLS-119hr3ih',bill_package_conflict=False),
        dict(component='fallback',package_id='FILENAME-ONLY',bill_package_conflict=False),
        dict(component='nonbill',package_id='CHRG-119hhrg49353',bill_package_conflict=False),
        dict(component='none',package_id=None,bill_package_conflict=False),
    ]


def test_hearing_date_corrections_preserve_held_days_and_require_package_evidence(tmp_path):
    # The 49353 cover says June 23, 2022. Its repost's filename says June 7, 2023.
    # The 60403 cover and its own meeting say May 15, despite MODS saying May 14.
    print_package = 'CHRG-117hhrg49353'
    multi_day_package = 'CHRG-117hhrg50139'
    metadata_error = 'CHRG-119hhrg60403'
    cover_68347 = '09bd414d3340e2460f48c6894ebdea0d3ee2420456ec1fde19a2e8f75f59a81f'
    cover_80849 = 'a600af79338071e29eba24fcb61977e89635fc0e6c1de7948013cddb3fe95749'
    cover_82590 = 'dc3e89f2578626fda386ab7fc85ae735dbeee8b69d6b2801b504b7ba7a88bc56'
    documents = [
        ('repost', print_package, '2023-06-07', 'filename'),
        ('multi-day-held-sitting', multi_day_package, '2022-06-13', 'filename'),
        ('multi-day-repost', multi_day_package, '2023-06-07', 'filename'),
        ('undated', print_package, None, None),
        ('other-date-source', print_package, '2023-06-07', 'meeting'),
        ('uncorroborated-mods', metadata_error, '2025-05-15', 'filename'),
        ('68347', 'CHRG-112hhrg68347', '2011-06-22', 'meeting', cover_68347),
        ('80849', 'CHRG-112hhrg80849', '2012-07-25', 'meeting', cover_80849),
        ('82590', 'CHRG-113hhrg82590', '2013-07-10', 'meeting', cover_82590),
        ('different-bytes', 'CHRG-112hhrg80849', '2012-07-25', 'meeting', 'f' * 64),
    ]
    inputs = [
        json_input(tmp_path, 'documents', [
            dict(doc_key=key, package_id=pkg, day=day, document_date_source=source, body_hex=body[0] if body else None)
            for key, pkg, day, source, *body in documents
        ], doc_key='Utf8', package_id='Utf8', day='Utf8', document_date_source='Utf8', body_hex='Utf8'),
        json_input(tmp_path, 'package_mods_facts', [
            dict(package_id=print_package, held_dates=['2022-06-23']),
            dict(package_id=multi_day_package, held_dates=['2021-07-27', '2022-06-13']),
            dict(package_id=metadata_error, held_dates=['2025-05-14']),
            dict(package_id='CHRG-112hhrg68347', held_dates=['2011-09-22']),
            dict(package_id='CHRG-112hhrg80849', held_dates=['2012-06-25']),
            dict(package_id='CHRG-113hhrg82590', held_dates=['2013-05-09']),
        ], package_id='Utf8', held_dates=list_of('Utf8')),
        json_input(tmp_path, 'package_meeting_links', [
            dict(package_id=print_package, event_id=114899),
            dict(package_id=multi_day_package, event_id=114877),
            dict(package_id='CHRG-112hhrg68347', event_id=103921),
        ], package_id='Utf8', event_id='Int64'),
        json_input(tmp_path, 'meetings', [
            dict(event_id=114899, day='2022-06-23', not_held=False),
            dict(event_id=114877, day='2022-06-13', not_held=False),
            dict(event_id=118173, day='2025-05-15', not_held=False),
            dict(event_id=103921, day='2011-09-22', not_held=False),
        ], event_id='Int64', day='Utf8', not_held='Boolean'),
    ]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=[
        dict(name='base_normalized', sql='SELECT * EXCLUDE(day),cast(day AS DATE) AS document_date FROM documents'),
        dict(name='meetings_resolved', sql='SELECT * EXCLUDE(day),cast(day AS DATE) AS meeting_date FROM meetings'),
        dict(name='document_hearing_date_corrections', sql=(ROOT/'model/sql/document-hearing-date-corrections.sql').read_text(), materialize=True),
    ], outputs=[], queries=[
        dict(name='corrections', sql='''SELECT doc_key,cast(document_date AS VARCHAR) AS document_date,document_date_source
             FROM document_hearing_date_corrections ORDER BY doc_key'''),
    ])
    assert result['corrections'] == [
        dict(doc_key='68347', document_date='2011-09-22', document_date_source='meeting'),
        dict(doc_key='80849', document_date='2012-06-25', document_date_source='content'),
        dict(doc_key='82590', document_date='2013-05-09', document_date_source='content'),
        dict(doc_key='multi-day-repost', document_date=None, document_date_source=None),
        dict(doc_key='repost', document_date='2022-06-23', document_date_source='meeting'),
    ]


def test_document_filename_facts_come_from_every_copy_of_the_saved_bytes(tmp_path):
    """ct-vq2a/ct-kwse: identical bytes saved first under a dated HHRG name, then under a plain name,
    keep the HHRG name's date and Congress; a structured name outranks an earlier plain one; bytes posted
    for two meetings date from the first meeting whichever was fetched first; a copy of other bytes in
    the same document never dates it; a plain name alone still dates it. A committee site's
    '<sha256>.hhrg-...' copy outranks a plain name but not the House name (it can carry the day it was
    posted); a date it misreads (the truncated '-2070906', after its capture or outside its Congress)
    never outranks a plausible one."""
    same,other='a'*64,'b'*64
    def copy(component,source,body,rank,fetched,date=None,valid=False,congress=None,name=None):
        return dict(component=component,source_id=source,body_sha=body,saved_rank=rank,first_fetched=fetched,source_url='https://x.test/'+source,
            filename=name or source+'.pdf',filename_date=date,filename_date_valid=valid,congress=congress,congress_valid=valid)
    hashed=lambda tail: '287CDD43'+'0'*56+'.'+tail
    rows=[copy('moved','plain-newer',same,1,'2026-10-20T12:00:00Z','2019-06-23',congress=None),
          copy('moved','hhrg',same,2,'2026-10-10T12:00:00Z','2020-06-25',True,116),
          copy('moved','other-bytes',other,3,'2026-10-01T12:00:00Z','2001-01-01',True,107),
          copy('ranked','plain-earlier',same,2,'2026-10-01T12:00:00Z','2020-01-01',congress=115),
          copy('ranked','structured',same,1,'2026-10-02T12:00:00Z','2020-02-02',True,116),
          copy('plain','only',same,1,'2026-10-02T12:00:00Z','2021-03-03'),
          copy('reused','later-meeting',same,2,'2026-10-01T12:00:00Z','2024-05-15',True,118),
          copy('reused','first-meeting',same,1,'2026-10-09T12:00:00Z','2024-04-16',True,118),
          copy('reused','plain-earliest',same,3,'2026-09-01T12:00:00Z','2023-01-01'),
          copy('undated','bare',same,1,None),
          copy('webster','plain-statement',same,1,'2026-10-01T12:00:00Z','2012-04-23',name='2012 04 23 Webster testimony.pdf'),
          copy('webster','hashed-hhrg',same,2,'2026-10-20T12:00:00Z','2012-04-25',congress=112,name=hashed('hhrg-112-sy21-wstate-websterj-20120425.pdf')),
          copy('bus','hashed-truncated',same,1,'2026-10-01T12:00:00Z','2070-09-06',congress=115,name=hashed('hhrg-115-sy18-wstate-jbus-2070906.pdf')),
          copy('bus','house',same,2,'2026-10-20T12:00:00Z','2017-09-06',True,115,name='HHRG-115-SY18-Wstate-BusJ-20170906.pdf'),
          copy('off-congress','hashed-early',same,1,'2026-10-01T12:00:00Z','2010-09-06',congress=115,name=hashed('hhrg-115-sy18-wstate-jbus-2010906.pdf')),
          copy('off-congress','plain-dated',same,2,'2026-10-20T12:00:00Z','2017-09-06',name='2017 09 06 Bus testimony.pdf'),
          copy('upload-day','hashed-posted',same,1,'2026-10-01T12:00:00Z','2016-09-13',congress=114,name=hashed('hhrg-114-sy-wstate-jturley-20160913.pdf')),
          copy('upload-day','house-hearing',same,2,'2026-10-20T12:00:00Z','2016-09-14',True,114,name='HHRG-114-SY00-Wstate-TurleyP-20160914.pdf'),
          copy('future','hashed-future',same,1,'2026-10-01T12:00:00Z','2070-09-06',name=hashed('hhrg-115-sy18-wstate-jbus-2070906.pdf')),
          copy('future','plain-statement-2017',same,2,'2026-10-20T12:00:00Z','2017-09-06',name='2017 09 06 Bus testimony.pdf')]
    inputs=[json_input(tmp_path,'copies',rows,component='Utf8',source_id='Utf8',body_sha='Utf8',saved_rank='Int64',first_fetched='Utf8',source_url='Utf8',
        filename='Utf8',filename_date='Utf8',filename_date_valid='Boolean',congress='Int64',congress_valid='Boolean')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=[
        dict(name='saved_files',sql='SELECT component,source_id,body_sha,saved_rank,source_url,filename,cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM copies'),
        dict(name='source_filename_readings',sql="""SELECT source_id,filename AS filename_date_name,filename AS congress_name,
            cast(filename_date AS DATE) AS filename_date,filename_date_valid,true AS filename_date_eligible,
            CASE WHEN filename_date IS NULL THEN 'missing' ELSE 'completed' END AS filename_date_status,
            congress,congress_valid,CASE WHEN congress IS NULL THEN 'missing' ELSE 'completed' END AS congress_status FROM copies"""),
        dict(name='document_filename_facts',sql=(ROOT/'model/sql/document-filename-facts.sql').read_text(),materialize=True)],outputs=[],
        queries=[dict(name='facts',sql='SELECT component,cast(filename_date AS VARCHAR) AS filename_date,congress FROM document_filename_facts ORDER BY component')])
    assert result['facts']==[dict(component='bus',filename_date='2017-09-06',congress=115),dict(component='future',filename_date='2017-09-06',congress=None),
                             dict(component='moved',filename_date='2020-06-25',congress=116),dict(component='off-congress',filename_date='2017-09-06',congress=115),
                             dict(component='plain',filename_date='2021-03-03',congress=None),
                             dict(component='ranked',filename_date='2020-02-02',congress=116),dict(component='reused',filename_date='2024-04-16',congress=118),
                             dict(component='undated',filename_date=None,congress=None),dict(component='upload-day',filename_date='2016-09-14',congress=114),
                             dict(component='webster',filename_date='2012-04-25',congress=112)]


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


def test_saved_file_order_picks_the_body_then_a_named_source_of_it(tmp_path):
    """A NULL-address unnamed source fetched later never names the saved body when a named one exists;
    a named ZIP member (no address of its own) keeps its place as a first-class copy."""
    members=[dict(component='xml',source_id='unnamed',body_sha='b'*64,filename='',source_url=None,format='xml',
                  exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='xml',source_id='named',body_sha='b'*64,filename='BILLS-119hr1ih.xml',
                  source_url='https://www.govinfo.gov/content/pkg/BILLS-119hr1ih/xml/BILLS-119hr1ih.xml',format='xml',
                  exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True),
             # Two bodies: the later one wins on order, even though only the earlier one is named.
             dict(component='pdf',source_id='later',body_sha='c'*64,filename='',source_url='https://x.test/a/?a=Files.Serve',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='pdf',source_id='earlier',body_sha='d'*64,filename='a.pdf',source_url='https://x.test/a.pdf',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True),
             # Rows of other bodies keep saved-file order, named or not.
             dict(component='pdf',source_id='third',body_sha='f'*64,filename='',source_url='https://x.test/b/?a=Files.Serve',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-22T12:00:00Z',is_real_file=True),
             dict(component='pdf',source_id='fourth',body_sha='0'*64,filename='c.pdf',source_url='https://x.test/c.pdf',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-21T12:00:00Z',is_real_file=True),
             dict(component='zip',source_id='member',body_sha='e'*64,filename='CHRG-1.pdf',source_url=None,
                  format='pdf',exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='zip',source_id='copy',body_sha='e'*64,filename='CHRG-1-copy.pdf',source_url='https://www.congress.gov/x/CHRG-1-copy.pdf',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True),
             # A source with neither an address nor a member path never names the saved body over an addressed one.
             dict(component='ctx',source_id='addressless',body_sha='9'*64,filename='P.pdf',source_url=None,
                  format='pdf',exact_bytes=True,first_fetched='2026-10-25T12:00:00Z',is_real_file=True),
             dict(component='ctx',source_id='addressed',body_sha='9'*64,filename='P.pdf',source_url='https://www.govinfo.gov/content/pkg/P/pdf/P.pdf',
                  format='pdf',exact_bytes=True,first_fetched='2026-10-20T12:00:00Z',is_real_file=True)]
    for row in members: row['archive_member']=row['source_id']=='member'
    inputs=[json_input(tmp_path,'members',members,component='Utf8',source_id='Utf8',body_sha='Utf8',filename='Utf8',
                       source_url='Utf8',format='Utf8',exact_bytes='Boolean',first_fetched='Utf8',is_real_file='Boolean',archive_member='Boolean'),
            json_input(tmp_path,'formats',[dict(id='pdf',kind='preference',value='pdf',rank=1),dict(id='xml',kind='preference',value='xml',rank=3)],
                       id='Utf8',kind='Utf8',value='Utf8',rank='Int32')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='document_members',sql="SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM members"),
               dict(name='saved_files',sql=(ROOT/'model/sql/saved-files.sql').read_text(),materialize=True)],outputs=[],
        queries=[dict(name='saved',sql='SELECT component,source_id,body_sha FROM saved_files WHERE saved_rank=1 ORDER BY component')])
    assert result['saved']==[dict(component='ctx',source_id='addressed',body_sha='9'*64),
                             dict(component='pdf',source_id='later',body_sha='c'*64),
                             dict(component='xml',source_id='named',body_sha='b'*64),
                             dict(component='zip',source_id='member',body_sha='e'*64)]
    order=run_job(tmp_path/'order',NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='document_members',sql="SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM members"),
               dict(name='saved_files',sql=(ROOT/'model/sql/saved-files.sql').read_text(),materialize=True)],outputs=[],
        queries=[dict(name='o',sql="SELECT source_id FROM saved_files WHERE component='pdf' ORDER BY saved_rank")])['o']
    assert [row['source_id'] for row in order]==['later','third','fourth','earlier']


def test_recovery_only_document_takes_the_recovered_reading_title_else_the_original_label(tmp_path):
    """068f2a40 hard-coded NULL; DM 7.5 gives a recovery-only row a title like any other."""
    from congress_api.retention.provenance import list_of, struct
    strings = list_of('Utf8')
    recoveries = [dict(component=c, saved_rank=1, id=c, body_sha=b, original_url=f'https://x.test/{c}.pdf', bytes=10,
                       imported_at='2026-10-01T00:00:00Z') for c, b in [('read', 'a' * 64), ('label', 'b' * 64)]]
    annotation = dict(document_kind=[], document_family=[], committee_keys=[], chambers=[], congress=None, filename_date=None,
                      meeting_keys=[], measure_keys=[], bioguide_ids=[], package_id=None, facts=[])
    from viewer_publication.archive_model import registry_inputs
    inputs = registry_inputs(tmp_path / 'registries') + [json_input(tmp_path, 'saved_recoveries', recoveries, component='Utf8', saved_rank='Int64', id='Utf8', body_sha='Utf8',
                         original_url='Utf8', bytes='Int64', imported_at='Utf8')] + [
        json_input(tmp_path, 'document_identities', [dict(component=c, document_id='doc:' + c, has_real=False) for c in ('read', 'label')],
                   component='Utf8', document_id='Utf8', has_real='Boolean'),
        json_input(tmp_path, 'effective_filenames', [dict(input_id='recovery:' + c, filename=c + '.pdf') for c in ('read', 'label')],
                   input_id='Utf8', filename='Utf8'),
        json_input(tmp_path, 'source_files', [dict(source_id='s:' + c, body_sha=None, source_url=f'https://x.test/{c}.pdf', filename=c + '.pdf')
                   for c in ('read', 'label')], source_id='Utf8', body_sha='Utf8', source_url='Utf8', filename='Utf8'),
        json_input(tmp_path, 'source_annotations', [dict(annotation, source_id='s:read', title='Original label'),
                   dict(annotation, source_id='s:label', title='Hearing on Rural Lands')], source_id='Utf8', title='Utf8',
                   document_kind=strings, document_family=strings, committee_keys=strings, chambers=strings, congress='Int32',
                   filename_date='Utf8', meeting_keys=strings, measure_keys=strings, bioguide_ids=strings, package_id='Utf8',
                   facts=list_of(struct(field='Utf8', value='Utf8'))),
        json_input(tmp_path, 'evidence', [dict(body_sha=b, format='html', suffix='') for b in ('a' * 64, 'b' * 64)],
                   body_sha='Utf8', format='Utf8', suffix='Utf8'),
        json_input(tmp_path, 'pages', [dict(body_hex='a' * 64, status='completed', title='Recovered hearing record', heading=None),
                                       dict(body_hex='b' * 64, status='completed', title='Untitled', heading=None)],
                   body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8'),
        json_input(tmp_path, 'capture_rows', [dict(body_hex='a' * 64, media_type='text/html')], body_hex='Utf8', media_type='Utf8'),
        json_input(tmp_path, 'component_meeting_links', [], component='Utf8', meeting_date='Utf8', meeting_keys=strings, committee_keys=strings, chambers=strings, congress='Int16'),
        json_input(tmp_path, 'document_witness_keys', [], component='Utf8', witness_keys=strings, witness_name='Utf8')]
    steps = [dict(name='body_evidence', sql='SELECT * FROM evidence'),
             dict(name='page_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,status,title,heading,cast(NULL AS DATE) AS content_date FROM pages"),
             dict(name='source_annotation_pages', sql=(ROOT / 'model/sql/source-annotations-pages.sql').read_text()),
             dict(name='captures', sql="SELECT decode(body_hex,'hex') AS sha256,media_type FROM capture_rows"),
             dict(name='recovery_rows', sql=(ROOT / 'model/sql/document-recovery-normalized.sql').read_text())]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='titles', sql='SELECT doc_key,title,media_type FROM recovery_rows ORDER BY doc_key')])
    assert result['titles'] == [dict(doc_key='doc:label', title='Hearing on Rural Lands', media_type='application/octet-stream'),
                                dict(doc_key='doc:read', title='Recovered hearing record', media_type='text/html')]


def test_a_blank_filename_needs_a_recorded_reason(tmp_path):
    """green-g/red-g: the reason reads every capture of the saved body and the published address."""
    from viewer_publication.archive_model import BLANK_FILENAMES_SQL
    fs = 'https://www.epw.senate.gov/public/?a=Files.Serve&File_id=1'
    docs = [dict(doc_key='files-serve', body_hex='a', source_url=fs, filename=''),
            dict(doc_key='final-url-named', body_hex='b', source_url=fs, filename=''),
            dict(doc_key='context-only', body_hex='c', source_url=None, filename=''),
            dict(doc_key='no-address', body_hex='d', source_url=None, filename=''),
            dict(doc_key='host', body_hex='e', source_url='https://docs.house.gov/', filename=''),
            dict(doc_key='plain-path', body_hex='f', source_url='https://x.test/a/b', filename=''),
            dict(doc_key='named', body_hex='g', source_url='https://x.test/a.pdf', filename='a.pdf')]
    captures = [dict(body_sha='a', url=fs, context_url=fs, filename=''),
                dict(body_sha='b', url=fs, context_url=fs, filename=''),
                dict(body_sha='b', url='https://www.epw.senate.gov/public/_cache/files/x/euler-testimony.pdf', context_url=fs, filename='euler-testimony.pdf'),
                dict(body_sha='c', url=None, context_url='https://www.govinfo.gov/content/pkg/P/pdf/P.pdf', filename='')]
    inputs = [json_input(tmp_path, 'ordered', docs, doc_key='Utf8', body_hex='Utf8', source_url='Utf8', filename='Utf8'),
              json_input(tmp_path, 'capture_sources', captures, body_sha='Utf8', url='Utf8', context_url='Utf8', filename='Utf8')]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=[], outputs=[],
        queries=[dict(name='r', sql=f'SELECT doc_key,reason FROM ({BLANK_FILENAMES_SQL}) r ORDER BY doc_key')])
    assert {row['doc_key']: row['reason'] for row in result['r']} == {
        'files-serve': 'query_names_no_file', 'final-url-named': None, 'context-only': None,
        'no-address': 'no_address', 'host': 'host_only', 'plain-path': None}


def test_the_generic_title_check_is_its_own_rule(tmp_path):
    """Independent of the page-signals link_word list: only format, size and download words."""
    from viewer_publication.archive_model import GENERIC_TITLE_SQL
    titles = ['PDF (48.1 MB)', 'Download XML (6KB)', 'ZIP', 'click here', 'Overview of the Hearing',
              'Testimony of Jane Doe (PDF, 2 MB)', '2024', None]
    inputs = [json_input(tmp_path, 'ordered', [dict(i=i, title=t) for i, t in enumerate(titles)], i='Int64', title='Utf8')]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=[], outputs=[],
        queries=[dict(name='g', sql=f'SELECT i,coalesce({GENERIC_TITLE_SQL},false) AS generic FROM ordered o ORDER BY i')])
    assert [row['generic'] for row in result['g']] == [True, True, True, True, False, False, False, False]


def test_a_title_generic_by_either_rule_refuses(tmp_path):
    """red-g2: the gate counts a registry link word OR the independent vocabulary rule."""
    from viewer_publication.archive_model import GENERIC_TITLES_SQL, registry_inputs
    titles = ['Untitled', 'Read more', 'Document', 'Attachment', 'Email', 'Text', 'PDF (48.1 MB)', 'Download XML (6KB)',
              'Printable PDF of this Document', 'Download Report', 'Exhibit A', 'Appendix D', 'Version 2', 'File 7', None]
    inputs = registry_inputs(tmp_path / 'registries') + [json_input(tmp_path, 'ordered', [dict(doc_key=str(i), title=t)
        for i, t in enumerate(titles)], doc_key='Utf8', title='Utf8')]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=[], outputs=[],
        queries=[dict(name='g', sql=f'SELECT title FROM ({GENERIC_TITLES_SQL}) g ORDER BY title')])
    assert sorted(row['title'] for row in result['g']) == sorted(titles[:10])


def test_the_generic_title_gate_checks_the_titles_the_link_word_rule_keeps(tmp_path):
    """A page title longer than the rule's bound is a title, for the rule and the gate alike.

    Raw (body e5abc9c8…, aging.senate.gov): the Aging Committee's 2022-07-28 hearing is named
    'Click Here: Accessible Federal Technology for People with Disabilities, Older Americans,
    and Veterans'; its <title> is the 71-character truncation below. The rule reads link words
    in titles of at most 64 characters, the gate read 96 (bbf7dbd5), so the release refused a
    title the rule had kept.
    """
    from viewer_publication.archive_model import GENERIC_TITLES_SQL, registry_inputs
    aging = 'Click Here: Accessible Federal Technolog... | Senate Committee On Aging'
    pages = [dict(body_hex=f'{i:064x}', status='completed', title=t, heading=None)
             for i, t in enumerate([aging, 'Click here', 'Download testimony'])]
    inputs = registry_inputs(tmp_path / 'registries') + [json_input(tmp_path, 'pages', pages,
        body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8')]
    steps = [dict(name='page_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,status,title,heading,cast(NULL AS DATE) AS content_date FROM pages"),
             dict(name='source_annotation_pages', sql=(ROOT / 'model/sql/source-annotations-pages.sql').read_text()),
             dict(name='ordered', sql="SELECT encode(body_sha,'hex') AS doc_key,title FROM source_annotation_pages")]
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='kept', sql='SELECT title FROM ordered WHERE title IS NOT NULL'),
                 dict(name='generic', sql=f'SELECT title FROM ({GENERIC_TITLES_SQL}) g')])
    assert [row['title'] for row in result['kept']] == [aging]
    assert result['generic'] == []
