"""Bounded local scale comparison; never loads provider/runtime configuration.

Generate typed source files in bounded batches. Compare exact terminal values,
not independent native latest pointers. Empty native Updates intentionally select
a new operation while guarded Build no-op does not; report that distinction.
"""
import argparse
from collections import Counter
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.docspec import NativeDatasets, DocSpecFailure, native_storage_schema
from congress_api.retention.raw_archive import STATE_SCHEMA
from congress_api.retention.raw_storage import RawStorage, STATE_KEY_FIELD, STATE_ORDER
from process_rss import resident_tree

LIMITS = dict(compute_threads=2, memory_bytes=512 << 20, scratch_bytes=256 << 20,
              batch_rows=1024, max_batch_bytes=4 << 20, max_metadata_bytes=8 << 20)
SCHEMA = RawStorage(None, None, state_schema=STATE_SCHEMA.append(pa.field('exact', pa.struct([
    pa.field('number', pa.uint64()), pa.field('values', pa.list_(pa.binary()))])))).state_native_schema
PHYSICAL = native_storage_schema(SCHEMA)


def digest(path):
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def checked_arguments(args):
    rows = list(map(int, args.rows.split(',')))
    if not rows or any(not 2 <= count <= 1000000 for count in rows):
        raise ValueError('Generated row counts must be between 2 and 1000000')
    if not 1 <= args.rounds <= 3 or not 1 <= args.seconds <= 1800 or not 0 < args.max_bytes <= 4 << 30:
        raise ValueError('Experiment exceeds its declared repetition/time/byte bounds')
    if not set(args.cases.split(',')) <= {'append', 'correction', 'delete', 'empty'}:
        raise ValueError('Unknown change case')
    if not set(args.axes.split(',')) <= {'population', 'files', 'history'}:
        raise ValueError('Unknown measurement axis')
    return rows


def footprint(root):
    total = dict(files=0, bytes=0, temporary_files=0, temporary_bytes=0)
    for path in root.rglob('*'):
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except FileNotFoundError:
            # The native process may finish/remove a scratch file mid-sample.
            continue
        total['files'] += 1
        total['bytes'] += size
        if any(part == 'scratch' or part.startswith('request-') for part in path.relative_to(root).parts):
            total['temporary_files'] += 1
            total['temporary_bytes'] += size
    return total


class Budget:
    def __init__(self, output, seconds, max_bytes):
        self.output, self.deadline = output, time.monotonic() + seconds
        self.maximum, self.completed = max_bytes, 0
        self.current = output
        self.peak_bytes = self.peak_files = self.peak_rss = self.samples = 0
        self.peak_temporary_bytes = self.peak_temporary_files = 0
        self.minimum_free = None
        self.observation_seconds = 0.0
        self.last_sample = 0.0

    def sample(self, *, force=False):
        now = time.monotonic()
        if now >= self.deadline:
            raise RuntimeError('Declared experiment time bound reached')
        if not force and now - self.last_sample < 1:
            return
        self.last_sample = now
        start = time.perf_counter()
        current = footprint(self.current)
        self.peak_bytes = max(self.peak_bytes, current['bytes'])
        self.peak_files = max(self.peak_files, current['files'])
        self.peak_temporary_bytes = max(self.peak_temporary_bytes, current['temporary_bytes'])
        self.peak_temporary_files = max(self.peak_temporary_files, current['temporary_files'])
        self.peak_rss = max(self.peak_rss, resident_tree(os.getpid()))
        free = shutil.disk_usage(self.output).free
        self.minimum_free = free if self.minimum_free is None else min(self.minimum_free, free)
        self.samples += 1
        self.observation_seconds += time.perf_counter() - start
        if self.completed + current['bytes'] > self.maximum:
            raise RuntimeError('Declared retained fixture byte bound reached')
        if free < (8 << 30) + LIMITS['scratch_bytes']:
            raise RuntimeError('Declared free-space plus scratch floor reached')

    def stage(self, function):
        self.peak_bytes = self.peak_files = self.peak_rss = self.samples = 0
        self.peak_temporary_bytes = self.peak_temporary_files = 0
        self.minimum_free = None
        self.observation_seconds = 0.0
        self.sample(force=True)
        observer_before = self.observation_seconds
        start = time.perf_counter()
        result = function()
        seconds = time.perf_counter() - start
        during = self.observation_seconds - observer_before
        self.sample(force=True)
        return result, dict(seconds=seconds, samples=self.samples,
            sampled_process_tree_rss_peak_bytes=self.peak_rss,
            sampled_fixture_peak_bytes=self.peak_bytes, sampled_fixture_peak_files=self.peak_files,
            sampled_scratch_request_peak_bytes=self.peak_temporary_bytes,
            sampled_scratch_request_peak_files=self.peak_temporary_files,
            sampled_free_bytes_minimum=self.minimum_free,
            observation_seconds=self.observation_seconds,
            observation_seconds_during_interval=during)


