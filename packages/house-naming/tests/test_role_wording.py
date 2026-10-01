"""Literal wording, not assertions about people, offices or authorship."""
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
    return result


@pytest.mark.parametrize('name,raw,code', [
    ('012225-ranking-member-merkley-opening-statement', 'ranking-member', 'ranking-member'),
    ('2019-11-19 Ranking Member Carper Opening Statement.pdf', 'Ranking Member', 'ranking-member'),
    ('ranking_member_warren_opening_statement_2-5-25.pdf', 'ranking_member', 'ranking-member'),
    ('011024-chairman-whitehouse-opening-statement', 'chairman', 'chair'),
    ('03 24 21 Opening Statement Chairwoman Klobuchar S11.pdf', 'Chairwoman', 'chair'),
    ('Statement of Amy Klobuchar - Chairwoman Committee on Rules and Administration1.pdf', 'Chairwoman', 'chair'),
    ('2021-03-24 Chair Hassan Opening Statement.pdf', 'Chair', 'chair'),
    ('08.22.18 Vice Chair Baird Testimony Final.pdf', 'Vice Chair', 'vice-chair'),
    ('Agua Caliente Vice Chairman Reid Milanovich Testimony 02.16.2022.pdf', 'Vice Chairman', 'vice-chair'),
    ('vice-chair-family-stability-statement.pdf', 'vice-chair', 'vice-chair'),
    ('011024-senator-grassley-opening-statement', 'senator', 'senator'),
    ('testimony_of_representative_fitzpatrick.pdf', 'representative', 'representative'),
    # Synthetic controls exercise supported case/separator variations.
    ('RankingMemberJones Testimony.pdf', 'RankingMember', 'ranking-member'),
    ('VICE_CHAIRWOMAN JONES TESTIMONY.pdf', 'VICE_CHAIRWOMAN', 'vice-chair'),
    ('Chairperson Jones Testimony.pdf', 'Chairperson', 'chair'),
])
def test_bounded_subject_wording_preserves_longest_phrase(engine, name, raw, code):
    row = checked(engine, name)['metadata']
    assert row['subject_role_wording'] == [raw]
    assert row['subject_role_wording_code'] == [code]
    assert 'target_role_wording' not in row
    assert 'context_role_wording' not in row
    assert not {'person_id', 'author', 'party', 'officeholder', 'person_role'} & row.keys()


def test_two_titles_are_not_reduced_to_one_person_role(engine):
    row = checked(engine, '10.21 Chairman Senator Joe Manchin Opening Statement.pdf')['metadata']
    assert row['subject_role_wording'] == ['Chairman', 'Senator']
    assert row['subject_token'] == ['Joe Manchin']


@pytest.mark.parametrize('name,original,remainder', [
    ('ranking-member-lee-opening-statement.pdf', 'ranking-member-lee', 'lee'),
    ('012225rankingmembermerkleyopeningstatement.pdf', 'rankingmembermerkley', 'merkley'),
    ('2019-11-19 Ranking Member Carper Opening Statement.pdf', 'Ranking Member Carper', 'Carper'),
    ('ranking_member_warren_opening_statement_2-5-25.pdf', 'ranking_member_warren', 'warren'),
    ('011024chairmanwhitehouseopeningstatement.pdf', 'chairmanwhitehouse', 'whitehouse'),
    ('Acting Vice Chairman Jones Testimony.pdf', 'Acting Vice Chairman Jones', 'Jones'),
    ('Former Senator Smith Testimony.pdf', 'Former Senator Smith', 'Smith'),
    ('030624chairmanwhitehousereefactopeningstatement.pdf', 'chairmanwhitehousereefact', 'whitehousereefact'),
])
def test_leading_roles_refine_the_subject_without_losing_source_text(engine, name, original, remainder):
    result = checked(engine, name)
    assert result['metadata']['subject_token'] == [remainder]
    fields = [f for m in result['observations'] for f in m['fields']]
    assert any(f['name'] == 'subject_token' and f['raw'] == original for f in fields)
    assert any(f['name'] == 'subject_token' and f['raw'] == remainder for f in fields)
    assert not {'person_id', 'surname', 'subject_name'} & result['metadata'].keys()


