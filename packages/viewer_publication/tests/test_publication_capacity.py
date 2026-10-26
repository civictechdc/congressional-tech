"""Bounded full-release metadata exercise; no production payloads or network.

The large test runs real client, journal, transition and restore paths. Only
per-event evidence saves and periodic cache writes are counted instead of doing
100K fsyncs; initial/final checkpoint serialization and restore stay real.
"""
import hashlib
import io
import json
import math
import resource
import time

import pytest
from botocore.exceptions import ClientError
from congress_shared.custody import canonical_json_bytes
from viewer_publication import continuation as state
from viewer_publication.client import ContinuedPublicationClient


class Remote:
    def __init__(self):
        self.objects = {}
        self.puts = self.gets = self.heads = 0

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        raw = self.objects[Key]
        self.gets += 1
        return dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag=hashlib.sha256(raw).hexdigest())

    def head_object(self, *, Bucket, Key):
        raw = self.objects[Key]
        self.heads += 1
        return dict(ContentLength=len(raw), ETag=hashlib.sha256(raw).hexdigest())

    def put_object(self, **options):
        key, raw = options['Key'], options['Body']
        assert options['IfNoneMatch'] == '*'
        if key in self.objects:
            raise AssertionError('Duplicate immutable PUT: ' + key)
        self.objects[key] = raw
        self.puts += 1
        return dict(ETag=hashlib.sha256(raw).hexdigest())

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        remote = self
        class Pages:
            def paginate(self, *, Bucket, Prefix):
                pending = []
                for key in remote.objects:
                    if key.startswith(Prefix):
                        pending.append(dict(Key=key))
                        if len(pending) == 1000:
                            yield dict(Contents=pending)
                            pending = []
                if pending:
                    yield dict(Contents=pending)
        return Pages()


def asset_name(number):
    digest = hashlib.sha256(str(number).encode()).hexdigest()
    return f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/page.json'


def write_fact(key):
    return dict(key=key, bytes=1, sha256=hashlib.sha256(b'x').hexdigest(),
                expected_etag=None, if_none_match='*')


def test_full_release_inventory_upload_interrupt_restore_and_replay(tmp_path, monkeypatch):
    count = 100_000
    started = time.monotonic()
    # Same accepted-input byte order as the retained 9,641,774-byte failed run.
    binding = dict(accepted={'retained_input': 'x' * 9_638_357})
    run = state.Continuation(tmp_path / 'attempt', binding)
    names = [asset_name(number) for number in range(count)]
    run.value['phases']['prepared'] = dict(result={'accepted': True}, files={
        'publication/' + name: hashlib.sha256(b'x').hexdigest() for name in names})
    state.validate_state(run.value)
    run.flush()
    accepted_bytes = run.path.stat().st_size
    # Real phase and binding are retained while the upload cache lags.
    remote = Remote()
    log_binding = {'preparation_sha256': 'a' * 64, 'artifact': {'id': 'fixture'}}
    log = state.DurableJournal(remote, 'bucket', run, 'capacity-fixture', log_binding)
    checkpoints, saves = [], [0, 0]
    def counted_flush():
        checkpoints.append(len(run.value['writes']))
    def counted_save(name, raw, **kwargs):
        saves[0] += 1
        saves[1] += len(raw)
    monkeypatch.setattr(run, 'flush', counted_flush)
    monkeypatch.setattr(run, 'save', counted_save)
    def proxy(log):
        return ContinuedPublicationClient(remote, continuation=run, guard=lambda: None,
            journal=log.record, after_write=lambda *args: None)
    client = proxy(log)
    split = count // 2
    for name in names[:split]:
        client.put_object(Bucket='bucket', Key='viewer-publications/' + name, Body=b'x', IfNoneMatch='*')
    # Abrupt loss: the last verification has not joined a remote event. Restore
    # from accepted preparation (no writes), never the current in-memory cache.
    fresh = state.Continuation(run.root, binding, resume=True)
    assert fresh.value['writes'] == {}
    monkeypatch.setattr(fresh, 'save', counted_save)
    fresh_flush = fresh.flush
    log = state.DurableJournal(remote, 'bucket', fresh, 'capacity-fixture', log_binding, resume=True)
    run = fresh
    assert len(run.value['writes']) == split
    assert sum(not item['verified'] for item in run.value['writes'].values()) == 1
    run.reconcile(remote, 'bucket', progress=lambda _: None)
    monkeypatch.setattr(fresh, 'flush', lambda: checkpoints.append(len(fresh.value['writes'])))
    before = remote.puts
    client = proxy(log)
    for name in names[:split]:
        client.put_object(Bucket='bucket', Key='viewer-publications/' + name, Body=b'x', IfNoneMatch='*')
    assert remote.puts == before  # All 50K exact immutable bodies reused.
    for name in names[split:]:
        client.put_object(Bucket='bucket', Key='viewer-publications/' + name, Body=b'x', IfNoneMatch='*')
    log.record('publication_completed', {'status': 'fixture'})
    state.validate_state(run.value)
    raw = canonical_json_bytes(run.value, ensure_ascii=True, trailing_newline=True)
    assert run._state_bytes == len(raw) < state.MAX_STATE_BYTES
    fresh_flush()  # Real bounded final serialization, atomic save and fsync.
    assert state.Continuation(run.root, binding, resume=True).value == run.value
    assert len(run.value['writes']) == count and all(x['verified'] for x in run.value['writes'].values())
    assert log.sequence == count + 2
    assert log.total_bytes < state.MAX_JOURNAL_BYTES
    assert len(checkpoints) <= math.ceil(count / state.JOURNAL_CHECKPOINT_EVENTS) + 5
    # Corruption remains a refusal at scale, before replacing the checkpoint.
    last = log.prefix + f'{log.sequence - 1:08d}.json'
    doc = json.loads(remote.objects[last]); doc['previous'] = '0' * 64
    remote.objects[last] = canonical_json_bytes(doc)
    before = run.path.read_bytes(), remote.puts
    with pytest.raises(ValueError, match='chain'):
        state.DurableJournal(remote, 'bucket', run, 'capacity-fixture', log_binding, resume=True)
    assert (run.path.read_bytes(), remote.puts) == before
    print(json.dumps(dict(files=count, accepted_state_bytes=accepted_bytes, final_state_bytes=len(raw),
        journal_events=log.sequence, journal_bytes=log.total_bytes, checkpoint_calls=len(checkpoints),
        counted_evidence_saves=saves[0], counted_evidence_bytes=saves[1], remote_puts=remote.puts,
        replayed_payloads=split, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, seconds=round(time.monotonic()-started, 3)), sort_keys=True))


