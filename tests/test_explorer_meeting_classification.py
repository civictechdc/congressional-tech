"""Explicit source labels and title phrases stay separate from agenda topics."""
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import pytest

from congress_api.adapters.common import AdapterContext
from congress_api.adapters.meetings import meeting_access, meeting_type, records


@pytest.mark.parametrize('title,expected', [
    ('To receive a closed briefing on the budget.', 'briefing'),
    ('To receive a joint closed briefing on Iran.', 'briefing'),
    ('To received a closed briefing on policy developments.', 'briefing'),
    ('Receive a closed briefing on the Sentinel program.', 'briefing'),
    ('Full Committee Member Briefing on NASA’s Independent Study Report', 'briefing'),
    ('"Briefing: The North Korean Threat: Nuclear, Missiles and Cyber"', 'briefing'),
    ('Hearings to examine proposed budget estimates.', 'hearing'),
    ('An oversight hearing to examine the Securities and Exchange Commission.', 'hearing'),
    ('A joint hearing with the House Committee on Veterans Affairs.', 'hearing'),
    ('Open and closed hearings to examine worldwide threats.', 'hearing'),
    ('Hearings to examine a nomination; to be followed by a business meeting.', 'hearing'),
    ('Closed business meeting to consider nominations; followed by a closed briefing.', 'business'),
    ('House Administration Full Committee Business Meeting', 'business'),
    ('RESCHEDULED: Full Committee Business Meeting', 'business'),
    ('Full Committee Organizational/Business Meeting (Closed)', 'business'),
    ('Full Committee Markup', 'markup'),
    ('Mark up for reconciliation pursuant to S. Con. Res. 5', 'markup'),
    ('Joint field hearing on rural access', 'field_hearing'),
])
def test_generic_source_type_uses_explicit_proceeding_title(title, expected):
    assert meeting_type({'type': 'Meeting', 'title': title}) == (expected, '/title')
    assert meeting_type({'title': title}) == (expected, '/title')


@pytest.mark.parametrize('title', [
    'To Consider a Resolution to Enable a Joint Hearing and Participation at a Briefing',
    'Meeting in the main hearing room to consider the oversight plan',
    'The Hearing Protection Act',
    'Hearing protection for industrial workers',
    'Small business lending',
    'Roundtable on railroad shippers',
])
def test_titles_without_an_explicit_supported_event_type_stay_generic(title):
    assert meeting_type({'type': 'Meeting', 'title': title}) == ('meeting', '/type')
    assert meeting_type({'title': title}) == ('unknown', '/type')


@pytest.mark.parametrize('native,title,expected', [
    ('Closed Hearing', 'To receive a closed briefing on intelligence', 'hearing'),
    ('Markup', 'Full Committee Business Meeting', 'markup'),
    ('Hearing', 'Field hearing on rural access', 'hearing'),
    ('Briefing', 'Full Committee Business Meeting', 'briefing'),
    ('Unrecognized source label', 'Briefing on intelligence', 'unknown'),
])
def test_specific_native_type_wins_over_title(native, title, expected):
    assert meeting_type({'type': native, 'title': title}) == (expected, '/type')


@pytest.mark.parametrize('title,expected', [
    ('To receive a closed briefing on the budget.', 'closed'),
    ('To receive a joint closed briefing on Iran.', 'closed'),
    ('To receive a closed\u00a0briefing on intelligence.', 'closed'),
    ('Ongoing Intelligence Activities (Closed)', 'closed'),
    ('FY 2020 Defense Subcommittee Markup [Closed]', 'closed'),
    ('Open Panel with Think Tank Experts', 'open'),
    ('Annual Threat Assessment (Open Session)', 'open'),
    ('Business Meeting (Open in a Closed Space)', 'open'),
    ('Testimony of Carter Page (Open Hearing in a Closed Space)', 'open'),
    ('Consideration of a Committee Report (Open - Possibility of Closing)', 'open'),
    ('Russia Investigation Task Force Hearing (Open & Closed)', 'partly_closed'),
    ('Open and closed hearings to examine worldwide threats.', 'partly_closed'),
    ('Closed hearings; to be followed by an open session at 9:30 a.m.', 'partly_closed'),
    ('Open hearings; to be immediately followed by a closed session.', 'partly_closed'),
    ('Closed hearings; to be immediately followed by a closed session.', 'closed'),
    ('Hearings with the possibility of a closed session following the open session.', 'open'),
])
def test_access_requires_an_explicit_source_phrase(title, expected):
    assert meeting_access({'type': 'Meeting', 'title': title}) == (expected, '/title')


@pytest.mark.parametrize('title', [
    'Open Borders, Closed Case: Secretary Mayorkas’ Dereliction of Duty',
    'Improving the Closed School Discharge Process',
    'The Impacts of Closed-Door Settlements on Endangered Species',
    'Joint hearing to examine the Open Skies Treaty',
    'Hearing on open-source software cybersecurity',
    'Hearing to consider S.2009, allowing disciplinary proceedings to be open to the public.',
    'Hearings with the possibility of a closed session.',
    'Hearings; to be immediately followed by a closed session.',
    'Hearings; to be immediately preceded by a closed hearing.',
    'Business meeting; to be followed by a closed briefing.',
    'A briefing on the annual budget',
])
def test_topics_and_uncertain_or_secondary_access_do_not_classify_entire_meeting(title):
    assert meeting_access({'type': 'Hearing', 'title': title}) == ('unknown', None)


@pytest.mark.parametrize('native,title,expected', [
    ('Open Hearing', 'Open borders policy', 'open'),
    ('Open Business Meeting', 'Closed session', 'open'),
    ('Closed Hearing', 'Closed hearings followed by an open session', 'closed'),
    ('Closed Markup Session', 'Markup', 'closed'),
    ('Open and Closed Hearing', 'Hearing', 'partly_closed'),
])
def test_explicit_native_access_wins(native, title, expected):
    assert meeting_access({'type': native, 'title': title}) == (expected, '/type')


def test_derived_classification_preserves_native_payload_and_field_evidence():
    row = {'eventId': '325783', 'congress': 116, 'chamber': 'Senate', 'type': 'Meeting',
           'title': 'To receive a closed briefing on issues related to Hungary and Russia.'}
    context = AdapterContext(datetime(2026, 9, 28, tzinfo=timezone.utc), 'input', 'congress.gov',
                             lambda kind, key: str(uuid5(NAMESPACE_URL, kind + key)))
    result = list(records([row], context))
    source = next(r for r in result if r.kind == 'source_record')
    meeting = next(r for r in result if r.kind == 'meeting')
    occurrence = next(r for r in result if r.kind == 'occurrence')
    assert source.payload == row and source.payload['type'] == 'Meeting'
    assert meeting.meeting_type == 'briefing' and occurrence.access == 'closed'
    for record, field in ((meeting, '/meeting_type'), (occurrence, '/access')):
        evidence = record.field_evidence[0]
        assert evidence.path == field
        assert evidence.selected.basis == 'derived'
        assert evidence.selected.citations[0].source.id == source.id
        assert evidence.selected.citations[0].selector == '/title'
