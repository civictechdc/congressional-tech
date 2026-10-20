"""Accepted preparation survives transfer failures and remote uncertainty."""
from datetime import datetime, timezone
from collections import Counter
import hashlib
import importlib.util
import io
import os
import time
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/site/scripts'), str(ROOT / 'tests')]
_NATIVE_FIXTURES = {}
import viewer_publication.attempt as attempts
from viewer_publication.continuation import Continuation, DurableJournal

spec = importlib.util.spec_from_file_location('attempt_publisher', ROOT / 'apps/site/scripts/publish-viewer-r2.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


class Remote:
    def __init__(self, source):
        self.objects = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob('*')
                        if path.is_file() and not path.is_relative_to(source / 'public')}
        self.versions = {key: 'v0-' + hashlib.sha256(raw).hexdigest() for key, raw in self.objects.items()}
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts':1}),
                                    events=SimpleNamespace(register_first=lambda *args, **kwargs: None))
        self.gets = Counter(); self.heads = Counter()
        self.puts = []; self.after_put = None; self.reject_journal = False
    def get_object(self, *, Bucket, Key):
        self.gets[Key] += 1
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        raw = self.objects[Key]
        return {'Body': io.BytesIO(raw), 'ContentLength': len(raw), 'ETag': self.versions[Key],
                'LastModified': datetime(2026, 10, 18, tzinfo=timezone.utc)}
    def head_object(self, **kwargs):
        self.heads[kwargs['Key']] += 1
        value = self.get_object(**kwargs); value['Body'].close(); return value
    def put_object(self, **kwargs):
        key = kwargs['Key']
        if self.reject_journal and key.startswith('viewer-publications/attempts/'):
            raise OSError('journal unavailable')
        if ((kwargs.get('IfNoneMatch') == '*' and key in self.objects)
                or (kwargs.get('IfMatch') and kwargs['IfMatch'] != self.versions.get(key))):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        body = kwargs['Body']; raw = body if isinstance(body, bytes) else body.read()
        self.puts.append((key, kwargs.get('IfMatch'), kwargs.get('IfNoneMatch')))
        self.objects[key] = raw; self.versions[key] = 'v' + str(len(self.puts))
        if self.after_put:
            self.after_put(key)
        return {'ETag': self.versions[key]}
    def download_file(self, bucket, key, destination):
        Path(destination).write_bytes(self.objects[key])
    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return SimpleNamespace(paginate=lambda **kw: [{'Contents': [{'Key': key} for key in self.objects if key.startswith(kw['Prefix'])]}])


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp('attempt-source')
    from congress_api.retention.catalog_cache import LocalStore
    from test_catalog_coalesced_batches import Native
    from test_native_catalog_selection import seed
    native = Native()
    seed(root, LocalStore(root), native)
    _NATIVE_FIXTURES[str(root)] = native
    return root


@pytest.fixture(autouse=True)
def configured_native_fixture(source, monkeypatch):
    from congress_api.retention.docspec import NativeDatasets
    monkeypatch.setenv('DOCSPEC_CONFIG', 'explicit-test-native-runtime.json')
    monkeypatch.setattr(NativeDatasets, 'from_config', classmethod(lambda cls, path: _NATIVE_FIXTURES[str(source)]))


@pytest.fixture
def ready(source, tmp_path, monkeypatch):
    remote = Remote(source)
    root = tmp_path / 'prepared'
    started = time.perf_counter()
    result = attempts.prepare(publisher, remote, root, run_id='123', run_attempt='1', public_url=publisher.PUBLIC_URL)
    remote.preparation_seconds = time.perf_counter() - started
    class Public(io.BytesIO):
        headers = {'Access-Control-Allow-Origin': '*'}
    monkeypatch.setattr(publisher, 'open_public', lambda request, **kwargs: Public(
        remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)]))
    assert not remote.puts
    return remote, root, result


def custody(artifact, prepared):
    if not artifact.get('id'):
        raise ValueError('Accepted preparation artifact is required')
    return {'id': artifact['id'], 'digest': 'test-artifact-digest', 'name': prepared['artifact_name'],
            'run_id': '123', 'repository': 'fixture/repo'}


