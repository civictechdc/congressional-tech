"""Collector decisions cite their retained record; publisher facts cite the page."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from committee_explorer.export import validate_selectors
from committee_meeting.common import Ref
from congress_api.adapters.senate import official_events, records
from congress_api.models.senate import SenateSite
from test_explorer_senate_adapter import PAGE, context, of_kind, page


def saved_state(workflow, storage):
    publisher = page()
    publisher.pop('events')
    site = {'pages': {PAGE: deepcopy(publisher)}}
    if storage == 'legacy':
        site['pages'][PAGE].update(deepcopy(workflow))
    else:
        site['workflow'] = {PAGE: deepcopy(workflow)}
    if storage == 'model':
        site = SenateSite.model_validate(site)
    return {'example.senate.gov': site}, publisher


@pytest.mark.parametrize('storage', ['legacy', 'separate', 'model'])
@pytest.mark.parametrize('details', [False, True])
def test_match_citations_resolve_to_collector_state_and_witness_cites_page(storage, details):
    workflow = {'events': ['12']}
    if details:
        workflow['match_details'] = {'12': {'method': 'senate.records.match_pages', 'version': '2'}}
    state, publisher = saved_state(workflow, storage)
    rows = list(records(state, context(), meetings={(119, 'senate', '12'): Ref(kind='meeting', id='meeting-12')}))
    sources = {row.id: row for row in of_kind(rows, 'source_record')}
    validate_selectors(SimpleNamespace(sources=sources.values(), records=[r for r in rows if r.kind != 'source_record']))
    appearance, = of_kind(rows, 'appearance')
    match, witness = appearance.provenance.citations
    assert match.source.id != witness.source.id
    assert sources[match.source.id].payload == workflow
    assert sources[witness.source.id].payload == publisher
    assert match.selector == ('/match_details/12' if details else '/events/0')
    assert witness.selector == '/witnesses/0'
    assert appearance.meeting.id == 'meeting-12'


@pytest.mark.parametrize('storage', ['legacy', 'separate', 'model'])
@pytest.mark.parametrize('workflow,selector,summary', [
    ({'events': ['missing']}, '/events/0', 'A saved page association'),
    ({'candidate_events': ['12']}, '/candidate_events', 'The official event may already'),
    ({'events': ['12'], 'last_check': {'mode': 'live', 'outcome': 'error',
        'completed_at': '2026-09-26T11:00:00+00:00'}}, '/last_check', 'The latest Senate page refresh failed'),
])
def test_workflow_issues_and_assessments_keep_resolvable_citations(storage, workflow, selector, summary):
    state, publisher = saved_state(workflow, storage)
    rows = list(records(state, context(), meetings={(119, 'senate', '12'): Ref(kind='meeting', id='meeting-12')}))
    sources = {row.id: row for row in of_kind(rows, 'source_record')}
    validate_selectors(SimpleNamespace(sources=sources.values(), records=[r for r in rows if r.kind != 'source_record']))
    issue, = [r for r in of_kind(rows, 'data_issue') if r.summary.startswith(summary)]
    citation, = issue.provenance.citations
    assert citation.selector == selector
    assert sources[citation.source.id].payload == workflow
    assert sources[issue.subject.id].payload == publisher
    if selector == '/last_check':
        assessment, = of_kind(rows, 'assessment')
        assert assessment.status == 'error'
        assert any(c.selector == '/last_check' for c in assessment.provenance.citations)
    else:
        assert not of_kind(rows, 'appearance')


@pytest.mark.parametrize('storage', ['legacy', 'separate', 'model'])
def test_readers_leave_caller_state_unchanged_and_replay_identically(storage):
    state, _ = saved_state({'events': ['12'], 'candidate_events': []}, storage)
    original = deepcopy(state)
    list(official_events(state))
    assert state == original
    first = list(records(state, context(), meetings={}))
    assert state == original
    assert list(records(state, context(), meetings={})) == first
    assert state == original
