"""house-meeting-records: fill House/joint meeting gaps from docs.house.gov.

Read the meeting export and GPO table, then meeting XML and witness-list XML
(page fallback). Write house_documents_found.csv, house_witnesses_found.csv and
house_amendments_found.csv to --output-dir. Keep parsed results, source URLs,
XML update-date, exact source bodies, Congress.gov updateDate, fetch date and confirmed absences in
--state-dir/house.json.gz. --seed-cache imports the research cache read-only.

Readers select from source inputs; the inventory is not an input. An attached
print discovered here can settle selection during this same pass. Changed and
new records are fetched first; at most --refresh-limit unchanged records are
refreshed per run, oldest checks first. --zyte is only a backfill option.
"""

import collections
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from congress_api.acquisition.refresh import due
from congress_api.matching.house import DOCUMENT_FIELDS, document_rows
from congress_api.matching.meetings import NOT_HELD, TRANSCRIPT, is_hearing
from congress_api.matching.prints import attached_prints, match_prints
from congress_api.models.content import RawContent
from congress_api.parsers.house import parsed
from congress_api.parsers.house_documents import AMENDMENT_FIELDS, WITNESS_FIELDS, addresses
from congress_api.parsers.house_evidence import SCHEMA_VERSION
from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses
from congress_api.retention.house import seed, timestamp
from congress_api.retention.tables import read_csv, read_meetings, read_state, write_csv, write_state
from congress_api.transport import http


def lacking(m, packages):
    transcript = any(d.get("url") and TRANSCRIPT.search(f"{d.get('documentType')} {d.get('name')}") for d in m.get("meetingDocuments") or [])
    return m.get("chamber") != "Senate" and not NOT_HELD.match(m.get("title") or "") and (
        not (m.get("meetingDocuments") or m.get("witnessDocuments"))
        or (is_hearing(m) and not m.get("witnesses")) or not (packages or transcript))


def request(url, through_zyte, receipts, allowed=(200, 404)):
    """Record the retry helper's final outcome, not its unobserved inner attempts."""
    receipt = {"url": url, "started_at": timestamp()}
    receipts.append(receipt)
    try:
        response = http.get_with_retry(None, url, allowed=allowed, through_zyte=through_zyte)
    except (RuntimeError, ValueError, OSError) as error:
        receipt.update(completed_at=timestamp(), outcome="error", error=str(error))
        raise
    receipt.update(completed_at=timestamp(), status_code=response.status_code,
                   outcome="not_found" if response.status_code == 404 else "retrieved")
    if response.status_code == 200:
        receipt["content"] = RawContent.from_bytes(response.content, "application/xml" if url.lower().endswith(".xml") else "text/html").source_dict()
    return response


def fetch_xml(urls, expected, through_zyte, receipts=None):
    receipts = receipts if receipts is not None else []
    for url in dict.fromkeys(urls):
        response = request(url, through_zyte, receipts)
        if response.status_code == 404:
            continue
        for attempt in range(3):
            try:
                parser = parse_house_meeting if expected == "committee-meeting" else parse_house_witnesses
                root = parser(response.content)
                if root.tag != expected:
                    raise ET.ParseError(f"unexpected root {root.tag}")
                break
            except (ET.ParseError, ValueError):
                receipts[-1]["outcome"] = "invalid_xml"
                if attempt == 2:
                    raise
                response = request(url, through_zyte, receipts, allowed=(200,))
        if root.tag != expected:
            raise ValueError(f"Unexpected XML root from {url}: {root.tag}")
        return root, url
    return None, ""


def fetch(m, previous, through_zyte=False, *, check=None):
    """Fetch one observation with actual UTC check times, independent of --as-of."""
    check = check if check is not None else {}
    check.update(started_at=timestamp(), mode="live", receipts=[])
    try:
        result = _fetch(m, previous, through_zyte, check["receipts"])
    except (RuntimeError, ValueError, OSError, ET.ParseError) as error:
        check.update(completed_at=timestamp(), outcome="error", error=str(error))
        raise
    absent = result["status"] == "absent" or (result["status"] == "page" and result["page_status"] == "no_meeting_data")
    check.update(completed_at=timestamp(), outcome="not_found" if absent else "present")
    result["last_check"] = check
    if any(receipt["outcome"] == "retrieved" for receipt in check["receipts"]):
        result["retrieved_at"] = check["completed_at"]
    return result


