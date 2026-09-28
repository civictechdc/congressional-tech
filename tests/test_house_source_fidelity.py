"""Original House file groups survive offline replay and adapter conversion."""
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters import house
from congress_api.house import records, repository
from congress_api.house.replay import MATCH_FIELDS, replay
from committee_explorer.ids import IdRegistry

FIXTURES = Path(__file__).parent / "fixtures/meeting_inventory"


def xml(name):
    return repository.parse_xml((FIXTURES / name).read_bytes())


def adapt(saved):
    context = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id="house-state", provider="docs.house.gov", ids=lambda kind, key: kind + ":" + key)
    return list(house.records({"100431": saved}, context, meetings={(113, "house", "100431"): Ref(kind="meeting", id="meeting-1")}))


def test_original_bill_xml_survives_pdf_overlap_in_csv_and_adapter():
    root = xml("house-multiple-files.xml")
    saved = records.parsed(root, None, "", "absent")
    pdf = "https://docs.house.gov/billsthisweek/20130304/BILLS-113hr933ih.pdf"
    rows = list(records.document_rows(saved, "100431", have=[pdf]))
    bill = next(row for row in rows if "BILLS-113hr933ih" in row["url"])
    assert bill["url"].endswith(".xml")
    assert bill["document_type"] == "BR"
    assert bill["add_date"] == "2013-03-04T14:33:35.403"
    assert not any(row["url"] == pdf for row in rows)
    assert all("files" not in row for row in rows)  # Full metadata belongs only in gzip state.
    original = {f.get("doc-url") for f in root.findall("meeting-documents/meeting-document/files/file")}
    representations = [row for row in adapt(saved) if row.kind == "representation"]
    assert {location.url for row in representations for location in row.locations} == original


def test_repeated_raw_entries_keep_individual_dates_and_owners():
    saved = records.parsed(xml("house-multiple-files.xml"), xml("house-repeated-documents.xml"), "", "present")
    rows = list(records.document_rows(saved, "100876"))
    qfr = [row for row in rows if row["url"].endswith("Wstate-BisceglieJ-20130521-SD003.pdf")]
    assert len(qfr) == 2
    assert qfr[0]["url"] == qfr[1]["url"]
    assert qfr[0]["publish_date"] != qfr[1]["publish_date"]
    assert qfr[0]["source_selector"] != qfr[1]["source_selector"]
    assert qfr[0]["owning_witness_selector"] == qfr[1]["owning_witness_selector"]


def test_removed_panel_never_emits_current_witnesses_or_files():
    wlist = xml("house-witnesses.xml")
    wlist.find("panel").set("remove-date", "2026-09-28")
    saved = records.parsed(xml("house-removed.xml"), wlist, "", "present")
    assert saved["documents"] == saved["witnesses"] == []
    assert list(records.document_rows(saved, "100431")) == []
    assert not [row for row in adapt(saved) if row.kind in ("appearance", "representation")]
    assert saved["evidence"]["witness_observations"][0]["metadata"]


def test_html_fallback_preserves_alternate_files_and_reaches_adapter():
    page = (FIXTURES / "house-fallback.html").read_text()
    saved = records.parsed(None, None, page, "unfetched")
    assert len(saved["documents"]) == 4  # Old summary remains usable for replay.
    groups = saved["evidence"]["document_groups"]
    assert len(groups) == 4 and sum(len(group["files"]) for group in groups) == 7
    assert saved["evidence"]["html"] == page
    assert len([row for row in adapt(saved) if row.kind == "representation"]) == 7


def test_fallback_witness_is_not_hidden_by_empty_xml_observations():
    page = '<h2>Witnesses</h2><p><strong>Ms. Example</strong><br/><small>Director, on behalf of Agency</small></p>'
    saved = records.parsed(None, None, page, "unfetched")
    appearance, = [row for row in adapt(saved) if row.kind == "appearance"]
    assert appearance.name.display == "Ms. Example"
    assert appearance.affiliation.position == "Director"


def test_house_codes_and_ownership_survive_adapter():
    saved = records.parsed(xml("house-removed.xml"), xml("house-witnesses.xml"), "", "present")
    rows = adapt(saved)
    assert {row.details.category for row in rows if row.kind == "material"} == {"biography", "statement"}
    appearance, = [row for row in rows if row.kind == "appearance"]
    assert {row.subject.id for row in rows if row.kind == "material_link"} == {appearance.id}


def test_rich_action_preserves_resolution_type_with_legacy_identity():
    saved = records.parsed(xml("house-multiple-files.xml"), None, "", "absent")
    group = next(group for group in saved["evidence"]["document_groups"] if group["type"] == "CV")
    group["metadata"].setdefault("children", []).append({"tag": "legis-num", "text": "H. Res. 123"})
    item = next(row for row in adapt(saved) if row.kind == "legislative_item")
    assert item.item_type == "resolution"
    assert item.id == "legislative_item:house|113|H. Res. 123"


def test_distinct_documents_with_same_add_time_do_not_share_identity():
    root = xml("house-multiple-files.xml")
    for group in root.findall("meeting-documents/meeting-document"):
        group.set("add-date", "2013-03-04T14:33:35.403")
    rows = adapt(records.parsed(root, None, "", "absent"))
    materials = [row for row in rows if row.kind == "material"]
    assert len({row.id for row in materials}) == len(materials) == 5


def legacy_cache(tmp_path):
    path = tmp_path / "docs_house_xml/meeting/100431.xml"
    path.parent.mkdir(parents=True)
    path.write_bytes((FIXTURES / "house-multiple-files.xml").read_bytes())
    witness = tmp_path / "docs_house_xml/wlist/100431.none"
    witness.parent.mkdir(parents=True)
    witness.touch()
    saved = records.parsed(xml("house-multiple-files.xml"), None, "", "absent")
    saved.pop("evidence")
    saved.update(checked="2026-09-27", version="old-api-update", seed="research cache")
    return {"100431": saved}