def publish(ready, **kwargs):
    remote, root, _ = ready
    return attempts.publish(publisher, remote, root, artifact={'id': '456'}, public_url=publisher.PUBLIC_URL,
                            verify_artifact=custody, probe=lambda *args: None, **kwargs)


def test_preparation_hashes_every_partition_and_rejects_same_size_corruption(ready):
    _, root, _ = ready
    receipt, manifest, _ = attempts.verify_prepared(publisher, root)
    shards = [relative for relative in receipt['files'] if relative.endswith('.parquet')]
    assert shards and not any('/ids/' in relative for relative in receipt['files'])
    path = next(root / relative for relative in shards if (root / relative).stat().st_size)
    raw = bytearray(path.read_bytes()); raw[5] ^= 1; path.write_bytes(raw)
    with pytest.raises(ValueError, match='file changed'):
        attempts.verify_prepared(publisher, root)


def test_no_artifact_means_no_public_or_journal_write(ready):
    remote, root, _ = ready
    with pytest.raises(ValueError, match='artifact is required'):
        attempts.publish(publisher, remote, root, artifact={}, public_url=publisher.PUBLIC_URL, verify_artifact=custody)
    assert not remote.puts


def test_success_journals_before_and_after_every_public_write(ready):
    remote, _, result = ready
    assert publish(ready)['status'] == 'published'
    records = [json.loads(raw) for key, raw in sorted(remote.objects.items()) if key.startswith('viewer-publications/attempts/')]
    events = []
    for record in records:
        if 'verified_write' in record:
            events.append(dict(event='publication_write_verified', value=record['verified_write']))
        events.append(record)
    for key, _, _ in remote.puts:
        if key.startswith('viewer-publications/attempts/'):
            continue
        intent = next(i for i, event in enumerate(events) if event['event'] == 'publication_write_intent' and event['value']['key'] == key)
        verified = next(i for i, event in enumerate(events) if event['event'] == 'publication_write_verified' and event['value']['key'] == key)
        assert intent < verified
    with pytest.raises(ValueError, match='explicit resume required'):
        publish(ready)


def test_probe_failure_resumes_original_release_without_builder(ready, monkeypatch, tmp_path):
    remote, root, prepared = ready
    started = time.perf_counter()
    saved = tmp_path / 'artifact'; shutil.copytree(root, saved)
    artifact_transfer_seconds = time.perf_counter() - started
    def fail(*args): raise OSError('probe unavailable')
    with pytest.raises(OSError, match='probe unavailable'):
        attempts.publish(publisher, remote, root, artifact={'id': '456'}, public_url=publisher.PUBLIC_URL,
                         verify_artifact=custody, probe=fail)
    payload_writes = [key for key, _, _ in remote.puts if '/releases/' in key]
    # Recreate a fresh runner solely from the pre-publication artifact.
    started = time.perf_counter()
    shutil.rmtree(root); shutil.copytree(saved, root)
    artifact_restore_seconds = time.perf_counter() - started
    monkeypatch.setattr(attempts, 'prepare', lambda *a, **k: pytest.fail('Builder called during resume'))
    started = time.perf_counter()
    result = publish(ready, resume=True, attempt=prepared['attempt'])
    retry_seconds = time.perf_counter() - started
    if destination := os.environ.get('VIEWER_RETRY_RECEIPT'):
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'scope': 'fixture with in-memory remote; artifact copy uses local filesystem',
            'preparation_seconds': remote.preparation_seconds, 'artifact_transfer_seconds': artifact_transfer_seconds,
            'artifact_restore_seconds': artifact_restore_seconds, 'retry_including_journal_seconds': retry_seconds,
            'retry_total_seconds': artifact_restore_seconds + retry_seconds,
            'journal_bytes': sum(len(raw) for key, raw in remote.objects.items() if key.startswith('viewer-publications/attempts/')),
            'builder_calls_on_resume': 0, 'repeated_release_payload_writes': 0}, indent=2) + '\n')
    assert result['status'] == 'published' and result['preparation_reused']
    assert [key for key, _, _ in remote.puts if '/releases/' in key] == payload_writes


