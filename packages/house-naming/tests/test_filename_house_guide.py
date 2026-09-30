"""Source-backed meanings and worked examples from the retained 2012 House guide.

The supplied JSON catalog retains source definitions, spelling and examples.
Expected field values and spans below are independently stated.
"""
from collections import Counter

import pytest

from house_naming.bill_codes import BILL_TYPES, BILL_VERSIONS
from house_naming.filenames import registry, parse_filename
from house_naming.naming import HOUSE_NAMING, code_label

GUIDE = HOUSE_NAMING.guide
SCOPES = {r['id']: r['scope'] for r in registry()}


def fields(filename):
    parsed = parse_filename(filename)
    assert ''.join(piece.raw for piece in parsed.pieces) == filename
    for match in parsed.matches:
        for field in match.fields:
            assert 0 <= match.start <= field.start <= field.end <= match.end <= len(filename)
            assert filename[field.start:field.end] == field.raw
    return {field.name: field for match in parsed.matches for field in match.fields}


def test_code_definitions_remain_contextual_and_source_attributed():
    rh = HOUSE_NAMING.lookup('version', 'RH')
    assert len(rh['statements']) == 2
    assert 'occurs with both' in rh['statements'][0]['text']
    assert 'occurs to both' in rh['statements'][1]['text']
    for context, entries in GUIDE['codes'].items():
        for entry in entries.values():
            for statement in entry['statements']:
                source_id = statement['source']['source_id']
                node = HOUSE_NAMING.source(source_id)
                text = node['text']
                if node['kind'] == 'section':
                    text = ' '.join(n['text'] for n in GUIDE['source_nodes'].values()
                                    if n.get('section_id') == source_id)
                assert ' '.join(statement['text'].split()) in ' '.join(text.split())
    assert HOUSE_NAMING.contexts('SC') == ['appropriation', 'continuing-resolution', 'supplemental', 'version']
    for code in GUIDE['codes']['version']:
        field = fields(f'BILLS-119hr42{code}.pdf')['version_token']
        assert field.code == code and field.label == GUIDE['codes']['version'][code]['label']
    assert 'rhuc' in BILL_VERSIONS  # Additional current GovInfo vocabulary survives.
    assert HOUSE_NAMING.lookup('version', 'rhuc') is None
    assert HOUSE_NAMING.lookup('consideration', 'PIH') is not None
    assert HOUSE_NAMING.lookup('consideration', 'PIS') is None


def test_all_measure_types_and_collection_names_are_available():
    for code, label in BILL_TYPES.items():
        assert HOUSE_NAMING.lookup('measure', code)['label'] == label
    assert len(GUIDE['codes']['collection']) == 22
    for code, entry in GUIDE['codes']['collection'].items():
        result = fields(f'{code.upper()}-opaque-package.pdf')
        assert result['collection_token'].code == code
        assert result['collection_token'].label == entry['label']
        assert result['payload'].raw == 'opaque-package'
        assert 'congress' not in result


