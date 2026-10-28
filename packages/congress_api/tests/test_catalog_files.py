"""Selected catalogs stream to owned files and fail before changing selection."""
import hashlib
import io
import os
from pathlib import Path
import stat

import pytest
from botocore.exceptions import ReadTimeoutError, ClientError

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import MANIFEST_KEY, read_catalog, publish_catalog, local_catalog_paths
from congress_api.retention.derived_files import copy_checked, file_identity
from congress_api.retention.r2 import R2Store
from test_catalog_publication import pair
from test_r2_body_files import Client

KEY = 'catalog-generations/' + 'a' * 32 + '/documents.parquet'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize('key', ['bodies/x', 'indexes/catalog.json', 'receipts/x',
    'indexes/../documents.parquet', 'indexes/processing/documents.parquet',
    'catalog-generations/invalid/documents.parquet', KEY + '/extra',
    'catalog-history/sha256/' + 'b' * 63 + '/documents.parquet'])
def test_derived_api_rejects_every_other_namespace(tmp_path, key):
    for store in (LocalStore(tmp_path), R2Store(Client(), 'bucket')):
        with pytest.raises(ValueError, match='exact catalog'):
            store.read_derived_file(key, tmp_path / 'out')
        with pytest.raises(ValueError, match='exact catalog'):
            store.put_derived_file(key, tmp_path / 'missing', expected=identity(b''))


def test_snapshot_owns_files_until_context_exit_and_reads_selector_once(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / 'store')
    publish_catalog(store, *pair(tmp_path / 'build'), previous=read_catalog(store))
    original = store.read
    reads = []
    def read(key):
        reads.append(key)
        assert key == MANIFEST_KEY  # Tables cannot take the whole-bytes route.
        return original(key)
    monkeypatch.setattr(store, 'read', read)
    with read_catalog(store) as snapshot:
        assert snapshot.filenames_path.is_file() and snapshot.documents_path.is_file()
        directory = snapshot.directory
        assert snapshot.files['filenames']['sha256'] == file_identity(snapshot.filenames_path)['sha256']
    assert reads == [MANIFEST_KEY] and not directory.exists()


def test_snapshot_failure_retains_actual_diagnostic_path(tmp_path):
    store = LocalStore(tmp_path / 'store')
    publish_catalog(store, *pair(tmp_path / 'build'), previous=read_catalog(store))
    with pytest.raises(RuntimeError) as caught:
        with read_catalog(store) as snapshot:
            raise RuntimeError('later build failure')
    assert snapshot.directory.is_dir()
    assert str(snapshot.directory) in '\n'.join(caught.value.__notes__)
    assert snapshot.filenames_path.is_file()


@pytest.mark.parametrize('data,size,expected', [
    (b'abc', 4, None), (b'abc', 2, None), (b'abc', 3, identity(b'xyz'))])
def test_bad_stream_retains_partial_and_never_publishes(tmp_path, data, size, expected):
    output = tmp_path / 'table'
    with pytest.raises(ValueError) as caught:
        copy_checked(io.BytesIO(data), output, size=size, expected=expected)
    assert not output.exists()
    partial = Path(caught.value.__notes__[-1].split(': ', 1)[1])
    assert partial.is_file()


def test_directory_fsync_failure_retains_named_evidence_and_old_selector(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / 'store')
    publish_catalog(store, *pair(tmp_path / 'first'), previous=read_catalog(store))
    with read_catalog(store) as previous:
        selector = (store.root / MANIFEST_KEY).read_bytes()
        original = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('injected directory fsync failure')
            return original(fd)
        monkeypatch.setattr(os, 'fsync', fail_directory)
        with pytest.raises(OSError, match='directory fsync') as caught:
            publish_catalog(store, *pair(tmp_path / 'second', 'two'), previous=previous)
        assert (store.root / MANIFEST_KEY).read_bytes() == selector
        partial = Path(next(note.split(': ', 1)[1] for note in caught.value.__notes__
                            if note.startswith('Owned catalog partial')))
        assert partial.is_file() and partial.stat().st_size > 0


def test_local_immutable_racing_destination_cannot_be_replaced(tmp_path, monkeypatch):
    source = tmp_path / 'input'; source.write_bytes(b'candidate')
    store = LocalStore(tmp_path / 'store')
    original = os.link
    def race(src, dst):
        Path(dst).write_bytes(b'concurrent')
        return original(src, dst)
    monkeypatch.setattr(os, 'link', race)
    with pytest.raises(ValueError, match='checksum'):
        store.put_derived_file(KEY, source, expected=file_identity(source))
    assert (store.root / KEY).read_bytes() == b'concurrent'


