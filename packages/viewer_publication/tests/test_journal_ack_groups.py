"""Bounded acknowledgments share journal appends; every intent stays pre-PUT durable."""
import hashlib
import json

import pytest

from viewer_publication import continuation as state
from viewer_publication.client import ContinuedPublicationClient
from test_publication_state_bounds import Remote, write_facts


@pytest.fixture
def group(tmp_path):
    run = state.Continuation(tmp_path / 'attempt', {})
    remote = Remote()
    log = state.DurableJournal(remote, 'bucket', run, 'ack-fixture', {})
    facts = [write_facts('viewer-publications/releases/fixture/' + str(n)) for n in range(6)]
    for intent, verified in facts:
        log.record('publication_write_intent', intent)
        remote.objects[intent['key']] = b'x'
    return log, run, remote, facts


def journal_rows(log, remote):
    return [json.loads(raw) for key, raw in sorted(remote.objects.items()) if key.startswith(log.prefix)]


def test_six_consecutive_acknowledgments_need_no_separate_put(group):
    log, run, remote, facts = group
    puts = remote.puts
    for _, verified in facts:
        log.record('publication_write_verified', verified)
        assert remote.puts == puts
    log.record('publication_completed', {})
    assert remote.puts == puts + 1
    final = journal_rows(log, remote)[-1]
    assert final['version'] == 2
    assert final['verified_writes'] == [verified for _, verified in facts]
    assert len(log.pending_verified) == 0


def test_loss_of_six_pending_facts_reconciles_without_duplicate_put(group, tmp_path):
    log, run, remote, facts = group
    for _, verified in facts:
        log.record('publication_write_verified', verified)
    fresh = state.Continuation(tmp_path / 'fresh', {})
    state.DurableJournal(remote, 'bucket', fresh, 'ack-fixture', {}, resume=True)
    assert sum(not row['verified'] for row in fresh.value['writes'].values()) == 6
    puts = remote.puts
    fresh.reconcile(remote, 'bucket')
    client = ContinuedPublicationClient(remote, continuation=fresh, guard=lambda: None,
        journal=lambda *args: pytest.fail('Replayed upload journaled again'), after_write=lambda *args: None)
    for intent, _ in facts:
        client.put_object(Bucket='bucket', Key=intent['key'], Body=b'x', IfNoneMatch='*')
    assert remote.puts == puts


@pytest.mark.parametrize('joined', [False, True])
def test_v1_prefix_accepts_v2_tail_and_retains_original_history(tmp_path, joined):
    run, remote = state.Continuation(tmp_path / 'attempt', {}), Remote()
    prefix = 'viewer-publications/attempts/legacy-fixture/'
    intent, verified = write_facts('viewer-publications/releases/legacy/file')
    previous = None
    old = {}
    for sequence, (event, value) in enumerate([
        ('attempt_started', {'binding': {}}), ('publication_write_intent', intent),
        ('publication_write_verified', verified)]):
        item = dict(version=1, sequence=sequence, previous=previous,
            nonce=f'{sequence:032x}', event=event, value=value)
        if joined and sequence == 2:
            item.update(event='progress', value={}, verified_write=verified)
        raw = json.dumps(item, sort_keys=True).encode()
        old[prefix + f'{sequence:08d}.json'] = raw
        previous = hashlib.sha256(raw).hexdigest()
    remote.objects.update(old)
    log = state.DurableJournal(remote, 'bucket', run, 'legacy-fixture', {}, resume=True)
    log.record('progress', {})
    assert journal_rows(log, remote)[-1]['version'] == 2
    assert all(remote.objects[key] == raw for key, raw in old.items())
    state.DurableJournal(remote, 'bucket', run, 'legacy-fixture', {}, resume=True)
    assert run.value['writes'][intent['key']]['verified'] is True


def test_seventh_acknowledgment_flushes_one_bounded_group(group):
    log, run, remote, facts = group
    seventh = write_facts('viewer-publications/releases/fixture/6')
    log.record('publication_write_intent', seventh[0])
    puts = remote.puts
    for _, verified in facts + [seventh]:
        log.record('publication_write_verified', verified)
        assert len(log.pending_verified) <= 6
    assert remote.puts == puts + 1
    assert journal_rows(log, remote)[-1]['verified_writes'] == [verified for _, verified in facts]
    assert log.pending_verified == [seventh[1]]
    log.record('publication_completed', {})
    state.DurableJournal(remote, 'bucket', run, 'ack-fixture', {}, resume=True)
    assert len(run.value['writes']) == 7 and all(row['verified'] for row in run.value['writes'].values())


