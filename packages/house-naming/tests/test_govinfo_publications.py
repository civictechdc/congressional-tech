"""GovInfo help examples and constructed combinations outside the saved corpus."""
import pytest
from jsonschema import Draft202012Validator

from house_naming import Engine
from house_naming.compiler import filename_schema


@pytest.fixture(scope='module')
def engine():
    return Engine()


PUBLICATIONS = [
    ('CPRT', 'hprt', 'published-print', 'House committee print'),
    ('CPRT', 'sprt', 'published-print', 'Senate committee print'),
    ('CPRT', 'jprt', 'published-print', 'Joint committee print'),
    ('CPRT', 'wprt', 'published-print', 'House Ways and Means committee print'),
    ('CRPT', 'hrpt', 'published-report', 'House report'),
    ('CRPT', 'srpt', 'published-report', 'Senate report'),
    ('CRPT', 'erpt', 'published-report', 'Senate executive report'),
    ('CHRG', 'hhrg', 'published-hearing', 'House hearing'),
    ('CHRG', 'shrg', 'published-hearing', 'Senate hearing'),
    ('CHRG', 'jhrg', 'published-hearing', 'Joint hearing'),
]


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('family,code,kind,label', PUBLICATIONS)
@pytest.mark.parametrize('congress', ['9', '99', '119'])
@pytest.mark.parametrize('extension', ['pdf', 'HTM'])
def test_all_documented_types_agree_in_strict_and_literal_readers(engine, family, code, kind, label, congress, extension):
    name = f'{family}-{congress}{code.upper()}12345.{extension}'
    result = checked(engine, name)
    assert result['valid']
    match, = [m for m in result['observations'] if m['rule'] == kind]
    data = {f['name']: f for f in match['fields']}
    assert data['publication_code']['raw'] == code.upper()
    assert data['publication_code']['code'] == code
    assert data['publication_code']['label'] == label
    assert data['publication_code']['vocabulary_url'] == f'https://www.govinfo.gov/help/{family.lower()}'
    assert data['publication_number']['raw'] == '12345'
    assert data['congress']['raw'] == congress
    assert not fields(result, 'short_date_token') and not fields(result, 'date_token')
    record, = [m['record'] for m in result['matches']]
    assert (record['kind'], record['publicationType'], record['congress']) == (kind, code, int(congress))
    assert engine.parse(engine.render(record))['matches'][0]['record'] == record
    Draft202012Validator(filename_schema(engine.guide)).validate(name)


@pytest.mark.parametrize('family,code,kind,label', PUBLICATIONS)
def test_literal_package_rules_cover_exactly_the_strict_publication_type_enums(engine, family, code, kind, label):
    typ = engine.guide['patterns'][kind]['fields']['publicationType']
    expected = {c for f, c, k, _ in PUBLICATIONS if k == kind}
    assert set(engine.guide['field_types'][typ]['enum']) == expected


@pytest.mark.parametrize('name,role', [
    ('CPRT-109HPRT23849.pdf', 'jacket ID when available, otherwise a print number'),
    ('CRPT-109srpt322.pdf', 'report number'),
    ('CHRG-111hhrg62619.pdf', 'jacket ID'),
    ('CHRG-118shrg049104057.pdf', 'jacket ID'),
])
def test_documented_number_roles_preserve_source_digits(engine, name, role):
    result = checked(engine, name)
    number, = fields(result, 'publication_number')
    assert role in number['note']
    assert not number['candidates'] and number['code'] is None
    if '049104057' in name:
        assert number['raw'] == '049104057'
    if name.startswith('CRPT'):
        assert all(m['record']['documentType'] == 'report' for m in result['matches'])
        assert not any('conference' == v for m in result['matches'] for v in m['record'].values())


@pytest.mark.parametrize('suffix,marker,number', [
    ('-ERRATA', 'ERRATA', None), ('-ERRATA2', 'ERRATA', '2'),
    ('-err', 'err', None), ('-err2', 'err', '2'),
    ('-addendum3', 'addendum', '3'), ('-add1', 'add', '1'),
    ('-volumeIII', 'volume', 'III'), ('-vol3', 'vol', '3'),
    ('-v3', 'v', '3'), ('-p2', 'p', '2'),
])
def test_full_publication_suffix_words_and_aliases(engine, suffix, marker, number):
    result = checked(engine, 'CRPT-105srpt36' + suffix + '.pdf')
    matches = [m for m in result['observations'] if m['rule'] == 'publication-suffix-marker']
    match, = matches
    data = {f['name']: f['raw'] for f in match['fields']}
    assert data['publication_marker'] == marker
    assert data.get('publication_identifier') == number
    assert fields(result, 'suffix')[0]['raw'] == suffix