@pytest.mark.parametrize('name', [
    'Agua Caliente Vice Chairman Reid Milanovich Testimony 02.16.2022.pdf',
    'Acting Chairman Jones and former Senator Smith Testimony.pdf',
    'former_ausa_hirst_support_for_sherriff.pdf',
    'BILLS-119-ChairmanTopic-C001053-Amdt-1.pdf',
    'HHRG-119-IF00-Wstate-ChairmanJones-20250318.pdf',
    'Chairman Statement.pdf',
])
def test_nonleading_roles_multiple_subjects_targets_and_identifiers_are_not_trimmed(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] == 'role-subject-remainder' for m in result['observations'])


@pytest.mark.parametrize('name,context,raw', [
    ('012225rankingmembermerkleyopeningstatement.pdf', 'subject', 'rankingmember'),
    ('011024chairmanwhitehouseopeningstatement.pdf', 'subject', 'chairman'),
    ('030624chairmanwhitehousereefactopeningstatement.pdf', 'subject', 'chairman'),
    ('011024senatorgrassleyopeningstatement.pdf', 'subject', 'senator'),
    ('030624senatorgrassleyreefactopeningstatement.pdf', 'subject', 'senator'),
    ('032526openingstatementofrankingmembermerkleysocialsecurity.pdf', 'context', 'rankingmember'),
    ('041626openingstatementofrankingmembermerkleypresidentsbudgetrequest.pdf', 'context', 'rankingmember'),
    ('080426openingstatementofrankingmembermerkleymedicaidhearing.pdf', 'context', 'rankingmember'),
])
def test_fused_prefix_requires_opening_statement_and_keeps_the_remainder(engine, name, context, raw):
    row = checked(engine, name)['metadata']
    assert row[context + '_role_wording'] == [raw]
    assert not {'member_surname_token', 'person_id', 'title_token'} & row.keys()
    if 'reefact' in name:
        assert any('reefact' in value for value in row['subject_token'])
    if 'socialsecurity' in name:
        assert row['context_token'] == ['ofrankingmembermerkleysocialsecurity']


@pytest.mark.parametrize('name', [
    'Chairmanship Opening Statement.pdf', 'chairmanshipopeningstatement.pdf',
    'senatorialopeningstatement.pdf', 'rankingmembershipopeningstatement.pdf',
    'senatorgrassley.pdf', 'chairmanwhitehouse.pdf', 'rankingmembermerkley.pdf',
    'RésuméchairmanOpeningStatement.pdf', 'chairmanéOpeningStatement.pdf',
    'TRANSCRIPT-unofficial-for-web-Slovakias-Chairmanship-of-the-OSCE.pdf',
    'BILLS-114S1576ih-RepresentativesPayeeFraudPreventionAct.pdf',
    'HHRG-119-IF00-Wstate-Senatorian-20250318.pdf',
    'Memo.pdf?chairman=senator&former=acting',
    # The counter-suffixed label is not yet recognized; do not guess a role.
    '092723chairmanwhitehouseopeningstatement1.pdf',
])
def test_substrings_plural_institutions_and_unqualified_fused_text_are_not_titles(engine, name):
    row = checked(engine, name)['metadata']
    assert not any('_role_wording' in key or '_role_modifier' in key for key in row)


