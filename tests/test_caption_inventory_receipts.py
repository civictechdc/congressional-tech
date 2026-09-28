"""Capture receipts survive inventory import and dated assessment normalization."""
from datetime import datetime, timezone
import json

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters import inventory
from congress_api.inventory.captions import import_observations
from congress_api.senate import captions as senate
from youtube_api.captions import main as youtube
from test_caption_source_fidelity import VIDEO, VTT, fake_ydl
from test_senate_caption_checks import PLAYER, responses, response


def adapt(state):
    context = AdapterContext(now=datetime.now(timezone.utc), provider='inventory', input_id='retained',
                             ids=lambda kind, key: kind + ':' + key)
    return list(inventory.records(state, context, meetings={}, materials={
        ('youtube', VIDEO): Ref(kind='material', id='youtube'),
        ('senate', 'epw120623'): Ref(kind='material', id='senate')}))


def test_youtube_capture_receipt_is_copied_exactly_to_inventory_and_assessment(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}}, tracks={'en': VTT})
    youtube.main(tmp_path, [VIDEO], nthreads=1)
    receipt = json.loads((tmp_path / youtube.RECEIPTS / f'{VIDEO}.json').read_text())
    # Inventory uses only the receipt; timed caption contents are not loaded.
    (tmp_path / 'tracks' / receipt['selected_track']).write_bytes(b'not loaded by inventory')
    state = {}
    import_observations(state, youtube_index=tmp_path / youtube.INDEX)
    assert state['youtube'][VIDEO] == 'manual'
    assert state['caption_observations']['youtube'][VIDEO] == receipt
    records = adapt(state)
    source = next(r for r in records if r.kind == 'source_record')
    assessment = next(r for r in records if r.kind == 'assessment')
    assert source.payload['receipt'] == receipt
    assert assessment.status == 'available'
    assert assessment.observed_at.isoformat() == receipt['observed_at']
    assert json.loads(assessment.scope) == receipt['scope']
    assert source.retrieved_at is None
    assert not any(r.kind in ('material', 'representation') for r in records)


def test_failed_youtube_refresh_retains_prior_positive_without_recursion(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}}, tracks={'en': VTT})
    youtube.main(tmp_path, [VIDEO], nthreads=1)
    path = tmp_path / youtube.RECEIPTS / f'{VIDEO}.json'
    original = json.loads(path.read_text())
    fake_ydl(monkeypatch, error='HTTP Error 403: Forbidden')
    youtube.fetch_one(VIDEO, tmp_path)
    youtube.fetch_one(VIDEO, tmp_path)
    receipt = json.loads(path.read_text())
    assert receipt['kind'] == 'error' and receipt['last_successful'] == original
    assert 'last_successful' not in receipt['last_successful']
    assert (tmp_path / 'tracks' / original['selected_track']).read_text() == VTT
    state = {}
    import_observations(state, youtube_index=tmp_path / youtube.INDEX)
    assert state['youtube'][VIDEO] == 'manual'
    records = adapt(state)
    by_status = {r.status: r for r in records if r.kind == 'assessment'}
    assert set(by_status) == {'error', 'available'}
    assert by_status['available'].observed_at.isoformat() == original['observed_at']
    assert by_status['error'].observed_at.isoformat() == receipt['observed_at']
    assert by_status['available'].observed_at < by_status['error'].observed_at
    assert by_status['available'].provenance.citations[0].selector == '/receipt/last_successful'
    assert next(r for r in records if r.kind == 'source_record').payload['receipt'] == receipt


def test_senate_positive_then_error_retains_source_pointer_and_bounded_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(senate.sess, 'get', responses())
    senate.main(tmp_path, [PLAYER], nthreads=1)
    original = json.loads(senate.receipt_path(tmp_path, PLAYER).read_text())
    import requests
    monkeypatch.setattr(senate.sess, 'get', lambda *a, **k: (_ for _ in ()).throw(requests.Timeout('timeout')))
    import pytest
    for _ in range(2):
        with pytest.raises(requests.Timeout):
            senate.fetch_one(PLAYER, tmp_path)
    receipt = json.loads(senate.receipt_path(tmp_path, PLAYER).read_text())
    assert receipt['last_successful'] == original
    assert receipt['last_successful']['source_file'] == 'epw120623.captions.json.gz'
    assert 'last_successful' not in receipt['last_successful']
    state = {}
    import_observations(state, senate_index=tmp_path / senate.INDEX)
    assert state['caption_observations']['senate']['epw120623'] == receipt
    assessments = {r.status: r for r in adapt(state) if r.kind == 'assessment'}
    assert set(assessments) == {'available', 'error'}
    assert not json.loads(assessments['available'].scope)['includes_embedded_archive_captions']
    assert assessments['available'].observed_at.isoformat() == original['observed_at'].replace('Z', '+00:00')


def test_confirmed_negatives_are_dated_scoped_but_legacy_csv_is_undated(tmp_path, monkeypatch):
    youtube_dir, senate_dir = tmp_path / 'youtube', tmp_path / 'senate'
    fake_ydl(monkeypatch, info={})
    youtube.main(youtube_dir, [VIDEO], nthreads=1)
    monkeypatch.setattr(senate.sess, 'get', lambda *a, **k: response(404))
    senate.main(senate_dir, [PLAYER], nthreads=1)
    state = {}
    import_observations(state, youtube_index=youtube_dir / youtube.INDEX, senate_index=senate_dir / senate.INDEX)
    assessments = [r for r in adapt(state) if r.kind == 'assessment']
    assert len(assessments) == 2 and all(a.status == 'not_found' and a.observed_at and a.scope for a in assessments)
    for path in (youtube_dir / youtube.RECEIPTS, senate_dir / senate.RECEIPTS):
        for receipt in path.glob('*.json'): receipt.unlink()
    legacy = {}
    import_observations(legacy, youtube_index=youtube_dir / youtube.INDEX, senate_index=senate_dir / senate.INDEX)
    assert 'caption_observations' not in legacy
    assert all(a.status == 'unknown' and a.observed_at is None for a in adapt(legacy) if a.kind == 'assessment')


def test_failed_only_receipt_is_imported_even_without_an_index_row(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, error='Unavailable')
    youtube.fetch_one(VIDEO, tmp_path)
    state = {}
    import_observations(state, youtube_index=tmp_path / youtube.INDEX)
    assert state.get('youtube', {}) == {}
    assessment = next(r for r in adapt(state) if r.kind == 'assessment')
    assert assessment.status == 'error' and assessment.observed_at


def test_invalid_recaptured_track_preserves_prior_timing_and_receipt(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}}, tracks={'en': VTT})
    youtube.fetch_one(VIDEO, tmp_path)
    original = json.loads((tmp_path / youtube.RECEIPTS / f'{VIDEO}.json').read_text())
    fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}}, tracks={'en': '<html>bad response</html>'})
    assert youtube.fetch_one(VIDEO, tmp_path)[1] == 'error'
    receipt = json.loads((tmp_path / youtube.RECEIPTS / f'{VIDEO}.json').read_text())
    assert receipt['last_successful'] == original
    assert receipt['track_files'] == []
    assert (tmp_path / 'tracks' / original['selected_track']).read_text() == VTT