def test_limits_cover_capacity_shape_and_refuse_next_count(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {})
    run.value['phases']['prepared'] = dict(result={}, files={
        'publication/' + asset_name(n): 'a' * 64 for n in range(state.MAX_PHASE_FILES)})
    fact = write_fact('viewer-publications/' + asset_name(0))
    for n in range(state.MAX_WRITES):
        key = 'viewer-publications/' + asset_name(n)
        run.value['writes'][key] = dict(fact, key=key, verified=True, etag='"' + 'a' * 32 + '"')
    run.value['binding'] = {'accepted': 'x' * 9_638_357}
    state.validate_state(run.value)
    raw = canonical_json_bytes(run.value, ensure_ascii=True, trailing_newline=True)
    assert len(raw) < state.MAX_STATE_BYTES
    with pytest.raises(ValueError, match='write limit'):
        state.apply_event(run.value, 'publication_write_intent', write_fact('viewer-publications/new'))
    run.value['phases']['prepared']['files']['extra'] = 'a' * 64
    with pytest.raises(ValueError, match='phase file limit'):
        state.validate_state(run.value)
    del run.value['phases']['prepared']['files']['extra']
    run.value['writes']['extra'] = dict(fact, key='extra', verified=False)
    with pytest.raises(ValueError, match='state count limit'):
        state.validate_state(run.value)
    print(json.dumps(dict(capacity_files=state.MAX_PHASE_FILES, capacity_writes=state.MAX_WRITES,
                          capacity_shape_state_bytes=len(raw)), sort_keys=True))


def test_state_byte_admission_precedes_remote_append_and_payload(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {})
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'small', {})
    client = ContinuedPublicationClient(remote, continuation=run, guard=lambda: None,
        journal=log.record, after_write=lambda *args: None)
    before = run.path.read_bytes(), remote.puts, log.sequence
    monkeypatch.setattr(state, 'MAX_STATE_BYTES', run._state_bytes + 1)
    with pytest.raises(ValueError, match='state byte limit'):
        client.put_object(Bucket='bucket', Key='viewer-publications/releases/x/page', Body=b'x', IfNoneMatch='*')
    assert (run.path.read_bytes(), remote.puts, log.sequence) == before
    assert run.value['writes'] == {}
    with pytest.raises(ValueError, match='state byte limit'):
        run.phase('oversize', lambda: {'result': 'x' * 100}, files=lambda: [])
    assert run.value['phases'] == {} and run.path.read_bytes() == before[0]


