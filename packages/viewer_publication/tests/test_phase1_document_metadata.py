"""Address provenance is one publisher tuple; URL packages precede filename facts."""
import os
from pathlib import Path

from congress_api.retention.provenance import json_input,list_of,run_job,struct
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
    from viewer_publication.archive_model import registry_inputs

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
    # The reviewed GPO print states the Congress and bill number on page 1
    # and HR 2899 IH in the footer of page 2. Other bytes must not inherit it.
    reviewed_sha = '1a9cae0e1043a2a2af6a4f7b187f15ef4cf64d796a23448b26b82a52989e4ed2'
    saved += [
        dict(component=component, source_id=f'{component}-pdf', saved_rank=1, format='pdf', body_sha=reviewed_sha)
        for component in ('reviewed', 'house-senate-collision', 'authoritative')
    ]
    saved += [
        dict(component='pre-introduction', source_id='draft-pdf', saved_rank=1, format='pdf',
             body_sha='59282bb7d29d214e2f562a6f38ca0b1f901d07a51806bfe01ea88991f7b4e2e1'),
        dict(component='different-bytes', source_id='different-2899', saved_rank=1, format='pdf',
             body_sha='f' + reviewed_sha[1:]),
        # The edition hold is explicit: a later package address needs a fresh
        # reviewed edition decision, while ordinary positive evidence retains
        # the existing authority precedence above.
        dict(component='withheld-authoritative', source_id='withheld-pdf', saved_rank=1, format='pdf',
             body_sha='f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee',
             source_url='https://www.congress.gov/118/meeting/house/115732/documents/BILLS-118HR4775ih.pdf'),
    ]
    inputs=registry_inputs(tmp_path/'registries')+[
        json_input(tmp_path,'saved_inputs',saved,component='Utf8',source_id='Utf8',saved_rank='Int64',
                   first_fetched='Utf8',format='Utf8',body_sha='Utf8',source_url='Utf8'),
        json_input(tmp_path,'source_annotation_addresses',[
            dict(source_id='saved',package_id='PUBLISHER-PACKAGE',publisher=True),
            dict(source_id='second',package_id='BILLS-119hr3ih',publisher=False),
            dict(source_id='third',package_id='BILLS-119hr2ih',publisher=False),
            dict(source_id='authoritative-pdf',package_id='BILLS-116s2899is',publisher=False),
            dict(source_id='withheld-pdf',package_id='BILLS-118hr4755ih',publisher=False)],
            source_id='Utf8',package_id='Utf8',publisher='Boolean'),
        json_input(tmp_path,'source_annotations',[dict(source_id='saved',package_id='BILLS-119hr1ih'),
            dict(source_id='fourth',package_id='BILLS-119hr4ih'),dict(source_id='only-filename',package_id='FILENAME-ONLY'),
            dict(source_id='newer-plain',package_id=None),dict(source_id='later-named',package_id='BILLS-117hr1833rh'),
            dict(source_id='earliest-named',package_id='BILLS-117hr1833ih'),dict(source_id='plain',package_id=None),
            dict(source_id='bill-5255',package_id='BILLS-118hr5255ih'),dict(source_id='bill-5225',package_id='BILLS-118hr5225ih'),
            dict(source_id='house-senate-collision-pdf',package_id='BILLS-116s2899is'),
            dict(source_id='print',package_id='CHRG-119hhrg49353'),dict(source_id='print-as-bill-1',package_id='BILLS-119hr1ih'),
            dict(source_id='print-as-bill-2',package_id='BILLS-119hr2ih')],
            source_id='Utf8',package_id='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=[dict(name='saved_files',sql='SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM saved_inputs'),
               dict(name='document_bill_decisions',sql=(ROOT/'model/sql/document-bill-decisions.sql').read_text(),materialize=True),
               dict(name='document_packages',sql=(ROOT/'model/sql/document-packages.sql').read_text(),materialize=True)],outputs=[],queries=[dict(name='packages',sql='SELECT * FROM document_packages ORDER BY component')])
    assert result['packages']==[
        dict(component='authoritative',package_id='BILLS-116s2899is',bill_package_conflict=False),
        dict(component='conflict',package_id=None,bill_package_conflict=True),
        dict(component='copies',package_id='BILLS-117hr1833ih',bill_package_conflict=False),
        dict(component='different-bytes',package_id=None,bill_package_conflict=False),
        dict(component='document',package_id='BILLS-119hr3ih',bill_package_conflict=False),
        dict(component='fallback',package_id='FILENAME-ONLY',bill_package_conflict=False),
        dict(component='house-senate-collision',package_id=None,bill_package_conflict=True),
        dict(component='nonbill',package_id='CHRG-119hhrg49353',bill_package_conflict=False),
        dict(component='none',package_id=None,bill_package_conflict=False),
        dict(component='pre-introduction',package_id=None,bill_package_conflict=False),
        dict(component='reviewed',package_id='BILLS-116hr2899ih',bill_package_conflict=False),
        dict(component='withheld-authoritative',package_id=None,bill_package_conflict=False),
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


def _saved_file_steps():
    """Fixture members as document_members, then the name standing and the saved-file order as the model runs them."""
    return [dict(name='document_members',sql="SELECT * EXCLUDE(first_fetched),cast(first_fetched AS TIMESTAMP WITH TIME ZONE) AS first_fetched FROM members"),
            dict(name='saved_name_standing',sql=(ROOT/'model/sql/saved-name-standing.sql').read_text(),materialize=True),
            dict(name='saved_files',sql=(ROOT/'model/sql/saved-files.sql').read_text(),materialize=True)]


def _name_readings(tmp_path,members,said=None):
    """What each member's name says: `said` maps a source to (official, families); every other name is plain and silent."""
    said=said or {}
    return json_input(tmp_path,'source_filename_readings',[dict(source_id=row['source_id'],valid=said.get(row['source_id'],(False,[]))[0],
        document_family_status='completed',document_family=said.get(row['source_id'],(False,[]))[1]) for row in members],
        source_id='Utf8',valid='Boolean',document_family_status='Utf8',document_family=list_of('Utf8'))


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
    for row in members: row.update(archive_member=row['source_id']=='member',body_stored=True)
    inputs=[json_input(tmp_path,'members',members,component='Utf8',source_id='Utf8',body_sha='Utf8',filename='Utf8',
                       source_url='Utf8',format='Utf8',exact_bytes='Boolean',first_fetched='Utf8',is_real_file='Boolean',archive_member='Boolean',
                       body_stored='Boolean'),
            json_input(tmp_path,'formats',[dict(id='pdf',kind='preference',value='pdf',rank=1),dict(id='xml',kind='preference',value='xml',rank=3)],
                       id='Utf8',kind='Utf8',value='Utf8',rank='Int32'),
            _name_readings(tmp_path,members)]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=_saved_file_steps(),outputs=[],
        queries=[dict(name='saved',sql='SELECT component,source_id,body_sha FROM saved_files WHERE saved_rank=1 ORDER BY component')])
    assert result['saved']==[dict(component='ctx',source_id='addressed',body_sha='9'*64),
                             dict(component='pdf',source_id='later',body_sha='c'*64),
                             dict(component='xml',source_id='named',body_sha='b'*64),
                             dict(component='zip',source_id='member',body_sha='e'*64)]
    order=run_job(tmp_path/'order',NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=_saved_file_steps(),outputs=[],
        queries=[dict(name='o',sql="SELECT source_id FROM saved_files WHERE component='pdf' ORDER BY saved_rank")])['o']
    assert [row['source_id'] for row in order]==['later','third','fourth','earlier']


