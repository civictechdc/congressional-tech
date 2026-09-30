"""Congress.gov collection keeps source fields and retries interrupted work."""
import json
from datetime import datetime

import pytest
from congress_api.acquisition import meetings
from congress_api.retention.meetings import read as meetings_read
from congress_api.retention.meetings import write as meetings_write


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(meetings, "load_congress_api_key", lambda: "private-key")
    monkeypatch.setattr(meetings, "FIRST_CONGRESS", 112)
    monkeypatch.setattr(meetings, "CONGRESS_METADATA", {"112": {}, "113": {}, "114": {}})
    monkeypatch.setattr(meetings, "CHAMBERS", ("house",))
    path = tmp_path / "meetings.jsonl.gz"
    url = f"{meetings.API}/committee-meeting/112/house/old"
    old = {"_url": url, "eventId": "old", "congress": 112, "chamber": "House", "updateDate": "2026-01-10T00:00:00Z"}
    meetings_write({url: old}, path)
    return path, url, old


def pending(path):
    return json.loads(path.with_suffix(path.suffix + ".pending.json").read_text())["urls"]


def test_failed_old_detail_is_retried_after_new_watermark_passes_it(tmp_path, monkeypatch):
    path, old_url, old = setup(monkeypatch, tmp_path)
    newer_url = f"{meetings.API}/committee-meeting/114/house/new"
    calls = []
    first = True

    def get(session, url, key, params=None):
        calls.append((url, dict(params) if params else None))
        if params:
            return {"committeeMeetings": [{"url": old_url + "?api_key=private-key"}, {"url": newer_url}] if first and url.endswith("112/house") else []}
        if url == old_url and first:
            raise RuntimeError("temporary error")
        return {"committeeMeeting": {**old, "eventId": "old" if url == old_url else "new", "updateDate": "2026-01-11T00:00:00Z" if url == old_url else "2026-01-20T00:00:00Z", "futureField": {"nested": [1, "kept"]}}}

    monkeypatch.setattr(meetings, "get", get)
    with pytest.raises(SystemExit):
        meetings.main(path, nthreads=1)
    assert pending(path) == [old_url]
    assert meetings_read(path)[old_url] == old
    first = False
    calls.clear()
    meetings.main(path, nthreads=1)
    assert [url for url, params in calls if params is None] == [old_url]
    assert all(params["fromDateTime"] == "2026-01-18T00:00:00Z" for _, params in calls if params)
    assert len([url for url, params in calls if params]) == 3  # Includes historical 112th Congress.
    assert pending(path) == []
    updated = meetings_read(path)[old_url]
    assert updated["futureField"] == {"nested": [1, "kept"]}
    assert datetime.fromisoformat(updated["_retrieved_at"]).tzinfo is not None
    assert "private-key" not in json.dumps(updated)


