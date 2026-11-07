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


def test_model_plan_preserves_selected_historical_versions(tmp_path):
    from viewer_publication.archive_model_job import load_spec

    value=spec(tmp_path)
    value['parser_versions']['sniff']='1'*64
    value['catalog_version']='2'*64
    value['readings_version']='3'*64
    selected=load_spec(write_spec(tmp_path,value))
    assert selected['parser_versions']==value['parser_versions']
    assert selected['catalog_version']==value['catalog_version']
    assert selected['readings_version']==value['readings_version']
    assert not Path(value['producer_proof']['path']).exists()


@pytest.mark.parametrize('change', ['mutable','empty_parser','empty_catalog','unknown'])
def test_mutable_selectors_or_missing_definitions_refuse_before_runtime(tmp_path,capsys,change):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path)
    if change=='mutable':value['captures']=dict(kind='native_table',catalog_root='/not-opened',table='captures')
    elif change=='empty_parser':value['parser_versions']['sniff']=''
    elif change=='empty_catalog':value['catalog_version']=''
    else:value['unexpected_option']=True
    with pytest.raises(SystemExit) as error:main(['--spec',write_spec(tmp_path,value),'--execute'])
    assert error.value.code==2
    message=capsys.readouterr().err
    expected={'mutable':'Native input selector requires exact metadata','empty_parser':'Model profile requires pinned parsers',
              'empty_catalog':'exact catalog and combined readings version selections','unknown':'Model job has unknown fields'}
    assert expected[change] in message
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()


def test_changed_local_pin_refuses_before_retaining_inputs(tmp_path):
    from viewer_publication.archive_model_job import load_spec,model_arguments
    value=spec(tmp_path)
    for name in ['captures','readings','filename_readings']:
        path=Path(value[name]['path']);path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Pinned model input changed'):
        with model_arguments(load_spec(write_spec(tmp_path,value))):
            pytest.fail('Changed input reached model preparation')
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()


def test_pending_spec_refuses_without_runtime_or_storage(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    pending=dict(status='blocked',reason='owner binding pending',engine_config='/not-opened/runtime.json')
    assert main(['--spec',write_spec(tmp_path,pending),'--execute'])==2
    assert json.loads(capsys.readouterr().out)==dict(status='blocked',reason='owner binding pending')


@pytest.mark.parametrize('defect',['missing','null','missing_pin','blank_policy'])
def test_model_refuses_unbound_capture_policy_before_runtime_or_storage(tmp_path,capsys,defect):
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path)
    if defect=='missing':value.pop('recovery_requirements')
    elif defect=='null':value['recovery_requirements']=None
    elif defect=='missing_pin':value['recovery_requirements'].pop('sha256')
    else:value['recovery_requirements']['acceptance_policy']=' '
    with pytest.raises(SystemExit) as error:
        main(['--spec',write_spec(tmp_path,value),'--execute'])
    assert error.value.code==2
    expected={'missing':'pinned recovery requirements','null':'pinned recovery requirements',
              'missing_pin':'immutable fields','blank_policy':'pinned recovery policy'}
    assert expected[defect] in capsys.readouterr().err
    assert not (tmp_path/'model').exists() and not (tmp_path/'release').exists()
    assert not (tmp_path/'unopened-runtime.json').exists()


def test_direct_preparation_refuses_absent_policy_before_creating_inputs(tmp_path):
    from viewer_publication.archive_model import prepare_model_inputs
    with pytest.raises(ValueError,match='pinned recovery requirements'):
        prepare_model_inputs(captures='unopened',readings='unopened',filename_readings='unopened',
            parser_versions={},catalog_version='unopened',engine=None,scratch=tmp_path/'scratch',
            recovery_requirements=None,readings_version='unopened')
    assert not (tmp_path/'scratch').exists()


