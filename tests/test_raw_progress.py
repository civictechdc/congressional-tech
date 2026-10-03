"""Progress must remain observable during work and truthful after a failure."""
import io
import json
import logging

import pytest

from congress_api.cli.raw_progress import ProgressLog
from congress_api.retention import raw_progress as progress


def test_heartbeat_retains_stage_counts_and_shows_idle_time(tmp_path):
    now = [100.0]
    stream = io.StringIO()
    path = tmp_path / 'summary.progress.json'
    remote = []
    with ProgressLog(path, stream=stream, clock=lambda: now[0], interval=3600) as log:
        log.publish = remote.append
        progress.report('extract_filenames', completed=12, total=40, unit='filenames')
        progress.advance('objects_read', 2)
        progress.advance('bytes_read', 128)
        now[0] += 31
        log.heartbeat()
        state = json.loads(path.read_text())
        assert state['stage'] == 'extract_filenames'
        assert state['completed'] == 12 and state['total'] == 40
        assert state['elapsed_seconds'] == state['stage_elapsed_seconds'] == 31
        assert state['seconds_since_progress'] == 31
        assert state['counters'] == {'objects_read': 2, 'bytes_read': 128}
        assert state['status'] == 'running'
        assert json.loads(remote[-1]) == state
    assert json.loads(path.read_text())['status'] == 'completed'
    assert json.loads(remote[-1])['status'] == 'completed'
    assert len([json.loads(line) for line in stream.getvalue().splitlines()]) >= 3


def test_failure_preserves_last_stage_without_exposing_exception_payload(tmp_path):
    path = tmp_path / 'summary.progress.json'
    logger = progress.LOGGER
    level, handlers = logger.level, logger.handlers[:]
    with pytest.raises(ValueError):
        with ProgressLog(path, stream=io.StringIO(), interval=3600):
            progress.report('publish_documents', completed=0, total=2, unit='tables')
            raise ValueError('secret-bearing URL must not enter status')
    state = json.loads(path.read_text())
    assert state['status'] == 'failed'
    assert state['stage'] == 'publish_documents'
    assert state['completed'] == 0
    assert state['error_type'] == 'ValueError'
    assert 'secret-bearing' not in path.read_text()
    assert logger.level == level and logger.handlers == handlers


def test_status_upload_failure_does_not_fail_the_rebuild(tmp_path):
    stream = io.StringIO()
    with ProgressLog(tmp_path / 'progress.json', stream=stream, interval=3600) as log:
        def fail(_):
            raise RuntimeError('secret')
        log.publish = fail
        log.heartbeat()
    assert 'status_upload_failed' in stream.getvalue()
    assert 'secret' not in stream.getvalue()


def test_cli_publishes_status_with_run_identity_and_bounded_network_timeouts(tmp_path, monkeypatch):
    import boto3
    from congress_api.cli import raw_sync

    configs, uploads = [], []
    def client(_, **kwargs):
        configs.append(kwargs['config'])
        return object()
    class Store:
        def __init__(self, *_):
            pass
        def put(self, key, payload):
            uploads.append((key, json.loads(payload)))
    monkeypatch.setattr(boto3, 'client', client)
    monkeypatch.setattr(raw_sync, 'R2Store', Store)
    def rebuild(*_, **kwargs):
        progress.report('catalog_published', completed=2, total=2, unit='tables')
        return {'rows': 7}
    monkeypatch.setattr(raw_sync, 'rebuild_catalog', rebuild)
    monkeypatch.setenv('R2_ACCESS_KEY_ID', 'secret-id')
    monkeypatch.setenv('R2_SECRET_ACCESS_KEY', 'secret-key')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    summary = tmp_path / 'summary.json'
    raw_sync.main(['--rebuild-only', '--account-id', 'fixture', '--summary', str(summary)])
    assert configs[1].connect_timeout == 3 and configs[1].read_timeout == 5
    assert configs[1].retries['total_max_attempts'] == 1
    key, state = uploads[-1]
    assert key == 'status/raw-source-sync.json'
    assert state['github_run_id'] == '123' and state['github_run_attempt'] == '2'
    assert state['mode'] == 'rebuild' and state['status'] == 'completed'
    assert state['run_id'] == json.loads(summary.read_text())['run_id']
    assert state == json.loads(summary.with_suffix('.progress.json').read_text())
    assert 'secret' not in json.dumps(state)


def test_tracking_counts_completed_items_not_yielded_items(caplog):
    with caplog.at_level(logging.INFO, logger=progress.LOGGER.name):
        iterator = progress.track([1, 2, 3], 'read_receipts', unit='receipts', every=1)
        assert next(iterator) == 1
        assert caplog.records[-1].progress['completed'] == 0
        assert next(iterator) == 2
        assert caplog.records[-1].progress['completed'] == 1
        assert list(iterator) == [3]
    assert caplog.records[-1].progress == {
        'stage': 'read_receipts', 'completed': 3, 'total': 3, 'unit': 'receipts'}


def test_rebuild_reports_real_stages_and_preserves_output(tmp_path):
    from congress_api.retention.raw_archive import Archive
    from congress_api.retention.raw_catalog import rebuild_catalog
    from test_raw_catalog import initialize, table

    store = initialize(tmp_path)
    Archive(store, 'progress-fixture').save()
    before = table(store).to_pylist()
    stream = io.StringIO()
    with ProgressLog(tmp_path / 'progress.json', stream=stream, interval=3600):
        result = rebuild_catalog(store, workers=1)
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    stages = [event['stage'] for event in events]
    assert stages.index('load_indexes') < stages.index('extract_filenames')
    assert stages.index('inspect_document_contents') < stages.index('write_document_tables')
    assert stages.index('validate_document_tables') < stages.index('publish_documents')
    assert stages.index('publish_documents') < stages.index('publish_filenames')
    assert events[-1]['status'] == 'completed'
    assert events[-1]['completed'] == events[-1]['total'] == 2
    assert events[-1]['counters']['objects_read'] >= 3
    assert result['rows'] == len(before)
    assert table(store).to_pylist() == before


def test_progress_with_spawned_filename_workers_preserves_metadata(tmp_path):
    import pyarrow.parquet as pq
    from congress_api.retention import document_index as index

    rows = [dict(filename='Witness Statement.pdf', source_url='https://example.gov/statement.pdf', body_key=None)]
    results = []
    with ProgressLog(tmp_path / 'progress.json', stream=io.StringIO(), interval=3600):
        for workers in (1, 2):
            root = tmp_path / str(workers)
            (root / 'indexes').mkdir(parents=True)
            index.write_filename_metadata(root, rows, workers=workers)
            results.append(pq.read_table(root / 'indexes/document-filenames.parquet').to_pylist())
    assert results[0] == results[1]


def test_local_index_command_reports_progress_without_remote_publication(tmp_path, monkeypatch):
    import sys
    from congress_api.cli import document_index

    monkeypatch.setattr(sys, 'argv', ['document-filename-index', str(tmp_path), '--documents-only'])
    def reindex(_):
        progress.report('write_document_tables', completed=3, total=3, unit='rows')
        return {'rows': 3}
    monkeypatch.setattr(document_index, 'reindex_documents', reindex)
    document_index.main()
    status = json.loads((tmp_path / 'status/document-index.json').read_text())
    assert status['status'] == 'completed'
    assert status['completed'] == status['total'] == 3