def test_pending_work_survives_output_write_failure(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(meetings, "get", lambda session, address, key, params=None: {"committeeMeetings": [{"url": url}]} if params else {"committeeMeeting": old})
    monkeypatch.setattr(meetings, "write", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        meetings.main(path, nthreads=1)
    assert path.read_bytes() == before
    assert pending(path) == [url]


def test_atomic_write_keeps_existing_bytes_after_serialization_failure(tmp_path):
    path = tmp_path / "meetings.jsonl.gz"
    meetings_write({"old": {"_url": "old", "native": True}}, path)
    before = path.read_bytes()
    with pytest.raises(TypeError):
        meetings_write({"first": {"_url": "first"}, "invalid": {"value": object()}}, path)
    assert path.read_bytes() == before


def test_duplicate_source_url_raises_like_gpo_evidence(tmp_path):
    import gzip
    import json

    from congress_api.retention.meetings import read as meetings_read

    path = tmp_path / "meetings.jsonl.gz"
    row = {"_url": "https://api.congress.gov/v3/committee-meeting/112/house/1",
           "eventId": "1", "congress": 112, "chamber": "House"}
    path.write_bytes(gzip.compress(
        (json.dumps(row, sort_keys=True) + "\n"
         + json.dumps({**row, "title": "again"}, sort_keys=True) + "\n").encode(),
        mtime=0))
    with pytest.raises(ValueError, match="Duplicate meeting source URL"):
        meetings_read(path)


def test_meeting_read_keeps_rows_inventory_scope_drops(tmp_path):
    from congress_api.retention.tables import read_meetings

    path = tmp_path / "meetings.jsonl.gz"
    url = "https://api.congress.gov/v3/committee-meeting/112/house/1"
    row = {"_url": url, "eventId": "1", "congress": 112, "chamber": "House", "meetingStatus": "Held"}
    meetings_write({url: row}, path)
    assert meetings_read(path)[url]["congress"] == 112
    assert read_meetings(path) == []


def test_scoped_reader_preserves_each_caller_population(tmp_path, caplog):
    import logging

    from congress_api.cli.gpo_match import load_meetings
    from congress_api.matching.meetings import scheduled_or_rescheduled
    from congress_api.retention.meetings import all_meetings
    from congress_api.retention.meetings import read_meetings as read_scoped
    from congress_api.retention.tables import read_meetings as read_inventory
    from congress_api.transcripts import context as metadata

    rows = [
        {"_url": "held112", "eventId": "held112", "congress": 112, "chamber": "House", "meetingStatus": "Held", "date": "2012-01-01", "committees": [{"systemCode": "hsju00"}]},
        {"_url": "sched112", "eventId": "sched112", "congress": 112, "chamber": "House", "meetingStatus": "Scheduled", "date": "2012-02-01", "committees": [{"systemCode": "hsju00"}]},
        {"_url": "sched119", "eventId": "sched119", "congress": 119, "chamber": "Senate", "meetingStatus": "Scheduled", "date": "2026-01-01", "committees": [{"systemCode": "ssbu00"}]},
        {"_url": "cancel", "eventId": "cancel", "congress": 119, "chamber": "Senate", "meetingStatus": "Canceled", "date": "2026-02-01", "committees": [{"systemCode": "slia00"}]},
    ]
    path = tmp_path / "meetings.jsonl.gz"
    meetings_write({row["_url"]: row for row in rows}, path)

    def ids(scope):
        return {row["eventId"] for row in read_scoped(path, scope=scope)}

    assert {row["eventId"] for row in read_inventory(path)} == {"sched119"}
    assert {row["eventId"] for row in read_scoped(path)} == {"sched119"}
    assert ids(scheduled_or_rescheduled) == {"sched112", "sched119"}
    assert ids(all_meetings) == {"held112", "sched112", "sched119", "cancel"}
    loaded = load_meetings(path)
    assert {record["eventId"] for dates in loaded.values() for records in dates.values() for record in records} == {"sched112", "sched119"}

    previous = dict(metadata.PATHS)
    try:
        metadata.set_paths(previous["gpo"], str(path))
        assert set(metadata.meetings()) == {"held112", "sched112", "sched119", "cancel"}
        missing = tmp_path / "absent.jsonl.gz"
        metadata.set_paths(previous["gpo"], str(missing))
        with caplog.at_level(logging.WARNING):
            assert metadata.meetings() == {}
            assert load_meetings(missing) == {}
        assert "no meetings file" in caplog.text
        assert "No meetings file" in caplog.text
    finally:
        metadata.set_paths(previous["gpo"], previous["meetings"])


def test_short_api_page_with_next_is_not_treated_as_complete(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    offsets = []
    monkeypatch.setattr(meetings, "CONGRESS_METADATA", {"112": {}})
    def get(session, address, key, params=None):
        if params:
            offsets.append(params["offset"])
            return {"committeeMeetings": [{"url": url}] if params["offset"] == 0 else [{"url": url + "2"}],
                    "pagination": {"next": "next"} if params["offset"] == 0 else {}}
        return {"committeeMeeting": old}
    monkeypatch.setattr(meetings, "get", get)
    meetings.main(path, nthreads=1)
    assert offsets == [0, 1]
    assert len(meetings_read(path)) == 2


def test_missing_collection_field_is_an_error_not_confirmed_empty(tmp_path, monkeypatch):
    path, _, _ = setup(monkeypatch, tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(meetings, "get", lambda *args: {})
    with pytest.raises(KeyError, match="committeeMeetings"):
        meetings.main(path, nthreads=1)
    assert path.read_bytes() == before
    rejected = json.loads(path.with_suffix(path.suffix + '.rejected.json').read_text())
    assert rejected[0]['response'] == {}


def test_repeating_pagination_fails_without_replacing_snapshot(tmp_path, monkeypatch):
    path, url, _ = setup(monkeypatch, tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(meetings, "get", lambda *args: {"committeeMeetings": [{"url": url}], "pagination": {"next": "next"}})
    with pytest.raises(ValueError, match="repeated a page"):
        meetings.main(path, nthreads=1)
    assert path.read_bytes() == before


def test_incomplete_detail_does_not_replace_previously_saved_record(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(meetings, "get", lambda session, address, key, params=None: {"committeeMeetings": [{"url": url}]} if params else {"committeeMeeting": {}})
    with pytest.raises(SystemExit):
        meetings.main(path, nthreads=1)
    assert meetings_read(path)[url] == old
    assert pending(path) == [url]
    retained = json.loads(path.with_suffix(path.suffix + ".pending.json").read_text())
    assert retained['responses'][url] == {'committeeMeeting': {}}


def test_rejected_source_survives_a_later_snapshot_write_failure(tmp_path, monkeypatch):
    path, url, old = setup(monkeypatch, tmp_path)
    raw = {'committeeMeeting': {**old, 'congress': 'unexpected publisher value'}}
    monkeypatch.setattr(meetings, 'get', lambda session, address, key, params=None:
                        {'committeeMeetings': [{'url': url}]} if params else raw)
    monkeypatch.setattr(meetings, 'write', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        meetings.main(path, nthreads=1)
    retained = json.loads(path.with_suffix(path.suffix + '.pending.json').read_text())
    assert retained['responses'][url] == raw
    assert retained['urls'] == [url]
    assert meetings_read(path)[url] == old