def test_pending_count_and_encoded_bytes_flush_without_avoidable_overflow(group, monkeypatch):
    log, run, remote, facts = group
    monkeypatch.setattr(state, 'MAX_EVENT_BYTES', 800)
    for _, verified in facts:
        log.record('publication_write_verified', dict(verified, etag='e' * 140))
        assert len(log.pending_verified) <= 6
    log.record('progress', {'padding': 'x' * 400})
    assert all(len(raw) <= 800 for key, raw in remote.objects.items() if key.startswith(log.prefix))
    state.DurableJournal(remote, 'bucket', run, 'ack-fixture', {}, resume=True)
    assert all(row['verified'] for row in run.value['writes'].values())


def test_failed_combined_append_retains_all_pending_facts(group, monkeypatch):
    log, run, remote, facts = group
    for _, verified in facts:
        log.record('publication_write_verified', verified)
    before = log.sequence, log.previous, log.total_bytes, remote.puts
    def unavailable(**options):
        raise OSError('request unavailable')
    monkeypatch.setattr(remote, 'put_object', unavailable)
    with pytest.raises(RuntimeError, match='uncertain'):
        log.record('publication_completed', {})
    assert (log.sequence, log.previous, log.total_bytes, remote.puts) == before
    assert log.pending_verified == [verified for _, verified in facts]


@pytest.mark.parametrize('limit', ['count', 'bytes'])
def test_separate_ack_flush_and_event_are_both_admitted_before_put(group, monkeypatch, limit):
    log, run, remote, facts = group
    for _, verified in facts[:2]:
        log.record('publication_write_verified', verified)
    value = {'padding': 'x' * 400}
    group_size = len(log._encoded_event('publication_acknowledgments', {}, log.pending_verified))
    event_size = len(log._encoded_event('progress', value, offset=1))
    monkeypatch.setattr(state, 'MAX_EVENT_BYTES', max(group_size, event_size))
    assert len(log._encoded_event('progress', value, log.pending_verified)) > state.MAX_EVENT_BYTES
    if limit == 'count':
        monkeypatch.setattr(state, 'MAX_EVENTS', log.sequence + 1)
    else:
        monkeypatch.setattr(state, 'MAX_JOURNAL_BYTES', log.total_bytes + group_size + event_size - 1)
    before = log.sequence, log.previous, log.total_bytes, remote.puts, list(log.pending_verified)
    with pytest.raises(ValueError, match='limit'):
        log.record('progress', value)
    assert (log.sequence, log.previous, log.total_bytes, remote.puts, log.pending_verified) == before


@pytest.mark.parametrize('damage', ['unknown_version', 'not_list', 'too_many', 'duplicate', 'unknown_key', 'mixed_fields'])
def test_bad_acknowledgment_group_refuses_before_accepted_state_mutation(group, damage):
    log, run, remote, facts = group
    for _, verified in facts:
        log.record('publication_write_verified', verified)
    log.record('publication_completed', {})
    key = log.prefix + f'{log.sequence - 1:08d}.json'
    event = json.loads(remote.objects[key])
    if damage == 'unknown_version': event['version'] = 3
    elif damage == 'not_list': event['verified_writes'] = {}
    elif damage == 'too_many': event['verified_writes'] = [facts[0][1]] * 7
    elif damage == 'duplicate': event['verified_writes'] = [facts[0][1]] * 2
    elif damage == 'unknown_key': event['verified_writes'] = [dict(facts[0][1], key='unknown')]
    else: event['verified_write'] = facts[0][1]
    remote.objects[key] = json.dumps(event).encode()
    checkpoint, writes = run.path.read_bytes(), json.dumps(run.value['writes'], sort_keys=True)
    accepted = {path.name: path.read_bytes() for path in (run.root / 'journal').glob('*.json')}
    with pytest.raises(ValueError):
        state.DurableJournal(remote, 'bucket', run, 'ack-fixture', {}, resume=True)
    assert run.path.read_bytes() == checkpoint
    assert json.dumps(run.value['writes'], sort_keys=True) == writes
    assert accepted == {path.name: path.read_bytes() for path in (run.root / 'journal').glob('*.json')}
