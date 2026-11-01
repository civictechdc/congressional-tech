"""House committee normalization agrees with the committed registry.

This cannot see corpus codes outside the registry, and it does not compare with the
release, where stems outside _HOUSE_SELECT_CODES are expected. missing_committee_keys
remains the real gate.
"""
import json
from pathlib import Path

from congress_api.lake import meeting_records
from congress_api.lake.meeting_records import normalize_house_committee_code

REGISTRY = json.loads((Path(__file__).parents[3] / 'model/registries/committee-codes.json').read_text())


def disagreements():
    return [row['code'] for row in REGISTRY if normalize_house_committee_code(row['code']) != row['system_code']]


def test_every_registry_code_normalizes_to_its_system_code():
    assert len(REGISTRY) == 1017
    assert disagreements() == []


def test_hs_prefixed_select_and_task_force_codes_map_back():
    codes = sorted({row['system_code'] for row in REGISTRY if row['system_code'][:2] in ('hl', 'ht')})
    assert codes
    assert [code for code in codes if normalize_house_committee_code('hs' + code[2:]) != code] == []


def test_removing_a_select_stem_is_detected(monkeypatch):
    monkeypatch.setattr(meeting_records, '_HOUSE_SELECT_CODES', meeting_records._HOUSE_SELECT_CODES - {'cn'})
    assert disagreements()
