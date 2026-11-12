"""Every model run records which runtime file, binary and limits it ran under (ct-64t4).

`docspec_client.client` owns the runtime file: `choose_runtime` keeps the pipeline's fallback unchanged (a named
runtime file that is missing gives way to the one DOCSPEC_RUNTIME_CONFIG names) and `runtime_record` says what was
chosen and why, the runtime file, binary and limits by path and the sha256 of their bytes, and the limits' values.
The model job prints it before the build and returns it in its result line; the publisher prints it and seals it
into its model continuation in the candidate folder. Runtimes here are constructed and their binary never runs.
The decoys a wrong reading would pick up: this session's own runtime (the local test limits) and a second
runtime file with other limits.
"""
import json
import os
from pathlib import Path

import pytest
from docspec_client.client import runtime_record

from archive_job_fixture import MAC_LIMITS, constructed_runtime, real_model_spec, runtime_ran
from test_archive_model_job import base_release, daily_candidate, pinned_local_spec, write_spec

LINE = '[docspec-runtime] '
HOSTED = dict(MAC_LIMITS, memory_bytes=10 << 30, scratch_bytes=10 << 30)


def logged(err):
    """The runtime records a run printed, parsed."""
    return [json.loads(line[len(LINE):]) for line in err.splitlines() if line.startswith(LINE)]


def test_the_session_runtime_is_a_decoy_with_other_limits():
    """Each record below must hold the Mac's limits; one read from this session's runtime would not."""
    session = runtime_record(os.environ['DOCSPEC_JOB_CONFIG'], {})  # resolves a relative limits path as the client does
    assert session['limits']['values']['memory_bytes'] != MAC_LIMITS['memory_bytes']


def run_model(monkeypatch, capsys, argv):
    """The model CLI with its build replaced: (result line, stderr printed before the build)."""
    import viewer_publication.archive_model as model
    from viewer_publication.archive_model_job import main
    before = []
    def build_release(**_):
        before.append(capsys.readouterr().err)
        return dict(release_id='ab' * 32, files=[dict(name='list.parquet', rows=1)])
    monkeypatch.setattr(model, 'build_release', build_release)
    assert main(argv) == 0
    (printed,) = before
    return json.loads(capsys.readouterr().out), printed


def model_job(tmp_path, monkeypatch, capsys, engine_config):
    raw = dict(pinned_local_spec(tmp_path))
    if engine_config is None:
        raw.pop('engine_config', None)
    else:
        raw['engine_config'] = str(engine_config)
    argv = ['--spec', write_spec(tmp_path, raw), '--execute']
    result, printed = run_model(monkeypatch, capsys, argv)
    return result['engine_runtime'], printed, result


def model_only_build(tmp_path, monkeypatch, capsys, runtime):
    """A candidate build. The bound template's spicy-regs tables are fetched data this checkout need not
    have, so neither the input check nor the build reads them (the table list both take is empty); every
    other input is checked and held, as the build does."""
    import viewer_publication.archive_model_job as job
    from viewer_publication.release_gate import prior_links
    monkeypatch.setattr(job, '_spicy_tables', lambda *_: ({}, {}))
    candidate = tmp_path / 'candidate'
    daily_candidate(candidate)
    ready = tmp_path / 'ready'
    prior_links(base_release(tmp_path), [], ready)
    build = (tmp_path / 'arm').resolve()
    result, printed = run_model(monkeypatch, capsys, ['--from-candidate', str(candidate), '--build', str(build),
                                                      '--runtime', str(runtime), '--ledger', str(ready), '--execute'])
    return result['engine_runtime'], printed, build / 'runtime.json'


def publisher_runtime(tmp_path, folder, **options):
    """A publication runtime: the publisher requires a remote; its credentials file is named, never opened."""
    from test_archive_publish_job import remote_config
    return constructed_runtime(folder, remote=str(remote_config(tmp_path)), credentials='never-opened.json', **options)


