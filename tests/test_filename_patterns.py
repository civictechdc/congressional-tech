"""Independent examples of filename syntax, not document-content labels."""
import re
import gzip
import json

import pytest

from congress_api.filenames import (
    RULES, ParsedFilename, resolve_unmatched_filename, date_readings, filename_tokens, parse_filename,
    shared_token_pattern,
)


def fields(name, rule, **options):
    matches = [m for m in parse_filename(name, **options).matches if m.rule == rule]
    assert len(matches) == 1
    return {f.name: f.raw for f in matches[0].fields}


@pytest.mark.parametrize(('name', 'rule', 'expected'), [
    ('CHRG-109hhrg32990.pdf', 'published-hearing',
     {'congress': '109', 'publication_code': 'hhrg', 'publication_number': '32990'}),
    ('CRPT-118srpt42.pdf', 'published-report', {'publication_code': 'srpt', 'publication_number': '42'}),
    ('CRPT-118-II00-VoteRC1-20231108.pdf', 'committee-file', {'committee_code': 'II00'}),
    ('HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf', 'person-document',
     {'document_token': 'Wstate', 'subject_token': 'ColbyJ', 'date_token': '20130314'}),
    ('HHRG-119-IF00-Wstate-M001218-20251212.pdf', 'person-document', {'subject_token': 'M001218'}),
    ('HHRG-115-IF02-MState--20170131.pdf', 'person-document', {'subject_token': ''}),
    ('HHRG-112-HM00-20110310-SD001.pdf', 'dated-document', {'document_token': 'SD', 'document_number': '001'}),
    ('CRPT-114-JU00-Vote1-10-20160525.pdf', 'token-date-document', {'document_number': '1-10'}),
    ('CRPT-116-ED00-Vote10-hr865-20190226.pdf', 'token-date-document', {'document_number': '10-hr865'}),
    ('CRPT-117-II00-VoteMotion-20210902-U3.pdf', 'token-date-document', {'document_token': 'VoteMotion', 'suffix': '-U3'}),
    ('BILLS-116-3239-G000578-Amdt-9.pdf', 'sponsored-amendment',
     {'subject_token': '3239', 'bioguide_token': 'G000578', 'amendment_token': '9'}),
    ('BILLS-1172126r4ih.pdf', 'legislative-text', {'measure_number': '2126', 'version_prefix': 'r4', 'version_token': 'ih'}),
    ('BILLS-115hr1892eas2.pdf', 'legislative-text', {'measure_token': 'hr', 'measure_number': '1892', 'version_token': 'eas', 'version_number_token': '2'}),
    ('BILLS-113-HR4660ih(asfiled).pdf', 'legislative-text', {'measure_token': 'HR', 'measure_number': '4660', 'version_token': 'ih', 'annotation': 'asfiled'}),
    ('BILLS-119HR2162HoneyIntegrityActih.pdf', 'described-legislation', {'descriptor': 'HoneyIntegrityAct', 'version_token': 'ih'}),
    ('BILLS-118HR1162Reportedih-billasreported.pdf', 'described-legislation', {'descriptor': 'Reported', 'version_token': 'ih', 'suffix': '-billasreported'}),
    ('BILLS-118hr2813or.pdf', 'legislative-unlisted-version', {'version_token': 'or'}),
    ('BILLS-1172878ih-U1.pdf', 'legislative-text', {'measure_number': '2878', 'suffix': '-U1'}),
    ('BILLS- 115HR5895HR5894HR5786-RCP115-71.xml', 'measure-list', {'measure_list': 'HR5895HR5894HR5786'}),
    ('BILLS-116pih-PCA-BSC-CA19.pdf', 'draft-legislation', {'version_token': 'pih'}),
    ('CPRT-113-HPRT-RU00-h3547-hamdt2samdt.xml', 'committee-print-file', {'committee_code': 'RU00'}),
    ('QFR Responses - Abrams - 2021-04-20_d3c992f4-69e6-4f6c-a132-c7d59ea42cb6.pdf', 'labeled-subject-date',
     {'label': 'QFR Responses', 'subject_token': 'Abrams', 'date_token': '2021-04-20'}),
    ('Official Hearing Transcript_1.13.2022.pdf', 'labeled-date', {'date_token': '1.13.2022'}),
    ('FY25 AG Bill Rules Committee Print Final.pdf', 'fiscal-year', {'fiscal_year_token': '25'}),
    ('Amdt #1 - Cortez Masto 1st Degree Amdt to S.1760 - Agenda Item 20 (FLO23798).pdf',
     'amendment-reference', {'amendment_token': '1'}),
    ('19Apr23 testimony.pdf', 'day-named-month-date', {'day_token': '19', 'month_token': 'Apr', 'year_token': '23'}),
    ('Testimony May 9, 2023.pdf', 'named-month-date', {'day_token': '9', 'month_token': 'May', 'year_token': '2023'}),
    ('dramolnavathetestimonysenatebudgetcommittee.pdf', 'compact-testimony',
     {'subject_token': 'dramolnavathe', 'document_token': 'testimony', 'context_token': 'senatebudgetcommittee'}),
    ('honglenmulreadysenatebudgetcommitteetestimony.pdf', 'compact-context-testimony',
     {'subject_token': 'honglenmulready', 'context_token': 'senatebudgetcommittee'}),
    ('retjudgethomasblewittsupportformehalchick.pdf', 'compact-support',
     {'subject_token': 'retjudgethomasblewitt', 'recipient_token': 'mehalchick'}),
    ('5824stratforcetranscript.pdf', 'compact-transcript', {'date_or_number_token': '5824', 'context_token': 'stratforce'}),
    ('BILLS-114HRXXXXpih-DraftEducationBill.pdf', 'unnumbered-measure',
     {'measure_token': 'HR', 'number_placeholder': 'XXXX', 'version_token': 'pih'}),
    ('BILLS-115CommitteeResolution115-21ih-Employees.pdf', 'named-draft',
     {'draft_label': 'CommitteeResolution', 'identifier_token': '115-21', 'version_token': 'ih'}),
    ('BILLS-113HR-FC-AP-FY2014-AP00-CJS.pdf', 'appropriation-routing',
     {'scope_token': 'FC', 'committee_token': 'AP', 'fiscal_year_token': '2014', 'committee_code': 'AP00'}),
    ('BILLS-115-SC-AP--AP00-Defense_Bill.pdf', 'appropriation-routing',
     {'scope_token': 'SC', 'committee_code': 'AP00'}),
    ('garridotint.pdf', 'compact-tint', {'subject_token': 'garrido', 'document_token': 'tint'}),
    ('20240731141320553.pdf', 'timestamp-shaped', {'date_token': '20240731', 'time_token': '141320', 'fraction_token': '553'}),
])
def test_observed_layouts(name, rule, expected):
    actual = fields(name, rule)
    assert actual.items() >= expected.items()
    parsed = parse_filename(name)
    assert ''.join(p.raw for p in parsed.pieces) == name
    for match in parsed.matches:
        assert 0 <= match.start <= match.end <= len(name)
        for field in match.fields:
            assert match.start <= field.start <= field.end <= match.end
            assert name[field.start:field.end] == field.raw
    assert ParsedFilename.model_validate_json(parsed.model_dump_json()) == parsed