@pytest.mark.parametrize('key',[
    'provenance/recoveries/accepted-backup.json',
    'provenance/recoveries/archive/fixture.jsonl',
    'provenance/reviews/fixture.jsonl',
])
def test_model_input_requires_a_record_of_its_declared_provenance_kind(tmp_path,key):
    from viewer_publication.archive_model_job import load_spec
    value=spec(tmp_path)
    value['recovery_files']=[dict(key=key,path='not-opened.json',sha256='a'*64,size=17)]
    with pytest.raises(ValueError,match='provenance record'):
        load_spec(write_spec(tmp_path,value))
    assert not (tmp_path/'not-opened.json').exists()


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


def test_existing_output_refuses_before_input_retention(tmp_path):
    from viewer_publication.archive_model_job import load_spec,model_arguments
    value=spec(tmp_path);Path(value['output']).mkdir()
    with pytest.raises(ValueError,match='must be fresh'):
        with model_arguments(load_spec(write_spec(tmp_path,value))):
            pytest.fail('Existing output reached model preparation')
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
    # The custody tests use arbitrary bytes; policy rows are not decoded here.
    value['recovery_requirements']=dict(path=str(source),**file_pin(source),acceptance_policy='recovery-identity-v1')
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
    assert Path(arguments['review_files'][0]['path']).is_file()
    assert Path(arguments['captures']['path']).is_file()


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


def test_checked_provenance_cache_is_retained_without_another_hash_pass(tmp_path, monkeypatch):
    from hashlib import md5
    import viewer_publication.archive_model_job as job
    from congress_shared.custody import verify_local_file
    value=pinned_local_spec(tmp_path);item=value['review_files'][0]
    checked=verify_local_file(item['path'],additional_hashes={'md5':md5})
    hashed=[];original=job.file_identity
    def record(path,**kwargs):
        hashed.append(str(path));return original(path,**kwargs)
    monkeypatch.setattr(job,'file_identity',record)
    with job.model_arguments(value,provenance_etags={item['key']:checked['md5']},
                             verified_files={item['path']:checked}) as arguments:
        assert Path(arguments['review_files'][0]['path']).read_bytes()==Path(item['path']).read_bytes()
        assert arguments['review_files'][0]['path']!=item['path']
    assert item['path'] not in hashed
    assert hashed==[value['captures']['path']]


@pytest.mark.parametrize('failure',['changed','checksum','plain_mapping','missing_md5'])
def test_checked_provenance_cache_refuses_invalid_custody_before_consumption(tmp_path,failure):
    from hashlib import md5
    from congress_shared.custody import verify_local_file
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path);item=value['review_files'][0]
    checked=verify_local_file(item['path'],additional_hashes={'md5':md5} if failure!='missing_md5' else None)
    etag=md5(Path(item['path']).read_bytes()).hexdigest()
    if failure=='changed':Path(item['path']).write_bytes(b'changed')
    elif failure=='checksum':item['sha256']='0'*64
    elif failure=='plain_mapping':checked=dict(checked)
    with pytest.raises(ValueError,match='custody|checksum|provenance'):
        with model_arguments(value,provenance_etags={item['key']:etag},verified_files={item['path']:checked}):
            pytest.fail('Unchecked cache reached native consumption')


@pytest.mark.parametrize('table',['meeting_records','appearance_records'])
@pytest.mark.parametrize('kind',['composite_scalar','arbitrary_scalar'])
def test_validate_spec_rejects_scalar_composite_entity_versions(tmp_path,table,kind):
    from congress_api.lake import appearance_records,meeting_records
    from viewer_publication.archive_model_job import load_spec
    value=spec(tmp_path)
    value['parser_versions']['meeting_records']=meeting_records.current_versions()
    value['parser_versions']['appearance_records']=appearance_records.current_versions()
    assert load_spec(write_spec(tmp_path,value))['parser_versions']['meeting_records']==meeting_records.current_versions()
    mod=meeting_records if table=='meeting_records' else appearance_records
    value['parser_versions'][table]=mod.current_version() if kind=='composite_scalar' else 'scalar-hash'
    with pytest.raises(ValueError,match='exact source-scoped '+table+' parser_versions'):
        load_spec(write_spec(tmp_path,value))