def publisher(tmp_path, monkeypatch, capsys, engine_config):
    """The publisher's execute up to the controller, with constructed services: (the record it hands the
    controller for the candidate folder, stderr printed before it)."""
    import viewer_publication.archive_controller as controller
    import viewer_publication.producer_proof as producer_proof
    from congress_api.retention.provenance import file_pin
    from test_archive_publish import Store
    from test_archive_publish_job import END_TO_END_PASSED, publish_spec
    from viewer_publication.archive_publish_job import execute, load_spec
    value = publish_spec(tmp_path)
    model = Path(value['model_spec']['path'])
    model_data = dict(json.loads(model.read_text()))
    if engine_config is None:
        model_data.pop('engine_config', None)
    else:
        model_data['engine_config'] = str(engine_config)
    model.write_text(json.dumps(model_data))
    value['model_spec'] = dict(path=str(model), **file_pin(model))
    path = tmp_path / 'publish.json'
    path.write_text(json.dumps(value))

    class Runtime:
        def __init__(self, configuration):
            self.remote = Path(json.loads(Path(configuration).read_text())['remote'])
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def verify_runtime(self):
            return dict(verified=True)

    handed = []
    def run_publish(*_, engine_runtime=None, **__):
        handed.append((engine_runtime, capsys.readouterr().err))
        return dict(status='published')
    monkeypatch.setattr(controller, 'run_publish', run_publish)
    monkeypatch.setattr(producer_proof, 'require_producers', lambda *_, **__: None)
    result = execute(load_spec(path), runtime_factory=Runtime, storage_factory=lambda **_: Store(),
                     end_to_end_runner=END_TO_END_PASSED)
    assert result['status'] == 'published'
    (handed,) = handed
    return handed


def backfill_run(tmp_path, monkeypatch, capsys, engine_config):
    from types import SimpleNamespace
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from congress_api.retention.provenance import file_pin
    from viewer_publication import archive_backfill_job

    anchor = tmp_path / 'appearance_records.json'
    anchor.write_bytes(b'{"selector":{}}\n')
    work = tmp_path / 'backfill-work'
    raw = dict(
        version=1,
        bucket='archive-fixture',
        catalog_root=None,
        work=str(work),
        tables={name: dict(namespace=['archive'], name=name) for name in ALL_TABLE_NAMES},
        batch_size=10,
        max_batches=1,
        producers=dict(appearance_records=dict(path=str(anchor), **file_pin(anchor))),
    )
    if engine_config is not None:
        raw['engine_config'] = str(engine_config)
    path = tmp_path / 'backfill.json'
    path.write_text(json.dumps(raw))
    before = []

    class Runtime:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def verify_runtime(self):
            return dict(verified=True)

    class BackfillR2:
        meta = SimpleNamespace(
            config=SimpleNamespace(retries={'total_max_attempts': 1}),
            events=SimpleNamespace(register_first=lambda *_, **__: None),
        )
        def get_paginator(self, _):
            return SimpleNamespace(paginate=lambda **_: [dict(Contents=[], IsTruncated=False)])

    def producer(*_, **__):
        before.append(capsys.readouterr().err)
        return dict(status='completed', pins={})

    result = archive_backfill_job.execute(
        archive_backfill_job.load_spec(path),
        runtime_factory=lambda _: Runtime(),
        storage_factory=lambda **_: BackfillR2(),
        producer=producer,
    )
    (printed,) = before
    saved = json.loads((work / 'backfill-report.json').read_text())
    assert saved['engine_runtime'] == result['engine_runtime']
    assert saved['engine_config'] == result['engine_config']
    return result['engine_runtime'], printed, result


