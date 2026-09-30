"""Explicit reference wording must not swallow unrelated measure digits."""
import pytest

from house_naming import Engine
from house_naming.errors import NamingError


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for match in (*result['observations'], *result['suppressed']):
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result


@pytest.mark.parametrize('tail', ['thCongress', 'THCONGRESS', 'ThCongress', 'stCenturyAct', 'ndSession', 'rd-Century'])
def test_numbered_title_with_ordinal_tail_stays_ambiguous(engine, tail):
    name = f'BILLS-118HR2534116{tail}ih.pdf'
    result = checked(engine, name)
    match, = result['matches']
    assert match['kind'] == 'bill-titled-draft'
    assert match['record']['description'] == f'HR2534116{tail}'
    assert match['canonical_filename'] == name
    assert not {'measureNumber', 'measureType', 'references'} & match['record'].keys()
    assert result['issues'] == ['ambiguous-number-boundary']
    assert result['rejected_candidates'][0]['kind'] == 'bill-numbered-described'
    fields = [f for m in result['observations'] for f in m['fields']]
    ambiguous, = [f for f in fields if f['name'] == 'ambiguous_number_token']
    assert ambiguous['raw'] == '2534116'
    assert 'division' in ambiguous['note'] and not ambiguous['candidates']
    assert not any(f['name'] in {'measure_number', 'referenced_congress'} for f in fields)


@pytest.mark.parametrize('title', [
    'theClimateAct', 'TheClimateAct', 'THECLIMATEACT', 'StephenHacalaAct',
    'STEPHENHACALAACT', 'ThirdPartyAct', 'THIRDPARTYACT', 'thunder',
    'STABILITY', 'StandardAct', 'ndlowercase',
])
def test_ordinary_title_initial_letters_are_not_ordinals(engine, title):
    result = checked(engine, f'BILLS-119HR1512{title}ih.pdf')
    match, = result['matches']
    assert match['kind'] == 'bill-numbered-described'
    assert match['record']['measureNumber'] == 1512
    assert match['record']['description'] == title
    assert 'ambiguous-number-boundary' not in result['issues']
    assert any(f['name'] == 'measure_number' and f['raw'] == '1512'
               for m in result['observations'] for f in m['fields'])


def test_explicit_record_validation_also_checks_boundary(engine):
    with pytest.raises(NamingError) as exc:
        engine.validate({'kind': 'bill-numbered-described', 'extension': 'pdf', 'congress': 118,
                         'numberedSubject': 'HR2534116', 'description': 'thCongress', 'stage': 'ih'})
    assert exc.value.code == 'ambiguous-number-boundary'


def test_primary_measure_survives_an_ambiguous_secondary_reference(engine):
    result = checked(engine, 'BILLS-115HR5759ih-HR575921stCentAct.pdf')
    assert result['matches'][0]['record']['measureNumber'] == 5759
    fields = [(f['name'], f['raw']) for m in result['observations'] for f in m['fields']]
    assert ('measure_number', '5759') in fields
    assert ('ambiguous_number_token', '575921') in fields
    assert ('measure_number', '575921') not in fields


@pytest.mark.parametrize('name,digits', [
    ('Notes-HR575921stCentAct.pdf', '575921'),
    ('Notes-H.R. 12345thCongress.pdf', '12345'),
])
def test_free_text_reference_uses_the_same_boundary_check(engine, name, digits):
    result = checked(engine, name)
    fields = [(f['name'], f['raw']) for m in result['observations'] for f in m['fields']]
    assert ('ambiguous_number_token', digits) in fields
    assert ('measure_number', digits) not in fields


@pytest.mark.parametrize('name,number,ordinal', [
    ('Summary of Activities End of 115 Congress Final Report.pdf', '115', None),
    ('119-Congress.pdf', '119', None),
    ('119_Congress.pdf', '119', None),
    ('HELP Rules 119th Congress1.pdf', '119', 'th'),
    ('BILLS-115-AuthorizationandOversightPlanforthe115thCongress-D000399-Amdt-1.pdf', '115', 'th'),
    ('Reportofthe116thCongress.pdf', '116', 'th'),
    ('115 Congresspdf.pdf', '115', None),
    ('119thCongress1&download=1', '119', 'th'),
    ('001 Congress.pdf', '001', None),
    ('0 Congress.pdf', '0', None),
])
def test_additional_explicit_reference_forms(engine, name, number, ordinal):
    result = checked(engine, name)
    match, = [m for m in result['observations'] if m['rule'] == 'congress-wording']
    fields = {f['name']: f for f in match['fields']}
    assert fields['referenced_congress']['raw'] == number
    if ordinal:
        assert fields['congress_ordinal']['raw'] == ordinal
    else:
        assert 'congress_ordinal' not in fields
    assert all(f['code'] is None and not f['candidates'] for f in fields.values())


@pytest.mark.parametrize('name', [
    '119Congress.pdf', 'X119thCongress.pdf', '1119thCongress.pdf',
    '119-Congressional.pdf', '%119thCongress.pdf', 'Name%20119thCongress.pdf',
    'HHRG-115-BU00-Wstate-ofthe115thCongressM-20170302.pdf',
    'HHRG-115-BU00-Wstate-ofthe115thCongress-20170302.pdf',
])
def test_reference_boundaries_and_protected_witness_slots(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] == 'congress-wording' for m in result['observations'])


def test_reference_does_not_replace_primary_congress(engine):
    result = checked(engine, 'BILLS-119pih-Reportofthe115thCongress.pdf')
    fields = [(f['name'], f['raw']) for m in result['observations'] for f in m['fields']]
    assert ('congress', '119') in fields
    assert ('referenced_congress', '115') in fields
