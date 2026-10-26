"""Remote journal fetches overlap within a fixed window; acceptance stays ordered."""
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from botocore.exceptions import ClientError

from viewer_publication import continuation as state


class Remote:
    def __init__(self):
        self.objects = {}
        self.puts = 0
        self.bodies = []

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        raw = self.objects[Key]
        stream = io.BytesIO(raw)
        self.bodies.append(stream)
        return dict(Body=stream, ContentLength=len(raw), ETag=hashlib.sha256(raw).hexdigest())

    def put_object(self, **options):
        assert options['IfNoneMatch'] == '*'
        if options['Key'] in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.objects[options['Key']] = options['Body']
        self.puts += 1
        return dict(ETag=hashlib.sha256(options['Body']).hexdigest())

    def get_paginator(self, name):
        remote = self
        class Pages:
            def paginate(self, *, Bucket, Prefix):
                # Listing order must not become fetch/validation order.
                yield dict(Contents=[dict(Key=key) for key in reversed(remote.objects)
                                     if key.startswith(Prefix)])
        return Pages()


@pytest.fixture
def history(tmp_path):
    run = state.Continuation(tmp_path / 'attempt', {'fixture': True})
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'restore-fixture', {'prepared': True})
    for index in range(17):
        log.record('progress', {'index': index})
    return log, run, remote


def restore(history):
    log, run, remote = history
    return state.DurableJournal(remote, 'bucket', run, 'restore-fixture',
                                {'prepared': True}, resume=True)


def snapshot(run):
    return ({str(path.relative_to(run.root)): path.read_bytes()
             for path in run.root.rglob('*') if path.is_file()},
            json.dumps(run.value, sort_keys=True))


def test_out_of_order_fetch_has_fixed_window_and_ordered_validation(history, monkeypatch):
    log, run, remote = history
    window = getattr(state, 'JOURNAL_RESTORE_WORKERS', 6)
    release_first, window_started, beyond_window = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    started, finished, validated = [], [], []
    active, peak = 0, 0
    original_get, original_apply = remote.get_object, state.apply_event
    def get(**options):
        nonlocal active, peak
        index = int(options['Key'].rsplit('/', 1)[1].split('.')[0])
        with lock:
            started.append(index)
            active += 1
            peak = max(peak, active)
            if len(started) == window:
                window_started.set()
            if len(started) > window and not release_first.is_set():
                beyond_window.set()
        try:
            if index == 0:
                assert release_first.wait(5), 'test did not release first fetch'
            response = original_get(**options)
            with lock:
                finished.append(index)
            return response
        finally:
            with lock:
                active -= 1
    def apply(value, event, detail):
        validated.append(-1 if event == 'attempt_started' else detail['index'])
        return original_apply(value, event, detail)
    monkeypatch.setattr(remote, 'get_object', get)
    monkeypatch.setattr(state, 'apply_event', apply)
    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(restore, history)
        try:
            assert window_started.wait(2), 'journal fetches did not overlap'
            assert not beyond_window.wait(.1), 'fetch window advanced past an unvalidated first event'
            assert len(started) == window
            assert validated == []
        finally:
            release_first.set()
        restored = future.result(timeout=5)
    assert finished[0] != 0 and 2 <= peak <= window
    assert sorted(started) == list(range(log.sequence))  # One GET per event, no retry.
    assert validated == list(range(-1, 17))
    assert restored.sequence == log.sequence
    assert not list(run.root.glob('.journal-restore-*'))
    assert all(stream.closed for stream in remote.bodies)


@pytest.mark.parametrize('failure', ['late_corruption', 'fetch', 'interrupt', 'spool_write'])
def test_failed_restore_keeps_accepted_state_and_cleans_spool(history, monkeypatch, failure):
    log, run, remote = history
    before, puts = snapshot(run), remote.puts
    original_get, original_write = remote.get_object, state.write_atomic_bytes
    staged = []
    def write(path, raw, **options):
        if any(part.startswith('.journal-restore-') for part in path.parts):
            staged.append(path)
            if failure == 'spool_write':
                raise OSError('spool full')
            assert options.get('fsync') is False  # Disposable staging is not a checkpoint.
        return original_write(path, raw, **options)
    monkeypatch.setattr(state, 'write_atomic_bytes', write)
    last = log.prefix + f'{log.sequence - 1:08d}.json'
    if failure == 'late_corruption':
        event = json.loads(remote.objects[last])
        event['previous'] = '0' * 64
        remote.objects[last] = json.dumps(event).encode()
    elif failure in ('fetch', 'interrupt'):
        def get(**options):
            if options['Key'] == last:
                if failure == 'interrupt':
                    raise KeyboardInterrupt('interrupted fetch')
                raise OSError('remote unavailable')
            return original_get(**options)
        monkeypatch.setattr(remote, 'get_object', get)
    with pytest.raises((ValueError, OSError, KeyboardInterrupt)):
        restore(history)
    assert staged, 'restore did not stage raw journal evidence on disk'
    assert snapshot(run) == before and remote.puts == puts
    assert not list(run.root.glob('.journal-restore-*'))
    assert all(stream.closed for stream in remote.bodies)


