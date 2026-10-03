"""Flush live progress to stderr, a local sidecar and an optional status writer."""
from datetime import datetime, timezone
import json
import logging
import os
import sys
import threading
import time

from congress_api.retention.raw_progress import LOGGER


class ProgressLog(logging.Handler):
    def __init__(self, path, *, stream=None, clock=time.monotonic, interval=30):
        super().__init__()
        self.path, self.stream, self.clock = path, stream or sys.stderr, clock
        self.interval = interval
        self.started = self.stage_started = self.changed = clock()
        self.last_written = self.started
        self.state = {'status': 'running', 'stage': 'starting', 'counters': {}}
        if os.environ.get('GITHUB_RUN_ID'):
            self.state['github_run_id'] = os.environ['GITHUB_RUN_ID']
            self.state['github_run_attempt'] = os.environ.get('GITHUB_RUN_ATTEMPT')
            self.state['code_revision'] = os.environ.get('GITHUB_SHA')
        self.publish = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def __enter__(self):
        self.old_level = LOGGER.level
        LOGGER.setLevel(logging.INFO)
        LOGGER.addHandler(self)
        self._write()
        self.thread.start()
        return self

    def emit(self, record):
        now = self.clock()
        if hasattr(record, 'counter'):
            metric, amount = record.counter
            self.state['counters'][metric] = self.state['counters'].get(metric, 0) + amount
            self.changed = now
        elif hasattr(record, 'progress'):
            event = record.progress
            new_stage = event['stage'] != self.state['stage']
            if new_stage:
                self.stage_started = now
            self.state.update(event)
            self.changed = now
            finished = event['total'] is not None and event['completed'] == event['total']
            if new_stage or finished or now - self.last_written >= self.interval:
                self._write()

    def _write(self):
        # Handler.handle holds this same reentrant lock during emit.
        with self.lock:
            now = self.clock()
            state = {**self.state,
                     'updated_at': datetime.now(timezone.utc).isoformat(),
                     'elapsed_seconds': round(now - self.started, 1),
                     'stage_elapsed_seconds': round(now - self.stage_started, 1),
                     'seconds_since_progress': round(now - self.changed, 1)}
            payload = (json.dumps(state, sort_keys=True) + '\n').encode()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + '.tmp')
            temporary.write_bytes(payload)
            temporary.replace(self.path)
            self.stream.write(payload.decode())
            self.stream.flush()
            self.last_written = now
            return payload

    def _publish(self, payload):
        if self.publish:
            try:
                self.publish(payload)
            except Exception as error:
                # A status-upload outage must not fail or expose details of data work.
                self.stream.write(json.dumps({'event': 'status_upload_failed',
                                              'error_type': type(error).__name__}) + '\n')
                self.stream.flush()

    def heartbeat(self):
        self._publish(self._write())

    def _watch(self):
        while not self.stop.wait(self.interval):
            self.heartbeat()
        # One writer publishes the terminal state after any in-flight heartbeat.
        self._publish(self._write())

    def __exit__(self, kind, error, traceback):
        with self.lock:
            self.state['status'] = 'failed' if kind else 'completed'
            if kind:
                self.state['error_type'] = kind.__name__
            self._write()
        self.stop.set()
        self.thread.join(timeout=20)
        LOGGER.removeHandler(self)
        LOGGER.setLevel(self.old_level)
        self.close()
