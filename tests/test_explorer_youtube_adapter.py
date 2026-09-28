"""YouTube cache adaptation stays offline and distinguishes metadata from bytes."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from committee_meeting import Catalog
from committee_meeting.common import Identifier, Ref
from committee_meeting.meetings import Meeting
from committee_meeting.provenance import Citation, Provenance, SourceRecord

from youtube_api.adapters import records


@dataclass
class Context:
    now: datetime = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)

    def ids(self, kind, key):
        return kind + "-" + sha256(key.encode()).hexdigest()[:24]

    def source(self, key, payload, url=None):
        return SourceRecord(
            id=self.ids("source_record", key + json.dumps(payload, sort_keys=True)),
            provider="youtube", identifier=Identifier(scheme="youtube:record", value=key),
            payload=payload, url=url, imported_at=self.now,
        )

    def evidence(self, source, basis="reported", method=None, selector=None):
        return Provenance(
            citations=(Citation(source=Ref(kind="source_record", id=source.id),
                                selector_type="json_pointer" if selector else None, selector=selector),),
            basis=basis, method=method,
        )


def video(**changes):
    value = {
        "videoId": "lQnpl1K8dVY", "title": "Committee markup", "description": "EventID=123456",
        "publishedAt": "2025-07-23T23:26:16Z", "caption": False, "duration": 7381,
    }
    value.update(changes)
    return value


def kind(items, name):
    return [r for r in items if r.kind == name]


def validate(items):
    return Catalog(sources=tuple(kind(items, "source_record")), records=tuple(r for r in items if r.kind != "source_record"))


class YoutubeAdapterTests(unittest.TestCase):
    def test_real_cache_shape_preserves_fields_without_inventing_channel_or_publication(self):
        row = video()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = list(records([row], Context()))
        validate(result)
        self.assertEqual(kind(result, "source_record")[0].payload, row)
        self.assertEqual(kind(result, "material_version")[0].duration_seconds, 7381)
        self.assertIsNone(kind(result, "material_version")[0].published_at)
        self.assertFalse(kind(result, "channel") or kind(result, "material_link"))
        representation = kind(result, "representation")[0]
        self.assertEqual(representation.locations[0].url, "https://www.youtube.com/watch?v=lQnpl1K8dVY")
        self.assertEqual(representation.locations[0].role, "player")
        self.assertIsNone(representation.retained)
        self.assertIsNone(representation.media_type)
        self.assertEqual(kind(result, "material")[0].id, Context().ids("material", "youtube|lQnpl1K8dVY"))

    def test_caption_flag_reports_availability_without_fabricating_caption_files(self):
        for flag, status in ((True, "available"), (False, "unknown"), (None, "unknown"), ("true", "unknown")):
            with self.subTest(flag=flag):
                result = list(records([video(caption=flag)], Context()))
                validate(result)
                assessment = kind(result, "assessment")[0]
                self.assertEqual(assessment.status, status)
                self.assertEqual(assessment.results, ())
                self.assertIsNone(assessment.observed_at)
                self.assertEqual(assessment.provenance.basis, "reported")
                self.assertEqual(len(kind(result, "representation")), 1)
                self.assertEqual(len(kind(result, "material")), 1)

    def test_unknown_flag_has_no_nonexistent_field_selector(self):
        row = video()
        del row["caption"]
        result = list(records([row], Context()))
        self.assertIsNone(kind(result, "assessment")[0].provenance.citations[0].selector)

    def test_native_channels_deduplicate_within_one_import(self):
        rows = [video(channelId="UC-native", channelTitle="Committee"), video(videoId="other-video", channelId="UC-native")]
        result = list(records(rows, Context()))
        validate(result)
        self.assertEqual(len(kind(result, "channel")), 1)
        channel = kind(result, "channel")[0]
        self.assertEqual(channel.url, "https://www.youtube.com/channel/UC-native")
        self.assertTrue(all(m.details.channel.id == channel.id for m in kind(result, "material")))

    def test_explicit_channel_context_is_preserved_separately_and_conflict_visible(self):
        result = list(records([video()], Context(), channel_id="UC-verified"))
        validate(result)
        self.assertEqual(kind(result, "source_record")[0].payload, {"video": video(), "verified_channel_id": "UC-verified"})
        self.assertEqual(kind(result, "assessment")[0].provenance.citations[0].selector, "/video/caption")
        conflict = list(records([video(channelId="UC-native")], Context(), channel_id="UC-other"))
        validate(conflict)
        self.assertEqual(kind(conflict, "channel")[0].identifiers[0].value, "UC-native")
        self.assertIn("conflicting", [i.category for i in kind(conflict, "data_issue")])

    def test_recording_can_serve_two_meetings_with_caller_match_evidence(self):
        ctx = Context()
        match = ctx.source("accepted-matches", {"video_id": "lQnpl1K8dVY", "meeting_ids": ["one", "two"], "method": "curated"})
        evidence = ctx.evidence(match, basis="curated")
        meeting_records = [Meeting(id=n, title=n, provenance=evidence) for n in ("one", "two")]
        associations = [(Ref(kind="meeting", id=m.id), evidence) for m in meeting_records]
        result = list(records([video()], ctx, meetings={"lQnpl1K8dVY": associations}))
        validate([match, *meeting_records, *result])
        self.assertEqual(len(kind(result, "material")), 1)
        self.assertEqual(len(kind(result, "material_link")), 2)
        self.assertTrue(all(link.provenance == evidence for link in kind(result, "material_link")))
        self.assertNotIn("unlinked", [i.category for i in kind(result, "data_issue")])

    def test_malformed_duration_is_retained_without_coercion(self):
        for value in (True, "7381", -1):
            with self.subTest(value=value):
                result = list(records([video(duration=value)], Context()))
                validate(result)
                self.assertIsNone(kind(result, "material_version")[0].duration_seconds)
                self.assertEqual(kind(result, "source_record")[0].payload["duration"], value)
                self.assertTrue(any(i.field_path == "/duration_seconds" for i in kind(result, "data_issue")))


if __name__ == "__main__":
    unittest.main()


def test_refreshed_video_uses_video_publication_time_without_playlist_warning():
    row = video(videoPublishedAt='2025-07-22T12:00:00Z', channelId='UC-example')
    result = list(records([row], Context()))
    validate(result)
    version = kind(result, 'material_version')[0]
    assert version.published_at.original == row['videoPublishedAt']
    assert version.published_at.timezone == 'UTC'
    assert not any(i.field_path == '/published_at' for i in kind(result, 'data_issue'))


def test_successful_api_omission_is_scoped_and_dated_without_claiming_deleted_video():
    row = video(available=False, caption=None, duration=None, details_checked_at='2026-09-26T12:00:00Z')
    result = list(records([row], Context())); validate(result)
    check = next(r for r in result if r.kind == 'assessment' and r.aspect == 'reachability')
    assert check.status == 'not_found'
    assert check.observed_at == datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    assert 'videos.list' in check.scope and 'web player was not checked' in check.scope
    assert kind(result, 'representation')  # Retain the historical source URL.
    unknown = list(records([video(available=False)], Context()))
    assert next(r for r in unknown if r.kind == 'assessment' and r.aspect == 'reachability').status == 'unknown'
