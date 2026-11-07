"""Private source access stays outside original model requests and public output."""
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('provide_source', [False, True])
def test_resume_passes_private_source_without_opening_it_or_changing_request(
        tmp_path, monkeypatch, provide_source):
    from ddk.adapters import docspec
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_catalog import capture_definitions
    from viewer_publication.archive_format import NativeReleaseNotReady
    from viewer_publication.archive_model_job import main

    source = tmp_path/'private-source.json'
    source.write_text('Private source configuration is native-owned.')
    native = dict(action='prepare', dataset='archive', operation='model',
        producer_adoption={'definition_sha256': 'a'*64},
        snapshot_inputs=[dict(name='captures', metadata_sha256='b'*64)],
        prerequisites=[dict(inputs=['captures'])])
    project = capture_definitions(tmp_path/'definitions')
    path = tmp_path/'release-request.json'
    raw = json.dumps(dict(native=native, workspace=str(tmp_path/'native'), project=str(project),
        native_rules=dict(path=str(tmp_path/'native-rules.json'), sha256='c'*64),
        origin=dict(kind='model'), controls_dir=str(tmp_path/'controls'))).encode()
    path.write_bytes(raw)
    original_stat = path.stat()
    calls = []

    def observe(workspace, request, *, snapshot_source):
        calls.append((workspace, request, snapshot_source))
        return dict(status='succeeded', result=dict(status='pending'))

    engine = SimpleNamespace(binary='unused', limits=tmp_path/'limits.json', timeout=5,
        source_revision='d'*40, binary_sha256='e'*64, verify_runtime=lambda: None)
    monkeypatch.setattr(NativeDatasets, 'from_config', lambda path: nullcontext(engine))
    monkeypatch.setattr(docspec, 'DocSpecAdapter', lambda *args, **kwargs:
                        SimpleNamespace(managed_job=observe))
    original_open = Path.open

    def open_control(path, *args, **kwargs):
        assert path != source, 'Application opened the native private source configuration'
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', open_control)
    args = ['--prepared-request', str(path), '--request-sha256', sha256(raw).hexdigest(),
            '--engine-config', str(tmp_path/'runtime.json'), '--execute']
    if provide_source:
        args += ['--snapshot-source', str(source)]
    with pytest.raises(NativeReleaseNotReady, match='preparation'):
        main(args)
    assert calls == [(str(tmp_path/'native'), native, source if provide_source else None)]
    assert path.read_bytes() == raw
    assert (path.stat().st_ino, path.stat().st_mtime_ns) == (original_stat.st_ino, original_stat.st_mtime_ns)
    assert not (tmp_path/'native').exists()
    assert not (tmp_path/'controls').exists()


@pytest.mark.parametrize('input_flag', ['--spec', '--prepared-request'])
def test_planning_refuses_source_access_before_opening_inputs(tmp_path, capsys, input_flag):
    from viewer_publication.archive_model_job import main

    with pytest.raises(SystemExit) as error:
        main([input_flag, str(tmp_path/'unopened.json'),
              '--snapshot-source', str(tmp_path/'private-source.json')])
    assert error.value.code == 2
    assert 'Snapshot source configuration belongs to --execute' in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_fresh_execution_source_option_stays_outside_spec_and_output(tmp_path, monkeypatch, capsys):
    from viewer_publication import archive_model_job

    spec = {'selected': 'original model inputs'}
    source = tmp_path/'private-source.json'
    calls = []
    monkeypatch.setattr(archive_model_job, 'load_spec', lambda path: spec)

    def execute(value, *, snapshot_source):
        assert value is spec
        calls.append(snapshot_source)
        return dict(status='built', executed=True, release_id='selected-model')

    monkeypatch.setattr(archive_model_job, 'execute', execute)
    assert archive_model_job.main(['--spec', str(tmp_path/'spec.json'), '--execute',
                                  '--snapshot-source', str(source)]) == 0
    assert calls == [source]
    assert spec == {'selected': 'original model inputs'}
    assert json.loads(capsys.readouterr().out) == dict(status='built', executed=True, release_id='selected-model')
    assert not list(tmp_path.iterdir())
