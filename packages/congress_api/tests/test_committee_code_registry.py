"""House committee normalization agrees with the committed registry.

This cannot see corpus codes outside the registry, and it does not compare with the
release, where stems outside _HOUSE_SELECT_CODES are expected. missing_committee_keys
remains the real gate.
"""
import json
from pathlib import Path
import re

from congress_api.lake import meeting_records
from congress_api.lake.meeting_records import normalize_house_committee_code

ROOT = Path(__file__).parents[3]
REGISTRY = json.loads((ROOT / 'model/registries/committee-codes.json').read_text())
SELECT_RULE = re.compile(r"\^hs\(\?:([a-z|]+)\)\[0-9\]\{2\}\$")


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


def sql_select_stems(texts):
    """Every hs-to-hl alternation, wherever the model SQL keeps it."""
    return [set(match.split('|')) for text in texts for match in SELECT_RULE.findall(text)]


def test_model_sql_select_stems_match_the_parser():
    rules = sql_select_stems(path.read_text() for path in (ROOT / 'model/sql').rglob('*.sql'))
    assert rules, 'no hs-to-hl rule found, so this gate would pass vacuously'
    assert all(rule == meeting_records._HOUSE_SELECT_CODES for rule in rules)


def test_dropping_a_stem_from_the_sql_rule_is_detected():
    text = (ROOT / 'model/sql/meeting-records-resolved.sql').read_text()
    mutated = text.replace('(?:cn|', '(?:', 1)
    assert mutated != text
    assert any(rule != meeting_records._HOUSE_SELECT_CODES for rule in sql_select_stems([mutated]))