def test_complete_prefix_is_staged_before_acceptance_and_spool_is_removed(history, monkeypatch):
    log, run, remote = history
    original_accept = run.accept_saved
    staged_counts = []
    def accept(source, name, **options):
        if name.startswith('journal/'):
            staged_counts.append(sum(1 for path in run.root.glob('.journal-restore-*/*.json')))
        return original_accept(source, name, **options)
    monkeypatch.setattr(run, 'accept_saved', accept)
    puts = remote.puts
    restored = restore(history)
    assert staged_counts == [log.sequence] * log.sequence
    assert restored.sequence == log.sequence and remote.puts == puts
    assert not list(run.root.glob('.journal-restore-*'))


def test_changed_spool_is_refused_before_publishing_accepted_evidence(history, monkeypatch):
    log, run, remote = history
    before = snapshot(run)
    original = state.validate_state
    def validate(value):
        result = original(value)
        staged = next(run.root.glob('.journal-restore-*/00000000.json'))
        staged.write_bytes(b'changed validated spool')
        return result
    monkeypatch.setattr(state, 'validate_state', validate)
    with pytest.raises(ValueError, match='custody changed'):
        restore(history)
    assert snapshot(run) == before
    assert not list(run.root.glob('.journal-restore-*'))


def test_acceptance_save_failure_also_removes_spool(history, monkeypatch):
    log, run, remote = history
    before = snapshot(run)
    def unavailable(*args, **kwargs):
        raise OSError('accepted evidence save failed')
    monkeypatch.setattr(run, 'accept_saved', unavailable)
    with pytest.raises(OSError, match='accepted evidence save failed'):
        restore(history)
    assert snapshot(run) == before
    assert not list(run.root.glob('.journal-restore-*'))


@pytest.mark.parametrize('existing', [False, True])
def test_restore_links_new_evidence_with_one_sync_and_does_not_rewrite(history, monkeypatch, existing):
    log, run, remote = history
    if not existing:
        for path in (run.root / 'journal').glob('*.json'):
            path.unlink()
    syncs, accepted, evidence_writes = [], [], []
    original_sync, original_accept, original_write = state.os.fsync, run.accept_saved, state.write_atomic_bytes
    def sync(fd):
        syncs.append(fd)
        return original_sync(fd)
    def write(path, raw, **options):
        if path.parent.name == 'journal':
            evidence_writes.append(path)
        return original_write(path, raw, **options)
    def accept(source, name, **options):
        assert options['fsync'] is True
        result = original_accept(source, name, **options)
        if not existing:
            assert (run.root / source).samefile(run.root / name)
        accepted.append(name)
        return result
    monkeypatch.setattr(state.os, 'fsync', sync)
    monkeypatch.setattr(state, 'write_atomic_bytes', write)
    monkeypatch.setattr(run, 'accept_saved', accept)
    restore(history)
    assert len(accepted) == log.sequence and not evidence_writes
    assert len(syncs) == (0 if existing else log.sequence) + 2  # Derived JSON file and directory.
    assert not list(run.root.glob('.journal-restore-*'))


def test_aggregate_spool_budget_and_declared_body_size_remain_bounded(history, monkeypatch):
    log, run, remote = history
    expected = sum(len(raw) for key, raw in remote.objects.items() if key.startswith(log.prefix))
    original_write = state.write_atomic_bytes
    staged_bytes = 0
    lock = threading.Lock()
    def write(path, raw, **options):
        nonlocal staged_bytes
        if any(part.startswith('.journal-restore-') for part in path.parts):
            with lock:
                staged_bytes += len(raw)
                assert staged_bytes <= state.MAX_JOURNAL_BYTES
        return original_write(path, raw, **options)
    monkeypatch.setattr(state, 'write_atomic_bytes', write)
    before = snapshot(run)
    monkeypatch.setattr(state, 'MAX_JOURNAL_BYTES', expected - 1)
    with pytest.raises(ValueError, match='total byte limit'):
        restore(history)
    assert snapshot(run) == before and 0 < staged_bytes < expected
    assert not list(run.root.glob('.journal-restore-*'))
    staged_bytes = 0
    monkeypatch.setattr(state, 'MAX_JOURNAL_BYTES', expected)
    assert restore(history).total_bytes == expected
    assert staged_bytes == expected


def test_counted_capacity_acceptance_hooks_skip_per_event_sync(history, monkeypatch):
    log, run, remote = history
    saves, accepts, syncs = [], [], []
    original_sync = state.os.fsync
    monkeypatch.setattr(run, 'save', lambda *args, **kwargs: saves.append(args))
    monkeypatch.setattr(run, 'accept_saved', lambda *args, **kwargs: accepts.append(args))
    monkeypatch.setattr(state.os, 'fsync', lambda fd: syncs.append(fd) or original_sync(fd))
    assert restore(history).sequence == log.sequence
    assert len(accepts) == log.sequence and not saves
    assert len(syncs) == 2  # Only the real derived checkpoint; capacity callbacks stay cheap.
    assert not list(run.root.glob('.journal-restore-*'))


@pytest.mark.parametrize('declared', [True, -1, None, 2 ** 30, 0])
def test_malformed_or_incomplete_fetch_never_accepts_evidence(history, monkeypatch, declared):
    log, run, remote = history
    before = snapshot(run)
    original = remote.get_object
    def get(**options):
        response = original(**options)
        response['ContentLength'] = declared
        return response
    monkeypatch.setattr(remote, 'get_object', get)
    with pytest.raises(ValueError, match='event byte limit|Incomplete publication journal read'):
        restore(history)
    assert snapshot(run) == before
    assert not list(run.root.glob('.journal-restore-*'))
    assert all(stream.closed for stream in remote.bodies)
