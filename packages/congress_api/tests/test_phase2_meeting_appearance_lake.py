"""Phase 2 Track D4 & Track B14 unit and contract tests (including S2 fixtures).

Covers:
1. `model/lake/meeting-records.schema.json` and `model/lake/appearance-records.schema.json`
   schema structure, Iceberg field IDs, and `congress_api.lake.tables` registration.
2. `meeting_records` extraction from `congress_gov` (JSON body, XML fallback body, and
   inline `congress/meetings` receipt record) and `house_xml` (`HHRG`, `HMKP`, `HMTG`
   prefix stripping, DM §3 chamber normalization, `sittings`, `committees`, `subject_keys`,
   `transcript_jackets` int32, `videos` with `youtube:` and `senate:` keys, and empty
   `meetings = []` rows).
3. `appearance_records` extraction across all 4 sources (`house_xml`, `congress_gov`,
   `senate_page`, `mods`), `name_key` normalization, unnamed witnesses `#1` / `#2` kept
   apart, S2 duplicate `name_key` deduplication within one `record_sha` (keeps first),
   S2 zero-witness `appearances = []` row retention, relative `document_urls` resolution,
   and incremental anti-join on `(record_sha, parser_version)`.
4. Track B14 raw fetcher routing (`Fetcher` + `ReceiptWriter` + `BodyStore`), `X-Api-Key`
   header injection (no credentials in recorded URLs), and S2 relist window watermark
   advancing only when every page through the final page has a good fetch.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pyarrow as pa
import pytest

from congress_api.acquisition import gpo as gpo_acq
from congress_api.acquisition import house as house_acq
from congress_api.acquisition import house_fallback
from congress_api.acquisition import meetings as meetings_acq
from congress_api.acquisition import senate as senate_acq
from congress_api.acquisition.fetcher import CaptureScope, Fetcher
from congress_api.lake import appearance_records, appearances, meeting_records, meetings, tables
from congress_api.models.raw_fetch import Transfer
from congress_api.parsers.house_xml import (
    HOUSE_MEETING_PREFIXES,
    parse_house_meeting,
    strip_house_meeting_prefix,
)
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.transport import congress as congress_transport
from native_test_helpers import empty_readings

ROOT = Path(__file__).resolve().parents[3]


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. Lake Schema & Table Registration Tests
# ---------------------------------------------------------------------------


def test_meeting_and_appearance_lake_schemas_and_table_profiles():
    meeting_schema_path = ROOT / "model/lake/meeting-records.schema.json"
    appearance_schema_path = ROOT / "model/lake/appearance-records.schema.json"
    assert meeting_schema_path.is_file()
    assert appearance_schema_path.is_file()

    m_schema = json.loads(meeting_schema_path.read_text(encoding="utf-8"))
    a_schema = json.loads(appearance_schema_path.read_text(encoding="utf-8"))

    assert m_schema["type"] == "struct"
    assert m_schema["identifier-field-ids"] == [1, 5, 2]
    m_top_names = [f["name"] for f in m_schema["fields"]]
    assert m_top_names == ["record_sha", "parser_version", "status", "error_type", "source", "meetings"]

    meetings_field = next(f for f in m_schema["fields"] if f["name"] == "meetings")
    meeting_elem_fields = {f["name"]: f for f in meetings_field["type"]["element"]["fields"]}
    assert set(meeting_elem_fields) == {
        "event_id",
        "chamber",
        "congress",
        "session",
        "updated",
        "title",
        "meeting_date",
        "meeting_type",
        "status",
        "sittings",
        "committees",
        "subject_keys",
        "transcript_jackets",
        "videos",
        "document_urls",
        "document_references",
        "collection_states",
        "access",
        "access_basis",
        "not_held",
        "title_key",
        "reschedule_candidate",
    }
    assert meeting_elem_fields["transcript_jackets"]["type"]["element"] == "int"

    assert a_schema["type"] == "struct"
    assert a_schema["identifier-field-ids"] == [1, 5, 2]
    a_top_names = [f["name"] for f in a_schema["fields"]]
    assert a_top_names == [
        "record_sha",
        "parser_version",
        "status",
        "error_type",
        "source",
        "event_id",
        "package_id",
        "declared_base",
        "collection_state",
        "appearances",
        "held_dates",
        "title",
        "created",
    ]

    appearances_field = next(f for f in a_schema["fields"] if f["name"] == "appearances")
    app_elem_fields = {f["name"]: f for f in appearances_field["type"]["element"]["fields"]}
    assert set(app_elem_fields) == {
        "source_locator",
        "name_key",
        "name",
        "honorific",
        "given",
        "middle",
        "family",
        "suffix",
        "position",
        "organization",
        "on_behalf_of",
        "location",
        "panel",
        "panel_order",
        "display_order",
        "witness_type",
        "testified",
        "bioguide_id",
        "document_links",
    }
    assert app_elem_fields["source_locator"]["required"] is True
    assert app_elem_fields["name_key"]["required"] is False
    assert app_elem_fields["document_links"]["required"] is True

    # Verify registration in congress_api.lake.tables
    assert "meeting_records" in tables.TABLE_SPECS
    assert "appearance_records" in tables.TABLE_SPECS
    assert tables.table_spec("meeting_records")["primary_key"] == ("record_sha", "source", "parser_version")
    assert tables.table_spec("appearance_records")["primary_key"] == ("record_sha", "source", "parser_version")
    assert meetings.ARROW_SCHEMA == meeting_records.ARROW_SCHEMA
    assert appearances.ARROW_SCHEMA == appearance_records.ARROW_SCHEMA


# ---------------------------------------------------------------------------
# 2. House Meeting Prefix Stripping Defect Fix (§8) & `meeting_records` Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [
        ("HHRG-118-JU00-20240501-SD001", "118-JU00-20240501-SD001"),
        ("HMKP-118-IF00-20240612-SD002", "118-IF00-20240612-SD002"),
        ("HMTG-119-AP00-20250210-SD003", "119-AP00-20250210-SD003"),
        ("115501", "115501"),
        ("hhrg-118-ju00-1", "118-ju00-1"),
    ],
)
def test_house_meeting_prefix_stripping_all_three_prefixes(raw_id: str, expected: str):
    assert HOUSE_MEETING_PREFIXES == ("HHRG", "HMKP", "HMTG")
    assert strip_house_meeting_prefix(raw_id) == expected


def test_meeting_records_from_congress_gov_body_and_inline_receipt():
    detail_payload = {
        "committeeMeeting": {
            "eventId": "115538",
            "congress": 118,
            "chamber": "NoChamber",
            "updateDate": "2024-07-10T14:22:00Z",
            "title": "Joint Hearing on Economic Outlook",
            "date": "2024-07-09T14:00:00Z",
            "type": "Hearing",
            "meetingStatus": "Scheduled",
            "location": {
                "room": "216",
                "building": "Hart Senate Office Building",
            },
            "continuations": [
                {"continuationDate": "2024-07-10T10:00:00Z"},
            ],
            "committees": [
                {"systemCode": "JSEC00", "name": "Joint Economic Committee", "chamber": "Joint"},
            ],
            "relatedItems": {
                "bills": [
                    {"congress": 118, "type": "S.", "number": "1102"},
                    {"congress": 118, "type": "HR", "number": "0042"},
                ],
                "nominations": [
                    {"congress": 119, "number": "PN730", "part": "02"},
                    {"congress": 117, "number": 78, "part": "20"},
                    {"congress": 116, "number": 5, "part": "00"},
                ],
                "treaties": [
                    {"congress": 114, "number": "1"},
                ],
            },
            "hearingTranscript": [
                {"jacketNumber": "55432"},
                {"jacketNumber": "00987"},
            ],
            # A URL-less entry is an agenda item, not a file.
            "meetingDocuments": [
                {"name": "A bill to amend title 5", "documentType": "Bills and Resolutions"},
                {"name": "Hearing notice", "url": "https://www.congress.gov/118/meeting/house/115538/documents/HHRG-118-JS00-20240709-SD001.pdf"},
            ],
            "videos": [
                {"name": "YouTube Stream", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                {
                    "name": "Senate ISVP",
                    "url": "https://www.senate.gov/isvp/?comm=jsec&filename=jsec070924",
                },
            ],
        }
    }

    sha_body = _sha("cg-body")
    row_body = meeting_records.build_meeting_record_row(
        sha_body,
        "congress_gov",
        json.dumps(detail_payload).encode("utf-8"),
        parser_version="v1",
    )
    assert row_body["record_sha"] == sha_body
    assert meeting_records.table([row_body]).to_pylist()[0]["record_sha"] == bytes.fromhex(sha_body)
    assert row_body["source"] == "congress_gov"
    assert len(row_body["meetings"]) == 1
    m = row_body["meetings"][0]
    assert m["event_id"] == "115538"
    assert m["chamber"] is None  # NoChamber -> None per DM §3
    assert m["congress"] == 118
    assert m["meeting_date"] == "2024-07-09"
    assert len(m["sittings"]) == 2
    assert m["sittings"][0]["start"] == "2024-07-09T14:00:00Z"
    assert m["sittings"][0]["room"] == "216"
    assert m["sittings"][1]["start"] == "2024-07-10T10:00:00Z"
    assert m["committees"] == [
        {
            "system_code": "jsec00",
            "name": "Joint Economic Committee",
            "chamber": "joint",
            "role": None,
        }
    ]
    assert m["subject_keys"] == [
        "118-s-1102",
        "118-hr-42",
        "119-pn-730-2",
        "117-pn-78-20",
        "116-pn-5",
        "114-treaty-1",
    ]
    assert m["transcript_jackets"] == [55432, 987]
    assert m["document_urls"] == ["https://www.congress.gov/118/meeting/house/115538/documents/HHRG-118-JS00-20240709-SD001.pdf"]
    assert m["collection_states"]["document_urls"] == "present"
    assert m["videos"] == [
        {
            "video_key": "youtube:dQw4w9WgXcQ",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "YouTube Stream",
        },
        {
            "video_key": "senate:jsec070924",
            "url": "https://www.senate.gov/isvp/?comm=jsec&filename=jsec070924",
            "title": "Senate ISVP",
        },
    ]

    # Inline receipt record (with _url and _retrieved_at metadata fields) produces identical meeting struct
    inline_record = {
        **detail_payload["committeeMeeting"],
        "_url": "https://api.congress.gov/v3/committee-meeting/118/nochamber/115538",
        "_retrieved_at": "2024-07-11T00:00:00Z",
    }
    row_inline = meeting_records.build_meeting_record_row(
        bytes.fromhex(_sha("cg-inline")),
        "congress_gov",
        inline_record,
        parser_version="v1",
    )
    assert row_inline["meetings"] == row_body["meetings"]


@pytest.mark.parametrize("prefix", ["HHRG", "HMKP", "HMTG"])
def test_meeting_records_from_house_xml_strips_all_prefixes(prefix: str):
    xml_bytes = f"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting meeting-id="{prefix}118555" meeting-type="HHRG" update-date="2024-05-01T15:30:00">
  <current-status>R</current-status>
  <heading>Oversight of Federal Agencies</heading>
  <meeting-details>
    <congress>118</congress>
    <session>2</session>
    <meeting-date>
      <calendar-date>2024-05-10</calendar-date>
      <start-time>10:00:00</start-time>
      <end-time>12:30:00</end-time>
    </meeting-date>
    <meeting-location>
      <capitol-complex>
        <room>2141</room>
        <building>Rayburn</building>
      </capitol-complex>
    </meeting-location>
    <committees>
      <committee-name id="JU00">Committee on the Judiciary</committee-name>
    </committees>
    <subcommittees>
      <committee-name id="JU05" parent-id="JU00">Subcommittee on the Administrative State</committee-name>
    </subcommittees>
  </meeting-details>
  <meeting-documents>
    <meeting-document-group>
      <meeting-document type="BR">
        <description>Text of H.R. 4321</description>
        <legis-num>H.R. 4321</legis-num>
        <files><file doc-url="/bills/hr4321.pdf"/></files>
      </meeting-document>
    </meeting-document-group>
  </meeting-documents>
</committee-meeting>""".encode("utf-8")

    row = meeting_records.build_meeting_record_row(_sha(f"house-{prefix}"), "house_xml", xml_bytes, parser_version="v1")
    assert len(row["meetings"]) == 1
    m = row["meetings"][0]
    assert m["event_id"] == "118555"
    assert m["chamber"] == "house"
    assert m["congress"] == 118
    assert m["session"] == 2
    assert m["meeting_date"] == "2024-05-10"
    # Raw House XML states <current-status> under the root, as a code.
    assert m["status"] == "Rescheduled" and m["not_held"] is False
    assert m["sittings"] == [
        {
            "start": "2024-05-10T10:00:00-04:00",
            "end": "2024-05-10T12:30:00-04:00",
            "room": "2141",
            "building": "Rayburn",
            "address": None,
        }
    ]
    assert m["committees"] == [
        {
            "system_code": "hsju00",
            "name": "Committee on the Judiciary",
            "chamber": "house",
            "role": "host",
        },
        {
            "system_code": "hsju05",
            "name": "Subcommittee on the Administrative State",
            "chamber": "house",
            "role": "subcommittee",
        },
    ]
    assert m["subject_keys"] == ["118-hr-4321"]
    assert m["transcript_jackets"] == []
    assert m["videos"] == []


