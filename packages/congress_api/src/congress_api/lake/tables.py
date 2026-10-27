"""Thin application binding to C7 jobs and C2 guarded native table appends."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.provenance import file_pin


def _identifier(value):
    if not isinstance(value,str) or re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',value) is None:
        raise ValueError('Lake SQL identifiers must be explicit simple names')
    return '"'+value+'"'


def _literal(value):
    return "'"+str(value).replace("'","''")+"'"


def _job(engine, work, *, catalog_root, inputs=(), operations=()):
    work=Path(work).resolve()
    work.mkdir(parents=True,exist_ok=False)
    spec=dict(scratch=str(work/'native'),catalog_root=str(Path(catalog_root).resolve()),
        inputs=list(inputs),steps=[],outputs=[],table_operations=list(operations))
    path=work/'job.json'
    path.write_text(json.dumps(spec,indent=2)+'\n')
    result=engine.run_job(path)
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def create_table(*,engine,work,catalog_root,table,schema,location,create_namespace=False,
                 partition_spec=None):
    """Explicit creation, never treating an existing table as successful create."""
    operations=[]
    if create_namespace:
        operations.append(dict(kind='create_namespace',name='namespace',
                               namespace=table['namespace'],properties={}))
    operation=dict(kind='create',name='create',table=table,location=str(Path(location).resolve()),
        schema=schema,format_version=2,properties={'gc.enabled':'true','commit.retry.num-retries':'0'})
    if partition_spec is not None:
        operation['partition_spec']=partition_spec
    operations.append(operation)
    return _job(engine,work,catalog_root=catalog_root,operations=operations)


def append_rows(source, *, engine,work,catalog_root,table,keys,definition,
                file_bytes=128<<20,row_group_rows=8192,row_group_bytes=32<<20):
    """Recompute missing keys inside the engine on each catalog conflict.

    Immutable source bytes and writer definition plus the sorted selected keys
    identify the whole work. Sorting the keys costs O(K log K); the anti-join is
    expected O(N+M). Python neither joins rows nor retries a table commit.
    """
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
    operation=dict(kind='append',name='append',table=table,current_table='existing',
        work_table='pending',sql='SELECT incoming.* FROM incoming LEFT ANTI JOIN existing ON '+join,
        identity_sql=identity_sql,
        layout=dict(file_bytes=file_bytes,row_group_rows=row_group_rows,row_group_bytes=row_group_bytes))
    result=_job(engine,work,catalog_root=catalog_root,
        inputs=[dict(name='incoming',kind='parquet',path=str(source))],operations=[operation])
    return result['table_operations'][0]
