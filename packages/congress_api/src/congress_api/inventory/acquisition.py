"""Acquire missing inventory evidence while retaining usable prior observations.

Only this inventory module performs HTTP. Callers can pass get= to exercise
acquisition without a network client or CLI flag. Offline reads accept saved
empty/absent observations, import local seed bytes, and raise for missing input.
See docs/congress-api-contracts.md for the per-command offline behavior.
"""
import datetime as dt
import re
from xml.etree.ElementTree import ParseError

from pypdf.errors import PyPdfError

from congress_api import http
from congress_api.inventory import witness_lists
from congress_api.inventory.common import due
from congress_api.models.content import RawContent
from congress_api.senate.isvp import archive_url, live_url, player_url


def timestamp():
    return dt.datetime.now(dt.UTC).isoformat()


def get_witnesses(key, url, state, version, day, today, offline, seed_cache=None, package=False, *, get=http.get_with_retry):
    saved = state.get(key)
    complete = saved is not None and "people" in saved
    if complete:
        if offline:
            return saved["people"]
        failed = (saved.get("last_check") or {}).get("outcome") == "error"
        # A missing file can appear without a package revision. Retry negatives
        # weekly, and failed refreshes next run, even for an unchanged print.
        unchanged_print = package and saved.get("version") == version and not saved.get("absent")
        if not failed and unchanged_print:
            return saved["people"]
        if not failed and saved.get("version") == version:
            expired = ((today - dt.date.fromisoformat(saved["checked"])).days >= 7
                       if saved.get("absent") else due(saved, day, version, today))
            if not expired:
                return saved["people"]
    data = None
    if not complete and seed_cache:
        path = seed_cache / "mods" / f"{key}.xml" if package else seed_cache / "witness_lists" / re.sub(r"\W+", "_", url.split("/meeting/")[-1])
        if path.exists():
            data = path.read_bytes()
    imported = data is not None
    if not imported and offline:
        raise RuntimeError(f"Missing saved witness source: {key}")
    check = {"mode": "cache_import" if imported else "live", "url": url, "started_at": timestamp()}
    try:
        if not imported:
            response = get(None, url, allowed=(200, 404))
            check.update(completed_at=timestamp(), status_code=response.status_code)
            data = response.content if response.status_code == 200 else None
        evidence = (witness_lists.mods_observation(data) if package else witness_lists.pdf_observation(data)) if data is not None else {}
    except (ValueError, RuntimeError, OSError, ParseError, PyPdfError) as error:
        check.update(completed_at=timestamp(), outcome="error", error=str(error))
        if data is not None:
            check['content'] = RawContent.from_bytes(data, 'application/xml' if package else 'application/pdf').source_dict()
        state[key] = {**(saved or {}), "url": url, "last_check": check}
        raise
    check.update(completed_at=check.get("completed_at") or timestamp(), outcome="present" if data is not None else "not_found")
    people = evidence.get("people", [])
    state[key] = {"people": people, "url": url, "version": version, "checked": today.isoformat(), "absent": data is None,
                  "text_present": evidence.get("text_present", False), **evidence, "last_check": check, "observation_check": check}
    if imported:
        state[key]["imported_at"] = check["completed_at"]
    elif data is not None:
        state[key]["retrieved_at"] = check["completed_at"]
    return people


def probe_day(comm, day, *, get=http.get_with_retry):
    date = dt.date.fromisoformat(day)
    found = []
    for filename in (f"{comm}{date:%m%d%y}", f"{comm}A{date:%m%d%y}", f"{comm}B{date:%m%d%y}", f"{comm}{date:%m%d%y}p"):
        for url in (archive_url(comm, filename), live_url(comm, filename)):
            response = get(None, url, method="HEAD", allowed=(200, 404))
            if response.status_code == 200:
                found.append(player_url(comm, filename))
                break
    return found


def probe_days(days, probes, today, offline=False, *, get=http.get_with_retry):
    """Save complete day answers once; defer days younger than seven days.

    Earlier completed days survive a later failure. A partial failed day does
    not become a saved absence and remains eligible on the next run.
    """
    count = 0
    for comm, day in days:
        key = f"{comm}|{day}"
        if key in probes or (today - dt.date.fromisoformat(day)).days < 7:
            continue
        if offline:
            raise RuntimeError(f"Missing saved Senate probe: {key}")
        probes[key] = {"urls": probe_day(comm, day, get=get), "checked": today.isoformat(), "source": "HEAD"}
        count += 1
    return count
