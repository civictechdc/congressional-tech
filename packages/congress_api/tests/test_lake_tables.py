"""D1/D3 append through C7; a second run closes no already-complete work."""
import os

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from docspec_client.client import NativeDatasets


def test_native_table_creation_and_repeated_append(tmp_path):
    from congress_api.lake.tables import create_table, append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1],
            'fields':[{'id':1,'name':'receipt_key','required':True,'type':'string'},
                      {'id':2,'name':'value','required':False,'type':'long'}]}
    table=dict(namespace=['archive'],name='captures_v1')
    create_table(engine=engine,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'data',create_namespace=True)
    source=tmp_path/'source.parquet'
    pq.write_table(pa.table({'receipt_key':['one','two'],'value':[1,2]}),source)
    first=append_rows(source,engine=engine,work=tmp_path/'first',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert sum(f['rows'] for f in first['files'])==2
    second=append_rows(source,engine=engine,work=tmp_path/'second',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert second['files']==[] and second['metadata_location']==first['metadata_location']
    more=tmp_path/'more.parquet'
    pq.write_table(pa.table({'receipt_key':['two','three'],'value':[2,3]}),more)
    third=append_rows(more,engine=engine,work=tmp_path/'third',catalog_root=tmp_path/'catalog',
        table=table,keys=['receipt_key'],definition='mapping-v1')
    assert sum(f['rows'] for f in third['files'])==1
    assert third['table_uuid']==first['table_uuid']
    assert third['snapshot']!=first['snapshot']


@pytest.mark.parametrize('binary_type,iceberg_type', [
    (pa.binary(32),'fixed[32]'), (pa.binary(),'binary')])
def test_compound_binary_work_key_appends_and_repeats_as_noop(tmp_path,binary_type,iceberg_type):
    """D2 body digests remain binary in storage and identify native pending work."""
    from congress_api.lake.tables import create_table, append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1,2],
        'fields':[{'id':1,'name':'body_sha','required':True,'type':iceberg_type},
                  {'id':2,'name':'parser_version','required':True,'type':'string'},
                  {'id':3,'name':'value','required':False,'type':'long'}]}
    table=dict(namespace=['archive'],name='body_readings')
    create_table(engine=engine,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'data',create_namespace=True)
    arrow_schema=pa.schema([('body_sha',binary_type),('parser_version',pa.string()),('value',pa.int64())])
    source=tmp_path/'source.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(body_sha=b'a'*32,parser_version='v1',value=1),
        dict(body_sha=b'a'*32,parser_version='v2',value=2)],schema=arrow_schema),source)
    kwargs=dict(engine=engine,catalog_root=tmp_path/'catalog',table=table,
                keys=['body_sha','parser_version'],definition='body-reader-v1')
    first=append_rows(source,work=tmp_path/'first',**kwargs)
    assert sum(f['rows'] for f in first['files'])==2
    second=append_rows(source,work=tmp_path/'second',**kwargs)
    assert second['files']==[] and second['metadata_location']==first['metadata_location']
    more=tmp_path/'more.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(body_sha=b'a'*32,parser_version='v2',value=2),
        dict(body_sha=b'b'*32,parser_version='v1',value=3)],schema=arrow_schema),more)
    third=append_rows(more,work=tmp_path/'third',**kwargs)
    assert sum(f['rows'] for f in third['files'])==1
    stored=pa.concat_tables([pq.read_table(f['path']) for f in first['files']+third['files']])
    assert set(zip(stored['body_sha'].to_pylist(),stored['parser_version'].to_pylist()))=={
        (b'a'*32,'v1'),(b'a'*32,'v2'),(b'b'*32,'v1')}


def test_append_refuses_null_required_field(tmp_path):
    """Gate 4 at the lake: a NULL in a required (non-key) field never commits.

    Characterization pin: the pinned engine already refuses the batch, so
    append_rows adds no second NULL scan. Parquet-kind model inputs never pass
    through append_rows, so this cannot see NULLs in them.
    """
    from congress_api.lake.tables import create_table, append_rows
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    schema={'type':'struct','schema-id':0,'identifier-field-ids':[1],
            'fields':[{'id':1,'name':'receipt_key','required':True,'type':'string'},
                      {'id':2,'name':'mode','required':True,'type':'string'}]}
    table=dict(namespace=['archive'],name='captures_null')
    create_table(engine=engine,work=tmp_path/'create',catalog_root=tmp_path/'catalog',
        table=table,schema=schema,location=tmp_path/'data',create_namespace=True)
    source=tmp_path/'source.parquet'
    pq.write_table(pa.table({'receipt_key':['one','two'],'mode':['fetch',None]}),source)
    from docspec_client.models import DocSpecFailure
    with pytest.raises(DocSpecFailure, match="Column 'mode' is declared as non-nullable but contains null values"):
        append_rows(source,engine=engine,work=tmp_path/'append',catalog_root=tmp_path/'catalog',
            table=table,keys=['receipt_key'],definition='mapping-v1')