def test_house_xml_meeting_bills_from_house_naming_and_sd_refusal():
    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting congress-num="118" session-num="2" meeting-id="HHRG118777" meeting-type="HHRG">
  <meeting-details>
    <meeting-title>Legislative Hearing on Wildfire Management and H.J. Res. 77</meeting-title>
    <meeting-date><calendar-date>2024-06-15</calendar-date></meeting-date>
    <committees><committee-name id="IG00">Permanent Select Committee on Intelligence</committee-name></committees>
  </meeting-details>
  <meeting-documents>
    <meeting-document type="SD">
      <description>Hearing Notice mentioning H.R. 9999 and S. 8888, plus Director's 2025 budget and H.R. 2 in the 117th Congress and Public Law 110-246 (H.R. 2419)</description>
      <files>
        <file doc-url="https://docs.house.gov/118/BILLS-118hr9999ih.pdf"/>
        <file doc-url="http://thomas.loc.gov/home/gpoxmlc118/hr123_rh.xml"/>
        <file doc-url="http://thomas.loc.gov/home/gpoxmlc118/h456_ih.xml"/>
        <file doc-url="http://thomas.loc.gov/home/gpoxmlc113/hr99_rh.xml"/>
      </files>
    </meeting-document>
    <meeting-document type="BR">
      <description>Discussion of R.S. 2477, W.S. 11-6-302, U.S. 500, and Clause S 2(N) alongside HR 1234</description>
      <files><file doc-url="https://docs.house.gov/118/BILLS-118HR3522ih-FIRESHEDSAct.pdf"/></files>
    </meeting-document>
  </meeting-documents>
</committee-meeting>"""
    row = meeting_records.build_meeting_record_row(_sha("house-naming-bills"), "house_xml", xml_bytes, parser_version="v1")
    m = row["meetings"][0]
    assert m["event_id"] == "118777"
    assert m["congress"] == 118
    assert m["session"] == 2
    assert m["title"] == "Legislative Hearing on Wildfire Management and H.J. Res. 77"
    assert m["committees"][0]["system_code"] == "hlig00"
    assert m["subject_keys"] == [
        "118-hr-9999",
        "118-hres-123",
        "118-hr-456",
        "118-s-8888",
        "118-hr-3522",
        "118-hr-1234",
        "118-hjres-77",
    ]
    assert m["document_urls"] == [
        "https://docs.house.gov/118/BILLS-118hr9999ih.pdf",
        "http://thomas.loc.gov/home/gpoxmlc118/hr123_rh.xml",
        "http://thomas.loc.gov/home/gpoxmlc118/h456_ih.xml",
        "http://thomas.loc.gov/home/gpoxmlc113/hr99_rh.xml",
        "https://docs.house.gov/118/BILLS-118HR3522ih-FIRESHEDSAct.pdf",
    ]
    assert m["collection_states"] == {
        "sittings": "present",
        "committees": "present",
        "subject_keys": "present",
        "transcript_jackets": "absent",
        "videos": "absent",
        "document_urls": "present",
    }


def test_source_scoped_version_independence_for_meeting_and_appearance_records(monkeypatch):
    """ct-h1nd AC 1 & 2: source-scoped current_version(source) digests are independent per source."""
    m_vers = meeting_records.current_versions()
    assert set(m_vers) == {"congress_gov", "house_xml"}
    assert m_vers["congress_gov"] != m_vers["house_xml"]

    a_vers = appearance_records.current_versions()
    assert set(a_vers) == {"house_xml", "congress_gov", "senate_page", "mods"}
    assert len(set(a_vers.values())) == 4

    # Simulate an edit to a house_xml-only symbol in meeting_records without touching congress_gov symbols
    orig_digest = meeting_records.source_ast_digest

    def fake_meeting_ast_digest(path, symbols):
        if "extract_house_xml_meetings" in symbols:
            return "f" * 64
        return orig_digest(path, symbols)

    monkeypatch.setattr(meeting_records, "source_ast_digest", fake_meeting_ast_digest)
    assert meeting_records.current_version("congress_gov") == m_vers["congress_gov"]
    assert meeting_records.current_version("house_xml") != m_vers["house_xml"]

    # Simulate an edit to a senate_page-only symbol in appearance_records
    orig_app_digest = appearance_records.source_ast_digest

    def fake_app_ast_digest(path, symbols):
        if "extract_senate_page_observation" in symbols:
            return "e" * 64
        return orig_app_digest(path, symbols)

    monkeypatch.setattr(appearance_records, "source_ast_digest", fake_app_ast_digest)
    assert appearance_records.current_version("house_xml") == a_vers["house_xml"]
    assert appearance_records.current_version("congress_gov") == a_vers["congress_gov"]
    assert appearance_records.current_version("mods") == a_vers["mods"]
    assert appearance_records.current_version("senate_page") != a_vers["senate_page"]


def test_shared_witness_helper_is_versioned_for_both_callers(monkeypatch):
    read_bytes = Path.read_bytes
    before = appearance_records.current_versions()

    def changed_witness_helper(path):
        original = read_bytes(path)
        return original + b"\n# version dependency probe" if path.name == "witness_names.py" else original

    monkeypatch.setattr(Path, "read_bytes", changed_witness_helper)
    after = appearance_records.current_versions()
    assert {source for source in before if before[source] != after[source]} == {"mods", "senate_page"}


# ---------------------------------------------------------------------------
# 3. `appearance_records` Extraction, Normalization, S2 Fixtures & Anti-Join
# ---------------------------------------------------------------------------


def test_name_key_normalization_and_unnamed_witnesses():
    # NFKC + casefold + punctuation removal + whitespace collapse
    assert appearance_records.compute_name_key("  Dr. María-José   O’Connor, Jr.! ", 1) == "dr maríajosé oconnor jr"
    assert appearance_records.compute_name_key("THE HONORABLE JOHN\tQ.\nPUBLIC", 2) == "the honorable john q public"
    # Unnamed or punctuation-only witnesses have nullable name_key (None); source_locator distinguishes them
    assert appearance_records.compute_name_key(None, 1) is None
    assert appearance_records.compute_name_key("", 2) is None
    assert appearance_records.compute_name_key(" --- ... ", 3) is None


def test_s2_fixture_1_repeated_names_and_unnamed_witnesses_preserved_with_locators():
    """ct-30fp AC 4 & 5: Repeated normalized `name_key` across panels/roles/documents and
    multiple unnamed witnesses are preserved as separate occurrences with stable `source_locator`s,
    and `resolve_old_witness_key` classifies unambiguous, ambiguous, and unresolved v1 keys.
    """
    house_wlist_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<witness-list meeting-id="HHRG118999">
  <panel sort-order="1">
    <witness display-order="1" witness-type="Non-Gov" testified="yes">
      <witness-name>
        <firstname></firstname>
        <lastname></lastname>
      </witness-name>
      <position>Anonymous Whistleblower</position>
      <organization>Organization A</organization>
    </witness>
    <witness display-order="2" witness-type="Gov" testified="yes" bioguideID="S000148">
      <witness-name>
        <honorific>Hon.</honorific>
        <firstname>Jane</firstname>
        <middlename>M.</middlename>
        <lastname>Smith</lastname>
      </witness-name>
      <position>Administrator</position>
      <organization>Agency X</organization>
      <witness-documents>
        <witness-document>
          <files>
            <file doc-url="/118/HHRG-118-WTTF-Smith.pdf"/>
          </files>
        </witness-document>
      </witness-documents>
    </witness>
  </panel>
  <panel sort-order="2">
    <witness display-order="1">
      <witness-name>
        <firstname></firstname>
        <lastname></lastname>
      </witness-name>
      <position>Second Unnamed Witness</position>
      <organization>Organization B</organization>
    </witness>
    <witness display-order="2">
      <witness-name>
        <honorific>HON</honorific>
        <firstname>JANE</firstname>
        <middlename>M</middlename>
        <lastname>SMITH,</lastname>
      </witness-name>
      <position>Acting Director</position>
      <organization>Agency Y</organization>
      <witness-documents>
        <witness-document>
          <files>
            <file doc-url="/118/HHRG-118-WState-Smith-Panel2.pdf"/>
          </files>
        </witness-document>
      </witness-documents>
    </witness>
  </panel>
</witness-list>"""

    row = appearance_records.build_appearance_record_row(
        _sha("s2-fixture-1"),
        "house_xml",
        house_wlist_xml,
        parser_version="v1",
    )
    assert row["event_id"] == 118999
    assert row["collection_state"] == "present"
    apps = row["appearances"]
    assert len(apps) == 4
    assert [a["source_locator"] for a in apps] == [
        "house_xml:panel[1]/witness[1]",
        "house_xml:panel[1]/witness[2]",
        "house_xml:panel[2]/witness[1]",
        "house_xml:panel[2]/witness[2]",
    ]
    assert [a["name_key"] for a in apps] == [None, "hon jane m smith", None, "hon jane m smith"]
    assert apps[0]["name"] is None
    assert apps[0]["position"] == "Anonymous Whistleblower"
    assert apps[1]["name"] == "Hon. Jane M. Smith"
    assert apps[1]["position"] == "Administrator"
    assert apps[1]["bioguide_id"] == "S000148"
    assert apps[1]["testified"] is True
    assert apps[1]["document_links"] == ["/118/HHRG-118-WTTF-Smith.pdf"]
    assert apps[2]["name"] is None
    assert apps[2]["position"] == "Second Unnamed Witness"
    assert apps[3]["name"] == "HON JANE M SMITH,"
    assert apps[3]["position"] == "Acting Director"
    assert apps[3]["organization"] == "Agency Y"
    assert apps[3]["document_links"] == ["/118/HHRG-118-WState-Smith-Panel2.pdf"]

    # Verify v1 -> v2 old-key resolution (mapped, ambiguous, unresolved)
    occasion = "meeting:118999"
    v1_smith = appearance_records.compute_v1_witness_key(occasion, "hon jane m smith")
    v1_single = appearance_records.compute_v1_witness_key(occasion, "dr single witness")
    v1_missing = appearance_records.compute_v1_witness_key(occasion, "nobody here")
    resolved_rows = [
        {"occasion": occasion, "name_key": "hon jane m smith", "witness_key": "v2key_panel1"},
        {"occasion": occasion, "name_key": "hon jane m smith", "witness_key": "v2key_panel2"},
        {"occasion": occasion, "name_key": "dr single witness", "witness_key": "v2key_single"},
    ]
    assert appearance_records.resolve_old_witness_key(v1_single, resolved_rows) == {
        "old_witness_key": v1_single,
        "status": "mapped",
        "witness_key": "v2key_single",
        "witness_keys": ["v2key_single"],
    }
    assert appearance_records.resolve_old_witness_key(v1_smith, resolved_rows) == {
        "old_witness_key": v1_smith,
        "status": "ambiguous",
        "witness_key": None,
        "witness_keys": ["v2key_panel1", "v2key_panel2"],
    }
    assert appearance_records.resolve_old_witness_key(v1_missing, resolved_rows) == {
        "old_witness_key": v1_missing,
        "status": "unresolved",
        "witness_key": None,
        "witness_keys": [],
    }


