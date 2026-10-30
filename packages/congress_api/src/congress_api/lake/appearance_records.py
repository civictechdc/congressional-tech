"""Lake producer and parsers for `appearance_records` (Phase 2 Track D4).

Extracts normalized `appearance_records` rows from four sources:
- `house_xml`: `docs.house.gov` `<witness-list>` XML (`HouseWitnessListXML`).
- `congress_gov`: Congress.gov `/v3/committee-meeting` detail JSON/XML bodies and inline
  `congress/meetings` receipt records (`CommitteeMeeting.witnesses`).
- `senate_page`: Senate committee hearing page HTML (`parsers.senate_page`).
- `mods`: GovInfo `CHRG` MODS XML (`parsers.gpo.parse_mods_document` + `parsers.witness_names`).

Rules ([[PHASE-2]] §1.3 & [[DATA-MODEL]] §3, §7.2):
- `name_key`: `NFKC` -> `casefold()` -> strip Unicode punctuation (`category.startswith('P')`)
  -> collapse whitespace (`" ".join(s.split())`).
- When a witness has no recorded name (or it normalizes to `""`), `name_key` is `f"#{pos}"`
  using the witness's 1-based position in the source's witness list, keeping unnamed
  witnesses distinct.
- Within a single `record_sha`, entries sharing a `name_key` keep the **first** in source
  order (`witness_key` is unique per occasion).
- An input with zero witnesses still emits a row with `appearances = []` so the anti-join
  on `(record_sha, parser_version)` does not re-parse it on future runs.
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urljoin

import lxml.html as lhtml
import pyarrow as pa

from ..models.congress import CommitteeMeeting, MeetingResponse, parse_response
from ..parsers.congress import meeting_from_xml, parse_congress_xml
from ..parsers.gpo import ModsDocument, parse_mods_document
from ..parsers.house_documents import NAME, active, number, value
from ..parsers.house_xml import (
    HOUSE_MEETING_PREFIXES,
    HouseWitnessListXML,
    parse_house_witnesses,
    strip_house_meeting_prefix,
)
from ..parsers.senate_page import source_details, witnesses as senate_witnesses
from ..parsers.text import text as clean_text
from ..parsers.witness_names import is_name, witness as parse_gpo_witness
from .meeting_records import normalize_record_sha
from .versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
TABLE_SCHEMA = ROOT / "model/lake/appearance-records.schema.json"
PK = ["record_sha", "parser_version"]

VALID_SOURCES = frozenset({"house_xml", "congress_gov", "senate_page", "mods"})

DEFAULT_BASE_URLS = {
    "house_xml": "https://docs.house.gov",
    "congress_gov": "https://www.congress.gov",
    "senate_page": "https://www.senate.gov",
    "mods": "https://www.govinfo.gov",
}

APPEARANCE_STRUCT = pa.struct(
    [
        pa.field("event_id", pa.string(), nullable=True),
        pa.field("package_id", pa.string(), nullable=True),
        pa.field("page_url", pa.string(), nullable=True),
        pa.field("name_key", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=True),
        pa.field("honorific", pa.string(), nullable=True),
        pa.field("given", pa.string(), nullable=True),
        pa.field("middle", pa.string(), nullable=True),
        pa.field("family", pa.string(), nullable=True),
        pa.field("suffix", pa.string(), nullable=True),
        pa.field("position", pa.string(), nullable=True),
        pa.field("organization", pa.string(), nullable=True),
        pa.field("on_behalf_of", pa.string(), nullable=True),
        pa.field("location", pa.string(), nullable=True),
        pa.field("panel", pa.string(), nullable=True),
        pa.field("panel_order", pa.int32(), nullable=True),
        pa.field("display_order", pa.int32(), nullable=True),
        pa.field("witness_type", pa.string(), nullable=True),
        pa.field("testified", pa.bool_(), nullable=True),
        pa.field("bioguide_id", pa.string(), nullable=True),
        pa.field("document_urls", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=False),
    ]
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("record_sha", pa.string(), nullable=False),
        pa.field("parser_version", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("appearances", pa.list_(pa.field("element", APPEARANCE_STRUCT, nullable=False)), nullable=False),
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
            "parsers_senate_page": pkg_dir / "parsers/senate_page.py",
            "parsers_gpo": pkg_dir / "parsers/gpo.py",
            "parsers_witness_names": pkg_dir / "parsers/witness_names.py",
            "lock": root / "uv.lock",
            "lake_schema": root / "model/lake/appearance-records.schema.json",
        },
        values={"prefixes": list(HOUSE_MEETING_PREFIXES)},
    )


DEFAULT_PARSER_VERSION = "appearance-records-v1"


def normalize_name_key(name: str | None) -> str:
    """Normalize a witness name: NFKC -> casefold -> drop punctuation (`P*`) -> collapse whitespace."""
    if not name or not isinstance(name, str):
        return ""
    norm = unicodedata.normalize("NFKC", name).casefold()
    no_punct = "".join(ch for ch in norm if not unicodedata.category(ch).startswith("P"))
    return " ".join(no_punct.split())


def compute_name_key(name: str | None, position_1based: int) -> str:
    """Return normalized `name_key`, or `f'#{position_1based}'` when unnamed/empty."""
    if position_1based < 1:
        raise ValueError(f"position_1based must be >= 1, got {position_1based}")
    key = normalize_name_key(name)
    if not key:
        return f"#{position_1based}"
    return key


def resolve_document_url(href: str | None, base_url: str) -> str | None:
    """Resolve a witness document link against its source URL ([[DATA-MODEL]] §7.2)."""
    if not href or not isinstance(href, str):
        return None
    cleaned = href.strip()
    if not cleaned:
        return None
    return urljoin(base_url, cleaned)


def _opt_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _opt_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if not s:
        return None
    if re.fullmatch(r"-?[0-9]+", s):
        return int(s)
    return None


def _opt_bool(val: Any) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "yes", "y", "1"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    return None


def deduplicate_appearances(raw_appearances: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Assign `name_key` by 1-based input position and keep the first entry per `name_key`."""
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for pos, item in enumerate(raw_appearances, start=1):
        name_val = _opt_str(item.get("name"))
        name_key = _opt_str(item.get("name_key")) or compute_name_key(name_val, pos)
        if name_key in seen_keys:
            continue
        seen_keys.add(name_key)
        doc_urls: list[str] = []
        seen_urls: set[str] = set()
        for u in item.get("document_urls") or []:
            u_clean = _opt_str(u)
            if u_clean and u_clean not in seen_urls:
                seen_urls.add(u_clean)
                doc_urls.append(u_clean)
        deduped.append(
            {
                "event_id": _opt_str(item.get("event_id")),
                "package_id": _opt_str(item.get("package_id")),
                "page_url": _opt_str(item.get("page_url")),
                "name_key": name_key,
                "name": name_val,
                "honorific": _opt_str(item.get("honorific")),
                "given": _opt_str(item.get("given")),
                "middle": _opt_str(item.get("middle")),
                "family": _opt_str(item.get("family")),
                "suffix": _opt_str(item.get("suffix")),
                "position": _opt_str(item.get("position")),
                "organization": _opt_str(item.get("organization")),
                "on_behalf_of": _opt_str(item.get("on_behalf_of")),
                "location": _opt_str(item.get("location")),
                "panel": _opt_str(item.get("panel")),
                "panel_order": _opt_int(item.get("panel_order")),
                "display_order": _opt_int(item.get("display_order")),
                "witness_type": _opt_str(item.get("witness_type")),
                "testified": _opt_bool(item.get("testified")),
                "bioguide_id": _opt_str(item.get("bioguide_id")),
                "document_urls": doc_urls,
            }
        )
    return deduped


