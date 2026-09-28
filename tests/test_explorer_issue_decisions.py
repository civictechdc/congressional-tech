"""Retained review decisions can be replayed without changing their evidence."""
from dataclasses import replace
from datetime import timedelta

import pytest

from committee_meeting import Catalog
from committee_meeting.common import Ref
from committee_meeting.issues import DataIssue
from committee_explorer.issues import apply_decisions
from test_explorer_material_adapters import context


def fixture():
    source_context = context('official')
    source = source_context.source('record', {'value': 'unverified'})
    issue = DataIssue(id='issue-1', subject=Ref(kind='source_record', id=source.id),
                      category='unverified', summary='Source needs review', detected_at=source_context.now,
                      provenance=source_context.evidence(source))
    catalog = Catalog(sources=(source,), records=(issue,))
    decision_context = context('curated-issue-decisions')
    decision = {'issue_id': issue.id, 'status': 'dismissed', 'explanation': 'Reviewed source limitation.'}
    return catalog, decision, decision_context


@pytest.mark.parametrize('explicit_time', [False, True])
def test_same_decision_is_idempotent_at_same_and_later_import_times(explicit_time):
    original, row, ctx = fixture()
    if explicit_time:
        row['decided_at'] = ctx.now.isoformat()
    first = apply_decisions(original, [row], ctx)
    assert len(first.sources) == 2
    assert apply_decisions(first, [row], ctx) == first
    later = replace(ctx, now=ctx.now + timedelta(days=2))
    replay = apply_decisions(first, [row], later)
    assert replay == first
    assert replay.records[0].resolution.decided_at == ctx.now
    assert replay.records[0].provenance == original.records[0].provenance


def test_changed_decision_keeps_previous_observation_and_has_new_cited_source():
    catalog, row, ctx = fixture()
    first = apply_decisions(catalog, [row], ctx)
    updated = dict(row, status='resolved', explanation='A subsequent source update resolves the limitation.')
    later = replace(ctx, now=ctx.now + timedelta(days=2))
    second = apply_decisions(first, [updated], later)
    assert len(second.sources) == 3
    assert set(s.id for s in first.sources) < set(s.id for s in second.sources)
    issue = second.records[0]
    assert issue.status == 'resolved' and issue.resolution.decided_at == later.now
    assert issue.resolution.provenance.citations != first.records[0].resolution.provenance.citations
    assert issue.provenance == first.records[0].provenance


def test_repeated_issue_within_one_batch_is_still_rejected():
    catalog, row, ctx = fixture()
    with pytest.raises(ValueError, match='Repeated issue decision'):
        apply_decisions(catalog, [row, row], ctx)
    assert len(catalog.sources) == 1 and catalog.records[0].status == 'open'


def test_same_source_id_cannot_silently_replace_different_evidence():
    catalog, row, ctx = fixture()
    first = apply_decisions(catalog, [row], ctx)
    source_id = first.records[0].resolution.provenance.citations[0].source.id
    collision = replace(ctx, ids=lambda kind, key: source_id)
    with pytest.raises(ValueError, match='Conflicting issue decision source'):
        apply_decisions(first, [dict(row, explanation='Different evidence')], collision)
