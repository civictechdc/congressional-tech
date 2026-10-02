"""Complete local layouts establish a kind; incidental references do not."""
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name, url=None):
    result = engine.extract(name, source_url=url)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result['metadata']


@pytest.mark.parametrize('name', [
    'S. Res. 123.pdf', 'S. Res. 123 As Reported.pdf',
    'S. Res. 148 As Reported1.pdf', 'S. Res. 120 REVISED.pdf',
    'S. Res. 226 (Reported Out).pdf', 'S.RES. 427 as reported.pdf',
    'S.Res. 52 - Reported Out.pdf', 'S.Res 713 -- reported out DAV22M60.pdf',
    'S.Res.322 -- reported out MDM22E72.pdf', 'S.Res.20_Reported Out1.pdf',
    'S Res 526 Text.pdf', 'S. Res. ___.pdf',
    'S. Res. __ (Commending Career Professionals at State).pdf',
])
def test_complete_resolution_layout(engine, name):
    assert checked(engine, name)['document_kind'] == ['legislative-text']


@pytest.mark.parametrize('name,number', [
    ('S. Res. 111111.pdf', '111111'), ('S. Res. 12345.pdf', '12345'),
    ('S. Res. 1481.pdf', '1481'), ('S.Res.4583.pdf', '4583'),
])
def test_resolution_number_is_whole_and_never_a_date(engine, name, number):
    row = checked(engine, name)
    assert row['document_kind'] == ['legislative-text']
    assert row['measure_references'] == ['sres' + number]
    assert not row.get('date_token') and not row.get('short_date_token')
    assert not row.get('numeric_suffix_token')


def test_reported_wording_does_not_invent_official_version(engine):
    row = checked(engine, 'S. Res. 123 As Reported.pdf')
    assert row['qualifier_wording'] == ['As Reported']
    assert not row.get('version_token') and not row.get('congress')


def test_placeholder_resolution_retains_title_without_number(engine):
    row = checked(engine, 'S. Res. __ (Commending Career Professionals at State).pdf')
    assert row['number_placeholder'] == ['__']
    assert row['description'] == ['Commending Career Professionals at State']
    assert not row.get('measure_number') and not row.get('congress')


@pytest.mark.parametrize('name', [
    'RCP_277_xml.pdf', 'RCP_288_xml.xml', 'RCP_3935_2_xml_0.pdf',
    'RCP_H5961_xml.pdf', 'rcp_h2616_h2617_xml_0.xml',
    'RCP_H2868etc_xml_1.pdf', 'rcp_h1897-2_xml.pdf',
    'RCP_H2483_xml (002).pdf', 'rcp_h7726_02_xml.xml',
    'RCP_xml_1.pdf', 'H3564_RCP_xml.pdf', 'CJS RCP FINAL_xml.pdf',
    'LHHS RCP FINAL_xml.pdf', 'mlva-rcp_xml.pdf',
    'RCP2_STOPINSIDERTRADING_xml.pdf',
])
def test_complete_local_print_layout(engine, name):
    assert checked(engine, name)['document_kind'] == ['committee-print']


def test_local_print_number_does_not_invent_identity(engine):
    row = checked(engine, 'RCP_111111_2_xml_0.pdf')
    assert row['local_number_token'] == ['111111']
    assert not row.get('measure_number') and not row.get('print_number')
    assert not row.get('congress') and not row.get('date_token')
    row = checked(engine, 'RCP_H5961_xml.pdf')
    assert row['measure_number'] == ['5961']
    assert not row.get('print_number') and not row.get('congress')
    row = checked(engine, 'RCP2_STOPINSIDERTRADING_xml.pdf')
    assert row['local_number_token'] == ['2']
    assert row['subject_token'] == ['STOPINSIDERTRADING']
    assert not row.get('print_number') and not row.get('measure_number')


@pytest.mark.parametrize('name,kind', [
    ('Motion to Authorize Subpoena to Twitter and Facebook (Graham).pdf', 'motion'),
    ('Motion to Recommit H.R. 123.pdf', 'motion'),
    ('Motion to Table the Amendment.pdf', 'motion'),
    ('Proposed Amendment to SENR Cmte Rules for the 119th Congress 1-23-25 Bus Mtg.pdf', 'amendment'),
    ('Amendment to Committee Rules.pdf', 'amendment'),
])
def test_procedural_headings(engine, name, kind):
    assert checked(engine, name)['document_kind'] == [kind]


