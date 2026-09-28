"""Explicit, mutually exclusive evidence states with separate overlapping issues."""
from collections import Counter, defaultdict
from committee_meeting.publication import CoverageMetric
from committee_meeting.provenance import Method


POSITIVE = ("observed", "reported", "curated", "derived", "inferred")
STATES = (*POSITIVE, "error", "blocked", "not_found_in_checked_scope", "not_applicable", "unknown", "unchecked")


def build(catalog, current, input_ids, *, states_out=None):
    selected = [r for r in catalog.records if (r.kind, r.id) in current]
    meetings = [r for r in selected if r.kind == "meeting"]
    index = {(r.kind, r.id): r for r in catalog.records}
    evidence = defaultdict(lambda: defaultdict(list))
    checks = defaultdict(lambda: defaultdict(list))
    recording_meetings = defaultdict(lambda: defaultdict(set))
    for r in selected:
        if r.kind == "material_link":
            meeting_id = r.subject.id if r.subject.kind == "meeting" else None
            if r.subject.kind in ("appearance", "occurrence"):
                meeting_id = index[(r.subject.kind, r.subject.id)].meeting.id
            if meeting_id:
                aspect = r.role if r.role in ("recording", "transcript", "captions") else "documents"
                evidence[meeting_id][aspect].append(r.provenance.basis)
                if aspect == "recording": recording_meetings[r.material.id][meeting_id].add(r.provenance.basis)
                if aspect == "transcript":
                    evidence[meeting_id]["documents"].append(r.provenance.basis)
        elif r.kind == "appearance" and set(r.roles).intersection(("witness", "nominee")):
            evidence[r.meeting.id]["witnesses"].append(r.provenance.basis)
        elif r.kind == "assessment" and r.subject.kind in ("meeting", "occurrence"):
            meeting_id = r.subject.id if r.subject.kind == "meeting" else index[(r.subject.kind, r.subject.id)].meeting.id
            checks[meeting_id][r.aspect].append(r)
    for r in selected:
        if r.kind == "assessment" and r.subject.kind == "material" and r.aspect == "captions":
            for meeting_id, bases in recording_meetings[r.subject.id].items():
                inherited = r
                if bases == {"inferred"}:
                    inherited = r.model_copy(update={"provenance": r.provenance.model_copy(update={"basis": "inferred"})})
                checks[meeting_id]["captions"].append(inherited)
    metrics, breakdown = [], {}
    for aspect in ("recording", "transcript", "documents", "witnesses", "captions"):
        counts = Counter({s: 0 for s in STATES})
        for meeting in meetings:
            basis = set(evidence[meeting.id][aspect])
            assessments = checks[meeting.id][aspect]
            basis.update(a.provenance.basis for a in assessments if a.status == "available")
            state = next((b for b in POSITIVE if b in basis), None)
            if state is None:
                statuses = {a.status for a in assessments}
                state = next((s for s in ("error", "blocked", "not_found", "not_applicable", "unknown") if s in statuses), "unchecked")
                if state == "not_found": state = "not_found_in_checked_scope"
            counts[state] += 1
            if states_out is not None:
                states_out.setdefault(meeting.id, {})[aspect] = state
        available = sum(counts[b] for b in POSITIVE)
        unknown = sum(counts[s] for s in ("error", "blocked", "unknown", "unchecked"))
        metrics.append(CoverageMetric(id=f"meetings-with-{aspect}", label=f"Meetings with {aspect} evidence", unit="meeting",
            population="Retained meetings from Congress.gov and official committee pages in the current export, all statuses. This measures supplied evidence, not expected publication or hearings held.",
            method=Method(name="committee-explorer.coverage.evidence-state", version="2"), input_snapshot_ids=tuple(input_ids),
            numerator=available, denominator=len(meetings), unknown=unknown, evidence_basis="mixed"))
        breakdown[aspect] = {"unit": "meeting", "denominator": len(meetings), "states": dict(counts),
            "rule": "One state per meeting: observed, reported, curated, derived, inferred; otherwise error, blocked, scoped not-found, not-applicable, unknown or unchecked. All checks remain in detail records."}
    return {"metrics": [m.model_dump(mode="json") for m in metrics], "state_breakdown": breakdown,
            "record_counts": dict(Counter(r.kind for r in selected)),
            "issue_counts": dict(Counter(r.category for r in selected if r.kind == "data_issue" and r.status == "open")),
            "current_issue_counts": dict(Counter(r.category for r in selected if r.kind == "data_issue" and r.status == "open")),
            "retained_issue_counts": dict(Counter(r.category for r in catalog.records if r.kind == "data_issue" and r.status == "open")),
            "historical_issue_counts": dict(Counter(r.category for r in catalog.records if r.kind == "data_issue" and r.status == "open" and (r.kind, r.id) not in current)),
            "assessment_counts": dict(Counter(r.status for r in selected if r.kind == "assessment")),
            "limitations": ["Evidence states are mutually exclusive within each aspect; issue and check totals overlap and must not be summed as completeness.",
                            "Current issue counts describe this selection; retained counts include current and historical issues. Historical counts are the difference, not an additional coverage population.",
                            "Reported or inferred availability does not establish checked URLs, captured bytes, full coverage, or searchable text.",
                            "Canceled, postponed, closed and future entries remain in this source-entry inventory; unchecked does not mean a publication failure.",
                            "Materials are source-described records; independent listings without identity evidence remain distinct."]}
