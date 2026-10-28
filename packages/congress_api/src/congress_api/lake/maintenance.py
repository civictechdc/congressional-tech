"""Application-owned lake rebuilds; native jobs move, compare and purge rows.

No generation is selected here. The caller can select the returned immutable
pin after equality succeeds, and separately supplies all kept input records
before requesting a purge. Raw objects are never inputs to a deletion.
"""
from math import isfinite
from pathlib import Path
from uuid import UUID

import pyarrow.parquet as pq

from congress_api.lake.tables import (
    _identifier, _job, append_rows, create_table, validate_catalog_authority,
)
from congress_api.retention.provenance import parquet_output, run_job


METRICS=('file_count','manifest_count','scan_planning_seconds')
PIN_FIELDS={'kind','metadata_location','table_uuid','snapshot','schema_id'}


def maintenance_decision(observations,thresholds):
    """Return exceeded metrics using a policy supplied from real measurements.

    Counts must be integers; elapsed seconds can be fractional. Equality does
    not cross a threshold. No production policy values are supplied by code.
    """
    for values in (observations,thresholds):
        if not isinstance(values,dict) or set(values)!=set(METRICS):
            raise ValueError('Maintenance needs all three explicit measured metrics')
        for metric,value in values.items():
            if (isinstance(value,bool) or not isinstance(value,(int,float))
                    or (isinstance(value,float) and not isfinite(value)) or value<0
                    or (metric!='scan_planning_seconds' and not isinstance(value,int))):
                raise ValueError('Maintenance metrics must be nonnegative finite numbers')
    return [metric for metric in METRICS if observations[metric]>thresholds[metric]]


def _pin(pin,name):
    if (not isinstance(pin,dict) or set(pin)!=PIN_FIELDS or pin['kind']!='native_table'
            or not isinstance(pin['metadata_location'],str) or not pin['metadata_location']
            or not isinstance(pin['schema_id'],int) or isinstance(pin['schema_id'],bool)
            or pin['schema_id']<0 or (pin['snapshot'] is not None and
                (not isinstance(pin['snapshot'],int) or isinstance(pin['snapshot'],bool)))):
        raise ValueError('Maintenance requires an exact native_table pin')
    try:table_uuid=str(UUID(pin['table_uuid']))
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Maintenance requires a native table UUID') from None
    return dict(pin,name=name,table_uuid=table_uuid)


def _keys(keys):
    if not keys or isinstance(keys,str) or len(set(keys))!=len(keys):
        raise ValueError('Maintenance requires explicit unique primary key fields')
    return [_identifier(key) for key in keys]


def _query(work,engine,*,inputs,queries=(),outputs=()):
    work=Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    return run_job(work,engine,inputs=inputs,steps=[],outputs=list(outputs),queries=queries)


def _pk_query(name,quoted):
    fields=','.join(quoted)
    nulls=' OR '.join(field+' IS NULL' for field in quoted)
    return dict(name=name+'_pk',sql=f'''SELECT count(*) AS invalid FROM (
        SELECT {fields} FROM {name} GROUP BY {fields}
        HAVING count(*)>1 OR {nulls}) invalid_keys''')


def _check_primary_keys(reports):
    if any(rows[0]['invalid'] for name,rows in reports.items() if name.endswith('_pk')):
        raise ValueError('Maintenance refused an invalid primary key')


