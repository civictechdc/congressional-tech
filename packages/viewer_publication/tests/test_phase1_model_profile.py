"""Pinned profile identity and native completeness precede release acceptance."""
import json
import os

import pytest

from congress_api.lake.compatible_versions import accepted_versions_input,selected_readings_steps

from congress_api.retention.provenance import json_input,run_job
from docspec_client.client import NativeDatasets


VERSIONS={name:name+'-1' for name in ['sniff','html','xml','json']}


def test_profile_identity_versions_rules_and_runtime_without_physical_selectors():
    from viewer_publication.archive_model_profile import profile_record
    args=dict(parser_versions=VERSIONS,catalog_version='catalog-1',engine_revision='a'*40,
        runtime_pins=dict(platform='linux-x86_64',binary_sha256='e'*64),
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
                    dict(runtime_pins=dict(platform='linux-x86_64',binary_sha256='f'*64))]:
        assert profile_record(**dict(args,**changed))['profile_sha256']!=first['profile_sha256']
    args['runtime_pins']['binary_sha256']='0'*64
    assert first['profile']['runtime_pins']['binary_sha256']=='e'*64


def _engine(tmp_path,name,limits,binary_sha256='e'*64):
    from types import SimpleNamespace
    path=tmp_path/(name+'-limits.json');path.write_text(json.dumps(limits))
    return SimpleNamespace(source_revision='a'*40,platform='darwin-arm64',build_features=['remote'],
                           binary_sha256=binary_sha256,limits=path)


