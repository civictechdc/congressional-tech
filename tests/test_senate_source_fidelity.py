"""Real retained HTML keeps witness-card ownership through state and adaptation."""
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from congress_api.matching.senate_pages import retained_matches
from congress_api.parsers.senate import parsed
from congress_api.replay.senate import replay
from test_explorer_senate_adapter import adapt, of_kind

FIXTURES = Path(__file__).parent / "fixtures" / "meeting_inventory"
URL = "https://www.aging.senate.gov/hearings/-21st-century-caregiving-supporting-workers-family-caregivers-seniors-and-people-with-disabilities"
FILE = "https://www.aging.senate.gov/download/sca_ai-jen_poo_6_17_21"


@pytest.mark.parametrize("number,people,owned", [(1, 3, 0), (2, 1, 1), (3, 3, 0), (4, 2, 2), (5, 1, 0), (6, 7, 7), (7, 3, 3)])
def test_all_seven_real_card_layouts(number, people, owned):
    result = parsed((FIXTURES / f"senate-{number}.html").read_text(), URL)
    assert len(result["witness_metadata"]) == people
    assert sum(bool(file["witness_indexes"]) for file in result["document_metadata"].values()) == owned
    for file in result["document_metadata"].values():
        assert all(0 <= index < len(result["witnesses"]) for index in file["witness_indexes"])


def test_real_page_preserves_content_order_and_player_attributes_in_source():
    saved = json.loads(json.dumps(parsed((FIXTURES / "senate-aging-page-content.html").read_text(), URL)))
    saved["events"] = ["12"]
    content = saved["page_metadata"]
    assert content["text"].index("Member Statements") < content["text"].index("Witnesses") < content["text"].index("Related Transcripts")
    player, = content["media"]
    assert player == {"tag": "iframe", "attributes": {
        "title": " 21st Century Caregiving: Supporting Workers, Family Caregivers, Seniors and People with Disabilities",
        "src": "https://www.senate.gov/isvp/?auto_play=false&comm=aging&filename=aging061721&poster=https://www.aging.senate.gov/assets/images/video-poster.png"}}
    assert content["links"] == [{"text": "Back To Hearings", "attributes": {
        "class": "Breadcrumbs__button h-100 mt-5 mt-lg-0 mb-3", "href": "https://www.aging.senate.gov/hearings"}}]
    assert of_kind(adapt(saved), "source_record")[0].payload == saved


def test_real_panel_heading_is_preserved_on_each_explicit_member_card():
    saved = parsed((FIXTURES / "senate-4.html").read_text(), URL)
    assert {card["panel"] for card in saved["witness_metadata"].values()} == {"Witness Panel 1"}
    words = saved["page_metadata"]["text"]
    assert words.index("Witness Panel 1") < words.index("Shannon Estenoz") < words.index("Chris French")


def test_source_content_keeps_repeated_prose_meta_and_data_but_not_scripts():
    raw = '<meta name="description" content="A hearing summary"><p>Repeated fact</p><p>Repeated fact</p><script>Executable boilerplate</script><style>Layout boilerplate</style><script type="application/ld+json">{"description":"Source fact"}</script>'
    saved = parsed(raw, URL)["page_metadata"]
    assert saved["text"] == "Repeated fact\nRepeated fact"
    assert saved["meta"] == [{"name": "description", "content": "A hearing summary"}]
    assert saved["structured_data"] == ['{"description":"Source fact"}']


def test_non_file_source_links_keep_literal_text_destination_and_attributes():
    raw = '<p>Legislative hearing on <a href="https://www.congress.gov/bill/119th-congress/senate-bill/10" data-bill="s10" title="Source bill">S. 10</a></p><p>Witness organization: <a href="/about" rel="external">Institute</a></p><a href="/document.pdf" type="application/pdf">Testimony</a>'
    saved = json.loads(json.dumps(parsed(raw, URL)))
    saved["events"] = ["12"]
    assert saved["page_metadata"]["links"] == [
        {"text": "S. 10", "attributes": {"href": "https://www.congress.gov/bill/119th-congress/senate-bill/10", "data-bill": "s10", "title": "Source bill"}},
        {"text": "Institute", "attributes": {"href": "/about", "rel": "external"}}]
    assert saved["document_metadata"]["https://www.aging.senate.gov/document.pdf"]["attributes"] == [{"href": "/document.pdf", "type": "application/pdf"}]
    assert of_kind(adapt(saved), "source_record")[0].payload == saved


