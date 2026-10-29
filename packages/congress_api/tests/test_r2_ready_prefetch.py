"""Ready keys follow verified cache writes and cancellation frees bounded queues."""
import hashlib,io,threading
from queue import Empty
import pytest
from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client


def setup(tmp_path,count=30,broken=False):
    objects={};pins={}
    for n in range(count):
        data=('body-'+str(n)).encode();sha=hashlib.sha256(data).hexdigest();key='bodies/sha256/'+sha[:2]+'/'+sha
        objects[key]=data;pins[key]=dict(md5=hashlib.md5(data).hexdigest(),bytes=len(data))
    enough=threading.Event();bad=next(iter(objects))
    class Reads(Client):
        def get_object(self,**kwargs):
            self.reads.append(kwargs)
            if len(self.reads)>=3:enough.set()
            data=objects[kwargs['Key']]
            if broken and kwargs['Key']==bad:data=data[:-1]
            return dict(Body=io.BytesIO(data),ContentLength=pins[kwargs['Key']]['bytes'],ETag=kwargs['IfMatch'])
    client=Reads();client.meta.config.retries={'total_max_attempts':1}
    return R2Store(client,'bucket',cache_dir=tmp_path/'cache'),objects,pins,enough,bad


def test_callback_only_yields_verified_files_and_preserves_read_failure(tmp_path):
    store,objects,pins,_,bad=setup(tmp_path,3,broken=True);seen=[]
    with pytest.raises(ValueError,match='Incomplete'):
        with store.prefetch_immutable_ready(list(objects),expected=pins,max_workers=2,max_ready=2) as ready:
            while True:
                try:key=ready.get(block=True)
                except StopIteration:break
                assert key!=bad and store._immutable_cache_path(key).read_bytes()==objects[key]
                seen.append(key)
    assert bad not in seen


def test_aborted_consumer_releases_full_ready_queue_before_joining(tmp_path):
    store,objects,pins,enough,_=setup(tmp_path);ready=store.prefetch_immutable_ready(list(objects),expected=pins,max_workers=2,max_ready=1)
    finished=threading.Event();errors=[]
    def consume():
        try:
            with ready:
                assert enough.wait(3)
                raise RuntimeError('consumer stopped')
        except RuntimeError as error:errors.append(str(error))
        finally:finished.set()
    thread=threading.Thread(target=consume,daemon=True);thread.start()
    try:assert finished.wait(3),'Cancellation must release callbacks before executor shutdown'
    finally:ready.cancel();thread.join(3)
    assert not thread.is_alive() and errors==['consumer stopped']
    assert len(store.client.reads)<=9  #4N submitted plus the one completed key.


@pytest.mark.parametrize('bound',[0,-1,True])
def test_ready_queue_admission_precedes_any_get(tmp_path,bound):
    store,objects,pins,_,_=setup(tmp_path,1)
    with pytest.raises(ValueError):store.prefetch_immutable_ready(list(objects),expected=pins,max_ready=bound)
    assert store.client.reads==[]
