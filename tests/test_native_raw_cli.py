"""One configured native owner enters maintained CLI capture/catalog boundaries."""
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


@pytest.mark.parametrize('operation', ['--rebuild-only', '--repair', '--inspect-bodies'])
def test_unscoped_reprocessing_refuses_before_runtime_or_archive_access(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(raw_sync, 'connect_storage', lambda *a, **k: pytest.fail('Storage accessed'))
    with pytest.raises(SystemExit, match='not operational|scoped native reprocessing'):
        execute(tmp_path, operation)


def test_update_injects_one_native_owner_and_does_not_enter_acquisition_or_rebuild(tmp_path, monkeypatch):
    store = object()
    owner = SimpleNamespace(store=store, native=object())
    for name in ('Archive', 'RustFetcher', 'run_sync'):
        monkeypatch.setattr(raw_sync, name, lambda *a, **k: pytest.fail('Acquisition entered'))
    monkeypatch.setattr(raw_sync.zyte, 'token', lambda *a: pytest.fail('Provider token requested'))
    calls = []
    def update(actual_store, **options):
        assert actual_store is store and options['raw_storage'] is owner
        assert 'repair' not in options and 'inspect_bodies' not in options
        calls.append(options)
        return dict(unchanged=True, rows=2, document_rows=1)
    monkeypatch.setattr(raw_sync, 'rebuild_catalog', update)
    result = execute(tmp_path, '--update-only', store=store, raw_storage=owner)
    assert len(calls) == 1
    assert result['mode'] == 'update' and result['acquisition_status'] == 'not_run'
    assert result['catalog_status'] == 'completed'


def test_explicit_runtime_constructed_once_and_same_owner_reaches_catalog(tmp_path, monkeypatch):
    from congress_api.retention.docspec import NativeDatasets
    from congress_api.retention.raw_storage import RawStorage
    store, native = object(), object()
    owner = SimpleNamespace(store=store, native=native)
    calls = []
    monkeypatch.setattr(NativeDatasets, 'from_config', lambda path: calls.append(path) or native)
    monkeypatch.setattr(RawStorage, 'open', lambda actual, client: owner if (actual is store and client is native) else pytest.fail('Different owner'))
    monkeypatch.setattr(raw_sync, 'rebuild_catalog', lambda actual, **options: dict(unchanged=options['raw_storage'] is owner))
    config = tmp_path / 'explicit.json'
    result = execute(tmp_path, '--update-only', '--native-config', str(config), store=store)
    assert calls == [config] and result['catalog']['unchanged']
