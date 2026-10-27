"""Node reuse keeps exact byte identity, file custody and independent results."""
from collections import Counter
import os

import pytest

from congress_api.retention import derived_files
from viewer_publication import filename_native as native
from viewer_publication.filename_renderer_state import RendererState


VALUE = {'version': 1, 'kind': 'probe', 'rows': [1, 2]}


def test_retained_node_reuses_checked_copy_proof_without_destination_rehash(tmp_path, monkeypatch):
    counts = Counter()
    address_hash, file_hash, identity = native.sha256, derived_files.sha256, native.file_identity
    def address(*args, **kwargs):
        counts['address_hashes'] += 1
        return address_hash(*args, **kwargs)
    def file_or_copy(*args, **kwargs):
        counts['file_or_copy_hashes'] += 1
        return file_hash(*args, **kwargs)
    def destination(path):
        counts['destination_rehashes'] += 1
        return identity(path)
    monkeypatch.setattr(native, 'sha256', address)
    monkeypatch.setattr(derived_files, 'sha256', file_or_copy)
    monkeypatch.setattr(native, 'file_identity', destination)
    assets = native.ViewerAssets(tmp_path / 'publication')
    with RendererState(assets.root, {'fixture': 'node'}) as state:
        assets.state = state
        reference = assets.put_node(VALUE)
        assert counts == dict(address_hashes=1, file_or_copy_hashes=1)
        proof = assets.identities[reference['path']]
        assert proof.require(assets.root / reference['path']) is proof
        assert state.db.execute('SELECT path,bytes,sha256 FROM assets').fetchall() == [
            (reference['path'], reference['bytes'], reference['sha256'])]


def test_three_node_reads_hash_once_and_parse_independent_results(tmp_path, monkeypatch):
    assets = native.ViewerAssets(tmp_path)
    reference = assets.put_node(VALUE)
    counts = Counter()
    hash_bytes, parse = native.sha256, native.json.loads
    def hashed(raw):
        counts['hashes'] += 1
        counts['hashed_bytes'] += len(raw)
        return hash_bytes(raw)
    def parsed(raw):
        counts['parses'] += 1
        return parse(raw)
    monkeypatch.setattr(native, 'sha256', hashed)
    monkeypatch.setattr(native.json, 'loads', parsed)
    first = assets.read_node(reference)
    first['rows'].append(99)
    second, third = assets.read_node(reference), assets.read_node(reference)
    assert second == third == VALUE
    assert second is not third and second['rows'] is not third['rows']
    assert assets.reads == 1
    assert counts == dict(hashes=1, hashed_bytes=reference['bytes'], parses=3)


@pytest.mark.parametrize('field,value', [('bytes', 42), ('sha256', 'f' * 64), ('path', 'elsewhere.json')])
def test_cached_node_rejects_wrong_reference_facts(tmp_path, field, value):
    assets = native.ViewerAssets(tmp_path)
    reference = assets.put_node(VALUE)
    assert assets.read_node(reference) == VALUE
    with pytest.raises(ValueError, match='reference|identity differs'):
        assets.read_node(dict(reference, **{field: value}))
    assert assets.read_node(reference) == VALUE


def test_validly_addressed_wrong_digest_still_checks_acquired_bytes(tmp_path):
    raw = native.encoded(VALUE)
    digest = 'f' * 64
    reference = dict(path=f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/page.json',
                     sha256=digest, bytes=len(raw))
    assets = native.ViewerAssets(tmp_path, read_asset=lambda key: raw)
    with pytest.raises(ValueError, match='identity differs'):
        assets.read_node(reference)
    assert not assets._nodes


def test_cached_acquired_bytes_are_immutable_and_detached(tmp_path):
    producer = native.ViewerAssets(tmp_path / 'producer')
    reference = producer.put_node(VALUE)
    raw = bytearray((producer.root / reference['path']).read_bytes())
    assets = native.ViewerAssets(tmp_path / 'consumer', read_asset=lambda key: raw)
    assert assets.read_node(reference) == VALUE
    raw[:] = b'X' * len(raw)
    assert assets.read_node(reference) == VALUE
    assert assets.reads == 1


@pytest.mark.parametrize('retained', [False, True])
def test_existing_collision_and_fresh_reader_corruption_are_rejected(tmp_path, retained):
    assets = native.ViewerAssets(tmp_path / 'publication')
    with RendererState(assets.root, {'fixture': 'collision'}) as state:
        if retained:
            assets.state = state
        reference = assets.put_node(VALUE)
        # Existing correct destinations remain independently admitted.
        assert assets.put_node(VALUE) == reference
        path = assets.root / reference['path']
        path.write_bytes(b'X' * reference['bytes'])
        with pytest.raises(ValueError, match='Conflicting immutable'):
            assets.put_node(VALUE)
        with pytest.raises(ValueError, match='identity differs'):
            native.ViewerAssets(assets.root).read_node(reference)
        assert path.read_bytes() == b'X' * reference['bytes']


def test_changed_copy_proof_custody_is_rejected_before_remembering(tmp_path, monkeypatch):
    assets = native.ViewerAssets(tmp_path / 'publication')
    with RendererState(assets.root, {'fixture': 'custody'}) as state:
        assets.state = state
        publish = state.publish_asset
        def changed(source, destination, **options):
            proof = publish(source, destination, **options)
            stat = destination.stat()
            destination.write_bytes(b'X' * proof['bytes'])
            os.utime(destination, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            return proof
        monkeypatch.setattr(state, 'publish_asset', changed)
        # Either metadata custody or the current-byte recheck can reject this
        # rewrite; Linux may retain both timestamps within one filesystem tick.
        with pytest.raises(ValueError, match=r'custody(?: or bytes)? changed'):
            assets.put_node(VALUE)
        assert not assets.identities
        assert state.db.execute('SELECT count(*) FROM assets').fetchone() == (0,)


def test_copy_failure_never_remembers_a_node(tmp_path, monkeypatch):
    assets = native.ViewerAssets(tmp_path / 'publication')
    with RendererState(assets.root, {'fixture': 'failed copy'}) as state:
        assets.state = state
        def failed(*args, **kwargs):
            raise OSError('copy failed')
        monkeypatch.setattr(state, 'publish_asset', failed)
        with pytest.raises(OSError, match='copy failed'):
            assets.put_node(VALUE)
        assert not assets.identities and assets.writes == 0
        assert state.db.execute('SELECT count(*) FROM assets').fetchone() == (0,)


def test_verified_byte_cache_stays_bounded_and_reloads_evicted_nodes(tmp_path):
    producer = native.ViewerAssets(tmp_path / 'producer')
    references = [producer.put_node(dict(VALUE, number=number)) for number in range(17)]
    assets = native.ViewerAssets(tmp_path / 'consumer',
        read_asset=lambda key: (producer.root / key).read_bytes())
    for number, reference in enumerate(references):
        assert assets.read_node(reference)['number'] == number
    assert assets.reads == 17 and len(assets._nodes) == 16
    assert assets.read_node(references[1])['number'] == 1 and assets.reads == 17
    assert assets.read_node(references[0])['number'] == 0 and assets.reads == 18
    assert len(assets._nodes) == 16