def test_s2_fixture_2_empty_witness_and_meeting_rows_retained_for_anti_join():
    """S2 Fixture 2: An input verified to have zero witnesses or zero meetings still emits
    a row with `appearances = []` (`collection_state = 'empty'`) or `meetings = []`, and the
    anti-join on `(record_sha, source, parser_version)` skips it on subsequent runs unless
    that source's `parser_version` bumps.
    """
    empty_wlist_xml = b'<?xml version="1.0"?><witness-list meeting-id="HHRG118000"></witness-list>'
    sha_empty = _sha("s2-empty-wlist")

    inputs = [{"record_sha": sha_empty, "source": "house_xml", "payload": empty_wlist_xml}]

    # First run parses the empty witness list and emits a row with appearances = [] and collection_state = 'empty'
    first_table = appearance_records.produce_appearance_records(inputs, parser_version="v1")
    assert first_table.num_rows == 1
    row_dict = first_table.to_pylist()[0]
    assert row_dict == {
        "record_sha": bytes.fromhex(sha_empty),
        "parser_version": "v1",
        "status": "completed",
        "error_type": None,
        "source": "house_xml",
        "event_id": 118000,
        "package_id": None,
        "declared_base": None,
        "collection_state": "empty",
        "appearances": [],
        "held_dates": None,
        "title": None,
        "created": None,
    }

    # Second run at the same parser_version skips via anti-join before touching payload
    bad_inputs = [{"record_sha": sha_empty, "source": "house_xml", "payload": b"should-not-be-read"}]
    second_table = appearance_records.produce_appearance_records(
        bad_inputs, existing=first_table, parser_version={"house_xml": "v1", "congress_gov": "v99"}
    )
    assert second_table.num_rows == 0

    # Bumping house_xml parser_version to "v2" re-runs the input
    third_table = appearance_records.produce_appearance_records(
        inputs, existing=first_table, parser_version={"house_xml": "v2", "congress_gov": "v99"}
    )
    assert third_table.num_rows == 1
    assert third_table.to_pylist()[0]["parser_version"] == "v2"

    # Also verify meeting_records emits meetings = [] and skips on unchanged rerun
    empty_meeting_sha = _sha("s2-empty-meeting")
    m_inputs = [{"record_sha": empty_meeting_sha, "source": "congress_gov", "payload": b"{}"}]
    m_first = meeting_records.produce_meeting_records(m_inputs, parser_version="v1")
    assert m_first.num_rows == 1
    assert m_first.to_pylist()[0]["meetings"] == []
    m_second = meeting_records.produce_meeting_records(
        m_inputs, existing=m_first, parser_version={"congress_gov": "v1", "house_xml": "v99"}
    )
    assert m_second.num_rows == 0


def test_appearance_records_from_congress_gov_senate_page_and_mods():
    # 1. congress_gov
    cg_payload = {
        "committeeMeeting": {
            "eventId": "116010",
            "witnesses": [
                {
                    "name": "The Honorable Janet Yellen",
                    "position": "Secretary of the Treasury",
                    "organization": "Department of the Treasury",
                },
                {
                    "name": None,
                    "position": "Staff Witness",
                    "organization": "Department of the Treasury",
                },
            ],
        }
    }
    cg_row = appearance_records.build_appearance_record_row(
        _sha("cg-app"), "congress_gov", cg_payload, parser_version="v1"
    )
    assert cg_row["event_id"] == 116010
    assert cg_row["collection_state"] == "present"
    assert [a["name_key"] for a in cg_row["appearances"]] == ["the honorable janet yellen", None]
    assert [a["source_locator"] for a in cg_row["appearances"]] == [
        "congress_gov:witness[1]",
        "congress_gov:witness[2]",
    ]
    assert cg_row["appearances"][0]["position"] == "Secretary of the Treasury"
    assert cg_row["appearances"][0]["document_links"] == []

    # 2. senate_page (context-free: retains literal document_links and optional <base href>)
    senate_html = """
    <html><head><base href="https://www.banking.senate.gov/hearings/nomination-hearing"/></head><body>
      <h2>Witnesses</h2>
      <div class="paragraph--witness">
        <div class="witness__field-name">Dr. Saule T. Omarova</div>
        <div class="witness__field-position">Professor of Law</div>
        <div class="witness__field-organization">Cornell Law School</div>
        <div class="witness__field-testimony">
          <a href="/imo/media/doc/Omarova_Testimony.pdf">Download Testimony</a>
        </div>
      </div>
    </body></html>
    """
    senate_row = appearance_records.build_appearance_record_row(
        _sha("senate-app"),
        "senate_page",
        senate_html,
        parser_version="v1",
    )
    assert senate_row["collection_state"] == "present"
    assert senate_row["declared_base"] == "https://www.banking.senate.gov/hearings/nomination-hearing"
    assert len(senate_row["appearances"]) == 1
    s_app = senate_row["appearances"][0]
    assert s_app["source_locator"] == "senate_page:witness[1]"
    assert s_app["name_key"] == "saule t omarova"
    assert s_app["position"] == "Professor of Law"
    assert s_app["organization"] == "Cornell Law School"
    assert s_app["document_links"] == ["/imo/media/doc/Omarova_Testimony.pdf"]

    # 3. mods (GovInfo MODS XML with witness lines and member bioguideId)
    mods_fixture = ROOT / "packages/congress_api/tests/fixtures/gpo_metadata/CHRG-113hhrg21122.xml"
    mods_bytes = mods_fixture.read_bytes()
    mods_row = appearance_records.build_appearance_record_row(
        _sha("mods-app"),
        "mods",
        mods_bytes,
        parser_version="v1",
    )
    assert mods_row["source"] == "mods"
    assert mods_row["collection_state"] == "present"
    assert len(mods_row["appearances"]) >= 1
    assert all(a["source_locator"].startswith("mods:witness[") for a in mods_row["appearances"])
    assert all(a["document_links"] == [] for a in mods_row["appearances"])
    # The print's own held dates and title, which a package-to-meeting link is checked against (ct-dx22).
    assert mods_row["held_dates"] == ["2013-06-13"]
    assert mods_row["title"] == "TAX REFORM: TAX HAVENS, BASE EROSION AND PROFIT-SHIFTING"
    assert cg_row["held_dates"] is None and cg_row["title"] is None

    # Round-trip through PyArrow table builder
    tbl = appearance_records.table([cg_row, senate_row, mods_row])
    assert tbl.schema == appearance_records.ARROW_SCHEMA
    assert tbl.num_rows == 3


# ---------------------------------------------------------------------------
# 4. Track B14: Raw Fetcher Routing, Header Credentials & S2 Relist Window
# ---------------------------------------------------------------------------


class _FakeDirectAdapter:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict[str, str]]] = []

    def hop(self, url: str, destination: Path, *, limit: int, headers: dict[str, str]):
        self.calls.append((url, dict(headers or {})))
        status, body, resp_headers = self.handler(url, headers or {})
        if body is not None:
            destination.write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            size = len(body)
        else:
            sha = None
            size = 0
        return Transfer(
            path=destination,
            url=url,
            http_status=status,
            provider_status=None,
            headers=resp_headers,
            complete=(status is not None and 200 <= status < 300),
            size=size,
            sha256=sha,
            error=None if (status is not None and 200 <= status < 300) else f"HTTP_{status}",
        )


def _make_raw_pipeline(tmp_path: Path, handler, *, headers_fn=None):
    store = BodyStore(LocalAdapter(tmp_path / "raw"))
    identity = {
        "job": "test-b14",
        "commit": "a" * 40,
        "lockfile_digest": "b" * 64,
    }
    writer = ReceiptWriter(
        store,
        identity=identity,
        run_id="run-b14",
        write_date="2026-10-30",
        archive_limits=None,
    )
    scope = CaptureScope(
        patterns=[r"https://.*"],
        exclusions=[],
        resolve=lambda host: ["93.184.216.34"],
    )
    direct = _FakeDirectAdapter(handler)
    fetcher = Fetcher(
        scope=scope,
        direct=direct,
        provider=None,
        pace=lambda url, transport: None,
        directory=tmp_path / "spool",
        spool_limit=16 << 20,
        headers=headers_fn,
        clock=lambda: "2026-10-30T00:00:00Z",
    )
    return store, writer, fetcher, direct


def test_b14_s2_relist_window_advances_only_when_every_page_succeeds(tmp_path: Path):
    """S2 Relist Fixture:
    - Keyed by `(endpoint, fromDateTime, toDateTime)`.
    - Sends Congress.gov API key in `X-Api-Key` header, never in the URL.
    - When page 2 fails (HTTP 500), the watermark does NOT advance (`window_advanced = False`).
    - When a retry fetches all pages through the final page cleanly, the watermark advances.
    """
    endpoint = f"{meetings_acq.API}/committee-meeting/118/house"
    from_dt = "2026-10-01T00:00:00Z"
    to_dt = "2026-10-30T00:00:00Z"
    fail_second_page = True

    page0_body = json.dumps(
        {
            "committeeMeetings": [
                {
                    "eventId": "118001",
                    "chamber": "House",
                    "congress": 118,
                    "updateDate": "2026-10-10T00:00:00Z",
                    "url": f"{endpoint}/118001?api_key=leak-attempt",
                },
                {
                    "eventId": "118002",
                    "chamber": "House",
                    "congress": 118,
                    "updateDate": "2026-10-11T00:00:00Z",
                    "url": f"{endpoint}/118002?format=json",
                },
            ],
            "pagination": {"count": 3, "next": f"{endpoint}?offset=2&limit=2"},
        }
    ).encode("utf-8")

    page1_body = json.dumps(
        {
            "committeeMeetings": [
                {
                    "eventId": "118003",
                    "chamber": "House",
                    "congress": 118,
                    "updateDate": "2026-10-12T00:00:00Z",
                    "url": f"{endpoint}/118003?format=json",
                }
            ],
            "pagination": {"count": 3, "next": None},
        }
    ).encode("utf-8")

    def handler(url: str, req_headers: dict[str, str]):
        assert "api_key" not in url.lower()
        assert req_headers.get("X-Api-Key") == "secret-congress-key"
        if "offset=0" in url:
            return 200, page0_body, {"content-type": "application/json"}
        if "offset=2" in url:
            if fail_second_page:
                return 500, b'{"error": "upstream failure"}', {"content-type": "application/json"}
            return 200, page1_body, {"content-type": "application/json"}
        return 404, b"{}", {"content-type": "application/json"}

    store, writer, fetcher, direct = _make_raw_pipeline(
        tmp_path, handler, headers_fn=congress_transport.api_headers("secret-congress-key")
    )
    watermarks: dict[Any, str] = {}

    # Run 1: Page 2 fails -> watermark must NOT advance
    run1 = meetings_acq.relist_endpoint_window(
        fetcher,
        writer,
        endpoint,
        from_date_time=from_dt,
        to_date_time=to_dt,
        limit=2,
        watermarks=watermarks,
    )
    assert run1["complete"] is False
    assert run1["window_advanced"] is False
    assert run1["failed_offset"] == 2
    assert watermarks == {}

    # Run 2: Page 2 succeeds -> watermark advances and all detail URLs are stripped of query params
    fail_second_page = False
    run2 = meetings_acq.relist_endpoint_window(
        fetcher,
        writer,
        endpoint,
        from_date_time=from_dt,
        to_date_time=to_dt,
        limit=2,
        watermarks=watermarks,
    )
    assert run2["complete"] is True
    assert run2["window_advanced"] is True
    assert run2["watermark"] == to_dt
    assert watermarks[(endpoint, from_dt, to_dt)] == to_dt
    assert run2["detail_urls"] == [
        f"{endpoint}/118001",
        f"{endpoint}/118002",
        f"{endpoint}/118003",
    ]

    # Verify stored receipts contain no credentials anywhere
    for r_key in run1["receipt_keys"] + run2["receipt_keys"]:
        raw_receipt = gzip.decompress((tmp_path / "raw" / r_key).read_bytes()).decode("utf-8")
        assert "secret-congress-key" not in raw_receipt
        assert "api_key" not in raw_receipt


