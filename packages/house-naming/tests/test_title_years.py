"""Literal Act title references must not become dates or split identifiers."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def references(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    found = [m for m in result['observations'] if m['rule'] == 'act-year-reference']
    for match in found:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert field['candidates'] == [] and field['code'] is None
            assert field['label'] is None and 'no enactment' in field['note']
    return found


@pytest.mark.parametrize('name,year', [
    # Retained corpus names, including historical references and current titles.
    ('BILLS-1133211ih-MortgageChoiceActof2013.pdf', '2013'),
    ('BILLS-113HR3176ih-ToreauthorizetheReclamationStatesEmergencyDroughtReliefActof1991.pdf', '1991'),
    ('BILLS-113HR982ih-FurtheringAsbestosClaimTransparencyFACTActof2013.pdf', '2013'),
    ('BILLS-118-HR__PipelineSafetyModernizationandExpansionActof2024-A000370-Amdt-AMD_03.pdf', '2024'),
    ('BILLS-117pih-HR___toamendtheSecuritiesExchangeActof1934torequirecoveredissuerstocarryoutaracialequityauditevery2yearsandforotherpurposes.pdf', '1934'),
    ('08.01.25-Final-Section-by-Section-Discussion-Draft-Native-Childrens-Commission-Implementation-Act-of-2025.pdf', '2025'),
    # Constructed spacing, casing, extension, and continuation controls.
    ('ACT OF 2024.pdf', '2024'),
    ('act_of_2024.xml', '2024'),
    ('Act-of-2024.pdf.pdf', '2024'),
    ('  ExampleActof2024.pdf  ', '2024'),
    ('ABCActof2024.pdf', '2024'),
    ('Actof2024ih.pdf', '2024'),
    ('Actof2024toreauthorize.pdf', '2024'),
    ('Actof2024TheProposal.pdf', '2024'),
    ('Actof2024things.pdf', '2024'),
    ('Actof2024pdf', '2024'),
    ('Act of 1934-summary.pdf', '1934'),
])
def test_printed_year_reference(engine, name, year):
    match, = references(engine, name)
    assert [(f['name'], f['raw']) for f in match['fields']] == [
        ('reference_marker', name[match['start']:match['start'] + 3]),
        ('reference_year_token', year),
    ]


@pytest.mark.parametrize('name', [
    # Real longer-number slug; its source label independently says 2018.
    'preliminary-estimate-of-the-original-bill-entitled-the-helping-to-end-addiction-and-lessen-heal-substance-use-disorders-act-of-20182',
    'preliminary-estimate-of-the-original-bill-entitled-the-helping-to-end-addiction-and-lessen-heal-substance-use-disorders-act-of-20182&download=1',
    # No visible boundary in this retained all-uppercase title.
    'BILLS-118676ih-COASTALCOMMUNIITESOCEANACIDIFICATIONACTOF2023.pdf',
    # Constructed word interiors, malformed years, ordinals and URL escapes.
    'compactof2024.pdf', 'COMPACTOF2024.pdf', 'actorof2024.pdf',
    'contractof2024.pdf', 'MyACTOF2024.pdf', 'éActof2024.pdf',
    '%41Actof2024.pdf', '%Actof2024.pdf', 'Actof20241.pdf',
    'Actof20240101.pdf', 'Actof24.pdf', 'Actof024.pdf',
    'Actof0000.pdf', 'Actof2024th.pdf', 'Actof2024thCentury.pdf',
    'Actof2024THCongress.pdf',
    'Actof2024TH.pdf', 'Actof2024ST.pdf', 'Actof2024ND.pdf',
    'Actof2024RD.pdf', 'Actof2024THProposal.pdf', 'Actof2024th.v2.pdf',
    'Actof2024TH-Revision.pdf', 'Actof2024ND_revision.pdf',
    # Existing concrete slots and query text must retain their ownership.
    'HHRG-119-IF00-Wstate-Actof2024-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-Actof2024.pdf',
    'download.pdf?title=Actof2024',
])
def test_does_not_reinterpret_unqualified_or_owned_text(engine, name):
    assert not references(engine, name)


def test_each_repeated_reference_keeps_its_own_span(engine):
    name = 'BILLS-116-theSafeAccountbleFairandEnvironmentallyResponsiblePipelinesActof2019ortheSAFERPipelinesActof2019-U000031-Amdt-1.pdf'
    found = references(engine, name)
    assert len(found) == 2
    assert [(f['raw'], f['start'], f['end']) for m in found for f in m['fields']
            if f['name'] == 'reference_year_token'] == [('2019', 74, 78), ('2019', 102, 106)]


def test_reference_year_is_not_an_event_date_or_congress(engine):
    name = 'Act of 1934 and Act of 2024.pdf'
    assert len(references(engine, name)) == 2
    fields = [f for m in engine.extract(name)['observations'] for f in m['fields']]
    assert not any(f['name'] in {'date_token', 'short_date_token', 'congress'} for f in fields)
