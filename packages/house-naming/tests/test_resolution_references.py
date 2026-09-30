"""Resolution wording and references retain source text without inferring events."""
import pytest
from house_naming import Engine

RULES = {'committee-resolution-wording', 'gsa-numbered-reference'}

@pytest.fixture(scope='module')
def engine():
    return Engine()

def checked(engine, name):
    r = engine.extract(name)
    assert all(r[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in r['pieces']) == name
    selected = [m for m in r['observations'] if m['rule'] in RULES]
    for m in selected:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert name[f['start']:f['end']] == f['raw']
            assert f['code'] is None and f['label'] is None and f['context'] is None
            assert f['candidates'] == []
    return r, selected

@pytest.mark.parametrize('name,marker,year,number', [
    ('BILLS-116pih-GSA2018-50.pdf', 'GSA', '2018', '50'),
    ('BILLS-116pih-GSA-2019-44.pdf', 'GSA', '2019', '44'),
    ('BILLS-116GSA2020-37ih.pdf', 'GSA', '2020', '37'),
    ('gsa 2020 0037.pdf', 'gsa', '2020', '0037'),
    ('GSA_2020_37.pdf', 'GSA', '2020', '37'),
    ('GSA2020-37pdf.pdf', 'GSA', '2020', '37'),
    ('GSA2020-37&download=1', 'GSA', '2020', '37'),
    ('GSA2020-20190101.pdf', 'GSA', '2020', '20190101'),
    ('GSA2020-111111.pdf', 'GSA', '2020', '111111'),
    ('BILLS-116GSA2020-20190101ih.pdf', 'GSA', '2020', '20190101'),
    ('GSA2020-37-U2.pdf', 'GSA', '2020', '37'),
])
def test_numbered_references_preserve_components(engine, name, marker, year, number):
    r, matches = checked(engine, name)
    m, = matches
    assert m['rule'] == 'gsa-numbered-reference'
    assert {f['name']: f['raw'] for f in m['fields']} == {
        'reference_marker': marker, 'reference_year_token': year, 'reference_number': number,
    }
    assert all('not an event date' in f['note'] for f in m['fields'])
    assert not any(f['name'] in {'date_token','short_date_token'} and f['start'] < m['end'] and m['start'] < f['end']
                   for obs in r['observations'] for f in obs['fields'])
    if name.startswith('BILLS-'):
        assert any(f['name'] == 'congress' and f['raw'] == '116' for obs in r['observations'] for f in obs['fields'])
        assert any(f['name'] == 'version_token' and f['code'] for obs in r['observations'] for f in obs['fields'])

@pytest.mark.parametrize('name,label', [
    ('GSA-committee-resolution---fbi-omaha-ne.pdf', 'GSA-committee-resolution'),
    ('committee-resolution-lease-department.pdf', 'committee-resolution'),
    ('GSA Resolutions.pdf', 'GSA Resolutions'),
    ('BILLS-117pih-18GSAResolutions-U4.pdf', 'GSAResolutions'),
    ('BILLS-118GSAResolutionsih.pdf', 'GSAResolutions'),
    ('BILLS-113pih-Committeeresolution.docx', 'Committeeresolution'),
    ('BILLS-114pih-CommitteeResolution2.pdf', 'CommitteeResolution'),
    ('21-gsa-committee-resolutions-approved.pdf', 'gsa-committee-resolutions'),
    ('CommitteeResolutionpdf.pdf', 'CommitteeResolution'),
    ('GSA_Committee_Resolutions&download=1', 'GSA_Committee_Resolutions'),
])
def test_resolution_phrases_keep_literal_wording(engine, name, label):
    _, matches = checked(engine, name)
    m, = matches
    assert m['rule'] == 'committee-resolution-wording'
    assert {f['name']: f['raw'] for f in m['fields']} == {'label': label}

@pytest.mark.parametrize('name', [
    'BiggsA-20190101.pdf', 'SkillingsA-20200806.pdf',
    'GSA12-12-2018.pdf', 'GSA2020-12-10.pdf', 'GSA2020_12_10.pdf',
    'GSA20-37.pdf', 'GSA20201-37.pdf', 'GSA2020-.pdf',
    'GSA2020-37th.pdf', 'GSA2020-37A.pdf', 'SomeGSA2020-37.pdf',
    'Topic%20GSA2020-37.pdf', 'GSA%202020-37.pdf',
    'CommitteeResolutionary.pdf', 'SubcommitteeResolution.pdf',
    'GSAResolutionsTheory.pdf', 'UncommitteeResolution.pdf',
    'Topic%20CommitteeResolution.pdf',
    'HHRG-119-IF00-Wstate-GSA2020-37-20250318.pdf',
    'HHRG-119-IF00-Wstate-CommitteeResolution-20250318.pdf',
])
def test_boundaries_and_protected_person_slots(engine, name):
    _, matches = checked(engine, name)
    assert matches == []


def test_actual_date_is_still_a_date(engine):
    r, matches = checked(engine, 'BILLS-115pih-GSA12-12-2018.pdf')
    assert matches == []
    assert any(f['raw'] == '12-12-2018' and f['candidates'] == ['2018-12-12']
               for m in r['observations'] for f in m['fields'])


def test_existing_named_resolution_is_not_duplicated(engine):
    r, matches = checked(engine, 'BILLS-115CommitteeResolution115-10ih.pdf')
    assert matches == []
    assert any(f['name'] == 'draft_label' and f['raw'] == 'CommitteeResolution'
               for m in r['observations'] for f in m['fields'])


def test_reference_does_not_set_meeting_year(engine):
    r, matches = checked(engine, 'BILLS-116GSA2020-37ih.pdf')
    assert all(f['name'] not in {'meeting_date','fiscal_year_token','date_token'}
               for m in r['observations'] for f in m['fields'])
    assert matches[0]['fields'][1]['raw'] == '2020'