@pytest.mark.parametrize('suffix,field', [
    ('-ERRATA12345', 'publication_identifier'),
    ('-err111111', 'publication_identifier'),
    ('-volume20250318', 'publication_identifier'),
    ('-pt12345', 'part_number'),
])
def test_suffix_numbers_are_not_dates(engine, suffix, field):
    result = checked(engine, 'CHRG-119shrg12345' + suffix + '.pdf')
    assert fields(result, field)
    assert not fields(result, 'short_date_token') and not fields(result, 'date_token')


def test_documented_combined_and_repeated_suffixes_remain_visible(engine):
    result = checked(engine, 'CRPT-105srpt36-vol3-pt2-ERRATA2.pdf')
    assert result['matches'][0]['record']['volume'] == '3'
    assert result['matches'][0]['record']['part'] == '2'
    assert result['matches'][0]['record']['errata'] == '2'
    assert [f['raw'] for f in fields(result, 'publication_marker')] == ['vol', 'ERRATA']
    assert fields(result, 'part_number')[0]['raw'] == '2'
    repeat = checked(engine, 'CRPT-105srpt36-ERRATA-ERRATA2.pdf')
    assert len(fields(repeat, 'publication_marker')) == 2
    assert 'errata' not in repeat['matches'][0]['record']


def test_hearing_err_marker_retains_documented_ambiguity(engine):
    result = checked(engine, 'CHRG-107shrg83924-err.pdf')
    marker, = fields(result, 'publication_marker')
    assert 'addenda and errata' in marker['note']
    assert marker['vocabulary_url'] == 'https://www.govinfo.gov/help/chrg'
    assert result['matches'][0]['record']['publicationSuffix'] == '-err'
    assert 'errata' not in result['matches'][0]['record']
    assert 'addendum' not in result['matches'][0]['record']


@pytest.mark.parametrize('name', ['S. Prt. 114-27.pdf', 'S.Prt.112-35.pdf', 'S-Prt-119-12345.pdf'])
def test_senate_print_citations_are_distinct_from_package_numbers(engine, name):
    result = checked(engine, name)
    marker, = fields(result, 'citation_marker')
    assert marker['code'] == 'sprt' and marker['label'] == 'Senate print citation'
    number, = fields(result, 'citation_number')
    assert 'print' in number['note'] and 'jacket' in number['note']
    assert marker['vocabulary_url'] == 'https://www.govinfo.gov/help/cprt'
    assert not fields(result, 'publication_number')
    assert not fields(result, 'date_token') and not fields(result, 'short_date_token')


@pytest.mark.parametrize('name', [
    'S.Prt.119.pdf', 'XS.Prt.119-12.pdf', 'S.Prt.1119-12.pdf',
    'S.Prt.119-12abc.pdf', 'CPRT-119SPRT12345.pdf',
    'HHRG-119-IF00-Wstate-SPrt119-12-20250318.pdf',
])
def test_partial_citations_and_structured_identifiers_do_not_become_print_citations(engine, name):
    assert not fields(checked(engine, name), 'citation_marker')


@pytest.mark.parametrize('name', [
    'CPRT-119ERPT12345.pdf', 'CRPT-119WPRT12345.pdf', 'CHRG-119SPRT12345.pdf',
    'CPRT-1119WPRT12345.pdf', 'CRPT-119ERPT.pdf',
])
def test_cross_family_codes_and_incomplete_packages_do_not_gain_publication_fields(engine, name):
    assert not fields(checked(engine, name), 'publication_number')


def test_new_govinfo_print_type_does_not_expand_the_separate_house_routing_layout(engine):
    assert not engine.parse('CPRT-119-WPRT-AG00-HR1.pdf')['valid']


@pytest.mark.parametrize('name', [
    'CRPT-119srpt12345-error.pdf', 'CHRG-119shrg12345-addendumreader.pdf',
    'CRPT-119hrpt12345-volcano.pdf', 'ERRATA2.pdf',
])
def test_suffix_word_boundaries_and_container_scope(engine, name):
    assert not fields(checked(engine, name), 'publication_marker')