def extract_house_xml_appearances(
    payload: bytes | str | HouseWitnessListXML,
    *,
    source_url: str | None = None,
    event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a `docs.house.gov` `<witness-list>` XML body."""
    base_url = source_url or DEFAULT_BASE_URLS["house_xml"]
    if isinstance(payload, HouseWitnessListXML):
        root = payload
    else:
        raw_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        if not raw_bytes.strip():
            return []
        try:
            root = parse_house_witnesses(raw_bytes)
        except (ET.ParseError, ValueError):
            return []

    if root.tag != "witness-list" or not active(root):
        return []

    raw_meeting_id = (root.get("meeting-id") or "").strip()
    resolved_event_id = strip_house_meeting_prefix(raw_meeting_id) or _opt_str(event_id)

    panels = [p for p in root.findall("panel") if active(p)]
    panels.sort(key=lambda p: number(p.get("sort-order", "")))

    raw_rows: list[dict[str, Any]] = []
    for p_idx, panel in enumerate(panels, start=1):
        panel_sort_raw = (panel.get("sort-order") or "").strip()
        panel_label = _opt_str(panel.get("panel-name")) or _opt_str(panel_sort_raw)
        panel_order = int(panel_sort_raw) if panel_sort_raw.isdigit() else p_idx

        witness_elems = [w for w in panel.findall("witness") if active(w)]
        for w_idx, w_elem in enumerate(witness_elems, start=1):
            w_name_elem = w_elem.find("witness-name")
            name_node = w_name_elem if w_name_elem is not None else w_elem
            name_parts = {field: value(name_node, tag) for field, tag in NAME}
            full_name = clean_text(" ".join(v for v in name_parts.values() if v)) or None

            honorific = _opt_str(name_parts.get("honorific"))
            given = _opt_str(name_parts.get("first_name"))
            middle = _opt_str(name_parts.get("middle_name"))
            family = _opt_str(name_parts.get("last_name"))
            suffix_parts = [s for s in (name_parts.get("suffix"), name_parts.get("retired")) if s]
            suffix = _opt_str(" ".join(suffix_parts)) if suffix_parts else None

            position = _opt_str(value(w_elem, "position") or value(w_elem, "title"))
            organization = _opt_str(value(w_elem, "organization"))
            on_behalf_of = _opt_str(value(w_elem, "behalf-of") or value(w_elem, "on-behalf-of"))

            loc_elem = w_elem.find("witness-location")
            if loc_elem is not None:
                loc_parts = [value(loc_elem, t) for t in ("city", "state", "country")]
                loc_parts = [p for p in loc_parts if p]
                location = ", ".join(loc_parts) if loc_parts else _opt_str(value(w_elem, "location"))
            else:
                location = _opt_str(value(w_elem, "location") or value(w_elem, "city"))

            disp_raw = (w_elem.get("display-order") or value(w_elem, "display-order") or "").strip()
            display_order = int(disp_raw) if disp_raw.isdigit() else w_idx

            witness_type = _opt_str(w_elem.get("witness-type") or value(w_elem, "witness-type"))
            testified = _opt_bool(w_elem.get("testified") or value(w_elem, "testified"))
            bioguide_id = _opt_str(
                w_elem.get("bioguideID")
                or w_elem.get("bioguide-id")
                or value(w_elem, "bioguideID")
                or value(w_elem, "bioguide-id")
            )

            doc_urls: list[str] = []
            w_docs_container = w_elem.find("witness-documents")
            doc_elems = (
                w_docs_container.findall("witness-document")
                if w_docs_container is not None
                else w_elem.findall("witness-document")
            )
            for doc_elem in doc_elems:
                if not active(doc_elem):
                    continue
                files_container = doc_elem.find("files")
                file_elems = (
                    files_container.findall("file")
                    if files_container is not None
                    else doc_elem.findall("file")
                )
                for f_elem in file_elems:
                    raw_href = f_elem.get("doc-url") or f_elem.get("url") or (f_elem.text or "")
                    resolved = resolve_document_url(raw_href, base_url)
                    if resolved:
                        doc_urls.append(resolved)

            raw_rows.append(
                {
                    "event_id": resolved_event_id,
                    "package_id": None,
                    "page_url": None,
                    "name": full_name,
                    "honorific": honorific,
                    "given": given,
                    "middle": middle,
                    "family": family,
                    "suffix": suffix,
                    "position": position,
                    "organization": organization,
                    "on_behalf_of": on_behalf_of,
                    "location": location,
                    "panel": panel_label,
                    "panel_order": panel_order,
                    "display_order": display_order,
                    "witness_type": witness_type,
                    "testified": testified,
                    "bioguide_id": bioguide_id,
                    "document_urls": doc_urls,
                }
            )

    return deduplicate_appearances(raw_rows)


def extract_congress_gov_appearances(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
    *,
    source_url: str | None = None,
    event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a Congress.gov meeting detail body or inline receipt record."""
    base_url = source_url or DEFAULT_BASE_URLS["congress_gov"]

    if isinstance(payload, CommitteeMeeting):
        meeting_dict = payload.source_dict()
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raw_bytes = bytes(payload).strip()
        if not raw_bytes:
            return []
        if raw_bytes.startswith(b"<"):
            root = parse_congress_xml(raw_bytes)
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                meeting_dict = meeting_from_xml(root).source_dict()
            else:
                return []
        else:
            meeting_dict = json.loads(raw_bytes.decode("utf-8"))
    elif isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        if text.startswith("<"):
            root = parse_congress_xml(text.encode("utf-8"))
            if root.find("committeeMeeting") is not None or root.tag == "committeeMeeting":
                meeting_dict = meeting_from_xml(root).source_dict()
            else:
                return []
        else:
            meeting_dict = json.loads(text)
    elif isinstance(payload, Mapping):
        meeting_dict = dict(payload)
    else:
        raise TypeError(f"Unsupported congress_gov payload type: {type(payload)!r}")

    if not meeting_dict:
        return []

    if "committeeMeeting" not in meeting_dict and "eventId" not in meeting_dict and "witnesses" not in meeting_dict:
        for wrapper_key in ("record", "payload", "body", "data"):
            inner = meeting_dict.get(wrapper_key)
            if isinstance(inner, Mapping):
                meeting_dict = dict(inner)
                break
        else:
            if isinstance(meeting_dict.get("_source_xml"), Mapping):
                from ..retention.body_files import content_bytes

                return extract_congress_gov_appearances(
                    content_bytes(meeting_dict["_source_xml"]),
                    source_url=source_url,
                    event_id=event_id,
                )
            return []

    if isinstance(meeting_dict.get("committeeMeeting"), Mapping):
        meeting_dict = dict(meeting_dict["committeeMeeting"])

    resolved_event_id = _opt_str(meeting_dict.get("eventId") or meeting_dict.get("event_id") or event_id)
    witness_list = meeting_dict.get("witnesses")
    if not isinstance(witness_list, Sequence) or isinstance(witness_list, (str, bytes)):
        return []

    raw_rows: list[dict[str, Any]] = []
    for idx, w in enumerate(witness_list, start=1):
        if not isinstance(w, Mapping):
            continue
        w_name = _opt_str(w.get("name"))
        w_pos = _opt_str(w.get("position") or w.get("title"))
        w_org = _opt_str(w.get("organization"))
        w_behalf = _opt_str(w.get("onBehalfOf") or w.get("on_behalf_of"))
        w_loc = _opt_str(w.get("location"))
        w_panel = _opt_str(w.get("panel"))
        w_panel_order = _opt_int(w.get("panelOrder") or w.get("panel_order"))
        w_disp_order = _opt_int(w.get("displayOrder") or w.get("display_order")) or idx
        w_type = _opt_str(w.get("witnessType") or w.get("witness_type") or w.get("type"))
        w_testified = _opt_bool(w.get("testified"))
        w_bioguide = _opt_str(w.get("bioguideId") or w.get("bioguide_id") or w.get("bioguideID"))

        doc_urls: list[str] = []
        for raw_u in w.get("document_urls") or w.get("documents") or []:
            href = raw_u.get("url") if isinstance(raw_u, Mapping) else raw_u
            resolved = resolve_document_url(href, base_url)
            if resolved:
                doc_urls.append(resolved)

        raw_rows.append(
            {
                "event_id": resolved_event_id,
                "package_id": None,
                "page_url": None,
                "name": w_name,
                "honorific": _opt_str(w.get("honorific")),
                "given": _opt_str(w.get("given") or w.get("firstName")),
                "middle": _opt_str(w.get("middle") or w.get("middleName")),
                "family": _opt_str(w.get("family") or w.get("lastName")),
                "suffix": _opt_str(w.get("suffix")),
                "position": w_pos,
                "organization": w_org,
                "on_behalf_of": w_behalf,
                "location": w_loc,
                "panel": w_panel,
                "panel_order": w_panel_order,
                "display_order": w_disp_order,
                "witness_type": w_type,
                "testified": w_testified,
                "bioguide_id": w_bioguide,
                "document_urls": doc_urls,
            }
        )

    return deduplicate_appearances(raw_rows)


def _fallback_senate_cards(html_text: str, page_url: str) -> list[dict[str, Any]]:
    """Fallback witness card parser for generic `<div/li class='...witness...'>` structures."""
    try:
        root = lhtml.fromstring(html_text)
    except Exception:
        return []
    cards = root.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), " witness ") '
        'or contains(normalize-space(@class), "witness-card") '
        'or contains(normalize-space(@class), "witness_card") '
        'or contains(normalize-space(@class), "witness-item")]'
    )
    rows: list[dict[str, Any]] = []
    for idx, card in enumerate(cards, start=1):
        name_nodes = card.xpath(
            './/*[contains(@class, "name") or contains(@class, "title") or self::h3 or self::h4 or self::strong]'
        )
        raw_name = clean_text(name_nodes[0].text_content()) if name_nodes else None
        pos_nodes = card.xpath('.//*[contains(@class, "position") or contains(@class, "role") or contains(@class, "title")]')
        pos_val = None
        for pn in pos_nodes:
            candidate = clean_text(pn.text_content())
            if candidate and candidate != raw_name:
                pos_val = candidate
                break
        org_nodes = card.xpath('.//*[contains(@class, "org") or contains(@class, "affiliation")]')
        org_val = clean_text(org_nodes[0].text_content()) if org_nodes else None
        loc_nodes = card.xpath('.//*[contains(@class, "location") or contains(@class, "locality")]')
        loc_val = clean_text(loc_nodes[0].text_content()) if loc_nodes else None

        doc_urls: list[str] = []
        for a in card.xpath(".//a[@href]"):
            resolved = resolve_document_url(a.get("href"), page_url)
            if resolved:
                doc_urls.append(resolved)

        rows.append(
            {
                "event_id": None,
                "package_id": None,
                "page_url": page_url,
                "name": raw_name,
                "position": pos_val,
                "organization": org_val,
                "location": loc_val,
                "display_order": idx,
                "document_urls": doc_urls,
            }
        )
    return rows


