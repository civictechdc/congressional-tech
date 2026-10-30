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



def test_running_heartbeat_has_expiry_and_memory_measurement(tmp_path):
    from datetime import datetime
    path = tmp_path / 'progress.json'
    with ProgressLog(path, stream=io.StringIO(), interval=3600):
        state = json.loads(path.read_text())
        assert datetime.fromisoformat(state['heartbeat_expires_at']) > datetime.fromisoformat(state['updated_at'])
        assert state['memory']['process_peak_bytes'] > 0
    assert json.loads(path.read_text())['heartbeat_expires_at'] is None
