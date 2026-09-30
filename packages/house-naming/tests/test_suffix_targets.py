"""Source-backed suffix components reuse the existing target/publication readers."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result


def matching(result, rule):
    return [m for m in result['observations'] if m['rule'] == rule]


@pytest.mark.parametrize('part', ['1', '2', '3'])
@pytest.mark.parametrize('extension', ['pdf', 'xml'])
def test_reported_bill_p_components_are_literal(engine, part, extension):
    name = f'BILLS-116HR3rh-p{part}.{extension}'
    row = checked(engine, name)
    match, = matching(row, 'publication-suffix-marker')
    fields = {f['name']: f for f in match['fields']}
    assert fields['publication_marker']['raw'] == 'p'
    assert fields['publication_identifier']['raw'] == part
    assert all(f['code'] is None and 'no official report' in f['note'] for f in match['fields'])
    assert not any(f['name'] in {'report_number', 'part_number'} for m in row['observations'] for f in m['fields'])


@pytest.mark.parametrize('version', ['rh', 'rs'])
@pytest.mark.parametrize('number', ['12345', '111111'])
def test_reported_bill_component_digits_do_not_become_dates(engine, version, number):
    row = checked(engine, f'BILLS-119hr1{version}-p{number}.pdf')
    match, = matching(row, 'publication-suffix-marker')
    assert next(f['raw'] for f in match['fields'] if f['name'] == 'publication_identifier') == number
    assert not any(f['name'] in {'date_token', 'short_date_token'} for m in row['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'BILLS-119hr1ih-p1.pdf', 'BILLS-119pih-p1.pdf',
    'BILLS-119hr1rh-Person1.pdf', 'BILLS-119hr1rh-p1abc.pdf',
    'BILLS-119hr1rh-p.pdf', 'BILLS-119hr1rh-pA.pdf',
    'BILLS-119-HR1-A000001-Amdt-p1.pdf',
    'HHRG-119-IF00-Wstate-p1-20260101.pdf',
])
def test_p_reader_requires_reported_bill_numeric_suffix(engine, name):
    assert not matching(checked(engine, name), 'publication-suffix-marker')


@pytest.mark.parametrize('name,marker,number', [
    ('BILLS-116HR1759ih-AINStoHR1759.pdf', 'AINS', '1759'),
    ('BILLS-116HR1994ih-AINStoHR1994.pdf', 'AINS', '1994'),
    ('BILLS-114207rfh-AmendmentintheNatureofaSubstitutetoHR207-U1.pdf', 'AmendmentintheNatureofaSubstitute', '207'),
    # Constructed separators, local modifier and explicit Senate target.
    ('BILLS-119hr1ih_ANS01toS123.pdf', 'ANS', '123'),
    ('BILLS-119hr1ih-ANSforHR2.pdf', 'ANS', '2'),
])
def test_owned_suffix_exposes_explicit_substitute_target(engine, name, marker, number):
    row = checked(engine, name)
    match, = matching(row, 'substitute-target')
    fields = {f['name']: f for f in match['fields']}
    assert fields['amendment_marker']['raw'] == marker
    assert fields['measure_number']['raw'] == number
    assert fields['target_marker']['raw'] in {'to', 'for'}
    assert fields['measure_token']['code'] in {'hr', 's'}


@pytest.mark.parametrize('number', ['12345', '111111'])
def test_target_number_reserves_its_slot_before_date_scans(engine, number):
    row = checked(engine, f'BILLS-119pih-ANStoHR{number}-U1.pdf')
    match, = matching(row, 'substitute-target')
    assert next(f['raw'] for f in match['fields'] if f['name'] == 'measure_number') == number
    assert not any(f['name'] in {'date_token', 'short_date_token'} for m in row['observations'] for f in m['fields'])
    assert any(f['name'] == 'revision_number' and f['raw'] == '1' for m in row['observations'] for f in m['fields'])


def test_offered_by_wording_preserves_text_without_resolving_identity(engine):
    name = 'BILLS-119pih-ANStoHR3633offeredbyChairmanThompsonofPennsylvania-U1.pdf'
    row = checked(engine, name)
    match, = matching(row, 'substitute-target')
    fields = {f['name']: f for f in match['fields']}
    assert fields['offering_marker']['raw'] == 'offeredby'
    assert fields['offerer_token']['raw'] == 'ChairmanThompsonofPennsylvania'
    assert fields['measure_number']['raw'] == '3633'
    assert all(fields[k]['code'] is None and 'withdrawal status' in fields[k]['note']
               for k in ('offering_marker', 'offerer_token'))
    assert any(f['name'] == 'revision_number' and f['raw'] == '1' for m in row['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'BILLS-119pih-ANStoHR123offeredby.pdf',
    'BILLS-119pih-ANStoHR123offeredbymore123.pdf',
    'BILLS-119pih-ANStoHR123offereddifferently.pdf',
    'BILLS-119pih-ANStoHR123extra.pdf',
    'BILLS-119pih-ANStoHR.pdf',
    'BILLS-119pih-%20ANStoHR123.pdf',
    'HHRG-119-IF00-Wstate-ANStoHR123-20260101.pdf',
])
def test_target_requires_a_complete_explicit_shape(engine, name):
    assert not matching(checked(engine, name), 'substitute-target')


def test_query_text_does_not_supply_target_or_component(engine):
    row = checked(engine, 'BILLS-119hr1rh.pdf?label=ANStoHR123&part=p1')
    assert not matching(row, 'substitute-target')
    assert not matching(row, 'publication-suffix-marker')


@pytest.mark.parametrize('name', ['CRPT-119hrpt12-pt2.pdf', 'CHRG-115hhrg12345-p1.pdf'])
def test_existing_publication_components_remain_distinct(engine, name):
    row = checked(engine, name)
    assert any(f['name'] in {'part_number', 'publication_identifier'} for m in row['observations'] for f in m['fields'])
    assert not any(f['note'] and 'reported-bill' in f['note'] for m in row['observations'] for f in m['fields'])
