"""Inventory observations do not manufacture caption tracks or witness identity."""
from datetime import UTC, datetime

from committee_meeting.common import Ref, ReportedTime
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.inventory import records


NOW = datetime(2026, 9, 27, tzinfo=UTC)
MATERIAL = Ref(kind="material", id="recording")
MEETING = Ref(kind="meeting", id="meeting")


def adapt(state, *, materials=None, meetings=None, recovered_witnesses=()):
    context = AdapterContext(now=NOW, provider="inventory", input_id="retained-input", ids=lambda kind, key: kind + ":" + key)
    return list(records(state, context, meetings=meetings or {(119, "senate", "12"): MEETING}, materials=materials, recovered_witnesses=recovered_witnesses))


def of_kind(rows, kind):
    return [row for row in rows if row.kind == kind]


def test_caption_positive_is_reported_but_undated_negative_is_unknown():
    rows = adapt({"youtube": {"yes": "auto", "no": "none"}, "senate": {"vtt": "webvtt"}}, materials={
        ("youtube", "yes"): MATERIAL, ("youtube", "no"): Ref(kind="material", id="negative"), ("senate", "vtt"): Ref(kind="material", id="senate")})
    assessments = {a.subject.id: a for a in of_kind(rows, "assessment")}
    assert assessments["recording"].status == assessments["senate"].status == "available"
    assert assessments["negative"].status == "unknown"
    assert all(a.observed_at is None and not a.results for a in assessments.values())
    assert all(a.provenance.basis == "reported" for a in assessments.values())
    assert not of_kind(rows, "material") and not of_kind(rows, "representation")
    assert all(source.retrieved_at is None for source in of_kind(rows, "source_record"))


def test_unknown_caption_target_keeps_small_observation_and_issue():
    rows = adapt({"youtube": {"unknown-id": "manual"}})
    source, = of_kind(rows, "source_record")
    assert source.payload == {"provider": "youtube", "recording_id": "unknown-id", "kind": "manual"}
    assert not of_kind(rows, "assessment")
    assert any(issue.category == "unlinked" for issue in of_kind(rows, "data_issue"))


def test_imported_probe_date_is_not_a_live_observation():
    player = "https://www.senate.gov/isvp/?comm=budget&filename=budget092026"
    rows = adapt({"probes": {"budget|2026-09-20": {"source": "research HEAD cache", "checked": "2026-09-25", "urls": [player]}}}, materials={("senate", "budget092026"): MATERIAL})
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "available" and assessment.observed_at is None
    assert of_kind(rows, "source_record")[0].retrieved_at is None
    assert any(issue.category == "unverified" for issue in of_kind(rows, "data_issue"))


def test_live_negative_probe_keeps_day_precision_and_exact_source_scope():
    rows = adapt({"probes": {"budget|2026-09-20": {"source": "HEAD", "checked": "2026-09-25", "urls": []}}}, materials={("senate", "budget092026"): MATERIAL})
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "not_found" and isinstance(assessment.observed_at, ReportedTime)
    assert assessment.observed_at.precision == "day" and assessment.observed_at.time is None
    assert "budget092026_1/master.m3u8" in assessment.scope and "HEAD " in assessment.scope
    assert of_kind(rows, "source_record")[0].retrieved_at is None
    malformed = adapt({"probes": {"budget|2026-09-20": {"source": "HEAD", "checked": "2026-09-25", "urls": "not-a-list"}}}, materials={("senate", "budget092026"): MATERIAL})
    assert not of_kind(malformed, "assessment")


def test_mods_people_need_explicit_recovered_meeting_ownership():
    state = {"mods": {"package": {"people": [{"name": "Alex Smith"}], "checked": "2026-09-25", "url": "https://example.org/mods.xml", "absent": False}}}
    rows = adapt(state)
    assert len(of_kind(rows, "source_record")) == 1 and not of_kind(rows, "appearance")
    assert any(issue.category == "unlinked" for issue in of_kind(rows, "data_issue"))
    recovered = {"event_id": "12", "name": "Alex Smith", "position": "Director", "organization": "Institute", "source": "gpo", "from": "package"}
    rows = adapt(state, recovered_witnesses=[recovered])
    appearance, = of_kind(rows, "appearance")
    assert appearance.meeting == MEETING and appearance.person is None and appearance.participation == "listed"
    assert len(appearance.provenance.citations) == 2
    assert not any(issue.category == "unlinked" for issue in of_kind(rows, "data_issue"))


def test_ambiguous_or_malformed_recovered_rows_never_guess():
    witness = {"event_id": "12", "name": "Alex Smith", "source": "gpo", "from": "package"}
    lookup = {(118, "senate", "12"): MEETING, (119, "senate", "12"): Ref(kind="meeting", id="other")}
    rows = adapt({}, meetings=lookup, recovered_witnesses=[witness, {"event_id": "12", "name": ""}])
    assert not of_kind(rows, "appearance")
    assert {issue.category for issue in of_kind(rows, "data_issue")} == {"unlinked", "unverified"}
    malformed = adapt({}, recovered_witnesses=[None, {**witness, "from": []}])
    assert not of_kind(malformed, "appearance")
    assert len(of_kind(malformed, "data_issue")) == 2


def test_title_nominee_does_not_become_a_testifying_witness():
    nominee = {"event_id": "12", "name": "Alex Smith", "source": "meeting title (nominees)", "from": "https://api.congress.gov/v3/committee-meeting/119/senate/12"}
    appearance, = of_kind(adapt({}, recovered_witnesses=[nominee]), "appearance")
    assert appearance.roles == ("nominee",) and appearance.participation == "listed"
    assert appearance.provenance.basis == "inferred" and appearance.person is None