# Each literal appears in the cited catalog source node or its indexed examples. These expectations exercise
# meaning (parts, degrees, grouped amendments, date roles), not just a regex hit.
@pytest.mark.parametrize(('source_id', 'name', 'expected'), [
    ('table-8479-row-2', 'BILLS-112hres-PIH-electing-sgt-at-arms.xml', {'measure_token': 'hres', 'version_token': 'PIH'}),
    ('table-8408-row-2', 'BILLS-112hr123-SUS.pdf', {'local_code_token': 'SUS', 'measure_number': '123'}),
    ('table-8396-row-2', 'BILLS-112hr2887-UConsent.pdf', {'local_code_token': 'UConsent'}),
    ('table-8384-row-2', 'BILLS-112HRes-ORH-Rule-HR10.pdf', {'measure_token': 'HRes', 'local_code_token': 'ORH', 'covered_measure_token': 'HR', 'covered_measure_number': '10'}),
    ('table-8177-row-2', 'BILLS-112HR-SC-AP-FY13-Agriculture.pdf', {'scope_token': 'SC', 'fiscal_year_token': '13', 'appropriation_subject': 'Agriculture'}),
    ('table-8177-row-12', 'BILLS-112HR-FC-AP- FY13- TransHUD.pdf', {'scope_token': 'FC', 'fiscal_year_token': '13', 'appropriation_subject': 'TransHUD'}),
    ('table-8177-row-12', 'BILLS-112HR-ORH-AP-TransHUD.pdf', {'scope_token': 'ORH', 'appropriation_subject': 'TransHUD'}),
    ('table-8159-row-2', 'BILLS-112HR-ORH-AP-FY13-suppl-02.pdf', {'appropriation_kind': 'suppl', 'appropriation_sequence': '02'}),
    ('table-8079-row-2', 'BILLS-112HJRes-ORH-AP-FY13-CR-01.pdf', {'measure_token': 'HJRes', 'appropriation_kind': 'CR', 'appropriation_sequence': '01'}),
    ('table-8035-row-2', 'BILLS-112s365-HAmdt2.pdf', {'amendment_marker': 'HAmdt', 'amendment_degree': '2'}),
    ('table-8035-row-2', 'BILLS-112s365-HAmdt3.pdf', {'amendment_degree': '3'}),
    ('table-8023-row-2', 'BILLS-112hr-HR2608-R000395-Amdt-001.pdf', {'bioguide_token': 'R000395', 'amendment_token': '001'}),
    ('table-7962-row-2', 'CRPT-112hrpt332.pdf', {'publication_number': '332'}),
    ('table-7952-row-2', 'CRPT-112hrpt-HR2055.pdf', {'congress': '112', 'measure_number': '2055'}),
    ('table-7926-row-2', 'CRPT-112hrpt-HR2055-DivisonA.pdf', {'division_marker': 'Divison', 'division_token': 'A'}),
    ('table-7926-row-3', 'CRPT-112hrpt-HR2055-frontmatter-som.pdf', {'report_component': 'som'}),
    ('table-7852-row-2', 'HMTG-112-AG-Weekof20111205', {'notice_marker': 'Weekof', 'date_token': '20111205'}),
    ('table-7835-row-2', 'HMTG-112-HMKP-BU-20110215-2.pdf', {'meeting_token': 'HMKP', 'meeting_sequence': '2'}),
    ('table-7835-row-3', 'HMTG-112--HHRG- AG03-20110705.pdf', {'meeting_token': 'HHRG', 'committee_code': 'AG03'}),
    ('table-7835-row-4', 'HMTG-112-HMTG-RU-20110215.pdf', {'meeting_token': 'HMTG', 'committee_code': 'RU'}),
    ('table-7787-row-2', 'HHRG-112-ED-WList-20110922.pdf', {'document_token': 'WList'}),
    ('table-7777-row-2', 'HHRG-112-ED-WState-IveyB-20110922.pdf', {'document_token': 'WState', 'subject_token': 'IveyB'}),
    ('table-7777-row-2', 'HHRG-112-ED-WState-S000510-20110922.pdf', {'bioguide_token': 'S000510'}),
    ('table-7768-row-2', 'HHRG-112-ED-WState-IveyB-20110922-SD001.pdf', {'document_marker': 'SD', 'document_identifier': '001'}),
    ('table-7714-row-2', 'HHRG-112-ED-TTF-MartinA-20110922.pdf', {'document_token': 'TTF', 'subject_token': 'MartinA'}),
    ('table-7704-row-2', 'HHRG-112-ED-Bio-IveyB-20110922.pdf', {'document_token': 'Bio'}),
    ('table-7691-row-2', 'CRPT-112-HMTG-ED-Vote002-20111026.pdf', {'document_token': 'Vote', 'document_number': '002'}),
    ('table-7633-row-3', 'BILLS-112-HR2608-R000395-Amdt-001-Enbloc-002.pdf', {'amendment_identifier': '001', 'enbloc_marker': 'Enbloc', 'enbloc_number': '002'}),
    ('table-7633-row-3', 'BILLS-112-HR2608-R000395-Amdt-Enbloc-001.pdf', {'enbloc_number': '001'}),
    ('table-7615-row-6', 'BILLS-112-HR3116-K000210-Amdt-001CC1.pdf', {'amendment_identifier': '001CC1'}),
    ('table-7615-row-3', 'BILLS-112-HR3116-000193-Amdt-001A.pdf', {'sponsor_identifier_token': '000193', 'amendment_identifier': '001A'}),
    ('table-7615-row-4', 'BILLS-112-HR3116-C001067 Amdt-001B.pdf', {'sponsor_identifier_token': 'C001067', 'amendment_identifier': '001B'}),
    ('table-7477-row-2', 'HMKP-112-IF03-MState-W000413-20120125.pdf', {'document_token': 'MState', 'bioguide_token': 'W000413'}),
    ('table-7460-row-2', 'HMTG-112-HMKP-BU-20110215-2-SD001.pdf', {'meeting_sequence': '2', 'document_identifier': '001'}),
    ('section-35', 'CPRT-112-HPRT-AG-CommitteeRules.pdf', {'document_token': 'CommitteeRules', 'committee_code': 'AG'}),
    ('section-37', 'HRPT-112-HR123-p2.pdf', {'measure_number': '123', 'part_marker': 'p', 'part_number': '2'}),
    ('section-38', 'CPRT-112hrpt-activities-Q4-RU.pdf', {'document_token': 'activities', 'quarter_number': '4'}),
    ('table-7319-row-2', 'BILLS-112hr123-SUS-U1.pdf', {'revision_marker': 'U', 'revision_number': '1'}),
])
def test_worked_example_values(source_id, name, expected):
    assert name in HOUSE_NAMING.source(source_id)['text'] or any(
        row['section_id'] == source_id or row['source']['source_id'] == source_id
        for row in HOUSE_NAMING.examples(name))
    result = fields(name)
    # A Rules resolution and its covered bill have distinct fields; generic
    # measure-reference also intentionally sees the covered bill.
    if 'covered_measure_token' in expected:
        assert any(f.name == 'measure_token' and f.raw == 'HRes' for m in parse_filename(name).matches for f in m.fields)
        expected = {k: v for k, v in expected.items() if k != 'measure_token'}
    assert {key: result[key].raw for key in expected} == expected


