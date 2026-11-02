"""Lake producer and parsers for `appearance_records` (Phase 2 Track D4).

Extracts context-free `appearance_records` rows from four sources:
- `house_xml`: `docs.house.gov` `<witness-list>` XML (`HouseWitnessListXML`).
- `congress_gov`: Congress.gov `/v3/committee-meeting` detail JSON/XML bodies and inline
  `congress/meetings` receipt records (`CommitteeMeeting.witnesses`).
- `senate_page`: Senate committee hearing page HTML (`parsers.senate_page`).
- `mods`: GovInfo `CHRG` MODS XML (`parsers.gpo.parse_mods_document` + `parsers.witness_names`).

Rules ([[PHASE-2]] §1.3 & [[DATA-MODEL]] §3, §7.2):
- Context-free parsing: reads body facts once per `(record_sha, source, parser_version)`.
  Does not select a capture URL or resolve relative links; literal links are stored in
  `document_links` and resolved per eligible context in the model.
- Subject identity (`event_id`, `package_id`), `declared_base`, and `collection_state`
  (`present`, `empty`, `absent`, `unrecognized`) are stored on the row outside `appearances`
  so an explicit empty list retains its subject and collection state.
- Every source occurrence is preserved in source order with a deterministic `source_locator`.
- `name_key`: `NFKC` -> `casefold()` -> strip Unicode punctuation (`category.startswith('P')`)
  -> collapse whitespace (`" ".join(s.split())`); `None` when unnamed. `name_key` is a
  grouping/diagnostic attribute, never used to deduplicate occurrences.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urljoin

import lxml.html as lhtml
import pyarrow as pa

from ..models.congress import CommitteeMeeting
from ..parsers.gpo import ModsDocument, parse_mods_document
from ..parsers.gpo_hearings import mods_title
from ..parsers.house_documents import NAME, active, number, value
from ..parsers.house_xml import (
    HOUSE_MEETING_PREFIXES,
    HouseWitnessListXML,
    parse_house_witnesses,
    strip_house_meeting_prefix,
)
from ..parsers.senate_page import witness_occurrences as senate_witness_occurrences
from ..parsers.text import text as clean_text
from ..parsers.witness_names import CONTENTS_LABEL, LABEL_NAME, UNMARKED_LABEL, drop_footnote_text, is_name, witness as parse_gpo_witness
from ._record_producer import (
    CANDIDATE_APPEARANCE_RECORDS_SQL,
    INLINE_CONGRESS_MEETINGS_SQL,
    PK,
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
TABLE_SCHEMA = ROOT / "model/lake/appearance-records.schema.json"

VALID_SOURCES = frozenset({"house_xml", "congress_gov", "senate_page", "mods"})

DEFAULT_BASE_URLS = {
    "house_xml": "https://docs.house.gov",
    "congress_gov": "https://www.congress.gov",
    "senate_page": "https://www.senate.gov",
    "mods": "https://www.govinfo.gov",
}

APPEARANCE_STRUCT = pa.struct(
    [
        pa.field("source_locator", pa.string(), nullable=False),
        pa.field("name_key", pa.string(), nullable=True),
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
        pa.field("document_links", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=False),
    ]
)

ARROW_SCHEMA = pa.schema(
    [
        pa.field("record_sha", pa.binary(32), nullable=False),
        pa.field("parser_version", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("error_type", pa.string(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
        pa.field("event_id", pa.int64(), nullable=True),
        pa.field("package_id", pa.string(), nullable=True),
        pa.field("declared_base", pa.string(), nullable=True),
        pa.field("collection_state", pa.string(), nullable=True),
        pa.field("appearances", pa.list_(pa.field("element", APPEARANCE_STRUCT, nullable=False)), nullable=False),
        # GovInfo MODS only: the print's held dates (ISO) and published title; empty and null elsewhere.
        pa.field("held_dates", pa.list_(pa.field("element", pa.string(), nullable=False)), nullable=True),
        pa.field("title", pa.string(), nullable=True),
        # House XML only: the witness list's create-date as stated.
        pa.field("created", pa.string(), nullable=True),
    ]
)
SCHEMA = ARROW_SCHEMA

# Every column ARROW_SCHEMA carries besides the shared record columns; a field missing here is written null.
_EXTRA_COLS = ("event_id", "package_id", "declared_base", "collection_state", "held_dates", "title", "created")

_SOURCE_SYMBOLS: dict[str, tuple[str, ...]] = {
    "house_xml": (
        "APPEARANCE_STRUCT",
        "ARROW_SCHEMA",
        "normalize_name_key",
        "compute_name_key",
        "_opt_str",
        "_opt_int",
        "_opt_bool",
        "_clean_links",
        "preserve_appearances",
        "extract_house_xml_observation",
        "extract_house_xml_appearances",
    ),
    "congress_gov": (
        "APPEARANCE_STRUCT",
        "ARROW_SCHEMA",
        "normalize_name_key",
        "compute_name_key",
        "_opt_str",
        "_opt_int",
        "_opt_bool",
        "_clean_links",
        "preserve_appearances",
        "extract_congress_gov_observation",
        "extract_congress_gov_appearances",
    ),
    "senate_page": (
        "APPEARANCE_STRUCT",
        "ARROW_SCHEMA",
        "normalize_name_key",
        "compute_name_key",
        "_opt_str",
        "_opt_int",
        "_opt_bool",
        "_clean_links",
        "preserve_appearances",
        "_extract_declared_base",
        "_fallback_senate_cards",
        "_classify_senate_empty_state",
        "extract_senate_page_observation",
        "extract_senate_page_appearances",
    ),
    "mods": (
        "APPEARANCE_STRUCT",
        "ARROW_SCHEMA",
        "normalize_name_key",
        "compute_name_key",
        "_opt_str",
        "_opt_int",
        "_opt_bool",
        "_clean_links",
        "preserve_appearances",
        "_PACKAGE_ID_IN_URL_RE",
        "mods_held_dates",
        "_MEMBER_STATEMENT",
        "_RECORD_ENTRY",
        "_RECORD_OPENING",
        "_RETAINED_IN_FILES",
        "_WITNESS_HEADING",
        "_TESTIFIED_WORDS",
        "mods_entry_kind",
        "extract_mods_observation",
        "extract_mods_appearances",
    ),
}


def current_version(source: str | None = None, *, root: Path = ROOT) -> str:
    root = Path(root)
    pkg_dir = Path(__file__).resolve().parents[1]
    this_file = Path(__file__)
    if source is None:
        return version_digest(
            packages={},
            files={},
            values={"sources": current_versions(root=root)},
        )
    if source == "mods":
        return version_digest(
            packages={},
            files={
                "record_producer": pkg_dir / "lake/_record_producer.py",
                "models_gpo": pkg_dir / "models/gpo.py",
                "parsers_gpo": pkg_dir / "parsers/gpo.py",
                "parsers_gpo_hearings": pkg_dir / "parsers/gpo_hearings.py",
                "parsers_xml": pkg_dir / "parsers/xml.py",
                "parsers_witness_names": pkg_dir / "parsers/witness_names.py",
                "lock": root / "uv.lock",
                "lake_schema": root / "model/lake/appearance-records.schema.json",
            },
            values={
                "source": "mods",
                "ast": source_ast_digest(this_file, _SOURCE_SYMBOLS["mods"]),
            },
        )
    if source == "congress_gov":
        return version_digest(
            packages={},
            files={
                "record_producer": pkg_dir / "lake/_record_producer.py",
                "models_congress": pkg_dir / "models/congress.py",
                "parsers_congress": pkg_dir / "parsers/congress.py",
                "lock": root / "uv.lock",
                "lake_schema": root / "model/lake/appearance-records.schema.json",
            },
            values={
                "source": "congress_gov",
                "ast": source_ast_digest(this_file, _SOURCE_SYMBOLS["congress_gov"]),
            },
        )
    if source == "house_xml":
        return version_digest(
            packages={},
            files={
                "record_producer": pkg_dir / "lake/_record_producer.py",
                "parsers_house_xml": pkg_dir / "parsers/house_xml.py",
                "parsers_house_documents": pkg_dir / "parsers/house_documents.py",
                "lock": root / "uv.lock",
                "lake_schema": root / "model/lake/appearance-records.schema.json",
            },
            values={
                "source": "house_xml",
                "prefixes": list(HOUSE_MEETING_PREFIXES),
                "parsers_text_ast": source_ast_digest(pkg_dir / "parsers/text.py", ("text",)),
                "ast": source_ast_digest(this_file, _SOURCE_SYMBOLS["house_xml"]),
            },
        )
    if source == "senate_page":
        return version_digest(
            packages={},
            files={
                "record_producer": pkg_dir / "lake/_record_producer.py",
                "parsers_senate_page": pkg_dir / "parsers/senate_page.py",
                "lock": root / "uv.lock",
                "lake_schema": root / "model/lake/appearance-records.schema.json",
            },
            values={
                "source": "senate_page",
                "parsers_text_ast": source_ast_digest(pkg_dir / "parsers/text.py", ("text",)),
                "ast": source_ast_digest(this_file, _SOURCE_SYMBOLS["senate_page"]),
            },
        )
    raise ValueError(f"Unsupported appearance_records source {source!r}; expected one of {sorted(VALID_SOURCES)}")


def current_versions(*, root: Path = ROOT) -> dict[str, str]:
    return {
        source: current_version(source, root=root)
        for source in ("house_xml", "congress_gov", "senate_page", "mods")
    }


DEFAULT_PARSER_VERSION = "appearance-records-v2"


def normalize_name_key(name: str | None) -> str:
    """Normalize a witness name: NFKC -> casefold -> drop punctuation (`P*`) -> collapse whitespace."""
    if not name or not isinstance(name, str):
        return ""
    norm = unicodedata.normalize("NFKC", name).casefold()
    no_punct = "".join(ch for ch in norm if not unicodedata.category(ch).startswith("P"))
    return " ".join(no_punct.split())


def compute_name_key(name: str | None, position_1based: int | None = None) -> str | None:
    """Return normalized `name_key`, or `None` when unnamed/empty ([[PHASE-2]] §1.3)."""
    if position_1based is not None and position_1based < 1:
        raise ValueError(f"position_1based must be >= 1, got {position_1based}")
    key = normalize_name_key(name)
    return key if key else None


def resolve_document_url(href: str | None, base_url: str, declared_base: str | None = None) -> str | None:
    """Resolve a witness document link against an optional declared base and source URL ([[DATA-MODEL]] §7.2)."""
    if not href or not isinstance(href, str):
        return None
    cleaned = href.strip()
    if not cleaned:
        return None
    effective_base = urljoin(base_url, declared_base.strip()) if declared_base and declared_base.strip() else base_url
    return urljoin(effective_base, cleaned)


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


def _clean_links(links: Iterable[Any] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in links or ():
        href = raw.get("url") if isinstance(raw, Mapping) else raw
        s = _opt_str(href)
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    return cleaned


def preserve_appearances(
    raw_appearances: Sequence[Mapping[str, Any]],
    *,
    default_source: str = "occurrence",
) -> list[dict[str, Any]]:
    """Normalize appearance occurrence fields while preserving every occurrence in source order."""
    preserved: list[dict[str, Any]] = []
    seen_locators: set[str] = set()
    for pos, item in enumerate(raw_appearances, start=1):
        name_val = _opt_str(item.get("name"))
        raw_nk = _opt_str(item.get("name_key"))
        if raw_nk and not raw_nk.startswith("#"):
            name_key = normalize_name_key(raw_nk) or raw_nk
        else:
            name_key = compute_name_key(name_val)
        loc = _opt_str(item.get("source_locator")) or f"{default_source}:witness[{pos}]"
        if loc in seen_locators:
            loc = f"{loc}@{pos}"
        seen_locators.add(loc)
        raw_links = item.get("document_links")
        if raw_links is None:
            raw_links = item.get("document_urls")
        doc_links = _clean_links(raw_links)
        preserved.append(
            {
                "source_locator": loc,
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
                "display_order": _opt_int(item.get("display_order")) or pos,
                "witness_type": _opt_str(item.get("witness_type")),
                "testified": _opt_bool(item.get("testified")),
                "bioguide_id": _opt_str(item.get("bioguide_id")),
                "document_links": doc_links,
            }
        )
    return preserved


# Backward-compatible alias that now preserves all source occurrences per PHASE-2 §1.3 / GB5.
deduplicate_appearances = preserve_appearances


def extract_house_xml_observation(
    payload: bytes | str | HouseWitnessListXML,
    *,
    event_id: int | str | None = None,
) -> dict[str, Any]:
    """Extract context-free observation metadata and appearances from a `docs.house.gov` `<witness-list>` XML body."""
    explicit_event_id = _opt_int(strip_house_meeting_prefix(str(event_id)) if event_id is not None else None)
    if isinstance(payload, HouseWitnessListXML):
        root = payload
    else:
        raw_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        if not raw_bytes.strip():
            return {
                "event_id": explicit_event_id,
                "package_id": None,
                "declared_base": None,
                "collection_state": "unrecognized",
                "appearances": [],
            }
        try:
            root = parse_house_witnesses(raw_bytes)
        except ET.ParseError:
            return {
                "event_id": explicit_event_id,
                "package_id": None,
                "declared_base": None,
                "collection_state": "unrecognized",
                "appearances": [],
            }
        except ValueError:
            try:
                xml_root = ET.fromstring(raw_bytes)
            except ET.ParseError:
                xml_root = None
            if xml_root is not None and xml_root.tag == "committee-meeting":
                raw_mid = (xml_root.get("meeting-id") or "").strip()
                resolved_eid = _opt_int(strip_house_meeting_prefix(raw_mid)) or explicit_event_id
                return {
                    "event_id": resolved_eid,
                    "package_id": None,
                    "declared_base": None,
                    "collection_state": "absent",
                    "appearances": [],
                }
            return {
                "event_id": explicit_event_id,
                "package_id": None,
                "declared_base": None,
                "collection_state": "unrecognized",
                "appearances": [],
            }

    raw_meeting_id = (root.get("meeting-id") or "").strip()
    resolved_event_id = _opt_int(strip_house_meeting_prefix(raw_meeting_id)) or explicit_event_id

    if root.tag != "witness-list" or not active(root):
        return {
            "event_id": resolved_event_id,
            "package_id": None,
            "declared_base": None,
            "collection_state": "absent",
            "appearances": [],
        }

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
            given = _opt_str(name_parts.get("first"))
            middle = _opt_str(name_parts.get("middle"))
            family = _opt_str(name_parts.get("last"))
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

            doc_links: list[str] = []
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
                    if not active(f_elem):
                        continue
                    raw_href = _opt_str(f_elem.get("doc-url") or f_elem.get("url") or (f_elem.text or ""))
                    if raw_href and raw_href not in doc_links:
                        doc_links.append(raw_href)

            w_id = _opt_str(w_elem.get("id") or w_elem.get("witness-id"))
            locator = f"house_xml:id[{w_id}]" if w_id else f"house_xml:panel[{p_idx}]/witness[{w_idx}]"
            raw_rows.append(
                {
                    "source_locator": locator,
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
                    "document_links": doc_links,
                }
            )

    appearances = preserve_appearances(raw_rows, default_source="house_xml")
    return {
        "event_id": resolved_event_id,
        "package_id": None,
        "declared_base": None,
        "collection_state": "present" if appearances else "empty",
        "appearances": appearances,
        # When the list was made: an empty list made before its hearing is a placeholder (111420), not a
        # statement that no one testified.
        "created": _opt_str(root.get("create-date")),
    }


def extract_house_xml_appearances(
    payload: bytes | str | HouseWitnessListXML,
    *,
    source_url: str | None = None,
    event_id: int | str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a `docs.house.gov` `<witness-list>` XML body."""
    del source_url
    return extract_house_xml_observation(payload, event_id=event_id)["appearances"]