def test_checked_in_policy_free_job_refuses_until_production_requirements_are_selected():
    """Retain the old pins without treating a missing production policy as v1 permission."""
    from viewer_publication import archive_backfill_job, archive_model_job, archive_publish_job
    jobs = Path(__file__).resolve().parents[3] / 'model/jobs'
    model = json.loads((jobs / 'publish-model.json').read_text())
    assert set(model['parser_versions']) >= {'video_records', 'committee_records'}
    assert 'recovery_requirements' not in model
    with pytest.raises(ValueError,match='pinned recovery requirements'):
        archive_model_job.load_spec(jobs / 'publish-model.json')
    with pytest.raises(ValueError,match='pinned recovery requirements'):
        archive_publish_job.load_spec(jobs / 'publish.json')
    assert archive_backfill_job.load_spec(jobs / 'backfill-selective.json')['status'] == 'blocked'


def test_a_spec_pin_for_a_table_the_helper_omits_is_refused(tmp_path):
    from viewer_publication import archive_model_job
    value=spec(tmp_path)
    value['parser_versions']['video_records'] = dict(youtube_cache='0' * 64)
    with pytest.raises(ValueError, match='exact source-scoped video_records parser_versions'):
        archive_model_job.load_spec(write_spec(tmp_path,value))


def entity_spec(tmp_path,*,spicy=True):
    """A model spec with entity inputs and, unless refused, the production spicy-regs pin shape."""
    from congress_api.lake import appearance_records,meeting_records
    from archive_job_fixture import empty_recovery_requirements,spicy_pin
    value=spec(tmp_path)
    value['recovery_requirements']=empty_recovery_requirements(tmp_path)
    value['parser_versions'].update(meeting_records=meeting_records.current_versions(),
                                    appearance_records=appearance_records.current_versions())
    value['meeting_records']=dict(kind='parquet',path=str(tmp_path/'meeting_records.parquet'),sha256='a'*64,size=17)
    if spicy:value['spicy_regs']=spicy_pin(tmp_path)
    return value


def test_entity_inputs_refuse_without_pinned_spicy_regs(tmp_path):
    from viewer_publication.archive_model_job import load_spec
    value=entity_spec(tmp_path,spicy=False)
    with pytest.raises(ValueError,match='require pinned spicy-regs generations'):load_spec(write_spec(tmp_path,value))
    # A bare path names no content: it must carry its SHA-256 and size (F2).
    value['spicy_regs']=str(tmp_path/'spicy-regs.json')
    with pytest.raises(ValueError,match='immutable fields'):load_spec(write_spec(tmp_path,value))


def test_spicy_regs_arguments_carry_exactly_the_stated_generations(tmp_path):
    from archive_job_fixture import SPICY_GENERATIONS
    from viewer_publication.archive_model import SPICY_SCHEMAS
    from viewer_publication.archive_model_job import _spicy_arguments,load_spec
    value=load_spec(write_spec(tmp_path,entity_spec(tmp_path)))
    held=[]
    def hold(item):held.append(item['path']);return item['path']
    arguments=_spicy_arguments(value['spicy_regs'],hold)
    assert arguments['generations']==SPICY_GENERATIONS
    assert set(arguments['tables'])==set(SPICY_SCHEMAS)
    # The spec file and every table go through custody; nothing else is read.
    assert held[0]==value['spicy_regs']['path'] and len(held)==1+len(SPICY_SCHEMAS)


