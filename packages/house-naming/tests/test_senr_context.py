"""SENR committee context is local to the printed filename family."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def contexts(result):
    return [m for m in result['observations'] if m['rule'] == 'senr-context']


def raw(match):
    return {f['name']: f['raw'] for f in match['fields']}


@pytest.mark.parametrize('tail,expected', [
    ('SENR Cmte Hrg', {'committee_marker': 'Cmte', 'meeting_wording': 'Hrg'}),
    ('SENR Hrg', {'meeting_wording': 'Hrg'}),
    ('SENR Cmte NP Subcmte Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'NP', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte PLFM Subcmte Hearing', {'committee_marker': 'Cmte', 'subcommittee_token': 'PLFM', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hearing'}),
    ('SENR Cmte W&P Subcmte Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'W&P', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte WP Subcmte Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'WP', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte ENR Subcmte Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'ENR', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hrg'}),
    ('SENR Energy Subcmte Hrg', {'subcommittee_token': 'Energy', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Hrg'}),
    ('SENR PLFM Hrg', {'subcommittee_token': 'PLFM', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte Noms Hrg', {'committee_marker': 'Cmte', 'nomination_wording': 'Noms', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte Nomination Hrg', {'committee_marker': 'Cmte', 'nomination_wording': 'Nomination', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte Bus Mtg', {'committee_marker': 'Cmte', 'meeting_wording': 'Bus Mtg'}),
    ('SENR Cmte Business Meeting', {'committee_marker': 'Cmte', 'meeting_wording': 'Business Meeting'}),
    ('SENR Cmte Roundtable', {'committee_marker': 'Cmte', 'meeting_wording': 'Roundtable'}),
    ('SENR Cmte PLFM Subcmte Roundtable', {'committee_marker': 'Cmte', 'subcommittee_token': 'PLFM', 'subcommittee_marker': 'Subcmte', 'meeting_wording': 'Roundtable'}),
    ('SENR Cmte WV Field Hrg', {'committee_marker': 'Cmte', 'field_location_token': 'WV', 'field_marker': 'Field', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte NP Subcmte MT Field Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'NP', 'subcommittee_marker': 'Subcmte', 'field_location_token': 'MT', 'field_marker': 'Field', 'meeting_wording': 'Hrg'}),
    ('SENR Cmtr Hrg', {'committee_marker': 'Cmtr', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte NP Submte Hrg', {'committee_marker': 'Cmte', 'subcommittee_token': 'NP', 'subcommittee_marker': 'Submte', 'meeting_wording': 'Hrg'}),
    ('SENR Cmte Hr', {'committee_marker': 'Cmte', 'meeting_wording': 'Hr'}),
    ('senr-cmte-np-subcmte-hrg', {'committee_marker': 'cmte', 'subcommittee_token': 'np', 'subcommittee_marker': 'subcmte', 'meeting_wording': 'hrg'}),
])
def test_context_slots_preserve_exact_source_wording(engine, tail, expected):
    result = checked(engine, f'Smith Testimony 4-10-24 {tail}.pdf')
    match, = contexts(result)
    assert raw(match) == {'committee_token': tail.split('-')[0].split()[0], **expected}
    assert all(f['code'] is None and f['context'] is None for f in match['fields'])


@pytest.mark.parametrize('token,label', [
    ('NP', 'National Parks'), ('PLFM', 'Public Lands, Forests, and Mining'),
    ('W&P', 'Water and Power'), ('WP', 'Water and Power'),
    ('ENR', 'Energy'), ('Energy', 'Energy'),
])
def test_subcommittee_meanings_require_senr_context(engine, token, label):
    match, = contexts(checked(engine, f'SENR Cmte {token} Subcmte Hrg.pdf'))
    fields = {f['name']: f for f in match['fields']}
    assert fields['committee_token']['label'] == 'Senate Committee on Energy and Natural Resources'
    assert fields['subcommittee_token']['label'] == label
    assert fields['meeting_wording']['label'] == 'Hearing'
    assert not contexts(checked(engine, f'{token} Subcmte Hrg.pdf'))


def test_source_labels_do_not_block_more_specific_context(engine):
    result = checked(engine, 'Agenda 7-16-19 SENR Cmte Business Meeting.pdf')
    match, = contexts(result)
    assert raw(match)['meeting_wording'] == 'Business Meeting'
    assert any(f['name'] == 'label' and f['raw'] == 'Business Meeting'
               for m in result['observations'] for f in m['fields'])
    result = checked(engine, 'Stone-Manning Responses to QFRs 6-8-21 SENR Cmte Nominations Hrg.pdf')
    assert raw(contexts(result)[0])['nomination_wording'] == 'Nominations'


def test_multiple_contexts_and_source_tail_remain(engine):
    name = '119th Congress SENR Cmte Subcommittee Assignments 2-11-25 SENR Cmte Bus Mtg.pdf'
    matches = contexts(checked(engine, name))
    assert len(matches) == 2
    assert raw(matches[0]) == {'committee_token': 'SENR', 'committee_marker': 'Cmte'}
    assert raw(matches[1])['meeting_wording'] == 'Bus Mtg'
    name = 'DOI-Statement-for-the-Record-9.16.26-SENR-Cmte-Hrg_Part-2_2b5e4d04-ae6a-4167-977a-1e5fd0cb086d.pdf'
    result = checked(engine, name)
    assert raw(contexts(result)[0])['meeting_wording'] == 'Hrg'
    assert any(f['name'] == 'opaque_uuid' for m in result['observations'] for f in m['fields'])
    assert any(f['name'] == 'part_number' and f['raw'] == '2' for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    '41322 Final Danly SENR QFRs.pdf',
    'Sec. Burgum Testimony on 2026 Budget (SENR) 6.11.25[1].pdf',
    '2.2.23 SENR Deputy Secretary David Turk Testimony.pdf',
    'SENR NP Smith.pdf', 'SENR Cmte XYZ Subcmte Hrg.pdf',
])
def test_no_missing_meeting_or_unknown_subcommittee_is_invented(engine, name):
    result = checked(engine, name)
    match, = contexts(result)
    assert 'committee_token' in raw(match)
    assert not any(k in raw(match) for k in ('subcommittee_token', 'meeting_wording'))


def test_house_bill_reference_is_not_a_short_hearing_word(engine):
    result = checked(engine, 'SENR Cmte HR 42.pdf')
    assert raw(contexts(result)[0]) == {'committee_token': 'SENR', 'committee_marker': 'Cmte'}
    assert any(f['name'] == 'measure_number' and f['raw'] == '42'
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'PreSENR Cmte Hrg.pdf', 'SENRsmith.pdf', '20SENR Cmte Hrg.pdf',
    'Smith%20SENR%20Cmte%20Hrg.pdf',
    'HHRG-119-IF00-Wstate-SENR-Cmte-Hrg-20250318.pdf',
])
def test_embedded_encoded_and_assigned_id_text_is_not_reclassified(engine, name):
    assert not contexts(checked(engine, name))
