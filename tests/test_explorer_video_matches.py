"""Retained matcher decisions do not become invented per-meeting coverage."""
from datetime import datetime, timezone
from hashlib import sha256
import unittest
from unittest.mock import patch

from committee_meeting import Catalog
from committee_meeting.common import Ref
from committee_meeting.materials import DocumentDetails, Material, MaterialVersion, RecordingDetails
from committee_meeting.meetings import Meeting

from congress_api.adapters.common import AdapterContext
from congress_api.adapters.video_matches import records


def context(provider="retained-gpo-matches"):
    return AdapterContext(
        now=datetime(2026, 9, 27, 12, tzinfo=timezone.utc), input_id="match-input", provider=provider,
        ids=lambda kind, key: kind + "-" + sha256(key.encode()).hexdigest()[:24],
    )


def row(**changes):
    result = {
        "package_id": "CHRG-118hhrg12345", "congress": "118", "chamber": "house",
        "committee_code": "hsju00", "held_date": "2024-01-02", "hearing_dates": "",
        "record_type": "hearing", "status": "full_recording", "video_ids": "abcdefghijk lmnopqrstuv",
        "channels": "channel-one channel-two", "method": "event id; congress.gov link",
        "score": "100", "video_minutes": "187", "flags": "audio_only", "source": "auto", "note": "",
    }
    result.update(changes)
    return result


def kind(items, name):
    return [r for r in items if r.kind == name]


def validate(items):
    return Catalog(sources=tuple(kind(items, "source_record")), records=tuple(r for r in items if r.kind != "source_record"))