def test_b14_govinfo_and_inventory_fetchers_route_through_raw(tmp_path: Path):
    mods_bytes = (ROOT / "packages/congress_api/tests/fixtures/gpo_metadata/CHRG-113hhrg21122.xml").read_bytes()
    collection_body = json.dumps(
        {
            "packages": [
                {
                    "packageId": "CHRG-113hhrg21122",
                    "lastModified": "2026-10-01T00:00:00Z",
                }
            ],
            "nextPage": None,
        }
    ).encode("utf-8")

    def handler(url: str, req_headers: dict[str, str]):
        assert "api_key" not in url.lower()
        if "api.govinfo.gov" in url:
            assert req_headers.get("X-Api-Key") == "secret-govinfo-key"
            return 200, collection_body, {"content-type": "application/json"}
        if url.endswith("/mods.xml"):
            return 200, mods_bytes, {"content-type": "application/xml"}
        if "senate.gov" in url:
            return 200, b"<html><head><title>Hearing</title></head><body><h1>Hearing</h1></body></html>", {"content-type": "text/html"}
        return 404, b"", {"content-type": "text/plain"}

    store, writer, fetcher, direct = _make_raw_pipeline(
        tmp_path, handler, headers_fn=gpo_acq.govinfo_api_headers("secret-govinfo-key")
    )

    packages = list(
        gpo_acq.list_collection(
            "2026-09-01T00:00:00Z",
            "secret-govinfo-key",
            fetcher=fetcher,
            receipt_writer=writer,
        )
    )
    assert len(packages) == 1
    assert packages[0]["packageId"] == "CHRG-113hhrg21122"

    pkg_res = gpo_acq.fetch_package_through_raw(fetcher, writer, "CHRG-113hhrg21122")
    assert pkg_res["complete"] is True
    assert pkg_res["outcome"] in ("stored", "unchanged")

    senate_res = senate_acq.fetch_page_through_raw(
        fetcher, writer, "https://www.banking.senate.gov/hearings/test-hearing"
    )
    assert senate_res["complete"] is True
    assert senate_res["http_status"] == 200

    fb = house_fallback.CommitteeFallback([], {}, fetcher=fetcher, receipt_writer=writer)
    fb_res = fb.fetch_through_raw("https://judiciary.house.gov/calendar/eventsingle.aspx?EventID=1")
    assert fb_res["http_status"] == 404


def test_d4_candidate_queries_and_native_iceberg_commits(tmp_path: Path):
    """D4 candidate queries match both archive-member and context_url CHRG MODS captures
    and commit `meeting_records` and `appearance_records` to native Iceberg tables.
    """
    import os
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets

    cfg = os.environ.get("DOCSPEC_JOB_CONFIG")
    if not cfg:
        pytest.skip("DOCSPEC_JOB_CONFIG required for native Iceberg test")

    sha_cm = bytes.fromhex(_sha("cand-cm"))
    sha_wl = bytes.fromhex(_sha("cand-wl"))
    sha_mods_member = bytes.fromhex(_sha("cand-mods-member"))
    sha_mods_context = bytes.fromhex(_sha("cand-mods-context"))
    sha_mods_bill = bytes.fromhex(_sha("cand-mods-bill"))
    sha_senate = bytes.fromhex(_sha("cand-senate"))

    captures_path = tmp_path / "captures.parquet"
    readings_path = tmp_path / "readings.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "sha256": sha_cm,
                    "url": "https://docs.house.gov/meetings/JU/JU00/20240510/118555/HHRG-118-JU00-20240510.xml",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                },
                {
                    "sha256": sha_wl,
                    "url": "https://docs.house.gov/meetings/JU/JU00/20240510/118555/HHRG-118-JU00-WList-20240510.xml",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                },
                {
                    "sha256": sha_mods_member,
                    "url": "https://www.govinfo.gov/content/pkg/CHRG-113hhrg21122.zip",
                    "requested_url": "https://www.govinfo.gov/content/pkg/CHRG-113hhrg21122.zip",
                    "context_url": "https://www.govinfo.gov/content/pkg/CHRG-113hhrg21122.zip",
                    "member_path": "CHRG-113hhrg21122/mods.xml",
                },
                {
                    "sha256": sha_mods_context,
                    "url": None,
                    "requested_url": None,
                    "context_url": "https://api.govinfo.gov/packages/CHRG-117hhrg44535/mods",
                    "member_path": None,
                },
                {
                    "sha256": sha_mods_bill,
                    "url": "https://www.govinfo.gov/metadata/pkg/BILLS-118hr1ih/mods.xml",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                },
                {
                    "sha256": sha_senate,
                    "url": "https://www.judiciary.senate.gov/meetings/oversight-hearing",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                },
            ],
            schema=pa.schema(
                [
                    ("sha256", pa.binary(32)),
                    ("url", pa.string()),
                    ("requested_url", pa.string()),
                    ("context_url", pa.string()),
                    ("member_path", pa.string()),
                ]
            ),
        ),
        captures_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"body_sha": sha_cm, "parser": "xml", "status": "completed", "xml_root": "committee-meeting"},
                {"body_sha": sha_wl, "parser": "xml", "status": "completed", "xml_root": "witness-list"},
                {"body_sha": sha_mods_member, "parser": "xml", "status": "completed", "xml_root": "mods"},
                {"body_sha": sha_mods_context, "parser": "xml", "status": "completed", "xml_root": "mods"},
                {"body_sha": sha_mods_bill, "parser": "xml", "status": "completed", "xml_root": "mods"},
                {"body_sha": sha_senate, "parser": "html", "status": "completed", "xml_root": None},
            ],
            schema=pa.schema(
                [
                    ("body_sha", pa.binary(32)),
                    ("parser", pa.string()),
                    ("status", pa.string()),
                    ("xml_root", pa.string()),
                ]
            ),
        ),
        readings_path,
    )

    engine = NativeDatasets.from_config(cfg)
    # Candidate routing is _record_producer.ROUTES, checked against the model's expected
    # sets in test_phase1_model_profile; the readings-only route queries are gone (ct-kn6d).
    # Stage and commit both tables to a local Iceberg catalog
    m_row = meeting_records.build_meeting_record_row(
        sha_cm.hex(),
        "congress_gov",
        {"eventId": "118555", "congress": 118, "chamber": "House", "title": "Oversight"},
    )
    a_row = appearance_records.build_appearance_record_row(
        sha_mods_context.hex(),
        "mods",
        {"package_id": "CHRG-117hhrg44535", "witnesses": ["Doe, Hon. John, Director, Agency Z"]},
    )
    m_staged = tmp_path / "m_staged.parquet"
    a_staged = tmp_path / "a_staged.parquet"
    pq.write_table(meeting_records.table([m_row]), m_staged)
    pq.write_table(appearance_records.table([a_row]), a_staged)

    cat_root = tmp_path / "catalog"
    m_spec = {"namespace": ["lake"], "name": "meeting_records"}
    a_spec = {"namespace": ["lake"], "name": "appearance_records"}
    meeting_records.create_table(
        engine=engine,
        work=tmp_path / "m_create",
        catalog_root=cat_root,
        table=m_spec,
        location=str(tmp_path / "tables/meeting_records"),
        create_namespace=True,
    )
    m_res = meeting_records.append(
        m_staged, engine=engine, work=tmp_path / "m_append", catalog_root=cat_root, table=m_spec
    )
    assert m_res["files"][0]["rows"] == 1

    appearance_records.create_table(
        engine=engine,
        work=tmp_path / "a_create",
        catalog_root=cat_root,
        table=a_spec,
        location=str(tmp_path / "tables/appearance_records"),
        create_namespace=False,
    )
    a_res = appearance_records.append(
        a_staged, engine=engine, work=tmp_path / "a_append", catalog_root=cat_root, table=a_spec
    )
    assert a_res["files"][0]["rows"] == 1


def test_record_producer_prefetch_and_local_cache_reuse(tmp_path: Path):
    """R2 candidate bodies are prefetched into `local_root` once and reused without re-fetching."""
    import gzip
    from congress_api.lake import _record_producer

    p1 = b'{"committeeMeeting":{"eventId":"118001","congress":118,"chamber":"House","title":"H1"}}'
    p2 = b'{"committeeMeeting":{"eventId":"118002","congress":118,"chamber":"House","title":"H2"}}'
    s1 = hashlib.sha256(p1).hexdigest()
    s2 = hashlib.sha256(p2).hexdigest()
    k1 = f"bodies/sha256/{s1[:2]}/{s1}.gz"
    k2 = f"bodies/sha256/{s2[:2]}/{s2}.gz"
    objects = {k1: gzip.compress(p1), k2: gzip.compress(p2)}
    calls: list[str] = []

    class FakeClient:
        def get_object(self, *, Bucket: str, Key: str):
            assert Bucket == "test-bucket"
            calls.append(Key)
            if Key not in objects:
                raise FileNotFoundError(Key)
            return {"Body": objects[Key]}

    class FakeAdapter:
        bucket = "test-bucket"
        client = FakeClient()

    class FakeStore:
        adapter = FakeAdapter()

    cache_dir = tmp_path / "local-cache"
    work_items = [
        {"record_sha": s1, "stored_suffix": ".gz", "source": "congress_gov"},
        {"record_sha": s2, "stored_suffix": ".gz", "source": "congress_gov"},
    ]
    _record_producer._prefetch_candidate_bodies(work_items, local_root=cache_dir, raw_store=FakeStore())
    assert sorted(calls) == sorted([k1, k2])
    assert (cache_dir / k1).is_file() and (cache_dir / k2).is_file()

    # Subsequent reads hit local_root without calling FakeClient.get_object again
    calls.clear()
    assert _record_producer._read_candidate_body(s1, ".gz", local_root=cache_dir, raw_store=FakeStore()) == p1
    assert _record_producer._read_candidate_body(s2, ".gz", local_root=cache_dir, raw_store=FakeStore()) == p2
    assert calls == []


def test_receipt_line_cursor_cache_and_version_decoupling(tmp_path: Path):
    """`_read_receipt_lines` keeps at most 1 receipt in memory and `current_version` is decoupled from orchestration."""
    import gzip
    from congress_api.lake import _record_producer, readings

    r1 = "receipts/congress/meetings/2026-10-01/r1.jsonl.gz"
    r2 = "receipts/congress/meetings/2026-10-02/r2.jsonl.gz"
    (tmp_path / r1).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / r2).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / r1).write_bytes(gzip.compress(b'{"line":1}\n'))
    (tmp_path / r2).write_bytes(gzip.compress(b'{"line":2}\n'))

    cache: dict[str, list[bytes]] = {}
    lines1 = _record_producer._read_receipt_lines(r1, local_root=tmp_path, raw_store=None, cache=cache)
    assert lines1 == [b'{"line":1}'] and list(cache.keys()) == [r1]
    lines2 = _record_producer._read_receipt_lines(r2, local_root=tmp_path, raw_store=None, cache=cache)
    assert lines2 == [b'{"line":2}'] and list(cache.keys()) == [r2]

    # Verify version digests are stable 64-char hex strings and decoupled from transport/orchestration
    assert len(meeting_records.current_version()) == 64
    assert len(appearance_records.current_version()) == 64
    leaf_versions = {p: readings.current_version(p) for p in ("sniff", "html", "xml", "json")}
    assert len(readings.bundle_version(leaf_versions, policy=readings.worker_limits())) == 64

    # Verify meetings.py is a thin re-export wrapper of meeting_records.py
    assert meetings.stage is meeting_records.stage
    assert meetings.current_versions is meeting_records.current_versions
    assert meetings._extract_prose_bill_keys is meeting_records._extract_prose_bill_keys
    assert meetings._extract_bill_keys_from_doc_url is meeting_records._extract_bill_keys_from_doc_url
    assert meetings.COLLECTION_STATES_STRUCT is meeting_records.COLLECTION_STATES_STRUCT