def verify_generations(old_pin,new_pin,*,keys,engine,work):
    """Refuse unequal typed rows or invalid keys, using native EXCEPT ALL twice.

    Hash grouping/comparison costs expected O(N+M); only two counts and empty
    Parquet schemas reach Python. No values are converted to JSON for equality.
    """
    quoted=_keys(keys)
    inputs=[_pin(old_pin,'old_rows'),_pin(new_pin,'new_rows')]
    work=Path(work).resolve()
    schemas=work/'schemas'
    _query(schemas,engine,inputs=inputs,outputs=[
        parquet_output(schemas,name,f'SELECT * FROM {name} WHERE FALSE',keys)
        for name in ('old_rows','new_rows')])
    if not pq.read_schema(schemas/'old_rows.parquet').equals(
            pq.read_schema(schemas/'new_rows.parquet'),check_metadata=False):
        raise ValueError('Maintenance generations differ in typed schema')
    reports=_query(work/'compare',engine,inputs=inputs,queries=[
        _pk_query('old_rows',quoted),_pk_query('new_rows',quoted),
        dict(name='difference',sql='''SELECT count(*) AS differences FROM (
            (SELECT * FROM old_rows EXCEPT ALL SELECT * FROM new_rows)
            UNION ALL
            (SELECT * FROM new_rows EXCEPT ALL SELECT * FROM old_rows)) delta''')])
    _check_primary_keys(reports)
    if reports['difference'][0]['differences']:
        raise ValueError('Maintenance generations differ in typed rows')


def rebuild_generation(old_pin,*,engine,work,catalog_root,table,schema,location,keys,definition):
    """Build a fresh generation and return its pin only after native equality.

    The immutable source is exported once, ordered by its validated unique PK
    (O(N log N)); the shared append performs the native anti-join. A failure can
    leave an unselected candidate, never an automatically purged old generation.
    """
    validate_catalog_authority(engine,catalog_root)
    quoted=_keys(keys)
    old=_pin(old_pin,'old_rows')
    if not isinstance(definition,str) or not definition:
        raise ValueError('Maintenance requires an explicit source definition')
    fields={field['name']:field for field in schema['fields']}
    if (any(key not in fields or not fields[key]['required'] for key in keys)
            or set(schema.get('identifier-field-ids',[]))!={fields[key]['id'] for key in keys}):
        raise ValueError('Maintenance schema must declare its required primary key')
    work=Path(work).resolve()
    reports=_query(work/'keys',engine,inputs=[old],queries=[_pk_query('old_rows',quoted)])
    _check_primary_keys(reports)
    exported=work/'source'
    _query(exported,engine,inputs=[old],outputs=[
        parquet_output(exported,'rows','SELECT * FROM old_rows',keys)])
    create_table(engine=engine,work=work/'create',catalog_root=catalog_root,
        table=table,schema=schema,location=location)
    result=append_rows(exported/'rows.parquet',engine=engine,work=work/'append',
        catalog_root=catalog_root,table=table,keys=keys,definition=definition)
    pin=dict(kind='native_table',snapshot=result.get('snapshot'),
        **{field:result[field] for field in PIN_FIELDS-{'kind','snapshot'}})
    verify_generations(old_pin,pin,keys=keys,engine=engine,work=work/'verify')
    return pin


def purge_generation(pin,*,table,kept_inputs,engine,work,catalog_root):
    """Purge only an exact unkept native generation, with native UUID/pin guards.

    Every supplied kept release input record is visited, including historical
    input identities of one release. O(P) over their metadata; no raw deletion.
    A UUID match also protects earlier snapshots of the same physical table.
    The caller must collect the full kept set under the maintenance/publish lock.
    """
    selected=_pin(pin,'selected')
    if not isinstance(kept_inputs,(list,tuple)):
        raise ValueError('Maintenance requires all kept release input records')
    def visit(value):
        if isinstance(value,dict):
            if 'metadata_location' in value or value.get('kind')=='native_table':
                kept=_pin({key:value[key] for key in PIN_FIELDS if key in value},'kept')
                if (kept['metadata_location']==selected['metadata_location']
                        or kept['table_uuid']==selected['table_uuid']):
                    raise ValueError('A kept release pins this native generation')
            for child in value.values():visit(child)
        elif isinstance(value,(list,tuple)):
            for child in value:visit(child)
    for record in kept_inputs:
        if not isinstance(record,dict):
            raise ValueError('Maintenance requires kept release input records')
        visit(record)
    return _job(engine,work,catalog_root=catalog_root,operations=[dict(kind='purge',
        name='purge',table=table,table_uuid=selected['table_uuid'],
        metadata_location=selected['metadata_location'])])
