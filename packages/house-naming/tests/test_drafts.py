"""Observed corpus examples, plus deliberately invalid or ambiguous controls."""
from copy import deepcopy

import pytest

from house_naming import Engine, NamingError, check_catalog


@pytest.fixture(scope='module')
def engine():
    return Engine()


def one(engine, name):
    result = engine.parse(name)
    assert result['valid'] and not result['ambiguous'], result
    match = result['matches'][0]
    assert match['record'] in [m['record'] for m in engine.parse(match['canonical_filename'])['matches']]
    return match['record']


@pytest.mark.parametrize('name,fields,absent', [
    ('BILLS-113HR____ih.pdf', {'kind': 'bill-unnumbered', 'congress': 113, 'measureType': 'hr', 'numberPlaceholder': '____', 'stage': 'ih'}, ['measureNumber']),
    ('BILLS-118HRih-U12.PDF', {'kind': 'bill-unnumbered', 'measureType': 'hr', 'numberPlaceholder': '', 'revision': 12}, ['measureNumber']),
    ('BILLS-118pih.pdf', {'kind': 'bill-unnumbered', 'measureToken': '', 'stage': 'pih'}, ['measureNumber', 'measureType']),
    ('BILLS-113-IH-HRtaxex.pdf', {'kind': 'bill-unnumbered', 'stage': 'ih', 'versionSuffix': '-HRtaxex'}, ['measureNumber', 'measureType']),
    ('BILLS-119-pih-ThisActmaybecitedastheBankLoanPrivacyAct.pdf', {'kind': 'bill-unnumbered', 'stage': 'pih', 'versionSuffix': '-ThisActmaybecitedastheBankLoanPrivacyAct'}, ['measureNumber', 'measureType']),
    ('BILLS-112CommRes1pih-CommitteeHiringResolution.pdf', {'kind': 'bill-named-draft', 'draftLabel': 'CommRes', 'draftIdentifier': '1', 'stage': 'pih'}, ['measureNumber']),
    ('BILLS-114DiscussionDraftih-U1.pdf', {'kind': 'bill-named-draft', 'draftLabel': 'DiscussionDraft', 'draftIdentifier': '', 'revision': 1}, ['measureNumber']),
    ('BILLS-115HR1329asamendedih.pdf', {'kind': 'bill-numbered-described', 'numberedSubject': 'HR1329', 'description': 'asamended', 'measureType': 'hr', 'measureNumber': 1329}, []),
    ('BILLS-1183744ANSih.pdf', {'kind': 'bill-numbered-described', 'numberedSubject': '3744', 'description': 'ANS'}, ['measureNumber', 'measureType']),
    ('BILLS-115HR0625ih.pdf', {'kind': 'bill-numbered-described', 'numberedSubject': 'HR0625', 'description': '', 'measureNumber': 625}, []),
    ('BILLS-115draftbillih.pdf', {'kind': 'bill-titled-draft', 'description': 'draftbill', 'stage': 'ih'}, ['measureNumber', 'measureType']),
    ('BILLS-116Interiorih.pdf', {'kind': 'bill-titled-draft', 'description': 'Interior', 'stage': 'ih'}, []),
    ('BILLS-1165245-HAmdt2.pdf', {'kind': 'bill-house-amendment', 'subject': '5245', 'amendmentSuffix': '2'}, ['measureNumber', 'measureType']),
    ('BILLS-1162227-HAmdt.pdf', {'kind': 'bill-house-amendment', 'subject': '2227', 'amendmentSuffix': ''}, ['measureNumber', 'measureType']),
    # Constructed leading-zero and typed-subject controls.
    ('BILLS-119HR123-HAmdt002.pdf', {'kind': 'bill-house-amendment', 'subject': 'HR123', 'amendmentSuffix': '002', 'measureNumber': 123}, []),
])
def test_exact_observed_metadata(engine, name, fields, absent):
    record = one(engine, name)
    assert all(record.get(key) == value for key, value in fields.items()), record
    assert not any(key in record for key in absent), record


def test_measure_list_preserves_each_occurrence_and_its_position(engine):
    record = one(engine, 'BILLS-115HR3798HR1150HR6718HR4616-RCP115-84.pdf')
    assert record['kind'] == 'bill-measure-list'
    assert 'measureType' not in record and 'measureNumber' not in record
    refs = record['references']
    assert [r['measureNumber'] for r in refs if r['type'] == 'measure'] == [3798, 1150, 6718, 4616]
    assert refs[-1]['type'] == 'rules-committee-print'
    assert refs[-1]['number'] == '84'
    for ref in refs:
        assert record[ref['sourceField']][ref['start']:ref['end']] == ref['raw']
    repeated = one(engine, 'BILLS-115SAHR123HR123-RCP115-01.pdf')
    assert repeated['referencePrefix'] == 'SA' and 'stage' not in repeated
    assert [(r['start'], r['end']) for r in repeated['references'][:2]] == [(0, 5), (5, 10)]
    wrong = deepcopy(record)
    wrong['references'][0]['measureNumber'] += 1
    with pytest.raises(NamingError, match='disagrees'):
        engine.validate(wrong)


