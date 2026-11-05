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
OPTIONAL={'engine_config','decided_at','max_work_items','body_inventory','receipt_inventory','local_root','selective','resume','through','producers'}


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


EXPLORER_TABLE_NAMES=('video_records','committee_records')


def _tables(value):
    # The five archive tables, and optionally both Explorer tables (built by the selective job).
    if not isinstance(value,dict) or set(value) not in (set(ALL_TABLE_NAMES),set(ALL_TABLE_NAMES)|set(EXPLORER_TABLE_NAMES)):
        raise ValueError('Backfill job requires all five archive lake table references, and both Explorer tables or neither')
    refs={name:_table_ref(value[name]) for name in value}
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
    if 'body_inventory' in value and value['body_inventory'] is not None:
        result['body_inventory']=_local(value['body_inventory'],base)
    if 'local_root' in value and value['local_root'] is not None:
        result['local_root']=_local(value['local_root'],base)
    if 'receipt_inventory' in value and value['receipt_inventory'] is not None:
        if not isinstance(value['receipt_inventory'],list) or any(not isinstance(item,dict) for item in value['receipt_inventory']):
            raise ValueError('Backfill receipt_inventory must be a list of objects')
        result['receipt_inventory']=list(value['receipt_inventory'])
    if 'resume' in value and type(value['resume']) is not bool:
        raise ValueError('Backfill resume must be boolean')
    result['resume']=value.get('resume',False)
    if 'selective' in value:
        from viewer_publication.archive_selective import validate_selective
        result['selective']=validate_selective(value['selective'],base=base,catalog_root=catalog_root,tables=result['tables'])
    elif result['resume'] or 'through' in value or set(result['tables'])&set(EXPLORER_TABLE_NAMES):
        raise ValueError('Only a selective backfill can resume, stop early or build the Explorer tables')
    if 'through' in value:
        from viewer_publication.archive_selective import THROUGH
        if value['through'] not in THROUGH:raise ValueError('Selective through must be tables or model')
        result['through']=value['through']
    if 'producers' in value:
        from viewer_publication.archive_publish_job import _metadata_pin
        if not isinstance(value['producers'],dict) or not value['producers']:
            raise ValueError('Backfill producers must map each anchored table to its record pin')
        result['producers']={name:_metadata_pin(pin,base) for name,pin in value['producers'].items()}
    elif catalog_root is None and 'selective' not in value:
        # Gate 5: a head this job moves without a record refuses every later publish.
        raise ValueError('A daily backfill of the R2 lake requires the producer anchors the publisher pins')
    return result


def _json_path(value):
    if isinstance(value,Path):return str(value)
    raise TypeError('Object of type '+type(value).__name__+' is not JSON serializable')


def _dumps(value):
    return json.dumps(value,sort_keys=True,default=_json_path)


def plan(spec):
    if spec.get('status')=='blocked':return dict(spec)
    planned=dict(
        status='planned',
        executed=False,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        tables=spec['tables'],
        batch_size=spec['batch_size'],
        max_batches=spec['max_batches'],
    )
    if 'selective' in spec:
        planned.update(where=spec['selective']['where'],base=spec['selective']['base'],resume=spec['resume'])
    return planned


def execute(spec,*,runtime_factory=None,storage_factory=None,producer=None):
    """Run bounded lake backfill batches against the configured remote runtime and raw store."""
    if spec.get('status')=='blocked':return dict(spec)
    if 'selective' in spec:
        from viewer_publication.archive_selective import execute_selective
        return execute_selective(spec,runtime_factory=runtime_factory)
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
    from congress_api.retention.r2 import configure_read_retries
    from congress_shared.storage import connect_r2
    from docspec_client.client import NativeDatasets
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    producer=producer or produce_daily
    decided_at=spec.get('decided_at') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with runtime_factory(engine_config) as engine:
        engine.verify_runtime()
        # Body GETs retry transient R2 server errors and throttling; writes keep one attempt.
        client=configure_read_retries(storage_factory(bucket=spec['bucket'],retries={'total_max_attempts':1}))
        raw_store=BodyStore(R2Adapter(client,spec['bucket']))
        snapshot=provenance_inventory(raw_store,work=work/'provenance')
        decision_kinds=('recoveries','reviews','unreadable')
        records=snapshot.qualify(row['key'] for row in snapshot.metadata()
            if provenance_record_kind(row['key']) in decision_kinds)
        provenance={kind:[row for row in records if provenance_record_kind(row['key'])==kind]
            for kind in decision_kinds}
        daily_spec=dict(
            work=str(work/'producer'),
            decided_at=decided_at,
            catalog_root=spec['catalog_root'],
            tables=spec['tables'],
            receipt_inventory=spec.get('receipt_inventory',[]),
            max_work_items=spec.get('max_work_items',spec['batch_size']*spec['max_batches']),
            provenance=provenance,
            # A pinned inventory only if the spec names one; otherwise bodies come from raw_store.
            **{k:spec[k] for k in ('body_inventory','local_root') if spec.get(k) is not None},
        )
        records=None
        if 'producers' in spec:
            from congress_api.lake.producer_records import ProducerRecords
            from viewer_publication.archive_publish_job import _verify_metadata
            anchors={}
            for name,pin in spec['producers'].items():
                identity=_verify_metadata(pin);anchors[name]=Path(pin['path']).read_bytes();identity.require(pin['path'])
            records=ProducerRecords(anchors,client=client,bucket=spec['bucket'])
        production=producer(daily_spec,engine=engine,raw_store=raw_store,producer_records=records)
    work.mkdir(parents=True,exist_ok=True)
    report=dict(
        status='executed',
        executed=True,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        production=production,
    )
    (work/'backfill-report.json').write_text(_dumps(report)+'\n',encoding='utf-8')
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
            print(_dumps(spec))
            return 2
        result=execute(spec) if args.execute else plan(spec)
    except (ValueError,OSError) as error:
        parser.error(str(error))
    print(_dumps(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
