from __future__ import annotations

import pytest

from congress_api.lake.appearance_records import (
    APPEARANCE_STRUCT,
    _MODS_ABBREVIATION,
    _mods_prose,
    extract_congress_gov_observation,
    extract_house_xml_observation,
    extract_mods_observation,
    extract_senate_page_observation,
)
from congress_api.parsers.witness_names import witness


def _mods_xml(package_id: str, lines: list[str]) -> str:
    body = "\n".join(f"<witness>{line}</witness>" for line in lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<mods xmlns="http://www.loc.gov/mods/v3"><extension><accessId>{package_id}</accessId>'
        f"{body}</extension></mods>"
    )


def test_ct_17op_appearance_struct_has_rank_and_credentials():
    names = [f.name for f in APPEARANCE_STRUCT]
    assert "rank" in names
    assert "credentials" in names


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "Lieutenant General Michael E. Conley, USAF, Commander, Air Force Special Operations Command",
            {
                "name": "Michael E. Conley",
                "honorific": "",
                "rank": "Lieutenant General",
                "credentials": "USAF",
                "position": "Commander",
                "organization": "Air Force Special Operations Command",
            },
        ),
        (
            "Conley, Lt. Gen. Michael E. USAF, Commander, Air Force Special Operations Command",
            {
                "name": "Michael E. Conley",
                "honorific": "",
                "rank": "Lt. Gen.",
                "credentials": "USAF",
                "position": "Commander",
                "organization": "Air Force Special Operations Command",
            },
        ),
        (
            "Jacoby, GEN Charles H., Jr., USA, Commander, USNORTHCOM",
            {
                "name": "Charles H. Jacoby Jr.",
                "honorific": "",
                "rank": "GEN",
                "credentials": "USA",
                "position": "Commander",
                "organization": "USNORTHCOM",
            },
        ),
        (
            "Woodruff, Ph.D., MPH, Tracey, Professor, UCSF",
            {
                "name": "Tracey Woodruff",
                "honorific": "",
                "rank": "",
                "credentials": "Ph.D., MPH",
                "position": "Professor",
                "organization": "UCSF",
            },
        ),
        (
            "Tankersley, D.D.S., Ronald L., President, American Association of Oral and Maxillofacial Surgeons",
            {
                "name": "Ronald L. Tankersley",
                "honorific": "",
                "rank": "",
                "credentials": "D.D.S.",
                "position": "President",
                "organization": "American Association of Oral and Maxillofacial Surgeons",
            },
        ),
        (
            "Puneet S. Arora MD MS, Physician",
            {
                "name": "Puneet S. Arora",
                "honorific": "",
                "rank": "",
                "credentials": "MD MS",
                "position": "Physician",
                "organization": "",
            },
        ),
        (
            "Admiral James Stavridis (Ret.), Former Supreme Allied Commander",
            {
                "name": "James Stavridis",
                "honorific": "",
                "rank": "Admiral",
                "credentials": "(Ret.)",
                "position": "Former Supreme Allied Commander",
                "organization": "",
            },
        ),
        (
            "Tech. Sgt. Jack Fe Torres, Current Resident",
            {
                "name": "Jack Fe Torres",
                "honorific": "",
                "rank": "Tech. Sgt.",
                "credentials": "",
                "position": "Current Resident",
                "organization": "",
            },
        ),
        (
            "Sam Huttenbauer, CEO, United Pet Group, Cincinnati, OH",
            {
                "name": "Sam Huttenbauer",
                "honorific": "",
                "rank": "",
                "credentials": "",
                "position": "CEO",
                "organization": "United Pet Group, Cincinnati, OH",
            },
        ),
        (
            "Dr. Matthew J. Major, Research Health Scientist",
            {
                "name": "Matthew J. Major",
                "honorific": "Dr.",
                "rank": "",
                "credentials": "",
                "position": "Research Health Scientist",
                "organization": "",
            },
        ),
        (
            "J.D. Vance, Author",
            {
                "name": "J.D. Vance",
                "honorific": "",
                "rank": "",
                "credentials": "",
                "position": "Author",
                "organization": "",
            },
        ),
        (
            "Police Chief John Smith, Metro Police Department",
            {
                "name": "Police Chief John Smith",
                "honorific": "",
                "rank": "",
                "credentials": "",
                "position": "",
                "organization": "Metro Police Department",
            },
        ),
        (
            "Ostrowski, Senior Chief Jon, USCGR (Ret.), Director",
            {
                "name": "Jon Ostrowski",
                "honorific": "",
                "rank": "Senior Chief",
                "credentials": "USCGR (Ret.)",
                "position": "Director",
                "organization": "",
            },
        ),
        (
            "Acheson, M.D., F.R.C.P., David W.K., Associate Commissioner",
            {
                "name": "David W.K. Acheson",
                "honorific": "",
                "rank": "",
                "credentials": "M.D., F.R.C.P.",
                "position": "Associate Commissioner",
                "organization": "",
            },
        ),
        (
            "Priddy, (Ret.), COL Ronald N., Director of Government Affairs",
            {
                "name": "Ronald N. Priddy",
                "honorific": "",
                "rank": "COL",
                "credentials": "(Ret.)",
                "position": "Director of Government Affairs",
                "organization": "",
            },
        ),
        (
            "McKetta, Ph.D., C.F., Charles W., Natural Resources Economist, Forest Econ Inc.",
            {
                "name": "Charles W. McKetta",
                "honorific": "",
                "rank": "",
                "credentials": "Ph.D., C.F.",
                "position": "Natural Resources Economist",
                "organization": "Forest Econ Inc.",
            },
        ),
        (
            "Coston, Ph.D., D.C., Vice President for Agriculture, North Dakota State University",
            {
                "name": "D.C. Coston",
                "honorific": "",
                "rank": "",
                "credentials": "Ph.D.",
                "position": "Vice President for Agriculture",
                "organization": "North Dakota State University",
            },
        ),
        (
            "Ioannidis, C.F., Economist, Economic Research Institute",
            {
                "name": "C.F. Ioannidis",
                "honorific": "",
                "rank": "",
                "credentials": "",
                "position": "Economist",
                "organization": "Economic Research Institute",
            },
        ),
        (
            "Ritchie, Elspeth Cameron, M.D., COL, USA (Ret.), Chief Clinical Officer, District of Columbia's Department of Mental Health",
            {
                "name": "Elspeth Cameron Ritchie",
                "honorific": "",
                "rank": "COL",
                "credentials": "M.D., USA (Ret.)",
                "position": "Chief Clinical Officer",
                "organization": "District of Columbia's Department of Mental Health",
            },
        ),
        (
            "LeGrande, Ms. Tomikia, ED.D., Vice Provost for Strategic Enrollment Management, Virginia Commonwealth University",
            {
                "name": "Tomikia LeGrande",
                "honorific": "Ms.",
                "rank": "",
                "credentials": "ED.D.",
                "position": "Vice Provost for Strategic Enrollment Management",
                "organization": "Virginia Commonwealth University",
            },
        ),
    ],
)
def test_ct_17op_witness_rank_and_credentials(line: str, expected: dict[str, str]):
    parsed = witness(line)
    for k, v in expected.items():
        assert parsed[k] == v, f"mismatch on {k!r} for {line!r}: got {parsed[k]!r}, expected {v!r}"


