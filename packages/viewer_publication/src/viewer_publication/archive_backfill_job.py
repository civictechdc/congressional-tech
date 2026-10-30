"""Plan or execute the bounded archive lake backfill job."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from congress_api.lake.daily import ALL_TABLE_NAMES
from viewer_publication.archive_model_job import _local,provenance_record_kind

FIELDS={'version','bucket','catalog_root','work','tables','batch_size','max_batches'}
OPTIONAL={'engine_config','decided_at','max_work_items'}


def _bucket(value):
    if not isinstance(value,str) or re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',value) is None:
        raise ValueError('Invalid archive bucket')
    return value


def _table_ref(value):
    if (not isinstance(value,dict) or set(value)!={'namespace','name'}
            or not isinstance(value['namespace'],list) or not value['namespace']
            or any(not isinstance(p,str) or not p for p in value['namespace'])
            or not isinstance(value['name'],str) or not value['name']):
        raise ValueError('Invalid lake table reference')
    return dict(namespace=list(value['namespace']),name=value['name'])


def _tables(value):
    if not isinstance(value,dict) or set(value)!=set(ALL_TABLE_NAMES):
        raise ValueError('Backfill job requires all five archive lake table references')
    refs={name:_table_ref(value[name]) for name in ALL_TABLE_NAMES}
    if len({json.dumps(t,sort_keys=True) for t in refs.values()})!=len(refs):
        raise ValueError('Backfill tables must name five distinct explicit targets')
    return refs


def load_spec(path):
    """Validate the committed backfill job specification without opening runtime or storage."""
    path=Path(path).resolve();value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('Backfill job spec must be an object')
    if value.get('status')=='blocked':
        if set(value)!={'status','reason'} or not isinstance(value.get('reason'),str) or not value['reason'].strip():
            raise ValueError('Blocked backfill job requires exactly its reason')
        return dict(value)
    if set(value)-FIELDS-OPTIONAL or not FIELDS<=set(value):
        raise ValueError('Backfill job requires version 1 and all explicit fields')
    if type(value['version']) is not int or value['version']!=1:
        raise ValueError('Backfill job requires version 1')
    base=path.parent
    work=_local(value['work'],base)
    if any(char in work for char in '\r\n\0'):
        raise ValueError('Backfill work path cannot contain control characters')
    catalog_root=value['catalog_root']
    if catalog_root is not None:
        if not isinstance(catalog_root,str) or not catalog_root.strip():
            raise ValueError('Backfill catalog_root must be None or a non-empty string')
        uri=urlsplit(catalog_root)
        if not uri.scheme:catalog_root=_local(catalog_root,base)
    for field_name in ('batch_size','max_batches'):
        number=value[field_name]
        if type(number) is not int or number<=0:
            raise ValueError(f'Backfill {field_name} must be a positive integer')
    result=dict(
        version=1,
        bucket=_bucket(value['bucket']),
        catalog_root=catalog_root,
        work=work,
        tables=_tables(value['tables']),
        batch_size=value['batch_size'],
        max_batches=value['max_batches'],
    )
    if 'engine_config' in value and value['engine_config'] is not None:
        result['engine_config']=_local(value['engine_config'],base)
    if 'decided_at' in value and value['decided_at'] is not None:
        if not isinstance(value['decided_at'],str) or not value['decided_at'].strip():
            raise ValueError('Backfill decided_at must be a non-empty ISO timestamp')
        result['decided_at']=value['decided_at']
    if 'max_work_items' in value and value['max_work_items'] is not None:
        if type(value['max_work_items']) is not int or value['max_work_items']<=0:
            raise ValueError('Backfill max_work_items must be a positive integer')
        result['max_work_items']=value['max_work_items']
    return result


def plan(spec):
    if spec.get('status')=='blocked':return dict(spec)
    return dict(
        status='planned',
        executed=False,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        tables=spec['tables'],
        batch_size=spec['batch_size'],
        max_batches=spec['max_batches'],
    )


def execute(spec,*,runtime_factory=None,storage_factory=None,producer=None):
    """Run bounded lake backfill batches against the configured remote runtime and raw store."""
    if spec.get('status')=='blocked':return dict(spec)
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():
        raise ValueError('Backfill work directory must be fresh')
    engine_config=(spec.get('engine_config')
        or os.environ.get('DOCSPEC_RUNTIME_CONFIG')
        or os.environ.get('DOCSPEC_JOB_CONFIG'))
    if not isinstance(engine_config,str) or not engine_config.strip():
        raise ValueError('Backfill execution requires an explicit engine_config or DOCSPEC_RUNTIME_CONFIG')
    from congress_api.lake.daily import produce_daily
    from congress_api.retention.body_store import BodyStore,R2Adapter
    from congress_api.retention.provenance_inventory import provenance_inventory
    from congress_shared.storage import connect_r2
    from docspec_client.client import NativeDatasets
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    producer=producer or produce_daily
    decided_at=spec.get('decided_at') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with runtime_factory(engine_config) as engine:
        engine.verify_runtime()
        client=storage_factory(bucket=spec['bucket'],retries={'total_max_attempts':1})
        raw_store=BodyStore(R2Adapter(client,spec['bucket']))
        snapshot=provenance_inventory(raw_store,work=work/'provenance')
        full={row['key']:row for row in snapshot.metadata()}
        records=snapshot.qualify([key for key in full if provenance_record_kind(key) is not None])
        provenance={kind:[row for row in records if provenance_record_kind(row['key'])==kind]
            for kind in ('recoveries','reviews','unreadable')}
        daily_spec=dict(
            work=str(work/'producer'),
            decided_at=decided_at,
            catalog_root=spec['catalog_root'],
            tables=spec['tables'],
            receipt_inventory=spec.get('receipt_inventory',[]),
            body_inventory=spec.get('body_inventory',str(work/'body-inventory.parquet')),
            local_root=spec.get('local_root',str(work/'raw')),
            max_work_items=spec.get('max_work_items',spec['batch_size']*spec['max_batches']),
            provenance=provenance,
        )
        production=producer(daily_spec,engine=engine,raw_store=raw_store)
    work.mkdir(parents=True,exist_ok=True)
    report=dict(
        status='executed',
        executed=True,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        production=production,
    )
    (work/'backfill-report.json').write_text(json.dumps(report,sort_keys=True)+'\n',encoding='utf-8')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',action='store_true')
    mode.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':
            print(json.dumps(spec,sort_keys=True))
            return 2
        result=execute(spec) if args.execute else plan(spec)
    except (ValueError,OSError) as error:
        parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