class VideoMatchTests(unittest.TestCase):
    def setUp(self):
        self.context = context()
        source = self.context.source("package", {"package_id": "CHRG-118hhrg12345"})
        self.evidence = self.context.evidence(source)
        self.package = Material(id="package-one", details=DocumentDetails(category="transcript"), provenance=self.evidence)
        self.baseline = [source, self.package]
        self.packages = {"CHRG-118hhrg12345": Ref(kind="material", id=self.package.id)}

    def test_accepted_row_creates_resources_and_conservative_single_meeting_links(self):
        native = row()
        meeting = Meeting(id="one-meeting", title="Known proceeding", provenance=self.evidence)
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = list(records([native], self.context, packages=self.packages,
                                  package_meetings={native["package_id"]: [Ref(kind="meeting", id=meeting.id)]}))
        validate([*self.baseline, meeting, *result])
        self.assertEqual(kind(result, "source_record")[0].payload, native)
        self.assertEqual(len(kind(result, "material")), 2)
        self.assertEqual(len(kind(result, "material_link")), 2)
        self.assertTrue(all(link.coverage == "unknown" for link in kind(result, "material_link")))
        self.assertTrue(all(version.duration_seconds is None for version in kind(result, "material_version")))
        self.assertTrue(all(material.details.coverage == "unknown" for material in kind(result, "material")))
        assessment = kind(result, "assessment")[0]
        self.assertEqual(assessment.status, "available")
        self.assertEqual(assessment.subject.id, self.package.id)
        self.assertEqual(assessment.provenance.basis, "derived")
        self.assertIsNone(assessment.observed_at)
        self.assertTrue(any("aggregates" in issue.summary for issue in kind(result, "data_issue")))
        self.assertEqual(kind(result, "representation")[0].locations[0].url, "https://www.youtube.com/watch?v=abcdefghijk")

    def test_existing_recordings_are_reused_without_mutating_lookup(self):
        recording = Material(id="existing-recording", details=RecordingDetails(medium="video", provider="youtube"), provenance=self.evidence)
        version = MaterialVersion(id="existing-version", material=Ref(kind="material", id=recording.id), provenance=self.evidence)
        lookup = {"abcdefghijk": (Ref(kind="material", id=recording.id), Ref(kind="material_version", id=version.id))}
        result = list(records([row(video_ids="abcdefghijk")], self.context, packages=self.packages, recordings=lookup))
        validate([*self.baseline, recording, version, *result])
        self.assertFalse(kind(result, "material") or kind(result, "material_version") or kind(result, "representation"))
        self.assertEqual(kind(result, "assessment")[0].results, (Ref(kind="material", id=recording.id),))
        self.assertEqual(len(lookup), 1)

    def test_inferred_package_association_remains_inferred_for_recordings(self):
        from committee_meeting.provenance import Method
        native = row()
        meeting = Meeting(id="one-meeting", provenance=self.evidence)
        inferred = self.evidence.model_copy(update={"basis": "inferred", "method": Method(name="print-title-rule", version="1")})
        result = list(records([native], self.context, packages=self.packages,
            package_meetings={native["package_id"]: [Ref(kind="meeting", id=meeting.id)]},
            package_evidence={(native["package_id"], meeting.id): [inferred]}))
        validate([*self.baseline, meeting, *result])
        self.assertTrue(all(link.provenance.basis == "inferred" for link in kind(result, "material_link")))
        self.assertTrue(all(len(link.provenance.citations) == 2 for link in kind(result, "material_link")))

    def test_curated_offsite_urls_keep_exact_spelling(self):
        url = "http://www.senate.gov/isvp/?comm=epw&filename=epw120623&part=one%2Ftwo"
        result = list(records([row(status="full_recording_offsite", video_ids=url, source="research", method="research", score="0")], self.context, packages=self.packages))
        validate([*self.baseline, *result])
        self.assertEqual(kind(result, "representation")[0].locations[0].url, url)
        self.assertEqual(kind(result, "assessment")[0].provenance.basis, "curated")
        self.assertEqual(kind(result, "material")[0].details.medium, "unknown")

    def test_shared_and_multiple_date_volumes_do_not_fan_out_to_meetings(self):
        meetings = [Meeting(id=n, title=n, provenance=self.evidence) for n in ("meeting-one", "meeting-two")]
        refs = [Ref(kind="meeting", id=m.id) for m in meetings]
        for native, supported in ((row(), refs), (row(hearing_dates="2024-01-02;2024-01-03"), refs[:1]),
                                  (row(hearing_dates="2024-01-03"), refs[:1])):
            with self.subTest(dates=native["hearing_dates"], meeting_count=len(supported)):
                result = list(records([native], self.context, packages=self.packages,
                                      package_meetings={native["package_id"]: supported}))
                validate([*self.baseline, *meetings, *result])
                self.assertFalse(kind(result, "material_link"))
                self.assertEqual(len(kind(result, "assessment")[0].results), 2)
                self.assertIn("unlinked", [issue.category for issue in kind(result, "data_issue")])

    def test_same_recording_across_packages_is_allocated_once(self):
        second = Material(id="package-two", details=DocumentDetails(category="transcript"), provenance=self.evidence)
        packages = {**self.packages, "CHRG-118hhrg54321": Ref(kind="material", id=second.id)}
        native = [row(video_ids="abcdefghijk"), row(package_id="CHRG-118hhrg54321", video_ids="abcdefghijk")]
        result = list(records(native, self.context, packages=packages))
        validate([*self.baseline, second, *result])
        self.assertEqual(len(kind(result, "material")), 1)
        self.assertEqual(len(kind(result, "assessment")), 2)
        self.assertEqual(kind(result, "assessment")[0].results, kind(result, "assessment")[1].results)

    def test_undated_negatives_are_not_absence_checks(self):
        for status, outcome in (("no_video_found", "unknown"), ("before_channel", "unknown"),
                                ("committee_not_tracked", "unknown"), ("not_public", "not_applicable")):
            with self.subTest(status=status):
                result = list(records([row(status=status, video_ids="")], self.context, packages=self.packages))
                validate([*self.baseline, *result])
                assessment = kind(result, "assessment")[0]
                self.assertEqual(assessment.status, outcome)
                self.assertIsNone(assessment.observed_at)
                self.assertFalse(kind(result, "material"))

    def test_unidentified_clips_do_not_create_fictional_resources(self):
        result = list(records([row(status="clips_only", video_ids="", score="", method="")], self.context, packages=self.packages))
        validate([*self.baseline, *result])
        self.assertFalse(kind(result, "material") or kind(result, "representation") or kind(result, "material_link"))
        self.assertEqual(kind(result, "assessment")[0].status, "unknown")
        self.assertTrue(any("clip identifiers" in issue.summary for issue in kind(result, "data_issue")))

    def test_missing_package_retains_only_unlinked_source_decision(self):
        result = list(records([row()], self.context, packages={}))
        validate(result)
        self.assertEqual(len(kind(result, "source_record")), 1)
        self.assertFalse(kind(result, "material") or kind(result, "assessment"))
        self.assertEqual(kind(result, "data_issue")[0].subject.kind, "source_record")

    def test_accepted_result_with_invalid_ids_is_visible_as_missing_evidence(self):
        result = list(records([row(video_ids="not-an-id https://untrusted.invalid")], self.context, packages=self.packages))
        validate([*self.baseline, *result])
        self.assertFalse(kind(result, "material"))
        self.assertEqual(kind(result, "assessment")[0].status, "available")
        self.assertEqual(kind(result, "assessment")[0].results, ())
        self.assertIn("missing", [issue.category for issue in kind(result, "data_issue")])


if __name__ == "__main__":
    unittest.main()