def test_selected_local_tables_are_hashed_once(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    publish_catalog(store, *pair(tmp_path / 'build'), previous=read_catalog(store))
    import congress_api.retention.catalog_publication as publication
    original = publication.file_identity
    calls = []
    def count(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(publication, 'file_identity', count)
    paths = local_catalog_paths(tmp_path)
    assert calls == list(paths)


def test_derived_remote_upload_streams_and_checks_expected_identity(tmp_path):
    source = tmp_path / 'source'; source.write_bytes(b'catalog')
    client = Client(); store = R2Store(client, 'bucket')
    assert store.put_derived_file(KEY, source, expected=file_identity(source))
    assert client.data == b'catalog' and client.puts[0]['Body'].closed
    assert not store.index_etags
    with pytest.raises(ValueError, match='checksum'):
        store.put_derived_file(KEY, source, expected=identity(b'bad'))
    assert len(client.puts) == 1


@pytest.mark.parametrize('second_version', ['original', 'changed'])
def test_derived_remote_retry_pins_etag_and_preserves_partial(tmp_path, monkeypatch, second_version):
    class Broken(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024**2
            raise ReadTimeoutError(endpoint_url='fixture')
    monkeypatch.setattr('congress_api.retention.r2.time.sleep', lambda _: None)
    broken, good = Broken(), io.BytesIO(b'catalog')
    client = Client()
    client.responses = [dict(Body=broken, ContentLength=7, ETag='original'),
                        dict(Body=good, ContentLength=7, ETag=second_version)]
    store = R2Store(client, 'bucket')
    output = tmp_path / 'out'
    if second_version == 'changed':
        with pytest.raises(ValueError, match='changed'):
            store.read_derived_file(KEY, output, expected=identity(b'catalog'))
        assert not output.exists()
    else:
        assert store.read_derived_file(KEY, output, expected=identity(b'catalog'))['version'] == 'original'
        assert output.read_bytes() == b'catalog'
    assert broken.closed and good.closed
    assert client.reads[1]['IfMatch'] == 'original'
    assert list(tmp_path.glob('*.partial'))


def test_history_collision_verifies_remote_contents_by_stream(tmp_path):
    source = tmp_path / 'source'; source.write_bytes(b'catalog')
    client = Client(); store = R2Store(client, 'bucket')
    def collision(**kwargs):
        raise ClientError({'Error': {'Code': '412'}}, 'PutObject')
    client.put_object = collision
    client.responses = [dict(Body=io.BytesIO(b'catalog'), ContentLength=7, ETag='version')]
    props = file_identity(source)
    key = f"catalog-history/sha256/{props['sha256']}/documents.parquet"
    assert store.put_derived_file(key, source, expected=props) is False
    with pytest.raises(RuntimeError, match='generation'):
        store.put_derived_file(KEY, source, expected=props)


def test_previous_snapshot_paths_stay_alive_through_history_then_close(tmp_path, monkeypatch):
    from test_raw_catalog import initialize
    from historical_raw_catalog import rebuild_catalog
    store = initialize(tmp_path)
    original_read, original_put = store.read_derived_file, store.put_derived_file
    owned, archived = [], []
    def read(key, path, **kwargs):
        result = original_read(key, path, **kwargs)
        if result:
            owned.append(path)
        return result
    def put(key, path, **kwargs):
        if key.startswith('catalog-history/'):
            assert path in owned and path.is_file()
            assert all(p.is_file() for p in owned)
            archived.append(path)
        return original_put(key, path, **kwargs)
    monkeypatch.setattr(store, 'read_derived_file', read)
    monkeypatch.setattr(store, 'put_derived_file', put)
    rebuild_catalog(store, workers=1)
    assert len(archived) == len(owned) == 2
    assert all(not path.exists() for path in owned)


def test_catalog_publication_requires_explicit_capabilities_before_any_write(tmp_path):
    from types import SimpleNamespace
    writes = []
    adapter = SimpleNamespace(put=lambda *a, **kw: writes.append(a),
                              put_derived_file=lambda *a, **kw: writes.append(a))
    with pytest.raises(TypeError, match='conditional selector'):
        publish_catalog(adapter, *pair(tmp_path / 'build'), previous=SimpleNamespace(version=None))
    assert writes == []


def test_small_catalog_selector_reads_have_explicit_budget_and_keep_missing_behavior(tmp_path):
    store = LocalStore(tmp_path)
    assert store.read(MANIFEST_KEY) is None
    path = tmp_path / MANIFEST_KEY; path.parent.mkdir(); path.write_bytes(b'x' * (1024**2 + 1))
    with pytest.raises(ValueError, match='read budget'):
        store.read(MANIFEST_KEY)


def test_local_small_immutable_two_writer_conflict_preserves_first_bytes(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    original = os.link
    def race(source, destination):
        Path(destination).write_bytes(b'first writer')
        return original(source, destination)
    monkeypatch.setattr(os, 'link', race)
    with pytest.raises(ValueError, match='Conflicting immutable'):
        store.put('receipts/immutable.json', b'second writer', immutable=True)
    assert store.read('receipts/immutable.json') == b'first writer'


def test_owned_retained_link_reuses_hash_and_bytes_and_invalidates_on_mutation(tmp_path, monkeypatch):
    from congress_api.retention.derived_files import retain_verified_file, VerifiedFile
    source = tmp_path / 'owned'; source.write_bytes(b'owned immutable catalog bytes')
    identity = file_identity(source)
    destination = tmp_path / 'retained' / 'documents.parquet'
    import congress_api.retention.derived_files as files
    monkeypatch.setattr(files, 'file_identity', lambda *_: pytest.fail('duplicate full hash'))
    saved = retain_verified_file(source, destination, expected=identity, key=KEY)
    assert source.stat().st_ino == destination.stat().st_ino
    assert saved.require(destination) and identity.require(source)
    source.unlink()
    # Removing an owned alias changes link count, even when ctime stays unchanged.
    with pytest.raises(ValueError, match='custody'):
        saved.require(destination)
    assert destination.read_bytes() == b'owned immutable catalog bytes'
    with pytest.raises(ValueError, match='custody'):
        VerifiedFile(saved).require(destination)


def test_proven_remote_file_checks_sha_and_md5_in_one_preflight_read(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.write_bytes(b'catalog' * 100)
    proof = file_identity(source)
    client = Client(); store = R2Store(client, 'bucket')
    original_open = Path.open
    read_bytes = []
    class CountedReader:
        def __init__(self, stream): self.stream = stream
        def __getattr__(self, name): return getattr(self.stream, name)
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def read(self, *args):
            chunk = self.stream.read(*args)
            read_bytes.append(len(chunk))
            return chunk
    def counted_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return CountedReader(stream) if path == source and args == ('rb',) else stream
    monkeypatch.setattr(Path, 'open', counted_open)
    assert store.put_derived_file(KEY, source, expected=proof)
    # One shared SHA/MD5 preflight read, then the service consumes the upload.
    assert sum(read_bytes) == 2 * len(b'catalog' * 100)
    assert client.data == b'catalog' * 100
    source.write_bytes(b'changed' * 100)
    with pytest.raises(ValueError, match='custody|checksum'):
        store.put_derived_file(KEY, source, expected=proof)
    assert len(client.puts) == 1


def test_remote_selector_budget_closes_response_and_never_authorizes_partial_read():
    client = Client(); store = R2Store(client, 'bucket')
    body = io.BytesIO(b'{}')
    client.responses.append(dict(Body=body, ContentLength=1024**2 + 1, ETag='oversized'))
    with pytest.raises(ValueError, match='read budget'):
        store.read(MANIFEST_KEY)
    assert body.closed and MANIFEST_KEY not in store.index_etags
    body = io.BytesIO(b'{')
    client.responses.append(dict(Body=body, ContentLength=2, ETag='partial'))
    with pytest.raises(ValueError, match='Incomplete'):
        store.read(MANIFEST_KEY)
    assert body.closed and MANIFEST_KEY not in store.index_etags


def test_file_proof_does_not_survive_an_inherited_process_registry(tmp_path, monkeypatch):
    path = tmp_path / 'source'; path.write_bytes(b'bound')
    proof = file_identity(path)
    process = os.getpid()
    monkeypatch.setattr(os, 'getpid', lambda: process + 1)
    with pytest.raises(ValueError, match='custody'):
        proof.require(path)


@pytest.mark.parametrize('handoff', ['issued', 'serialized', 'changed', 'serialized_changed'])
def test_remote_snapshot_history_handoff_preserves_proof_and_rechecks_restored_facts(tmp_path, monkeypatch, handoff):
    import json
    from congress_api.retention.derived_files import VerifiedFile

    paths = pair(tmp_path / 'build')
    generation = 'a' * 32
    manifest = dict(version=1, generation=generation, catalog_id='one', files={})
    payloads = []
    for label, path in zip(('filenames', 'documents'), paths):
        data = path.read_bytes()
        manifest['files'][label] = dict(key=f'catalog-generations/{generation}/{path.name}',
                                      rows=1, **identity(data))
        payloads.append(data)
    client = Client()
    responses = [dict(Body=io.BytesIO(data), ContentLength=len(data), ETag=version)
                 for data, version in [(json.dumps(manifest).encode(), 'selector'),
                                       (payloads[0], 'filenames-v1'), (payloads[1], 'documents-v1')]]
    client.responses = list(responses)
    store = R2Store(client, 'bucket')
    with read_catalog(store) as snapshot:
        path, proof = snapshot.filenames_path, snapshot.files['filenames']
        assert isinstance(proof, VerifiedFile)
        assert proof.require(path) is proof
        assert proof == dict(manifest['files']['filenames'], version='filenames-v1', catalog_id='one')
        expected = json.loads(json.dumps(proof)) if handoff.startswith('serialized') else proof
        if handoff.endswith('changed'):
            path.write_bytes(payloads[0][:-1] + bytes([payloads[0][-1] ^ 1]))
        hashed_bytes = []
        original = hashlib.sha256
        class Counted:
            def __init__(self): self.digest = original()
            def update(self, data):
                hashed_bytes.append(len(data)); self.digest.update(data)
            def hexdigest(self): return self.digest.hexdigest()
        monkeypatch.setattr(hashlib, 'sha256', Counted)
        key = f"catalog-history/sha256/{proof['sha256']}/document-filenames.parquet"
        if handoff.endswith('changed'):
            with pytest.raises(ValueError, match='checksum' if handoff == 'serialized_changed' else 'custody|checksum'):
                store.put_derived_file(key, path, expected=expected)
            assert not client.puts
        else:
            assert store.put_derived_file(key, path, expected=expected)
            assert client.data == payloads[0]
        # Actual bytes are SHA-checked in the transport MD5 pass. A changed
        # issued file may instead be rejected by its metadata before that read.
        assert sum(hashed_bytes) in ({0, len(payloads[0])} if handoff == 'changed' else {len(payloads[0])})
    assert not client.responses and all(response['Body'].closed for response in responses)


@pytest.mark.parametrize('handoff', ['issued', 'serialized', 'changed', 'serialized_changed'])
def test_remote_read_to_owned_retention_reuses_only_issued_file_custody(tmp_path, monkeypatch, handoff):
    import json
    import congress_api.retention.derived_files as files

    data = b'owned remote catalog bytes'
    body = io.BytesIO(data)
    client = Client()
    client.responses = [dict(Body=body, ContentLength=len(data), ETag='source-version')]
    source = tmp_path / 'download.parquet'
    proof = R2Store(client, 'bucket').read_derived_file(KEY, source, expected=identity(data))
    assert proof['version'] == 'source-version' and body.closed
    expected = json.loads(json.dumps(proof)) if handoff.startswith('serialized') else proof
    if handoff.endswith('changed'):
        source.write_bytes(data[:-1] + b'!')
    hashed_bytes = []
    original = files.sha256
    class Counted:
        def __init__(self): self.digest = original()
        def update(self, value):
            hashed_bytes.append(len(value)); self.digest.update(value)
        def hexdigest(self): return self.digest.hexdigest()
    monkeypatch.setattr(files, 'sha256', Counted)
    destination = tmp_path / 'retained' / 'documents.parquet'
    if handoff.endswith('changed'):
        with pytest.raises(ValueError, match='checksum' if handoff == 'serialized_changed' else 'custody|checksum'):
            files.retain_verified_file(source, destination, expected=expected, key=KEY)
        assert not destination.exists()
    else:
        retained = files.retain_verified_file(source, destination, expected=expected, key=KEY)
        assert retained.require(destination)
        assert destination.stat().st_ino == source.stat().st_ino
        assert destination.read_bytes() == data
        if handoff == 'issued':
            assert retained['version'] == 'source-version'
    assert sum(hashed_bytes) == (len(data) if handoff.startswith('serialized') else 0)


def test_derived_upload_rejects_same_tick_same_size_mutation_before_put(tmp_path, monkeypatch):
    import congress_shared.custody as custody
    import congress_api.retention.derived_files as files

    source = tmp_path / "source"
    source.write_bytes(b"catalog" * 100)
    original_identity = custody.custody_identity
    def unchanged_timestamps(path):
        value = list(original_identity(path))
        value[3:5] = [1, 1]
        return tuple(value)
    monkeypatch.setattr(custody, "custody_identity", unchanged_timestamps)
    monkeypatch.setattr(files, "custody_identity", unchanged_timestamps)
    proof = file_identity(source)
    source.write_bytes(b"changed" * 100)
    assert custody.custody_identity(source) == proof.custody  # Metadata alone misses these bytes.
    client = Client()
    with pytest.raises(ValueError, match="checksum"):
        R2Store(client, "bucket").put_derived_file(KEY, source, expected=proof)
    assert client.puts == []
