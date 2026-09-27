"""house-meeting-records: fill House/joint meeting gaps from docs.house.gov.

Read the meeting export and GPO table, then meeting XML and witness-list XML
(page fallback). Write house_documents_found.csv, house_witnesses_found.csv and
house_amendments_found.csv to --output-dir. Keep parsed results, source URLs,
XML update-date, Congress.gov updateDate, fetch date and confirmed absences in
--state-dir/house.json.gz. --seed-cache imports the research cache read-only.

Readers select from source inputs; the inventory is not an input. An attached
print discovered here can settle selection during this same pass. Changed and
new records are fetched first; at most --refresh-limit unchanged records are
refreshed per run, oldest checks first. --zyte is only a backfill option.
"""
import argparse
import collections
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from congress_api import http
from congress_api.house.repository import (AMENDMENT_FIELDS, WITNESS_FIELDS, addresses, cached_xml, documents,
    read_xml, witness_area, witness_rows, witnesses)
from congress_api.inventory.common import (NOT_HELD, TRANSCRIPT, due, kind, nonnegative, read_csv, read_meetings,
    read_state, source_args, write_csv, write_state)
from congress_api.inventory.prints import attached_prints, match_prints
from congress_api.xml import parse_xml

DOCUMENT_FIELDS = "event_id kind name url".split()


def lacking(m, packages):
    transcript = any(d.get("url") and TRANSCRIPT.search(f"{d.get('documentType')} {d.get('name')}") for d in m.get("meetingDocuments") or [])
    return m.get("chamber") != "Senate" and not NOT_HELD.match(m.get("title") or "") and (
        not (m.get("meetingDocuments") or m.get("witnessDocuments"))
        or (kind(m) == "hearing" and not m.get("witnesses")) or not (packages or transcript))


def parsed(root, wlist, page, wstatus):
    docs, amendments = read_xml(root, wlist) if root is not None else ([], [])
    listed = witness_rows(wlist) if wlist is not None else []
    fallback = page if root is None else witness_area(page) if wstatus == "unfetched" else ""
    if fallback:
        docs += [(k, n, u, {u.rsplit("/", 1)[-1]}) for k, n, u in documents(fallback)]
        listed = [dict(zip(WITNESS_FIELDS[1:5], w)) for w in witnesses(page)]
    return {"documents": [[k, n, u, sorted(files)] for k, n, u, files in docs], "witnesses": listed,
            "amendments": amendments, "xml_update": root.get("update-date", "") if root is not None else "",
            "status": "xml" if root is not None else "page" if page else "absent", "witness_status": wstatus}


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
    result["urls"] = addresses(m, root, page) if root is not None else addresses(m, page=page)
    result["seed"] = "research cache"
    return result


def fetch_xml(urls, expected, through_zyte):
    for url in dict.fromkeys(urls):
        response = http.get_with_retry(None, url, allowed=(200, 404), through_zyte=through_zyte)
        if response.status_code == 404:
            continue
        for attempt in range(3):
            try:
                root = parse_xml(response.content)
                if root.tag != expected:
                    raise ET.ParseError(f"unexpected root {root.tag}")
                break
            except ET.ParseError:
                if attempt == 2:
                    raise
                response = http.get_with_retry(None, url, through_zyte=through_zyte)
        if root.tag != expected:
            raise ValueError(f"Unexpected XML root from {url}: {root.tag}")
        return root, url
    return None, ""


def fetch(m, previous, through_zyte=False):
    candidates = list(dict.fromkeys(previous.get("urls", []) + addresses(m)))
    root, url = fetch_xml(candidates, "committee-meeting", through_zyte)
    page, page_url = "", f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={m['eventId']}"
    if root is None:
        response = http.get_with_retry(None, page_url, allowed=(200, 404), through_zyte=through_zyte)
        page = response.content.decode("utf-8", "replace") if response.status_code == 200 else ""
        extra = [u for u in addresses(m, page=page) if u not in candidates]
        root, url = fetch_xml(extra, "committee-meeting", through_zyte)
        candidates += extra
        if root is None and page and not any(s in page for s in ("DivMeetingContent", "No meeting data is available")):
            raise ValueError(f"Unrecognized House meeting page for {m['eventId']}")
    wlist, wurl = None, ""
    if root is not None:
        bases = [url] + [u for u in candidates if f"/{root.get('meeting-type')}-" in u] + addresses(m, root)
        wlist, wurl = fetch_xml([re.sub(r"-(\d{8})\.xml$", r"-WList-\1.xml", u) for u in bases if u], "witness-list", through_zyte)
    result = parsed(root, wlist, page, "present" if wlist is not None else "absent")
    result["urls"] = [url] if url else candidates
    result["witness_url"], result["page_url"] = wurl, page_url if page else ""
    return result


def main(meetings, gpo_path, state_dir, output_dir, seed_cache=None, offline=False, as_of=None,
         refresh_limit=400, limit=None, zyte=False, threads=1):
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
            if m["eventId"] not in state and (result := seed(m, seed_cache)) is not None:
                state[m["eventId"]] = {**result, "checked": as_of.isoformat(), "version": m.get("updateDate", "")}
                totals["seeded"] += 1
    pending = [m for m in selected if due(state.get(m["eventId"]), m["date"], m.get("updateDate", ""), as_of)]
    changed = [m for m in pending if state.get(m["eventId"], {}).get("version") != m.get("updateDate", "")]
    aged = [m for m in pending if m not in changed]
    aged.sort(key=lambda m: (state.get(m["eventId"], {}).get("checked", ""), m["eventId"]))
    todo = (changed + aged[:refresh_limit])[:limit] if not offline else []
    def fetch_one(m):
        try:
            return fetch(m, state.get(m["eventId"], {}), zyte), ""
        except (RuntimeError, ValueError, OSError, ET.ParseError) as error:
            return None, f"{m['eventId']}: {error}"
    with ThreadPoolExecutor(threads) as pool:
        for m, (result, error) in zip(todo, pool.map(fetch_one, todo)):
            if error:
                errors.append(error)
            else:
                state[m["eventId"]] = {**result, "checked": as_of.isoformat(), "version": m.get("updateDate", "")}
                totals["fetched meetings"] += 1
    write_state(path, state)
    missing = [m["eventId"] for m in selected if m["eventId"] not in state]
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
        have = {d["url"].rsplit("/", 1)[-1] for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or []) if d.get("url")}
        found_docs += [dict(zip(DOCUMENT_FIELDS, (e, k, n, u))) for k, n, u, files in saved["documents"] if not set(files) & have]
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
