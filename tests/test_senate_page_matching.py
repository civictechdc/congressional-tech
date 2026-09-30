"""Senate page subject scoring: threshold, ties, and witness agreement."""

from congress_api.matching.senate_pages import match_pages

HOST = "armed-services.senate.gov"
CODE = "ssas00"
DAY = "2025-03-26"
PAGE_A = f"https://www.{HOST}/hearings/strategic-forces"
PAGE_B = f"https://www.{HOST}/hearings/strategic-forces-alt"


def _meeting(title="Hearings to examine strategic forces."):
    return {"eventId": "336743", "date": DAY, "chamber": "Senate", "type": "Hearing",
            "title": title, "committees": [{"systemCode": CODE}]}


def _state(pages):
    listings = {url: [DAY, pages[url].get("title", "")] for url in pages}
    return {HOST: {"listings": listings, "pages": pages}}


def test_subject_below_half_is_not_a_match():
    state = _state({PAGE_A: {
        "title": "Unrelated nomination", "lines": ["March 26, 2025", "Unrelated nomination of a judge"],
        "documents": [], "witnesses": [{"name": "A"}],
    }})
    # Extra committee titles so "strategic"/"forces" are rare in the corpus but absent from the page.
    meetings = [_meeting(), _meeting(title="Hearings to examine naval shipbuilding."),
                _meeting(title="Hearings to examine personnel policy.")]
    for i, meeting in enumerate(meetings):
        meeting["eventId"] = str(336743 + i)
    found, _, _ = match_pages(meetings[:1], state)
    assert found == []


def test_tied_pages_with_differing_witnesses_are_dropped():
    witnesses_a = [{"name": "Alice"}, {"name": "Bob"}]
    witnesses_b = [{"name": "Alice"}, {"name": "Carol"}]
    lines = ["March 26, 2025", "Hearings to examine strategic forces."]
    state = _state({
        PAGE_A: {"title": "Strategic forces", "lines": lines, "documents": [], "witnesses": witnesses_a},
        PAGE_B: {"title": "Strategic forces", "lines": lines, "documents": [], "witnesses": witnesses_b},
    })
    found, _, _ = match_pages([_meeting()], state)
    assert found == []


def test_tied_pages_with_identical_witnesses_accept_the_first():
    witnesses = [{"name": "Alice"}, {"name": "Bob"}]
    lines = ["March 26, 2025", "Hearings to examine strategic forces."]
    state = _state({
        PAGE_A: {"title": "Strategic forces", "lines": lines, "documents": [], "witnesses": witnesses},
        PAGE_B: {"title": "Strategic forces", "lines": list(lines), "documents": [], "witnesses": list(witnesses)},
    })
    found, people, _ = match_pages([_meeting()], state)
    assert [row["page"] for row in found] == [PAGE_A]
    assert {person["name"] for person in people} == {"Alice", "Bob"}


def test_associate_pages_checkpoints_fuzzy_details_and_exact_replacement():
    from congress_api.matching.senate_pages import associate_pages

    lines = ["March 26, 2025", "Hearings to examine strategic forces."]
    page = {"title": "Strategic forces", "lines": lines, "documents": [], "witnesses": [{"name": "Alice"}],
            "event": {"date": DAY, "title": "Hearings to examine strategic forces."},
            "events": ["fuzzy-id"], "match_details": {"fuzzy-id": {"method": "senate.records.match_pages", "version": "2"}}}
    state = _state({PAGE_A: page})
    meeting = _meeting()
    meeting["hearingTranscript"] = [{"jacketNumber": "37479"}]
    page["documents"] = [["transcript", "Record", "https://www.govinfo.gov/content/pkg/CHRG-119shrg37479/pdf/CHRG-119shrg37479.pdf"]]
    meeting["congress"] = 119
    updates = associate_pages([meeting], [meeting], state)
    assert updates[PAGE_A]["events"] == ["336743"]
    assert updates[PAGE_A]["match_details"]["336743"]["method"] == "senate.records.match_identifiers"
    assert updates[PAGE_A]["events"] == state[HOST]["workflow"][PAGE_A]["events"]
    assert "events" not in state[HOST]["pages"][PAGE_A]
