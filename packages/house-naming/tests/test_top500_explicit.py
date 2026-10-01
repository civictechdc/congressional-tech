"""Observed explicit genre failures, with reference/topic counterexamples."""
import pytest
from house_naming import Engine

@pytest.fixture(scope='module')
def engine():
    return Engine()

def checked(engine, filename, source_url=None):
    result = engine.extract(filename, source_url=source_url)
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    assert all(result[k] == v for k, v in engine.parse(filename).items())
    return result['metadata']

@pytest.mark.parametrize('filename,kind,field,value', [
    ('09-09-21_en_bloc_1_tally_sheet.pdf','tally-sheet','subject_token','en_bloc_1'),
    ('09-09-21_garbarino_2v1_recorded_vote_tally_sheet.pdf','tally-sheet','date_token','09-09-21'),
    ('09-09-21_velazquez_amendment_in_the_nature_of_a_substitute_tally_sheet.pdf','tally-sheet','date_token','09-09-21'),
    ('09-21-22_h._res._1298_as_amended_tally_sheet.pdf','tally-sheet','measure_references','hres1298'),
    ('h.r._3462_tally_sheet.pdf','tally-sheet','measure_references','hr3462'),
    ('Exhibit 10_20211215_InfoSec Risk Committee Presentation Items to be aware of_redacted_sanitized_opt.pdf','exhibit','item_token','10'),
    ('Exhibit B5_2021XXXX_Snapshot of data center security system deficiencies_redacted1.pdf','exhibit','item_token','B5'),
    ('Public Exhibit to Second Supplement to UBS Bank USA OCC Application.pdf','exhibit','label','Exhibit'),
    ('Appendix A - ABO Incompatibilty Case 1 (Donor Network West).zip','appendix','appendix_identifier','A'),
    ('draeger_-_appendix_a-nasfaa_history_of_fm_and_pell_changes.pdf','appendix','item_token','a'),
    ('Dubbin-Mermelstein Response Appendixes (1 of 2).pdf','appendix','label','Appendixes'),
    ('05-07-20_panelist_list.pdf','panelist-list','label','panelist_list'),
    ('Participant List 10-25-19 SENR Cmte PLFM Subcmte Roundtable.pdf','participant-list','label','Participant List'),
    ('Opening Statment-Johnson-2020-05-13.pdf','opening-statement','label','Opening Statment'),
    ('Cotton Opening Statment 12-16-201.pdf','opening-statement','label','Opening Statment'),
    ('scott_statment_3-12-25.pdf','statement','label','statment'),
    ('11.19.14 SCIA Witness Testimoiny - IHS.pdf','testimony','label','Testimoiny'),
    ('210312_Fed Soc Letter.pdf','letter','label','Letter'),
    ('letter_to_the_committee_-_levi.pdf','letter','label','letter'),
    ('jones_day_letter_in_support_of_brett_shumate.pdf','letter','target_subject','brett_shumate'),
    ('ABLE_PA_Constituent_Support_Letters_Web.pdf','letter','label','Letters'),
])
def test_literal_genres_preserve_usable_values(engine, filename, kind, field, value):
    row = checked(engine, filename)
    assert kind in row.get('document_kind', [])
    assert value in row.get(field, [])
    assert not row.get('witness_id')