def test_runner_loss_after_commit_is_reconciled_from_remote_intent(ready, tmp_path):
    remote, root, prepared = ready
    saved = tmp_path / 'artifact'; shutil.copytree(root, saved)
    killed = []
    def die(key):
        if '/releases/' in key and not killed:
            killed.append(key); raise KeyboardInterrupt('runner died after commit')
    remote.after_put = die
    with pytest.raises(KeyboardInterrupt, match='runner died'):
        publish(ready)
    remote.after_put = None
    shutil.rmtree(root); shutil.copytree(saved, root)
    assert publish(ready, resume=True, attempt=prepared['attempt'])['status'] == 'published'
    assert sum(key == killed[0] for key, _, _ in remote.puts) == 1


def test_lost_acknowledgment_does_not_repeat_conditional_mutation(ready):
    remote, _, _ = ready
    def lose(key):
        if '/releases/' in key: raise TimeoutError('lost acknowledgment')
    remote.after_put = lose
    assert publish(ready)['status'] == 'published'
    keys = [key for key, _, _ in remote.puts]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize('key', ['indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX + 'manifest.json'])
def test_stale_protected_inputs_cannot_select_preparation(ready, key):
    remote, _, _ = ready
    remote.objects[key] = b'{}'; remote.versions[key] = 'changed'
    assert publish(ready)['status'] == 'superseded'
    assert remote.puts == []


def test_journal_outage_prevents_public_mutation(ready):
    remote, _, _ = ready; remote.reject_journal = True
    with pytest.raises(Exception):
        publish(ready)
    assert remote.puts == []


@pytest.mark.parametrize('identity', ['revision', 'dependencies', 'review_identities'])
def test_changed_runtime_or_review_input_refuses_reuse(ready, monkeypatch, identity):
    remote, _, _ = ready
    previous = attempts.content_identity(publisher)
    monkeypatch.setattr(attempts, 'content_identity', lambda _: dict(previous, **{identity: 'changed'}))
    with pytest.raises(ValueError, match='runtime, code or review'):
        publish(ready)
    assert remote.puts == []


def test_explicit_resume_requires_original_attempt(ready):
    with pytest.raises(ValueError, match='requires the original attempt'):
        publish(ready, resume=True)


def test_attempt_journal_detects_missing_middle_event(ready):
    remote, root, prepared = ready
    publish(ready)
    del remote.objects['viewer-publications/attempts/' + prepared['attempt'] + '/00000001.json']
    with pytest.raises(ValueError, match='gap'):
        publish(ready, resume=True, attempt=prepared['attempt'])


def test_recovery_only_preparation_and_runner_loss_never_rebuild_catalog(ready, tmp_path, monkeypatch):
    remote, _, _ = ready
    publish(ready)
    accepted = {'version': 1, 'recoveries': [{'original_url': 'https://committee.test/file.pdf',
        'recovered_url': 'http://committee.test/file.pdf', 'body_key': 'bodies/sha256/aa/' + 'a' * 64 + '.gz',
        'kind': 'pdf', 'recovery_status': 'recovered', 'recovery_basis': 'user_accepted_url_variant'}]}
    remote.objects[publisher.ACCEPTED_KEY] = publisher.encoded(accepted)
    remote.versions[publisher.ACCEPTED_KEY] = 'mapping-v2'
    root = tmp_path / 'recovery-prepared'
    prepared = attempts.prepare(publisher, remote, root, run_id='123', run_attempt='2', public_url=publisher.PUBLIC_URL)
    assert prepared['mode'] == 'recovery'
    files = json.loads((root / 'preparation.json').read_text())['files']
    assert len(files) == 4 and {'publication/manifest.json', 'publication/recovery-prepared.json'} <= files.keys()
    assert not any(path.endswith('.parquet') for path in files)
    monkeypatch.setattr(publisher, 'index_recoveries', lambda *a, **kw: pytest.fail('Second recovery scan during publish/resume'))
    saved = tmp_path / 'artifact-recovery'; shutil.copytree(root, saved)
    def die(key):
        if key == publisher.PREFIX + 'manifest.json':
            raise KeyboardInterrupt('selected then died')
    remote.after_put = die
    with pytest.raises(KeyboardInterrupt, match='selected then died'):
        publish((remote, root, prepared))
    remote.after_put = None
    shutil.rmtree(root); shutil.copytree(saved, root)
    assert publish((remote, root, prepared), resume=True, attempt=prepared['attempt'])['status'] == 'recovery_updated'


def test_two_runners_cannot_append_the_same_journal_sequence(ready):
    remote, root, _ = ready
    receipt, _, _ = attempts.verify_prepared(publisher, root)
    continuation = Continuation(root, receipt['binding'], resume=True)
    first = DurableJournal(remote, publisher.BUCKET, continuation, 'competing-attempt', {'same': 'binding'})
    second = DurableJournal(remote, publisher.BUCKET, continuation, 'competing-attempt', {'same': 'binding'}, resume=True)
    first.record('first', {})
    with pytest.raises(ClientError):
        second.record('second', {})
    assert json.loads(remote.objects[first.prefix + '00000001.json'])['event'] == 'first'


def test_github_artifact_identity_and_digest_are_verified(monkeypatch):
    value = {'id': 456, 'name': 'prepared-name', 'digest': 'sha256:exact', 'expired': False, 'workflow_run': {'id': 123}}
    monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: json.dumps(value))
    artifact = {'id': '456', 'digest': 'exact', 'repository': 'fixture/repo', 'run_id': '123'}
    assert attempts.verify_github_artifact(artifact, {'artifact_name': 'prepared-name'})['id'] == '456'
    value['digest'] = 'different'
    with pytest.raises(ValueError, match='digest differs'):
        attempts.verify_github_artifact(artifact, {'artifact_name': 'prepared-name'})



def test_ambiguous_journal_ack_cannot_claim_another_runners_identical_event(ready, tmp_path):
    remote, root, _ = ready
    receipt, _, _ = attempts.verify_prepared(publisher, root)
    first_state = Continuation(root, receipt['binding'], resume=True)
    first = DurableJournal(remote, publisher.BUCKET, first_state, 'ambiguous-attempt', {'same': 'binding'})
    second_state = Continuation(tmp_path / 'other-runner', receipt['binding'])
    second = DurableJournal(remote, publisher.BUCKET, second_state, 'ambiguous-attempt', {'same': 'binding'}, resume=True)
    first.record('publication_write_intent', {'key': 'viewer-publications/releases/x/file', 'bytes': 1, 'sha256': 'a' * 64, 'if_none_match': '*'})
    def unknown(**kwargs):
        raise TimeoutError('request outcome unknown')
    remote.put_object = unknown
    with pytest.raises(RuntimeError, match='outcome is uncertain') as caught:
        second.record('publication_write_intent', {'key': 'viewer-publications/releases/x/file', 'bytes': 1, 'sha256': 'a' * 64, 'if_none_match': '*'})
    assert isinstance(caught.value.reconciliation_error, ValueError)
    assert 'readback differs' in str(caught.value.reconciliation_error)
    assert second.sequence == 1
    pending = list((second_state.root / 'journal-intents').glob('00000001-*.json'))
    assert len(pending) == 1
    assert json.loads(pending[0].read_text())['nonce'] != json.loads(remote.objects[first.prefix + '00000001.json'])['nonce']



def test_explicit_resume_can_start_after_initial_journal_outage(ready):
    remote, root, prepared = ready
    remote.reject_journal = True
    with pytest.raises(Exception):
        publish(ready)
    assert remote.puts == []
    remote.reject_journal = False
    assert publish(ready, resume=True, attempt=prepared['attempt'])['status'] == 'published'


def test_fresh_runner_restores_complete_local_journal(ready, tmp_path):
    remote, root, prepared = ready
    saved = tmp_path / 'artifact'; shutil.copytree(root, saved)
    publish(ready)
    shutil.rmtree(root); shutil.copytree(saved, root)
    assert publish(ready, resume=True, attempt=prepared['attempt'])['status'] == 'published'
    prefix = 'viewer-publications/attempts/' + prepared['attempt'] + '/'
    for key, raw in remote.objects.items():
        if key.startswith(prefix):
            assert (root / 'journal' / key.removeprefix(prefix)).read_bytes() == raw



def test_successful_attempt_request_cost_is_recorded_without_per_file_mutable_polls(ready):
    remote, root, _ = ready
    remote.gets.clear(); remote.heads.clear()
    assert publish(ready)['status'] == 'published'
    protected = ['indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX + 'manifest.json']
    assert all(remote.gets[key] < 10 for key in protected)
    journal_prefix = 'viewer-publications/attempts/'
    journal_puts = [key for key, _, _ in remote.puts if key.startswith(journal_prefix)]
    public_puts = [key for key, _, _ in remote.puts if not key.startswith(journal_prefix)]
    assert len(public_puts) + 2 <= len(journal_puts) < 2 * len(public_puts) + 2
    if destination := os.environ.get('VIEWER_SUCCESS_RECEIPT'):
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'scope': 'fixture with in-memory remote; counts exclude GitHub artifact metadata API and public probes',
            'publication_puts': len(public_puts), 'journal_puts': len(journal_puts),
            'journal_get_calls': sum(count for key, count in remote.gets.items() if key.startswith(journal_prefix)),
            'journal_full_readbacks': len(journal_puts),
            'mutable_identity_gets': {key: remote.gets[key] for key in protected},
            'file_version_heads': sum(remote.heads.values()),
            'journal_bytes': sum(len(raw) for key, raw in remote.objects.items() if key.startswith(journal_prefix))}, indent=2) + '\n')


