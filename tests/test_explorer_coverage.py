"""Coverage counts subjects once and keeps evidence strength and gaps visible."""
from datetime import date, datetime, timezone
import unittest

from committee_explorer.coverage import POSITIVE, STATES, build
from committee_meeting import Catalog
from committee_meeting.assessments import Assessment
from committee_meeting.common import Identifier, Ref, ReportedTime
from committee_meeting.issues import DataIssue, IssueResolution
from committee_meeting.materials import DocumentDetails, Material, MaterialLink, RecordingDetails, TextDetails
from committee_meeting.meetings import Appearance, Meeting, MeetingOccurrence, RecordedName
from committee_meeting.provenance import Citation, Method, Provenance, SourceRecord


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


class Graph:
    def __init__(self):
        self.source = SourceRecord(id="fixture-source", provider="fixture", identifier=Identifier(scheme="fixture", value="one"), payload={})
        self.records = []
        self.current = set()

    def evidence(self, basis="reported"):
        return Provenance(citations=(Citation(source=Ref(kind="source_record", id=self.source.id)),), basis=basis,
                          method=Method(name="fixture-method", version="1") if basis in ("derived", "inferred") else None)

    def add(self, record, current=True):
        self.records.append(record)
        if current:
            self.current.add((record.kind, record.id))
        return Ref(kind=record.kind, id=record.id)

    def meeting(self, name, current=True):
        return self.add(Meeting(id=name, title=name, provenance=self.evidence()), current)

    def material(self, name, recording=False):
        return self.add(Material(id=name, details=RecordingDetails(medium="video") if recording else DocumentDetails(category="statement"),
                                 provenance=self.evidence()))

    def link(self, name, material, subject, role="recording", basis="reported", coverage="unknown"):
        return self.add(MaterialLink(id=name, material=material, subject=subject, role=role, coverage=coverage, provenance=self.evidence(basis)))

    def assessment(self, name, subject, status, aspect="recording", basis="reported"):
        return self.add(Assessment(id=name, subject=subject, aspect=aspect, status=status,
                                   evaluated_at=NOW, observed_at=NOW if status == "not_found" else None,
                                   scope="A specific retained source page" if status == "not_found" else None,
                                   provenance=self.evidence(basis)))

    def issue(self, name, subject, category, current=True, closed=False):
        return self.add(DataIssue(id=name, subject=subject, category=category,
                                  expected="A source-listed item" if category == "missing" else None,
                                  summary=name, detected_at=NOW, provenance=self.evidence(),
                                  status="resolved" if closed else "open",
                                  resolution=IssueResolution(decided_at=NOW, explanation="Documented correction", provenance=self.evidence()) if closed else None), current)

    def result(self):
        catalog = Catalog(sources=(self.source,), records=tuple(self.records))
        return build(catalog, self.current, ["retained-input-one"])


def metric(result, aspect):
    return next(m for m in result["metrics"] if m["id"] == "meetings-with-" + aspect)


