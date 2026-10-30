"""Lake producer and parsers for `meeting_records` (Phase 2 Track D4).

Extracts normalized `meeting_records` rows from:
- `congress_gov`: Congress.gov `/v3/committee-meeting` detail JSON/XML bodies and inline
  `congress/meetings` receipt records (`CommitteeMeeting`).
- `house_xml`: `docs.house.gov` `<committee-meeting>` XML bodies (`HouseMeetingXML`),
  stripping all three House meeting-ID prefixes (`HHRG`, `HMKP`, `HMTG`).

An input that parses cleanly to zero meetings still emits a row with `meetings = []`
so the anti-join on `(record_sha, parser_version)` never re-parses it on future runs.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..models.congress import CommitteeMeeting, MeetingResponse, MeetingsPage, parse_response
from ..parsers.congress import meeting_from_xml, parse_congress_xml
from ..parsers.house_documents import active, value
from ..parsers.house_xml import (
    HOUSE_MEETING_PREFIXES,
    HouseMeetingXML,
    parse_house_meeting,
    strip_house_meeting_prefix,
)
from ..parsers.media import recording_reference, youtube_video_id
from ..parsers.senate_player import parse_player_url
from .versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/meeting-records.schema.json"
PK = ["record_sha", "parser_version"]

VALID_SOURCES = frozenset({"congress_gov", "house_xml"})

# House select/permanent committees that use `hl` rather than `hs` in 6-char system codes
_HOUSE_SELECT_CODES = frozenset({"ig", "vc", "fd", "qj"})

SITTING_STRUCT = pa.struct(
    [
        pa.field("start", pa.string(), nullable=True),
        pa.field("end", pa.string(), nullable=True),
        pa.field("room", pa.string(), nullable=True),
        pa.field("building", pa.string(), nullable=True),
        pa.field("address", pa.string(), nullable=True),
    ]
)

COMMITTEE_STRUCT = pa.struct(
    [
        pa.field("system_code", pa.string(), nullable=True),
        pa.field("name", pa.string(), nullable=True),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("role", pa.string(), nullable=True),
    ]
)

VIDEO_STRUCT = pa.struct(
    [
        pa.field("video_key", pa.string(), nullable=True),
        pa.field("url", pa.string(), nullable=True),
        pa.field("title", pa.string(), nullable=True),
    ]
)

MEETING_STRUCT = pa.struct(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("chamber", pa.string(), nullable=True),
        pa.field("congress", pa.int32(), nullable=True),
        pa.field("session", pa.int32(), nullable=True),
        pa.field("updated", pa.string(), nullable=True),
        pa.field("title", pa.string(), nullable=True),
        pa.field("meeting_date", pa.string(), nullable=True),
        pa.field("meeting_type", pa.string(), nullable=True),
        pa.field("status", pa.string(), nullable=True),
        pa.field("sittings", pa.list_(pa.field("element", SITTING_STRUCT, nullable=False)), nullable=False),
        pa.field("committees", pa.list_(pa.field("element", COMMITTEE_STRUCT, nullable=False)), nullable=False),
        pa.field("subject_keys", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=False),
        pa.field("transcript_jackets", pa.list_(pa.field("element", pa.int32(), nullable=False)), nullable=False),
        pa.field("videos", pa.list_(pa.field("element", VIDEO_STRUCT, nullable=False)), nullable=False),
    ]
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("record_sha", pa.string(), nullable=False),
        pa.field("parser_version", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("meetings", pa.list_(pa.field("element", MEETING_STRUCT, nullable=False)), nullable=False),
    ]
)
SCHEMA = ARROW_SCHEMA


def current_version(*, root: Path = ROOT) -> str:
    root = Path(root)
    pkg_dir = Path(__file__).resolve().parents[1]
    return version_digest(
        packages={},
        files={
            "producer": Path(__file__),
            "models_congress": pkg_dir / "models/congress.py",
            "parsers_congress": pkg_dir / "parsers/congress.py",
            "parsers_house_xml": pkg_dir / "parsers/house_xml.py",
            "parsers_house_documents": pkg_dir / "parsers/house_documents.py",
            "parsers_media": pkg_dir / "parsers/media.py",
            "parsers_senate_player": pkg_dir / "parsers/senate_player.py",
            "lock": root / "uv.lock",
            "lake_schema": root / "model/lake/meeting-records.schema.json",
        },
        values={"prefixes": list(HOUSE_MEETING_PREFIXES)},
    )


DEFAULT_PARSER_VERSION = "meeting-records-v1"


def normalize_record_sha(value: str | bytes) -> str:
    """Normalize a SHA-256 record identifier to a 64-character lowercase hex string."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 32:
            return raw.hex()
        text = raw.decode("ascii").strip().lower()
    elif isinstance(value, str):
        text = value.strip().lower()
    else:
        raise TypeError(f"Unsupported record_sha type: {type(value)!r}")
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"Invalid SHA-256 hex digest: {value!r}")
    return text


