"""Replay reviewed record changes into importable Parquet files."""
import gzip
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import appearance_records, committee_records, meeting_records, playlist_records
from congress_api.lake._record_producer import _candidate_rel_paths
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.provenance import file_pin
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model_job import _local, _pin
from viewer_publication.archive_selective_records import SELECTION_SCHEMA, stage_selected_records
from viewer_publication.producer_proof import BACKFILL, IMPORT, ROOT, _record_reasons, record, snapshot_reasons

FILE = {'path', 'size', 'sha256'}
RECORD_TABLES = {'meeting_records', 'appearance_records'}
CAPTURE_PRODUCERS = {'committee_records': committee_records, 'playlist_records': playlist_records}
HOUSE_XML_RECEIPTS = 'receipts/house/meeting-xml/'
HOUSE_XML_PATH = 'external-sources/hearing-text/docs_house_xml/meeting/'
MEETING_PRIOR = {
    'congress_gov': 'ecc51fcdb572b426da01a9135b467bf3f9a85e91d268ff895a56e2dda5ef716e',
    'house_xml': '8a2417a2c876b2cd3f202ed92dfbc48bca580f7fa2848d6644310771484617c8',
}
MEETING_DOCUMENT_REFERENCES = {
    'congress_gov': '325702c1794f246323ed30d7430650355121dd4891a7cea62b44a34a8ae5084d',
    'house_xml': '684f3663274217a2c24a19a5a71887aa0f5f9f8c61dc5a590959e48ab84dd24b',
}


def load_record_only(value, *, base):
    if set(value) != {'version', 'work', 'engine_config', 'record_only'} or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Record-only backfill requires version 1, work and a local engine config')
    job = value['record_only']
    fields = {'base_model', 'bases', 'raw_root', 'raw_mirror', 'max_work_items'}
    optional = {'meeting_selection', 'capture_inputs', 'retained_committee', 'committee_composition', 'replay_sources'}
    if not isinstance(job, dict) or not fields <= job.keys() or job.keys() - fields - optional:
        raise ValueError('Record-only backfill requires pinned bases, raw locations and a work limit')
    if not isinstance(job['bases'], dict) or job['bases'].keys() - RECORD_TABLES:
        raise ValueError('Record-only backfill bases must name meeting_records or appearance_records')
    if ('meeting_records' in job['bases']) != ('meeting_selection' in job):
        raise ValueError('Meeting backfill requires its exact source selection')
    # The reviewed move: the run refuses unless exactly these appearance sources moved (_appearances).
    if ('appearance_records' in job['bases']) != ('replay_sources' in job) or 'replay_sources' in job and (
            not isinstance(job['replay_sources'], list) or not job['replay_sources']
            or any(not isinstance(s, str) or not s for s in job['replay_sources'])
            or len(set(job['replay_sources'])) != len(job['replay_sources'])):
        raise ValueError('Appearance backfill requires its reviewed replay_sources, a list of distinct sources')
    if type(job['max_work_items']) is not int or job['max_work_items'] <= 0:
        raise ValueError('Record-only backfill requires a positive max_work_items')

    def local_pin(pin):
        _pin(pin, FILE)
        return dict(pin, path=_local(pin['path'], base))

    captures = job.get('capture_inputs', {})
    if not isinstance(captures, dict) or captures.keys() - CAPTURE_PRODUCERS.keys():
        raise ValueError('Record-only capture inputs must name committee_records or playlist_records')
    retained = job.get('retained_committee')
    if 'retained_committee' in job:
        if (not isinstance(retained, dict) or set(retained) != {'receipt_key', 'receipt', 'selection', 'base'}
                or not isinstance(retained['receipt_key'], str) or 'committee_records' in captures):
            raise ValueError('Retained committee input requires its receipt, selection and base without a second committee input')
        key = retained['receipt_key']
        validate_key(key)
        if not key.startswith(HOUSE_XML_RECEIPTS) or not key.endswith('.jsonl.gz'):
            raise ValueError('Retained committee receipt must be House meeting XML')
        retained = dict(retained, **{k: local_pin(retained[k]) for k in ('receipt', 'selection', 'base')})
        if not retained['receipt']['path'].endswith('/' + key):
            raise ValueError('Retained committee receipt path does not match its key')
    composition = job.get('committee_composition')
    if 'committee_composition' in job:
        pins = {'base', 'base_producer', 'delta', 'delta_producer'}
        counts = {'expected_base_rows', 'expected_delta_rows'}
        if (not isinstance(composition, dict) or set(composition) != pins | counts
                or retained is not None or 'committee_records' in captures
                or any(type(composition[k]) is not int or composition[k] <= 0 for k in counts)
                or composition['expected_delta_rows'] > job['max_work_items']):
            raise ValueError('Committee composition requires pinned base and delta origins and bounded row counts')
        composition = dict(composition, **{k: local_pin(composition[k]) for k in pins})
    if not captures and not job['bases'] and retained is None and composition is None:
        raise ValueError('Record-only backfill requires at least one table')
    for item in captures.values():
        if (not isinstance(item, dict) or set(item) != {'capture', 'expected_rows'}
                or type(item['expected_rows']) is not int or not 0 < item['expected_rows'] <= job['max_work_items']):
            raise ValueError('A capture input requires a pinned file and a positive bounded expected_rows')
    job = dict(job, base_model=local_pin(job['base_model']),
        bases={name: local_pin(pin) for name, pin in job['bases'].items()},
        raw_root=_local(job['raw_root'], base), raw_mirror=_local(job['raw_mirror'], base),
        capture_inputs={name: dict(item, capture=local_pin(item['capture'])) for name,item in captures.items()})
    if 'meeting_selection' in job:
        job['meeting_selection'] = local_pin(job['meeting_selection'])
    if retained is not None:
        job['retained_committee'] = retained
    if composition is not None:
        job['committee_composition'] = composition
    return dict(value, work=_local(value['work'], base), engine_config=_local(value['engine_config'], base), record_only=job)


