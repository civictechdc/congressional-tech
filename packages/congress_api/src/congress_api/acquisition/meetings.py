"""
Keep a local copy of every House, Senate and joint committee meeting record on Congress.gov.

    congress-meetings --output-path congress_meetings.jsonl.gz

Each line is one meeting's detail record (event ID, date, committees, title, type,
status, witnesses, and the official `videos` links, usually to YouTube). The
first run lists every meeting from the 112th Congress on (about 13,600 detail
calls). Later runs fetch meetings Congress.gov updated since the newest
`updateDate` on file, plus any previously failed detail URLs retained in the
adjacent ``.pending.json`` file. Listing still covers every Congress.
"""

import json
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from congress_shared.auth import load_congress_api_key
from congress_shared.resources import CONGRESS_METADATA
from congress_shared.paths import DEFAULT_MEETINGS_FILE

from congress_api.models.congress import (
    MeetingResponse,
    MeetingsPage,
    parse_response,
)
from congress_api.models.content import RawContent
from congress_api.parsers.congress import meeting_from_xml, parse_congress_xml
from congress_api.retention.meetings import read, write, write_pending
from congress_api.retention.rejected_pages import retain_rejected_page
from congress_api.transport.congress import API, api_headers, get
from congress_api.transport.http import HttpRequestError, get_with_retry
from urllib.parse import urlencode


FIRST_CONGRESS = 112  # Congress.gov's committee meeting records start here


CHAMBERS = ("house", "nochamber", "senate")  # nochamber = joint committees and commissions


RELIST_OVERLAP = timedelta(days=2)