def test_inputs_advancing_during_immutable_transfer_never_select_pointer(ready):
    remote, _, _ = ready
    changed = []
    def advance(key):
        if '/releases/' in key and not changed:
            changed.append(True)
            remote.versions[publisher.ACCEPTED_KEY] = 'new-mapping'
            remote.objects[publisher.ACCEPTED_KEY] = publisher.encoded({'version': 1, 'recoveries': []})
    remote.after_put = advance
    assert publish(ready)['status'] == 'superseded'
    assert publisher.PREFIX + 'manifest.json' not in remote.objects


def test_full_release_identity_tracks_dirty_transitive_sources_and_ignores_docs(tmp_path):
    helper = tmp_path / 'packages/congress_api/src/congress_api/retention/helper.py'
    helper.parent.mkdir(parents=True); helper.write_text('VALUE = 1\n')
    before = publisher.release_source_files(tmp_path)
    (tmp_path / 'README.md').write_text('Unrelated documentation\n')
    assert publisher.release_source_files(tmp_path) == before
    helper.write_text('VALUE = 2\n')
    assert publisher.release_source_files(tmp_path) != before
    review = tmp_path / 'apps/site/document-review-identities.json'
    review.parent.mkdir(parents=True); review.write_text('{}')
    assert str(review.relative_to(tmp_path)) in publisher.release_source_files(tmp_path)
    before = publisher.release_source_files(tmp_path)
    descriptor = review.with_name('document-review-publication.json')
    descriptor.write_text('{"sha256": "old"}')
    after = publisher.release_source_files(tmp_path)
    assert after != before
    descriptor.write_text('{"sha256": "new"}')
    assert publisher.release_source_files(tmp_path) != after


