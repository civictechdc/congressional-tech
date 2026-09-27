"""
Fetch metadata and links for official GPO hearing transcripts from GovInfo.

GovInfo's "Congressional Hearings" collection (CHRG) holds the official printed
transcript of each hearing, usually published a year or more after it was held.
We store one row per hearing: metadata plus links to the HTML text and the PDF.
The transcript text is read once per hearing, for the days it was held, and not kept;
the links point to it.

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

Runs incrementally: the output CSV doubles as the cache, and only packages
modified since the newest lastModified in it are re-fetched.
"""

import argparse
import collections
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
## transcripts are read for their hearing days from this Congress on: the first with
##  committee channels and Congress.gov meeting records to match the days against
TEXT_DAYS_FROM_CONGRESS = 113


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
    ## committee code exactly as GPO published it; `committee_code` is cleaned
    ##  (typos fixed, blanks filled from the committee name)
    committee_code_gpo: str = ""
    ## "hearing", or "errata" for errata cover sheets GPO files as separate packages
    record_type: str = "hearing"
    ## the hearing days the transcript's day headers give, ";"-separated, when they say
    ##  more than `held_date` does: every day of a multi-hearing volume, both days of a
    ##  two-day hearing, or the one day GPO got wrong. Blank when the transcript agrees
    ##  with `held_date` or has no day header (scanned prints).
    hearing_dates: str = ""
    ## "yes" once the transcript has been read for its day headers
    text_read: str = ""


