"""scripts/run_lanes.py stamps completion after each child exits, closes parent log fds, and locks cleanly."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / 'scripts/run_lanes.py'


def load_run_lanes():
    spec = importlib.util.spec_from_file_location('run_lanes', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_lanes_stamps_completion_after_process_wait_and_releases_lock(tmp_path, monkeypatch):
    """ct-dagf (7): f'{stamp()} ... {process.wait()}' previously evaluated stamp() before wait()."""
    run_lanes = load_run_lanes()
    events = []
    clock = [0]

    def fake_stamp():
        clock[0] += 1
        tag = f'T{clock[0]:02d}'
        events.append(('stamp', tag))
        return tag

    class FakeProc:
        def __init__(self, label, rc=0):
            self.label = label
            self.rc = rc

        def wait(self):
            events.append(('wait', self.label))
            return self.rc

    worktree = tmp_path / 'wt'
    for i in range(1, 7):
        rt = worktree / f'.cache/local-runtime/shard-{i}/runtime.json'
        rt.parent.mkdir(parents=True, exist_ok=True)
        rt.write_text('{}')
    logs = tmp_path / 'logs'
    lock_dir = tmp_path / 'heavy-slot.lock'

    monkeypatch.setattr(run_lanes, 'stamp', fake_stamp)
    monkeypatch.setattr(run_lanes, 'default_lock_path', lambda wt: lock_dir)
    monkeypatch.setattr(run_lanes, 'lane', lambda wt, lg, name, args, rt: FakeProc(name))
    monkeypatch.setattr(run_lanes.subprocess, 'run',
                        lambda cmd, **kw: type('R', (), {'stdout': 'abc1234\n' if 'rev-parse' in cmd else ''})())

    assert run_lanes.run_driver(worktree, logs, take_lock=True) == 0
    assert not lock_dir.exists()
    driver_lines = (logs / 'driver.log').read_text().splitlines()
    assert any('production-offline (shard 1/6): exit 0' in line for line in driver_lines)
    assert any('storage-loopback (full lane): exit 0' in line for line in driver_lines)
    assert driver_lines[-1].endswith('DONE')

    # Crucial ordering invariant: each wait(name) happens BEFORE the stamp() used on its exit line!
    wait_idx = {label: idx for idx, (kind, label) in enumerate(events) if kind == 'wait'}
    stamp_idx = {label: idx for idx, (kind, label) in enumerate(events) if kind == 'stamp'}
    for line in driver_lines:
        if 'production-offline (shard ' in line and ': exit ' in line:
            tag = line.split()[0]
            shard_num = line.split('(shard ')[1].split('/')[0]
            assert wait_idx[f'shard-{shard_num}'] < stamp_idx[tag], (line, events)
        elif 'storage-loopback (full lane): exit ' in line:
            tag = line.split()[0]
            assert wait_idx['storage-loopback'] < stamp_idx[tag], (line, events)
