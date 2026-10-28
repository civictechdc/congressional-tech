"""Bound filename parser, native source work lists and typed lake row staging."""
from datetime import date
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

import house_naming
from house_naming import Engine
from house_naming.errors import NamingError
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.tables import table_input
from congress_api.lake.versions import version_digest
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import field, json_input, list_of, struct, parquet_output, run_job, instant, import_unreadable, finish_stage, imported_unreadable_provenance


ROOT = Path(__file__).resolve().parents[6]
SQL = ROOT / 'model/sql/effective-filenames.sql'
INPUT_SQL = ROOT / 'model/sql/filename-inputs.sql'
PARAMETERS = ROOT / 'model/registries/filename-parameters.json'
TABLE_SCHEMA = ROOT / 'model/lake/filename-readings.schema.json'
PARTITION_SPEC = {'spec-id': 0, 'fields': [{'source-id': 3, 'field-id': 1000,
    'name': 'catalog_version', 'transform': 'identity'}]}
PK = ['filename', 'source_url', 'catalog_version']
MAX_FILENAME_BYTES = 16384
WORKER_INPUT_BYTES = 1 << 20
WORKER_MEMORY_BYTES = 256 << 20
WORKER_TIMEOUT_SECONDS = 5
STRINGS = pa.list_(pa.string())
SCHEMA = pa.schema([
    *[(name, pa.string()) for name in PK],
    ('status', pa.string()), ('error_type', pa.string()), ('valid', pa.bool_()),
    *[(name, STRINGS) for name in ('document_kind', 'document_family', 'committee_code')],
    ('congress', pa.int32()), ('date_token', pa.string()), ('measure_type', pa.string()),
    ('measure_number', pa.string()), ('filename_date', pa.date32()),
    ('measure_keys', STRINGS), ('bioguide_ids', STRINGS), ('package_id', pa.string()),
    ('fields', pa.list_(pa.struct([('field', pa.string()), ('value', pa.string())])))])


def current_version(*, vocabularies=None, root=ROOT):
    root = Path(root)
    return version_digest(packages={'filename_parser': Path(house_naming.__file__).parent,
        'producer': Path(__file__).parent}, files={'lock': root/'uv.lock',
        'effective_filename': root/'model/sql/effective-filenames.sql',
        'filename_inputs': root/'model/sql/filename-inputs.sql',
        'parser_worker': root/'packages/congress_api/src/congress_api/retention/parser_worker.py',
        'process_resources': root/'packages/congress_api/src/congress_api/retention/process_resources.py',
        'filename_parameters': root/'model/registries/filename-parameters.json',
        'lake_schema': root/'model/lake/filename-readings.schema.json'},
        values={'vocabularies': vocabularies or {}})


@lru_cache(maxsize=1)
def _parser():
    return Engine()


@lru_cache(maxsize=4)
def _vocabulary(path, expected_sha):
    data = Path(path).read_bytes()
    if sha256(data).hexdigest() != expected_sha:
        raise ValueError('Filename vocabulary differs from its work pin')
    return json.loads(data)


def parse_payload(payload):
    """Shared worker entry; package initialization and vocabulary reads are cached."""
    payload = json.loads(payload)
    vocabularies = _vocabulary(payload['vocabulary_path'], payload['vocabulary_sha256'])
    row = read_filename(payload['filename'], payload['source_url'], parser=_parser(),
        catalog_version=payload['catalog_version'], vocabularies=vocabularies)
    if row['filename_date'] is not None:
        row['filename_date'] = row['filename_date'].isoformat()
    return row


def _single(values):
    return values[0] if len(values or []) == 1 else None


def _day(value):
    if value is None: return None
    try:
        return date.fromisoformat(value if '-' in value else
                                  value[:4] + '-' + value[4:6] + '-' + value[6:])
    except ValueError:
        return None


