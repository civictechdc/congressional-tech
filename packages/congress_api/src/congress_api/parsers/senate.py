"""Interpret supplied Senate hearing and listing pages without fetching them."""

import calendar
import datetime as dt
import re
from html import unescape

from lxml import html as dom

from congress_api.models.content import RawContent
from congress_api.models.senate import ListingRow, SenatePage
from congress_api.parsers.senate_page import (
    DATE,
    HEARING_LINK,
    document_kind,
    document_labels,
    documents,
    event_details,
    lines,
    source_details,
    witnesses,
    written_day,
)
from congress_api.parsers.text import text

PARSER_VERSION = 11


def parse_page(page: str | bytes, url: str) -> SenatePage:
    """Read source bytes into a source model before normalization or storage.

    Byte inputs must be strict UTF-8; invalid sequences raise UnicodeDecodeError.
    """
    if isinstance(page, bytes):
        original, page = page, page.decode("utf-8")
    else:
        original = page.encode("utf-8")
    title = re.search(r'<meta property="og:title" content="([^"]+)"|<title>(.*?)</title>', page, re.S)
    result = {"title": text(title.group(1) or title.group(2)).split(" | ")[0] if title else "",
              "lines": sorted(lines(page)), "witnesses": witnesses(page, url)}
    if labels := document_labels(page, url):
        result["document_labels"] = labels
    result["document_metadata"], result["witness_metadata"], result["page_metadata"] = source_details(page, url, result["witnesses"])
    result["documents"] = documents(page, url, result["document_metadata"])
    known = {row[2] for row in result["documents"]}
    for file, metadata in result["document_metadata"].items():
        if file not in known:
            label = next(iter(metadata["labels"]), "")
            kind = document_kind(label, file, metadata)
            result["documents"].append((kind, label or file.rsplit("/", 1)[-1], file))
    event = event_details(page, url)
    if event:
        result["event"] = event
        result["title"] = result["title"] or event["title"]
    result["raw_html"] = RawContent.from_bytes(original, "text/html").source_dict()
    return SenatePage.model_validate(result)


def parsed(page, url):
    """Compatibility writer for callers that need the existing dictionary shape."""
    return parse_page(page, url).model_dump(mode="python", by_alias=True, exclude_unset=True)


def parse_listing_page(page, site):
    """(day, url, title) for hearing pages one listing page shows.

    Prefer a date written on the row or near the link. When only a `/YYYY/M/name`
    path dates the link, rank it by the last day of that month so since/pagination
    treat the whole month as in scope. That bound is not a printed calendar day
    (and is never mid-month day 15).
    """
    rows = []
    if not page.strip():
        return rows
    # Source row boundaries take precedence over proximity to another row.
    row_days = {}
    for anchor in dom.fromstring(page).xpath(".//a[@href]"):
        dates = anchor.xpath(".//time")
        if not dates:
            table_rows = anchor.xpath("ancestor::tr[1]")
            if table_rows:
                dates = table_rows[0].xpath(".//td[contains(concat(' ', normalize-space(@class), ' '), ' recordListDate ')]")
        day = next((written_day(match) for node in dates for match in DATE.finditer(node.text_content()) if written_day(match)), None)
        if day:
            row_days[anchor.get("href"), text(dom.tostring(anchor, encoding="unicode", with_tail=False))] = day
    written = re.sub(r"<[^>]+>", lambda tag: " " * len(tag.group()), page)  # the page's words, each where it stood
    for link in HEARING_LINK.finditer(page):
        near = sorted((abs(m.start() - link.start()), written_day(m)) for m in DATE.finditer(written, max(0, link.start() - 900), link.end() + 900) if written_day(m))
        filed = re.search(r"/(\d{4})/(\d{1,2})/[^/]+$", unescape(link.group(1)))
        day = row_days.get((unescape(link.group(1)), text(link.group(2)))) or (near[0][1] if near else None)
        if day is None and filed:
            year, month = int(filed.group(1)), int(filed.group(2))
            day = dt.date(year, month, calendar.monthrange(year, month)[1])
        if day and text(link.group(2)):
            href = unescape(link.group(1))
            row = ListingRow(day=day, url=href if href.startswith("http") else f"https://www.{site}{href}", title=text(link.group(2)))
            rows.append((row.day, row.url, row.title))
    return rows
