"""Stage the reviewed House XML syntax transition without changing shared tables.

Previously selected rows are preservation obligations, even outside today's fetch
filter. Strict-success evidence is shared by body hash across the three producers;
only ambiguous pairs and prior refusals need raw bytes. Shared decision import,
append acknowledgment and head records remain the existing activation job's work.
"""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import appearance_records, committee_records, meeting_records, tables
from congress_api.lake._record_producer import _candidate_rel_paths, normalize_record_sha
from congress_api.lake.readings import BackfillRequired
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.provenance import durable_json, file_pin, instant, parquet_output, run_job, validate_provenance
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model_job import _local, _pin, _selector
from viewer_publication.archive_selective_records import SELECTION_SCHEMA, stage_selected_records
from viewer_publication.producer_proof import BACKFILL, ROOT, _record_reasons, record

MODULES = dict(meeting_records=meeting_records, appearance_records=appearance_records, committee_records=committee_records)
OLD = dict(meeting_records='684f3663274217a2c24a19a5a71887aa0f5f9f8c61dc5a590959e48ab84dd24b',
           appearance_records='7ecb6f0a62538695c0b5b2b93654cc148e0fb11fcb72c7e189cc8ce328a86abd',
           committee_records='83d27c2ae65792ef9e00a878329068b6fe4a757386efce09e8beebc4cd54d2f3')
NEW = dict(meeting_records='24c88e855dab86f0c362387ffd4c40cf196e2a6f5c14d8aa1dba66f821ca0df5',
           appearance_records='5078ef426e0e262ffcd972b244c3b472669583f164121cc6189ccf69e6abf3a5',
           committee_records='e1c6ad0d1398f1d1985e085a0fb9b94c6c42ad38a2d9175ad3e8908eb46c531e')
FILE = {'path', 'sha256', 'size'}
LIMITS = {'max_pairs', 'max_recompute_pairs', 'max_unique_bodies', 'max_body_bytes', 'max_stored_bytes',
          'max_total_decoded_bytes', 'max_output_bytes', 'min_disk_bytes'}


