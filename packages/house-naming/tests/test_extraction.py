"""Literal source cases and controls for uncertain or overlapping metadata."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from house_naming import Engine, NamingError, check_catalog
from house_naming.extraction import date_candidates


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(result, name, *, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


def raw(result, name, *, rule=None):
    return [f['raw'] for f in fields(result, name, rule=rule)]


@pytest.mark.parametrize('name', [
    'Opening Statement-Hassan-2020-06-03.pdf',
    'CHRG-106hhrg53880', 'HHRG-113-HM08-Bio-BejtlichR-20130320.docx',
    'BILLS -115HR3219HR3162HR2998HR3266-RCP115-30.pdf',
    '\nARTAU Letter of Support - Centro de Comunidad Cristiana.pdf',
    'James.docx.pdf', 'O’Brien-Élodie.pdf', 'James.pdf&download=1',
    'BILLS-119HR123ih.pdf', '20260231-Smith.pdf', '',
])
def test_lossless_source_and_unchanged_strict_api(engine, name):
    strict = engine.parse(name)
    result = engine.extract(name)
    assert all(result[key] == value for key, value in strict.items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    for item in result['suppressed']:
        assert name[item['start']:item['end']] == item['raw']
        for field in item['fields']:
            assert name[field['start']:field['end']] == field['raw']


def test_extensionless_publication_does_not_invent_pdf(engine):
    result = engine.extract('CHRG-106hhrg53880')
    assert not result['valid'] and not raw(result, 'extension')
    assert raw(result, 'congress') == ['106']
    assert raw(result, 'publication_code') == ['hhrg']
    assert raw(result, 'publication_number') == ['53880']


def test_statement_with_spaces_has_subject_and_real_date(engine):
    result = engine.extract('Opening Statement-Hassan-2020-06-03.pdf')
    assert raw(result, 'label') == ['Opening Statement']
    assert raw(result, 'subject_token') == ['Hassan']
    assert fields(result, 'date_token')[0]['candidates'] == ['2020-06-03']


def test_non_pdf_witness_document_retains_its_actual_type(engine):
    result = engine.extract('HHRG-113-HM08-Bio-BejtlichR-20130320.docx')
    assert raw(result, 'extension') == ['docx'] and not result['valid']
    assert raw(result, 'subject_token') == ['BejtlichR']
    field = fields(result, 'document_token')[0]
    assert field['raw'] == 'Bio' and field['code'] == 'bio' and field['context'] == 'document'


def test_substitute_retains_marker_target_and_version(engine):
    result = engine.extract('BILLS-116ANStoHR1988ih.pdf')
    assert raw(result, 'amendment_marker', rule='substitute-file') == ['ANS']
    assert raw(result, 'target_marker') == ['to']
    assert raw(result, 'measure_number') == ['1988']
    assert fields(result, 'measure_token')[0]['code'] == 'hr'
    assert fields(result, 'version_token')[0]['code'] == 'ih'


def test_version_shaped_word_is_not_a_known_version(engine):
    result = engine.extract('BILLS-119ANSServices.pdf')
    assert raw(result, 'descriptor') == ['Services']
    field = fields(result, 'version_token')[0]
    assert field['raw'].lower() == 'es' and field['code'] is None
    assert field['candidates'] == ['es']
    result = engine.extract('BILLS-117OAWPih.pdf')
    assert raw(result, 'descriptor') == ['OAWPih']
    assert fields(result, 'version_token')[0]['candidates'] == ['ih', 'pih']


def test_witness_ids_cannot_become_bills_dates_or_revisions(engine):
    result = engine.extract('HHRG-119-AS00-Wstate-S000522-20260101.pdf')
    assert not raw(result, 'measure_number')
    assert not raw(result, 'revision_number')
    assert not raw(result, 'short_date_token')
    assert raw(result, 'date_token') == ['20260101']
    assert result['matches'][0]['record']['witnessIdType'] == 'bioguide'
    assert raw(result, 'bioguide_token') == ['S000522']
    assert any(f['name']=='measure_number' and f['raw']=='000522'
               for m in result['suppressed'] for f in m['fields'])


def test_explicit_measure_lists_and_amendment_text_keep_each_reference(engine):
    result = engine.extract('BILLS-115SAHR3219HR3162HR2998HR3266-RCP115-30.pdf')
    assert raw(result, 'measure_number') == ['3219','3162','2998','3266']
    assert raw(result, 'print_congress') == ['115']
    assert raw(result, 'print_number') == ['30']
    assert '115' not in raw(result, 'document_identifier')
    result = engine.extract('BILLS-115-HR1133-W000815-Amdt-HR1133.pdf')
    assert raw(result, 'measure_number') == ['1133','1133']
    assert len({f['start'] for f in fields(result, 'measure_number')}) == 2


def test_part_and_revision_markers_do_not_steal_the_following_date(engine):
    result = engine.extract('moynihan-testimony-addendum-part-2-5-26-21')
    assert raw(result, 'part_number') == ['2']
    assert raw(result, 'date_token', rule='date-separated') == ['5-26-21']
    result = engine.extract('Russia-China-Activity Hard Cards 2021 v4_03-16-21.pptx')
    assert raw(result, 'revision_number') == ['4']
    assert raw(result, 'date_token', rule='date-separated') == ['03-16-21']
    result = engine.extract('Hamilton Testimony Update 3-4-21.pdf')
    assert raw(result, 'revision_marker') == ['Update']
    assert not raw(result, 'revision_number')
    assert raw(result, 'date_token', rule='date-separated') == ['3-4-21']


def test_hex_prefix_does_not_contaminate_the_subject(engine):
    name = '002F430042B8C2DEA37CD4859843FEC30ED3C4233E457F335A81715B2CBDAA86.bliss-testimony.pdf'
    result = engine.extract(name)
    assert raw(result, 'subject_token') == ['bliss']
    assert raw(result, 'label') == ['testimony']
    assert not raw(result, 'short_date_token')
    assert raw(result, 'opaque_identifier') == [name.split('.')[0]]


def test_archive_appendix_has_identifier_and_title_without_a_person_name(engine):
    result = engine.extract('Appendix A - ABO Incompatibilty Case 1 (Donor Network West).zip')
    assert raw(result, 'appendix_identifier') == ['A']
    assert raw(result, 'subject_token') == ['ABO Incompatibilty Case 1 (Donor Network West)']
    assert not raw(result, 'name_token')
    result = engine.extract('61422_Amendments.zip')
    assert raw(result, 'short_date_token') == ['61422']
    assert not raw(result, 'generic_identifier')
    assert not raw(result, 'name_token')


@pytest.mark.parametrize('text,candidates,plausible', [
    ('20240229', ['2024-02-29'], True), ('20230229', [], False),
    ('2024-13-01', [], False), ('02.03.2024', ['2024-02-03','2024-03-02'], True),
    ('020324', [], True), ('1.13.22', [], True), ('999999', [], False),
    ('20260719', ['2026-07-19'], True), ('00000000', [], False),
])
def test_calendar_candidates_do_not_guess_date_order_or_century(text, candidates, plausible):
    values, possible, _ = date_candidates(text)
    assert values == candidates and possible is plausible


@pytest.mark.parametrize('name,expected,note', [
    ('results-of-executive-session-on-january-22-2021.pdf', ['2021-01-22'], 'Calendar-valid'),
    ('Smith-February-29-2024.pdf', ['2024-02-29'], 'Calendar-valid'),
    ('Smith-29Feb2024.pdf', ['2024-02-29'], 'Calendar-valid'),
    ('Smith-February-31-2024.pdf', [], 'Invalid named'),
    ('Smith-February-29-2023.pdf', [], 'Invalid named'),
    ('Smith-February-29.pdf', [], 'year or century remains unspecified'),
    ('Smith-29Feb24.pdf', [], 'year or century remains unspecified'),
])
def test_named_dates_keep_calendar_meaning_without_becoming_generic_ids(engine, name, expected, note):
    result = engine.extract(name)
    dates = [f for m in result['observations'] if m['rule'] in {'named-month-date', 'day-named-month-date'}
             for f in m['fields'] if f['name'] == 'date_token']
    assert len(dates) == 1
    assert dates[0]['candidates'] == expected and note in dates[0]['note']
    assert not raw(result, 'generic_identifier')
    assert name[dates[0]['start']:dates[0]['end']] == dates[0]['raw']


@pytest.mark.parametrize('name,rule,expected', [
    ('sammypdf.pdf', 'assumed-name', {'name_token':'sammy','ignored_suffix':'pdf'}),
    ('tobias-tedtimony.pdf', 'assumed-name', {'name_token':'tobias','ignored_suffix':'-tedtimony'}),
    ('999999-Smith.pdf', 'assumed-leading-identifier', {'generic_identifier':'999999','name_token':'Smith'}),
    ('20260231-Smith.pdf', 'assumed-leading-identifier', {'generic_identifier':'20260231','name_token':'Smith'}),
    ('20240229-Smith.pdf', 'unmatched-leading-date', {'date_token':'20240229','name_token':'Smith'}),
    ('020324-Smith.pdf', 'unmatched-leading-date', {'date_token':'020324','name_token':'Smith'}),
    ('Smith-020324.pdf', 'unmatched-trailing-date', {'date_token':'020324','name_token':'Smith'}),
    ('Smith-2024-02-29.pdf', 'unmatched-trailing-date', {'date_token':'2024-02-29','name_token':'Smith'}),
    ('20240731141320553-Smith.pdf', 'unmatched-leading-timestamp', {'date_token':'20240731','time_token':'141320','fraction_token':'553','name_token':'Smith'}),
])
def test_user_fallbacks_run_after_date_and_timestamp_recognition(engine, name, rule, expected):
    result = engine.extract(name)
    match = next(m for m in result['observations'] if m['rule'] == rule)
    actual = {f['name']:f['raw'] for f in match['fields']}
    assert all(actual[k] == v for k,v in expected.items())
    for f in match['fields']:
        if f['name'] in {'name_token','generic_identifier','ignored_suffix'}:
            assert 'fallback assumption' in f['note']


@pytest.mark.parametrize('name', ['Jones.zip','abcdef1234567890.pdf','12345678-abcd-1234-abcd-123456789012.pdf'])
def test_archives_and_whole_opaque_ids_are_not_person_names(engine, name):
    result = engine.extract(name)
    assert not raw(result, 'name_token')


@pytest.mark.parametrize('name', [None, [], '../file.pdf', 'a/b.pdf', 'a\\b.pdf', 'a\x00b.pdf', '\ud800', 'x'*16385])
def test_invalid_inputs_and_bounds(engine, name):
    with pytest.raises(NamingError):
        engine.extract(name)


def test_stacked_extensions_query_text_and_padding_stay_separate(engine):
    result = engine.extract(' \nJames.docx.pdf&download=1 ')
    assert raw(result, 'extension') == ['pdf','docx']
    assert raw(result, 'query_text') == ['&download=1']
    assert raw(result, 'name_token') == ['James']


def test_cli_extraction_success_does_not_claim_convention_validity():
    result = subprocess.run([sys.executable,'-m','house_naming','extract','Opening Statement-Hassan-2020-06-03.pdf'],capture_output=True,text=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert not data['valid'] and data['observations']


def test_catalog_extraction_rules_are_checked(engine):
    guide = engine.guide
    guide['extraction_rules'].append(guide['extraction_rules'][0])
    with pytest.raises(NamingError, match='Duplicate'):
        check_catalog(guide)
    guide = engine.guide
    guide['extraction_rules'][0]['pattern'] = '['
    with pytest.raises(NamingError, match='Bad extraction'):
        check_catalog(guide)