def import_run(tmp_path, monkeypatch, capsys, engine_config):
    import pyarrow.parquet as pq
    import congress_api.lake.maintenance as lake_maint
    import congress_api.lake.tables as lake_tables
    import congress_api.retention.writer_identity as identity
    from test_archive_import_job import ROWS, SCHEMA
    from congress_api.retention.provenance import file_pin
    from viewer_publication import archive_import_job

    monkeypatch.setattr(identity, 'writer_identity', lambda root, job: dict(job=job, commit='c' * 40, lockfile_digest='d' * 64))
    monkeypatch.setattr(lake_tables, 'validate_catalog_authority', lambda *_, **__: None)
    monkeypatch.setattr(lake_tables, 'create_table', lambda **_: dict(table_operations=[dict(name='create')]))
    monkeypatch.setattr(
        lake_tables, 'append_rows',
        lambda *_, **__: dict(
            metadata_location=str(tmp_path / 'meta.json'),
            table_uuid='00000000-0000-4000-8000-000000000001',
            snapshot=1,
            schema_id=0,
            files=1,
        ),
    )
    before = []
    monkeypatch.setattr(lake_maint, 'verify_generations', lambda *_, **__: before.append(capsys.readouterr().err))

    class Runtime:
        source_revision = 'a' * 40
        binary_sha256 = 'b' * 64
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def verify_runtime(self):
            return dict(verified=True)

    source = tmp_path / 'rows.parquet'
    pq.write_table(ROWS, source)
    schema = tmp_path / 'schema.json'
    schema.write_text(json.dumps(SCHEMA))
    work = tmp_path / 'import-work'
    raw = dict(
        version=1,
        catalog_root=str(tmp_path / 'catalog'),
        work=str(work),
        location=str(tmp_path / 'data'),
        definition='import:fixture',
        provenance={'writer': 'fixture'},
        create_namespace=True,
        tables=dict(meeting_records=dict(
            source=dict(path=str(source), **file_pin(source)),
            schema=dict(path=str(schema), **file_pin(schema)),
            partition_spec=None,
            table=dict(namespace=['archive'], name='meeting_records_fixture'),
        )),
    )
    if engine_config is not None:
        raw['engine_config'] = str(engine_config)
    path = tmp_path / 'import.json'
    path.write_text(json.dumps(raw))
    result = archive_import_job.execute(archive_import_job.load_spec(path), runtime_factory=lambda _: Runtime())
    (printed,) = before
    saved = json.loads((work / 'import-report.json').read_text())
    assert saved['engine_runtime'] == result['engine_runtime']
    assert saved['engine_config'] == result['engine_config']
    return result['engine_runtime'], printed, result


def maintenance_run(tmp_path, monkeypatch, capsys, engine_config, *, need_engine=True):
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from test_archive_maintenance import NOW, RecordingS3, fixture
    from viewer_publication import archive_maintenance

    store, _ = fixture()
    client = RecordingS3(store)
    work = tmp_path / 'maint-work'
    raw = dict(
        version=1,
        bucket='archive-fixture',
        catalog_root=None,
        work=str(work),
        external_pins=[],
        tables={name: dict(namespace=['archive'], name=name) for name in ALL_TABLE_NAMES},
        thresholds=dict(file_count=256, manifest_count=64, scan_planning_seconds=30.0),
    )
    if need_engine:
        raw['lake_maintenance'] = dict(observations=dict(captures=dict(file_count=1, manifest_count=1, scan_planning_seconds=0)))
    if engine_config is not None:
        raw['engine_config'] = str(engine_config)
    path = tmp_path / 'maintenance.json'
    path.write_text(json.dumps(raw))
    before = []
    orig_retain = archive_maintenance._retain_releases
    def retain(*args, **kwargs):
        before.append(capsys.readouterr().err)
        return orig_retain(*args, **kwargs)
    monkeypatch.setattr(archive_maintenance, '_retain_releases', retain)

    class Runtime:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def verify_runtime(self):
            return dict(verified=True)

    result = archive_maintenance.execute(
        archive_maintenance.load_spec(path),
        runtime_factory=lambda _: Runtime(),
        storage_factory=lambda **_: client,
        now=NOW,
        execute=False,
    )
    (printed,) = before
    saved = json.loads((work / 'maintenance-report.json').read_text())
    assert saved['engine_runtime'] == result['engine_runtime']
    assert saved['engine_config'] == result['engine_config']
    return result['engine_runtime'], printed, result


@pytest.mark.parametrize('caller', ['model job', 'model-only build', 'publisher', 'backfill', 'import', 'maintenance'])
def test_each_caller_records_the_runtime_it_runs_under_before_it_runs(tmp_path, monkeypatch, capsys, caller):
    """The same fields from every caller, read from the chosen file's own bytes, printed before any work.
    A named file that exists wins over both environment variables, which here name runtimes with other limits."""
    monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(constructed_runtime(tmp_path / 'decoy', limits=HOSTED)))
    if caller == 'publisher':
        ran = publisher_runtime(tmp_path, tmp_path / 'engine')
        record, printed = publisher(tmp_path, monkeypatch, capsys, ran)
    elif caller == 'model job':
        ran = constructed_runtime(tmp_path / 'engine')
        record, printed, _ = model_job(tmp_path, monkeypatch, capsys, ran)
    elif caller == 'model-only build':
        runtime = constructed_runtime(tmp_path / 'engine')
        record, printed, ran = model_only_build(tmp_path, monkeypatch, capsys, runtime)
        # The build's copy names the original binary and limits: one engine, whichever file names it.
        assert {name: record[name] for name in ('binary', 'limits')} == {
            name: runtime_ran(runtime)[name] for name in ('binary', 'limits')}
    elif caller == 'backfill':
        ran = constructed_runtime(tmp_path / 'engine')
        record, printed, _ = backfill_run(tmp_path, monkeypatch, capsys, ran)
    elif caller == 'import':
        ran = constructed_runtime(tmp_path / 'engine')
        record, printed, _ = import_run(tmp_path, monkeypatch, capsys, ran)
    else:
        ran = constructed_runtime(tmp_path / 'engine')
        record, printed, _ = maintenance_run(tmp_path, monkeypatch, capsys, ran)
    assert record == runtime_ran(ran) and record['limits']['values'] == MAC_LIMITS
    assert logged(printed) == [record]


