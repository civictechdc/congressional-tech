"""Capture batches persist independently; a later rebuild consumes their receipts."""

from io import StringIO
import json
import sys

import pytest

from congress_api.cli import raw_sync
from congress_api.cli.raw_progress import ProgressLog
from congress_api.retention.catalog_publication import MANIFEST_KEY
from congress_api.retention.raw_archive import Archive, CAPTURES_KEY, STATE_KEY
from test_raw_catalog import table
from test_raw_source_sync import MemoryStore


@pytest.fixture
def worker(tmp_path):
    """Exercise the real worker adapter against a deterministic process boundary."""
    binary = tmp_path / "worker"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    body = pathlib.Path(sys.argv[1]) / str(request['id'])\n"
        "    body.write_bytes(b'%PDF-1.7\\nfixture\\n%%EOF')\n"
        "    response = dict(body_file=str(body), http_status=200,\n"
        "        final_url=request['url'], complete=True,\n"
        "        response_header_items=[dict(name='Content-Type', value='application/pdf')])\n"
        "    print(json.dumps(dict(id=request['id'], response=response)), flush=True)\n"
    )
    binary.chmod(0o700)
    return binary


def execute(tmp_path, store, *argv):
    args = raw_sync.parser().parse_args([
        "--transport", "direct", "--index-workers", "1", "--workers", "1",
        "--summary", str(tmp_path / "summary.json"), *map(str, argv),
    ])
    with ProgressLog(args.summary.with_suffix('.progress.json'), stream=StringIO()) as log:
        raw_sync.run(args, log, store=store)
    return json.loads(args.summary.read_text())


def test_capture_only_saves_and_resumes_before_separate_publication(tmp_path, worker):
    store = MemoryStore()
    # Start from a published empty generation, then capture a newly discovered URL.
    execute(tmp_path, store, "--rebuild-only")
    old_catalog = dict(store.objects)
    old_capture_index = store.objects[CAPTURES_KEY]
    store.writes.clear()
    seed = tmp_path / "seed.json"
    url = "https://example.gov/new.pdf"
    seed.write_text(json.dumps({"url": url}))
    result = execute(tmp_path, store, "--capture-only", "--fetcher-binary", worker,
                     "--seed", seed)
    assert result['acquisition_status'] == 'completed'
    assert result['catalog_status'] == 'not_run'
    assert 'catalog' not in result
    assert 'filename_rows' not in result['accounting']
    assert result['accounting']['native_request_dispatches'] == 1
    assert Archive(store, 'read').state[url]['outcome'] == 'saved'
    assert store.objects[CAPTURES_KEY] != old_capture_index
    assert store.keys('receipts/') and store.keys('bodies/')
    assert MANIFEST_KEY not in store.writes
    assert all(store.objects[k] == v for k, v in old_catalog.items() if k != CAPTURES_KEY)
    assert len(table(store)) == 0
    progress = json.loads((tmp_path / 'summary.progress.json').read_text())
    assert progress['status'] == 'completed' and progress['stage'] == 'capture_saved'

    receipts = store.keys('receipts/')
    result = execute(tmp_path, store, "--capture-only", "--fetcher-binary", worker,
                     "--seed", seed)
    assert result['accounting']['native_request_dispatches'] == 0
    assert result['catalog_status'] == 'not_run'
    assert store.keys('receipts/') == receipts
    retained = {k: v for k, v in store.objects.items()
                if k in {CAPTURES_KEY, STATE_KEY} or k.startswith(('receipts/', 'bodies/'))}
    result = execute(tmp_path, store, "--rebuild-only")
    assert result['acquisition_status'] == 'not_run'
    assert result['catalog_status'] == 'completed'
    assert store.objects[MANIFEST_KEY] != old_catalog[MANIFEST_KEY]
    assert all(store.objects[k] == v for k, v in retained.items())
    row, = table(store).to_pylist()
    assert row['source_url'] == url and row['body_key']


