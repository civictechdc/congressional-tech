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

import argparse
import collections
import csv
import json
import logging
import re
import sys

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from congress_api.http import get_with_retry
from congress_api.xml import MODS_NS, mods_elements, parse_xml
from congress_api.gpo.reviewed_committees import reviewed
from congress_api.gpo import evidence as upstream_evidence
from congress_shared.auth import load_congress_api_key
from congress_shared.globals import CONGRESS_METADATA, DEFAULT_GPO_HEARINGS_FILE

GOVINFO_API = "https://api.govinfo.gov"
GOVINFO_CONTENT = "https://www.govinfo.gov"

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
# Parser revisions queue bounded repairs even when GovInfo does not change a package.
PARSER_VERSION = "2"


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
    # All bodies/files explicitly listed in root and constituent metadata.
    # Singular columns remain the first value for older readers.
    committee_codes_gpo: str = ""
    committee_codes: str = ""
    html_urls: str = ""
    pdf_urls: str = ""
    # URL-keyed part labels preserve publisher distinctions such as hearing,
    # markup, errata and addendum without splitting the package identity.
    file_metadata: str = ""
    committee_metadata: str = ""
    # `serial` historically held preferredCitation; retain it for old readers.
    preferred_citation: str = ""
    serial_numbers: str = ""
    parser_version: str = ""
    document_class: str = ""
    granule_classes: str = ""
    held_dates: str = ""


def mods_witnesses(data):
    """Witness names and affiliations from MODS, including granule-only lists."""
    from congress_api.witnesses import is_name, person_key, witness
    found = {}
    ## Some Senate records put witnesses in granules only; deduplicate across both levels.
    for element in parse_xml(data).iter("{http://www.loc.gov/mods/v3}witness"):
        fields = witness(element.text or "")
        if is_name(fields["name"]):
            found[person_key(fields["name"])] = fields
    return list(found.values())


def main(
    output_path: Path = DEFAULT_GPO_HEARINGS_FILE,
    chambers: str = "hsj",
    min_congress: int | None = None,
    nthreads: int = 4,
    full_relist: bool = False,
    refresh_limit: int = 100,
    evidence_path: Path | None = None,
) -> None:
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



def merge_cached_row(old, parsed, *, live_refresh=False):
    """Combine explicit facts without replacing existing scalar corrections.

    Only a current network response may fill legacy scalar blanks: an offline
    cache can predate both a source correction and a deliberately cleared value.
    """
    merged = dict(old)
    if live_refresh:
        for field in ('event_id', 'committee_code_gpo', 'committee_name', 'subcommittees',
                      'title', 'held_date', 'date_ingested', 'serial', 'html_url', 'pdf_url'):
            merged[field] = old.get(field) or parsed.get(field, '')
        if parsed.get('record_type') == 'errata':
            merged['record_type'] = 'errata'
    for field in ('html_urls', 'pdf_urls', 'committee_codes_gpo', 'committee_codes',
                  'serial_numbers', 'granule_classes', 'held_dates'):
        values = str(old.get(field) or '').split(';')
        singular = {'html_urls': 'html_url', 'pdf_urls': 'pdf_url',
                    'committee_codes_gpo': 'committee_code_gpo', 'committee_codes': 'committee_code'}.get(field)
        if singular and old.get(singular):
            values.insert(0, old[singular])
        merged[field] = ';'.join(dict.fromkeys(v for v in values + str(parsed.get(field) or '').split(';') if v))
    for field in ('document_class', 'preferred_citation'):
        merged[field] = old.get(field) or parsed[field]
    claims = json.loads(old.get('committee_metadata') or '[]')
    for claim in json.loads(parsed.get('committee_metadata') or '[]'):
        if claim not in claims:
            claims.append(claim)
    merged['committee_metadata'] = json.dumps(claims, ensure_ascii=False, separators=(',', ':')) if claims else ''
    files = json.loads(parsed.get('file_metadata') or '{}')
    for url, existing in json.loads(old.get('file_metadata') or '{}').items():
        files[url] = {**files.get(url, {}), **existing}
    merged['file_metadata'] = json.dumps(files, ensure_ascii=False, separators=(',', ':')) if files else ''
    # A cached MODS file can predate this row. Parser freshness belongs to a
    # successful network refresh, not additive replay of an unknown acquisition.
    return merged


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


