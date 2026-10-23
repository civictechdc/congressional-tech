"""Operational adoption refuses drift in the exact retained source checkpoints."""
from copy import deepcopy

import pytest

from congress_api.retention import raw_adoption, raw_adoption_inputs
from congress_api.retention.raw_archive import CAPTURES_KEY, STATE_KEY
from congress_api.retention.raw_storage import RAW_KEY, RawStorage
from test_raw_complete_adoption import setup


def source_setup(tmp_path):
    store, owner, options, captures, states = setup(tmp_path)
    store.bucket = 'fixture-raw-source'
    sources = {}
    for name, key in [('captures', CAPTURES_KEY), ('state', STATE_KEY)]:
        store.objects[key] = options['paths'][name].read_bytes()
        sources[name] = dict(bucket=store.bucket, key=key, version=store.version(key))
    options['source_pins'] = sources
    return store, owner, options, captures, states


@pytest.mark.parametrize('name', ['captures', 'state'])
def test_source_drift_refuses_before_any_preparation(tmp_path, monkeypatch, name):
    store, owner, options, _, _ = source_setup(tmp_path)
    store.objects[options['source_pins'][name]['key']] += b'changed'
    before = list(store.writes)
    monkeypatch.setattr(raw_adoption_inputs, 'prepare_reading_input',
        lambda *a, **k: pytest.fail('Reading preparation entered'))
    with pytest.raises(ValueError, match='Raw adoption source changed'):
        raw_adoption.adopt_archive(owner, **options)
    assert store.writes == before and not owner.native.writes
    assert RAW_KEY not in store.objects


@pytest.mark.parametrize('name', ['captures', 'state'])
def test_source_drift_before_selection_refuses_and_completed_candidates_retry(tmp_path, name):
    store, owner, options, captures, states = source_setup(tmp_path)
    key = options['source_pins'][name]['key']
    original = store.objects[key]
    run = owner.native.run_table
    def changed(table, **request):
        pin = run(table, **request)
        store.objects[key] = original + b'changed'
        return pin
    owner.native.run_table = changed
    with pytest.raises(ValueError, match='Raw adoption source changed'):
        raw_adoption.adopt_archive(owner, **options)
    assert RAW_KEY not in store.objects and owner.native.writes
    completed = list(owner.native.writes)
    store.objects[key] = original
    owner.native.run_table = run
    fresh = RawStorage(store, owner.native, state_schema=states.schema,
        max_state_rows=3, max_capture_rows=3)
    selected = raw_adoption.adopt_archive(fresh, **options)
    assert selected.captures().equals(captures, check_metadata=True)
    assert selected.states().equals(states, check_metadata=True)
    assert all(owner.native.writes.count(pin) == 1 for pin in completed)
    assert store.writes.count(RAW_KEY) == 1


def test_completed_retry_binds_source_pins_without_rechecking_later_legacy_changes(tmp_path):
    store, owner, options, _, _ = source_setup(tmp_path)
    selected = raw_adoption.adopt_archive(owner, **options)
    before = list(store.writes), list(owner.native.writes)
    store.version = lambda *a: pytest.fail('Completed adoption rechecked source history')
    assert raw_adoption.adopt_archive(owner, **options).identity == selected.identity
    changed = deepcopy(options)
    changed['source_pins']['state']['version'] = 'different-source-version'
    with pytest.raises(ValueError, match='different inputs'):
        raw_adoption.adopt_archive(owner, **changed)
    assert (store.writes, owner.native.writes) == before


@pytest.mark.parametrize('change', ['missing', 'bucket', 'key', 'version'])
def test_operational_source_authority_refuses_before_preparation(tmp_path, monkeypatch, change):
    store, owner, options, _, _ = source_setup(tmp_path)
    if change == 'missing':
        options.pop('source_pins')
    else:
        options['source_pins']['state'][change] = {'bucket': 'other-bucket',
            'key': 'indexes/unrelated.parquet', 'version': ''}[change]
    monkeypatch.setattr(raw_adoption_inputs, 'prepare_reading_input',
        lambda *a, **k: pytest.fail('Reading preparation entered'))
    before = list(store.writes)
    with pytest.raises(ValueError, match='source pins|source bucket|source key|source version'):
        raw_adoption.adopt_archive(owner, **options)
    assert store.writes == before and not owner.native.writes
