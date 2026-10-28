"""Additional digests share the verified file's existing streaming read."""
from hashlib import md5,sha256

from congress_shared.custody import CHUNK_BYTES,verify_local_file


def test_additional_digest_updates_interleave_with_sha256_in_one_pass(tmp_path):
    path=tmp_path/'provenance.jsonl';payload=b'x'*(CHUNK_BYTES*2+17);path.write_bytes(payload)
    events=[]
    class Digest:
        def __init__(self,name,factory):self.name=name;self.inner=factory()
        def update(self,chunk):events.append((self.name,len(chunk)));self.inner.update(chunk)
        def hexdigest(self):return self.inner.hexdigest()
    verified=verify_local_file(path,sha256_factory=lambda:Digest('sha256',sha256),
        additional_hashes={'md5':lambda:Digest('md5',md5)})
    assert events==[(name,size) for size in [CHUNK_BYTES,CHUNK_BYTES,17] for name in ['sha256','md5']]
    assert verified['sha256']==sha256(payload).hexdigest() and verified['md5']==md5(payload).hexdigest()
    assert verified['bytes']==len(payload) and verified.require(path) is verified
    assert set(verify_local_file(path))=={'sha256','bytes'}
