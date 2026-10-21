"""Local fixed-change raw -> catalog -> viewer publication growth diagnostic.

Uses maintained computation/publication owners and existing fixture transports.
No provider client, source fetcher, held-out corpus, or production write exists.
"""
import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
import gzip
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import tracemalloc
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / p) for p in ('tests', 'apps/site/scripts', 'packages/congress_api/src',
                                      'packages/viewer_publication/src', 'packages/viewer_publication/tests', 'scripts', 'scripts/measure')]
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError
from native_memory_helpers import MemoryNative
from test_viewer_publication_attempt import Remote as FixtureRemote
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, STATE_SCHEMA
from congress_api.retention.raw_catalog import update_from_raw
from congress_api.retention.raw_storage import RawStorage
from congress_api.retention.derived_files import file_identity
from congress_api.retention.viewer_inventory import issue_inventory
from viewer_publication.native import prepare_native_output
from viewer_publication.filename_native import ViewerAssets, public_component


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load('e2e_publisher', 'scripts/publication/publish-viewer-r2.py')
builder = load('e2e_builder', 'scripts/publication/publish-filename-viewer.py')
fixture_builder = SimpleNamespace(publish_selected=partial(builder.publish_selected, review_identities=None))
ABSENT = (None, None, None, None)


class CountedStore(LocalStore):
    def __init__(self, root):
        super().__init__(root)
        self.counts = Counter()

    def read(self, key):
        value = super().read(key)
        self.counts['read_calls'] += 1
        self.counts['read_bytes'] += len(value or b'')
        return value

    def put(self, key, value, **options):
        self.counts['put_calls'] += 1
        self.counts['put_bytes'] += len(value)
        return super().put(key, value, **options)

    def version(self, key):
        path = self.root / key
        self.counts['version_calls'] += 1
        self.counts['version_file_bytes'] += path.stat().st_size if path.is_file() else 0
        return super().version(key)

    def keys(self, prefix, **options):
        self.counts['list_calls'] += 1
        for key in super().keys(prefix, **options):
            self.counts['listed_keys'] += 1
            yield key


class CountedNative(MemoryNative):
    def __init__(self):
        super().__init__()
        self.counts, self.events = Counter(), []

    def run_table(self, table, **request):
        self.counts['run_calls'] += 1
        self.counts['submitted_rows'] += len(table)
        self.counts['submitted_arrow_bytes'] += table.nbytes
        self.counts['unique_created_runs'] += request['dataset'] not in self.tables
        self.events.append(dict(kind='run', dataset=request['dataset'], rows=len(table), arrow_bytes=table.nbytes))
        return super().run_table(table, **request)

    @contextmanager
    def source_batches(self, pin, *, schema=None):
        key = pin['dataset']['dataset']
        table = self.tables[key]
        self.counts['read_calls'] += 1
        self.counts['read_rows'] += len(table)
        self.counts['read_arrow_bytes'] += table.nbytes
        self.events.append(dict(kind='read', dataset=key, rows=len(table), arrow_bytes=table.nbytes))
        with super().source_batches(pin, schema=schema) as reader:
            yield reader


class LocalRemote(FixtureRemote):
    """Existing conditional publication fixture, reading current local source keys."""
    def __init__(self, store, empty):
        empty.mkdir()
        super().__init__(empty)
        self.store, self.counts = store, Counter()

    def get_object(self, *, Bucket, Key):
        self.counts['get_calls'] += 1
        if Key in self.objects:
            result = super().get_object(Bucket=Bucket, Key=Key)
        else:
            raw = self.store.read(Key)
            if raw is None:
                raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
            result = dict(Body=io.BytesIO(raw), ContentLength=len(raw), ETag=sha256(raw).hexdigest(),
                          LastModified=datetime(2026, 10, 20, tzinfo=timezone.utc))
        self.counts['get_bytes'] += result['ContentLength']
        return result

    def put_object(self, **options):
        body = options['Body']
        size = len(body) if isinstance(body, bytes) else options['ContentLength']
        self.counts['put_calls'] += 1
        self.counts['put_bytes'] += size
        return super().put_object(**options)

    def download_file(self, bucket, key, destination):
        self.counts['download_calls'] += 1
        self.counts['download_bytes'] += len(self.objects[key])
        return super().download_file(bucket, key, destination)


