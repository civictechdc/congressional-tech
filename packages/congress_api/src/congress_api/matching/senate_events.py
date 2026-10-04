"""Source-owned Senate event admission and dated publisher context.

No normalized meeting records, IDs, file reads or acquisition are required.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from congress_api.models.senate import SenatePage, SenateSite, normalize_senate_state
from congress_api.matching.senate_corrections import selected_date
from congress_api.parsers.senate_page import DATE, SITE, written_day


def _site_data(site):
    if isinstance(site, SenateSite):
        return site.source_dict()
    pages = site.get("pages") or {}
    if any(isinstance(page, SenatePage) for page in pages.values()):
        return {**site, "pages": {url: page.source_dict() if isinstance(page, SenatePage) else page for url, page in pages.items()}}
    return site


def prepared_state(state):
    """Lift workflow off page copies without changing the caller's retained state."""
    prepared = {}
    for host, site in state.items():
        prepared[host] = deepcopy(_site_data(site))
    return normalize_senate_state(prepared)


def official_events(state):
    """Validated source-owned events for metadata discovery and offline admission."""
    codes = {host: code for code, host in SITE.items()}
    state = prepared_state(state)
    for host, site in sorted(state.items()):
        site = _site_data(site)
        if host not in codes:
            continue
        for url, page in sorted((site.get("pages") or {}).items()):
            event = page.get("event")
            if page.get("absent") or page.get("status") == "error" or not isinstance(event, dict):
                continue
            if not event.get("title") or event.get("url") != url or (urlsplit(url).hostname or "").removeprefix("www.") != host:
                continue
            try:
                day = date.fromisoformat(selected_date(url, event))
            except (ValueError, TypeError, KeyError):
                continue
            # Congresses since 1935 begin January 3. This collector's explicit
            # historical boundary is much later; dates before that stay raw.
            if day.year < 1935:
                continue
            year = day.year - (1 if (day.month, day.day) < (1, 3) else 0)
            congress = (year - 1789) // 2 + 1
            yield {"host": host, "url": url, "page": page, "event": event,
                   "congress": congress, "committee_code": codes[host]}


@dataclass(frozen=True)
class DatedAccess:
    access: str
    day: date
    label_selector: str
    date_selector: str


def dated_access(url, page, event=None):
    """Return an unambiguous explicit access label with its own sitting date."""
    labels = {item.get("text", "").strip(" :").casefold(): index
              for index, item in enumerate((page.get("page_metadata") or {}).get("heading_prefixes") or [])}
    access_labels = {"open": "open", "closed": "closed", "open/closed": "partly_closed", "open and closed": "partly_closed"}
    stated = {access_labels[label] for label in labels if label in access_labels}
    dated_lines = [(index, written_day(found)) for index, line in enumerate(page.get("lines") or [])
                   if line.strip().casefold().startswith("date:") and (found := DATE.search(line))]
    page_days = {date.fromisoformat(selected_date(url, event))} if event else {day for _, day in dated_lines if day}
    if len(stated) != 1 or len(page_days) != 1:
        return None
    access = next(iter(stated))
    label_index = next(index for label, index in labels.items() if access_labels.get(label) == access)
    return DatedAccess(access, next(iter(page_days)), f"/page_metadata/heading_prefixes/{label_index}",
                       "/event/date" if event else f"/lines/{dated_lines[0][0]}")


def reconciled_event_type(event, existing_type):
    """Only an explicit source Roundtable type overrides an existing type."""
    return "roundtable" if event.get("type") == "Roundtable" else existing_type


def no_broadcast_notices(page):
    """Yield exact publisher notices and their source indexes, without inference."""
    for index, message in enumerate((page.get("page_metadata") or {}).get("video_messages") or []):
        if message.get("text", "").strip().casefold() == "there is no video broadcast for this event.":
            yield index, message["text"]


def source_only_event_allowed(workflow):
    """Refuse a new event while retained associations or candidates exist.

    Validation by official_events is required separately. An unresolved native
    event association is still evidence against admitting a duplicate event.
    """
    return not workflow.get('events') and not workflow.get('candidate_events')
