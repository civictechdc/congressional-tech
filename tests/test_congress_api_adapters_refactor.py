"""Malformed evidence stays retained without inventing recordings or freshness."""

from datetime import UTC, datetime

import pytest

from committee_meeting.common import Ref
from congress_api.adapters import inventory, recordings, senate
from congress_api.adapters.common import AdapterContext
from test_explorer_senate_adapter import retained_page

NOW = datetime(2026, 9, 30, tzinfo=UTC)
PAGE = "https://example.senate.gov/hearing"


def context():
    return AdapterContext(NOW, "snapshot", "test", lambda kind, key: kind + ":" + key)


@pytest.mark.parametrize("token", [17, True, ["abcdefghijk"], {"url": PAGE}])
def test_non_string_recording_keeps_evidence_and_reports_invalid_reference(token):
    row = {"event_id": "12", "recording": token, "note": "original evidence"}
    result = list(recordings.records([row], context(), meetings={}))
    source, issue = result
    assert source.payload == row
    assert issue.category == "unverified"
    assert issue.subject.id == source.id
    assert not any(record.kind in ("material", "material_version", "representation") for record in result)


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-09-29T12:00:00Z", datetime(2026, 9, 29, 12, tzinfo=UTC)),
        ("2026-09-29T08:00:00-04:00", datetime(2026, 9, 29, 12, tzinfo=UTC)),
        ("2026-09-29T12:00:00", None),
        ("2026-10-01T12:00:00Z", None),
        ("2026-09-29", None),
        ("unreadable", None),
        (17, None),
        (None, None),
    ],
)
def test_caption_and_senate_negative_checks_require_past_zoned_times(timestamp, expected):
    caption_state = {"caption_observations": {"youtube": {"abcdefghijk": {
        "observed_at": timestamp, "outcome": "not_found", "scope": "English captions",
    }}}}
    captions = list(inventory.records(caption_state, context(), meetings={}, materials={
        ("youtube", "abcdefghijk"): Ref(kind="material", id="recording"),
    }))
    assessment, = [record for record in captions if record.kind == "assessment"]
    assert assessment.observed_at == expected
    assert assessment.status == ("not_found" if expected else "unknown")
    caption_source, = [record for record in captions if record.kind == "source_record"]
    assert caption_source.payload["receipt"]["observed_at"] == timestamp

    page = {"absent": True, "events": ["12"], "observation_check": {
        "mode": "live", "receipts": [{"url": PAGE, "status_code": 404,
            "outcome": "not_found", "completed_at": timestamp}],
    }}
    result = list(senate.records({"example.senate.gov": {"pages": {PAGE: page}}}, context(),
        meetings={(119, "senate", "12"): Ref(kind="meeting", id="meeting")}))
    assessment, = [record for record in result if record.kind == "assessment"]
    assert assessment.observed_at == expected
    assert assessment.status == ("not_found" if expected else "unknown")
    source = retained_page(result, page)
    assert source.payload == {"absent": True}
    sources = {record.id: record for record in result if record.kind == "source_record"}
    match, = assessment.provenance.citations
    assert match.source.id != source.id
    assert sources[match.source.id].payload["observation_check"] == page["observation_check"]


@pytest.mark.parametrize("check", ["unreadable", 17, ["unknown"]])
def test_senate_listing_keeps_unknown_check_shape_with_source_bodies(check):
    bodies = [{"url": PAGE, "text": "retained listing"}]
    result = list(senate.records({"example.senate.gov": {
        "last_check": check, "source_bodies": bodies, "pages": {},
    }}, context(), meetings={}))
    source, = result
    assert source.kind == "source_record"
    assert source.payload == {"host": "example.senate.gov", "last_check": check, "source_bodies": bodies}
    assert source.retrieved_at is None