@pytest.mark.parametrize('caller', ['model job', 'publisher', 'backfill', 'import', 'maintenance'])
def test_absent_engine_config_records_runtime_config_over_job_config(tmp_path, monkeypatch, capsys, caller):
    """When a spec omits engine_config, DOCSPEC_RUNTIME_CONFIG wins over DOCSPEC_JOB_CONFIG for all five callers."""
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(constructed_runtime(tmp_path / 'job-decoy', limits=HOSTED)))
    if caller == 'publisher':
        # Publisher requires a local-only DOCSPEC_JOB_CONFIG for require_end_to_end (stubbed) and remote runtime.
        fallback = publisher_runtime(tmp_path, tmp_path / 'remote-runtime')
        monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(fallback))
        record, printed = publisher(tmp_path, monkeypatch, capsys, None)
    else:
        fallback = constructed_runtime(tmp_path / 'remote-runtime')
        monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(fallback))
        runner = {'model job': model_job, 'backfill': backfill_run, 'import': import_run, 'maintenance': maintenance_run}[caller]
        record, printed, result = runner(tmp_path, monkeypatch, capsys, None)
        assert result['engine_config'] == str(fallback)
    assert logged(printed) == [record]
    reason = record.pop('reason')
    assert 'no runtime file named' in reason and 'DOCSPEC_RUNTIME_CONFIG' in reason
    assert record == runtime_ran(fallback, named=None) and record['limits']['values'] == MAC_LIMITS


@pytest.mark.parametrize('caller', ['backfill', 'import', 'maintenance'])
def test_job_fallback_callers_use_job_config_only_when_named_and_runtime_config_are_absent(tmp_path, monkeypatch, capsys, caller):
    """Backfill, import and maintenance keep their third step (DOCSPEC_JOB_CONFIG) and record how it was chosen."""
    monkeypatch.delenv('DOCSPEC_RUNTIME_CONFIG', raising=False)
    job_runtime = constructed_runtime(tmp_path / 'job-runtime')
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(job_runtime))
    runner = {'backfill': backfill_run, 'import': import_run, 'maintenance': maintenance_run}[caller]
    record, printed, result = runner(tmp_path, monkeypatch, capsys, None)
    assert result['engine_config'] == str(job_runtime)
    assert logged(printed) == [record]
    reason = record.pop('reason')
    assert 'DOCSPEC_RUNTIME_CONFIG' in reason and 'DOCSPEC_JOB_CONFIG' in reason
    assert record == runtime_ran(job_runtime, named=None) and record['limits']['values'] == MAC_LIMITS


def test_maintenance_without_engine_operations_records_no_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('DOCSPEC_RUNTIME_CONFIG', raising=False)
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(constructed_runtime(tmp_path / 'job-decoy', limits=HOSTED)))
    record, printed, result = maintenance_run(tmp_path, monkeypatch, capsys, None, need_engine=False)
    assert record is None and result['engine_config'] is None and logged(printed) == []