def test_candidate_eligibility_mods_senate_predicates_and_budget_fast_fail(tmp_path: Path):
    """ct-h1nd / ct-30fp / ct-kw9b:
    - CANDIDATE_MEETING_RECORDS_SQL and CANDIDATE_APPEARANCE_RECORDS_SQL require mode='fetch',
      complete=true, outcome IN ('stored','unchanged'), http_status BETWEEN 200 AND 299, sha256 IS NOT NULL.
    - Non-XML gpo/chrg captures (PDF/HTML transcripts) are NOT staged as 'mods', while lowercase
      'chrg' zip URLs with 'CHRG-.../mods.xml' member_path ARE staged as 'mods'.
    - .senate.gov PDF captures are NOT staged as 'senate_page', while family IN ('senate/hearings', 'senate/pages')
      and .senate.gov hearing HTMLs ARE staged as 'senate_page'.
    - max_work_items fast-fails before reading inline receipts when work_items exceeds budget.
    """
    import os
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets
    from congress_api.lake import readings

    cfg = os.environ.get("DOCSPEC_JOB_CONFIG")
    if not cfg:
        pytest.skip("DOCSPEC_JOB_CONFIG required for native candidate SQL test")
    engine = NativeDatasets.from_config(cfg)

    sha_incomplete = bytes.fromhex(_sha("incomplete-cg"))
    sha_chrg_pdf = bytes.fromhex(_sha("chrg-pdf"))
    sha_chrg_mods_zip = bytes.fromhex(_sha("chrg-mods-zip"))
    sha_senate_pdf = bytes.fromhex(_sha("senate-pdf"))
    sha_senate_pages = bytes.fromhex(_sha("senate-pages-html"))

    captures_path = tmp_path / "captures_eligibility.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "mode": "fetch",
                    "complete": None,
                    "outcome": "failed",
                    "http_status": None,
                    "sha256": sha_incomplete,
                    "stored_suffix": ".gz",
                    "family": "congress/meetings",
                    "url": "https://api.congress.gov/v3/committee-meeting/118/house/115538",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "json",
                    "media_type": "application/json",
                    "receipt_key": "r1",
                    "receipt_line": 1,
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": sha_chrg_pdf,
                    "stored_suffix": "",
                    "family": "gpo/chrg",
                    "url": "https://www.govinfo.gov/content/pkg/CHRG-118hhrg55555/pdf/CHRG-118hhrg55555.pdf",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "pdf",
                    "media_type": "application/pdf",
                    "receipt_key": "r1",
                    "receipt_line": 2,
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": sha_chrg_mods_zip,
                    "stored_suffix": ".gz",
                    "family": "documents",
                    "url": "https://www.govinfo.gov/bulkdata/chrg/118/chrg-118.zip",
                    "requested_url": "https://www.govinfo.gov/bulkdata/chrg/118/chrg-118.zip",
                    "context_url": None,
                    "member_path": "CHRG-118shrg99999/mods.xml",
                    "sniffed_format": "xml",
                    "media_type": "application/xml",
                    "receipt_key": "r1",
                    "receipt_line": 3,
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": sha_senate_pdf,
                    "stored_suffix": "",
                    "family": "documents",
                    "url": "https://www.banking.senate.gov/imo/media/doc/hearing_statement.pdf",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": None,
                    "media_type": "application/pdf",
                    "receipt_key": "r1",
                    "receipt_line": 4,
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": sha_senate_pages,
                    "stored_suffix": ".gz",
                    "family": "senate/pages",
                    "url": "https://www.banking.senate.gov/hearings/nomination-hearing",
                    "requested_url": None,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "html",
                    "media_type": "text/html",
                    "receipt_key": "r1",
                    "receipt_line": 5,
                },
            ],
            schema=pa.schema(
                [
                    ("mode", pa.string()),
                    ("bytes", pa.int64()),
                    ("complete", pa.bool_()),
                    ("outcome", pa.string()),
                    ("http_status", pa.int32()),
                    ("sha256", pa.binary(32)),
                    ("stored_suffix", pa.string()),
                    ("family", pa.string()),
                    ("url", pa.string()),
                    ("requested_url", pa.string()),
                    ("context_url", pa.string()),
                    ("member_path", pa.string()),
                    ("sniffed_format", pa.string()),
                    ("media_type", pa.string()),
                    ("receipt_key", pa.string()),
                    ("receipt_line", pa.int64()),
                ]
            ),
        ),
        captures_path,
    )

    with pytest.raises(readings.BackfillRequired) as exc_info:
        appearance_records.stage(
            captures=captures_path,
            engine=engine,
            work=tmp_path / "ar_budget",
            max_work_items=1,
            readings=empty_readings(tmp_path / "readings"),
        )
    assert exc_info.value.report["work_items"] == 2
    work_rows = pq.read_table(tmp_path / "ar_budget/work-list.parquet").to_pylist()
    assert {(r["record_sha"], r["source"]) for r in work_rows} == {
        (sha_chrg_mods_zip.hex(), "mods"),
        (sha_senate_pages.hex(), "senate_page"),
    }


def test_ct_h1nd_compact_dotted_senate_bills_amendatory_act_years_and_source_symbols():
    """ct-h1nd:
    - Compact dotted Senate bill designators ('S.140', 'S.744') extract '{congress}-s-140' and '{congress}-s-744',
      while 'U.S. 2023', 'R.S. 2477', 'W.S. 11-6-302', 'S 2(N)', and \"GAO's 2013\" remain rejected.
    - Amendatory bill descriptions like 'H.R. 2215, To amend the Help America Vote Act of 2002' in the 118th Congress
      extract '118-hr-2215', while 'H.R. 2, Agriculture Improvement Act of 2018' in a non-115th Congress remains suppressed.
    - SITTING_STRUCT, COMMITTEE_STRUCT, and VIDEO_STRUCT are included in meeting_records._SOURCE_SYMBOLS.
    """
    for src in ("congress_gov", "house_xml"):
        for struct_sym in ("SITTING_STRUCT", "COMMITTEE_STRUCT", "VIDEO_STRUCT"):
            assert struct_sym in meeting_records._SOURCE_SYMBOLS[src]

    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8"?>
<committee-meeting congress-num="118" session-num="2" meeting-id="HHRG118888" meeting-type="HHRG">
  <meeting-details>
    <meeting-title>Legislative Hearing on S.140 and U.S. 2023</meeting-title>
    <meeting-date><calendar-date>2024-06-20</calendar-date></meeting-date>
    <committees><committee-name id="II00">Committee on Natural Resources</committee-name></committees>
  </meeting-details>
  <meeting-documents>
    <meeting-document type="BR">
      <legis-num>S.744</legis-num>
      <description>H.R. 2215, To amend the Help America Vote Act of 2002; H.R. 2, Agriculture Improvement Act of 2018; R.S. 2477; W.S. 11-6-302; S 2(N); GAO's 2013</description>
    </meeting-document>
  </meeting-documents>
