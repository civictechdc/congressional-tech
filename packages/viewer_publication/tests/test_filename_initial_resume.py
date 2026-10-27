"""Initial native serving adoption shares verified renderer checkpoints."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tests')]
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed
from viewer_publication import publish_filename_viewer as builder


@pytest.mark.parametrize('task_prefix', ['component-chunk:', 'source-route:'])
@pytest.mark.parametrize('event', ['renderer_task_started', 'renderer_task_completed'])
def test_initial_adoption_resumes_completed_chunks_after_keyboard_interrupt(tmp_path, task_prefix, event):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    snapshot = read_catalog(store, native=native)
    selector = store.read('indexes/catalog.json')
    options = dict(review_identities=None, preparation_binding=dict(origin='initial-adoption'))
    stopped = []
    def interrupt(value):
        if value['event'] == event and value.get('task', '').startswith(task_prefix):
            stopped.extend(native.reads)
            raise KeyboardInterrupt()
    native.reads.clear()
    with pytest.raises(KeyboardInterrupt):
        builder.publish_selected(snapshot, tmp_path / 'publication', stage_event=interrupt, **options)
    assert not (tmp_path / 'publication/manifest.json').exists()
    assert (tmp_path / 'publication.renderer-upgrade/stages.sqlite').is_file()
    native.reads.clear()
    manifest = builder.publish_selected(snapshot, tmp_path / 'publication', resume_preparation=True, **options)
    if event == 'renderer_task_completed':
        assert not set(stopped) & set(native.reads)
    assert manifest['version'] == 6 and manifest['source_identity'] == snapshot.identity
    assert store.read('indexes/catalog.json') == selector
    native.reads.clear()
    assert builder.publish_selected(snapshot, tmp_path / 'publication', resume_preparation=True, **options) == manifest
    assert not native.reads


def test_initial_adoption_refuses_changed_source_config_review_binding_and_corruption(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    snapshot = read_catalog(store, native=native)
    options = dict(review_identities=None, preparation_binding=dict(runtime='pinned'),
                   prior_review_binding=dict(version=1, catalog_id='v5', withdrawn=[]))
    def stop(value):
        if value['event'] == 'renderer_task_completed' and value.get('task', '').startswith('component-chunk:'):
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        builder.publish_selected(snapshot, tmp_path / 'publication', stage_event=stop, **options)
    native.reads.clear()
    for changed in (dict(preparation_binding=dict(runtime='changed')),
                    dict(prior_review_binding=dict(version=1, catalog_id='changed', withdrawn=[])),
                    dict(review_identities=builder.review_binding.IDENTITIES),
                    dict(compression_policy=builder.DEFAULT_COMPRESSION_POLICY._replace(level=9))):
        with pytest.raises(ValueError, match='inputs changed'):
            builder.publish_selected(snapshot, tmp_path / 'publication', resume_preparation=True, **dict(options, **changed))
        assert not native.reads
    original = snapshot.identity
    snapshot.identity = dict(original, selector_sha256='0' * 64)
    with pytest.raises(ValueError, match='inputs changed'):
        builder.publish_selected(snapshot, tmp_path / 'publication', resume_preparation=True, **options)
    snapshot.identity = original
    asset = next((tmp_path / 'publication').rglob('*.parquet'))
    raw = asset.read_bytes()
    asset.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='asset.*changed'):
        builder.publish_selected(snapshot, tmp_path / 'publication', resume_preparation=True, **options)
    assert not native.reads


@pytest.mark.parametrize('event', ['renderer_task_started', 'renderer_task_completed'])
def test_initial_cli_checkpoint_survives_abrupt_process_exit(tmp_path, event):
    import subprocess
    import pyarrow.parquet as pq
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    tables = {}
    for index, (name, table) in enumerate(native.tables.items()):
        path = tmp_path / f'table-{index}.parquet'
        pq.write_table(table, path)
        tables[name] = str(path)
    (tmp_path / 'tables.json').write_text(json.dumps(tables))
    (tmp_path / 'runtime').write_bytes(b'exact fixture runtime')
    script = r'''
from contextlib import contextmanager
from pathlib import Path
import json, os, sys
import pyarrow.parquet as pq
repo, folder, event, mode = sys.argv[1:]
repo, folder = Path(repo), Path(folder)
sys.path[:0] = [str(repo / 'tests'), str(repo / 'packages/congress_api/tests'), str(repo / 'packages/viewer_publication/tests')]
from test_catalog_coalesced_batches import Native
from test_viewer_publication_attempt import Remote
from congress_api.retention.docspec import NativeDatasets
from viewer_publication import filename_native, publication_cli as cli, publish_viewer_r2 as publisher
native = Native()
native.tables = {name: pq.read_table(path) for name, path in json.loads((folder / 'tables.json').read_text()).items()}
native.execution_files = lambda: (folder / 'runtime',)
original_read = native.source_batches
@contextmanager
def observed(*args, **kwargs):
    with original_read(*args, **kwargs) as reader:
        (folder / (mode + '-reads.json')).write_text(json.dumps(native.reads))
        yield reader
native.source_batches = observed
NativeDatasets.from_config = classmethod(lambda cls, path: native)
cli.make_client = lambda: Remote(folder / 'store')
original = filename_native.publish_selected
def interrupted(*args, **options):
    progress = options['stage_event']
    def observe(value):
        progress(value)
        if mode == 'stop' and value['event'] == event and value.get('task', '').startswith('component-chunk:'):
            os._exit(73)
    options['stage_event'] = observe
    return original(*args, **options)
filename_native.publish_selected = interrupted
arguments = ['prepare', '--directory', str(folder / 'preparation'), '--native-config', str(folder / 'runtime'),
             '--run-id', '123' if mode == 'stop' else '999', '--run-attempt', '1']
if mode == 'resume':
    arguments.append('--resume-preparation')
raise SystemExit(cli.main(publisher, arguments))
'''
    args = [sys.executable, '-c', script, str(ROOT), str(tmp_path), event]
    stopped = subprocess.run([*args, 'stop'], capture_output=True, text=True, timeout=60)
    assert stopped.returncode == 73, stopped.stderr
    root = tmp_path / 'preparation'
    assert not (root / 'preparation.json').exists() and not (root / 'prepared-result.json').exists()
    latest = json.loads((root / 'preparation-diagnostics.json').read_text())['latest']
    assert latest['event'] == event and latest['task'].startswith('component-chunk:')
    resumed = subprocess.run([*args, 'resume'], capture_output=True, text=True, timeout=60)
    assert resumed.returncode == 0, resumed.stderr
    before = json.loads((tmp_path / 'stop-reads.json').read_text()) if (tmp_path / 'stop-reads.json').exists() else []
    after = json.loads((tmp_path / 'resume-reads.json').read_text())
    if event == 'renderer_task_completed':
        assert not set(before) & set(after)
    receipt = json.loads((root / 'preparation.json').read_text())
    result = json.loads((root / 'prepared-result.json').read_text())
    assert receipt['binding']['run_id'] == '123' and receipt['artifact_producer']['run_id'] == '999'
    assert result['artifact_name'].startswith('viewer-prepared-999-1-')
