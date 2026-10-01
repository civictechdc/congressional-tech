"""Real failures from the three 500-row reviews, with conservative controls."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    return result


@pytest.mark.parametrize('name,subject', [
    ('Crapo Statement 6-25-19.pdf', 'Crapo'),
    ('Levi Pesata REVISED testimony.pdf', 'Levi Pesata'),
    ('testimony-sharkey-final.pdf', 'sharkey'),
    ('nicole_hurd_testimony_final.pdf', 'nicole_hurd'),
    ('Joel Szabat Testimony FINAL.pdf', 'Joel Szabat'),
    ('Goulet Testimony1.pdf', 'Goulet'),
    ('052119_Pedrosa_Testimony1.pdf', 'Pedrosa'),
    ('2025-09-30 PM - Testimony - Biffle.pdf', 'Biffle'),
    ('Donaldson Testimony 10-19-23 SENR Cmte Hrg.pdf', 'Donaldson'),
    ('Logan Bio_0809120e-ec9f-49fd-9542-e1420b3f73df.pdf', 'Logan'),
    ('2024-09-25 - QFR Responses - Desai_3b5fcefd-756b-41ca-8bfc-89f746e7f549.pdf', 'Desai'),
    ('061826_Segura_Testimony_dadb8439-4f74-419e-9256-3341de2ea354.pdf', 'Segura'),
    ('Wally Adeyemo Testimony Final 1.pdf', 'Wally Adeyemo'),
])
def test_subject_excludes_already_recognized_filename_components(engine, name, subject):
    result = checked(engine, name)
    assert result['metadata']['subject_token'] == [subject]
    assert 'name_token' not in result['metadata']
    assert not {'witness_id', 'member_bioguide_id', 'sponsor_bioguide_id'} & result['metadata'].keys()


@pytest.mark.parametrize('extension', ['pdf', 'xml', 'docx', 'zip'])
def test_literal_witness_roles_do_not_depend_on_strict_extension(engine, extension):
    result = checked(engine, f'HHRG-113-PW00-Bio-OBrienPrimmerM-20130530.{extension}')
    metadata = result['metadata']
    assert metadata['document_kind'] == ['witness-biography']
    assert metadata['witness_id'] == ['OBrienPrimmerM']
    assert metadata['meeting_date'] == ['20130530']
    assert metadata['meeting_type'] == ['HHRG']
    assert metadata['extension'] == [extension]
    if extension in {'docx', 'zip'}:
        assert not result['valid']


def test_missing_amendment_number_does_not_hide_known_sponsor_and_category(engine):
    metadata = checked(engine, 'BILLS-119-5300-J000298-Amdt--.pdf')['metadata']
    assert metadata['document_kind'] == ['committee-amendment']
    assert metadata['sponsor_bioguide_id'] == ['J000298']
    assert 'amendment_identifier' not in metadata
    assert 'measure_number' not in metadata


def test_revision_is_separate_from_literal_amendment_token(engine):
    metadata = checked(engine, 'BILLS-119-8870-G000559-Amdt-079Rev1.pdf')['metadata']
    assert metadata['amendment_token'] == ['079Rev1']
    assert metadata['amendment_identifier'] == ['079']
    assert metadata['amendment_id'] == ['079']
    assert metadata['revision_number'] == ['1']


def test_report_layout_preserves_explicit_reference_without_inventing_report_number(engine):
    result = checked(engine, 'CRPT-115HRPTConferencereporttoaccompanyHR5515-.xml')
    metadata = result['metadata']
    assert metadata['congress'] == ['115']
    assert metadata['publication_code'] == ['HRPT']
    assert metadata['measure_references'] == ['hr5515']
    assert metadata['document_kind'] == ['conference-report']
    assert 'report_number' not in metadata
    assert not result['valid']


@pytest.mark.parametrize('name,category', [
    ('Testimony-Sund-2021-02-23.pdf', 'testimony'),
    ('Hunter Opening Statement.pdf', 'opening-statement'),
    ('QFR Responses - Slover - 2021-03-11.pdf', 'questions-for-record-response'),
    ('HHRG-115-IF14-20180130-MbrRoster.pdf', 'member-roster'),
    ('HHRG-116-CN00-20190716-QFR002.pdf', 'questions-for-record'),
    ('HRPT-114-HRept114-571.pdf', 'committee-report'),
    ('CHRG-109hhrg26292v1.zip', 'published-hearing'),
])
def test_known_categories_survive_nonstandard_names(engine, name, category):
    assert checked(engine, name)['metadata']['document_kind'] == [category]


def test_drafting_number_and_valid_reference_numbers_never_become_dates(engine):
    for name in ['TAM22385.pdf', 'HR111111.pdf', 'H.R. 12345.pdf']:
        fields = [f for m in checked(engine, name)['observations'] for f in m['fields']]
        assert not any(f['name'] in {'date_token', 'short_date_token'} for f in fields)


@pytest.mark.parametrize('name', [
    'Final Creek.pdf', 'Statement on Final Decisions.pdf',
    'HHRG-119-IF00-Wstate-FinalJ-20250101.pdf',
    'HHRG-119-IF00-Wstate-RevisionA-20250101.pdf',
])
def test_subject_refinement_does_not_remove_words_inside_names_and_topics(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] == 'document-subject-remainder' for m in result['observations'])


def test_fallback_date_ambiguity_and_unknown_codes_remain_unresolved(engine):
    metadata = checked(engine, 'Testimony_Quintenz_06.10.2025.pdf')['metadata']
    assert metadata['date_token_candidates'] == ['2025-06-10', '2025-10-06']
    unknown = checked(engine, 'HHRG-119-IF00-20250101-XYZ003.pdf')['metadata']
    assert unknown['document_token'] == ['XYZ']
    assert 'document_token_label' not in unknown


def test_nonstandard_extension_preserves_bioguide_role_without_claiming_identity(engine):
    for token,role in [('Wstate','witness_id'),('Mstate','member_bioguide_id')]:
        row = checked(engine, f'HHRG-119-IF00-{token}-S000522-20250101.docx')['metadata']
        assert row[role] == ['S000522']
        assert row['bioguide_token'] == ['S000522']
        if token == 'Wstate':
            assert row['witness_id_type'] == ['bioguide']
    row = checked(engine, 'HHRG-119-IF00-Mstate-Smith-20250101.docx')['metadata']
    assert 'member_bioguide_id' not in row


def test_vote_date_keeps_its_specific_role(engine):
    row = checked(engine, 'CRPT-116-ED00-Vote002-20190918.docx')['metadata']
    assert row['vote_date'] == ['20190918']
    assert 'meeting_date' not in row


@pytest.mark.parametrize('name,subject,measure,amendment', [
    ('Markey S.558 Amendment #5.pdf', 'Markey', 's558', '5'),
    ('Cassidy S.2840 Amendment #51.pdf', 'Cassidy', 's2840', '51'),
])
def test_named_amendments_keep_literal_subject_without_assigning_sponsorship(engine, name, subject, measure, amendment):
    row = checked(engine, name)['metadata']
    assert row['subject_token'] == [subject]
    assert row['measure_references'] == [measure]
    assert row['amendment_token'] == [amendment]
    assert row['document_kind'] == ['amendment']
    assert row['measure_token'] == ['S.']
    assert 'sponsor_bioguide_id' not in row


@pytest.mark.parametrize('suffix,expected', [
    ('PRISMAct','PRISMAct'), ('PostalNaming-ShirleyTolentino','PostalNaming-ShirleyTolentino'),
    ('FunctionTables','FunctionTables'),
])
def test_descriptive_legislative_suffix_has_a_readable_field_without_word_guessing(engine, suffix, expected):
    row = checked(engine, f'BILLS-115HR998ih-{suffix}.xml')['metadata']
    assert row['description'] == [expected]
    assert row['suffix'] == ['-' + suffix]


@pytest.mark.parametrize('suffix', ['U1','RCP115-77','IETC','xml','SD001'])
def test_technical_suffixes_and_unknown_abbreviations_are_not_titles(engine, suffix):
    row = checked(engine, f'BILLS-115HR998ih-{suffix}.xml')['metadata']
    assert 'description' not in row


def test_support_category_does_not_claim_a_document_number(engine):
    for token in ['SD','SD003']:
        row = checked(engine, f'HHRG-119-IF00-20250101-{token}.docx')['metadata']
        assert row['document_kind'] == ['meeting-support']
        assert row.get('document_number') == (['003'] if token == 'SD003' else None)


@pytest.mark.parametrize('extension', ['pdf','docx'])
@pytest.mark.parametrize('code', ['HPRT','hprt'])
def test_publication_type_keeps_its_canonical_code_and_original_spelling(engine, extension, code):
    row = checked(engine, f'CPRT-118{code}54293.{extension}')['metadata']
    assert row['publication_type'] == ['hprt']
    assert row['publication_code'] == [code]


@pytest.mark.parametrize('extension', ['pdf','docx'])
def test_meeting_type_is_consistent_without_strict_parsing(engine, extension):
    row = checked(engine, f'hhrg-119-IF00-Bio-SmithJ-20250101.{extension}')['metadata']
    assert row['meeting_type'] == ['HHRG']
    assert row['package_family'] == ['hhrg']


@pytest.mark.parametrize('extension', ['pdf','docx'])
def test_explicit_bioguide_roles_keep_canonical_case_and_literal_tokens(engine, extension):
    member = checked(engine, f'HHRG-119-IF00-Mstate-s000522-20250101.{extension}')['metadata']
    sponsor = checked(engine, f'BILLS-119-HR1-j000298-Amdt-5.{extension}')['metadata']
    assert member['member_bioguide_id'] == ['S000522']
    assert member['bioguide_token'] == ['s000522']
    assert sponsor['sponsor_bioguide_id'] == ['J000298']
    assert sponsor['bioguide_token'] == ['j000298']
