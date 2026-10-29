"""Actual Python owner loss stops owned intake while native work drains safely."""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

import pyarrow.parquet as pq
import pytest

from congress_api.retention.docspec import NativeDatasets
from native_test_helpers import native_test_util_binary


def wait_for(condition, *, seconds=15):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def running(pid, workspace):
    # A reparented child may await its new parent's reap; zombies hold no host resources.
    result = subprocess.run(['ps', '-ww', '-o', 'stat=', '-o', 'command=', '-p', str(pid)],
                            capture_output=True, text=True, check=False)
    fields = result.stdout.strip().split(maxsplit=1)
    return (len(fields) == 2 and not fields[0].startswith('Z')
            and str(workspace.resolve()) in fields[1])


@pytest.mark.skipif(os.name != 'posix', reason='exercise SIGKILL and Unix child process ownership')
@pytest.mark.parametrize('phase', ['idle', 'processing'])
def test_actual_owner_death_stops_intake_and_drains_admitted_work(tmp_path, phase):
    binary = (native_test_util_binary() if phase == 'processing'
              else os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec'))
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the owned-stdin-eof native candidate')
    marker, resume, ready = tmp_path / 'paused', tmp_path / 'resume', tmp_path / 'owner-ready.json'
    workspace = tmp_path / 'native'
    script = '''import json, sys, time
from pathlib import Path
import pyarrow as pa
from native_test_helpers import native_test_client
native = native_test_client(sys.argv[1], sys.argv[2])
host = native._execution_host()
ready = Path(sys.argv[3])
record = ready.with_suffix('.tmp')
record.write_text(json.dumps({'pid': host.process.pid, 'port': host.client.base_url.port, 'readiness': host.readiness.name}))
record.replace(ready)
if sys.argv[4] == 'processing':
    native.run_table(pa.table({'key': ['one', 'two', 'one'], 'values': [['same', None, 'same'], None, []]}), dataset='owner-custody', operation='initial', definition='v1')
while True:
    time.sleep(60)
'''
    environment = dict(os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parent) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    if phase == 'processing':
        environment.update(DOCSPEC_TEST_PAUSE_BEFORE='processing',
                           DOCSPEC_TEST_PAUSE_MARKER=str(marker),
                           DOCSPEC_TEST_RESUME_MARKER=str(resume))
    owner, pid, host = None, None, None
    try:
        with (tmp_path / 'owner.stderr').open('wb') as stderr:
            owner = subprocess.Popen([sys.executable, '-c', script, binary, str(workspace), str(ready), phase],
                                     env=environment, stdout=subprocess.DEVNULL, stderr=stderr)
            assert wait_for(ready.exists), 'actual Python owner must start the native child'
            host = json.loads(ready.read_text())
            pid = host['pid']
            if phase == 'processing':
                assert wait_for(marker.exists), 'native task must reach its durable admission handoff'
            assert running(pid, workspace)
            with socket.create_connection(('127.0.0.1', host['port']), timeout=1):
                pass
            owner.kill()
            assert owner.wait(timeout=5) != 0

        def stopped_intake():
            try:
                with socket.create_connection(('127.0.0.1', host['port']), timeout=0.1):
                    return False
            except OSError:
                return True
        assert wait_for(stopped_intake, seconds=5), 'owner EOF must stop the actual native listener'
        if phase == 'processing':
            assert running(pid, workspace), 'shutdown must drain the paused admitted task rather than kill it'
            resume.touch()
        assert wait_for(lambda: not running(pid, workspace)), 'native process must exit after owned work drains'

        with NativeDatasets(binary, workspace, limits=workspace / 'test-limits.json') as fresh:
            if phase == 'idle':
                assert fresh.retained_producer_inputs() == []
            else:
                saved, = fresh.retained_producer_inputs()
                source = Path(saved['input'])
                assert saved['bytes'] == source.stat().st_size
                table = pq.read_table(source)
                request = json.loads(Path(saved['request']).read_text())
                source.unlink()  # Known admission plus drained completion, not an automatic cleanup rule.
                pin = fresh.release('owner-custody', 'initial')
                assert fresh.run(request) == pin
                with fresh.source_batches(pin, schema=table.schema) as reader:
                    assert sorted(reader.read_all().to_pylist(), key=repr) == sorted(table.to_pylist(), key=repr)
    finally:
        resume.touch()
        if owner is not None and owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if pid is not None and running(pid, workspace):
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            if not wait_for(lambda: not running(pid, workspace), seconds=5):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if host is not None and not running(pid, workspace):
            # Test-owned readiness metadata is disposable after confirmed host exit.
            shutil.rmtree(host['readiness'], ignore_errors=True)
