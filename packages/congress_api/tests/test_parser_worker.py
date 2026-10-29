"""A persistent parser cannot hold the work list open on one damaged input."""
import os
import time

import pytest

from congress_api.retention.parser_worker import ParserWorker


@pytest.fixture
def parser(tmp_path):
    path = tmp_path / 'fixture_parser.py'
    path.write_text('''import os, time, weakref
count = 0
previous = None
class Reading(dict): pass
def parse(body):
    global count, previous
    count += 1
    if body == b"retained":
        if previous is not None and previous() is not None: os._exit(13)
        result = Reading(pid=os.getpid(), count=count)
        result.working = bytearray(40 * 1024**2)
        previous = weakref.ref(result)
        return result
    if body == b"crash": os._exit(12)
    if body == b"hang": time.sleep(30)
    if body == b"reading":
        from congress_api.retention.parser_worker import reading_input
        with reading_input(): time.sleep(30)
    if body == b"unknown_phase":
        open(os.environ['DOCSPEC_PARSER_IO_MARKER'], "w").write("unknown")
        os._exit(12)
    if body == b"memory":
        data = bytearray(180 * 1024**2)
        time.sleep(30)
    if body == b"output": return {"data": "x" * 100000}
    if body.startswith(b"once:"):
        path = body[5:].decode()
        if not os.path.exists(path):
            open(path, "w").close()
            os._exit(12)
    return {"pid": os.getpid(), "count": count, "status": "error" if body == b"rejected" else "ok"}
''')
    return str(path) + ':parse'


def worker(parser, **overrides):
    settings = dict(timeout_seconds=.5, memory_bytes=96 * 1024**2,
                    max_input_bytes=4096, max_output_bytes=4096)
    return ParserWorker('fixture', 'v1', parser, **(settings | overrides))


def test_worker_reuses_initialized_process_and_normal_rejection(parser):
    with worker(parser) as run:
        first = run.parse('one', b'valid')
        rejected = run.parse('two', b'rejected')
        assert first['status'] == rejected['status'] == 'completed'
        assert first['value']['pid'] == rejected['value']['pid']
        assert rejected['value']['count'] == 2
        assert rejected['value']['status'] == 'error'
        pid = first['value']['pid']
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize('body,reason', [(b'crash', 'parser_crash'), (b'hang', 'timeout'),
                                      (b'memory', 'memory_limit'), (b'output', 'output_limit')])
def test_two_failures_settle_one_input_and_next_input_can_run(parser, body, reason):
    with worker(parser) as run:
        start = time.monotonic()
        result = run.parse('bad', body)
        assert result == {'status': 'unreadable', 'reason': reason, 'attempts': 2}
        assert time.monotonic() - start < 10
        assert run.parse('next', b'valid')['status'] == 'completed'


def test_one_crash_retries_successfully(parser, tmp_path):
    with worker(parser) as run:
        assert run.parse('once', ('once:' + str(tmp_path / 'marker')).encode())['status'] == 'completed'


def test_input_bound_refuses_before_invocation(parser):
    with worker(parser, max_input_bytes=3) as run:
        assert run.parse('large', b'four') == {'status': 'size_limit'}
        assert run.parse('one', b'ok')['value']['count'] == 1


def test_startup_error_is_not_an_unreadable_input(tmp_path):
    with pytest.raises(RuntimeError, match='startup'):
        with worker(str(tmp_path / 'missing.py') + ':parse'):
            pytest.fail('invalid parser initialized')


def test_worker_requires_valid_settings_and_an_open_context(parser):
    with pytest.raises(ValueError):
        worker(parser, timeout_seconds=0)
    run = worker(parser)
    with pytest.raises(RuntimeError, match='context'):
        run.parse('one', b'valid')


def test_completed_large_result_is_released_before_the_next_invocation(parser):
    # Include the installed package imports as well as this reading's working state.
    with worker(parser, memory_bytes=256 * 1024**2) as run:
        first = run.parse('one', b'retained')
        second = run.parse('two', b'retained')
        assert first['status'] == second['status'] == 'completed'
        assert first['value']['pid'] == second['value']['pid']
        assert second['value']['count'] == 2


def test_hung_raw_read_remains_pending_instead_of_becoming_unreadable(parser):
    with worker(parser) as run:
        assert run.parse('missing', b'reading') == {'status': 'read_error', 'reason': 'timeout'}
        assert run.parse('next', b'valid')['status'] == 'completed'


def test_unknown_raw_phase_is_pending_after_the_child_has_stopped(parser):
    with worker(parser) as run:
        assert run.parse('uncertain', b'unknown_phase') == {'status': 'read_error', 'reason': 'parser_crash'}
        assert run.parse('next', b'valid')['status'] == 'completed'


@pytest.mark.parametrize('pooled',[False,True])
def test_exhausted_get_crosses_the_real_worker_boundary_without_retry_or_unreadable(tmp_path,pooled):
    from congress_api.retention.parser_worker import ParserWorkerPool
    from congress_api.retention.r2 import R2GetTransportExhausted
    from test_readings_ranged import payload
    attempts=tmp_path/'attempts'
    parser=tmp_path/'transport_reader.py'
    parser.write_text('''import boto3
from pathlib import Path
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from congress_api.lake.readings import parse_once_payload
from congress_api.retention.r2 import R2Store
import botocore.endpoint
client=boto3.client('s3',endpoint_url='https://r2.example.test',region_name='auto',
    aws_access_key_id='test',aws_secret_access_key='test',
    config=Config(retries={'total_max_attempts':1,'mode':'legacy'}))
def send(request):
    with Path('''+repr(str(attempts))+''').open('a') as stream:stream.write('GET\\n')
    raise ReadTimeoutError(endpoint_url='https://r2.example.test')
client._endpoint.http_session.send=send
botocore.endpoint.time.sleep=lambda delay:None
store=R2Store(client,'bucket',read_throttle_attempts=5)
def parse(body):return parse_once_payload(body,body_store=store)
''')
    args=('fixture','v1',str(parser)+':parse')
    limits=dict(timeout_seconds=10,memory_bytes=512<<20,max_input_bytes=65536,max_output_bytes=4096)
    request=payload(tmp_path,b'body',b'body')
    with pytest.raises(R2GetTransportExhausted,match='after 5 attempts'):
        if pooled:
            with ParserWorkerPool(*args,workers=1,memory_budget=512<<20,**limits) as run:
                list(run.map(lambda reader,body:reader.parse('body',body),[request]))
        else:
            with ParserWorker(*args,**limits) as run:run.parse('body',request)
    assert attempts.read_text().splitlines()==['GET']*5