def _typed(result, filename):
    metadata = result['metadata']
    one = lambda name: _single(metadata.get(name, []))
    congress = one('congress')
    congress = int(congress) if congress and re.fullmatch(r'[0-9]{1,9}', congress) else None
    measures = list(metadata.get('measure_references', []))
    if one('measure_type') and one('measure_number'):
        measures.append(one('measure_type') + one('measure_number'))
    keys = set()
    if congress is not None:
        for reference in measures:
            match = re.fullmatch(r'(hr|s|hjres|sjres|hconres|sconres|hres|sres)([0-9]+)', reference.lower())
            if match: keys.add(f'{congress}-{match[1]}-{int(match[2])}')
    stem = filename.rsplit('.', 1)[0]
    package = None
    if (one('package_family') or '').upper() in {'BILLS', 'CHRG', 'CRPT', 'CPRT'}:
        package = next((match['canonical_filename'].rsplit('.', 1)[0]
            for match in result.get('matches', [])
            if match.get('canonical_filename', '').rsplit('.', 1)[0].lower() == stem.lower()), None)
    return dict(valid=bool(result['valid']),
        **{name: list(metadata.get(name, [])) for name in ('document_kind', 'document_family', 'committee_code')},
        congress=congress, date_token=one('date_token'), measure_type=one('measure_type'),
        measure_number=one('measure_number'),
        filename_date=_day(one('meeting_date')) if metadata.get('meeting_date')
            else _day(one('date_token_candidates')),
        measure_keys=sorted(keys), bioguide_ids=sorted(set(metadata.get('bioguide_token', [])
            + metadata.get('sponsor_bioguide_id', []))), package_id=package,
        fields=[dict(field=name, value=value) for name, values in sorted(metadata.items()) for value in values])


def _reading(filename, source_url, catalog_version, *, status='completed', error_type=None):
    return dict(filename=filename, source_url=source_url or '', catalog_version=catalog_version,
        status=status, error_type=error_type, valid=False, document_kind=[], document_family=[],
        committee_code=[], congress=None, date_token=None, measure_type=None, measure_number=None,
        filename_date=None, measure_keys=[], bioguide_ids=[], package_id=None, fields=[])


def read_filename(filename, source_url, *, catalog_version, parser=None, vocabularies=None):
    """Read one independent source name, preserving ambiguity and stable errors."""
    row = _reading(filename, source_url, catalog_version)
    try:
        if len(filename.encode('utf-8')) > MAX_FILENAME_BYTES:
            row.update(status='size_limit', error_type='input-too-large')
            return row
        parser = parser or Engine()
        try:
            result = parser.extract(filename, source_url=source_url or None,
                                    member_surnames=(vocabularies or {}).get('member_surnames'))
        except NamingError as error:
            if error.code != 'invalid-source-url': raise
            result = parser.extract(filename, member_surnames=(vocabularies or {}).get('member_surnames'))
        row.update(_typed(result, filename))
    except NamingError as error:
        row.update(status='error', error_type=error.code)
    except UnicodeEncodeError:
        row.update(status='error', error_type='invalid-unicode')
    return row


def _work_inputs(captures, recovery_files, unreadable_files, existing, work):
    inputs = [table_input('captures',captures)]
    if recovery_files:
        inputs.append(dict(name='recoveries', kind='json_lines', files=recovery_files,
            schema=dict(fields=[field(name, 'Utf8') for name in
                ('id', 'original_url', 'body_sha256', 'recovered_filename', 'kind', 'decided_at', 'supersedes')], metadata={})))
    else:
        inputs.append(json_input(work, 'recoveries', [], id='Utf8', original_url='Utf8',
                                 body_sha256='Utf8', recovered_filename='Utf8', kind='Utf8', decided_at='Utf8', supersedes='Utf8'))
    unreadable_schema = dict(fields=[field(name, 'Utf8') for name in
        ('id', 'record_sha', 'parser', 'parser_version', 'supersedes')], metadata={})
    if unreadable_files:
        inputs.append(dict(name='unreadable',kind='json_lines',files=unreadable_files,schema=unreadable_schema))
    else:
        inputs.append(json_input(work, 'unreadable', [], id='Utf8', record_sha='Utf8',
                                 parser='Utf8', parser_version='Utf8', supersedes='Utf8'))
    params = json.loads(PARAMETERS.read_text())
    priorities = [row['priority'] for row in params]
    names = [row['parameter'] for row in params]
    if len(set(priorities)) != len(params) or len(set(names)) != len(params):
        raise ValueError('Filename parameter registry has duplicate names or priorities')
    inputs.append(json_input(work, 'filename_parameters', params, priority='Int32', parameter='Utf8'))
    if existing is not None:
        inputs.append(table_input('existing',existing))
    return inputs