# Exact source occurrences remain separate in the catalog. Exercise every
# distinct concrete filename, including source errors, without regenerating it.
EXAMPLES = sorted({row['value'] for row in GUIDE['examples'].values()
                   if row['form'] == 'filename' and not row['placeholders']})


@pytest.mark.parametrize('name', EXAMPLES)
def test_every_retained_worked_example_has_one_layout_and_exact_spans(name):
    fields(name)
    parsed = parse_filename(name)
    layouts = Counter(SCOPES[m.rule] for m in parsed.matches if SCOPES.get(m.rule) in {'stem', 'legislative-payload', 'committee-payload'})
    if name == 'CMTG-112-HHRG-ED-201109022-U3.pdf':
        assert not layouts  # Malformed in the guide; do not silently repair it.
        return
    assert layouts['stem'] == 1
    if name.startswith('BILLS-'):
        assert layouts['legislative-payload'] == 1
    assert all(count == 1 for count in layouts.values())


def test_part_definition_and_list_example_have_specific_meaning():
    name = 'HRPT-112-HR123-p2.pdf'
    records = HOUSE_NAMING.parse(name)['matches']
    assert len(records) == 1
    assert records[0]['record'] == {'kind': 'committee-report-part', 'congress': 112,
                                   'measureType': 'HR', 'measureNumber': 123,
                                   'partNumber': 2, 'extension': 'pdf'}
    assert HOUSE_NAMING.render(records[0]['record']) == name
    assert 'for part two of a report' in HOUSE_NAMING.examples(name)[0]['gloss']
    result = fields(name)
    assert result['part_marker'].label == 'Report part'
    assert result['part_number'].raw == '2'
    assert result['measure_number'].raw == '123'
    assert 'publication_number' not in result


def test_context_separates_shared_codes_and_numeric_roles():
    version = fields('BILLS-119hr42sc.pdf')['version_token']
    scope = fields('BILLS-112HR-SC-AP-FY13-Agriculture.pdf')['scope_token']
    assert version.label == 'Sponsor Change'
    assert 'subcommittee' in scope.label
    assert HOUSE_NAMING.lookup('version', 'sc') != HOUSE_NAMING.lookup('appropriation', 'sc')
    assert fields('HHRG-112-ED-WState-IveyB-20110922-SD001.pdf')['document_marker'].vocabulary_url.endswith('page=14')
    assert fields('HMTG-112-HMKP-BU-20110215-SD001.pdf')['document_marker'].vocabulary_url.endswith('page=17')
    assert 'fiscal_year_token' not in fields('BILLS-112HR-ORH-AP-TransHUD.pdf')
    assert 'amendment_identifier' not in fields('BILLS-112-HR2608-R000395-Amdt-Enbloc-001.pdf')
    assert 'second degree' in fields('BILLS-112s365-HAmdt2.pdf')['amendment_marker'].label
    assert 'first degree' in fields('BILLS-112s365-HAmdt.pdf')['amendment_marker'].label
    weekly = next(m for m in parse_filename('HMTG-112-AG-Weekof20111205').matches if m.rule == 'weekly-notice')
    assert 'Monday' in next(f for f in weekly.fields if f.name == 'date_token').note