def test_all_measure_occurrences_and_stacked_extensions_survive():
    parsed = parse_filename('BILLS- 115HR5895HR5894HR5786-RCP115-71.docx.pdf')
    assert [next(f.raw for f in m.fields if f.name == 'measure_number')
            for m in parsed.matches if m.rule == 'measure-reference'] == ['5895', '5894', '5786']
    assert [m.fields[0].raw for m in parsed.matches if m.rule == 'extension'] == ['pdf', 'docx']
    assert not any(t.raw in {'pdf', 'docx'} for t in filename_tokens(parsed))


def test_filename_claims_do_not_become_document_truth():
    # A retained PDF with this Bio name actually contains written testimony.
    parsed = parse_filename('HHRG-115-II24-Bio-ChavarriaJ-20170607.pdf')
    assert fields(parsed.filename, 'person-document')['document_token'] == 'Bio'
    assert 'document_type' not in parsed.model_dump()
    missing_chamber = fields('BILLS-1172878ih.pdf', 'legislative-text')
    assert 'measure_token' not in missing_chamber
    assert 'chamber' not in missing_chamber


@pytest.mark.parametrize(('name', 'type_code', 'version_code', 'version_label'), [
    ('BILLS-115hr1892eas2.pdf', 'hr', 'eas', 'Engrossed Amendment (Senate)'),
    ('BILLS-113-HR4660ih(asfiled).pdf', 'hr', 'ih', 'Introduced (House)'),
    ('BILLS-119s1rh.xml', 's', 'rh', 'Reported in (House)'),
    ('BILLS-119HCONRES14pp.htm', 'hconres', 'pp', 'Public Print'),
])
def test_published_labels_preserve_bill_origin_and_version_separately(name, type_code, version_code, version_label):
    match = next(m for m in parse_filename(name).matches if m.rule == 'legislative-text')
    fs = {f.name: f for f in match.fields}
    assert fs['measure_token'].code == type_code
    assert fs['version_token'].code == version_code
    assert fs['version_token'].label == version_label
    assert fs['version_token'].vocabulary_url == 'https://www.govinfo.gov/help/bills'
    for modifier in ('version_number_token', 'annotation'):
        if modifier in fs:
            assert fs[modifier].label is None
            assert name[fs[modifier].start:fs[modifier].end] == fs[modifier].raw