def _verified(pin):
    if file_pin(pin['path']) != {k: pin[k] for k in ('sha256', 'size')}:
        raise ValueError('Record-only input differs from its pin: ' + pin['path'])
    return Path(pin['path'])


def _key(row):
    return row['record_sha'], row['source']


def _versioned_key(row):
    return (*_key(row), row['parser_version'])


def _base_keys(table, versions, *, history):
    columns = table.select(['record_sha', 'source', 'parser_version', 'status']).to_pylist()
    if any(row['record_sha'] is None or row['parser_version'] is None for row in columns):
        raise ValueError('Record-only base contains missing keys')
    if len({_versioned_key(row) for row in columns}) != len(columns):
        raise ValueError('Record-only base contains duplicate keys')
    current = [row for row in columns if row['parser_version'] == versions.get(row['source'])]
    if set(row['source'] for row in current) != versions.keys() or any(row['status'] != 'completed' for row in current):
        raise ValueError('Record-only base lacks a completed prior source generation')
    if not history and len(current) != len(columns):
        raise ValueError('Meeting transition expects only its reviewed prior versions')
    return current


def _body_selection(digest, source, roots):
    sha = digest.hex()
    for key in _candidate_rel_paths(sha, '.gz'):
        if any((root / key).is_file() for root in roots):
            return dict(record_sha=sha, source=source, stored_suffix='.gz')
    raise ValueError(f'Record-only body is missing: {source} {sha}')


def _replay(name, selection, expected, versions, *, engine, work, raw_root, mirror, unreadable, limit):
    staged = stage_selected_records(name, selection, engine=engine, work=work, local_root=raw_root,
        raw_store=BodyStore(LocalAdapter(mirror)), unreadable_files=unreadable, max_work_items=limit)
    if staged['unreadable_pending'] or staged['work_items'] != len(expected):
        raise ValueError(f'Record-only {name} work count changed or unreadable decisions need review')
    table = pq.read_table(staged['records'])
    keys = table.select(['record_sha', 'source', 'parser_version', 'status']).to_pylist()
    if (len(keys) != len(expected) or {_key(row) for row in keys} != expected
            or any(row['status'] != 'completed' or row['parser_version'] != versions.get(row['source']) for row in keys)):
        raise ValueError(f'Record-only {name} replay changed keys, versions or completed status')
    return table


def _meetings(base, versions, selection, **stage):
    current = meeting_records.current_versions()
    if versions != MEETING_PRIOR or current != MEETING_DOCUMENT_REFERENCES:
        raise ValueError('Record-only meetings supports the reviewed document-reference transition')
    _base_keys(base, versions, history=False)
    rows = base.to_pylist()
    # The old producer called a collection absent only when both document keys
    # were absent. The new field is null for exactly that unchanged case.
    expected = {_key(row) for row in rows if row['source'] == 'congress_gov' and any(
        m['document_urls'] or (m.get('collection_states') or {}).get('document_urls') in ('present', 'empty')
        for m in row['meetings'])}
    if len(expected) > stage['limit']:
        raise ValueError('Record-only meeting selection exceeds max_work_items')
    if pq.ParquetFile(selection).metadata.num_rows != len(expected):
        raise ValueError('Meeting selection does not cover the exact document collection predicate')
    rebuilt = _replay('meeting_records', selection, expected, current, **stage)
    replacements = {_key(row): row for row in rebuilt.to_pylist()}
    for row in rows:
        if replacement := replacements.get(_key(row)):
            projected = [{k: v for k, v in m.items() if k != 'document_references'} for m in replacement['meetings']]
            if projected != row['meetings']:
                raise ValueError('Document-reference replay changed existing meeting values: ' + row['record_sha'].hex())
    output = meeting_records.table([replacements.get(_key(row), dict(row, parser_version=current[row['source']])) for row in rows])
    return output, dict(reused_rows=len(rows) - len(expected), appended=len(expected))


