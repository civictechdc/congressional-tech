"""Replay the reviewed meeting and appearance changes into importable Parquet files."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import appearance_records, committee_records, meeting_records, playlist_records
from congress_api.lake._record_producer import _candidate_rel_paths
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import file_pin
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model_job import _local, _pin
from viewer_publication.archive_selective_records import SELECTION_SCHEMA, stage_selected_records
from viewer_publication.producer_proof import BACKFILL, ROOT, record

FILE = {'path', 'size', 'sha256'}
RECORD_TABLES = {'meeting_records', 'appearance_records'}
CAPTURE_PRODUCERS = {'committee_records': committee_records, 'playlist_records': playlist_records}
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
    if not isinstance(job, dict) or not fields <= job.keys() or job.keys() - fields - {'meeting_selection', 'capture_inputs'}:
        raise ValueError('Record-only backfill requires pinned bases, raw locations and a work limit')
    if not isinstance(job['bases'], dict) or job['bases'].keys() - RECORD_TABLES:
        raise ValueError('Record-only backfill bases must name meeting_records or appearance_records')
    if ('meeting_records' in job['bases']) != ('meeting_selection' in job):
        raise ValueError('Meeting backfill requires its exact source selection')
    if type(job['max_work_items']) is not int or job['max_work_items'] <= 0:
        raise ValueError('Record-only backfill requires a positive max_work_items')

    def local_pin(pin):
        _pin(pin, FILE)
        return dict(pin, path=_local(pin['path'], base))

    captures = job.get('capture_inputs', {})
    if not isinstance(captures, dict) or captures.keys() - CAPTURE_PRODUCERS.keys():
        raise ValueError('Record-only capture inputs must name committee_records or playlist_records')
    if not captures and not job['bases']:
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


def _appearances(base, versions, *, directory, **stage):
    current = appearance_records.current_versions()
    changed = {source for source in current if current[source] != versions.get(source)}
    if changed != {'mods', 'senate_page'} or current.keys() != versions.keys():
        raise ValueError('Record-only appearances requires the MODS and Senate page transition')
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
    return output, dict(reused_rows=base.num_rows, appended=replay.num_rows)


def _from_captures(name, capture, expected, *, engine, work, raw_root, mirror, unreadable, limit):
    module = CAPTURE_PRODUCERS[name]
    staged = module.stage(captures=capture, engine=engine, work=work, local_root=raw_root,
        raw_store=BodyStore(LocalAdapter(mirror)), unreadable_files=unreadable, max_work_items=limit)
    table = pq.read_table(staged['records'])
    if staged['unreadable_pending'] or table.num_rows != expected:
        raise ValueError(f'Record-only {name} capture count changed or unreadable decisions need review')
    return table, dict(reused_rows=0, appended=table.num_rows)


def execute_record_only(spec, *, runtime_factory=None):
    writer = writer_identity(ROOT, BACKFILL)
    job = spec['record_only']
    model_path = _verified(job['base_model'])
    model = json.loads(model_path.read_text())
    bases = {name: _verified(pin) for name, pin in job['bases'].items()}
    captures = {name: _verified(item['capture']) for name,item in job['capture_inputs'].items()}
    selection = _verified(job['meeting_selection']) if 'meeting_selection' in job else None
    unreadable = [dict(key=item['key'], path=str(_verified(dict(path=_local(item['path'], model_path.parent),
        sha256=item['sha256'], size=item['size'])))) for item in model['unreadable_files']]
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
        for name in (*bases, *captures):
            directory = work / name
            directory.mkdir()
            stage = dict(engine=engine, work=directory/'replay', raw_root=Path(job['raw_root']),
                mirror=Path(job['raw_mirror']), unreadable=unreadable, limit=job['max_work_items'])
            if name in captures:
                item = job['capture_inputs'][name]
                rows, counts = _from_captures(name, captures[name], item['expected_rows'], **stage)
                lineage = dict(source=item['capture'], scope='selected captures')
            else:
                base = pq.read_table(bases[name])
                versions = model['parser_versions'][name]
                if name == 'meeting_records':
                    rows, counts = _meetings(base, versions, selection, **stage)
                else:
                    rows, counts = _appearances(base, versions, directory=directory, **stage)
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
