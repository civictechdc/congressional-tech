"""Validate kept rebuild evidence and retain only old, unkept derived releases.

The weekly caller holds the shared publish/maintenance exclusion. This helper
never lists or deletes raw keys and never selects a lake generation to purge.
"""
from datetime import datetime,timedelta
import json
from pathlib import Path
import re

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
