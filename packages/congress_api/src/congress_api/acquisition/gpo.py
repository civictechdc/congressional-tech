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
from xml.etree.ElementTree import ParseError

import requests
from congress_shared.auth import load_congress_api_key
from congress_shared.resources import CONGRESS_METADATA
from congress_shared.paths import DEFAULT_GPO_HEARINGS_FILE

from congress_api.matching.gpo_committees import clean_rows, merge_cached_row
from congress_api.models.gpo import (
    GpoCollectionPage,
    GpoListingObservation,
    GpoTranscriptDates,
)
from congress_api.parsers.gpo import parse_mods_document, parse_package_manifest
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
from congress_api.transport.zip_member import read_zip_member, ZipMemberReadError

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
    evidence_changed = False
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
        listings[package['packageId']] = GpoListingObservation.model_validate({
            'payload': package, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'url': f'{GOVINFO_API}/collections/CHRG/{since}',
        }).source_dict()
        old = existing.get(package["packageId"])
        if old is None or old["last_modified"] != package["lastModified"]:
            to_fetch[package["packageId"]] = package["lastModified"]
    stale = sorted((row for row in existing.values()
                    if (match := PACKAGE_ID_REGEX.match(row["package_id"]))
                    and match[2] in chambers
                    and (row.get("parser_version") != PARSER_VERSION
                         or (evidence_path is not None and (
                             not upstream.get(row["package_id"], {}).get("mods")
                             or not upstream.get(row["package_id"], {}).get("manifest")
                             or (upstream.get(row["package_id"], {}).get("manifest") or {}).get("error")
                         )))
                    and int(row["congress"]) >= min_congress
                    and row["package_id"] not in to_fetch),
                   key=lambda row: (-int(row["congress"]), row["package_id"]))
    skipped_ids = sorted({row["package_id"] for row in existing.values()
                          if not PACKAGE_ID_REGEX.match(row["package_id"])})
    if skipped_ids:
        logging.warning(f"Skipping {len(skipped_ids)} malformed package_id(s) in CSV: {skipped_ids[0]}"
                        + (f" (+{len(skipped_ids) - 1} more)" if len(skipped_ids) > 1 else ""))
    for row in stale[:refresh_limit]:
        to_fetch[row["package_id"]] = row["last_modified"]
    pending.update(to_fetch)
    write_pending(pending, pending_path)
    logging.info(f"Fetching metadata for {len(to_fetch)} new, changed or parser-stale hearings")

    failures = []
    session = requests.Session()

    def fetch_one(item):
        """Return hearing/error/evidence updates; the caller merges shared state."""
        package_id, last_modified = item
        captured = None
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
                mods_doc = parse_mods_document(mods)
                hearing = parse_mods(package_id, mods_doc, last_modified)
            except (ParseError, ValueError, KeyError, TypeError, OSError, RuntimeError) as ex:
                # Keep rejected response bytes without replacing the last valid
                # MODS record or marking its CSV row freshly parsed.
                captured['failed_mods'] = {**observation, 'error': str(ex)}
                raise
            captured.update(
                parser_version=PARSER_VERSION,
                mods=observation,
                mods_document=mods_doc.record_dict(),
            )
            captured.pop('failed_mods', None)
            if evidence_path is not None:
                mets_url = f"{GOVINFO_CONTENT}/content/pkg/{package_id}.zip"
                manifest_obs = upstream_evidence.observation(
                    b"", mets_url, "application/xml",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
                try:
                    cached_manifest = captured.get('manifest') or {}
                    if (cached_manifest.get('source_zip') and not cached_manifest.get('error')
                            and not captured.get('failed_manifest')
                            and cached_manifest.get('package_last_modified') == last_modified):
                        manifest_obs = cached_manifest
                        mets_bytes = upstream_evidence.body_bytes(cached_manifest)
                    else:
                        member = read_zip_member(session, mets_url, f'{package_id}/dip.xml')
                        mets_bytes = member.data
                        manifest_obs = upstream_evidence.observation(
                            mets_bytes, mets_url, "application/xml",
                            retrieved_at=datetime.now(timezone.utc).isoformat(),
                        )
                        manifest_obs.update(acquisition='http-zip-member', source_zip=member.source,
                                            package_last_modified=last_modified)
                    parsed_manifest = parse_package_manifest(mets_bytes)
                    if parsed_manifest.attributes.get('OBJID') != package_id:
                        raise ValueError('GovInfo METS manifest identifies another package')
                except (requests.RequestException, ParseError, OSError, ValueError,
                        KeyError, TypeError, RuntimeError) as mets_ex:
                    # Retain rejected bytes separately from the last valid file
                    # manifest. Fail this package so its row stays pending.
                    if isinstance(mets_ex, ZipMemberReadError):
                        manifest_obs = upstream_evidence.observation(
                            mets_ex.data, mets_url, mets_ex.media_type,
                            retrieved_at=datetime.now(timezone.utc).isoformat(),
                        )
                        manifest_obs.update(acquisition='http-zip-member', source_zip=mets_ex.source)
                    captured['failed_manifest'] = {**manifest_obs, 'error': str(mets_ex)}
                    raise
                captured['manifest'] = manifest_obs
                captured['manifest_files'] = [f.source_dict() for f in parsed_manifest.files]
                captured.pop('failed_manifest', None)
            captured['transcripts'] = dict(captured.get('transcripts', {}))
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
                hearing.hearing_dates = read["hearing_dates"]
                hearing.committee_name = hearing.committee_name or read["committee_name"]
                if read.get("text_read"):
                    hearing.text_read = read["text_read"]
            result = asdict(hearing)
            if unchanged:
                result = merge_cached_row(old, result, live_refresh=True)
                result.update(parser_version=PARSER_VERSION, hearing_dates=hearing.hearing_dates,
                              text_read=hearing.text_read, witness_count=hearing.witness_count)
            return result, None, captured if evidence_path is not None else None
        except (requests.RequestException, ParseError, OSError, ValueError, KeyError, TypeError, RuntimeError) as ex:
            return None, f"{package_id}: {ex!r}", captured if evidence_path is not None and captured is not None else None

    completed = set()
    with ThreadPoolExecutor(nthreads) as pool:
        for i, (hearing, error, captured) in enumerate(pool.map(fetch_one, to_fetch.items()), 1):
            if captured is not None:
                if captured != upstream.get(captured['package_id']):
                    evidence_changed = True
                upstream[captured['package_id']] = captured
            if error:
                failures.append(error)
            elif hearing is not None:
                existing[hearing["package_id"]] = hearing
                completed.add(hearing["package_id"])
            if i % 500 == 0:
                logging.info(f"Fetched {i}/{len(to_fetch)}")

    # A failed metadata refresh must not change its last valid row through the
    # independent transcript backfill below.
    failed_packages = set(to_fetch) - completed
    ## one-time backfill: hearing days for transcripts fetched before they were read
    backfill = sorted((r for r in existing.values()
                if (match := PACKAGE_ID_REGEX.match(r["package_id"]))
                and match[2] in chambers
                and int(r["congress"]) >= max(TEXT_DAYS_FROM_CONGRESS, min_congress)
                and r["package_id"] not in failed_packages
                and not r.get("text_read")),
                key=lambda row: (-int(row["congress"]), row["package_id"]))[:refresh_limit]
    if backfill:
        logging.info(f"Reading hearing days from {len(backfill)} transcripts")

        def fill(row):
            try:
                transcripts = {} if evidence_path else None
                read = read_transcript(session, row, transcripts)
                return row, read, transcripts, None
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError, RuntimeError) as ex:
                return row, None, None, f"{row['package_id']} hearing days: {ex!r}"

        with ThreadPoolExecutor(nthreads) as pool:
            for row, read, transcripts, error in pool.map(fill, backfill):
                if error:
                    failures.append(error)
                    continue
                row["hearing_dates"] = read["hearing_dates"]
                row["committee_name"] = row["committee_name"] or read["committee_name"]
                if read.get("text_read"):
                    row["text_read"] = read["text_read"]
                if evidence_path and transcripts is not None:
                    captured = dict(upstream.get(row['package_id'], {'package_id': row['package_id']}))
                    captured['transcripts'] = {**captured.get('transcripts', {}), **transcripts}
                    if captured != upstream.get(row['package_id']):
                        evidence_changed = True
                    upstream[row['package_id']] = captured

    clean_rows(existing)

    ## Persist changed evidence before CSV/pending progress, including failures.
    if evidence_path is not None and (evidence_changed or not Path(evidence_path).exists()):
        upstream_evidence.write(upstream, evidence_path)
    write_csv(existing, output_path)
    write_pending({package: modified for package, modified in pending.items() if package not in completed}, pending_path)
    logging.info(f"Wrote {len(existing)} hearings to {output_path}")

    if failures:
        logging.error(
            f"{len(failures)} hearing(s) failed:\n  " + "\n  ".join(failures[:50])
        )
        sys.exit(1)


