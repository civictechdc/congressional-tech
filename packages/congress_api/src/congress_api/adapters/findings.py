"""Translate decisions emitted by existing matchers; do not reimplement rules."""
from collections import defaultdict
from committee_meeting.common import Ref
from committee_meeting.materials import MaterialLink
from committee_meeting.provenance import Citation, Method, Provenance
from .common import ref


def print_links(decisions, context, *, meetings, versions):
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        by_event[event].append(meeting)
    for decision in decisions:
        event, package = decision["event_id"], decision["package_id"]
        if len(by_event[event]) != 1 or package not in versions:
            continue
        source = context.source(f"{event}|{package}|{decision['rule']}", decision)
        yield source
        meeting = by_event[event][0]
        material, version = versions[package]
        evidence = context.evidence(source, basis=decision.get("basis", "derived"),
                                    method=Method(name="congress_api.inventory.prints." + decision["rule"], version=decision["rule_version"]))
        yield MaterialLink(id=context.ids("material_link", f"govinfo:{package}:meeting:{meeting.id}"), material=material, version=version,
                           subject=meeting, role="transcript", provenance=evidence)
