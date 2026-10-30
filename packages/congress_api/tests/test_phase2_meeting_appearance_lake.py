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
from congress_api.retention.index.records import DocumentSources, add_retained_house_documents
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.transport import congress as congress_transport

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
    assert m_schema["identifier-field-ids"] == [1, 2]
    m_top_names = [f["name"] for f in m_schema["fields"]]
    assert m_top_names == ["record_sha", "parser_version", "source", "meetings"]

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
    }
    assert meeting_elem_fields["transcript_jackets"]["type"]["element"] == "int"

    assert a_schema["type"] == "struct"
    assert a_schema["identifier-field-ids"] == [1, 2]
    a_top_names = [f["name"] for f in a_schema["fields"]]
    assert a_top_names == ["record_sha", "parser_version", "source", "appearances"]

    appearances_field = next(f for f in a_schema["fields"] if f["name"] == "appearances")
    app_elem_fields = {f["name"]: f for f in appearances_field["type"]["element"]["fields"]}
    assert set(app_elem_fields) == {
        "event_id",
        "package_id",
        "page_url",
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
        "document_urls",
    }
    assert app_elem_fields["name_key"]["required"] is True
    assert app_elem_fields["document_urls"]["required"] is True

    # Verify registration in congress_api.lake.tables
    assert "meeting_records" in tables.TABLE_SPECS
    assert "appearance_records" in tables.TABLE_SPECS
    assert tables.table_spec("meeting_records")["primary_key"] == ("record_sha", "parser_version")
    assert tables.table_spec("appearance_records")["primary_key"] == ("record_sha", "parser_version")
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