def main(output_path: Path = DEFAULT_MEETINGS_FILE, nthreads: int = 5) -> None:
    if nthreads < 1:
        raise ValueError("nthreads must be positive")
    output_path = Path(output_path)
    api_key = load_congress_api_key()
    session = requests.Session()

    records = read(output_path)
    since = None
    if records:
        newest = max(r.get("updateDate", "") for r in records.values())
        since = (datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S") - RELIST_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(f"{len(records)} meetings on file; listing {'changes since ' + since if since else 'everything'}")

    # Historical records can also be corrected; use the update window for every
    # Congress instead of silently ignoring changes more than two Congresses old.
    current = max(int(c) for c in CONGRESS_METADATA)
    have = {(r.get("chamber") or "").lower() for r in records.values()}  # "house", "nochamber", "senate"
    pending_path = output_path.with_suffix(output_path.suffix + ".pending.json")
    pending = json.loads(pending_path.read_text()) if pending_path.exists() else {"urls": []}
    failed_responses = dict(pending.get("responses", {}))
    urls = list(pending["urls"])
    for chamber in CHAMBERS:
        new_chamber = since is None or chamber not in have
        congresses = range(FIRST_CONGRESS, current + 1)
        for congress in congresses:
            params = {"limit": 250, "offset": 0}
            listed = set()
            if since and not new_chamber:
                params.update(fromDateTime=since, toDateTime="2100-01-01T00:00:00Z")
            while True:
                page = get(session, f"{API}/committee-meeting/{congress}/{chamber}", api_key, params)
                try:
                    envelope = parse_response(page)
                    if not isinstance(envelope, MeetingsPage):
                        raise ValueError("Congress.gov meeting list did not return a MeetingsPage")
                    meetings = envelope.committeeMeetings
                except (ValueError, TypeError, KeyError):
                    retain_rejected_page(output_path, page, url=f"{API}/committee-meeting/{congress}/{chamber}", offset=params['offset'])
                    raise
                page_urls = [m.url.split("?")[0] for m in meetings]
                if page_urls and not set(page_urls) - listed:
                    raise ValueError(f"Meeting pagination repeated a page: {congress}/{chamber}")
                listed.update(page_urls)
                urls += page_urls
                if not (envelope.pagination and envelope.pagination.next) and len(meetings) < params["limit"]:
                    break
                if not meetings:
                    raise ValueError(f"Meeting pagination did not advance: {congress}/{chamber}")
                params["offset"] += len(meetings)
    urls = list(dict.fromkeys(urls))
    logging.info(f"Fetching {len(urls)} new or updated meeting records")
    # Save work before beginning detail requests. A crash may repeat completed
    # requests, but a later global updateDate can never skip unfinished URLs.
    write_pending(pending_path, urls, failed_responses)

    failures, failed_urls, lock = [], [], threading.Lock()

    def fetch(url):
        response = None
        try:
            if not url.startswith(f"{API}/committee-meeting/"):
                raise ValueError("Meeting detail URL is not on the Congress.gov API")
            try:
                response = get(session, url, api_key)
            except (HttpRequestError, ValueError) as error:
                # Some historical endpoints fail JSON serialization but serve
                # XML. Refusals, rate limits and missing records are not that case.
                if isinstance(error, HttpRequestError) and error.status != 500:
                    raise
                xml = get_with_retry(session, url, params={'format': 'xml'}, headers={'X-Api-Key': api_key}, attempts=5)
                # Retained in failed_responses if XML parsing raises before committeeMeeting is built.
                response = {'_source_xml': RawContent.from_bytes(xml.content, 'application/xml').source_dict()}
                response = {'committeeMeeting': meeting_from_xml(parse_congress_xml(xml.content)).source_dict()}
                recovered = response['committeeMeeting']
                expected = url.removeprefix(f'{API}/committee-meeting/').split('/')
                chamber = recovered['chamber'].lower()
                if chamber == 'joint':
                    chamber = 'nochamber'
                if expected != [str(recovered['congress']), chamber, recovered['eventId']]:
                    raise ValueError('XML meeting identity does not match the requested endpoint')
            envelope = parse_response(response)
            if not isinstance(envelope, MeetingResponse):
                raise ValueError("Congress.gov meeting detail did not return a MeetingResponse")
            record = envelope.committeeMeeting.source_dict()
            if any(record.get(field) in (None, "") for field in ("eventId", "congress", "chamber")):
                raise ValueError("Meeting detail lacks eventId, congress or chamber")
            record["_url"] = url
            record["_retrieved_at"] = datetime.now(UTC).isoformat()
            with lock:
                records[url] = record
                failed_responses.pop(url, None)
        except Exception as ex:
            with lock:
                failures.append(f"{url}: {type(ex).__name__}")
                failed_urls.append(url)
                if response is not None:
                    # Keep the source JSON if interpretation failed. A strict
                    # model must never turn a new publisher shape into data loss.
                    failed_responses[url] = response

    with ThreadPoolExecutor(nthreads) as pool:
        list(pool.map(fetch, urls))

    if failed_responses:
        # Keep the full retry set until the parsed snapshot is safely written.
        write_pending(pending_path, urls, failed_responses)
    write(records, output_path)
    write_pending(pending_path, failed_urls, failed_responses)
    logging.info(f"Wrote {len(records)} meetings to {output_path}")
    if failures:
        logging.error(f"{len(failures)} meeting(s) failed:\n  " + "\n  ".join(failures[:50]))
        sys.exit(1)


def build_list_url(
    endpoint: str,
    *,
    offset: int = 0,
    limit: int = 250,
    from_date_time: str | None = None,
    to_date_time: str | None = None,
) -> str:
    """Build a public Congress.gov list URL without credentials in query parameters."""
    base = endpoint.split("?", 1)[0]
    params: dict[str, str | int] = {"format": "json", "limit": limit, "offset": offset}
    if from_date_time:
        params["fromDateTime"] = from_date_time
    if to_date_time:
        params["toDateTime"] = to_date_time
    return f"{base}?{urlencode(params)}"


def relist_endpoint_window(
    fetcher,
    receipt_writer,
    endpoint: str,
    *,
    from_date_time: str | None = None,
    to_date_time: str | None = None,
    limit: int = 250,
    watermarks: dict | None = None,
    family: str = "congress/meetings",
) -> dict:
    """Relist one Congress.gov meeting endpoint window through the raw `Fetcher` and `ReceiptWriter`.

    Track B14 invariant: the incremental relist is keyed by `(endpoint, fromDateTime, toDateTime)`,
    and the window advances ONLY when every page from `offset=0` through the final page has a
    good fetch (`complete`, HTTP 200..299, and valid `MeetingsPage`). A later-page failure leaves
    the watermark unchanged so the next run repeats the window.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    clean_endpoint = endpoint.split("?", 1)[0]
    window_key = (clean_endpoint, from_date_time, to_date_time)
    offset = 0
    listed: set[str] = set()
    detail_urls: list[str] = []
    receipt_keys: list[str] = []
    pages_fetched = 0
    last_retrieved_at: str | None = None

    while True:
        page_url = build_list_url(
            clean_endpoint,
            offset=offset,
            limit=limit,
            from_date_time=from_date_time,
            to_date_time=to_date_time,
        )
        result = fetcher.fetch(page_url)
        receipt_key, receipt_line = receipt_writer.write(result, family=family)
        receipt_keys.append(receipt_key)
        pages_fetched += 1
        final = result.final
        last_retrieved_at = final.retrieved_at
        good_fetch = (
            final.complete
            and receipt_line.get("outcome") in ("stored", "unchanged")
            and final.http_status is not None
            and 200 <= final.http_status < 300
            and final.body is not None
            and final.body.path is not None
        )
        if not good_fetch:
            return {
                "window_key": window_key,
                "complete": False,
                "window_advanced": False,
                "detail_urls": list(dict.fromkeys(detail_urls)),
                "receipt_keys": receipt_keys,
                "pages_fetched": pages_fetched,
                "failed_offset": offset,
                "error": final.error or f"http_{final.http_status}",
            }

        try:
            payload = json.loads(final.body.path.read_bytes().decode("utf-8"))
            envelope = parse_response(payload)
            if not isinstance(envelope, MeetingsPage):
                raise ValueError("Congress.gov meeting list did not return a MeetingsPage")
            meetings_list = envelope.committeeMeetings
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
            return {
                "window_key": window_key,
                "complete": False,
                "window_advanced": False,
                "detail_urls": list(dict.fromkeys(detail_urls)),
                "receipt_keys": receipt_keys,
                "pages_fetched": pages_fetched,
                "failed_offset": offset,
                "error": type(exc).__name__,
            }

        page_urls = [m.url.split("?", 1)[0] for m in meetings_list]
        if page_urls and not (set(page_urls) - listed):
            return {
                "window_key": window_key,
                "complete": False,
                "window_advanced": False,
                "detail_urls": list(dict.fromkeys(detail_urls)),
                "receipt_keys": receipt_keys,
                "pages_fetched": pages_fetched,
                "failed_offset": offset,
                "error": "repeated_page",
            }
        listed.update(page_urls)
        detail_urls.extend(page_urls)

        has_next = bool(envelope.pagination and envelope.pagination.next)
        if not has_next and len(meetings_list) < limit:
            break
        if not meetings_list:
            return {
                "window_key": window_key,
                "complete": False,
                "window_advanced": False,
                "detail_urls": list(dict.fromkeys(detail_urls)),
                "receipt_keys": receipt_keys,
                "pages_fetched": pages_fetched,
                "failed_offset": offset,
                "error": "pagination_stalled",
            }
        offset += len(meetings_list)

    new_watermark = to_date_time or last_retrieved_at or datetime.now(UTC).isoformat()
    if watermarks is not None:
        watermarks[window_key] = new_watermark
        watermarks[clean_endpoint] = new_watermark

    return {
        "window_key": window_key,
        "complete": True,
        "window_advanced": True,
        "watermark": new_watermark,
        "detail_urls": list(dict.fromkeys(detail_urls)),
        "receipt_keys": receipt_keys,
        "pages_fetched": pages_fetched,
        "failed_offset": None,
        "error": None,
    }


def fetch_detail_through_raw(
    fetcher,
    receipt_writer,
    url: str,
    *,
    family: str = "congress/meetings",
    observations=(),
) -> dict:
    """Fetch one Congress.gov meeting detail endpoint through `Fetcher` + `ReceiptWriter`."""
    clean_url = url.split("?", 1)[0]
    if not clean_url.startswith(f"{API}/committee-meeting/"):
        raise ValueError("Meeting detail URL is not on the Congress.gov API")
    json_url = f"{clean_url}?format=json"
    result = fetcher.fetch(json_url)
    receipt_key, receipt_line = receipt_writer.write(
        result, family=family, observations=observations
    )
    receipt_keys = [receipt_key]
    final = result.final
    if final.http_status == 500:
        xml_url = f"{clean_url}?format=xml"
        xml_result = fetcher.fetch(xml_url)
        xml_key, receipt_line = receipt_writer.write(
            xml_result, family=family, observations=observations
        )
        receipt_keys.append(xml_key)
        final = xml_result.final
    return {
        "url": clean_url,
        "receipt_keys": receipt_keys,
        "outcome": receipt_line.get("outcome"),
        "http_status": receipt_line.get("http_status"),
        "complete": final.complete,
    }

