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

from viewer_publication.filename_recoveries import ACCEPTED_KEY, accepted_rows, index_recoveries

from viewer_publication import publish_viewer_r2 as publisher


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
    monkeypatch.setattr(publisher, 'read_identity', lambda client, key, **kw: ({'version': 1, 'recoveries': accepted}, 'etag', None, 'digest') if key == ACCEPTED_KEY else None)
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


def test_sidecar_accepts_successful_upload_without_readback_and_only_writes_viewer_keys(monkeypatch):
    writes = []
    monkeypatch.setattr(publisher, 'put_json', lambda client, key, value, **condition: writes.append((key, value, condition)))
    class Client:
        def get_object(self, **kwargs):
            pytest.fail('Successful recovery upload was read back')
    descriptor = publisher.store_recovery_index(Client(), {'version': 1, 'recoveries': []})
    assert writes[0][0] == publisher.PREFIX + descriptor['path']
    assert writes[0][2] == {'IfNoneMatch': '*'}


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
    monkeypatch.setattr(publisher, 'read_identity', lambda client, key, **kw: (*read(client, key, **kw), hashlib.sha256(publisher.encoded(stored.get(key))).hexdigest()))
    monkeypatch.setattr(publisher, 'put_json', put)
    monkeypatch.setattr(publisher, 'open_public', lambda request: Public(publisher.encoded(stored[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)])))
    stored[ACCEPTED_KEY] = {'version': 1, 'recoveries': accepted}
    def publish_prepared_status():
        selected_record=publisher.read_identity(Client(),'indexes/catalog.json')
        accepted_record=publisher.read_identity(Client(),ACCEPTED_KEY)
        pointer_record=publisher.read_identity(Client(),publisher.PREFIX+'manifest.json')
        prepared=publisher.prepare_recovery(tmp_path,manifest,accepted_record)
        return publisher.select_recoveries(Client(),tmp_path,manifest,selected_record,accepted_record,pointer_record,'digest',public_url=publisher.PUBLIC_URL,index=prepared['value'])
    result = publish_prepared_status()
    assert result['accepted_recoveries'] == 1 and result['affected_groups'] == 2
    assert writes[-1] == (publisher.PREFIX + 'manifest.json', {'IfMatch': 'original-etag'})
    assert len(writes) == 2
    assert stored['indexes/catalog.json'] == selected
    assert pq.read_table(tmp_path / 'filenames.parquet').to_pylist() == original
    # Repeated application reuses the same status index and does not reselect the pointer.
    before = len(writes)
    publish_prepared_status()
    assert writes[before:][0][0].startswith(publisher.PREFIX + 'releases/')
    assert len(writes[before:]) == 1


@pytest.mark.parametrize('damage', ['missing_filenames', 'corrupt_groups'])
def test_acceptance_validates_prepared_files_before_any_write(tmp_path, monkeypatch, damage):
    accepted, manifest, _ = fixture(tmp_path)
    selected = {'catalog_id': manifest['info']['catalog_id'], 'generation': 'a' * 32}
    manifest['source_manifest'] = selected
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    pointer = {'catalog_id': selected['catalog_id'], 'source_manifest': selected,
               'manifest': 'releases/' + 'c' * 32 + '/manifest.json'}
    stored = {'indexes/catalog.json': selected, publisher.PREFIX + 'manifest.json': pointer,
              publisher.PREFIX + pointer['manifest']: manifest}
    monkeypatch.setattr(publisher, 'read_identity', lambda client, key, **kw:
                        (stored[key], 'etag', None, 'digest'))
    monkeypatch.setattr(publisher, 'read_json', lambda *args, **kw: (None, None, None))
    monkeypatch.setattr(publisher, 'put_json', lambda *args, **kw: pytest.fail('Invalid preparation must not write'))
    if damage == 'missing_filenames':
        (tmp_path / 'filenames.parquet').unlink()
    else:
        (tmp_path / 'groups.bin').write_bytes(struct.pack('<III', 2, 1, 0))
    with pytest.raises((OSError, ValueError)):
        publisher.prepare_recovery(tmp_path, manifest, ({'version':1,'recoveries':accepted},'etag',None,'digest'))


