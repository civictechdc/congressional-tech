"""The model CLI plans without input access and executes the maintained producer."""
import json
from pathlib import Path

import pytest


from archive_job_fixture import model_spec as spec, real_model_spec


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
    import pyarrow.parquet as pq
    from viewer_publication.archive_model_job import main
    value,digest,_html=real_model_spec(tmp_path)
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


def pinned_local_spec(tmp_path):
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import load_spec
    value=spec(tmp_path)
    source=tmp_path/'selected.parquet';source.write_bytes(b'selected A')
    for name in ['captures','readings','filename_readings']:
        value[name]=dict(kind='parquet',path=str(source),**file_pin(source))
    decision=tmp_path/'review.jsonl';decision.write_bytes(b'{"selected":"A"}\n')
    value['review_files']=[dict(key='provenance/reviews/fixture.jsonl',path=str(decision),**file_pin(decision))]
    return load_spec(write_spec(tmp_path,value))


@pytest.mark.parametrize('target',['captures','review_files'])
def test_selected_local_files_stay_under_custody_during_consumption(tmp_path,target):
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path)
    item=value[target][0] if target=='review_files' else value[target]
    original=Path(item['path']);selected=original.read_bytes()
    # Removing the original link changes ctime: custody must refuse acceptance,
    # while the private retained path must still serve A rather than replacement B.
    with pytest.raises(ValueError,match='custody changed'):
        with model_arguments(value) as arguments:
            entry=arguments[target][0] if target=='review_files' else arguments[target]
            retained=Path(entry['path'])
            assert retained!=original and retained.read_bytes()==selected
            assert arguments['captures']['path']==arguments['readings']['path']==arguments['filename_readings']['path']
            original.unlink();original.write_bytes(b'replacement B')
            assert retained.read_bytes()==selected
    assert original.read_bytes()==b'replacement B'


@pytest.mark.parametrize('target',['captures','review_files'])
def test_in_place_local_mutation_refuses_after_consumption(tmp_path,target):
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path)
    item=value[target][0] if target=='review_files' else value[target]
    with pytest.raises(ValueError,match='custody changed'):
        with model_arguments(value) as arguments:
            entry=arguments[target][0] if target=='review_files' else arguments[target]
            Path(item['path']).write_bytes(b'in-place mutation')
            assert Path(entry['path']).read_bytes()==b'in-place mutation'


def test_provenance_etag_matches_exact_local_bytes_in_retained_inputs(tmp_path):
    from hashlib import md5
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path);item=value['review_files'][0]
    etag='"'+md5(Path(item['path']).read_bytes()).hexdigest().upper()+'"'
    alias=dict(item,key='provenance/reviews/alias.jsonl');value['review_files'].append(alias)
    with model_arguments(value,provenance_etags={item['key']:etag,alias['key']:etag.strip(chr(34)).lower()}) as arguments:
        assert Path(arguments['review_files'][0]['path']).read_bytes()==Path(item['path']).read_bytes()
        assert arguments['review_files'][0]['path']==arguments['review_files'][1]['path']
    assert not list(tmp_path.glob('.model-inputs-*'))


@pytest.mark.parametrize('failure',['changed','opaque','multipart','missing','extra','alias_conflict'])
def test_invalid_provenance_etag_binding_refuses_before_yield(tmp_path,failure):
    from hashlib import md5
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path);item=value['review_files'][0]
    etags={item['key']:md5(Path(item['path']).read_bytes()).hexdigest()}
    if failure=='changed':etags[item['key']]='0'*32
    elif failure=='opaque':etags[item['key']]='opaque'
    elif failure=='multipart':etags[item['key']]='a'*32+'-2'
    elif failure=='missing':etags={}
    elif failure=='extra':etags['provenance/reviews/extra.jsonl']='a'*32
    else:
        value['review_files'].append(dict(item,key='provenance/reviews/alias.jsonl'))
        etags['provenance/reviews/alias.jsonl']='a'*32
    with pytest.raises(ValueError,match='provenance|ETag'):
        with model_arguments(value,provenance_etags=etags):
            pytest.fail('Unbound provenance reached model consumption')