@pytest.mark.parametrize('token', ['pis', 'or', 'SA', 'SUS'])
def test_unlisted_tokens_survive_without_fabricated_official_labels(token):
    parsed = parse_filename(f'BILLS-119HR42{token}.pdf')
    versions = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert len(versions) == 1
    assert versions[0].raw == token
    assert versions[0].code is None
    assert versions[0].label is None
    assert versions[0].vocabulary_url is None


def test_explicit_interior_ih_boundary():
    name = 'BILLS-119HR10128RepMcClintockTocodifySecretarysOrderNo3434oftheDepartmentoftheInteriorih-U2.pdf'
    match = next(m for m in parse_filename(name).matches if m.rule == 'described-legislation')
    version = next(f for f in match.fields if f.name == 'version_token')
    descriptor = next(f for f in match.fields if f.name == 'descriptor')
    assert descriptor.raw.endswith('DepartmentoftheInterior')
    assert version.raw == 'ih'
    assert version.code == 'ih'
    assert version.label == 'Introduced (House)'
    assert version.candidates == ('ih',)
    assert fields('BILLS-119HR42rih.pdf', 'legislative-text')['version_token'] == 'rih'


def test_other_ambiguous_descriptive_suffixes_remain_candidates():
    name = 'BILLS-119HR42OtherTitleeas.pdf'
    match = next(m for m in parse_filename(name).matches if m.rule == 'described-legislation')
    version = next(f for f in match.fields if f.name == 'version_token')
    assert version.candidates == ('as', 'eas')
    assert version.label is None
    assert version.code is None
    assert all(name[version.end-len(c):version.end].lower() == c for c in version.candidates)


@pytest.mark.parametrize(('name', 'surname', 'title'), [
    ('BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf', 'Clyburn', 'RenewingtheAfricanAmericanCivilRightsNetworkAct'),
    ('BILLS-119HR5470RepLaHoodRoute66NationalHistoricTrailDesignationActih.pdf', 'LaHood', 'Route66NationalHistoricTrailDesignationAct'),
    ('BILLS-119HR10128RepMcClintockTocodifySecretarysOrderNo3434oftheDepartmentoftheInteriorih-U2.pdf', 'McClintock', 'TocodifySecretarysOrderNo3434oftheDepartmentoftheInterior'),
    ('BILLS-119HR9600RepRaskinCommonSenseAct250Actof2026ih.pdf', 'Raskin', 'CommonSenseAct250Actof2026'),
    ('BILLS-119S675RepHoevenTheodoreRooseveltPresidentialLibraryActats.pdf', 'Hoeven', 'TheodoreRooseveltPresidentialLibraryAct'),
])
def test_congress_member_and_title_are_separate_lossless_fields(name, surname, title):
    context = {'119': (surname,)}
    parsed = parse_filename(name, member_surnames=context)
    assert fields(name, 'legislative-file')['congress'] == '119'
    fs = fields(name, 'described-legislation', member_surnames=context)
    assert fs['member_marker'] == 'Rep'
    assert fs['member_surname_token'] == surname
    assert fs['title_token'] == title
    # Joined ATS is a candidate, so preserve it in the whole descriptor even
    # though the candidate title reading stops before it.
    trailing_candidate = 'ats' if name.endswith('LibraryActats.pdf') else ''
    assert fs['descriptor'] == 'Rep' + surname + title + trailing_candidate
    for match in parsed.matches:
        for field in match.fields:
            assert name[field.start:field.end] == field.raw


def test_unknown_member_name_boundary_and_absent_title_stay_unresolved():
    fs = fields('BILLS-119HR42RepVanDrewSomeTitleih.pdf', 'described-legislation')
    assert fs['descriptor'] == 'RepVanDrewSomeTitle'
    assert 'member_surname_token' not in fs
    fs = fields('BILLS-118HR6062RepRadewagenih.pdf', 'described-legislation',
                member_surnames={'118': ('Radewagen',)})
    assert fs['member_surname_token'] == 'Radewagen'
    assert 'title_token' not in fs