</committee-meeting>"""
    row = meeting_records.build_meeting_record_row(_sha("ct-h1nd-compact"), "house_xml", xml_bytes, parser_version="v1")
    m = row["meetings"][0]
    assert m["subject_keys"] == [
        "118-s-744",
        "118-hr-2215",
        "118-s-140",
    ]
    assert meeting_records._extract_prose_bill_keys("H.R. 2, Agriculture Improvement Act of 2018", 116) == []
    assert meeting_records._extract_prose_bill_keys("H.R. 2, Agriculture Improvement Act of 2018", 115) == ["115-hr-2"]
    assert (
        meeting_records._extract_prose_bill_keys(
            "H.R. 2215. To amend the Help America Vote Act of 2002", 118
        )
        == ["118-hr-2215"]
    )
    assert (
        meeting_records._extract_prose_bill_keys(
            "H.R. 2215 -- To amend the Help America Vote Act of 2002", 118
        )
        == ["118-hr-2215"]
    )
    assert (
        meeting_records._extract_prose_bill_keys(
            "H.R. 1732\u2014Regulatory Integrity Protection Act of 2015", 118
        )
        == []
    )
    assert (
        meeting_records._extract_prose_bill_keys(
            "H.R. 1732\u2014Regulatory Integrity Protection Act of 2015", 114
        )
        == ["114-hr-1732"]
    )


def test_jec_continuation_keeps_one_witness_and_does_not_merge_shared_file():
    href = "https://www.jec.senate.gov/public/index.cfm?a=Files.Serve&File_id=D2F941B3-FF5F-4503-B354-5C8BE5D7AF3B"
    # Source structure from the retained June 12, 2024 JEC page, followed by
    # two actual person labels sharing another file and an ungrouped link.
    html = f"""
    <p><strong>Witnesses:</strong></p>
    <p><a href="{href}">Mr. Scott Lincicome, Vice President of General Economics and</a></p>
    <p><a href="{href}">Stiefel Trade Policy Center</a></p>
    <p>Cato Institute</p>
    <p>Washington, DC</p>
    <p><a href="/shared.pdf">Dr. Sam Smith, Professor</a></p>
    <p><a href="/shared.pdf">Ms. Jane Doe, Researcher</a></p>
    <p><a href="/flat.pdf">Download testimony</a></p>
    """
    apps = appearance_records.extract_senate_page_observation(html)["appearances"]
    assert [(a["name"], a["position"], a["organization"], a["document_links"]) for a in apps] == [
        ("Scott Lincicome", "Vice President of General Economics and Stiefel Trade Policy Center", "Cato Institute", [href]),
        ("Sam Smith", "Professor", None, ["/shared.pdf"]),
        ("Jane Doe", "Researcher", None, ["/shared.pdf"]),
    ]


def test_senate_jet_roster_keeps_nominee_and_types_related_files_as_record_material():
    html = """<h2>Witnesses</h2>
      <div class="elementor-widget-jet-listing-grid">
        <div class="jet-listing-grid__item jet-listing-dynamic-post-1">
          <h3 class="jet-listing-dynamic-field__content">CHRISTINE M. MACEY</h3>
          <div class="jet-listing-dynamic-field__content">to be an Associate Judge</div>
          <a href="/macey-testimony.pdf">Download Testimony</a>
        </div>
      </div>
      <div class="elementor-widget-heading"><h2>Related Files</h2></div>
      <div class="elementor-widget-jet-listing-grid">
        <div class="jet-listing-grid__item jet-listing-dynamic-post-2">
          <h3 class="jet-listing-dynamic-field__content">Christine M. Macey (testimony.pdf)</h3>
          <a href="/macey-testimony.pdf">Related PDF</a>
        </div>
      </div>"""
    rows = appearance_records.extract_senate_page_observation(html)["appearances"]
    assert [(row["source_locator"], row["name"], row["witness_type"], row["document_links"]) for row in rows] == [
        ("senate_page:witness[1]", "CHRISTINE M. MACEY", None, ["/macey-testimony.pdf"]),
        ("senate_page:witness[2]", "Christine M. Macey", "record_material", ["/macey-testimony.pdf"]),
    ]


def test_ct_30fp_senate_page_repeated_witness_names_and_relative_document_links():
    """ct-30fp:
    - Two witness cards on a Senate hearing page sharing the same normalized name ('John Smith' from 'Org A'
      with href='smith-a.pdf' and 'John Smith' from 'Org B' with href='smith-b.pdf') are both preserved with
      distinct source_locator ('senate_page:witness[1]', 'senate_page:witness[2]'), their respective organization,
      and their respective document_links (['smith-a.pdf'], ['smith-b.pdf']).
    - Relative href='testimony.pdf' and href='../media/bio.pdf' (with no <base href>) are preserved literally
      in document_links rather than rewritten against https://senate-page.local/ to '/testimony.pdf' and '/media/bio.pdf'.
    """
    repeated_html = """
    <html><body>
      <h2>Witnesses</h2>
      <div class="paragraph--witness">
        <div class="witness__field-name">John Smith</div>
        <div class="witness__field-position">Director</div>
        <div class="witness__field-organization">Org A</div>
        <div class="witness__field-testimony">
          <a href="smith-a.pdf">Download Testimony</a>
        </div>
      </div>
      <div class="paragraph--witness">
        <div class="witness__field-name">John Smith</div>
        <div class="witness__field-position">President</div>
        <div class="witness__field-organization">Org B</div>
        <div class="witness__field-testimony">
          <a href="smith-b.pdf">Download Testimony</a>
        </div>
      </div>
    </body></html>
    """
    row_rep = appearance_records.build_appearance_record_row(
        _sha("senate-repeated-smith"), "senate_page", repeated_html, parser_version="v1"
    )
    assert row_rep["collection_state"] == "present"
    assert row_rep["declared_base"] is None
    apps = row_rep["appearances"]
    assert len(apps) == 2
    assert [a["source_locator"] for a in apps] == ["senate_page:witness[1]", "senate_page:witness[2]"]
    assert [a["name_key"] for a in apps] == ["john smith", "john smith"]
    assert [a["organization"] for a in apps] == ["Org A", "Org B"]
    assert [a["document_links"] for a in apps] == [["smith-a.pdf"], ["smith-b.pdf"]]

    rel_html = """
    <html><body>
      <h2>Witnesses</h2>
      <div class="paragraph--witness">
        <div class="witness__field-name">Dr. Alice Example</div>
        <div class="witness__field-position">Senior Fellow</div>
        <div class="witness__field-organization">Policy Institute</div>
        <div class="witness__field-testimony">
          <a href="testimony.pdf">Prepared Statement</a>
          <a href="../media/bio.pdf">Witness Biography</a>
        </div>
      </div>
    </body></html>
    """
    row_rel = appearance_records.build_appearance_record_row(
        _sha("senate-relative-links"), "senate_page", rel_html, parser_version="v1"
    )
    assert row_rel["declared_base"] is None
    assert len(row_rel["appearances"]) == 1
    assert row_rel["appearances"][0]["document_links"] == ["testimony.pdf", "../media/bio.pdf"]

    senate6_html = (ROOT / "packages/congress_api/tests/fixtures/meeting_inventory/senate-6.html").read_text(encoding="utf-8")
    row_s6 = appearance_records.build_appearance_record_row(
        _sha("senate-6"), "senate_page", senate6_html, parser_version="v1"
    )
    assert len(row_s6["appearances"]) == 7
    assert all(a["name"] != "Download File" for a in row_s6["appearances"])
    assert all(len(a["document_links"]) == 1 for a in row_s6["appearances"])
    assert row_s6["appearances"][0]["organization"] == "Veterans Health Administration, U.S. Department of Veterans Affairs"

    bad_senate_dict = {"witnesses": ["not-a-dict", {"name": "   "}]}
    row_bad_senate = appearance_records.build_appearance_record_row(
        _sha("senate-bad-dict"), "senate_page", bad_senate_dict, parser_version="v1"
    )
    assert row_bad_senate["collection_state"] == "unrecognized"

    bad_mods_dict = {"package_id": "CHRG-118shrg1", "witnesses": [123, {"name": ""}]}
    row_bad_mods = appearance_records.build_appearance_record_row(
        _sha("mods-bad-dict"), "mods", bad_mods_dict, parser_version="v1"
    )
    assert row_bad_mods["collection_state"] == "unrecognized"


def test_ct_30fp_congress_gov_invalid_witness_items_and_sql_per_context_freshness_and_failed_state(tmp_path: Path):
    """ct-30fp:
    - Congress.gov JSON payload with 'witnesses': [123, 'bad'] maps to collection_state = 'unrecognized' (not 'empty').
    - status IN ('error', 'size_limit') on appearance_records_input maps to collection_state = 'failed'
      (distinct from 'unrecognized' in appearance-records-resolved.sql while blocking lower-priority fallback).
    - Multi-context update ordering (X@A -> Y@A -> X@B): body X captured at URL A (t=1), updated body Y captured at
      URL A (t=2), then old body X captured at mirror URL B (t=3); X@B does not resurrect X at A or beat Y when A
      has already superseded X with Y.
    """
    import os
    import pyarrow.parquet as pq
    from docspec_client.client import NativeDatasets
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import json_input, list_of, run_job, struct

    bad_cg = {"committeeMeeting": {"eventId": "118901", "witnesses": [123, "bad"]}}
    bad_row = appearance_records.build_appearance_record_row(
        _sha("cg-bad-items"), "congress_gov", bad_cg, parser_version="v1"
    )
    assert bad_row["collection_state"] == "unrecognized"
    assert bad_row["appearances"] == []

    cfg = os.environ.get("DOCSPEC_JOB_CONFIG")
    if not cfg:
        pytest.skip("DOCSPEC_JOB_CONFIG required for appearance-records-resolved.sql test")
    engine = NativeDatasets.from_config(cfg)

    sha_x = _sha("body-x")
    sha_y = _sha("body-y")
    sha_err = _sha("body-err")
    sha_cg_fb = _sha("body-cg-fb")
    sha_cg_present = _sha("body-cg-present-joint")
    sha_cg_unres = _sha("body-cg-unres-joint")
    url_a = "https://docs.house.gov/meetings/JU/JU00/20240510/3001/HHRG-118-JU00-WList-20240510-a.xml"
    url_b = "https://docs.house.gov/meetings/JU/JU00/20240510/3001/HHRG-118-JU00-WList-20240510-b.xml"
    url_err = "https://docs.house.gov/meetings/JU/JU00/20240510/3002/HHRG-118-JU00-WList-20240510.xml"
    url_cg_fb = "https://api.congress.gov/v3/committee-meeting/118/house/3002"
    url_cg_joint_1 = "https://www.congress.gov/committee-meeting/118/joint/3003"
    url_cg_joint_2 = "https://api.congress.gov/v3/committee-meeting/118/joint/3003"

    work = tmp_path / "sql_check"
    work.mkdir(parents=True, exist_ok=True)
    captures_path = work / "captures.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [dict(row, fidelity="exact-bytes", receipt_key="receipts/fixture.jsonl",
                  receipt_line=index+1, capture_index=0, run_id="fixture")
             for index, row in enumerate([
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_x),
                    "family": "house/witness-xml",
                    "url": url_a,
                    "requested_url": url_a,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "xml",
                    "media_type": "text/xml",
                    "retrieved_at": "2024-05-10T10:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_y),
                    "family": "house/witness-xml",
                    "url": url_a,
                    "requested_url": url_a,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "xml",
                    "media_type": "text/xml",
                    "retrieved_at": "2024-05-10T12:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_x),
                    "family": "house/witness-xml",
                    "url": url_b,
                    "requested_url": url_b,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "xml",
                    "media_type": "text/xml",
                    "retrieved_at": "2024-05-10T14:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_err),
                    "family": "house/witness-xml",
                    "url": url_err,
                    "requested_url": url_err,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "xml",
                    "media_type": "text/xml",
                    "retrieved_at": "2024-05-10T15:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_cg_fb),
                    "family": "congress/meetings",
                    "url": url_cg_fb,
                    "requested_url": url_cg_fb,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "json",
                    "media_type": "application/json",
                    "retrieved_at": "2024-05-10T16:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_cg_present),
                    "family": "congress/meetings",
                    "url": url_cg_joint_1,
                    "requested_url": url_cg_joint_1,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "json",
                    "media_type": "application/json",
                    "retrieved_at": "2024-05-10T17:00:00Z",
                },
                {
                    "mode": "fetch",
                    "complete": True,
                    "outcome": "stored",
                    "http_status": 200,
                    "sha256": bytes.fromhex(sha_cg_unres),
                    "family": "congress/meetings",
                    "url": url_cg_joint_2,
                    "requested_url": url_cg_joint_2,
                    "context_url": None,
                    "member_path": None,
                    "sniffed_format": "json",
                    "media_type": "application/json",
                    "retrieved_at": "2024-05-10T18:00:00Z",
                },
            ])],
            schema=pa.schema(
                [
                    ("fidelity", pa.string()),
                    ("receipt_key", pa.string()),
                    ("receipt_line", pa.int64()),
                    ("capture_index", pa.int32()),
                    ("run_id", pa.string()),
                    ("mode", pa.string()),
                    ("complete", pa.bool_()),
                    ("outcome", pa.string()),
                    ("http_status", pa.int32()),
                    ("sha256", pa.binary(32)),
                    ("family", pa.string()),
                    ("url", pa.string()),
                    ("requested_url", pa.string()),
                    ("context_url", pa.string()),
                    ("member_path", pa.string()),
                    # captures.original_path and mapping_version (r1b-e1): the model reads every column it joins.
                    ("original_path", pa.string()),
                    ("sniffed_format", pa.string()),
                    ("media_type", pa.string()),
                    ("retrieved_at", pa.string()),
                    ("mapping_version", pa.string()),
                ]
            ),
        ),
        captures_path,
    )
    inputs = [
        table_input("captures", captures_path),
        json_input(work, "appearance_observation_exclusions", [], source="Utf8", receipt_key="Utf8",
                   receipt_line="Int64", capture_index="Int32", run_id="Utf8", reason="Utf8"),
        json_input(
            work,
            "parser_versions",
            [
                {"parser": "appearance_records.house_xml", "version": "v1"},
                {"parser": "appearance_records.congress_gov", "version": "v1"},
            ],
            parser="Utf8",
            version="Utf8",
        ),
        json_input(
            work,
            "meeting_sources",
            [
                {"kind": "appearance", "source": "house_xml", "priority": 1},
                {"kind": "appearance", "source": "congress_gov", "priority": 2},
            ],
            kind="Utf8",
            source="Utf8",
            priority="Int32",
        ),
        json_input(
            work,
            "meeting_records_input",
            [],
            record_sha_hex="Utf8",
            parser_version="Utf8",
            status="Utf8",
            source="Utf8",
            meetings=list_of(struct(updated="Utf8")),
        ),
        json_input(work, "package_meeting_links", [], package_id="Utf8", event_id="Int64", witness_eligible="Boolean"),
        json_input(work, "appearance_url_keys", [], url="Utf8", url_key="Utf8", error="Utf8"),
        json_input(
            work,
            "appearance_records_input",
            [
                {
                    "record_sha_hex": sha_x,
                    "parser_version": "v1",
                    "status": "completed",
                    "error_type": None,
                    "source": "house_xml",
                    "event_id": 3001,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "present",
                    "context_url": None,
                    "appearances": [
                        {
                            "source_locator": "house_xml:panel[1]/witness[1]",
                            "name_key": "stale witness x",
                            "name": "Stale Witness X",
                            "honorific": None,
                            "given": "Stale",
                            "middle": None,
                            "family": "X",
                            "suffix": None,
                            "position": None,
                            "organization": None,
                            "on_behalf_of": None,
                            "location": None,
                            "panel": None,
                            "panel_order": 1,
                            "display_order": 1,
                            "witness_type": None,
                            "testified": None,
                            "bioguide_id": None,
                            "document_links": [],
                        }
                    ],
                },
                {
                    "record_sha_hex": sha_y,
                    "parser_version": "v1",
                    "status": "completed",
                    "error_type": None,
                    "source": "house_xml",
                    "event_id": 3001,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "present",
                    "context_url": None,
                    "appearances": [
                        {
                            "source_locator": "house_xml:panel[1]/witness[1]",
                            "name_key": "updated witness y",
                            "name": "Updated Witness Y",
                            "honorific": None,
                            "given": "Updated",
                            "middle": None,
                            "family": "Y",
                            "suffix": None,
                            "position": None,
                            "organization": None,
                            "on_behalf_of": None,
                            "location": None,
                            "panel": None,
                            "panel_order": 1,
                            "display_order": 1,
                            "witness_type": None,
                            "testified": None,
                            "bioguide_id": None,
                            "document_links": [],
                        }
                    ],
                },
                {
                    "record_sha_hex": sha_err,
                    "parser_version": "v1",
                    "status": "error",
                    "error_type": "ParseError",
                    "source": "house_xml",
                    "event_id": 3002,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": None,
                    "context_url": None,
                    "appearances": [],
                },
                {
                    "record_sha_hex": sha_cg_fb,
                    "parser_version": "v1",
                    "status": "completed",
                    "error_type": None,
                    "source": "congress_gov",
                    "event_id": 3002,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "present",
                    "context_url": None,
                    "appearances": [
                        {
                            "source_locator": "congress_gov:witness[1]",
                            "name_key": "should be blocked",
                            "name": "Should Be Blocked",
                            "honorific": None,
                            "given": None,
                            "middle": None,
                            "family": None,
                            "suffix": None,
                            "position": None,
                            "organization": None,
                            "on_behalf_of": None,
                            "location": None,
                            "panel": None,
                            "panel_order": 1,
                            "display_order": 1,
                            "witness_type": None,
                            "testified": None,
                            "bioguide_id": None,
                            "document_links": [],
                        }
                    ],
                },
                {
                    "record_sha_hex": sha_cg_present,
                    "parser_version": "v1",
                    "status": "completed",
                    "error_type": None,
                    "source": "congress_gov",
                    "event_id": None,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "present",
                    "context_url": None,
                    "appearances": [
                        {
                            "source_locator": "congress_gov:witness[1]",
                            "name_key": "joint witness z",
                            "name": "Joint Witness Z",
                            "honorific": None,
                            "given": None,
                            "middle": None,
                            "family": None,
                            "suffix": None,
                            "position": None,
                            "organization": None,
                            "on_behalf_of": None,
                            "location": None,
                            "panel": None,
                            "panel_order": 1,
                            "display_order": 1,
                            "witness_type": None,
                            "testified": None,
                            "bioguide_id": None,
                            "document_links": [],
                        }
                    ],
                },
                {
                    "record_sha_hex": sha_cg_unres,
                    "parser_version": "v1",
                    "status": "completed",
                    "error_type": None,
                    "source": "congress_gov",
                    "event_id": None,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "unrecognized",
                    "context_url": None,
                    "appearances": [],
                },
            ],
            record_sha_hex="Utf8",
            parser_version="Utf8",
            status="Utf8",
            error_type="Utf8",
            source="Utf8",
            event_id="Int64",
            package_id="Utf8",
            declared_base="Utf8",
            collection_state="Utf8",
            context_url="Utf8",
            created="Utf8",
            appearances=list_of(
                struct(
                    source_locator="Utf8",
                    name_key="Utf8",
                    name="Utf8",
                    honorific="Utf8",
                    given="Utf8",
                    middle="Utf8",
                    family="Utf8",
                    suffix="Utf8",
                    position="Utf8",
                    organization="Utf8",
                    on_behalf_of="Utf8",
                    location="Utf8",
                    panel="Utf8",
                    panel_order="Int32",
                    display_order="Int32",
                    witness_type="Utf8",
                    testified="Boolean",
                    bioguide_id="Utf8",
                    document_links=list_of("Utf8"),
                )
            ),
        ),
    ]
    resolved_sql = (ROOT / "model/sql/appearance-records-resolved.sql").read_text(encoding="utf-8")
    observations_sql = (ROOT / "model/sql/appearance-observations.sql").read_text(encoding="utf-8")
    state_sql = "SELECT record_sha_hex, collection_state, effective_state FROM appearance_observations WHERE record_sha_hex='" + sha_err + "'"
    res = run_job(
        work,
        engine,
        inputs=inputs,
        steps=[{"name": "selected_appearance_records", "sql": "SELECT * FROM appearance_records_input", "materialize": True},
               {"name": "selected_meeting_records", "sql": "SELECT * FROM meeting_records_input", "materialize": True},
               {"name": "meetings_resolved", "sql": "SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS DATE) AS meeting_date WHERE false", "materialize": True},
               {"name": "appearance_people", "sql": (ROOT / "model/sql/appearance-people.sql").read_text(encoding="utf-8"), "materialize": True},
               {"name": "senate_page_meeting_links", "sql": "SELECT cast(NULL AS VARCHAR) AS record_sha_hex,cast(NULL AS BIGINT) AS event_id WHERE false", "materialize": True},
               {"name": "appearance_capture_contexts", "sql": (ROOT / "model/sql/appearance-capture-contexts.sql").read_text(encoding="utf-8"), "materialize": True},
               {"name": "appearance_observations", "sql": observations_sql, "materialize": True},
               {"name": "resolved", "sql": resolved_sql, "materialize": True}],
        outputs=[],
        queries=[
            {"name": "rows", "sql": "SELECT occasion, name, record_sha_hex FROM resolved ORDER BY occasion, display_order"},
            {"name": "err_state", "sql": state_sql},
        ],
    )
    assert res["err_state"] == [
        {"record_sha_hex": sha_err, "collection_state": "failed", "effective_state": "unresolved"}
    ]
    assert res["rows"] == [
        {"occasion": "meeting:3001", "name": "Updated Witness Y", "record_sha_hex": sha_y},
        {"occasion": "meeting:3003", "name": "Joint Witness Z", "record_sha_hex": sha_cg_present},
    ]


def _house_location(location):
    xml = f"""<committee-meeting meeting-id="HHRG-118-JU00-20240510" update-date="2024-05-09T10:00:00" meeting-status="1">
    <meeting-details><meeting-date><calendar-date>{{day}}</calendar-date><start-time>10:00:00</start-time><end-time>12:30:00</end-time></meeting-date>
    <meeting-location>{location}</meeting-location></meeting-details></committee-meeting>"""
    return xml


@pytest.mark.parametrize("day,start,end", [("2012-09-13", "2012-09-13T10:00:00-04:00", "2012-09-13T12:30:00-04:00"),
                                          ("2019-11-13", "2019-11-13T10:00:00-05:00", "2019-11-13T12:30:00-05:00")])
def test_house_times_state_their_eastern_offset(day, start, end):
    xml = _house_location("<capitol-complex><room>2141</room><building>RHOB</building></capitol-complex>").replace("{day}", day).encode()
    sitting = meeting_records.extract_house_xml_meetings(xml)[0]["sittings"][0]
    assert (sitting["start"], sitting["end"], sitting["room"], sitting["building"]) == (start, end, "2141", "Rayburn House Office Building")


def test_house_field_location_states_building_and_address_once():
    xml = _house_location("""<field><building-name>Richmond City Hall</building-name><street-address>36725 Division Road</street-address>
    <city>Richmond</city><state postal-code="MI"><state-fullname>Michigan</state-fullname></state><zip>48062</zip></field>""").replace("{day}", "2019-11-13").encode()
    sitting = meeting_records.extract_house_xml_meetings(xml)[0]["sittings"][0]
    assert sitting["building"] == "Richmond City Hall" and sitting["room"] is None
    assert sitting["address"] == "36725 Division Road, Richmond, MI, 48062"


@pytest.mark.parametrize("placeholder", ["Select one", "----------", "---"])
def test_unset_form_values_state_no_place(placeholder):
    xml = _house_location(f"<capitol-complex><room>{placeholder}</room><building>{placeholder}</building></capitol-complex>").replace("{day}", "2019-11-13").encode()
    sitting = meeting_records.extract_house_xml_meetings(xml)[0]["sittings"][0]
    assert sitting["room"] is None and sitting["building"] is None
    congress = meeting_records._convert_congress_meeting_dict({"eventId": "1", "date": "2019-11-13T19:00:00Z", "location": {"room": placeholder, "building": placeholder}})
    assert congress["sittings"][0]["room"] is None and congress["sittings"][0]["building"] is None


@pytest.mark.parametrize("control", json.loads(
    (Path(__file__).parent / "fixtures/source_models/mods-witness-affiliations.json").read_text()
), ids=lambda control: control["package"] + ":" + control["locator"])
def test_mods_affiliation_spans_match_independently_read_originals(control):
    # Keep the exact source position and an adjacent copy as distinct occurrences.
    index = int(control["locator"].removeprefix("mods:witness[").removesuffix("]"))
    xml = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension>'
           + '<witness/>' * (index - 1)
           + f'<witness>{escape(control["literal"])}</witness>' * 2
           + '</extension></mods>')
    row = appearance_records.build_appearance_record_row(_sha(xml), "mods", xml, package_id=control["package"])
    item, copy = (item for item in row["appearances"] if item["name"])
    assert item["source_locator"] == control["locator"]
    assert copy["source_locator"] == f"mods:witness[{index + 1}]"
    assert {field: item[field] for field in control["expected"]} == control["expected"]


@pytest.mark.parametrize("package,index,suffix", [
    ("CHRG-112hhrg72238", 3, ""),
    ("CHRG-112hhrg72239", 2, ""),
    ("CHRG-112hhrg72238", 2, " (test)"),
    (None, 2, ""),
])
def test_mods_unreviewed_affiliation_keeps_original_field_split(package, index, suffix):
    line = ("Mr. Thomas L. Farmer, Assistant Vice President for Security, Safety, and Operations, "
            "Association of American Railroads" + suffix + ":")
    row = appearance_records.build_appearance_record_row(
        _sha(line), "mods", {"witnesses": [""] * (index - 1) + [line]}, package_id=package,
    )
    item, = row["appearances"]
    assert item["source_locator"] == f"mods:witness[{index}]"
    assert item["name"] == "Thomas L. Farmer"
    assert item["position"] == "Assistant Vice President for Security"
    assert item["organization"] == "Safety, and Operations, Association of American Railroads" + suffix + ":"


@pytest.mark.parametrize("control", json.loads(
    (Path(__file__).parent / "fixtures/source_models/mods-representative-boundaries.json").read_text()
), ids=lambda control: control["package"] + ":" + control["locator"])
def test_mods_representative_preserves_party_qualifiers_and_excludes_other_entries(control):
    xml = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension><witness>'
           + escape(control["source_literal"]) + '</witness></extension></mods>')
    row = appearance_records.build_appearance_record_row(_sha(xml), "mods", xml)
    item, = row["appearances"]
    assert item["on_behalf_of"] in [
        control["expected_source_span"], *control["allowed_if_boundary_remains_unresolved"],
    ]


@pytest.mark.parametrize("line, expected", [
    ("Jane Doe, Director, on behalf of (Ret.) :", None),
    ("Jane Doe, Director, on behalf of The Testimony Project", "The Testimony Project"),
    ("Jane Doe, Director, on behalf of The Hon. Jane Roe", "The Hon. Jane Roe"),
    ("Jane Doe, Director, on behalf of the Hon. Jane Roe", "the Hon. Jane Roe"),
    ("Jane Doe, Director, on behalf of Agency, and President's Council on the Arts",
     "Agency, and President's Council on the Arts"),
    ("Jane Doe (filed, on behalf of Panel 42), Director, on behalf of Agency", "Agency"),
])
def test_mods_representative_preserves_names_and_legacy_marker_selection(line, expected):
    row = appearance_records.build_appearance_record_row(_sha(line), "mods", {"witnesses": [line]})
    item, = row["appearances"]
    assert item["on_behalf_of"] == expected
    assert item["position"] == "Director"


@pytest.mark.parametrize("control", json.loads(
    (Path(__file__).parent / "fixtures/source_models/mods-person-boundaries.json").read_text()
), ids=lambda control: control["package"] + ":" + control["locator"])
def test_mods_reads_qualified_person_fields_at_exact_source_position(control):
    index = int(control["locator"].split("[")[1].removesuffix("]"))
    row = appearance_records.build_appearance_record_row(
        _sha(control["source_literal"]), "mods",
        {"witnesses": [""] * (index - 1) + [control["source_literal"]]},
        package_id=control["package"],
    )
    item, = row["appearances"]
    assert item["source_locator"] == control["locator"]
    assert {key: item[key] for key in control["fields"]} == control["fields"]
    assert item["name_key"] == appearance_records.normalize_name_key(control["expected_name"])


def test_mods_person_qualification_requires_package_position_and_original_line():
    line = "American Enterprise Institute, John H. Makin"
    expected = "John H. Makin"
    assert appearance_records._mods_witness_fields(
        line, package_id="CHRG-108hhrg91630", source_index=4,
    )["name"] == expected
    for package, index, text in [
        ("CHRG-108hhrg91630", 3, line),
        ("CHRG-108hhrg91631", 4, line),
        ("CHRG-108hhrg91630", 4, line + ", Additional material"),
        (None, 4, line),
    ]:
        assert appearance_records._mods_witness_fields(
            text, package_id=package, source_index=index,
        )["name"] != expected


def test_mods_reviewed_joined_line_yields_both_printed_entries():
    """ct-79j1: CHRG-113shrg89525's sixth contents line repeats Victor Joseph's entry and runs it into
    Michael K. Abbott's. The retained MODS bytes give Abbott his own occurrence after Joseph's."""
    xml = (ROOT / "packages/congress_api/tests/fixtures/gpo_metadata/CHRG-113shrg89525.xml").read_bytes()
    assert hashlib.sha256(xml).hexdigest() == "83dbe14fa901ff9af106119cfa1da71e896381bb92d12cafdfca1a7ce0a8deaa"
    row = appearance_records.build_appearance_record_row(_sha("mods-89525"), "mods", xml)
    assert row["package_id"] == "CHRG-113shrg89525" and row["event_id"] is None
    people = [(a["source_locator"], a["name"], a["position"], a["organization"], a["display_order"])
              for a in row["appearances"]]
    joseph = ("Victor Joseph", "President and Chairman", "Tanana Chiefs Conference")
    assert people[3:] == [
        ("mods:witness[4]", *joseph, 4),
        ("mods:witness[5]", "Danita Koehler", "Chair",
         "Rural Committee, National Association of Emergency Medical Services Physicians", 5),
        ("mods:witness[6]", *joseph, 6),
        ("mods:witness[6]/part[2]", "Michael K. Abbott", "Assistant Superintendent", "Anchorage School District", 7),
    ]
    assert [a["source_locator"] for a in row["appearances"][:3]] == [f"mods:witness[{i}]" for i in (1, 2, 3)]
    abbott = row["appearances"][-1]
    assert abbott["name_key"] == "michael k abbott" and abbott["witness_type"] is None
    assert abbott["on_behalf_of"] is None and abbott["document_links"] == []

    # The split needs the reviewed package, position and exact original line.
    for package, before in [("CHRG-113shrg89526", 5), ("CHRG-113shrg89525", 4)]:
        line = xml.decode().split("<witness>")[6].split("</witness>")[0]
        lines = "".join("<witness/>" for _ in range(before)) + f"<witness>{line}</witness>"
        other = ('<mods xmlns="http://www.loc.gov/mods/v3"><extension>' + lines + "</extension></mods>")
        found = appearance_records.extract_mods_appearances(other, package_id=package)
        assert [a["name"] for a in found if a["name"]] == ["Victor Joseph"]


def test_mods_print_states_every_held_day_and_labels_statements():
    """A multi-day print states later days in constituent items (Haaland 328803), and its <witness> list
    carries letters for the record and Members' statements, which are not witnesses (red-f2)."""
    xml = b"""<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Haaland Nomination</title></titleInfo>
      <extension><heldDate>2021-02-23</heldDate><witness>Doe, Hon. Jane, Director, Office of Things</witness>
      <witness>Florida Fish and Wildlife Conservation Commission, Letter of Support for H.R. 5103</witness>
      <witness>Prepared statement of Hon. Richard E. Neal, a Representative in Congress from the State of Massachusetts</witness>
      <witness>Green, Hon. Al, a Representative in Congress from the State of Texas</witness>
      <witness>Hon. Russell T. Vought to be Director, Office of Management and Budget, Testimony</witness></extension>
      <relatedItem type="constituent"><extension><heldDate>2021-02-24</heldDate></extension></relatedItem></mods>"""
    row = appearance_records.build_appearance_record_row(_sha("mods-two-day"), "mods", xml, parser_version="v1", package_id="CHRG-117shrg43821")
    assert row["held_dates"] == ["2021-02-23", "2021-02-24"] and row["title"] == "Haaland Nomination"
    assert [(a["name"], a["witness_type"]) for a in row["appearances"]] == [
        ("Jane Doe", None),
        ("Florida Fish and Wildlife Conservation Commission", "statement_for_record"),
        ("Richard E. Neal", "member_statement"),
        # red-f3: a Member who appears and a nominee are witnesses; only explicit markers make a statement.
        ("Al Green", None),
        ("Russell T. Vought to be Director", None),
    ]


