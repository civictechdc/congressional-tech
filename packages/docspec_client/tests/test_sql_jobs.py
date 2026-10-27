"""The SQL client reuses the native executable adapter and retains failures."""
from hashlib import sha256
import json
from pathlib import Path
import shlex

import pytest

from docspec_client.client import NativeDatasets
from docspec_client.models import DocSpecFailure


def executable(tmp_path, *, failure=False):
    log = tmp_path / 'arguments'
    payload = ({'status': 'failed', 'completed': {'steps': [], 'outputs': [
        {'name': 'one.parquet', 'sha256': 'a' * 64, 'size': 10, 'rows': 1}]},
        'error': {'code': 'invalid_export', 'message': 'second output failed'}}
        if failure else {'steps': [], 'outputs': []})
    body = (f'#!/bin/sh\nprintf "%s\\n" "$@" > {shlex.quote(str(log))}\n'
            f'printf "%s\\n" {shlex.quote(json.dumps(payload))}\n'
            + ('printf "second output failed\\n" >&2\nexit 1\n' if failure else ''))
    binary = tmp_path / 'engine'
    binary.write_text(body)
    binary.chmod(0o700)
    limits = tmp_path / 'limits.json'
    limits.write_text('{}')
    client = NativeDatasets(binary=binary, workspace=tmp_path / 'unused', limits=limits,
                            source_revision='a' * 40, binary_sha256=sha256(body.encode()).hexdigest())
    return client, log, binary


def test_sql_job_uses_the_configured_verified_executable(tmp_path):
    client, log, _ = executable(tmp_path)
    spec = tmp_path / 'job.json'
    spec.write_text('{}')
    assert client.run_job(spec) == {'steps': [], 'outputs': []}
    args = log.read_text().splitlines()
    assert args[-3:] == ['job', '--spec', str(spec)]
    assert '--limits' in args
    assert not (tmp_path / 'unused').exists()


def test_job_failure_preserves_the_native_completed_output_identities(tmp_path):
    client, _, _ = executable(tmp_path, failure=True)
    with pytest.raises(DocSpecFailure) as raised:
        client.run_job(tmp_path / 'job.json')
    assert raised.value.returncode == 1
    assert raised.value.completed['outputs'][0]['name'] == 'one.parquet'
    assert json.loads(raised.value.stdout)['status'] == 'failed'


@pytest.mark.parametrize('missing', ['limits', 'binary_sha256', 'source_revision'])
def test_job_refuses_missing_pins_or_limits_before_executing(tmp_path, missing):
    client, log, _ = executable(tmp_path)
    setattr(client, missing, None)
    with pytest.raises(ValueError, match='limits|pin'):
        client.run_job(tmp_path / 'job.json')
    assert not log.exists()


def test_job_refuses_changed_binary_before_executing(tmp_path):
    client, log, binary = executable(tmp_path)
    binary.write_text('#!/bin/sh\nexit 0\n')
    with pytest.raises(ValueError, match='SHA-256'):
        client.run_job(tmp_path / 'job.json')
    assert not log.exists()


def test_job_refuses_lifecycle_remote_configuration(tmp_path):
    client, log, _ = executable(tmp_path)
    client.remote = Path('not-opened.json')
    with pytest.raises(ValueError, match='remote'):
        client.run_job(tmp_path / 'job.json')
    assert not log.exists()