def parse_mods(package_id: str, mods: bytes, last_modified: str) -> GpoHearing:
    """Pull the hearing-level fields out of a GovInfo MODS record."""
    root = parse_xml(mods)
    if root.tag != '{http://www.loc.gov/mods/v3}mods':
        raise ValueError('GovInfo metadata response is not a MODS document')
    match = PACKAGE_ID_REGEX.fullmatch(package_id)
    if match is None:
        raise ValueError(f'Invalid GovInfo hearing package identifier: {package_id}')
    congress, chamber, _ = match.groups()

    ## hearing-level data lives in the root's own <extension> blocks; the
    ##  <relatedItem> granules below repeat some of it, so don't search deeper
    def ext_all(tag):
        return mods_elements(root, tag)

    def ext_text(tag):
        found = ext_all(tag)
        return found[0].text.strip() if found and found[0].text else ""

    # Root and constituent metadata describe package contents. Other related
    # items are cited laws/bills and must not contribute committee ownership.
    committees = ext_all("congCommittee") + root.findall(
        "m:relatedItem[@type='constituent']/m:extension/m:congCommittee", MODS_NS
    )
    committee_codes = list(dict.fromkeys(c.get("authorityId", "").strip().lower()
                                        for c in committees if c.get("authorityId")))
    committee_metadata = []
    for committee in committees:
        claim = {**committee.attrib,
                 'names': [{'type': n.get('type'), 'name': n.text.strip()}
                           for n in committee.findall('m:name', MODS_NS) if n.text],
                 'subcommittees': [n.text.strip() for n in committee.findall('m:subCommittee/m:name', MODS_NS) if n.text]}
        if claim not in committee_metadata:
            committee_metadata.append(claim)
    ## codes are lowercase in youtube-accounts.csv (a few MODS records aren't)
    committee_code = committee_codes[0] if committee_codes else ""
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
    ).strip() or ext_text("errata")

    scopes = [root, *root.findall("m:relatedItem[@type='constituent']", MODS_NS)]
    serial_numbers = list(dict.fromkeys(el.get('number', '').strip()
        for scope in scopes for el in mods_elements(scope, 'congSerial') if el.get('number', '').strip()))

    def rendition_urls(label):
        nodes = root.findall('m:location/m:url', MODS_NS) + root.findall(
            "m:relatedItem[@type='constituent']/m:location/m:url", MODS_NS)
        return list(dict.fromkeys(el.text.strip() for el in nodes
                                  if el.get('displayLabel') == label and el.text and el.text.strip()))

    html_urls, pdf_urls = rendition_urls('HTML rendition'), rendition_urls('PDF rendition')
    file_metadata = {}
    for part in root.findall("m:relatedItem[@type='constituent']", MODS_NS):
        label = part.findtext('m:titleInfo/m:title', '', MODS_NS).strip()
        part_type = part.findtext('m:extension/m:granuleClass', '', MODS_NS).strip()
        for element in part.findall('m:location/m:url', MODS_NS):
            if element.get('displayLabel') in ('HTML rendition', 'PDF rendition') and element.text:
                file_metadata[element.text.strip()] = {'title': label, 'granule_class': part_type}

    return GpoHearing(
        package_id=package_id,
        congress=int(congress),
        chamber=CHAMBERS[chamber],
        event_id=ext_text("eventId"),
        committee_code=committee_code,
        committee_code_gpo=committee_code,
        committee_codes_gpo=";".join(committee_codes),
        committee_codes=";".join(committee_codes),
        committee_metadata=json.dumps(committee_metadata, ensure_ascii=False, separators=(',', ':')) if committee_metadata else "",
        record_type="errata" if (ext_text('isErrata').lower() == 'true'
            or ext_text('granuleClass').upper() == 'ERRATA'
            or "[ERRATA]" in title.upper()) else "hearing",
        committee_name=committee_name,
        subcommittees="; ".join(dict.fromkeys(subcommittees)),
        title=" ".join(title.split()),
        held_date=held_date,
        date_ingested=date_ingested,
        days_to_govinfo=days_to_govinfo,
        serial=ext_text("preferredCitation"),
        preferred_citation=ext_text("preferredCitation"),
        serial_numbers=";".join(serial_numbers),
        parser_version=PARSER_VERSION,
        document_class=ext_text("docClass"),
        granule_classes=";".join(dict.fromkeys(el.text.strip() for scope in scopes
            for el in mods_elements(scope, "granuleClass") if el.text and el.text.strip())),
        held_dates=";".join(held_dates),
        witness_count=len(dict.fromkeys(el.text.strip() for scope in scopes
            for el in mods_elements(scope, "witness") if el.text and el.text.strip())),
        html_url=html_urls[0] if html_urls else "",
        pdf_url=pdf_urls[0] if pdf_urls else "",
        html_urls=";".join(html_urls),
        pdf_urls=";".join(pdf_urls),
        file_metadata=json.dumps(file_metadata, ensure_ascii=False, separators=(',', ':')) if file_metadata else "",
        last_modified=last_modified,
    )


VALID_CODE = re.compile(r"^[hsj][a-z0-9]{3}\d\d$")
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
PARENT_BODY = re.compile(r"(?<![A-Z])((?:COMMITTEE|COMMISSION|CAUCUS) ON [A-Z][A-Z,'\u2019 \-]*(?:\n[ \t]*(?:\n[ \t]*)*(?!(?:BEFORE THE|UNITED STATES)\b)[A-Z][A-Z,'\u2019 \-]*)?)")
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
    return {"hearing_dates": ";".join(days) if tells_more else "", "committee_name": names[0] if names else ""}


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
        codes = list(dict.fromkeys(fix(c) for c in row.get('committee_codes_gpo', '').split(';') if fix(c)))
        if code and code not in codes:
            codes.insert(0, code)
        decision = reviewed(row)
        if decision and decision.get('committee_codes') and not fix(row['committee_code_gpo']) and not row.get('committee_codes_gpo'):
            codes = decision['committee_codes']
        row["committee_code"] = codes[0] if codes else ""
        # An old cache row remains readable without asserting additional codes.
        if row.get('committee_codes_gpo') or (decision and decision.get('committee_codes')):
            row['committee_codes'] = ';'.join(codes)


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def read_csv(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["package_id"]: row for row in csv.DictReader(handle)}


def write_csv(rows: dict[str, dict], path: Path) -> None:
    field_names = [field.name for field in fields(GpoHearing)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        with open(temporary, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            writer.writeheader()
            ## sort so weekly diffs only show real changes
            for package_id in sorted(rows):
                writer.writerow(rows[package_id])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_pending(values, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_text(json.dumps(values, sort_keys=True) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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

    parser.add_argument("--evidence-path", type=Path,
                        help="Gzip JSONL upstream XML/HTML evidence on pipeline-data; kept out of the CSV.")
    parser.add_argument("--refresh-limit", type=int, default=100,
                        help="Maximum unchanged rows to refresh for a newer parser (default: 100).")

    ## ignore the unknown args (e.g. --congress-api-key, read by the key loader)
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
