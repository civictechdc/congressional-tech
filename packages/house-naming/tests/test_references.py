"""Observed embedded references and incomplete layouts, with adversarial controls."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from house_naming import Engine, NamingError
from house_naming.compiler import records_schema


@pytest.fixture(scope='module')
def engine():
    return Engine()


def parsed(engine, name):
    result = engine.parse(name)
    assert result['valid'] and not result['ambiguous'], result
    record = result['matches'][0]['record']
    assert record in [m['record'] for m in engine.parse(engine.render(record))['matches']]
    return record


@pytest.mark.parametrize('name,field,raw,expected', [
    ('BILLS-116HR3401EAS-RCP116-21.pdf', 'versionSuffix', 'RCP116-21',
     {'type':'rules-committee-print','congress':116,'number':'21'}),
    ('BILLS-117-SConRes14ReconciliationDirectives-A000370-Amdt-4.pdf', 'subject', 'SConRes14',
     {'type':'measure','measureType':'sconres','measureNumber':14}),
    ('BILLS-115-HR1181rev1-E000293-Amdt-1.pdf', 'subject', 'HR1181',
     {'type':'measure','measureType':'hr','measureNumber':1181}),
    ('BILLS-116-HR0034-J000126-Amdt-1.pdf', 'subject', 'HR0034',
     {'type':'measure','measureType':'hr','measureNumber':34}),
    ('BILLS-116-HR_5315-B001281-Amdt-9-U2.pdf', 'subject', 'HR_5315',
     {'type':'measure','measureType':'hr','measureNumber':5315}),
    ('CPRT-113-HPRT-RU00-HR1900a.xml', 'subject', 'HR1900',
     {'type':'measure','measureType':'hr','measureNumber':1900}),
    ('CRPT-116-ED00-Vote10-hr865-20190226.pdf', 'voteId', 'hr865',
     {'type':'measure','measureType':'hr','measureNumber':865}),
    ('BILLS-118-HR7159-F000471-Amdt-HR7156.pdf', 'amendmentId', 'HR7156',
     {'type':'measure','measureType':'hr','measureNumber':7156}),
    ('BILLS-114-FY16BVE-B001281-Amdt-006.pdf', 'subject', 'FY16',
     {'type':'fiscal-year','year':'16'}),
    ('BILLS-115HR-SC-AP--StateForOp-FY2018StateForeignOperationsAppropriations.pdf',
     'descriptionRemainder', 'FY2018', {'type':'fiscal-year','year':'2018'}),
    ('BILLS-119pih-HR3360.pdf', 'description', 'HR3360',
     {'type':'measure','measureType':'hr','measureNumber':3360}),
])
def test_observed_references(engine, name, field, raw, expected):
    record = parsed(engine, name)
    start = record[field].index(raw)
    assert record['references'] == [{**expected,'raw':raw,'sourceField':field,'start':start,'end':start+len(raw)}]
    Draft202012Validator(records_schema(engine.guide)).validate(record)
    if name.startswith('BILLS-118-HR7159'):
        assert (record['measureType'],record['measureNumber'],record['amendmentId']) == ('HR',7159,'HR7156')
    if raw == 'FY2018':
        assert 'fiscalYear' not in record


@pytest.mark.parametrize('name', [
    'BILLS-112-HR3116-S000030-Amdt-1AAA.pdf',
    'BILLS-113-HR1281-U000031-Amdt-1.pdf',
    'HHRG-114-FA16-Wstate-_S-20160511.pdf',
    'CHRG-108shrg39104100.pdf',
    'BILLS-115HR5759ih-HR575921stCentAct.pdf',
    # Constructed counterexamples: same source boundaries, hostile lookalikes.
    'BILLS-115HR5759ih-HR575921STCENTACT.pdf',
    'BILLS-119pih-S000030.pdf',
    'BILLS-119pih-FY123.pdf',
    'BILLS-119pih-HR0.pdf',
    'BILLS-119pih-HR2147483648.pdf',
    'BILLS-119pih-HR123unknown.pdf',
    'BILLS-119pih-XHR123.pdf',
    'BILLS-119pih-RCP116-21x.pdf',
    'CPRT-113-HPRT-RU00-HR1105.pdf',  # Already a complete primary measure.
])
def test_no_cross_slot_or_unbounded_search(engine, name):
    assert 'references' not in parsed(engine, name)


def test_repeated_references_have_exact_independent_locations(engine):
    # Constructed, including a Unicode prefix: offsets count characters, not bytes.
    record = parsed(engine, 'BILLS-119pih-É-HR123-HR123.pdf')
    assert [r['start'] for r in record['references']] == [2,8]
    assert [r['raw'] for r in record['references']] == ['HR123','HR123']
    for ref in record['references']:
        assert record[ref['sourceField']][ref['start']:ref['end']] == ref['raw']
    original = deepcopy(record)
    normalized = engine.validate(record)
    normalized['references'][0]['raw'] = 'changed'
    assert record == original


@pytest.mark.parametrize('key,value', [
    ('measureNumber',124),('measureType','s'),('raw','HR124'),('sourceField','amendmentId'),
    ('start',1),('end',4),('extra','invented'),
])
def test_conflicting_references_rejected(engine, key, value):
    record = parsed(engine, 'BILLS-119pih-HR123.pdf')
    record['references'][0][key] = value
    with pytest.raises(NamingError):
        engine.validate(record)


@pytest.mark.parametrize('value', [None,{},[],['bad'],[None],[{'raw':[]}],[{'raw':{}}],
                                  [{'measureNumber':float('nan')}],[{}]*65])
def test_reference_shape_and_resource_bounds(engine, value):
    record = parsed(engine, 'BILLS-119pih-HR123.pdf')
    record['references'] = value
    with pytest.raises(NamingError):
        engine.validate(record)


def test_cannot_add_or_omit_references(engine):
    record = parsed(engine, 'BILLS-119pih-HR123.pdf')
    reference = record['references'][0]
    with pytest.raises(NamingError, match='references disagrees'):
        engine.validate({**record, 'references':[reference,reference]})
    without = {k:v for k,v in record.items() if k!='references'}
    assert engine.validate(without) == record
    no_reference = parsed(engine, 'BILLS-119pih-Something.pdf')
    with pytest.raises(NamingError, match='references disagrees'):
        engine.validate({**no_reference,'references':[reference]})


@pytest.mark.parametrize('name,expected,absent', [
    ('BILLS-1131129ih.pdf', {'kind':'bill-untyped-numbered','congress':113,'numberToken':'1129','stage':'ih'}, ['measureType','measureNumber']),
    ('BILLS-1130000ih.pdf', {'congress':113,'numberToken':'0000'}, ['measureType','measureNumber']),
    ('BILLS-1134565pih-StartupCapitalModernization.pdf', {'kind':'bill-untyped-numbered','congress':113,'numberToken':'4565','stage':'pih'}, ['measureType','measureNumber']),
    ('BILLS-11702pih-HResXXX.pdf', {'kind':'bill-untyped-numbered','congress':117,'numberToken':'02','stage':'pih'}, ['measureType','measureNumber']),
    ('BILLS-113pih-BACPACAct.pdf', {'kind':'bill-untyped-draft','stage':'pih','description':'BACPACAct'}, ['measureType','measureNumber']),
    ('BILLS-113-FC-AP-FY2014-AP00-TransHUD.pdf', {'kind':'appropriation-routed','stage':'FC','fiscalYear':'2014','committeeCode':'AP00','subject':'TransHUD'}, ['measureType']),
    ('BILLS-114-HR--AP-FY2016-AP00-Amdt-1.pdf', {'measureType':'hr','fiscalYear':'2016','subject':'Amdt-1'}, ['stage']),
    ('BILLS-116--AP--AP00-FY2020EW_Bill.pdf', {'subject':'FY2020EW_Bill','committeeCode':'AP00'}, ['stage','measureType','fiscalYear']),
    ('BILLS-113-20-FC-AP-FY2014-AP00-Amdt-20.pdf', {'stage':'FC','subject':'Amdt-20'}, ['measureType','measureNumber','sponsorBioguideId']),
    ('BILLS-116-Fortenberry_1--AP--AP00-Amdt-2.pdf', {'subject':'Amdt-2'}, ['measureType','stage','sponsorBioguideId']),
    ('BILLS-115-HR6470-FC-AP-FY2019-AP00-Amdt-1.pdf', {'measureType':'hr','measureNumber':6470,'stage':'FC','fiscalYear':'2019','subject':'Amdt-1'}, ['sponsorBioguideId']),
])
def test_observed_incomplete_layouts(engine,name,expected,absent):
    record = parsed(engine,name)
    assert all(record[k] == v for k,v in expected.items())
    assert all(k not in record for k in absent)
    if record['kind']=='appropriation-routed':
        assert record['routing'] == name.removeprefix(f"BILLS-{record['congress']}-").removesuffix('.pdf')


@pytest.mark.parametrize('name', [
    'BILLS-113ih.pdf', 'BILLS-01131129ih.pdf', 'BILLS-113pih-.pdf',
    'BILLS-113-BOGUS-AP-FY2014-X.pdf', 'BILLS-113-HR-FC-AP-FY2014-AP00-Agriculture.pdf',
])
def test_incomplete_rules_do_not_absorb_complete_or_unknown_layouts(engine,name):
    result=engine.parse(name)
    assert all(m['kind'] not in {'bill-untyped-numbered','bill-untyped-draft','appropriation-routed'} for m in result['matches'])


def test_reference_vocabulary_and_stage_linkage(engine):
    from house_naming import check_catalog
    guide = engine.guide
    guide['field_types']['references']['items']['oneOf'][0]['properties']['measureType']['enum'].append('invented')
    with pytest.raises(NamingError, match='Reference field measureType disagrees'):
        check_catalog(guide)
    guide = engine.guide
    guide['field_types']['untypedLegislativeStage']['enum'].remove('pih')
    with pytest.raises(NamingError, match='Untyped stage values'):
        check_catalog(guide)