def _schema_field_ids(kind, prefix=''):
    if not isinstance(kind, dict):
        return []
    if kind.get('type') == 'struct':
        children = [(field['name'], field['id'], field['type']) for field in kind['fields']]
    elif kind.get('type') == 'list':
        children = [('element', kind['element-id'], kind['element'])]
    elif kind.get('type') == 'map':
        children = [('key', kind['key-id'], kind['key']), ('value', kind['value-id'], kind['value'])]
    else:
        return []
    out = []
    for name, ident, sub in children:
        out.append((prefix + name, ident))
        out.extend(_schema_field_ids(sub, prefix + name + '.'))
    return out


def test_every_declared_lake_schema_matches_its_created_iceberg_field_ids(tmp_path):
    """Every model/lake/*.schema.json must state the exact Iceberg field IDs create_table assigns (ct-tx7u)."""
    import gzip
    import json
    from pathlib import Path
    from congress_api.lake.tables import create_table

    root = Path(__file__).resolve().parents[3]
    schemas = sorted((root / 'model/lake').glob('*.schema.json'))
    assert len(schemas) >= 9
    mismatches = {}
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        for index, schema_path in enumerate(schemas):
            declared = json.loads(schema_path.read_text(encoding='utf-8'))
            table_name = schema_path.name.removesuffix('.schema.json').replace('-', '_')
            created = create_table(
                engine=engine,
                work=tmp_path / f'create-{table_name}',
                catalog_root=tmp_path / 'catalog',
                table=dict(namespace=['archive'], name=table_name),
                schema=declared,
                location=tmp_path / 'data' / table_name,
                create_namespace=(index == 0),
            )
            meta_loc = created['table_operations'][-1]['metadata_location'].removeprefix('file://')
            raw = Path(meta_loc).read_bytes()
            metadata = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
            actual = next(s for s in metadata['schemas'] if s['schema-id'] == metadata['current-schema-id'])
            declared_ids = dict(_schema_field_ids(declared))
            actual_ids = dict(_schema_field_ids(actual))
            declared_ident = set(declared.get('identifier-field-ids', ()))
            actual_ident = set(actual.get('identifier-field-ids', ()))
            if (
                declared['fields'] != actual['fields']
                or declared_ids != actual_ids
                or declared_ident != actual_ident
            ):
                diffs = {
                    path: (declared_ids.get(path), actual_ids.get(path))
                    for path in list(dict.fromkeys([*declared_ids, *actual_ids]))
                    if declared_ids.get(path) != actual_ids.get(path)
                }
                if declared_ident != actual_ident:
                    diffs['identifier-field-ids'] = (sorted(declared_ident), sorted(actual_ident))
                if not diffs:
                    diffs['fields'] = (declared['fields'], actual['fields'])
                mismatches[schema_path.name] = diffs
    assert mismatches == {}