def test_ct_17op_all_four_sources_extract_rank_and_credentials():
    # 1. MODS
    mods = extract_mods_observation(
        _mods_xml(
            "CHRG-118shrg1",
            [
                "Conley, Lt. Gen. Michael E., USAF, Commander, Air Force Special Operations Command",
                "American Academy of Pediatrics, Kent Hymel, M.D., Falls Church, Virginia",
            ],
        )
    )["appearances"]
    assert mods[0]["name"] == "Michael E. Conley"
    assert mods[0]["rank"] == "Lt. Gen."
    assert mods[0]["credentials"] == "USAF"
    assert mods[1]["name"] == "Kent Hymel"
    assert mods[1]["rank"] is None
    assert mods[1]["credentials"] == "M.D."

    # 2. senate_page
    html = """
    <html><body>
      <h2>Witnesses</h2>
      <ul class="capigacr-widget-card__panel-section">
        <li class="capigacr-widget-card">
          <h3 class="capigacr-widget-card__title">The Honorable Jay Bhattacharya, M.D., Ph.D.</h3>
          <div class="member-detail-item">Professor of Health Policy</div>
          <div class="member-detail-item">Stanford University</div>
        </li>
        <li class="capigacr-widget-card">
          <h3 class="capigacr-widget-card__title">CAPT Christopher Jones</h3>
          <div class="member-detail-item">Director</div>
          <div class="member-detail-item">SAMHSA</div>
        </li>
      </ul>
    </body></html>
    """
    senate = extract_senate_page_observation(html)["appearances"]
    assert senate[0]["name"] == "Jay Bhattacharya"
    assert senate[0]["rank"] is None
    assert senate[0]["credentials"] == "M.D., Ph.D."
    assert senate[1]["name"] == "Christopher Jones"
    assert senate[1]["rank"] == "CAPT"
    assert senate[1]["credentials"] is None

    # 3. house_xml
    hxml = """<?xml version="1.0" encoding="UTF-8"?>
    <witness-list meeting-id="HHRG-118-1">
      <panel sort-order="1">
        <witness id="w1" display-order="1">
          <witness-name>
            <honorific>Lieutenant General</honorific>
            <firstname>Kenneth</firstname>
            <middlename>J.</middlename>
            <lastname>Glueck, Jr., USMC</lastname>
          </witness-name>
          <position>Deputy Commandant</position>
        </witness>
        <witness id="w2" display-order="2">
          <witness-name>
            <honorific>Mr.</honorific>
            <firstname>D. Andrew</firstname>
            <lastname>Austin</lastname>
            <suffix>Ph.D</suffix>
          </witness-name>
          <position>Analyst</position>
        </witness>
        <witness id="w3" display-order="3">
          <witness-name>
            <honorific>Brigadier General</honorific>
            <firstname>Gary</firstname>
            <middlename>M.</middlename>
            <lastname>Profit (USA, Ret.)</lastname>
          </witness-name>
          <position>Senior Director</position>
        </witness>
      </panel>
    </witness-list>
    """
    house = extract_house_xml_observation(hxml)["appearances"]
    assert house[0]["name"] == "Kenneth J. Glueck, Jr."
    assert house[0]["honorific"] is None
    assert house[0]["rank"] == "Lieutenant General"
    assert house[0]["suffix"] == "Jr."
    assert house[0]["credentials"] == "USMC"
    assert house[1]["name"] == "D. Andrew Austin"
    assert house[1]["honorific"] == "Mr."
    assert house[1]["rank"] is None
    assert house[1]["suffix"] is None
    assert house[1]["credentials"] == "Ph.D"
    assert house[2]["name"] == "Gary M. Profit"
    assert house[2]["rank"] == "Brigadier General"
    assert house[2]["credentials"] == "(USA, Ret.)"

    # 4. congress_gov
    cgov = extract_congress_gov_observation(
        {
            "eventId": 118001,
            "witnesses": [
                {"name": "Rear Admiral Upper Half David Titley", "position": "Director"},
                {"name": "Rochelle Walensky, MD, MPH", "position": "Director", "organization": "CDC"},
                {"name": "Dr. Jeromie Ballreich, PhD, MHS", "position": "Associate Research Professor"},
            ],
        }
    )["appearances"]
    assert cgov[0]["name"] == "David Titley"
    assert cgov[0]["rank"] == "Rear Admiral Upper Half"
    assert cgov[0]["credentials"] is None
    assert cgov[1]["name"] == "Rochelle Walensky"
    assert cgov[1]["rank"] is None
    assert cgov[1]["credentials"] == "MD, MPH"
    assert cgov[2]["name"] == "Jeromie Ballreich"
    assert cgov[2]["honorific"] == "Dr."
    assert cgov[2]["rank"] is None
    assert cgov[2]["credentials"] == "PhD, MHS"


