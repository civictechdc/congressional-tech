#!/usr/bin/env python3
"""Bounded offline DocSpec capability proof; this is not a production adapter.

Each call uses the maintained CLI in a fresh process. Requests and native outputs
remain beside the workspace so the proof can be reviewed without this script.
"""
import argparse
import base64
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time

import pyarrow as pa
import pyarrow.parquet as pq

HEADER = pa.struct([('name', pa.string()), ('value', pa.string())])
PROVENANCE = pa.struct([
    ('receipt_key', pa.string()), ('receipt_line', pa.int64()),
    ('receipt_json_pointer', pa.string()),
    ('acquisition_path', pa.string()), ('acquisition_sha256', pa.string()),
    ('retrieved_at', pa.string()), ('headers', pa.list_(HEADER)),
    ('member_path', pa.string()),
    ('acquisition_receipt_base64', pa.string()),
])
ROW_SCHEMA = pa.schema([
    ('record_key', pa.string()), ('body_sha256', pa.string()),
    ('body_bytes', pa.int64()), ('review', pa.string()),
    ('aliases', pa.list_(pa.string())), ('provenance', PROVENANCE),
])


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return path


def reference_rows(receipt_path):
    """Keep one real receipt's nested semantics plus labeled edge-case values."""
    raw = Path(receipt_path).read_bytes()
    receipt = json.loads(raw)
    digest = sha256(raw).hexdigest()
    package = receipt['package_id']
    acquisition = receipt['record']
    parent_key = package + '-zip'
    provenance = dict(
        receipt_key=f'audits/local-retention/20261019/sha256/{digest}/receipt.json',
        receipt_line=None, receipt_json_pointer='',
        acquisition_path=acquisition['local_body_path'].rsplit('/', 1)[0] + '/receipt.json',
        acquisition_sha256=digest, retrieved_at=acquisition['retrieved_at'],
        headers=acquisition['source_metadata']['response_header_items'], member_path=None,
        acquisition_receipt_base64=base64.b64encode(raw).decode())
    rows = [dict(record_key=parent_key, body_sha256=acquisition['body_sha256'],
                 body_bytes=int(acquisition['response_headers']['content-length']),
                 review=None, aliases=None, provenance=provenance)]
    for i, member in enumerate(receipt['members']):
        rows.append(dict(record_key=f'{package}-member-{i}', body_sha256=member['sha256'],
                         body_bytes=member['bytes'], review='', aliases=[] if i else [parent_key],
                         provenance={**deepcopy(provenance), 'member_path': member['name']}))
    # A second observation of the same member is distinct from body identity.
    rows.append({**deepcopy(rows[1]), 'record_key': package + '-duplicate-observation'})
    return rows


def change_example(rows):
    replacement = deepcopy(rows[1])
    replacement.update(review='corrected-local-proof', aliases=[rows[3]['record_key']])
    change = dict(transform_versions={'source': 'retained-package-v1', 'grouping': 'alias-v1'},
                  changed_record_keys=[rows[1]['record_key'], rows[2]['record_key']],
                  replacements=[replacement], deletions=[rows[2]['record_key']],
                  edges_before=[[rows[1]['record_key'], rows[0]['record_key']]],
                  edges_after=[[rows[1]['record_key'], rows[3]['record_key']]])
    # A stable native operation ID, within the CLI's ASCII/length restrictions.
    change['operation'] = 'change-' + sha256(json.dumps(change, sort_keys=True).encode()).hexdigest()
    return change


def expected_rows(rows, change):
    replaced = {r['record_key'] for r in change['replacements']}
    removed = replaced | set(change['deletions'])
    return [deepcopy(r) for r in rows if r['record_key'] not in removed] + deepcopy(change['replacements'])


def canonical(rows):
    return Counter(json.dumps(row, sort_keys=True) for row in rows)


def files(root):
    return {str(p.relative_to(root)): dict(bytes=p.stat().st_size, sha256=sha256(p.read_bytes()).hexdigest())
            for p in root.rglob('*') if p.is_file()}


