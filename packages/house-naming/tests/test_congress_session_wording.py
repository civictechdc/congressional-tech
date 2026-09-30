"""Printed Congress and session wording does not establish event identity."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def observe(engine, name, rule):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result, [m for m in result['observations'] if m['rule'] == rule]


@pytest.mark.parametrize('name,number,ordinal,marker', [
    ('116th Congress Nominations Hearings - First Session - Part I.pdf', '116', 'th', 'Congress'),
    ('116th-congress-sfrc-rules-020719', '116', 'th', 'congress'),
    ('Results of Executive Session to Organize for the 116TH Congress.pdf', '116', 'TH', 'Congress'),
    ('Proposed Committee Rules (119th Congress) - redline1.docx', '119', 'th', 'Congress'),
    ('open_executive_session_to_organize_for_the_119th_congress.pdf', '119', 'th', 'congress'),
    ('Testimony before the 101stCongress.pdf', '101', 'st', 'Congress'),
    ('2nd-Congress.pdf', '2', 'nd', 'Congress'),
    ('3rd_Congress.pdf', '3', 'rd', 'Congress'),
    ('119th Congresspdf.pdf', '119', 'th', 'Congress'),
    ('119th Congress&download=1', '119', 'th', 'Congress'),
])
def test_explicit_congress_reference_retains_all_components(engine, name, number, ordinal, marker):
    _, matches = observe(engine, name, 'congress-wording')
    match, = matches
    assert {f['name']: f['raw'] for f in match['fields']} == {
        'referenced_congress': number, 'congress_ordinal': ordinal, 'congress_marker': marker,
    }
    assert all(f['code'] is None and f['context'] is None and not f['candidates'] for f in match['fields'])
    assert all('reference' in f['note'] for f in match['fields'])


def test_repeated_references_do_not_overwrite_the_primary_congress(engine):
    result, matches = observe(engine, 'BILLS-119pih-116th-Congress-vs-118th-Congress.pdf', 'congress-wording')
    assert [f['raw'] for m in matches for f in m['fields'] if f['name'] == 'referenced_congress'] == ['116', '118']
    assert [f['raw'] for m in result['observations'] for f in m['fields'] if f['name'] == 'congress'] == ['119']


@pytest.mark.parametrize('raw,warning', [
    ('111st', 'Ordinal'), ('112nd', 'Ordinal'), ('113rd', 'Ordinal'),
    ('001st', 'Leading zeros'), ('0th', 'positive'),
])
def test_malformed_numbering_is_retained_without_repair(engine, raw, warning):
    _, matches = observe(engine, raw + ' Congress.pdf', 'congress-wording')
    match, = matches
    assert ''.join(f['raw'] for f in match['fields'][:2]) == raw
    assert any(warning in f['note'] for f in match['fields'])
    assert all(not f['candidates'] for f in match['fields'])


@pytest.mark.parametrize('name,wording,access', [
    ('11-15-18 -- Open Executive Session.pdf', 'Executive Session', 'Open'),
    ('07222025-crapo-executive-session-statement', 'executive-session', None),
    ('Results of Executive Session to Organize for the 118th Congress.pdf', 'Executive Session', None),
    ('results_of_the_open_executive_session_of_september_24_2026.pdf', 'executive_session', 'open'),
    ('open-executive-session&download=1', 'executive-session', 'open'),
    ('Closed Executive Session.pdf', 'Executive Session', 'Closed'),
    ('OPEN_EXECUTIVE_SESSIONS.pdf', 'EXECUTIVE_SESSIONS', 'OPEN'),
    ('Executive Sessionpdf.pdf', 'Executive Session', None),
])
def test_session_and_access_wording_do_not_verify_an_event(engine, name, wording, access):
    result, matches = observe(engine, name, 'executive-session-wording')
    match, = matches
    fields = {f['name']: f for f in match['fields']}
    assert fields['meeting_wording']['raw'] == wording
    assert fields['meeting_wording']['label'] == 'Executive session'
    if access:
        assert fields['access_wording']['raw'] == access
        assert fields['access_wording']['label'] == access.title()
    else:
        assert 'access_wording' not in fields
    assert all(f['code'] is None and f['context'] is None for f in fields.values())
    assert all('verified' in f['note'] for f in fields.values())
    assert not any(f['name'] in {'meeting_id', 'status', 'is_open'} for m in result['observations'] for f in m['fields'])


def test_two_session_mentions_keep_their_own_access_wording(engine):
    _, matches = observe(engine, 'Open Executive Session and Closed Executive Session.pdf', 'executive-session-wording')
    assert [f['raw'] for m in matches for f in m['fields'] if f['name'] == 'access_wording'] == ['Open', 'Closed']


@pytest.mark.parametrize('name', [
    'X119thCongress.pdf', '1119thCongress.pdf', '119thCongressional.pdf',
    '%119thCongress.pdf', '119th-CongressPDFreader.pdf',
    'HHRG-119-IF00-Wstate-119thCongress-20250318.pdf',
    'HHRG-119-IF00-Wstate-Open_Executive_Session-20250318.pdf',
    'Executive Director.pdf', 'PreExecutive Session.pdf', 'Executive Sessionnaire.pdf',
    'OpenExecutiveSession.pdf', 'Executive%20Session.pdf',
    'Data.pdf?title=119th-Congress-Open-Executive-Session',
])
def test_fragments_queries_and_structured_witness_ids_are_protected(engine, name):
    for rule in ('congress-wording', 'executive-session-wording'):
        assert not observe(engine, name, rule)[1]