def test_real_inline_player_configuration_survives_without_executing_javascript():
    from lxml import html
    raw = (FIXTURES / "senate-hsgac-player-config.html").read_text()
    saved = json.loads(json.dumps(parsed(raw, "https://www.hsgac.senate.gov/hearings/whistleblower-testimony-on-the-covid-coverup/")))
    scripts = saved["page_metadata"]["media_scripts"]
    assert scripts == [{"attributes": dict(node.attrib), "text": node.text or ""} for node in html.fromstring(raw).xpath(".//script")]
    assert len(scripts) == 4
    assert 'archive_stream = "govtaff051326"' in scripts[0]["text"]
    assert 'archive_offset = "910"' in scripts[1]["text"]
    assert 'originalTimestamp = 1778665620' in scripts[2]["text"]
    assert 'iframeSrc.replace("STREAM", encodeURIComponent(archive_stream))' in scripts[3]["text"]
    assert not saved["page_metadata"].get("media")
    saved["events"] = ["12"]
    rows = adapt(saved)
    source, = of_kind(rows, "source_record")
    readback = json.loads(source.model_dump_json())
    assert readback["payload"] == saved
    assert readback["payload"]["page_metadata"]["media_scripts"][1]["text"] == scripts[1]["text"]
    assert not of_kind(rows, "material")


def test_generic_player_library_options_are_not_hearing_configuration():
    raw = '<script>const app={player:"jwplayer",youtube:true};</script><script src="/player.js"></script>'
    assert "media_scripts" not in parsed(raw, URL)["page_metadata"]


def test_aging_card_retains_ownership_location_and_source_words_to_output():
    saved = json.loads(json.dumps(parsed((FIXTURES / "senate-aging-witness-card.html").read_text(), URL)))
    saved["events"] = ["12"]
    assert saved["witnesses"][0]["name"] == "Ai-jen Poo"
    assert saved["witness_metadata"]["0"]["location"] == "Chicago, IL"
    assert saved["document_metadata"][FILE]["witness_indexes"] == [0]
    assert saved["document_metadata"][FILE]["labels"] == ["SCA_Ai-jen_Poo_6_17_21"]
    rows = adapt(saved)
    appearance, = of_kind(rows, "appearance")
    assert appearance.affiliation.location == "Chicago, IL"
    links = of_kind(rows, "material_link")
    assert {link.subject.kind for link in links} == {"meeting", "appearance"}
    assert next(link for link in links if link.subject.kind == "appearance").subject.id == appearance.id
    legacy = {key: value for key, value in saved.items() if key not in ("document_metadata", "witness_metadata")}
    assert of_kind(adapt(legacy), "appearance")[0].id == appearance.id
    assert of_kind(adapt(legacy), "material")[0].id == of_kind(rows, "material")[0].id
    assert of_kind(rows, "source_record")[0].payload == saved
    _, witnesses, documents = retained_matches({"aging.senate.gov": {"pages": {URL: saved}}})
    assert witnesses[0]["location"] == "Chicago, IL"
    assert documents[0]["witness_names"] == '["Ai-jen Poo"]'


def test_unsupported_name_only_proximity_does_not_create_ownership():
    raw = (FIXTURES / "senate-aging-witness-card.html").read_text()
    raw += "<p>Ai-jen Poo</p><a href='/download/unowned' type='application/pdf'>Other evidence</a>"
    saved = json.loads(json.dumps(parsed(raw, URL)))
    saved["events"] = ["12"]
    file = "https://www.aging.senate.gov/download/unowned"
    assert saved["document_metadata"][file]["witness_indexes"] == []
    rows = adapt(saved)
    representation = next(row for row in of_kind(rows, "representation") if row.locations[0].url == file)
    assert representation.media_type == "application/pdf"
    assert not any(link.subject.kind == "appearance" and link.version == representation.version for link in of_kind(rows, "material_link"))