def test_incremental_json_size_and_checkpoint_cadence(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {'unicode': '雪'})
    run.value['versions']['viewer-publications/雪'] = None
    run.flush()
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'deltas', {})
    monkeypatch.setattr(state, 'JOURNAL_CHECKPOINT_EVENTS', 4)
    original = run.flush
    checkpoints = []
    monkeypatch.setattr(run, 'flush', lambda: checkpoints.append(True) or original())
    for n in range(10):
        key = 'viewer-publications/雪' + (str(n) if n else '')
        fact = write_fact(key)
        log.record('publication_write_intent', fact)
        assert run._state_bytes == len(canonical_json_bytes(run.value, ensure_ascii=True)) + 1
        if n % 2:
            log.record('publication_write_refused', dict(key=key))
        else:
            log.record('publication_write_verified', dict(key=key, bytes=1, sha256=fact['sha256'], etag='"雪"'))
        assert run._state_bytes == len(canonical_json_bytes(run.value, ensure_ascii=True)) + 1
    log.record('publication_completed', {})
    assert 2 < len(checkpoints) < 10
    assert state.Continuation(run.root, {'unicode': '雪'}, resume=True).value == run.value


def test_paged_inventory_and_state_validator_accept_complete_metadata(tmp_path):
    from viewer_publication.filename_native import ViewerAssets, write_inventory, iterator_inventory
    count = 100_000
    assets = ViewerAssets(tmp_path / 'publication')
    # Inventory references are synthetic. Inventory pages are real hash-checked
    # ViewerAssets files; payload custody is exercised in the small fixture suite.
    assets.identities.update({asset_name(n): dict(bytes=1, sha256=hashlib.sha256(str(n).encode()).hexdigest())
                              for n in range(count)})
    inventory = write_inventory(assets)
    references = list(iterator_inventory(assets, inventory))
    assert len(references) == count + math.ceil(count / 64)
    assert len({item['path'] for item in references}) == len(references)
    run = state.Continuation(tmp_path / 'attempt', {})
    run.value['phases']['prepared'] = dict(result={}, files={
        'publication/' + item['path']: item['sha256'] for item in references})
    state.validate_state(run.value)
    print(json.dumps(dict(inventory_assets=count, inventory_pages=math.ceil(count / 64),
        inventory_references=len(references), inventory_page_bytes=assets.written_bytes), sort_keys=True))


def test_event_and_journal_bounds_refuse_next_append_before_payload(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {})
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'bounded', {})
    client = ContinuedPublicationClient(remote, continuation=run, guard=lambda: None,
        journal=log.record, after_write=lambda *args: None)
    monkeypatch.setattr(state, 'MAX_EVENTS', log.sequence)
    before = remote.puts, run.value.copy(), log.sequence
    with pytest.raises(ValueError, match='event count'):
        client.put_object(Bucket='bucket', Key='viewer-publications/releases/x/page', Body=b'x', IfNoneMatch='*')
    assert (remote.puts, run.value, log.sequence) == before
    monkeypatch.setattr(state, 'MAX_EVENTS', log.sequence + 10)
    monkeypatch.setattr(state, 'MAX_JOURNAL_BYTES', log.total_bytes)
    with pytest.raises(ValueError, match='total byte'):
        client.put_object(Bucket='bucket', Key='viewer-publications/releases/x/page', Body=b'x', IfNoneMatch='*')
    assert (remote.puts, run.value, log.sequence) == before


def test_noncoalesced_journal_accepts_write_capacity(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {})
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'uncoalesced', {})
    # Exercise worst-case completion ordering without a network, per-event
    # local files or serializing the full cache every 1024 events.
    monkeypatch.setattr(run, 'save', lambda *args, **kwargs: None)
    monkeypatch.setattr(run, 'flush', lambda: None)
    for n in range(state.MAX_WRITES):
        log.record('publication_write_intent', write_fact('viewer-publications/' + asset_name(n)))
    for n in range(state.MAX_WRITES):
        fact = write_fact('viewer-publications/' + asset_name(n))
        log.record('publication_write_verified', dict(key=fact['key'], bytes=1, sha256=fact['sha256'], etag='"' + 'a' * 32 + '"'))
    log.record('publication_completed', {})
    assert log.sequence == 2 * state.MAX_WRITES + 1 < state.MAX_EVENTS
    assert log.total_bytes < state.MAX_JOURNAL_BYTES
    state.validate_state(run.value)
    assert run._state_bytes == len(canonical_json_bytes(run.value, ensure_ascii=True)) + 1
    print(json.dumps(dict(noncoalesced_writes=state.MAX_WRITES, noncoalesced_events=log.sequence,
        noncoalesced_journal_bytes=log.total_bytes, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), sort_keys=True))


def test_restored_unicode_state_still_obeys_serialized_byte_limit(tmp_path, monkeypatch):
    run = state.Continuation(tmp_path / 'attempt', {})
    run.value['binding'] = {'unicode': '雪' * 50}
    raw = json.dumps(run.value, ensure_ascii=False, separators=(',', ':')).encode()
    run.path.write_bytes(raw)
    monkeypatch.setattr(state, 'MAX_STATE_BYTES', len(raw))
    with pytest.raises(ValueError, match='state byte limit'):
        state.Continuation(run.root, run.value['binding'], resume=True)
    assert run.path.read_bytes() == raw
