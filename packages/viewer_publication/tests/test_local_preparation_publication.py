"""Local custody replaces hosted artifact metadata, never output admission."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import stat

from viewer_publication.local import read_local_journal

import pytest

from test_viewer_publication_attempt import source, configured_native_fixture, ready
from viewer_publication import attempt

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('local_preparation_publisher',
    ROOT / 'scripts/publication/publish_local_preparation.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


@pytest.fixture(autouse=True)
def no_github(monkeypatch):
    monkeypatch.setattr(attempt, 'github_json', lambda *args: pytest.fail('Local publication contacted GitHub'))


def publish(ready, **kwargs):
    remote, root, _ = ready
    return local.publish_local(remote, root, probe=lambda *args: None, **kwargs)


def test_local_preparation_publishes_and_explicitly_resumes_without_artifact_service(ready):
    remote, root, prepared = ready
    remote.reject_journal = True  # Any accidental remote journal PUT must fail this route.
    assert publish(ready)['status'] == 'published'
    custody = json.loads((root / local.RECEIPT).read_bytes())
    assert custody['kind'] == 'local_preparation' and custody['run_id'] == '123'
    assert custody['preparation_sha256'] == prepared['preparation_sha256']
    assert custody['directory'] == str(root.resolve()) and 'id' not in custody
    assert custody['journal_mode'] == 'local'
    assert not any(key.startswith('viewer-publications/attempts/') for key, *_ in remote.puts)
    events = [json.loads(line) for line in (root / local.LOCAL_STATE / 'events.jsonl').read_bytes().splitlines()]
    authority = events[0]['value']['binding']['custody']
    assert authority['local_receipt_sha256'] == hashlib.sha256((root / local.RECEIPT).read_bytes()).hexdigest()
    before = [write for write in remote.puts if not write[0].startswith('viewer-publications/attempts/')]
    with pytest.raises(ValueError, match='explicit --resume'):
        publish(ready)
    assert publish(ready, resume=True)['status'] == 'published'
    assert [write for write in remote.puts if not write[0].startswith('viewer-publications/attempts/')] == before


def test_local_resume_can_recover_failure_before_first_remote_journal(ready):
    remote, root, _ = ready
    remote.reject_journal = True
    with pytest.raises(RuntimeError, match='outcome is uncertain') as error:
        publish(ready, journal_mode='remote')
    assert isinstance(error.value.request_error, OSError)
    assert (root / local.RECEIPT).is_file()
    remote.reject_journal = False
    assert publish(ready, resume=True, journal_mode='remote')['status'] == 'published'


@pytest.mark.parametrize('change', ['same-size-output', 'extra-output', 'missing-output'])
def test_local_custody_cannot_bypass_full_prepared_inventory(ready, change):
    remote, root, _ = ready
    receipt = json.loads((root / 'preparation.json').read_bytes())
    path = next(root / name for name in receipt['files'] if name.endswith('.parquet'))
    if change == 'same-size-output':
        raw = bytearray(path.read_bytes()); raw[5] ^= 1; path.write_bytes(raw)
    elif change == 'extra-output':
        (root / 'publication' / 'unexpected').write_bytes(b'extra')
    else:
        path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        publish(ready)
    assert not remote.puts and not (root / local.RECEIPT).exists()


@pytest.mark.parametrize('change', ['receipt', 'move', 'adapter'])
def test_local_receipt_refuses_changed_custody_before_resume_write(ready, tmp_path, monkeypatch, change):
    remote, root, _ = ready
    assert publish(ready)['status'] == 'published'
    before = len(remote.puts)
    if change == 'receipt':
        p = root / local.RECEIPT
        value = json.loads(p.read_bytes()); value['run_id'] = 'another'
        p.write_text(json.dumps(value))
    elif change == 'move':
        moved = tmp_path / 'moved'; shutil.copytree(root, moved)
        ready = remote, moved, ready[2]
    else:
        script = tmp_path / 'changed-adapter.py'; script.write_bytes(b'changed')
        monkeypatch.setattr(local, '__file__', str(script))
    with pytest.raises(ValueError, match='custody changed'):
        publish(ready, resume=True)
    assert len(remote.puts) == before


def test_local_publish_rechecks_current_selectors(ready):
    remote, root, _ = ready
    remote.versions['indexes/catalog.json'] = 'changed'
    assert publish(ready)['status'] == 'superseded'
    assert not remote.puts


def test_local_resume_requires_receipt(ready):
    with pytest.raises(FileNotFoundError):
        publish(ready, resume=True)
    assert not ready[0].puts


def test_local_publish_excludes_a_second_owner(ready):
    remote, root, _ = ready
    with (root / '.local-publication.lock').open('ab') as held:
        local.fcntl.flock(held, local.fcntl.LOCK_EX | local.fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already being published'):
            publish(ready)
    assert not remote.puts and not (root / local.RECEIPT).exists()


@pytest.mark.parametrize('mode', ['local', 'remote'])
def test_journal_authority_cannot_switch_on_resume(ready, mode):
    assert publish(ready, journal_mode=mode)['status'] == 'published'
    before = len(ready[0].puts)
    other = 'remote' if mode == 'local' else 'local'
    with pytest.raises(ValueError, match='custody changed'):
        publish(ready, resume=True, journal_mode=other)
    assert len(ready[0].puts) == before


@pytest.mark.parametrize('competing', [False, True])
def test_local_restart_reconciles_committed_pointer_before_selectors_without_repeating_put(ready, monkeypatch, competing):
    remote, root, _ = ready
    pointer = local.publisher.PREFIX + 'manifest.json'
    original = local.LocalContinuation.record
    with monkeypatch.context() as patch:
        def interrupt(state, event, value):
            if event == 'publication_write_verified' and value['key'] == pointer:
                raise KeyboardInterrupt('after pointer commit before local acknowledgment')
            return original(state, event, value)
        patch.setattr(local.LocalContinuation, 'record', interrupt)
        with pytest.raises(KeyboardInterrupt):
            publish(ready)
    before = len(remote.puts)
    assert any(key == pointer for key, *_ in remote.puts)
    assert not any(key.startswith('viewer-publications/attempts/') for key, *_ in remote.puts)
    gets, get = [], remote.get_object
    def observe(**kwargs):
        gets.append(kwargs['Key'])
        return get(**kwargs)
    monkeypatch.setattr(remote, 'get_object', observe)
    if competing:
        remote.objects[pointer] = b'{}'
        remote.versions[pointer] = 'concurrent-pointer'
        with pytest.raises(ValueError, match='Uncertain publication conflicts'):
            publish(ready, resume=True)
    else:
        assert publish(ready, resume=True)['status'] == 'published'
        state, _ = read_local_journal(root / local.LOCAL_STATE / 'events.jsonl')
        assert state['versions'][pointer] == remote.versions[pointer]
    assert gets[0] == pointer  # Reconcile before the source selector guard reads.
    assert len(remote.puts) == before


def test_acknowledged_wrong_upload_bytes_remain_unverified_and_never_select_pointer(ready, monkeypatch):
    remote, root, _ = ready
    put = remote.put_object
    damaged = []
    def corrupt(**kwargs):
        if not damaged and hasattr(kwargs['Body'], 'name'):
            path = Path(kwargs['Body'].name)
            raw = bytearray(path.read_bytes()); raw[0] ^= 1; path.write_bytes(raw)
            damaged.append(kwargs['Key'])
        return put(**kwargs)
    monkeypatch.setattr(remote, 'put_object', corrupt)
    with pytest.raises(ValueError, match='upload bytes'):
        publish(ready)
    assert damaged
    assert not any(key == local.publisher.PREFIX + 'manifest.json' for key, *_ in remote.puts)
    events = [json.loads(line) for line in (root / local.LOCAL_STATE / 'events.jsonl').read_bytes().splitlines()]
    assert not any(event['event'] == 'publication_write_verified' and event['value']['key'] == damaged[0] for event in events)


@pytest.mark.parametrize('change', ['preparation', 'source-bytes', 'source-version'])
def test_local_route_refuses_changed_preparation_or_source_before_put(ready, change):
    remote, root, _ = ready
    if change == 'preparation':
        path = root / 'preparation.json'
        receipt = json.loads(path.read_bytes())
        receipt['binding']['code_runtime']['dependencies'] = 'changed'
        path.write_text(json.dumps(receipt))
        with pytest.raises(ValueError, match='identities changed'):
            publish(ready)
    else:
        key = 'indexes/catalog.json'
        if change == 'source-version':
            remote.versions[key] = 'changed'
        else:
            value = json.loads(remote.objects[key]); value['different-source'] = True
            remote.objects[key] = json.dumps(value).encode()
        assert publish(ready)['status'] == 'superseded'
    assert not remote.puts



def test_partial_local_journal_refuses_resume_without_remote_writes(ready):
    remote, root, _ = ready
    assert publish(ready)['status'] == 'published'
    before = len(remote.puts)
    with (root / local.LOCAL_STATE / 'events.jsonl').open('ab') as stream:
        stream.write(b'partial event')
    with pytest.raises(ValueError, match='Incomplete or oversized local publication journal'):
        publish(ready, resume=True)
    assert len(remote.puts) == before


def test_source_advance_during_upload_does_not_select_pointer(ready):
    remote, root, _ = ready
    changed = []
    def advance(key):
        if not changed and key.startswith('viewer-publications/releases/'):
            changed.append(key)
            remote.versions['indexes/catalog.json'] = 'source-advanced'
    remote.after_put = advance
    assert publish(ready)['status'] == 'superseded'
    assert changed
    assert not any(key == local.publisher.PREFIX + 'manifest.json' for key, *_ in remote.puts)



@pytest.mark.parametrize('boundary', ['receipt', 'journal-intent', 'state-parent'])
def test_local_fsync_failure_prevents_any_remote_put(ready, monkeypatch, boundary):
    remote, root, _ = ready
    fsync = local.os.fsync
    failed = []
    def refuse(descriptor):
        info = local.os.fstat(descriptor)
        receipt = root / local.RECEIPT
        journal = root / local.LOCAL_STATE / 'events.jsonl'
        receipt_sync = receipt.exists() and stat.S_ISREG(info.st_mode) and info.st_ino == receipt.stat().st_ino
        parent_sync = journal.exists() and stat.S_ISDIR(info.st_mode) and info.st_ino == root.stat().st_ino
        intent_sync = journal.exists() and stat.S_ISREG(info.st_mode) and info.st_ino == journal.stat().st_ino and json.loads(journal.read_bytes().splitlines()[-1])['event'] == 'publication_write_intent'
        if not failed and {'receipt': receipt_sync, 'journal-intent': intent_sync, 'state-parent': parent_sync}[boundary]:
            failed.append(boundary)
            raise OSError('injected local fsync failure')
        return fsync(descriptor)
    monkeypatch.setattr(local.os, 'fsync', refuse)
    with pytest.raises(OSError, match='injected local fsync failure'):
        publish(ready)
    assert failed == [boundary]
    assert not remote.puts


def test_local_state_parent_is_durable_before_first_remote_put(ready, monkeypatch):
    remote, root, _ = ready
    fsync, put = local.os.fsync, remote.put_object
    durable = []
    def observe(descriptor):
        result = fsync(descriptor)
        info = local.os.fstat(descriptor)
        if (root / local.LOCAL_STATE / 'events.jsonl').exists() and stat.S_ISDIR(info.st_mode) and info.st_ino == root.stat().st_ino:
            durable.append(True)
        return result
    def require_parent(**kwargs):
        assert durable, 'New local state directory must be durably linked before PUT'
        return put(**kwargs)
    monkeypatch.setattr(local.os, 'fsync', observe)
    monkeypatch.setattr(remote, 'put_object', require_parent)
    assert publish(ready)['status'] == 'published'
    assert remote.puts and durable



def test_pretransfer_is_bounded_exact_and_core_replays_without_duplicate_puts(ready, monkeypatch):
    import threading
    remote, root, _ = ready
    remote.meta.config.max_pool_connections = 8
    put = remote.put_object
    lock, rendezvous = threading.Lock(), threading.Barrier(8)
    active = peak = arrivals = 0
    observed, calls = [], {}
    upload = local.ContinuedPublicationClient.upload_verified_file
    def exact_headers(client, filename, bucket, key, ExtraArgs=None, **kwargs):
        calls.setdefault(key, []).append((bucket, dict(ExtraArgs or {})))
        return upload(client, filename, bucket, key, ExtraArgs=ExtraArgs, **kwargs)
    monkeypatch.setattr(local.ContinuedPublicationClient, 'upload_verified_file', exact_headers)
    accepted = local.attempt.verify_prepared(local.publisher, root).plan
    planned_keys = {local.publisher.PREFIX + name for name in accepted.files}
    def counted(**kwargs):
        nonlocal active, peak, arrivals
        is_asset = '/viewer-v2/' in kwargs['Key'] and hasattr(kwargs['Body'], 'name')
        if is_asset:
            with lock:
                active += 1; peak = max(peak, active); arrivals += 1
                first = arrivals <= 8
            try:
                if first: rendezvous.wait(timeout=10)
                observed.append({key: kwargs[key] for key in ('Key','IfNoneMatch','ContentType','CacheControl','Metadata')})
                return put(**kwargs)
            finally:
                with lock: active -= 1
        return put(**kwargs)
    monkeypatch.setattr(remote, 'put_object', counted)
    assert publish(ready, pretransfer_workers=8)['status'] == 'published'
    assert peak == 8 and active == 0
    keys = [key for key, *_ in remote.puts]
    assert len(keys) == len(set(keys)), 'Core must replay accepted uploads, not send another PUT'
    assert len(observed) >= 8
    assert set(keys[:len(planned_keys)]) == planned_keys, 'Pre-transfer must finish plan assets before core control writes'
    for key in planned_keys:
        assert len(calls[key]) == 2 and calls[key][0] == calls[key][1], 'Pre-transfer and core must use identical bucket/key/headers'
    for row in observed:
        assert row['IfNoneMatch'] == '*'
        assert row['CacheControl'] == 'public, max-age=31536000, immutable'
        assert row['Metadata']['sha256'] == hashlib.sha256(remote.objects[row['Key']]).hexdigest()
        assert row['ContentType'] == ('application/vnd.apache.parquet' if row['Key'].endswith('.parquet') else 'application/json' if row['Key'].endswith('.json') else 'application/octet-stream')
    before = len(remote.puts)
    assert publish(ready, resume=True, pretransfer_workers=8)['status'] == 'published'
    assert len(remote.puts) == before


def test_failed_pretransfer_drains_before_unlock_then_resumes_original_conditions(ready, monkeypatch):
    import threading
    import time
    remote, root, _ = ready
    remote.meta.config.max_pool_connections = 4
    put = remote.put_object
    lock, joined = threading.Lock(), threading.Barrier(4)
    active = arrivals = 0
    conditions = []
    with monkeypatch.context() as patch:
        def fail_one(**kwargs):
            nonlocal active, arrivals
            with lock:
                active += 1; arrivals += 1; ordinal = arrivals
            try:
                if ordinal <= 4: joined.wait(timeout=10)
                if ordinal == 1: raise KeyboardInterrupt('injected pre-transfer interruption')
                time.sleep(.03)
                with (root / '.local-publication.lock').open('ab') as other:
                    with pytest.raises(BlockingIOError):
                        local.fcntl.flock(other, local.fcntl.LOCK_EX | local.fcntl.LOCK_NB)
                conditions.append(kwargs['IfNoneMatch'])
                return put(**kwargs)
            finally:
                with lock: active -= 1
        patch.setattr(remote, 'put_object', fail_one)
        with pytest.raises(KeyboardInterrupt):
            publish(ready, pretransfer_workers=4)
    assert active == 0 and conditions and set(conditions) == {'*'}
    assert not any(key == local.publisher.PREFIX + 'manifest.json' for key, *_ in remote.puts)
    assert publish(ready, resume=True, pretransfer_workers=4)['status'] == 'published'
    keys = [key for key, *_ in remote.puts]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize('workers', [-1, 33, True])
def test_pretransfer_rejects_unbounded_worker_configuration(ready, workers):
    with pytest.raises(ValueError, match='between 0 and 32'):
        publish(ready, pretransfer_workers=workers)
    assert not ready[0].puts


def test_pretransfer_requires_sdk_pool_and_source_drift_blocks_selection(ready):
    remote, root, _ = ready
    with pytest.raises(ValueError, match='matching SDK connection pool'):
        publish(ready, pretransfer_workers=16)
    remote.meta.config.max_pool_connections = 16
    changed = []
    def advance(key):
        if not changed:
            changed.append(key)
            remote.versions['indexes/catalog.json'] = 'advanced during pre-transfer'
    remote.after_put = advance
    assert publish(ready, pretransfer_workers=16)['status'] == 'superseded'
    assert not any(key == local.publisher.PREFIX + 'manifest.json' for key, *_ in remote.puts)


def test_wrong_bytes_in_pretransfer_are_rejected_before_core_selection(ready, monkeypatch):
    remote, root, _ = ready
    remote.meta.config.max_pool_connections = 1
    put = remote.put_object
    def corrupt(**kwargs):
        path = Path(kwargs['Body'].name)
        raw = bytearray(path.read_bytes()); raw[0] ^= 1; path.write_bytes(raw)
        return put(**kwargs)
    monkeypatch.setattr(remote, 'put_object', corrupt)
    with pytest.raises(ValueError, match='upload bytes'):
        publish(ready, pretransfer_workers=1)
    assert not any(key == local.publisher.PREFIX + 'manifest.json' for key, *_ in remote.puts)
