"""Offline import boundaries for retained official documents and transcript bodies."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from committee_meeting import Catalog
from committee_meeting.common import Ref
from committee_meeting.materials import Material, MaterialVersion, RecordingDetails
from committee_meeting.meetings import Meeting

from congress_api.adapters import gpo, transcripts
from congress_api.adapters.common import AdapterContext


def context(provider="govinfo"):
    return AdapterContext(
        now=datetime(2026, 9, 27, 12, tzinfo=timezone.utc),
        input_id="retained-input-1", provider=provider,
        ids=lambda kind, key: f"{kind}-{sha256(key.encode()).hexdigest()[:24]}",
    )


def catalog(records):
    return Catalog(
        sources=tuple(r for r in records if r.kind == "source_record"),
        records=tuple(r for r in records if r.kind != "source_record"),
    )


def kind(records, name):
    return [r for r in records if r.kind == name]


def gpo_row(**changes):
    row = {
        "package_id": "CHRG-118hhrg50001", "congress": "118", "chamber": "house",
        "event_id": "123456", "title": "A retained hearing record", "record_type": "hearing",
        "held_date": "2024-01-02", "hearing_dates": "", "date_ingested": "2025-02-01",
        "last_modified": "2025-02-02T13:45:02Z", "text_read": "yes",
        "html_url": "https://example.gov/print.htm?edition=original%2Fcopy",
        "pdf_url": "http://example.gov/print.PDF?download=true", "committee_code_gpo": "HSVR00",
    }
    row.update(changes)
    return row


def body(**changes):
    value = {
        "schema_version": "1.0",
        "header": {
            "title": "A retained hearing record", "chamber": "house", "congress": 118,
            "event_id": "123456", "package_id": "CHRG-118hhrg50001", "date": "2024-01-02",
            "time_convened": "10:00 a.m.", "present": ["chair-other-hearing"],
        },
        "participants": {"chair-other-hearing": {"name": "Context only", "role": "chair"}},
        "turns": [{"speaker": "spk:unresolved", "text": "Testimony retained exactly."}],
        "inserts": [], "source": {"kind": "gpo_print", "url": "https://example.gov/print.htm"},
    }
    value.update(changes)
    return value


class GpoAdapterTests(unittest.TestCase):
    def test_exact_urls_dates_and_unlinked_packages_survive(self):
        row = gpo_row(record_type="errata")
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = list(gpo.records([row], context()))
        catalog(result)
        material = kind(result, "material")[0]
        self.assertEqual(material.details.category, "errata")
        self.assertEqual(material.proceeding_dates[0].precision, "day")
        self.assertEqual(kind(result, "source_record")[0].payload, row)
        self.assertIsNone(kind(result, "source_record")[0].retrieved_at)
        self.assertIsNone(kind(result, "material_version")[0].published_at)
        self.assertEqual({r.locations[0].url for r in kind(result, "representation")}, {row["html_url"], row["pdf_url"]})
        self.assertTrue(all(r.sha256 is None and r.retained is None for r in kind(result, "representation")))
        self.assertEqual([i.category for i in kind(result, "data_issue")], ["unlinked"])
        self.assertFalse(kind(result, "meeting") or kind(result, "material_relation") or kind(result, "assessment"))

    def test_day_header_disagreement_retains_both_dates(self):
        result = list(gpo.records([gpo_row(hearing_dates="2024-01-03;2024-01-04")], context()))
        catalog(result)
        material = kind(result, "material")[0]
        self.assertEqual([d.date.isoformat() for d in material.proceeding_dates], ["2024-01-03", "2024-01-04"])
        evidence = material.field_evidence[0]
        self.assertEqual(evidence.alternatives[0].value[0]["date"], "2024-01-02")
        self.assertEqual(evidence.selected.citations[0].selector, "/hearing_dates")
        self.assertIn("conflicting", [i.category for i in kind(result, "data_issue")])
        self.assertFalse(kind(result, "occurrence"))

    def test_multiple_dates_including_held_date_are_not_a_conflict(self):
        result = list(gpo.records([gpo_row(hearing_dates="2024-01-02;2024-01-03;2024-01-02")], context()))
        self.assertEqual(len(kind(result, "material")[0].proceeding_dates), 2)
        self.assertNotIn("conflicting", [i.category for i in kind(result, "data_issue")])

    def test_only_a_scoped_verified_event_lookup_creates_a_link(self):
        target = Ref(kind="meeting", id="meeting-known")
        unrelated = list(gpo.records([gpo_row()], context(), meetings={(118, "senate", "123456"): target}))
        self.assertFalse(kind(unrelated, "material_link"))
        result = list(gpo.records([gpo_row()], context(), meetings={(118, "house", "123456"): target}))
        link = kind(result, "material_link")[0]
        meeting = Meeting(id=target.id, title="Known meeting", congress=118, provenance=link.provenance)
        catalog([*result, meeting])
        self.assertEqual(link.coverage, "unknown")
        self.assertFalse(kind(result, "data_issue"))

    def test_bad_fields_remain_evidence_without_guessed_urls_or_dates(self):
        row = gpo_row(html_url="relative.htm", hearing_dates="unreadable;also-unreadable")
        result = list(gpo.records([row], context()))
        catalog(result)
        self.assertEqual(len(kind(result, "representation")), 1)
        self.assertEqual(kind(result, "source_record")[0].payload["html_url"], "relative.htm")
        self.assertEqual(kind(result, "material")[0].proceeding_dates[0].date.isoformat(), "2024-01-02")
        self.assertEqual(len([i for i in kind(result, "data_issue") if i.category == "unverified"]), 2)


class TranscriptAdapterTests(unittest.TestCase):
    def setUp(self):
        for target in ("builtins.open", "pathlib.Path.open", "socket.create_connection", "socket.socket.connect"):
            blocked = patch(target, side_effect=AssertionError("adapter attempted I/O"))
            blocked.start()
            self.addCleanup(blocked.stop)

    def source(self, name, value=None, raw=None):
        return transcripts.TranscriptInput(
            data=raw if raw is not None else (json.dumps(value or body(), indent=2) + "\n\n").encode(),
            name=name, uri=f"https://example.gov/retained/{name}",
        )

    def test_body_bytes_and_local_speakers_survive_without_attendance(self):
        item = self.source("body.json")
        result = list(transcripts.records([item], context("transcript-artifacts")))
        catalog(result)
        representation = kind(result, "representation")[0]
        self.assertEqual(representation.sha256, sha256(item.data).hexdigest())
        self.assertEqual(representation.byte_size, len(item.data))
        self.assertEqual(representation.retained.uri, item.uri)
        self.assertEqual(representation.locations, ())
        self.assertEqual(representation.content_schema.version, "1.0")
        source = kind(result, "source_record")[0]
        self.assertEqual(source.payload["turns"][0]["speaker"], "spk:unresolved")
        self.assertEqual(source.payload["header"]["time_convened"], "10:00 a.m.")
        self.assertIsNone(source.retrieved_at)
        self.assertFalse(kind(result, "appearance") or kind(result, "person") or kind(result, "occurrence"))
        roster_issue = next(i for i in kind(result, "data_issue") if i.field_path == "/payload/participants")
        self.assertEqual(roster_issue.subject.id, source.id)
        self.assertEqual(roster_issue.category, "unverified")
        self.assertEqual(source.payload["participants"], body()["participants"])

    def test_known_gpo_json_is_another_representation_of_the_original_version(self):
        official = list(gpo.records([gpo_row()], context()))
        version = kind(official, "material_version")[0]
        result = list(transcripts.records(
            [self.source("parsed.json")], context("transcript-artifacts"),
            source_versions={("govinfo", "CHRG-118hhrg50001"): Ref(kind="material_version", id=version.id)},
        ))
        catalog([*official, *result])
        self.assertEqual(kind(result, "representation")[0].version.id, version.id)
        self.assertEqual(kind(result, "representation")[0].provenance.basis, "derived")
        self.assertFalse(kind(result, "material") or kind(result, "material_version") or kind(result, "material_link"))

    def test_generated_text_uses_verified_recording_and_event_associations(self):
        video_context = context("youtube")
        video_source = video_context.source("video-1", {"video_id": "video-1"})
        video_evidence = video_context.evidence(video_source)
        video = Material(id="video-material", details=RecordingDetails(medium="video", provider="youtube"), provenance=video_evidence)
        source_version = MaterialVersion(id="video-version", material=Ref(kind="material", id=video.id), provenance=video_evidence)
        original = [video_source, video, source_version]
        data = body(source={"kind": "gemini_transcription", "video_id": "video-1", "generated_at": "2026-09-26T12:30:00Z"})
        meeting_ref = Ref(kind="meeting", id="meeting-known")
        result = list(transcripts.records(
            [self.source("generated.json", data)], context("transcript-artifacts"),
            meetings={(118, "house", "123456"): meeting_ref},
            source_versions={("youtube", "video-1"): Ref(kind="material_version", id=source_version.id)},
        ))
        meeting = Meeting(id=meeting_ref.id, title="Known", provenance=kind(result, "material")[0].provenance)
        catalog([*original, *result, meeting])
        self.assertEqual(kind(result, "material")[0].details.production, "automatic")
        self.assertEqual(kind(result, "material_version")[0].generated_at.time.isoformat(), "12:30:00")
        self.assertEqual(kind(result, "material_relation")[0].relation, "derived_from")
        self.assertEqual(kind(result, "material_link")[0].subject, meeting_ref)
        self.assertEqual({i.field_path for i in kind(result, "data_issue")}, {"/content_schema", "/payload/participants"})

    def test_scheduled_header_time_keeps_its_note_and_does_not_become_actual_start(self):
        data = body(source={"kind": "gemini_transcription", "notes": "tokens in 10; time_convened is the scheduled time from Congress.gov"})
        result = list(transcripts.records([self.source("scheduled.json", data)], context("transcript-artifacts")))
        catalog(result)
        source = kind(result, "source_record")[0]
        issue = next(i for i in kind(result, "data_issue") if i.field_path == "/payload/header/time_convened")
        self.assertEqual(issue.category, "unverified")
        self.assertEqual(issue.provenance.citations[0].selector, "/source/notes")
        self.assertEqual(source.payload["header"]["time_convened"], "10:00 a.m.")
        self.assertEqual(source.payload["source"]["notes"], data["source"]["notes"])
        self.assertFalse(kind(result, "occurrence") or kind(result, "appearance") or kind(result, "person"))

    def test_owner_reader_rejects_bad_scalar_without_losing_source_data(self):
        data = body(participants={}, turns=[{"speaker": "unresolved", "text": 123}])
        result = list(transcripts.records([self.source("untyped.json", data)], context("transcript-artifacts")))
        catalog(result)
        source = kind(result, "source_record")[0]
        representation = kind(result, "representation")[0]
        issue = next(i for i in kind(result, "data_issue") if i.impact == "blocks_use")
        self.assertEqual(source.payload["turns"][0]["text"], 123)
        self.assertEqual(issue.subject.id, representation.id)
        self.assertIsNone(representation.content_schema)
        self.assertIn("valid string", issue.explanation)
        self.assertFalse(any(i.field_path == "/payload/participants" for i in kind(result, "data_issue")))

    def test_changed_bytes_keep_one_work_and_distinct_versions(self):
        first = self.source("one.json")
        second = self.source("two.json", raw=first.data + b" \n")
        result = list(transcripts.records([first, second, first], context("transcript-artifacts")))
        catalog(result)
        self.assertEqual(len(kind(result, "source_record")), 2)
        self.assertEqual(len(kind(result, "material")), 1)
        self.assertEqual(len(kind(result, "material_version")), 2)
        self.assertEqual(len(kind(result, "representation")), 2)

    def test_unreadable_body_is_retained_with_a_blocking_issue(self):
        item = self.source("broken.json", raw=b"{not json}")
        result = list(transcripts.records([item], context("transcript-artifacts")))
        catalog(result)
        representation = kind(result, "representation")[0]
        self.assertEqual(representation.sha256, sha256(item.data).hexdigest())
        self.assertIsNone(representation.content_schema)
        self.assertIn("blocks_use", [i.impact for i in kind(result, "data_issue")])

    def test_unsupported_body_version_is_not_labeled_as_valid_current_schema(self):
        result = list(transcripts.records([self.source("future.json", body(schema_version="2.0"))], context("transcript-artifacts")))
        catalog(result)
        self.assertIsNone(kind(result, "representation")[0].content_schema)
        self.assertEqual(kind(result, "source_record")[0].payload["schema_version"], "2.0")


if __name__ == "__main__":
    unittest.main()