def test_ct_eppo_three_written_answer_shapes_and_owner_typing_rule():
    # Shape 1: \*\ footnote marker, absent from testimony -> statement_for_record
    obs1 = extract_mods_observation(
        _mods_xml(
            "CHRG-113hhrg86394",
            [
                "Janet Woodcock, M.D., Director, Center for Drug Evaluation and Research, Food and Drug Administration",
                r"Answers to submitted questions \*\ Carmen Catizone, Executive Director, National Association of Boards of Pharmacy",
            ],
        )
    )["appearances"]
    assert len(obs1) == 2
    assert obs1[1]["name"] == "Carmen Catizone"
    assert obs1[1]["position"] == "Executive Director"
    assert obs1[1]["organization"] == "National Association of Boards of Pharmacy"
    assert obs1[1]["witness_type"] == "statement_for_record"

    # When the answerer ALSO testified in the print, keeps testimony row's type (None)
    obs1_testified = extract_mods_observation(
        _mods_xml(
            "CHRG-113hhrg99999",
            [
                "Carmen Catizone, Executive Director, National Association of Boards of Pharmacy",
                r"Answers to submitted questions \*\ Carmen Catizone, Executive Director, National Association of Boards of Pharmacy",
            ],
        )
    )["appearances"]
    assert obs1_testified[1]["name"] == "Carmen Catizone"
    assert obs1_testified[1]["witness_type"] is None

    # Shape 2: comma after label
    obs2 = extract_mods_observation(
        _mods_xml(
            "CHRG-111hhrg62589",
            [
                "Mr. Gregory Boyce, Chairman and Chief Executive Officer, Peabody Energy",
                "Answers to Submitted Questions, Mr. Jeff Hopkins",
            ],
        )
    )["appearances"]
    assert len(obs2) == 2
    assert obs2[1]["name"] == "Jeff Hopkins"
    assert obs2[1]["honorific"] == "Mr."
    assert obs2[1]["witness_type"] == "statement_for_record"

    # Shape 3: singular 'Response to question submitted for the record by'
    obs3 = extract_mods_observation(
        _mods_xml(
            "CHRG-110hhrg33608",
            [
                "Featherstone, Roger, Southwest Circuit Rider, EARTHWORKS",
                "Response to question submitted for the record by Jeanine Derby, Forest Supervisor, Coronado National Forest",
            ],
        )
    )["appearances"]
    assert len(obs3) == 2
    assert obs3[1]["name"] == "Jeanine Derby"
    assert obs3[1]["position"] == "Forest Supervisor"
    assert obs3[1]["organization"] == "Coronado National Forest"
    assert obs3[1]["witness_type"] == "statement_for_record"


