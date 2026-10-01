"""Reviewed null-kind legislative layouts; references are not document genres."""
import pytest
from house_naming import Engine

@pytest.fixture(scope='module')
def engine():
    return Engine()

def checked(engine, filename):
    result = engine.extract(filename)
    assert ''.join(piece['raw'] for piece in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    assert all(result[key] == value for key, value in engine.parse(filename).items())
    return result['metadata']

@pytest.mark.parametrize('filename,kind', [
    ('H.R.260_Paul_1st_Degree_1.pdf', 'amendment'),
    ('S.1462_Booker_1st_degree_2.pdf', 'amendment'),
    ('S.1462_Boozman_2nd_Degree_to_Schiff_1st_Degree_1.pdf', 'amendment'),
    ('S.3874_Cardin_2nd_Degree_1_to_Cruz_1st_Degree_1.pdf', 'amendment'),
    ('S.__Bennet_1st_Degree_11.pdf', 'amendment'),
    ('S.___Durbin_1st_Degree_08_Modified_2edc583a-0d7f-4453-b841-47b2edf091b7.pdf', 'amendment'),
    ('S___, Strategic Competition Act of 2021_Cardin_1st_Degree_2.pdf', 'amendment'),
    ('S. 151 Thune_Substitute.pdf', 'amendment'),
    ('S. 3232 Klobuchar_Blumenthal_Casey_Blunt_Substitute.pdf', 'amendment'),
    ('S. 1669 Markey-Cruz_Substitute (modified).pdf', 'amendment'),
    ('S. 4802 Cantwell-Wicker-Baldwin_Substitute Part 2.pdf', 'amendment'),
    ('#16 S. 1354 Lee Amdt  (FLO21C55).pdf', 'amendment'),
    ('AMNT-113-HJRes59sa-1R.xml', 'amendment'),
    ('AMNT-113-HJRes59sa-1R_xml.pdf', 'amendment'),
    ('CP-116HR1500RH-COMPARED-RCP116-15.pdf', 'bill-comparison'),
    ('CP-116HR3RH-P2-COMPARED-RCP116-41.pdf', 'bill-comparison'),
    ('CP-117HR5314IH-COMPARED-RCP117-20-U1.pdf', 'bill-comparison'),
    ('CRPT-114hrpt-SConRes11NS.pdf', 'committee-report'),
    ('CRPT-116hrpt-PRHhr1CHA.pdf', 'committee-report'),
    ('H. Rept 118-275.pdf', 'committee-report'),
    ('H. Rept. 118-XX (H.R. 3935).pdf', 'committee-report'),
    ('Treaty Doc. 111-8 As Reported.pdf', 'treaty-document'),
    ('Treaty Doc. 112-83.pdf', 'treaty-document'),
    ('S. 1782 Introduced Text_9dd95004-b2aa-4afb-ba57-b67ef71b2a6a.pdf', 'legislative-text'),
    ('S. 1173 Introduced.pdf', 'legislative-text'),
    ('S.484 Introduced Text.pdf', 'legislative-text'),
    ('FY25 EW Rules Print_PDF.xml', 'committee-print'),
    ('Rules_Print_HR1735_xml.pdf', 'committee-print'),
])
def test_explicit_legislative_layout_has_kind(engine, filename, kind):
    assert kind in checked(engine, filename).get('document_kind', [])

@pytest.mark.parametrize('filename', [
    '09-09-21_velazquez_amendment_in_the_nature_of_a_substitute_tally_sheet.pdf',
    'S. 151 Thune_Substitute_tally_sheet.pdf',
    'S. 447 Hickenlooper Substitute Teachers Act.pdf',
    'Report on S. 447 Hickenlooper Substitute.pdf',
    'Testimony on S. 1303 Cruz-Cantwell Substitute.pdf',
    'Degree Requirements for Higher Education.pdf',
    '1st Degree Burns.pdf',
    'Klobuchar_Substitute.pdf',
    'Substitute.pdf',
    'S. 151 Policy Substitute.pdf',
])
def test_topic_or_ambiguous_substitute_does_not_become_amendment(engine, filename):
    assert 'amendment' not in checked(engine, filename).get('document_kind', [])

@pytest.mark.parametrize('filename,forbidden', [
    ('Testimony concerning Treaty Doc. 119-3.pdf', 'treaty-document'),
    ('Treaty Doc. 117-1_ Resolution_of_Advice_and_Consent_to_Ratification.pdf', 'treaty-document'),
    ('Treaty Doc Policy.pdf', 'treaty-document'),
    ('Letter about H. Rept. 118-275.pdf', 'committee-report'),
    ('CP-117HR2116RH-RCP117-36.pdf', 'bill-comparison'),
    ('COMPARED wage trends.pdf', 'bill-comparison'),
    ('Rules Print Policy.pdf', 'committee-print'),
    ('S. 1173 Introduced Species Act.pdf', 'legislative-text'),
])
def test_reference_or_uncertain_layout_stays_uncertain(engine, filename, forbidden):
    assert forbidden not in checked(engine, filename).get('document_kind', [])

def test_comparison_preserves_both_sides_and_part(engine):
    row=checked(engine, 'CP-116HR3RH-P2-COMPARED-RCP116-41.pdf')
    assert row['comparison_source'] == ['116HR3RH-P2']
    assert row['comparison_target'] == ['RCP116-41']
    assert row['comparison_relation'] == ['COMPARED']
    assert row['congress'] == ['116']
    assert row['measure_references'] == ['hr3']
    assert row['version_token_code'] == ['rh']
    assert row['part_number'] == ['2']
    assert row['print_congress'] == ['116']
    assert row['print_number'] == ['41']

@pytest.mark.parametrize('filename,measure', [
    ('H.R.111111_Paul_1st_Degree_1.pdf', 'hr111111'),
    ('H.R. 12345 Garcia_Substitute.pdf', 'hr12345'),
    ('S.111111 Introduced.pdf', 's111111'),
])
def test_date_plausible_measure_numbers_remain_numbers(engine, filename, measure):
    row=checked(engine, filename)
    assert row['measure_references'] == [measure]
    assert not row.get('date_token')
    assert not row.get('short_date_token')

def test_unknown_report_number_and_cited_measure_are_separate(engine):
    row=checked(engine, 'H. Rept. 118-XX (H.R. 3935).pdf')
    assert row['citation_congress'] == ['118']
    assert row['number_placeholder'] == ['XX']
    assert row['measure_references'] == ['hr3935']
    assert not row.get('citation_number')
    assert not row.get('report_number')

def test_degree_metadata_preserves_literal_local_components(engine):
    row=checked(engine, 'S.3874_Cardin_2nd_Degree_1_to_Cruz_1st_Degree_1.pdf')
    assert row['subject_token'] == ['Cardin']
    assert row['target_subject'] == ['Cruz']
    assert row['degree_token'] == ['2nd_Degree','1st_Degree']
    assert row['local_number_token'] == ['1']
    assert not row.get('amendment_id')
    assert not row.get('sponsor_bioguide_id')


def test_secondary_legislative_descriptions_and_qualifiers_survive(engine):
    row=checked(engine, 'S___, Strategic Competition Act of 2021_Cardin_1st_Degree_2.pdf')
    assert row['description'] == ['Strategic Competition Act of 2021']
    assert row['subject_token'] == ['Cardin']
    row=checked(engine, 'NEW S. 3580 Cantwell_Substitute modified.pdf')
    assert row['local_modifier'] == ['NEW']
    row=checked(engine, 'FY25 EW Rules Print_PDF.xml')
    assert row['appropriation_subject'] == ['EW']
    assert row['fiscal_year_token'] == ['25']
    assert row['filename_format_token'] == ['PDF']


@pytest.mark.parametrize('filename,kind', [
    ('CRPT-117hrpt-261.pdf', 'published-report'),
    ('CRPT-117hrpt-269.pdf', 'published-report'),
    ('CRPT-114HRPT-HR644.pdf', 'conference-unnumbered'),
    ('CRPT-114HRPT-S1177.pdf', 'conference-unnumbered'),
    ('CRPT-114HRPT-HR644-JES.pdf', 'conference-legislation-part'),
    ('CRPT-114hrpt-SConRes11-Sig.xml', 'conference-legislation-part'),
    ('CRPT-114HRPT-S1177-NOCOVSIG.xml', 'conference-legislation-part'),
])
def test_report_family_is_fallback_to_specific_catalog_kind(engine, filename, kind):
    result = engine.extract(filename)
    assert checked(engine, filename)['document_kind'] == [kind]
    # The literal prefix observation remains available despite adopting the
    # more specific catalog kind in useful metadata.
    assert any(field.get('category') == 'committee-report'
               for match in result['observations'] for field in match['fields'])


@pytest.mark.parametrize('filename', [
    'CRPT-114hrpt-SConRes11NS.pdf',
    'CRPT-116hrpt-PRHhr1CHA.pdf',
])
def test_loose_report_without_specific_catalog_kind_keeps_family(engine, filename):
    assert checked(engine, filename)['document_kind'] == ['committee-report']
