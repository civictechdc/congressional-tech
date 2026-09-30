"""Real corpus spellings plus negative controls for the additional layouts."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from house_naming import Engine, NamingError, check_catalog
from house_naming.compiler import filename_schema, records_schema


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,expected', [
    ('HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf',
     {'kind':'witness-statement','congress':113,'committeeCode':'AG00','witnessId':'ColbyJ','meetingDate':'20130314','meetingType':'HHRG','extension':'pdf'}),
    ('BILLS-112-HR3116-C001063-Amdt-1DD.PDF',
     {'kind':'committee-amendment','congress':112,'measureType':'HR','measureNumber':3116,'sponsorBioguideId':'C001063','amendmentId':'1DD','extension':'pdf'}),
    ('HHRG-112-HM00-20110310-SD001.pdf',
     {'kind':'committee-document-numbered','meetingType':'HHRG','congress':112,'committeeCode':'HM00','meetingDate':'20110310','documentType':'SD','documentNumber':'001','extension':'pdf'}),
    ('HMKP-119-II00-20251120-QFR001.pdf',
     {'kind':'committee-document-numbered','meetingType':'HMKP','congress':119,'committeeCode':'II00','meetingDate':'20251120','documentType':'QFR','documentNumber':'001','extension':'pdf'}),
    ('HHRG-114-IF02-20160224-MbrRoster.pdf',
     {'kind':'committee-document','meetingType':'HHRG','congress':114,'committeeCode':'IF02','meetingDate':'20160224','documentType':'MbrRoster','extension':'pdf'}),
    ('HHRG-114-HA00-20160517-CPg.pdf',
     {'kind':'committee-document','meetingType':'HHRG','congress':114,'committeeCode':'HA00','meetingDate':'20160517','documentType':'CPg','extension':'pdf'}),
    ('HHRG-115-SM27-20180614-TOC.pdf',
     {'kind':'committee-document','meetingType':'HHRG','congress':115,'committeeCode':'SM27','meetingDate':'20180614','documentType':'TOC','extension':'pdf'}),
    ('CRPT-113-AP00-Vote001-20130521.pdf',
     {'kind':'committee-vote','congress':113,'committeeCode':'AP00','voteId':'001','voteDate':'20130521','extension':'pdf'}),
    ('HMTG-113-AP06-Wstate-BrewerB-20130424.pdf',
     {'kind':'witness-statement','meetingType':'HMTG','congress':113,'committeeCode':'AP06','witnessId':'BrewerB','meetingDate':'20130424','extension':'pdf'}),
    ('HMKP-115-AG14-Wstate-BlackL-20170309-SD001.pdf',
     {'kind':'witness-support','meetingType':'HMKP','congress':115,'committeeCode':'AG14','witnessId':'BlackL','meetingDate':'20170309','supportId':'001','extension':'pdf'}),
    ('HMKP-115-AG14-Bio-BlackL-20170309.pdf',
     {'kind':'witness-biography','meetingType':'HMKP','congress':115,'committeeCode':'AG14','witnessId':'BlackL','meetingDate':'20170309','extension':'pdf'}),
    ('HMKP-115-ED02-TTF-BowmanT-20180426.pdf',
     {'kind':'testimony-disclosure','meetingType':'HMKP','congress':115,'committeeCode':'ED02','witnessId':'BowmanT','meetingDate':'20180426','extension':'pdf'}),
    ('HMTG-114-HM11-WList-20160509.pdf',
     {'kind':'witness-list','meetingType':'HMTG','congress':114,'committeeCode':'HM11','meetingDate':'20160509','extension':'pdf'}),
    ('HMKP-113-FA00-Transcript-20130724.pdf',
     {'kind':'committee-transcript','meetingType':'HMKP','congress':113,'committeeCode':'FA00','meetingDate':'20130724','extension':'pdf'}),
    ('CHRG-106hhrg53880.pdf',
     {'kind':'published-hearing','congress':106,'publicationType':'hhrg','publicationNumber':'53880','publicationSuffix':'','extension':'pdf'}),
    ('CHRG-106shrg98240-pt1-err.pdf',
     {'kind':'published-hearing','congress':106,'publicationType':'shrg','publicationNumber':'98240','publicationSuffix':'-pt1-err','part':'1','errata':'','extension':'pdf'}),
    ('CHRG-107shrg87708-volII.pdf',
     {'kind':'published-hearing','congress':107,'publicationType':'shrg','publicationNumber':'87708','publicationSuffix':'-volII','volume':'II','extension':'pdf'}),
    ('CHRG-114shrg52542-add1.pdf',
     {'kind':'published-hearing','congress':114,'publicationType':'shrg','publicationNumber':'52542','publicationSuffix':'-add1','addendum':'1','extension':'pdf'}),
    ('CHRG-118shrg049104057.pdf',
     {'kind':'published-hearing','congress':118,'publicationType':'shrg','publicationNumber':'049104057','publicationSuffix':'','extension':'pdf'}),
])
def test_actual_corpus_metadata(engine, name, expected):
    result = engine.parse(name)
    assert result['input'] == name and result['valid'] and not result['ambiguous']
    assert result['matches'][0]['record'] == expected
    canonical = result['matches'][0]['canonical_filename']
    assert engine.render(expected) == canonical
    assert expected in [m['record'] for m in engine.parse(canonical)['matches']]
    Draft202012Validator(records_schema(engine.guide)).validate(expected)
    Draft202012Validator(filename_schema(engine.guide)).validate(name)


def test_case_preserves_free_text_and_source(engine):
    name = 'hhrg-113-ag00-wstate-O’Brien-ÉlodieA-20130314-u2.PDF'
    r = engine.parse(name)
    assert r['input'] == name
    record = r['matches'][0]['record']
    assert record['witnessId'] == 'O’Brien-ÉlodieA'
    assert record['committeeCode'] == 'AG00' and record['revision'] == 2
    assert r['matches'][0]['canonical_filename'] == 'HHRG-113-AG00-WState-O’Brien-ÉlodieA-20130314-U2.pdf'


def test_old_witness_records_keep_rendering_without_collection(engine):
    old = {'kind':'witness-statement','congress':113,'committeeCode':'AG00','witnessId':'ColbyJ','meetingDate':'20130314','extension':'pdf'}
    before = deepcopy(old)
    assert engine.render(old) == 'HHRG-113-AG00-WState-ColbyJ-20130314.pdf'
    assert engine.validate(old) == {**old, 'meetingType':'HHRG'}
    assert old == before


@pytest.mark.parametrize('name', [
    'HHRG-113-AG00-20130230-SD001.pdf',
    'HHRG-113-AG00-20131301-SD001.pdf',
    'HHRG-113-AG00-20130314-SD.pdf',
    'HHRG-113-AG00-20130314-QFRWords.pdf',
    'HHRG-113-AG00-20130314-Unknown001.pdf',
    'HHRG-113-AG00-20130314-TOCextra.pdf',
    'CRPT-113-AP00-Vote001-20130230.pdf',
    'CRPT-113-AP00-VoteMotion-20130230.pdf',
    'HHRG-113-AG00-MState--20130314.pdf',
    'XYZ-113-AG00-Wstate-ColbyJ-20130314.pdf',
    'BILLS-113pih-.pdf',
    'BILLS-115-HR146-B001250-Amdt-__.pdf',
    'BİLLS-113hr1ih.pdf',
    'CHRG-106hhrg53880.pdf.bak',
    'HHRG-113-AG00-Wstate-ColbyJ-20130314.html',
    'CHRG-106hhrg53880junk.pdf',
    'CHRG-106hhrg53880-../x.pdf',
])
def test_does_not_invent_fields_or_repair_arbitrary_text(engine, name):
    assert not engine.parse(name)['valid']


@pytest.mark.parametrize('kind,field', [('bill-preintroduced','description'),('witness-statement','witnessId'),('published-hearing','publicationSuffix')])
def test_lowercase_revision_cannot_hide_inside_free_field(engine, kind, field):
    from test_runtime import CASES
    record = next(c['input'] for c in CASES if c['input']['kind'] == kind)
    with pytest.raises(NamingError):
        engine.render({**record, field:'part-u1'})


def test_new_shapes_are_not_fabricated_guide_examples(engine):
    guide = engine.guide
    assert len(guide['examples']) == 160
    for kind in ('committee-document-numbered','committee-document','committee-transcript','published-hearing'):
        rule = guide['patterns'][kind]
        assert not rule['sources'] and not rule['source_example_ids']
        assert rule['observed_examples']
        for name in rule['observed_examples']:
            result = engine.parse(name)
            assert result['valid'] and not result['found_in_source']
    missing = deepcopy(guide)
    missing['patterns']['published-hearing'].pop('observed_examples')
    with pytest.raises(NamingError):
        check_catalog(missing)


def test_alternative_templates_and_defaults_are_checked(engine):
    guide = engine.guide
    guide['patterns']['committee-vote']['parse_templates'] = ['CRPT-{congress}-{absent}']
    with pytest.raises(NamingError):
        check_catalog(guide)
    guide = engine.guide
    guide['field_types']['witnessMeetingType']['default'] = 'XYZ'
    with pytest.raises(NamingError):
        check_catalog(guide)
