"""Recurring printed components stay distinct from inferred identities/versions."""
import subprocess
import sys

import pytest

from house_naming import Engine
from house_naming.corpus import residual_fields


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('subject,identifier', [
    ('CommitteePrint119-A', '119-A'), ('CommitteePrint2', '2'),
    ('Committee_Print0002', '0002'), ('committeeprint119-a', '119-a'),
])
def test_print_identifier_never_supplies_congress_or_measure_number(engine, subject, identifier):
    result = checked(engine, f'BILLS-118-{subject}-C001103-Amdt-015.pdf')
    assert fields(result, 'print_identifier', 'committee-print-subject')[0]['raw'] == identifier
    assert [f['raw'] for f in fields(result, 'congress')] == ['118']
    assert not fields(result, 'measure_number') and not fields(result, 'print_congress')
    assert fields(result, 'subject_token')[0]['raw'] == subject


@pytest.mark.parametrize('subject', ['CommitteePrint119-AExtra', 'CommitteePrinter2', 'CommitteePrint-2', 'CP119-A'])
def test_unsupported_print_spelling_is_not_partially_matched(engine, subject):
    result = checked(engine, f'BILLS-118-{subject}-C001103-Amdt-015.pdf')
    assert not fields(result, 'print_identifier', 'committee-print-subject')


@pytest.mark.parametrize('subject,prefix,marker', [
    ('GrijalvaANS', 'Grijalva', 'ANS'),
    ('NewpersonANS', 'Newperson', 'ANS'),
    ('VanDrewAINS', 'VanDrew', 'AINS'),
    ('GrijalvaANStoCommitteePrint', 'Grijalva', 'ANS'),
    ('NewpersonANStoHR42', 'Newperson', 'ANS'),
])
def test_printed_case_boundary_does_not_claim_a_person_identity(engine, subject, prefix, marker):
    result = checked(engine, f'BILLS-117-{subject}-B000668-Amdt-21.pdf')
    assert fields(result, 'descriptor', 'attached-substitute')[0]['raw'] == prefix
    assert fields(result, 'amendment_marker', 'attached-substitute')[0]['raw'] == marker
    assert not fields(result, 'member_surname_token')
    assert 'not an established person name' in fields(result, 'descriptor', 'attached-substitute')[0]['note']
    assert fields(result, 'subject_token')[0]['raw'] == subject
    if subject.endswith('CommitteePrint'):
        assert fields(result, 'label', 'committee-print-subject')[0]['raw'] == 'CommitteePrint'
    if subject.endswith('HR42'):
        assert [f['raw'] for f in fields(result, 'measure_number')] == ['42']
    residual = residual_fields(result, field_names={'subject_token'})
    assert any(s['raw'] == prefix for r in residual for s in r['residual_spans'])


@pytest.mark.parametrize('subject', ['Evans', 'EVANS', 'TRANS', 'HANS', 'Grijalvaans', 'GrijalvaANSon', 'GrijalvaANSto'])
def test_words_and_ambiguous_case_do_not_get_an_attached_marker(engine, subject):
    result = checked(engine, f'BILLS-117-{subject}-B000668-Amdt-21.pdf')
    assert not fields(result, 'amendment_marker', 'attached-substitute')


@pytest.mark.parametrize('token,marker,number', [
    ('CMT-AMD_01', 'AMD', '01'), ('D_AMDT_01', 'AMDT', '01'),
    ('SC-AINS_02', 'AINS', '02'), ('CMT-ANS_02-U1', 'ANS', '02'),
    ('AMD_001', 'AMD', '001'), ('FC-AMD_04', 'AMD', '04'),
    ('SUD-REENTRY-AINS_01', 'AINS', '01'), ('amd-12', 'amd', '12'),
    ('LOCAL-AMD_20240123', 'AMD', '20240123'),
])
def test_local_marker_and_number_remain_non_official_components(engine, token, marker, number):
    result = checked(engine, f'BILLS-118-HR42-B000668-Amdt-{token}.pdf')
    components = fields(result, 'local_number_token', 'local-amendment-component')
    assert [f['raw'] for f in components] == [number]
    assert 'not an established bill or amendment sequence' in components[0]['note']
    assert fields(result, 'amendment_marker', 'local-amendment-component')[0]['raw'] == marker
    assert fields(result, 'amendment_marker', 'local-amendment-component')[0]['code'] is None
    assert fields(result, 'amendment_token', 'sponsored-amendment')[0]['raw'] == token
    assert not fields(result, 'amendment_identifier')
    assert {f['raw'] for f in fields(result, 'measure_number')} == {'42'}
    assert not fields(result, 'date_token')