def test_record_table_declared_schemas_preserve_created_iceberg_and_arrow_equivalence(tmp_path):
    """ct-tx7u equivalence guard: record schemas create identical Iceberg schemas regardless of input ID numbering."""
    import copy
    import gzip
    import json
    from pathlib import Path
    from congress_api.lake import (
        appearance_records,
        committee_records,
        daily,
        meeting_records,
        playlist_records,
        tables,
        video_records,
    )

    def _renumber_depth_first(kind, counter):
        if not isinstance(kind, dict):
            return kind
        out = copy.deepcopy(kind)
        if out.get('type') == 'struct':
            for field in out['fields']:
                field['id'] = next(counter)
                field['type'] = _renumber_depth_first(field['type'], counter)
        elif out.get('type') == 'list':
            out['element-id'] = next(counter)
            out['element'] = _renumber_depth_first(out['element'], counter)
        elif out.get('type') == 'map':
            out['key-id'] = next(counter)
            out['key'] = _renumber_depth_first(out['key'], counter)
            out['value-id'] = next(counter)
            out['value'] = _renumber_depth_first(out['value'], counter)
        return out

    producers = {
        'appearance_records': appearance_records.ARROW_SCHEMA,
        'committee_records': committee_records.ARROW_SCHEMA,
        'meeting_records': meeting_records.ARROW_SCHEMA,
        'playlist_records': playlist_records.ARROW_SCHEMA,
        'video_records': video_records.ARROW_SCHEMA,
    }
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        for index, (name, arrow_schema) in enumerate(producers.items()):
            declared = tables.load_schema(name)
            legacy_dfs = _renumber_depth_first(declared, iter(range(1, 10_000)))
            assert daily._iceberg_field_paths(declared) == daily._arrow_field_paths(pa.struct(arrow_schema)) == daily.writer_field_paths(name)
            assert daily._iceberg_field_paths(legacy_dfs) == daily._iceberg_field_paths(declared)
            c_new = tables.create_table(
                engine=engine,
                work=tmp_path / f'new-{name}',
                catalog_root=tmp_path / 'catalog',
                table=dict(namespace=['archive'], name=f'{name}_new'),
                schema=declared,
                location=tmp_path / 'data' / f'{name}_new',
                create_namespace=(index == 0),
            )
            c_old = tables.create_table(
                engine=engine,
                work=tmp_path / f'old-{name}',
                catalog_root=tmp_path / 'catalog',
                table=dict(namespace=['archive'], name=f'{name}_old'),
                schema=legacy_dfs,
                location=tmp_path / 'data' / f'{name}_old',
                create_namespace=False,
            )

            def _read_schema(created):
                loc = created['table_operations'][-1]['metadata_location'].removeprefix('file://')
                raw = Path(loc).read_bytes()
                meta = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
                return next(s for s in meta['schemas'] if s['schema-id'] == meta['current-schema-id'])

            s_new, s_old = _read_schema(c_new), _read_schema(c_old)
            assert s_new['fields'] == s_old['fields'] == declared['fields']
            assert set(s_new['identifier-field-ids']) == set(s_old['identifier-field-ids']) == set(declared['identifier-field-ids'])


