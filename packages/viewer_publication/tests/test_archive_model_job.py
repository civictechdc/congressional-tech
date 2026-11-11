"""The model CLI plans without input access and executes the maintained producer."""
from contextlib import contextmanager
import json
import os
from pathlib import Path

import pytest


from archive_job_fixture import _Capture, _Submitted, fake_release, model_spec as spec, real_model_spec, versions

TEMPLATE = Path(__file__).resolve().parents[3]/'model/jobs/publish-model.json'


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
    with pytest.raises(ValueError,match='Parser versions must match the current definitions'):
        load_spec(write_spec(tmp_path,value))



def test_checked_in_job_specs_load():
    """The committed specs must pass their own loaders (2351caf4 added Explorer pins the loader refused)."""
    from viewer_publication import archive_backfill_job, archive_model_job, archive_publish_job
    jobs = Path(__file__).resolve().parents[3] / 'model/jobs'
    model = archive_model_job.load_spec(jobs / 'publish-model.json')
    assert set(model['parser_versions']) >= {'video_records', 'committee_records'}
    assert archive_publish_job.load_spec(jobs / 'publish.json')
    assert archive_backfill_job.load_spec(jobs / 'backfill-selective.json')['status'] == 'blocked'


def test_a_spec_pin_for_a_table_the_helper_omits_is_refused(tmp_path):
    from viewer_publication import archive_model_job
    jobs = Path(__file__).resolve().parents[3] / 'model/jobs'
    value = json.loads((jobs / 'publish-model.json').read_text())
    value['parser_versions']['video_records'] = dict(youtube_cache='0' * 64)
    path = jobs / '.stale-pin-test.json'
    try:
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError, match='Parser versions must match'):
            archive_model_job.load_spec(path)
    finally:
        path.unlink(missing_ok=True)


def entity_spec(tmp_path,*,spicy=True):
    """A model spec with entity inputs and, unless refused, the production spicy-regs pin shape."""
    from congress_api.lake import appearance_records,meeting_records
    from archive_job_fixture import spicy_pin
    value=spec(tmp_path)
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
    written = {path.name for path in Path(built['output']).glob('*.parquet')}
    assert {'meeting_coverage.parquet', 'videos.parquet', 'channels.parquet', 'recording_matches.parquet',
            'committee_records.parquet'} <= written


def test_explorer_inputs_come_together(tmp_path):
    from viewer_publication.archive_model_job import validate_spec
    value = entity_spec(tmp_path)
    value['video_records'] = dict(kind='parquet', path=str(tmp_path / 'video.parquet'), sha256='a' * 64, size=17)
    with pytest.raises(ValueError, match='Explorer tables require'):
        validate_spec(value, base=tmp_path)


def test_model_job_publishes_pinned_historical_matcher_rows(tmp_path):
    import csv
    import pyarrow.parquet as pq
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_model_job import execute, validate_spec
    from viewer_publication.historical_recording_matcher import SOURCE_FIELDS

    value, _, _ = real_model_spec(tmp_path)
    source = tmp_path / 'historical.csv'
    with source.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=SOURCE_FIELDS, restval='')
        writer.writeheader()
        writer.writerow(dict(package_id='CHRG-111hhrg54388', status='full_recording',
                             method='date window + title', score='60', video_ids='-AxBVdmECic'))
        writer.writerow(dict(package_id='CHRG-114hhrg93915', status='no_video_found', score=''))
        writer.writerow(dict(package_id='CHRG-114hhrg93915', status='not_public', score='0'))
    pin = file_pin(source)
    value['historical_recording_matcher'] = dict(path=str(source), **pin)
    pinned = validate_spec(value, base=tmp_path)
    bad = dict(pinned, historical_recording_matcher=dict(pinned['historical_recording_matcher'], sha256='0' * 64))
    with pytest.raises(ValueError, match='Pinned model input changed'):
        execute(bad)
    built = execute(pinned)
    output = Path(built['output'])
    artifact = pq.read_table(output / 'historical_recording_matches.parquet')
    assert artifact.column_names==[*SOURCE_FIELDS,'source_snapshot_sha256','source_record_ordinal']
    rows = artifact.to_pylist()
    assert [(row['source_record_ordinal'],row['package_id'],row['status'],row['score']) for row in rows] == [
        (1,'CHRG-111hhrg54388','full_recording',60),
        (2,'CHRG-114hhrg93915','no_video_found',None),
        (3,'CHRG-114hhrg93915','not_public',0),
    ]
    assert all(row['source_snapshot_sha256'] == pin['sha256'] for row in rows)
    assert rows[0]['method'] == 'date window + title' and rows[1]['method'] == ''
    schema = json.loads((output/'schema.json').read_text())
    table, = [entry for entry in schema['files'] if entry['name']=='historical_recording_matches.parquet']
    assert table['available'] and table['identity']['fields']==['source_snapshot_sha256','source_record_ordinal']
    assert json.loads((Path(built['scratch'])/'profile.json').read_text())['profile']['historical_recording_matcher']==pin