@pytest.mark.parametrize(('source_name', 'filename_name'), [
    ('Van Drew', 'VanDrew'), ('Blunt Rochester', 'BluntRochester'),
    ('Miller-Meeks', 'MillerMeeks'), ('O\'Brien', 'OBrien'),
    ('Newperson', 'Newperson'),
])
def test_new_and_multipart_surnames_require_no_parser_change(source_name, filename_name):
    name = f'BILLS-119HR42Rep{filename_name}SomeTitleih.pdf'
    fs = fields(name, 'described-legislation', member_surnames={'119': (source_name,)})
    assert fs['member_surname_token'] == filename_name
    assert fs['title_token'] == 'SomeTitle'
    absent = fields(name, 'described-legislation', member_surnames={'118': (source_name,)})
    assert 'member_surname_token' not in absent


def test_surname_boundary_uses_longest_reference_name_without_consuming_lowercase_word():
    context = {'119': ('Miller', 'Miller-Meeks', 'Smith')}
    fs = fields('BILLS-119HR42RepMillerMeeksSomeTitleih.pdf', 'described-legislation', member_surnames=context)
    assert fs['member_surname_token'] == 'MillerMeeks'
    fs = fields('BILLS-119HR42RepSmithsonianSomeTitleih.pdf', 'described-legislation', member_surnames=context)
    assert 'member_surname_token' not in fs


def test_service_dates_scope_names_to_congress_with_exclusive_term_end():
    from congress_api.filename_corpus import member_surnames_by_congress
    from congress_api.models.legislators import Legislator
    members = [Legislator.model_validate({'id': {'bioguide': f'T{i:06}'},
        'name': {'first': 'Example', 'last': last},
        'terms': [{'type': 'rep', 'state': 'VA', 'start': start, 'end': end}]})
        for i, (last, start, end) in enumerate([
            ('Retired', '2023-01-03', '2025-01-03'),
            ('Newmember', '2025-01-03', '2027-01-03'),
            ('Boundary', '2025-01-02', '2025-01-04')])]
    by_congress = member_surnames_by_congress(members)
    assert by_congress == {'118': ('Boundary', 'Retired'), '119': ('Boundary', 'Newmember')}


def test_multiple_bills_are_not_a_version_and_numeric_modifier():
    name = 'BILLS-115HR6147HR6258-RCP115-81.pdf'
    assert fields(name, 'measure-list')['measure_list'] == 'HR6147HR6258'
    assert not any(f.name == 'version_number_token' for m in parse_filename(name).matches for f in m.fields)


def test_suffix_words_and_routing_are_not_mistaken_for_version_codes():
    name = 'BILLS-113HR1422toamendtheEnvironmentalResearchDevelopmentandDemonstrationAuthorizationActofih-ToamendtheEnvironmentalRes.pdf'
    actual = fields(name, 'described-legislation')
    assert actual['version_token'] == 'ih'
    assert actual['suffix'] == '-ToamendtheEnvironmentalRes'
    routing = parse_filename('BILLS-113-20-FC-AP-FY2014-AP00-FServices.pdf')
    assert not any(f.name == 'version_token' for m in routing.matches for f in m.fields)


@pytest.mark.parametrize('name', [
    'HHRG-113-AG00-Bio-BentsenK-20130314.pdf',
    'BILLS-112-HR1165-J000032-Amdt-1.pdf',
    'BILLS-114-08A-P000608-Amdt-12.pdf',
    'BILLS-115HR6147HR6258-RCP115-81.pdf',
    'BILLS-115hr1892eas2.pdf',
    'BILLS-113-HR4660ih(asfiled).pdf',
    'honglenmulreadysenatebudgetcommitteetestimony.pdf',
])
def test_specific_layout_does_not_also_match_generic_payload(name):
    scopes = {r.id: r.scope for r in RULES}
    for scope in ('stem', 'committee-payload', 'legislative-payload'):
        assert len([m for m in parse_filename(name).matches if scopes.get(m.rule) == scope]) <= 1


@pytest.mark.parametrize(('raw', 'expected'), [
    ('20220518', ('2022-05-18',)),
    ('03042022', ('2022-03-04', '2022-04-03')),
    ('03-04-2022', ('2022-03-04', '2022-04-03')),
    ('2024 2 29', ('2024-02-29',)),
    ('20230229', ()), ('20261340', ()), ('06_17_21', ()),
])
def test_date_readings_do_not_guess(raw, expected):
    assert date_readings(raw)[0] == expected


