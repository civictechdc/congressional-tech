import importlib.util
import json
from pathlib import Path
import sys

SCRIPT = Path(__file__).parents[1] / 'scripts/capture-memory-guard.py'
spec = importlib.util.spec_from_file_location('capture_memory_guard', SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_failure_exit_and_resource_report_are_preserved(tmp_path):
    report = tmp_path / 'memory.json'
    code = guard.run([sys.executable, '-c', 'raise SystemExit(17)'], report, interval=0.01)
    assert code == 17
    assert not json.loads(report.read_text())['stopped_for_memory']


def test_memory_stop_allows_capture_to_checkpoint_but_still_fails(tmp_path):
    ready, checkpoint = tmp_path / 'ready', tmp_path / 'checkpoint'
    command = [sys.executable, '-c',
        'import signal,time,pathlib; '
        f'checkpoint=pathlib.Path({str(checkpoint)!r}); '
        'signal.signal(signal.SIGTERM, lambda *_: (checkpoint.write_text("saved"), exit(0))); '
        f'pathlib.Path({str(ready)!r}).touch(); time.sleep(10)']
    report = tmp_path / 'memory.json'
    code = guard.run(command, report, interval=0.01, limit_bytes=1,
                     sample=lambda pid: 2 if ready.exists() else 0)
    assert code == 1
    assert checkpoint.read_text() == 'saved'
    result = json.loads(report.read_text())
    assert result['stopped_for_memory'] and result['child_exit_code'] == 0