@pytest.mark.parametrize('name', ['plan.py', 'reconciliation.py'])
def test_release_identity_includes_accepted_plan_and_reconciliation_source(tmp_path, name):
    helper = tmp_path / 'packages/viewer_publication/src/viewer_publication' / name
    helper.parent.mkdir(parents=True); helper.write_text('VALUE = 1\n')
    before = publisher.release_source_files(tmp_path)
    assert str(helper.relative_to(tmp_path)) in before
    helper.write_text('VALUE = 2\n')
    assert publisher.release_source_files(tmp_path) != before


@pytest.mark.parametrize('field', ['implementation', 'dependencies', 'publisher_version'])
def test_changed_full_release_inputs_require_full_preparation(ready, tmp_path, monkeypatch, field):
    remote, _, _ = ready
    assert publish(ready)['status'] == 'published'
    identity = publisher.full_release_identity()
    monkeypatch.setattr(publisher, 'full_release_identity', lambda: dict(identity, **{field: 'changed'}))
    result = attempts.prepare(publisher, remote, tmp_path / 'new', run_id='124', run_attempt='1', public_url=publisher.PUBLIC_URL)
    assert result['mode'] == 'full'


def test_absent_empty_and_same_count_mapping_identities_remain_distinct():
    manifest = {'files': {'filenames': {'sha256': 'f'}, 'groups': {'sha256': 'g'}}}
    absent = publisher.recovery_inputs('source', 'manifest', manifest, None)
    empty = publisher.recovery_inputs('source', 'manifest', manifest, {'version': 1, 'recoveries': []})
    assert absent['accepted'] != empty['accepted']