@pytest.mark.parametrize('name,forbidden', [
    ('Testimony on S. Res. 123.pdf', 'legislative-text'),
    ('S. Res. 123 Fact Sheet.pdf', 'legislative-text'),
    # The retained s-res-542 download alias points to a resolving-clause
    # amendment, unlike a complete printed resolution basename.
    ('s-res-542', 'legislative-text'),
    ('S.Res.123_Cardin_1st_Degree_1.pdf', 'legislative-text'),
    ('Letter about RCP_277_xml.pdf', 'committee-print'),
    ('Testimony on RCP_H5961_xml.pdf', 'committee-print'),
    ('RCP-116-01.pdf', 'committee-print'),
    ('RCP_277_Policy.pdf', 'committee-print'),
    ('Motion Pictures.pdf', 'motion'),
    ('Motion to Authorize Act Testimony.pdf', 'motion'),
    ('Report on Motion to Recommit.pdf', 'motion'),
    ('First Amendment and Committee Rules.pdf', 'amendment'),
    ('Testimony on Proposed Amendment to Committee Rules.pdf', 'amendment'),
    ('Proposed Amendment to Committee Rules Summary.pdf', 'amendment'),
])
def test_reference_or_topic_is_not_primary_kind(engine, name, forbidden):
    assert forbidden not in checked(engine, name).get('document_kind', [])


def test_source_qualified_comparative_print(engine):
    name = 'CP-117HR2773RH-RCP117-47.pdf'
    row = checked(engine, name, 'https://rules.house.gov/sites/republicans.rules.house.gov/files/' + quote(name))
    assert row['document_kind'] == ['bill-comparison']
    assert row['comparison_source'] == ['117HR2773RH']
    assert row['comparison_target'] == ['RCP117-47']
    assert row['measure_references'] == ['hr2773']
    assert row['congress'] == ['117']
    assert row['print_congress'] == ['117'] and row['print_number'] == ['47']
    for url in (None, 'https://example.com/' + name, 'https://rules.house.gov.example.com/' + name):
        assert 'bill-comparison' not in checked(engine, name, url).get('document_kind', [])


@pytest.mark.parametrize('name,measure,subject', [
    ('118hr5893ih_to_CJS RCP FINAL_xml.pdf', 'hr5893', 'CJS'),
    ('118hr5894ih_to_LHHS RCP FINAL_xml.pdf', 'hr5894', 'LHHS'),
])
def test_reviewed_comparative_print_to_layout(engine, name, measure, subject):
    row = checked(engine, name, 'https://rules.house.gov/sites/republicans.rules.house.gov/files/' + quote(name))
    assert row['document_kind'] == ['bill-comparison']
    assert row['comparison_target'] == [subject + ' RCP FINAL_xml']
    assert row['measure_references'] == [measure]
    assert row['version_token_code'] == ['ih']
    assert row['congress'] == ['118']
    assert not row.get('print_number') and not row.get('print_congress')
    assert 'bill-comparison' not in checked(engine, name).get('document_kind', [])


@pytest.mark.parametrize('name,url', [
    ('SCA_04.27.2017.pdf', 'https://www.aging.senate.gov/imo/media/doc/SCA_04.27.2017.pdf'),
    ('SCA_Scott_2_6_19.pdf', 'https://www.aging.senate.gov/imo/media/doc/SCA_Scott_2_6_19.pdf'),
    ('B2E156A9718FFEE0A39AEE760A2112F1855BAD18DAD413F75FE4A6ADA01E8BAD.spw-06092021.pdf', None),
])
def test_committee_abbreviation_alone_does_not_supply_kind(engine, name, url):
    # Reviewed SCA PDFs include both statements and a complete hearing.
    # One retained SPW transcript cannot qualify every SPW file as a transcript.
    assert not checked(engine, name, url).get('document_kind')


REVIEWED = json.loads((Path(__file__).parent / 'fixtures/reviewed_legislative_committee_files.json').read_text())


@pytest.mark.parametrize('case', REVIEWED['cases'], ids=lambda case: case['filename'])
def test_reviewed_source_filename_reading(engine, case):
    # The fixture records body findings separately from what filenames establish.
    # These tests validate extraction only, not live URLs or retained PDF bytes.
    row = checked(engine, case['filename'], case['url'])
    assert row.get('document_kind', []) == case['expected_filename_kind']
    for alias in case.get('aliases', []):
        row = checked(engine, alias['filename'], alias['url'])
        assert row.get('document_kind', []) == alias['expected_filename_kind']
