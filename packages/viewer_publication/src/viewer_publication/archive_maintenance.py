"""Validate kept rebuild evidence and retain only old, unkept derived releases.

The weekly caller holds the shared publish/maintenance exclusion. This helper
never lists or deletes raw keys and never selects a lake generation to purge.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from viewer_publication.archive_publish import (NativeArchiveStore,SPICY_PINS,_encoded,
    _read,input_digest,read_pointer,write_spicy_generations)
from viewer_publication.client import require_publication_client
from viewer_publication.receipt_pins import PREFIX


class ArchiveMaintenanceStore:
    """Small metadata SDK operations, without native runtime/config creation."""
    def __init__(self,*,client,bucket):
        require_publication_client(client)
        if not isinstance(bucket,str) or not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):
            raise ValueError('Invalid archive bucket')
        self.client,self.bucket=client,bucket
    def pointer(self):return read_pointer(self.client,bucket=self.bucket)
    def get(self,key):
        NativeArchiveStore._key(key)
        return _read(self.client,self.bucket,key)[0]
    def write_spicy_generations(self,generations):
        return write_spicy_generations(self.client,bucket=self.bucket,generations=generations)
    def inventory(self):
        token=None
        while True:
            request=dict(Bucket=self.bucket,Prefix=PREFIX)
            if token is not None:request['ContinuationToken']=token
            page=self.client.list_objects_v2(**request)
            for item in page.get('Contents',[]):
                _inventory_release(item['Key'])
                yield item
            if not page.get('IsTruncated'):return
            next_token=page.get('NextContinuationToken')
            if not isinstance(next_token,str) or not next_token or next_token==token:
                raise ValueError('Archive listing did not advance')
            token=next_token
    def delete(self,key):
        NativeArchiveStore._key(key)
        return self.client.delete_object(Bucket=self.bucket,Key=key)


def _inventory_release(key):
    if not isinstance(key,str) or not key.startswith(PREFIX):
        raise ValueError('Archive inventory escaped its release prefix')
    release=key[len(PREFIX):].split('/',1)[0]
    if re.fullmatch('[a-f0-9]{64}',release) is None:
        return None  # Old publication namespaces remain outside engine retention.
    NativeArchiveStore._key(key)
    return release


def _release(value):
    if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:
        raise ValueError('Maintenance requires exact release IDs')
    return value


def _time(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Maintenance requires timezone-aware timestamps')
    return value


def _pointer(store):
    value,etag=store.pointer()
    if not isinstance(value,dict) or not isinstance(etag,str) or not etag.strip():
        raise ValueError('Maintenance requires a live pointer and ETag')
    _release(value.get('release_id'))
    if value.get('previous_release_id') is not None:_release(value['previous_release_id'])
    # Detach from an external adapter's mutable object before later comparison.
    return json.loads(json.dumps(value)),etag


class _InventoryEvidence:
    """Index the single inventory and cache each kept metadata GET once."""
    def __init__(self,store,objects):
        self.store,self.objects,self.cache=store,objects,{}
    def keys(self,prefix):
        NativeArchiveStore._key(prefix+'x')
        release=prefix[len(PREFIX):].split('/',1)[0]
        return [key for key in self.objects.get(release,()) if key.startswith(prefix)]
    def get(self,key):
        NativeArchiveStore._key(key)
        if key not in self.cache:self.cache[key]=self.store.get(key)
        return self.cache[key]


def _validate_kept_model(record,receipt_keys):
    from viewer_publication.archive_model_job import TABLES,OPTIONAL_TABLES,_selector
    from viewer_publication.archive_model_profile import profile_record
    snapshots=record['snapshots']
    if (not isinstance(snapshots,dict) or not set(TABLES)<=set(snapshots)
            or not set(snapshots)<=(set(TABLES)|set(OPTIONAL_TABLES))):
        raise ValueError('Kept input requires the complete model table selectors')
    selected={}
    for name,value in snapshots.items():
        if isinstance(value,dict) and value.get('kind')=='native_table' and 'name' in value:
            if value['name']!=name:
                raise ValueError('Kept native selector name differs from its table key')
            value={key:item for key,item in value.items() if key!='name'}
        selected[name]=_selector(value,Path('/'))
    profile=record['profile']
    # None invokes definition hashing in the producer helper. Maintenance must
    # validate recorded definitions, never read the current filesystem instead.
    if not isinstance(profile,dict) or profile.get('file_hashes') is None:
        raise ValueError('Kept model profile requires explicit definition hashes')
    rebuilt=profile_record(**profile,snapshots=selected)
    if rebuilt['profile']!=profile:
        raise ValueError('Kept model profile has unsupported fields')


def maintain_releases(store,*,now,external_pins=(),execute=False):
    """Collect all kept inputs before planning or deleting unkept release keys.

    Inventory work is linear in object count; input identity canonicalizes each
    receipt set in O(R log R), and final deletion sorting costs O(D log D). No
    release assets, raw bodies or lake rows are read. The caller supplies explicit
    external pins and passes returned kept_inputs to D5 guards.
    """
    now=_time(now)
    if isinstance(external_pins,str):raise ValueError('External pins must be release IDs')
    pins={_release(value) for value in external_pins}
    pointer,etag=_pointer(store)
    kept=pins|{pointer['release_id']}
    if pointer.get('previous_release_id') is not None:kept.add(pointer['previous_release_id'])
    objects={};newest={};seen=set();ignored_legacy_objects=0
    for item in store.inventory():
        key=item['Key']
        release=_inventory_release(key)
        if release is None:
            ignored_legacy_objects+=1
            continue
        if key in seen:raise ValueError('Archive inventory repeats an object')
        seen.add(key)
        modified=_time(item['LastModified'])
        objects.setdefault(release,[]).append(key)
        newest[release]=max(newest.get(release,modified),modified)
    evidence=_InventoryEvidence(store,objects)
    from viewer_publication.receipt_pins import kept_input_records
    # Reuse the maintained parse/receipt validation, then validate semantic identity
    # from its already parsed records and receipt keys without more GETs or parses.
    entries,protected=kept_input_records(evidence,sorted(kept))
    records=[]
    for entry in entries:
        record=entry['record']
        try:
            actual=input_digest(receipt_keys=entry['receipt_keys'],provenance=record['provenance'],
                profile=record['profile'],entity_digests=record['entity_digests'])
            if actual!=record['input_digest']:
                raise ValueError('Kept input record differs from its semantic identity')
            _validate_kept_model(record,entry['receipt_keys'])
        except (KeyError,TypeError) as error:
            raise ValueError('Kept input record has an invalid identity shape') from error
        records.append(record)
    cutoff=now-timedelta(days=1)
    delete_keys=sorted(key for release,keys in objects.items()
                       if release not in kept and newest[release]<cutoff for key in keys)
    spicy_pairs=sorted({(family,digest) for record in records
                        for family,digest in (record.get('entity_digests') or {}).items()})
    spicy_generations=[dict(family=family,digest=digest) for family,digest in spicy_pairs]
    if execute and (delete_keys or spicy_generations):
        if _pointer(store)!=(pointer,etag):
            raise ValueError('Live pointer changed before maintenance deletion')
        if spicy_generations:
            if callable(getattr(store,'write_spicy_generations',None)):
                store.write_spicy_generations(spicy_generations)
            elif callable(getattr(store,'create',None)):
                store.create(SPICY_PINS,_encoded(dict(version=1,generations=spicy_generations)))
        for key in delete_keys:
            # Keep the destructive boundary self-contained even for injected stores.
            NativeArchiveStore._key(key)
            if key[len(PREFIX):].split('/',1)[0] in kept:
                raise ValueError('Maintenance cannot delete a kept release')
            store.delete(key)
    return dict(status='executed' if execute else 'planned',pointer=pointer,pointer_etag=etag,
        kept_releases=sorted(kept),kept_inputs=records,protected_keys=sorted(protected),delete_keys=delete_keys,
        spicy_generations=spicy_generations,ignored_legacy_objects=ignored_legacy_objects)


JOB_FIELDS={'version','bucket','catalog_root','work','external_pins','tables','thresholds'}
JOB_OPTIONAL={'engine_config','raw_verification','lake_maintenance'}


def load_spec(path):
    """Validate the committed maintenance job specification without opening runtime or storage."""
    from congress_api.lake.daily import ALL_TABLE_NAMES
    from congress_api.lake.maintenance import METRICS,maintenance_decision
    from viewer_publication.archive_backfill_job import _tables
    from viewer_publication.archive_model_job import _local
    path=Path(path).resolve();value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('Maintenance job spec must be an object')
    if value.get('status')=='blocked':
        if set(value)!={'status','reason'} or not isinstance(value.get('reason'),str) or not value['reason'].strip():
            raise ValueError('Blocked maintenance job requires exactly its reason')
        return dict(value)
    if set(value)-JOB_FIELDS-JOB_OPTIONAL or not JOB_FIELDS<=set(value):
        raise ValueError('Maintenance job requires version 1 and all explicit fields')
    if type(value['version']) is not int or value['version']!=1:
        raise ValueError('Maintenance job requires version 1')
    bucket=value['bucket']
    if not isinstance(bucket,str) or not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):
        raise ValueError('Invalid archive bucket')
    base=path.parent
    work=_local(value['work'],base)
    if any(char in work for char in '\r\n\0'):
        raise ValueError('Maintenance work path cannot contain control characters')
    catalog_root=value['catalog_root']
    if catalog_root is not None:
        if not isinstance(catalog_root,str) or not catalog_root.strip():
            raise ValueError('Maintenance catalog_root must be None or a non-empty string')
        uri=urlsplit(catalog_root)
        if not uri.scheme:catalog_root=_local(catalog_root,base)
    external_pins=value['external_pins']
    if not isinstance(external_pins,list):
        raise ValueError('Maintenance external_pins must be a list of release IDs')
    pins=[_release(pin) for pin in external_pins]
    validated_tables=_tables(value['tables'])
    thresholds=value['thresholds']
    maintenance_decision({metric:0 for metric in METRICS},thresholds)
    result=dict(
        version=1,
        bucket=bucket,
        catalog_root=catalog_root,
        work=work,
        external_pins=pins,
        tables=validated_tables,
        thresholds=dict(thresholds),
    )
    if 'engine_config' in value and value['engine_config'] is not None:
        result['engine_config']=_local(value['engine_config'],base)
    if 'raw_verification' in value and value['raw_verification'] is not None:
        raw_cfg=value['raw_verification']
        if not isinstance(raw_cfg,dict) or not {'captures','receipt_inventory','verification_inventory'}<=set(raw_cfg):
            raise ValueError('Maintenance raw_verification requires captures, receipt_inventory and verification_inventory')
        result['raw_verification']=dict(
            captures=_local(raw_cfg['captures'],base),
            receipt_inventory=_local(raw_cfg['receipt_inventory'],base),
            verification_inventory=_local(raw_cfg['verification_inventory'],base),
            seed=raw_cfg.get('seed'),
            apply_staged=bool(raw_cfg.get('apply_staged',True)),
        )
    if 'lake_maintenance' in value and value['lake_maintenance'] is not None:
        lake_cfg=value['lake_maintenance']
        if not isinstance(lake_cfg,dict):
            raise ValueError('Maintenance lake_maintenance must be an object')
        result['lake_maintenance']=dict(lake_cfg)
    return result


def plan(spec):
    if spec.get('status')=='blocked':return dict(spec)
    return dict(
        status='planned',
        executed=False,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        external_pins=spec['external_pins'],
        tables=spec['tables'],
        thresholds=spec['thresholds'],
    )


def execute(spec,*,runtime_factory=None,storage_factory=None,now=None):
    """Execute weekly release retention, raw verification and lake maintenance."""
    if spec.get('status')=='blocked':return dict(spec)
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():
        raise ValueError('Maintenance work directory must be fresh')
    from congress_api.cli.raw_verify import apply_staged
    from congress_api.lake.maintenance import maintenance_decision,purge_generation,rebuild_generation
    from congress_api.retention.body_store import BodyStore,R2Adapter,R2Source
    from congress_api.retention.raw_verifier import verify as verify_raw
    from congress_shared.storage import connect_r2
    from docspec_client.client import NativeDatasets
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    current_time=_time(now or datetime.now(timezone.utc))
    client=storage_factory(bucket=spec['bucket'],retries={'total_max_attempts':1})
    store=ArchiveMaintenanceStore(client=client,bucket=spec['bucket'])
    releases=maintain_releases(store,now=current_time,external_pins=spec['external_pins'],execute=True)
    raw_report=None
    lake_report=dict(decisions={},rebuilt={},purged=[])
    need_engine=bool(spec.get('raw_verification') or spec.get('lake_maintenance'))
    if need_engine:
        engine_config=(spec.get('engine_config')
            or os.environ.get('DOCSPEC_RUNTIME_CONFIG')
            or os.environ.get('DOCSPEC_JOB_CONFIG'))
        if not isinstance(engine_config,str) or not engine_config.strip():
            raise ValueError('Maintenance raw or lake operations require engine_config or DOCSPEC_RUNTIME_CONFIG')
        with runtime_factory(engine_config) as engine:
            engine.verify_runtime()
            if spec.get('raw_verification'):
                raw_cfg=spec['raw_verification']
                raw_work=work/'raw-verify'
                verified=verify_raw(
                    R2Source(client,spec['bucket']),
                    captures=Path(raw_cfg['captures']),
                    receipts=json.loads(Path(raw_cfg['receipt_inventory']).read_text(encoding='utf-8')),
                    previous=json.loads(Path(raw_cfg['verification_inventory']).read_text(encoding='utf-8')),
                    engine=engine,
                    work=raw_work,
                    checked_at=current_time.isoformat(),
                    seed=raw_cfg.get('seed'),
                )
                applied=None
                if raw_cfg.get('apply_staged',True) and verified.get('valid'):
                    applied=apply_staged(raw_work,BodyStore(R2Adapter(client,spec['bucket'])))
                raw_report=dict(verification=verified,applied=applied)
            if spec.get('lake_maintenance'):
                lake_cfg=spec['lake_maintenance']
                for table_name,obs in (lake_cfg.get('observations') or {}).items():
                    exceeded=maintenance_decision(obs,spec['thresholds'])
                    lake_report['decisions'][table_name]=exceeded
                    rebuild_spec=(lake_cfg.get('rebuild') or {}).get(table_name)
                    if exceeded and rebuild_spec is not None:
                        rebuilt_pin=rebuild_generation(
                            rebuild_spec['old_pin'],
                            engine=engine,
                            work=work/'lake-rebuild'/table_name,
                            catalog_root=spec['catalog_root'],
                            table=spec['tables'][table_name],
                            schema=rebuild_spec['schema'],
                            location=rebuild_spec['location'],
                            keys=rebuild_spec['keys'],
                            definition=rebuild_spec['definition'],
                        )
                        lake_report['rebuilt'][table_name]=rebuilt_pin
                for index,purge_spec in enumerate(lake_cfg.get('purge') or ()):
                    table_name=purge_spec['table']
                    purged=purge_generation(
                        purge_spec['pin'],
                        table=spec['tables'][table_name],
                        kept_inputs=releases['kept_inputs'],
                        engine=engine,
                        work=work/'lake-purge'/f'{index:04d}-{table_name}',
                        catalog_root=spec['catalog_root'],
                    )
                    lake_report['purged'].append(dict(table=table_name,result=purged))
    work.mkdir(parents=True,exist_ok=True)
    result=dict(
        status='executed',
        executed=True,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        releases=releases,
        raw_verification=raw_report,
        lake_maintenance=lake_report,
    )
    (work/'maintenance-report.json').write_text(json.dumps(result,sort_keys=True)+'\n',encoding='utf-8')
    return result


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
