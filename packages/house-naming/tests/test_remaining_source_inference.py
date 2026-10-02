"""Source-qualified SPW readings and complete Senate bill edition boundaries."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,number', [
    ('S. 4064 Reported out version -- PAT22557.pdf', '4064'),
    ('S. 712 As Reported2.pdf', '712'),
    ('S. 727 As Reported1.pdf', '727'),
    ('S.1203_Reported Out1.pdf', '1203'),
    ('S.1457_Reported Out1.pdf', '1457'),
    ('S.2006_Reported Out1.pdf', '2006'),
    ('S.416_Reported Out1.pdf', '416'),
    ('S.490_Reported Out2.pdf', '490'),
    ('S.4955 Reported out version -- ROS22G14.pdf', '4955'),
    ('S.847_Reported Out1.pdf', '847'),
    ('S. 111111 Reported Out1.pdf', '111111'),
    ('S. 12345 Reported out version -- DAV22M71.pdf', '12345'),
])
def test_complete_senate_edition_keeps_measure_number(engine, name, number):
    result = engine.extract(name)
    assert result['metadata']['document_kind'] == ['legislative-text']
    assert result['metadata']['measure_number'] == [number]
    assert result['metadata']['measure_references'] == ['s' + number]
    assert not result['metadata'].get('congress')
    assert not result['metadata'].get('version_token_code')
    assert result['matches'] == engine.parse(name)['matches']
    assert ''.join(part['raw'] for part in result['pieces']) == name


@pytest.mark.parametrize('name', [
    'S. 1945 SAFE Act_Revised.pdf',
    'S. 3386 TB Reported out version -- MDM22E73.pdf',
    'S. 860 - BUST Fentanyl Reported Out.pdf',
    'S. 868 - MEGOBARI Reported Out.pdf',
    'S. 1441 Substitute Amendment REVISED.pdf',
    'S. 482_Cardin_1st_Degree_7_REVISED1.pdf',
    'S. 704_Murphy_1st_Degree_1_REVISED.pdf',
    'S.2043_Cruz_1st_Degree_1_REVISED.pdf',
    'S. 123 Summary As Reported.pdf',
    'S. 123 Amendment Reported Out.pdf',
    'S. 123 Letter As Reported.pdf',
    'S. 123 Text Summary.pdf',
])
def test_edition_words_do_not_reclassify_titles_or_other_genres(engine, name):
    assert 'legislative-text' not in engine.extract(name)['metadata'].get('document_kind', [])


EPW = 'https://www.epw.senate.gov/public/_cache/files/example.pdf'
PREFIX = 'C2616049BC40936D732882E3AB14200BC3F409C6DBCE4377E06F979312E87D34.'


@pytest.mark.parametrize('stem', [
    'spw-01242024-oversight-of-tsca-amendments-implementation',
    'spw-05042022-business-meeting',
    'spw-06082022-nomination-hearing---caputo-and-crowell',
    'spw-04212022-field-hearing',
    'spw-031319',
    'spw-05042022-hearing-on-S.111111-and-HR12345',
])
def test_epw_spw_adds_genre_without_losing_existing_readings(engine, stem):
    name = PREFIX + stem + '.pdf'
    baseline = engine.extract(name)
    qualified = engine.extract(name, source_url=EPW)
    assert qualified['metadata']['document_kind'] == ['transcript']
    assert qualified['metadata']['document_family'] == ['transcript']
    for key, values in baseline['metadata'].items():
        if key not in {'document_kind', 'document_family'}:
            assert set(values) <= set(qualified['metadata'].get(key, [])), key
    assert qualified['matches'] == baseline['matches']
    assert qualified['valid'] == baseline['valid']
    assert ''.join(part['raw'] for part in qualified['pieces']) == name
    for match in qualified['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    assert qualified['metadata']['document_abbreviation'] == ['spw']
    assert not qualified['metadata'].get('document_abbreviation_label')


def test_spw_retains_ambiguous_dates_and_suffix_measure_references(engine):
    row = engine.extract('SPW-05042022-Hearing-on-S.111111-and-HR12345.pdf', source_url=EPW)['metadata']
    assert row['document_kind'] == ['transcript']
    assert row['date_token_candidates'] == ['2022-04-05', '2022-05-04']
    assert row['measure_number'] == ['111111', '12345']
    assert row['measure_references'] == ['s111111', 'hr12345']


@pytest.mark.parametrize('url', [
    None,
    'https://example.org/SPW-03152023.pdf',
    'https://epw.senate.gov.example.org/SPW-03152023.pdf',
    'https://www.epw.senate.gov.example.org/SPW-03152023.pdf',
    'https://other.senate.gov/SPW-03152023.pdf',
])
def test_spw_requires_exact_publisher_host(engine, url):
    assert 'transcript' not in engine.extract('SPW-03152023.pdf', source_url=url)['metadata'].get('document_kind', [])


@pytest.mark.parametrize('url', ['https://epw.senate.gov/example.pdf', EPW])
def test_spw_accepts_only_the_reviewed_publisher_hosts(engine, url):
    assert engine.extract('SPW-03152023.pdf', source_url=url)['metadata']['document_kind'] == ['transcript']


@pytest.mark.parametrize('name', [
    'SPW05112022.pdf', 'SPW-090132023-Extreme-Heat.pdf',
    'Field-SPW-05062022.pdf', 'SPW-04142021B.pdf',
    '06-09-2021-mehan-testimony.pdf',
    'gsa-committee-resolution---san-francisco-federal-building.pdf',
    'wildlife-innovation-and-longevity-driver-reauthorization-act.pdf',
    'SCA-123.pdf', 'Support-123.pdf',
])
def test_spw_keeps_unreviewed_variants_and_other_epw_documents_out(engine, name):
    assert 'transcript' not in engine.extract(name, source_url=EPW)['metadata'].get('document_kind', [])
