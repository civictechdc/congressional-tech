"""
Fetch metadata and links for official GPO hearing transcripts from GovInfo.

GovInfo's "Congressional Hearings" collection (CHRG) holds the official printed
transcript of each hearing, usually published a year or more after it was held.
We store one row per hearing: metadata plus links to the HTML text and the PDF.
The transcript text is read for the days it was held. With --evidence-path, the
upstream XML/HTML bytes are retained separately from this CSV.

Data flow:
    1. api.govinfo.gov/collections/CHRG/{since}   -> package ids + lastModified
       (needs a data.gov API key)
    2. www.govinfo.gov/metadata/pkg/{id}/mods.xml -> hearing metadata
       (public; one request per new or changed hearing)
    3. www.govinfo.gov/content/pkg/{id}/html/{id}.htm -> the day headers in the transcript
       (public; one request per new or changed hearing since the 113th Congress)

GPO's held date is one date per package. A volume that prints several hearings carries
only the first (or, for Appropriations volumes, the first day of the Congress), and a
few single hearings carry the wrong date. The transcript's own day headers
("WEDNESDAY, FEBRUARY 25, 2015") say when the hearings were held, so they are recorded
in `hearing_dates` wherever they say something other than GPO's one date. Where GPO names
no committee, the title page does ("COMMITTEE ON THE JUDICIARY / UNITED STATES SENATE").

The MODS record carries the committee's system code (e.g. hsvr00, the same codes
as youtube-accounts.csv) and, for many hearings since the 115th Congress, the
Congress.gov event id (the id committees put in YouTube descriptions).

Runs incrementally: new and modified packages are fetched, plus a bounded number
of unchanged rows needing a newer parser or retained upstream evidence. The small
CSV remains the summary; --evidence-path retains XML/HTML bytes on pipeline-data.
"""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from congress_shared.auth import load_congress_api_key
from congress_shared.globals import CONGRESS_METADATA, DEFAULT_GPO_HEARINGS_FILE

from congress_api.matching.gpo_committees import clean_rows, merge_cached_row
from congress_api.models.gpo import GpoCollectionPage, GpoTranscriptDates
from congress_api.parsers.gpo_hearings import (
    PACKAGE_ID_REGEX,
    PARSER_VERSION,
    committee_on_title_page,
    hearing_days,
    is_multi_hearing_volume,
    parse_mods,
)
from congress_api.retention import gpo as upstream_evidence
from congress_api.retention.gpo import read_csv, write_csv, write_pending
from congress_api.transport.http import get_with_retry

GOVINFO_API = "https://api.govinfo.gov"


GOVINFO_CONTENT = "https://www.govinfo.gov"


## first listing when there's no existing CSV
FULL_HISTORY_START = "1990-01-01T00:00:00Z"


## re-list a little before the newest lastModified we have, to be safe
RELIST_OVERLAP = timedelta(days=2)


## transcripts are read for their hearing days from this Congress on: the first with
##  committee channels and Congress.gov meeting records to match the days against
TEXT_DAYS_FROM_CONGRESS = 113