@pytest.mark.parametrize('filename,excluded', [
    ('Statement-about-tally-sheet.pdf', {'tally-sheet'}),
    ('09-09-21_statement_about_tally_sheet.pdf', {'tally-sheet'}),
    ('Statement-on-eapheaa-letter.pdf', {'letter'}),
    ('Report on Exhibit 10.pdf', {'exhibit'}),
    ('Hearing on Appendix A.pdf', {'appendix'}),
    ('Letter about Exhibit B5.pdf', {'exhibit'}),
    ('Report on Participant List Procedures.pdf', {'participant-list'}),
    ('BILLS-119-HR123-Garcia-letter-ih.pdf', {'letter'}),
    ('BILLS-119-HR123-Exhibit-10-ih.pdf', {'exhibit'}),
    ('BILLS-119-HR123-TallySheetAct-ih.pdf', {'tally-sheet'}),
    ('newsletter.pdf', {'letter'}),
    ('letterman.pdf', {'letter'}),
    ('witness-helium-multipage.pdf', {'testimony','statement','witness-list'}),
    ('JFR Afghanistan outside witnesses hearing 2021.09.291.pdf', {'testimony','statement','witness-list'}),
    ('2024-tvpra-list-of-goods.pdf', {'witness-list','panelist-list','participant-list'}),
    ('Short List 2-11-25 SENR Cmte Bus Mtg.pdf', {'witness-list','panelist-list','participant-list'}),
    ('Opener for the annual baseball season.pdf', {'opening-statement','statement'}),
])
def test_topics_references_and_roles_are_not_genres(engine, filename, excluded):
    row = checked(engine, filename)
    assert not excluded & set(row.get('document_kind', []))

@pytest.mark.parametrize('filename,kind', [
    ('Exhibit List (FOR RELEASE).pdf', 'exhibit-list'),
    ('Smith Letter of Support.pdf', 'letter-of-support'),
    ('Notice Letter Footjoy IP EDGE.pdf', 'notice'),
])
def test_specific_phrase_owns_generic_wording(engine, filename, kind):
    assert checked(engine, filename).get('document_kind') == [kind]

@pytest.mark.parametrize('filename,url', [
    ('Cornyn Opener - POE Hearing.pdf','https://www.finance.senate.gov/imo/media/doc/Cornyn%20Opener%20-%20POE%20Hearing.pdf'),
    ('Klomp_Opener_HELP_d5d68c57-2b9c-4e31-a0d8-0bf30c7a2b52.pdf','https://www.help.senate.gov/imo/media/doc/17ee2dec-bda3-6894-8f3d-2a5a1080b546/Klomp_Opener_HELP_d5d68c57-2b9c-4e31-a0d8-0bf30c7a2b52.pdf'),
])
def test_source_corroborated_opener_is_not_a_global_word_expansion(engine, filename, url):
    row = checked(engine, filename, url)
    assert row.get('document_kind') == ['opening-statement']
    assert row.get('label') == ['Opener']
    assert not row.get('witness_id')
    for other_url in (None, 'https://example.org/' + filename.replace(' ','%20')):
        assert 'opening-statement' not in checked(engine,filename,other_url).get('document_kind',[])

@pytest.mark.parametrize('filename', [
    '09-21-22_meuser_amendment_1v2_tally_sheet.pdf',
    '09-09-21_adoption_of_committee_print_as_amended_tally_sheet.pdf',
])
def test_tally_sheet_records_a_vote_on_the_named_target(engine, filename):
    row = checked(engine, filename)
    assert row['document_kind'] == ['tally-sheet']
    # Raw target wording remains available even though it is not this file's genre.
    assert row.get('amendment_marker') or row.get('print_token')


def test_explicit_letter_of_support_does_not_add_redundant_generic_label(engine):
    row = checked(engine, 'Group Letter of Support for Smith.pdf')
    assert row['document_kind'] == ['letter-of-support']
    assert row['label'] == ['Letter of Support']
    assert row['target_subject'] == ['Smith']


def test_distinct_amendment_and_tally_sheet_genres_remain_independent(engine):
    row = checked(engine, 'Amendment 1 and Tally Sheet.pdf')
    assert set(row['document_kind']) == {'amendment', 'tally-sheet'}


def test_existing_joined_recommendation_phrase_is_a_letter(engine):
    row = checked(engine, 'honjosephschmitzletterofrecommendationforjohneisenberg.pdf')
    assert row.get('document_kind') == ['letter']
    assert row['document_token'] == ['letterofrecommendationfor']
    assert row['subject_token'] == ['honjosephschmitz']
    assert row['recipient_token'] == ['johneisenberg']
