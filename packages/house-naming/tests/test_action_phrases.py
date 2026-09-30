"""Filename action wording is evidence, not a verified event or actor identity."""
import pytest

from house_naming import Engine


RULES = {'ordered-reported-wording', 'legislative-text-wording', 'action-by-wording'}


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert name[f['start']:f['end']] == f['raw']
    matches = [m for m in result['observations'] if m['rule'] in RULES]
    assert all(f['code'] is None and f['label'] is None and f['context'] is None and not f['candidates']
               for m in matches for f in m['fields'])
    return result, matches


@pytest.mark.parametrize('name,expected', [
    ('BILLS-1153170ih-orderedreportedvoicevote.pdf', {'qualifier_wording': 'orderedreported', 'vote_wording': 'voicevote'}),
    ('BILLS-1154743rh-orderedreportedasamendedvoicevote.pdf', {'qualifier_wording': 'orderedreportedasamended', 'vote_wording': 'voicevote'}),
    ('BILLS-1155178rh-orderedreportedvoicevote.pdf', {'qualifier_wording': 'orderedreported', 'vote_wording': 'voicevote'}),
    ('Ordered Reported As Amended By Voice Vote.pdf', {'qualifier_wording': 'Ordered Reported As Amended', 'vote_wording': 'By Voice Vote'}),
    ('Ordered Reported.pdf', {'qualifier_wording': 'Ordered Reported'}),
    ('Ordered-Reported-Voice-Votepdf.pdf', {'qualifier_wording': 'Ordered-Reported', 'vote_wording': 'Voice-Vote'}),
    ('OrderedReportedVoiceVote&download=1', {'qualifier_wording': 'OrderedReported', 'vote_wording': 'VoiceVote'}),
])
def test_reported_and_vote_phrases_keep_literal_fields(engine, name, expected):
    result, matches = checked(engine, name)
    match, = [m for m in matches if m['rule'] == 'ordered-reported-wording']
    assert {f['name']: f['raw'] for f in match['fields']} == expected
    for field in match['fields']:
        if field['name'] == 'vote_wording':
            assert field['note'] == 'Printed voting-method wording; no vote occurrence, count, passage or result is verified.'
        else:
            assert 'not verified' in field['note']
    if name.startswith('BILLS-'):
        assert any(f['name'] == 'version_token' and f['code'] for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name,label,qualifier', [
    ('BILLS-119pih-LegislativeText.pdf', 'LegislativeText', None),
    ('BILLS-119pih-LegislativeTextasReportedOutofCommittee.pdf', 'LegislativeText', 'asReportedOutofCommittee'),
    ('budget-committee-reconciliation-legislative-text', 'legislative-text', None),
    ('budget-committee-reconciliation-legislative-text&download=1', 'legislative-text', None),
    ('budget_committee_reconciliation_legislative_text.pdf', 'legislative_text', None),
    ('Legislative Text As Reported Out of Committee.pdf', 'Legislative Text', 'As Reported Out of Committee'),
    ('LegislativeTextAsReportedpdf.pdf', 'LegislativeText', 'AsReported'),
])
def test_legislative_text_phrase_keeps_prefix_and_qualifier(engine, name, label, qualifier):
    _, matches = checked(engine, name)
    match, = matches
    assert match['rule'] == 'legislative-text-wording'
    expected = {'label': label}
    if qualifier:
        expected['qualifier_wording'] = qualifier
    assert {f['name']: f['raw'] for f in match['fields']} == expected


@pytest.mark.parametrize('name,qualifier,relation,target', [
    ('BILLS-113HR2413ih-HR2413asamendedbyEnvironmentSubcommittee.pdf', 'asamended', 'by', 'EnvironmentSubcommittee'),
    ('HR1029 as reported by the Committee.pdf', 'as reported', 'by', 'the Committee'),
    ('hr-1029-as-reported-by-the-committee', 'as-reported', 'by', 'the-committee'),
    ('redline_hr3633_reportedbyagriculture_vs_rcp.pdf', 'reported', 'by', 'agriculture'),
    ('redline_hr3633_reportedbyfinancialservices_vs_rcp.pdf', 'reported', 'by', 'financialservices'),
    ('Reported By Unknown Organization.pdf', 'Reported', 'By', 'Unknown Organization'),
    ('ReportedBySomeCommittee.pdf', 'Reported', 'By', 'SomeCommittee'),
    ('as_reported_by_the_Committeepdf.pdf', 'as_reported', 'by', 'the_Committee'),
    ('As Reported By the Committee&download=1', 'As Reported', 'By', 'the Committee'),
])
def test_by_relation_keeps_unresolved_actor_text(engine, name, qualifier, relation, target):
    result, matches = checked(engine, name)
    match, = [m for m in matches if m['rule'] == 'action-by-wording']
    assert {f['name']: f['raw'] for f in match['fields']} == {
        'qualifier_wording': qualifier, 'relation_wording': relation, 'target_subject': target,
    }
    assert all('identity' in f['note'] for f in match['fields'] if f['name'] in {'relation_wording', 'target_subject'})
    assert not any(f['name'] in {'committee_id', 'person_id', 'vote_result', 'action_date'}
                   for m in result['observations'] for f in m['fields'])
    if '_vs_rcp' in name:
        assert name[match['end']:] == '_vs_rcp.pdf'


@pytest.mark.parametrize('name', [
    'DisorderedReported.pdf', 'OrderedReporter.pdf',
    'OrderedReportedasAmendedly.pdf', 'OrderedReportedVoiceVoteman.pdf',
    'Topic%20OrderedReportedVoiceVote.pdf',
    'PreLegislativeText.pdf', 'LegislativeTexture.pdf',
    'LegislativeTextasReportedOutofCommitteeman.pdf',
    'Topic%20LegislativeText.pdf',
    'UnreportedByCommittee.pdf', 'ReportedBy.pdf',
    'AmendedBylaws.pdf', 'Reported Bylaws.pdf', 'Reportedbylaw.pdf',
    'ReportedBy12345.pdf', 'ReportedByCommittee123.pdf',
    'ReportedBythe%20Committee.pdf', 'Topic%20ReportedByCommittee.pdf',
    'HHRG-119-IF00-Wstate-OrderedReportedVoiceVote-20250318.pdf',
    'HHRG-119-IF00-Wstate-LegislativeText-20250318.pdf',
    'HHRG-119-IF00-Wstate-ReportedByCommittee-20250318.pdf',
])
def test_unsupported_boundaries_and_protected_slots(engine, name):
    _, matches = checked(engine, name)
    assert matches == []


def test_concrete_identifier_does_not_become_actor_text(engine):
    _, matches = checked(engine, 'Reported By ABCDEF1234567890.pdf')
    assert matches == []


def test_prior_short_qualifiers_and_references_remain(engine):
    result, matches = checked(engine, 'HR1029 as reported by the Committee.pdf')
    assert any(m['rule'] == 'edition-wording' and any(f['raw'] == 'as reported' for f in m['fields'])
               for m in result['observations'])
    assert any(f['name'] == 'measure_number' and f['raw'] == '1029' for m in result['observations'] for f in m['fields'])
    assert len(matches) == 1


def test_full_raw_actor_is_retained_without_resolving_a_person(engine):
    _, matches = checked(engine, 'Reported By Smith.pdf')
    assert matches[0]['fields'][-1]['raw'] == 'Smith'
    assert matches[0]['fields'][-1]['name'] == 'target_subject'
