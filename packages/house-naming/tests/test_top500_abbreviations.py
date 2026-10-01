"""Observed null-kind families plus constructed boundaries from top-500 audit."""
import pytest
from house_naming import Engine

@pytest.fixture(scope='module')
def engine(): return Engine()

def checked(engine, name, url=None):
    result = engine.extract(name, source_url=url)
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']
    assert all(result[k] == value for k, value in engine.parse(name).items())
    return result['metadata']

@pytest.mark.parametrize('name,expected', [
    ('Alpha 2.0 Twitter 20220706_Protected Whistleblower Disclosure_redacted_sanitized_opt.pdf', ['redacted', 'sanitized', 'opt']),
    ('Exhibit 11_20210112_Parag_e-mails_Memorandum for the record_Jan_12_2022_redacted_sanitized.pdf', ['redacted', 'sanitized']),
    ('0723-Human-Rights-at-Home-Media-Politics-and-Safety-of-Journalists_Scrubbed.pdf', ['Scrubbed']),
    ('1211-Religious-Freedom-in-Eurasia-Are-Governments-Keeping-Their-Commitments-Unofficial-Scrubbed.pdf', ['Unofficial', 'Scrubbed']),
    ('DIVISION A- AG SOM OCR FY17.pdf', ['OCR']),
])
def test_processing_wording_survives_terminal_groups(engine, name, expected):
    row = checked(engine, name)
    assert row.get('qualifier_wording') == expected
    assert not {'redacted','sanitized','scrubbed','ocr','opt'} & set(row.get('document_kind', []))

@pytest.mark.parametrize('name', [
    'Hearing on Sanitized Food Regulations.pdf',
    'Report on Scrubbed Launch Operations.pdf',
    'Opt Out of Federal Regulations.pdf',
    'The Unofficial Economy.pdf',
    'OCR Technology in Public Schools.pdf',
    'Sanitized Food Regulations.pdf',
    'Scrubbed Launch Operations.pdf',
])
def test_qualifier_topics_are_not_processing_claims(engine, name):
    assert not checked(engine, name).get('qualifier_wording')

@pytest.mark.parametrize('name', [
    'S 3775 SxS.pdf',
    'Childhood Diabetes Reduction Act SxS_e31b4831-eff3-4edc-b54d-115bca2de4a1.pdf',
    'S. 2355 SxS (2)_cdc056e4-8308-4f12-a644-5662156d6b8d.pdf',
])
def test_help_sxs_source_qualified(engine, name):
    row = checked(engine, name, 'https://www.help.senate.gov/imo/media/doc/example.pdf')
    assert row.get('document_kind') == ['section-by-section']
    assert row['document_abbreviation'] == ['SxS']

@pytest.mark.parametrize('url', [None, 'https://example.org/S%203775%20SxS.pdf'])
def test_sxs_remains_ambiguous_outside_qualified_publisher(engine, url):
    row = checked(engine, 'S 3775 SxS.pdf', url)
    assert not row.get('document_kind')
    assert row['document_abbreviation'] == ['SxS']

@pytest.mark.parametrize('name', ['SxS Racing.pdf', 'Report about SxS.pdf', 'HHRG-119-IF00-Wstate-SxS-20250318.pdf'])
def test_sxs_topics_and_witness_slots_are_not_section_analysis(engine, name):
    row = checked(engine, name, 'https://www.help.senate.gov/imo/media/doc/example.pdf')
    assert 'section-by-section' not in row.get('document_kind', [])

@pytest.mark.parametrize('name', [
    'DIV A AG SOM FY18 OMNI.OCR.pdf',
    'DIVISION A- AG SOM OCR FY17.pdf',
    'DIV C - DEFENSESOM FY18 OMNI.OCR.pdf',
    '1 - FRONT -SOM FY17OCR.pdf',
])
def test_appropriations_som_source_qualified(engine, name):
    row = checked(engine, name, 'https://docs.house.gov/billsthisweek/example.pdf')
    assert row.get('document_kind') == ['explanatory-statement']
    assert row.get('document_abbreviation') == ['SOM']
    assert row.get('fiscal_year_token') in (['17'], ['18'])
    assert row.get('qualifier_wording') == ['OCR']

@pytest.mark.parametrize('name,url', [
    ('SOM.pdf', 'https://docs.house.gov/billsthisweek/example.pdf'),
    ('DIV A AG SOM FY18 OMNI.OCR.pdf', None),
    ('DIV A AG SOM FY18 OMNI.OCR.pdf', 'https://example.org/file.pdf'),
    ('HHRG-119-IF00-Wstate-SOM-20250318.pdf', 'https://docs.house.gov/meetings/example.pdf'),
])
def test_som_needs_publisher_and_appropriation_structure(engine, name, url):
    assert 'explanatory-statement' not in checked(engine, name, url).get('document_kind', [])