def test_mods_style_two_column_addition_evolves_lake_table_in_place_and_filters_nullable_lists(tmp_path):
    """ct-auhc + ct-ly88: add two optional MODS columns (`title`, `created`) without a new table, keep old snapshots
    readable, append rows carrying the new fields, and filter nullable list columns (`held_dates IS [NOT] NULL`)."""
    import copy
    from congress_api.lake import tables
    from congress_api.retention.provenance import query, query_result
    from docspec_client.models import DocSpecFailure

    full_schema = tables.load_schema('appearance_records')
    initial_schema = copy.deepcopy(full_schema)
    initial_schema['fields'] = [
        f for f in full_schema['fields'] if f['name'] not in {'title', 'created', 'committees', 'committee_members'}
    ]
    catalog = tmp_path / 'catalog'
    table_ref = dict(namespace=['archive'], name='appearance_records')

    appearance_struct = pa.struct([
        pa.field('source_locator', pa.string(), nullable=False),
        pa.field('name_key', pa.string()),
        pa.field('name', pa.string()),
        pa.field('honorific', pa.string()),
        pa.field('given', pa.string()),
        pa.field('middle', pa.string()),
        pa.field('family', pa.string()),
        pa.field('suffix', pa.string()),
        pa.field('position', pa.string()),
        pa.field('organization', pa.string()),
        pa.field('on_behalf_of', pa.string()),
        pa.field('location', pa.string()),
        pa.field('panel', pa.string()),
        pa.field('panel_order', pa.int32()),
        pa.field('display_order', pa.int32()),
        pa.field('witness_type', pa.string()),
        pa.field('testified', pa.bool_()),
        pa.field('bioguide_id', pa.string()),
        pa.field('document_links', pa.list_(pa.field('item', pa.string(), nullable=False)), nullable=False),
    ])
    base_fields = [
        pa.field('record_sha', pa.binary(32), nullable=False),
        pa.field('parser_version', pa.string(), nullable=False),
        pa.field('status', pa.string(), nullable=False),
        pa.field('error_type', pa.string()),
        pa.field('source', pa.string(), nullable=False),
        pa.field('event_id', pa.int64()),
        pa.field('package_id', pa.string()),
        pa.field('declared_base', pa.string()),
        pa.field('collection_state', pa.string()),
        pa.field('appearances', pa.list_(pa.field('item', appearance_struct, nullable=False)), nullable=False),
        pa.field('held_dates', pa.list_(pa.field('item', pa.string(), nullable=False))),
    ]

    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        tables.create_table(
            engine=engine,
            work=tmp_path / 'create',
            catalog_root=catalog,
            table=table_ref,
            schema=initial_schema,
            location=tmp_path / 'lake',
            create_namespace=True,
        )
        old_stage = tmp_path / 'old.parquet'
        pq.write_table(
            pa.Table.from_pylist(
                [
                    dict(
                        record_sha=b'\x01' * 32,
                        parser_version='mods-v1',
                        status='completed',
                        error_type=None,
                        source='govinfo_mods',
                        event_id=None,
                        package_id='CHRG-118shrg55101',
                        declared_base=None,
                        collection_state='complete',
                        appearances=[],
                        held_dates=None,
                    )
                ],
                schema=pa.schema(base_fields),
            ),
            old_stage,
        )
        first = tables.append_rows(
            old_stage,
            engine=engine,
            work=tmp_path / 'append-old',
            catalog_root=catalog,
            table=table_ref,
            keys=['record_sha', 'source', 'parser_version'],
            definition='mods-appearance-v1',
        )
        old_pin = {k: first[k] for k in ('metadata_location', 'table_uuid', 'snapshot', 'schema_id')}
        assert old_pin['schema_id'] == 0

        added = tables.add_optional_columns(
            engine=engine,
            work=tmp_path / 'add-cols',
            catalog_root=catalog,
            table=table_ref,
            expected_schema_id=0,
            columns=[
                dict(name='title', type='string', doc='MODS hearing title'),
                dict(name='created', type='string'),
            ],
        )
        assert added['table_uuid'] == old_pin['table_uuid']
        assert added['previous_schema_id'] == 0 and added['schema_id'] == 1
        assert [c['name'] for c in added['added_columns']] == ['title', 'created']
        assert [c['field_id'] for c in added['added_columns']] == [34, 35]

        # Repeating all-present columns is an idempotent no-op even on a stale expected_schema_id;
        # adding a new column on a stale expected_schema_id refuses with stale_authority;
        # re-adding an existing column with a conflicting type refuses with schema_mismatch.
        noop = tables.add_optional_columns(
            engine=engine,
            work=tmp_path / 'add-cols-noop',
            catalog_root=catalog,
            table=table_ref,
            expected_schema_id=1,
            columns=[dict(name='title', type='string'), dict(name='created', type='string')],
        )
        assert noop['added_columns'] == [] and noop['schema_id'] == noop['previous_schema_id'] == 1
        noop_stale = tables.add_optional_columns(
            engine=engine,
            work=tmp_path / 'add-cols-noop-stale',
            catalog_root=catalog,
            table=table_ref,
            expected_schema_id=0,
            columns=[dict(name='title', type='string'), dict(name='created', type='string')],
        )
        assert noop_stale['added_columns'] == [] and noop_stale['schema_id'] == 1
        with pytest.raises(DocSpecFailure, match='stale_authority'):
            tables.add_optional_columns(
                engine=engine,
                work=tmp_path / 'add-cols-stale',
                catalog_root=catalog,
                table=table_ref,
                expected_schema_id=0,
                columns=[dict(name='extra', type='string')],
            )
        with pytest.raises(DocSpecFailure, match='schema_mismatch'):
            tables.add_optional_columns(
                engine=engine,
                work=tmp_path / 'add-cols-conflict',
                catalog_root=catalog,
                table=table_ref,
                expected_schema_id=1,
                columns=[dict(name='title', type='long')],
            )

        evolved_stage = tmp_path / 'new.parquet'
        pq.write_table(
            pa.Table.from_pylist(
                [
                    dict(
                        record_sha=b'\x02' * 32,
                        parser_version='mods-v2',
                        status='completed',
                        error_type=None,
                        source='govinfo_mods',
                        event_id=None,
                        package_id='CHRG-118shrg55102',
                        declared_base=None,
                        collection_state='complete',
                        appearances=[],
                        held_dates=['2024-05-14'],
                        title='Oversight of Agency Operations',
                        created='2024-09-01',
                    )
                ],
                schema=pa.schema([*base_fields, pa.field('title', pa.string()), pa.field('created', pa.string())]),
            ),
            evolved_stage,
        )
        second = tables.append_rows(
            evolved_stage,
            engine=engine,
            work=tmp_path / 'append-new',
            catalog_root=catalog,
            table=table_ref,
            keys=['record_sha', 'source', 'parser_version'],
            definition='mods-appearance-v2',
        )
        new_pin = {k: second[k] for k in ('metadata_location', 'table_uuid', 'snapshot', 'schema_id')}
        assert new_pin['table_uuid'] == old_pin['table_uuid'] and new_pin['schema_id'] == 1

        # Old snapshot still reads with its original 11-column schema; new head reads both rows with NULL fill.
        old_cols, old_rows = query_result(engine, 'SELECT * FROM t', dict(t=old_pin))
        assert 'title' not in old_cols and 'created' not in old_cols and len(old_rows) == 1
        assert old_rows[0]['package_id'] == 'CHRG-118shrg55101'

        head_rows = query(
            engine,
            'SELECT package_id, title, created, held_dates FROM t ORDER BY package_id',
            dict(t=new_pin),
        )
        assert head_rows == [
            dict(package_id='CHRG-118shrg55101', title=None, created=None, held_dates=None),
            dict(
                package_id='CHRG-118shrg55102',
                title='Oversight of Agency Operations',
                created='2024-09-01',
                held_dates=['2024-05-14'],
            ),
        ]
        # ct-ly88: IS NULL / IS NOT NULL on nullable list column `held_dates` pushes cleanly without accessor failure.
        assert query(engine, 'SELECT package_id FROM t WHERE held_dates IS NULL', dict(t=new_pin)) == [
            dict(package_id='CHRG-118shrg55101')
        ]
        assert query(engine, 'SELECT package_id FROM t WHERE held_dates IS NOT NULL', dict(t=new_pin)) == [
            dict(package_id='CHRG-118shrg55102')
        ]
        # table_columns preserves schema order on pins (including empty tables) without scanning rows.
        assert tables.table_columns(engine, tmp_path / 'cols-old', old_pin) == [f.name for f in base_fields]
        assert tables.table_columns(engine, tmp_path / 'cols-new', new_pin) == [
            *[f.name for f in base_fields],
            'title',
            'created',
        ]
        empty_ref = dict(namespace=['archive'], name='empty_appearances')
        empty_created = tables.create_table(
            engine=engine,
            work=tmp_path / 'create-empty',
            catalog_root=catalog,
            table=empty_ref,
            schema=initial_schema,
            location=tmp_path / 'lake-empty',
            create_namespace=False,
        )['table_operations'][-1]
        empty_pin = {
            'metadata_location': empty_created['metadata_location'],
            'table_uuid': empty_created['table_uuid'],
            'snapshot': None,
            'schema_id': empty_created['schema_id'],
        }
        assert tables.table_columns(engine, tmp_path / 'cols-empty', empty_pin) == [f.name for f in base_fields]