# Congress.gov appearance rows are built from inline receipt lines (_record_producer's inline candidates), not
# stored bodies: on 2026-11-11, 36,333 of the lake's 36,438 congress_gov records had no body. The stored-body
# selection below cannot replay them; a congress_gov move goes through the daily or the selective backfill.
INLINE_SOURCES = frozenset({'congress_gov'})


def _moved_sources(current, prior, reviewed):
    """Sources whose producer version moved from the base model's pin; the rest are reused verbatim.

    The base model and this code must name the same sources, at least one must move (replaying nothing
    would re-import an unchanged table), the move must be exactly the spec's reviewed `replay_sources`,
    and none may be a source built from inline receipt lines.
    """
    unexpected = sorted(current.keys() ^ prior.keys())
    if unexpected:
        raise ValueError('Record-only appearances: the base model and this code name different sources: '
                         + ', '.join(unexpected))
    moved = {source for source in current if current[source] != prior[source]}
    if not moved:
        raise ValueError('Record-only appearances: no source producer version moved from the base model')
    if moved != set(reviewed):
        raise ValueError(f'Record-only appearances: moved sources {sorted(moved)} differ from the reviewed '
                         f'replay_sources {sorted(reviewed)}')
    if moved & INLINE_SOURCES:
        raise ValueError('Record-only appearances cannot replay inline-built sources: '
                         + ', '.join(sorted(moved & INLINE_SOURCES)))
    return moved


def _appearances(base, versions, reviewed, *, directory, **stage):
    current = appearance_records.current_versions()
    changed = _moved_sources(current, versions, reviewed)
    current_rows = _base_keys(base, versions, history=True)
    rows = [row for row in current_rows if row['source'] in changed]
    if len(rows) > stage['limit']:
        raise ValueError('Record-only appearance selection exceeds max_work_items')
    selection = directory / 'selection.parquet'
    roots = (stage['raw_root'], stage['mirror'])
    pq.write_table(pa.Table.from_pylist(
        [_body_selection(row['record_sha'], row['source'], roots) for row in rows], schema=SELECTION_SCHEMA), selection)
    replay = _replay('appearance_records', selection, {_key(row) for row in rows}, current, **stage)
    history = {_versioned_key(row) for row in base.select(['record_sha', 'source', 'parser_version']).to_pylist()}
    new = {_versioned_key(row) for row in replay.select(['record_sha', 'source', 'parser_version']).to_pylist()}
    if history & new:
        raise ValueError('Record-only replay overlaps an already retained appearance version')
    output = pa.concat_tables([base, replay], promote_options='default').sort_by([('record_sha', 'ascending'), ('source', 'ascending'), ('parser_version', 'ascending')])
    return output, dict(reused_rows=base.num_rows, appended=replay.num_rows, replayed_sources=sorted(changed))


def _from_captures(name, capture, expected, *, engine, work, raw_root, mirror, unreadable, limit):
    module = CAPTURE_PRODUCERS[name]
    staged = module.stage(captures=capture, engine=engine, work=work, local_root=raw_root,
        raw_store=BodyStore(LocalAdapter(mirror)), unreadable_files=unreadable, max_work_items=limit)
    table = pq.read_table(staged['records'])
    if staged['unreadable_pending'] or table.num_rows != expected:
        raise ValueError(f'Record-only {name} capture count changed or unreadable decisions need review')
    return table, dict(reused_rows=0, appended=table.num_rows)


