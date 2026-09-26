"""
Fetch metadata and links for official GPO hearing transcripts from GovInfo.

GovInfo's "Congressional Hearings" collection (CHRG) holds the official printed
transcript of each hearing, usually published a year or more after it was held.
We store one row per hearing: metadata plus links to the HTML text and the PDF.
The transcript text itself is not downloaded; the links point to it.

Data flow:
    1. api.govinfo.gov/collections/CHRG/{since}   -> package ids + lastModified
       (needs a data.gov API key)
    2. www.govinfo.gov/metadata/pkg/{id}/mods.xml -> hearing metadata
       (public; one request per new or changed hearing)

The MODS record carries the committee's system code (e.g. hsvr00, the same codes
as youtube-accounts.csv) and, for many hearings since the 115th Congress, the
Congress.gov event id (the id committees put in YouTube descriptions).

Runs incrementally: the output CSV doubles as the cache, and only packages
modified since the newest lastModified in it are re-fetched.
"""

import argparse
import csv
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from congress_shared.auth import load_congress_api_key
from congress_shared.globals import CONGRESS_METADATA, DEFAULT_GPO_HEARINGS_FILE

GOVINFO_API = "https://api.govinfo.gov"
GOVINFO_CONTENT = "https://www.govinfo.gov"
MODS_NS = {"m": "http://www.loc.gov/mods/v3"}

## e.g. CHRG-118hhrg57177 -> congress 118, chamber h, jacket 57177
PACKAGE_ID_REGEX = re.compile(r"^CHRG-(\d+)([hsj])hrg(\w+)$")
CHAMBERS = {"h": "house", "s": "senate", "j": "joint"}

## first listing when there's no existing CSV
FULL_HISTORY_START = "1990-01-01T00:00:00Z"
## re-list a little before the newest lastModified we have, to be safe
RELIST_OVERLAP = timedelta(days=2)


## define columns in the output CSV
@dataclass
class GpoHearing:
    package_id: str
    congress: int
    chamber: str
    event_id: str
    committee_code: str
    committee_name: str
    subcommittees: str
    title: str
    held_date: str
    ## when GovInfo added it; for hearings before ~2009 this is when GPO
    ##  digitized old records, not when the transcript first came out
    date_ingested: str
    days_to_govinfo: str
    serial: str
    witness_count: int
    html_url: str
    pdf_url: str
    last_modified: str


