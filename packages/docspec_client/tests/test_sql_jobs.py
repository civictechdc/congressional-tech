"""The SQL client reuses the native executable adapter and retains failures."""
from hashlib import sha256
import json
from pathlib import Path
import shlex
import subprocess

import pytest

from docspec_client.client import NativeDatasets
from docspec_client.models import DocSpecFailure


STEP = {'event': 'step', 'name': 'one', 'rows': 3, 'step_index': 0, 'storage': 'memory'}
RELEASE = {'event': 'release', 'released_name': 'one', 'bytes_released': 96}
METRICS = ''.join(f'[docspec-metric] {json.dumps(event)}\n' for event in (STEP, RELEASE))


def executable(tmp_path, *, failure=False, stderr=''):
    log = tmp_path / 'arguments'
    payload = ({'status': 'failed', 'completed': {'steps': [], 'outputs': [
        {'name': 'one.parquet', 'sha256': 'a' * 64, 'size': 10, 'rows': 1}]},
        'error': {'code': 'invalid_export', 'message': 'second output failed'}}
        if failure else {'steps': [], 'outputs': []})
    body = (f'#!/bin/sh\nprintf "%s\\n" "$@" > {shlex.quote(str(log))}\n'
            f'printf "%s\\n" {shlex.quote(json.dumps(payload))}\n'
            f'printf "%s" {shlex.quote(stderr)} >&2\n'
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


def test_job_failure_leads_with_the_engine_error_and_keeps_the_whole_stream(tmp_path):
    """Nightly 20261110T111252Z: 808 metric lines came before the one line that said what failed."""
    client, _, _ = executable(tmp_path, failure=True, stderr=METRICS)
    with pytest.raises(DocSpecFailure, match='second output failed') as raised:
        client.run_job(tmp_path / 'job.json')
    assert str(raised.value).splitlines() == ['invalid_export: second output failed', 'second output failed']
    assert '[docspec-metric]' not in str(raised.value)
    assert raised.value.stderr == METRICS + 'second output failed\n'
    assert raised.value.code is None  # as before: the report's code is a pre-admission name with no reader on this path
    silent = subprocess.CompletedProcess(['docspec'], 7, stdout='', stderr=METRICS)
    assert str(DocSpecFailure(['docspec'], silent)) == 'DocSpec exited 7'


def test_a_failure_without_a_report_or_metric_lines_keeps_its_stderr_as_the_message():
    diagnostic = '{"code": "no_release", "message": "nothing selected", "pre_admission": true}'
    for stdout in ('', None):
        refusal = subprocess.CompletedProcess(['GET', '/datasets/x/latest'], 404, stdout=stdout, stderr=diagnostic + '\n')
        error = DocSpecFailure(refusal.args, refusal)
        assert str(error) == diagnostic and (error.code, error.pre_admission, error.completed) == ('no_release', True, None)


@pytest.mark.parametrize('failure', [False, True])
def test_job_log_keeps_the_engine_stream_whether_the_job_passes_or_fails(tmp_path, failure):
    from docspec_client.models import metric_events
    client, _, _ = executable(tmp_path, failure=failure, stderr=METRICS)
    log = tmp_path / 'engine.log'
    if failure:
        with pytest.raises(DocSpecFailure) as raised:
            client.run_job(tmp_path / 'job.json', log=log)
        assert raised.value.stderr == log.read_text() == METRICS + 'second output failed\n'
        assert str(raised.value).splitlines()[0] == 'invalid_export: second output failed'
    else:
        assert client.run_job(tmp_path / 'job.json', log=log) == {'steps': [], 'outputs': []}
        assert log.read_text() == METRICS
    assert list(metric_events(log)) == [STEP, RELEASE]


@pytest.mark.parametrize('spoil,kept', [('rm -f {log}', ''), ("printf '\\377\\n' >&2", METRICS + 'second output failed\n\ufffd\n')],
                         ids=['removed', 'not-text'])
def test_a_failed_job_raises_the_engine_failure_whatever_became_of_its_log(tmp_path, spoil, kept):
    """A log removed under the job, or holding bytes that are not text, must not replace the failure."""
    client, _, binary = executable(tmp_path, failure=True, stderr=METRICS)
    log = tmp_path / 'engine.log'
    body = binary.read_text().replace('exit 1\n', spoil.format(log=shlex.quote(str(log))) + '\nexit 1\n')
    binary.write_text(body)
    client.binary_sha256 = sha256(body.encode()).hexdigest()
    with pytest.raises(DocSpecFailure) as raised:
        client.run_job(tmp_path / 'job.json', log=log)
    assert raised.value.returncode == 1 and raised.value.completed['outputs'][0]['name'] == 'one.parquet'
    assert str(raised.value).splitlines()[0] == 'invalid_export: second output failed'
    assert raised.value.stderr == kept


def test_job_log_outlives_a_timeout(tmp_path):
    client, _, binary = executable(tmp_path, stderr=METRICS)
    body = binary.read_text() + 'exec sleep 30\n'
    binary.write_text(body)
    client.binary_sha256, client.timeout = sha256(body.encode()).hexdigest(), 1
    with pytest.raises(subprocess.TimeoutExpired):
        client.run_job(tmp_path / 'job.json', log=tmp_path / 'engine.log')
    assert (tmp_path / 'engine.log').read_text() == METRICS


def test_job_without_a_log_writes_nothing_new(tmp_path):
    client, arguments, _ = executable(tmp_path, stderr=METRICS)
    before = sorted(tmp_path.iterdir())
    client.run_job(tmp_path / 'job.json')
    assert sorted(tmp_path.iterdir()) == sorted([*before, arguments])


def test_metric_events_read_a_whole_last_line_and_report_a_torn_one(tmp_path):
    from docspec_client.models import TornMetricLine, metric_events
    log = tmp_path / 'engine.log'
    log.write_text('warning: not a metric\n' + METRICS + 'Error: query: failed\n' + METRICS.rstrip('\n'))
    assert list(metric_events(log)) == [STEP, RELEASE, STEP, RELEASE]  # a last line with no newline that parses is an event
    log.write_text(METRICS + 'Error: que')  # other text cut short is not a metric line
    assert list(metric_events(log)) == [STEP, RELEASE]
    steps = tmp_path / 'steps.jsonl'  # DOCSPEC_STEP_LOG holds the same events without the prefix.
    whole = ''.join(json.dumps(event) + '\n' for event in (STEP, RELEASE))
    steps.write_text(whole + json.dumps(STEP))
    assert list(metric_events(steps, prefix='')) == [STEP, RELEASE, STEP]
    # A kill mid-line: every whole event is read, then the caller is told, whether the cut fell in the event or in the prefix.
    for path, prefix, torn in ((log, '[docspec-metric] ', METRICS + '[docspec-metric] {"event":"st'),
                               (log, '[docspec-metric] ', METRICS + '[docspec-me'), (steps, '', whole + '{"event":"st')):
        path.write_text(torn)
        events = metric_events(path, prefix=prefix)
        assert [next(events), next(events)] == [STEP, RELEASE]
        with pytest.raises(TornMetricLine, match=path.name):
            next(events)
    log.write_text('[docspec-metric] {oops\n' + METRICS)  # a whole line that does not parse is damage, not a torn line
    with pytest.raises(json.JSONDecodeError):
        list(metric_events(log))


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


def test_job_forwards_explicit_remote_connection_and_named_secrets(tmp_path):
    client, log, binary = executable(tmp_path)
    client.remote = tmp_path / 'remote.json'
    client._remote_secrets = {'DOCSPEC_FIXTURE_SECRET': 'dummy-fixture'}
    body = binary.read_text().replace('#!/bin/sh\n', '#!/bin/sh\n'
        'test "$DOCSPEC_FIXTURE_SECRET" = dummy-fixture || exit 93\n')
    binary.write_text(body)
    client.binary_sha256 = sha256(body.encode()).hexdigest()
    assert client.run_job(tmp_path / 'job.json') == {'steps': [], 'outputs': []}
    arguments = log.read_text().splitlines()
    assert arguments[arguments.index('--remote') + 1] == str(client.remote)
    assert arguments[-3:] == ['job', '--spec', str(tmp_path / 'job.json')]


def test_create_file_forwards_to_same_pinned_remote_adapter(tmp_path):
    client, log, _ = executable(tmp_path)
    client.remote = tmp_path / 'remote.json'
    assert client.create_file(tmp_path / 'upload.json') == {'steps': [], 'outputs': []}
    arguments = log.read_text().splitlines()
    assert arguments[-3:] == ['create-file', '--spec', str(tmp_path / 'upload.json')]
    assert arguments[arguments.index('--remote') + 1] == str(client.remote)


@pytest.mark.parametrize('missing', ['remote', 'limits', 'binary_sha256', 'source_revision'])
def test_create_file_refuses_missing_configuration_before_executing(tmp_path, missing):
    client, log, _ = executable(tmp_path)
    client.remote = tmp_path / 'remote.json'
    setattr(client, missing, None)
    with pytest.raises(ValueError, match='remote|limits|pin'):
        client.create_file(tmp_path / 'upload.json')
    assert not log.exists()