@pytest.mark.parametrize('name', ['2-9-23 -- Open Executive Session.pdf', 'executive_session_030425.pdf',
                                '1-7-20 -- Exec Bus Mtg U.S.-Mexico-Canada Agreement.pdf'])
def test_finance_session_heading_preserves_context_without_document_guess(engine, name):
    row = checked(engine, name, 'https://www.finance.senate.gov/imo/media/doc/example.pdf')
    assert not row.get('document_kind')
    assert row.get('meeting_wording')
    assert not row.get('meeting_type')

@pytest.mark.parametrize('name', ['05-08-2025-full-nom.pdf', 'nom_1162025.pdf', '07-31-2025-nom_hearing.pdf'])
def test_armed_services_nomination_headings(engine, name):
    row = checked(engine, name, 'https://www.armed-services.senate.gov/imo/media/doc/example.pdf')
    assert row.get('document_kind') == ['nomination']
    assert row.get('date_token')
    assert not row.get('witness_id')

@pytest.mark.parametrize('name,url', [
    ('05-08-2025-full-nom.pdf', None),
    ('nom_1162025.pdf', 'https://example.org/file.pdf'),
    ('Report on Executive Session Procedure.pdf', 'https://www.finance.senate.gov/imo/media/doc/example.pdf'),
    ('118th Congress ENR Cmte Subcommittee Assignments 3-23-23 SENR Cmte Bus Mtg.pdf', 'https://www.energy.senate.gov/meeting/file.pdf'),
    ('Short List 1-23-25 SENR Cmte Bus Mtg.pdf', 'https://www.energy.senate.gov/meeting/file.pdf'),
    ('COFA Legislative Proposal - Executive Branch Transmittal.pdf', 'https://www.energy.senate.gov/meeting/file.pdf'),
])
def test_referenced_event_or_unqualified_abbreviation_is_not_primary_kind(engine, name, url):
    assert not {'business-meeting','nomination'} & set(checked(engine, name, url).get('document_kind', []))


def test_compact_support_trailing_local_number(engine):
    row = checked(engine, 'john_rmaleysupportforkolar1.pdf')
    assert row.get('subject_token') == ['john_rmaley']
    assert row.get('document_token') == ['supportfor']
    assert row.get('recipient_token') == ['kolar']
    assert row.get('local_number_token') == ['1']
    assert not row.get('document_kind')

@pytest.mark.parametrize('name', ['aaj_support_for_saporito.pdf', 'revhornsupportforbryan.pdf',
                                '03 28 23 -- U.S. Support of Democracy And Human Rights.pdf'])
def test_support_does_not_imply_a_letter_or_witness(engine, name):
    row = checked(engine, name)
    assert not row.get('document_kind')
    assert not row.get('witness_id')


def test_finance_session_context_does_not_replace_nomination_kind(engine):
    row = checked(engine, '11-17-21 -- Executive Session - Nominations.pdf',
                  'https://www.finance.senate.gov/imo/media/doc/example.pdf')
    assert row['document_kind'] == ['nomination']
    assert row['meeting_wording'] == ['Executive Session']


@pytest.mark.parametrize('suffix', ['(2)', '2'])
def test_source_qualified_sxs_keeps_local_numeric_component(engine, suffix):
    # The parenthesized form is observed; bare-number is a boundary control.
    name = f'S. 2355 SxS {suffix}_cdc056e4-8308-4f12-a644-5662156d6b8d.pdf'
    row = checked(engine, name, 'https://www.help.senate.gov/imo/media/doc/example.pdf')
    assert row['document_kind'] == ['section-by-section']
    assert row.get('local_number_token') == ['2']
    assert not row.get('revision_number')


@pytest.mark.parametrize('suffix', ['(2', '2)', '(2))', '((2)'])
def test_sxs_numeric_suffix_requires_balanced_parentheses(engine, suffix):
    row = checked(engine, f'S. 2355 SxS {suffix}.pdf',
                  'https://www.help.senate.gov/imo/media/doc/example.pdf')
    assert 'section-by-section' not in row.get('document_kind', [])


def test_degree_amendment_keeps_observed_modifier_spelling(engine):
    name = 'S.___Grassley_1st_Degree_01_Modfied_92ae810d-649a-4a3b-8edc-64ee0c0aee3a.pdf'
    row = checked(engine, name)
    assert row['document_kind'] == ['amendment']
    assert row.get('qualifier_wording') == ['Modfied']
    assert row['subject_token'] == ['Grassley']
    assert row['degree_token_code'] == ['1']


def test_degree_modifier_capture_preserves_revision_components(engine):
    row = checked(engine, 'S. 482_Cardin_1st_Degree_7_REVISED1.pdf')
    assert row['revision_marker'] == ['REVISED']
    assert row['revision_number'] == ['1']
    assert row['qualifier_wording'] == ['REVISED1']
    assert row['local_number_token'] == ['7']
    assert row['measure_references'] == ['s482']