def _retained_committee_selection(selection, receipt, limit):
    targets = json.loads(selection.read_text())
    if not isinstance(targets, list) or not 0 < len(targets) <= limit:
        raise ValueError('Retained committee selection exceeds its work limit or is empty')
    by_line = {}
    events = {}
    event_ids = set()
    for item in targets:
        if not isinstance(item, dict) or set(item) != {'receipt_line', 'event_id', 'original_path', 'record_sha'}:
            raise ValueError('Retained committee selection requires receipt line, event, path and digest')
        line, event, digest = item['receipt_line'], item['event_id'], item['record_sha']
        if (type(line) is not int or line <= 0 or line in by_line
                or not isinstance(event, str) or not re.fullmatch(r'[0-9]+', event) or event in event_ids
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or digest in events
                or item['original_path'] != f'{HOUSE_XML_PATH}{event}.xml'):
            raise ValueError('Invalid retained committee line, event, path or digest')
        by_line[line] = item
        events[digest] = event
        event_ids.add(event)

    with gzip.open(receipt, 'rb') as stream:
        for number, raw in enumerate(stream, 1):
            if number not in by_line:
                continue
            target = by_line.pop(number)
            line = json.loads(raw)
            path, digest = target['original_path'], target['record_sha']
            reference = dict(status='verified', reference_kind='retained-file', fidelity='retained-file',
                resolution='digest_verified', family='house/meeting-xml', original_path=path, source_file=path,
                sha256=digest, source_sha256=digest, body_key=f'bodies/sha256/{digest[:2]}/{digest}.gz')
            refs = line.get('file_references') if isinstance(line, dict) else None
            if (not isinstance(line, dict) or line.get('captures') != [] or line.get('source_file') != path
                    or line.get('record') != {'original_path': path}
                    or not isinstance(refs, list) or len(refs) != 1
                    or not isinstance(refs[0], dict) or any(refs[0].get(k) != v for k,v in reference.items())):
                raise ValueError(f'Retained committee receipt line {number} does not verify its selected file')
            if not by_line:
                break
    if by_line:
        raise ValueError('Retained committee selection names missing receipt lines')
    return events


def _from_retained_committee(item, model, directory, **stage):
    name = 'committee_records'
    versions = committee_records.current_versions()
    if model['parser_versions'].get(name) != versions:
        raise ValueError('Retained committee input requires the current committee parser pin')
    events = _retained_committee_selection(_verified(item['selection']), _verified(item['receipt']), stage['limit'])
    base = pq.read_table(_verified(item['base']), columns=['record_sha','source','parser_version'])
    expected = {(bytes.fromhex(sha), committee_records.SOURCE) for sha in events}
    if any(_key(row) in expected and row['parser_version'] == versions[committee_records.SOURCE] for row in base.to_pylist()):
        raise ValueError('Retained committee selection overlaps existing current producer rows')
    selection = directory/'selection.parquet'
    pq.write_table(pa.Table.from_pylist(
        [dict(record_sha=sha, source=committee_records.SOURCE, stored_suffix='.gz') for sha in events],
        schema=SELECTION_SCHEMA), selection)
    table = _replay(name, selection, expected, versions, **stage)
    if any(row['event_id'] != events[row['record_sha'].hex()] or not row['records'] for row in table.to_pylist()):
        raise ValueError('Retained committee body does not contain records for its selected event')
    return table, dict(reused_rows=0, appended=table.num_rows, existing_rows_checked=base.num_rows,
        delta_only=True, final_reconciliation_required=True)


def _compose_committee(item, model, base_model):
    """Combine two qualified Parquet inputs without reopening receipts or XML."""
    name = 'committee_records'
    versions = committee_records.current_versions()
    selector = model.get(name)
    if (model['parser_versions'].get(name) != versions or not isinstance(selector, dict)
            or selector.get('kind') != 'native_table' or selector.get('snapshot') is None):
        raise ValueError('Committee composition requires the pinned base selector and current parser')
    base_proof = json.loads(_verified(item['base_producer']).read_text())
    delta_proof = json.loads(_verified(item['delta_producer']).read_text())
    if (not isinstance(base_proof, dict) or base_proof.get('job') != IMPORT
            or base_proof.get('source') != item['base']
            or base_proof.get('verified') != 'EXCEPT ALL both ways against the source file'):
        raise ValueError('Committee composition base must match the verified import source')
    delta_source = delta_proof.get('source') if isinstance(delta_proof, dict) else None
    if (not isinstance(delta_source, dict) or delta_source.get('base') != item['base']
            or delta_proof.get('job') != BACKFILL or delta_proof.get('base_model') != base_model
            or delta_proof.get('delta_only') is not True or delta_proof.get('final_reconciliation_required') is not True
            or delta_proof.get('appended') != item['expected_delta_rows']):
        raise ValueError('Committee composition delta must match the retained backfill and its pinned base')
    selected = {name: selector, 'parser_versions': model['parser_versions']}
    delta_selector = dict(kind='parquet', **item['delta'])
    reasons = snapshot_reasons(selected, {name: base_proof}) + _record_reasons(
        name, delta_proof, selected, None, ROOT, label=f'{name} delta', selector=delta_selector, allow_delta=True)
    if reasons:
        raise ValueError('Committee composition input origin refused: ' + '; '.join(reasons))

    tables = []
    keys = []
    for label in ('base', 'delta'):
        with pq.ParquetFile(_verified(item[label])) as source:
            if (source.metadata.num_rows != item[f'expected_{label}_rows']
                    or not source.schema_arrow.equals(committee_records.ARROW_SCHEMA)):
                raise ValueError(f'Committee composition {label} schema or row count changed')
            table = source.read()
        current = _base_keys(table, versions, history=True)
        if len(current) != table.num_rows:
            raise ValueError(f'Committee composition {label} contains unselected versions')
        tables.append(table)
        keys.append({tuple(row[k] for k in committee_records.PK) for row in current})
    if keys[0] & keys[1]:
        raise ValueError('Committee composition base and delta primary keys overlap')
    base, delta = tables
    return pa.concat_tables(tables), dict(reused_rows=base.num_rows, appended=delta.num_rows)


