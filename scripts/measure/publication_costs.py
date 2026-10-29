"""Bounded fixture telemetry; never supplies publication authority.

Wraps observable Python boundaries. Native Arrow I/O bytes are not inferred from
compressed input sizes. Named hash bytes exclude hashes performed inside native
libraries and hashlib.sha256.update; request bytes count full mock-store bodies.
"""
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from process_rss import resident_tree


class PublicationCosts:
    def __init__(self, scratch):
        self.scratch = Path(scratch)
        self.counts = Counter()
        self.stages = []
        self._stop = threading.Event()
        self.peak = 0
        self.samples = 0
        self.errors = []
        self.count_lock = threading.Lock()

    def add(self, values):
        with self.count_lock:
            self.counts.update(values)

    @contextmanager
    def request(self, method, key):
        category = ('journal' if key.startswith('viewer-publications/attempts/') else
                    'payload' if key.startswith('viewer-publications/releases/') else 'control')
        prefix = category + '_' + method
        started = time.perf_counter()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            self.add({prefix + '_requests': 1, prefix + '_seconds': time.perf_counter() - started,
                      prefix + '_failures': int(failed)})

    def sample(self):
        try:
            self.peak = max(self.peak, resident_tree(os.getpid()))
            self.samples += 1
        except Exception as error:
            self.errors.append(type(error).__name__)

    def sampler(self):
        while not self._stop.wait(.05):
            self.sample()

    @contextmanager
    def stage(self, name):
        before = self.counts.copy()
        started = time.perf_counter()
        self.peak = 0; self.samples = 0; self.sample()
        thread = threading.Thread(target=self.sampler, daemon=True); thread.start()
        status = 'complete'
        try:
            yield
        except BaseException:
            status = 'failed'
            raise
        finally:
            self._stop.set(); thread.join(); self._stop.clear()
            self.sample()
            self.stages.append({'stage': name, 'status': status, 'seconds': time.perf_counter() - started,
                'sampled_process_tree_rss_peak_bytes': self.peak, 'memory_samples': self.samples,
                'scratch_bytes': sum(p.stat().st_size for p in self.scratch.rglob('*') if p.is_file()),
                'counts': dict(self.counts - before)})

    @contextmanager
    def instrument(self):
        import pyarrow.parquet as pq
        from viewer_publication.continuation import DurableJournal
        old_record, old_restore = DurableJournal.record, DurableJournal.restore
        metrics = self
        def record(journal, event, value):
            started = time.perf_counter()
            with journal.lock:
                acquired = time.perf_counter()
                try:
                    return old_record(journal, event, value)
                finally:
                    metrics.add({"journal_record_calls": 1,
                        "journal_lock_wait_seconds": acquired - started,
                        "journal_lock_held_seconds": time.perf_counter() - acquired})
        def restore(journal):
            started = time.perf_counter()
            try:
                return old_restore(journal)
            finally:
                metrics.add({"journal_restore_calls": 1,
                             "journal_restore_seconds": time.perf_counter() - started})
        old_file_digest, old_parquet, old_connect = hashlib.file_digest, pq.ParquetFile, sqlite3.connect
        old_fsync, old_dump, old_dumps = os.fsync, json.dump, json.dumps
        counts = self.counts
        def file_digest(stream, *args, **kwargs):
            start = stream.tell()
            try:
                return old_file_digest(stream, *args, **kwargs)
            finally:
                counts['hash_helper_bytes'] += stream.tell() - start
                counts['hash_helper_passes'] += 1
        def fsync(*args, **kwargs):
            started = time.perf_counter()
            try:
                return old_fsync(*args, **kwargs)
            finally:
                counts['fsync_calls'] += 1
                counts['fsync_seconds'] += time.perf_counter() - started
        def dump(value, stream, *args, **kwargs):
            started, before = time.perf_counter(), stream.tell()
            try:
                return old_dump(value, stream, *args, **kwargs)
            finally:
                counts['state_json_dump_calls'] += 1
                counts['state_json_serialized_characters'] += stream.tell() - before
                counts['state_json_serialization_seconds'] += time.perf_counter() - started
        def dumps(value, *args, **kwargs):
            started = time.perf_counter()
            result = old_dumps(value, *args, **kwargs)
            counts['json_dumps_calls'] += 1
            counts['json_serialized_characters'] += len(result)
            counts['json_serialization_seconds'] += time.perf_counter() - started
            if isinstance(value, dict) and {'binding', 'phases', 'writes', 'versions'} <= value.keys():
                counts['state_json_dump_calls'] += 1
                counts['state_json_serialized_characters'] += len(result)
                counts['state_json_serialization_seconds'] += time.perf_counter() - started
            return result
        class CountedParquet(old_parquet):
            def iter_batches(self, *args, **kwargs):
                counts['decode_iterator_passes'] += 1
                for batch in super().iter_batches(*args, **kwargs):
                    counts['decoded_batches'] += 1
                    counts['decoded_rows'] += batch.num_rows
                    counts['largest_decoded_batch_bytes'] = max(counts['largest_decoded_batch_bytes'], batch.nbytes)
                    yield batch
            def read(self, *args, **kwargs):
                counts['decode_read_passes'] += 1
                return super().read(*args, **kwargs)
            def read_row_group(self, *args, **kwargs):
                counts['decode_row_group_passes'] += 1
                return super().read_row_group(*args, **kwargs)
        class CountedConnection(sqlite3.Connection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.set_trace_callback(lambda query: counts.update({'sqlite_selects': 1}) if query.lstrip().upper().startswith('SELECT') else None)
        def connect(*args, **kwargs):
            kwargs.setdefault('factory', CountedConnection)
            return old_connect(*args, **kwargs)
        hashlib.file_digest, pq.ParquetFile, sqlite3.connect = file_digest, CountedParquet, connect
        os.fsync, json.dump, json.dumps = fsync, dump, dumps
        DurableJournal.record, DurableJournal.restore = record, restore
        try:
            yield self
        finally:
            hashlib.file_digest, pq.ParquetFile, sqlite3.connect = old_file_digest, old_parquet, old_connect
            os.fsync, json.dump, json.dumps = old_fsync, old_dump, old_dumps
            DurableJournal.record, DurableJournal.restore = old_record, old_restore

    def save(self, path, *, inputs, outcomes):
        Path(path).write_text(json.dumps({'version': 1, 'scope': 'small generated fixture and in-memory remote only',
            'inputs': inputs, 'outcomes': outcomes, 'stages': self.stages, 'sampling_errors': self.errors,
            'limits': {'memory_sample_interval_seconds': .05, 'remote_network': False,
                'excluded': 'interpreter/import startup, GitHub artifact API, public HTTP, actual GitHub Actions setup/downloads; native Arrow I/O bytes and internal hashes',
                'full_linux_oom_stage': 'unknown; no retry or resource change'}}, indent=2) + '\n')