def test_ct_6mvl_organization_in_position_tower_and_dann():
    obs = extract_mods_observation(
        _mods_xml(
            "CHRG-109hhrg99991",
            [
                "Page Barreto, Hon. Hector V., U.S. Small Business Administration",
                "Biden, Hon. Joseph, U.S. Senator from the State of Delaware",
                "Lunine, Cynthia, Private Landowner",
            ],
        )
    )["appearances"]
    assert obs[0]["name"] == "Hector V. Barreto"
    assert obs[0]["position"] is None
    assert obs[0]["organization"] == "U.S. Small Business Administration"
    # Member style and personal role stay in position
    assert obs[1]["name"] == "Joseph Biden"
    assert obs[1]["position"] == "U.S. Senator from the State of Delaware"
    assert obs[1]["organization"] is None
    assert obs[2]["name"] == "Cynthia Lunine"
    assert obs[2]["position"] == "Private Landowner"
    assert obs[2]["organization"] is None

    # William Tower reviewed row on CHRG-109hhrg30447 #12
    tower_lines = [f"Witness {i}, Name {i}" for i in range(1, 12)] + [
        "American Family Rights Association, William Tower, Fair Oaks, California"
    ]
    tower_obs = extract_mods_observation(_mods_xml("CHRG-109hhrg30447", tower_lines))["appearances"]
    tower = next(r for r in tower_obs if r["source_locator"] == "mods:witness[12]")
    assert tower["name"] == "William Tower"
    assert tower["position"] is None
    assert tower["organization"] == "American Family Rights Association"

    # C. Richard Dann on CHRG-108hhrg99682 #4
    dann_obs = extract_mods_observation(
        _mods_xml(
            "CHRG-108hhrg99682",
            [
                "American Federation of State, County, and Municipal Employees, Union of American Physicians and Dentists, Dann, Dr. C. Richard,",
            ],
        )
    )["appearances"]
    assert dann_obs[0]["name"] == "C. Richard Dann"
    assert dann_obs[0]["honorific"] == "Dr."
    assert dann_obs[0]["position"] is None
    assert (
        dann_obs[0]["organization"]
        == "American Federation of State, County, and Municipal Employees, Union of American Physicians and Dentists"
    )

    # Corpus regressions caught by mods_name_fields_raw_check: "Senior" orgs, LLC orgs, and multi-segment org prefixes
    org_first = extract_mods_observation(
        _mods_xml(
            "CHRG-110hhrg37464",
            [
                "Senior Executives Association, Carol A. Bonosaro, President",
                "The Ballard Group LLC, Hon. Frances D. Cook",
                "Placid Refining Company LLC, Dan Robinson",
                "Council of the Americas, Washington Operations, Hon. William T. Pryce",
            ],
        )
    )["appearances"]
    assert org_first[0]["name"] == "Carol A. Bonosaro"
    assert org_first[0]["position"] == "President"
    assert org_first[0]["organization"] == "Senior Executives Association"
    assert org_first[1]["name"] == "Frances D. Cook"
    assert org_first[1]["organization"] == "The Ballard Group LLC"
    assert org_first[2]["name"] == "Dan Robinson"
    assert org_first[2]["organization"] == "Placid Refining Company LLC"
    assert org_first[3]["name"] == "William T. Pryce"
    assert org_first[3]["organization"] == "Council of the Americas, Washington Operations"


