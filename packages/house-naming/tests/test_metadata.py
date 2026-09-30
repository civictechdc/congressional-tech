"""Source/corpus examples, intentional migrations and misleading-token controls."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from house_naming import Engine, NamingError, check_catalog
from house_naming.compiler import filename_schema, records_schema


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,expected', [
    ('CRPT-112hrpt332.pdf', dict(kind='published-report', congress=112,
        publicationType='hrpt', reportNumber=332, publicationSuffix='', documentType='report', extension='pdf')),
    ('CRPT-112hrpt592-pt1.pdf', dict(kind='published-report', congress=112,
        publicationType='hrpt', reportNumber=592, publicationSuffix='-pt1', part='1', documentType='report', extension='pdf')),
    ('CHRG-107shrg87708-volII.pdf', dict(kind='published-hearing', congress=107,
        publicationType='shrg', publicationNumber='87708', publicationSuffix='-volII', volume='II', extension='pdf')),
    ('CHRG-106shrg98240-pt1-err.pdf', dict(kind='published-hearing', congress=106,
        publicationType='shrg', publicationNumber='98240', publicationSuffix='-pt1-err', part='1', errata='', extension='pdf')),
    ('BILLS-113HR-FC-AP-FY2014-AP00-Agriculture.pdf', dict(kind='appropriation-described', congress=113,
        measureType='HR', stage='FC', description='AP-FY2014-AP00-Agriculture', fiscalYear='2014',
        committeeCode='AP00', subject='Agriculture', extension='pdf')),
    ('BILLS-115HR-SC-AP-FY2018-CJS-CommerceJusticeScience.pdf', dict(kind='appropriation-described', congress=115,
        measureType='HR', stage='SC', description='AP-FY2018-CJS-CommerceJusticeScience', fiscalYear='2018',
        subject='CJS', descriptionRemainder='CommerceJusticeScience', extension='pdf')),
    ('BILLS-113-HR-FC-AP-FY2014-AP00-Amdt-001.pdf', dict(kind='appropriation-described', congress=113,
        measureType='HR', stage='FC', description='AP-FY2014-AP00-Amdt-001', fiscalYear='2014',
        committeeCode='AP00', subject='Amdt-001', extension='pdf')),
    ('BILLS-112-CommitteePrint-D000096-Amdt-10.pdf', dict(kind='committee-amendment-described', congress=112,
        subject='CommitteePrint', sponsorBioguideId='D000096', amendmentId='10', extension='pdf')),
    ('BILLS-114-CP-L000559-Amdt-1-Enbloc-1.pdf', dict(kind='committee-enbloc-described', congress=114,
        subject='CP', sponsorBioguideId='L000559', amendmentId='1', enblocId='1', extension='pdf')),
    ('BILLS-119-5300-A000370-Amdt-119.pdf', dict(kind='committee-amendment-described', congress=119,
        subject='5300', sponsorBioguideId='A000370', amendmentId='119', extension='pdf')),
    ('BILLS-113-HR2879ih.pdf', dict(kind='bill-numbered', congress=113, measureType='hr', measureNumber=2879,
        stage='ih', versionSuffix='', extension='pdf')),
    ('BILLS-115hr1892eas2.pdf', dict(kind='bill-numbered', congress=115, measureType='hr', measureNumber=1892,
        stage='eas', versionSuffix='2', stageOccurrence='2', extension='pdf')),
    ('BILLS-113-HR4660ih(asfiled).pdf', dict(kind='bill-numbered', congress=113, measureType='hr', measureNumber=4660,
        stage='ih', versionSuffix='(asfiled)', annotation='asfiled', extension='pdf')),
    ('CPRT-113-HPRT-RU00-HR1105.pdf', dict(kind='committee-print', congress=113, publicationType='hprt',
        committeeCode='RU00', subject='HR1105', measureType='hr', measureNumber=1105, extension='pdf')),
    ('CPRT-115HPRT24746.pdf', dict(kind='published-print', congress=115, publicationType='hprt',
        publicationNumber='24746', publicationSuffix='', extension='pdf')),
    ('CRPT-114-JU00-Vote1-10-20160525.pdf', dict(kind='committee-vote', congress=114, committeeCode='JU00',
        voteId='1-10', voteDate='20160525', extension='pdf')),
    ('CRPT-117-II00-VoteMotion-20210902-U3.pdf', dict(kind='committee-vote', congress=117, committeeCode='II00',
        voteId='Motion', voteDate='20210902', revision=3, extension='pdf')),
    ('HHRG-113-AP02-Wstate-B001279-20140404.pdf', dict(kind='witness-statement', congress=113, meetingType='HHRG',
        committeeCode='AP02', witnessId='B001279', witnessIdType='bioguide', meetingDate='20140404', extension='pdf')),
])
def test_reviewed_metadata(engine, name, expected):
    result = engine.parse(name)
    assert result['input'] == name and result['valid'] and not result['ambiguous']
    assert result['matches'][0]['record'] == expected
    assert engine.validate(expected) == expected
    assert expected in [m['record'] for m in engine.parse(engine.render(expected))['matches']]
    Draft202012Validator(records_schema(engine.guide)).validate(expected)
    Draft202012Validator(filename_schema(engine.guide)).validate(name)


def test_guide_conference_convention_survives(engine):
    rule = engine.guide['patterns']['conference-numbered']
    assert rule['title'] == 'Conference Reports with Report Numbers'
    assert {'source_id': 'section-19', 'page': 12} in rule['sources']
    assert engine.render(dict(kind='conference-numbered', congress=112, reportNumber=332, extension='pdf')) == 'CRPT-112hrpt332.pdf'
    match = engine.parse('CRPT-112hrpt332.pdf')['matches'][0]
    assert set(match['matched_conventions']) == {'conference-numbered', 'published-report'}
    assert match['record']['documentType'] == 'report'
    assert 'conference' not in match['record'].values()


@pytest.mark.parametrize('kind', ['appropriation-annual', 'appropriation-supplemental',
                                 'continuing-resolution-reported', 'continuing-resolution-committee'])
@pytest.mark.parametrize('year', ['13', '2014'])
def test_fiscal_year_conventions_share_a_record(engine, kind, year):
    from test_runtime import CASES
    record = deepcopy(next(c['input'] for c in CASES if c['input']['kind'] == kind))
    record['fiscalYear'] = year
    result = engine.parse(engine.render(record))
    assert result['valid'] and not result['ambiguous']
    assert result['matches'][0]['record']['fiscalYear'] == year
    assert result['matches'][0]['record']['kind'] == 'appropriation-described'
    assert kind in result['matches'][0]['matched_conventions']


@pytest.mark.parametrize('prefix', ['CHRG-118shrg049104057', 'CRPT-112hrpt466', 'CPRT-115hprt24746'])
@pytest.mark.parametrize('extension', ['htm', 'HTML'])
def test_html_publication_variants(engine, prefix, extension):
    name = f'{prefix}.{extension}'
    result = engine.parse(name)
    assert result['valid'] and not result['ambiguous']
    assert result['matches'][0]['record']['extension'] == extension.lower()
    Draft202012Validator(filename_schema(engine.guide)).validate(name)


@pytest.mark.parametrize('name,absent', [
    ('BILLS-112-HR3116-S000030-Amdt-1AAA.pdf', ['witnessIdType']),
    ('BILLS-113-HR1281-U000031-Amdt-1.pdf', ['revision']),
    ('HHRG-115-IF16-MState-M001180-20171130-U849615.pdf', ['witnessIdType']),
    ('CHRG-108shrg39104100.pdf', ['meetingDate', 'voteDate']),
    ('HHRG-114-FA16-Wstate-_S-20160511.pdf', ['measureType', 'measureNumber', 'witnessIdType']),
    ('BILLS-115HR-SC-AP--StateForOp-FY2018StateForeignOperationsAppropriations.pdf', ['fiscalYear']),
])
def test_slot_boundaries(engine, name, absent):
    result = engine.parse(name)
    assert result['valid'] and not result['ambiguous']
    record = result['matches'][0]['record']
    assert all(key not in record for key in absent)
    if 'S000030' in name:
        assert record['measureType'] == 'HR' and record['measureNumber'] == 3116
        assert record['sponsorBioguideId'] == 'S000030'
    if 'U849615' in name:
        assert record['memberBioguideId'] == 'M001180' and record['revision'] == 849615


def test_conflicting_derived_values_are_rejected(engine):
    record = engine.parse('CHRG-107shrg87708-volII.pdf')['matches'][0]['record']
    with pytest.raises(NamingError, match='volume disagrees'):
        engine.render({**record, 'volume': '2'})
    with pytest.raises(NamingError, match='part disagrees'):
        engine.render({**record, 'part': '1'})
    witness = engine.parse('HHRG-113-AG00-WState-ColbyJ-20130314.pdf')['matches'][0]['record']
    with pytest.raises(NamingError, match='witnessIdType disagrees'):
        engine.render({**witness, 'witnessIdType': 'bioguide'})


def test_constructed_suffix_controls(engine):
    # Constructed controls, not corpus observations.
    record = engine.parse('CHRG-112hhrg123-volII-pt3-err2.pdf')['matches'][0]['record']
    assert (record['volume'], record['part'], record['errata']) == ('II', '3', '2')
    repeated = engine.parse('CHRG-112hhrg123-pt1-pt2.pdf')['matches'][0]['record']
    assert repeated['publicationSuffix'] == '-pt1-pt2' and 'part' not in repeated
    unknown = engine.parse('CHRG-112hhrg123-appendix.pdf')['matches'][0]['record']
    assert unknown['publicationSuffix'] == '-appendix' and 'part' not in unknown


@pytest.mark.parametrize('name', [
    'HHRG-113-AG00-WState-ColbyJ-20130314.html',
    'BILLS-113-HR3116-000030-Amdt-1.pdf',
    'BILLS-113-CommitteePrint-S000030-Amdt-.pdf',
    'BILLS-113HR-FC-AP-FY201-Agriculture.pdf.bak',
    'CRPT-114-JU00-Vote1-10-20160230.pdf',
])
def test_rejects_missing_structure_and_invalid_dates(engine, name):
    assert not engine.parse(name)['valid']


@pytest.mark.parametrize('mutation', [
    lambda g: g['patterns']['conference-numbered'].__setitem__('parse_as', 'absent'),
    lambda g: g['patterns']['conference-numbered'].__setitem__('parse_as', 'conference-numbered'),
    lambda g: g['patterns']['published-report'].__setitem__('derived_fields', ['congress']),
    lambda g: g['patterns']['published-report'].__setitem__('derived_fields', ['absent']),
])
def test_catalog_checks_new_metadata_settings(engine, mutation):
    guide = engine.guide
    mutation(guide)
    with pytest.raises(NamingError):
        check_catalog(guide)