class Phases:
    def __init__(self, store, native, remote):
        self.store, self.native, self.remote = store, native, remote
        self.rows = []

    @contextmanager
    def phase(self, name):
        starts = [owner.counts.copy() for owner in (self.store, self.native, self.remote)]
        event = len(self.native.events)
        current, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        started = time.perf_counter()
        status = 'completed'
        try:
            yield
        except BaseException:
            status = 'failed'
            raise
        finally:
            final, peak = tracemalloc.get_traced_memory()
            self.rows.append(dict(phase=name, status=status, seconds=time.perf_counter() - started,
                python_current_start_bytes=current, python_current_end_bytes=final,
                python_traced_peak_bytes=peak, python_additional_peak_bytes=max(0, peak - current),
                store=dict(self.store.counts - starts[0]), native=dict(self.native.counts - starts[1]),
                viewer_remote=dict(self.remote.counts - starts[2]), native_events=self.native.events[event:]))


def capture(store, event, name):
    url = f'https://fixture.example.gov/{name}.pdf'
    key = f'receipts/congress/meetings/{name}.jsonl.gz'
    record = dict(eventId=event, congress=119, chamber='House', meetingDocuments=[dict(
        url=url, documentType='Statement', name='Exact publisher ' + name)])
    store.put(key, gzip.compress((json.dumps(dict(record=record)) + '\n').encode(), mtime=0), immutable=True)
    return dict(family='congress/meetings', source_file=name + '.json', receipt_key=key,
                receipt_line=1, pointer_json='[]'), dict(url=url, outcome='pending', attempts=0,
                    checked_at='2026-10-19T00:00:00Z')


def tables(snapshot):
    return {label: pa.Table.from_batches(list(snapshot.table(label, max_ordered_bytes=16 << 20).iter_batches())).to_pylist()
            for label in ('filenames', 'documents')}


def by_id(values, label):
    return {row['source_id' if label == 'filenames' else 'document_id']: row for row in values}


def immutable_hashes(remote):
    return {key: sha256(raw).hexdigest() for key, raw in remote.objects.items()
            if key != publisher.PREFIX + 'manifest.json'}


def component_records(remote, manifest, ids, scratch):
    assets = ViewerAssets(scratch, read_asset=lambda path: remote.objects[publisher.PREFIX + path])
    return {identity: public_component(assets, manifest['roots']['components'], identity) for identity in ids}


def prepare_viewer(store, native, remote, target):
    accepted = publisher.read_identity(remote, publisher.ACCEPTED_KEY, optional=True)
    previous = publisher.read_identity(remote, publisher.PREFIX + 'manifest.json', optional=True)
    with read_catalog(store, native=native) as snapshot:
        manifest, recovery = prepare_native_output(publisher, fixture_builder, remote, snapshot, target,
            accepted_record=accepted, viewer_record=previous)
    proof = issue_inventory(target, manifest.identities, context={})
    publisher.prepare_recovery(target, manifest, accepted, validation=proof, index=recovery)
    identities = dict(manifest.identities)
    identities['recovery-prepared.json'] = file_identity(target / 'recovery-prepared.json')
    return manifest, issue_inventory(target, identities, context={}), previous[1]


def publish_viewer(remote, target, manifest, proof, previous_etag):
    selected_etag = publisher.read_identity(remote, 'indexes/catalog.json')[1]
    result = publisher.upload(remote, target, manifest, previous_etag=previous_etag,
        selected_etag=selected_etag, validation=proof, probe=lambda *args: None)
    assert result['status'] == 'published'
    return result


