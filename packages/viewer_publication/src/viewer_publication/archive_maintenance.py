"""Verify raw custody and retain only old, unkept derived releases.

The weekly caller holds the shared publish/maintenance exclusion. Raw keys
are never deleted. Lake maintenance acts only on explicitly supplied pins.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from viewer_publication.archive_publish import (CONTROL_BYTES,NativeArchiveStore,SPICY_PINS,_encoded,
    _read,input_digest,read_pointer,write_spicy_generations)
from viewer_publication.client import require_publication_client
from viewer_publication.receipt_pins import PREFIX

ARCHIVE_RELEASE_PINS='viewer-publications/pins/archive-releases.json'
PROFILE_SOURCE='packages/viewer_publication/src/viewer_publication/archive_model_profile.py'
# Profile producer at 3f6548e6, before source-scoped pins for entity tables.
LEGACY_PROFILE_SHA='cad3c0e5c498b495a4911ea9450d0c1ad992dec6eb31d498fcb5a2d52c2f3237'


class ReadOnlyClient:
    """Expose the S3 reads used by maintenance and refuse mutation calls."""
    READS=frozenset({'meta','get_object','head_object','list_objects_v2'})

    def __init__(self,client):self._client=client

    def get_paginator(self,operation):
        if operation!='list_objects_v2':
            raise PermissionError('Read-only maintenance client refused paginator '+operation)
        return self._client.get_paginator(operation)

    def __getattr__(self,name):
        if name in self.READS:return getattr(self._client,name)
        def refused(*_,**__):raise PermissionError('Read-only maintenance client refused '+name)
        return refused


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
    def read_archive_release_pins(self):
        try:
            raw=_read(self.client,self.bucket,ARCHIVE_RELEASE_PINS)[0]
        except Exception as error:
            raise ValueError('Failed to read archive release pins from store') from error
        return read_archive_release_pins(raw)
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
    from viewer_publication.archive_model_profile import ENTITY_SOURCES,PARSERS,profile_record
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
    if not isinstance(profile,dict) or not isinstance(profile.get('file_hashes'),dict):
        raise ValueError('Kept model profile requires explicit definition hashes')
    validation=profile
    parsers=profile.get('parser_versions')
    lake_versions=profile.get('lake_versions')
    if (profile['file_hashes'].get(PROFILE_SOURCE)==LEGACY_PROFILE_SHA
            and isinstance(parsers,dict) and set(parsers)==set(PARSERS)
            and isinstance(lake_versions,dict) and lake_versions.keys()==selected.keys()
            and set(selected)==set(TABLES)|set(ENTITY_SOURCES)
            and all(selected[name]['kind']=='parquet' for name in ENTITY_SOURCES)):
        # This historical producer used pinned entity Parquet files. Its
        # original profile has already been checked against the input digest.
        # Apply the shared shape checks without requiring later parser fields.
        validation=dict(profile,lake_versions={name:value for name,value in lake_versions.items()
            if name not in ENTITY_SOURCES})
    rebuilt=profile_record(**validation,snapshots=selected)
    if rebuilt['profile']!=validation:
        raise ValueError('Kept model profile has unsupported fields')


def read_archive_release_pins(source,*,key=ARCHIVE_RELEASE_PINS):
    """Parse and validate the v1 pins/archive-releases.json wire contract, failing closed."""
    if source is None:
        raise ValueError('Archive release pin source is required')
    if isinstance(source,dict):
        payload=source
    elif isinstance(source,(bytes,bytearray)):
        try:
            payload=json.loads(bytes(source).decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError) as error:
            raise ValueError('Invalid archive release pins JSON') from error
    elif isinstance(source,Path):
        try:
            payload=json.loads(source.read_text(encoding='utf-8'))
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as error:
            raise ValueError('Unreadable archive release pins file') from error
    elif isinstance(source,str):
        stripped=source.lstrip()
        if stripped.startswith(('{','[')):
            try:
                payload=json.loads(source)
            except json.JSONDecodeError as error:
                raise ValueError('Invalid archive release pins JSON') from error
        else:
            uri=urlsplit(source)
            if uri.scheme in {'http','https','file'}:
                from urllib.request import Request,urlopen
                try:
                    request=Request(source,headers={'User-Agent':'CongressionalArchiveMaintenance/1.0'})
                    with urlopen(request,timeout=30) as response:
                        raw=response.read(CONTROL_BYTES+1)
                    if len(raw)>CONTROL_BYTES:
                        raise ValueError('Archive release pins exceed control byte limit')
                    payload=json.loads(raw.decode('utf-8'))
                except Exception as error:
                    if isinstance(error,ValueError):raise
                    raise ValueError('Failed to fetch archive release pins') from error
            elif uri.scheme:
                raise ValueError(f'Unsupported archive release pin URI scheme: {uri.scheme}')
            else:
                try:
                    payload=json.loads(Path(source).read_text(encoding='utf-8'))
                except (OSError,UnicodeDecodeError,json.JSONDecodeError) as error:
                    raise ValueError('Unreadable archive release pins path') from error
    elif isinstance(source,ArchiveMaintenanceStore):
        try:
            raw=_read(source.client,source.bucket,key)[0]
        except Exception as error:
            raise ValueError('Failed to read archive release pins from store') from error
        return read_archive_release_pins(raw,key=key)
    elif callable(getattr(source,'read_archive_release_pins',None)):
        try:
            loaded=source.read_archive_release_pins()
        except Exception as error:
            if isinstance(error,ValueError):raise
            raise ValueError('Failed to read archive release pins') from error
        if isinstance(loaded,list) and all(isinstance(item,str) for item in loaded):
            return list(dict.fromkeys(_release(item) for item in loaded))
        return read_archive_release_pins(loaded,key=key)
    elif callable(getattr(source,'get',None)):
        try:
            raw=source.get(key)
        except Exception as error:
            raise ValueError('Failed to read archive release pins from store') from error
        if raw is None:
            raise ValueError('Missing archive release pins in store')
        return read_archive_release_pins(raw,key=key)
    elif hasattr(source,'objects') and isinstance(getattr(source,'objects'),dict):
        if key not in source.objects:
            raise ValueError('Missing archive release pins in store')
        return read_archive_release_pins(source.objects[key],key=key)
    elif callable(getattr(source,'read',None)):
        try:
            raw=source.read()
        except Exception as error:
            raise ValueError('Failed to read archive release pins stream') from error
        return read_archive_release_pins(raw,key=key)
    elif callable(source):
        try:
            raw=source()
        except Exception as error:
            if isinstance(error,ValueError):raise
            raise ValueError('Failed to read archive release pins') from error
        return read_archive_release_pins(raw,key=key)
    else:
        raise ValueError('Unsupported archive release pin source')
    if not isinstance(payload,dict) or set(payload)!={'version','updated_at','releases'}:
        raise ValueError('Archive release pins require version, updated_at and releases')
    if type(payload.get('version')) is not int or payload['version']!=1:
        raise ValueError('Archive release pins require version 1')
    updated_at=payload.get('updated_at')
    if not isinstance(updated_at,str) or not updated_at.strip():
        raise ValueError('Archive release pins require a non-empty updated_at timestamp')
    releases=payload.get('releases')
    if not isinstance(releases,list):
        raise ValueError('Archive release pins releases must be a list')
    return list(dict.fromkeys(_release(item) for item in releases))


def prunable_release_ids(newest,*,kept,now,min_age=timedelta(days=1)):
    """Return sorted release IDs outside kept whose newest object is older than min_age."""
    cutoff=_time(now)-min_age
    kept_set={_release(value) for value in kept}
    return sorted(release for release,modified in newest.items()
                  if _release(release) not in kept_set and _time(modified)<cutoff)


def maintain_releases(store,*,now,external_pins=(),external_pins_source=None,execute=False):
    """Collect all kept inputs before planning or deleting unkept release keys.

    Inventory work is linear in object count; input identity canonicalizes each
    receipt set in O(R log R), and final deletion sorting costs O(D log D). No
    release assets, raw bodies or lake rows are read. The caller supplies explicit
    external pins and passes returned kept_inputs to D5 guards.
    """
    now=_time(now)
    if isinstance(external_pins,str):raise ValueError('External pins must be release IDs')
    if isinstance(external_pins,dict):
        pins=set(read_archive_release_pins(external_pins))
    else:
        pins={_release(value) for value in external_pins}
    source=store if external_pins_source is True else external_pins_source
    source_pins=set(read_archive_release_pins(source)) if source is not None else set()
    pins.update(source_pins)
    pointer,etag=_pointer(store)
    pointer_kept={pointer['release_id']}
    if pointer.get('previous_release_id') is not None:pointer_kept.add(pointer['previous_release_id'])
    kept=pins|pointer_kept
    objects={};newest={};sizes={};seen=set();ignored_legacy_objects=0
    for item in store.inventory():
        key=item['Key']
        release=_inventory_release(key)
        if release is None:
            ignored_legacy_objects+=1
            continue
        if key in seen:raise ValueError('Archive inventory repeats an object')
        seen.add(key)
        modified=_time(item['LastModified'])
        sizes[key]=item.get('Size')
        objects.setdefault(release,[]).append(key)
        newest[release]=max(newest.get(release,modified),modified)
    existing_releases=set(objects)
    evidence=_InventoryEvidence(store,objects)
    def _has_input_record(release):
        if callable(getattr(store,'input_records',None)):
            return bool(store.input_records(release))
        prefix=PREFIX+release+'/inputs/'
        return any(re.fullmatch(re.escape(prefix)+'[a-f0-9]{64}[.]json',key)
                   for key in evidence.keys(prefix))
    external_only=pins-pointer_kept
    active_external_pins={release for release in (external_only&existing_releases) if _has_input_record(release)}
    stale_external_pins=sorted(external_only-active_external_pins)
    from viewer_publication.receipt_pins import kept_input_records
    # Reuse the maintained parse/receipt validation, then validate semantic identity
    # from its already parsed records and receipt keys without more GETs or parses.
    # live and last_good must strictly exist; external pins absent from releases/
    # or whose inputs/ prefix was already pruned are recorded in stale_external_pins.
    entries,protected=kept_input_records(evidence,sorted(pointer_kept|active_external_pins))
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
    prunable=set(prunable_release_ids(newest,kept=kept,now=now))
    delete_keys=sorted(key for release in sorted(prunable) for key in objects.get(release,()))
    delete_sizes=[sizes[key] for key in delete_keys]
    delete_bytes=sum(delete_sizes) if all(type(size) is int for size in delete_sizes) else None
    spicy_pairs=sorted({(family,digest) for record in records
                        for family,digest in (record.get('entity_digests') or {}).items()})
    spicy_generations=[dict(family=family,digest=digest) for family,digest in spicy_pairs]
    if execute:
        if _pointer(store)!=(pointer,etag):
            raise ValueError('Live pointer changed before maintenance deletion')
        if source is not None and set(read_archive_release_pins(source))!=source_pins:
            raise ValueError('External release pins changed before maintenance deletion')
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
        kept_releases=sorted(kept),stale_external_pins=stale_external_pins,kept_inputs=records,
        retained_releases=sorted(existing_releases-prunable),
        protected_keys=sorted(protected),delete_releases=sorted(prunable),delete_keys=delete_keys,
        delete_bytes=delete_bytes,spicy_generations=spicy_generations,ignored_legacy_objects=ignored_legacy_objects)


JOB_FIELDS={'version','bucket','catalog_root','work','external_pins','tables','thresholds'}
JOB_OPTIONAL={'engine_config','external_pins_source','raw_verification','lake_maintenance'}


def _daily_tables(value,base):
    """The daily job owns the table list, so the committed spec names its file (ct-yndj).

    A copied list drifted: ea2cf179 moved the daily to new tables and left this one naming
    superseded generations. An explicit map remains, and lake rebuild and purge entries require
    one (load_spec), for a one-off spec whose targets the daily does not write, such as a
    superseded generation to purge.
    """
    from viewer_publication.archive_model_job import _local
    if not isinstance(value,str):return value
    daily=json.loads(Path(_local(value,base)).read_text(encoding='utf-8'))
    if not isinstance(daily,dict) or 'tables' not in daily:
        raise ValueError('Maintenance tables must name a daily job spec that lists its tables')
    return daily['tables']


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
    validated_tables=_tables(_daily_tables(value['tables'],base))
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
    if 'external_pins_source' in value and value['external_pins_source'] is not None:
        pin_src=value['external_pins_source']
        if isinstance(pin_src,bool):
            if not pin_src:raise ValueError('Maintenance external_pins_source cannot be False')
            result['external_pins_source']=True
        elif isinstance(pin_src,str) and pin_src.strip():
            uri=urlsplit(pin_src)
            if not uri.scheme and pin_src!=ARCHIVE_RELEASE_PINS and not pin_src.lstrip().startswith('{'):
                pin_src=_local(pin_src,base)
            result['external_pins_source']=pin_src
        else:
            raise ValueError('Maintenance external_pins_source must be a valid source')
    if 'raw_verification' in value and value['raw_verification'] is not None:
        from congress_api.retention.raw_verifier import MAX_BODY_WORKERS
        from viewer_publication.archive_model_job import _selector
        raw_cfg=value['raw_verification']
        inventories={'receipt_inventory','verification_inventory'}
        if not isinstance(raw_cfg,dict) or 'captures' not in raw_cfg:
            raise ValueError('Maintenance raw_verification requires a captures input')
        if raw_cfg.keys()&inventories and not inventories<=raw_cfg.keys():
            raise ValueError('Supply both raw verification inventories or discover both from the bucket')
        body_workers=raw_cfg.get('body_workers',1)
        if type(body_workers) is not int or not 1<=body_workers<=MAX_BODY_WORKERS:
            raise ValueError(f'Maintenance raw_verification body_workers must be an integer from 1 to {MAX_BODY_WORKERS}')
        captures=raw_cfg['captures']
        if isinstance(captures,dict) and set(captures)=={'model_spec'}:
            model_path=Path(_local(captures['model_spec'],base))
            model=json.loads(model_path.read_text(encoding='utf-8'))
            if not isinstance(model,dict) or 'captures' not in model:
                raise ValueError('Maintenance model spec requires a captures selector')
            captures_cfg=_selector(model['captures'],model_path.parent)
        elif isinstance(captures,dict):
            captures_cfg=_selector(captures,base)
        else:
            captures_cfg=_local(captures,base)
        result['raw_verification']=dict(
            captures=captures_cfg,
            seed=raw_cfg.get('seed'),
            apply_staged=bool(raw_cfg.get('apply_staged',True)),
            body_workers=body_workers,
        )
        for key in raw_cfg.keys()&inventories:
            source=raw_cfg[key]
            result['raw_verification'][key]=source if isinstance(source,list) else _local(source,base)
    if 'lake_maintenance' in value and value['lake_maintenance'] is not None:
        lake_cfg=value['lake_maintenance']
        if not isinstance(lake_cfg,dict):
            raise ValueError('Maintenance lake_maintenance must be an object')
        # tables are also the rebuild and purge targets: through the daily reference a rebuild
        # would aim at a live table and a purge target would move whenever the daily moves.
        if isinstance(value['tables'],str) and (lake_cfg.get('rebuild') or lake_cfg.get('purge')):
            raise ValueError('Lake rebuild and purge name their targets: give an explicit tables map')
        result['lake_maintenance']=dict(lake_cfg)
    return result


def _connect(spec,storage_factory,**options):
    if storage_factory is None:
        from congress_shared.storage import connect_r2 as storage_factory
    return storage_factory(bucket=spec['bucket'],**options)


def _engine_config(spec,*,need_engine):
    """The runtime config a maintenance step uses: the spec's, the remote runtime's, else the local job runtime's."""
    from docspec_client.client import choose_runtime
    config,choice=choose_runtime(spec.get('engine_config'),job_fallback=need_engine)
    if need_engine and (not isinstance(config,str) or not config.strip()):
        raise ValueError('Maintenance raw or lake operations require engine_config or DOCSPEC_RUNTIME_CONFIG')
    return config,choice


