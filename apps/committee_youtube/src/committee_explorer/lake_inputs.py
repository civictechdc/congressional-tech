"""Adapt Phase-2 lake `meeting_records`, `appearance_records`, and `spicy-regs` inputs for Committee Explorer export (F3)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import gzip
from hashlib import file_digest, sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pyarrow.parquet as pq

from congress_shared.custody import canonical_json_bytes


def _sha_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _file_sha(path: Path | str) -> str:
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _open_text(path: Path):
    with path.open("rb") as probe:
        is_gz = probe.read(2) == b"\x1f\x8b"
    if is_gz:
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _load_table_or_rows(spec: Any) -> list[dict[str, Any]]:
    """Load rows from a Parquet path, JSON/JSONL file, descriptor dict, or in-memory sequence."""
    if spec is None:
        return []
    if isinstance(spec, (list, tuple)):
        return [dict(r) for r in spec]
    if isinstance(spec, Mapping):
        if "path" in spec and spec.get("kind") in (None, "parquet", "json", "jsonl"):
            return _load_table_or_rows(Path(spec["path"]))
        return [dict(spec)]
    path = Path(spec)
    if path.suffix == ".parquet":
        return pq.read_table(path).to_pylist()
    with _open_text(path) as stream:
        text = stream.read().strip()
        if not text:
            return []
        if text.startswith("["):
            data = json.loads(text)
            return [dict(r) for r in data]
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def input_digest(spec: Any) -> str | None:
    """Compute a deterministic SHA-256 digest for any lake or spicy-regs input specification."""
    if spec is None:
        return None
    if isinstance(spec, (str, Path)):
        p = Path(spec)
        if p.is_file():
            return _file_sha(p)
        if p.is_dir():
            manifest = p / "publication.v2.json"
            if manifest.is_file():
                return _file_sha(manifest)
            parts = sorted(
                (child.name, _file_sha(child))
                for child in p.glob("*.parquet")
                if child.is_file()
            )
            return _sha_bytes(canonical_json_bytes(parts, ensure_ascii=False))
    if isinstance(spec, Mapping):
        if "path" in spec and Path(spec["path"]).exists():
            return input_digest(Path(spec["path"]))
        normalized: dict[str, Any] = {}
        for k, v in sorted(spec.items()):
            if isinstance(v, (str, Path)) and Path(v).exists():
                normalized[k] = input_digest(Path(v))
            elif isinstance(v, Mapping) and "path" in v and Path(v["path"]).exists():
                normalized[k] = input_digest(Path(v["path"]))
            else:
                normalized[k] = v
        return _sha_bytes(canonical_json_bytes(normalized, ensure_ascii=False))
    return _sha_bytes(canonical_json_bytes(list(spec), ensure_ascii=False))


def _parse_subject_keys(subject_keys: Sequence[str], default_congress: int) -> dict[str, list[dict[str, Any]]]:
    """Translate normalized `subject_keys` (e.g. `119:hr:1`, `119:pn:12-01`, `119:treaty:3`) to `relatedItems`."""
    bills: list[dict[str, Any]] = []
    nominations: list[dict[str, Any]] = []
    treaties: list[dict[str, Any]] = []
    for raw_key in subject_keys or ():
        if not raw_key or not isinstance(raw_key, str):
            continue
        parts = raw_key.strip().split(":")
        if len(parts) == 3:
            cong_str, kind, number_part = parts
            cong = int(cong_str) if cong_str.isdigit() else default_congress
            kind_lower = kind.lower()
            if kind_lower in ("pn", "nomination"):
                num, _, part = number_part.partition("-")
                item: dict[str, Any] = {"congress": cong, "number": num}
                if part:
                    item["part"] = part
                nominations.append(item)
            elif kind_lower in ("treaty", "tdoc"):
                treaties.append({"congress": cong, "number": number_part})
            else:
                bills.append({"congress": cong, "type": kind.upper(), "number": number_part})
    related: dict[str, list[dict[str, Any]]] = {}
    if bills:
        related["bills"] = bills
    if nominations:
        related["nominations"] = nominations
    if treaties:
        related["treaties"] = treaties
    return related


def _chamber_display(value: str | None) -> str:
    cleaned = str(value or "").strip().lower()
    return {
        "house": "House",
        "senate": "Senate",
        "joint": "NoChamber",
        "nochamber": "NoChamber",
    }.get(cleaned, value or "House")


def _status_display(value: str | None) -> str:
    cleaned = str(value or "").strip().lower()
    return {
        "scheduled": "Scheduled",
        "rescheduled": "Rescheduled",
        "postponed": "Postponed",
        "canceled": "Canceled",
        "cancelled": "Canceled",
        "held": "Held",
    }.get(cleaned, (value or "Scheduled").title())


def _type_display(value: str | None) -> str:
    if not value:
        return "Hearing"
    return str(value).strip().title()


def adapt_lake_meetings_and_appearances(
    meeting_records_spec: Any,
    appearance_records_spec: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert lake `meeting_records` and `appearance_records` into native meeting dicts and supplemental Senate state."""
    raw_meeting_rows = _load_table_or_rows(meeting_records_spec)
    raw_appearance_rows = _load_table_or_rows(appearance_records_spec)

    # Index appearances by event_id and collect senate_page appearances by page_url
    appearances_by_event: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    senate_pages: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for row in raw_appearance_rows:
        if "appearances" in row and isinstance(row["appearances"], Iterable):
            source = str(row.get("source") or "congress_gov")
            items = list(row["appearances"] or ())
        else:
            source = str(row.get("source") or "congress_gov")
            items = [row]
        for app in items:
            event_id = str(app.get("event_id") or "").strip()
            page_url = str(app.get("page_url") or "").strip()
            if event_id:
                appearances_by_event[event_id].append((source, dict(app)))
            if source == "senate_page" and page_url:
                host = urlsplit(page_url).hostname or "www.senate.gov"
                pages = senate_pages[host].setdefault("pages", {})
                page_entry = pages.setdefault(
                    page_url,
                    {
                        "title": app.get("panel") or "Senate Committee Hearing",
                        "events": [],
                        "documents": [],
                        "witnesses": [],
                    },
                )
                if event_id and event_id not in page_entry["events"]:
                    page_entry["events"].append(event_id)
                witness_entry = {
                    "name": app.get("name"),
                    "position": app.get("position"),
                    "organization": app.get("organization"),
                    "page": page_url,
                }
                page_entry["witnesses"].append(witness_entry)
                for doc_url in app.get("document_urls") or ():
                    if doc_url:
                        page_entry["documents"].append({"url": doc_url, "witness": app.get("name")})

    # Flatten meeting_records, preferring congress_gov over house_xml when both share (congress, chamber, event_id)
    by_event_key: dict[tuple[int, str, str], tuple[int, dict[str, Any]]] = {}
    for row in raw_meeting_rows:
        if "meetings" in row and isinstance(row["meetings"], Iterable):
            source = str(row.get("source") or "congress_gov")
            items = list(row["meetings"] or ())
        else:
            source = str(row.get("source") or "congress_gov")
            items = [row]
        source_priority = 1 if source == "congress_gov" else 2
        for m in items:
            event_id = str(m.get("event_id") or m.get("eventId") or "").strip()
            if not event_id:
                continue
            congress = int(m.get("congress") or 119)
            chamber_norm = _chamber_display(m.get("chamber"))
            key = (congress, chamber_norm.lower(), event_id)
            existing = by_event_key.get(key)
            if existing is not None and existing[0] <= source_priority:
                continue
            by_event_key[key] = (source_priority, dict(m))

    native_rows: list[dict[str, Any]] = []
    for (congress, chamber_lower, event_id), (_, m) in sorted(by_event_key.items()):
        if "eventId" in m and "committees" in m and any("systemCode" in c for c in (m.get("committees") or ()) if isinstance(c, Mapping)):
            row_copy = dict(m)
            native_rows.append(row_copy)
            continue

        sittings = list(m.get("sittings") or ())
        first_sitting = dict(sittings[0]) if sittings else {}
        date_val = first_sitting.get("start") or m.get("meeting_date")
        location: dict[str, Any] = {}
        for loc_key in ("building", "room", "address"):
            if first_sitting.get(loc_key):
                location[loc_key] = first_sitting[loc_key]

        committees = []
        for c in m.get("committees") or ():
            code = c.get("system_code") or c.get("systemCode")
            if code:
                committees.append({
                    "systemCode": str(code),
                    "name": c.get("name") or str(code),
                    "chamber": _chamber_display(c.get("chamber") or m.get("chamber")),
                })

        videos = []
        for v in m.get("videos") or ():
            if v.get("url"):
                videos.append({
                    "url": v["url"],
                    "name": v.get("title") or v.get("name"),
                })

        # Select appearances for this event_id (preferring congress_gov, then house_xml, then any)
        ev_apps = appearances_by_event.get(event_id, [])
        preferred_apps = [a for src, a in ev_apps if src == "congress_gov"]
        if not preferred_apps:
            preferred_apps = [a for src, a in ev_apps if src == "house_xml"]
        if not preferred_apps:
            preferred_apps = [a for _, a in ev_apps]

        witnesses = []
        witness_documents = []
        for a in preferred_apps:
            if a.get("name"):
                witnesses.append({
                    "name": a.get("name"),
                    "position": a.get("position"),
                    "organization": a.get("organization"),
                })
            for doc_url in a.get("document_urls") or ():
                if doc_url:
                    witness_documents.append({
                        "name": f"Statement of {a.get('name')}" if a.get("name") else "Witness Statement",
                        "documentType": "Witness Statement",
                        "url": doc_url,
                    })

        chamber_disp = _chamber_display(m.get("chamber"))
        url_chamber = chamber_disp.lower() if chamber_disp != "NoChamber" else "nochamber"
        native_row: dict[str, Any] = {
            "_url": f"https://api.congress.gov/v3/committee-meeting/{congress}/{url_chamber}/{event_id}",
            "eventId": event_id,
            "congress": congress,
            "chamber": chamber_disp,
            "title": m.get("title"),
            "type": _type_display(m.get("meeting_type") or m.get("type")),
            "meetingStatus": _status_display(m.get("status") or m.get("meetingStatus")),
            "date": date_val,
            "committees": committees,
            "witnesses": witnesses,
            "meetingDocuments": list(m.get("meetingDocuments") or ()),
            "witnessDocuments": witness_documents,
            "videos": videos,
            "relatedItems": _parse_subject_keys(m.get("subject_keys") or (), congress),
        }
        if location:
            native_row["location"] = location
        if len(sittings) > 1:
            native_row["continuations"] = [
                {"continuationDate": s.get("start")}
                for s in sittings[1:]
                if s.get("start")
            ]
        native_rows.append(native_row)

    return native_rows, dict(senate_pages)


