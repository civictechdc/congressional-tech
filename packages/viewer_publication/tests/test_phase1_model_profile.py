"""Pinned profile identity and native completeness precede release acceptance."""
import os

import pytest

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


VERSIONS={name:name+'-1' for name in ['sniff','html','xml','json']}


def test_profile_identity_versions_rules_and_runtime_without_physical_selectors():
    from viewer_publication.archive_model_profile import profile_record
    args=dict(parser_versions=VERSIONS,catalog_version='catalog-1',engine_revision='a'*40,
        runtime_pins=dict(runner_class='linux-4cpu-16gb',limits=dict(compute_threads=4,batch_rows=8192)),
        lake_versions=dict(captures='b'*64,readings='c'*64,filename_readings='d'*64),
        writer_settings=dict(row_group_rows=65536,compression='zstd3'),
        file_hashes={'model/sql/roles.sql':'e'*64,'model/registries/formats.json':'f'*64},
        snapshots={'captures':dict(metadata_location='/one/metadata.json',table_uuid='one',snapshot=1,schema_id=0)})
    first=profile_record(**args)
    relocated=profile_record(**dict(args,snapshots={'captures':dict(metadata_location='/two/metadata.json',table_uuid='two',snapshot=2,schema_id=7)}))
    assert first['profile_sha256']==relocated['profile_sha256']
    assert first['snapshots']!=relocated['snapshots']
    assert first['profile']['engine_revision']=='a'*40
    assert first['profile']['parser_versions']==VERSIONS
    for changed in [dict(file_hashes={'model/sql/roles.sql':'0'*64,'model/registries/formats.json':'f'*64}),
                    dict(parser_versions=dict(VERSIONS,html='html-2')),
                    dict(catalog_version='catalog-2'),
                    dict(writer_settings=dict(row_group_rows=32768,compression='zstd3')),
                    dict(runtime_pins=dict(runner_class='other',limits=dict(compute_threads=4,batch_rows=8192)))]:
        assert profile_record(**dict(args,**changed))['profile_sha256']!=first['profile_sha256']
    args['runtime_pins']['limits']['batch_rows']=1
    assert first['profile']['runtime_pins']['limits']['batch_rows']==8192


def test_profile_record_refuses_unpinned_definitions():
    from viewer_publication.archive_model_profile import profile_record
    with pytest.raises(ValueError):
        profile_record(parser_versions=VERSIONS,catalog_version='',engine_revision='a'*40,
            runtime_pins={},lake_versions={},writer_settings={},snapshots={},file_hashes={})


