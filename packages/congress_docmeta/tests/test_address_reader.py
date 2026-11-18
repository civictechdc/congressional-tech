"""`congress_docmeta.address_reader` (the copied Keeplist prose reader and its congressional additions) and rule R8."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from congress_docmeta.relational_rules_v6 import attach_work_addresses_v6

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def test_docmeta_import_does_not_load_the_reader() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(SRC_DIR)!r})\n"
        "import congress_docmeta\n"
        "loaded = [m for m in ('usaddress', 'pycountry', 'msgspec_schemaorg', 'congress_docmeta.address_reader') if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_a_missing_address_library_raises_instead_of_switching_the_rule_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from congress_docmeta import post_pass_v6

    monkeypatch.setitem(sys.modules, "congress_docmeta.address_reader.congressional", None)  # import raises ImportError
    people = [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}]
    text = "Testimony of\nJane Doe\nAcme Institute\n1615 H Street NW\nWashington, DC 20062\n"
    with pytest.raises(ImportError):
        attach_work_addresses_v6(people, primary_kind="witness_statement", text=text)
    raw = {"status": "usable", "text_quality": "native", "primary_kind": "witness_statement", "personas": people,
           "composed_title": "Testimony of Jane Doe", "gist": "Jane Doe testifies.", "topics": ["testimony"]}
    with pytest.raises(ImportError):  # the post-pass swallows a reader that fails on a document, not a missing library
        post_pass_v6(raw, filename="doe.pdf", text=text)


from congress_docmeta.address_reader import get_address_claims, get_addresses  # noqa: E402
from congress_docmeta.address_reader.congressional import fold_washington_periods, read_work_addresses  # noqa: E402


def _addresses(text: str) -> list[str]:
    return [address for _, _, address in read_work_addresses(text)[1]]


def _attach(people: list[dict], kind: str, text: str) -> dict[str, str | None]:
    return {p["name"]: p.get("work_addr") for p in attach_work_addresses_v6(people, primary_kind=kind, text=text)}


def test_copy_reads_a_plain_street_address() -> None:
    claims = get_address_claims("Please write to 1615 H Street NW, Washington, DC 20062 for details.")
    assert [c.text for c in claims] == ["1615 H Street NW, Washington, DC 20062"]
    assert claims[0].stated and claims[0].parts.door
    assert get_addresses("Thank you, Chairman, for the opportunity to testify today.") == []


def test_washington_addresses_written_with_periods() -> None:
    text = "American Geophysical Union\n2000 Florida Avenue, N.W.\nWashington, D.C. 20009\nDear Ms. Lachance:"
    assert get_addresses(text) == []  # the copied reader alone stops at "N.W."
    assert fold_washington_periods("N.W. S. E. D.C. D. C. U.S.D.C. N.W.T") == "NW SE DC DC U.S.D.C. N.W.T"
    assert _addresses(text) == ["2000 Florida Avenue, NW Washington, DC 20009"]
    assert _addresses("1620 L Street, N.W., Suite 630, Washington, D.C. 20036") == [
        "1620 L Street, NW, Suite 630, Washington, DC 20036"
    ]


def test_post_office_boxes() -> None:
    assert _addresses("Suzanna Hupp\nP.O. Box 648\nKempner, TX 76539\n512-470-8080") == ["P.O. Box 648, Kempner, TX 76539"]
    assert _addresses("Quinault Indian Nation\nPost Office Box 189, Taholah, Washington 98587") == [
        "Post Office Box 189, Taholah, Washington 98587"
    ]
    assert _addresses("Send it to PO Box 12 and we will reply.") == []  # a box with no town is not an address


def test_house_and_senate_office_buildings() -> None:
    inside = (
        "The Honorable Jason Chaffetz\n2157 Rayburn House Office Building\n"
        "Committee on Oversight and Government Reform\nUnited States House of Representatives\nWashington, DC 20515\n"
    )
    assert _addresses(inside) == ["2157 Rayburn House Office Building, Washington, DC 20515"]
    assert _addresses("428A Russell Senate Office Bldg, Washington, D.C. 20510") == [
        "428A Russell Senate Office Building, Washington, DC 20510"
    ]
    assert _addresses("ED CASE\n1ST DISTRICT, HAWAI'I\n2210 RAYBURN HOUSE OFFICE BUILDING\nWASHINGTON, DC 20515") == [
        "2210 Rayburn House Office Building, Washington, DC 20515"
    ]
    assert _addresses("He walked to the Rayburn House Office Building that morning.") == []
    assert _addresses("Washington, DC 20515") == []  # a city names nobody's office


def test_inside_address_goes_to_the_person_named_above_it() -> None:
    text = (
        "COMMITTEE ON ENERGY AND COMMERCE\n2125 RAYBURN HOUSE OFFICE BUILDING\nWASHINGTON, DC 20515-6115\n"
        "June 29, 2018\nThe Honorable Alex M. Azar II\nSecretary\nU.S. Department of Health and Human Services\n"
        "200 Independence Avenue, S.W.\nWashington, D.C. 20201\nDear Secretary Azar:\nPursuant to Rules X and XI\n"
    )
    people = [{"name": "Greg Walden", "role": "sender"}, {"name": "Alex M. Azar II", "role": "recipient"}]
    assert _attach(people, "oversight_letter", text) == {
        "Greg Walden": None,
        "Alex M. Azar II": "200 Independence Avenue, SW Washington, DC 20201",
    }
    assert _attach(people, "hearing_notice", text) == {"Greg Walden": None, "Alex M. Azar II": None}


def test_committee_letterhead_is_nobodys_office() -> None:
    text = (
        "GREG WALDEN, OREGON\nCHAIRMAN\nFRANK PALLONE, JR., NEW JERSEY\nRANKING MEMBER\n"
        "ONE HUNDRED FIFTEENTH CONGRESS\nCongress of the United States\nHouse of Representatives\n"
        "COMMITTEE ON ENERGY AND COMMERCE\n2125 RAYBURN HOUSE OFFICE BUILDING\nWASHINGTON, DC 20515-6115\n"
    )
    people = [{"name": "Greg Walden", "role": "chair"}, {"name": "Frank Pallone, Jr.", "role": "ranking_member"}]
    assert _attach(people, "oversight_letter", text) == {"Greg Walden": None, "Frank Pallone, Jr.": None}


def test_a_name_in_prose_above_a_letterhead_is_not_its_owner() -> None:
    text = (
        "5. Letter to Chair Duncan and Ranking Member DeGette from SMUD Chief Executive Officer\n"
        "and General Manager Paul Lau, April 10, 2024, submitted by Rep. Matsui.\n"
        "Oklo Inc. - 3190 Coronado Dr., Santa Clara, CA 95054 - oklo.com\nApril 9th, 2024\n"
        "Representative Jeff Duncan\nCommittee on Energy and Commerce\n2125 Rayburn House Office Building\n"
        "Washington, DC 20515\n"
    )
    people = [{"name": "Paul Lau", "role": "sender"}, {"name": "Jeff Duncan", "role": "recipient"}]
    assert _attach(people, "external_submission_letter", text) == {
        "Paul Lau": None,
        "Jeff Duncan": "2125 Rayburn House Office Building, Washington, DC 20515",
    }


def test_side_by_side_inside_addresses_pair_off_in_order() -> None:
    text = (
        "November 18, 2024 The Honorable Richard J. Durbin The Honorable Lindsey Graham Chairman, Ranking Member, "
        "Committee on the Judiciary Committee on the Judiciary United States Senate United States Senate "
        "711 Hart Senate Office Building 211 Russell Senate Office Washington D.C. 20510 Washington D.C. 20510 RE: "
    )
    people = [{"name": "Richard J. Durbin", "role": "recipient"}, {"name": "Lindsey Graham", "role": "recipient"}]
    assert _attach(people, "nomination_or_support_letter", text) == {
        "Richard J. Durbin": "711 Hart Senate Office Building, Washington, DC 20510",
        "Lindsey Graham": "211 Russell Senate Office Building, Washington, DC 20510",
    }


def test_the_models_address_stays_and_a_second_office_is_not_handed_on() -> None:
    text = (
        "Testimony of\nJane Doe\nAcme Institute\n1615 H Street NW\nWashington, DC 20062\n"
        "100 Main Street\nSpringfield, IL 62701\n\nJohn Roe\nP.O. Box 648\nKempner, TX 76539\n"
    )
    people = [
        {"name": "Jane Doe", "role": "witness", "work_addr": "Washington, DC"},
        {"name": "John Roe", "role": "witness"},
        {"name": "Acme Institute", "role": "witness", "entity_type": "organization"},
    ]
    assert _attach(people, "witness_statement", text) == {
        "Jane Doe": "Washington, DC",
        "John Roe": "P.O. Box 648, Kempner, TX 76539",
        "Acme Institute": None,
    }


def test_an_address_inside_a_sentence_is_not_an_office_block() -> None:
    text = (
        "Dear Dr. Doe:\nChairman Guthrie invites you to testify on Tuesday at a hearing that will take place in "
        "2123 Rayburn House Office Building, Washington, DC 20515.\n"
    )
    people = [{"name": "Brett Guthrie", "role": "sender"}, {"name": "Jane Doe", "role": "recipient"}]
    assert _attach(people, "witness_invitation", text) == {"Brett Guthrie": None, "Jane Doe": None}


def test_a_hearing_room_on_a_testimony_cover_is_not_the_witnesss_office() -> None:
    text = (
        "Written Testimony of Congressman Paul D. Tonko (NY-20)\nBefore the House Veterans Affairs Committee\n"
        "10:00 am, Wednesday, May 16, 2018\n334 Cannon House Office Building\nThank you Mr. Chairman.\n"
    )
    assert _attach([{"name": "Paul D. Tonko", "role": "witness"}], "witness_statement", text) == {"Paul D. Tonko": None}
