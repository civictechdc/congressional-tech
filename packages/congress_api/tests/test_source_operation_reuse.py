"""Operation reuse preserves exact inputs and notices source-version changes."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

from congress_api.retention import source_replay as replay, source_update_proof as proof
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.immutable_metadata import encoded


@pytest.mark.parametrize('values', [[], [dict(url=f'https://example.gov/{i}.pdf', native=dict(name=str(i))) for i in (2, 1, 2)]])
def test_seed_snapshot_reuses_serialization_and_survives_nested_owner(tmp_path, monkeypatch, values):
    encodes = []
    original = replay.encoded
    def observed(value):
        encodes.append(value)
        return original(value)
    monkeypatch.setattr(replay, 'encoded', observed)
    inserts = []
    with closing(WorkingCatalog(tmp_path / 'outer.sqlite')) as outer:
        outer.connection.set_trace_callback(inserts.append)
        seeds, digest = replay.retain_source_seeds(outer, iter(values))
        with closing(WorkingCatalog(tmp_path / 'nested.sqlite')) as nested:
            nested.connection.set_trace_callback(inserts.append)
            again, same_digest = replay.retain_source_seeds(nested, seeds)
            assert list(again) == values
            assert same_digest == digest == sha256(encoded(values)).hexdigest()
        assert list(seeds) == list(seeds) == values
        if values:
            detached = next(iter(seeds))
            detached['native']['name'] = 'mutated by consumer'
            assert list(seeds) == values
    assert len(encodes) == len(values)
    assert sum(line.startswith('INSERT INTO requested_seeds') for line in inserts) == len(values)


def test_requirements_reuse_is_operation_local_and_returns_detached_values(monkeypatch):
    reads = Counter()
    calculations = []
    calculate = proof._calculate_source_update_requirements
    def observed_calculation():
        calculations.append(True)
        return calculate()
    monkeypatch.setattr(proof, '_calculate_source_update_requirements', observed_calculation)
    read = Path.read_bytes
    def observed(path):
        reads[path] += 1
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', observed)
    with proof.source_update_operation():
        first = proof.source_update_requirements()
        count = sum(reads.values())
        with proof.source_update_operation():
            assert proof.source_update_requirements() == first
        changed = proof.source_update_requirements()
        changed['format'] = 'consumer mutation'
        assert proof.source_update_requirements() == first
        assert sum(reads.values()) == count
        assert max(reads.values()) == 1
        assert len(calculations) == 1
    with proof.source_update_operation():
        assert proof.source_update_requirements() == first
    assert sum(reads.values()) == 2 * count
    assert len(calculations) == 2


def test_source_mutation_refuses_current_operation_and_refreshes_next(tmp_path, monkeypatch):
    from congress_api.retention import source_inputs
    copy = tmp_path / 'source_inputs.py'
    copy.write_bytes(Path(source_inputs.__file__).read_bytes() + b'\n# version a\n')
    monkeypatch.setattr(source_inputs, '__file__', str(copy))
    with proof.source_update_operation():
        before = proof.source_update_requirements()
        copy.write_bytes(copy.read_bytes().replace(b'# version a', b'# version b'))
        with pytest.raises(ValueError, match='Source update implementation changed during operation'):
            proof.source_update_requirements()
    with proof.source_update_operation():
        after = proof.source_update_requirements()
    assert before['implementation_sha256'] != after['implementation_sha256']


def test_new_parser_file_refuses_reuse(tmp_path, monkeypatch):
    from congress_api import parsers
    copy = tmp_path / 'parsers'
    copy.mkdir()
    (copy / '__init__.py').write_text('')
    monkeypatch.setattr(parsers, '__file__', str(copy / '__init__.py'))
    with proof.source_update_operation():
        before = proof.source_update_requirements()
        (copy / 'added.py').write_text('# new parser implementation')
        with pytest.raises(ValueError, match='Source update implementation changed during operation'):
            proof.source_update_requirements()
    assert proof.source_update_requirements()['source_policy_sha256'] != before['source_policy_sha256']


def test_failed_operation_does_not_leak_requirements(tmp_path, monkeypatch):
    from congress_api.retention import source_inputs
    copy = tmp_path / 'source_inputs.py'
    copy.write_bytes(Path(source_inputs.__file__).read_bytes())
    monkeypatch.setattr(source_inputs, '__file__', str(copy))
    with pytest.raises(OSError, match='worker stopped'):
        with proof.source_update_operation():
            before = proof.source_update_requirements()
            raise OSError('worker stopped')
    copy.write_bytes(copy.read_bytes() + b'\n# subsequent operation\n')
    with proof.source_update_operation():
        assert proof.source_update_requirements() != before


@pytest.mark.parametrize('change', ['rewrite', 'add', 'remove'])
def test_filename_rule_changes_refuse_reuse(tmp_path, monkeypatch, change):
    import house_naming
    root = tmp_path / 'house_naming'
    root.mkdir()
    (root / '__init__.py').write_text('')
    rule = root / 'rules.json'
    rule.write_text('{"version":1}')
    monkeypatch.setattr(house_naming, '__file__', str(root / '__init__.py'))
    with proof.source_update_operation():
        before = proof.source_update_requirements()
        if change == 'rewrite':
            stat = rule.stat()
            rule.write_text('{"version":2}')
            import os
            os.utime(rule, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        elif change == 'add':
            (root / 'extra.json').write_text('{}')
        else:
            rule.unlink()
        with pytest.raises(ValueError, match='Source update implementation changed during operation'):
            proof.source_update_requirements()
    assert proof.source_update_requirements()['filename_rules_sha256'] != before['filename_rules_sha256']


def test_source_change_during_update_refuses_publication_and_old_continuation(tmp_path, monkeypatch):
    from congress_api.retention import source_inputs
    from congress_api.retention.catalog_publication import MANIFEST_KEY
    from congress_api.retention.raw_catalog import update_from_raw
    from congress_api.retention.raw_storage import RawSnapshot
    from congress_api.retention.source_observations import SourceObservationTrace
    from test_catalog_raw_updates import seed, MemoryNative
    from testing_fakes import SelectorStore
    native, store = MemoryNative(), SelectorStore()
    raw = seed(store, native)
    monkeypatch.setattr(RawSnapshot, 'body_readings', lambda self, keys: iter(()), raising=False)
    copy = tmp_path / 'source_inputs.py'
    copy.write_bytes(Path(source_inputs.__file__).read_bytes())
    monkeypatch.setattr(source_inputs, '__file__', str(copy))
    replay_sources = SourceObservationTrace.replay
    def changed(self, *args, **kwargs):
        result = replay_sources(self, *args, **kwargs)
        copy.write_bytes(copy.read_bytes() + b'\n# changed during replay\n')
        return result
    options = dict(raw_storage=raw, directory=tmp_path / 'old', candidate='old')
    with monkeypatch.context() as during:
        during.setattr(SourceObservationTrace, 'replay', changed)
        with pytest.raises(ValueError, match='Source update implementation changed during operation'):
            update_from_raw(store, **options)
    assert store.read(MANIFEST_KEY) is None
    with pytest.raises(ValueError, match='continuation inputs differ'):
        update_from_raw(store, **options)
    assert store.read(MANIFEST_KEY) is None
    update_from_raw(store, raw_storage=raw, directory=tmp_path / 'fresh', candidate='fresh')
    assert store.read(MANIFEST_KEY) is not None
