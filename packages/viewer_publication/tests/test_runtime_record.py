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

from archive_job_fixture import MAC_LIMITS, constructed_runtime, real_model_spec, runtime_ran
from test_archive_model_job import base_release, daily_candidate, pinned_local_spec, write_spec

LINE = '[docspec-runtime] '
HOSTED = dict(MAC_LIMITS, memory_bytes=10 << 30, scratch_bytes=10 << 30)


def logged(err):
    """The runtime records a run printed, parsed."""
    return [json.loads(line[len(LINE):]) for line in err.splitlines() if line.startswith(LINE)]


def test_the_session_runtime_is_a_decoy_with_other_limits():
    """Each record below must hold the Mac's limits; one read from this session's runtime would not."""
    session = json.loads(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    assert json.loads(Path(session['limits']).read_text())['memory_bytes'] != MAC_LIMITS['memory_bytes']


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
    argv = ['--spec', write_spec(tmp_path, dict(pinned_local_spec(tmp_path), engine_config=str(engine_config))), '--execute']
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
    model.write_text(json.dumps(dict(json.loads(model.read_text()), engine_config=str(engine_config))))
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


@pytest.mark.parametrize('caller', ['model job', 'model-only build', 'publisher'])
def test_each_caller_records_the_runtime_it_runs_under_before_it_runs(tmp_path, monkeypatch, capsys, caller):
    """The same fields from every caller, read from the chosen file's own bytes, printed before any model work.
    A named file that exists wins over the variable, which here names a runtime with other limits."""
    monkeypatch.setenv('DOCSPEC_RUNTIME_CONFIG', str(constructed_runtime(tmp_path / 'decoy', limits=HOSTED)))
    if caller == 'publisher':
        ran = publisher_runtime(tmp_path, tmp_path / 'engine')
        record, printed = publisher(tmp_path, monkeypatch, capsys, ran)
    elif caller == 'model job':
        ran = constructed_runtime(tmp_path / 'engine')
        record, printed, _ = model_job(tmp_path, monkeypatch, capsys, ran)
    else:
        runtime = constructed_runtime(tmp_path / 'engine')
        record, printed, ran = model_only_build(tmp_path, monkeypatch, capsys, runtime)
        # The build's copy names the original binary and limits: one engine, whichever file names it.
        assert {name: record[name] for name in ('binary', 'limits')} == {
            name: runtime_ran(runtime)[name] for name in ('binary', 'limits')}
    assert record == runtime_ran(ran) and record['limits']['values'] == MAC_LIMITS
    assert logged(printed) == [record]


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
