"""Validate a completed House cohort and hand its appends to the daily owner."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

import pyarrow.parquet as pq

from congress_api.lake import daily
from congress_api.lake.producer_records import ProducerRecords
from congress_api.retention.body_store import BodyStore, LocalAdapter, R2Adapter
from congress_api.retention.provenance import durable_json, instant
from congress_shared.storage import connect_r2
from docspec_client.client import NativeDatasets
from viewer_publication.archive_house_xml_dispositions import MODULES, NEW, OLD, FILE, _keys, _verified
from viewer_publication.archive_model_job import _local, _pin
from viewer_publication.producer_proof import ROOT, _record_reasons, snapshot_reasons

EXPECTED = dict(meeting_records=dict(selected=6183, reused=6182, produced=1),
                appearance_records=dict(selected=3401, reused=3401, produced=0),
                committee_records=dict(selected=6238, reused=5654, produced=584))


def load_activation(value, *, base):
    if (set(value) != {'version', 'work', 'engine_config', 'house_xml_activation'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('House XML activation requires version 1, work and an engine config')
    job = value['house_xml_activation']
    fields = {'cohort', 'tables', 'anchors', 'catalog_root', 'raw_root', 'bucket', 'decided_at',
              'resume', 'max_output_bytes', 'min_disk_bytes'}
    if not isinstance(job, dict) or set(job) != fields:
        raise ValueError('House XML activation requires the pinned cohort and explicit existing targets')
    if (any(not isinstance(job[key], dict) or job[key].keys() != MODULES.keys() for key in ('tables', 'anchors'))
            or type(job['resume']) is not bool
            or any(type(job[key]) is not int or job[key] <= 0 for key in ('max_output_bytes', 'min_disk_bytes'))):
        raise ValueError('House XML activation requires three tables and finite limits')
    from viewer_publication.archive_backfill_job import _bucket, _table_ref

    def pin(item):
        _pin(item, FILE)
        return dict(item, path=_local(item['path'], base))

    targets = {name: _table_ref(ref) for name, ref in job['tables'].items()}
    if len({json.dumps(ref, sort_keys=True) for ref in targets.values()}) != len(MODULES):
        raise ValueError('House XML activation targets must be distinct')
    remote = job['catalog_root'] is None
    if remote != (job['raw_root'] is None) or remote != (job['bucket'] is not None):
        raise ValueError('House XML activation needs one local or remote authority')
    instant(job['decided_at'])
    return dict(value, work=_local(value['work'], base), engine_config=_local(value['engine_config'], base),
        house_xml_activation=dict(job, tables=targets, cohort=pin(job['cohort']),
            anchors={name: pin(item) for name, item in job['anchors'].items()},
            catalog_root=None if remote else _local(job['catalog_root'], base),
            raw_root=None if remote else _local(job['raw_root'], base), bucket=_bucket(job['bucket']) if remote else None))


def prepare_activation(pin):
    """Reuse the checked staging result; qualify its retained artifacts at this boundary."""
    state = json.loads(_verified(pin).read_text())
    report, job = state['report'], state['identity']['house_xml_disposition']
    if (report['status'] != 'local_staged' or report['pilot_body'] is not None or job['pilot_body'] is not None
            or report['house_versions'] != NEW or report['prior_house_versions'] != OLD
            or report['tables'].keys() != MODULES.keys() or report['settlement']['settled_work_items'] != 0
            or report['settlement']['pending_pairs'] != 0):
        raise ValueError('House XML activation requires the completed whole cohort with no pending work')
    census = json.loads(_verified(job['census']).read_text())
    if len(job['unreadable_files']) != 31:
        raise ValueError('House XML activation requires the unchanged 31-file refusal baseline')
    prepared = dict(cohort=pin, tables={}, frozen_unreadable=job['unreadable_files'],
                    unchanged_selectors={name: item for name, item in census['selectors'].items() if name not in MODULES},
                    unchanged_inventory=census.get('inventory'))
    for name, module in MODULES.items():
        stage = report['tables'][name]
        if (module.current_versions()['house_xml'] != NEW[name] or stage['pending'] or stage['unreadable']
                or stage['unreadable_files'] or stage['unreadable_pending']
                or any(stage[key] != count for key, count in EXPECTED[name].items())
                or job['bases'][name] != census['selectors'][name] or job['bases'][name]['kind'] != 'native_table'):
            raise ValueError('House XML activation base or version differs from its staged census')
        origin = json.loads(_verified(stage['producer']).read_text())
        reasons = _record_reasons(name, origin, dict(parser_versions={name: module.current_versions()}), None, ROOT,
            label=name, selector=stage['selector'], allow_delta=True)
        if (reasons or origin.get('delta_only') is not True or origin.get('final_reconciliation_required') is not True
                or origin['commit'] != state['identity']['writer']['commit']
                or origin['base'] != job['bases'][name] or origin['base_producer'] != job['origins'][name]
                or origin['census'] != job['census']):
            raise ValueError('House XML staged producer refused: ' + '; '.join(reasons))
        _verified(job['origins'][name])
        table = pq.read_table(_verified(stage['selector']))
        expected_schema = module.table([]).schema
        rows = table.to_pylist()
        completed = _keys(rows)
        if (not completed or table.schema.names != expected_schema.names
                or any(a.type != b.type for a, b in zip(table.schema, expected_schema))
                or any(row['parser_version'] != NEW[name] or row['status'] != 'completed' for row in rows)):
            raise ValueError('House XML incoming rows lack a complete typed new-version generation')
        ledger = json.loads(_verified(stage['ledger']).read_text())
        universe = _keys(ledger)
        old = _keys(pq.read_table(_verified(state['exports'][name]), columns=['record_sha', 'source']).to_pylist())
        counts = census['tables'][name]
        dispositions = {kind: {row['record_sha'] for row in ledger if row['disposition'] == kind}
                        for kind in ('reused', 'completed', 'unreadable')}
        refused = dispositions['unreadable']
        if (any(row['disposition'] not in dispositions for row in ledger)
                or {row['record_sha'] for row in ledger if row['prior_selected']} != old
                or len(old) != counts['O'] or stage['selected'] != counts['O']
                or len(dispositions['reused']) != counts['O'] - counts['ambiguous']
                or len(dispositions['reused']) != stage['reused']
                or len(dispositions['completed']) != stage['produced'] or len(refused) != stage['unreadable']
                or completed != dispositions['reused'] | dispositions['completed']
                or refused or completed != universe or universe != old
                or len({row['record_sha'] for row in ledger if row['in_candidates']}) != counts['K_base']):
            raise ValueError('House XML staged selected/candidate dispositions differ from their proof')
        prepared['tables'][name] = dict(base={k: v for k, v in job['bases'][name].items() if k != 'kind'},
            base_record=job['origins'][name], records=stage['selector'], producer=stage['producer'],
            ledger=stage['ledger'], version=NEW[name])
    for item in prepared['frozen_unreadable']:
        _verified(item)
    if report['resident_selected_rows'] != sum(census['tables'][name]['O'] for name in MODULES):
        raise ValueError('House XML cohort omits retained selected pairs')
    return prepared


def _lock_path(catalog_root):
    if catalog_root is None:
        common = Path(subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--path-format=absolute', '--git-common-dir'], text=True).strip())
        return common.parent / '.cache/archive-release/nightly/lock'
    return Path(catalog_root).parent / 'house-activation.lock'


@contextmanager
def _activation_lock(catalog_root):
    path = _lock_path(catalog_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('House XML activation refused: another archive writer holds the lock') from None
        yield handle.fileno()


def _activation_command(spec, invocation, fd):
    return [sys.executable, str(ROOT / 'scripts/archive_watchdog.py'), '--rss-gb', '2', '--expect-gb', '2',
        '--start-available-gb', '6', '--min-disk-gb', '15', '--interval', '0.2', '--hold-fd', str(fd),
        '--report', str(invocation / 'watchdog.json'), '--', sys.executable, '-m',
        'viewer_publication.archive_backfill_job', '--spec', str(invocation / 'spec.json'),
        '--execute', '--activation-lock-fd', str(fd)]


def _launch_activation(spec):
    """The owned process group retains the lock until every native descendant stops."""
    with _activation_lock(spec['house_xml_activation']['catalog_root']) as fd:
        launcher = Path(spec['work']).with_name(Path(spec['work']).name + '-launcher')
        launcher.mkdir(parents=True, exist_ok=True)
        invocation = launcher / ('attempt-' + str(len(list(launcher.glob('attempt-*'))) + 1))
        invocation.mkdir()
        durable_json(invocation / 'spec.json', spec)
        with (invocation / 'stdout.json').open('w') as out, (invocation / 'stderr.log').open('w') as err:
            result = subprocess.run(_activation_command(spec, invocation, fd), pass_fds=(fd,), stdout=out, stderr=err)
        if result.returncode:
            raise ValueError('House XML owned activation failed; retained evidence: ' + str(invocation))
        return json.loads((invocation / 'stdout.json').read_text())


def execute_activation(spec, *, runtime_factory=None, storage_factory=None, lock_fd=None):
    if lock_fd is None:
        return _launch_activation(spec)
    job = spec['house_xml_activation']
    if not os.path.samestat(os.fstat(lock_fd), _lock_path(job['catalog_root']).stat()):
        raise ValueError('House XML activation requires the inherited archive writer lock')
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    prepared = prepare_activation(job['cohort'])
    anchors = {name: _verified(item).read_bytes() for name, item in job['anchors'].items()}
    factory = runtime_factory or NativeDatasets.from_config
    with factory(spec['engine_config']) as engine:
        engine.verify_runtime()
        if job['catalog_root'] is None:
            client = (storage_factory or connect_r2)(bucket=job['bucket'], retries={'total_max_attempts': 1})
            store = BodyStore(R2Adapter(client, job['bucket']))
            records = ProducerRecords(anchors, client=client, bucket=job['bucket'])
        else:
            store = BodyStore(LocalAdapter(job['raw_root']))
            records = ProducerRecords(anchors, root=job['raw_root'])
        result = daily.activate_house_xml_records(prepared, engine=engine, raw_store=store, producer_records=records,
            catalog_root=job['catalog_root'], targets=job['tables'], work=Path(spec['work']),
            decided_at=job['decided_at'], resume=job['resume'],
            max_output_bytes=job['max_output_bytes'], min_disk_bytes=job['min_disk_bytes'])
        head_records = {name: records.find(name, selector)[0] for name, selector in result['pins'].items()}
        model = dict(**result['pins'], parser_versions={name: module.current_versions() for name, module in MODULES.items()})
        reasons = snapshot_reasons(model, head_records, ledger=records)
        if reasons:
            raise ValueError('House XML activation final producer chain refused: ' + '; '.join(reasons))
        result.update(status='activated', producer_chain_verified=True, anchors=job['anchors'])
        durable_json(Path(spec['work']) / 'activation-complete.json', result)
        return result