def run_case(unrelated, output):
    output.mkdir(parents=True, exist_ok=False)
    store, native = CountedStore(output / 'objects'), CountedNative()
    remote = LocalRemote(store, output / 'empty')
    phases = Phases(store, native, remote)
    class Public(io.BytesIO):
        headers = {'Access-Control-Allow-Origin': '*'}
    publisher.open_public = lambda request, **kwargs: Public(
        remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)])
    tracemalloc.start()
    results, checks = {}, {}
    try:
        with phases.phase('setup_raw'):
            initial = [capture(store, 100 + i, f'unrelated-{i:04}') for i in range(unrelated)]
            initial.append(capture(store, 7, 'target'))
            owner = RawStorage(store, native)
            old_raw = owner.publish(owner.prepare(owner.snapshot(), operation='initial',
                captures=pa.Table.from_pylist([row for row, _ in initial], schema=CAPTURE_SCHEMA),
                states=pa.Table.from_pylist([row for _, row in initial], schema=STATE_SCHEMA), qualify_readings=True))
        with phases.phase('setup_catalog'):
            update_from_raw(store, raw_storage=RawStorage.open(store, native), directory=output / 'initial-catalog', candidate='initial')
        with phases.phase('setup_viewer_preparation'):
            manifest, proof, etag = prepare_viewer(store, native, remote, output / 'initial-viewer')
        with phases.phase('setup_viewer_publication'):
            publish_viewer(remote, output / 'initial-viewer', manifest, proof, etag)
        old_catalog = read_catalog(store, native=native)
        baseline = tables(old_catalog)
        unrelated_ids = [row['source_id'] for row in baseline['filenames'] if '/unrelated-' in row['source_url']]
        unrelated_documents = [row['document_id'] for row in baseline['filenames'] if row['source_id'] in unrelated_ids]
        immutable_before = immutable_hashes(remote)
        component_before = component_records(remote, manifest, unrelated_documents, output / 'read-public')
        old_state = old_raw.states().to_pylist()
        old_capture = old_raw.captures().to_pylist()
        expected_states, expected_captures = deepcopy(old_state), deepcopy(old_capture)
        (output / 'initial-raw-selection.json').write_text(json.dumps(old_raw.manifest, indent=2) + '\n')
        (output / 'initial-catalog-selection.json').write_text(json.dumps(old_catalog.selection, indent=2) + '\n')
        for change in ('append', 'correction'):
            with phases.phase(change + '_raw'):
                owner = RawStorage.open(store, native)
                if change == 'append':
                    row, state = capture(store, 99999, 'appended')
                    state_input = pa.Table.from_pylist([state], schema=STATE_SCHEMA)
                    capture_input = pa.Table.from_pylist([row], schema=CAPTURE_SCHEMA)
                else:
                    state_input = pa.Table.from_pylist([dict(url='https://fixture.example.gov/target.pdf',
                        outcome='request_failed', attempts=1, checked_at='2026-10-20T00:00:00Z')], schema=STATE_SCHEMA)
                    capture_input = None
                current_raw = owner.publish(owner.prepare(owner.snapshot(), operation=change,
                    captures=capture_input, states=state_input))
            with phases.phase(change + '_catalog'):
                results[change] = update_from_raw(store, raw_storage=RawStorage.open(store, native),
                    directory=output / (change + '-catalog'), candidate=change)
            with phases.phase(change + '_viewer_preparation'):
                manifest, proof, etag = prepare_viewer(store, native, remote, output / (change + '-viewer'))
            with phases.phase(change + '_viewer_publication'):
                publish_viewer(remote, output / (change + '-viewer'), manifest, proof, etag)
            with read_catalog(store, native=native) as current:
                observed = tables(current)
                (output / (change + '-catalog-selection.json')).write_text(json.dumps(current.selection, indent=2) + '\n')
                assert observed['filenames'] and len(observed['filenames']) == unrelated + 2
                for label in ('filenames', 'documents'):
                    old_rows, new_rows = by_id(baseline[label], label), by_id(observed[label], label)
                    keys = unrelated_ids if label == 'filenames' else unrelated_documents
                    assert all(new_rows[key] == old_rows[key] for key in keys), label + ' unrelated values changed'
                target = next(row for row in observed['filenames'] if row['source_url'].endswith('/target.pdf'))
                original = next(row for row in baseline['filenames'] if row['source_url'].endswith('/target.pdf'))
                assert target['source_id'] == original['source_id'] and target['document_id'] == original['document_id']
                assert target['source_document_label'] == ['Exact publisher target']
                if change == 'correction':
                    assert target['state_outcome'] == ['request_failed']
                    assert target['state_checked_at'] == ['2026-10-20T00:00:00Z']
                    allowed = {'state_outcome', 'state_checked_at'}
                    assert {key for key in target if target[key] != original[key]} <= allowed
                state = state_input.to_pylist()[0]
                if change == 'append':
                    expected_states.append(state)
                    expected_captures.extend(capture_input.to_pylist())
                else:
                    position = next(i for i, row in enumerate(expected_states) if row['url'] == state['url'])
                    expected_states[position] = state
                actual_states, actual_captures = current_raw.states(), current_raw.captures()
                assert actual_states.to_pylist() == expected_states
                assert actual_captures.to_pylist() == expected_captures
                pq.write_table(actual_states, output / (change + '-raw-states.parquet'))
                pq.write_table(actual_captures, output / (change + '-raw-captures.parquet'))
                (output / (change + '-raw-selection.json')).write_text(json.dumps(current_raw.manifest, indent=2) + '\n')
                assert tables(old_catalog) == baseline
                assert old_raw.states().to_pylist() == old_state and old_raw.captures().to_pylist() == old_capture
                assert all(remote.objects[key] and sha256(remote.objects[key]).hexdigest() == digest
                           for key, digest in immutable_before.items())
                assert component_records(remote, manifest, unrelated_documents, output / 'read-public') == component_before
                checks[change] = dict(exact_old_selected_values=True, unrelated_source_document_values_and_ids_preserved=True,
                    exact_complete_new_raw_values_and_order=True,
                    unchanged_target_source_document_ids=True, immutable_previous_objects_unchanged=len(immutable_before),
                    unrelated_public_component_records_reused=len(component_before), source_rows=len(observed['filenames']),
                    document_rows=len(observed['documents']))
        old_catalog.close()
        status = 'completed'
    except BaseException as error:
        status = 'failed'
        results['error'] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        tracemalloc.stop()
        receipt = dict(unrelated_rows=unrelated, status=locals().get('status', 'failed'),
            git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            python=sys.version, pyarrow=pa.__version__, platform=platform.platform(),
            phases=phases.rows, checks=checks, results=results,
            scope='Generated local fixture transport. Logical Arrow/store boundaries only; excludes actual native engine and remote physical throughput, hosted artifact/journal orchestration.')
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unrelated', type=int)
    args = parser.parse_args()
    if args.unrelated is not None:
        with (args.output.parent / (args.output.name + '.log')).open('w') as log, redirect_stdout(log):
            return run_case(args.unrelated, args.output)
    args.output.mkdir(parents=True, exist_ok=False)
    failures = 0
    deadline = time.monotonic() + 1200
    for repetition in (1, 2):
        for size in (4, 40):
            case = args.output / f'{size}-r{repetition}'
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SystemExit('Reached the protocol twenty-minute limit')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--output', str(case), '--unrelated', str(size)], timeout=min(600, remaining))
            if result.returncode:
                failures += 1
                if failures >= 3:
                    raise SystemExit('Stopped after three retained fixture failures')
                raise SystemExit('Fixture failure retained; investigate before a new run')


if __name__ == '__main__':
    main()
