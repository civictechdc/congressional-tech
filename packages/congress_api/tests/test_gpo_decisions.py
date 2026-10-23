"""Greedy assignment and research overrides for GPO video verdicts."""

from congress_api.matching.gpo_decisions import decide
from congress_api.matching.gpo_videos import words


def hearing(package_id, day, event_id="", title="Competition in digital information markets"):
    return {"package_id": package_id, "congress": "114", "chamber": "House", "committee_code": "hsju00",
            "title": title, "held_date": day, "hearing_dates": "", "event_id": event_id,
            "subcommittees": "", "record_type": "hearing"}


def video(published="2015-03-19", event_ids=(), duration=3600, title="Competition in digital information markets"):
    return {"videoId": "abcdefghijk", "channel": "judiciary", "published": published, "title": title,
            "words": words(title), "dates": set(), "event_ids": set(event_ids), "duration": duration, "audio_only": False}


def rows_by_id(rows):
    return {row["package_id"]: row for row in rows}


def test_greedy_assignment_keeps_the_stronger_hearing_on_another_day():
    hearings = [hearing("early", "2015-03-18"), hearing("later", "2015-03-19", event_id="117681")]
    rows = rows_by_id(decide(hearings, {"hsju00": [video(published="2015-03-18", event_ids={"117681"})]}, {}, tracked_codes={"hsju00"}))
    assert rows["later"]["status"] == "full_recording"
    assert rows["later"]["video_ids"] == "abcdefghijk"
    assert rows["later"]["score"] == 95
    assert rows["early"]["video_ids"] == ""
    assert rows["early"]["status"] == "no_video_found"


def test_negative_override_yields_only_to_strong_evidence_unless_locked():
    strong = [hearing("pkg", "2015-03-19", event_id="117681")]
    weak = [hearing("pkg", "2015-03-19")]
    videos = {"hsju00": [video(event_ids={"117681"})]}
    weak_videos = {"hsju00": [video()]}
    negative = {"pkg": {"verdict": "no_video_found", "video_ids": "", "channel": "", "note": "reviewed absent"}}
    beaten = rows_by_id(decide(strong, videos, {}, {**negative}, tracked_codes={"hsju00"}))["pkg"]
    assert beaten["status"] == "full_recording"
    assert "newer evidence" in beaten["note"]
    held = rows_by_id(decide(weak, weak_videos, {}, negative, tracked_codes={"hsju00"}))["pkg"]
    assert held["status"] == "no_video_found" and held["video_ids"] == "" and held["source"] == "research"
    locked = rows_by_id(decide(strong, videos, {}, {"pkg": {**negative["pkg"], "lock": "yes"}}, tracked_codes={"hsju00"}))["pkg"]
    assert locked["status"] == "no_video_found" and locked["video_ids"] == "" and locked["source"] == "research"