def test_engine_limits_stay_out_of_the_semantic_profile_and_input_identity(tmp_path):
    """C3: a CI run and a Mac run of the same inputs share one profile and input digest.

    Byte identity across threads, batch sizes and a forced spill is proven by
    test_model_determinism; the limits used are recorded beside the run instead.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.lake import filenames,readings
    from viewer_publication.archive_controller import PublicationInputsChanged,_require_model_definition
    from viewer_publication.archive_model import prepare_model_inputs
    from viewer_publication.archive_publish import input_digest
    tables={}
    for name in ['captures','readings','filename_readings']:
        tables[name]=tmp_path/(name+'.parquet');pq.write_table(pa.table(dict(value=[1])),tables[name])
    versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']}
    mac=dict(compute_threads=2,memory_bytes=36507222016,scratch_bytes=6<<30,batch_rows=8192,
             max_batch_bytes=64<<20,max_metadata_bytes=32<<20)
    ci=dict(mac,compute_threads=4,memory_bytes=15032385536,batch_rows=512)
    def profile(name,engine):
        return prepare_model_inputs(**tables,parser_versions=versions,catalog_version=filenames.current_version(),
            engine=engine,scratch=tmp_path/name)['profile']
    digest=lambda value:input_digest(receipt_keys=['receipts/documents/a.jsonl.gz'],provenance=[],
                                     profile=value['profile'],entity_digests={})
    first=profile('mac',_engine(tmp_path,'mac',mac))
    second=profile('ci',_engine(tmp_path,'ci',ci))
    assert 'limits' not in first['profile']['runtime_pins']
    assert first['profile_sha256']==second['profile_sha256'] and digest(first)==digest(second)
    # A resume under the other memory pool continues the same retained model.
    saved=dict(profile=first,entity_digests={},
        admitted_names=['invariants','model_invariants','url_state_invariants','profile_completeness'])
    _require_model_definition(saved,_engine(tmp_path,'resume',ci))
    # The native build and real inputs still define semantics.
    other=profile('binary',_engine(tmp_path,'binary',mac,binary_sha256='f'*64))
    assert other['profile_sha256']!=first['profile_sha256'] and digest(other)!=digest(first)
    with pytest.raises(PublicationInputsChanged,match='Native runtime changed'):
        _require_model_definition(saved,_engine(tmp_path,'rebuilt',mac,binary_sha256='f'*64))
    changed=prepare_model_inputs(**tables,parser_versions=versions,catalog_version='catalog-other',
        engine=_engine(tmp_path,'input',mac),scratch=tmp_path/'input')['profile']
    assert changed['profile_sha256']!=first['profile_sha256'] and digest(changed)!=digest(first)
    assert input_digest(receipt_keys=['receipts/documents/b.jsonl.gz'],provenance=[],
                        profile=first['profile'],entity_digests={})!=digest(first)


def test_profile_record_refuses_unpinned_definitions():
    from viewer_publication.archive_model_profile import profile_record
    with pytest.raises(ValueError):
        profile_record(parser_versions=VERSIONS,catalog_version='',engine_revision='a'*40,
            runtime_pins={},lake_versions={},writer_settings={},snapshots={},file_hashes={})


@pytest.mark.parametrize('case,expected',[
    ('complete',{}),('error-settles',{}),('size-limit-settles',{}),('current-capture-sniff',{}),
    ('partial-html',{'invalid_readings':1,'missing_pages':1}),
    ('body-admission',{}),('unreadable-current',{}),('bundle-current',{}),('filename-unreadable',{}),
    ('missing-sniff',{'missing_sniff':1}),('missing-page',{'missing_pages':1}),
    ('old-page',{'missing_pages':1}),('old-unreadable',{'missing_pages':1}),
    ('missing-filename',{'missing_filenames':1}),('old-filename',{'missing_filenames':1}),
    ('duplicate-capture',{'duplicate_captures':1}),('duplicate-reading',{'duplicate_readings':1}),
    ('duplicate-filename',{'duplicate_filename_readings':1}),
    ('bad-admission',{'invalid_body_admissions':1,'missing_sniff':1}),
    ('sniff-error-settles',{}),('bundle-sniff-current',{}),('old-bundle',{'missing_pages':1}),
    ('old-filename-unreadable',{'missing_filenames':1}),('duplicate-parser',{'duplicate_parser_versions':1}),
    ('covered-old-page',{}),('covered-old-bundle',{}),
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
    if case=='partial-html':readings[1]['status']='partial'
    if case=='error-settles':readings[1]['status']='error';filenames[0]['status']='error'
    if case=='size-limit-settles':readings[1]['status']='size_limit';filenames[0]['status']='size_limit'
    if case=='current-capture-sniff':readings=readings[1:]
    if case in {'body-admission','bad-admission'}:
        readings=[];sniff=[];admissions=[dict(body_hex=body,format='empty' if case=='body-admission' else 'html',basis='writer')]
    if case in {'missing-sniff','bundle-sniff-current'}:readings=[];sniff=[]
    if case=='sniff-error-settles':readings[0]['status']='error';sniff=[]
    if case in {'missing-page','old-unreadable','unreadable-current','bundle-current','old-bundle'}:readings=readings[:1]
    if case in {'old-page','covered-old-page'}:readings[1]['parser_version']='old'
    if case=='covered-old-bundle':readings=readings[:1]
    if case in {'unreadable-current','old-unreadable','bundle-current','bundle-sniff-current','old-bundle','covered-old-bundle'}:
        unreadable=[dict(body_sha256=body,record_sha=None,
            parser='readings' if case in {'bundle-current','bundle-sniff-current','old-bundle','covered-old-bundle'} else 'html',
            parser_version=readings_bundle_version(VERSIONS) if case in {'bundle-current','bundle-sniff-current'} else
                'old' if case in {'old-unreadable','old-bundle','covered-old-bundle'} else 'html-1')]
    # Registry coverage, as the model renders it: whole-version entries for the old pins.
    entries=([dict(parser='html',version='old',current=VERSIONS['html'],basis='predicate',recompute_sql='none')] if case=='covered-old-page' else
             [dict(parser='readings',version='old',current=readings_bundle_version(VERSIONS),basis='bundle',recompute_sql='none')] if case=='covered-old-bundle' else [])
    pins={**VERSIONS,'readings':readings_bundle_version(VERSIONS)}
    if case in {'missing-filename','filename-unreadable','old-filename-unreadable'}:filenames=[]
    if case in {'filename-unreadable','old-filename-unreadable'}:
        # The native query computes the same compact-JSON identity as D3.
        unreadable=[dict(body_sha256=None,record_sha='native',parser='filename',parser_version='old' if case=='old-filename-unreadable' else 'catalog-1')]
    if case=='old-filename':filenames[0]['catalog_version']='old'
    if case=='duplicate-capture':captures*=2
    if case=='duplicate-reading':readings.append(dict(readings[1]))
    if case=='duplicate-filename':filenames*=2
    inputs=[json_input(tmp_path,'capture_rows',captures,receipt_key='Utf8',receipt_line='Int32',capture_index='Int32',body_hex='Utf8',bytes='Int64'),
        json_input(tmp_path,'reading_rows',readings,body_hex='Utf8',parser='Utf8',parser_version='Utf8',status='Utf8'),
        json_input(tmp_path,'sniff_rows',sniff,body_hex='Utf8',format='Utf8'),
        json_input(tmp_path,'admission_rows',admissions,body_hex='Utf8',format='Utf8',basis='Utf8'),
        json_input(tmp_path,'filename_readings',filenames,filename='Utf8',source_url='Utf8',catalog_version='Utf8',status='Utf8'),
        json_input(tmp_path,'unreadable_rows',unreadable,body_sha256='Utf8',record_sha='Utf8',parser='Utf8',parser_version='Utf8'),
        json_input(tmp_path,'parser_versions',[dict(parser=p,version=v) for p,v in VERSIONS.items()]+([dict(parser='html',version='html-1')] if case=='duplicate-parser' else []),parser='Utf8',version='Utf8'),
        accepted_versions_input(tmp_path,entries,pins=pins)]
    steps=[dict(name='captures',sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
        dict(name='readings',sql="SELECT *,decode(body_hex,'hex') AS body_sha FROM reading_rows"),*selected_readings_steps(entries),
        dict(name='sniff_facts',sql="SELECT decode(body_hex,'hex') AS body_sha,format FROM sniff_rows"),
        dict(name='body_admissions',sql="SELECT decode(body_hex,'hex') AS body_sha,format,basis FROM admission_rows"),
        dict(name='source_files',sql="SELECT 'a.pdf' AS filename,cast(NULL AS VARCHAR) AS source_url"),
        dict(name='active_unreadable',sql="SELECT body_sha256,CASE WHEN record_sha='native' THEN encode(sha256(json_array('a.pdf','')),'hex') ELSE record_sha END AS record_sha,parser,parser_version FROM unreadable_rows")]
    queries=completeness_checks(catalog_version='catalog-1')
    report=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
        steps=steps+completeness_steps(),outputs=[],queries=queries)['profile_completeness'][0]
    assert {name:value for name,value in report.items() if value}==expected


def test_profile_hashes_current_definition_files_and_reuses_capture_profile():
    from viewer_publication.archive_model_profile import profile_record,capture_profile_record
    record=profile_record(parser_versions=VERSIONS,catalog_version='catalog-1',engine_revision='a'*40,
        runtime_pins=dict(platform='local',binary_sha256='e'*64),
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


@pytest.mark.parametrize('helper',['lookup_aliases.py','meeting_detail_observations.py'])
def test_retained_model_refuses_changed_publication_helper(tmp_path,monkeypatch,helper):
    import shutil
    from types import SimpleNamespace
    from viewer_publication import archive_model_profile as model_profile
    from viewer_publication.archive_controller import PublicationInputsChanged,_require_model_definition

    definition_hashes=model_profile._definition_hashes
    for name in definition_hashes(model_profile.ROOT):
        target=tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(model_profile.ROOT/name,target)
    monkeypatch.setattr(model_profile,'_definition_hashes',lambda root:definition_hashes(tmp_path))
    limits=tmp_path/'limits.json'
    limits.write_text('{}')
    engine=SimpleNamespace(source_revision='a'*40,binary_sha256='b'*64,
        platform='test',build_features=[],limits=limits)
    args=dict(parser_versions=VERSIONS,catalog_version='catalog-1',engine_revision=engine.source_revision,
        runtime_pins=model_profile.runtime_pins(engine),
        lake_versions=dict(captures='c'*64),writer_settings=dict(row_group_rows=65536),
        snapshots={'captures':dict(metadata_location='/pinned/metadata.json')},root=tmp_path)
    original=model_profile.profile_record(**args)
    saved=dict(profile=original,entity_digests={},
        admitted_names=['invariants','model_invariants','url_state_invariants','profile_completeness'])
    _require_model_definition(saved,engine)

    path=tmp_path/'packages/viewer_publication/src/viewer_publication'/helper
    path.write_text(path.read_text()+'\n# Deliberately changed helper definition.\n')
    assert model_profile.profile_record(**args)['profile_sha256']!=original['profile_sha256']
    with pytest.raises(PublicationInputsChanged,match='Model definitions changed'):
        _require_model_definition(saved,engine)


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
        CURRENT_PAGE_READINGS_SQL,
        expected_records_sql,
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
    sha_house_amendment = 'aa' * 32
    sha_house_wlist_unread = 'bb' * 32

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
        # 10. House XML whose root is neither meeting nor witness list -> NOT a candidate (ct-kn6d)
        dict(
            receipt_key='r1', receipt_line=10, capture_index=0, body_hex=sha_house_amendment,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='house/Committees', url='https://docs.house.gov/billsthisweek/20230510/BILLS-118hr1-amendment.xml',
            requested_url='https://docs.house.gov/billsthisweek/20230510/BILLS-118hr1-amendment.xml',
            context_url=None, member_path=None, sniffed_format='xml', media_type='application/xml',
        ),
        # 11. A wlist URL with no completed XML reading -> appearance only, by the URL fallback
        dict(
            receipt_key='r1', receipt_line=11, capture_index=0, body_hex=sha_house_wlist_unread,
            mode='fetch', complete=True, outcome='stored', http_status=200, stored_suffix='.gz',
            family='house/Committees', url='https://docs.house.gov/meetings/IF/IF00/20230511/115539/HHRG-118-IF00-WList-20230511.xml',
            requested_url='https://docs.house.gov/meetings/IF/IF00/20230511/115539/HHRG-118-IF00-WList-20230511.xml',
            context_url=None, member_path=None, sniffed_format='xml', media_type='application/xml',
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
        elif bhex == sha_house_amendment:
            xml_root = 'amendment-doc'
        r_status = 'size_limit' if bhex == sha_cg_sizelimit else 'error' if bhex == sha_house_wlist_unread else 'completed'
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
        dict(record_sha_hex=sha_house_wlist_unread, source='house_xml', parser_version=ar_vers['house_xml'], status='completed'),
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
            accepted_versions_input(sub_dir, [], pins=dict(VERSIONS, readings=readings_bundle_version(VERSIONS))),
            json_input(sub_dir, 'meeting_records_input', mr_rows, record_sha_hex='Utf8', source='Utf8', parser_version='Utf8', status='Utf8'),
            json_input(sub_dir, 'appearance_records_input', ar_rows, record_sha_hex='Utf8', source='Utf8', parser_version='Utf8', status='Utf8'),
        ]
        steps = [
            dict(name='captures', sql="SELECT *,decode(body_hex,'hex') AS sha256 FROM capture_rows"),
            dict(name='readings', sql="SELECT *,decode(body_hex,'hex') AS body_sha FROM reading_rows"),
            *selected_readings_steps([]),
            dict(name='current_page_readings', sql=CURRENT_PAGE_READINGS_SQL),
            dict(name='sniff_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,format FROM sniff_rows"),
            dict(name='body_admissions', sql="SELECT decode(body_hex,'hex') AS body_sha,format,basis FROM admission_rows"),
            dict(name='source_files', sql="SELECT cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS source_url WHERE false"),
            dict(name='active_unreadable', sql="SELECT body_sha256,record_sha,parser,parser_version FROM unreadable_rows"),
        ] + completeness_steps()
        queries = completeness_checks(
            catalog_version='catalog-1',
            include_entities=True,
            meeting_records_version=mr_vers,
            appearance_records_version=ar_vers,
        ) + [
            dict(name='producer_mr', sql=CANDIDATE_MEETING_RECORDS_SQL),
            dict(name='producer_ar', sql=CANDIDATE_APPEARANCE_RECORDS_SQL),
            dict(name='expected_mr', sql=expected_records_sql('meeting_records')),
            dict(name='expected_ar', sql=expected_records_sql('appearance_records')),
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
    # ct-kn6d: routing by XML root, URL fallback when unread, and no House XML in both tables.
    house_mr = {sha for sha, source in prod_mr if source == 'house_xml'}
    house_ar = {sha for sha, source in prod_ar if source == 'house_xml'}
    assert house_mr == {sha_house_cm} and house_ar == {sha_house_wl, sha_house_wlist_unread}
    # Producer candidates are exactly the model's expected keys (both built from ROUTES).
    assert prod_mr == {(r['record_sha_hex'], r['source']) for r in res_settled['expected_mr']}
    assert prod_ar == {(r['record_sha_hex'], r['source']) for r in res_settled['expected_ar']}

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


def test_unrelated_locked_package_leaves_model_profile_while_imported_package_moves_it(tmp_path):
    """ct-6p6d: bumping an unrelated uv.lock package leaves profile_sha256 unchanged; bumping an imported one moves it."""
    import re
    import shutil
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes, profile_record

    base_hashes = _definition_hashes(ROOT)
    assert {
        'packages/house-naming/src/house_naming/data/guide.json',
        'packages/house-naming/src/house_naming/catalog.py',
        'packages/congress_api/src/congress_api/lake/receipt_metadata.py',
        'packages/congress_api/src/congress_api/lake/playlist_records.py',
        'packages/congress_api/src/congress_api/lake/committee_records.py',
        'packages/viewer_publication/src/viewer_publication/release_gate.py',
    } <= base_hashes.keys()
    checkout = tmp_path / 'checkout'
    for name in base_hashes:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert _definition_hashes(checkout) == base_hashes

    common = dict(
        parser_versions=VERSIONS,
        catalog_version='catalog-1',
        engine_revision='a' * 40,
        runtime_pins=dict(platform='local', binary_sha256='e' * 64),
        lake_versions=dict(captures='b' * 64),
        writer_settings=dict(row_group_rows=65536),
        snapshots={'captures': dict(metadata_location='/pinned/metadata.json')},
    )
    original_lock = (ROOT / 'uv.lock').read_text()
    original_sha = profile_record(**common, root=ROOT)['profile_sha256']

    def bump(pkg):
        pat = re.compile(r'(\[\[package\]\]\nname = "' + re.escape(pkg) + r'"\nversion = ")([^"]+)(")')
        updated, count = pat.subn(lambda m: m[1] + m[2] + '.post999' + m[3], original_lock)
        assert count == 1, pkg
        (checkout / 'uv.lock').write_text(updated)
        return profile_record(**common, root=checkout)

    for unrelated in ('aiohttp', 'boto3', 'pillow', 'pytest', 'trafilatura'):
        record = bump(unrelated)
        assert record['profile']['file_hashes'] == base_hashes, unrelated
        assert record['profile_sha256'] == original_sha, unrelated

    for imported in ('pyarrow', 'duckdb', 'jsonschema', 'pydantic'):
        record = bump(imported)
        assert record['profile']['file_hashes']['uv.lock'] != base_hashes['uv.lock'], imported
        assert record['profile_sha256'] != original_sha, imported