_SPICY_TYPE_CODES = {
    "standing": "Standing",
    "select": "Select",
    "special": "Special",
    "joint": "Joint",
    "subcommittee": "Subcommittee",
    "commission_or_caucus": "Commission or Caucus",
    "task_force": "Task Force",
    "other": "Other",
}


def adapt_spicy_regs_committees(
    spicy_regs_spec: Any,
    *,
    congresses: Iterable[int] = (),
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Load `committees`, `members`, and `rosters` from `spicy_regs` and emit `CommitteeSnapshot` rows + entity counts."""
    if spicy_regs_spec is None:
        return [], {"committees": 0, "members": 0, "rosters": 0}

    base_dir: Path | None = None
    spec: Mapping[str, Any] = {}
    if isinstance(spicy_regs_spec, (str, Path)):
        p = Path(spicy_regs_spec)
        if p.is_file():
            spec = json.loads(p.read_text())
            base_dir = p.parent
        elif p.is_dir():
            base_dir = p
            manifest = p / "publication.v2.json"
            if manifest.is_file():
                spec = json.loads(manifest.read_text())
    elif isinstance(spicy_regs_spec, Mapping):
        spec = spicy_regs_spec

    tables_map = spec.get("tables") if isinstance(spec.get("tables"), Mapping) else spec

    def _find_table(names: Sequence[str]) -> list[dict[str, Any]]:
        for name in names:
            if name in tables_map and tables_map[name] is not None:
                return _load_table_or_rows(tables_map[name])
        if base_dir is not None:
            for name in names:
                candidate = base_dir / f"{name}.parquet"
                if candidate.is_file():
                    return _load_table_or_rows(candidate)
        return []

    spicy_committees = _find_table(("spicy_committees", "committees"))
    spicy_members = _find_table(("spicy_members", "members"))
    spicy_rosters = _find_table(("spicy_committee_assignments", "rosters", "committee_assignments"))

    target_congresses = sorted({int(c) for c in congresses if c} | {
        int(r["congress"]) for r in spicy_rosters if r.get("congress")
    })
    if not target_congresses:
        target_congresses = [119]

    snapshots: list[dict[str, Any]] = []
    for c_row in spicy_committees:
        code = str(c_row.get("system_code") or c_row.get("systemCode") or "").strip()
        if not code:
            continue
        raw_type = str(c_row.get("committee_type") or c_row.get("committeeTypeCode") or "").strip()
        type_code = _SPICY_TYPE_CODES.get(raw_type.lower(), raw_type or "Standing")
        parent_code = c_row.get("parent_system_code")
        chamber_disp = _chamber_display(c_row.get("chamber") or ("House" if code.startswith("h") else "Senate" if code.startswith("s") else "Joint"))
        for cong in target_congresses:
            comm_dict: dict[str, Any] = {
                "systemCode": code,
                "name": c_row.get("name") or code,
                "chamber": chamber_disp,
                "committeeTypeCode": type_code,
            }
            if parent_code:
                comm_dict["parent"] = {"systemCode": str(parent_code)}
            snapshots.append({
                "_url": f"https://api.congress.gov/v3/committee/{cong}/{code}",
                "congress": cong,
                "committee": comm_dict,
            })

    counts = {
        "committees": len(spicy_committees),
        "members": len(spicy_members),
        "rosters": len(spicy_rosters),
    }
    return snapshots, counts