def test_published_model_spec_omits_dead_runtime_and_keeps_24gib_two_thread_remote_limits(tmp_path):
    """Owner Decision A1 (ct-64t4): publish-model.json omits dead ../../.runtime/docspec/runtime.json, and the Mac
    remote-runtime keeps 24 GiB / 2 threads on purpose under the 14 GiB RSS watchdog (W21 FairSpillPool rationale)."""
    import importlib.util
    from viewer_publication import archive_model_job, archive_publish_job

    root = Path(__file__).resolve().parents[3]
    model_path = root / 'model/jobs/publish-model.json'
    model_text = model_path.read_text()
    assert '.runtime/docspec/runtime.json' not in model_text
    assert 'engine_config' not in json.loads(model_text)
    assert 'engine_config' not in archive_model_job.load_spec(model_path)
    assert archive_publish_job.load_spec(root / 'model/jobs/publish.json')

    jobs = json.loads((root / '.github/archive-jobs.json').read_text())
    assert jobs['publish']['rss_gb'] == 14
    assert MAC_LIMITS['memory_bytes'] == 24 << 30 and MAC_LIMITS['compute_threads'] == 2

    spec = importlib.util.spec_from_file_location('nightly_publish_limits', root / 'scripts/nightly_publish.py')
    nightly = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nightly)
    assert (nightly.REMOTE_RUNTIME_MEMORY_BYTES, nightly.REMOTE_RUNTIME_THREADS) == (24 << 30, 2)

    remote_dir = tmp_path / '.cache/archive-release/remote-runtime'
    constructed_runtime(remote_dir, limits=MAC_LIMITS)
    (remote_dir / 'credentials.json').write_text(json.dumps(dict(
        DOCSPEC_S3_ACCESS_KEY_ID='ak', DOCSPEC_S3_SECRET_ACCESS_KEY='sk')))
    (remote_dir / 'remote.json').write_text(json.dumps(dict(
        properties={'s3.endpoint': 'https://' + 'a' * 32 + '.r2.cloudflarestorage.com'})))
    env = nightly.publish_env(tmp_path, root)
    assert env['DOCSPEC_RUNTIME_CONFIG'] == str(remote_dir / 'runtime.json')

    (remote_dir / 'limits.json').write_text(json.dumps(dict(MAC_LIMITS, memory_bytes=12 << 30, compute_threads=4)))
    with pytest.raises(SystemExit, match='ct-64t4'):
        nightly.publish_env(tmp_path, root)

    live_limits = nightly.main_checkout(root) / '.cache/archive-release/remote-runtime/limits.json'
    if live_limits.is_file():
        values = json.loads(live_limits.read_text())
        assert (values['memory_bytes'], values['compute_threads']) == (24 << 30, 2)


def test_the_record_names_what_the_client_hands_the_engine(tmp_path, monkeypatch, capsys):
    from docspec_client.client import NativeDatasets
    runtime = constructed_runtime(tmp_path / 'engine')
    record, _, result = model_job(tmp_path, monkeypatch, capsys, runtime)
    with NativeDatasets.from_config(runtime) as engine:
        command = engine._command()
    assert (record['binary']['path'], record['limits']['path']) == (command[0], command[command.index('--limits') + 1])
    assert result['engine_config'] == str(runtime.resolve())


def test_the_binary_is_recorded_by_its_bytes_not_by_the_runtime_s_own_claim(tmp_path, monkeypatch, capsys):
    """A digest supplied by the thing being checked is not evidence of what ran."""
    runtime = constructed_runtime(tmp_path / 'engine', binary_sha256='0' * 64)
    record, _, _ = model_job(tmp_path, monkeypatch, capsys, runtime)
    assert record['binary']['sha256'] == runtime_ran(runtime)['binary']['sha256'] != '0' * 64


@pytest.mark.parametrize('caller', ['model job', 'publisher'])
def test_a_missing_named_runtime_is_recorded_as_the_fallback_that_ran(tmp_path, monkeypatch, capsys, caller):
    """Today's fallback, unchanged: the record names the missing file, the file that ran, and why."""
    named = (tmp_path / 'absent' / 'runtime.json').resolve()
    if caller == 'publisher':
        fallback = publisher_runtime(tmp_path, tmp_path / 'remote-runtime')
        monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(fallback))
        record, printed = publisher(tmp_path, monkeypatch, capsys, named)
    else:
        fallback = constructed_runtime(tmp_path / 'remote-runtime')
        monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(fallback))
        record, printed, result = model_job(tmp_path, monkeypatch, capsys, named)
        assert result['engine_config'] == str(fallback)
    assert logged(printed) == [record]
    reason = record.pop('reason')
    assert 'DOCSPEC_RUNTIME_CONFIG' in reason and 'no runtime file' in reason
    assert record == runtime_ran(fallback, named=named)