def stage(*, captures, recovery_files, engine, work, decided_at, existing=None, catalog_version=None,
          vocabularies=None, unreadable_files=(), worker_factory=None, unreadable_store=None):
    """Stage native missing pairs and local parser rows; does not commit a lake table."""
    instant(decided_at)
    version = current_version(vocabularies=vocabularies)
    if catalog_version is not None and catalog_version != version:
        raise ValueError('Catalog version does not match the current parser and inputs')
    if worker_factory is None:
        from congress_api.retention.parser_worker import ParserWorker
        worker_factory = ParserWorker
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=False)
    inputs = _work_inputs(captures, recovery_files, unreadable_files, existing, work)
    steps = [dict(name='current_recoveries', sql='''SELECT * FROM (
        SELECT r.*,row_number() OVER (PARTITION BY original_url,body_sha256
            ORDER BY cast(decided_at AS TIMESTAMP WITH TIME ZONE) DESC,id DESC) AS selected
        FROM recoveries r WHERE NOT EXISTS (SELECT 1 FROM recoveries s WHERE s.supersedes=r.id))
        WHERE selected=1'''),
        dict(name='filename_captures', sql='SELECT * FROM captures'),
        dict(name='filename_inputs', sql=INPUT_SQL.read_text()),
        dict(name='effective_names', sql=SQL.read_text()),
        dict(name='distinct_pairs', sql="SELECT DISTINCT filename,coalesce(source_url,'') AS source_url FROM effective_names"),
        dict(name='source_pairs', sql="SELECT *,encode(sha256(json_array(filename,source_url)),'hex') AS input_id FROM distinct_pairs")]
    version_sql = "'" + version.replace("'", "''") + "'"
    missing = (' WHERE NOT EXISTS (SELECT 1 FROM unreadable u WHERE u.record_sha=p.input_id '
        "AND u.parser='filename' AND u.parser_version=" + version_sql +
        ' AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id))')
    if existing is not None:
        missing += (' AND NOT EXISTS (SELECT 1 FROM existing e WHERE e.filename=p.filename '
                    'AND e.source_url=p.source_url AND e.catalog_version=' + version_sql + ')')
    run_job(work, engine, inputs=inputs, steps=steps,
        outputs=[parquet_output(work, 'work-list', 'SELECT p.* FROM source_pairs p' + missing,
                                ['filename', 'source_url'])])
    parsed = work/'parsed'; parsed.mkdir()
    vocabulary_path = parsed/'vocabulary.json'
    vocabulary_bytes = json.dumps(vocabularies or {},ensure_ascii=False,sort_keys=True,
                                  separators=(',', ':'),allow_nan=False).encode('utf-8')
    vocabulary_path.write_bytes(vocabulary_bytes)
    vocabulary_sha = sha256(vocabulary_bytes).hexdigest()
    decisions_path = parsed/'unreadable.jsonl'
    decision_count = 0
    def rows():
        nonlocal decision_count
        with worker_factory('filename',version,'congress_api.lake.filenames:parse_payload',
                timeout_seconds=WORKER_TIMEOUT_SECONDS,memory_bytes=WORKER_MEMORY_BYTES,
                max_input_bytes=WORKER_INPUT_BYTES) as worker, decisions_path.open('x') as decisions:
            with pq.ParquetFile(work/'work-list.parquet') as source:
                for batch in source.iter_batches(batch_size=1024):
                    for item in batch.to_pylist():
                        payload = dict(filename=item['filename'],source_url=item['source_url'],
                            catalog_version=version,vocabulary_path=str(vocabulary_path),
                            vocabulary_sha256=vocabulary_sha)
                        encoded = json.dumps(payload,ensure_ascii=False,separators=(',', ':'),
                                             allow_nan=False).encode('utf-8')
                        outcome = worker.parse(item['input_id'],encoded)
                        if outcome['status'] == 'completed':
                            yield outcome['value']
                        elif outcome['status'] == 'size_limit':
                            yield _reading(item['filename'],item['source_url'],version,
                                status='size_limit',error_type='worker_input_size_limit')
                        elif (outcome['status'] == 'unreadable' and outcome.get('attempts') == 2
                              and isinstance(outcome.get('reason'),str)
                              and re.fullmatch('[a-z][a-z0-9_]*',outcome['reason'])):
                            identity = json.dumps([item['input_id'],version,decided_at],separators=(',', ':'))
                            record = dict(id=sha256(identity.encode()).hexdigest(),record_sha=item['input_id'],
                                parser='filename',parser_version=version,reason=outcome['reason'],
                                decided_by='filename_readings',decided_at=decided_at,supersedes=None)
                            decisions.write(json.dumps(record,separators=(',', ':'))+'\n')
                            decision_count += 1
                        else:
                            raise ValueError('Invalid filename worker result')
    fields = {name: 'Utf8' for name in
        (*PK, 'status', 'error_type', 'date_token', 'measure_type', 'measure_number',
         'filename_date', 'package_id')}
    fields.update(valid='Boolean', congress='Int32', fields=list_of(struct(field='Utf8', value='Utf8')))
    fields.update({name: list_of('Utf8') for name in
        ('document_kind', 'document_family', 'committee_code', 'measure_keys', 'bioguide_ids')})
    source = json_input(parsed, 'parsed_readings', rows(), **fields)
    columns = ["cast(filename_date AS DATE) AS filename_date" if name == 'filename_date'
               else name for name in SCHEMA.names]
    run_job(parsed, engine, inputs=[source], steps=[], outputs=[parquet_output(work,
        'filename-readings', 'SELECT ' + ','.join(columns) + ' FROM parsed_readings', PK)])
    unreadable_key = unreadable_path = unreadable_stage = unreadable_provenance = unreadable_custody = None
    pending = bool(decision_count and unreadable_store is None)
    if decision_count:
        if pending:
            unreadable_stage=work/'unreadable-stage';unreadable_stage.mkdir()
            imported=import_unreadable(BodyStore(LocalAdapter(unreadable_stage)),decisions_path,decided_at=decided_at)
            unreadable_path=str(unreadable_stage/imported['key'])
            finish_stage(unreadable_stage,kind='unreadable',provenance=imported['key'],
                records=decision_count,inputs={},extra=dict(decided_at=decided_at))
        else:
            imported=import_unreadable(unreadable_store,decisions_path,decided_at=decided_at)
            unreadable_provenance,unreadable_custody=imported_unreadable_provenance(imported,unreadable_store,decisions_path)
        unreadable_key=imported['key']
    return dict(readings=work/'filename-readings.parquet', work_list=work/'work-list.parquet',
        catalog_version=version,unreadable_key=unreadable_key,unreadable_path=unreadable_path,
        unreadable_stage=unreadable_stage,unreadable_pending=pending,
        unreadable_provenance=unreadable_provenance,_unreadable_custody=unreadable_custody)