def test_house_records_index_strips_hhrg_hmkp_and_hmtg():
    bodies = {}
    capture_rows = []
    for prefix, event_num in (("HHRG", "118001"), ("HMKP", "118002"), ("HMTG", "118003")):
        xml = f'<committee-meeting meeting-id="{prefix}{event_num}" meeting-type="{prefix}"><meeting-details><congress>118</congress></meeting-details></committee-meeting>'.encode("utf-8")
        b_key = f"bodies/sha256/00/{_sha(prefix)}.gz"
        bodies[b_key] = xml
        capture_rows.append(
            {
                "family": "house/meeting-xml",
                "body_key": b_key,
                "context_url": f"https://docs.house.gov/{prefix}{event_num}.xml",
                "http_status": 200,
                "receipt_key": "receipts/house/2026-10-30/r.jsonl.gz",
                "receipt_line": 1,
            }
        )
    captures_tbl = pa.Table.from_pylist(capture_rows)
    seen_events = []

    class _Recorder(DocumentSources):
        def event_context(self, event_id, chamber):
            seen_events.append((event_id, chamber))
            return {}

        def add_house_evidence(self, evidence, values):
            pass

    add_retained_house_documents(_Recorder(), captures_tbl, lambda k: bodies.get(k))
    assert seen_events == [("118001", "house"), ("118002", "house"), ("118003", "house")]


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
  <heading>Oversight of Federal Agencies</heading>
  <meeting-details>
    <congress>118</congress>
    <session>2</session>
    <current-status>Scheduled</current-status>
    <meeting-date>
      <calendar-date>2024-05-10</calendar-date>
      <start-time>10:00:00</start-time>
      <end-time>12:30:00</end-time>
    </meeting-date>
    <capitol-complex-location>
      <room>2141</room>
      <building>Rayburn</building>
    </capitol-complex-location>
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
    assert m["sittings"] == [
        {
            "start": "2024-05-10T10:00:00",
            "end": "2024-05-10T12:30:00",
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


# ---------------------------------------------------------------------------
# 3. `appearance_records` Extraction, Normalization, S2 Fixtures & Anti-Join
# ---------------------------------------------------------------------------


def test_name_key_normalization_and_unnamed_witnesses():
    # NFKC + casefold + punctuation removal + whitespace collapse
    assert appearance_records.compute_name_key("  Dr. María-José   O’Connor, Jr.! ", 1) == "dr maríajosé oconnor jr"
    assert appearance_records.compute_name_key("THE HONORABLE JOHN\tQ.\nPUBLIC", 2) == "the honorable john q public"
    # Unnamed or punctuation-only witnesses get #<1-based-position> so they stay apart
    assert appearance_records.compute_name_key(None, 1) == "#1"
    assert appearance_records.compute_name_key("", 2) == "#2"
    assert appearance_records.compute_name_key(" --- ... ", 3) == "#3"


def test_s2_fixture_1_duplicate_name_key_deduplication_and_unnamed_kept_apart():
    """S2 Fixture 1: Duplicate `name_key` within a single `record_sha` keeps the first
    entry in source order, while multiple unnamed witnesses get distinct `#1`, `#3` keys.
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
      <position>Duplicate Entry Should Be Dropped</position>
      <organization>Agency Y</organization>
    </witness>
  </panel>
</witness-list>"""

    row = appearance_records.build_appearance_record_row(
        _sha("s2-fixture-1"),
        "house_xml",
        house_wlist_xml,
        parser_version="v1",
        source_url="https://docs.house.gov/meetings/JU/JU00/20240510/118999/HHRG-118-JU00-WList-20240510.xml",
    )
    apps = row["appearances"]
    # 4 input witnesses -> 3 kept (unnamed #1, "hon jane m smith", unnamed #3; duplicate "hon jane m smith" dropped)
    assert [a["name_key"] for a in apps] == ["#1", "hon jane m smith", "#3"]
    assert apps[0]["name"] is None
    assert apps[0]["position"] == "Anonymous Whistleblower"
    assert apps[1]["name"] == "Hon. Jane M. Smith"
    assert apps[1]["position"] == "Administrator"
    assert apps[1]["bioguide_id"] == "S000148"
    assert apps[1]["testified"] is True
    assert apps[1]["document_urls"] == ["https://docs.house.gov/118/HHRG-118-WTTF-Smith.pdf"]
    assert apps[2]["name"] is None
    assert apps[2]["position"] == "Second Unnamed Witness"


def test_s2_fixture_2_empty_witness_and_meeting_rows_retained_for_anti_join():
    """S2 Fixture 2: An input verified to have zero witnesses or zero meetings still emits
    a row with `appearances = []` or `meetings = []`, and the anti-join on
    `(record_sha, parser_version)` skips it on subsequent runs unless `parser_version` bumps.
    """
    empty_wlist_xml = b'<?xml version="1.0"?><witness-list meeting-id="HHRG118000"></witness-list>'
    sha_empty = _sha("s2-empty-wlist")

    parse_calls = 0
    orig_extract = appearance_records.extract_house_xml_appearances

    def counted_extract(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        return orig_extract(*args, **kwargs)

    inputs = [{"record_sha": sha_empty, "source": "house_xml", "payload": empty_wlist_xml}]

    # First run parses the empty witness list and emits a row with appearances = []
    first_table = appearance_records.produce_appearance_records(inputs, parser_version="v1")
    assert first_table.num_rows == 1
    row_dict = first_table.to_pylist()[0]
    assert row_dict == {
        "record_sha": sha_empty,
        "parser_version": "v1",
        "source": "house_xml",
        "appearances": [],
    }

    # Second run at the same parser_version skips via anti-join before touching payload
    bad_inputs = [{"record_sha": sha_empty, "source": "house_xml", "payload": b"should-not-be-read"}]
    second_table = appearance_records.produce_appearance_records(
        bad_inputs, existing=first_table, parser_version="v1"
    )
    assert second_table.num_rows == 0

    # Bumping parser_version to "v2" re-runs the input
    third_table = appearance_records.produce_appearance_records(
        inputs, existing=first_table, parser_version="v2"
    )
    assert third_table.num_rows == 1
    assert third_table.to_pylist()[0]["parser_version"] == "v2"

    # Also verify meeting_records emits meetings = [] and skips on unchanged rerun
    empty_meeting_sha = _sha("s2-empty-meeting")
    m_inputs = [{"record_sha": empty_meeting_sha, "source": "congress_gov", "payload": b"{}"}]
    m_first = meeting_records.produce_meeting_records(m_inputs, parser_version="v1")
    assert m_first.num_rows == 1
    assert m_first.to_pylist()[0]["meetings"] == []
    m_second = meeting_records.produce_meeting_records(m_inputs, existing=m_first, parser_version="v1")
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
    assert [a["name_key"] for a in cg_row["appearances"]] == ["the honorable janet yellen", "#2"]
    assert cg_row["appearances"][0]["event_id"] == "116010"
    assert cg_row["appearances"][0]["position"] == "Secretary of the Treasury"
    assert cg_row["appearances"][0]["document_urls"] == []

    # 2. senate_page (with card-scoped testimony links resolved against page_url)
    senate_html = """
    <html><body>
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
    senate_url = "https://www.banking.senate.gov/hearings/nomination-hearing"
    senate_row = appearance_records.build_appearance_record_row(
        _sha("senate-app"),
        "senate_page",
        senate_html,
        parser_version="v1",
        source_url=senate_url,
    )
    assert len(senate_row["appearances"]) == 1
    s_app = senate_row["appearances"][0]
    assert s_app["page_url"] == senate_url
    assert s_app["name_key"] == "saule t omarova"
    assert s_app["position"] == "Professor of Law"
    assert s_app["organization"] == "Cornell Law School"
    assert s_app["document_urls"] == ["https://www.banking.senate.gov/imo/media/doc/Omarova_Testimony.pdf"]

    # 3. mods (GovInfo MODS XML with witness lines and member bioguideId)
    mods_fixture = ROOT / "packages/congress_api/tests/fixtures/gpo_metadata/CHRG-113hhrg21122.xml"
    mods_bytes = mods_fixture.read_bytes()
    mods_row = appearance_records.build_appearance_record_row(
        _sha("mods-app"),
        "mods",
        mods_bytes,
        parser_version="v1",
        source_url="https://www.govinfo.gov/metadata/pkg/CHRG-113hhrg21122/mods.xml",
    )
    assert mods_row["source"] == "mods"
    assert len(mods_row["appearances"]) >= 1
    assert all(a["package_id"] == "CHRG-113hhrg21122" for a in mods_row["appearances"])
    assert all(a["document_urls"] == [] for a in mods_row["appearances"])

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
