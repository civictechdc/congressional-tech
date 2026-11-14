"""Thin application binding to C7 jobs and C2 guarded native table appends."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.provenance import file_pin

ROOT = Path(__file__).resolve().parents[5]
PART_LAYOUT = dict(file_bytes=128 << 20, row_group_rows=100_000, row_group_bytes=32 << 20)
WRITER_PROFILES = {
    'part': dict(
        compression_codec='zstd',
        compression_level=3,
        row_group_rows=100_000,
        layout=PART_LAYOUT,
    ),
}
LAKE_SCHEMA_PATHS = {
    'captures': ROOT / 'model/lake/captures.schema.json',
    'readings': ROOT / 'model/lake/readings.schema.json',
    'filename_readings': ROOT / 'model/lake/filename-readings.schema.json',
    'meeting_records': ROOT / 'model/lake/meeting-records.schema.json',
    'appearance_records': ROOT / 'model/lake/appearance-records.schema.json',
    'video_records': ROOT / 'model/lake/video-records.schema.json',
    'committee_records': ROOT / 'model/lake/committee-records.schema.json',
    'playlist_records': ROOT / 'model/lake/playlist-records.schema.json',
    'transcript_headings': ROOT / 'model/lake/transcript-headings.schema.json',
}
TABLE_SPECS = {
    'captures': dict(
        schema_path=LAKE_SCHEMA_PATHS['captures'],
        primary_key=('receipt_key', 'receipt_line', 'capture_index'),
        sort_key=('receipt_key', 'receipt_line', 'capture_index'),
        writer_profile='part',
        row_group_rows=100_000,
    ),
    'readings': dict(
        schema_path=LAKE_SCHEMA_PATHS['readings'],
        primary_key=('body_sha', 'parser', 'parser_version'),
        sort_key=('body_sha', 'parser', 'parser_version'),
        writer_profile='part',
        row_group_rows=100_000,
    ),
    'filename_readings': dict(
        schema_path=LAKE_SCHEMA_PATHS['filename_readings'],
        primary_key=('filename', 'source_url', 'catalog_version'),
        sort_key=('filename', 'source_url', 'catalog_version'),
        writer_profile='part',
        row_group_rows=100_000,
    ),
    'meeting_records': dict(
        schema_path=LAKE_SCHEMA_PATHS['meeting_records'],
        primary_key=('record_sha', 'source', 'parser_version'),
        sort_key=('record_sha', 'source', 'parser_version'),
        writer_profile='part',
        row_group_rows=100_000,
    ),
    **{name: dict(
        schema_path=LAKE_SCHEMA_PATHS[name],
        primary_key=('record_sha', 'source', 'parser_version'),
        sort_key=('record_sha', 'source', 'parser_version'),
        writer_profile='part',
        row_group_rows=100_000,
    ) for name in ('appearance_records', 'video_records', 'committee_records', 'playlist_records', 'transcript_headings')},
}


def load_schema(name, *, root=ROOT):
    key = name.replace('-', '_')
    if key not in LAKE_SCHEMA_PATHS:
        raise ValueError(f'Unknown lake schema: {name}')
    path = Path(root) / 'model/lake' / LAKE_SCHEMA_PATHS[key].name
    return json.loads(path.read_text())


def table_spec(name, *, root=ROOT):
    key = name.replace('-', '_')
    if key not in TABLE_SPECS:
        raise ValueError(f'Unknown lake table: {name}')
    spec = dict(TABLE_SPECS[key])
    spec['schema_path'] = Path(root) / 'model/lake' / spec['schema_path'].name
    spec['schema'] = load_schema(key, root=root)
    return spec


def _identifier(value):
    if not isinstance(value,str) or re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',value) is None:
        raise ValueError('Lake SQL identifiers must be explicit simple names')
    return '"'+value+'"'


def _literal(value):
    return "'"+str(value).replace("'","''")+"'"


def validate_catalog_authority(engine,catalog_root):
    """Require one native authority, without opening its catalog or objects."""
    local=catalog_root is not None
    remote=engine.remote is not None
    if local==remote:
        raise ValueError('Exactly one local or explicitly configured remote catalog is required')
    return str(Path(catalog_root).resolve()) if local else None


def _job(engine, work, *, catalog_root, inputs=(), operations=()):
    catalog=validate_catalog_authority(engine,catalog_root)
    work=Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    spec=dict(scratch=str(work/'native'),
        inputs=list(inputs),steps=[],outputs=[],table_operations=list(operations))
    if catalog is not None:
        spec['catalog_root']=catalog
    path=work/'job.json'
    path.write_text(json.dumps(spec,indent=2)+'\n')
    result=engine.run_job(path)
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def table_input(name,source):
    """Bind a local stage or exact immutable native table, without exporting it."""
    _identifier(name)
    if isinstance(source,dict):
        fields={'metadata_location','table_uuid','snapshot','schema_id'}
        if (set(source)!=fields or any(not isinstance(source[k],str) or not source[k]
                for k in ('metadata_location','table_uuid'))
                or type(source['schema_id']) is not int or source['schema_id']<0
                or (source['snapshot'] is not None and
                    (type(source['snapshot']) is not int or source['snapshot']<0))):
            raise ValueError('Native input requires an exact immutable table pin')
        return dict(name=name,kind='native_table',**source)
    return dict(name=name,kind='parquet',path=str(Path(source).resolve()))


def resolve_tables(*,engine,work,catalog_root,tables):
    """Resolve current immutable pins in one read-only native catalog job."""
    if not isinstance(tables,dict) or not tables:
        raise ValueError('Resolve requires explicit named tables')
    for name in tables:_identifier(name)
    result=_job(engine,work,catalog_root=catalog_root,operations=[
        dict(kind='resolve',name=name,table=table) for name,table in tables.items()])
    rows=result.get('table_operations')
    if (not isinstance(rows,list) or len(rows)!=len(tables)
            or any(not isinstance(r,dict) or r.get('name') not in tables for r in rows)
            or len({r['name'] for r in rows})!=len(tables)):
        raise ValueError('Malformed native table head results')
    pins={}
    for row in rows:
        name=row['name']
        if row.get('exists') is False:
            raise ValueError(name+' table does not exist')
        if row.get('exists') is not True:
            raise ValueError('Malformed native table head for '+name)
        pin={key:row.get(key) for key in ('metadata_location','table_uuid','snapshot','schema_id')}
        try:table_input(name,pin)
        except ValueError:raise ValueError('Malformed native table head for '+name) from None
        pins[name]=pin
    return pins


def create_table(*,engine,work,catalog_root,table,schema,location,create_namespace=False,
                 partition_spec=None):
    """Explicit creation, never treating an existing table as successful create."""
    operations=[]
    if create_namespace:
        operations.append(dict(kind='create_namespace',name='namespace',
                               namespace=table['namespace'],properties={}))
    target=str(location) if engine.remote is not None else str(Path(location).resolve())
    operation=dict(kind='create',name='create',table=table,location=target,
        schema=schema,format_version=2,properties={'gc.enabled':'true','commit.retry.num-retries':'0'})
    if partition_spec is not None:
        operation['partition_spec']=partition_spec
    operations.append(operation)
    return _job(engine,work,catalog_root=catalog_root,operations=operations)


def add_optional_columns(*,engine,work,catalog_root,table,expected_schema_id,columns):
    """Add optional primitive top-level columns while the table's head is `expected_schema_id` (ct-auhc).

    The engine assigns fresh Iceberg field IDs above `highest_field_id`, reports an idempotent no-op
    when every requested column already exists with the same optional type (even on a stale
    `expected_schema_id`), and otherwise refuses a stale head (`stale_authority`)."""
    if type(expected_schema_id) is not int or expected_schema_id<0:
        raise ValueError('add_optional_columns requires a non-negative integer expected_schema_id')
    if not isinstance(columns,(list,tuple)) or not columns:
        raise ValueError('add_optional_columns requires at least one column specification')
    normalized=[]
    for item in columns:
        if not isinstance(item,dict) or not {'name','type'}<=set(item)<={'name','type','doc'}:
            raise ValueError('Each optional column must be a dict of name, type and optional doc')
        _identifier(item['name'])
        if not isinstance(item['type'],str) or not item['type']:
            raise ValueError('Each optional column requires a primitive Iceberg type name')
        entry=dict(name=item['name'],type=item['type'])
        if item.get('doc') is not None:
            if not isinstance(item['doc'],str):
                raise ValueError('Optional column doc must be a string')
            entry['doc']=item['doc']
        normalized.append(entry)
    operation=dict(kind='add_columns',name='add_columns',table=table,
                   expected_schema_id=expected_schema_id,columns=normalized)
    return _job(engine,work,catalog_root=catalog_root,operations=[operation])['table_operations'][0]


def append_rows(source, *, engine,work,catalog_root,table,keys,definition,
                file_bytes=128<<20,row_group_rows=8192,row_group_bytes=32<<20):
    """Recompute missing keys inside the engine on each catalog conflict.

    Immutable source bytes and writer definition plus the sorted selected keys
    identify the whole work. Sorting the keys costs O(K log K); the anti-join is
    expected O(N+M). Python neither joins rows nor retries a table commit.
    """
    validate_catalog_authority(engine,catalog_root)
    source=Path(source).resolve()
    if not keys or not isinstance(definition,str) or not definition:
        raise ValueError('Append requires work keys and an explicit writer definition')
    quoted=[_identifier(k) for k in keys]
    source_pin=file_pin(source)
    writer_definition=json.dumps(dict(definition=definition,keys=keys,
        source_revision=engine.source_revision,binary_sha256=engine.binary_sha256,
        layout=dict(file_bytes=file_bytes,row_group_rows=row_group_rows,row_group_bytes=row_group_bytes)),
        sort_keys=True,separators=(',',':')).encode()
    writer=sha256(writer_definition+Path(__file__).read_bytes()).hexdigest()
    identity_prefix=source_pin['sha256']+':'+writer+':'
    schema=pq.read_schema(source)
    # JSON has no binary scalar. Encode only binary-typed identity fields as
    # lowercase hex; storage and the native anti-join retain the original type.
    identity_fields=[]
    for key,q in zip(keys,quoted):
        kind=schema.field(key).type
        binary=(pa.types.is_binary(kind) or pa.types.is_large_binary(kind)
                or pa.types.is_fixed_size_binary(kind))
        identity_fields.append(f"encode(cast({q} AS BYTEA),'hex')" if binary else q)
    key_json='json_array('+','.join(identity_fields)+')'
    # Source hash covers all values; the native sorted key hash covers which
    # immutable rows remain work after a concurrent append or maintenance commit.
    identity_sql=(f'SELECT concat({_literal(identity_prefix)},encode(sha256('
        f"string_agg(DISTINCT {key_json},'' ORDER BY {key_json})),'hex')) AS identity FROM pending")
    join=' AND '.join(f'(incoming.{q} IS NOT DISTINCT FROM existing.{q})' for q in quoted)
    # Both joins build on the left. First keep incoming keys that already exist,
    # then reject those keys while streaming incoming payloads. Even duplicated
    # stored keys cannot enlarge the builds; existing history only streams.
    incoming_keys=','.join(f'incoming.{q}' for q in quoted)
    matching_keys=f'(SELECT {incoming_keys} FROM incoming LEFT SEMI JOIN existing ON {join})'
    operation=dict(kind='append',name='append',table=table,current_table='existing',
        work_table='pending',sql=f'SELECT incoming.* FROM {matching_keys} existing RIGHT ANTI JOIN incoming ON '+join,
        identity_sql=identity_sql,
        layout=dict(file_bytes=file_bytes,row_group_rows=row_group_rows,row_group_bytes=row_group_bytes))
    result=_job(engine,work,catalog_root=catalog_root,
        inputs=[dict(name='incoming',kind='parquet',path=str(source))],operations=[operation])
    return result['table_operations'][0]


def table_columns(engine, work, source):
    """Column names of a Parquet file or an exact native table pin, in schema order."""
    if not isinstance(source, dict):
        return pq.read_schema(source).names
    from congress_api.retention.provenance import query_result
    return query_result(engine, 'SELECT * FROM t LIMIT 0', {'t': source}, work=work)[0]


def column_differential(engine, work, old, new, *, keys, compared, value_columns=(), predicate_sql='true',
                        new_predicate_sql=None, derived=None):
    """Join two tables on `keys` once, both ways, and report each column's changes.

    `predicate_sql` selects rows (alias c) on both sides, unless `new_predicate_sql` gives the
    new side its own; `derived` adds named boolean
    or scalar expressions over the same alias before comparison. Returns the joined
    row count, rows only on either side, a change count for every compared column, and
    (column, old, new, rows) value pairs for `value_columns`. One hash join and one
    narrow grouped pass per value column over the materialized join: O(N) expected.
    """
    derived = dict(derived or {})
    extra = ''.join(f',({sql}) AS "{name}"' for name, sql in derived.items())
    same = ' AND '.join(f'(o."{k}" IS NOT DISTINCT FROM n."{k}")' for k in keys)
    present = f'o_present AND n_present'
    side = lambda alias, table, predicate: (f'SELECT c.*{extra},true AS {alias}_present FROM {table} c '
                                            f'WHERE coalesce(({predicate}),false)')
    selected = ','.join([f'o."{keys[0]}" IS NOT NULL AS o_present', f'n."{keys[0]}" IS NOT NULL AS n_present']
        + [f'o."{c}" IS DISTINCT FROM n."{c}" AS "d_{c}"' for c in compared]
        + [f'cast(o."{c}" AS VARCHAR) AS "o_{c}",cast(n."{c}" AS VARCHAR) AS "n_{c}"' for c in value_columns])
    steps = [dict(name='o_rows', sql=side('o', 'old', predicate_sql)),
             dict(name='n_rows', sql=side('n', 'new', predicate_sql if new_predicate_sql is None else new_predicate_sql)),
             dict(name='joined', sql=f'SELECT {selected} FROM o_rows o FULL JOIN n_rows n ON {same}', materialize=True)]
    counts = ['count(*) AS total', 'count(*) FILTER (WHERE NOT n_present) AS only_old',
              'count(*) FILTER (WHERE NOT o_present) AS only_new']
    counts += [f'count(*) FILTER (WHERE {present} AND "d_{c}") AS "{c}"' for c in compared]
    pairs = ' UNION ALL '.join(
        f"""SELECT '{c}' AS "column","o_{c}" AS old,"n_{c}" AS new,count(*) AS rows FROM joined
            WHERE {present} AND "d_{c}" GROUP BY "o_{c}","n_{c}\"""" for c in value_columns)
    queries = [dict(name='counts', sql='SELECT ' + ','.join(counts) + ' FROM joined')]
    if value_columns:
        queries.append(dict(name='pairs', sql=f'SELECT * FROM ({pairs}) ORDER BY "column",old,new'))
    from congress_api.retention.provenance import run_job
    result = run_job(work, engine, inputs=[table_input('old', old), table_input('new', new)],
                     steps=steps, outputs=[], queries=queries)
    row = result['counts'][0]
    return dict(rows=row['total'], only_old=row['only_old'], only_new=row['only_new'],
                changes={c: row[c] for c in compared},
                pairs=[(p['column'], p['old'], p['new'], p['rows']) for p in result.get('pairs', [])])
