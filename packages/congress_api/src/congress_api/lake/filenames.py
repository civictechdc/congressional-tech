"""Bound filename parser, native source work lists and typed lake row staging."""
from datetime import date
import json
from pathlib import Path
import re

import house_naming
from house_naming import Engine
from house_naming.errors import NamingError
import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake.versions import version_digest
from congress_api.retention.provenance import field, json_input, list_of, struct, parquet_output, run_job


ROOT = Path(__file__).resolve().parents[5]
SQL = ROOT / 'model/sql/effective-filenames.sql'
PARAMETERS = ROOT / 'model/registries/filename-parameters.json'
PK = ['filename', 'source_url', 'catalog_version']
MAX_FILENAME_BYTES = 16384
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
        'filename_parameters': root/'model/registries/filename-parameters.json'},
        values={'vocabularies': vocabularies or {}})


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
    package = stem if (one('package_family') in {'BILLS', 'CHRG', 'CRPT', 'CPRT'}
        and any(match.get('canonical_filename', '').rsplit('.', 1)[0].lower() == stem.lower()
                for match in result.get('matches', []))) else None
    return dict(valid=bool(result['valid']),
        **{name: list(metadata.get(name, [])) for name in ('document_kind', 'document_family', 'committee_code')},
        congress=congress, date_token=one('date_token'), measure_type=one('measure_type'),
        measure_number=one('measure_number'),
        filename_date=_day(one('meeting_date')) if metadata.get('meeting_date')
            else _day(one('date_token_candidates')),
        measure_keys=sorted(keys), bioguide_ids=sorted(set(metadata.get('bioguide_token', [])
            + metadata.get('sponsor_bioguide_id', []))), package_id=package,
        fields=[dict(field=name, value=value) for name, values in sorted(metadata.items()) for value in values])


def read_filename(filename, source_url, *, catalog_version, parser=None, vocabularies=None):
    """Read one independent source name, preserving ambiguity and stable errors."""
    row = dict(filename=filename, source_url=source_url or '', catalog_version=catalog_version,
        status='completed', error_type=None, valid=False, document_kind=[], document_family=[],
        committee_code=[], congress=None, date_token=None, measure_type=None, measure_number=None,
        filename_date=None, measure_keys=[], bioguide_ids=[], package_id=None, fields=[])
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


def _work_inputs(captures, recovery_files, existing, work):
    inputs = [dict(name='captures', kind='parquet', path=str(Path(captures).resolve()))]
    if recovery_files:
        inputs.append(dict(name='recoveries', kind='json_lines', files=recovery_files,
            schema=dict(fields=[field(name, 'Utf8') for name in
                ('id', 'original_url', 'body_sha256', 'recovered_filename', 'kind', 'decided_at', 'supersedes')], metadata={})))
    else:
        inputs.append(json_input(work, 'recoveries', [], id='Utf8', original_url='Utf8',
                                 body_sha256='Utf8', recovered_filename='Utf8', kind='Utf8', decided_at='Utf8', supersedes='Utf8'))
    params = json.loads(PARAMETERS.read_text())
    priorities = [row['priority'] for row in params]
    names = [row['parameter'] for row in params]
    if len(set(priorities)) != len(params) or len(set(names)) != len(params):
        raise ValueError('Filename parameter registry has duplicate names or priorities')
    inputs.append(json_input(work, 'filename_parameters', params, priority='Int32', parameter='Utf8'))
    if existing:
        inputs.append(dict(name='existing', kind='parquet', path=str(Path(existing).resolve())))
    return inputs


def stage(*, captures, recovery_files, engine, work, existing=None, catalog_version=None,
          vocabularies=None):
    """Stage native missing pairs and local parser rows; does not commit a lake table."""
    version = current_version(vocabularies=vocabularies)
    if catalog_version is not None and catalog_version != version:
        raise ValueError('Catalog version does not match the current parser and inputs')
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=False)
    inputs = _work_inputs(captures, recovery_files, existing, work)
    steps = [dict(name='current_recoveries', sql='''SELECT * FROM (
        SELECT r.*,row_number() OVER (PARTITION BY original_url,body_sha256
            ORDER BY cast(decided_at AS TIMESTAMP WITH TIME ZONE) DESC,id DESC) AS selected
        FROM recoveries r WHERE NOT EXISTS (SELECT 1 FROM recoveries s WHERE s.supersedes=r.id))
        WHERE selected=1'''),
        dict(name='filename_inputs', sql='''SELECT
        encode(sha256(json_array(receipt_key,receipt_line,capture_index)),'hex') AS input_id,
        CASE WHEN member_path IS NOT NULL THEN cast(NULL AS VARCHAR) ELSE url END AS source_url,
        requested_url,member_path,h_content_disposition,cast(NULL AS VARCHAR) AS recovered_filename,
        false AS recovery_rejected FROM captures WHERE mode='fetch'
        UNION ALL SELECT 'recovery:' || id AS input_id,original_url AS source_url,
        original_url AS requested_url,cast(NULL AS VARCHAR) AS member_path,
        cast(NULL AS VARCHAR) AS h_content_disposition,recovered_filename,
        kind='rejected' AS recovery_rejected FROM current_recoveries'''),
        dict(name='effective_names', sql=SQL.read_text()),
        dict(name='source_pairs', sql="SELECT DISTINCT filename,coalesce(source_url,'') AS source_url FROM effective_names")]
    version_sql = "'" + version.replace("'", "''") + "'"
    missing = (' WHERE NOT EXISTS (SELECT 1 FROM existing e WHERE e.filename=p.filename '
               'AND e.source_url=p.source_url AND e.catalog_version=' + version_sql + ')') if existing else ''
    run_job(work, engine, inputs=inputs, steps=steps,
        outputs=[parquet_output(work, 'work-list', 'SELECT p.* FROM source_pairs p' + missing,
                                ['filename', 'source_url'])])
    parser = Engine()
    parsed = work/'parsed'; parsed.mkdir()
    def rows():
        with pq.ParquetFile(work/'work-list.parquet') as source:
            for batch in source.iter_batches(batch_size=1024):
                for source_row in batch.to_pylist():
                    row = read_filename(source_row['filename'], source_row['source_url'],
                        catalog_version=version, parser=parser, vocabularies=vocabularies)
                    if row['filename_date'] is not None:
                        row['filename_date'] = row['filename_date'].isoformat()
                    yield row
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
    return dict(readings=work/'filename-readings.parquet', work_list=work/'work-list.parquet',
                catalog_version=version)