def _retain_releases(spec,client,*,now,execute=False):
    store=ArchiveMaintenanceStore(client=client,bucket=spec['bucket'])
    source=spec.get('external_pins_source')
    if source==ARCHIVE_RELEASE_PINS:
        source=store
    return maintain_releases(store,now=now,external_pins=spec['external_pins'],
        external_pins_source=source,execute=execute)


def plan(spec,*,storage_factory=None,now=None):
    """List the release keys retention would delete and the releases it keeps, writing nothing.

    Reads the pointer, release pins, one release inventory and the kept input records
    through a client that refuses every call but a read. Raw verification and lake
    maintenance run only in a dry run or an execution.
    """
    if spec.get('status')=='blocked':return dict(spec)
    result=dict(
        status='planned',
        executed=False,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        external_pins=spec['external_pins'],
        tables=spec['tables'],
        thresholds=spec['thresholds'],
    )
    for key in ('external_pins_source','raw_verification','lake_maintenance'):
        if key in spec:
            result[key]=spec[key]
    client=ReadOnlyClient(_connect(spec,storage_factory,retries={'total_max_attempts':1}))
    releases=_retain_releases(spec,client,now=_time(now or datetime.now(timezone.utc)))
    result['releases']={key:releases[key] for key in ('pointer','pointer_etag','kept_releases','retained_releases','stale_external_pins',
        'delete_releases','delete_keys','delete_bytes','spicy_generations','ignored_legacy_objects')}
    result['releases']['kept_input_digests']=sorted(record['input_digest'] for record in releases['kept_inputs'])
    return result