def _fetch(m, previous, through_zyte, receipts):
    candidates = list(dict.fromkeys(previous.get("urls", []) + addresses(m)))
    root, url = fetch_xml(candidates, "committee-meeting", through_zyte, receipts)
    page, page_url = "", f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={m['eventId']}"
    if root is None:
        response = request(page_url, through_zyte, receipts)
        page = response.content.decode("utf-8", "replace") if response.status_code == 200 else ""
        extra = [u for u in addresses(m, page=page) if u not in candidates]
        root, url = fetch_xml(extra, "committee-meeting", through_zyte, receipts)
        candidates += extra
        if root is None and page and not any(s in page for s in ("DivMeetingContent", "No meeting data is available")):
            next(r for r in receipts if r["url"] == page_url)["outcome"] = "unrecognized_page"
            raise ValueError(f"Unrecognized House meeting page for {m['eventId']}")
    wlist, wurl = None, ""
    if root is not None:
        bases = [url] + [u for u in candidates if f"/{root.get('meeting-type')}-" in u] + addresses(m, root)
        wlist, wurl = fetch_xml([re.sub(r"-(\d{8})\.xml$", r"-WList-\1.xml", u) for u in bases if u], "witness-list", through_zyte, receipts)
    result = parsed(root, wlist, page, "present" if wlist is not None else "absent")
    if page:
        # ``page`` was decoded for extraction; retain the original response
        # bytes, including a non-UTF-8 encoding, rather than the decoded copy.
        receipt = next(r for r in reversed(receipts) if r["url"] == page_url and r.get("content"))
        result.setdefault("source_bodies", {})["page_html"] = receipt["content"]
    retained = {body["sha256"] for body in result.get("source_bodies", {}).values()}
    for receipt in receipts:
        content = receipt.get("content")
        if content and content["sha256"] in retained:
            receipt["sha256"] = content["sha256"]
            del receipt["content"]  # One exact body; receipts identify it by digest.
    result["urls"] = [url] if url else candidates
    result["witness_url"], result["page_url"] = wurl, page_url if page else ""
    result["page_status"] = "no_meeting_data" if "No meeting data is available" in page else "present" if page else "not_retrieved"
    return result


def main(meetings, gpo_path, state_dir, output_dir, seed_cache=None, offline=False, as_of=None,
         refresh_limit=400, limit=None, zyte=False, threads=1):
    """Offline mode uses saved usable entries or seed inputs, still writes state/CSVs,
    and raises for selected entries with no usable result. It never refreshes HTTP.

    See docs/congress-api-contracts.md#offline-behavior.
    """
    if threads < 1 or (threads > 1 and not zyte):
        raise ValueError("Direct House requests use one worker; parallel backfills require --zyte")
    ms, gpo = read_meetings(meetings), read_csv(gpo_path)
    path = state_dir / "house.json.gz"
    state = read_state(path)
    prints = match_prints(ms, gpo)
    selected = [m for m in ms if lacking(m, prints[m["eventId"]])]
    totals, errors = collections.Counter(selected=len(selected)), []
    if seed_cache:
        for m in selected:
            if (m["eventId"] not in state or state[m["eventId"]].get("status") == "error") and (result := seed(m, seed_cache)) is not None:
                state[m["eventId"]] = {**result, "checked": as_of.isoformat(), "version": m.get("updateDate", "")}
                totals["seeded"] += 1
    # A parser upgrade joins the bounded unchanged-record queue. It must not
    # turn an old seed into thousands of immediate requests.
    pending = [m for m in selected if state.get(m["eventId"], {}).get("status") == "error"
               or state.get(m["eventId"], {}).get("evidence", {}).get("schema_version") != SCHEMA_VERSION
               or due(state.get(m["eventId"]), m["date"], m.get("updateDate", ""), as_of)]
    changed = [m for m in pending if state.get(m["eventId"], {}).get("version") != m.get("updateDate", "")]
    aged = [m for m in pending if m not in changed]
    aged.sort(key=lambda m: (state.get(m["eventId"], {}).get("checked", ""), m["eventId"]))
    todo = (changed + aged[:refresh_limit])[:limit] if not offline else []
    def fetch_one(m):
        check = {}
        try:
            return fetch(m, state.get(m["eventId"], {}), zyte, check=check), "", check
        except (RuntimeError, ValueError, OSError, ET.ParseError) as error:
            return None, f"{m['eventId']}: {error}", check
    with ThreadPoolExecutor(threads) as pool:
        for m, (result, error, check) in zip(todo, pool.map(fetch_one, todo)):
            if error:
                errors.append(error)
                # Preserve the last usable parsed observation after a failed
                # check. A first-check failure remains explicitly incomplete.
                previous = state.setdefault(m["eventId"], {"documents": [], "witnesses": [], "amendments": [], "status": "error"})
                previous["last_check"] = check
            else:
                state[m["eventId"]] = {**result, "checked": as_of.isoformat(), "version": m.get("updateDate", "")}
                totals["fetched meetings"] += 1
    write_state(path, state)
    missing = [m["eventId"] for m in selected if m["eventId"] not in state or state[m["eventId"]].get("status") == "error"]
    if missing or errors:
        raise RuntimeError(f"House source incomplete: {len(missing)} missing, {len(errors)} failed; {errors[:5] or missing[:5]}")
    attached = {e: attached_prints(d[2] for d in saved["documents"]) for e, saved in state.items()}
    prints = match_prints(ms, gpo, attached)
    found_docs, found_witnesses, found_amendments = [], [], []
    for m in selected:
        e = m["eventId"]
        if not lacking(m, prints[e]):
            continue
        saved = state[e]
        have = {d["url"] for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or []) if d.get("url")}
        found_docs += list(document_rows(saved, e, have))
        if not m.get("witnesses"):
            found_witnesses += [{"event_id": e, **w} for w in saved["witnesses"]]
        found_amendments += [{"event_id": e, **a} for a in saved["amendments"]]
    for name, rows, fields in (("house_documents_found", found_docs, DOCUMENT_FIELDS), ("house_witnesses_found", found_witnesses, WITNESS_FIELDS),
                                ("house_amendments_found", found_amendments, AMENDMENT_FIELDS)):
        write_csv(output_dir / f"{name}.csv", rows, fields)
        totals[name] = len(rows)
    totals["refreshes deferred"] = max(0, len(pending) - len(todo))
    print(dict(totals), dict(http.COUNTS))