def test_ct_vj08_lowercase_surnames_the_honorable_and_abbreviations():
    assert witness("van Welie, Gordon, President and CEO, ISO New England Inc.")["name"] == "Gordon van Welie"
    assert witness("de Rugy, Veronique, Senior Research Fellow, Mercatus Center")["name"] == "Veronique de Rugy"
    assert witness("van der Hoeven, Guido, Extension Specialist")["name"] == "Guido van der Hoeven"
    assert witness("van de Ligt, Jennifer, Director")["name"] == "Jennifer van de Ligt"
    assert witness("von Eschenbach, Andrew C., M.D., Commissioner")["name"] == "Andrew C. von Eschenbach"
    assert witness("de la Garza, Ariana, Director")["name"] == "Ariana de la Garza"
    assert witness("the Honorable Robert Wilkie, Secretary, Department of Veterans Affairs")["name"] == "Robert Wilkie"
    assert witness("the Hon. Jane Doe, Director")["name"] == "Jane Doe"

    for abbr in ("gov", "maj", "amb", "sec", "inc", "corp"):
        assert abbr in _MODS_ABBREVIATION
    assert not _mods_prose("van Welie, Gov. Jane, joined Acme Inc. Board and Maj. John Doe spoke")
    # Org split with Inc. and Corp. stays intact
    parsed_inc = witness("Steven F. Leer, Chairman and Chief Executive Officer, Arch Coal, Inc.")
    assert parsed_inc["name"] == "Steven F. Leer"
    assert parsed_inc["organization"] == "Arch Coal, Inc."


def test_ct_uz8q_round9_residual_lines():
    paulsen = extract_mods_observation(
        _mods_xml(
            "CHRG-113hhrg91127",
            ["The Hon. Erik Paulsen, a Member of Congress, from the state of Minnesota Written Statement"],
        )
    )["appearances"]
    assert paulsen[0]["name"] == "Erik Paulsen"
    assert paulsen[0]["witness_type"] == "member_statement"

    richmond = extract_mods_observation(
        _mods_xml(
            "CHRG-114hhrg96873",
            ["The Hon.Cedric Richmond, a Member of Congress from the State of Louisiana Written Statement"],
        )
    )["appearances"]
    assert richmond[0]["name"] == "Cedric Richmond"
    assert richmond[0]["witness_type"] == "member_statement"

    walberg_lines = [f"Witness {i}, Title" for i in range(1, 6)] + [
        "Walberg, Hon. Tim, Chairman, Subcommittee on Workforce Protections: Statement submitted on behalf of the National Restaurant Association"
    ]
    walberg = extract_mods_observation(_mods_xml("CHRG-114hhrg94823", walberg_lines))["appearances"]
    w6 = next(r for r in walberg if r["source_locator"] == "mods:witness[6]")
    assert w6["name"] == "Tim Walberg"
    assert w6["position"] == "Chairman"
    assert (
        w6["organization"]
        == "Subcommittee on Workforce Protections: Statement submitted on behalf of the National Restaurant Association"
    )
    assert w6["witness_type"] is None  # typed member_statement by ct-sfra witness-transcript-facts.sql (owner decision 2026-11-11)

    tierney_lines = [f"Witness {i}, Title" for i in range(1, 11)] + [
        "Tierney, Hon. John F., a Representative in Congress from the State of Massachusetts: Letter, American Association of Community Colleges (AACC); Association of Community College Trustees (ACCT)"
    ]
    tierney = extract_mods_observation(_mods_xml("CHRG-112hhrg73706", tierney_lines))["appearances"]
    t11 = next(r for r in tierney if r["source_locator"] == "mods:witness[11]")
    assert t11["name"] == "John F. Tierney"
    assert t11["position"] == "a Representative in Congress from the State of Massachusetts: Letter"
    assert t11["witness_type"] == "member_statement"

    messer_lines = [f"Witness {i}, Title" for i in range(1, 10)] + [
        "Messer, Hon. Luke, a Representative in Congress from the State of Indiana: Community School Corporation of Southern Hancock County, letter, dated Sept. 3, 2014"
    ]
    messer = extract_mods_observation(_mods_xml("CHRG-113hhrg89535", messer_lines))["appearances"]
    m10 = next(r for r in messer if r["source_locator"] == "mods:witness[10]")
    assert m10["name"] == "Luke Messer"
    assert m10["organization"] == "letter, dated Sept. 3, 2014"
    assert m10["witness_type"] == "member_statement"