def normalize_chamber(value: str | None) -> str | None:
    """Map source chamber values through [[DATA-MODEL]] §3 (`house`, `senate`, `joint`, or None)."""
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in ("house", "h", "house of representatives"):
        return "house"
    if cleaned in ("senate", "s"):
        return "senate"
    if cleaned in ("joint", "j"):
        return "joint"
    if cleaned in ("nochamber", "no chamber", "none", ""):
        return None
    return None


def normalize_house_committee_code(code: str | None) -> str | None:
    """Normalize a House XML committee code (e.g. `RU00`, `PW02`, `IG00`, `hsru00`) to 6-char lowercase."""
    if not code:
        return None
    cleaned = code.strip().lower()
    if not cleaned:
        return None
    if re.fullmatch(r"[hsj][a-z]{3}[0-9]{2}", cleaned):
        return cleaned
    if re.fullmatch(r"[a-z]{2}[0-9]{2}", cleaned):
        prefix = "hl" if cleaned[:2] in _HOUSE_SELECT_CODES else "hs"
        return f"{prefix}{cleaned}"
    if re.fullmatch(r"[a-z]{2}", cleaned):
        prefix = "hl" if cleaned in _HOUSE_SELECT_CODES else "hs"
        return f"{prefix}{cleaned}00"
    return cleaned


def format_subject_key_bill(congress: int | str | None, bill_type: str | None, number: int | str | None) -> str | None:
    """Format `{congress}-{type}-{number}` in lowercase (`116-s-1102`, `118-hr-1`)."""
    if congress is None or not bill_type or number is None:
        return None
    try:
        cong_int = int(str(congress).strip())
    except ValueError:
        return None
    btype = re.sub(r"[^a-z0-9]", "", str(bill_type).strip().lower())
    num_str = str(number).strip()
    if not btype or not num_str:
        return None
    if num_str.isdigit():
        num_str = str(int(num_str))
    return f"{cong_int}-{btype}-{num_str.lower()}"


def format_subject_key_nomination(
    congress: int | str | None, number: int | str | None, part: str | int | None = None
) -> str | None:
    """Format `{congress}-pn-{number}` or `{congress}-pn-{number}-{int(part)}` per Phase-2 Annex §2.

    Examples:
    - `PN730-2` (or `number=730, part='02'`) -> `119-pn-730-2`
    - `number=78, part='20'` -> `117-pn-78-20`
    - `number=5, part='00'` -> `116-pn-5`
    """
    if congress is None or number is None:
        return None
    try:
        cong_int = int(str(congress).strip())
    except ValueError:
        return None
    raw_num = str(number).strip()
    if not raw_num:
        return None
    if raw_num.upper().startswith("PN"):
        raw_num = raw_num[2:].strip()
    if "-" in raw_num and (part is None or str(part).strip() == ""):
        raw_num, part = raw_num.split("-", 1)
    num_clean = str(int(raw_num)) if raw_num.isdigit() else raw_num.lower()
    if not num_clean:
        return None
    if part is not None:
        part_str = str(part).strip()
        if part_str and part_str.isdigit():
            part_int = int(part_str)
            if part_int > 0:
                return f"{cong_int}-pn-{num_clean}-{part_int}"
        elif part_str and part_str not in ("0", "00"):
            return f"{cong_int}-pn-{num_clean}-{part_str.lower()}"
    return f"{cong_int}-pn-{num_clean}"