def main(
    output_path: Path = DEFAULT_GPO_HEARINGS_FILE,
    chambers: str = "hj",
    min_congress: int | None = None,
    nthreads: int = 4,
    full_relist: bool = False,
) -> None:
    api_key = load_congress_api_key()
    if min_congress is None:
        ## match the congresses covered by the YouTube report
        min_congress = min(int(c) for c in CONGRESS_METADATA)

    existing = read_csv(output_path)
    since = FULL_HISTORY_START
    ## a full relist still only fetches hearings that are new or changed; use
    ##  it after widening --chambers or --min-congress
    if existing and not full_relist:
        newest = max(row["last_modified"] for row in existing.values())
        since = (parse_timestamp(newest) - RELIST_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
    logging.info(f"{len(existing)} hearings on file; listing changes since {since}")

    ## figure out which packages are new or changed
    to_fetch = {}
    for package in list_collection(since, api_key):
        match = PACKAGE_ID_REGEX.match(package["packageId"])
        if not match or match[2] not in chambers:
            continue
        if int(match[1]) < min_congress:
            continue
        old = existing.get(package["packageId"])
        if old is None or old["last_modified"] != package["lastModified"]:
            to_fetch[package["packageId"]] = package["lastModified"]
    logging.info(f"Fetching metadata for {len(to_fetch)} new or changed hearings")

    failures = []
    session = requests.Session()

    def fetch_one(item):
        package_id, last_modified = item
        try:
            mods = get_with_retry(
                session, f"{GOVINFO_CONTENT}/metadata/pkg/{package_id}/mods.xml"
            ).content
            return parse_mods(package_id, mods, last_modified)
        except Exception as ex:
            failures.append(f"{package_id}: {ex!r}")
            return None

    with ThreadPoolExecutor(nthreads) as pool:
        for i, hearing in enumerate(pool.map(fetch_one, to_fetch.items()), 1):
            if hearing is not None:
                existing[hearing.package_id] = asdict(hearing)
            if i % 500 == 0:
                logging.info(f"Fetched {i}/{len(to_fetch)}")

    ## write what we have even on failure, so a local run keeps its progress
    write_csv(existing, output_path)
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
        page = get_with_retry(session, url, params=params).json()
        yield from page["packages"]
        ## nextPage already carries the paging params, minus the key
        url = page.get("nextPage")
        params = {"api_key": api_key}


def get_with_retry(session, url, params=None, attempts=4) -> requests.Response:
    for attempt in range(attempts):
        response = session.get(url, params=params, timeout=60)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            time.sleep(2 ** (attempt + 1))
            continue
        response.raise_for_status()
        return response


def parse_mods(package_id: str, mods: bytes, last_modified: str) -> GpoHearing:
    """Pull the hearing-level fields out of a GovInfo MODS record."""
    root = ET.fromstring(mods)
    congress, chamber, _ = PACKAGE_ID_REGEX.match(package_id).groups()

    ## hearing-level data lives in the root's own <extension> blocks; the
    ##  <relatedItem> granules below repeat some of it, so don't search deeper
    def ext_all(tag):
        return root.findall(f"m:extension/m:{tag}", MODS_NS)

    def ext_text(tag):
        found = ext_all(tag)
        return found[0].text.strip() if found and found[0].text else ""

    ## a joint hearing lists several committees; the first is the lead
    committees = ext_all("congCommittee")
    ## codes are lowercase in youtube-accounts.csv (a few MODS records aren't)
    committee_code = committees[0].get("authorityId", "").lower() if committees else ""
    committee_name = ""
    subcommittees = []
    for committee in committees:
        if not committee_name:
            committee_name = committee.findtext(
                "m:name[@type='authority-standard']", "", MODS_NS
            ).strip()
        subcommittees += [
            name.text.strip()
            for name in committee.findall("m:subCommittee/m:name", MODS_NS)
            if name.text
        ]

    ## some hearings span several days; the first is when it started
    held_dates = sorted(el.text.strip() for el in ext_all("heldDate") if el.text)
    held_date = held_dates[0] if held_dates else ""
    date_ingested = ext_text("dateIngested")
    days_to_govinfo = ""
    if held_date and date_ingested:
        days_to_govinfo = str(
            (date.fromisoformat(date_ingested) - date.fromisoformat(held_date)).days
        )

    title = ext_text("searchTitle") or root.findtext(
        "m:titleInfo/m:title", "", MODS_NS
    ).strip()

    return GpoHearing(
        package_id=package_id,
        congress=int(congress),
        chamber=CHAMBERS[chamber],
        event_id=ext_text("eventId"),
        committee_code=committee_code,
        committee_name=committee_name,
        subcommittees="; ".join(dict.fromkeys(subcommittees)),
        title=" ".join(title.split()),
        held_date=held_date,
        date_ingested=date_ingested,
        days_to_govinfo=days_to_govinfo,
        serial=ext_text("preferredCitation"),
        witness_count=len(ext_all("witness")),
        html_url=f"{GOVINFO_CONTENT}/content/pkg/{package_id}/html/{package_id}.htm",
        pdf_url=f"{GOVINFO_CONTENT}/content/pkg/{package_id}/pdf/{package_id}.pdf",
        last_modified=last_modified,
    )


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def read_csv(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["package_id"]: row for row in csv.DictReader(handle)}


def write_csv(rows: dict[str, dict], path: Path) -> None:
    field_names = [field.name for field in fields(GpoHearing)]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_names)
        writer.writeheader()
        ## sort so weekly diffs only show real changes
        for package_id in sorted(rows):
            writer.writerow(rows[package_id])


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Fetch metadata and transcript links for GPO hearing transcripts."
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_GPO_HEARINGS_FILE,
        help="Path to the output CSV (also used as the cache between runs).",
    )
    parser.add_argument(
        "--chambers",
        default="hj",
        help="Which chambers to include: any of h (house), s (senate), j (joint).",
    )
    parser.add_argument(
        "--full-relist",
        action="store_true",
        help="List the whole collection instead of only recent changes (after widening filters).",
    )
    parser.add_argument(
        "--min-congress",
        type=int,
        default=None,
        help="Oldest congress to include (default: the oldest in congress_metadata.json).",
    )
    parser.add_argument(
        "--nthreads",
        type=int,
        default=4,
        help="Concurrent metadata downloads.",
    )

    ## ignore the unknown args (e.g. --congress-api-key, read by the key loader)
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