def extract_senate_page_appearances(
    payload: bytes | str | Mapping[str, Any],
    *,
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances and card-scoped `document_urls` from a Senate committee hearing page."""
    base_url = source_url or DEFAULT_BASE_URLS["senate_page"]

    if isinstance(payload, Mapping):
        page_url = _opt_str(payload.get("page_url") or payload.get("url") or source_url) or base_url
        if isinstance(payload.get("raw_html"), Mapping):
            from ..retention.body_files import content_bytes

            html_text = content_bytes(payload["raw_html"]).decode("utf-8", "replace")
        elif isinstance(payload.get("html"), str):
            html_text = payload["html"]
        elif isinstance(payload.get("witnesses"), Sequence):
            raw_rows: list[dict[str, Any]] = []
            for idx, w in enumerate(payload["witnesses"], start=1):
                if isinstance(w, Mapping):
                    doc_urls = [
                        u
                        for raw_u in (w.get("document_urls") or w.get("documents") or [])
                        if (u := resolve_document_url(raw_u.get("url") if isinstance(raw_u, Mapping) else raw_u, page_url))
                    ]
                    raw_rows.append(
                        {
                            "event_id": None,
                            "package_id": None,
                            "page_url": page_url,
                            "name": _opt_str(w.get("name")),
                            "honorific": _opt_str(w.get("honorific")),
                            "position": _opt_str(w.get("position") or w.get("title")),
                            "organization": _opt_str(w.get("organization")),
                            "location": _opt_str(w.get("location")),
                            "panel": _opt_str(w.get("panel")),
                            "display_order": _opt_int(w.get("display_order")) or idx,
                            "document_urls": doc_urls,
                        }
                    )
            return deduplicate_appearances(raw_rows)
        else:
            return []
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        page_url = source_url or base_url
        html_text = bytes(payload).decode("utf-8", "replace")
    elif isinstance(payload, str):
        page_url = source_url or base_url
        html_text = payload
    else:
        raise TypeError(f"Unsupported senate_page payload type: {type(payload)!r}")

    if not html_text.strip():
        return []

    people = senate_witnesses(html_text, page_url, plain=True)
    if people:
        files, witness_metadata, _ = source_details(html_text, page_url, people, plain=True)
        urls_by_index: dict[int, list[str]] = {i: [] for i in range(len(people))}
        for href, entry in files.items():
            resolved = resolve_document_url(href, page_url)
            if not resolved:
                continue
            for w_idx in entry.get("witness_indexes") or []:
                if w_idx in urls_by_index and resolved not in urls_by_index[w_idx]:
                    urls_by_index[w_idx].append(resolved)

        raw_rows = []
        for idx, p in enumerate(people):
            meta = witness_metadata.get(str(idx)) or {}
            raw_rows.append(
                {
                    "event_id": None,
                    "package_id": None,
                    "page_url": page_url,
                    "name": _opt_str(p.get("name")),
                    "honorific": _opt_str(p.get("honorific")),
                    "position": _opt_str(p.get("position")),
                    "organization": _opt_str(p.get("organization")),
                    "location": _opt_str(meta.get("location") or p.get("location")),
                    "panel": _opt_str(meta.get("panel")),
                    "display_order": idx + 1,
                    "document_urls": urls_by_index.get(idx, []),
                }
            )
        return deduplicate_appearances(raw_rows)

    fallback_rows = _fallback_senate_cards(html_text, page_url)
    return deduplicate_appearances(fallback_rows)


_PACKAGE_ID_IN_URL_RE = re.compile(r"\b(CHRG-\d+[hsj]hrg\d+)\b", re.IGNORECASE)


def extract_mods_appearances(
    payload: bytes | str | Mapping[str, Any] | ModsDocument,
    *,
    source_url: str | None = None,
    package_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a GovInfo MODS XML document (`mods_witnesses`)."""
    resolved_pkg = _opt_str(package_id)
    if not resolved_pkg and source_url:
        m = _PACKAGE_ID_IN_URL_RE.search(source_url)
        if m:
            resolved_pkg = m.group(1)

    if isinstance(payload, Mapping) and not isinstance(payload, ModsDocument):
        resolved_pkg = resolved_pkg or _opt_str(payload.get("package_id") or payload.get("packageId"))
        raw_witnesses = payload.get("witnesses") or []
        raw_rows: list[dict[str, Any]] = []
        for idx, w in enumerate(raw_witnesses, start=1):
            if isinstance(w, str):
                parsed = parse_gpo_witness(w)
                w_name = _opt_str(parsed.get("name"))
                if not w_name:
                    continue
                raw_rows.append(
                    {
                        "event_id": None,
                        "package_id": resolved_pkg,
                        "page_url": None,
                        "name": w_name,
                        "honorific": _opt_str(parsed.get("honorific")),
                        "position": _opt_str(parsed.get("position")),
                        "organization": _opt_str(parsed.get("organization")),
                        "display_order": idx,
                        "document_urls": [],
                    }
                )
            elif isinstance(w, Mapping):
                raw_rows.append(
                    {
                        "event_id": None,
                        "package_id": resolved_pkg,
                        "page_url": None,
                        "name": _opt_str(w.get("name")),
                        "honorific": _opt_str(w.get("honorific")),
                        "position": _opt_str(w.get("position")),
                        "organization": _opt_str(w.get("organization")),
                        "bioguide_id": _opt_str(w.get("bioguide_id") or w.get("bioGuideId")),
                        "display_order": _opt_int(w.get("display_order")) or idx,
                        "document_urls": [],
                    }
                )
        return deduplicate_appearances(raw_rows)

    if isinstance(payload, ModsDocument):
        doc = payload
        raw_xml_bytes = doc.content.body_bytes()
    else:
        raw_xml_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        if not raw_xml_bytes.strip():
            return []
        try:
            doc = parse_mods_document(raw_xml_bytes)
        except Exception:
            return []

    if not resolved_pkg:
        try:
            xml_root = ET.fromstring(raw_xml_bytes)
            for acc in xml_root.iter("{http://www.loc.gov/mods/v3}accessId"):
                if acc.text and acc.text.strip():
                    candidate = acc.text.strip()
                    m = _PACKAGE_ID_IN_URL_RE.search(candidate)
                    resolved_pkg = m.group(1) if m else candidate
                    break
        except ET.ParseError:
            pass

    # Map any `<congMember role="WITNESS" bioGuideId="...">` names to bioguide_id
    member_bioguides: dict[str, str] = {}
    for mem in doc.members or []:
        role = (getattr(mem, "role", None) or "").strip().upper()
        bg = (getattr(mem, "bio_guide_id", None) or getattr(mem, "bioGuideId", None) or "").strip()
        if bg and role == "WITNESS":
            for n_obj in getattr(mem, "names", None) or []:
                if n_obj.text:
                    nk = normalize_name_key(parse_gpo_witness(n_obj.text).get("name") or n_obj.text)
                    if nk:
                        member_bioguides[nk] = bg

    raw_rows = []
    for idx, w_line in enumerate(doc.witnesses or [], start=1):
        cleaned_line = (w_line or "").strip()
        if not cleaned_line:
            raw_rows.append(
                {
                    "event_id": None,
                    "package_id": resolved_pkg,
                    "page_url": None,
                    "name": None,
                    "display_order": idx,
                    "document_urls": [],
                }
            )
            continue
        parsed = parse_gpo_witness(cleaned_line)
        w_name = _opt_str(parsed.get("name"))
        if w_name and not is_name(w_name) and any(
            phrase in cleaned_line.lower()
            for phrase in ("answers to questions", "printed hearing record", "submitted for the record")
        ):
            continue
        nk = normalize_name_key(w_name)
        bg = member_bioguides.get(nk) if nk else None
        raw_rows.append(
            {
                "event_id": None,
                "package_id": resolved_pkg,
                "page_url": None,
                "name": w_name,
                "honorific": _opt_str(parsed.get("honorific")),
                "position": _opt_str(parsed.get("position")),
                "organization": _opt_str(parsed.get("organization")),
                "bioguide_id": bg,
                "display_order": len(raw_rows) + 1,
                "document_urls": [],
            }
        )

    return deduplicate_appearances(raw_rows)


def build_appearance_record_row(
    record_sha: str | bytes,
    source: str,
    payload: Any,
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
    source_url: str | None = None,
    event_id: str | None = None,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Parse one input from `house_xml`, `congress_gov`, `senate_page`, or `mods` into an `appearance_records` row."""
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported appearance_records source {source!r}; expected one of {sorted(VALID_SOURCES)}")
    sha_hex = normalize_record_sha(record_sha)
    if source == "house_xml":
        appearances = extract_house_xml_appearances(payload, source_url=source_url, event_id=event_id)
    elif source == "congress_gov":
        appearances = extract_congress_gov_appearances(payload, source_url=source_url, event_id=event_id)
    elif source == "senate_page":
        appearances = extract_senate_page_appearances(payload, source_url=source_url)
    else:
        appearances = extract_mods_appearances(payload, source_url=source_url, package_id=package_id)

    return {
        "record_sha": sha_hex,
        "parser_version": str(parser_version),
        "source": source,
        "appearances": appearances,
    }


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    """Convert `appearance_records` row dicts into a sorted PyArrow Table conforming to `ARROW_SCHEMA`."""
    normalized = [
        {
            "record_sha": normalize_record_sha(r["record_sha"]),
            "parser_version": str(r["parser_version"]),
            "source": str(r["source"]),
            "appearances": list(r.get("appearances") or []),
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


def produce_appearance_records(
    inputs: Iterable[Mapping[str, Any]],
    *,
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> pa.Table:
    """Incrementally parse only unprocessed `(record_sha, parser_version)` inputs into a PyArrow Table."""
    todo = filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)
    rows = [
        build_appearance_record_row(
            item["record_sha"],
            item["source"],
            item["payload"],
            parser_version=item["parser_version"],
            source_url=item.get("source_url"),
            event_id=item.get("event_id"),
            package_id=item.get("package_id"),
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
    parser_version: str | None = None,
) -> dict[str, Any]:
    """Stage missing `appearance_records` rows from `captures` via native anti-join."""
    import pyarrow.parquet as pq

    from ..retention.provenance import field, json_input, parquet_output, run_job
    from .meeting_records import _read_candidate_body
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
            WHEN bool_or(family IN ('house/witness-xml', 'house/meeting-xml')
                OR (coalesce(url, requested_url, context_url, '') ILIKE '%docs.house.gov%'
                    AND (coalesce(url, requested_url, '') ILIKE '%.xml%' OR sniffed_format = 'xml'))) THEN 'house_xml'
            WHEN bool_or(family = 'gpo/chrg'
                OR coalesce(url, requested_url, '') ILIKE '%govinfo.gov%CHRG%mods%'
                OR coalesce(member_path, '') ILIKE '%mods.xml') THEN 'mods'
            WHEN bool_or(family = 'senate/hearings'
                OR (coalesce(url, requested_url, '') ILIKE '%.senate.gov%'
                    AND coalesce(sniffed_format, 'html') = 'html')) THEN 'senate_page'
        END AS source
        FROM captures
        WHERE sha256 IS NOT NULL AND coalesce(complete, true) AND coalesce(http_status, 200) BETWEEN 200 AND 299
        GROUP BY sha256"""

    version_sql = "'" + version.replace("'", "''") + "'"
    missing = (
        " WHERE c.source IS NOT NULL AND NOT EXISTS (SELECT 1 FROM unreadable u "
        "WHERE u.record_sha=c.record_sha AND u.parser='appearance_records' AND u.parser_version="
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
                "source_url": item.get("source_url") or None,
                "parser_version": version,
            }
        )

    produced_table = produce_appearance_records(to_parse, parser_version=version)
    out_path = work / "appearance-records.parquet"
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
        definition=f"appearance_records:{resolved_version}",
    )