def check_retained_package(receipt_path):
    """Bounded local byte verification; no storage mutation or new acquisition."""
    receipt = json.loads(Path(receipt_path).read_bytes())
    record = receipt['record']
    inputs = [(record['local_body_path'], record['body_sha256'])]
    inputs += [(member['path'], member['sha256']) for member in receipt['members']]
    checked = []
    for name, expected in inputs:
        path = Path(name)
        if path.stat().st_size > 8 << 20:
            raise ValueError(f'Proof source exceeds 8 MiB bound: {path}')
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError(f'Retained source byte mismatch: {path}')
        checked.append(dict(path=str(path), sha256=expected, bytes=len(raw)))
    return checked


class NativeProof:
    """Record finite proof commands; lifecycle decisions remain in DocSpec."""
    def __init__(self, binary, output, *, batch_bytes=4 << 20):
        self.binary, self.output = str(Path(binary).resolve()), Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.workspace = self.output / 'workspace'
        self.limits = write_json(self.output / 'limits.json', dict(
            compute_threads=2, memory_bytes=512 << 20, scratch_bytes=256 << 20,
            batch_rows=2, max_batch_bytes=batch_bytes, max_metadata_bytes=8 << 20))
        self.commands = []

    def call(self, label, *args, fails=False):
        command = [self.binary, '--workspace', str(self.workspace), '--limits', str(self.limits),
                   *map(str, args)]
        started = time.perf_counter()
        result = subprocess.run(command, capture_output=True, timeout=120)
        (self.output / f'{label}.stdout').write_bytes(result.stdout)
        (self.output / f'{label}.stderr').write_bytes(result.stderr)
        self.commands.append(dict(label=label, command=command, exit=result.returncode,
                                  elapsed_seconds=time.perf_counter() - started))
        write_json(self.output / 'commands.json', self.commands)
        if fails:
            if result.returncode == 0:
                raise AssertionError(f'{label}: expected refusal')
            return result.stderr.decode()
        if result.returncode:
            raise RuntimeError(f'{label}: {result.stderr.decode()}')
        return json.loads(result.stdout) if result.stdout.strip() else None

    def input(self, name, rows, schema=ROW_SCHEMA):
        path = self.output / f'{name}.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=2)
        identity = self.call(name + '-hash', 'hash', path)
        return dict(path=str(path), digest=identity['digest'])

    def read(self, label, release):
        pin = write_json(self.output / f'{label}-release.json', release)
        path = self.output / f'{label}.arrow'
        self.call(label + '-read', 'read-combined', pin, path)
        with path.open('rb') as stream:
            return pa.ipc.open_stream(stream).read_all().select(ROW_SCHEMA.names).to_pylist()