@pytest.mark.parametrize('variable', [None, ''])
def test_without_the_variable_a_missing_named_runtime_still_fails_and_records_nothing(tmp_path, monkeypatch, capsys, variable):
    from viewer_publication.archive_model_job import main
    if variable is None:
        monkeypatch.delenv('DOCSPEC_RUNTIME_CONFIG', raising=False)
    else:
        monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', variable)
    absent = tmp_path / 'absent.json'
    with pytest.raises(SystemExit) as error:
        main(['--spec', write_spec(tmp_path, dict(pinned_local_spec(tmp_path), engine_config=str(absent))), '--execute'])
    err = capsys.readouterr().err
    assert error.value.code == 2 and str(absent) in err and LINE not in err


@pytest.mark.parametrize('caller', ['model job', 'publisher'])
def test_model_and_publisher_without_engine_config_never_fall_back_to_job_config(tmp_path, monkeypatch, capsys, caller):
    monkeypatch.delenv('DOCSPEC_RUNTIME_CONFIG', raising=False)
    monkeypatch.setenv('DOCSPEC_JOB_CONFIG', str(constructed_runtime(tmp_path / 'job-decoy', limits=HOSTED)))
    if caller == 'publisher':
        with pytest.raises(ValueError, match='DOCSPEC_RUNTIME_CONFIG'):
            publisher(tmp_path, monkeypatch, capsys, None)
    else:
        raw = dict(pinned_local_spec(tmp_path))
        raw.pop('engine_config', None)
        from viewer_publication.archive_model_job import main
        with pytest.raises(SystemExit) as error:
            main(['--spec', write_spec(tmp_path, raw), '--execute'])
        assert error.value.code == 2
    assert LINE not in capsys.readouterr().err


@pytest.mark.parametrize('record,readable', [(None, True), (dict(chosen='named'), True), ('not a record', False)])
def test_a_continuation_reads_with_or_without_its_runtime_record(tmp_path, record, readable):
    """Continuations written before the record existed still resume; a record that is not one refuses."""
    from viewer_publication.archive_controller import _read_continuation, _save_continuation
    value = dict(version=1, identity='1' * 64, profile={}, entity_digests={}, admitted_names=[], pointer=None, pointer_etag=None)
    if record is not None:
        value['engine_runtime'] = record
    _save_continuation(tmp_path / 'model-intent.json', value)
    if readable:
        assert _read_continuation(tmp_path)[1] == value
    else:
        with pytest.raises(ValueError, match='Corrupt publication continuation fields'):
            _read_continuation(tmp_path)


def test_a_resumed_publication_keeps_the_record_of_the_runtime_that_built_its_model(tmp_path, monkeypatch):
    """The intent carries the record of the attempt that builds; a later attempt that only completes the
    exported model (promotes the intent) keeps it, so the candidate never credits the build to another runtime."""
    import viewer_publication.archive_controller as controller
    from docspec_client.client import NativeDatasets
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    from viewer_publication.archive_model_job import load_spec
    spec, _, _ = real_model_spec(tmp_path)
    path = tmp_path / 'model-spec.json'
    path.write_text(json.dumps(spec))
    built, resumed = dict(chosen='named', attempt='built the model'), dict(chosen='fallback', attempt='resumed')
    export = controller.build_prepared_release
    def exported_then_stopped(*args, **kwargs):
        export(*args, **kwargs)
        raise RuntimeError('stopped after the export')
    def never(*_, **__):
        raise AssertionError('the exported model was rebuilt')
    def passed(**context):
        return dict(status='passed', releaseId=context['release_id'], targets='owner-approved')
    store = Store()
    work = tmp_path / 'publish'
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        options = dict(first_release=True, client=store, engine=Runtime(native, store), bucket='derived-fixture', work=work,
                       receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'], provenance=[], run={'id': 'record'},
                       public_origin='https://archive.fixture.test', contract=passed, canary=passed)
        monkeypatch.setattr(controller, 'build_prepared_release', exported_then_stopped)
        with pytest.raises(RuntimeError, match='stopped after the export'):
            controller.run_publish(load_spec(path), engine_runtime=built, **options)
        assert json.loads((work / 'model-intent.json').read_text())['engine_runtime'] == built
        assert not (work / 'completed-model.json').exists()
        monkeypatch.setattr(controller, 'build_prepared_release', never)
        assert controller.run_publish(load_spec(path), engine_runtime=resumed, resume=True, **options)['status'] == 'published'
    assert json.loads((work / 'completed-model.json').read_text())['engine_runtime'] == built
