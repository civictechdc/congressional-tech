"""Validation failures remain visible without changing priority selection."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,code', [
    ('HHRG-112-ED-WState-IveyB-20110231.pdf', 'invalid-calendar-date'),
    ('HMTG-119-AG00-Weekof20260317.pdf', 'not-monday'),
])
def test_structural_match_reports_why_validation_failed(engine, name, code):
    result = engine.parse(name)
    assert not result['valid']
    assert code in result['issues']
    rejected = [r for r in result['rejected_candidates'] if r['code'] == code]
    assert rejected and all(r['kind'] and r['message'] for r in rejected)
    assert all(r['priority'] == 0 for r in rejected)
    assert engine.extract(name)['rejected_candidates'] == result['rejected_candidates']


def test_no_layout_match_has_no_validation_failure(engine):
    result = engine.parse('NoConventionHere.pdf')
    assert result['issues'] == ['no-matching-convention']
    assert result['rejected_candidates'] == []


def test_later_valid_priority_survives_failed_specific_candidate(engine):
    result = engine.parse('BILLS-119hr2147483648ih.pdf')
    assert result['valid']
    assert [m['kind'] for m in result['matches']] == ['bill-numbered-described']
    assert any(r['kind'] == 'bill-numbered' and r['code'] == 'invalid-record'
               and r['priority'] == 0 for r in result['rejected_candidates'])
    assert result['matches'][0]['record']['numberedSubject'] == 'hr2147483648'


def test_first_valid_priority_still_wins(engine):
    result = engine.parse('BILLS-119hr1ih.pdf')
    assert result['valid']
    assert [m['kind'] for m in result['matches']] == ['bill-numbered']
    assert not result['rejected_candidates']