def test_ct_17op_horizontal_audit_p0_3cde_and_mods_edge_cases():
    # P0-3(c): Senate Banking vcard with nested <span>Dr.</span> and leading credential in <div class="title">
    # (verbatim structure from 45cf54ec80ea1b5f59ccda4b61c870c52d975380d5bb0861b321f828f3f3ee99, event_id=332070)
    schulz_html = """
    <html><body>
      <h2>Witnesses</h2>
      <ul>
        <li class="vcard ">
          <span class="fn"><span class="">Dr.</span> Dorothy Moses Schulz</span>
          <div class="title">Ph.D., Adjunct Fellow</div>
          <div class="org">The Manhattan Institute</div>
        </li>
        <li class="vcard ">
          <span class="fn">Pat Kelleher</span>
          <div class="title">USA Hockey</div>
        </li>
      </ul>
    </body></html>
    """
    senate = extract_senate_page_observation(schulz_html)["appearances"]
    assert senate[0]["name"] == "Dorothy Moses Schulz"
    assert senate[0]["honorific"] == "Dr."
    assert senate[0]["credentials"] == "Ph.D."
    assert senate[0]["position"] == "Adjunct Fellow"
    assert senate[0]["organization"] == "The Manhattan Institute"
    # Non-credential sports org "USA Hockey" must stay intact in position
    assert senate[1]["name"] == "Pat Kelleher"
    assert senate[1]["credentials"] is None
    assert senate[1]["position"] == "USA Hockey"

    # P0-3(c) & P0-3(e) on congress_gov: General Dunford ("USMC, Chairman"), civil honorifics ("Mr.", "The Honorable"),
    # and occupational phrases ("U.S. Army Veteran", "Ph.D. Candidate", "CPA and Small Business Owner") kept intact
    cgov = extract_congress_gov_observation(
        {
            "eventId": 116574,
            "witnesses": [
                {"name": "General Joseph Dunford", "position": "USMC, Chairman", "organization": "Joint Chiefs of Staff"},
                {"name": "Mr. Robert Gordon", "position": "Senior Vice President"},
                {"name": "The Honorable James O'Brien", "position": "Assistant Secretary"},
                {"name": "Mr. Mark Favors", "position": "U.S. Army Veteran"},
                {"name": "Ms. Sabrina Casucci", "position": "Ph.D Candidate", "organization": "University at Buffalo"},
                {"name": "Mr. Grafton Willey", "position": "CPA and Small Business Owner"},
            ],
        }
    )["appearances"]
    assert cgov[0]["name"] == "Joseph Dunford"
    assert cgov[0]["rank"] == "General"
    assert cgov[0]["credentials"] == "USMC"
    assert cgov[0]["position"] == "Chairman"
    assert cgov[1]["name"] == "Robert Gordon"
    assert cgov[1]["honorific"] == "Mr."
    assert cgov[2]["name"] == "James O'Brien"
    assert cgov[2]["honorific"] == "The Honorable"
    assert cgov[3]["name"] == "Mark Favors"
    assert cgov[3]["honorific"] == "Mr."
    assert cgov[3]["credentials"] is None
    assert cgov[3]["position"] == "U.S. Army Veteran"
    assert cgov[4]["name"] == "Sabrina Casucci"
    assert cgov[4]["honorific"] == "Ms."
    assert cgov[4]["credentials"] is None
    assert cgov[4]["position"] == "Ph.D Candidate"
    assert cgov[5]["name"] == "Grafton Willey"
    assert cgov[5]["credentials"] is None
    assert cgov[5]["position"] == "CPA and Small Business Owner"

    # P0-3(d): House XML <lastname>Worley II USAF</lastname> cleans structured family and extracts suffix
    # (verbatim structure from b61d3622e5033a05abb55f3676766c9e263cad065750add2b1c32183b831394c, event_id=103140)
    worley_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <witness-list meeting-id="103140">
      <panel sort-order="1">
        <witness display-order="1">
          <witness-name>
            <honorific>Major General</honorific>
            <firstname>Robert</firstname>
            <middlename>M.</middlename>
            <lastname>Worley II USAF</lastname>
          </witness-name>
          <position>Director, Education Service</position>
          <organization>Veterans Benefit Administration</organization>
        </witness>
      </panel>
    </witness-list>
    """
    worley = extract_house_xml_observation(worley_xml)["appearances"][0]
    assert worley["name"] == "Robert M. Worley II"
    assert worley["given"] == "Robert"
    assert worley["middle"] == "M."
    assert worley["family"] == "Worley"
    assert worley["suffix"] == "II"
    assert worley["rank"] == "Major General"
    assert worley["credentials"] == "USAF"

    # MODS corpus edge cases: Ioannidis C.F., CIVIC IMPULSE LLC, Melroy slash, Otstott Ret, Moreau D.C., ASEH Resolution
    assert witness("Ioannidis, C.F., Economist")["name"] == "C.F. Ioannidis"
    assert witness("Ioannidis, C.F., Economist")["credentials"] == ""
    civic = witness("JOSHUA TAUBERER, CIVIC IMPULSE LLC")
    assert civic["name"] == "JOSHUA TAUBERER"
    assert civic["position"] == ""
    assert civic["organization"] == "CIVIC IMPULSE LLC"
    melroy = witness("Colonel Pamela A. Melroy, United States Air Force (Ret.)/NASA Astronaut")
    assert melroy["name"] == "Pamela A. Melroy"
    assert melroy["rank"] == "Colonel"
    assert melroy["credentials"] == "United States Air Force (Ret.)"
    assert melroy["position"] == "NASA Astronaut"
    otstott = witness("Lieutenant General Charley Otstott, U.S. Army, Ret, Deputy Chairman")
    assert otstott["credentials"] == "U.S. Army, Ret"
    assert otstott["position"] == "Deputy Chairman"
    moreau = witness("Bill Moreau, D.C., Managing Director, United States Olympic Committee")
    assert moreau["credentials"] == "D.C."
    assert moreau["position"] == "Managing Director"
    aseh = extract_mods_observation(_mods_xml("CHRG-111shrg1", ["ASEH, Resolution"]))["appearances"][0]
    assert aseh["name"] is None
    assert aseh["organization"] == "ASEH, Resolution"
    assert aseh["witness_type"] == "statement_for_record"

    # CHRG-110shrg52887 #14 ("PEER, Presidents of Local Unions, June 29, 2006") under "Letters from:" is record_material
    shrg52887_lines = [f"Witness {i}, Director, Agency" for i in range(1, 14)] + [
        "PEER, Presidents of Local Unions, June 29, 2006",
        "ASEH, Resolution",
        "Society of Environmental Journalists (SEJ), August 8, 2006",
    ]
    shrg52887 = extract_mods_observation(_mods_xml("CHRG-110shrg52887", shrg52887_lines))["appearances"]
    peer_row = next(a for a in shrg52887 if a["source_locator"] == "mods:witness[14]")
    assert peer_row["name"] is None
    assert peer_row["organization"] == "PEER, Presidents of Local Unions, June 29, 2006"
    assert peer_row["witness_type"] == "record_material"

    # Senate page stacked civil prefixes ("The Honorable Senator ...") and plain links preserve chamber cues in honorific
    stacked_html = """
    <html><body><h2>Witnesses</h2><ul><li class="vcard">
      <span class="fn">The Honorable Senator John Barrasso</span>
      <div class="title">United States Senator</div>
    </li></ul>
    <p><a href="https://www.epw.senate.gov/public/testimony-murkowski.pdf">Senator Lisa Murkowski</a></p>
    </body></html>
    """
    sen_rows = extract_senate_page_observation(stacked_html)["appearances"]
    by_name = {r["name"]: r for r in sen_rows}
    assert by_name["John Barrasso"]["honorific"] == "The Honorable Senator"
    assert by_name["Lisa Murkowski"]["honorific"] == "Senator"