def test_numbered_pih_is_a_house_marker(engine):
    record = one(engine, 'BILLS-114HR2200pih-CBRNIntelligenceandInformat.pdf')
    assert record['kind'] == 'bill-numbered' and record['stage'] == 'pih'
    assert engine.lookup('version', 'pih') is None
    assert engine.lookup('consideration', 'pih') is not None


@pytest.mark.parametrize('name', ['BILLS-114hres132-PRH.pdf', 'BILLS-116HRes476-RCP116-23.pdf'])
def test_hres_is_not_hr_plus_es(engine, name):
    record = one(engine, name)
    assert record['kind'] == 'bill-measure-list'
    assert record['references'][0]['measureType'] == 'hres'
    assert 'stage' not in record


def test_placeholder_after_complete_measure_code(engine):
    record = one(engine, 'BILLS-117HRes---ih.pdf')
    assert record['measureType'] == 'hres'
    assert record['numberPlaceholder'] == '---'
    assert record['stage'] == 'ih'


@pytest.mark.parametrize('name', ['BILLS-117OAWPih.pdf', 'BILLS-116H3170_SCPih.pdf'])
def test_uncertain_join_does_not_assert_pih(engine, name):
    result = engine.parse(name)
    assert not result['valid'] and result['input'] == name
    assert 'ambiguous-stage-boundary' in result['issues']


@pytest.mark.parametrize('name,degree', [
    ('BILLS-112s365-HAmdt.pdf', 1), ('BILLS-112s365-HAmdt2.pdf', 2),
    ('BILLS-112s365-HAmdt3.pdf', 3), ('BILLS-112hr123-SAmdt2.pdf', 2),
    ('BILLS-1162227-HAmdt.pdf', 1), ('BILLS-1165245-HAmdt2.pdf', 2),
])
def test_interchamber_amendment_degree_is_not_a_sequence_number(engine, name, degree):
    record = one(engine, name)
    assert record['amendmentDegree'] == degree
    assert 'amendmentNumber' not in record


def test_nonstandard_amendment_suffix_retains_uncertainty(engine):
    record = one(engine, 'BILLS-119HR123-HAmdt002.pdf')
    assert record['amendmentSuffix'] == '002'
    assert 'amendmentDegree' not in record and 'amendmentType' not in record


def test_precedence_preserves_specific_records_and_within_tier_ambiguity(engine):
    assert one(engine, 'BILLS-112HR123ih.pdf')['kind'] == 'bill-numbered'
    assert one(engine, 'BILLS-1131129ih.pdf')['kind'] == 'bill-untyped-numbered'
    assert one(engine, 'BILLS-113pih-BACPACAct.pdf')['kind'] == 'bill-untyped-draft'
    assert one(engine, 'BILLS-114DiscussionDraftih.pdf')['kind'] == 'bill-named-draft'
    assert engine.parse('CRPT-112hrpt-HR2055-DivisonA-som.pdf')['ambiguous']


@pytest.mark.parametrize('name', [
    'BILLS-119ANSServices.pdf', 'BILLS-119Services.pdf',
    'BILLS-119HR123Services.pdf', 'BILLS-119HR123Serviceses.pdf',
    'BILLS-119HR1234stCentAct.pdf', 'BILLS-119HR123pis.pdf',
    'BILLS-119XYZ.pdf', 'BILLS-119HR123HRbad.pdf',
    'BILLS-119HR2147483648-RCP119-01.pdf',
    'BILLS-112-HR3116-000193-Amdt-001A.pdf',
    'BILLS-119HR123.pdf\n', 'BILLS-119HR123/HR456.pdf',
])
def test_no_arbitrary_word_versions_or_invalid_slot_repairs(engine, name):
    assert not engine.parse(name)['valid']


@pytest.mark.parametrize('value', [-1, 3, '1', None, 1.5, True])
def test_priority_is_catalog_validated(engine, value):
    guide = engine.guide
    guide['patterns']['bill-titled-draft']['parse_priority'] = value
    with pytest.raises(NamingError):
        check_catalog(guide)
