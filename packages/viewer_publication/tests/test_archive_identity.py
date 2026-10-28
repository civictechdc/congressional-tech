"""Release content identity has one maintained, ordered serialization."""
from hashlib import sha256


def test_release_identity_matches_the_declared_compact_json_and_ignores_run_metadata():
    from viewer_publication.archive_format import release_identity
    files=[dict(name='a.parquet',sha256='a'*64,size=10,rows=2,producer='archive',coverage={})]
    raw=('[1,[["a.parquet","'+'a'*64+'",10,2]]]').encode()
    assert release_identity(1,files)==sha256(raw).hexdigest()
    assert release_identity(1,[dict(files[0],producer='other',coverage={'run':'different'})])==sha256(raw).hexdigest()
    other=[dict(name='b.json',sha256='b'*64,size=1,rows=0)]
    assert release_identity(1,files+other)!=release_identity(1,other+files)