def govinfo_api_headers(api_key: str):
    """Return a per-URL header provider supplying `X-Api-Key` for `api.govinfo.gov` endpoints."""
    def _headers(url: str) -> dict[str, str]:
        if url and "api.govinfo.gov" in url:
            return {"X-Api-Key": api_key}
        return {}
    return _headers


def _strip_api_key_from_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(url)
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.casefold() != "api_key"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def list_collection(since: str, api_key: str, *, fetcher=None, receipt_writer=None, family: str = "govinfo/collections", receipt_keys: list[str] | None = None):
    """Yield every CHRG package modified since `since` (paged, 1000 at a time).

    Sends `X-Api-Key` in request headers so credentials never appear in recorded URLs.
    When `fetcher` and `receipt_writer` are supplied, routes every page through the raw fetcher.
    """
    url: str | None = f"{GOVINFO_API}/collections/CHRG/{since}?pageSize=1000&offsetMark=*"
    if fetcher is not None and receipt_writer is not None:
        while url:
            clean_url = _strip_api_key_from_url(url)
            result = fetcher.fetch(clean_url)
            r_key, _ = receipt_writer.write(result, family=family)
            if receipt_keys is not None:
                receipt_keys.append(r_key)
            if not (result.final.complete and result.final.http_status == 200 and result.final.body and result.final.body.path):
                raise RuntimeError(f"GovInfo collection page fetch failed for {clean_url}: {result.final.error or result.final.http_status}")
            page = GpoCollectionPage.model_validate(json.loads(result.final.body.path.read_bytes().decode("utf-8")))
            yield from (package.source_dict() for package in page.packages)
            url = _strip_api_key_from_url(page.next_page)
        return

    url = f"{GOVINFO_API}/collections/CHRG/{since}"
    params: dict | None = {"pageSize": 1000, "offsetMark": "*"}
    headers = {"X-Api-Key": api_key}
    session = requests.Session()
    while url:
        clean_url = _strip_api_key_from_url(url)
        page = GpoCollectionPage.model_validate(
            get_with_retry(session, clean_url, params=params, headers=headers).json()
        )
        yield from (package.source_dict() for package in page.packages)
        ## nextPage already carries the paging params, minus the key
        url = _strip_api_key_from_url(page.next_page)
        params = None