def test_a_later_capture_of_held_bytes_never_names_the_saved_body(tmp_path):
    """ct-f7hp: a source file whose captures only found the archive already holding its bytes
    (body_stored false; the 2026-11-08 run fetched 621 documents' bytes again at a mirror address) comes
    after one that stored them, so the document keeps its name and what that name says. Naming and
    the address still come first, the body never moves, and copies that each stored the bytes keep
    saved-file order."""
    official='https://docs.house.gov/meetings/ED/ED10/20250520/118261/HHRG-119-ED10-Wstate-PalagashviliL-20250520.pdf'
    mirror='https://democrats-edworkforce.house.gov/imo/media/doc/'
    def member(component,source_id,body,filename,url,fetched,stored):
        return dict(component=component,source_id=source_id,body_sha=body*64,filename=filename,source_url=url,format='pdf',
                    exact_bytes=True,first_fetched=fetched,is_real_file=True,archive_member=False,body_stored=stored)
    early,late='2026-10-01T12:00:00Z','2026-11-08T18:00:00Z'
    members=[
        # An official name fetched first; the same bytes found again later under a generic name.
        member('kept','official','a','HHRG-119-ED10-Wstate-PalagashviliL-20250520.pdf',official,early,True),
        member('kept','generic','a','testimony7.pdf',mirror+'testimony7.pdf',late,False),
        # The only named copy is the later one: a name still comes before who stored the bytes.
        member('named','unnamed','b','','https://edworkforce.house.gov/download/?id=B6029D49',early,True),
        member('named','later-name','b','akers_written_testimony.pdf',mirror+'akers_written_testimony.pdf',late,False),
        # A recovery-only document captured live at its original address: its one file leads.
        member('live','original','c','opening_statement11.pdf',mirror+'opening_statement11.pdf',late,False),
        # A stored copy with neither an address nor a member path never blanks the published address.
        member('address','addressless','d','P.pdf',None,early,True),
        member('address','addressed','d','P.pdf',mirror+'P.pdf',late,False),
        # The saved body is still the newest fetch, whoever stored what.
        member('body','old-body','e','old.pdf','https://x.test/old.pdf',early,True),
        member('body','new-body','f','new.pdf','https://x.test/new.pdf',late,False),
        # Copies that each stored the bytes (every fetch before 2026-10-30 says so) keep saved-file order.
        member('both','first','9','first.pdf','https://x.test/first.pdf',early,True),
        member('both','second','9','second.pdf','https://x.test/second.pdf','2026-10-12T12:00:00Z',True)]
    said=dict(official=(['witness-statement'],['statement'],[dict(field='Witness',value='PalagashviliL')]),
              generic=(['testimony'],['statement'],[]))
    annotations=[dict(source_id=row['source_id'],document_kind=said.get(row['source_id'],([],[],[]))[0],
                      document_family=said.get(row['source_id'],([],[],[]))[1],facts=said.get(row['source_id'],([],[],[]))[2]) for row in members]
    strings=list_of('Utf8')
    inputs=[json_input(tmp_path,'members',members,component='Utf8',source_id='Utf8',body_sha='Utf8',filename='Utf8',
                       source_url='Utf8',format='Utf8',exact_bytes='Boolean',first_fetched='Utf8',is_real_file='Boolean',
                       archive_member='Boolean',body_stored='Boolean'),
            json_input(tmp_path,'source_annotations',annotations,source_id='Utf8',document_kind=strings,document_family=strings,
                       facts=list_of(struct(field='Utf8',value='Utf8'))),
            json_input(tmp_path,'formats',[dict(id='pdf',kind='preference',value='pdf',rank=1)],id='Utf8',kind='Utf8',value='Utf8',rank='Int32'),
            _name_readings(tmp_path,members,dict(official=(True,['statement']),generic=(False,['statement'])))]
    # The document row reads its name from the leading source file and its kind, family and facts from
    # that file's annotation (document-normalized.sql joins the same two keys).
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=_saved_file_steps(),outputs=[],
        queries=[dict(name='lead',sql="""SELECT s.component,s.source_id,s.body_sha,s.filename,s.source_url,a.document_kind,a.document_family,a.facts
                      FROM saved_files s JOIN source_annotations a ON s.source_id=a.source_id WHERE s.saved_rank=1 ORDER BY s.component"""),
                 dict(name='columns',sql="SELECT * FROM saved_files LIMIT 1")])
    lead={row['component']:row for row in result['lead']}
    assert {c:row['source_id'] for c,row in lead.items()}==dict(kept='official',named='later-name',live='original',
        address='addressed',body='new-body',both='second')
    assert (lead['kept']['filename'],lead['kept']['document_kind'],lead['kept']['document_family'],lead['kept']['facts'])==(
        'HHRG-119-ED10-Wstate-PalagashviliL-20250520.pdf',['witness-statement'],['statement'],[dict(field='Witness',value='PalagashviliL')])
    assert lead['body']['body_sha']=='f'*64
    assert all(row['source_url'] for row in lead.values())
    # The flag orders rows here and goes no further: saved_files keeps its columns.
    assert 'body_stored' not in result['columns'][0] and 'name_standing' not in result['columns'][0]


