"""Private runtime installation stays byte-pinned, read-only and secret-safe."""
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location('native_setup', ROOT / '.github/scripts/setup-native-runtime.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def inputs():
    binary = b'\x7fELF-qualified-private-runtime-fixture'
    digest, revision = sha256(binary).hexdigest(), module().QUALIFIED_DOCSPEC_RUNTIME['source_revision']
    descriptor = dict(version=1, platform='linux-amd64', source_revision=revision,
        bucket='private-runtime-fixture', key=f'runtime/docspec/{revision}/linux-amd64/{digest}/docspec',
        bytes=len(binary), sha256=digest)
    credentials = {name: 'fixture-secret-' + name for name in module().SECRET_NAMES}
    return binary, descriptor, credentials


class ArtifactClient:
    def __init__(self, binary, *, declared=None):
        self.binary = binary
        self.declared = len(binary) if declared is None else declared
        self.calls = []
        self.body = None

    def get_object(self, **options):
        self.calls.append(options)
        self.body = io.BytesIO(self.binary)
        return dict(Body=self.body, ContentLength=self.declared)


def test_install_uses_exact_selected_object_and_existing_runtime_validation(tmp_path, inputs, monkeypatch):
    value = module()
    binary, descriptor, credentials = inputs
    client = ArtifactClient(binary)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Native process started'))
    directory = tmp_path / 'runtime'
    config, result = value.install(descriptor, credentials, ROOT / '.github/docspec-remote.json', directory, client=client)
    assert client.calls == [dict(Bucket=descriptor['bucket'], Key=descriptor['key'])]
    assert client.body.closed
    assert (directory / 'docspec').read_bytes() == binary
    assert (directory / 'docspec').stat().st_mode & 0o777 == 0o700
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ['runtime.json', 'credentials.json', 'remote.json']:
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert (directory / 'remote.json').read_bytes() == (ROOT / '.github/docspec-remote.json').read_bytes()
    from congress_api.retention.docspec import NativeDatasets
    native = NativeDatasets.from_config(config)
    assert native._remote_secrets == credentials
    assert native.limits is None and native.timeout == 120
    assert not (directory / 'workspace').exists()
    assert result['verified'] and result['artifact_downloaded']
    assert not result['native_executed'] and not result['native_provider_accessed']
    assert all(secret not in json.dumps(result) for secret in credentials.values())
    assert str(directory / 'credentials.json') not in result['execution_sha256']


@pytest.mark.parametrize('change',[
    dict(version=True), dict(version=2), dict(platform='darwin-arm64'), dict(source_revision='short'),
    dict(sha256='not-a-digest'), dict(bytes=True), dict(bytes=0), dict(bytes=1024**3+1),
    dict(bucket='https://public.test/bucket'), dict(key='../docspec'), dict(extra='unrecognized'),
])
def test_descriptor_refuses_unpinned_or_changed_distribution(inputs, change):
    _, descriptor, _ = inputs
    with pytest.raises(ValueError):
        module().artifact_descriptor(json.dumps({**descriptor, **change}))


def test_descriptor_refuses_a_self_consistent_artifact_from_another_revision(inputs):
    _, descriptor, _ = inputs
    stale = '9' * 40
    assert stale != module().QUALIFIED_DOCSPEC_RUNTIME['source_revision']
    changed = {**descriptor, 'source_revision': stale,
               'key': f"runtime/docspec/{stale}/linux-amd64/{descriptor['sha256']}/docspec"}
    with pytest.raises(ValueError, match='qualified DocSpec revision'):
        module().artifact_descriptor(json.dumps(changed))


@pytest.mark.parametrize('fault',['size', 'truncated', 'extra', 'digest'])
def test_bad_artifact_never_gets_executable_bit_and_partial_install_cannot_resume(tmp_path, inputs, fault):
    value = module()
    binary, descriptor, credentials = inputs
    raw = binary[:-1] if fault == 'truncated' else binary+b'x' if fault == 'extra' else binary[:-1]+b'x' if fault == 'digest' else binary
    client = ArtifactClient(raw, declared=descriptor['bytes']+1 if fault == 'size' else descriptor['bytes'])
    root = tmp_path / 'runtime'
    with pytest.raises(ValueError):
        value.install(descriptor, credentials, ROOT / '.github/docspec-remote.json', root, client=client)
    assert client.body.closed and not (root / 'docspec').exists()
    assert all(not os.access(path, os.X_OK) for path in root.rglob('*') if path.is_file())
    client.calls.clear()
    with pytest.raises(ValueError, match='fresh directory'):
        value.install(descriptor, credentials, ROOT / '.github/docspec-remote.json', root, client=client)
    assert not client.calls


def test_stale_and_dangling_symlink_installations_refuse_without_touching_existing_bytes(tmp_path, inputs):
    binary, descriptor, credentials = inputs
    root = tmp_path / 'runtime'
    root.mkdir()
    (root / 'docspec').write_bytes(b'stale-runtime')
    client = ArtifactClient(binary)
    with pytest.raises(ValueError, match='fresh directory'):
        module().install(descriptor, credentials, ROOT / '.github/docspec-remote.json', root, client=client)
    assert not client.calls and (root / 'docspec').read_bytes() == b'stale-runtime'
    link = tmp_path / 'linked';link.symlink_to(tmp_path / 'absent')
    with pytest.raises(ValueError, match='fresh directory'):
        module().install(descriptor, credentials, ROOT / '.github/docspec-remote.json', link, client=client)
    assert not (tmp_path / 'absent').exists() and not client.calls


def test_main_exports_only_checked_paths_and_digest_and_never_logs_credentials(tmp_path, inputs, monkeypatch, capsys):
    value = module()
    binary, descriptor, credentials = inputs
    monkeypatch.setenv('DOCSPEC_RUNTIME_ARTIFACT', json.dumps(descriptor))
    monkeypatch.setenv('DOCSPEC_ENGINE_CREDENTIALS', json.dumps(credentials))
    monkeypatch.setattr(value, 'make_client', lambda _: ArtifactClient(binary))
    output, environment = tmp_path / 'report.json', tmp_path / 'github-env'
    assert value.main(['--directory', str(tmp_path / 'runtime'), '--output', str(output), '--github-env', str(environment)]) == 0
    logged = ''.join(capsys.readouterr()) + output.read_text() + environment.read_text()
    assert all(secret not in logged for secret in credentials.values())
    assert environment.read_text().splitlines() == [f'DOCSPEC_RUNTIME_CONFIG={tmp_path}/runtime/runtime.json',
        f'DOCSPEC_BINARY_SHA256={descriptor["sha256"]}']


@pytest.mark.parametrize('credentials', ['malformed-secret-json', '{}', 'null', '{"DOCSPEC_CATALOG_TOKEN":"secret-only"}'])
def test_bad_credentials_refuse_before_artifact_client_and_do_not_log_input(tmp_path, inputs, monkeypatch, capsys, credentials):
    value = module()
    monkeypatch.setenv('DOCSPEC_RUNTIME_ARTIFACT', json.dumps(inputs[1]))
    monkeypatch.setenv('DOCSPEC_ENGINE_CREDENTIALS', credentials)
    monkeypatch.setattr(value, 'make_client', lambda _: pytest.fail('Client created before input validation'))
    output = tmp_path / 'report.json'
    assert value.main(['--directory', str(tmp_path / 'runtime'), '--output', str(output)]) == 1
    logged = ''.join(capsys.readouterr())
    assert credentials not in logged and 'secret-only' not in logged
    assert not output.exists() and not (tmp_path / 'runtime').exists()


def test_provider_failure_cannot_leak_response_body_or_credentials(tmp_path, inputs, monkeypatch, capsys):
    value = module()
    monkeypatch.setenv('DOCSPEC_RUNTIME_ARTIFACT', json.dumps(inputs[1]))
    monkeypatch.setenv('DOCSPEC_ENGINE_CREDENTIALS', json.dumps(inputs[2]))
    class Rejected:
        def get_object(self, **_):
            raise RuntimeError('private-response-' + next(iter(inputs[2].values())))
    monkeypatch.setattr(value, 'make_client', lambda _: Rejected())
    assert value.main(['--directory', str(tmp_path / 'runtime'), '--output', str(tmp_path / 'report.json')]) == 1
    logged = ''.join(capsys.readouterr())
    assert 'RuntimeError' in logged and 'private-response-' not in logged
    assert all(secret not in logged for secret in inputs[2].values())


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def test_workflow_installation_preserves_execution_gates_and_secret_boundaries():
    capture = workflow('capture-raw-sources.yml')['jobs']
    steps = [(job, step) for job in [capture['capture'], capture['update_catalog_after_capture']]
             for step in job['steps'] if 'setup-native-runtime.py' in step.get('run', '')]
    assert len(steps) == 2
    assert steps[0][1]['if'] == "steps.operation.outputs.mode != 'validate'"
    assert 'if' not in steps[1][1]
    for job, step in steps:
        assert step['env']['DOCSPEC_RUNTIME_ARTIFACT'] == '${{ vars.DOCSPEC_RUNTIME_ARTIFACT }}'
        assert step['env']['DOCSPEC_ENGINE_CREDENTIALS'] == '${{ secrets.DOCSPEC_ENGINE_CREDENTIALS }}'
        assert 'R2_ACCESS_KEY_ID' not in step['env'] and 'R2_SECRET_ACCESS_KEY' not in step['env']
        assert '--directory "$RUNNER_TEMP/docspec-runtime"' in step['run']
        assert '--github-env "$GITHUB_ENV"' in step['run']
        assert 'DOCSPEC_RUNTIME_CONFIG' not in job.get('env', {})
        assert job['runs-on'] == 'ubuntu-24.04'
    assert capture['capture']['timeout-minutes'] == capture['update_catalog_after_capture']['timeout-minutes'] == '360'
    assert workflow('archive-jobs.yml')['jobs']['publish']['timeout-minutes'] == '180'
    for job in [capture['capture'], capture['update_catalog_after_capture']]:
        for step in job['steps']:
            if step.get('uses', '').startswith('actions/upload-artifact'):
                assert 'docspec-runtime' not in step.get('with', {}).get('path', '')


def test_artifact_client_uses_only_declared_engine_s3_credentials(inputs, monkeypatch):
    import boto3
    value = module()
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    monkeypatch.delenv('R2_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('R2_SECRET_ACCESS_KEY', raising=False)
    captured = {}
    def client(kind, **options):
        captured.update(options)
        assert kind == 's3'
        return 'fixture-client'
    monkeypatch.setattr(boto3, 'client', client)
    assert value.make_client(inputs[2]) == 'fixture-client'
    assert captured['aws_access_key_id'] == inputs[2]['DOCSPEC_S3_ACCESS_KEY_ID']
    assert captured['aws_secret_access_key'] == inputs[2]['DOCSPEC_S3_SECRET_ACCESS_KEY']
    assert captured['config'].retries['total_max_attempts'] == 1


def test_local_install_uses_private_binary_without_persisting_credentials(tmp_path, inputs, monkeypatch):
    value = module()
    binary, descriptor, credentials = inputs
    client = ArtifactClient(binary)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Native process started'))
    limits = dict(compute_threads=4, memory_bytes=14*1024**3, scratch_bytes=6*1024**3,
                  batch_rows=8192, max_batch_bytes=64*1024**2, max_metadata_bytes=32*1024**2)
    limits_file = tmp_path/'limits.json'
    limits_file.write_text(json.dumps(limits))
    directory = tmp_path/'runtime'
    config, result = value.install(descriptor, credentials, tmp_path/'must-not-read-remote.json',
        directory, client=client, local_limits=limits_file)
    settings = json.loads(config.read_text())
    assert 'remote' not in settings and 'credentials' not in settings
    assert json.loads((directory/'limits.json').read_text()) == limits
    assert set(p.name for p in directory.iterdir()) == {'docspec','runtime.json','limits.json'}
    assert client.calls == [dict(Bucket=descriptor['bucket'], Key=descriptor['key'])]
    assert client.body.closed
    assert (directory/'docspec').read_bytes() == binary
    assert settings['binary_sha256'] == descriptor['sha256']
    assert result['verified'] and not result['native_provider_accessed']
    assert all(secret not in config.read_text()+json.dumps(result) for secret in credentials.values())
    from docspec_client import NativeDatasets
    with NativeDatasets.from_config(config) as native:
        assert native._remote_secrets == {}
        assert native.limits == directory/'limits.json'
    assert not (directory/'workspace').exists()


@pytest.mark.parametrize('change', [{'compute_threads': True}, {'memory_bytes': 0}, {'extra':1}])
def test_local_limits_refuse_before_download_or_secret_file_creation(tmp_path, inputs, change):
    value = module()
    binary, descriptor, credentials = inputs
    limits = dict(compute_threads=4, memory_bytes=14*1024**3, scratch_bytes=6*1024**3,
                  batch_rows=8192, max_batch_bytes=64*1024**2, max_metadata_bytes=32*1024**2)
    limits.update(change)
    policy=tmp_path/'limits.json';policy.write_text(json.dumps(limits))
    client=ArtifactClient(binary)
    with pytest.raises(ValueError,match='limits'):
        value.install(descriptor,credentials,tmp_path/'absent',tmp_path/'installed',
                      client=client,local_limits=policy)
    assert client.calls == []
    assert not (tmp_path/'installed').exists()


@pytest.mark.parametrize('doctor_fails', [False, True])
def test_local_cli_exports_only_local_paths_after_offline_doctor(tmp_path, inputs, monkeypatch, capsys, doctor_fails):
    value = module()
    binary, descriptor, credentials = inputs
    monkeypatch.setenv('DOCSPEC_RUNTIME_ARTIFACT', json.dumps(descriptor))
    monkeypatch.setenv('DOCSPEC_ENGINE_CREDENTIALS', json.dumps(credentials))
    monkeypatch.setattr(value, 'make_client', lambda creds: ArtifactClient(binary))
    calls=[]
    def doctor(command, **kwargs):
        calls.append((command, kwargs))
        assert command[-3:] == ['doctor','--lane','production-offline']
        local=json.loads(Path(kwargs['env']['DOCSPEC_JOB_CONFIG']).read_text())
        assert 'remote' not in local and 'credentials' not in local
        if doctor_fails:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(subprocess,'run',doctor)
    envfile=tmp_path/'github-env';envfile.touch()
    result=value.main(['--local','--directory',str(tmp_path/'runtime'),
        '--output',str(tmp_path/'report.json'),'--github-env',str(envfile)])
    assert calls and result == (1 if doctor_fails else 0)
    if doctor_fails:
        assert envfile.read_text() == ''
    else:
        exported=dict(line.split('=',1) for line in envfile.read_text().splitlines())
        assert set(exported)=={'DOCSPEC_JOB_CONFIG','DOCSPEC_BINARY','DOCSPEC_BINARY_SHA256'}
    output=capsys.readouterr()
    assert all(secret not in output.out+output.err+envfile.read_text() for secret in credentials.values())