def _stage_raw_inventories(client,bucket,work):
    """Take complete prefix listings and stage only the raw verifier's JSON inputs."""
    from congress_api.lake.receipt_inventory import R2ReceiptStore,copy_receipts
    from congress_api.retention.body_store import BodyStore,R2Adapter
    from congress_api.retention.provenance_inventory import ProvenanceInventory,VERIFICATION_PREFIX
    from viewer_publication.archive_model_job import provenance_record_kind

    class VerificationInventory(ProvenanceInventory):
        prefix=VERIFICATION_PREFIX

    receipt_store=R2ReceiptStore(client,bucket)
    listed=list(receipt_store.files('receipts/'))
    if len({row['key'] for row in listed})!=len(listed):
        raise ValueError('Duplicate raw verification receipt key')
    copied=copy_receipts(receipt_store,sorted(listed,key=lambda row:row['key']),work/'receipts')
    receipts=[dict(key=row['key'],path=row['path']) for row in copied]
    with VerificationInventory(BodyStore(R2Adapter(client,bucket)),work=work/'verification',
            include_verification_history=True) as inventory:
        inventory.qualify(row['key'] for row in inventory.metadata() if provenance_record_kind(row['key'])=='verification')
        previous=inventory.files()
    for name,rows in (('receipt',receipts),('verification',previous)):
        (work/(name+'-inventory.json')).write_text(json.dumps(rows,sort_keys=True)+'\n',encoding='utf-8')
    return receipts,previous