def alias_fixture(tmp_path):
    accepted, manifest, rows = fixture(tmp_path)
    rows[2]['source_url'] = '../file.pdf'
    for row in rows:
        row['source_resolved_url'] = [accepted[0]['recovered_url']] if row is rows[2] else None
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / 'filenames.parquet')
    path = tmp_path / 'filenames.parquet'
    manifest['files']['filenames'].update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return accepted, manifest, rows


def test_catalog_alias_attaches_saved_copy_to_original_group(tmp_path):
    accepted, manifest, rows = alias_fixture(tmp_path)
    result = index_recoveries(tmp_path, manifest, accepted)
    assert result['sources'] == [[0, 0], [1, 0], [2, 1]]
    assert result['groups'] == [[0, [0]], [1, [0]], [2, [1]]]
    assert result['recoveries'][1]['original_url'] == '../file.pdf'
    assert result['recoveries'][1]['body_key'] == accepted[0]['body_key']
    assert result['recoveries'][0] == accepted[0]
    assert pq.read_table(tmp_path / 'filenames.parquet').to_pylist() == rows


def test_aliases_publish_without_any_manual_acceptances(tmp_path, monkeypatch):
    _, manifest, _ = alias_fixture(tmp_path)
    monkeypatch.setattr(publisher, 'read_identity', lambda *args, **kwargs: (None, None, None, None))
    stored = []
    monkeypatch.setattr(publisher, 'store_recovery_index', lambda client, value: stored.append(value) or {'path': 'recovery.json'})
    assert publisher.recovery_for_publication(None, tmp_path, manifest)[0] == {'path': 'recovery.json'}
    assert stored[0]['groups'] == [[2, [0]]]


def test_same_catalog_refreshes_new_accepted_mappings(tmp_path, monkeypatch):
    accepted, manifest, _ = fixture(tmp_path)
    selected = {'catalog_id': manifest['info']['catalog_id']}
    manifest['source_manifest'] = selected
    pointer = {'source_manifest': selected, 'publisher_version': publisher.PUBLISHER_VERSION,
               'full_release_inputs': publisher.full_release_identity(),
               'catalog_id': selected['catalog_id'], 'manifest': 'releases/current/manifest.json'}
    objects = {'indexes/catalog.json': selected, publisher.PREFIX + 'manifest.json': pointer,
               publisher.PREFIX + pointer['manifest']: manifest,
               ACCEPTED_KEY: {'version': 1, 'recoveries': accepted}}
    monkeypatch.setattr(publisher, 'read_json', lambda client, key, **kw: (objects[key], 'etag', None))
    monkeypatch.setattr(publisher, 'read_identity', lambda client, key, **kw: (objects.get(key), 'etag', None, hashlib.sha256(publisher.encoded(objects.get(key))).hexdigest()))
    downloads = []
    class Client:
        def download_file(self, bucket, key, destination):
            downloads.append(key)
            Path(destination).write_bytes((tmp_path / Path(key).name).read_bytes())
    def accept(client, root, manifest, selected_record, accepted_record, pointer_record, manifest_digest, **kwargs):
        result = index_recoveries(root, manifest, accepted_record[0]['recoveries'])
        assert result['sources'] == [[0, 0], [1, 0]]
        return {'status': 'recovery_updated'}
    monkeypatch.setattr(publisher, 'select_recoveries', accept)
    assert publisher.check_selected_publication(Client(),pointer)['status'] == 'recovery_preparation_required'
    assert downloads == []
    prepared = publisher.prepare_recovery(tmp_path,manifest,publisher.read_identity(Client(),ACCEPTED_KEY))
    assert prepared['value']['sources'] == [[0,0],[1,0]]


def test_shape_valid_wrong_shard_body_key_is_rejected_before_indexing(tmp_path):
    accepted, _, _ = fixture(tmp_path)
    accepted[0]['body_key'] = accepted[0]['body_key'].replace('/aa/', '/bb/')
    with pytest.raises(ValueError, match='Invalid'):
        accepted_rows(accepted)


