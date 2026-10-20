"""Compare bounded raw-state leaf Build and native Update using local fixtures.

This is an experiment, not a second raw-storage implementation. The public raw
writer has no deletion operation; deletion is checked at the native leaf boundary.
All clients use explicit local paths and never load runtime configuration.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention.docspec import DocSpecFailure, NativeDatasets, native_storage_schema
from congress_api.retention.raw_archive import STATE_SCHEMA
from congress_api.retention.raw_storage import RawStorage, STATE_KEY_FIELD, STATE_ORDER


class ObservedNative(NativeDatasets):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.counts = Counter()

    def _call(self, *args, **kwargs):
        self.counts['cli_' + str(args[0])] += 1
        if args[0] == 'hash':
            self.counts['producer_hash_bytes'] += Path(args[1]).stat().st_size
        result = super()._call(*args, **kwargs)
        if args[0] == 'read':
            self.counts['source_ipc_bytes_returned'] += Path(args[2]).stat().st_size
        return result


def inventory(root):
    return {str(path.relative_to(root)): (path.stat().st_size, sha256(path.read_bytes()).hexdigest())
            for path in root.rglob('*') if path.is_file()}


def table(schema, count=16):
    rows = [dict(_state_order=i, _state_key='url:' + str(i), url=str(i),
                 attempts=i, outcome='saved', links_scanned=bool(i % 2),
                 exact=dict(number=2**64 - 1 - i, values=[None, b'', b'exact', b'exact']))
            for i in range(count)]
    rows[0]['url'] = None
    rows[0]['_state_key'] = 'null:'
    return pa.Table.from_pylist(rows, schema=schema)


def read(native, pin, schema):
    with native.source_batches(pin, schema=schema) as reader:
        result = reader.read_all()
    return result.take(pc.sort_indices(result[STATE_ORDER])).cast(schema)


def update(native, base, before, after, operation):
    """Pass only complete changed rows and removed keys to existing Update."""
    previous = {row[STATE_KEY_FIELD]: row for row in before.to_pylist()}
    current = {row[STATE_KEY_FIELD]: row for row in after.to_pylist()}
    replacements = pa.Table.from_pylist([row for key, row in current.items()
        if previous.get(key) != row], schema=after.schema)
    deletions = pa.table({STATE_KEY_FIELD: pa.array(sorted(previous.keys() - current.keys()), type=pa.string())})
    with native._scratch() as scratch:
        def source(name, values):
            path = scratch / (name + '.parquet')
            pq.write_table(values.cast(native_storage_schema(values.schema), safe=True), path, compression='zstd')
            return dict(path=str(path), digest=native.hash_input(path)['digest'])
        request = dict(dataset=base['dataset']['dataset'], operation=operation,
            definition='raw-native-v1', base=base['id'], keys=[STATE_KEY_FIELD],
            replacements=source('replacements', replacements))
        if len(deletions):
            request['deletions'] = source('deletions', deletions)
        result = native.update(request)
        return result, request


def processing(native, pin):
    inspected = native._call('inspect', pin['dataset']['dataset'])
    phases = [value for key, value in inspected.items() if key.startswith('phase/')
              and value.get('phase') == 'processing' and value.get('operation') == pin['id']]
    assert len(phases) == 1
    return phases[0]['metrics']


def changed(before, case):
    rows = before.to_pylist()
    if case == 'append':
        rows.append(dict(rows[-1], _state_order=len(rows), _state_key='url:new', url='new'))
    elif case == 'correction':
        rows[3] = dict(rows[3], attempts=99, exact=dict(number=2**64 - 1, values=[b'corrected', None, b'']))
    elif case == 'delete':
        rows.pop(3)
    return pa.Table.from_pylist(rows, schema=before.schema)


def run(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    schema = STATE_SCHEMA.append(pa.field('exact', pa.struct([
        pa.field('number', pa.uint64()), pa.field('values', pa.list_(pa.binary()))])))
    # Reuse the actual application's native state schema and Build candidate path.
    schema = RawStorage(None, None, state_schema=schema).state_native_schema
    report = dict(version=1, binary=str(Path(args.binary).resolve()), rounds=args.rounds,
        changed_leaf_rows=16, unrelated_leaf_rows=16, cases=[], checks={},
        measurement_scope='Local CLI wall time and command counts; native processing metrics; returned Arrow IPC bytes and producer hash bytes. No physical disk/network read-byte counter is exposed.',
        deletion_scope='Complete native state-leaf replacement only; RawStorage.prepare supports state upserts and capture append, not state/capture deletion.')
    for scale in (1, 10):
        for arm in ('build', 'update'):
            workspace = output / f'{scale}x-{arm}'
            workspace.mkdir()
            limits = workspace / 'limits.json'
            limits.write_text(json.dumps(dict(compute_threads=2, memory_bytes=512 << 20,
                scratch_bytes=256 << 20, batch_rows=2, max_batch_bytes=4 << 20,
                max_metadata_bytes=8 << 20)))
            native = ObservedNative(args.binary, workspace, limits=limits)
            unrelated = [native.run_table(table(schema), dataset=f'unrelated-{i}',
                operation='initial', definition='raw-native-v1') for i in range(scale)]
            unrelated_objects = {obj['path']: sha256(Path(obj['path']).read_bytes()).hexdigest()
                for pin in unrelated for obj in pin['dataset']['groups']['source']['objects']}
            owner = RawStorage(None, native)
            for repeat in range(args.rounds):
                # Reverse alternating case order to reduce systematic warm-up bias.
                cases = ['append', 'correction', 'delete', 'noop']
                if repeat % 2:
                    cases.reverse()
                for case in cases:
                    before = table(schema)
                    base = native.run_table(before, dataset=f'target-{repeat}-{case}',
                        operation='initial', definition='raw-native-v1')
                    original_objects = {obj['path']: sha256(Path(obj['path']).read_bytes()).hexdigest()
                        for obj in base['dataset']['groups']['source']['objects']}
                    start_files = inventory(workspace)
                    counts = native.counts.copy()
                    started = time.perf_counter()
                    loaded = read(native, base, schema)
                    after = changed(loaded, case)
                    if loaded.equals(after):
                        result, request = base, None
                    elif arm == 'build':
                        result = owner._candidate('state', after, operation=f'{repeat}-{case}',
                            prefix='', base_id=base['id'])
                        request = None
                    else:
                        result, request = update(native, base, loaded, after, 'changed')
                    seconds = time.perf_counter() - started
                    observed = dict(native.counts - counts)
                    after_files = inventory(workspace)
                    added = set(after_files) - set(start_files)
                    metrics = processing(native, result) if case != 'noop' else None
                    assert read(native, result, schema).equals(after)
                    assert read(native, base, schema).equals(before)
                    assert all(sha256(Path(path).read_bytes()).hexdigest() == digest
                               for path, digest in {**original_objects, **unrelated_objects}.items())
                    checks = dict(exact_result=True, old_pin_readable=True, old_objects_unchanged=True,
                                  unrelated_objects_unchanged=True)
                    if case == 'noop':
                        assert start_files == after_files
                        assert observed.get('cli_read') == 1 and not observed.get('cli_update') and not observed.get('cli_run')
                        checks['zero_writes'] = True
                    if request:
                        retry_before = inventory(workspace)
                        # Original producers have disappeared with the request scratch directory.
                        assert native.update(request) == result
                        assert inventory(workspace) == retry_before
                        checks['completed_replay_without_inputs_zero_writes'] = True
                        try:
                            native.update({**request, 'operation': 'competing'})
                        except DocSpecFailure as error:
                            assert 'stale_base' in str(error)
                            checks['unselected_native_candidate_blocks_old_base'] = True
                        else:
                            raise AssertionError('Old selected base unexpectedly accepted')
                    entry = dict(scale=scale, arm=arm, repeat=repeat, case=case, seconds=seconds,
                        commands=observed, processing=metrics,
                        new_retained_files=len(added), new_retained_bytes=sum(after_files[key][0] for key in added),
                        checks=checks)
                    report['cases'].append(entry)
                    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
            assert all(read(native, pin, schema).equals(table(schema)) for pin in unrelated)
    report['checks'] = dict(all_cases_passed=True, schema_types_restored=True,
        nested_duplicates_null_empty_binary_and_max_uint64_preserved=True,
        native_stale_base_refused=True, production_configuration_loaded=False,
        provider_calls=False)
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--rounds', type=int, default=3)
    run(parser.parse_args())