def create_table(*, engine, work, catalog_root, table, location, create_namespace=False):
    from congress_api.lake.tables import create_table as native_create
    return native_create(engine=engine, work=work, catalog_root=catalog_root, table=table,
        schema=json.loads(TABLE_SCHEMA.read_text()), location=location,
        create_namespace=create_namespace, partition_spec=PARTITION_SPEC)


def append(staged, *, engine, work, catalog_root, table):
    if staged.get('unreadable_pending'):
        raise ValueError('Pending unreadable decisions require durable import: '
            '.venv/bin/python -I -m congress_api.cli.provenance --stage '+str(staged['unreadable_stage'])+' --apply --bucket congressional-tech-raw')
    from congress_api.lake.tables import append_rows
    version = staged['catalog_version']
    # The staged content version is part of every work key and writer identity.
    return append_rows(staged['readings'], engine=engine, work=work, catalog_root=catalog_root,
        table=table, keys=PK, definition='filename_readings:' + version)


def main(argv=None, *, worker_factory=None,engine_factory=None):
    import argparse
    from docspec_client.client import NativeDatasets
    from congress_api.lake.tables import validate_catalog_authority
    parser = argparse.ArgumentParser(description='Stage missing filename readings through native jobs')
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--recovery-inventory', type=Path, required=True,
                        help='Pinned JSON list of {key,path} provenance recovery files')
    parser.add_argument('--existing', type=Path)
    parser.add_argument('--engine-config', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--vocabularies', type=Path)
    parser.add_argument('--unreadable-inventory', type=Path)
    parser.add_argument('--decided-at', required=True)
    parser.add_argument('--apply', action='store_true', help='Append through the selected native catalog')
    parser.add_argument('--catalog-root', type=Path,
                        help='Local catalog authority; omit for an explicitly configured remote engine')
    parser.add_argument('--table', help='Explicit namespace.table for native append')
    parser.add_argument('--create-table', action='store_true')
    parser.add_argument('--table-location',help='Local table path or exact remote object URI')
    parser.add_argument('--create-namespace', action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.table:
        parser.error('--apply requires --table')
    if args.create_table and (not args.apply or args.table_location is None):
        parser.error('--create-table requires --apply and --table-location')
    if args.create_namespace and not args.create_table:
        parser.error('--create-namespace requires --create-table')
    table = None
    if args.apply:
        identifiers = args.table.split('.')
        if len(identifiers) < 2 or any(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', part) is None
                                      for part in identifiers):
            parser.error('--table must be an explicit namespace.table')
        table = dict(namespace=identifiers[:-1], name=identifiers[-1])
    engine=(engine_factory or NativeDatasets.from_config)(args.engine_config)
    if args.apply:
        try:
            validate_catalog_authority(engine,args.catalog_root)
        except ValueError as error:
            parser.error(str(error))
    recovery_files = json.loads(args.recovery_inventory.read_text())
    vocabularies = json.loads(args.vocabularies.read_text()) if args.vocabularies else None
    result = stage(captures=args.captures, recovery_files=recovery_files,
        engine=engine, work=args.work,
        existing=args.existing, vocabularies=vocabularies,decided_at=args.decided_at,
        unreadable_files=json.loads(args.unreadable_inventory.read_text()) if args.unreadable_inventory else [],
        worker_factory=worker_factory)
    if args.apply:
        if result['unreadable_pending']:
            parser.error('Pending unreadable decisions require durable import: '
                '.venv/bin/python -I -m congress_api.cli.provenance --stage '+str(result['unreadable_stage'])+' --apply --bucket congressional-tech-raw')
        if args.create_table:
            create_table(engine=engine,
                work=args.work/'create', catalog_root=args.catalog_root, table=table,
                location=args.table_location, create_namespace=args.create_namespace)
        result['append'] = append(result, engine=engine,
            work=args.work/'append', catalog_root=args.catalog_root, table=table)
    print(json.dumps(result, default=str, sort_keys=True))
    return 0

