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

from functools import lru_cache
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa

from ..models.congress import CommitteeMeeting
from ..parsers.house_documents import active, value
from ..parsers.house_xml import (
    HOUSE_MEETING_PREFIXES,
    HouseMeetingXML,
    parse_house_meeting,
    strip_house_meeting_prefix,
)
from ..parsers.media import recording_reference, youtube_video_id
from ..parsers.senate_player import parse_player_url
from ._record_producer import (
    INLINE_CONGRESS_MEETINGS_SQL,
    PK,
    _is_missing_key_error,
    _read_candidate_body,
    _read_receipt_lines,
    append_record_table,
    build_record_table,
    create_record_table,
    filter_unprocessed_inputs as _shared_filter_unprocessed_inputs,
    normalize_record_sha,
    stage_record_table,
    unwrap_congress_gov_payload,
)
from .versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/meeting-records.schema.json"

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
            "record_producer": pkg_dir / "lake/_record_producer.py",
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


def extract_congress_gov_meetings(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
) -> list[dict[str, Any]]:
    """Extract normalized meeting structs from a Congress.gov body or inline receipt record."""
    items = unwrap_congress_gov_payload(payload, allow_list_page=True)
    return [
        _convert_congress_meeting_dict(item)
        for item in items
        if item.get("eventId") or item.get("event_id")
    ]


# Hardened bill designator pattern aligned with `spicy_docs.interpretation.citations.BILL_NUMBER_PATTERN`:
# - Rejects `U.S.`, `R.S. 2477`, and `W.S.` prefixes
# - Accepts both dotted (`H.R. 1234`) and undotted (`HR 1234`) bill designators
# - Rejects clause subdivisions (`S 2(N)`) and year headings (`S. Con. Res.\n2022:`)
_HOUSE_BILL_RE = re.compile(
    r"(?<![A-Za-z]\.)(?<!U\.\s)(?<![A-Za-z])"
    r"(H\.?\s*R\.?|H\.?\s*J\.?\s*Res\.?|H\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?"
    r"|S\.?\s*J\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|S\.?\s*Res\.?|S\.?)"
    r"[.\s]\s*([0-9]{1,5})\b(?!\()(?!(?<=\n(?:19|20)\d\d):)",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _house_naming_engine():
    from house_naming import Engine

    return Engine()


def _extract_bill_keys_from_doc_url(doc_url: str | None, congress: int) -> list[str]:
    """Extract `{congress}-{type}-{number}` bill keys from a document URL's filename via `house-naming`."""
    if not doc_url or not isinstance(doc_url, str):
        return []
    basename = doc_url.strip().rsplit("/", 1)[-1].split("?", 1)[0]
    if not basename:
        return []
    try:
        res = _house_naming_engine().extract(basename)
    except Exception:
        return []
    metadata = res.get("metadata") or {}
    file_cong_vals = metadata.get("congress") or []
    if len(file_cong_vals) == 1 and str(file_cong_vals[0]).isdigit():
        if int(file_cong_vals[0]) != congress:
            return []
    measures = list(metadata.get("measure_references") or [])
    m_types = metadata.get("measure_type") or []
    m_nums = metadata.get("measure_number") or []
    if len(m_types) == 1 and len(m_nums) == 1:
        measures.append(f"{m_types[0]}{m_nums[0]}")
    keys: list[str] = []
    for ref in measures:
        m = re.fullmatch(r"(hr|s|hjres|sjres|hconres|sconres|hres|sres)([0-9]+)", str(ref).lower())
        if m:
            key = format_subject_key_bill(congress, m.group(1), m.group(2))
            if key and key not in keys:
                keys.append(key)
    return keys


def _iter_active_meeting_documents(docs_elem: ET.Element | None) -> Iterable[ET.Element]:
    """Yield active `<meeting-document>` elements whether direct children or inside `<meeting-document-group>`."""
    if docs_elem is None:
        return
    for doc in docs_elem.findall("meeting-document"):
        if active(doc):
            yield doc
    for grp in docs_elem.findall("meeting-document-group"):
        if not active(grp):
            continue
        for doc in grp.findall("meeting-document"):
            if active(doc):
                yield doc


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
    root_cong = (root.get("congress-num") or "").strip()
    if root_cong.isdigit():
        congress = int(root_cong)
    root_sess = (root.get("session-num") or "").strip()
    if root_sess.isdigit():
        session = int(root_sess)

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
        for doc in _iter_active_meeting_documents(root.find("meeting-documents")):
            doc_type = (doc.get("type") or value(doc, "type") or "").strip().upper()
            # Support documents (`SD`, such as hearing notices) mention bills in prose
            # without placing them on the legislative agenda.
            if doc_type == "SD":
                continue
            files_container = doc.find("files")
            file_elems = (
                files_container.findall("file")
                if files_container is not None
                else doc.findall("file")
            )
            for f_elem in file_elems:
                if not active(f_elem):
                    continue
                doc_url = f_elem.get("doc-url") or f_elem.get("url") or (f_elem.text or "")
                for b_key in _extract_bill_keys_from_doc_url(doc_url, congress):
                    if b_key not in seen_subjects:
                        seen_subjects.add(b_key)
                        subject_keys.append(b_key)

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
    details_title = value(details, "meeting-title") if details is not None else ""
    title = (
        details_title
        or value(root, "Descriptive-Name")
        or value(root, " Descriptive-Name")
        or value(root, "heading")
        or None
    )
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
    return build_record_table(rows, payload_col="meetings", schema=ARROW_SCHEMA)


def filter_unprocessed_inputs(
    inputs: Iterable[Mapping[str, Any]],
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, parser_version)` before parsing payloads."""
    return _shared_filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)


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


CANDIDATE_MEETING_RECORDS_SQL = """SELECT encode(sha256, 'hex') AS record_sha,
    min(coalesce(stored_suffix, '')) AS stored_suffix,
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
    max_work_items: int | None = None,
    decided_at: str | None = None,
    unreadable_store: Any = None,
) -> dict[str, Any]:
    """Stage missing `meeting_records` rows from `captures` via native anti-join."""
    version = current_version() if parser_version is None else str(parser_version)
    return stage_record_table(
        parser_name="meeting_records",
        out_filename="meeting-records.parquet",
        candidate_sql=CANDIDATE_MEETING_RECORDS_SQL,
        inline_sql=INLINE_CONGRESS_MEETINGS_SQL,
        build_row_fn=build_meeting_record_row,
        table_fn=table,
        captures=captures,
        engine=engine,
        work=work,
        version=version,
        existing=existing,
        local_root=local_root,
        raw_store=raw_store,
        unreadable_files=unreadable_files,
        max_work_items=max_work_items,
        decided_at=decided_at,
        unreadable_store=unreadable_store,
        pass_source_url=False,
    )


def create_table(
    *,
    engine: Any,
    work: Path,
    catalog_root: Path | None,
    table: dict[str, Any],
    location: str,
    create_namespace: bool = False,
) -> Any:
    return create_record_table(
        schema_path=TABLE_SCHEMA,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        location=location,
        create_namespace=create_namespace,
    )


def append(
    staged_parquet: Path | Mapping[str, Any],
    *,
    engine: Any,
    work: Path,
    catalog_root: Path | None,
    table: dict[str, Any],
    parser_version: str | None = None,
) -> Any:
    return append_record_table(
        staged_parquet,
        parser_name="meeting_records",
        default_version=DEFAULT_PARSER_VERSION,
        current_version_fn=current_version,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        parser_version=parser_version,
    )
