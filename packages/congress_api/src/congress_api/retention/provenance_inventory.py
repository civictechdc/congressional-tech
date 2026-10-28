"""One current unreadable-key inventory with checked, opaque local byte caches."""
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
PUBLIC_FIELDS={'key','path','etag','sha256','size'}


def _public(row):
    if (not isinstance(row,dict) or set(row)!=PUBLIC_FIELDS
            or not isinstance(row['key'],str) or not row['key'].startswith(PREFIX)
            or not isinstance(row['path'],str) or not Path(row['path']).is_absolute()
            or type(row['size']) is not int or row['size']<0
            or not isinstance(row['sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):
        raise ValueError('Invalid qualified unreadable provenance')
    validate_key(row['key'])
    return dict(row)


class UnreadableInventory:
    """Keep one LIST snapshot plus this store's later acknowledged imports.

    Cache files persist after exit because their paths are producer outputs.
    Construction validates all authoritative metadata before any GET. A checked
    unchanged cache costs a custody check; missing custody costs one conditional
    GET and one local combined SHA/MD5 verification, never a remote HEAD.
    """
    def __init__(self,store,*,work,qualified=(),verified=None,max_bytes=MAX_OBJECT_BYTES):
        if (not isinstance(store,BodyStore) or not isinstance(store.adapter,(LocalAdapter,R2Adapter))
                or type(max_bytes) is not int or max_bytes<=0):
            raise ValueError('Unreadable inventory needs an explicit supported raw store and byte limit')
        self.store,self.work,self.epoch=store,Path(work).resolve(),store._provenance_epoch
        self.remote=isinstance(store.adapter,R2Adapter)
        verified=verified or {}
        known={key:dict(row) for key,(row,_,_) in store._provenance_cache.items()}
        supplied={}
        for value in qualified:
            row=_public(value);key=row['key']
            if self.remote:row['etag']=single_put_md5(row['etag'])
            if key in supplied:raise ValueError('Duplicate qualified unreadable provenance')
            if key in known and any(known[key][k]!=row[k] for k in ('etag','size','sha256')):
                raise ValueError('Previously checked raw provenance changed')
            known[key]=row;supplied[key]=verified.get(row['path'])
        if self.remote:
            listed=list(store.adapter.listing(PREFIX))
        else:
            root=store.adapter.root.resolve()
            listed=[dict(key=p.relative_to(root).as_posix(),size=p.stat().st_size,etag=None,path=str(p))
                    for p in sorted((root/PREFIX).glob('*')) if p.is_file()]
        selected={}
        for value in listed:
            key=value.get('key');size=value.get('size')
            if not isinstance(key,str) or not key.startswith(PREFIX):
                raise ValueError('Unreadable listing contains a key outside its prefix')
            validate_key(key)
            if type(size) is not int or size<0:raise ValueError('Invalid unreadable object size')
            if size>max_bytes:raise ValueError('Unreadable object exceeds its byte limit')
            etag=single_put_md5(value.get('etag')) if self.remote else None
            if key in selected:raise ValueError('Duplicate unreadable inventory key')
            if key in known and (known[key]['size']!=size or known[key]['etag']!=etag):
                raise ValueError('Previously checked raw provenance changed')
            selected[key]=dict(value,etag=etag)
        if known.keys()-selected.keys():raise ValueError('Previously checked raw provenance is missing')
        self.work.mkdir(parents=True,exist_ok=False)
        self._keys=set(selected)
        for key,metadata in sorted(selected.items()):
            cached=store._provenance_cache.get(key)
            row=known.get(key)
            custody=supplied.get(key) or (cached[1] if cached else None)
            if row is not None and isinstance(custody,VerifiedFile):
                try:
                    custody.require(row['path'])
                    store.remember_provenance(row,custody)
                    continue
                except (OSError,ValueError):
                    pass
            if self.remote:
                row,custody=self._download(metadata,expected=row)
            else:
                path=metadata['path']
                custody=verify_local_file(path,expected_sha256=row['sha256'] if row else None,
                    expected_size=metadata['size'])
                row=dict(key=key,path=path,etag=None,sha256=custody.sha256,size=custody.size_bytes)
            store.remember_provenance(row,custody)

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
            row=_public(value)
            if snapshot.remote:row['etag']=single_put_md5(row['etag'])
            if row['size']>MAX_OBJECT_BYTES:raise ValueError('Unreadable object exceeds its byte limit')
            if row['key'] in snapshot._keys:raise ValueError('Duplicate qualified unreadable provenance')
            snapshot._keys.add(row['key']);rows.append(row)
        if store._provenance_cache.keys()-snapshot._keys:
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
        response=self.store.adapter.get(metadata['key'],if_match=metadata['etag'])
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
        keys=self._keys|{key for key,(_,_,epoch) in self.store._provenance_cache.items() if epoch>self.epoch}
        for key,(_,_,epoch) in self.store._provenance_acks.items():
            if epoch>self.epoch and key not in keys:
                raise ValueError('Acknowledged unreadable import needs checked cache custody')
        rows=[]
        for key in sorted(keys):
            row,custody,_=self.store._provenance_cache[key]
            custody.require(row['path']);rows.append(dict(row))
        return rows

    def files(self):
        return [dict(key=row['key'],path=row['path']) for row in self.rows() if row['key'].endswith('.jsonl')]

    def __enter__(self):return self
    def __exit__(self,*_):return False


def unreadable_inventory(store,**kwargs):
    return UnreadableInventory(store,**kwargs)