def _prepare_raw_verification_inputs(raw_cfg,*,client,bucket,work):
    for extra_key in ('inventory','baseline','scope'):
        if extra_key in raw_cfg and isinstance(raw_cfg[extra_key],(str,Path)):
            if not Path(raw_cfg[extra_key]).is_file():
                raise ValueError(f'Missing raw_verification {extra_key} input')
    captures_spec=raw_cfg['captures']
    if isinstance(captures_spec,dict):
        old_native='inputs' in captures_spec
        d1_native=not old_native and (captures_spec.get('kind')=='native_table' or 'metadata_location' in captures_spec)
        if not old_native and not d1_native:
            cap_path=Path(captures_spec['path'])
            if not cap_path.is_file():
                raise ValueError('Missing raw_verification captures input')
        captures=captures_spec
    else:
        cap_path=Path(captures_spec)
        if not cap_path.is_file():
            raise ValueError('Missing raw_verification captures input')
        captures=cap_path
    inventory_keys=('receipt_inventory','verification_inventory')
    supplied=[key for key in inventory_keys if key in raw_cfg]
    if not supplied:
        work.mkdir(parents=True,exist_ok=False)
        receipts,previous=_stage_raw_inventories(client,bucket,work)
        return captures,receipts,previous
    if len(supplied)!=len(inventory_keys):
        raise ValueError('Supply both raw verification inventories or discover both from the bucket')
    inventories=[]
    for key in inventory_keys:
        rows=raw_cfg[key]
        try:
            if not isinstance(rows,list):
                rows=json.loads(Path(rows).read_text(encoding='utf-8'))
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as error:
            raise ValueError('Missing or unreadable raw_verification '+key) from error
        if not isinstance(rows,list):
            raise ValueError('Raw verification inventory must contain a list: '+key)
        inventories.append(rows)
    receipts,previous=inventories
    return captures,receipts,previous