# The model-only build (W3): a completed daily's candidate bound into one build folder, the
# retired-link ledger its publisher passed, and a control build's expected release id.

@pytest.fixture(scope='module')
def fixture_inputs(tmp_path_factory):
    """One engine-derived input set for the tests that stop where the job is submitted."""
    value,_digest,_html=real_model_spec(tmp_path_factory.mktemp('inputs'))
    return value


def submitted_inputs(monkeypatch,tmp_path,argv):
    """Run the CLI with an engine that records the job it would run; return the job's inputs by name."""
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model_job import main
    real=NativeDatasets.from_config
    @contextmanager
    def capturing(path):
        with real(path) as engine:
            yield _Capture(engine,tmp_path/'submitted-job.json')
    monkeypatch.setattr(NativeDatasets,'from_config',capturing)
    with pytest.raises(_Submitted):
        main(argv)
    return {item['name']:item for item in json.loads((tmp_path/'submitted-job.json').read_text())['inputs']}


RETIRED_KEY=b'rrrrrrrr'


def base_release(tmp_path,*,ledger=True):
    """A live release as the ledger reads it; with its own ledger it carries one retired key."""
    retired=[dict(link_key=RETIRED_KEY,successor_key=None,last_release_id='d'*64,last_filename='r.pdf')] if ledger else None
    return fake_release(tmp_path/'base','b'*64,[('gone.pdf',b'gggggggg',[b'gggggggg'])],retired=retired)


@pytest.mark.parametrize('named',[None,'--ledger','--ledger-base'])
def test_the_named_ledger_reaches_the_model_job(tmp_path,monkeypatch,fixture_inputs,named):
    """Without a ledger the job's ledger inputs are the empty ones in its scratch (today's behaviour);
    a named one, ready-made or derived from a release as the publisher derives it, is what the job reads."""
    import pyarrow.parquet as pq
    from viewer_publication.release_gate import prior_links
    base=base_release(tmp_path);ready=tmp_path/'ready'
    prior_links(base,[],ready)
    build=tmp_path/'build'
    value=dict(fixture_inputs,output=str(build/'archive-release'),scratch=str(build/'archive-model'))
    argv=['--spec',write_spec(tmp_path,value),'--execute']
    if named:argv+=[named,str(ready if named=='--ledger' else base)]
    inputs=submitted_inputs(monkeypatch,tmp_path,argv)
    folder={None:build/'archive-model/ledger','--ledger':ready,'--ledger-base':build/'ledger'}[named]
    for name in ('prior_links','prior_sources','base_retired'):
        assert Path(inputs[name]['path'])==(folder/(name+'.parquet')).resolve()
    retired=pq.read_table(inputs['base_retired']['path'])['link_key'].to_pylist()
    assert retired==([] if named is None else [RETIRED_KEY])


def daily_candidate(root,*,definitions=None):
    """A candidate folder as the nightly leaves it: the completed daily's summary with its publication
    records, their provenance files, and the model intent sealed by the controller's own writer, whose
    profile holds the model definition hashes it was made with (by default this checkout's)."""
    from hashlib import md5,sha256
    from viewer_publication.archive_controller import _save_continuation
    from viewer_publication.archive_model import ROOT
    from viewer_publication.archive_model_job import TABLES
    from viewer_publication.archive_model_profile import _definition_hashes
    parsers,catalog=versions()
    held=root/'archive-daily-provenance';held.mkdir(parents=True)
    records=[]
    for index,family in enumerate(['recoveries','reviews','unreadable','verification','recording_decisions']):
        body=json.dumps(dict(fixture=index)).encode()+b'\n';name=f'{index:064x}-{index:032x}.jsonl'
        (held/name).write_bytes(body)
        records.append(dict(key=f'provenance/{family}/{index}.jsonl',etag=md5(body).hexdigest(),size=len(body),
            path='/elsewhere/nightly/candidate/archive-daily-provenance/'+name,sha256=sha256(body).hexdigest()))
    pins={name:dict(metadata_location=f's3://fixture-lake/archive/{name}/metadata/00001.metadata.json',
        table_uuid=f'00000000-0000-4000-8000-00000000000{index}',snapshot=1000+index,schema_id=0)
        for index,name in enumerate(TABLES)}
    summary=dict(status='completed',pins=pins,receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],new_receipt_keys=[],
        currentversions=dict(parsers=parsers,filename_readings=catalog),producers={},carried={},
        publication=dict(records=records,provenance=[dict(key=row['key'],etag=row['etag']) for row in records],deferred='0'*64))
    daily=root/'archive-daily';daily.mkdir()
    (daily/'daily-summary.json').write_text(json.dumps(summary,sort_keys=True))
    publish=root/'archive-publish';publish.mkdir()
    profile=dict(profile=dict(file_hashes=_definition_hashes(ROOT) if definitions is None else definitions))
    _save_continuation(publish/'model-intent.json',dict(version=1,identity='1'*64,profile=profile,entity_digests={},admitted_names=[],
        pointer=None,pointer_etag=None,input_digest='2'*64,
        daily_summary_sha256=sha256((daily/'daily-summary.json').read_bytes()).hexdigest()),seal=True)
    return summary