class MeasuredNative(NativeDatasets):
    def __init__(self, binary, workspace, limits, budget):
        super().__init__(binary, workspace, limits=limits)
        self.counts, self.budget = Counter(), budget

    def _call(self, *args, remote=True):
        # Explicit local fixture subprocess; polling bounds the experiment and
        # drains both pipes. The maintained request/read/schema adapter is reused.
        self.budget.sample()
        command = [self.binary, '--workspace', str(self.workspace), '--limits', str(self.limits),
                   *map(str, args)]
        self.counts['cli_' + str(args[0])] += 1
        if args[0] == 'hash':
            self.counts['producer_hash_bytes'] += Path(args[1]).stat().st_size
        start = time.monotonic()
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
            try:
                while True:
                    try:
                        stdout, stderr = child.communicate(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        self.budget.sample()
                        if time.monotonic() - start > self.timeout:
                            raise TimeoutError('Native fixture command exceeded its original 120-second bound')
            except BaseException:
                child.kill()
                child.communicate()
                raise
        if child.returncode:
            raise DocSpecFailure(command, subprocess.CompletedProcess(command, child.returncode, stdout, stderr))
        if args[0] == 'read':
            self.counts['source_ipc_bytes_returned'] += Path(args[2]).stat().st_size
        return json.loads(stdout) if stdout.strip() else None


def row(ordinal, *, correction=False):
    digest = sha256(('generated-state:' + str(ordinal)).encode()).digest()
    url = None if ordinal == 0 else 'https://example.gov/generated/' + str(ordinal)
    result = dict.fromkeys(SCHEMA.names)
    result.update(_state_order=ordinal, _state_key='null:' if url is None else 'url:' + url,
        url=url, family='generated-only', body_key='bodies/' + digest.hex() + '.gz', sha256=digest.hex(),
        media_type='application/pdf', outcome='saved', attempts=ordinal % 5,
        links_scanned=bool(ordinal % 2), http_status=200,
        exact=dict(number=2**64 - 1 - ordinal, values=[None, b'', digest, digest]))
    if correction:
        result.update(attempts=99, exact=dict(number=2**64 - 1, values=[b'corrected', None, b'']))
    return result


def producer(path, count, case, budget):
    target = max(1, count // 2)
    maximum = count + (case == 'append')
    with pq.ParquetWriter(path, PHYSICAL, compression='zstd') as writer:
        for start in range(0, maximum, 1024):
            rows = [row(i, correction=case == 'correction' and i == target)
                    for i in range(start, min(maximum, start + 1024))
                    if not (case == 'delete' and i == target)]
            writer.write_table(pa.Table.from_pylist(rows, schema=SCHEMA).cast(PHYSICAL, safe=True))
            budget.sample()


def source_spec(native, path):
    return dict(path=str(path), digest=native.hash_input(path)['digest'])


def mutate(native, base, count, case, directory):
    target = max(1, count // 2)
    replacement = ([row(count)] if case == 'append' else
                   [row(target, correction=True)] if case == 'correction' else [])
    path = directory / 'replacements.parquet'
    pq.write_table(pa.Table.from_pylist(replacement, schema=SCHEMA).cast(PHYSICAL, safe=True), path,
                   compression='zstd')
    request = dict(dataset=base['dataset']['dataset'], operation='changed', definition='raw-native-v1',
                   base=base['id'], keys=[STATE_KEY_FIELD], replacements=source_spec(native, path))
    if case == 'delete':
        path = directory / 'deletions.parquet'
        pq.write_table(pa.table({STATE_KEY_FIELD: [row(target)[STATE_KEY_FIELD]]}), path, compression='zstd')
        request['deletions'] = source_spec(native, path)
    return native.update(request)


def prepare_history(native, base, steps, directory):
    source_pin = base['dataset']['groups']['source']
    for step in range(steps):
        empty = directory / 'history.parquet'
        pq.write_table(pa.Table.from_pylist([], schema=SCHEMA).cast(PHYSICAL), empty)
        base = native.update(dict(dataset='target', operation=f'history-{step}', definition='raw-native-v1',
            base=base['id'], keys=[STATE_KEY_FIELD], replacements=source_spec(native, empty)))
        assert base['dataset']['groups']['source'] == source_pin
    return base


def validate(native, pin, count, case):
    target, maximum = max(1, count // 2), count + (case == 'append')
    seen = bytearray(maximum)
    total = 0
    with native.source_batches(pin, schema=SCHEMA) as reader:
        assert reader.schema.equals(SCHEMA, check_metadata=False)
        for batch in reader:
            for actual in batch.to_pylist():
                ordinal = actual[STATE_ORDER]
                assert type(ordinal) is int and 0 <= ordinal < maximum and not seen[ordinal]
                assert not (case == 'delete' and ordinal == target)
                assert actual == row(ordinal, correction=case == 'correction' and ordinal == target)
                seen[ordinal] = 1
                total += 1
            native.budget.sample()
    assert total == maximum - (case == 'delete')
    return total


def registrations(native):
    path = native.workspace / 'catalog.sqlite'
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        return db.execute('SELECT COUNT(*) FROM iceberg_tables').fetchone()[0]


def metrics(native, pin):
    values = native._call('inspect', pin['dataset']['dataset'])
    phase = [value for key, value in values.items() if key.startswith('phase/')
             and value.get('phase') == 'processing' and value.get('operation') == pin['id']]
    assert len(phase) == 1
    return phase[0]['metrics']


def main(args):
    rows = checked_arguments(args)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(output, args.seconds, args.max_bytes)
    report = dict(version=1, status='running', limits=LIMITS, cases=[],
        binaries={name: dict(path=str(Path(path).resolve()), sha256=digest(path))
                  for name, path in [('baseline', args.baseline), ('candidate', args.candidate)]},
        scope='Generated local fixture only. Physical backend request/read-byte totals unavailable; native processing scans/writes and returned IPC bytes are separate counters.',
        operation_scope='Includes local CLI startup/hash/run or delta Parquet preparation/hash/update. Omits application old-leaf read; complete Build input preparation and independent readback are separately timed. Update does not prepare a complete input.',
        source_files_scope='Initial selected source files, proven unchanged throughout the history preparation axis.',
        observer_interval_seconds=1,
        stop_observation_scope='Fixture byte/free-space limits are sampled; a native call may overshoot between observations. Elapsed deadline is checked on each 100ms subprocess poll and generated batch.',
        temporary_observation_scope='Sampled native scratch and client request paths only; short-lived files between samples may be missed. Protected native attempt files remain retained, not scratch.',
        stop_bounds=dict(seconds=args.seconds, fixture_bytes=args.max_bytes, free_bytes=8 << 30),
        application_leaf_policy=dict(max_rows=8192, max_decoded_bytes=16 << 20))
    configurations = []
    for axis in args.axes.split(','):
        if axis == 'population':
            configurations.extend((axis, n, 0, 4 << 20, case)
                for n in rows for case in args.cases.split(','))
        elif axis == 'files':
            configurations.extend((axis, 100000, 0, size, case)
                for size in (4 << 20, 256 << 10) for case in ('append', 'correction', 'delete'))
        elif axis == 'history':
            configurations.extend((axis, 8192, history, 4 << 20, 'correction')
                for history in (0, 8, 32))
        else:
            raise ValueError('Unknown axis: ' + axis)
    try:
        for repeat in range(args.rounds):
            for number, (axis, count, history, file_bytes, case) in enumerate(configurations):
                arms = ['build', 'baseline-update', 'candidate-update']
                rotation = (repeat + number) % len(arms)
                arms = arms[rotation:] + arms[:rotation]
                for arm in arms:
                    report['active'] = dict(axis=axis, rows=count, history=history, case=case, arm=arm, repeat=repeat)
                    directory = output / f'{axis}-{count}-{history}-{file_bytes}-{case}-{repeat}-{arm}'
                    directory.mkdir()
                    budget.current = directory
                    workspace = directory / 'native'
                    workspace.mkdir()
                    limits = directory / 'limits.json'
                    limits.write_text(json.dumps({**LIMITS, 'max_batch_bytes': file_bytes,
                        'batch_rows': 128 if axis == 'files' else LIMITS['batch_rows']}))
                    native = MeasuredNative(args.candidate if arm == 'candidate-update' else args.baseline,
                                            workspace, limits, budget)
                    original = directory / 'original.parquet'
                    _, generation = budget.stage(lambda: producer(original, count, 'original', budget))
                    seed_input = source_spec(native, original)
                    base, seed = budget.stage(lambda: native.run(dict(dataset='target', operation='initial',
                        definition='raw-native-v1', input=seed_input['path'], expected_digest=seed_input['digest'],
                        sql='SELECT * FROM input')))
                    limits.write_text(json.dumps(LIMITS))
                    original_pin = base
                    source_pin = base['dataset']['groups']['source']
                    history_counters = native.counts.copy()
                    history_preparation = None
                    if history:
                        base, history_preparation = budget.stage(lambda: prepare_history(native, base, history, directory))
                    history_commands = dict(native.counts - history_counters)
                    original_objects = {obj['path']: digest(obj['path'])
                        for obj in source_pin['objects']}
                    full = directory / 'complete.parquet'
                    preparation = None
                    if arm == 'build' and case != 'empty':
                        _, preparation = budget.stage(lambda: producer(full, count, case, budget))
                    before = footprint(directory)
                    registered = registrations(native)
                    counters = native.counts.copy()
                    if arm == 'build':
                        def operation():
                            if case == 'empty':
                                return base
                            source = source_spec(native, full)
                            return native.run(dict(dataset='independent', operation='initial', definition='raw-native-v1',
                                input=source['path'], expected_digest=source['digest'], sql='SELECT * FROM input'))
                    else:
                        operation = lambda: mutate(native, base, count, case, directory)
                    result, timing = budget.stage(operation)
                    observed = dict(native.counts - counters)
                    after = footprint(directory)
                    processing = None if arm == 'build' and case == 'empty' else metrics(native, result)
                    new_tables = registrations(native) - registered
                    readback_counters = native.counts.copy()
                    _, readback = budget.stage(lambda: (validate(native, result, count, case),
                        validate(native, original_pin, count, 'original')))
                    readback_commands = dict(native.counts - readback_counters)
                    assert all(digest(path) == expected for path, expected in original_objects.items())
                    entry = dict(axis=axis, rows=count, history=history, seed_target_file_bytes=file_bytes,
                        repeat=repeat, arm=arm, case=case, fixture_generation=generation, seed=seed,
                        history_preparation=history_preparation, history_commands=history_commands,
                        complete_input_preparation=preparation, operation=timing, readback=readback,
                        commands=observed, readback_commands=readback_commands,
                        processing=processing, native_table_registrations=new_tables,
                        source_files=sum(obj['path'].endswith('.parquet') for obj in source_pin['objects']),
                        new_retained_files=after['files'] - before['files'],
                        new_retained_bytes=after['bytes'] - before['bytes'],
                        selection_advanced=result['id'] != base['id'] or result['dataset']['dataset'] != base['dataset']['dataset'],
                        exact_old_new_values_schema_and_ordinals=True,
                        old_source_object_hashes_unchanged=True,
                        key_metadata_files=len(list(workspace.glob('objects/*/*/keys/metadata/*.json'))))
                    report['cases'].append(entry)
                    budget.completed += footprint(directory)['bytes']
                    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        report['status'] = 'complete'
    except BaseException as error:
        report.update(status='stopped', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report['whole_experiment_seconds'] = time.monotonic() - (budget.deadline - args.seconds)
        (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--rows', default='1000,8192,10000,100000')
    parser.add_argument('--cases', default='append,correction,delete,empty')
    parser.add_argument('--axes', default='population,files,history')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--max-bytes', type=int, default=4 << 30)
    main(parser.parse_args())
