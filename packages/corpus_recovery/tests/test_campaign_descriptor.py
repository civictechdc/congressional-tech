"""The shared campaign descriptor binds its metadata before any consumer acts."""
import hashlib
import json
import pytest

from congress_shared.campaign import load_campaign


def descriptor(tmp_path):
    tables = {}
    for name in ('targets', 'candidates'):
        path = tmp_path / (name + '.parquet')
        path.write_bytes(name.encode())
        tables[name] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path = tmp_path / 'campaign.json'
    path.write_text(json.dumps({'version': 1, 'campaign_id': 'test', 'requirement': 'historical_exact',
        'tables': tables, 'target_table': 'targets', 'candidate_table': 'candidates'}))
    return path


def test_pins_and_rerun(tmp_path):
    path = descriptor(tmp_path)
    first, second = load_campaign(path), load_campaign(path)
    assert first.descriptor_sha256 == second.descriptor_sha256
    assert first.table_path('targets').read_bytes() == b'targets'
    first.require_custody()


def test_fixed_size_change_refuses_before_use(tmp_path):
    path = descriptor(tmp_path)
    campaign = load_campaign(path)
    (tmp_path / 'targets.parquet').write_bytes(b'TARGETS')
    with pytest.raises(ValueError):
        campaign.require_custody()
    with pytest.raises(ValueError, match='SHA-256'):
        load_campaign(path)


def test_invalid_requirement_refused(tmp_path):
    path = descriptor(tmp_path)
    value = json.loads(path.read_text())
    value['requirement'] = 'anything'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='requirement'):
        load_campaign(path)


def test_rejects_ambiguous_json_and_table_replacement(tmp_path):
    path = descriptor(tmp_path)
    campaign = load_campaign(path)
    with pytest.raises(TypeError):
        campaign.tables['targets'] = campaign.tables['candidates']
    raw = path.read_text().replace('"version": 1', '"version": 1, "version": 1')
    path.write_text(raw)
    with pytest.raises(ValueError, match='Duplicate'):
        load_campaign(path)
