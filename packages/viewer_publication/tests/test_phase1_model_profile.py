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
