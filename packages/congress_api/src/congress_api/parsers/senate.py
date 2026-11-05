"""Interpret supplied Senate hearing and listing pages without fetching them."""

import calendar
import datetime as dt
import re
from html import unescape
from urllib.parse import urljoin, urlsplit

from lxml import html as dom

from congress_api.models.content import RawContent
from congress_api.models.senate import ListingColumns, ListingRow, SenatePage
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

PARSER_VERSION = 20

INTELLIGENCE_SITE = "intelligence.senate.gov"
INTELLIGENCE_OPEN_HEARINGS = "/category/hearings/open-hearings/"
_INTELLIGENCE_HEARING_PATH = re.compile(
    r"/[0-9]{4}/[0-9]{2}/[0-9]{2}/(?:open-hearing|hearings?|nomination-hearing)-[a-z0-9-]+/"
)

_EVENT = ('contains(concat(" ",normalize-space(@class)," ")," vevent ") '
          'or contains(concat(" ",normalize-space(@class)," ")," h-event ")')
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*([AP])\.?M", re.I)
_ENCODED_CLOCK = re.compile(r"T(\d{2}):(\d{2})")


def _event_rows(tree) -> dict:
    """Map each link to its nearest event row in one walk: O(links), not O(links x depth).

    Only an element with exactly one <time> is a row. A vevent class on a wrapper would
    give every link the first date; on a row dated by a table cell it would hide that cell.
    """
    return {anchor: row for row in tree.xpath(f"//*[{_EVENT}]") if len(row.xpath(".//time")) == 1
            for anchor in row.xpath("descendant-or-self::a[@href]")}


def displayed_clock(displayed: str) -> tuple[int, int] | None:
    """(hour, minute) of a written 12-hour clock; no meridiem is ever inferred."""
    shown = _CLOCK.search(displayed)
    if not shown or not 1 <= int(shown[1]) <= 12 or int(shown[2]) > 59:
        return None
    return int(shown[1]) % 12 + (12 if shown[3].upper() == "P" else 0), int(shown[2])


def _time_evidence(displayed: str, encoded: str | None) -> str:
    """How a displayed clock relates to the encoded one; the displayed clock is the selection.

    These templates drop the meridiem when encoding, so 03:00PM is encoded 03:00: an
    encoded hour from 1 to 11 with no displayed clock cannot be read as AM or PM.
    """
    shown, coded = displayed_clock(displayed), _ENCODED_CLOCK.search(encoded or "")
    if not coded:
        return "displayed_only"
    if not shown:
        return "encoded_only_ambiguous"
    return "displayed_matches_encoded" if shown == (int(coded[1]), int(coded[2])) else "displayed_conflicts_encoded"


def _event_columns(row) -> dict[str, str]:
    """Columns of one semantic event row: visible text selects, the encoded value is retained."""
    cols: dict[str, str] = {}
    for key, name in (("room", "location"), ("type", "type")):
        nodes = row.xpath(f".//*[contains(concat(' ', normalize-space(@class), ' '), ' {name} ')]")
        if nodes and (value := text(nodes[0].text_content())):
            cols[key] = value
    time, = row.xpath(".//time")
    raw = time.text_content()
    match = DATE.search(raw)
    if match:
        cols["date_text"] = text(match.group())
    if remainder := text(raw[match.end():] if match else raw):
        cols["time"] = remainder
    if encoded := time.get("datetime"):
        cols["encoded_start"] = encoded
    cols["time_evidence"] = _time_evidence(text(raw), encoded)
    return cols


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


def parse_listing_details(page: str, site: str) -> dict[str, dict]:
    """Extract optional listing columns (time, room, type) keyed by canonical URL."""
    details: dict[str, dict] = {}
    if not page.strip():
        return details
    tree = dom.fromstring(page)
    event_rows = _event_rows(tree)
    for anchor in tree.xpath(".//a[@href]"):
        href = anchor.get("href") or ""
        if not href or "#" in href:
            continue
        url = href if href.startswith("http") else f"https://www.{site}{href}"
        cols: dict[str, str] = {}
        item_texts = [
            text(node.text_content())
            for node in anchor.xpath(
                ".//*[contains(concat(' ', normalize-space(@class), ' '), ' LegislationList__itemText ') "
                "and not(contains(concat(' ', normalize-space(@class), ' '), ' LegislationList__title '))]"
            )
            if text(node.text_content())
        ]
        if len(item_texts) == 3:
            cols["type"], cols["room"], cols["time"] = item_texts
        elif anchor in event_rows:
            cols = _event_columns(event_rows[anchor])
        elif table_rows := anchor.xpath("ancestor::tr[1]"):
            tr = table_rows[0]
            types = [
                text(td.text_content())
                for td in tr.xpath(".//td[contains(concat(' ', normalize-space(@class), ' '), ' recordListType ')]")
                if not td.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' location ')]")
                and text(td.text_content())
            ]
            if types:
                cols["type"] = types[0]
            rooms = [
                text(node.text_content())
                for node in tr.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' location ')]")
                if text(node.text_content())
            ]
            if rooms:
                cols["room"] = rooms[0]
            for td in tr.xpath(".//td[contains(concat(' ', normalize-space(@class), ' '), ' recordListDate ')]"):
                raw_date = td.text_content()
                m = DATE.search(raw_date)
                remainder = text(raw_date[m.end():] if m else raw_date)
                if remainder:
                    cols["time"] = remainder
                    break
        if cols:
            details[url] = ListingColumns.model_validate(cols).source_dict()
    return details


def _intelligence_listing_rows(tree):
    """Read dated open-hearing cards. The permalink date is a post date."""
    cards = tree.xpath('//article[contains(concat(" ",normalize-space(@class)," ")," category-open-hearings ")]')
    rows = []
    for card in cards:
        links = card.xpath('./h3[contains(concat(" ",normalize-space(@class)," ")," entry-title ")]/a[@href]')
        dates = card.xpath('./p/span[contains(concat(" ",normalize-space(@class)," ")," date-display ")]')
        if len(links) != 1 or len(dates) != 1:
            continue
        try:
            url = urljoin(f"https://www.{INTELLIGENCE_SITE}/", links[0].get("href"))
            address = urlsplit(url)
        except ValueError:
            continue
        if (address.scheme != "https" or address.netloc != f"www.{INTELLIGENCE_SITE}"
                or address.query or address.fragment or not _INTELLIGENCE_HEARING_PATH.fullmatch(address.path)):
            continue
        title = text(links[0].text_content())
        displayed = DATE.search(dates[0].text_content())
        day = written_day(displayed) if displayed else None
        if title and day:
            row = ListingRow(day=day, url=url, title=title)
            rows.append((row.day, row.url, row.title))
    return rows


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
    tree = dom.fromstring(page)
    if site == INTELLIGENCE_SITE:
        return _intelligence_listing_rows(tree)
    # Source row boundaries take precedence over proximity to another row.
    row_days = {}
    event_rows = _event_rows(tree)
    for anchor in tree.xpath(".//a[@href]"):
        dates = anchor.xpath(".//time")
        if not dates and anchor in event_rows:
            dates = event_rows[anchor].xpath(".//time")
        elif not dates:
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
