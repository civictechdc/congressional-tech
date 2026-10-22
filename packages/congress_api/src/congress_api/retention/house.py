"""Import retained House XML/HTML and confirmed absences from a local cache."""

from collections.abc import Sequence
import datetime as dt
import json
import xml.etree.ElementTree as ET

from congress_api.models.content import RawContent
from congress_api.parsers.house import parsed
from congress_api.matching.house import addresses
from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses
from congress_api.retention.weekly_tables import WeeklyRetentionTables, house_event_to_row


def seed(m, cache, *, tables: WeeklyRetentionTables | None = None):
    path = cache / "docs_house_xml/meeting" / f"{m['eventId']}.xml"
    wpath = cache / "docs_house_xml/wlist" / f"{m['eventId']}.xml"
    page_path = cache / "docs_house" / f"{m['eventId']}.html"
    root, wlist = cached_xml(path), cached_xml(wpath)
    if root is None and not page_path.exists() and not path.with_suffix(".none").exists():
        return None
    page = page_path.read_text(errors="replace") if page_path.exists() else ""
    wstatus = "present" if wlist is not None else "absent" if wpath.with_suffix(".none").exists() else "unfetched"
    result = parsed(root, wlist, page, wstatus)
    result["source_bodies"] = {name: RawContent.from_bytes(source.read_bytes(), media).source_dict()
                               for name, source, media in (("meeting_xml", path, "application/xml"),
                                   ("witness_xml", wpath, "application/xml"), ("page_html", page_path, "text/html"))
                               if source.exists() and source.stat().st_size}
    result["urls"] = addresses(m, root, page) if root is not None else addresses(m, page=page)
    result["seed"] = "research cache"
    result["imported_at"] = timestamp()
    if tables is not None:
        upsert_events({str(m["eventId"]): result}, tables)
    return result


def upsert_events(events: dict[str, dict], tables: WeeklyRetentionTables):
    """Incrementally admit or update ``house_events`` rows by ``event_id``."""
    return tables.upsert_rows(
        "house_events",
        (house_event_to_row(event_id, events[event_id]) for event_id in sorted(events)),
    )


def read_events(
    tables: WeeklyRetentionTables,
    *,
    event_ids: Sequence[str] | None = None,
) -> dict[str, dict]:
    """Read House events from the incremental ``house_events`` table."""
    if event_ids is not None:
        arrow_table = tables.read_keys("house_events", event_ids, key="event_id")
        return {
            row["event_id"]: json.loads(row["payload_json"])
            for row in arrow_table.to_pylist()
        }
    return {
        row["event_id"]: json.loads(row["payload_json"])
        for row in tables.iter_rows("house_events", columns=("event_id", "payload_json"))
    }


def timestamp():
    return dt.datetime.now(dt.UTC).isoformat()


def cached_xml(path):
    if path.exists() and path.stat().st_size:
        try:
            parser = parse_house_meeting if path.parent.name == "meeting" else parse_house_witnesses
            return parser(path.read_bytes())
        except (ET.ParseError, ValueError):
            pass
    return None
