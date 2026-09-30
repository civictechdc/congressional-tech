"""Translate decisions emitted by existing matchers; do not reimplement rules."""

from collections import defaultdict

from committee_meeting.issues import DataIssue
from committee_meeting.materials import MaterialLink
from committee_meeting.provenance import Method

from congress_api.adapters.common import ref


def print_links(decisions, context, *, meetings, versions):
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        by_event[str(event)].append(meeting)
    for decision in decisions:
        event, package = str(decision.get("event_id") or ""), decision["package_id"]
        source = context.source(f"{event}|{package}|{decision['rule']}", decision)
        yield source
        evidence = context.evidence(
            source, basis=decision.get("basis", "derived"),
            method=Method(name="congress_api.inventory.prints." + decision["rule"], version=decision["rule_version"]),
        )
        candidates = by_event.get(event, [])
        if len(candidates) != 1:
            yield DataIssue(
                id=context.ids("data_issue", source.id + "|unlinked"),
                subject=ref(source), category="unlinked",
                summary="The retained print decision has no unique meeting association.",
                explanation=f"Event {event} resolves to {len(candidates)} entries in the supplied meeting lookup.",
                detected_at=context.now, provenance=evidence,
            )
            continue
        if package not in versions:
            yield DataIssue(
                id=context.ids("data_issue", source.id + "|missing-version"),
                subject=ref(source), category="unlinked",
                summary="The retained print decision's package is not present in this catalog.",
                explanation="The original decision is retained without inventing a document or meeting link.",
                detected_at=context.now, provenance=evidence,
            )
            continue
        meeting = candidates[0]
        material, version = versions[package]
        yield MaterialLink(
            id=context.ids("material_link", f"govinfo:{package}:meeting:{meeting.id}"),
            material=material, version=version, subject=meeting, role="transcript", provenance=evidence,
        )