@pytest.mark.parametrize('name', ['../HHRG-113-AG00-Bio-A-20130314.pdf', 'x\\file.pdf', 'x\0.pdf'])
def test_paths_are_not_silently_rewritten(name):
    with pytest.raises(ValueError, match='basename'):
        parse_filename(name)


@pytest.mark.parametrize(('variants', 'kind', 'yes', 'no'), [
    (('Bio', 'BIO'), 'word', ['Bio.pdf', 'BIO-Smith1.pdf'], ['Biography.pdf', 'microBio.pdf', 'bio.pdf']),
    (('117',), 'number', ['HHRG-117-AG00.pdf', '117abc'], ['1117.pdf', '1179.pdf']),
    (('Statement',), 'wordpart', ['OpeningStatement.pdf', 'Statement.pdf', 'StatementSmith.pdf'],
     ['Statements.pdf', 'Statementary.pdf']),
    (('QFR',), 'wordpart', ['QFRResponses.pdf', 'QFR.pdf'], ['XQFR.pdf', 'QFResponses.pdf']),
    (('café',), 'word', ['café-test.pdf'], ['caféteria.pdf']),
])
def test_generated_rules_respect_token_boundaries(variants, kind, yes, no):
    rule = re.compile(shared_token_pattern(variants, kind))
    assert all(rule.search(name) for name in yes)
    assert all(not rule.search(name) for name in no)


def test_whole_words_camel_parts_unicode_and_punctuation_remain_literal():
    parsed = parse_filename('QFRResponses_SmithM—café__01.PDF')
    assert ''.join(p.raw for p in parsed.pieces) == parsed.filename
    assert [t.raw for t in filename_tokens(parsed) if t.kind == 'wordpart'] == ['QFR', 'Responses', 'Smith', 'M', 'café']
    assert all(parsed.filename[t.start:t.end] == t.raw for t in filename_tokens(parsed))


@pytest.mark.parametrize(('variants', 'kind'), [((), 'word'), (('',), 'word'), (('Bio.*',), 'word'), (('12',), 'word'), (('Bio',), 'invalid')])
def test_shared_rules_require_literal_token_inputs(variants, kind):
    with pytest.raises(ValueError):
        shared_token_pattern(variants, kind)


def test_corpus_build_checks_variants_offsets_and_unmatched_names(tmp_path):
    from congress_api.filename_corpus import build_corpus
    names = [
        'HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf',
        'HHRG-113-AG00-Wstate-SmithM-20130314.pdf',
        'OpeningStatement_A.pdf', 'OpeningStatement_B.pdf',
        'BIO_Smith.pdf', 'Bio_Smith.pdf', 'UniquelyOpaque.pdf',
        'retjudgethomasblewittsupportformehalchick.pdf',
        'retjudgefeltssupportforbrisco.pdf',
    ]
    result = build_corpus(names + [names[0]], tmp_path)
    assert result['literal_filenames'] == 9
    assert result['structural_collisions'] == 0
    assert result['lossless_filenames_checked'] == 9
    assert result['filenames_with_shared_token'] == 6
    assert result['filenames_with_shared_token_or_recurring_layout'] == 8
    rules = {r['id']: r for r in map(json.loads, gzip.open(tmp_path / 'shared-tokens.jsonl.gz', 'rt'))}
    assert rules['word:bio']['variants'] == ['BIO', 'Bio']
    assert rules['wordpart:statement']['filenames'] == 2
    assert all(r['token'] != 'pdf' for r in rules.values())
    unmatched = list(map(json.loads, gzip.open(tmp_path / 'review.jsonl.gz', 'rt')))
    assert any(r['filename'] == 'UniquelyOpaque.pdf' and not r['has_shared_token'] for r in unmatched)


