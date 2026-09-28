"""Legacy flattened House state still contains useful action metadata."""
from datetime import UTC, datetime
import pytest

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.house import records


PDF = "https://docs.house.gov/meetings/FA/FA00/20260920/1/amendment.pdf"
XML = "https://docs.house.gov/meetings/FA/FA00/20260920/1/amendment.xml"


def action(**updates):
    return {"kind": "amendment", "bill": "5300", "number": "79", "sponsor_bioguide": "S001224", "amendment_type": "substitute",
            "enbloc": "1", "description": "Amendment 79", "url": PDF, **updates}


def adapt(saved, meetings=None):
    context = AdapterContext(now=datetime(2026, 9, 27, tzinfo=UTC), input_id="house-state", provider="docs.house.gov", ids=lambda kind, key: kind + ":" + key)
    return list(records({"1": saved}, context, meetings={(119, "house", "1"): Ref(kind="meeting", id="meeting-1")} if meetings is None else meetings))


def of_kind(rows, kind):
    return [row for row in rows if row.kind == kind]


def test_legacy_action_reuses_exact_document_and_keeps_scoped_metadata():
    saved = {"documents": [["bill or amendment", "Amendment 79", PDF, ["amendment.pdf"]]], "amendments": [action()]}
    rows = adapt(saved)
    material, = of_kind(rows, "material")
    amendment, = of_kind(rows, "amendment")
    assert amendment.number == "79" and amendment.meeting.id == "meeting-1"
    assert amendment.target is None  # The bare source number does not supply a bill type.
    assert amendment.amendment_type == "substitute" and amendment.disposition == "unknown"
    assert amendment.sponsors[0].person.id.endswith("bioguide|S001224")
    assert amendment.provenance.citations[0].selector == "/amendments/0"
    links = [link for link in of_kind(rows, "material_link") if link.subject.kind == "amendment"]
    assert len(links) == 1 and links[0].material.id == material.id
    group, = of_kind(rows, "amendment_group")
    assert group.label == "1" and group.members[0].id == amendment.id
    assert group.provenance.citations[0].selector == "/amendments/0"


def test_format_rows_share_action_and_preserve_extra_exact_url_once():
    saved = {"documents": [["bill or amendment", "Amendment 79", PDF, ["amendment.pdf", "amendment.xml"]]],
             "amendments": [action(), action(url=XML), action(url=XML)]}
    rows = adapt(saved)
    amendment, = of_kind(rows, "amendment")
    assert [citation.selector for citation in amendment.provenance.citations] == ["/amendments/0", "/amendments/1", "/amendments/2"]
    assert len(of_kind(rows, "material")) == 2  # Distinct URLs are not merged using only basenames.
    assert sorted(representation.locations[0].url for representation in of_kind(rows, "representation")) == sorted([PDF, XML])
    assert len([link for link in of_kind(rows, "material_link") if link.subject.kind == "amendment"]) == 2


def test_fileless_vote_has_no_invented_tally_or_attachment():
    saved = {"documents": [], "amendments": [action(kind="vote", number="7", bill="H. Res. 123", enbloc="", sponsor_bioguide="", url="")]}
    rows = adapt(saved)
    vote, = of_kind(rows, "vote")
    assert vote.number == "7" and vote.tally is None and vote.ballots == ()
    assert vote.method == vote.outcome == "unknown"
    item, = of_kind(rows, "legislative_item")
    assert item.designation == "H. Res. 123" and item.item_type == "resolution" and vote.subject.id == item.id
    assert not of_kind(rows, "material") and not of_kind(rows, "material_link")


def test_ambiguous_meeting_preserves_generic_document_but_does_not_assign_action():
    lookup = {(118, "house", "1"): Ref(kind="meeting", id="first"), (119, "house", "1"): Ref(kind="meeting", id="second")}
    saved = {"documents": [["bill or amendment", "Amendment 79", PDF, ["amendment.pdf"]]], "amendments": [action()]}
    rows = adapt(saved, lookup)
    assert not of_kind(rows, "amendment") and len(of_kind(rows, "material")) == 1
    assert not of_kind(rows, "material_link")
    assert of_kind(rows, "source_record")[0].payload["amendments"] == [action()]


def test_same_local_number_in_another_meeting_has_different_identity():
    saved = {"documents": [], "amendments": [action(url="")]}
    context = AdapterContext(now=datetime(2026, 9, 27, tzinfo=UTC), input_id="house-state", provider="docs.house.gov", ids=lambda kind, key: kind + ":" + key)
    rows = list(records({"1": saved, "2": saved}, context, meetings={(119, "house", event): Ref(kind="meeting", id="meeting-" + event) for event in ("1", "2")}))
    amendments = of_kind(rows, "amendment")
    assert len(amendments) == 2 and amendments[0].id != amendments[1].id
    assert {row.number for row in amendments} == {"79"}


def test_rich_document_groups_do_not_reimport_legacy_action_rows():
    rows = adapt({"evidence": {"document_groups": []}, "documents": [], "amendments": [action()]})
    assert not of_kind(rows, "amendment")


def test_failed_house_refresh_keeps_prior_material_and_retrieval_time():
    failed_url = "https://docs.house.gov/meetings/FA/FA00/20260920/1/meeting.xml"
    saved = {"documents": [["bill or amendment", "Amendment 79", PDF, ["amendment.pdf"]]], "amendments": [action()],
             "retrieved_at": "2026-09-20T12:00:00Z", "last_check": {"mode": "live", "outcome": "error", "completed_at": "2026-09-26T12:00:00Z",
                 "receipts": [{"url": failed_url, "outcome": "error", "error": "403 Forbidden"}]}}
    rows = adapt(saved)
    assert len(of_kind(rows, "material")) == 1 and len(of_kind(rows, "amendment")) == 1
    source, = of_kind(rows, "source_record")
    assert source.retrieved_at == datetime(2026, 9, 20, 12, tzinfo=UTC)
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "error" and assessment.aspect == "reachability" and assessment.scope == failed_url
    assert assessment.subject.id == "meeting-1" and assessment.observed_at == datetime(2026, 9, 26, 12, tzinfo=UTC)
    issue, = [item for item in of_kind(rows, "data_issue") if item.id.endswith("failed-refresh")]
    assert issue.last_checked_at == assessment.observed_at and issue.provenance.citations[0].selector == "/last_check"
    assert not of_kind(adapt(saved, meetings={}), "assessment")


@pytest.mark.parametrize("retrieved", ["not a date", "2027-01-01T00:00:00Z", "2026-09-20T12:00:00", 17, ""])
def test_unusable_house_retrieval_times_stay_in_source_payload(retrieved):
    saved = {"documents": [], "retrieved_at": retrieved, "last_check": {"mode": "live", "outcome": "error", "completed_at": "not a date"}}
    rows = adapt(saved)
    source, = of_kind(rows, "source_record")
    assert source.retrieved_at is None and source.payload["retrieved_at"] == retrieved
    assert any(item.id.endswith("invalid-retrieval-time") for item in of_kind(rows, "data_issue"))
    assessment, = of_kind(rows, "assessment")
    assert assessment.status == "error" and assessment.observed_at is None