@pytest.mark.parametrize("line,kind", [
    # A line that opens with a record entry's marker is that entry, whatever words follow (red-f3, v21 prints).
    ("Letter from the nominee to the Office of General Counsel, U.S. Department of Veterans Affairs", "statement_for_record"),
    ("Letter, followup to hearing testimony", "statement_for_record"),
    ("Submittals for the record: John Windhausen, Jr., President, letter dated June 23, 1999, and the testimony of US West CEO "
     "Sol Trujillo to Hon. John McCain and Hon. Ernest F. Hollings", "statement_for_record"),
    ("Additional information for the record \\1\\ Vednita Carter, Founder and Executive Director, Breaking Free", "statement_for_record"),
    ("Additional material for the record \\1\\ John S. Hughes, M.D., Professor of Medicine, Yale School of Medicine", "statement_for_record"),
    ("Additional oral comments presented for the record: Carper, Chip, Hebron, Maryland", "statement_for_record"),
    ('Investing in Racial Diversity in Tech" has been retained in committee files and also is available as part of Ms. Kim\'s '
     "written testimony at https://docs.house.gov/meetings/IF/IF17/20190306/108901/HHRG-116-IF17-Wstate-KimJ-20190306.pdf", "statement_for_record"),
    # A witness's own line that mentions material for the record, or ends in a contents tail, is still the witness.
    ("Goodlatte, Bob, U.S. Representative from Virginia, along with added material for the record; China: Export of Technology "
     "Would be Liberating Force", None),
    ("Steve Chalk, Chief Financial Officer, Energy Efficiency and Renewable Energy, Department of Energy \\1\\..................... "
     "Insert for the record", None),
    ("Hon. Russell T. Vought to be Director, Office of Management and Budget, Testimony", None),
    # Footnote text before a witness's own line does not make it a record entry (green-f4).
    ("Science, Changing the Culture'' and the accompanying slide presentation have been retained in committee records and also are "
     "available at http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=101897. Gerard A. Gioia, Chief, Division of "
     "Pediatric Neuropsychology, Children's National Health System", None),
    ("is available at https://docs.house.gov/meetings/IF/IF14/ 20200129/110423/HHRG-116-IF14-Wstate-ChuaK-20200129.pdf. \\2\\ "
     "Nancy Perry, did not answer the question by the time of publication. Melanie Benesh, Legislative Attorney, Environmental "
     "Working Group", None),
    # A witness's own entries (their prepared statement, their answers) are the witness's (D4 gate).
    ("Prepared statement \\2\\ \\1\\ The information has been retained in committee files and also is available at "
     "http://docs.house.gov/meetings/IF/IF03/20150603/103551/ BILLS-114pih-SubtitleA-EnergyEfficiency.pdf. John E. Shelk, "
     "President and Chief Executive Officer, Electric Power Supply Association", None),
    ("Prepared statement Erik D. Olson, Senior Strategic Director for Health And Food, Natural Resources Defense Counsel", None),
    ("Submitted questions: Taylor, Alexis", None),
    # Some prints list each witness as "Statement of ..."; that heading is the witness, not an entry.
    ("Statement of Dr. Robert D. Putnam, Professor of Public Policy, Harvard University", None),
    ("Additional information \\1\\ Kevin Sunday, Director, Government Affairs, Pennsylvania Chamber of Business and Industry", "statement_for_record"),
])
def test_mods_record_entries_are_read_from_their_opening_marker(line, kind):
    assert appearance_records.mods_entry_kind(line, None) == kind