def engine_runtime(tmp_path):
    """A runtime file with paths relative to itself; never the real remote one."""
    runtime=tmp_path/'engine/runtime.json';runtime.parent.mkdir()
    runtime.write_text(json.dumps(dict(version=1,binary='bin/docspec',limits='limits.json',workspace='shared',timeout_seconds=60)))
    return runtime


def test_a_candidate_binds_its_daily_into_one_build_folder(tmp_path,capsys):
    """The daily's pins, catalog version and provenance records (read from the candidate's own copies), and
    the checkout's template for everything else; output, scratch, runtime and workspace in the build folder."""
    from viewer_publication.archive_model_job import PROVENANCE,TABLES,load_spec,main
    candidate=tmp_path/'candidate';summary=daily_candidate(candidate);runtime=engine_runtime(tmp_path)
    build=(tmp_path/'arm').resolve()
    assert main(['--from-candidate',str(candidate),'--build',str(build),'--runtime',str(runtime)])==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='planned' and report['executed'] is False and report['spec']==str(build/'model-spec.json')
    assert report['model_definition_changes_from_candidate']==[]
    bound=json.loads((build/'model-spec.json').read_text())
    for name in TABLES:
        assert bound[name]==dict(summary['pins'][name],kind='native_table')
    assert bound['catalog_version']==summary['currentversions']['filename_readings']
    held=candidate.resolve()/'archive-daily-provenance'
    for field,family in PROVENANCE.items():
        assert bound[field]==[dict(key=row['key'],path=str(held/Path(row['path']).name),sha256=row['sha256'],size=row['size'])
                              for row in summary['publication']['records'] if row['key'].split('/')[1]==family]
    assert sum(map(len,(bound[field] for field in PROVENANCE)))==len(summary['publication']['records'])
    assert (bound['output'],bound['scratch'],bound['engine_config'])==(
        str(build/'archive-release'),str(build/'archive-model'),str(build/'runtime.json'))
    origin=runtime.parent.resolve()
    assert json.loads((build/'runtime.json').read_text())==dict(version=1,binary=str(origin/'bin/docspec'),
        limits=str(origin/'limits.json'),workspace=str(build/'workspace'),timeout_seconds=60)
    template=load_spec(TEMPLATE)
    rest=set(template)-{*TABLES,*PROVENANCE,'catalog_version','output','scratch','engine_config'}
    assert rest and {name:bound[name] for name in rest}=={name:template[name] for name in rest}
    assert load_spec(build/'model-spec.json')==bound


def test_a_changed_model_binds_and_names_the_definition_files_it_changed(tmp_path,capsys):
    """Building a changed model on the candidate's pinned inputs is the command's purpose, and a changed
    model can still reproduce the release id; so nothing is refused, and the result line names every
    definition file added, removed or changed since the candidate's model intent. None: a control build."""
    from viewer_publication.archive_model import ROOT
    from viewer_publication.archive_model_job import main
    from viewer_publication.archive_model_profile import _definition_hashes
    current=_definition_hashes(ROOT);changed,dropped=sorted(current)[:2]
    recorded={**{name:pin for name,pin in current.items() if name!=dropped},changed:'0'*64,'model/sql/retired-step.sql':'1'*64}
    candidate=tmp_path/'candidate';daily_candidate(candidate,definitions=recorded)
    assert main(['--from-candidate',str(candidate),'--build',str(tmp_path/'arm'),'--runtime',str(engine_runtime(tmp_path))])==0
    report=json.loads(capsys.readouterr().out)
    assert report['model_definition_changes_from_candidate']==sorted([changed,dropped,'model/sql/retired-step.sql'])
    assert (tmp_path/'arm/model-spec.json').is_file()