def main(
    output_path: Path = DEFAULT_GPO_HEARINGS_FILE,
    chambers: str = "hsj",
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
            hearing = parse_mods(package_id, mods, last_modified)
            if hearing.congress >= TEXT_DAYS_FROM_CONGRESS:
                read = read_transcript(session, asdict(hearing))
                hearing.hearing_dates, hearing.text_read = read["hearing_dates"], "yes"
                hearing.committee_name = hearing.committee_name or read["committee_name"]
            return hearing
        except Exception as ex:
            failures.append(f"{package_id}: {ex!r}")
            return None

    with ThreadPoolExecutor(nthreads) as pool:
        for i, hearing in enumerate(pool.map(fetch_one, to_fetch.items()), 1):
            if hearing is not None:
                existing[hearing.package_id] = asdict(hearing)
            if i % 500 == 0:
                logging.info(f"Fetched {i}/{len(to_fetch)}")

    ## one-time backfill: hearing days for transcripts fetched before they were read
    backfill = [r for r in existing.values()
                if int(r["congress"]) >= TEXT_DAYS_FROM_CONGRESS and not r.get("text_read")]
    if backfill:
        logging.info(f"Reading hearing days from {len(backfill)} transcripts")

        def fill(row):
            try:
                read = read_transcript(session, row)
                row["hearing_dates"], row["text_read"] = read["hearing_dates"], "yes"
                row["committee_name"] = row["committee_name"] or read["committee_name"]
            except Exception as ex:
                failures.append(f"{row['package_id']} hearing days: {ex!r}")

        with ThreadPoolExecutor(nthreads) as pool:
            list(pool.map(fill, backfill))

    clean_rows(existing)

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
        committee_code_gpo=committee_code,
        record_type="errata" if "[ERRATA]" in title.upper() else "hearing",
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


VALID_CODE = re.compile(r"^[hsj][a-z]{3}\d\d$")
MONTHS = "January February March April May June July August September October November December".split()
WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
## a day header stands alone on its line: "WEDNESDAY, FEBRUARY 25, 2015", or in the prints
##  of some committees and in Appropriations volumes "Wednesday, February 25, 2015."
DAY = rf"({'|'.join(WEEKDAYS)}),\s+({'|'.join(MONTHS)})\s+(\d{{1,2}}),\s+(\d{{4}})"
DAY_HEADER = re.compile(rf"^[ \t]*{DAY}\.?[ \t]*$".replace("\\s+", "[ \\t]+"), re.IGNORECASE | re.MULTILINE)
## some volumes' HTML runs the page head and the day header together:
##  "DEPARTMENT OF HOMELAND SECURITY APPROPRIATIONS FOR 2022Wednesday, March 17, 2021DHS ..."
RUNNING_HEAD_DAY = re.compile(rf"APPROPRIATIONS FOR \d{{4}}\s*{DAY}", re.IGNORECASE)


def is_multi_hearing_volume(title: str) -> bool:
    """House Appropriations prints several hearings per volume ("... APPROPRIATIONS FOR 2016"),
    under a title that names none of them."""
    return bool(re.search(r"APPROPRIATIONS FOR \d{4}", title.upper()))


def hearing_days(text: str, congress: int, volume: bool = False) -> list[str]:
    """The days a transcript's day headers name, within the Congress's years. A hearing's print
    sets its day headers one way: where any is in capitals, a date in ordinary case standing
    alone is something else (the dateline of the hearing advisory that Ways and Means prints).
    A multi-hearing volume mixes the two, and every header counts. Headers are taken as printed:
    checking the weekday against the date drops more real days, whose weekday was misprinted,
    than false ones."""
    first_year = 1789 + 2 * (congress - 1)
    capitals, ordinary = set(), set()
    for header in list(DAY_HEADER.finditer(text)) + (list(RUNNING_HEAD_DAY.finditer(text)) if volume else []):
        _, month, day, year = header.groups()
        if first_year - 1 <= int(year) <= first_year + 2:
            try:
                date = datetime(int(year), [m.lower() for m in MONTHS].index(month.lower()) + 1, int(day)).date().isoformat()
            except ValueError:
                continue
            (capitals if header.group(0) == header.group(0).upper() else ordinary).add(date)
    return sorted(capitals | ordinary if volume else capitals or ordinary)


## the chamber line that closes a title page's committee block
CHAMBER_LINE = re.compile(r"^[ \t]*(?:UNITED STATES SENATE|U\.S\. SENATE|(?:U\.S\. )?HOUSE OF REPRESENTATIVES)[ \t]*$", re.MULTILINE)
PARENT_BODY = re.compile(r"(?<![A-Z])((?:COMMITTEE|COMMISSION|CAUCUS) ON [A-Z][A-Z,'\u2019 \-]*(?:\n[ \t]*[A-Z][A-Z,'\u2019 \-]*)?)")
SMALL_WORDS = {"on", "the", "and", "of", "for", "in", "to"}


def committee_on_title_page(text: str) -> str:
    """The committee a transcript's title page names, in GPO's style ("Committee on the Judiciary"), or "".
    The title page reads "BEFORE THE / SUBCOMMITTEE ON ... / OF THE / COMMITTEE ON THE JUDICIARY /
    UNITED STATES SENATE": the body wanted is the last one named before the chamber line."""
    chamber = CHAMBER_LINE.search(text[:8000])
    named = PARENT_BODY.findall(text[:chamber.start()]) if chamber else []
    if not named:
        return ""
    words = re.sub(r"\s+", " ", named[-1]).strip(" ,-").lower().split()
    return " ".join(w if i and w in SMALL_WORDS else w.capitalize() for i, w in enumerate(words))


def read_transcript(session, row: dict) -> dict:
    """What the transcript itself says: `hearing_dates`, the hearing days when they say more than
    GPO's held date, and `committee_name`, the committee on its title page."""
    text = get_with_retry(session, row["html_url"]).text
    volume = is_multi_hearing_volume(row["title"])
    days = hearing_days(text, int(row["congress"]), volume)
    tells_more = days and (days != [row["held_date"]] or volume)
    return {"hearing_dates": ";".join(days) if tells_more else "", "committee_name": committee_on_title_page(text)}


def name_key(chamber: str, committee_name: str) -> tuple:
    """A committee's name reduced to its distinctive words, with its chamber: both chambers have a
    "Committee on the Judiciary"."""
    words = re.sub(r"[^a-z ]", " ", committee_name.lower()).split()
    return chamber, " ".join(w for w in words if w not in SMALL_WORDS and w not in ("committee", "united", "states", "senate", "house"))


def clean_rows(rows: dict[str, dict]) -> None:
    """Fix committee codes and flag errata, in place. Idempotent: always starts from GPO's own code."""
    for row in rows.values():
        if not row.get("committee_code_gpo") and "committee_code_gpo" not in row:
            row["committee_code_gpo"] = row["committee_code"]  # rows written before this column existed
        row.setdefault("record_type", "errata" if "[ERRATA]" in row["title"].upper() else "hearing")
        row.setdefault("hearing_dates", "")
        row.setdefault("text_read", "")

    def fix(code):
        code = (code or "").strip().lower()
        if len(code) == 6 and not VALID_CODE.match(code):
            code = code[:4] + code[4:].replace("o", "0")  # e.g. "hssmoo" -> "hssm00"
        return code if VALID_CODE.match(code) else ""

    ## for blank or unusable codes, use the code GPO most often gives that committee name in that chamber,
    ##  or in any chamber when only one has a committee of that name (a joint print of a Senate committee)
    by_name = collections.defaultdict(collections.Counter)
    for row in rows.values():
        code = fix(row["committee_code_gpo"])
        if code and row["committee_name"]:
            by_name[name_key(row["chamber"], row["committee_name"])][code] += 1
            by_name[name_key("", row["committee_name"])][code] += 1
    for row in rows.values():
        code = fix(row["committee_code_gpo"])
        if not code and row["committee_name"]:
            here, anywhere = by_name.get(name_key(row["chamber"], row["committee_name"])), by_name.get(name_key("", row["committee_name"]), {})
            code = here.most_common(1)[0][0] if here else next(iter(anywhere)) if len(anywhere) == 1 else ""
        row["committee_code"] = code


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
        default="hsj",
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