def execute_record_only(spec, *, runtime_factory=None):
    writer = writer_identity(ROOT, BACKFILL)
    job = spec['record_only']
    model_path = _verified(job['base_model'])
    model = json.loads(model_path.read_text())
    bases = {name: _verified(pin) for name, pin in job['bases'].items()}
    captures = {name: _verified(item['capture']) for name,item in job['capture_inputs'].items()}
    retained = job.get('retained_committee')
    composition = job.get('committee_composition')
    selection = _verified(job['meeting_selection']) if 'meeting_selection' in job else None
    unreadable_files = model['unreadable_files'] if bases or captures or retained is not None else ()
    unreadable = [dict(key=item['key'], path=str(_verified(dict(path=_local(item['path'], model_path.parent),
        sha256=item['sha256'], size=item['size'])))) for item in unreadable_files]
    runtime = json.loads(Path(spec['engine_config']).read_text())
    if {'remote', 'credentials'} & runtime.keys():
        raise ValueError('Record-only backfill requires the local engine and held sources')
    work = Path(spec['work'])
    work.mkdir(parents=True, exist_ok=False)
    report = dict(status='tables_built', executed=True, base_model=job['base_model'], tables={})
    factory = runtime_factory or NativeDatasets.from_config
    with factory(spec['engine_config']) as engine:
        engine.verify_runtime()
        if engine.remote is not None:
            raise ValueError('Record-only backfill requires the local engine and held sources')
        committee = ('committee_records',) if retained is not None or composition is not None else ()
        for name in (*bases, *captures, *committee):
            directory = work / name
            directory.mkdir()
            stage = dict(engine=engine, work=directory/'replay', raw_root=Path(job['raw_root']),
                mirror=Path(job['raw_mirror']), unreadable=unreadable, limit=job['max_work_items'])
            if name in captures:
                item = job['capture_inputs'][name]
                rows, counts = _from_captures(name, captures[name], item['expected_rows'], **stage)
                lineage = dict(source=item['capture'], scope='selected captures')
            elif name == 'committee_records' and composition is not None:
                rows, counts = _compose_committee(composition, model, job['base_model'])
                lineage = dict(source=composition, base_selector=model[name], scope='complete retained committee composition')
            elif name == 'committee_records':
                rows, counts = _from_retained_committee(retained, model, directory, **stage)
                lineage = dict(source=retained, scope='selected retained House meeting XML')
            else:
                base = pq.read_table(bases[name])
                versions = model['parser_versions'][name]
                if name == 'meeting_records':
                    rows, counts = _meetings(base, versions, selection, **stage)
                else:
                    rows, counts = _appearances(base, versions, job['replay_sources'], directory=directory, **stage)
                lineage = dict(source=job['bases'][name], base_selector=model[name])
            output = directory / f'{name}.parquet'
            pq.write_table(rows, output, compression='zstd')
            if not pq.read_table(output).equals(rows) or writer_identity(ROOT, BACKFILL) != writer:
                raise ValueError(f'Record-only {name} output or writer identity changed')
            selector = dict(kind='parquet', path=str(output), **file_pin(output))
            producer_path = directory/'producer.json'
            proof = record(producer_path, input=name, selector=selector, job=BACKFILL)
            proof.update(recorded='with production', base_model=job['base_model'], **lineage, **counts)
            if name == 'meeting_records':
                proof['selection'] = job['meeting_selection']
            producer_path.write_text(json.dumps(proof, indent=2, sort_keys=True)+'\n')
            report['tables'][name] = dict(selector=selector, producer=dict(path=str(producer_path), **file_pin(producer_path)), **counts)
    (work/'record-only-report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    return report