def extract_congress_gov_observation(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
    *,
    event_id: int | str | None = None,
) -> dict[str, Any]:
    """Extract context-free observation metadata and appearances from a Congress.gov meeting payload."""
    explicit_event_id = _opt_int(event_id)
    try:
        unwrapped = unwrap_congress_gov_payload(payload, allow_list_page=False)
    except Exception:
        return {
            "event_id": explicit_event_id,
            "package_id": None,
            "declared_base": None,
            "collection_state": "unrecognized",
            "appearances": [],
        }
    if not unwrapped:
        return {
            "event_id": explicit_event_id,
            "package_id": None,
            "declared_base": None,
            "collection_state": "absent",
            "appearances": [],
        }
    meeting_dict = unwrapped[0]
    resolved_event_id = _opt_int(meeting_dict.get("eventId") or meeting_dict.get("event_id")) or explicit_event_id

    if "witnesses" not in meeting_dict or meeting_dict.get("witnesses") is None:
        return {
            "event_id": resolved_event_id,
            "package_id": None,
            "declared_base": None,
            "collection_state": "absent",
            "appearances": [],
        }

    witness_list = meeting_dict.get("witnesses")
    if not isinstance(witness_list, Sequence) or isinstance(witness_list, (str, bytes)):
        return {
            "event_id": resolved_event_id,
            "package_id": None,
            "declared_base": None,
            "collection_state": "unrecognized",
            "appearances": [],
        }

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

        doc_links = _clean_links(w.get("document_links") or w.get("document_urls") or w.get("documents"))

        raw_rows.append(
            {
                "source_locator": _opt_str(w.get("source_locator")) or f"congress_gov:witness[{idx}]",
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
                "document_links": doc_links,
            }
        )

    appearances = preserve_appearances(raw_rows, default_source="congress_gov")
    return {
        "event_id": resolved_event_id,
        "package_id": None,
        "declared_base": None,
        "collection_state": "present" if appearances else ("unrecognized" if witness_list else "empty"),
        "appearances": appearances,
    }