def fetch_package_through_raw(
    fetcher,
    receipt_writer,
    package_id: str,
    *,
    mods_family: str = "govinfo/mods",
    html_family: str = "govinfo/transcript-html",
    html_urls: tuple[str, ...] = (),
) -> dict:
    """Fetch a GovInfo CHRG package's `mods.xml` (and optional transcript HTMLs) through `Fetcher` + `ReceiptWriter`."""
    mods_url = f"{GOVINFO_CONTENT}/metadata/pkg/{package_id}/mods.xml"
    mods_result = fetcher.fetch(mods_url)
    mods_key, mods_line = receipt_writer.write(mods_result, family=mods_family)
    receipt_keys = [mods_key]
    for h_url in html_urls:
        if not h_url:
            continue
        h_res = fetcher.fetch(h_url)
        h_key, _ = receipt_writer.write(h_res, family=html_family)
        receipt_keys.append(h_key)
    return {
        "package_id": package_id,
        "mods_url": mods_url,
        "receipt_keys": receipt_keys,
        "outcome": mods_line.get("outcome"),
        "http_status": mods_line.get("http_status"),
        "complete": mods_result.final.complete,
    }


def read_transcript(session, row: dict, evidence: dict | None = None) -> dict:
    """What the transcript itself says: `hearing_dates`, the hearing days when they say more than
    GPO's held date, and `committee_name`, the committee on its title page.

    Sets ``text_read`` to ``yes`` only when at least one HTML body was fetched. With no HTML
    URLs, leave ``text_read`` unset so a later parser refresh can still enqueue backfill.
    """
    volume = is_multi_hearing_volume(row["title"])
    days, names = set(), []
    urls = [u for u in dict.fromkeys(str(row.get('html_urls') or row.get('html_url') or '').split(';')) if u]
    if not urls:
        return GpoTranscriptDates(hearing_dates="", committee_name="").source_dict()
    for url in urls:
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
    return {**GpoTranscriptDates(hearing_dates=";".join(days) if tells_more else "",
                                 committee_name=names[0] if names else "").source_dict(),
            "text_read": "yes"}


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