def test_replay_is_additive_and_protects_live_receipts(tmp_path):
    raw = (FIXTURES / "senate-aging-witness-card.html").read_text()
    (tmp_path / (re.sub(r"\W+", "_", URL)[-180:] + ".html")).write_text(raw)
    saved = parsed(raw, URL)
    del saved["document_metadata"], saved["witness_metadata"]
    saved.update(events=["12"], checked="2025-04-03", imported_at="2025-04-03T10:00:00Z", match_details={"12": {"method": "kept"}})
    state = {"aging.senate.gov": {"pages": {URL: saved}, "listings": {URL: ["2021-06-17", "Hearing"]}}}
    before = deepcopy(state)
    output, report = replay(state, tmp_path, meetings=[], parsed_at="2026-09-28T00:00:00Z")
    page = output["aging.senate.gov"]["pages"][URL]
    assert state == before
    for key, value in saved.items():
        assert page[key] == value
    assert report["counts"]["replayed_pages"] == 1
    assert page["cache_replay"]["acquisition_time"] is None
    assert "retrieved_at" not in page and "last_check" not in page
    assert replay(output, tmp_path, meetings=[])[0] == output
    saved["last_check"] = {"mode": "live", "completed_at": "2026-09-27T00:00:00Z"}
    assert replay(state, tmp_path, meetings=[])[0] == state


def test_replay_rejects_changed_source_text(tmp_path):
    raw = (FIXTURES / "senate-aging-witness-card.html").read_text()
    (tmp_path / (re.sub(r"\W+", "_", URL)[-180:] + ".html")).write_text(raw)
    saved = parsed(raw, URL)
    saved["lines"].append("A newer observation")
    state = {"aging.senate.gov": {"pages": {URL: saved}}}
    output, report = replay(state, tmp_path, meetings=[])
    assert output == state
    assert report["counts"]["different_or_unrecognized_page"] == 1


def test_replayed_event_header_keeps_native_duplicate_guard(tmp_path):
    url = "https://www.hsgac.senate.gov/hearings/business-meeting/"
    raw = '<title>Business Meeting</title><h1>Business Meeting</h1><div class="jet-listing-dynamic-field__content">Date: January 26, 2021</div>'
    saved = parsed(raw, url)
    del saved["event"]
    state = {"hsgac.senate.gov": {"pages": {url: saved}}}
    (tmp_path / (re.sub(r"\W+", "_", url)[-180:] + ".html")).write_text(raw)
    meetings = [{"eventId": "321", "chamber": "Senate", "date": "2021-01-26", "committees": [{"systemCode": "ssga00"}]}]
    output, _ = replay(state, tmp_path, meetings=meetings)
    assert output["hsgac.senate.gov"]["pages"][url]["candidate_events"] == ["321"]
    assert not output["hsgac.senate.gov"]["pages"][url].get("events")


def test_actual_drug_caucus_attachment_aliases_keep_direct_identity_and_both_sources():
    saved = json.loads((FIXTURES.parent / "senate_official" / "drug-duplicate-attachments.json").read_text())
    rows = adapt(saved)
    direct = {**saved, "documents": [document for document in saved["documents"] if "/media-center/files/" not in document[2]]}
    assert len(of_kind(rows, "material")) == 3
    assert {row.id for row in of_kind(rows, "material")} == {row.id for row in of_kind(adapt(direct), "material")}
    assert {row.title for row in of_kind(rows, "material")} == {"Regina LaBelle", "Tom Coderre", "Nora Volkow"}
    assert {location.url for row in of_kind(rows, "representation") for location in row.locations} == {document[2] for document in saved["documents"]}
    assert all(location.role == "landing" for row in of_kind(rows, "representation") for location in row.locations if "/media-center/files/" in location.url)
    assert all(sum(citation.selector.startswith("/documents/") for citation in row.provenance.citations) == 2 for row in of_kind(rows, "material"))


def test_attachment_identity_rejects_different_owners_and_types():
    saved = json.loads((FIXTURES.parent / "senate_official" / "drug-duplicate-attachments.json").read_text())
    landing = saved["documents"][0][2]
    saved["document_metadata"] = {landing: {"witness_indexes": [0]}}
    assert len(of_kind(adapt(saved), "material")) == 4
    saved.pop("document_metadata")
    saved["documents"][0][0] = "witness statement"
    assert len(of_kind(adapt(saved), "material")) == 4
    saved.pop("attachments")
    assert len(of_kind(adapt(saved), "material")) == 6