@pytest.mark.parametrize(('filename', 'expected'), [
    ('105526.pdf', {'generic_identifier': '105526', 'name_token': ''}),
    ('999999-sammypdf.pdf', {'generic_identifier': '999999', 'name_token': 'sammy', 'ignored_suffix': 'pdf'}),
    ('3451027152158245824.pdf', {'generic_identifier': '3451027152158245824', 'name_token': ''}),
    ('Doraiswamy.04061.pdf', {'name_token': 'Doraiswamy', 'generic_identifier': '04061'}),
    ('Betancourt.pdf', {'name_token': 'Betancourt'}),
    ('Caroline-Vicini.pdf', {'name_token': 'Caroline-Vicini'}),
    ('premis.xml', {'name_token': 'premis'}),
    ('sammypdf.pdf', {'name_token': 'sammy', 'ignored_suffix': 'pdf'}),
    ('SammyPDF.PDF', {'name_token': 'Sammy', 'ignored_suffix': 'PDF'}),
    ('tobias-tedtimony.pdf', {'name_token': 'tobias', 'ignored_suffix': '-tedtimony'}),
])
def test_unmatched_name_assumptions_preserve_original_spelling(filename, expected):
    parsed = parse_filename(filename)
    interpretation = resolve_unmatched_filename(parsed)
    assert interpretation is not None
    assert {f.name: f.raw for f in interpretation.fields} == expected
    for field in interpretation.fields:
        assert filename[field.start:field.end] == field.raw
        assert not field.candidates
        assert field.note == 'User-specified assumption for otherwise unmatched filenames.'
    assert ''.join(piece.raw for piece in parsed.pieces) == filename
    assert parsed == parse_filename(filename)


@pytest.mark.parametrize('filename', ['offered.zip', 'offered.ZIP', 'archive.txt.zip', 'CHRG-109hhrg32990.pdf'])
def test_name_assumptions_do_not_reclassify_archives_or_known_layouts(filename):
    assert resolve_unmatched_filename(parse_filename(filename)) is None


@pytest.mark.parametrize(('filename', 'rule', 'expected', 'readings'), [
    ('020415.pdf', 'unmatched-leading-date', {'date_token': '020415', 'name_token': ''}, ()),
    ('20220307.xml', 'unmatched-leading-date', {'date_token': '20220307', 'name_token': ''}, ('2022-03-07',)),
    ('31225subreadiness.pdf', 'unmatched-leading-date', {'date_token': '31225', 'name_token': 'subreadiness'}, ()),
    ('20240731141320553.pdf', 'unmatched-leading-timestamp',
     {'date_token': '20240731', 'time_token': '141320', 'fraction_token': '553', 'name_token': ''}, ('2024-07-31',)),
    ('2024-07-31_sammypdf.pdf', 'unmatched-leading-date',
     {'date_token': '2024-07-31', 'name_token': 'sammy', 'ignored_suffix': 'pdf'}, ('2024-07-31',)),
    ('03-04-2022_name.pdf', 'unmatched-leading-date',
     {'date_token': '03-04-2022', 'name_token': 'name'}, ('2022-03-04', '2022-04-03')),
])
def test_dates_and_timestamps_win_before_identifier_fallbacks(filename, rule, expected, readings):
    interpretation = resolve_unmatched_filename(parse_filename(filename))
    assert interpretation.rule == rule
    assert {f.name: f.raw for f in interpretation.fields} == expected
    date_field = next(f for f in interpretation.fields if f.name == 'date_token')
    assert date_field.candidates == readings
    for field in interpretation.fields:
        assert filename[field.start:field.end] == field.raw
    assert 'generic_identifier' not in expected


def test_corpus_uses_assumptions_only_for_the_unmatched_remainder(tmp_path):
    from congress_api.filename_corpus import build_corpus
    result = build_corpus(['20220307.xml', 'sammypdf.pdf', 'tobias-tedtimony.pdf', 'offered.zip',
                           'shared_one.pdf', 'shared_two.pdf'], tmp_path)
    assert result['filenames_with_shared_token_or_recurring_layout'] == 2
    assert result['filenames_unmatched_before_assumptions'] == 4
    assert result['filenames_resolved_by_assumption'] == 2
    assert result['filenames_resolved_by_date_pattern'] == 1
    assert result['filenames_unmatched_after_assumptions'] == 1
    assert (tmp_path / 'unmatched-names.txt').read_text() == 'offered.zip\n'
    rows = [json.loads(line) for line in (tmp_path / 'unmatched-resolutions.jsonl').read_text().splitlines()]
    assert {r['filename'] for r in rows} == {'20220307.xml', 'sammypdf.pdf', 'tobias-tedtimony.pdf', 'offered.zip'}
    numeric = next(r for r in rows if r['filename'] == '20220307.xml')
    assert numeric['basis'] == 'date_pattern'
    assert numeric['interpretation']['rule'] == 'unmatched-leading-date'
    assert 'generic_identifier' not in {f['name'] for f in numeric['interpretation']['fields']}