def qualify(binary, output, receipt_path, *, copies=1, batch_bytes=4 << 20, build_batch_bytes=None):
    native = NativeProof(binary, output, batch_bytes=batch_bytes)
    normal_limits = json.loads(native.limits.read_text())
    if build_batch_bytes:
        write_json(native.limits, {**normal_limits, 'max_batch_bytes': build_batch_bytes})
    retained = check_retained_package(receipt_path)
    rows = reference_rows(receipt_path)
    # Constructed unrelated copies test same-dataset cost growth, not new sources.
    rows += [{**deepcopy(row), 'record_key': f'unrelated-{i}-' + row['record_key']}
             for i in range(1, copies) for row in reference_rows(receipt_path)]
    change = change_example(rows)
    write_json(native.output / 'reference.json', rows)
    write_json(native.output / 'change-example.json', change)
    source = native.input('source', rows)
    build = dict(dataset='govinfo-package', operation='initial', definition='retained-package-v1',
                 input=source['path'], expected_digest=source['digest'], sql='SELECT * FROM input')
    build_path = write_json(native.output / 'build.json', build)
    before = native.call('build', 'run', build_path)
    assert canonical(native.read('before', before)) == canonical(rows)
    # An independent application partition uses the same native workspace.
    unrelated = {**build, 'dataset': 'unrelated-package'}
    unrelated_release = native.call('unrelated-build', 'run', write_json(native.output / 'unrelated.json', unrelated))
    unrelated_objects = {item['path']: sha256(Path(item['path']).read_bytes()).hexdigest()
                         for item in unrelated_release['dataset']['groups']['source']['objects']}
    # Build may deliberately create small native files; updates need room for
    # joined rows plus occurrence identity. The two named profiles stay explicit.
    write_json(native.output / 'build-limits.json', json.loads(native.limits.read_text()))
    write_json(native.limits, normal_limits)
    workspace_before_update = files(native.workspace)
    replacement = native.input('replacement', change['replacements'])
    deletion = native.input('deletion', [dict(record_key=k) for k in change['deletions']],
                            pa.schema([('record_key', pa.string())]))
    update = dict(dataset=build['dataset'], operation=change['operation'], definition=build['definition'],
                  base=before['id'], keys=['record_key'], replacements=replacement, deletions=deletion)
    update_path = write_json(native.output / 'update.json', update)
    native.call('update-plan', 'plan-update', update_path)
    after = native.call('update', 'update', update_path)
    assert canonical(native.read('after', after)) == canonical(expected_rows(rows, change))
    assert canonical(native.read('old-pin', before)) == canonical(rows)
    version = write_json(native.output / 'version.json', dict(
        dataset=build['dataset'], version=after['id'], manifest=after['manifest']))
    certificate = native.call('changes', 'inspect-changes', version)
    inspection = native.call('inspection', 'inspect', build['dataset'])
    workspace_after_update = files(native.workspace)
    assert all(sha256(Path(path).read_bytes()).hexdigest() == digest
               for path, digest in unrelated_objects.items())
    # Completed retry has no producer inputs. Every CLI invocation is a restart.
    for item in [source, replacement, deletion]:
        Path(item['path']).rename(Path(item['path']).with_suffix('.unavailable'))
    old_files = files(native.workspace)
    retry = native.call('restart-retry', 'update', update_path)
    assert retry == after
    plan = native.call('completed-plan', 'plan-update', update_path)
    assert plan['completed'] is True
    assert native.call('inspection-after-retry', 'inspect', build['dataset']) == inspection
    new_files = files(native.workspace)
    assert new_files == old_files, 'Completed retry changed retained workspace files'
    stale = {**update, 'operation': 'stale-base'}
    stale_error = native.call('stale-base', 'update', write_json(native.output / 'stale.json', stale), fails=True)
    conflict = {**update, 'definition': 'conflicting-definition'}
    conflict_error = native.call('conflicting-request', 'update',
                                 write_json(native.output / 'conflict.json', conflict), fails=True)
    assert 'stale_base:' in stale_error
    assert 'operation_conflict:' in conflict_error
    processing = [value for key, value in inspection.items() if key.startswith('phase/') and key.endswith('/processing')]
    source_changes = certificate['changes']['source']
    assert source_changes['before_metadata'] == before['dataset']['groups']['source']['metadata']
    assert source_changes['after_metadata'] == after['dataset']['groups']['source']['metadata']
    assert source_changes['added']['rows'] == 1 and source_changes['removed']['rows'] == 2
    added = {key: value for key, value in workspace_after_update.items() if key not in workspace_before_update}
    summary = dict(copies=copies, source_rows=len(rows), changed_record_keys=change['changed_record_keys'],
                   exact_base=before['id'], selected_version=after['id'],
                   exhaustive_value_parity=True, original_pin_preserved=True,
                   restart_completed_reuse=True, unchanged_workspace_files=True,
                   stale_refusal=stale_error, conflicting_request_refusal=conflict_error,
                   processing=processing, certificate=certificate,
                   retained_local_body_checks=retained,
                   exact_acquisition_receipt_roundtrip=True,
                   unrelated_dataset_objects_unchanged=True,
                   update_created_files=len(added), update_created_bytes=sum(x['bytes'] for x in added.values()),
                   workspace_files=len(new_files), workspace_bytes=sum(x['bytes'] for x in new_files.values()),
                   native_binary_sha256=sha256(Path(binary).read_bytes()).hexdigest())
    write_json(native.output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=Path(__file__).parents[1] /
                        'tests/fixtures/incremental-boundary/acquisition-receipt.json')
    parser.add_argument('--copies', type=int, default=1)
    parser.add_argument('--batch-bytes', type=int, default=4 << 20)
    parser.add_argument('--build-batch-bytes', type=int)
    args = parser.parse_args()
    if not 1 <= args.copies <= 10:
        parser.error('--copies must be 1 through 10')
    result = qualify(args.binary, args.output, args.receipt, copies=args.copies,
                     batch_bytes=args.batch_bytes, build_batch_bytes=args.build_batch_bytes)
    print(json.dumps({k: result[k] for k in ('source_rows', 'selected_version', 'restart_completed_reuse')}))


if __name__ == '__main__':
    main()
