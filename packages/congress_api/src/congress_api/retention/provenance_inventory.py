"""One raw provenance inventory with selected, checked opaque byte caches."""
from contextlib import closing
from hashlib import md5,sha256
from pathlib import Path
import re
from uuid import uuid4

from congress_shared.custody import VerifiedFile,verify_local_file
from congress_shared.storage import single_put_md5

from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter,validate_key


PREFIX='provenance/unreadable/'
MAX_OBJECT_BYTES=32<<20
MAX_CACHE_BYTES=256<<20
PUBLIC_FIELDS={'key','path','etag','sha256','size'}


def _public(row,*,prefix='provenance/'):
    if (not isinstance(row,dict) or set(row)!=PUBLIC_FIELDS
            or not isinstance(row['key'],str) or not row['key'].startswith(prefix)
            or not isinstance(row['path'],str) or not Path(row['path']).is_absolute()
            or type(row['size']) is not int or row['size']<0
            or not isinstance(row['sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):
        raise ValueError('Invalid qualified unreadable provenance')
    validate_key(row['key'])
    return dict(row)


class ProvenanceInventory:
    """List complete opaque metadata, then qualify explicitly selected files.

    Cache files persist after exit because their paths are producer outputs.
    The caller owns record recognition. Backup ETags and sizes remain opaque
    identity metadata and require no GET. Selected files obey configured per-file
    and total cache bounds before GET. Download and combined local SHA/MD5 checks
    share one path with the unreadable producer view, never per-object HEADs.
    """
    prefix='provenance/'

    def __init__(self,store,*,work,max_file_bytes=MAX_OBJECT_BYTES,max_total_bytes=MAX_CACHE_BYTES):
        if (not isinstance(store,BodyStore) or not isinstance(store.adapter,(LocalAdapter,R2Adapter))
                or any(type(v) is not int or v<=0 for v in (max_file_bytes,max_total_bytes))):
            raise ValueError('Provenance inventory needs a supported raw store and positive byte limits')
        self.store,self.work,self.epoch=store,Path(work).resolve(),store._provenance_epoch
        self.remote=isinstance(store.adapter,R2Adapter)
        self.max_file_bytes,self.max_total_bytes=max_file_bytes,max_total_bytes
        if self.remote:
            listed=list(store.adapter.listing(self.prefix,preserve_etags=True))
        else:
            root=store.adapter.root.resolve()
            listed=[dict(key=p.relative_to(root).as_posix(),size=p.stat().st_size,etag=None,path=str(p))
                    for p in sorted((root/self.prefix).rglob('*')) if p.is_file()]
        selected={}
        for value in listed:
            key=value.get('key');size=value.get('size')
            if not isinstance(key,str) or not key.startswith(self.prefix):
                raise ValueError('Provenance listing contains a key outside its prefix')
            validate_key(key)
            if type(size) is not int or size<0:raise ValueError('Invalid provenance object size')
            etag=value.get('etag')
            if self.remote and (not isinstance(etag,str) or not etag.strip()):
                raise ValueError('Invalid provenance inventory ETag')
            if key in selected:raise ValueError('Duplicate provenance inventory key')
            cached=store._provenance_cache.get(key)
            if cached and (cached[0]['size']!=size or self.remote and cached[0]['etag']!=single_put_md5(etag)):
                raise ValueError('Previously checked raw provenance changed')
            selected[key]=dict(value,etag=etag)
        known={key for key in store._provenance_cache if key.startswith(self.prefix)}
        if known-selected.keys():raise ValueError('Previously checked raw provenance is missing')
        self.work.mkdir(parents=True,exist_ok=False)
        self._listed=selected;self._keys=set()

    def metadata(self):
        """Return the exact initial full metadata set, including unselected keys."""
        return [dict(key=key,etag=self._listed[key]['etag'],size=self._listed[key]['size'])
                for key in sorted(self._listed)]

    def qualify(self,record_keys,*,qualified=(),verified=None):
        """Cache only explicit selected keys; no record policy or JSON parsing."""
        keys=list(record_keys)
        if any(not isinstance(k,str) for k in keys) or len(keys)!=len(set(keys)):
            raise ValueError('Selected provenance keys must be unique strings')
        if set(keys)-self._listed.keys():raise ValueError('Selected provenance key is missing')
        selected=self._keys|set(keys)
        if (any(self._listed[k]['size']>self.max_file_bytes for k in selected)
                or sum(self._listed[k]['size'] for k in selected)>self.max_total_bytes):
            raise ValueError('Selected provenance exceeds its file or total byte limit')
        metadata={k:dict(self._listed[k],request_etag=self._listed[k]['etag'],
                    etag=single_put_md5(self._listed[k]['etag']) if self.remote else None)
                  for k in keys}
        known={k:dict(self.store._provenance_cache[k][0]) for k in keys if k in self.store._provenance_cache}
        supplied={};verified=verified or {}
        for value in qualified:
            row=_public(value,prefix=self.prefix);key=row['key']
            if self.remote:row['etag']=single_put_md5(row['etag'])
            if key not in metadata:raise ValueError('Qualified provenance key is missing from current inventory')
            if key in supplied:raise ValueError('Qualified provenance must bind unique selected keys')
            if row['size']!=metadata[key]['size'] or row['etag']!=metadata[key]['etag']:
                raise ValueError('Previously checked raw provenance changed')
            if key in known and any(known[key][k]!=row[k] for k in ('etag','size','sha256')):
                raise ValueError('Previously checked raw provenance changed')
            known[key]=row;supplied[key]=verified.get(row['path'])
        for key in sorted(keys):
            cached=self.store._provenance_cache.get(key)
            row=known.get(key);custody=supplied.get(key) or (cached[1] if cached else None)
            if row is not None and isinstance(custody,VerifiedFile):
                try:
                    custody.require(row['path'])
                    self.store.remember_provenance(row,custody)
                    self._keys.add(key)
                    continue
                except (OSError,ValueError):
                    pass
            if self.remote:
                row,custody=self._download(metadata[key],expected=row)
            else:
                path=metadata[key]['path']
                custody=verify_local_file(path,expected_sha256=row['sha256'] if row else None,
                    expected_size=metadata[key]['size'])
                row=dict(key=key,path=path,etag=None,sha256=custody.sha256,size=custody.size_bytes)
            self.store.remember_provenance(row,custody)
            self._keys.add(key)
        return self._cache_rows(keys)

    def _cache_rows(self,keys):
        rows=[]
        for key in sorted(keys):
            row,custody,_=self.store._provenance_cache[key]
            custody.require(row['path']);rows.append(dict(row))
        return rows

    def verified(self):
        """Return held custody for the same initial and acknowledged rows."""
        return {row['path']:self.store._provenance_cache[row['key']][1] for row in self.rows()}

    @classmethod
    def from_qualified(cls,store,*,qualified,verified=None):
        """Use the controller's complete current snapshot without another LIST.

        The controller supplies every qualified key and checks concurrency again
        before publishing. This path checks held local bytes and adds only this
        invocation's acknowledged imports; it never discovers remote state.
        """
        if not isinstance(store,BodyStore) or not isinstance(store.adapter,(LocalAdapter,R2Adapter)):
            raise ValueError('Qualified unreadable snapshot requires a supported raw store')
        snapshot=cls.__new__(cls)
        snapshot.store,snapshot.epoch=store,store._provenance_epoch
        snapshot.remote=isinstance(store.adapter,R2Adapter)
        snapshot.work=None;snapshot._keys=set();verified=verified or {}
        rows=[]
        for value in qualified:
            row=_public(value,prefix=snapshot.prefix)
            if snapshot.remote:row['etag']=single_put_md5(row['etag'])
            if row['size']>MAX_OBJECT_BYTES:raise ValueError('Unreadable object exceeds its byte limit')
            if row['key'] in snapshot._keys:raise ValueError('Duplicate qualified unreadable provenance')
            snapshot._keys.add(row['key']);rows.append(row)
        known={key for key in store._provenance_cache if key.startswith(snapshot.prefix)}
        if known-snapshot._keys:
            raise ValueError('Previously checked raw provenance is missing from initial qualified snapshot')
        for row in rows:
            cached=store._provenance_cache.get(row['key'])
            custody=verified.get(row['path']) or (cached[1] if cached else None)
            try:
                if not isinstance(custody,VerifiedFile):raise ValueError('Unqualified cache')
                custody.require(row['path'])
                if snapshot.remote and custody.get('md5') is None:raise ValueError('Unqualified MD5 cache')
            except (OSError,ValueError):
                custody=verify_local_file(row['path'],expected_sha256=row['sha256'],expected_size=row['size'],
                    additional_hashes={'md5':md5} if snapshot.remote else None)
            if snapshot.remote and custody.get('md5')!=row['etag']:
                raise ValueError('Qualified unreadable cache MD5 checksum differs from its inventory')
            store.remember_provenance(row,custody)
        return snapshot

    def _download(self,metadata,*,expected):
        response=self.store.adapter.get(metadata['key'],if_match=metadata['request_etag'])
        path=self.work/(sha256(metadata['key'].encode()).hexdigest()+'-'+uuid4().hex+'.jsonl')
        with closing(response['Body']) as stream:
            if (type(response.get('ContentLength')) is not int or response['ContentLength']!=metadata['size']
                    or single_put_md5(response.get('ETag'))!=metadata['etag']):
                raise ValueError('Unreadable response metadata changed after listing')
            try:
                count=0
                with path.open('xb') as out:
                    while chunk:=stream.read(min(65536,metadata['size']+1-count)):
                        count+=len(chunk)
                        if count>metadata['size']:raise ValueError('Unreadable response length changed')
                        out.write(chunk)
                if count!=metadata['size']:raise ValueError('Unreadable response length changed')
                custody=verify_local_file(path,expected_size=metadata['size'],
                    expected_sha256=expected['sha256'] if expected else None,additional_hashes={'md5':md5})
                if custody['md5']!=metadata['etag']:raise ValueError('Unreadable response MD5 checksum changed')
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return dict(key=metadata['key'],path=str(path),etag=metadata['etag'],
                    sha256=custody.sha256,size=custody.size_bytes),custody

    def rows(self):
        keys=self._keys|{key for key,(_,_,epoch) in self.store._provenance_cache.items()
                        if epoch>self.epoch and key.startswith(self.prefix)}
        for key,(_,_,epoch) in self.store._provenance_acks.items():
            if epoch>self.epoch and key.startswith(self.prefix) and key not in keys:
                raise ValueError('Acknowledged unreadable import needs checked cache custody')
        return self._cache_rows(keys)

    def files(self):
        return [dict(key=row['key'],path=row['path']) for row in self.rows() if row['key'].endswith('.jsonl')]

    def __enter__(self):return self
    def __exit__(self,*_):return False


class UnreadableInventory(ProvenanceInventory):
    """The producer's unreadable subset, plus this invocation's checked imports."""
    prefix=PREFIX

    def __init__(self,store,*,work,qualified=(),verified=None,max_bytes=MAX_OBJECT_BYTES,
                 max_total_bytes=MAX_CACHE_BYTES):
        super().__init__(store,work=work,max_file_bytes=max_bytes,max_total_bytes=max_total_bytes)
        self.qualify(sorted(self._listed),qualified=qualified,verified=verified)


def provenance_inventory(store,**kwargs):
    return ProvenanceInventory(store,**kwargs)


def unreadable_inventory(store,**kwargs):
    return UnreadableInventory(store,**kwargs)