def test_runtime_change_refuses_original_artifact_before_any_write(ready, monkeypatch):
    remote, root, _ = ready
    current = publisher.full_release_identity()
    monkeypatch.setattr(publisher, 'full_release_identity', lambda: dict(current, dependencies='other-runtime'))
    with pytest.raises(ValueError, match='runtime, code or review'):
        publish(ready)
    assert not remote.puts


def test_bounded_fixture_complete_publication_cost_receipt(source, tmp_path, monkeypatch):
    measure = str(ROOT / 'scripts/measure')
    if measure not in sys.path:
        sys.path.insert(0, measure)
    spec = importlib.util.spec_from_file_location('publication_costs', ROOT / 'scripts/measure/publication_costs.py')
    publication_costs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publication_costs)
    PublicationCosts = publication_costs.PublicationCosts
    remote = Remote(source)
    metrics = PublicationCosts(tmp_path)
    original_get, original_put, original_download = remote.get_object, remote.put_object, remote.download_file
    def get(**kwargs):
        metrics.counts['get_requests'] += 1
        response = original_get(**kwargs)
        metrics.counts['remote_body_bytes_read'] += response['ContentLength']
        return response
    def put(**kwargs):
        metrics.counts['put_requests'] += 1
        body = kwargs['Body']
        metrics.counts['put_body_bytes'] += len(body) if isinstance(body, bytes) else kwargs['ContentLength']
        return original_put(**kwargs)
    def download(bucket, key, destination):
        metrics.counts['download_requests'] += 1
        metrics.counts['download_bytes'] += len(remote.objects[key])
        return original_download(bucket, key, destination)
    remote.get_object, remote.put_object, remote.download_file = get, put, download
    class Public(io.BytesIO):
        headers = {'Access-Control-Allow-Origin': '*'}
    monkeypatch.setattr(publisher, 'open_public', lambda request, **kwargs: Public(
        remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)]))
    root = tmp_path / 'attempt'
    outcomes = {}
    with metrics.instrument():
        with metrics.stage('accepted_preparation'):
            prepared = attempts.prepare(publisher, remote, root, run_id='123', run_attempt='1', public_url=publisher.PUBLIC_URL)
        with metrics.stage('successful_publication'):
            outcomes['successful_publication'] = publish((remote, root, prepared))
        with metrics.stage('unchanged_poll'):
            outcomes['unchanged_poll'] = attempts.prepare(publisher, remote, tmp_path / 'noop', run_id='124', run_attempt='1', public_url=publisher.PUBLIC_URL)
        with metrics.stage('explicit_resume'):
            outcomes['explicit_resume'] = publish((remote, root, prepared), resume=True, attempt=prepared['attempt'])
    assert outcomes['successful_publication']['status'] == 'published'
    assert outcomes['unchanged_poll']['status'] == 'unchanged'
    assert outcomes['explicit_resume']['status'] == 'published'
    noop = next(stage for stage in metrics.stages if stage['stage'] == 'unchanged_poll')
    assert noop['counts'].get('put_requests', 0) == 0
    assert noop['counts'].get('download_requests', 0) == 0
    assert noop['counts'].get('decode_iterator_passes', 0) == 0
    if destination := os.environ.get('PUBLICATION_COST_RECEIPT'):
        metrics.save(destination, inputs={'source_manifest_sha256': publisher.digest(source / 'indexes/catalog.json'),
            'source_files': {str(p.relative_to(source)): publisher.digest(p) for p in source.rglob('*.parquet')},
            'runtime': publisher.full_release_identity(), 'python': sys.version, 'executable': sys.executable,
            'measurement_source_sha256': publisher.digest(ROOT / 'scripts/measure/publication_costs.py')}, outcomes=outcomes)