def test_mods_lines_that_name_only_a_contents_entry_are_not_people():
    """A line left holding only a contents label after its name is read ("Prepared statement, dated October 22,
    2015", "Prepared statement on H.R. 841, ...") names an entry of the witness above it, not a person (green-f4)."""
    xml = b"""<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Hearing</title></titleInfo>
      <extension><heldDate>2015-10-22</heldDate>
      <witness>Doe, Hon. Jane, Director, Office of Things</witness>
      <witness>Prepared statement, dated October 22, 2015</witness>
      <witness>Prepared statement on H.R. 841, H.R. 931, and H.R. 1410</witness>
      <witness>Submitted questions \\2\\...................................... Mark Johnson, Senior Environmental Health Scientist</witness>
      <witness>Joint prepared statement with Lieutenant General Thomas P. Bostick, Chief of Engineers, U.S. Army Corps of Engineers</witness>
      </extension></mods>"""
    row = appearance_records.build_appearance_record_row(_sha("mods-entries"), "mods", xml, parser_version="v1", package_id="CHRG-114shrg52553")
    assert [(a["name"], a["witness_type"]) for a in row["appearances"]] == [
        ("Jane Doe", None),
        # A witness's own entries (questions put to them, their joint statement) are the witness (D4 gate).
        ("Mark Johnson", None),
        ("Thomas P. Bostick", None),
    ]


def test_the_lake_table_keeps_each_records_held_dates_title_and_created():
    """The staged table is what the model reads: a print's held dates and title, and a House list's create-date,
    must survive appearance_records.table, not only build_appearance_record_row (D4 published every print as
    package-only because the table dropped them)."""
    mods = b"""<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Haaland Nomination</title></titleInfo>
      <extension><heldDate>2021-02-23</heldDate><witness>Doe, Hon. Jane, Director, Office of Things</witness></extension></mods>"""
    house = b"""<witness-list meeting-id="111420" create-date="2021-04-07T11:07:59.340"></witness-list>"""
    rows = [
        appearance_records.build_appearance_record_row(_sha("mods-table"), "mods", mods, parser_version="v1", package_id="CHRG-117shrg43821"),
        appearance_records.build_appearance_record_row(_sha("house-table"), "house_xml", house, parser_version="v1", event_id=111420),
    ]
    got = {r["source"]: r for r in appearance_records.table(rows).to_pylist()}
    assert (got["mods"]["held_dates"], got["mods"]["title"]) == (["2021-02-23"], "Haaland Nomination")
    assert got["house_xml"]["created"] == rows[1]["created"] and rows[1]["created"] is not None


@pytest.mark.parametrize("line,kind", [
    # D4 gate, witnesses: a witness's own prepared statement or answers mark that they testified.
    ("Coston, James E., Attorney, Chicago, IL, prepared statement", None),
    ("Levin, Gerald M., Chairman, Chief Executive Officer, Time Warner, Inc., prepared statement", None),
    ("Answers to submitted questions \\1\\ Lynn Goldman, M.D., M.P.H., Professor, Johns Hopkins School of Public Health", None),
    ("Written Statement of Ted Willke, Associate Administrator for Hazardous Materials Safety", None),
    # "Letter" inside an organization or title is not a letter.
    ("Mr. Fredric V. Rolando, President, National Association of Letter Carriers", None),
    ("Timm Kopp, Letter Carrier, U.S. Postal Service", None),
    # Statements: a statement only, a letter, a submission, a Member's prepared statement, questions a Member asked.
    ("Bonnie Carroll, Founder and President, Tragedy Assistance Program For Survivors, prepared statement only", "statement_for_record"),
    ("Additional materials supplied: Pautzke, Dr. Clarence, Executive Director, North Pacific Research Board, Statement "
     "submitted for the record", "statement_for_record"),
    ("Steiner, Larry R., Adirondack-Catskill Chapter, Safari Club International, Letter submitted for the record on H.R. 1054", "statement_for_record"),
    ("Rep. Napolitano Submission Napolitano, Hon. Grace F., Letter to Secretary of the Interior, dated August 28, 2009", "statement_for_record"),
    ("Letter dated January 31, 2017 to Michael Flores, President, California Fish and Game Commission", "statement_for_record"),
    ("The Honorable Tom Lantos, a Representative in Congress From the State of California, and Ranking Member Prepared Statement", "member_statement"),
    ("Kingston, Hon. Jack, a Representative in Congress from the State of Georgia, Oral statement of", None),
    ("Statement of Honorable Amy Klobuchar, A United States Senator from the State of Minnesota", None),
    ("Response to posthearing questions submitted by: Hon. Jon Tester", "statement_for_record"),
    ("Responses to questions for the record from the following Representatives: Hon. Andre Carson, of Indiana", "statement_for_record"),
])
def test_a_witnesss_own_entries_are_the_witness_and_submissions_are_statements(line, kind):
    assert appearance_records.mods_entry_kind(line, None) == kind


def test_every_source_version_covers_the_table_write():
    """The staged row is shaped by appearance_records.table as much as by each source's parser: 3fb41ddd changed
    the table write (held_dates, title, created), and rows written null carried the same versions as fixed rows."""
    for source, symbols in appearance_records._SOURCE_SYMBOLS.items():
        missing = {"_EXTRA_COLS", "_normalize_row_for_table", "table", "build_appearance_record_row"} - set(symbols)
        assert not missing, (source, missing)
        assert all(hasattr(appearance_records, name) for name in symbols), source
