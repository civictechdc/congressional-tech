"""Explicit native CLI modes share one owner and never imply acquisition/rebuild."""
from io import StringIO
import json
from types import SimpleNamespace

import pytest

from congress_api.cli import raw_sync
from congress_api.cli.raw_progress import ProgressLog


def execute(tmp_path, *arguments, **injections):
    args = raw_sync.parser().parse_args(['--summary', str(tmp_path / 'summary.json'), *arguments])
    with ProgressLog(args.summary.with_suffix('.progress.json'), stream=StringIO()) as log:
        raw_sync.run(args, log, **injections)
    return json.loads(args.summary.read_text())


def owner_for(store):
    return SimpleNamespace(store=store, native=object(), snapshot=lambda: SimpleNamespace(identity='a' * 64))


def no_acquisition(monkeypatch):
    for name in ('Archive', 'RustFetcher', 'run_sync', 'capture_sources'):
        monkeypatch.setattr(raw_sync, name, lambda *a, **k: pytest.fail('Acquisition entered'))
    monkeypatch.setattr(raw_sync.zyte, 'token', lambda *a: pytest.fail('Provider token requested'))


@pytest.mark.parametrize('operation', ['--rebuild-only', '--repair', '--inspect-bodies'])
def test_unscoped_reprocessing_refuses_before_runtime_or_archive_access(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(raw_sync, 'connect_storage', lambda *a, **k: pytest.fail('Storage accessed'))
    with pytest.raises(SystemExit, match='not operational|scoped native reprocessing'):
        execute(tmp_path, operation)


def test_update_injects_one_native_owner_and_does_not_enter_acquisition_or_rebuild(tmp_path, monkeypatch):
    store = object(); owner = owner_for(store)
    no_acquisition(monkeypatch)
    calls = []
    def update(actual_store, **options):
        assert actual_store is store and options['raw_storage'] is owner
        assert 'repair' not in options and 'inspect_bodies' not in options
        calls.append(options)
        return dict(unchanged=True, counts=dict(source_rows=2, document_rows=1))
    monkeypatch.setattr(raw_sync, 'update_from_raw', update)
    result = execute(tmp_path, '--update-only', store=store, raw_storage=owner)
    assert len(calls) == 1
    assert result['mode'] == 'update' and result['acquisition_status'] == 'not_run'
    assert result['catalog_status'] == 'completed'


def test_explicit_runtime_constructed_once_and_same_owner_reaches_catalog(tmp_path, monkeypatch):
    from congress_api.retention.docspec import NativeDatasets
    from congress_api.retention.raw_storage import RawStorage
    store, native = object(), object(); owner = owner_for(store); owner.native = native
    calls = []
    monkeypatch.setattr(NativeDatasets, 'from_config', lambda path: calls.append(path) or native)
    monkeypatch.setattr(RawStorage, 'open', lambda actual, client: owner if (actual is store and client is native) else pytest.fail('Different owner'))
    monkeypatch.setattr(raw_sync, 'update_from_raw', lambda actual, **options: dict(
        unchanged=options['raw_storage'] is owner, counts=dict(source_rows=0, document_rows=0)))
    config = tmp_path / 'explicit.json'
    result = execute(tmp_path, '--update-only', '--native-config', str(config), store=store)
    assert calls == [config] and result['catalog']['unchanged']


@pytest.mark.parametrize('flags,label,api', [
    (['--qualify-sources'], 'qualify-sources', 'qualify_source_contributions'),
    (['--upgrade-source-rules', 'source-rules-2'], 'upgrade-source-rules', 'upgrade_source_rules'),
])
def test_explicit_complete_modes_dispatch_without_acquisition_and_reuse_retry_directory(tmp_path, monkeypatch, flags, label, api):
    from congress_api.retention import raw_catalog
    store = object(); owner = owner_for(store)
    no_acquisition(monkeypatch)
    monkeypatch.setattr(raw_sync, 'update_from_raw', lambda *a, **k: pytest.fail('Ordinary update entered'))
    calls = []
    def complete(actual, **options):
        assert actual is store and options['raw_storage'] is owner
        calls.append(options)
        if len(calls) == 1:
            raise RuntimeError('Worker lost')
        return dict(counts=dict(source_rows=2, document_rows=1))
    monkeypatch.setattr(raw_catalog, api, complete, raising=False)
    with pytest.raises(RuntimeError, match='Worker lost'):
        execute(tmp_path, *flags, store=store, raw_storage=owner)
    failed = json.loads((tmp_path / 'summary.json').read_text())
    assert failed['catalog_status'] == 'failed' and failed['acquisition_status'] == 'not_run'
    result = execute(tmp_path, *flags, store=store, raw_storage=owner)
    assert result['mode'] == label and result['catalog_status'] == 'completed'
    assert calls[0]['directory'] == calls[1]['directory']
    assert calls[0]['candidate'] == calls[1]['candidate']
    if api == 'upgrade_source_rules':
        assert calls[1]['rule_version'] == 'source-rules-2'


def test_explicit_modes_are_mutually_exclusive_and_blank_upgrade_refuses_before_storage(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        raw_sync.parser().parse_args(['--qualify-sources', '--update-only'])
    monkeypatch.setattr(raw_sync, 'connect_storage', lambda *a, **k: pytest.fail('Storage accessed'))
    with pytest.raises(SystemExit, match='nonempty rule version'):
        execute(tmp_path, '--upgrade-source-rules', ' ')


def test_explicit_raw_adoption_preserves_investigated_values_and_retries_without_acquisition(tmp_path, monkeypatch):
    from test_raw_complete_adoption import setup
    store, owner, options, captures, states = setup(tmp_path)
    no_acquisition(monkeypatch)
    receipt = tmp_path / 'adopt.json'
    receipt.write_text(json.dumps(dict(version=1, operation=options['operation'], filename_version=options['filename_version'],
        inputs={name: dict(path=str(path), sha256=options['sha256s'][name]) for name, path in options['paths'].items()})))
    result = execute(tmp_path, '--adopt-raw', str(receipt), store=store, raw_storage=owner)
    assert result['mode'] == 'adopt-raw' and result['raw_adoption_status'] == 'completed'
    assert result['acquisition_status'] == result['catalog_status'] == 'not_run'
    selected = owner.snapshot()
    assert selected.captures().equals(captures) and selected.states().equals(states)
    before = list(store.writes), list(owner.native.writes)
    assert execute(tmp_path, '--adopt-raw', str(receipt), store=store, raw_storage=owner)['raw_adoption'] == result['raw_adoption']
    assert (store.writes, owner.native.writes) == before
    options['paths']['state'].write_bytes(b'changed')
    with pytest.raises(ValueError, match='input digest changed'):
        execute(tmp_path, '--adopt-raw', str(receipt), store=store, raw_storage=owner)
    assert owner.snapshot().identity == selected.identity


def test_explicit_catalog_adoption_preserves_pair_and_completed_retry(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    from test_catalog_adoption import existing
    from test_catalog_coalesced_batches import Native
    store, native = LocalStore(tmp_path / 'store'), Native()
    existing(tmp_path, store)
    with read_catalog(store) as old:
        sources, documents = pq.read_table(old.filenames_path), pq.read_table(old.documents_path)
    owner = owner_for(store); owner.native = native
    no_acquisition(monkeypatch)
    first = execute(tmp_path, '--adopt-catalog', 'investigated-pair', store=store, raw_storage=owner)
    with read_catalog(store, native=native) as selected:
        assert first['catalog']['selected_identity'] == selected.identity
        assert pa.Table.from_batches(list(selected.table('filenames', max_ordered_bytes=16 << 20).iter_batches())).equals(sources, check_metadata=True)
        assert pa.Table.from_batches(list(selected.table('documents', max_ordered_bytes=16 << 20).iter_batches())).equals(documents, check_metadata=True)
    second = execute(tmp_path, '--adopt-catalog', 'investigated-pair', store=store, raw_storage=owner)
    assert second['catalog']['selection'] == first['catalog']['selection'] and second['catalog']['unchanged']


def test_local_raw_archive_enters_same_incremental_owner_and_refuses_legacy_rebuild(tmp_path, monkeypatch):
    from congress_api.cli import document_index
    from congress_api.retention.catalog_cache import LocalStore
    (tmp_path / 'indexes').mkdir()
    (tmp_path / 'indexes/captures.parquet').write_bytes(b'legacy must not be decoded')
    with pytest.raises(SystemExit):
        document_index.main([str(tmp_path)])
    calls = []
    def run(args, log, *, store):
        assert isinstance(store, LocalStore) and store.root == tmp_path
        calls.append(args)
    monkeypatch.setattr(raw_sync, 'run', run)
    document_index.main([str(tmp_path), '--native-config', 'native.json'])
    assert calls[0].update_only and calls[0].native_config.name == 'native.json'
    document_index.main([str(tmp_path), '--native-config', 'native.json', '--upgrade-source-rules', 'v2'])
    assert calls[1].upgrade_source_rules == 'v2' and not calls[1].update_only
    with pytest.raises(SystemExit):
        document_index.main([str(tmp_path), '--native-config', 'native.json', '--rebuild'])
    assert len(calls) == 2


def test_raw_adoption_constructs_complete_investigated_schema_from_explicit_runtime(tmp_path, monkeypatch):
    from test_raw_complete_adoption import setup
    from congress_api.retention.docspec import NativeDatasets
    from congress_api.retention.raw_storage import RawStorage
    store, fixture, options, _, states = setup(tmp_path)
    no_acquisition(monkeypatch)
    monkeypatch.setattr(NativeDatasets, 'from_config', lambda _: fixture.native)
    receipt = tmp_path / 'adopt.json'
    receipt.write_text(json.dumps(dict(version=1, operation='configured-adoption', filename_version=options['filename_version'],
        inputs={name: dict(path=path.name, sha256=options['sha256s'][name]) for name, path in options['paths'].items()})))
    execute(tmp_path, '--adopt-raw', str(receipt), '--native-config', str(tmp_path / 'native.json'), store=store)
    reopened = RawStorage.open(store, fixture.native)
    assert reopened.state_schema.equals(states.schema, check_metadata=True)
    assert reopened.snapshot().states().equals(states, check_metadata=True)


@pytest.mark.parametrize('flags', [
    ['--update-only'], ['--qualify-sources'], ['--upgrade-source-rules', 'rules-2'],
    ['--adopt-catalog', 'pair'], ['--adopt-raw', 'investigated.json'],
])
def test_capture_only_conflicts_refuse_at_parser_and_injected_run_boundary(tmp_path, monkeypatch, flags):
    from congress_api.retention.docspec import NativeDatasets
    with pytest.raises(SystemExit):
        raw_sync.parser().parse_args(['--capture-only', *flags])
    no_acquisition(monkeypatch)
    monkeypatch.setattr(raw_sync, 'connect_storage', lambda *a, **k: pytest.fail('Archive storage accessed'))
    monkeypatch.setattr(NativeDatasets, 'from_config', lambda *a, **k: pytest.fail('Native runtime accessed'))
    monkeypatch.setattr(raw_sync, 'adoption_inputs', lambda *a: pytest.fail('Adoption inputs accessed'))
    args = raw_sync.parser().parse_args(['--native-config', 'native.json', '--summary', str(tmp_path / 'summary.json'), *flags])
    # Programmatic callers can bypass argparse's mutually exclusive group.
    args.capture_only = True
    with ProgressLog(args.summary.with_suffix('.progress.json'), stream=StringIO()) as log:
        with pytest.raises(SystemExit, match='--capture-only cannot be combined'):
            raw_sync.run(args, log)
    assert not args.summary.exists()


@pytest.mark.parametrize('version', [True, 1.0])
def test_raw_adoption_requires_integer_receipt_version_before_input_access(tmp_path, monkeypatch, version):
    from congress_api.retention import derived_files
    monkeypatch.setattr(derived_files, 'file_identity', lambda *a: pytest.fail('Input files accessed'))
    receipt = tmp_path / 'adopt.json'
    receipt.write_text(json.dumps(dict(version=version, operation='adoption',
        filename_version=dict(selector_sha256=None, selected_ref=None),
        inputs={name: dict(path=name + '.parquet', sha256='a' * 64) for name in ('captures', 'state')})))
    with pytest.raises(ValueError, match='Raw adoption requires exact input pins'):
        raw_sync.adoption_inputs(receipt)
