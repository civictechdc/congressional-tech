"""Print mentions are not document identities; local tags retain their own slots."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    for m in result['observations']:
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def added(result, rule):
    return [m for m in result['observations'] if m['rule'] == rule]


@pytest.mark.parametrize('name,phrase', [
    ('09-09-21_committee_print.pdf', 'committee_print'),
    ('09-09-21_adoption_of_committee_print_as_amended_tally_sheet.pdf', 'committee_print'),
    ('BILLS-113pih-CommitteePrintofHR_______theDepartmentofEnergyResearchandDevelopmentActof2014.pdf', 'CommitteePrint'),
    ('BILLS-117pih-ANStotheCommitteePrint.pdf', 'CommitteePrint'),
    ('BILLS-117pih-CommitteePrintbytheCommitteeonOversightandReform.pdf', 'CommitteePrint'),
    ('BILLS-119HR647ih-CommitteePrint-U2.pdf', 'CommitteePrint'),
    ('FY25 AG Bill Rules Committee Print Final.pdf', 'Rules Committee Print'),
    ('FY25 MCVA Rules Committee Print 3.43 05.23.2024_xml.pdf', 'Rules Committee Print'),
    ('Final INT Rules Committee Print_PDF.pdf', 'Rules Committee Print'),
    ('committee-print-1251', 'committee-print'),
    ('updated_committee_print_for_website.pdf', 'committee_print'),
    # Constructed casing and word-boundary controls.
    ('draft_SubcommitteePrint.pdf', 'SubcommitteePrint'),
    ('draft_CmtePrint.pdf', 'CmtePrint'),
    ('COMMITTEE_PRINT.pdf', 'COMMITTEE_PRINT'),
])
def test_print_wording_preserves_the_exact_mention(engine, name, phrase):
    result = checked(engine, name)
    match, = added(result, 'committee-print-wording')
    field, = match['fields']
    assert (field['name'], field['raw']) == ('print_token', phrase)
    assert (field['start'], field['end']) == (name.index(phrase), name.index(phrase) + len(phrase))
    assert field['code'] is None and field['label'] is None and not field['candidates']
    assert not any(f['name'] in {'print_number', 'print_identifier'} for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'BILLS-117CommitteePrintih.pdf',
    'BILLS-119CommitteePrint119-Aih.pdf',
    'BILLS-119CommitteePrintSubtitleApp-U1.pdf',
    'BILLS-119CommitteePrintSubtitleBpp.pdf',
    'BILLS-119CommitteePrintSubtitleCpp.pdf',
    'BILLS-112-CommitteePrint-J000032-Amdt-19.pdf',
    'BILLS-117CmtePrint117-1ih.pdf',
])
def test_existing_print_fields_are_not_duplicated(engine, name):
    result = checked(engine, name)
    assert not added(result, 'committee-print-wording')
    assert any(f['name'] in {'label', 'print_token'} and 'print' in f['raw'].lower()
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'committeeprinting.pdf', 'COMMITTEEPRINTING.pdf', 'CommitteePrinters.pdf',
    'committeeprintemps.pdf', 'CommitteePrintoffice.pdf',
    'HHRG-119-IF00-Wstate-CommitteePrint-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-CommitteePrint.pdf',
    'éCommitteePrint.pdf', '%20CommitteePrint.pdf',
])
def test_print_word_boundaries_and_assigned_slots(engine, name):
    assert not added(checked(engine, name), 'committee-print-wording')


@pytest.mark.parametrize('name,number', [
    ('BILLS-116H1058_CPTih.pdf', '1058'),
    ('BILLS-116H806_CPTih.pdf', '806'),
    ('BILLS-119HR1_cptIH.pdf', '1'),
])
def test_cpt_tail_exposes_version_without_changing_measure(engine, name, number):
    result = checked(engine, name)
    match, = added(result, 'local-introduction-component')
    fields = {f['name']: f for f in match['fields']}
    assert fields['local_identifier']['raw'].lower() == 'cpt'
    assert fields['local_identifier']['code'] is None
    assert 'no expansion' in fields['local_identifier']['note']
    assert fields['version_token']['raw'].lower() == 'ih'
    assert fields['version_token']['code'] == 'ih'
    assert fields['version_token']['label'] == 'Introduced in House'
    assert any(f['name'] == 'measure_number' and f['raw'] == number for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('number', ['01', '12345', '111111'])
def test_local_cpt_numbers_reserve_their_slots(engine, number):
    result = checked(engine, f'BILLS-116CPT_{number}ih.pdf')
    match, = added(result, 'local-introduction-component')
    fields = {f['name']: f for f in match['fields']}
    assert fields['local_number_token']['raw'] == number
    assert 'not an established bill' in fields['local_number_token']['note']
    assert not any(f['name'] in {'date_token', 'short_date_token', 'measure_number', 'print_number', 'bioguide_token'}
                   for m in result['observations'] for f in m['fields'])
    assert len([f for m in result['observations'] for f in m['fields'] if f['name'] == 'version_token']) == 1


@pytest.mark.parametrize('name', [
    'Near-Miss-Cpt.-Ambrosi-Testimony_f02a29e9-f068-4cdd-8f39-40ee4f139072-1.pdf',
    'CPT_01ih.pdf', 'BILLS-119-HR1-A000001-Amdt-CPT_01.pdf',
    'BILLS-119HR1_CPTfooih.pdf', 'BILLS-119HR1_CPTihMore.pdf',
])
def test_local_cpt_reader_requires_its_legislative_slot(engine, name):
    assert not added(checked(engine, name), 'local-introduction-component')


def test_query_text_does_not_supply_either_kind_of_marker(engine):
    result = checked(engine, 'BILLS-119hr1ih.pdf?label=CommitteePrint&other=CPTih')
    assert not added(result, 'committee-print-wording')
    assert not added(result, 'local-introduction-component')