def test_an_official_name_leads_unless_a_committee_name_contradicts_it(tmp_path):
    """ct-h8dr, ct-yuf0: a document takes its official House or GovInfo name whenever a copy of its saved
    bytes has one, whichever copy was fetched last or stored the bytes; but when a committee's own name
    for the same bytes states a kind and no committee name states the official name's, the committee
    name leads when the official one is a House meeting-document slot (the House repository filed 54
    testimonies under Bio and support-document names, one under another witness's surname). A
    contradicted official name of another kind stays where saved-file order puts it. The saved body
    never moves, a body with no official name keeps saved-file order, and every document whose names
    state different kinds is counted."""
    house='https://docs.house.gov/meetings/XX/XX00/20200311/110712/'
    congress='https://www.congress.gov/116/meeting/house/110712/witnesses/'
    site='https://democrats-homeland.house.gov/imo/media/doc/'
    early,middle,late='2026-10-01T12:00:00Z','2026-10-12T12:00:00Z','2026-10-31T00:11:00Z'
    said,members={},[]
    def member(component,source_id,body,filename,url,fetched,stored,official,families):
        members.append(dict(component=component,source_id=source_id,body_sha=body*64,filename=filename,source_url=url,format='pdf',
            exact_bytes=True,first_fetched=fetched,is_real_file=True,archive_member=False,body_stored=stored))
        said[source_id]=(official,families)
    # A testimony filed under a House Bio name: the committee's name and kind stay, though the House copy stored the bytes.
    member('bio-slot','knox-house','1','HHRG-117-II13-Bio-KnoxJ-20211026.pdf',house+'HHRG-117-II13-Bio-KnoxJ-20211026.pdf',early,True,True,['biography'])
    member('bio-slot','knox-site','1','Knox Testimony - WOW Ov Hrg 10.26.21.pdf',site+'Knox%20Testimony.pdf',late,False,False,['statement'])
    # Bryan's testimony under Hentz's Bio name, at both official addresses.
    member('bryan','hentz-house','2','HHRG-116-HM08-Bio-HentzA-20200311.pdf',house+'HHRG-116-HM08-Bio-HentzA-20200311.pdf',early,True,True,['biography'])
    member('bryan','hentz-congress','2','HHRG-116-HM08-Bio-HentzA-20200311.pdf',congress+'HHRG-116-HM08-Bio-HentzA-20200311.pdf',middle,True,True,['biography'])
    member('bryan','bryan-site','2','Testimony - Bryan.pdf',site+'Testimony%20-%20Bryan.pdf',late,False,False,['statement'])
    # A real biography: the committee's name agrees, so the House name leads the newer committee copy.
    member('real-bio','hayden-house','3','HHRG-118-HA00-Bio-HaydenC-20240710.pdf',house+'HHRG-118-HA00-Bio-HaydenC-20240710.pdf',early,True,True,['biography'])
    member('real-bio','hayden-site','3','Bio_Dr.Carla Hayden.pdf',site+'Bio_Dr.Carla%20Hayden.pdf',middle,True,False,['biography'])
    # Plain names beside a correct House name, one agreeing and one silent: the House name leads both.
    member('plain','kessler-house','4','HHRG-119-ED10-Wstate-KesslerG-20260224.pdf',house+'HHRG-119-ED10-Wstate-KesslerG-20260224.pdf',early,True,True,['statement'])
    member('plain','kessler-agrees','4','download_testimony95.pdf',site+'download_testimony95.pdf',middle,True,False,['statement'])
    member('plain','kessler-silent','4','kessler.pdf',site+'kessler.pdf',late,True,False,[])
    # A House support-document slot beside a committee name that states what the file is.
    member('support-slot','memo-site','5','hearing_memo_03.20.2024.pdf',site+'hearing_memo_03.20.2024.pdf',early,True,False,['memorandum'])
    member('support-slot','memo-house','5','HHRG-118-II06-20240320-SD003.pdf',house+'HHRG-118-II06-20240320-SD003.pdf',late,True,True,['supporting-material'])
    # Two official names of different kinds: the one a committee name agrees with leads the newer one.
    member('two-official','donaldson-wstate','6','HHRG-118-SY00-Wstate-DonaldsonT-20230419.pdf',house+'HHRG-118-SY00-Wstate-DonaldsonT-20230419.pdf',early,True,True,['statement'])
    member('two-official','donaldson-site','6','2023-04-19-donaldson-testimony.pdf',site+'2023-04-19-donaldson-testimony.pdf',middle,True,False,['statement'])
    member('two-official','odonnell-bio','6','HHRG-118-SY00-Bio-ODonnellS-20230419.pdf',house+'HHRG-118-SY00-Bio-ODonnellS-20230419.pdf',late,True,True,['biography'])
    # Two official names of different kinds and no committee name: saved-file order holds (only a reading settles it).
    member('unsettled','daigh-bio','7','HHRG-113-VR00-Bio-DaighJ-20140409.pdf',house+'HHRG-113-VR00-Bio-DaighJ-20140409.pdf',early,True,True,['biography'])
    member('unsettled','daigh-wstate','7','HHRG-113-VR00-Wstate-DaighJ-20140409.pdf',house+'HHRG-113-VR00-Wstate-DaighJ-20140409.pdf',late,True,True,['statement'])
    # No official name: a name that states a kind does not jump saved-file order.
    member('no-official','ford-says','8','ford_testimony.pdf',site+'ford_testimony.pdf',early,True,False,['statement'])
    member('no-official','ford-silent','8','6.27.2013-Ford.pdf',site+'6.27.2013-Ford.pdf',late,True,False,[])
    # A committee name with no address cannot name the body, so it contradicts nothing.
    member('addressless','smith-house','9','HHRG-118-XX00-Bio-SmithA-20240101.pdf',house+'HHRG-118-XX00-Bio-SmithA-20240101.pdf',early,True,True,['biography'])
    member('addressless','smith-nowhere','9','Smith Testimony.pdf',None,late,True,False,['statement'])
    # A GovInfo hearing beside a committee "transcript" name is no slot label: saved-file order holds, whichever is newer.
    gpo='https://www.govinfo.gov/content/pkg/'
    member('hearing-new','chrg-new','c','CHRG-119shrg60688.pdf',gpo+'CHRG-119shrg60688/pdf/CHRG-119shrg60688.pdf',late,True,True,['published-hearing'])
    member('hearing-new','transcript-old','c','S.HRG.119-99_Transcript.pdf',site+'S.HRG.119-99_Transcript.pdf',early,True,False,['transcript'])
    member('hearing-old','chrg-old','d','CHRG-118shrg53651.pdf',gpo+'CHRG-118shrg53651/pdf/CHRG-118shrg53651.pdf',early,True,True,['published-hearing'])
    member('hearing-old','transcript-new','d','S. Hrg. 118-126_Transcript_3.16.2023.pdf',site+'S.%20Hrg.%20118-126_Transcript.pdf',late,True,False,['transcript'])
    # The saved body is still the newest fetch: an official name on older bytes names nothing.
    member('body','old-official','a','HHRG-118-XX00-Wstate-JonesB-20240101.pdf',house+'HHRG-118-XX00-Wstate-JonesB-20240101.pdf',early,True,True,['statement'])
    member('body','new-plain','b','jones_revised.pdf',site+'jones_revised.pdf',late,True,False,[])
    kinds=dict(biography='witness-biography',statement='testimony',memorandum='committee-memorandum')
    kinds.update({'supporting-material':'meeting-support','published-hearing':'published-hearing','transcript':'transcript'})
    annotations=[dict(source_id=row['source_id'],document_family=said[row['source_id']][1],
        document_kind=[('witness-statement' if said[row['source_id']][0] and f=='statement' else kinds[f]) for f in said[row['source_id']][1]]) for row in members]
    strings=list_of('Utf8')
    inputs=[json_input(tmp_path,'members',members,component='Utf8',source_id='Utf8',body_sha='Utf8',filename='Utf8',
                       source_url='Utf8',format='Utf8',exact_bytes='Boolean',first_fetched='Utf8',is_real_file='Boolean',
                       archive_member='Boolean',body_stored='Boolean'),
            json_input(tmp_path,'source_annotations',annotations,source_id='Utf8',document_kind=strings,document_family=strings),
            json_input(tmp_path,'formats',[dict(id='pdf',kind='preference',value='pdf',rank=1)],id='Utf8',kind='Utf8',value='Utf8',rank='Int32'),
            _name_readings(tmp_path,members,said)]
    from viewer_publication.archive_model import SAVED_NAME_KINDS
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=_saved_file_steps()+[dict(name='saved_name_conflicts',sql=(ROOT/'model/sql/saved-name-conflicts.sql').read_text(),materialize=True)],outputs=[],
        queries=[dict(name='lead',sql="""SELECT s.component,s.source_id,s.body_sha,s.filename,a.document_kind,a.document_family
                      FROM saved_files s JOIN source_annotations a ON s.source_id=a.source_id WHERE s.saved_rank=1 ORDER BY s.component"""),
                 dict(name='conflicts',sql="SELECT * FROM saved_name_conflicts ORDER BY component"),SAVED_NAME_KINDS,
                 dict(name='rows',sql="SELECT count(*) AS n,count(DISTINCT source_id) AS sources FROM saved_files")])
    lead={row['component']:row for row in result['lead']}
    assert {c:row['source_id'] for c,row in lead.items()}=={'bio-slot':'knox-site','bryan':'bryan-site','real-bio':'hayden-house',
        'plain':'kessler-house','support-slot':'memo-site','two-official':'donaldson-wstate','unsettled':'daigh-wstate',
        'no-official':'ford-silent','addressless':'smith-house','hearing-new':'chrg-new','hearing-old':'transcript-new','body':'new-plain'}
    for component,name in (('bio-slot','Knox Testimony - WOW Ov Hrg 10.26.21.pdf'),('bryan','Testimony - Bryan.pdf')):
        assert (lead[component]['filename'],lead[component]['document_kind'],lead[component]['document_family'])==(name,['testimony'],['statement'])
    assert (lead['real-bio']['filename'],lead['real-bio']['document_kind'])==('HHRG-118-HA00-Bio-HaydenC-20240710.pdf',['witness-biography'])
    assert (lead['plain']['filename'],lead['plain']['document_kind'])==('HHRG-119-ED10-Wstate-KesslerG-20260224.pdf',['witness-statement'])
    assert (lead['support-slot']['filename'],lead['support-slot']['document_kind'])==('hearing_memo_03.20.2024.pdf',['committee-memorandum'])
    assert lead['body']['body_sha']=='b'*64 and result['rows']==[dict(n=len(members),sources=len(members))]
    # Every document whose leading name's kind another name of the same bytes does not share, and who leads it.
    flags=lambda component,*values:dict(component=component,**dict(zip(('official_leads','official_slot','committee_speaks','committee_agrees'),values)))
    assert result['conflicts']==[flags('bio-slot',False,False,False,False),flags('bryan',False,False,False,False),
        flags('hearing-new',True,False,True,False),flags('hearing-old',False,False,False,False),flags('support-slot',False,False,False,False),
        flags('two-official',True,True,True,True),flags('unsettled',True,True,False,False)]
    assert result['saved_name_kinds']==[dict(documents=7,committee_name_leads=4,official_name_leads_with_committee_agreement=1,
        official_names_disagree_unsettled=1,other_official_name_leads_contradicted=1,slot_name_leads_contradicted=0)]


