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


def test_the_parser_alone_maps_select_codes():
    """ct-p3ff: the model SQL keeps no hs-to-hl copy that could drift from _HOUSE_SELECT_CODES."""
    texts = {path.name: path.read_text() for path in (ROOT / 'model/sql').rglob('*.sql')}
    assert [name for name, text in texts.items() if re.search(r"'hl'\s*\|\|", text) or SELECT_RULE.search(text)] == []


def test_a_house_select_committee_meeting_reaches_a_registry_code_without_sql_help():
    """With the SQL copy gone, the parser's output must already be a released committee key."""
    xml = b"""<committee-meeting meeting-id="HHRG118900" meeting-type="HHRG"><current-status>S</current-status>
      <meeting-details><meeting-title>Select committee hearing on the economy and jobs</meeting-title>
      <meeting-date><calendar-date>2024-05-10</calendar-date></meeting-date>
      <committees><committee-name id="CN00">Select Committee on the CCP</committee-name></committees></meeting-details></committee-meeting>"""
    row = meeting_records.build_meeting_record_row('ab' * 32, 'house_xml', xml, parser_version='v')
    codes = [c['system_code'] for c in row['meetings'][0]['committees']]
    assert codes == ['hlcn00'] and set(codes) <= {r['system_code'] for r in REGISTRY}