@pytest.mark.parametrize('case,expected',[
    ('complete',{}),('error-settles',{}),('size-limit-settles',{}),('current-capture-sniff',{}),
    ('body-admission',{}),('unreadable-current',{}),('bundle-current',{}),('filename-unreadable',{}),
    ('missing-sniff',{'missing_sniff':1}),('missing-page',{'missing_pages':1}),
    ('old-page',{'missing_pages':1}),('old-unreadable',{'missing_pages':1}),
    ('missing-filename',{'missing_filenames':1}),('old-filename',{'missing_filenames':1}),
    ('duplicate-capture',{'duplicate_captures':1}),('duplicate-reading',{'duplicate_readings':1}),
    ('duplicate-filename',{'duplicate_filename_readings':1}),
    ('bad-admission',{'invalid_body_admissions':1,'missing_sniff':1}),
    ('sniff-error-settles',{}),('bundle-sniff-current',{}),('old-bundle',{'missing_pages':1}),
    ('old-filename-unreadable',{'missing_filenames':1}),('duplicate-parser',{'duplicate_parser_versions':1}),
])
def test_native_profile_completeness_counts_pending_and_settled_inputs(tmp_path,case,expected):
    from viewer_publication.archive_model_profile import completeness_checks,completeness_steps,readings_bundle_version
    body='a'*64
    captures=[dict(receipt_key='r',receipt_line=1,capture_index=0,body_hex=body)]
    readings=[dict(body_hex=body,parser='sniff',parser_version='sniff-1',status='completed'),
              dict(body_hex=body,parser='html',parser_version='html-1',status='completed')]
    sniff=[dict(body_hex=body,format='html')]
    filenames=[dict(filename='a.pdf',source_url='',catalog_version='catalog-1',status='completed')]
    unreadable=[];admissions=[]
    if case=='error-settles':readings[1]['status']='error';filenames[0]['status']='error'
    if case=='size-limit-settles':readings[1]['status']='size_limit';filenames[0]['status']='size_limit'
    if case=='current-capture-sniff':readings=readings[1:]
    if case in {'body-admission','bad-admission'}:
        readings=[];sniff=[];admissions=[dict(body_hex=body,format='empty' if case=='body-admission' else 'html',basis='writer')]
    if case in {'missing-sniff','bundle-sniff-current'}:readings=[];sniff=[]
    if case=='sniff-error-settles':readings[0]['status']='error';sniff=[]
    if case in {'missing-page','old-unreadable','unreadable-current','bundle-current','old-bundle'}:readings=readings[:1]
    if case=='old-page':readings[1]['parser_version']='old'
    if case in {'unreadable-current','old-unreadable','bundle-current','bundle-sniff-current','old-bundle'}:
        unreadable=[dict(body_sha256=body,record_sha=None,
            parser='readings' if case in {'bundle-current','bundle-sniff-current','old-bundle'} else 'html',
            parser_version=readings_bundle_version(VERSIONS) if case in {'bundle-current','bundle-sniff-current'} else
                'old' if case in {'old-unreadable','old-bundle'} else 'html-1')]
    if case in {'missing-filename','filename-unreadable','old-filename-unreadable'}:filenames=[]
    if case in {'filename-unreadable','old-filename-unreadable'}:
        # The native query computes the same compact-JSON identity as D3.
        unreadable=[dict(body_sha256=None,record_sha='native',parser='filename',parser_version='old' if case=='old-filename-unreadable' else 'catalog-1')]
    if case=='old-filename':filenames[0]['catalog_version']='old'
    if case=='duplicate-capture':captures*=2
    if case=='duplicate-reading':readings.append(dict(readings[1]))
    if case=='duplicate-filename':filenames*=2
    inputs=[json_input(tmp_path,'capture_rows',captures,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',body_hex='Utf8'),
        json_input(tmp_path,'reading_rows',readings,body_hex='Utf8',parser='Utf8',parser_version='Utf8',status='Utf8'),
        json_input(tmp_path,'sniff_rows',sniff,body_hex='Utf8',format='Utf8'),
        json_input(tmp_path,'admission_rows',admissions,body_hex='Utf8',format='Utf8',basis='Utf8'),
        json_input(tmp_path,'filename_readings',filenames,filename='Utf8',source_url='Utf8',catalog_version='Utf8',status='Utf8'),
        json_input(tmp_path,'unreadable_rows',unreadable,body_sha256='Utf8',record_sha='Utf8',parser='Utf8',parser_version='Utf8'),
        json_input(tmp_path,'parser_versions',[dict(parser=p,version=v) for p,v in VERSIONS.items()]+([dict(parser='html',version='html-1')] if case=='duplicate-parser' else []),parser='Utf8',version='Utf8')]
    steps=[dict(name='captures',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
        dict(name='readings',sql="SELECT *,decode(body_hex,'hex') AS body_sha FROM reading_rows"),
        dict(name='sniff_facts',sql="SELECT decode(body_hex,'hex') AS body_sha,format FROM sniff_rows"),
        dict(name='body_admissions',sql="SELECT decode(body_hex,'hex') AS body_sha,format,basis FROM admission_rows"),
        dict(name='source_files',sql="SELECT 'a.pdf' AS filename,cast(NULL AS VARCHAR) AS source_url"),
        dict(name='active_unreadable',sql="SELECT body_sha256,CASE WHEN record_sha='native' THEN encode(sha256(json_array('a.pdf','')),'hex') ELSE record_sha END AS record_sha,parser,parser_version FROM unreadable_rows")]
    queries=completeness_checks(catalog_version='catalog-1',readings_version=readings_bundle_version(VERSIONS))
    report=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+completeness_steps(),outputs=[],queries=queries)['profile_completeness'][0]
    assert {name:value for name,value in report.items() if value}==expected


def test_profile_hashes_current_definition_files_and_reuses_capture_profile():
    from viewer_publication.archive_model_profile import profile_record,capture_profile_record
    record=profile_record(parser_versions=VERSIONS,catalog_version='catalog-1',engine_revision='a'*40,
        runtime_pins=dict(runner_class='local',limits=dict(compute_threads=4)),
        lake_versions=dict(captures='b'*64),writer_settings=dict(row_group_rows=65536),
        snapshots={'captures':dict(metadata_location='/pinned/metadata.json')})
    hashes=record['profile']['file_hashes']
    public=capture_profile_record(engine_revision='a'*40)
    assert public['sql']['url_normalized']['sha256']==hashes['model/sql/url-normalized.sql']
    assert public['sql']['url_keys']['sha256']==hashes['model/sql/url-keys.sql']
    assert 'model/sql/profile-completeness.sql' in hashes
    assert 'model/registries/release-schema.json' in hashes
    assert 'packages/viewer_publication/src/viewer_publication/archive_format.py' in hashes
    assert 'packages/viewer_publication/src/viewer_publication/archive_schema.py' in hashes


def test_semantic_profile_pins_the_failure_producer_separately_from_leaf_parsers():
    from viewer_publication.archive_model_profile import _definition_hashes,ROOT
    hashes=_definition_hashes(ROOT)
    assert {
        'packages/congress_api/src/congress_api/lake/readings.py',
        'packages/congress_api/src/congress_api/retention/parser_worker.py',
        'packages/congress_api/src/congress_api/retention/process_resources.py',
    } <= hashes.keys()


def test_validate_parser_versions_rejects_scalar_entity_versions():
    from viewer_publication.archive_model_profile import validate_parser_versions
    with pytest.raises(ValueError, match='source-scoped'):
        validate_parser_versions(dict(VERSIONS, meeting_records='scalar-hash'))
    with pytest.raises(ValueError, match='source-scoped'):
        validate_parser_versions(dict(VERSIONS, appearance_records='scalar-hash'))


def test_entity_completeness_and_record_producer_candidates_agree_1_for_1(tmp_path):
    """ct-kw9b: completeness_checks(include_entities=True) and _record_producer candidate SQL agree 1-for-1."""
    from congress_api.lake._record_producer import (
        CANDIDATE_APPEARANCE_RECORDS_SQL,
        CANDIDATE_MEETING_RECORDS_SQL,
    )
    from viewer_publication.archive_model_profile import (
        APPEARANCE_SOURCES,
        MEETING_SOURCES,
        completeness_checks,
        completeness_steps,
        expand_parser_version_rows,
        readings_bundle_version,
    )

    mr_vers = {s: f'mr-{s}-1' for s in MEETING_SOURCES}
    ar_vers = {s: f'ar-{s}-1' for s in APPEARANCE_SOURCES}
    all_versions = dict(VERSIONS, meeting_records=mr_vers, appearance_records=ar_vers)

    sha_non_house_cm = '11' * 32
    sha_non_house_wl = '22' * 32
    sha_non_mods_xml = '33' * 32
    sha_cg_web_url = '44' * 32
    sha_house_cm = '55' * 32
    sha_house_wl = '66' * 32
    sha_mods_xml = '77' * 32
    sha_cg_sizelimit = '88' * 32
    sha_inline_cg = '99' * 32

    capture_rows = [
        # 1. Non-House XML with xml_root='committee-meeting' -> NOT a candidate
        dict(
            receipt_key='r1', receipt_line=1, capture_index=0, body_hex=sha_non_house_cm,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='documents', url='https://example.org/other.xml',
            requested_url='https://example.org/other.xml', context_url=None, member_path=None,
            sniffed_format='xml', media_type='application/xml',
        ),
        # 2. Non-House XML with xml_root='witness-list' -> NOT a candidate
        dict(
            receipt_key='r1', receipt_line=2, capture_index=0, body_hex=sha_non_house_wl,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='documents', url='https://example.org/witnesses.xml',
            requested_url='https://example.org/witnesses.xml', context_url=None, member_path=None,
            sniffed_format='xml', media_type='application/xml',
        ),
        # 3. Non-MODS XML with xml_root='mods' and CHRG in URL but no 'mods' in family/URL -> NOT a candidate
        dict(
            receipt_key='r1', receipt_line=3, capture_index=0, body_hex=sha_non_mods_xml,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='documents', url='https://example.org/CHRG-118hhrg12345/other.xml',
            requested_url='https://example.org/CHRG-118hhrg12345/other.xml', context_url=None, member_path=None,
            sniffed_format='xml', media_type='application/xml',
        ),
        # 4. Congress.gov committee-meeting JSON without /v3/ prefix -> candidate for both mr and ar
        dict(
            receipt_key='r1', receipt_line=4, capture_index=0, body_hex=sha_cg_web_url,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='congress/meetings', url='https://www.congress.gov/committee-meeting/118/house/115538',
            requested_url='https://www.congress.gov/committee-meeting/118/house/115538', context_url=None, member_path=None,
            sniffed_format='json', media_type='application/json',
        ),
        # 5. House committee-meeting XML -> candidate for mr
        dict(
            receipt_key='r1', receipt_line=5, capture_index=0, body_hex=sha_house_cm,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='house/Committees', url='https://docs.house.gov/meetings/IF/IF00/20230510/115538/HHRG-118-IF00-20230510.xml',
            requested_url='https://docs.house.gov/meetings/IF/IF00/20230510/115538/HHRG-118-IF00-20230510.xml',
            context_url=None, member_path=None, sniffed_format='xml', media_type='application/xml',
        ),
        # 6. House witness-list XML -> candidate for ar
        dict(
            receipt_key='r1', receipt_line=6, capture_index=0, body_hex=sha_house_wl,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='house/Committees', url='https://docs.house.gov/meetings/IF/IF00/20230510/115538/HHRG-118-IF00-WList-20230510.xml',
            requested_url='https://docs.house.gov/meetings/IF/IF00/20230510/115538/HHRG-118-IF00-WList-20230510.xml',
            context_url=None, member_path=None, sniffed_format='xml', media_type='application/xml',
        ),
        # 7. GovInfo MODS XML -> candidate for ar
        dict(
            receipt_key='r1', receipt_line=7, capture_index=0, body_hex=sha_mods_xml,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='govinfo/mods', url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg55555/mods.xml',
            requested_url='https://www.govinfo.gov/metadata/pkg/CHRG-118hhrg55555/mods.xml',
            context_url=None, member_path=None, sniffed_format='xml', media_type='application/xml',
        ),
        # 8. Congress.gov JSON whose page reading status='size_limit' -> still a candidate for both mr and ar
        dict(
            receipt_key='r1', receipt_line=8, capture_index=0, body_hex=sha_cg_sizelimit,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='congress/meetings', url='https://api.congress.gov/v3/committee-meeting/118/house/115777',
            requested_url='https://api.congress.gov/v3/committee-meeting/118/house/115777', context_url=None, member_path=None,
            sniffed_format='json', media_type='application/json',
        ),
        # 9. Inline saved-record Congress.gov meeting (sha256 IS NULL, outcome='saved-record') -> candidate for both mr and ar
        dict(
            receipt_key='r1', receipt_line=9, capture_index=0, body_hex=None,
            mode='fetch', complete=True, outcome='saved-record', http_status=200, stored_suffix=None,
            family='congress/meetings', url='https://api.congress.gov/v3/committee-meeting/118/house/115999',
            requested_url='https://api.congress.gov/v3/committee-meeting/118/house/115999', context_url=None, member_path=None,
            sniffed_format=None, media_type=None,
        ),
    ]

    reading_rows = []
    sniff_rows = []
    for row in capture_rows:
        bhex = row['body_hex']
        if bhex is None:
            continue
        fmt = row['sniffed_format']
        sniff_rows.append(dict(body_hex=bhex, format=fmt))
        reading_rows.append(dict(body_hex=bhex, parser='sniff', parser_version='sniff-1', status='completed', xml_root=None))
        xml_root = None
        if bhex in (sha_non_house_cm, sha_house_cm):
            xml_root = 'committee-meeting'
        elif bhex in (sha_non_house_wl, sha_house_wl):
            xml_root = 'witness-list'
        elif bhex in (sha_non_mods_xml, sha_mods_xml):
            xml_root = 'mods'
        r_status = 'size_limit' if bhex == sha_cg_sizelimit else 'completed'
        reading_rows.append(dict(body_hex=bhex, parser=fmt, parser_version=f'{fmt}-1', status=r_status, xml_root=xml_root))

    # Settled entity rows for ONLY the genuine candidates (4, 5, 6, 7, 8, 9)
    mr_input = [
        dict(record_sha_hex=sha_cg_web_url, source='congress_gov', parser_version=mr_vers['congress_gov'], status='completed'),
        dict(record_sha_hex=sha_house_cm, source='house_xml', parser_version=mr_vers['house_xml'], status='completed'),
        dict(record_sha_hex=sha_cg_sizelimit, source='congress_gov', parser_version=mr_vers['congress_gov'], status='completed'),
        dict(record_sha_hex=sha_inline_cg, source='congress_gov', parser_version=mr_vers['congress_gov'], status='completed'),
    ]
    ar_input = [
        dict(record_sha_hex=sha_cg_web_url, source='congress_gov', parser_version=ar_vers['congress_gov'], status='completed'),
        dict(record_sha_hex=sha_house_wl, source='house_xml', parser_version=ar_vers['house_xml'], status='completed'),
        dict(record_sha_hex=sha_mods_xml, source='mods', parser_version=ar_vers['mods'], status='completed'),
        dict(record_sha_hex=sha_cg_sizelimit, source='congress_gov', parser_version=ar_vers['congress_gov'], status='completed'),
        dict(record_sha_hex=sha_inline_cg, source='congress_gov', parser_version=ar_vers['congress_gov'], status='completed'),
    ]

    def _run_completeness(sub_dir, mr_rows, ar_rows):
        sub_dir.mkdir(parents=True, exist_ok=True)
        inputs = [
            json_input(
                sub_dir, 'capture_rows', capture_rows,
                receipt_key='Utf8', receipt_line='Int32', capture_index='Int32', body_hex='Utf8',
                mode='Utf8', complete='Boolean', outcome='Utf8', http_status='Int32', stored_suffix='Utf8',
                family='Utf8', url='Utf8', requested_url='Utf8', context_url='Utf8', member_path='Utf8',
                sniffed_format='Utf8', media_type='Utf8',
            ),
            json_input(
                sub_dir, 'reading_rows', reading_rows,
                body_hex='Utf8', parser='Utf8', parser_version='Utf8', status='Utf8', xml_root='Utf8',
            ),
            json_input(sub_dir, 'sniff_rows', sniff_rows, body_hex='Utf8', format='Utf8'),
            json_input(sub_dir, 'admission_rows', [], body_hex='Utf8', format='Utf8', basis='Utf8'),
            json_input(sub_dir, 'filename_readings', [], filename='Utf8', source_url='Utf8', catalog_version='Utf8', status='Utf8'),
            json_input(sub_dir, 'unreadable_rows', [], body_sha256='Utf8', record_sha='Utf8', parser='Utf8', parser_version='Utf8'),
            json_input(sub_dir, 'parser_versions', expand_parser_version_rows(all_versions), parser='Utf8', version='Utf8'),
            json_input(sub_dir, 'meeting_records_input', mr_rows, record_sha_hex='Utf8', source='Utf8', parser_version='Utf8', status='Utf8'),
            json_input(sub_dir, 'appearance_records_input', ar_rows, record_sha_hex='Utf8', source='Utf8', parser_version='Utf8', status='Utf8'),
        ]
        steps = [
            dict(name='captures', sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
            dict(name='readings', sql="SELECT *,decode(body_hex,'hex') AS body_sha FROM reading_rows"),
            dict(name='sniff_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,format FROM sniff_rows"),
            dict(name='body_admissions', sql="SELECT decode(body_hex,'hex') AS body_sha,format,basis FROM admission_rows"),
            dict(name='source_files', sql="SELECT cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS source_url WHERE false"),
            dict(name='active_unreadable', sql="SELECT body_sha256,record_sha,parser,parser_version FROM unreadable_rows"),
        ] + completeness_steps()
        queries = completeness_checks(
            catalog_version='catalog-1',
            readings_version=readings_bundle_version(VERSIONS),
            include_entities=True,
            meeting_records_version=mr_vers,
            appearance_records_version=ar_vers,
        ) + [
            dict(name='producer_mr', sql=CANDIDATE_MEETING_RECORDS_SQL),
            dict(name='producer_ar', sql=CANDIDATE_APPEARANCE_RECORDS_SQL),
        ]
        return run_job(
            sub_dir,
            NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            inputs=inputs,
            steps=steps,
            outputs=[],
            queries=queries,
        )

    res_settled = _run_completeness(tmp_path / 'settled', mr_input, ar_input)
    # Producer SQL must not select non-House XML or non-MODS XML captures
    prod_mr = {(r['record_sha'], r['source']) for r in res_settled['producer_mr']}
    prod_ar = {(r['record_sha'], r['source']) for r in res_settled['producer_ar']}
    assert (sha_non_house_cm, 'house_xml') not in prod_mr
    assert (sha_non_house_wl, 'house_xml') not in prod_ar
    assert (sha_non_mods_xml, 'mods') not in prod_ar
    assert {(sha_cg_web_url, 'congress_gov'), (sha_house_cm, 'house_xml')} <= prod_mr
    assert {(sha_cg_web_url, 'congress_gov'), (sha_house_wl, 'house_xml'), (sha_mods_xml, 'mods')} <= prod_ar

    # Completeness checks must agree 1-for-1: 0 unsettled when genuine candidates are settled
    ent_settled = res_settled['entity_profile_completeness'][0]
    assert {k: v for k, v in ent_settled.items() if v} == {}

    # Omitting the Congress.gov web URL candidate must be flagged as unsettled in both mr and ar
    res_missing_cg = _run_completeness(tmp_path / 'missing-cg', mr_input[1:], ar_input[1:])
    ent_missing_cg = res_missing_cg['entity_profile_completeness'][0]
    assert ent_missing_cg['unsettled_meeting_records'] == 1
    assert ent_missing_cg['unsettled_appearance_records'] == 1

    # Omitting the size_limit reading candidate must also be flagged as unsettled in both mr and ar
    res_missing_sl = _run_completeness(
        tmp_path / 'missing-sl',
        [r for r in mr_input if r['record_sha_hex'] != sha_cg_sizelimit],
        [r for r in ar_input if r['record_sha_hex'] != sha_cg_sizelimit],
    )
    ent_missing_sl = res_missing_sl['entity_profile_completeness'][0]
    assert ent_missing_sl['unsettled_meeting_records'] == 1
    assert ent_missing_sl['unsettled_appearance_records'] == 1

    # Omitting the inline saved-record Congress.gov candidate must also be flagged as unsettled in both mr and ar
    res_missing_inline = _run_completeness(
        tmp_path / 'missing-inline',
        [r for r in mr_input if r['record_sha_hex'] != sha_inline_cg],
        [r for r in ar_input if r['record_sha_hex'] != sha_inline_cg],
    )
    ent_missing_inline = res_missing_inline['entity_profile_completeness'][0]
    assert ent_missing_inline['unsettled_meeting_records'] == 1
    assert ent_missing_inline['unsettled_appearance_records'] == 1