@pytest.mark.parametrize('plant',['dropped_provenance_file','edited_daily_summary','no_model_intent'])
def test_a_candidate_that_differs_from_its_daily_refuses_before_the_build_folder(tmp_path,capsys,plant):
    from viewer_publication.archive_model_job import main
    candidate=tmp_path/'candidate';summary=daily_candidate(candidate);runtime=engine_runtime(tmp_path)
    dropped=Path(summary['publication']['records'][1]['path']).name
    if plant=='dropped_provenance_file':
        (candidate/'archive-daily-provenance'/dropped).unlink()
    elif plant=='edited_daily_summary':
        path=candidate/'archive-daily/daily-summary.json';edited=json.loads(path.read_text())
        edited['pins']['captures']['snapshot']+=1;path.write_text(json.dumps(edited,sort_keys=True))
    else:
        (candidate/'archive-publish/model-intent.json').unlink()
    with pytest.raises(SystemExit) as error:
        main(['--from-candidate',str(candidate),'--build',str(tmp_path/'arm'),'--runtime',str(runtime)])
    assert error.value.code==2
    expected={'dropped_provenance_file':'Provenance file not in the candidate: '+dropped,
              'edited_daily_summary':'Retained daily summary differs from the model continuation',
              'no_model_intent':'requires a completed model checkpoint or intent'}[plant]
    assert expected in capsys.readouterr().err
    assert not (tmp_path/'arm').exists()


@pytest.mark.parametrize('case',['ledger_file_missing','base_without_its_ledger','ledger_without_execute',
    'malformed_expected_id','candidate_build_without_a_ledger','candidate_build_with_an_incomplete_ledger',
    'candidate_build_with_a_base_without_its_ledger','candidate_without_a_build','existing_build'])
def test_build_options_refuse_before_inputs_or_runtime(tmp_path,capsys,case):
    """A bad ledger refuses before the candidate is bound, so the build folder stays fresh for a rerun."""
    from viewer_publication.archive_model_job import main
    value=spec(tmp_path);path=write_spec(tmp_path,value)
    partial=tmp_path/'partial-ledger';partial.mkdir();(partial/'prior_links.parquet').write_bytes(b'')
    bare=str(base_release(tmp_path,ledger=False))
    candidate=tmp_path/'candidate';daily_candidate(candidate);runtime=engine_runtime(tmp_path);arm=tmp_path/'arm'
    from_candidate=['--from-candidate',str(candidate),'--runtime',str(runtime)]
    candidate_build=[*from_candidate,'--build',str(arm),'--execute']
    if case=='existing_build':arm.mkdir()
    argv,expected={
        'ledger_file_missing':(['--spec',path,'--execute','--ledger',str(partial)],'Ledger folder lacks prior_sources.parquet'),
        'base_without_its_ledger':(['--spec',path,'--execute','--ledger-base',bare],'has no retired_links'),
        'ledger_without_execute':(['--spec',path,'--ledger',str(partial)],'apply only with --execute'),
        'malformed_expected_id':(['--spec',path,'--execute','--expect-release-id','77673bf'],'12 to 64 lowercase hex'),
        'candidate_build_without_a_ledger':(candidate_build,'needs the ledger its publisher passed'),
        'candidate_build_with_an_incomplete_ledger':([*candidate_build,'--ledger',str(partial)],'Ledger folder lacks prior_sources.parquet'),
        'candidate_build_with_a_base_without_its_ledger':([*candidate_build,'--ledger-base',bare],'has no retired_links'),
        'candidate_without_a_build':(from_candidate,'--from-candidate needs --build and --runtime'),
        'existing_build':([*from_candidate,'--build',str(arm)],'The build folder must be fresh'),
    }[case]
    with pytest.raises(SystemExit) as error:main(argv)
    assert error.value.code==2 and expected in capsys.readouterr().err
    assert not (tmp_path/'release').exists() and not (tmp_path/'model').exists()
    assert case=='existing_build' or not arm.exists()


@pytest.mark.parametrize('expected',['ab'*6,'ab'*32,'cd'*6])
def test_a_control_build_fails_naming_both_ids_when_its_release_differs(tmp_path,capsys,monkeypatch,expected):
    """The result line is printed either way, so a differing arm still reports its id, rows and paths."""
    import viewer_publication.archive_model as model
    from viewer_publication.archive_model_job import main
    value=dict(pinned_local_spec(tmp_path),engine_config=os.environ['DOCSPEC_JOB_CONFIG'])
    built='ab'*32
    monkeypatch.setattr(model,'build_release',lambda **_:dict(release_id=built,files=[dict(name='list.parquet',rows=3)]))
    code=main(['--spec',write_spec(tmp_path,value),'--execute','--expect-release-id',expected])
    out,err=capsys.readouterr()
    report=json.loads(out)
    assert report['release_id']==built and report['rows']=={'list.parquet':3} and report['output']==value['output']
    # Before the build every build states its runtime (ct-64t4); a matching one says nothing else.
    ran,_,err=err.partition('\n')
    assert ran=='[docspec-runtime] '+json.dumps(report['engine_runtime'],sort_keys=True)
    if expected.startswith('ab'):
        assert code==0 and not err
    else:
        assert code==1 and built in err and expected in err
