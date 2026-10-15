"""Accepted statuses survive publications without changing archived content."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

scripts = Path(__file__).resolve().parents[1] / 'apps/site/scripts'
sys.path.insert(0, str(scripts))
from filename_recoveries import ACCEPTED_KEY, accepted_rows, index_recoveries

spec = importlib.util.spec_from_file_location('recovery_publisher', scripts / 'publish-viewer-r2.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def fixture(tmp_path):
    body = 'bodies/sha256/aa/' + 'a' * 64 + '.gz'
    accepted = [{'original_url': 'https://committee.test/file.pdf', 'recovered_url': 'http://committee.test/file.pdf',
                 'body_key': body, 'kind': 'pdf', 'recovery_status': 'recovered', 'recovery_basis': 'user_accepted_url_variant'}]
    rows = [{'source_url': accepted[0]['original_url'], 'body_key': 'original-error-body'},
            {'source_url': accepted[0]['recovered_url'], 'body_key': body},
            {'source_url': 'https://unrelated.test/', 'body_key': None}]
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / 'filenames.parquet')
    (tmp_path / 'groups.bin').write_bytes(struct.pack('<III', 0, 1, 2))
    files = {name: {'path': filename, 'bytes': (tmp_path / filename).stat().st_size,
                    'sha256': hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()}
             for name, filename in [('filenames', 'filenames.parquet'), ('groups', 'groups.bin')]}
    manifest = {'info': {'catalog_id': 'b' * 32, 'rows': 3, 'entries': 3}, 'files': files}
    return accepted, manifest, rows


def test_indexes_original_and_retained_copy_without_rewriting_values(tmp_path):
    accepted, manifest, original = fixture(tmp_path)
    result = index_recoveries(tmp_path, manifest, accepted)
    assert result['sources'] == [[0, 0], [1, 0]]
    assert result['groups'] == [[0, [0]], [1, [0]]]
    assert result['recoveries'] == accepted
    assert pq.read_table(tmp_path / 'filenames.parquet').to_pylist() == original
    (tmp_path / 'groups.bin').write_bytes(struct.pack('<III', 2, 1, 0))
    with pytest.raises(ValueError, match='hash mismatch'):
        index_recoveries(tmp_path, manifest, accepted)


def test_duplicate_acceptance_and_non_http_urls_are_rejected(tmp_path):
    accepted, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='duplicate'):
        accepted_rows(accepted * 2)
    with pytest.raises(ValueError, match='URL'):
        accepted_rows([dict(accepted[0], recovered_url='javascript:bad()')])


@pytest.mark.parametrize('basis', ['verified_archive_capture', 'official_document_identifier'])
def test_recovery_basis_survives_publication(tmp_path, basis):
    accepted, manifest, _ = fixture(tmp_path)
    accepted[0]['recovery_basis'] = basis
    assert index_recoveries(tmp_path, manifest, accepted)['recoveries'] == accepted
    with pytest.raises(ValueError):
        accepted_rows([dict(accepted[0], recovery_basis='unverified_guess')])


@pytest.mark.parametrize('kind', ['pdf', 'doc', 'video'])
def test_future_publications_reindex_durable_acceptance(tmp_path, monkeypatch, kind):
    accepted, manifest, _ = fixture(tmp_path)
    accepted[0]['kind'] = kind
    monkeypatch.setattr(publisher, 'read_json', lambda client, key, **kw: ({'version': 1, 'recoveries': accepted}, 'etag', None) if key == ACCEPTED_KEY else None)
    stored = []
    monkeypatch.setattr(publisher, 'store_recovery_index', lambda client, value: stored.append(value) or {'path': 'recovery.json'})
    publisher.recovery_for_publication(None, tmp_path, manifest)
    # A future catalog changes both identity and group positions.
    manifest['info']['catalog_id'] = 'c' * 32
    (tmp_path / 'groups.bin').write_bytes(struct.pack('<III', 2, 0, 1))
    manifest['files']['groups']['sha256'] = hashlib.sha256((tmp_path / 'groups.bin').read_bytes()).hexdigest()
    publisher.recovery_for_publication(None, tmp_path, manifest)
    assert stored[0]['catalog_id'] == 'b' * 32
    assert stored[1]['catalog_id'] == 'c' * 32
    assert stored[1]['groups'] == [[0, [0]], [2, [0]]]


def test_sidecar_readback_checks_actual_bytes_and_only_writes_viewer_keys(monkeypatch):
    writes = []
    monkeypatch.setattr(publisher, 'put_json', lambda client, key, value, **condition: writes.append((key, value, condition)))
    class Client:
        def get_object(self, **kw):
            return {'Body': io.BytesIO(publisher.encoded(writes[-1][1]))}
    descriptor = publisher.store_recovery_index(Client(), {'version': 1, 'recoveries': []})
    assert writes[0][0] == publisher.PREFIX + descriptor['path']
    assert writes[0][2] == {'IfNoneMatch': '*'}
    class Corrupt:
        def get_object(self, **kw):
            return {'Body': io.BytesIO(b'{}')}
    with pytest.raises(ValueError, match='readback'):
        publisher.store_recovery_index(Corrupt(), {'version': 1})


def test_status_only_publication_uses_conditional_pointer_and_preserves_catalog(tmp_path, monkeypatch):
    accepted, manifest, original = fixture(tmp_path)
    selected = {'catalog_id': manifest['info']['catalog_id'], 'generation': 'a' * 32}
    manifest['source_manifest'] = selected
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    pointer = {'version': 1, 'catalog_id': selected['catalog_id'], 'source_manifest': selected,
               'manifest': 'releases/' + 'c' * 32 + '/manifest.json'}
    stored = {'indexes/catalog.json': selected, publisher.PREFIX + 'manifest.json': pointer,
              publisher.PREFIX + pointer['manifest']: manifest}
    writes = []
    def read(client, key, **kw):
        return stored.get(key), 'original-etag', None
    def put(client, key, value, **condition):
        assert key.startswith(publisher.PREFIX)
        writes.append((key, condition))
        stored[key] = value
    class Client:
        def get_object(self, **kw):
            return {'Body': io.BytesIO(publisher.encoded(stored[kw['Key']]))}
    class Public(io.BytesIO):
        headers = {'Access-Control-Allow-Origin': '*'}
    monkeypatch.setattr(publisher, 'read_json', read)
    monkeypatch.setattr(publisher, 'put_json', put)
    monkeypatch.setattr(publisher, 'open_public', lambda request: Public(publisher.encoded(stored[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)])))
    result = publisher.accept_recoveries(Client(), tmp_path, accepted)
    assert result['accepted_recoveries'] == 1 and result['affected_groups'] == 2
    assert writes[-1] == (publisher.PREFIX + 'manifest.json', {'IfMatch': 'original-etag'})
    assert len(writes) == 3
    assert stored['indexes/catalog.json'] == selected
    assert pq.read_table(tmp_path / 'filenames.parquet').to_pylist() == original
    # Repeated application reuses the same status index and does not reselect the pointer.
    before = len(writes)
    publisher.accept_recoveries(Client(), tmp_path, accepted)
    assert writes[before:][0][0].startswith(publisher.PREFIX + 'releases/')
    assert len(writes[before:]) == 1