@pytest.mark.parametrize('change',['missing_family','made_up_digest','other_generation','unpinned_table','changed_bytes'])
def test_spicy_regs_input_refuses_anything_not_stated_and_pinned(tmp_path,change):
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import model_arguments,load_spec
    value=entity_spec(tmp_path)
    path=Path(value['spicy_regs']['path']);stated=json.loads(path.read_text())
    table=stated['tables']['spicy_committees']
    if change=='missing_family':del stated['generations']['amendments']
    elif change=='made_up_digest':stated['generations']['members']='spicy-regs:members'
    elif change=='other_generation':table['path']=table['path'].replace('1'*64,'2'*64)
    elif change=='unpinned_table':del table['sha256']
    if change=='changed_bytes':(path.parent/table['path']).write_bytes(b'not the pinned table')
    else:path.write_text(json.dumps(stated))
    value['spicy_regs']=dict(path=str(path),**file_pin(path))
    for name in ['captures','readings','filename_readings','meeting_records']:
        source=tmp_path/(name+'.parquet');source.write_bytes(name.encode())
        value[name]=dict(kind='parquet',path=str(source),**file_pin(source))
    expected={'missing_family':'generation digest for each','made_up_digest':'generation digest for each',
              'other_generation':'not under its stated generation','unpinned_table':'immutable fields',
              'changed_bytes':'Pinned model input changed'}[change]
    with pytest.raises(ValueError,match=expected):
        with model_arguments(load_spec(write_spec(tmp_path,value))):
            pytest.fail('Unpinned spicy-regs input reached the producer')


def test_entity_release_never_fabricates_a_generation(tmp_path):
    from archive_job_fixture import SPICY_GENERATIONS,spicy_input
    from viewer_publication.archive_model import _prepare_spicy_inputs
    with pytest.raises(ValueError,match='require pinned spicy-regs generations'):
        _prepare_spicy_inputs(tmp_path/'a',None,True)
    stated={k:v for k,v in SPICY_GENERATIONS.items() if k!='nominations'}
    with pytest.raises(ValueError,match='generation digest for each'):
        _prepare_spicy_inputs(tmp_path/'b',spicy_input(generations=stated),True)
    # Without entity files no generation is named at all.
    assert _prepare_spicy_inputs(tmp_path/'c',None,False)[1] is None
    assert _prepare_spicy_inputs(tmp_path/'d',spicy_input(),True)[1]==SPICY_GENERATIONS


def test_production_spec_pins_the_spicy_regs_input():
    """The production job states its spicy-regs pin; the producer cannot run without it."""
    value=json.loads((Path(__file__).parents[3]/'model/jobs/publish-model.json').read_text())
    assert set(value['spicy_regs'])=={'path','sha256','size'}


def test_the_production_model_job_writes_the_explorer_files(tmp_path):
    # ct-gi01 gap: the release schema declares five Explorer files, but the model job spec (the
    # path the publish controller and the selective job use) had no field for their inputs,
    # so only the frozen builder could write them.
    import pyarrow.parquet as pq
    from congress_api.lake import committee_records, playlist_records, video_records
    from congress_api.retention.provenance import file_pin
    from archive_job_fixture import real_model_spec, spicy_pin
    from viewer_publication.archive_model_job import execute, validate_spec
    value, _, _ = real_model_spec(tmp_path, entities=True)
    value['spicy_regs'] = spicy_pin(tmp_path)
    for name, module in (('video_records', video_records), ('committee_records', committee_records),
                         ('playlist_records', playlist_records)):
        path = tmp_path / (name + '.parquet'); pq.write_table(module.table([]), path)
        value[name] = dict(kind='parquet', path=str(path), **file_pin(path))
        value['parser_versions'][name] = module.current_versions()
    decisions = tmp_path / 'decisions.jsonl'
    decisions.write_text(json.dumps(dict(id='a' * 64, subject_kind='event', subject_id='115538', verdict='found',
        video_refs=['https://example.test/watch'], note=None, disputed_by=None, decided_at=None, supersedes=None)) + '\n')
    value['recording_decision_files'] = [dict(key='provenance/recording_decisions/a.jsonl', path=str(decisions), **file_pin(decisions))]
    built = execute(validate_spec(value, base=tmp_path))
    written = {name for name,path in built['files'].items() if name.endswith('.parquet') and Path(path).is_file()}
    assert {'meeting_coverage.parquet', 'videos.parquet', 'channels.parquet', 'recording_matches.parquet',
            'committee_records.parquet'} <= written


def test_explorer_inputs_come_together(tmp_path):
    from viewer_publication.archive_model_job import validate_spec
    value = entity_spec(tmp_path)
    value['video_records'] = dict(kind='parquet', path=str(tmp_path / 'video.parquet'), sha256='a' * 64, size=17)
    with pytest.raises(ValueError, match='Explorer tables require'):
        validate_spec(value, base=tmp_path)


