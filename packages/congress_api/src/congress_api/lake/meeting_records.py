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

from datetime import datetime
from functools import lru_cache
import re
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

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
from ..parsers.meeting_facts import publisher_status, stated_facts
from ..parsers.senate_player import parse_player_url
from ._record_producer import (
    CANDIDATE_MEETING_RECORDS_SQL,
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
    source_ast_digest,
    stage_record_table,
    unwrap_congress_gov_payload,
)
from .versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/meeting-records.schema.json"

VALID_SOURCES = frozenset({"congress_gov", "house_xml"})

# House select/permanent committees that use `hl` rather than `hs` in 6-char system codes
_HOUSE_SELECT_CODES = frozenset(
    {"ig", "vc", "fd", "qj", "cn", "ef", "gw", "hk", "ie", "ij", "mh", "rk", "zi", "zs"}
)

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

COLLECTION_STATES_STRUCT = pa.struct(
    [
        pa.field("sittings", pa.string(), nullable=True),
        pa.field("committees", pa.string(), nullable=True),
        pa.field("subject_keys", pa.string(), nullable=True),
        pa.field("transcript_jackets", pa.string(), nullable=True),
        pa.field("videos", pa.string(), nullable=True),
        pa.field("document_urls", pa.string(), nullable=True),
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
        pa.field("document_urls", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("collection_states", COLLECTION_STATES_STRUCT, nullable=True),
        pa.field("access", pa.string(), nullable=True),
        pa.field("access_basis", pa.string(), nullable=True),
        pa.field("not_held", pa.bool_(), nullable=True),
        pa.field("title_key", pa.string(), nullable=True),
        pa.field("reschedule_candidate", pa.bool_(), nullable=True),
    ]
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("record_sha", pa.binary(32), nullable=False),
        pa.field("parser_version", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("error_type", pa.string(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
        pa.field("meetings", pa.list_(pa.field("element", MEETING_STRUCT, nullable=False)), nullable=False),
    ]
)
SCHEMA = ARROW_SCHEMA

_SOURCE_SYMBOLS: dict[str, tuple[str, ...]] = {
    "congress_gov": (
        "SITTING_STRUCT",
        "COMMITTEE_STRUCT",
        "VIDEO_STRUCT",
        "COLLECTION_STATES_STRUCT",
        "MEETING_STRUCT",
        "ARROW_SCHEMA",
        "_FORM_PLACEHOLDER",
        "_stated_place",
        "normalize_chamber",
        "format_subject_key_bill",
        "format_subject_key_nomination",
        "format_subject_key_treaty",
        "extract_video_key",
        "_convert_congress_meeting_dict",
        "extract_congress_gov_meetings",
    ),
    "house_xml": (
        "SITTING_STRUCT",
        "COMMITTEE_STRUCT",
        "VIDEO_STRUCT",
        "COLLECTION_STATES_STRUCT",
        "MEETING_STRUCT",
        "ARROW_SCHEMA",
        "_HOUSE_SELECT_CODES",
        "_FORM_PLACEHOLDER",
        "_stated_place",
        "_HOUSE_BUILDINGS",
        "_HOUSE_ZONE",
        "_house_instant",
        "normalize_house_committee_code",
        "format_subject_key_bill",
        "_HOUSE_BILL_RE",
        "_CROSS_CONGRESS_RE",
        "_PRE_CONGRESS_RE",
        "_ACT_YEAR_RE",
        "_THOMAS_GPOXML_RE",
        "_DATE_PATH_RE",
        "_THOMAS_TYPE_MAP",
        "_congress_from_year",
        "_extract_prose_bill_keys",
        "_extract_bill_keys_from_doc_url",
        "_iter_active_meeting_documents",
        "extract_house_xml_meetings",
    ),
}


def current_version(source: str | None = None, *, root: Path = ROOT) -> str:
    """Return the source-scoped parser version for `source`, or the composite digest when `source` is None."""
    root = Path(root)
    if source is None:
        return version_digest(packages={}, files={}, values=current_versions(root=root))
    if source not in VALID_SOURCES:
        raise ValueError(f"Unknown meeting_records source: {source!r}")
    pkg_dir = Path(__file__).resolve().parents[1]
    producer_path = Path(__file__)
    ast_hash = source_ast_digest(producer_path, _SOURCE_SYMBOLS[source])
    if source == "congress_gov":
        return version_digest(
            packages={},
            files={
                "shared_producer": pkg_dir / "lake/_record_producer.py",
                "models_congress": pkg_dir / "models/congress.py",
                "parsers_congress": pkg_dir / "parsers/congress.py",
                "parsers_media": pkg_dir / "parsers/media.py",
                "parsers_senate_player": pkg_dir / "parsers/senate_player.py",
                "parsers_meeting_facts": pkg_dir / "parsers/meeting_facts.py",
                "parsers_text": pkg_dir / "parsers/text.py",
                "lock": root / "uv.lock",
                "lake_schema": root / "model/lake/meeting-records.schema.json",
            },
            values={"source": "congress_gov", "ast": ast_hash},
        )
    return version_digest(
        packages={"house-naming": root / "packages/house-naming/src/house_naming"},
        files={
            "shared_producer": pkg_dir / "lake/_record_producer.py",
            "parsers_house_xml": pkg_dir / "parsers/house_xml.py",
            "parsers_house_documents": pkg_dir / "parsers/house_documents.py",
            "parsers_meeting_facts": pkg_dir / "parsers/meeting_facts.py",
            "parsers_text": pkg_dir / "parsers/text.py",
            "lock": root / "uv.lock",
            "lake_schema": root / "model/lake/meeting-records.schema.json",
        },
        values={
            "source": "house_xml",
            "prefixes": list(HOUSE_MEETING_PREFIXES),
            "ast": ast_hash,
        },
    )


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    """Return the per-source parser version mapping `{source: version}`."""
    root = Path(root)
    return {src: current_version(src, root=root) for src in sorted(VALID_SOURCES)}


DEFAULT_PARSER_VERSION = "meeting-records-v1"


# Both publishers leave unset form values in location fields; these state no place.
_FORM_PLACEHOLDER = re.compile(r"^(?:-+|select one)$", re.I)


def _stated_place(value: Any) -> str | None:
    text = str(value).strip() if value else ""
    return None if not text or _FORM_PLACEHOLDER.match(text) else text


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
        if cleaned.startswith("hs"):
            stem = cleaned[2:4]
            if stem in _HOUSE_SELECT_CODES:
                return f"hl{cleaned[2:]}"
            if stem == "zt":
                return f"ht{cleaned[2:]}"
        return cleaned
    if re.fullmatch(r"[a-z]{2}[0-9]{2}", cleaned):
        stem = cleaned[:2]
        prefix = "hl" if stem in _HOUSE_SELECT_CODES else ("ht" if stem == "zt" else "hs")
        return f"{prefix}{cleaned}"
    if re.fullmatch(r"[a-z]{2}", cleaned):
        prefix = "hl" if cleaned in _HOUSE_SELECT_CODES else ("ht" if cleaned == "zt" else "hs")
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
    room = _stated_place(loc.get("room")) if loc else None
    building = _stated_place(loc.get("building")) if loc else None
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

    document_urls: list[str] = []
    for key in ("meetingDocuments", "witnessDocuments"):
        for doc in m.get(key) or []:
            url = str(doc.get("url") or "").strip() if isinstance(doc, Mapping) else ""
            if url and url not in document_urls:
                document_urls.append(url)

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
        "document_urls": document_urls,
        "collection_states": {
            "sittings": "present" if sittings else ("empty" if ("location" in m or "continuations" in m) else "absent"),
            "committees": "present" if committees else ("empty" if m.get("committees") is not None else "absent"),
            "subject_keys": "present" if subject_keys else ("empty" if m.get("relatedItems") is not None else "absent"),
            "transcript_jackets": "present" if jackets else ("empty" if m.get("hearingTranscript") is not None else "absent"),
            "videos": "present" if videos else ("empty" if m.get("videos") is not None else "absent"),
            # Entries with no URL are agenda items ("A bill to ..."), not files.
            "document_urls": "present" if document_urls else (
                "empty" if ("meetingDocuments" in m or "witnessDocuments" in m) else "absent"),
        },
        **stated_facts(meeting_type, title, status),
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
# - Rejects `U.S.`, `R.S. 2477`, `W.S.`, and possessives (`GAO's 2013`, `Navy’s 30`)
# - Accepts both dotted (`H.R. 1234`) and undotted (`HR 1234`) House bill designators and dotted Senate (`S. 744`)
# - Rejects clause subdivisions (`S 2(N)`) and year headings (`S. Con. Res.\n2022:`)
_HOUSE_BILL_RE = re.compile(
    r"(?<![A-Za-z]\.)(?<!U\.\s)(?<![A-Za-z.\x27\u2018\u2019])"
    r"(H\.?\s*R\.?|H\.?\s*J\.?\s*Res\.?|H\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?"
    r"|S\.?\s*J\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|S\.?\s*Res\.?|S\.)"
    r"(?:(?<=\.)\s*|[.\s]\s*)([0-9]{1,5})\b(?!\()(?!(?<=\n(?:19|20)\d\d):)",
    re.IGNORECASE,
)

_CROSS_CONGRESS_RE = re.compile(
    r"^\s*(?:\(\s*|\bof\s+the\s+|,\s*|\bin\s+the\s+)?([0-9]{2,3})\s*(?:st|nd|rd|th)?\s+Congress\b",
    re.IGNORECASE,
)

_PRE_CONGRESS_RE = re.compile(
    r"(?:([0-9]{2,3})\s*(?:st|nd|rd|th)\s+Congress\s*[,):;-]*|(?:Public\s+Law|P\.?\s*L\.?)\s+([0-9]{2,3})-[0-9]+\s*\()\s*$",
    re.IGNORECASE,
)

_ACT_YEAR_RE = re.compile(
    r"^\s*[,:;.\-–—()\'\"\u2018\u2019\u201c\u201d\s]*"
    r"(?!(?:(?:a\s+bill|an\s+act)\s+)?to\s+\w+\b|"
    r"(?:amend|reauthoriz|repeal|extend|modif|clarif)\w*\b|"
    r"(?:under|pursuant\s+to)\b)"
    r"(?:the\s+)?(?:(?!(?:to|amend|reauthoriz|repeal|extend|modif|clarif)\b)[A-Za-z0-9][A-Za-z0-9'\u2019.-]*\s+){1,8}?Act\s+of\s+((?:19|20)[0-9]{2})\b",
    re.IGNORECASE,
)

_THOMAS_GPOXML_RE = re.compile(
    r"/gpoxmlc([0-9]{2,3})/(hr|h|hj|hc|sr|s|sj|sc)([0-9]+)(?:_[a-z0-9]+)?\.xml$",
    re.IGNORECASE,
)

_DATE_PATH_RE = re.compile(
    r"/(?:billsthisweek|meetings/[A-Za-z0-9]+/[A-Za-z0-9]+)/((?:19|20)[0-9]{2})([0-1][0-9])([0-3][0-9])/",
    re.IGNORECASE,
)

_THOMAS_TYPE_MAP: dict[str, str] = {
    "h": "hr",
    "hr": "hres",
    "hj": "hjres",
    "hc": "hconres",
    "s": "s",
    "sr": "sres",
    "sj": "sjres",
    "sc": "sconres",
}


def _congress_from_year(year: int) -> int | None:
    if year < 1789 or year > 2100:
        return None
    return ((year - 1789) // 2) + 1


def _extract_prose_bill_keys(text: str | None, congress: int | None) -> list[str]:
    """Extract `{congress}-{type}-{number}` keys from prose with cross-Congress and Act-year guards."""
    if not text or congress is None:
        return []
    keys: list[str] = []
    for match in _HOUSE_BILL_RE.finditer(text):
        after = text[match.end() : match.end() + 80]
        before = text[max(0, match.start() - 48) : match.start()]
        post_c = _CROSS_CONGRESS_RE.search(after)
        if post_c and int(post_c.group(1)) != congress:
            continue
        pre_c = _PRE_CONGRESS_RE.search(before)
        if pre_c and int(pre_c.group(1) or pre_c.group(2)) != congress:
            continue
        # Guard against prior-Congress Act-year prose attributing a historical bill to the current Congress
        act_m = _ACT_YEAR_RE.search(after)
        if act_m:
            act_cong = _congress_from_year(int(act_m.group(1)))
            if act_cong is not None and act_cong != congress:
                continue
        b_key = format_subject_key_bill(congress, match.group(1), match.group(2))
        if b_key and b_key not in keys:
            keys.append(b_key)
    return keys


@lru_cache(maxsize=1)
def _house_naming_engine():
    from house_naming import Engine

    return Engine()


def _extract_bill_keys_from_doc_url(doc_url: str | None, congress: int | None) -> list[str]:
    """Extract `{congress}-{type}-{number}` bill keys from a document URL's filename via `house-naming`."""
    if not doc_url or not isinstance(doc_url, str):
        return []
    cleaned_url = unquote(doc_url.strip()).split("?", 1)[0]
    if not cleaned_url:
        return []

    # Check legacy THOMAS gpoxmlc{congress}/{type}{num}_{stage}.xml
    thomas_m = _THOMAS_GPOXML_RE.search(cleaned_url)
    if thomas_m:
        t_cong = int(thomas_m.group(1))
        if congress is not None and t_cong != congress:
            return []
        t_type = _THOMAS_TYPE_MAP.get(thomas_m.group(2).lower())
        t_num = thomas_m.group(3)
        b_key = format_subject_key_bill(t_cong, t_type, t_num)
        return [b_key] if b_key else []

    basename = cleaned_url.rsplit("/", 1)[-1].replace(" ", "")
    if not basename:
        return []
    try:
        res = _house_naming_engine().extract(basename)
    except Exception:
        return []
    metadata = res.get("metadata") or {}
    file_cong: int | None = None
    for field_name in ("congress", "print_congress"):
        vals = metadata.get(field_name) or []
        if len(vals) == 1 and str(vals[0]).isdigit():
            file_cong = int(vals[0])
            break
    if file_cong is None:
        for gen_id in metadata.get("generic_identifier") or []:
            m_cong = re.match(r"^([0-9]{3})-", str(gen_id))
            if m_cong:
                file_cong = int(m_cong.group(1))
                break
    if file_cong is None:
        date_m = _DATE_PATH_RE.search(cleaned_url)
        if date_m:
            file_cong = _congress_from_year(int(date_m.group(1)))

    if file_cong is not None and congress is not None and file_cong != congress:
        return []
    effective_cong = file_cong if file_cong is not None else congress
    if effective_cong is None:
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
            key = format_subject_key_bill(effective_cong, m.group(1), m.group(2))
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


# House XML codes, spelled as Congress.gov spells them for the same events in all 5,510 paired records.
_HOUSE_BUILDINGS = {
    "CAPITOL": "Capitol",
    "CHOB": "Cannon House Office Building",
    "DSOB": "Dirksen Senate Office Building",
    "HSOB": "Hart Senate Office Building",
    "LHOB": "Longworth House Office Building",
    "RHOB": "Rayburn House Office Building",
}

# House XML states committee times as unzoned Eastern local time.
_HOUSE_ZONE = ZoneInfo("America/New_York")


def _house_instant(day: str, clock: str) -> str:
    """An offset-bearing timestamp, so no reader has to know the House's zone."""
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=_HOUSE_ZONE).isoformat()


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
                start_ts = _house_instant(cal, s_time)
            elif cal:
                start_ts = cal
            if cal and e_time:
                end_ts = _house_instant(cal, e_time)

        cap_loc = details.find("meeting-location/capitol-complex")
        if cap_loc is not None:
            room = _stated_place(value(cap_loc, "room"))
            building = _stated_place(value(cap_loc, "building"))
            building = _HOUSE_BUILDINGS.get(building, building)

        field_loc = details.find("meeting-location/field")
        if field_loc is not None:
            building = building or _stated_place(value(field_loc, "building-name"))
            state_elem = field_loc.find("state")
            addr_parts = [
                value(field_loc, "street-address"),
                value(field_loc, "city"),
                (state_elem.get("postal-code") or "").strip() if state_elem is not None else "",
                value(field_loc, "zip"),
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
    document_urls: list[str] = []
    seen_doc_urls: set[str] = set()
    docs_root = root.find("meeting-documents")
    for doc in _iter_active_meeting_documents(docs_root):
        files_container = doc.find("files")
        file_elems = (
            files_container.findall("file")
            if files_container is not None
            else doc.findall("file")
        )
        for f_elem in file_elems:
            if not active(f_elem):
                continue
            doc_url = (f_elem.get("doc-url") or f_elem.get("url") or (f_elem.text or "")).strip()
            if doc_url and doc_url not in seen_doc_urls:
                seen_doc_urls.add(doc_url)
                document_urls.append(doc_url)
            for b_key in _extract_bill_keys_from_doc_url(doc_url, congress):
                if b_key not in seen_subjects:
                    seen_subjects.add(b_key)
                    subject_keys.append(b_key)

        legis_num = value(doc, "legis-num")
        desc = value(doc, "description")
        for candidate in (legis_num, desc):
            for b_key in _extract_prose_bill_keys(candidate, congress):
                if b_key not in seen_subjects:
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
    for b_key in _extract_prose_bill_keys(title, congress):
        if b_key not in seen_subjects:
            seen_subjects.add(b_key)
            subject_keys.append(b_key)

    meeting_type = (root.get("meeting-type") or "").strip() or None
    # Raw House XML puts <current-status> (S, R or P) directly under the root,
    # not inside <meeting-details>: 6,176 of 6,179 retained bodies.
    status = publisher_status(value(root, "current-status"))

    has_loc_elems = details is not None and (
        details.find("meeting-date") is not None
        or details.find("meeting-location") is not None
    )
    has_comm_elems = details is not None and (
        details.find("committees") is not None or details.find("subcommittees") is not None
    )

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
            "document_urls": document_urls,
            "collection_states": {
                "sittings": "present" if sittings else ("empty" if has_loc_elems else "absent"),
                "committees": "present" if committees else ("empty" if has_comm_elems else "absent"),
                "subject_keys": "present" if subject_keys else "empty",
                "transcript_jackets": "absent",
                "videos": "absent",
                "document_urls": "present" if document_urls else ("empty" if docs_root is not None else "absent"),
            },
            **stated_facts(meeting_type, title, status),
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
        "status": "completed",
        "error_type": None,
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
    parser_version: str | Mapping[str, str] = DEFAULT_PARSER_VERSION,
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, source, parser_version)` before parsing payloads."""
    return _shared_filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)


def produce_meeting_records(
    inputs: Iterable[Mapping[str, Any]],
    *,
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    parser_version: str | Mapping[str, str] = DEFAULT_PARSER_VERSION,
) -> pa.Table:
    """Incrementally parse only unprocessed `(record_sha, source, parser_version)` inputs into a PyArrow Table."""
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


def stage(
    *,
    captures: Any,
    engine: Any,
    work: Path,
    existing: Any = None,
    local_root: Path | str | None = None,
    raw_store: Any = None,
    unreadable_files: Sequence[Mapping[str, Any]] = (),
    parser_version: str | Mapping[str, str] | None = None,
    max_work_items: int | None = None,
    decided_at: str | None = None,
    unreadable_store: Any = None,
    readings: Any = None,
) -> dict[str, Any]:
    """Stage missing `meeting_records` rows from `captures` via native anti-join."""
    version = current_versions() if parser_version is None else parser_version
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
        readings=readings,
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
    parser_version: str | Mapping[str, str] | None = None,
) -> Any:
    return append_record_table(
        staged_parquet,
        parser_name="meeting_records",
        default_version=DEFAULT_PARSER_VERSION,
        current_version_fn=current_versions,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        parser_version=parser_version,
    )
