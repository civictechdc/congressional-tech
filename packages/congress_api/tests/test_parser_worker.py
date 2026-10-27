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
    with worker(parser) as run:
        first = run.parse('one', b'retained')
        second = run.parse('two', b'retained')
        assert first['status'] == second['status'] == 'completed'
        assert first['value']['pid'] == second['value']['pid']
        assert second['value']['count'] == 2