def test_missing_producer_proof_refuses_before_runtime_or_input_access(tmp_path):
    from viewer_publication.archive_model_job import execute
    value=spec(tmp_path)
    value['producer_proof']=None
    with pytest.raises(ValueError,match='pinned native receipt'):
        execute(value)
    assert not Path(value['scratch']).exists()
    assert not (tmp_path/'model-inputs').exists()
    assert not Path(value['native_scope']['workspace']).exists()


def test_uncertain_native_admission_preserves_the_original_input_paths(tmp_path):
    from viewer_publication.archive_format import NativeReleaseNotReady
    from viewer_publication.archive_model_job import model_arguments
    value=pinned_local_spec(tmp_path)
    with pytest.raises(NativeReleaseNotReady):
        with model_arguments(value) as arguments:
            paths={Path(arguments[name]['path']) for name in ('captures','readings','filename_readings')}
            paths.update(Path(item['path']) for item in arguments['review_files'])
            held={path:path.read_bytes() for path in paths}
            raise NativeReleaseNotReady('preparation',dict(status='unknown'))
    assert {path:path.read_bytes() for path in paths}==held
    with pytest.raises(FileExistsError):
        with model_arguments(value):
            pytest.fail('A retry must consume the original prepared request')


def test_unapproved_runtime_refuses_before_capturing_a_new_model_request(tmp_path):
    from types import SimpleNamespace
    from viewer_publication.archive_model import build_prepared_release
    value=spec(tmp_path)
    def changed_runtime():
        raise ValueError('binary differs from its approved SHA-256')
    with pytest.raises(ValueError,match='approved SHA-256'):
        build_prepared_release(dict(scratch=tmp_path/'scratch'),
            engine=SimpleNamespace(verify_runtime=changed_runtime,binary_sha256='a'*64,source_revision='b'*40,limits='unused'),
            native_scope=value['native_scope'],
            producer_proof=None,producer_definition=None,output=tmp_path/'release')
    assert not (tmp_path/'scratch').exists()
    assert not (tmp_path/'native-workspace').exists()


def test_prepared_resume_requires_its_original_digest_and_explicit_runtime(tmp_path,capsys):
    from viewer_publication.archive_model_job import main
    with pytest.raises(SystemExit) as error:
        main(['--prepared-request',str(tmp_path/'request.json'),'--execute'])
    assert error.value.code==2
    assert 'requires its SHA-256 and explicit engine config' in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('missing',['binary_sha256','source_revision','limits'])
def test_model_runtime_requires_all_execution_pins_before_verification(missing):
    from types import SimpleNamespace
    from viewer_publication.archive_model import require_model_runtime
    values=dict(binary_sha256='a'*64,source_revision='b'*40,limits='unused')
    values[missing]=None
    def must_not_run():
        pytest.fail('Missing runtime pins reached executable verification')
    with pytest.raises(ValueError,match='binary, source revision and host limit pins'):
        require_model_runtime(SimpleNamespace(**values,verify_runtime=must_not_run))


@pytest.mark.parametrize('prerequisites',[None,[]])
def test_original_model_request_cannot_resume_without_its_producer_requirements(tmp_path,prerequisites):
    from hashlib import sha256
    from types import SimpleNamespace
    from viewer_publication.archive_format import execute_native_release
    native=dict(action='prepare')
    if prerequisites is not None:native['prerequisites']=prerequisites
    raw=json.dumps(dict(native=native,workspace=str(tmp_path/'native'),origin=dict(kind='model'))).encode()
    path=tmp_path/'request.json';path.write_bytes(raw)
    def must_not_run(*args,**kwargs):
        pytest.fail('A model request without producer obligations reached native submission')
    with pytest.raises(ValueError,match='original native producer proof bindings'):
        execute_native_release(dict(path=str(path),sha256=sha256(raw).hexdigest()),
            adapter=SimpleNamespace(managed_job=must_not_run))
    assert not (tmp_path/'native').exists()