def extract_congress_gov_appearances(
    payload: bytes | str | Mapping[str, Any] | CommitteeMeeting,
    *,
    source_url: str | None = None,
    event_id: int | str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a Congress.gov meeting detail body or inline receipt record."""
    del source_url
    return extract_congress_gov_observation(payload, event_id=event_id)["appearances"]


def _extract_declared_base(html_text: str) -> str | None:
    """Extract literal `<base href='...'>` from HTML if present."""
    try:
        root = lhtml.fromstring(html_text)
    except Exception:
        return None
    for b in root.xpath("//base[@href]"):
        href = _opt_str(b.get("href"))
        if href:
            return href
    return None


def _fallback_senate_cards(html_text: str) -> list[dict[str, Any]]:
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

        doc_links: list[str] = []
        for a in card.xpath(".//a[@href]"):
            raw_href = _opt_str(a.get("href"))
            if raw_href and raw_href not in doc_links:
                doc_links.append(raw_href)

        rows.append(
            {
                "source_locator": f"senate_page:card[{idx}]",
                "name": raw_name,
                "position": pos_val,
                "organization": org_val,
                "location": loc_val,
                "display_order": idx,
                "document_links": doc_links,
            }
        )
    return rows


def _classify_senate_empty_state(html_text: str) -> str:
    """Classify a zero-witness Senate HTML page as `empty`, `absent`, or `unrecognized`."""
    try:
        root = lhtml.fromstring(html_text)
    except Exception:
        return "unrecognized"

    if re.search(r"\bwitness(?:es|\s+list)?\s*:\s*(?:none|n/a|no\s+witnesses)\b", html_text, re.IGNORECASE):
        return "empty"

    containers = root.xpath(
        '//*[@id="witnesses" or @id="witness-list" '
        'or contains(normalize-space(@class), "witness-list") '
        'or contains(normalize-space(@class), "witnesses-container")]'
    )
    for c in containers:
        txt = clean_text(c.text_content() or "").lower()
        if not txt or txt in ("witnesses", "witness list", "none", "no witnesses"):
            return "empty"
        return "unrecognized"

    headings = root.xpath("//h1 | //h2 | //h3 | //h4")
    for h in headings:
        htxt = clean_text(h.text_content() or "").lower().rstrip(":")
        if htxt in ("witnesses", "witness list"):
            sibs = [s for s in h.itersiblings() if clean_text(s.text_content() or "")]
            if not sibs:
                return "empty"
            first_sib_txt = clean_text(sibs[0].text_content() or "").lower()
            if first_sib_txt in ("none", "no witnesses"):
                return "empty"
            return "unrecognized"

    return "absent"


def extract_senate_page_observation(
    payload: bytes | str | Mapping[str, Any],
) -> dict[str, Any]:
    """Extract context-free observation metadata and appearances from a Senate committee hearing page."""
    explicit_state: str | None = None
    explicit_base: str | None = None

    if isinstance(payload, Mapping):
        explicit_state = _opt_str(payload.get("collection_state"))
        explicit_base = _opt_str(payload.get("declared_base"))
        if isinstance(payload.get("raw_html"), Mapping):
            from ..retention.body_files import content_bytes

            html_text = content_bytes(payload["raw_html"]).decode("utf-8", "replace")
        elif isinstance(payload.get("html"), str):
            html_text = payload["html"]
        elif isinstance(payload.get("witnesses"), Sequence) and not isinstance(
            payload.get("witnesses"), (str, bytes, bytearray)
        ):
            raw_witnesses = list(payload.get("witnesses") or ())
            raw_rows: list[dict[str, Any]] = []
            for idx, w in enumerate(raw_witnesses, start=1):
                if isinstance(w, Mapping):
                    w_name = _opt_str(w.get("name"))
                    if not w_name:
                        continue
                    doc_links = _clean_links(w.get("document_links") or w.get("document_urls") or w.get("documents"))
                    raw_rows.append(
                        {
                            "source_locator": _opt_str(w.get("source_locator")) or f"senate_page:witness[{idx}]",
                            "name": w_name,
                            "honorific": _opt_str(w.get("honorific")),
                            "position": _opt_str(w.get("position") or w.get("title")),
                            "organization": _opt_str(w.get("organization")),
                            "location": _opt_str(w.get("location")),
                            "panel": _opt_str(w.get("panel")),
                            "display_order": _opt_int(w.get("display_order")) or idx,
                            "document_links": doc_links,
                        }
                    )
            appearances = preserve_appearances(raw_rows, default_source="senate_page")
            return {
                "event_id": None,
                "package_id": None,
                "declared_base": explicit_base,
                "collection_state": explicit_state
                or ("present" if appearances else ("unrecognized" if raw_witnesses else "empty")),
                "appearances": appearances,
            }
        else:
            return {
                "event_id": None,
                "package_id": None,
                "declared_base": explicit_base,
                "collection_state": explicit_state or "absent",
                "appearances": [],
            }
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        html_text = bytes(payload).decode("utf-8", "replace")
    elif isinstance(payload, str):
        html_text = payload
    else:
        raise TypeError(f"Unsupported senate_page payload type: {type(payload)!r}")

    if not html_text.strip():
        return {
            "event_id": None,
            "package_id": None,
            "declared_base": explicit_base,
            "collection_state": explicit_state or "unrecognized",
            "appearances": [],
        }

    declared_base = explicit_base or _extract_declared_base(html_text)
    people = senate_witness_occurrences(html_text, plain=True)
    if people:
        raw_rows = []
        for idx, p in enumerate(people):
            raw_rows.append(
                {
                    "source_locator": f"senate_page:witness[{idx + 1}]",
                    "name": _opt_str(p.get("name")),
                    "honorific": _opt_str(p.get("honorific")),
                    "position": _opt_str(p.get("position")),
                    "organization": _opt_str(p.get("organization")),
                    "location": _opt_str(p.get("location")),
                    "panel": _opt_str(p.get("panel")),
                    "display_order": idx + 1,
                    "document_links": list(p.get("document_links") or ()),
                }
            )
        appearances = preserve_appearances(raw_rows, default_source="senate_page")
        return {
            "event_id": None,
            "package_id": None,
            "declared_base": declared_base,
            "collection_state": explicit_state or "present",
            "appearances": appearances,
        }

    fallback_rows = _fallback_senate_cards(html_text)
    appearances = preserve_appearances(fallback_rows, default_source="senate_page")
    state = explicit_state or ("present" if appearances else _classify_senate_empty_state(html_text))
    return {
        "event_id": None,
        "package_id": None,
        "declared_base": declared_base,
        "collection_state": state,
        "appearances": appearances,
    }


def extract_senate_page_appearances(
    payload: bytes | str | Mapping[str, Any],
    *,
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances and card-scoped `document_links` from a Senate committee hearing page."""
    del source_url
    return extract_senate_page_observation(payload)["appearances"]


_PACKAGE_ID_IN_URL_RE = re.compile(r"\b(CHRG-\d+[hsj]hrg\d+)\b", re.IGNORECASE)


_MEMBER_STATEMENT = re.compile(
    r"\b(?:a representative in congress|a delegate (?:in congress )?from|resident commissioner|congress(?:man|woman)\b"
    r"|united states house of representatives|member of congress|a (?:united states )?senator from)", re.I)
# Explicit record entries only (red-f3): a letter, a statement or submission for the record, questions or
# answers for the record, a prepared statement. A name a parser cannot read is not evidence of a statement.
_RECORD_ENTRY = re.compile(
    r"\b(?:letters?\b|statements? (?:for|submitted for) the record|submitted (?:by|for the record)|submissions? (?:for|to) the record"
    r"|questions? for the record|responses? to questions|answers? to questions|prepared statement)", re.I)
# A line that says the person testified or was the nominee is a witness whatever else it says.
_TESTIFIED_WORDS = re.compile(r"\b(?:testimony|testified|nominee|nominated)\b", re.I)
# ...unless the line opens with a record entry's own marker ("Letter from the nominee to the Office of General
# Counsel", "Submittals for the record: ... and the testimony of ..."), or is GPO's note that an item "has been
# retained in committee files": then it names the entry, and later words describe its contents.
_RECORD_OPENING = re.compile(
    r"^\W*(?:letters?\b|(?:additional |supplemental )?(?:information|material|materials|submissions?|submittals?|(?:oral )?comments)"
    r"(?: (?:presented|submitted))? for the record\b|questions? for the record|responses? to (?:additional |written )?questions"
    r"|answers? to (?:submitted |additional )?questions|submitted questions\b|additional information\b)", re.I)
_WITNESS_HEADING = re.compile(r"^\W*(?:opening )?statements?\b", re.I)
# GPO's note that an item has been retained, when it is the line's opening and no name follows it.
_RETAINED_IN_FILES = re.compile(r"^\W*[^\\]*?\b(?:has|have|are) been retained in (?:committee|the files)", re.I)


def mods_entry_kind(line: str, name: str | None) -> str | None:
    """A print's <witness> line is sometimes a record entry (a letter, a submission, questions for the
    record) or a Member's prepared statement, not a witness. Only explicit markers say so; a Member who
    appears (Member Day panels, "Green, Hon. Al") and a nominee or anyone said to testify is a witness.
    The model also treats anyone the meeting's own list names as a witness."""
    line = line or ""
    # A contents label that opens the line ("Prepared statement \\1\\ ...", "Submitted questions: ...") names an entry.
    # A bare "Statement of ..." is how some prints list each witness, so it is not one.
    opening = _RECORD_OPENING.match(line) or (
        (CONTENTS_LABEL.match(line) or UNMARKED_LABEL.match(line)) and not _WITNESS_HEADING.match(line))
    if opening or (_RETAINED_IN_FILES.match(line) and not drop_footnote_text(line)):
        return "member_statement" if _MEMBER_STATEMENT.search(line) else "statement_for_record"
    # Footnote text that runs into a witness's line says nothing about that witness (green-f4).
    text = drop_footnote_text(line)
    # "to be Director" names a nomination; "to be included in the record" does not (capital follows).
    if _TESTIFIED_WORDS.search(text) or re.search(r"\b[Tt]o be (?:an? |the )?[A-Z]", text) or not _RECORD_ENTRY.search(text):
        return None
    return "member_statement" if _MEMBER_STATEMENT.search(text) else "statement_for_record"


def mods_held_dates(doc: ModsDocument) -> list[str]:
    """Every heldDate the print states, root and constituent items, as distinct sorted ISO dates."""
    found = set()
    for scope in (doc.root, *(doc.related_items or ())):
        for value in getattr(scope, "held_dates", None) or ():
            text = (value or "").strip()[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                found.add(text)
    return sorted(found)


def extract_mods_observation(
    payload: bytes | str | Mapping[str, Any] | ModsDocument,
    *,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Extract context-free observation metadata and appearances from a GovInfo MODS XML document."""
    resolved_pkg = _opt_str(package_id)

    if isinstance(payload, Mapping) and not isinstance(payload, ModsDocument):
        resolved_pkg = resolved_pkg or _opt_str(payload.get("package_id") or payload.get("packageId"))
        explicit_state = _opt_str(payload.get("collection_state"))
        if "witnesses" not in payload or payload.get("witnesses") is None:
            return {
                "event_id": None,
                "package_id": resolved_pkg,
                "declared_base": None,
                "collection_state": explicit_state or "absent",
                "appearances": [],
            }
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
                        "source_locator": f"mods:witness[{idx}]",
                        "name": w_name,
                        "honorific": _opt_str(parsed.get("honorific")),
                        "position": _opt_str(parsed.get("position")),
                        "organization": _opt_str(parsed.get("organization")),
                        "display_order": idx,
                        "document_links": [],
                    }
                )
            elif isinstance(w, Mapping):
                w_name = _opt_str(w.get("name"))
                if not w_name:
                    continue
                raw_rows.append(
                    {
                        "source_locator": _opt_str(w.get("source_locator")) or f"mods:witness[{idx}]",
                        "name": w_name,
                        "honorific": _opt_str(w.get("honorific")),
                        "position": _opt_str(w.get("position")),
                        "organization": _opt_str(w.get("organization")),
                        "bioguide_id": _opt_str(w.get("bioguide_id") or w.get("bioGuideId")),
                        "display_order": _opt_int(w.get("display_order")) or idx,
                        "document_links": _clean_links(w.get("document_links") or w.get("document_urls")),
                    }
                )
        appearances = preserve_appearances(raw_rows, default_source="mods")
        return {
            "event_id": None,
            "package_id": resolved_pkg,
            "declared_base": None,
            "collection_state": explicit_state
            or ("present" if appearances else ("unrecognized" if raw_witnesses else "empty")),
            "appearances": appearances,
        }

    if isinstance(payload, ModsDocument):
        doc = payload
    else:
        raw_xml_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        if not raw_xml_bytes.strip():
            return {
                "event_id": None,
                "package_id": resolved_pkg,
                "declared_base": None,
                "collection_state": "unrecognized",
                "appearances": [],
            }
        try:
            doc = parse_mods_document(raw_xml_bytes)
        except Exception:
            return {
                "event_id": None,
                "package_id": resolved_pkg,
                "declared_base": None,
                "collection_state": "unrecognized",
                "appearances": [],
            }

    if not resolved_pkg:
        for scope in (doc.root, *(doc.related_items or ())):
            for raw_acc in getattr(scope, "access_ids", None) or ():
                if raw_acc and raw_acc.strip():
                    candidate = raw_acc.strip()
                    m = _PACKAGE_ID_IN_URL_RE.search(candidate)
                    resolved_pkg = m.group(1) if m else candidate
                    break
            if resolved_pkg:
                break

    # What the print states about its sitting: every held date and its published title, so a
    # package-to-meeting link can be checked against the meeting's own date and title (ct-dx22).
    facts = {"held_dates": mods_held_dates(doc), "title": _opt_str(mods_title(doc.root))}

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

    raw_witness_lines = list(doc.witnesses or ())
    if not raw_witness_lines:
        return {
            "event_id": None,
            "package_id": resolved_pkg,
            "declared_base": None,
            "collection_state": "absent",
            "appearances": [],
            **facts,
        }

    raw_rows = []
    for idx, w_line in enumerate(raw_witness_lines, start=1):
        cleaned_line = (w_line or "").strip()
        if not cleaned_line:
            raw_rows.append(
                {
                    "source_locator": f"mods:witness[{idx}]",
                    "name": None,
                    "display_order": len(raw_rows) + 1,
                    "document_links": [],
                }
            )
            continue
        parsed = parse_gpo_witness(cleaned_line)
        w_name = _opt_str(parsed.get("name"))
        # "Prepared statement, dated October 22, 2015" is an entry of the witness above it (green-f4).
        if w_name and LABEL_NAME.match(w_name) and not _WITNESS_HEADING.match(w_name):
            continue
        if w_name and not is_name(w_name) and any(
            phrase in cleaned_line.lower()
            for phrase in ("answers to questions", "printed hearing record", "submitted for the record")
        ):
            continue
        nk = normalize_name_key(w_name)
        bg = member_bioguides.get(nk) if nk else None
        raw_rows.append(
            {
                "source_locator": f"mods:witness[{idx}]",
                "name": w_name,
                "honorific": _opt_str(parsed.get("honorific")),
                "position": _opt_str(parsed.get("position")),
                "organization": _opt_str(parsed.get("organization")),
                "bioguide_id": bg,
                "witness_type": mods_entry_kind(cleaned_line, w_name),
                "display_order": len(raw_rows) + 1,
                "document_links": [],
            }
        )

    appearances = preserve_appearances(raw_rows, default_source="mods")
    return {
        "event_id": None,
        "package_id": resolved_pkg,
        "declared_base": None,
        "collection_state": "present" if appearances else "empty",
        "appearances": appearances,
        **facts,
    }


def extract_mods_appearances(
    payload: bytes | str | Mapping[str, Any] | ModsDocument,
    *,
    source_url: str | None = None,
    package_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract appearances from a GovInfo MODS XML document (`mods_witnesses`)."""
    del source_url
    return extract_mods_observation(payload, package_id=package_id)["appearances"]


def build_appearance_record_row(
    record_sha: str | bytes,
    source: str,
    payload: Any,
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
    source_url: str | None = None,
    event_id: int | str | None = None,
    package_id: str | None = None,
) -> dict[str, Any]:
    """Parse one input from `house_xml`, `congress_gov`, `senate_page`, or `mods` into a context-free `appearance_records` row."""
    del source_url
    if source not in VALID_SOURCES:
        raise ValueError(f"Unsupported appearance_records source {source!r}; expected one of {sorted(VALID_SOURCES)}")
    sha_hex = normalize_record_sha(record_sha)
    if source == "house_xml":
        obs = extract_house_xml_observation(payload, event_id=event_id)
    elif source == "congress_gov":
        obs = extract_congress_gov_observation(payload, event_id=event_id)
    elif source == "senate_page":
        obs = extract_senate_page_observation(payload)
    else:
        obs = extract_mods_observation(payload, package_id=package_id)

    return {
        "record_sha": sha_hex,
        "parser_version": str(parser_version),
        "status": "completed",
        "error_type": None,
        "source": source,
        "event_id": obs["event_id"],
        "package_id": obs["package_id"],
        "declared_base": obs["declared_base"],
        "collection_state": obs["collection_state"],
        "appearances": obs["appearances"],
        "held_dates": obs.get("held_dates"),
        "title": obs.get("title"),
        "created": obs.get("created"),
    }


def compute_v1_witness_key(occasion: str, name_key: str) -> str:
    """Compute the legacy v1 name-derived `witness_key` for migration/redirect checks."""
    payload = json.dumps(["witness", occasion, name_key], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(payload).hexdigest()[:16]


def resolve_old_witness_key(
    old_key: str,
    resolved_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Map a legacy v1 name-derived `witness_key` to v2 occurrence key(s), preserving 1-to-many and unresolved cases."""
    matches: list[str] = []
    for row in resolved_rows:
        occ = _opt_str(row.get("occasion"))
        w_key = _opt_str(row.get("witness_key"))
        nk = _opt_str(row.get("name_key")) or normalize_name_key(_opt_str(row.get("name")))
        if not occ or not w_key or not nk:
            continue
        if compute_v1_witness_key(occ, nk) == old_key and w_key not in matches:
            matches.append(w_key)
    if len(matches) == 1:
        return {
            "old_witness_key": old_key,
            "status": "mapped",
            "witness_key": matches[0],
            "witness_keys": matches,
        }
    if len(matches) > 1:
        return {
            "old_witness_key": old_key,
            "status": "ambiguous",
            "witness_key": None,
            "witness_keys": matches,
        }
    return {
        "old_witness_key": old_key,
        "status": "unresolved",
        "witness_key": None,
        "witness_keys": [],
    }


def _normalize_row_for_table(row: Mapping[str, Any]) -> dict[str, Any]:
    src = str(row["source"])
    status = row.get("status") or "completed"
    raw_apps = list(row.get("appearances") or ())
    norm_apps = preserve_appearances(raw_apps, default_source=src)
    ev_id = _opt_int(row.get("event_id"))
    if ev_id is None and raw_apps:
        ev_id = _opt_int(raw_apps[0].get("event_id"))
    pkg_id = _opt_str(row.get("package_id"))
    if pkg_id is None and raw_apps:
        pkg_id = _opt_str(raw_apps[0].get("package_id"))
    coll_state = _opt_str(row.get("collection_state")) or (
        "failed" if status != "completed" else ("present" if norm_apps else "empty")
    )
    return {
        "record_sha": row["record_sha"],
        "parser_version": row.get("parser_version") or DEFAULT_PARSER_VERSION,
        "status": status,
        "error_type": row.get("error_type"),
        "source": src,
        "event_id": ev_id,
        "package_id": pkg_id,
        "declared_base": _opt_str(row.get("declared_base")),
        "collection_state": coll_state,
        "appearances": norm_apps,
        "held_dates": list(row["held_dates"]) if row.get("held_dates") is not None else None,
        "title": _opt_str(row.get("title")),
        "created": _opt_str(row.get("created")),
    }


def table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    """Convert `appearance_records` row dicts into a sorted PyArrow Table conforming to `ARROW_SCHEMA`."""
    normalized = [_normalize_row_for_table(r) for r in rows]
    return build_record_table(
        normalized,
        payload_col="appearances",
        schema=ARROW_SCHEMA,
        extra_cols=_EXTRA_COLS,
    )


def filter_unprocessed_inputs(
    inputs: Iterable[Mapping[str, Any]],
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    *,
    parser_version: str | Mapping[str, str] = DEFAULT_PARSER_VERSION,
) -> list[dict[str, Any]]:
    """Anti-join candidate inputs on `(record_sha, source, parser_version)` before parsing payloads."""
    return _shared_filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)


def produce_appearance_records(
    inputs: Iterable[Mapping[str, Any]],
    *,
    existing: pa.Table | Sequence[Mapping[str, Any]] | None = None,
    parser_version: str | Mapping[str, str] = DEFAULT_PARSER_VERSION,
) -> pa.Table:
    """Incrementally parse only unprocessed `(record_sha, source, parser_version)` inputs into a PyArrow Table."""
    todo = filter_unprocessed_inputs(inputs, existing, parser_version=parser_version)
    rows = [
        build_appearance_record_row(
            item["record_sha"],
            item["source"],
            item["payload"],
            parser_version=item["parser_version"],
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
    parser_version: str | Mapping[str, str] | None = None,
    max_work_items: int | None = None,
    decided_at: str | None = None,
    unreadable_store: Any = None,
    readings: Any = None,
) -> dict[str, Any]:
    """Stage missing `appearance_records` rows from `captures` via native anti-join."""
    version = current_versions() if parser_version is None else parser_version
    return stage_record_table(
        parser_name="appearance_records",
        out_filename="appearance-records.parquet",
        candidate_sql=CANDIDATE_APPEARANCE_RECORDS_SQL,
        inline_sql=INLINE_CONGRESS_MEETINGS_SQL,
        build_row_fn=build_appearance_record_row,
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
        parser_name="appearance_records",
        default_version=DEFAULT_PARSER_VERSION,
        current_version_fn=current_versions,
        engine=engine,
        work=work,
        catalog_root=catalog_root,
        table=table,
        parser_version=parser_version,
    )