@pytest.mark.parametrize('other', ['--rebuild-only', '--update-only', '--plan-only'])
def test_capture_only_is_mutually_exclusive(other):
    with pytest.raises(SystemExit):
        raw_sync.parser().parse_args(['--capture-only', other])


def test_capture_only_rejects_body_inspection_before_storage_access(tmp_path):
    with pytest.raises(SystemExit, match='--inspect-bodies requires a catalog rebuild'):
        execute(tmp_path, object(), '--capture-only', '--inspect-bodies')


@pytest.mark.parametrize('other', ['--repair', '--update-only', '--rebuild-only', '--plan-only'])
def test_initial_only_rejects_replay_or_non_acquisition_before_storage_access(tmp_path, other):
    with pytest.raises(SystemExit, match='--initial-only requires acquisition'):
        execute(tmp_path, object(), '--initial-only', other)


@pytest.mark.parametrize('extra', [[], ['--plan-only'], ['--rebuild-only'], ['--update-only'],
    ['--capture-only', '--repair'], ['--capture-only', '--initial-only'],
    ['--capture-only', '--seed', 'absent.json']])
def test_retry_selector_rejects_other_modes_before_storage(tmp_path, extra):
    with pytest.raises(SystemExit, match='--retry-outcome requires'):
        execute(tmp_path, object(), '--retry-outcome', 'request_failed', *extra)


def test_cli_targeted_retry_does_not_fetch_other_failures(tmp_path, worker):
    store = MemoryStore()
    archive = Archive(store, 'seed-retries')
    for outcome in ['retry_later', 'request_failed', 'http_error']:
        url = f'https://example.gov/{outcome}.pdf'
        archive.seed({'url': url}, publisher_link=True)
        archive.state[url].update(outcome=outcome, next_attempt_at=None)
    archive.save()
    result = execute(tmp_path, store, '--capture-only', '--fetcher-binary', worker,
        '--retry-outcome', 'retry_later', '--retry-outcome', 'request_failed')
    assert result['attempted'] == result['fetch'] == 2
    assert result['retry_outcomes'] == ['request_failed', 'retry_later']
    assert result['accounting']['url_outcomes']['http_error'] == 1
    assert result['accounting']['retained_replays_completed'] == 0


def test_capture_failure_preserves_catalog_and_reports_acquisition_failure(tmp_path):
    store = MemoryStore()
    execute(tmp_path, store, '--rebuild-only')
    before = dict(store.objects)
    with pytest.raises(FileNotFoundError):
        execute(tmp_path, store, '--capture-only', '--fetcher-binary', tmp_path / 'missing')
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['acquisition_status'] == 'failed'
    assert result['catalog_status'] == 'not_run'
    assert result['error_type'] == 'FileNotFoundError'
    assert store.objects == before


def test_default_cli_still_captures_and_publishes(tmp_path, worker):
    store = MemoryStore()
    seed = tmp_path / 'seed.json'
    seed.write_text('{"url":"https://example.gov/default.pdf"}')
    result = execute(tmp_path, store, '--fetcher-binary', worker, '--seed', seed)
    assert result['acquisition_status'] == result['catalog_status'] == 'completed'
    assert result['body_metadata']['failed'] == 1  # Fixture bytes are not a readable PDF.
    assert store.keys('indexes/processing/body-results/')
    row, = table(store).to_pylist()
    assert row['filename'] == 'default.pdf' and row['body_key']
    assert row['body_format'] == ['pdf']


def test_update_only_preserves_catalog_without_starting_acquisition(tmp_path):
    store = MemoryStore()
    execute(tmp_path, store, '--rebuild-only')
    before = dict(store.objects)
    result = execute(tmp_path, store, '--update-only', '--fetcher-binary', tmp_path / 'absent')
    assert result['mode'] == 'update'
    assert result['acquisition_status'] == 'not_run'
    assert result['catalog']['unchanged'] is True
    assert store.objects == before


def test_capture_capacity_defaults():
    args = raw_sync.parser().parse_args([])
    assert args.max_buffer_mib == 2048
    assert args.metadata_workers == 3
