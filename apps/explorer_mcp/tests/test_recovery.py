"""Failure injection at process lifetime and atomic-selection boundaries."""
import asyncio
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from congressional_explorer_mcp import release
from congressional_explorer_mcp.models import ExplorerError
from congressional_explorer_mcp.reader import Reader
from conftest import CURRENT


def test_hard_parent_death_stops_query_and_removes_only_owned_scratch(tmp_path, phase2):
    cache = tmp_path/'cache'
    selected = release.prepare(cache, phase2)
    status = tmp_path/'worker.json'
    helper = tmp_path/'parent.py'
    helper.write_text('''import asyncio,json,sys
from pathlib import Path
from congressional_explorer_mcp.release import load_selection
from congressional_explorer_mcp.worker import Worker
async def main():
    worker=Worker(load_selection(sys.argv[1]),timeout=120)
    await worker.call('query_sql',{'sql':'SELECT 1'})
    task=asyncio.create_task(worker.call('query_sql',{'sql':'SELECT i,row_number() OVER(ORDER BY hash(i)) AS ordinal FROM range(1000000000) t(i)'}))
    await asyncio.sleep(.1)
    assert not task.done()
    status=Path(sys.argv[2]); temporary=status.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid':worker.process.pid,'scratch':worker.scratch.name}))
    temporary.replace(status)
    await task
if __name__=='__main__': asyncio.run(main())
''')
    parent = subprocess.Popen([sys.executable, str(helper), str(cache), str(status)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    worker = None
    live = Reader(selected)
    try:
        deadline = time.monotonic() + 15
        while not status.exists() and parent.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert status.exists(), parent.communicate(timeout=1) if parent.poll() is not None else 'worker did not start'
        worker = json.loads(status.read_text())
        scratch = Path(worker['scratch'])
        deadline = time.monotonic() + 8
        while not list(scratch.glob('duckdb_temp*')) and parent.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert list(scratch.glob('duckdb_temp*')), 'query did not create native spill files'
        # The query is outstanding and the worker still exists before SIGKILL.
        assert subprocess.run(['ps','-o','stat=','-p',str(worker['pid'])], capture_output=True, text=True).stdout.strip()
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        state = ''
        while time.monotonic() < deadline:
            state = subprocess.run(['ps','-o','stat=','-p',str(worker['pid'])], capture_output=True, text=True).stdout.strip()
            if (not state or state.startswith('Z')) and not scratch.exists():
                break
            time.sleep(.02)
        assert not state or state.startswith('Z'), 'orphan worker is still executing'
        assert not scratch.exists()
        assert Path(live.scratch.name).is_dir()
        assert live.query_sql({'sql':'SELECT 1 AS alive'})['rows'] == [{'alive':1}]
        assert release.load_selection(cache)['release_id'] == selected['release_id']
    finally:
        live.close()
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=5)
        if worker:
            try:
                os.kill(worker['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize('stage', ['payload', 'selection'])
def test_disk_full_preserves_selection_and_cleans_partial_files(tmp_path, phase2, monkeypatch, stage):
    cache = tmp_path/'cache'
    before = release.prepare(cache, CURRENT/'manifest.json')
    previous_bytes = (cache/'selection.json').read_bytes()
    temporary_file = release.NamedTemporaryFile
    target = cache/'objects' if stage=='payload' else cache

    class FullDisk:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def write(self, data):
            self.stream.write(data[:max(1,len(data)//2)])
            raise OSError(errno.ENOSPC, 'simulated disk full')

    @contextmanager
    def full(**kwargs):
        with temporary_file(**kwargs) as stream:
            yield FullDisk(stream) if Path(kwargs['dir'])==target else stream

    with monkeypatch.context() as patch:
        patch.setattr(release, 'NamedTemporaryFile', full)
        with pytest.raises(OSError) as failure:
            release.prepare(cache, phase2)
        assert failure.value.errno == errno.ENOSPC
    assert (cache/'selection.json').read_bytes() == previous_bytes
    assert release.load_selection(cache)['release_id'] == before['release_id']
    assert not list((cache/'objects').glob('*.partial'))
    assert {p.name for p in cache.iterdir()} == {'prepare.lock','objects','selection.json'}
    assert release.prepare(cache, phase2)['release_id'] != before['release_id']


@pytest.mark.parametrize('failure', ['eof', 'reset'])
def test_partial_transfer_preserves_previous_selection(tmp_path, phase2, monkeypatch, failure):
    cache = tmp_path/'cache'
    before = release.prepare(cache, CURRENT/'manifest.json')
    opened = release.opened

    class Interrupted:
        def __init__(self, stream):
            self.stream, self.started = stream, False
        def read(self, size):
            if not self.started:
                self.started = True
                return self.stream.read(min(size,31))
            if failure=='reset':
                raise ConnectionResetError('simulated transfer reset')
            return b''

    @contextmanager
    def partial(location):
        with opened(location) as stream:
            yield Interrupted(stream) if Path(location)==phase2.parent/'witnesses.parquet' else stream

    with monkeypatch.context() as patch:
        patch.setattr(release, 'opened', partial)
        with pytest.raises((ExplorerError, ConnectionResetError)):
            release.prepare(cache, phase2)
    assert release.load_selection(cache)['release_id'] == before['release_id']
    assert not list((cache/'objects').glob('*.partial'))
    assert release.prepare(cache, phase2)['release_id'] != before['release_id']


def test_update_and_rollback_preserve_running_readers(tmp_path, phase2):
    cache = tmp_path/'cache'
    first = release.prepare(cache, CURRENT/'manifest.json')
    old_reader = Reader(first)
    newer = None
    try:
        second = release.prepare(cache, phase2)
        newer = Reader(second)
        assert old_reader.dataset_info({})['release_id'] == first['release_id']
        assert newer.dataset_info({})['release_id'] == second['release_id']
        assert old_reader.query_sql({'sql':'SELECT count(*) AS n FROM documents'})['rows'] == [{'n':7}]
        assert newer.query_sql({'sql':'SELECT count(*) AS n FROM witnesses'})['rows'] == [{'n':2}]
        rolled_back = release.prepare(cache, CURRENT/'manifest.json')
        assert rolled_back['release_id'] == first['release_id']
        assert release.load_selection(cache)['release_id'] == first['release_id']
        assert newer.query_sql({'sql':'SELECT count(*) AS n FROM witnesses'})['rows'] == [{'n':2}]
        assert old_reader.query_sql({'sql':'SELECT count(*) AS n FROM documents'})['rows'] == [{'n':7}]
    finally:
        old_reader.close()
        if newer:
            newer.close()


def test_corrupt_old_object_refuses_rollback_without_damaging_selected_release(tmp_path, phase2):
    cache = tmp_path/'cache'
    first = release.prepare(cache, CURRENT/'manifest.json')
    second = release.prepare(cache, phase2)
    old_list = Path(first['tables']['list'][0]['path'])
    assert old_list.name not in second['files']
    old_list.chmod(0o644)
    with old_list.open('r+b') as stream:
        stream.write(b'BROKEN')
    with pytest.raises(ExplorerError, match='corrupt cached object'):
        release.prepare(cache, CURRENT/'manifest.json')
    assert release.load_selection(cache)['release_id'] == second['release_id']
    # Recovery is explicit: independently prepare the retained release in a fresh cache.
    recovered = release.prepare(tmp_path/'recovered', CURRENT/'manifest.json')
    assert recovered['release_id'] == first['release_id']


def test_dead_worker_cleans_scratch_and_next_query_recovers(selection):
    from congressional_explorer_mcp.worker import Worker
    async def run():
        worker = Worker(selection)
        try:
            await worker.call('query_sql', {'sql':'SELECT 1 AS n'})
            scratch = Path(worker.scratch.name)
            worker.process.kill()
            await asyncio.to_thread(worker.process.join, 2)
            with pytest.raises(ExplorerError, match='disconnected|exited'):
                await worker.call('query_sql', {'sql':'SELECT 2 AS n'})
            assert not scratch.exists()
            assert worker.process is None
            assert (await worker.call('query_sql', {'sql':'SELECT 3 AS n'}))['rows'] == [{'n':3}]
        finally:
            await worker.close()
    asyncio.run(run())


def test_hard_killed_prepare_resumes_without_retiring_live_objects(tmp_path, phase2):
    cache = tmp_path/'cache'
    before = release.prepare(cache, CURRENT/'manifest.json')
    live = Reader(before)
    status = tmp_path/'downloading'
    helper = tmp_path/'prepare.py'
    helper.write_text('''from contextlib import contextmanager
from pathlib import Path
import sys,time
from congressional_explorer_mcp import release
opened=release.opened
class Interrupted:
    def __init__(self,stream): self.stream,self.started=stream,False
    def read(self,size):
        if not self.started:
            self.started=True
            return self.stream.read(min(size,31))
        Path(sys.argv[3]).touch()
        time.sleep(60)
        return b''
@contextmanager
def interrupt(location):
    with opened(location) as stream:
        yield Interrupted(stream) if Path(location).name=='witnesses.parquet' else stream
release.opened=interrupt
release.prepare(sys.argv[1],sys.argv[2])
''')
    parent = subprocess.Popen([sys.executable,str(helper),str(cache),str(phase2),str(status)],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline = time.monotonic()+15
        while not status.exists() and parent.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert status.exists(), parent.communicate(timeout=1) if parent.poll() is not None else 'prepare did not start'
        partials = list((cache/'objects').glob('.download-*.partial'))
        assert partials
        parent.kill(); parent.wait(timeout=5)
        assert release.load_selection(cache)['release_id']==before['release_id']
        resumed = release.prepare(cache, phase2)
        assert resumed['release_id'] != before['release_id']
        assert all(not p.exists() for p in partials)
        assert all(Path(item['path']).is_file() for item in before['files'].values())
        assert live.query_sql({'sql':'SELECT count(*) AS n FROM documents'})['rows']==[{'n':7}]
    finally:
        live.close()
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=5)


def test_partial_cleanup_requires_the_exclusive_prepare_lock(tmp_path):
    import fcntl
    release.prepare(tmp_path, CURRENT/'manifest.json')
    partial = tmp_path/'objects/.download-held.partial'
    partial.write_bytes(b'active writer bytes')
    selection_partial = tmp_path/'.selection-interrupted.partial'
    selection_partial.write_bytes(b'incomplete candidate selection')
    with (tmp_path/'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ExplorerError, match='Another prepare'):
            release.prepare(tmp_path, CURRENT/'manifest.json')
        assert partial.exists() and selection_partial.exists()
    release.prepare(tmp_path, CURRENT/'manifest.json')
    assert not partial.exists() and not selection_partial.exists()