def test_spilled_alias_index_scans_source_once_and_preserves_high_fanout_mapping(tmp_path):
    count = 1000
    rows = [dict(source_url=f'https://old.test/{index:04}', source_resolved_url=['https://new.test/shared.pdf'], body_key=None)
            for index in range(count)]
    body = 'bodies/sha256/aa/' + 'a' * 64 + '.gz'
    rows.append(dict(source_url='https://new.test/shared.pdf', body_key=body, source_resolved_url=None))
    # An invalid/self value remains conflict evidence even beside a usable target.
    rows += [dict(source_url='https://old.test/conflict', body_key=None,
                  source_resolved_url=['https://new.test/shared.pdf', 'javascript:invalid'])]
    path = tmp_path / 'filenames.parquet'; pq.write_table(pa.Table.from_pylist(rows), path)
    (tmp_path / 'groups.bin').write_bytes(b''.join(struct.pack('<I', index % 7) for index in range(len(rows))))
    files = {name: dict(path=file.name, bytes=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest())
             for name, file in [('filenames', path), ('groups', tmp_path / 'groups.bin')]}
    manifest = dict(files=files, info=dict(rows=len(rows), entries=7, catalog_id='bounded'))
    metrics = {}
    result = index_recoveries(tmp_path, manifest, [], metrics=metrics)
    assert len(result['recoveries']) == count
    assert result['sources'] == [[index, index] for index in range(count)]
    assert result['groups'] == [[group, list(range(group, count, 7))] for group in range(7)]
    assert metrics['source_scans'] == 1 and metrics['max_batch_rows'] <= 128
    assert metrics['sqlite_cache_kib'] == 8192 and metrics['scratch_bytes'] > 0


def test_alias_output_budget_refuses_without_returning_partial_status(tmp_path, monkeypatch):
    import viewer_publication.filename_alias_index as filename_alias_index
    import shutil
    accepted, manifest, _ = alias_fixture(tmp_path)
    monkeypatch.setattr(filename_alias_index, 'OUTPUT_BYTES', 10)
    with pytest.raises(ValueError, match='output budget') as caught:
        index_recoveries(tmp_path, manifest, accepted)
    folder = Path(next(note.split(': ', 1)[1] for note in caught.value.__notes__ if note.startswith('Owned alias index')))
    assert folder.is_dir()
    shutil.rmtree(folder)


@pytest.mark.parametrize('unicode_url', [False, True])
def test_status_header_and_separators_count_toward_exact_final_output_budget(tmp_path, monkeypatch, unicode_url):
    import viewer_publication.filename_alias_index as filename_alias_index
    import shutil
    accepted, manifest, _ = fixture(tmp_path)
    if unicode_url:
        accepted[0]['original_url'] += '/José-🏛️'
    result = index_recoveries(tmp_path, manifest, accepted)
    size = len(publisher.encoded(result))
    monkeypatch.setattr(filename_alias_index, 'OUTPUT_BYTES', size - 1)
    with pytest.raises(ValueError, match='output budget') as caught:
        index_recoveries(tmp_path, manifest, accepted)
    folder = Path(next(note.split(': ', 1)[1] for note in caught.value.__notes__ if note.startswith('Owned alias index')))
    assert folder.is_dir(); shutil.rmtree(folder)
    monkeypatch.setattr(filename_alias_index, 'OUTPUT_BYTES', size)
    metrics = {}
    assert index_recoveries(tmp_path, manifest, accepted, metrics=metrics) == result
    assert metrics['exact_output_bytes'] == size


def test_exact_final_budget_matches_empty_recovery_arrays(tmp_path):
    _, manifest, _ = fixture(tmp_path)
    metrics = {}
    value = index_recoveries(tmp_path, manifest, [], metrics=metrics)
    assert value['recoveries'] == value['sources'] == value['groups'] == []
    assert metrics['exact_output_bytes'] == len(publisher.encoded(value))