def test_each_restored_inventory_file_hashes_once_and_reuses_only_issued_proof(ready, monkeypatch):
    from congress_api.retention import viewer_inventory
    from copy import copy
    remote, root, _ = ready
    original = viewer_inventory.file_identity
    hashes = []
    def counted(path):
        hashes.append(Path(path))
        return original(path)
    monkeypatch.setattr(viewer_inventory, 'file_identity', counted)
    verified = attempts.verify_prepared(publisher, root)
    receipt, manifest, _ = verified
    assert len(hashes) == len(receipt['files']) and len(set(hashes)) == len(hashes)
    attempts.verify_prepared(publisher, root, validation=verified.validation)
    publisher.prepared_files(root / 'publication', manifest, validation=verified.validation)
    assert len(hashes) == len(receipt['files'])
    with pytest.raises(ValueError, match='proof no longer applies'):
        attempts.verify_prepared(publisher, root, validation=copy(verified.validation))
    with pytest.raises(ValueError, match='issued proof'):
        attempts.verify_prepared(publisher, root, validation=receipt['files'])
    path = root / next(relative for relative, item in receipt['files'].items() if relative.endswith('.parquet') and item['bytes'])
    raw = path.read_bytes(); path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='custody'):
        attempts.verify_prepared(publisher, root, validation=verified.validation)


def test_full_publication_consumes_accepted_status_without_second_index_scan(ready, monkeypatch):
    monkeypatch.setattr(publisher, 'index_recoveries', lambda *a, **kw: pytest.fail('Second recovery index scan'))
    assert publish(ready)['status'] == 'published'


def test_mapping_change_after_accepted_preparation_refuses_before_public_writes(ready):
    remote, _, _ = ready
    remote.objects[publisher.ACCEPTED_KEY] = publisher.encoded({'version': 1, 'recoveries': []})
    remote.versions[publisher.ACCEPTED_KEY] = 'mapping-advanced'
    assert publish(ready)['status'] == 'superseded'
    assert remote.puts == []


def test_oversized_output_refuses_before_artifact_acceptance_or_remote_write(source,tmp_path,monkeypatch):
    remote=Remote(source);root=tmp_path/'oversized'
    original=publisher.validate_prepared_output
    def oversized(directory,manifest):
        with (directory/'oversized.bin').open('wb') as stream:
            stream.truncate(5*1024**3)
        return original(directory,manifest)
    monkeypatch.setattr(publisher,'validate_prepared_output',oversized)
    with pytest.raises(ValueError,match='single-PUT limit'):
        attempts.prepare(publisher,remote,root,run_id='123',run_attempt='1',public_url=publisher.PUBLIC_URL)
    assert remote.puts==[] and not (root/'preparation.json').exists()
    assert json.loads((root/'continuation.json').read_text())['phases']=={}


def test_preparation_refuses_unadopted_file_catalog_without_rebuilding(source, tmp_path):
    remote=Remote(source)
    remote.objects['indexes/catalog.json']=publisher.encoded(dict(version=1,catalog_id='old'))
    remote.versions['indexes/catalog.json']='old'
    with pytest.raises(ValueError,match='explicitly adopted native'):
        attempts.prepare(publisher,remote,tmp_path/'refused',run_id='1',run_attempt='1',public_url=publisher.PUBLIC_URL)
    assert not (tmp_path/'refused').exists() and not remote.puts
    assert not any(key.endswith('.parquet') for key in remote.gets)


def test_preparation_requires_explicit_native_runtime_before_creating_output(source, tmp_path, monkeypatch):
    remote=Remote(source);monkeypatch.delenv('DOCSPEC_CONFIG')
    with pytest.raises(ValueError,match='explicit DOCSPEC_CONFIG'):
        attempts.prepare(publisher,remote,tmp_path/'refused',run_id='1',run_attempt='1',public_url=publisher.PUBLIC_URL)
    assert not (tmp_path/'refused').exists() and not remote.puts


def test_preparation_rechecks_exact_native_selector_before_payload_reads(source, tmp_path, monkeypatch):
    remote=Remote(source);original=remote.get_object;count=0
    def read(**request):
        nonlocal count
        if request['Key']=='indexes/catalog.json':
            count+=1
            if count==2:remote.versions[request['Key']]='advanced'
        return original(**request)
    monkeypatch.setattr(remote,'get_object',read)
    with pytest.raises(ValueError,match='Catalog changed before'):
        attempts.prepare(publisher,remote,tmp_path/'refused',run_id='1',run_attempt='1',public_url=publisher.PUBLIC_URL)
    assert not (tmp_path/'refused').exists() and not remote.puts
