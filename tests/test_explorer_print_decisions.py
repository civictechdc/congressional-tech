"""Match explanations are additive; the established matching policy is fixed."""
import json

import pytest
from congress_api.matching.gpo_videos import similarity, words
from congress_api.matching.prints import match_prints

PACKAGE = "CHRG-119hhrg123"


def meeting(event="1", **updates):
    return {"eventId": event, "congress": 119, "date": "2026-09-20", "type": "Hearing",
            "title": "Competition in digital information markets", "committees": [{"systemCode": "hsju00"}], **updates}


def package(**updates):
    return {"package_id": PACKAGE, "congress": "119", "event_id": "", "committee_code": "hsju00",
            "title": "Agricultural insurance commodity programs", "held_date": "2026-09-20", "hearing_dates": "", **updates}


def serialized_matches(matches):
    return json.dumps({event: sorted(packages) for event, packages in matches.items()}, sort_keys=True)


@pytest.mark.parametrize("rule,meetings,packages,attached,expected", [
    ("package_event_id", [meeting()], [package(event_id="1", committee_code="hsag00", held_date="2020-01-01")], None, {"1": {PACKAGE}}),
    ("attached_file", [meeting(meetingDocuments=[{"url": f"http://example.org/{PACKAGE}.pdf"}]), meeting("2", title="Transportation infrastructure investment")], [package()], None, {"1": {PACKAGE}, "2": set()}),
    ("collection_day", [meeting(), meeting("2", title="Transportation infrastructure investment")], [package(title="APPROPRIATIONS FOR FISCAL YEAR 2027")], None, {"1": {PACKAGE}, "2": {PACKAGE}}),
    ("markup_print_day", [meeting(type="Markup")], [package(title="Markup of agricultural insurance commodity programs")], None, {"1": {PACKAGE}}),
    ("unique_committee_day", [meeting()], [package()], None, {"1": {PACKAGE}}),
    ("title_similarity", [meeting(), meeting("2", title="Transportation infrastructure investment")], [package(title="Competition in digital information markets")], None, {"1": {PACKAGE}, "2": set()}),
])
def test_each_accepted_branch_explains_unchanged_results(rule, meetings, packages, attached, expected):
    decisions = []
    plain = match_prints(meetings, packages, attached)
    explained = match_prints(meetings, packages, attached, decisions=decisions)
    assert plain == explained == expected
    assert serialized_matches(plain) == serialized_matches(explained)
    assert rule in {decision["rule"] for decision in decisions}
    assert all(decision["rule_version"] == ("2" if decision["rule"] in ("markup_print_day", "unique_committee_day") else "1")
               for decision in decisions)
    assert all(decision["package_id"] in expected[decision["event_id"]] for decision in decisions)
    for decision in decisions:
        assert decision["evidence"]["meeting"]["eventId"] == decision["event_id"]
        assert decision["evidence"]["packages"][0]["package_id"] == decision["package_id"]


def test_multiple_reasons_preserve_real_title_score_and_native_fields():
    title = "APPROPRIATIONS FOR FISCAL YEAR 2027"
    meetings = [meeting(title=title, meetingDocuments=[{"url": f"https://example.org/{PACKAGE}.pdf"}])]
    packages = [package(event_id="1", title=title)]
    decisions = [{"already": "present"}]
    assert match_prints(meetings, packages, decisions=decisions) == {"1": {PACKAGE}}
    assert decisions[0] == {"already": "present"}  # Caller-owned list is appended to.
    reasons = {decision["rule"]: decision for decision in decisions[1:]}
    assert set(reasons) == {"package_event_id", "title_similarity", "collection_day", "attached_file", "unique_committee_day"}
    title_evidence = reasons["title_similarity"]["evidence"]
    assert title_evidence["score"] == similarity(words(title), words(title))
    assert title_evidence["threshold"] == 0.4
    assert reasons["package_event_id"]["basis"] == "derived"
    assert reasons["unique_committee_day"]["basis"] == "inferred"
    assert reasons["attached_file"]["evidence"]["meeting_document_urls"] == [f"https://example.org/{PACKAGE}.pdf"]
    assert reasons["unique_committee_day"]["evidence"]["meeting_count"] == 1
    assert all("score" not in decision["evidence"] for name, decision in reasons.items() if name != "title_similarity")


def test_same_day_title_sharing_names_original_matches_and_respects_share_flag():
    meetings = [meeting(), meeting("2", committees=[{"systemCode": "hsag00"}])]
    packages = [package(event_id="1", title=meetings[0]["title"])]
    decisions = []
    expected = {"1": {PACKAGE}, "2": {PACKAGE}}
    assert match_prints(meetings, packages) == match_prints(meetings, packages, decisions=decisions) == expected
    sharing, = [decision for decision in decisions if decision["rule"] == "same_day_title_sharing"]
    assert sharing["event_id"] == "2" and sharing["shared_from"] == ["1"]
    assert sharing["basis"] == "inferred" and sharing["evidence"]["matching_day"] == "2026-09-20"
    no_share = []
    assert match_prints(meetings, packages, share=False, decisions=no_share) == {"1": {PACKAGE}, "2": set()}
    assert not any(decision["rule"] == "same_day_title_sharing" for decision in no_share)


def test_attached_package_still_requires_existing_committee_day_candidate():
    meetings, packages = [meeting()], [package(held_date="2020-01-01")]
    decisions = []
    assert match_prints(meetings, packages, {"1": {PACKAGE}}, decisions=decisions) == {"1": set()}
    assert decisions == []


@pytest.mark.parametrize('row', [
    meeting(type='Markup'),
    meeting(type='Closed Markup Session'),
    meeting(type='Meeting', title='Full Committee Markup'),
])
def test_all_markup_spellings_use_the_same_print_rules(row):
    assert match_prints([row], [package()]) == {'1': set()}
    decisions = []
    assert match_prints([row], [package(title='Markup of agricultural insurance commodity programs')],
                        decisions=decisions) == {'1': {PACKAGE}}
    reason = next(d for d in decisions if d['rule'] == 'markup_print_day')
    assert reason['rule_version'] == '2'
    assert reason['evidence']['meeting_type'] == 'markup'
    assert reason['evidence']['meeting_type_source'] == ('/title' if row['type'] == 'Meeting' else '/type')
    assert not any(d['rule'] == 'unique_committee_day' for d in decisions)


def test_multiple_committee_paths_keep_native_codes_and_matching_alias():
    meetings = [meeting(committees=[{"systemCode": "hlqj00"}, {"systemCode": "hsag00"}])]
    packages = [package()]
    decisions = []
    match_prints(meetings, packages, decisions=decisions)
    assert decisions[0]["evidence"]["meeting"]["committees"] == meetings[0]["committees"]
    assert decisions[0]["evidence"]["matching_committee_code"] == "hsju00"
