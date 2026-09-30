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
import argparse
import collections
import datetime as dt
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from congress_api import http
from congress_api.house.evidence import SCHEMA_VERSION, parse_retained_evidence
from congress_api.models.content import RawContent
from congress_api.models.house import HouseParsedRecord
from congress_api.house.source import parse_house_meeting, parse_house_witnesses
from congress_api.house.repository import (AMENDMENT_FIELDS, WITNESS_FIELDS, addresses, cached_xml, document_kind, documents,
    read_xml, witness_area, witness_rows, witnesses)
from congress_api.meeting_rules import is_hearing
from congress_api.inventory.common import (NOT_HELD, TRANSCRIPT, due, nonnegative, read_csv, read_meetings,
    read_state, source_args, write_csv, write_state)
from congress_api.inventory.prints import attached_prints, match_prints

DOCUMENT_FIELDS = "event_id kind name url document_type source_group source_selector owning_witness_selector add_date publish_date".split()


def document_rows(saved, event, have=()):
    """Compact recovery report: one row per file missing from the API listing.

    Congress.gov mirrors House files under a different URL, so this report uses
    filenames within the same meeting to suppress already-listed renditions.
    Compare each format separately: a listed PDF cannot suppress its XML. Full
    source URLs, metadata, removed entries and grouping remain in gzip state;
    this report's overlap check does not merge material identities.
    """
    normalize = lambda url: url.replace("http://", "https://")
    have = {normalize(url).rsplit("/", 1)[-1] for url in have}
    groups = saved.get("evidence", {}).get("document_groups")
    if groups is None:
        groups = [{"legacy_kind": kind, "description": name, "files": [{"url": url}]}
                  for kind, name, url, _ in saved.get("documents", [])]
    owners = {w.get("selector"): w.get("name", "") for w in saved.get("evidence", {}).get("witness_observations", []) if w.get("selector")}
    for group in groups:
        if not group.get("active", True):
            continue
        files = [file for file in group.get("files", []) if file.get("active", True) and file.get("url")]
        code, description = group.get("type", ""), group.get("description", "")
        owner = owners.get(group.get("owning_witness_selector"))
        attributes = group.get("metadata", {}).get("attributes", {})
        for file in files:
            url = normalize(file["url"])
            if url.rsplit("/", 1)[-1] in have:
                continue
            kind = group.get("legacy_kind") or document_kind(code, description, url)
            yield {"event_id": event, "kind": kind,
                   "name": description or (f"{kind}: {owner}" if owner else url.rsplit("/", 1)[-1]), "url": url,
                   "document_type": code, "source_group": group.get("source", ""),
                   "source_selector": group.get("selector", ""), "owning_witness_selector": group.get("owning_witness_selector") or "",
                   "add_date": attributes.get("add-date", ""), "publish_date": attributes.get("publish-date", "")}


def lacking(m, packages):
    transcript = any(d.get("url") and TRANSCRIPT.search(f"{d.get('documentType')} {d.get('name')}") for d in m.get("meetingDocuments") or [])
    return m.get("chamber") != "Senate" and not NOT_HELD.match(m.get("title") or "") and (
        not (m.get("meetingDocuments") or m.get("witnessDocuments"))
        or (is_hearing(m) and not m.get("witnesses")) or not (packages or transcript))


def parse_house_record(root, wlist, page, wstatus) -> HouseParsedRecord:
    root = parse_house_meeting(root) if root is not None else None
    wlist = parse_house_witnesses(wlist) if wlist is not None else None
    docs, amendments = read_xml(root, wlist) if root is not None else ([], [])
    listed = witness_rows(wlist) if wlist is not None else []
    fallback = page if root is None else witness_area(page) if wstatus == "unfetched" else ""
    if fallback:
        docs += [(k, n, u, {u.rsplit("/", 1)[-1]}) for k, n, u in documents(fallback)]
        listed = [dict(zip(WITNESS_FIELDS[1:5], w)) for w in witnesses(page)]
    bodies = {name: node.raw_content for name, node in (("meeting_xml", root), ("witness_xml", wlist))
              if node is not None and node.raw_content is not None}
    if page:
        bodies['page_html'] = RawContent.from_bytes(page.encode('utf-8'), 'text/html')
    return HouseParsedRecord.model_validate({"documents": [[k, n, u, sorted(files)] for k, n, u, files in docs], "witnesses": listed,
            "amendments": amendments, "xml_update": root.get("update-date", "") if root is not None else "",
            "status": "xml" if root is not None else "page" if page else "absent", "witness_status": wstatus,
            "evidence": parse_retained_evidence(root, wlist, fallback), **({"source_bodies": bodies} if bodies else {})})


def parsed(root, wlist, page, wstatus):
    return parse_house_record(root, wlist, page, wstatus).source_dict()


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


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--gpo-path", type=Path, required=True)
    p.add_argument("--refresh-limit", type=nonnegative, default=400)
    p.add_argument("--limit", type=nonnegative, help="bound live meeting fetches; incomplete backfills fail")
    p.add_argument("--zyte", action="store_true", help="metered backfill through ZYTE_TOKEN")
    p.add_argument("--threads", type=int, help="workers: one directly, default 16 with --zyte")
    args = p.parse_args()
    args.threads = args.threads if args.threads is not None else 16 if args.zyte else 1
    if args.threads < 1 or (args.threads > 1 and not args.zyte):
        p.error("Direct House requests use one worker; parallel backfills require --zyte")
    main(**vars(args))