def test_a_document_named_by_an_unlisted_copy_keeps_the_link_text_of_its_listed_copy(tmp_path):
    """ct-h8dr: the name can come from an official copy that no page lists. The fallback title is still the
    reading title of the first other-format file; with none it is the listing-link text of another copy
    of the same bytes, in saved-file order. Text on a link to other bytes of the same format titles nothing."""
    def saved(component,source_id,body,rank,fmt='pdf'):
        return dict(component=component,source_id=source_id,body_sha=body*64,format=fmt,saved_rank=rank)
    files=[saved('official','house','1',1),saved('official','site','1',2),saved('official','mirror','1',3),
           saved('formats','pdf','3',1),saved('formats','html','4',2,'html'),
           saved('both','chrg','5',1),saved('both','transcript','5',2),saved('both','htm','6',3,'html'),
           saved('edition','new','7',1),saved('edition','old','8',2),
           saved('none','only','9',1)]
    titles=dict(site=(None,'Mr. Steve Mathison'),mirror=(None,'Mathison testimony'),html=('H.R. 5376',None),
                transcript=(None,'GPO_FINAL_5.19.21.pdf (10.25 MB)'),htm=('- HEARING ON PENDING NOMINATIONS',None),old=(None,'An earlier edition'))
    inputs=[json_input(tmp_path,'saved_files',files,component='Utf8',source_id='Utf8',body_sha='Utf8',format='Utf8',saved_rank='Int64'),
            json_input(tmp_path,'source_annotations',[dict(source_id=row['source_id'],reading_title=titles.get(row['source_id'],(None,None))[0],
                listing_title=titles.get(row['source_id'],(None,None))[1]) for row in files],source_id='Utf8',reading_title='Utf8',listing_title='Utf8')]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=[],outputs=[],
        queries=[dict(name='t',sql='SELECT * FROM ('+(ROOT/'model/sql/document-rendition-titles.sql').read_text()+') t ORDER BY component')])
    assert result['t']==[dict(component='both',title='- HEARING ON PENDING NOMINATIONS'),dict(component='formats',title='H.R. 5376'),
                         dict(component='official',title='Mr. Steve Mathison')]


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


def test_a_title_with_no_name_in_it_refuses(tmp_path):
    """ct-ccsi: a title with no letter, or a numbering word and a number, is a link word for the gate
    as for the rule; a number after a name, and letters of any script, are a title."""
    from viewer_publication.archive_model import GENERIC_TITLES_SQL, registry_inputs
    titles = ['12', '_3', '.', '16-4', '$1.5', '19-26-03-26-19', 'no. 3', 'No 8', 'Number 12', 'nos. 3-5',
              'Amendment No. 3', 'Exhibit 3', 'Version 2', 'No', 'H.R. 1', '中文', 'Number of Farms in 2022', None]
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