def test_offline_replay_requires_exact_reproduction_and_never_advances_checks(tmp_path):
    previous = legacy_cache(tmp_path)
    upgraded, report = replay(previous, tmp_path)
    assert report["counts"] == {"replayed": 1}
    saved = upgraded["100431"]
    assert all(saved[field] == previous["100431"][field] for field in previous["100431"])
    assert "retrieved_at" not in saved and "last_check" not in saved
    assert saved["replay"]["mode"] == "offline"
    assert saved["replay"]["matched_fields"] == list(MATCH_FIELDS)
    assert all(len(item["sha256"]) == 64 for item in saved["replay"]["inputs"])
    assert replay(upgraded, tmp_path)[1]["counts"] == {"current": 1}
    newer = deepcopy(previous)
    newer["100431"]["xml_update"] = "2026-09-28T12:00:00"
    refused, report = replay(newer, tmp_path)
    assert refused == newer
    assert report["events"]["100431"]["fields"] == ["xml_update"]
    newer = deepcopy(previous)
    newer["100431"]["documents"][0][1] = "A later source correction"
    assert replay(newer, tmp_path)[0] == newer


def test_replay_does_not_claim_old_live_time_for_expanded_cache_payload(tmp_path):
    previous = legacy_cache(tmp_path)
    previous["100431"].update(retrieved_at="2026-09-27T12:00:00Z", last_check={"mode": "live", "outcome": "present"})
    upgraded, _ = replay(previous, tmp_path)
    source, = [row for row in adapt(upgraded["100431"]) if row.kind == "source_record"]
    assert source.retrieved_at is None
    assert source.payload["retrieved_at"] == "2026-09-27T12:00:00Z"


def test_malformed_upstream_url_stays_visible_as_an_issue():
    root = xml("house-multiple-files.xml")
    root.find("meeting-documents/meeting-document/files/file").set("doc-url", "mailto:https://www.congress.gov/bill.pdf")
    rows = adapt(records.parsed(root, None, "", "absent"))
    issue, = [row for row in rows if row.kind == "data_issue" and row.category == "incorrect"]
    assert issue.provenance.citations[0].selector == "/evidence/document_groups/0/files/0/url"
    assert not [row for row in rows if row.kind == "representation" and row.locations[0].url.startswith("mailto:")]


def test_same_name_observations_in_separate_panels_do_not_collapse():
    wlist = xml("house-witnesses.xml")
    wlist.append(deepcopy(wlist.find("panel")))
    wlist.findall("panel")[1].set("sort-order", "2")
    rows = adapt(records.parsed(xml("house-removed.xml"), wlist, "", "present"))
    appearances = [row for row in rows if row.kind == "appearance"]
    assert len(appearances) == len({row.id for row in appearances}) == 2
    assert len({row.panel.id for row in appearances}) == 2


def test_removed_names_do_not_change_active_witness_identity():
    wlist = xml("house-witnesses.xml")
    before = [row.id for row in adapt(records.parsed(xml("house-removed.xml"), wlist, "", "present")) if row.kind == "appearance"]
    duplicate = deepcopy(wlist.find("panel/witness"))
    duplicate.set("remove-date", "2026-09-28")
    wlist.find("panel").append(duplicate)
    after = [row.id for row in adapt(records.parsed(xml("house-removed.xml"), wlist, "", "present")) if row.kind == "appearance"]
    assert after == before


def test_replay_preserves_unambiguous_published_material_and_version_ids(tmp_path):
    saved = records.parsed(xml("house-multiple-files.xml"), None, "", "absent")
    legacy = {key: value for key, value in saved.items() if key != "evidence"}
    ids = IdRegistry(tmp_path / "ids.json")
    context = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id="house-state", provider="docs.house.gov", ids=ids)
    lookup = {(113, "house", "100431"): Ref(kind="meeting", id="meeting-1")}
    before = list(house.records({"100431": legacy}, context, meetings=lookup))
    after = list(house.records({"100431": saved}, context, meetings=lookup))
    for kind in ("material", "material_version"):
        assert {row.id for row in before if row.kind == kind} == {row.id for row in after if row.kind == kind}
    ids.save()
    context.ids = IdRegistry(tmp_path / "ids.json")
    repeated = list(house.records({"100431": saved}, context, meetings=lookup))
    assert {row.id for row in repeated if row.kind == "material"} == {row.id for row in after if row.kind == "material"}
    assert len([row for row in after if row.kind == "representation"]) == 7


def test_ambiguous_repeated_source_entries_do_not_alias_published_identity(tmp_path):
    root = xml("house-multiple-files.xml")
    original = root.find("meeting-documents/meeting-document")
    copy = deepcopy(original)
    copy.set("add-date", "2013-03-06T10:00:00")
    root.find("meeting-documents").append(copy)
    saved = records.parsed(root, None, "", "absent")
    legacy = {key: value for key, value in saved.items() if key != "evidence"}
    ids = IdRegistry(tmp_path / "ids.json")
    context = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id="house-state", provider="docs.house.gov", ids=ids)
    lookup = {(113, "house", "100431"): Ref(kind="meeting", id="meeting-1")}
    before = list(house.records({"100431": legacy}, context, meetings=lookup))
    after = list(house.records({"100431": saved}, context, meetings=lookup))
    title = saved["evidence"]["document_groups"][0]["description"]
    old_ids = {row.id for row in before if row.kind == "material" and row.title == title}
    new_ids = {row.id for row in after if row.kind == "material" and row.title == title}
    assert len(old_ids) == 1 and len(new_ids) == 2 and not old_ids & new_ids