def test_add_optional_columns_validates_inputs(tmp_path):
    from congress_api.lake import tables

    base = dict(
        engine=None,
        work=tmp_path / 'work',
        catalog_root=tmp_path / 'cat',
        table=dict(namespace=['archive'], name='t'),
        expected_schema_id=0,
        columns=[dict(name='title', type='string')],
    )
    with pytest.raises(ValueError, match='expected_schema_id'):
        tables.add_optional_columns(**{**base, 'expected_schema_id': True})
    with pytest.raises(ValueError, match='expected_schema_id'):
        tables.add_optional_columns(**{**base, 'expected_schema_id': -1})
    with pytest.raises(ValueError, match='at least one column'):
        tables.add_optional_columns(**{**base, 'columns': []})
    with pytest.raises(ValueError, match='dict of name, type'):
        tables.add_optional_columns(**{**base, 'columns': [dict(name='title', type='string', required=False)]})
    with pytest.raises(ValueError, match='Lake SQL identifiers'):
        tables.add_optional_columns(**{**base, 'columns': [dict(name='bad-name', type='string')]})
    with pytest.raises(ValueError, match='primitive Iceberg type'):
        tables.add_optional_columns(**{**base, 'columns': [dict(name='title', type='')]})
    with pytest.raises(ValueError, match='doc must be a string'):
        tables.add_optional_columns(**{**base, 'columns': [dict(name='title', type='string', doc=123)]})

