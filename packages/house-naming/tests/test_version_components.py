"""Version components retain their literal slots without inventing acronym meanings."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result


def matches(result, rule):
    return [match for match in result['observations'] if match['rule'] == rule]


@pytest.mark.parametrize('name,version', [
    ('BILLS-113hjres124-IH.pdf', 'IH'),
    ('BILLS-113hjres124-IH.xml', 'IH'),
    ('BILLS-114-HR7-IH-Filed.pdf', 'IH'),
    ('BILLS-114-HR7-IH-Filed.xml', 'IH'),
    ('BILLS-113hjres70-PIH.pdf', 'PIH'),
    # Constructed source casing / separator controls.
    ('BILLS-119hr1_ih.pdf', 'ih'),
    ('BILLS-119hr1_pih.pdf', 'pih'),
])
def test_separated_house_stage(engine, name, version):
    row = checked(engine, name)
    match, = matches(row, 'house-stage-marker')
    field, = match['fields']
    assert (field['name'], field['raw'], field['code']) == ('version_token', version, version.lower())
    assert field['label']
    assert (field['start'], field['end']) == (name.index(version), name.index(version) + len(version))


@pytest.mark.parametrize('name,marker', [
    ('BILLS-116H1618_RSCih.pdf', 'RSC'),
    ('BILLS-116H3375_RSCih.pdf', 'RSC'),
    ('BILLS-116H3170_SCPih.pdf', 'SCP'),
    ('BILLS-116H3172_SCPih.pdf', 'SCP'),
    ('BILLS-116H1058_CPTih.pdf', 'CPT'),
    ('BILLS-117OAWPih.pdf', 'OAWP'),
    # Unlisted uppercase markers use the shape, not an acronym allowlist.
    ('BILLS-119HR1_XYZih.pdf', 'XYZ'),
])
def test_local_introduction_component(engine, name, marker):
    row = checked(engine, name)
    match, = matches(row, 'local-introduction-component')
    fields = {f['name']: f for f in match['fields']}
    assert fields['local_identifier']['raw'] == marker
    assert fields['local_identifier']['code'] is None
    assert fields['local_identifier']['label'] is None
    assert 'no expansion' in fields['local_identifier']['note']
    assert fields['version_token']['raw'] == fields['version_token']['code'] == 'ih'
    assert fields['version_token']['label'] == 'Introduced in House'


@pytest.mark.parametrize('number', ['01', '12345', '111111'])
def test_local_numbers_do_not_become_dates(engine, number):
    row = checked(engine, f'BILLS-119HR1_RSC_{number}ih.pdf')
    match, = matches(row, 'local-introduction-component')
    field, = [f for f in match['fields'] if f['name'] == 'local_number_token']
    assert field['raw'] == number
    assert not any(f['name'] in {'date_token', 'short_date_token', 'bioguide_token'}
                   for m in row['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'BILLS-119HR1_Services.pdf', 'BILLS-119HR1_RSCIH.pdf',
    'BILLS-119HR1_rscIh.pdf', 'BILLS-119HR1_rscih.pdf',
    'BILLS-119HR1_RSC.pdf', 'BILLS-119HR1_RSChecking.pdf',
    'BILLS-119HR1_RSCihmore.pdf', 'RSCih.pdf',
    'HHRG-119-IF00-Wstate-RSCih-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-RSCih.pdf',
    'BILLS-119HR1_%20RSCih.pdf', 'BILLS-119HR1_éRSCih.pdf',
])
def test_local_version_requires_a_whole_supported_slot(engine, name):
    assert not matches(checked(engine, name), 'local-introduction-component')


@pytest.mark.parametrize('name', [
    'HHRG-119-IF00-Wstate-IH-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-IH.pdf',
    'BILLS-119HR1-IHmore.pdf', 'IH.pdf',
])
def test_stage_marker_stays_out_of_unrelated_slots(engine, name):
    assert not matches(checked(engine, name), 'house-stage-marker')


@pytest.mark.parametrize('name', [
    'BILLS-114-HR7-IH-Filed.pdf', 'BILLS-114-HR7-IH-Filed.xml',
    'BILLS-119HR1ih-filed.pdf',
])
def test_terminal_filed_wording_is_not_a_verified_action(engine, name):
    match, = matches(checked(engine, name), 'edition-wording')
    field, = match['fields']
    assert field['name'] == 'qualifier_wording' and field['raw'].lower() == 'filed'
    assert field['code'] is None
    assert 'not an official version' in match['description']


@pytest.mark.parametrize('name', [
    'BILLS-119HR1ih-Filedmore.pdf', 'BILLS-119HR1ih-FiledbyRepJones.pdf',
    'HHRG-119-IF00-Wstate-Filed-20260101.pdf',
])
def test_terminal_filed_wording_requires_its_boundary(engine, name):
    assert not any(f['raw'].lower() == 'filed' for m in matches(checked(engine, name), 'edition-wording')
                   for f in m['fields'])


def test_query_text_does_not_supply_a_stage(engine):
    row = checked(engine, 'BILLS-119hr1ih.pdf?name=RSCih&stage=-IH&label=Filed')
    assert not matches(row, 'local-introduction-component')
    assert not matches(row, 'house-stage-marker')
    assert not matches(row, 'edition-wording')
