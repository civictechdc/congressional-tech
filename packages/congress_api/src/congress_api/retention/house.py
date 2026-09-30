"""Import retained House XML/HTML and confirmed absences from a local cache."""

import datetime as dt
import xml.etree.ElementTree as ET

from congress_api.models.content import RawContent
from congress_api.parsers.house import parsed
from congress_api.parsers.house_documents import addresses
from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses


def seed(m, cache):
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
    return result


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
