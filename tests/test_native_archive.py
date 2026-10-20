"""Maintained acquisition policy runs against the injected native raw owner."""
import gzip
import json

import pyarrow as pa
import pytest

from congress_api.retention.raw_archive import Archive, adopt_legacy_archive, CAPTURE_SCHEMA
from native_memory_helpers import memory_raw_storage
import test_raw_source_sync as policy


@pytest.fixture
def archive_factory(monkeypatch):
    def create(store, run_id, **kwargs):
        if not hasattr(store, '_native_raw'):
            store._native_raw = memory_raw_storage(store)
            adopt_legacy_archive(store, store._native_raw, operation='explicit-fixture-seed')
        return Archive(store, run_id, storage=store._native_raw, **kwargs)
    monkeypatch.setattr(policy, 'Archive', create)
    return create


@pytest.mark.parametrize('case', [
    policy.test_capture_links_and_resume_without_repeating_successes,
    policy.test_200_challenge_and_failed_provider_do_not_become_saved_documents,
    policy.test_attempt_budget_leaves_discovered_links_for_the_next_run,
    policy.test_stop_saves_state_and_does_not_continue_to_later_work,
    policy.test_collector_exception_drains_other_inflight_successes,
    policy.test_accounting_distinguishes_urls_tasks_usable_results_and_bodies,
    policy.test_accounting_counts_legacy_body_references_without_digests,
])
def test_acquisition_policy_on_native_archive(archive_factory, case):
    case()


