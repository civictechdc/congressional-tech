"""Explicit, mutually exclusive evidence states with separate overlapping issues."""
from collections import Counter, defaultdict
from committee_meeting.publication import CoverageMetric
from committee_meeting.provenance import Method


POSITIVE = ("observed", "reported", "curated", "derived", "inferred")
STATES = (*POSITIVE, "error", "blocked", "not_found_in_checked_scope", "not_applicable", "unknown", "unchecked")


def build(catalog, current, input_ids, *, states_out=None):
    import sys

    meeting_ids = []
    owner_meeting = {}
    evidence = defaultdict(lambda: defaultdict(set))
    checks = defaultdict(lambda: defaultdict(set))
    recording_meetings = defaultdict(lambda: defaultdict(set))
    pending_links = []
    pending_occurrence_assessments = []
    material_caption_assessments = []
    record_counts = Counter()
    current_issue_counts = Counter()
    retained_issue_counts = Counter()
    historical_issue_counts = Counter()
    assessment_counts = Counter()

    def _apply_link(meeting_id, role, material_id, basis):
        if not meeting_id:
            return
        b = sys.intern(basis)
        aspect = role if role in ("recording", "transcript", "captions") else "documents"
        evidence[meeting_id][aspect].add(b)
        if aspect == "recording":
            recording_meetings[material_id][meeting_id].add(b)
        if aspect == "transcript":
            evidence[meeting_id]["documents"].add(b)

    if hasattr(catalog.records, "iter_keys") and hasattr(catalog.records, "iter_kind"):
        for key in catalog.records.iter_keys():
            if key in current:
                record_counts[key[0]] += 1
        records_iter = (
            r
            for kind in ("appearance", "occurrence", "data_issue", "meeting", "material_link", "assessment")
            for r in catalog.records.iter_kind(kind)
        )
        count_inline = False
    else:
        records_iter = iter(catalog.records)
        count_inline = True

    for r in records_iter:
        key = (r.kind, r.id)
        is_current = key in current
        if r.kind in ("appearance", "occurrence"):
            owner_meeting[key] = r.meeting.id
        if r.kind == "data_issue" and r.status == "open":
            retained_issue_counts[r.category] += 1
            if is_current:
                current_issue_counts[r.category] += 1
            else:
                historical_issue_counts[r.category] += 1
        if not is_current:
            continue
        if count_inline:
            record_counts[r.kind] += 1
        if r.kind == "meeting":
            meeting_ids.append(r.id)
        elif r.kind == "material_link":
            if r.subject.kind == "meeting":
                _apply_link(r.subject.id, r.role, r.material.id, r.provenance.basis)
            elif r.subject.kind in ("appearance", "occurrence"):
                subj_key = (r.subject.kind, r.subject.id)
                if subj_key in owner_meeting:
                    _apply_link(owner_meeting[subj_key], r.role, r.material.id, r.provenance.basis)
                else:
                    pending_links.append((subj_key, r.role, r.material.id, r.provenance.basis))
        elif r.kind == "appearance" and set(r.roles).intersection(("witness", "nominee")):
            evidence[r.meeting.id]["witnesses"].add(sys.intern(r.provenance.basis))
        elif r.kind == "assessment":
            status = sys.intern(r.status)
            basis = sys.intern(r.provenance.basis)
            aspect = sys.intern(r.aspect)
            assessment_counts[status] += 1
            if r.subject.kind == "meeting":
                checks[r.subject.id][aspect].add((status, basis))
            elif r.subject.kind == "occurrence":
                pending_occurrence_assessments.append((r.subject.id, aspect, status, basis))
            elif r.subject.kind == "material" and aspect == "captions":
                material_caption_assessments.append((r.subject.id, status, basis))

    for subj_key, role, material_id, basis in pending_links:
        _apply_link(owner_meeting[subj_key], role, material_id, basis)
    for occ_id, aspect, status, basis in pending_occurrence_assessments:
        meeting_id = owner_meeting[("occurrence", occ_id)]
        checks[meeting_id][aspect].add((status, basis))
    for mat_id, status, basis in material_caption_assessments:
        for meeting_id, bases in recording_meetings[mat_id].items():
            inherited_basis = "inferred" if bases == {"inferred"} else basis
            checks[meeting_id]["captions"].add((status, inherited_basis))
    del owner_meeting, recording_meetings, pending_links, pending_occurrence_assessments, material_caption_assessments

    metrics, breakdown = [], {}
    for aspect in ("recording", "transcript", "documents", "witnesses", "captions"):
        counts = Counter({s: 0 for s in STATES})
        for meeting_id in meeting_ids:
            basis = set(evidence[meeting_id][aspect])
            assessments = checks[meeting_id][aspect]
            basis.update(a_basis for a_status, a_basis in assessments if a_status == "available")
            state = next((b for b in POSITIVE if b in basis), None)
            if state is None:
                statuses = {a_status for a_status, _ in assessments}
                state = next((s for s in ("error", "blocked", "not_found", "not_applicable", "unknown") if s in statuses), "unchecked")
                if state == "not_found": state = "not_found_in_checked_scope"
            counts[state] += 1
            if states_out is not None:
                states_out.setdefault(meeting_id, {})[aspect] = state
        available = sum(counts[b] for b in POSITIVE)
        unknown = sum(counts[s] for s in ("error", "blocked", "unknown", "unchecked"))
        metrics.append(CoverageMetric(id=f"meetings-with-{aspect}", label=f"Meetings with {aspect} evidence", unit="meeting",
            population="Retained meetings from Congress.gov and official committee pages in the current export, all statuses. This measures supplied evidence, not expected publication or hearings held.",
            method=Method(name="committee-explorer.coverage.evidence-state", version="2"), input_snapshot_ids=tuple(input_ids),
            numerator=available, denominator=len(meeting_ids), unknown=unknown, evidence_basis="mixed"))
        breakdown[aspect] = {"unit": "meeting", "denominator": len(meeting_ids), "states": dict(counts),
            "rule": "One state per meeting: observed, reported, curated, derived, inferred; otherwise error, blocked, scoped not-found, not-applicable, unknown or unchecked. All checks remain in detail records."}
    return {"metrics": [m.model_dump(mode="json") for m in metrics], "state_breakdown": breakdown,
            "record_counts": dict(record_counts),
            "issue_counts": dict(current_issue_counts),
            "current_issue_counts": dict(current_issue_counts),
            "retained_issue_counts": dict(retained_issue_counts),
            "historical_issue_counts": dict(historical_issue_counts),
            "assessment_counts": dict(assessment_counts),
            "limitations": ["Evidence states are mutually exclusive within each aspect; issue and check totals overlap and must not be summed as completeness.",
                            "Current issue counts describe this selection; retained counts include current and historical issues. Historical counts are the difference, not an additional coverage population.",
                            "Reported or inferred availability does not establish checked URLs, captured bytes, full coverage, or searchable text.",
                            "Canceled, postponed, closed and future entries remain in this source-entry inventory; unchecked does not mean a publication failure.",
                            "Materials are source-described records; independent listings without identity evidence remain distinct."]}
