"""Retained EPW source structure preserves testimony ownership through extraction."""
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.senate import records
from congress_api.lake.appearance_records import extract_senate_page_observation
from congress_api.parsers.senate import parsed


FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"
ORIGIN = "https://www.epw.senate.gov"
OWNED = "/public/?a=Files.Serve&File_id=391EA31E-7410-4755-BC58-CDE2E371224A"
UNGROUPED = "/public/?a=Files.Serve&File_id=B32A431F-9FD6-4B2A-9793-60F9A0798533"
CASES = [
    ("owned", "849703A0-3081-4FD8-BB1B-316B56FF3DF0", OWNED,
     ["Kristine Svinicki", "Jeff Baran", "Stephen Burns", "Annie Caputo", "David Wright"], [0]),
    ("ungrouped", "44BD2998-A955-42FF-8158-49DE2AD56DD3", UNGROUPED,
     ["Rickey Dale “R.D.” James", "Ryan Fisher", "Todd Semonite", "Charlotte Bertrand"], []),
]


@pytest.mark.parametrize("case,page_id,literal,names,owners", CASES)
def test_retained_epw_lake_keeps_only_source_assigned_testimony(case, page_id, literal, names, owners):
    raw = (FIXTURES / f"senate-epw-{case}-testimony.html").read_text()
    observation = extract_senate_page_observation(raw)
    assert observation["collection_state"] == "present"
    people = observation["appearances"]
    assert [p["name"] for p in people] == names
    assert [p["source_locator"] for p in people] == [f"senate_page:witness[{i}]" for i in range(1, len(names) + 1)]
    assert [i for i, p in enumerate(people) if literal in p["document_links"]] == owners
    assert [p["document_links"] for p in people] == [[literal] if i in owners else [] for i in range(len(names))]
    if owners:
        assert (people[0]["position"], people[0]["organization"]) == ("Chairman", "U.S. Nuclear Regulatory Commission")


@pytest.mark.parametrize("case,page_id,literal,names,owners", CASES)
def test_retained_epw_source_adapter_keeps_hearing_and_individual_links(case, page_id, literal, names, owners):
    url = f"{ORIGIN}/public/index.cfm/hearings?ID={page_id}"
    raw = (FIXTURES / f"senate-epw-{case}-testimony.html").read_text()
    saved = json.loads(json.dumps(parsed(raw, url)))
    assert saved["document_metadata"][ORIGIN + literal]["witness_indexes"] == owners
    saved["events"] = ["12"]  # Adapter control; native event matching is qualified separately.
    context = AdapterContext(now=datetime(2026, 11, 6, tzinfo=UTC), input_id="epw-fixture", provider="senate",
                             ids=lambda kind, key: kind + ":" + key)
    rows = list(records({"epw.senate.gov": {"pages": {url: saved}}}, context,
                        meetings={(119, "senate", "12"): Ref(kind="meeting", id="meeting-12")}))
    representations = [r for r in rows if r.kind == "representation" and any(l.url == ORIGIN + literal for l in r.locations)]
    representation, = representations
    links = [r for r in rows if r.kind == "material_link" and r.version == representation.version]
    assert any(link.subject.kind == "meeting" and link.subject.id == "meeting-12" for link in links)
    appearances = {r.id: r for r in rows if r.kind == "appearance"}
    individual = [appearances[link.subject.id].name.display for link in links if link.subject.kind == "appearance"]
    assert individual == [names[i] for i in owners]