@pytest.mark.parametrize('name,prefix,word', [
    ('BILLS-1165214ih-ANStotheRepresentativePayeeFraudPreventionActof2019.pdf', 'target', 'Representative'),
    ('BILLS-119pih-ANStoHR3633offeredbyChairmanThompsonofPennsylvania-U1.pdf', 'target', 'Chairman'),
    ('BILLS-119-ChairmanTopic-C001053-Amdt-1.pdf', 'target', 'Chairman'),
    ('BILLS-113pih-RepChairViceChairSubMemb113.pdf', 'context', 'ViceChair'),
    ('fy25_302b_chair_proposal.pdf', 'context', 'chair'),
    ('accredited_investor_-_purchaser_representative.pdf', 'context', 'representative'),
    ('SlovakiasChair.pdf', 'context', 'Chair'),
    ('Chairman of the Board Act.pdf', 'context', 'Chairman'),
    ('022521 Wyden Statement at Finance Committee Hearing on the Nomination of Katherine Tai for U.S. Trade Representative.pdf', 'context', 'Representative'),
    ('37. Terry Cole Letter of Support - Óscar Adolfo Naranjo Trujillo - To Chair_48j79b55uagw.pdf', 'context', 'Chair'),
])
def test_topic_or_target_wording_is_not_promoted_to_the_primary_subject(engine, name, prefix, word):
    row = checked(engine, name)['metadata']
    assert word in row[prefix + '_role_wording']
    assert 'subject_role_wording' not in row
    assert not {'person_id', 'author', 'party', 'person_role'} & row.keys()


@pytest.mark.parametrize('name,prefix,word', [
    ('111413 Acting Director Roubideaux Testimony.docx', 'subject', 'Acting'),
    ('Acting Administrator Elwell Testimony.pdf', 'subject', 'Acting'),
    ('former_ausa_hirst_support_for_sherriff.pdf', 'subject', 'former'),
    ('former-department-of-justice-officials-letter-of-support-for-bondi-1', 'subject', 'former'),
    ('HHRG-117-II10-Wstate-BarberFormerMemberofCongressHR250R-20211014.pdf', 'subject', 'Former'),
    ('Jones support for former Senator Smith.pdf', 'target', 'former'),
    ('June 24, 2021 SASC Joint Testimony of Secretary Granholm and Acting Under Secretary Verdon on DOE Posture Final.pdf', 'subject', 'Acting'),
    ('4.30.14 Acting Chairman Mike OlguinTestimony - Southern Ute Indian Tribe.pdf', 'context', 'Acting'),
])
def test_modifiers_preserve_literal_context_without_inventing_attachment(engine, name, prefix, word):
    row = checked(engine, name)['metadata']
    assert row[prefix + '_role_modifier'] == [word]
    assert row[prefix + '_role_modifier_code'] == [word.lower()]
    assert not {'office_status', 'person_status', 'former_officeholder'} & row.keys()
    if 'Barber' in name:
        assert row['witness_id'] == ['BarberFormerMemberofCongressHR250R']
    if 'sherriff' in name:
        assert row['subject_token'] == ['former_ausa_hirst']
        assert row['target_subject'] == ['sherriff']
        assert 'target_role_modifier' not in row


def test_modifiers_do_not_attach_to_every_role(engine):
    name = 'Acting Chairman Jones and former Senator Smith Testimony.pdf'
    result = checked(engine, name)
    row = result['metadata']
    assert row['subject_role_wording'] == ['Chairman', 'Senator']
    assert row['subject_role_modifier'] == ['Acting', 'former']
    assert 'person_role' not in row
    fields = [f for m in result['observations'] for f in m['fields'] if '_role_' in f['name']]
    assert all(f['context'] == 'subject_token' for f in fields)


def test_existing_filer_and_chair_mark_readings_remain_intact(engine):
    row = checked(engine, 'BILLS-118-HR6571-B001303-Amdt-ANS_02XMLfiledbyRepBluntRochestertoHR6571.pdf')['metadata']
    assert row['member_marker'] == ['Rep']
    assert row['name_token'] == ['BluntRochester']
    row = checked(engine, 'description-of-the-chairmans-mark-for-the-modernizing-and-ensuring-pbm-accountability-mepa-act-of-2023')['metadata']
    assert not any('_role_wording' in key for key in row)