def format_subject_key_treaty(congress: int | str | None, number: int | str | None) -> str | None:
    """Format `{congress}-treaty-{number}` (`114-treaty-1`)."""
    if congress is None or number is None:
        return None
    try:
        cong_int = int(str(congress).strip())
    except ValueError:
        return None
    num_str = str(number).strip()
    if not num_str:
        return None
    if num_str.isdigit():
        num_str = str(int(num_str))
    return f"{cong_int}-treaty-{num_str.lower()}"


def extract_video_key(url: str | None) -> str | None:
    """Derive `video_key` (`youtube:{id}` or `senate:{filename}`) from a meeting video URL."""
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    yt_id = youtube_video_id(cleaned)
    if yt_id:
        return f"youtube:{yt_id}"
    senate = parse_player_url(cleaned)
    if senate:
        _, filename = senate
        return f"senate:{filename}"
    ref = recording_reference({"url": cleaned})
    if ref:
        kind, ident = ref
        return f"{kind}:{ident}"
    return None


def _convert_congress_meeting_dict(m: Mapping[str, Any]) -> dict[str, Any]:
    event_id = str(m.get("eventId") or m.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("Congress.gov CommitteeMeeting lacks eventId")

    chamber = normalize_chamber(m.get("chamber"))
    raw_cong = m.get("congress")
    congress = int(raw_cong) if raw_cong is not None and str(raw_cong).strip().isdigit() else None
    raw_upd = m.get("updateDate")
    updated = str(raw_upd).strip() if raw_upd and str(raw_upd).strip() else None
    raw_title = m.get("title")
    title = str(raw_title).strip() if raw_title and str(raw_title).strip() else None
    raw_date = m.get("date")
    date_str = str(raw_date).strip() if raw_date and str(raw_date).strip() else None
    meeting_date = date_str[:10] if date_str and len(date_str) >= 10 else date_str
    raw_type = m.get("type")
    meeting_type = str(raw_type).strip() if raw_type and str(raw_type).strip() else None
    raw_status = m.get("meetingStatus") or m.get("status")
    status = str(raw_status).strip() if raw_status and str(raw_status).strip() else None

    sittings: list[dict[str, str | None]] = []
    loc = m.get("location") if isinstance(m.get("location"), Mapping) else None
    room = str(loc.get("room")).strip() if loc and loc.get("room") and str(loc.get("room")).strip() else None
    building = str(loc.get("building")).strip() if loc and loc.get("building") and str(loc.get("building")).strip() else None
    addr = None
    if loc and isinstance(loc.get("address"), Mapping):
        addr_map = loc["address"]
        parts = [
            str(addr_map.get(k)).strip()
            for k in ("buildingName", "streetAddress", "city", "state", "zipCode")
            if addr_map.get(k) and str(addr_map.get(k)).strip()
        ]
        if parts:
            addr = ", ".join(parts)
    if date_str or room or building or addr:
        sittings.append(
            {
                "start": date_str,
                "end": None,
                "room": room,
                "building": building,
                "address": addr,
            }
        )
    for cont in m.get("continuations") or []:
        if isinstance(cont, Mapping):
            c_date = str(cont.get("continuationDate") or "").strip() or None
            if c_date:
                sittings.append(
                    {
                        "start": c_date,
                        "end": None,
                        "room": room,
                        "building": building,
                        "address": addr,
                    }
                )

    committees: list[dict[str, str | None]] = []
    for comm in m.get("committees") or []:
        if not isinstance(comm, Mapping):
            continue
        raw_sc = comm.get("systemCode") or comm.get("system_code")
        sys_code = str(raw_sc).strip().lower() if raw_sc and str(raw_sc).strip() else None
        c_chamber = normalize_chamber(comm.get("chamber"))
        if c_chamber is None and sys_code:
            c_chamber = {"h": "house", "s": "senate", "j": "joint"}.get(sys_code[:1])
        raw_cname = comm.get("name")
        committees.append(
            {
                "system_code": sys_code,
                "name": str(raw_cname).strip() if raw_cname and str(raw_cname).strip() else None,
                "chamber": c_chamber,
                "role": None,
            }
        )

    subject_keys: list[str] = []
    seen_subjects: set[str] = set()
    rel = m.get("relatedItems")
    if isinstance(rel, Mapping):
        for bill in rel.get("bills") or []:
            if isinstance(bill, Mapping):
                key = format_subject_key_bill(bill.get("congress") or congress, bill.get("type"), bill.get("number"))
                if key and key not in seen_subjects:
                    seen_subjects.add(key)
                    subject_keys.append(key)
        for nom in rel.get("nominations") or []:
            if isinstance(nom, Mapping):
                key = format_subject_key_nomination(nom.get("congress") or congress, nom.get("number"), nom.get("part"))
                if key and key not in seen_subjects:
                    seen_subjects.add(key)
                    subject_keys.append(key)
        for treaty in rel.get("treaties") or []:
            if isinstance(treaty, Mapping):
                key = format_subject_key_treaty(treaty.get("congress") or congress, treaty.get("number"))
                if key and key not in seen_subjects:
                    seen_subjects.add(key)
                    subject_keys.append(key)

    jackets: list[int] = []
    seen_jackets: set[int] = set()
    for ht in m.get("hearingTranscript") or []:
        if isinstance(ht, Mapping):
            raw_jacket = str(ht.get("jacketNumber") or "").strip()
            if raw_jacket:
                digits = re.sub(r"[^0-9]", "", raw_jacket)
                if digits:
                    j_val = int(digits)
                    if j_val not in seen_jackets:
                        seen_jackets.add(j_val)
                        jackets.append(j_val)

    videos: list[dict[str, str | None]] = []
    for vid in m.get("videos") or []:
        if isinstance(vid, Mapping):
            raw_vurl = vid.get("url")
            v_url = str(raw_vurl).strip() if raw_vurl and str(raw_vurl).strip() else None
            raw_vname = vid.get("name") or vid.get("title")
            v_title = str(raw_vname).strip() if raw_vname and str(raw_vname).strip() else None
            v_key = extract_video_key(v_url)
            if v_key or v_url or v_title:
                videos.append(
                    {
                        "video_key": v_key,
                        "url": v_url,
                        "title": v_title,
                    }
                )

    return {
        "event_id": event_id,
        "chamber": chamber,
        "congress": congress,
        "session": None,
        "updated": updated,
        "title": title,
        "meeting_date": meeting_date,
        "meeting_type": meeting_type,
        "status": status,
        "sittings": sittings,
        "committees": committees,
        "subject_keys": subject_keys,
        "transcript_jackets": jackets,
        "videos": videos,
    }


def _convert_congress_meeting(meeting: CommitteeMeeting) -> dict[str, Any]:
    return _convert_congress_meeting_dict(meeting.source_dict())


def extract_congress_gov_meetings(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
) -> list[dict[str, Any]]:
    """Extract normalized meeting structs from a Congress.gov body or inline receipt record."""
    if isinstance(payload, CommitteeMeeting):
        return [_convert_congress_meeting(payload)]

    if isinstance(payload, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(payload).strip()
        if not raw_bytes:
            return []
        if raw_bytes.startswith(b"<"):
            root = parse_congress_xml(raw_bytes)
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                return [_convert_congress_meeting(meeting_from_xml(root))]
            return []
        data = json.loads(raw_bytes.decode("utf-8"))
    elif isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        if text.startswith("<"):
            root = parse_congress_xml(text.encode("utf-8"))
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                return [_convert_congress_meeting(meeting_from_xml(root))]
            return []
        data = json.loads(text)
    elif isinstance(payload, Mapping):
        data = dict(payload)
    else:
        raise TypeError(f"Unsupported congress_gov payload type: {type(payload)!r}")

    if not data:
        return []

    # Unwrap inline receipt wrapper if present (`{"record": {...}}` or `{"payload": {...}}`)
    if "committeeMeeting" not in data and "eventId" not in data and "committeeMeetings" not in data:
        for wrapper_key in ("record", "payload", "body", "data"):
            inner = data.get(wrapper_key)
            if isinstance(inner, Mapping):
                data = dict(inner)
                break
        else:
            if isinstance(data.get("_source_xml"), Mapping):
                from ..retention.body_files import content_bytes

                return extract_congress_gov_meetings(content_bytes(data["_source_xml"]))
            return []

    if "committeeMeeting" in data:
        inner = data["committeeMeeting"]
        if isinstance(inner, Mapping) and (inner.get("eventId") or inner.get("event_id")):
            return [_convert_congress_meeting_dict(inner)]
        return []

    if "eventId" in data or "event_id" in data:
        return [_convert_congress_meeting_dict(data)]

    if "committeeMeetings" in data:
        items = data.get("committeeMeetings") or []
        out: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, Mapping) and (item.get("eventId") or item.get("event_id")) and any(
                k in item for k in ("title", "date", "committees", "meetingStatus", "type", "videos", "witnesses")
            ):
                out.append(_convert_congress_meeting_dict(item))
        return out

    return []


_HOUSE_BILL_RE = re.compile(
    r"\b(H\.\s*R\.|S\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.|H\.\s*Con\.\s*Res\.|S\.\s*Con\.\s*Res\.|H\.\s*Res\.|S\.\s*Res\.)\s*([0-9]+)\b",
    re.IGNORECASE,
)


def extract_house_xml_meetings(payload: bytes | str | HouseMeetingXML) -> list[dict[str, Any]]:
    """Extract normalized meeting structs from a `docs.house.gov` `<committee-meeting>` XML body."""
    if isinstance(payload, HouseMeetingXML):
        root = payload
    else:
        raw_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        if not raw_bytes.strip():
            return []
        try:
            root = parse_house_meeting(raw_bytes)
        except (ET.ParseError, ValueError):
            # If the XML is a `<witness-list>` or another non-meeting XML root, it has 0 meetings.
            return []

    if root.tag != "committee-meeting" or not active(root):
        return []

    raw_id = (root.get("meeting-id") or "").strip()
    event_id = strip_house_meeting_prefix(raw_id)
    if not event_id:
        raise ValueError(f"House XML committee-meeting lacks a valid meeting-id: {raw_id!r}")

    details = root.find("meeting-details")
    congress: int | None = None
    session: int | None = None
    meeting_date: str | None = None
    start_ts: str | None = None
    end_ts: str | None = None
    room: str | None = None
    building: str | None = None
    address: str | None = None
    committees: list[dict[str, str | None]] = []

    if details is not None:
        cong_elem = details.find("congress")
        if cong_elem is not None and cong_elem.text and cong_elem.text.strip().isdigit():
            congress = int(cong_elem.text.strip())
        sess_elem = details.find("session")
        if sess_elem is not None and sess_elem.text and sess_elem.text.strip().isdigit():
            session = int(sess_elem.text.strip())

        m_date = details.find("meeting-date")
        if m_date is not None:
            cal = value(m_date, "calendar-date") or None
            s_time = value(m_date, "start-time") or None
            e_time = value(m_date, "end-time") or None
            meeting_date = cal
            if cal and s_time:
                start_ts = f"{cal}T{s_time}"
            elif cal:
                start_ts = cal
            if cal and e_time:
                end_ts = f"{cal}T{e_time}"

        cap_loc = details.find("capitol-complex-location")
        if cap_loc is not None:
            room = value(cap_loc, "room") or None
            building = value(cap_loc, "building") or None

        field_loc = details.find("field-location")
        if field_loc is not None:
            if not building:
                building = value(field_loc, "building-name") or None
            addr_parts = [
                value(field_loc, tag)
                for tag in ("building-name", "street-address", "city", "state", "zip")
            ]
            addr_parts = [p for p in addr_parts if p]
            if addr_parts:
                address = ", ".join(addr_parts)

        comms_elem = details.find("committees")
        if comms_elem is not None:
            for c_elem in comms_elem.findall("committee-name"):
                c_id = normalize_house_committee_code(c_elem.get("id"))
                c_name = (c_elem.text or "").strip() or None
                c_chamber = "joint" if (c_id and c_id.startswith("j")) else "house"
                committees.append(
                    {
                        "system_code": c_id,
                        "name": c_name,
                        "chamber": c_chamber,
                        "role": "host",
                    }
                )
        subcomms_elem = details.find("subcommittees")
        if subcomms_elem is not None:
            for sc_elem in subcomms_elem.findall("committee-name"):
                sc_id = normalize_house_committee_code(sc_elem.get("id"))
                sc_name = (sc_elem.text or "").strip() or None
                sc_chamber = "joint" if (sc_id and sc_id.startswith("j")) else "house"
                committees.append(
                    {
                        "system_code": sc_id,
                        "name": sc_name,
                        "chamber": sc_chamber,
                        "role": "subcommittee",
                    }
                )

    sittings: list[dict[str, str | None]] = []
    if start_ts or end_ts or room or building or address:
        sittings.append(
            {
                "start": start_ts,
                "end": end_ts,
                "room": room,
                "building": building,
                "address": address,
            }
        )

    subject_keys: list[str] = []
    seen_subjects: set[str] = set()
    if congress is not None:
        docs_elem = root.find("meeting-documents")
        if docs_elem is not None:
            for grp in docs_elem.findall("meeting-document-group"):
                if not active(grp):
                    continue
                for doc in grp.findall("meeting-document"):
                    if not active(doc):
                        continue
                    legis_num = value(doc, "legis-num")
                    desc = value(doc, "description")
                    for candidate in (legis_num, desc):
                        if not candidate:
                            continue
                        for match in _HOUSE_BILL_RE.finditer(candidate):
                            b_key = format_subject_key_bill(congress, match.group(1), match.group(2))
                            if b_key and b_key not in seen_subjects:
                                seen_subjects.add(b_key)
                                subject_keys.append(b_key)

    chamber = "joint" if any(c["chamber"] == "joint" for c in committees) else "house"
    updated = (root.get("update-date") or "").strip() or None
    title = value(root, " Descriptive-Name") or value(root, "heading") or None
    meeting_type = (root.get("meeting-type") or "").strip() or None
    current_status = value(details, "current-status") if details is not None else ""
    status = current_status or None

    return [
        {
            "event_id": event_id,
            "chamber": chamber,
            "congress": congress,
            "session": session,
            "updated": updated,
            "title": title,
            "meeting_date": meeting_date,
            "meeting_type": meeting_type,
            "status": status,
            "sittings": sittings,
            "committees": committees,
            "subject_keys": subject_keys,
            "transcript_jackets": [],
            "videos": [],
        }
    ]


def build_meeting_record_row(
    record_sha: str | bytes,
    source: str,
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting | HouseMeetingXML,
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> dict[str, Any]:
    """Parse one `congress_gov` or `house_xml` input into a `meeting_records` lake row."""
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported meeting_records source {source!r}; expected one of {sorted(VALID_SOURCES)}")
    sha_hex = normalize_record_sha(record_sha)
    if source == "congress_gov":
        meetings = extract_congress_gov_meetings(payload)
    else:
        meetings = extract_house_xml_meetings(payload)
    return {
        "record_sha": sha_hex,
        "parser_version": str(parser_version),
        "source": source,
        "meetings": meetings,
    }


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    """Convert `meeting_records` row dicts into a sorted PyArrow Table conforming to `ARROW_SCHEMA`."""
    normalized = [
        {
            "record_sha": normalize_record_sha(r["record_sha"]),
            "parser_version": str(r["parser_version"]),
            "source": str(r["source"]),
            "meetings": list(r.get("meetings") or []),
        }
        for r in rows
    ]
    normalized.sort(key=lambda r: (r["record_sha"], r["parser_version"]))
    if not normalized:
        return pa.Table.from_pylist([], schema=ARROW_SCHEMA)
    return pa.Table.from_pylist(normalized, schema=ARROW_SCHEMA)


def filter_unprocessed_inputs(
    inputs: Iterable[Mapping[str, Any]],
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, parser_version)` before parsing payloads."""
    existing_keys: set[tuple[str, str]] = set()
    if existing is not None:
        if isinstance(existing, pa.Table):
            for row in existing.select(["record_sha", "parser_version"]).to_pylist():
                existing_keys.add((normalize_record_sha(row["record_sha"]), str(row["parser_version"])))
        else:
            for row in existing:
                existing_keys.add((normalize_record_sha(row["record_sha"]), str(row["parser_version"])))

    pending: list[dict[str, Any]] = []
    seen_in_batch: set[tuple[str, str]] = set()
    for item in inputs:
        sha_hex = normalize_record_sha(item["record_sha"])
        ver = str(item.get("parser_version") or parser_version)
        key = (sha_hex, ver)
        if key in existing_keys or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        pending.append({**item, "record_sha": sha_hex, "parser_version": ver})
    return pending


def produce_meeting_records(
    inputs: Iterable[Mapping[str, Any]],
    *,
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> pa.Table:
    """Incrementally parse only unprocessed `(record_sha, parser_version)` inputs into a PyArrow Table."""
    todo = filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)
    rows = [
        build_meeting_record_row(
            item["record_sha"],
            item["source"],
            item["payload"],
            parser_version=item["parser_version"],
        )
        for item in todo
    ]
    return table(rows)


CANDIDATE_HOUSE_XML_SQL = """
SELECT encode(r.body_sha, 'hex') AS sha
FROM readings r
WHERE r.parser='xml' AND r.status='completed' AND r.xml_root='committee-meeting'
GROUP BY r.body_sha
""".strip()


def query_candidate_house_xml(*, engine: Any, work: Path, captures: Any, readings: Any) -> list[dict[str, Any]]:
    """Query `readings` via the native engine for `<committee-meeting>` XML body SHAs."""
    from ..retention.provenance import run_job
    from .tables import table_input

    res = run_job(
        Path(work),
        engine,
        inputs=[table_input("captures", captures), table_input("readings", readings)],
        steps=[],
        outputs=[],
        queries=[{"name": "house_cm", "sql": CANDIDATE_HOUSE_XML_SQL}],
    )
    return list(res["house_cm"])


def _read_candidate_body(record_sha: str, stored_suffix: str, *, local_root: Path | None, raw_store: Any) -> bytes:
    import gzip as _gzip

    suffix = stored_suffix if stored_suffix is not None else ".gz"
    rel_candidates = [f"bodies/sha256/{record_sha[:2]}/{record_sha}{suffix}"]
    if suffix != ".gz":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}.gz")
    if suffix != "":
        rel_candidates.append(f"bodies/sha256/{record_sha[:2]}/{record_sha}")

    raw_bytes: bytes | None = None
    if local_root is not None:
        base = Path(local_root)
        for rel in rel_candidates:
            candidate = base / rel
            if candidate.is_file():
                raw_bytes = candidate.read_bytes()
                break
    if raw_bytes is None and raw_store is not None:
        adapter = getattr(raw_store, "adapter", None)
        adapter_root = getattr(adapter, "root", None)
        if adapter_root is not None:
            for rel in rel_candidates:
                candidate = Path(adapter_root) / rel
                if candidate.is_file():
                    raw_bytes = candidate.read_bytes()
                    break
        elif hasattr(adapter, "client") and hasattr(adapter, "bucket"):
            for rel in rel_candidates:
                try:
                    resp = adapter.client.get_object(Bucket=adapter.bucket, Key=rel)
                    body = resp["Body"]
                    raw_bytes = body.read() if hasattr(body, "read") else bytes(body)
                    break
                except Exception:
                    continue
    if raw_bytes is None:
        raise FileNotFoundError(f"Missing raw body for record_sha={record_sha}")
    if raw_bytes[:2] == b"\x1f\x8b":
        return _gzip.decompress(raw_bytes)
    return raw_bytes


def stage(
    *,
    captures: Any,
    engine: Any,
    work: Path,
    existing: Any = None,
    local_root: Path | str | None = None,
    raw_store: Any = None,
    unreadable_files: Sequence[Mapping[str, Any]] = (),
    parser_version: str | None = None,
) -> dict[str, Any]:
    """Stage missing `meeting_records` rows from `captures` via native anti-join."""
    from ..retention.provenance import field, json_input, parquet_output, run_job
    from .tables import table_input

    version = current_version() if parser_version is None else str(parser_version)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)

    inputs: list[dict[str, Any]] = [table_input("captures", captures)]
    unreadable_schema = dict(
        fields=[field(name, "Utf8") for name in ("id", "record_sha", "parser", "parser_version", "supersedes")],
        metadata={},
    )
    if unreadable_files:
        inputs.append(dict(name="unreadable", kind="json_lines", files=list(unreadable_files), schema=unreadable_schema))
    else:
        inputs.append(
            json_input(
                work,
                "unreadable",
                [],
                id="Utf8",
                record_sha="Utf8",
                parser="Utf8",
                parser_version="Utf8",
                supersedes="Utf8",
            )
        )
    if existing is not None:
        inputs.append(table_input("existing", existing))

    candidate_sql = """SELECT encode(sha256, 'hex') AS record_sha,
        max(coalesce(stored_suffix, '.gz')) AS stored_suffix,
        max(coalesce(url, requested_url, context_url, '')) AS source_url,
        CASE
            WHEN bool_or(family = 'congress/meetings'
                OR coalesce(url, requested_url, '') ILIKE '%api.congress.gov%/committee-meeting%'
                OR coalesce(url, requested_url, '') ILIKE '%congress.gov/committee-meeting%') THEN 'congress_gov'
            WHEN bool_or(family IN ('house/meeting-xml', 'house/witness-xml')
                OR (coalesce(url, requested_url, context_url, '') ILIKE '%docs.house.gov%'
                    AND (coalesce(url, requested_url, '') ILIKE '%.xml%' OR sniffed_format = 'xml'))) THEN 'house_xml'
        END AS source
        FROM captures
        WHERE sha256 IS NOT NULL AND coalesce(complete, true) AND coalesce(http_status, 200) BETWEEN 200 AND 299
        GROUP BY sha256"""

    version_sql = "'" + version.replace("'", "''") + "'"
    missing = (
        " WHERE c.source IS NOT NULL AND NOT EXISTS (SELECT 1 FROM unreadable u "
        "WHERE u.record_sha=c.record_sha AND u.parser='meeting_records' AND u.parser_version="
        + version_sql
        + " AND NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id))"
    )
    if existing is not None:
        missing += (
            " AND NOT EXISTS (SELECT 1 FROM existing e WHERE e.record_sha=c.record_sha "
            "AND e.parser_version=" + version_sql + ")"
        )

    run_job(
        work,
        engine,
        inputs=inputs,
        steps=[dict(name="candidates", sql=candidate_sql)],
        outputs=[parquet_output(work, "work-list", "SELECT c.* FROM candidates c" + missing, ["record_sha"])],
    )

    work_list_path = work / "work-list.parquet"
    work_items = pq.read_table(work_list_path).to_pylist()
    local_root_path = Path(local_root) if local_root is not None else None
    to_parse: list[dict[str, Any]] = []
    for item in work_items:
        payload_bytes = _read_candidate_body(
            item["record_sha"],
            item.get("stored_suffix") or ".gz",
            local_root=local_root_path,
            raw_store=raw_store,
        )
        to_parse.append(
            {
                "record_sha": item["record_sha"],
                "source": item["source"],
                "payload": payload_bytes,
                "parser_version": version,
            }
        )

    produced_table = produce_meeting_records(to_parse, parser_version=version)
    out_path = work / "meeting-records.parquet"
    pq.write_table(produced_table, out_path)
    return dict(
        records=out_path,
        work_list=work_list_path,
        work_items=len(work_items),
        produced=produced_table.num_rows,
        parser_version=version,
        unreadable_pending=False,
        unreadable_provenance=None,
    )


def create_table(*, engine: Any, work: Path, catalog_root: Path | None, table: dict[str, Any], location: str, create_namespace: bool = False) -> Any:
    from .tables import create_table as native_create

    return native_create(
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        schema=json.loads(TABLE_SCHEMA.read_text()),
        location=location,
        create_namespace=create_namespace,
    )


def append(staged_parquet: Path | Mapping[str, Any], *, engine: Any, work: Path, catalog_root: Path | None, table: dict[str, Any], parser_version: str | None = None) -> Any:
    from .tables import append_rows

    if isinstance(staged_parquet, Mapping):
        if staged_parquet.get("unreadable_pending"):
            raise ValueError("Pending unreadable decisions require durable import")
        resolved_version = str(staged_parquet.get("parser_version") or parser_version or current_version())
        source_path = Path(staged_parquet["records"])
    else:
        resolved_version = str(parser_version or DEFAULT_PARSER_VERSION)
        source_path = Path(staged_parquet)

    return append_rows(
        source_path,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        keys=PK,
        definition=f"meeting_records:{resolved_version}",
    )