def test_archive_resume_body_lookup_summary_and_unchanged_avoid_capture_scan(archive_factory):
    store = policy.MemoryStore()
    archive = archive_factory(store, 'first')
    url = 'https://example.gov/a.pdf'
    archive.record(policy.response(url, b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    owner = store._native_raw
    owner.capture_pages.entries = lambda *args: pytest.fail('Hidden capture scan')
    writes = list(store.writes)
    native_writes = list(owner.native.writes)
    resumed = archive_factory(store, 'next')
    digest = resumed.state[url]['sha256']
    assert resumed.body_info[digest]['body_key'] == resumed.state[url]['body_key']
    assert resumed.retained_body_count == 1
    resumed.save()
    assert store.writes == writes
    assert owner.native.writes == native_writes


def test_receipt_interruption_recovers_once_with_preserved_observation(archive_factory):
    store = policy.MemoryStore()
    first = archive_factory(store, 'interrupted')
    first.record(policy.response('https://example.gov/a.pdf', b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    first.flush()  # Durable receipt, no selected captures yet.
    resumed = archive_factory(store, 'resume')
    assert len(resumed.additions) == 1
    resumed.save()
    again = archive_factory(store, 'again')
    assert again.additions == []
    assert len(again.captures) == 1
    assert again.state == resumed.state


def test_real_native_archive_roundtrip_and_unchanged_restart(tmp_path):
    import os
    import shutil
    from native_test_helpers import native_test_client
    from congress_api.retention.raw_storage import RawStorage
    from test_raw_storage import SelectorStore
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    store = SelectorStore()
    native = native_test_client(binary, tmp_path / 'native')
    owner = RawStorage(store, native)
    adopt_legacy_archive(store, owner, operation='explicit-empty-seed')
    archive = Archive(store, 'actual-native', storage=owner)
    url = 'https://example.gov/a.pdf'
    archive.record(policy.response(url, b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    assert archive.captures['context_url'].to_pylist() == [url]
    assert archive.retained_body_count == 1
    writes = list(store.writes)
    owner.capture_pages.entries = lambda *args: pytest.fail('Hidden capture scan on restart')
    resumed = Archive(store, 'actual-native-resume', storage=owner)
    assert resumed.body_info[resumed.state[url]['sha256']]['body_key'] == resumed.state[url]['body_key']
    resumed.save()
    assert store.writes == writes


from test_raw_capture_only import worker


def test_capture_only_cli_uses_the_injected_native_archive(tmp_path, worker, archive_factory):
    from io import StringIO
    from congress_api.cli import raw_sync
    from congress_api.cli.raw_progress import ProgressLog
    from congress_api.retention.raw_storage import RAW_KEY
    store = policy.MemoryStore()
    archive_factory(store, 'explicit-seed')
    seed = tmp_path / 'seed.json'
    seed.write_text(json.dumps({'url': 'https://example.gov/new.pdf'}))
    args = raw_sync.parser().parse_args(['--capture-only', '--transport', 'direct',
        '--fetcher-binary', str(worker), '--seed', str(seed), '--workers', '1',
        '--summary', str(tmp_path / 'summary.json')])
    with ProgressLog(tmp_path / 'progress.json', stream=StringIO()) as log:
        raw_sync.run(args, log, store=store, raw_storage=store._native_raw)
    result = json.loads(args.summary.read_text())
    assert result['acquisition_status'] == 'completed'
    assert result['catalog_status'] == 'not_run'
    assert result['accounting']['unique_retained_body_keys'] == 1
    assert RAW_KEY in store.writes
    assert 'indexes/captures.parquet' not in store.writes
    assert 'indexes/download-state.parquet' not in store.writes


def test_cli_requires_explicit_native_configuration_before_storage_access(tmp_path):
    from io import StringIO
    from congress_api.cli import raw_sync
    from congress_api.cli.raw_progress import ProgressLog
    args = raw_sync.parser().parse_args(['--capture-only', '--transport', 'direct',
        '--summary', str(tmp_path / 'summary.json')])
    with ProgressLog(tmp_path / 'progress.json', stream=StringIO()) as log:
        with pytest.raises(SystemExit, match='--native-config is required'):
            raw_sync.run(args, log, store=object())


def test_archive_preserves_richer_adopted_state_on_correction_and_restart():
    from congress_api.retention.raw_archive import STATE_SCHEMA, STATE_KEY, encode_table
    schema = STATE_SCHEMA.append(pa.field('extra', pa.struct([
        pa.field('large', pa.uint64()), pa.field('nested', pa.list_(pa.binary()))])))
    url = 'https://example.gov/richer.pdf'
    extra = dict(large=2**64-1, nested=[None, b'exact'])
    prior = pa.Table.from_pylist([dict(url=url, family='documents', outcome='failed',
        attempts=7, extra=extra)], schema=schema)
    store = policy.MemoryStore()
    store.objects[STATE_KEY] = encode_table(prior)
    owner = memory_raw_storage(store, state_schema=schema)
    adopt_legacy_archive(store, owner, operation='explicit-rich-seed')
    archive = Archive(store, 'correct-rich', storage=owner)
    archive.record(policy.response(url, b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    restarted = Archive(store, 'restart-rich', storage=owner)
    assert restarted.state[url]['extra'] == extra
    assert restarted.state[url]['attempts'] == 8
    assert restarted.state[url]['outcome'] == 'saved'
    assert restarted.selected.states().schema.equals(schema)


def test_changed_native_catalog_seeds_only_scope_sources_and_retains_cursor(monkeypatch, archive_factory):
    from contextlib import contextmanager
    from congress_api.retention import catalog_publication
    from congress_api.retention.catalog_publication import MANIFEST_KEY
    store = policy.MemoryStore()
    archive_factory(store, 'initial')
    store.objects[MANIFEST_KEY] = b'{"version":2,"selection":{}}'
    table = pa.table(dict(source_url=['https://example.gov/queued.pdf'], body_key=[None],
        format=[['pdf']], http_status=[['200']], media_type=[['application/pdf']]))
    calls = []
    class LogicalTable:
        schema_arrow = table.schema
        def iter_batches(self, *, batch_size, columns):
            assert batch_size == 256
            calls.append(columns)
            yield from table.select(columns).to_batches()
    class NativeCatalog:
        version = store.version(MANIFEST_KEY)
        identity = dict(selector_sha256='current', selected_ref={'scope': 'current'})
        def changed_sources_since(self, previous, *, max_ordered_bytes):
            assert previous == dict(selector_sha256=None, selected_ref=None) and max_ordered_bytes == 64 << 20
            return LogicalTable()
        def changes_since(self, previous):
            pytest.fail('Payload replay across obsolete scopes attempted')
        @property
        def filenames_path(self):
            pytest.fail('Native catalog path export attempted')
        def table(self, label, *, max_ordered_bytes):
            pytest.fail('Full native source scan attempted')
    @contextmanager
    def read(store, *, native, read=None):
        assert native is store._native_raw.native
        yield NativeCatalog()
    monkeypatch.setattr(catalog_publication, 'read_catalog', read)
    archive = archive_factory(store, 'changed-catalog')
    assert calls
    assert archive.state['https://example.gov/queued.pdf']['outcome'] == 'pending'
    archive.save()
    assert archive.selected.manifest['filename_version'] == NativeCatalog.identity
    calls.clear()
    NativeCatalog.changes_since = lambda *args: pytest.fail('Unchanged cursor traversed')
    restarted = archive_factory(store, 'same-catalog')
    assert restarted.filename_version == NativeCatalog.identity and calls == []


def test_archive_consumes_real_retained_catalog_scope_chain_and_unchanged_reads_no_catalog_payload(tmp_path, monkeypatch):
    from congress_api.retention.catalog_publication import read_catalog
    from congress_api.retention.catalog_selection import NativeCatalogSnapshot
    from congress_api.retention.catalog_updates import update_native_catalog
    from test_native_catalog_selection import seed
    from test_catalog_dependencies import identity, source
    from test_raw_storage import SelectorStore
    store = SelectorStore()
    owner = memory_raw_storage(store, max_state_rows=3)
    adopt_legacy_archive(store, owner, operation='explicit-empty')
    dependencies, rows = seed(tmp_path, store, owner.native)
    initial = Archive(store, 'initial-catalog', storage=owner)
    initial.save()
    cursor = initial.filename_version
    with read_catalog(store, native=owner.native) as previous:
        update_native_catalog(store, native=owner.native, previous=previous, dependencies=dependencies,
            deletions=[identity(rows[2])], candidate='split', directory=tmp_path / 'split',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    with read_catalog(store, native=owner.native) as previous:
        update_native_catalog(store, native=owner.native, previous=previous, dependencies=dependencies,
            replacements=[source('newly-discovered.pdf', 'N')], candidate='new-url', directory=tmp_path / 'new-url',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    with read_catalog(store, native=owner.native) as previous:
        update_native_catalog(store, native=owner.native, previous=previous, dependencies=dependencies,
            deletions=[identity(source('newly-discovered.pdf', 'N'))], replacements=[source('newly-discovered.pdf', 'N2')],
            candidate='newer-body', directory=tmp_path / 'newer-body',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    with read_catalog(store, native=owner.native) as previous:
        update_native_catalog(store, native=owner.native, previous=previous, dependencies=dependencies,
            replacements=[source('removed-before-startup.pdf', 'D')], candidate='temporary-url', directory=tmp_path / 'temporary-url',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    with read_catalog(store, native=owner.native) as previous:
        update_native_catalog(store, native=owner.native, previous=previous, dependencies=dependencies,
            deletions=[identity(source('removed-before-startup.pdf', 'D'))], candidate='removed-url', directory=tmp_path / 'removed-url',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'))
    owner.native.reads.clear()
    monkeypatch.setattr(NativeCatalogSnapshot, 'table', lambda *a, **k: pytest.fail('Full selected catalog scanned'))
    caught_up = Archive(store, 'catch-up', storage=owner)
    assert caught_up.state['https://example.gov/newly-discovered.pdf']['outcome'] == 'retained'
    assert caught_up.state['https://example.gov/newly-discovered.pdf']['body_key'] == 'N2'
    assert 'https://example.gov/removed-before-startup.pdf' not in caught_up.state
    assert caught_up.filename_version != cursor
    assert len([dataset for dataset in owner.native.reads if dataset.startswith('catalog-filenames-')]) == 2
    caught_up.save()
    owner.native.reads.clear()
    writes = list(store.writes)
    again = Archive(store, 'unchanged', storage=owner)
    again.save()
    assert again.filename_version == caught_up.filename_version
    assert not [dataset for dataset in owner.native.reads if dataset.startswith('catalog-filenames-')]
    assert store.writes == writes


def test_native_catalog_missing_cursor_refuses_without_full_scan(tmp_path, monkeypatch):
    from congress_api.retention.catalog_selection import NativeCatalogSnapshot
    from test_native_catalog_selection import seed
    from test_raw_storage import SelectorStore
    store = SelectorStore()
    owner = memory_raw_storage(store)
    owner.publish(owner.prepare(owner.snapshot(), operation='unseeded-catalog-cursor', filename_version='old-etag'))
    seed(tmp_path, store, owner.native)
    monkeypatch.setattr(NativeCatalogSnapshot, 'table', lambda *a, **k: pytest.fail('Full selected catalog scanned'))
    owner.native.reads.clear()
    with pytest.raises(ValueError, match='explicit initial cursor'):
        Archive(store, 'must-adopt-cursor', storage=owner)
    assert not [dataset for dataset in owner.native.reads if dataset.startswith('catalog-filenames-')]


def test_changed_file_catalog_requires_explicit_adoption_before_payload_read(monkeypatch, archive_factory):
    from congress_api.retention.catalog_publication import MANIFEST_KEY
    store = policy.MemoryStore()
    archive_factory(store, 'empty')
    store.objects[MANIFEST_KEY] = b'{"version":1,"changed":true}'
    monkeypatch.setattr(store, 'read_derived_file', lambda *a, **k: pytest.fail('Legacy catalog payload read'))
    with pytest.raises(ValueError, match='explicit catalog adoption'):
        archive_factory(store, 'changed-file-catalog')


def test_unchanged_archive_does_not_read_unrelated_state_payloads(archive_factory):
    store = policy.MemoryStore()
    archive = archive_factory(store, 'empty')
    for i in range(100):
        archive.seed({'url': f'https://example.gov/{i}.pdf'})
        archive.state[f'https://example.gov/{i}.pdf'].update(outcome='saved', links_scanned=True)
    archive.save()
    owner = store._native_raw
    owner.native.reads.clear()
    writes = list(store.writes)
    restarted = Archive(store, 'no-change', storage=owner)
    assert len(restarted.state) == 100
    restarted.save()
    assert owner.native.reads == []
    assert store.writes == writes


def test_accessed_state_reference_remains_mutable_after_save(archive_factory):
    store = policy.MemoryStore()
    archive = archive_factory(store, 'working-reference')
    url = 'https://example.gov/lifetime.pdf'
    archive.seed({'url': url})
    held = archive.state[url]
    archive.save()
    held.update(outcome='request_failed', attempts=4)
    archive.save()
    assert store._native_raw.snapshot().state(url)['attempts'] == 4