def execute(spec,*,runtime_factory=None,storage_factory=None,now=None,execute=True):
    """Stage verification and retention decisions, applying changes only in execute mode."""
    if isinstance(spec,(str,Path)):spec=load_spec(spec)
    if spec.get('status')=='blocked':return dict(spec)
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():
        raise ValueError('Maintenance work directory must be fresh')
    from contextlib import nullcontext
    from congress_api.cli.raw_verify import apply_staged
    from congress_api.lake.maintenance import maintenance_decision,purge_generation,rebuild_generation
    from congress_api.retention.body_store import BodyStore,R2Adapter,R2Source
    from congress_api.retention.r2 import configure_read_retries
    import congress_api.retention.raw_verifier as raw_verifier
    import sys
    from docspec_client.client import NativeDatasets,runtime_record
    runtime_factory=runtime_factory or NativeDatasets.from_config
    current_time=_time(now or datetime.now(timezone.utc))
    need_engine=bool(spec.get('raw_verification') or spec.get('lake_maintenance'))
    engine_config,choice=_engine_config(spec,need_engine=need_engine)
    ran=None
    raw_report=None
    lake_report=dict(decisions={},rebuilt={},purged=[])
    with (runtime_factory(engine_config) if engine_config else nullcontext(None)) as engine:
        if engine is not None:
            ran=runtime_record(engine_config,choice,log=sys.stderr)
            engine.verify_runtime()
        client=_connect(spec,storage_factory,retries={'total_max_attempts':1})
        reader=ReadOnlyClient(client)
        if spec.get('raw_verification'):
            configure_read_retries(reader)
            raw_cfg=spec['raw_verification']
            raw_captures,raw_receipts,raw_previous=_prepare_raw_verification_inputs(raw_cfg,
                client=reader,bucket=spec['bucket'],work=work/'raw-verification-inputs')
            raw_work=work/'raw-verify'
            verified=raw_verifier.verify(
                R2Source(reader,spec['bucket']),
                captures=raw_captures,
                receipts=raw_receipts,
                previous=raw_previous,
                engine=engine,
                work=raw_work,
                checked_at=current_time.isoformat(),
                seed=raw_cfg.get('seed'),
                body_workers=raw_cfg.get('body_workers',1),
            )
            if execute and not verified.get('valid',False):
                raise RuntimeError('raw verification failed; refusing release pruning')
            applied=None
            if execute and raw_cfg.get('apply_staged',True) and verified.get('valid'):
                applied=apply_staged(raw_work,BodyStore(R2Adapter(client,spec['bucket'])))
            raw_report=dict(verification=verified,applied=applied)
        releases=_retain_releases(spec,client if execute else reader,now=current_time,execute=execute)
        if spec.get('lake_maintenance'):
            lake_cfg=spec['lake_maintenance']
            for table_name,obs in (lake_cfg.get('observations') or {}).items():
                exceeded=maintenance_decision(obs,spec['thresholds'])
                lake_report['decisions'][table_name]=exceeded
                rebuild_spec=(lake_cfg.get('rebuild') or {}).get(table_name)
                if execute and exceeded and rebuild_spec is not None:
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
            purges=lake_cfg.get('purge') or ()
            for index,purge_spec in enumerate(purges if execute else ()):
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
        status='executed' if execute else 'dry_run',
        executed=bool(execute),
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        engine_config=engine_config,
        engine_runtime=ran,
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
    mode.add_argument('--plan',action='store_true',help='List retained releases and deletion keys')
    mode.add_argument('--dry-run',action='store_true',help='Stage raw verification and retention reports locally')
    mode.add_argument('--execute',action='store_true',help='Apply verification and maintenance changes')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':
            print(json.dumps(spec,sort_keys=True))
            return 2
        result=execute(spec,execute=args.execute) if args.execute or args.dry_run else plan(spec)
    except (ValueError,OSError,RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
