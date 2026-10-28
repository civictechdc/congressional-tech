"""The model CLI plans without input access and executes the maintained producer."""
import hashlib
import json
import os
from pathlib import Path

import pytest


def versions():
    from congress_api.lake import readings,filenames
    return {p:readings.current_version(p) for p in ['sniff','html','xml','json']},filenames.current_version()


def spec(tmp_path):
    parsers,catalog=versions()
    return dict(version=1,engine_config=str(tmp_path/'unopened-runtime.json'),
        **{name:dict(kind='parquet',path=str(tmp_path/(name+'.parquet')),sha256='a'*64,size=17)
           for name in ['captures','readings','filename_readings']},
        parser_versions=parsers,catalog_version=catalog,output=str(tmp_path/'release'),scratch=str(tmp_path/'model'))


def write_spec(tmp_path,value):
    path=tmp_path/'spec.json';path.write_text(json.dumps(value));return str(path)


def test_plan_is_default_and_opens_no_runtime_or_inputs(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path)
    value['captures']=dict(kind='native_table',metadata_location='s3://fixture-lake/archive/captures/metadata/00000.metadata.json',
        table_uuid='00000000-0000-4000-8000-000000000001',snapshot=None,schema_id=0)
    assert main(['--spec',write_spec(tmp_path,value)])==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='planned' and report['executed'] is False
    assert report['inputs']['captures']==value['captures']
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()
    assert not (tmp_path/'unopened-runtime.json').exists()


@pytest.mark.parametrize('change', ['mutable','old_parser','old_catalog','unknown'])
def test_mutable_selectors_or_noncurrent_definitions_refuse_before_runtime(tmp_path,capsys,change):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path)
    if change=='mutable':value['captures']=dict(kind='native_table',catalog_root='/not-opened',table='captures')
    elif change=='old_parser':value['parser_versions']['sniff']='old'
    elif change=='old_catalog':value['catalog_version']='old'
    else:value['unexpected_option']=True
    with pytest.raises(SystemExit) as error:main(['--spec',write_spec(tmp_path,value),'--execute'])
    assert error.value.code==2
    message=capsys.readouterr().err
    expected={'mutable':'Native input selector requires exact metadata','old_parser':'Parser versions must match the current definitions',
              'old_catalog':'Catalog version must match the current definition','unknown':'Model job has unknown fields'}
    assert expected[change] in message
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()


def test_changed_local_pin_refuses_before_runtime_creation(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path)
    for name in ['captures','readings','filename_readings']:
        path=Path(value[name]['path']);path.write_bytes(b'changed')
    with pytest.raises(SystemExit) as error:main(['--spec',write_spec(tmp_path,value),'--execute'])
    assert error.value.code==2 and 'Pinned model input changed' in capsys.readouterr().err
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()


def test_pending_spec_refuses_without_runtime_or_storage(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    pending=dict(status='blocked',reason='owner binding pending',engine_config='/not-opened/runtime.json')
    assert main(['--spec',write_spec(tmp_path,pending),'--execute'])==2
    assert json.loads(capsys.readouterr().out)==dict(status='blocked',reason='owner binding pending')


def test_model_cli_executes_real_raw_lake_fixture(tmp_path,capsys):
    import gzip
    import pyarrow.parquet as pq
    from congress_api.lake import readings,filenames
    from congress_api.lake.captures import stage_captures
    from congress_api.retention.provenance import file_pin,parquet_output,run_job
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model_job import main
    runtime=os.environ['DOCSPEC_JOB_CONFIG'];engine=NativeDatasets.from_config(runtime)
    raw=tmp_path/'raw';raw.mkdir()
    html=b'<html><head><title>Retained CLI report</title></head><body><p>'+b'Substantive retained report evidence. '*100+b'</p></body></html>'
    digest=hashlib.sha256(html).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest+'.gz'
    stored=gzip.compress(html,mtime=0);body=raw/key;body.parent.mkdir(parents=True);body.write_bytes(stored)
    url='https://fixture.test/report.html'
    row=dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',outcome='stored',
        requested_url=url,url=url,http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
        captures=[dict(sha256=digest,bytes=len(html),media_type='text/html',fidelity='exact-bytes',
            sniffed_format='html',sniff_version=readings.current_version('sniff'),stored_suffix='.gz',
            stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())])
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz';receipt.parent.mkdir(parents=True)
    receipt.write_bytes(gzip.compress((json.dumps(row)+'\n').encode(),mtime=0))
    qualification=tmp_path/'receipt-pin.json';qualification.write_text(json.dumps(dict(path=str(receipt),**file_pin(receipt),producer='fixture creation')))
    captures=stage_captures([dict(key=receipt.relative_to(raw).as_posix(),path=str(receipt),qualification=str(qualification))],engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
    inventory=tmp_path/'inventory';inventory.mkdir()
    run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
        parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
        stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
    pages=readings.stage_once(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,
        engine=engine,work=tmp_path/'reading-stage',decided_at='2026-10-27T12:00:00Z')
    names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'filename-stage',decided_at='2026-10-27T12:00:00Z')
    value=spec(tmp_path);value['engine_config']=runtime
    for name,path in [('captures',captures),('readings',pages['readings']),('filename_readings',names['readings'])]:
        value[name]=dict(kind='parquet',path=str(path),**file_pin(path))
    assert main(['--spec',write_spec(tmp_path,value),'--execute'])==0
    report=json.loads(capsys.readouterr().out)
    manifest=json.loads((tmp_path/'release/manifest.json').read_text())
    assert report['status']=='built' and report['release_id']==manifest['release_id']
    listed=pq.read_table(tmp_path/'release/list.parquet').to_pylist()
    detail=pq.read_table(tmp_path/'release/detail.parquet').to_pylist()
    assert len(listed)==len(detail)==1 and listed[0]['title']=='Retained CLI report'
    assert detail[0]['saved_body']==bytes.fromhex(digest) and detail[0]['saved_suffix']=='.gz'


def test_existing_output_refuses_before_input_or_runtime_access(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path);Path(value['output']).mkdir()
    with pytest.raises(SystemExit) as error:main(['--spec',write_spec(tmp_path,value),'--execute'])
    assert error.value.code==2 and 'must be fresh' in capsys.readouterr().err
    assert not Path(value['scratch']).exists()
