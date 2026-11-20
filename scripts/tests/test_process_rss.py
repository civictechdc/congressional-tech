"""Exited and zombie descendants do not invalidate a physical memory sample."""
import errno
import importlib.util
from pathlib import Path

import pytest


path=Path(__file__).resolve().parents[1]/'measure/process_rss.py'
spec=importlib.util.spec_from_file_location('process_rss_contract',path)
sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)


@pytest.mark.parametrize('code',[errno.EPERM,errno.ESRCH])
def test_exited_or_zombie_child_is_skipped_but_live_permission_errors_remain_errors(code):
    def sample(pid):
        if pid==2:raise OSError(code,'child exited')
        return 123
    assert sampler._physical_sum([1,2],sample,lambda pid:pid==1)==123
    with pytest.raises(OSError):sampler._physical_sum([1,2],sample,lambda pid:True)


def test_signal_recorder_restores_handlers_and_wakes_within_slice():
    import signal
    import types

    clock, slept = [0.0], []

    def sleep(seconds):
        if not slept:
            handler = signal.getsignal(signal.SIGTERM)
            handler(int(signal.SIGTERM), None)
        slept.append(seconds)
        clock[0] += seconds

    fake_clock = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
    before = {num: signal.getsignal(num) for num in sampler.STOP_SIGNALS}
    try:
        with sampler.SignalRecorder(clock=fake_clock) as signals:
            assert signals.first is None
            assert signals.sleep(0.5) is True
            assert signals.first == int(signal.SIGTERM)
            assert slept == [sampler.WAKE_SECONDS]
        assert {num: signal.getsignal(num) for num in before} == before
    finally:
        for num, handler in before.items():
            signal.signal(num, handler)


@pytest.mark.parametrize('failed_action', ['poll', 'term', 'term_wait', 'kill', 'kill_wait'])
def test_cleanup_failure_does_not_skip_later_termination_attempts(failed_action):
    import signal

    attempts = []

    class Child:
        waits = 0

        def poll(self):
            if failed_action == 'poll':
                raise OSError('injected poll failure')
            return None

        def wait(self, timeout):
            assert timeout == 5
            self.waits += 1
            action = 'term_wait' if self.waits == 1 else 'kill_wait'
            attempts.append(action)
            if action == failed_action:
                raise OSError('injected wait failure')
            return 0

    def send(number):
        action = 'term' if number == signal.SIGTERM else 'kill'
        attempts.append(action)
        if action == failed_action:
            raise PermissionError('injected signal failure')

    notes = sampler._cleanup_child(Child(), send)
    assert attempts == ['term', 'term_wait', 'kill', 'kill_wait']
    assert len(notes) == 1 and notes[0]['action'] == failed_action and notes[0]['type']


def test_empty_system_process_inventory_is_unknown(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(sampler.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=''))
    with pytest.raises(RuntimeError, match='no rows'):
        sampler.group_members(123)