@pytest.mark.parametrize('token', ['CMTAMD_01', 'DSCAMD_01', 'AMD_12th', 'AMD_01XML', 'AMD_', 'AMD1', 'MADAMDT_01'])
def test_local_components_require_explicit_marker_and_number_boundaries(engine, token):
    result = checked(engine, f'BILLS-118-HR42-B000668-Amdt-{token}.pdf')
    assert not fields(result, 'local_number_token', 'local-amendment-component')


def test_repeated_local_components_keep_their_own_offsets(engine):
    result = checked(engine, 'BILLS-118-D_AMDT_01-B000668-Amdt-CMT-AMD_01.pdf')
    parts = fields(result, 'local_number_token', 'local-amendment-component')
    assert len(parts) == 2 and len({p['start'] for p in parts}) == 2


def test_nested_filing_identifier_uses_the_same_component_rule(engine):
    token = '5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555'
    result = checked(engine, f'BILLS-118-HR5555-M001215-Amdt-{token}.pdf')
    assert fields(result, 'local_number_token', 'local-amendment-component')[0]['raw'] == '01'
    assert not fields(result, 'amendment_identifier')


@pytest.mark.parametrize('subject,label', [
    ('DiscussionDraft', 'DiscussionDraft'),
    ('DiscussionDrafttheDataBreachSecurityandNotificationActof2015', 'DiscussionDraft'),
    ('DiscussionDraftofHR____ImprovingCoalCombustionResidualsRegulationActof2015', 'DiscussionDraft'),
    ('DiscussionDraftonFERCProcess', 'DiscussionDraft'),
    ('DiscussionDrafttoamendthe', 'DiscussionDraft'),
    ('AmericanPrivacyRightsActdiscussiondraft', 'discussiondraft'),
    ('Agriculture-SubcommitteeDraft', 'SubcommitteeDraft'),
    ('Drafted-Discussion_Draft', 'Discussion_Draft'),
])
def test_draft_wording_is_literal_not_a_version_code(engine, subject, label):
    result = checked(engine, f'BILLS-118-{subject}-B000668-Amdt-1.pdf')
    matched = fields(result, 'draft_label', 'draft-wording')
    assert [f['raw'] for f in matched] == [label]
    assert matched[0]['code'] is None and 'official text version' in matched[0]['note']
    assert fields(result, 'subject_token')[0]['raw'] == subject


@pytest.mark.parametrize('subject', ['DiscussionDrafter', 'DiscussionDrafting', 'SubcommitteeDraftsmanship'])
def test_draft_wording_does_not_truncate_ordinary_word_endings(engine, subject):
    result = checked(engine, f'BILLS-118-{subject}-B000668-Amdt-1.pdf')
    assert not fields(result, 'draft_label', 'draft-wording')


@pytest.mark.parametrize('name', [
    'GrijalvaANS.pdf', 'CMT-AMD_01.pdf', 'CommitteePrint119-A.pdf',
    'HHRG-119-IF00-Wstate-DiscussionDraft-20250318.pdf',
])
def test_refinements_stay_within_legislative_fields(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] in {'attached-substitute','local-amendment-component','draft-wording','committee-print-subject'} for m in result['observations'])


def test_long_unsupported_case_boundary_is_bounded():
    subprocess.run([sys.executable, '-c',
        'from house_naming import Engine; Engine().extract("BILLS-118-" + "Aa" * 6000 + "ANSon-B000668-Amdt-1.pdf")'],
        capture_output=True, check=True, timeout=8)