@pytest.mark.parametrize('name', ['BILLS-112HR1-HAmdt2a.pdf', 'BILLS-112HR1-HAmdt4.pdf',
    'Biography-HAmdt2.pdf', 'BILLS-112hr1-suppl-01.pdf', 'Biography-SUS.pdf',
    'Biography-FC-AP-FY13.pdf', 'Biography-p2.pdf', 'Biography-CommitteeRules.pdf',
    'BILLS-112hr1-UConsentSomething.pdf'])
def test_context_and_boundaries_do_not_create_official_meanings(name):
    result = fields(name)
    assert not any(key in result for key in ('amendment_degree', 'appropriation_sequence', 'part_number', 'local_code_token', 'scope_token'))


def test_source_errors_and_unknown_codes_are_preserved():
    result = fields('CMTG-112-HHRG-ED-201109022-U3.pdf')
    assert 'date_token' not in result and 'meeting_token' not in result
    assert result['revision_number'].raw == '3'
    result = fields('BILLS-112-HR3116-000193-Amdt-001A.pdf')
    assert 'bioguide_token' not in result
    assert result['sponsor_identifier_token'].raw == '000193'
    assert HOUSE_NAMING.lookup('consideration', 'SUSPECT') is None
    assert code_label('document', 'SUSPECT') is None


def test_local_orh_does_not_automatically_mean_a_rules_resolution():
    field = fields('BILLS-119hrTITLE-ORH.pdf')['local_code_token']
    assert field.raw == 'ORH' and field.label is None


@pytest.mark.parametrize('name', [
    'BILLS-112-HR1-R000395-Amdt-Words001-Enbloc-002.pdf',
    'BILLS-112-HR1-R000395-Amdt-Name001CC1.pdf',
    'CPRT-112-HPRT-AG-NotCommitteeRules.pdf',
])
def test_word_tails_do_not_become_structured_identifiers(name):
    result = fields(name)
    assert 'amendment_identifier' not in result
    assert 'document_token' not in result


@pytest.mark.parametrize('name', ['IveyB', 'JohnSmith', 'S000510', 'iveyb'])
def test_witness_ids_remain_opaque(name):
    result = fields(f'HHRG-119-ED-WState-{name}-20260915.pdf')
    assert result['subject_token'].raw == name
    assert not any(key.startswith('witness_') for key in result)


def test_observed_house_layout_preserves_extractor_fields():
    name = 'HMKP-119-II00-20260915-SD002.pdf'
    record = HOUSE_NAMING.parse(name)['matches'][0]['record']
    assert record['meetingType'] == 'HMKP'
    assert record['documentType'] == 'SD' and record['documentNumber'] == '002'
    result = fields(name)
    assert result['document_token'].raw == 'SD'
    assert result['document_token'].label == 'Documents in general support of the meeting'
    assert result['document_number'].raw == '002'
    assert result['committee_code'].raw == 'II00'
    malformed = 'HMTG-112--HHRG- AG03-20110705.pdf'
    source = HOUSE_NAMING.parse(malformed)
    assert source['found_in_source'] and not source['valid']
    assert fields(malformed)['committee_code'].raw == 'AG03'


@pytest.mark.parametrize('tail', ['Amdt-001', 'UnknownSubject', 'AgricultureExtra'])
def test_appropriation_subject_requires_a_catalog_token(tail):
    result = fields(f'BILLS-119-HR-FC-AP-FY2026-AP00-{tail}.pdf')
    assert result['descriptor'].raw == tail
    assert 'appropriation_subject' not in result


@pytest.mark.parametrize('subject', ['Defense', 'Agriculture', 'TransHUD', 'CJS'])
def test_appropriation_subject_uses_catalog_names_without_example_year(subject):
    result = fields(f'BILLS-119-HR-FC-AP-FY2026-AP00-{subject}.pdf')
    assert result['appropriation_subject'].raw == subject