def main(
    output_path: Path = DEFAULT_GPO_HEARINGS_FILE,
    chambers: str = "hsj",
    min_congress: int | None = None,
    nthreads: int = 4,
    full_relist: bool = False,
    refresh_limit: int = 100,
    evidence_path: Path | None = None,
) -> None:
    if nthreads < 1:
        raise ValueError("nthreads must be positive")
    if refresh_limit < 0:
        raise ValueError("refresh_limit must be nonnegative")
    api_key = load_congress_api_key()
    if min_congress is None:
        ## match the congresses covered by the YouTube report
        min_congress = min(int(c) for c in CONGRESS_METADATA)

    existing = read_csv(output_path)
    upstream = upstream_evidence.read(evidence_path)
    # Keep unfinished packages beside retained evidence in CI, or beside the CSV
    # for local runs. A later successful package must not advance past a failure.
    pending_path = Path(str(evidence_path or output_path) + '.pending.json')
    pending = json.loads(pending_path.read_text()) if pending_path.exists() else {}
    since = FULL_HISTORY_START
    ## a full relist still only fetches hearings that are new or changed; use
    ##  it after widening --chambers or --min-congress
    if existing and not full_relist:
        newest = max(row["last_modified"] for row in existing.values())
        since = (parse_timestamp(newest) - RELIST_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(f"{len(existing)} hearings on file; listing changes since {since}")

    ## figure out which packages are new or changed
    to_fetch = {package: modified for package, modified in pending.items()
                if (match := PACKAGE_ID_REGEX.fullmatch(package)) and match[2] in chambers and int(match[1]) >= min_congress}
    listings = {}
    for package in list_collection(since, api_key):
        match = PACKAGE_ID_REGEX.match(package["packageId"])
        if not match or match[2] not in chambers:
            continue
        if int(match[1]) < min_congress:
            continue
        listings[package['packageId']] = {
            'payload': package, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'url': f'{GOVINFO_API}/collections/CHRG/{since}',
        }
        old = existing.get(package["packageId"])
        if old is None or old["last_modified"] != package["lastModified"]:
            to_fetch[package["packageId"]] = package["lastModified"]
    stale = sorted((row for row in existing.values()
                    if (row.get("parser_version") != PARSER_VERSION
                        or (evidence_path is not None and not upstream.get(row["package_id"], {}).get("mods")))
                    and PACKAGE_ID_REGEX.match(row["package_id"])[2] in chambers
                    and int(row["congress"]) >= min_congress
                    and row["package_id"] not in to_fetch),
                   key=lambda row: (-int(row["congress"]), row["package_id"]))
    for row in stale[:refresh_limit]:
        to_fetch[row["package_id"]] = row["last_modified"]
    pending.update(to_fetch)
    write_pending(pending, pending_path)
    logging.info(f"Fetching metadata for {len(to_fetch)} new, changed or parser-stale hearings")

    failures = []
    session = requests.Session()

    def fetch_one(item):
        package_id, last_modified = item
        try:
            mods = get_with_retry(
                session, f"{GOVINFO_CONTENT}/metadata/pkg/{package_id}/mods.xml"
            ).content
            captured = dict(upstream.get(package_id, {}))
            captured['package_id'] = package_id
            observation = upstream_evidence.observation(mods,
                f"{GOVINFO_CONTENT}/metadata/pkg/{package_id}/mods.xml", "application/xml",
                retrieved_at=datetime.now(timezone.utc).isoformat())
            if package_id in listings:
                captured['listing'] = listings[package_id]
            try:
                hearing = parse_mods(package_id, mods, last_modified)
            except Exception as ex:
                # Keep rejected response bytes without replacing the last valid
                # MODS record or marking its CSV row freshly parsed.
                captured['failed_mods'] = {**observation, 'error': str(ex)}
                if evidence_path is not None:
                    upstream[package_id] = captured
                raise
            captured.update(parser_version=PARSER_VERSION, mods=observation)
            captured.pop('failed_mods', None)
            captured['transcripts'] = dict(captured.get('transcripts', {}))
            if evidence_path is not None:
                upstream[package_id] = captured
            old = existing.get(package_id)
            # Parser repairs must not discard transcript-derived corrections or
            # turn a small metadata refresh into a full transcript download.
            unchanged = old and old.get("last_modified") == last_modified
            if unchanged:
                hearing.hearing_dates = old.get("hearing_dates", "")
                hearing.text_read = old.get("text_read", "")
                hearing.committee_name = hearing.committee_name or old.get("committee_name", "")
            if hearing.congress >= TEXT_DAYS_FROM_CONGRESS and not (unchanged and hearing.text_read):
                read = read_transcript(session, asdict(hearing), captured["transcripts"] if evidence_path else None)
                hearing.hearing_dates, hearing.text_read = read["hearing_dates"], "yes"
                hearing.committee_name = hearing.committee_name or read["committee_name"]
            result = asdict(hearing)
            if unchanged:
                result = merge_cached_row(old, result, live_refresh=True)
                result.update(parser_version=PARSER_VERSION, hearing_dates=hearing.hearing_dates,
                              text_read=hearing.text_read, witness_count=hearing.witness_count)
            return result
        except Exception as ex:
            failures.append(f"{package_id}: {ex!r}")
            return None

    completed = set()
    with ThreadPoolExecutor(nthreads) as pool:
        for i, hearing in enumerate(pool.map(fetch_one, to_fetch.items()), 1):
            if hearing is not None:
                existing[hearing["package_id"]] = hearing
                completed.add(hearing["package_id"])
            if i % 500 == 0:
                logging.info(f"Fetched {i}/{len(to_fetch)}")

    ## one-time backfill: hearing days for transcripts fetched before they were read
    backfill = sorted((r for r in existing.values()
                if int(r["congress"]) >= max(TEXT_DAYS_FROM_CONGRESS, min_congress)
                and PACKAGE_ID_REGEX.match(r["package_id"])[2] in chambers and not r.get("text_read")),
                key=lambda row: (-int(row["congress"]), row["package_id"]))[:refresh_limit]
    if backfill:
        logging.info(f"Reading hearing days from {len(backfill)} transcripts")

        def fill(row):
            try:
                captured = upstream.setdefault(row['package_id'], {'package_id': row['package_id']}) if evidence_path else {}
                read = read_transcript(session, row, captured.setdefault('transcripts', {}) if evidence_path else None)
                row["hearing_dates"], row["text_read"] = read["hearing_dates"], "yes"
                row["committee_name"] = row["committee_name"] or read["committee_name"]
            except Exception as ex:
                failures.append(f"{row['package_id']} hearing days: {ex!r}")

        with ThreadPoolExecutor(nthreads) as pool:
            list(pool.map(fill, backfill))

    clean_rows(existing)

    ## write what we have even on failure, so a local run keeps its progress
    if evidence_path is not None:
        upstream_evidence.write(upstream, evidence_path)
    write_csv(existing, output_path)
    write_pending({package: modified for package, modified in pending.items() if package not in completed}, pending_path)
    logging.info(f"Wrote {len(existing)} hearings to {output_path}")

    if failures:
        logging.error(
            f"{len(failures)} hearing(s) failed:\n  " + "\n  ".join(failures[:50])
        )
        sys.exit(1)


def list_collection(since: str, api_key: str):
    """Yield every CHRG package modified since `since` (paged, 1000 at a time)."""
    url = f"{GOVINFO_API}/collections/CHRG/{since}"
    params = {"pageSize": 1000, "offsetMark": "*", "api_key": api_key}
    session = requests.Session()
    while url:
        page = GpoCollectionPage.model_validate(get_with_retry(session, url, params=params).json())
        yield from (package.source_dict() for package in page.packages)
        ## nextPage already carries the paging params, minus the key
        url = page.next_page
        params = {"api_key": api_key}


def read_transcript(session, row: dict, evidence: dict | None = None) -> dict:
    """What the transcript itself says: `hearing_dates`, the hearing days when they say more than
    GPO's held date, and `committee_name`, the committee on its title page."""
    volume = is_multi_hearing_volume(row["title"])
    days, names = set(), []
    urls = str(row.get('html_urls') or row.get('html_url') or '').split(';')
    for url in dict.fromkeys(u for u in urls if u):
        response = get_with_retry(session, url)
        text = response.text
        if evidence is not None:
            evidence[url] = upstream_evidence.observation(response.content, url, 'text/html',
                retrieved_at=datetime.now(timezone.utc).isoformat())
        days.update(hearing_days(text, int(row['congress']), volume))
        name = committee_on_title_page(text)
        if name:
            names.append(name)
    days = sorted(days)
    tells_more = days and (days != [row["held_date"]] or volume)
    return GpoTranscriptDates(hearing_dates=";".join(days) if tells_more else "",
                              committee_name=names[0] if names else "").source_dict()


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