class CoverageTests(unittest.TestCase):
    def test_exclusive_states_sum_to_the_subject_population(self):
        graph = Graph()
        for state in STATES:
            meeting = graph.meeting("meeting-" + state)
            if state in POSITIVE:
                graph.assessment("check-" + state, meeting, "available", basis=state)
            elif state != "unchecked":
                graph.assessment("check-" + state, meeting,
                                 "not_found" if state == "not_found_in_checked_scope" else state)
        result = graph.result()
        recording = result["state_breakdown"]["recording"]
        self.assertEqual(recording["states"], {state: 1 for state in STATES})
        for aspect, breakdown in result["state_breakdown"].items():
            self.assertEqual(sum(breakdown["states"].values()), breakdown["denominator"], aspect)
            self.assertEqual(breakdown["denominator"], len(STATES))
        count = metric(result, "recording")
        self.assertEqual(count["numerator"], len(POSITIVE))
        self.assertEqual(count["unknown"], 4)  # Error, blocked, unknown and unchecked.
        self.assertEqual(count["input_snapshot_ids"], ["retained-input-one"])

    def test_overlapping_positive_evidence_does_not_count_one_meeting_twice(self):
        graph = Graph()
        meeting = graph.meeting("one")
        material = graph.material("video", recording=True)
        graph.link("partial-video", material, meeting, basis="reported", coverage="partial")
        graph.assessment("inference", meeting, "available", basis="inferred")
        graph.assessment("other-source-failed", meeting, "error")
        result = graph.result()
        self.assertEqual(metric(result, "recording")["numerator"], 1)
        self.assertEqual(result["state_breakdown"]["recording"]["states"]["reported"], 1)
        self.assertEqual(result["state_breakdown"]["recording"]["states"]["inferred"], 0)
        self.assertEqual(result["assessment_counts"], {"available": 1, "error": 1})

    def test_reported_and_inferred_records_remain_separate_states(self):
        graph = Graph()
        for basis in ("reported", "inferred"):
            meeting = graph.meeting(basis)
            graph.link("link-" + basis, graph.material("video-" + basis, recording=True), meeting, basis=basis)
        states = graph.result()["state_breakdown"]["recording"]["states"]
        self.assertEqual(states["reported"], 1)
        self.assertEqual(states["inferred"], 1)
        self.assertEqual(states["observed"], 0)

    def test_failed_blocked_unknown_and_unchecked_are_distinct(self):
        graph = Graph()
        for state in ("error", "blocked", "unknown", "unchecked"):
            meeting = graph.meeting(state)
            if state != "unchecked":
                graph.assessment("check-" + state, meeting, state)
        states = graph.result()["state_breakdown"]["recording"]["states"]
        self.assertEqual({s: states[s] for s in ("error", "blocked", "unknown", "unchecked")},
                         {s: 1 for s in ("error", "blocked", "unknown", "unchecked")})
        self.assertEqual(states["not_found_in_checked_scope"], 0)

    def test_issue_counts_overlap_without_inflating_coverage_and_name_historical_scope(self):
        graph = Graph()
        current = graph.meeting("current")
        old = graph.meeting("retained-only", current=False)
        graph.issue("missing-one", current, "missing")
        graph.issue("missing-two", current, "missing")
        graph.issue("unverified", current, "unverified")
        graph.issue("old-conflict", old, "conflicting", current=False)
        graph.issue("resolved", current, "missing", closed=True)
        result = graph.result()
        self.assertEqual(result["current_issue_counts"], {"missing": 2, "unverified": 1})
        self.assertEqual(result["retained_issue_counts"], {"missing": 2, "unverified": 1, "conflicting": 1})
        self.assertEqual(result["historical_issue_counts"], {"conflicting": 1})
        self.assertEqual(result["issue_counts"], result["current_issue_counts"])
        self.assertGreater(sum(result["issue_counts"].values()), metric(result, "recording")["denominator"])
        self.assertEqual(metric(result, "recording")["denominator"], 1)
        self.assertEqual(sum(result["state_breakdown"]["recording"]["states"].values()), 1)

    def test_documents_resolve_appearance_and_occurrence_subjects(self):
        graph = Graph()
        witness_meeting = graph.meeting("witness-meeting")
        chair_meeting = graph.meeting("chair-meeting")
        nominee_meeting = graph.meeting("nominee-meeting")
        unknown_meeting = graph.meeting("unknown-role-meeting")
        witness = graph.add(Appearance(id="witness", meeting=witness_meeting, name=RecordedName(display="Listed witness"), roles=("witness",),
                                      participation="listed", provenance=graph.evidence()))
        graph.add(Appearance(id="chair", meeting=chair_meeting, name=RecordedName(display="Committee chair"), roles=("chair",), provenance=graph.evidence()))
        graph.add(Appearance(id="nominee", meeting=nominee_meeting, name=RecordedName(display="Listed nominee"), roles=("nominee",), provenance=graph.evidence()))
        graph.add(Appearance(id="unknown", meeting=unknown_meeting, name=RecordedName(display="Unknown role"), provenance=graph.evidence()))
        occurrence = graph.add(MeetingOccurrence(id="sitting", meeting=nominee_meeting, provenance=graph.evidence()))
        graph.link("statement", graph.material("statement-document"), witness, role="statement")
        graph.link("transcript", graph.material("transcript-document"), occurrence, role="transcript", basis="derived", coverage="partial")
        result = graph.result()
        self.assertEqual(metric(result, "witnesses")["numerator"], 2)
        self.assertEqual(metric(result, "documents")["numerator"], 2)
        self.assertEqual(metric(result, "transcript")["numerator"], 1)
        self.assertEqual(result["state_breakdown"]["documents"]["states"]["reported"], 1)
        self.assertEqual(result["state_breakdown"]["documents"]["states"]["derived"], 1)
        self.assertEqual(result["record_counts"]["appearance"], 4)

    def test_partial_material_is_evidence_without_claiming_complete_coverage(self):
        graph = Graph()
        meeting = graph.meeting("one")
        link = graph.link("partial", graph.material("video", recording=True), meeting, coverage="partial")
        result = graph.result()
        self.assertEqual(metric(result, "recording")["numerator"], 1)
        self.assertEqual(next(r for r in graph.records if r.kind == link.kind and r.id == link.id).coverage, "partial")
        self.assertIn("evidence", metric(result, "recording")["label"])
        self.assertTrue(any("full coverage" in limitation for limitation in result["limitations"]))
        self.assertNotIn("complete", result["state_breakdown"]["recording"]["states"])

    def test_caption_evidence_requires_a_recording_link_and_preserves_inferred_association(self):
        graph = Graph()
        reported_meeting = graph.meeting("reported-meeting")
        inferred_meeting = graph.meeting("inferred-meeting")
        graph.meeting("unchecked-meeting")
        for label, subject, basis in (("reported", reported_meeting, "reported"), ("inferred", inferred_meeting, "inferred")):
            video = graph.material(label + "-video", recording=True)
            graph.link(label + "-link", video, subject, basis=basis)
            graph.assessment(label + "-captions", video, "available", aspect="captions", basis="reported")
        unlinked = graph.material("unlinked-video", recording=True)
        graph.assessment("unlinked-captions", unlinked, "available", aspect="captions", basis="observed")
        result = graph.result()
        states = result["state_breakdown"]["captions"]["states"]
        self.assertEqual(states["reported"], 1)
        self.assertEqual(states["inferred"], 1)
        self.assertEqual(states["observed"], 0)
        self.assertEqual(states["unchecked"], 1)
        self.assertEqual(metric(result, "captions")["numerator"], 2)

    def test_empty_current_population_has_zero_counts_without_false_percentage(self):
        graph = Graph()
        graph.meeting("retained-only", current=False)
        result = graph.result()
        for count in result["metrics"]:
            self.assertEqual((count["numerator"], count["denominator"], count["unknown"]), (0, 0, 0))
            self.assertNotIn("percentage", count)
        for breakdown in result["state_breakdown"].values():
            self.assertEqual(sum(breakdown["states"].values()), 0)

    def test_direct_caption_resource_is_caption_evidence_without_a_recording(self):
        graph = Graph()
        meeting = graph.meeting("captioned-meeting")
        text = graph.add(Material(id="caption-text", details=TextDetails(category="captions"), provenance=graph.evidence()))
        graph.link("caption-link", text, meeting, role="captions", coverage="partial")
        result = graph.result()
        self.assertEqual(metric(result, "captions")["numerator"], 1)
        self.assertEqual(result["state_breakdown"]["captions"]["states"]["reported"], 1)
        self.assertEqual(metric(result, "recording")["numerator"], 0)

    def test_lifecycle_states_stay_in_inventory_without_becoming_publication_failures(self):
        graph = Graph()
        for label, status, access in (("canceled", "canceled", "unknown"), ("postponed", "postponed", "unknown"),
                                      ("closed", "held", "closed"), ("future", "scheduled", "open")):
            meeting = graph.meeting(label)
            graph.add(MeetingOccurrence(id="occurrence-" + label, meeting=meeting, status=status, access=access,
                                       scheduled_start=ReportedTime(date=date(2099, 1, 1)) if label == "future" else None,
                                       provenance=graph.evidence()))
        result = graph.result()
        for count in result["metrics"]:
            self.assertEqual((count["numerator"], count["denominator"], count["unknown"]), (0, 4, 4))
        for breakdown in result["state_breakdown"].values():
            self.assertEqual(breakdown["states"]["unchecked"], 4)
            self.assertEqual(breakdown["states"]["not_found_in_checked_scope"], 0)


if __name__ == "__main__":
    unittest.main()
