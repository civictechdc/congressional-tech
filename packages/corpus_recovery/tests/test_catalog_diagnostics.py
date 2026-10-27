"""Catalog diagnostics never consume, repair or accept retained build contents."""
from pathlib import Path
import pytest
from corpus_recovery.diagnostics import catalog_build_observation


@pytest.mark.parametrize(('phases', 'last', 'state'), [
    ({}, None, 'incomplete_catalog_requires_reconciliation'),
    ({'catalog': {}}, 'catalog', 'catalog_acceptance_recorded'),
    ({'catalog': {}, 'mappings': {}}, 'mappings', 'catalog_acceptance_recorded'),
])
@pytest.mark.parametrize('folder', ['build', 'catalog-update'])
def test_observation_does_not_read_or_write_build(tmp_path, monkeypatch, phases, last, state, folder):
    (tmp_path / folder).mkdir()
    for name in ('working.sqlite', 'working.sqlite-wal', 'working.sqlite-shm'):
        (tmp_path / folder / name).write_bytes(b'retained diagnostic bytes')
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('Diagnostic opened a file'))
    monkeypatch.setattr(Path, 'rglob', lambda *a, **k: pytest.fail('Diagnostic scanned build'))
    value = catalog_build_observation(tmp_path, phases)
    assert value['state'] == state and value['last_recorded_accepted_phase'] == last
    assert value['retained_build_path'] == str(tmp_path / folder)
    if folder == 'catalog-update':
        assert 'native selector' in value['next_read_only_checks'][2]['check']
    assert not value['publication_complete'] and not value['resume_authorized']
    assert all(Path(item['path']).is_absolute() for item in value['next_read_only_checks'])
    assert Path(value['next_read_only_checks'][0]['path']).name == 'events.jsonl'
    assert 'without an accepted acknowledgment' in value['next_read_only_checks'][-1]['check']


def test_absent_build_does_not_invent_retained_evidence(tmp_path):
    assert catalog_build_observation(tmp_path, {}) is None
