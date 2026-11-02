"""The raw judge explains a change only from raw facts, and names what it cannot explain."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('raw_judge', ROOT / 'scripts/measure/capture_causes/raw_judge.py')
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)
LINES = {(d['key'], d['line']): d['row'] for d in map(json.loads,
         (ROOT / 'packages/congress_api/tests/fixtures/document_rule_receipt_lines.jsonl').read_text().splitlines())}
PLAYERS = 'receipts/senate/players/2026-09-29/assemble-20260930.jsonl.gz'


def row(index=0, **changes):
    value = dict(capture_index=index, old_outcome='stored', new_outcome='stored', old_http_status=None, new_http_status=None,
                 old_complete=True, new_complete=True, old_attempt=0, new_attempt=0, old_fetch_http_status=None,
                 new_fetch_http_status=None, old_fetch_outcome='stored', new_fetch_outcome='stored',
                 old_good_fetch=False, new_good_fetch=False, new_url='https://x.test/a', requested_url='https://x.test/a')
    value.update(changes)
    return value


def causes(line, **changes):
    found, _, _, _, unexplained, _ = judge.judge(row(**changes), LINES[line])
    return found, unexplained


def test_each_cause_comes_from_the_raw_line():
    # record status 404 with a 248-byte body; then 404 with an empty body; then a stated 200.
    assert causes((PLAYERS, 3661), new_outcome='failed', new_http_status=404)[0] == dict(
        outcome='non_document_status', http_status='stated_status_read')
    assert causes((PLAYERS, 3664), new_outcome='failed', new_http_status=404)[0]['outcome'] == 'empty_body'
    assert causes((PLAYERS, 3660), new_http_status=200, new_good_fetch=True)[0] == dict(
        http_status='stated_status_read', good_fetch='stated_2xx_read')
    # The three bounded 206 samples are partial ranges.
    partial = causes(('receipts/senate/players/undated/assemble-20260930.jsonl.gz', 12), new_outcome='failed', new_http_status=206)
    assert partial[0]['outcome'] == 'partial_206'


def test_a_change_the_raw_line_does_not_support_is_a_defect():
    # 3660 states 200 with a 142-byte body: failing it, or reading 404, has no raw cause.
    found, unexplained = causes((PLAYERS, 3660), new_outcome='failed', new_http_status=404)
    assert found == {} and unexplained == ['outcome', 'http_status']