def load_dispositions(value, *, base):
    if (set(value) != {'version', 'work', 'engine_config', 'house_xml_disposition'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('House XML disposition requires version 1, work and an engine config')
    job = value['house_xml_disposition']
    fields = {'census', 'bases', 'origins', 'candidates', 'unreadable_files', 'raw_root', 'decided_at', 'limits', 'resume', 'pilot_body'}
    if not isinstance(job, dict) or set(job) != fields:
        raise ValueError('House XML disposition requires pinned census, bases, origins, candidates and limits')
    for key in ('bases', 'origins', 'candidates'):
        if not isinstance(job[key], dict) or job[key].keys() != MODULES.keys():
            raise ValueError('House XML disposition requires all three House tables')
    if (not isinstance(job['limits'], dict) or job['limits'].keys() != LIMITS
            or any(type(v) is not int or v <= 0 for v in job['limits'].values())
            or type(job['resume']) is not bool or not isinstance(job['unreadable_files'], list)):
        raise ValueError('House XML disposition requires positive finite limits and an explicit resume flag')
    instant(job['decided_at'])
    if job['pilot_body'] is not None and normalize_record_sha(job['pilot_body']) != job['pilot_body']:
        raise ValueError('House XML pilot requires an exact lowercase body SHA-256')

    def pin(item, fields=FILE):
        _pin(item, fields)
        return dict(item, path=_local(item['path'], base))

    def decision_pin(item):
        result = pin(item, FILE | {'key'})
        validate_key(result['key'])
        if not result['key'].startswith('provenance/unreadable/'):
            raise ValueError('House XML refusal files must name unreadable provenance keys')
        return result

    bases = {name: _selector(item, base) for name, item in job['bases'].items()}
    if any(item['kind'] == 'native_table' and item['snapshot'] is None for item in bases.values()):
        raise ValueError('House XML disposition bases must name nonempty immutable snapshots')
    return dict(value, work=_local(value['work'], base), engine_config=_local(value['engine_config'], base),
                house_xml_disposition=dict(job, census=pin(job['census']), bases=bases,
                    origins={name: pin(item) for name, item in job['origins'].items()},
                    candidates={name: pin(item) for name, item in job['candidates'].items()},
                    unreadable_files=[decision_pin(item) for item in job['unreadable_files']], raw_root=_local(job['raw_root'], base)))


def _verified(pin):
    if file_pin(pin['path']) != {key: pin[key] for key in ('sha256', 'size')}:
        raise ValueError('House XML input differs from its pin: ' + pin['path'])
    return Path(pin['path'])


def _pinned(path):
    return dict(path=str(path), **file_pin(path))


def _keys(rows):
    result = [normalize_record_sha(row['record_sha']) for row in rows]
    if any(row['source'] != 'house_xml' for row in rows) or len(set(result)) != len(result):
        raise ValueError('House XML selection contains duplicate or non-House keys')
    return set(result)


def _decisions(files):
    from congress_api.retention.provenance import active_unreadable_rows
    by_id = {}
    for pin in files:
        for line in _verified(pin).read_bytes().splitlines():
            row = validate_provenance('unreadable', json.loads(line))
            if row['id'] in by_id and by_id[row['id']] != row:
                raise ValueError('Conflicting unreadable decision identity')
            by_id[row['id']] = row
    return active_unreadable_rows(by_id.values())


def _refusals(name, decisions, version):
    short = {'meeting_records': 'meetings', 'appearance_records': 'appearances'}.get(name, name)
    return {normalize_record_sha(row.get('record_sha') or row.get('body_sha256'))
            for row in decisions if row['parser'] in {name, short, name + '.house_xml'} and row['parser_version'] == version}


def _strict_success(name, row):
    if name == 'meeting_records':
        return bool(row['meetings'])
    if name == 'appearance_records':
        return row['collection_state'] in {'present', 'empty', 'absent'}
    return bool(row['records']) or row['event_id'] is not None or row['updated'] is not None


def _space(work, limits):
    if shutil.disk_usage(work).free < limits['min_disk_bytes']:
        raise ValueError('House XML transition reached its free disk floor')
    if sum(path.stat().st_size for path in work.rglob('*') if path.is_file() and path.name != 'engine.log') > limits['max_output_bytes']:
        raise ValueError('House XML transition exceeded its output byte limit')


def _qualify_body(digest, raw, target, limits, remaining, remaining_stored):
    """Decode once with CRC, byte caps and SHA validation before the producer can catch errors."""
    source = next((raw / rel for rel in _candidate_rel_paths(digest, '.gz') if (raw / rel).is_file()), None)
    if source is None:
        return None
    if source.stat().st_size > min(limits['max_stored_bytes'], remaining_stored):
        raise ValueError('House XML stored body exceeds its byte limit: ' + digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.partial')
    count, hashed = 0, sha256()
    with source.open('rb') as stored:
        compressed = stored.read(2) == b'\x1f\x8b'
        stored.seek(0)
        stream = gzip.GzipFile(fileobj=stored) if compressed else stored
        try:
            with temporary.open('wb') as out:
                while chunk := stream.read(min(1 << 20, limits['max_body_bytes'] - count + 1, remaining - count + 1)):
                    count += len(chunk)
                    if count > limits['max_body_bytes'] or count > remaining:
                        raise ValueError('House XML decoded bytes exceed the admitted limit: ' + digest)
                    hashed.update(chunk)
                    out.write(chunk)
        finally:
            if compressed:
                stream.close()
    if hashed.hexdigest() != digest:
        raise ValueError('House XML body SHA-256 mismatch: ' + digest)
    temporary.replace(target)
    target.chmod(0o444)
    return dict(source=str(source), stored=file_pin(source), decoded=_pinned(target), decoded_bytes=count)


def _stage_once(name, keys, engine, directory, raw, unreadable, decided_at, *, existing=None, limit=None):
    directory.mkdir(parents=True, exist_ok=False)
    selection = directory / 'selection.parquet'
    pq.write_table(pa.Table.from_pylist([dict(record_sha=key, source='house_xml', stored_suffix='')
                                      for key in sorted(keys)], schema=SELECTION_SCHEMA), selection)
    return stage_selected_records(name, selection, engine=engine, work=directory / 'stage', existing=existing,
        local_root=raw, raw_store=BodyStore(LocalAdapter(raw)),
        unreadable_files=[dict(key=pin['key'], path=str(_verified(pin))) for pin in unreadable],
        decided_at=decided_at, max_work_items=limit)


def execute_dispositions(spec, *, runtime_factory=None):
    job, work = spec['house_xml_disposition'], Path(spec['work'])
    if any(module.current_versions()['house_xml'] != NEW[name] for name, module in MODULES.items()):
        raise ValueError('House XML disposition only supports the reviewed syntax change')
    writer = writer_identity(ROOT, BACKFILL)
    identity = dict(spec, house_xml_disposition=dict(job, resume=False), writer=writer)
    state_path = work / 'state.json'
    if work.exists():
        if not job['resume'] or not state_path.is_file():
            raise ValueError('House XML disposition requires a fresh work directory or a matching resume')
        state = json.loads(state_path.read_text())
        if state['identity'] != identity:
            raise ValueError('House XML resume inputs or writer changed')
        for pin in state['files']:
            _verified(pin)
    else:
        work.mkdir(parents=True)
        state = dict(identity=identity, files=[], exports={}, stages={})

    def save():
        _space(work, job['limits'])
        durable_json(state_path, state)

    census = json.loads(_verified(job['census']).read_text())
    decisions = _decisions(job['unreadable_files'])
    factory = runtime_factory or NativeDatasets.from_config
    selected, candidates, refused = {}, {}, {}
    with factory(spec['engine_config']) as engine:
        engine.verify_runtime()
        for name, module in MODULES.items():
            base = job['bases'][name]
            if base != census['selectors'][name]:
                raise ValueError('House XML base differs from the admitted census')
            origin = json.loads(_verified(job['origins'][name]).read_text())
            versions = dict(module.current_versions(), house_xml=OLD[name])
            reasons = _record_reasons(name, origin, dict(parser_versions={name: versions}), None, ROOT,
                                      label=name, selector=base)
            if reasons:
                raise ValueError('House XML base producer refused: ' + '; '.join(reasons))
            if name not in state['exports']:
                source = _verified(base) if base['kind'] == 'parquet' else {k: v for k, v in base.items() if k != 'kind'}
                directory = work / ('base-' + name)
                # An interrupted export is retained; only completed, pinned exports are reused.
                attempt = directory / str(len(list(directory.glob('*'))) + 1)
                run_job(attempt, engine, inputs=[tables.table_input('base', source)], steps=[],
                    outputs=[parquet_output(attempt, 'selected',
                        f"SELECT * FROM base WHERE source='house_xml' AND parser_version='{OLD[name]}' LIMIT {job['limits']['max_pairs'] + 1}",
                        list(tables.TABLE_SPECS[name]['primary_key']))])
                pin = _pinned(attempt / 'selected.parquet')
                state['exports'][name] = pin
                state['files'].append(pin)
                save()
            table = pq.read_table(_verified(state['exports'][name]))
            if (table.schema.names != module.table([]).schema.names
                    or any(a.type != b.type for a, b in zip(table.schema, module.table([]).schema))):
                raise ValueError('House XML selected payload schema changed')
            rows = table.to_pylist()
            old = _keys(rows)
            if any(row['status'] != 'completed' or row['parser_version'] != OLD[name] for row in rows):
                raise ValueError('House XML selected rows lack completed prior-version evidence')
            selected[name] = {normalize_record_sha(row['record_sha']): row for row in rows}
            candidates[name] = _keys(pq.read_table(_verified(job['candidates'][name])).to_pylist())
            refused[name] = _refusals(name, decisions, OLD[name])
            counts = census['tables'][name]
            if (len(old) != counts['O'] or len(candidates[name]) != counts['K_base'] or len(refused[name]) != counts['U']
                    or old & refused[name] or len(candidates[name] - old - refused[name]) != counts['P']):
                raise ValueError('House XML selected/candidate/refusal sets differ from the census')

        proofs = {key for name, rows in selected.items() for key, row in rows.items() if _strict_success(name, row)}
        reuse = {name: set(rows) & proofs for name, rows in selected.items()}
        universe = {name: set(selected[name]) | candidates[name] | refused[name] for name in MODULES}
        affected = {name: universe[name] - reuse[name] for name in MODULES}
        if (sum(map(len, universe.values())) > job['limits']['max_pairs']
                or sum(map(len, affected.values())) > job['limits']['max_recompute_pairs']
                or len(set().union(*affected.values())) > job['limits']['max_unique_bodies']):
            raise ValueError('House XML transition exceeds its pair limit')
        if any(len(set(selected[name]) - reuse[name]) != census['tables'][name]['ambiguous'] for name in MODULES):
            raise ValueError('House XML strict-success proof set differs from the census')
        pilot = job['pilot_body']
        if pilot is not None and pilot not in set().union(*affected.values()):
            raise ValueError('House XML pilot body is outside the reviewed affected set')
        scheduled = {name: keys if pilot is None else keys & {pilot} for name, keys in affected.items()}

        progress = state.setdefault('integrity', dict(bodies={}, decoded_bytes=0, stored_bytes=0))
        integrity = progress['bodies']
        for key in sorted(set().union(*scheduled.values())):
            if key in integrity:
                continue
            _space(work, job['limits'])
            target = work / 'validated' / _candidate_rel_paths(key, '')[0]
            proof = _qualify_body(key, Path(job['raw_root']), target, job['limits'],
                job['limits']['max_total_decoded_bytes'] - progress['decoded_bytes'],
                job['limits']['max_stored_bytes'] - progress['stored_bytes'])
            integrity[key] = proof
            if proof:
                progress['decoded_bytes'] += proof['decoded_bytes']
                progress['stored_bytes'] += proof['stored']['size']
                state['files'].append(proof['decoded'])
            save()
        # Budget the producer's repeated full-body reads per table/body pair as well.
        producer_bytes = sum(integrity[key]['decoded_bytes'] for keys in scheduled.values() for key in keys if integrity[key])
        if producer_bytes > job['limits']['max_total_decoded_bytes']:
            raise ValueError('House XML producer reads exceed the total decoded byte limit')
        progress['producer_decoded_bytes'] = producer_bytes
        integrity = state['integrity']['bodies']
        pending = {name: {key for key in scheduled[name] if integrity[key] is None} for name in MODULES}
        if any(pending[name] & (set(selected[name]) | refused[name]) for name in MODULES):
            raise ValueError('House XML previously settled bodies are missing; activation is blocked')

        for name, module in MODULES.items():
            if name in state['stages'] or pilot is not None and not scheduled[name]:
                continue
            directory = work / name
            attempt = directory / str(len(list(directory.glob('*'))) + 1)
            staged = _stage_once(name, scheduled[name] - pending[name], engine, attempt, work / 'validated',
                                 job['unreadable_files'], job['decided_at'], limit=job['limits']['max_recompute_pairs'])
            result = pq.read_table(staged['records'])
            completed = _keys(result.to_pylist())
            new_files = [dict(key=staged['unreadable_key'], **_pinned(staged['unreadable_path']))] if staged['unreadable_path'] else []
            new_decisions = _decisions(new_files)
            unreadable = _refusals(name, new_decisions, NEW[name])
            if (any(row['reason'] != 'parse_error' for row in new_decisions)
                    or any(row['parser_version'] != NEW[name] or row['status'] != 'completed' for row in result.to_pylist())
                    or len(new_decisions) != len(unreadable) or completed & unreadable
                    or completed | unreadable != scheduled[name] - pending[name]
                    or staged['work_items'] != len(scheduled[name] - pending[name])):
                raise ValueError('House XML replay changed its expected dispositions')
            carried_keys = reuse[name] if pilot is None else set()
            carried = [dict(selected[name][key], parser_version=NEW[name]) for key in sorted(carried_keys)]
            combined = pa.Table.from_pylist(carried + result.to_pylist(), schema=module.table([]).schema)
            combined = combined.sort_by([('record_sha', 'ascending'), ('source', 'ascending'), ('parser_version', 'ascending')])
            output = attempt / 'append.parquet'
            pq.write_table(combined, output)
            readback = pq.read_table(output)
            by_key = {normalize_record_sha(row['record_sha']): row for row in readback.to_pylist()}
            if (_keys(readback.to_pylist()) != carried_keys | completed
                    or any({k: v for k, v in by_key[key].items() if k != 'parser_version'} !=
                           {k: v for k, v in selected[name][key].items() if k != 'parser_version'} for key in carried_keys)):
                raise ValueError('House XML carry-forward changed semantic values')
            done = set(by_key)
            scope = universe[name] if pilot is None else scheduled[name]
            if (done & unreadable or (done | unreadable | pending[name]) != scope
                    or pilot is None and (set(selected[name]) - done - unreadable
                    or candidates[name] != ((done | unreadable) & candidates[name]) | pending[name])):
                raise ValueError('House XML transition lost a selected or candidate pair')
            ledger = attempt / 'dispositions.json'
            durable_json(ledger, [dict(record_sha=key, source='house_xml', prior_selected=key in selected[name],
                in_candidates=key in candidates[name], disposition='reused' if key in carried_keys else
                'completed' if key in done else 'unreadable' if key in unreadable else 'pending') for key in sorted(scope)])
            selector = dict(kind='parquet', **_pinned(output))
            stage = dict(selector=selector, unreadable_files=new_files, unreadable_stage=str(staged['unreadable_stage']) if new_files else None,
                unreadable_pending=bool(new_files), reused=len(carried_keys), produced=len(completed), unreadable=len(unreadable),
                pending=len(pending[name]), selected=len(selected[name]), candidates=len(candidates[name]), ledger=_pinned(ledger))
            state['stages'][name] = stage
            state['files'] += [_pinned(output), stage['ledger'], *new_files]
            save()

    # A fresh runtime proves persisted completions/refusals settle exactly those keys.
    if 'settlement' not in state:
        with factory(spec['engine_config']) as engine:
            engine.verify_runtime()
            for name, stage in state['stages'].items():
                directory = work / 'settlement' / name
                attempt = directory / str(len(list(directory.glob('*'))) + 1)
                try:
                    check = _stage_once(name, universe[name] if pilot is None else scheduled[name], engine, attempt, work / 'validated',
                        [*job['unreadable_files'], *stage['unreadable_files']], job['decided_at'],
                        existing=Path(stage['selector']['path']), limit=0)
                    remaining = set()
                    if check['produced'] or check['unreadable_pending']:
                        raise ValueError('House XML settled rows unexpectedly produced work')
                except BackfillRequired as stop:
                    remaining = _keys(pq.read_table(stop.report['work_list']).to_pylist())
                if remaining != pending[name]:
                    raise ValueError('House XML fresh planning did not preserve exact pending work')
        state['settlement'] = dict(fresh_runtime=True, pending_pairs=sum(map(len, pending.values())), settled_work_items=0)
        save()
    if writer_identity(ROOT, BACKFILL) != writer:
        raise ValueError('House XML writer changed during staging')
    if 'report' not in state:
        for name, stage in state['stages'].items() if pilot is None else ():
            path = work / (name + '.json')
            origin = record(path, input=name, selector=stage['selector'], job=BACKFILL)
            origin.update(delta_only=True, final_reconciliation_required=True, base=job['bases'][name],
                          base_producer=job['origins'][name], census=job['census'])
            durable_json(path, origin)
            stage['producer'] = _pinned(path)
            state['files'].append(stage['producer'])
        state['report'] = dict(status='local_staged' if pilot is None else 'local_pilot', executed=True, shared_writes=0, tables=state['stages'],
            prior_house_versions=OLD, house_versions=NEW, integrity=state['integrity'], settlement=state['settlement'],
            activation_required=True, pilot_body=pilot, resident_selected_rows=sum(map(len, selected.values())))
        save()
    return state['report']
