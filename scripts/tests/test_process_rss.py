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

