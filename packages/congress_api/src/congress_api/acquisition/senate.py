"""Collect Senate/joint committee pages and retain replayable parsed source data.

Discovery reads official hearing listings on the supported sites. The default
boundary is June 2019. An earlier --since requires an explicit --site scope;
that boundary and the latest collection date remain in each site's state.
WordPress event dates rank listings when available. Publication dates are only
ranking hints, never evidence of a proceeding's date.

Page associations use the page's own date and at least half the native title's
rarity-weighted subject. ``matching.senate_pages.associate_pages`` returns the
events and match details; this collector only checkpoints them. Shared menu lines
and files are excluded from matching; ambiguous ties remain unlinked. Existing
associations survive changes in rarity weights unless a newly explicit event date
contradicts the native record.

Recognized official event headers retain their title, date and type, so an
unmatched official proceeding can later be admitted under its own URL identity.
Same-day native candidates are retained even after a partial collection failure
and prevent accidental duplicate admission. Indian Affairs and Drug Caucus use
all native statuses for matching; other sites keep their established population.

Witness parsing covers the seven retained layouts, including Jet h3/h4 names and
paragraph roles. Explicit Drug Caucus attachment pages are followed to their
reported files; original landing URLs and anchor labels remain in state. Files
are discovered, not downloaded. Every request has an actual receipt, separate
from the scheduling day. Failures keep the last usable page.

State contains complete captured HTML/JSON bodies alongside typed page evidence,
listings, associations and request outcomes. It is checkpointed every 25 pages.
CSV files are views of those same saved associations. --seed-cache imports existing research pages read-only.
"""

import collections
import datetime as dt
import json
import re

from congress_api.acquisition.refresh import due
from congress_api.matching.committees import codes_of
from congress_api.matching.meetings import in_inventory_scope
from congress_api.matching.senate_pages import associate_pages, mark_possible_matches, retained_matches
from congress_api.models.content import RawContent
from congress_api.models.senate import WORDPRESS_POSTS, WORDPRESS_TYPES, SenatePage, WordPressHearingFields
from congress_api.parsers.senate import PARSER_VERSION, parse_listing_page, parsed
from congress_api.parsers.senate_page import FIRST_RECORD, LISTINGS, SITE, attachment_page, documents
from congress_api.parsers.text import text
from congress_api.retention.meetings import all_meetings, read_meetings
from congress_api.retention.senate import cached_html_path, seed_fetch
from congress_api.retention.tables import read_state, write_csv, write_state
from congress_api.transport import http

PAGE_FIELDS = "event_id page title witnesses documents".split()


WITNESS_FIELDS = "event_id name position organization page location".split()


DOCUMENT_FIELDS = "event_id kind name url page source_labels witness_indexes witness_names".split()


def listing_page(site, form, n, get):
    return parse_listing_page(get(f"https://www.{site}{form.format(n)}"), site)


def wordpress_listed(site, get):
    """(day, url, title) for every hearing a WordPress site holds, when the site records the day a hearing is held."""
    try:
        types = json.loads(get(f"https://www.{site}/wp-json/wp/v2/types") or "{}")
    except ValueError:
        return []
    types = WORDPRESS_TYPES.validate_python(types, strict=True)
    out = []
    for base in sorted({t.rest_base for t in types.values() if re.search(r"hearing|meeting", t.rest_base) and "file" not in t.rest_base}):
        for n in range(1, 100):
            try:
                posts = json.loads(get(f"https://www.{site}/wp-json/wp/v2/{base}?per_page=100&page={n}&_fields=link,title,acf,date") or "[]")
            except ValueError:
                break
            posts = WORDPRESS_POSTS.validate_python(posts, strict=True)
            held = []
            for post in posts:
                day = post.acf.hearing_date_time if isinstance(post.acf, WordPressHearingFields) else None
                # Publication day only ranks discovery candidates for this site;
                # a page's own event date is required before event admission.
                if not day and site == "drugcaucus.senate.gov":
                    day = post.date
                if re.match(r"\d{4}-\d\d-\d\d", day or ""):
                    held.append((day, post))
            out += [(dt.date.fromisoformat(day[:10]), p.link, text(p.title.rendered)) for day, p in held]
            # A full page of undated posts is not end-of-list; only a short or
            # empty API page means there are no further pages to read.
            if len(posts) < 100:
                break
    return out


def listed(site, get, saved=None, since=FIRST_RECORD):
    """(day, url, title) for the hearing pages a site lists, back to the first Senate meeting record."""
    out = [r for r in wordpress_listed(site, get) if r[0] >= since] if not saved or saved.get("wordpress") else []
    if out:
        return out, {"wordpress": True}
    if saved and saved.get("form"):
        form, from_0 = saved["form"], saved["from_0"]
    else:
        first = {f: {r[1] for r in listing_page(site, f, 1, get)} for f in LISTINGS}
        form = next((f for f in LISTINGS if first[f] and {r[1] for r in listing_page(site, f, 2, get)} - first[f]), None) or next((f for f in LISTINGS if first[f]), None)
        from_0 = form and {r[1] for r in listing_page(site, form, 0, get)} - first[form]
    for n in range(0 if from_0 else 1, 300) if form else ():
        have = {o[1] for o in out}
        new = [r for r in listing_page(site, form, n, get) if r[1] not in have]
        if not new:
            break  # past the last page, the site repeats or empties
        out += new
        if saved and n >= (1 if from_0 else 2) and all(r[1] in saved["listings"] for r in new):
            break  # two overlapping pages protect against a newly inserted hearing at a page boundary
        if max(r[0] for r in new) < since:
            break
    return [row for row in out if row[0] >= since], {"form": form, "from_0": bool(from_0)}


def timestamp():
    return dt.datetime.now(dt.UTC).isoformat()


def request(url, receipts, *, allowed=(200, 404)):
    """Retain one retry-helper outcome; its internal attempts are not counted."""
    receipt = {"url": url, "started_at": timestamp()}
    receipts.append(receipt)
    try:
        response = http.get_with_retry(None, url, allowed=allowed)
    except (ValueError, RuntimeError, OSError) as error:
        receipt.update(completed_at=timestamp(), outcome="error", error=str(error))
        raise
    receipt.update(completed_at=timestamp(), status_code=response.status_code,
                   outcome="retrieved" if response.status_code == 200 else "not_found" if response.status_code == 404 else "unsupported")
    return response


def decoded_page(response, url, receipt):
    """The hearing-page reader accepts text, never a PDF decoded as UTF-8.

    Body bytes must be strict UTF-8, matching parsers.senate.parse_page.
    """
    headers = getattr(response, "headers", {})
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    if response.content.lstrip().startswith(b"%PDF-") or content_type.split(";", 1)[0].strip().lower() == "application/pdf":
        receipt.update(outcome="unsupported_format", detected_format="pdf")
        if content_type:
            receipt["content_type"] = content_type
        raise ValueError(f"Senate hearing-page reader received PDF content from {url}")
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        receipt.update(outcome="error", error=f"invalid UTF-8 from {url}")
        raise

def fetch_page(url, previous, today, *, cache=None, check=None):
    """Read one page, retaining schedule dates separately from actual receipts."""
    check = check if check is not None else {}
    if cache is not None:
        result = parsed(seed_fetch(cache, url), url)
        path = cached_html_path(cache, url)
        if path.exists():
            result["raw_html"] = RawContent.from_bytes(path.read_bytes(), "text/html").source_dict()
        result["imported_at"] = timestamp()
    else:
        check.update(mode="live", started_at=timestamp(), receipts=[])
        captured = []
        try:
            response = request(url, check["receipts"])
            page_receipt = check["receipts"][-1]
            captured.append((page_receipt, RawContent.from_bytes(response.content, getattr(response, "headers", {}).get("Content-Type", "text/html"))))
            if response.status_code == 404:
                result = {"title": "", "lines": [], "witnesses": [], "documents": [], "absent": True,
                          "raw_html": captured[0][1].source_dict()}
            else:
                result = parsed(decoded_page(response, url, check["receipts"][-1]), url)
                result["raw_html"] = captured[0][1].source_dict()
                attachments = {}
                attachment_sources = {}
                for _, _, linked_url in result["documents"]:
                    if attachment_page(linked_url):
                        response_file = request(linked_url, check["receipts"])
                        captured.append((check["receipts"][-1], RawContent.from_bytes(response_file.content, getattr(response_file, "headers", {}).get("Content-Type", "text/html"))))
                        attachment_sources[linked_url] = captured[-1][1].source_dict()
                        if response_file.status_code == 200:
                            attachment_html = decoded_page(response_file, linked_url, check["receipts"][-1])
                            attachments[linked_url] = [dict(kind=kind, label=label, url=file_url) for kind, label, file_url in documents(attachment_html, linked_url) if not attachment_page(file_url)]
                if attachments:
                    result["attachments"] = attachments
                if attachment_sources:
                    result["attachment_sources"] = attachment_sources
                if not result["title"] or result["title"].strip().casefold() in {"403 forbidden", "error"}:
                    page_receipt["outcome"] = "unrecognized_page"
                    raise ValueError(f"Unrecognized Senate hearing page {url}")
            check.update(completed_at=timestamp(), outcome="not_found" if result.get("absent") else "present")
            result["last_check"] = check
            result["observation_check"] = check  # Retain this evidence if a later refresh fails.
            if response.status_code == 200:
                result["retrieved_at"] = next(receipt["completed_at"] for receipt in check["receipts"] if receipt["url"] == url)
        except (ValueError, RuntimeError, OSError) as error:
            # Failed refreshes keep the prior usable page. Retain the attempted
            # new bodies with their own receipts, not as that older observation.
            for receipt, body in captured:
                receipt["raw_body"] = body.source_dict()
            check.update(completed_at=timestamp(), outcome="error", error=str(error))
            raise
    return SenatePage.model_validate({**result, "checked": today.isoformat(), "version": "", "parser_version": PARSER_VERSION, "events": previous.get("events", []), **({"match_details": previous["match_details"]} if previous.get("match_details") else {})}).model_dump(mode="python", by_alias=True, exclude_unset=True)


def refresh_urls(state, versions, today, limit, sites=None):
    """Spend the maintenance budget on the oldest due checks across all sites."""
    aged = []
    for host, saved in state.items():
        if host not in versions or (sites and host not in sites):
            continue
        changed = {e for e, v in versions[host].items() if saved.get("versions", {}).get(e) != v}
        for url, page in saved["pages"].items():
            if page.get("status") == "error":
                continue  # No successful observation exists; the main pass retries it as urgent.
            if url in saved["listings"] and not changed.intersection(page.get("events", [])) and (page.get("parser_version", 0) < PARSER_VERSION or due(page, saved["listings"][url][0], page.get("version"), today)):
                aged.append((page.get("parser_version", 0) >= PARSER_VERSION, page.get("checked", ""), url))
    return {url for _, _, url in sorted(aged)[:limit]}


def main(meetings, state_dir, output_dir, seed_cache=None, offline=False, as_of=None, refresh_limit=450, site=None, limit=None, since=None):
    """Offline mode uses saved site state or local seed imports, still joins and writes
    outputs, and raises for missing required listings. It never refreshes HTTP.

    See docs/congress-api-contracts.md#offline-behavior.
    """
    if refresh_limit < 0:
        raise ValueError("refresh_limit must be nonnegative")
    if limit is not None and limit < 0:
        raise ValueError("limit must be nonnegative")
    if since is not None and since < FIRST_RECORD and not site:
        raise ValueError("Historical collection before June 2019 requires an explicit --site scope")
    # Collection/admission must see canceled and historical native meetings too;
    # the inventory's reporting filter would make them look like missing events.
    native_meetings = read_meetings(meetings, scope=all_meetings)
    # Preserve the established refresh scope for other sites. Full native input
    # still informs duplicate guards, including canceled or historical records.
    ms = [meeting for meeting in native_meetings if any(code in ("slia00", "scnc00") for code in codes_of(meeting)) or
          in_inventory_scope(meeting)]
    path = state_dir / "senate.json.gz"
    state, totals = read_state(path), collections.Counter()
    versions = collections.defaultdict(dict)
    for m in ms:
        codes = codes_of(m)
        if m.get("chamber") != "House" and codes and codes[0] in SITE:
            versions[SITE[codes[0]]][m["eventId"]] = m.get("updateDate", "")
    for host in site or ():
        versions.setdefault(host, {})
    maintenance = refresh_urls(state, versions, as_of, refresh_limit, site)
    errors, live_pages = [], 0
    for host in sorted(versions):
        if site and host not in site:
            continue
        saved = state.get(host, {})
        if saved.get("status") == "error":
            saved = {}  # Failed initial discovery does not change discovery policy.
        boundary = since or dt.date.fromisoformat(saved.get("collection_scope", {}).get("since", FIRST_RECORD.isoformat()))
        expanded = boundary < dt.date.fromisoformat(saved.get("collection_scope", {}).get("since", FIRST_RECORD.isoformat()))
        importing = not saved and seed_cache is not None
        if offline and not importing:
            if not saved:
                errors.append(f"{host}: no saved listing")
            continue
        listing_check = {}
        source_bodies = dict(saved.get("source_bodies", {}))
        attempt = {"mode": "cache_import" if importing else "live", "started_at": timestamp()}
        def get(url):
            if importing:
                body = seed_fetch(seed_cache, url)
                raw_path = cached_html_path(seed_cache, url)
                if raw_path.exists():
                    source_bodies[url] = RawContent.from_bytes(raw_path.read_bytes(), "application/json" if "/wp-json/" in url else "text/html").source_dict()
                return body
            response = request(url, listing_check["receipts"], allowed=(200, 400, 404))
            source_bodies[url] = RawContent.from_bytes(response.content, getattr(response, "headers", {}).get("Content-Type", "application/json" if "/wp-json/" in url else "text/html")).source_dict()
            return decoded_page(response, url, listing_check["receipts"][-1]) if response.status_code == 200 else ""
        try:
            if importing or not saved or expanded or saved.get("versions") != versions[host] or (as_of - dt.date.fromisoformat(saved["checked"])).days >= 7:
                if not importing:
                    listing_check.update(mode="live", started_at=timestamp(), receipts=[])
                try:
                    rows, route = (listed(host, get, None if expanded else saved, since=boundary)
                                   if boundary != FIRST_RECORD else listed(host, get, saved))
                    if not rows and not importing:
                        raise ValueError(f"{host}: previously working listing returned no hearings")
                except (ValueError, RuntimeError, OSError) as error:
                    if not importing:
                        listing_check.update(completed_at=timestamp(), outcome="error", error=str(error))
                        saved = saved or {"pages": {}, "listings": {}, "status": "error"}
                        saved["last_check"] = listing_check
                    raise
                listing = {**saved.get("listings", {}), **{u: [d.isoformat(), t] for d, u, t in rows}}
                saved = {**saved, **route, "checked": as_of.isoformat(), "listings": listing, "pages": saved.get("pages", {})}
                if importing:
                    saved["imported_at"] = timestamp()
                else:
                    listing_check.update(completed_at=timestamp(), outcome="present")
                    saved["last_check"] = listing_check
                saved["collection_scope"] = {"since": boundary.isoformat(), "through": as_of.isoformat(), "basis": "official hearing listings"}
                totals["sites listed"] += 1
            if source_bodies:
                saved["source_bodies"] = source_bodies
            pages = saved["pages"]
            changed = {e for e, v in versions[host].items() if saved.get("versions", {}).get(e) != v}
            urgent, aged = [], []
            for url, (day, _) in saved["listings"].items():
                previous = pages.get(url)
                if not previous or previous.get("status") == "error" or (host in ("indian.senate.gov", "drugcaucus.senate.gov") and previous.get("parser_version", 0) < 2) or changed.intersection(previous.get("events", [])):
                    urgent.append(url)
                elif url in maintenance:
                    aged.append(url)
            aged.sort(key=lambda u: (pages.get(u, {})["checked"], u))
            for url in urgent + aged:
                if limit is not None and live_pages >= limit and not importing:
                    break
                page_check = {}
                try:
                    pages[url] = fetch_page(url, pages.get(url, {}), as_of, cache=seed_cache if importing else None, check=page_check)
                except (ValueError, RuntimeError, OSError):
                    if not importing:
                        previous = pages.setdefault(url, {"title": "", "lines": [], "witnesses": [], "documents": [], "events": [], "status": "error"})
                        previous["last_check"] = page_check
                    raise
                totals["pages seeded" if importing else "pages fetched"] += 1
                if not importing and totals["pages fetched"] % 25 == 0:
                    print(f"{host}: {totals['pages fetched']} pages refreshed; checkpoint saved", flush=True)
                    state[host] = saved
                    mark_possible_matches(native_meetings, state)
                    write_state(path, state)
                if not importing:
                    live_pages += 1
            if limit is None or live_pages < limit:
                saved["versions"] = versions[host]
            attempt.update(completed_at=timestamp(), outcome="imported" if importing else "complete")
            saved["last_attempt"] = attempt
            state[host] = saved
        except (ValueError, RuntimeError, OSError) as error:
            errors.append(str(error))
            if saved:
                attempt.update(completed_at=timestamp(), outcome="error", error=str(error))
                saved["last_attempt"] = attempt
                state[host] = saved
        if saved and source_bodies:
            saved["source_bodies"] = source_bodies
    mark_possible_matches(native_meetings, state)
    write_state(path, state)
    missing = [host for host in versions if (not site or host in site) and (host not in state or state[host].get("status") == "error" or any(
        u not in state[host]["pages"] or state[host]["pages"][u].get("status") == "error" for u in state[host]["listings"]))]
    if errors or missing:
        raise RuntimeError(f"Senate source incomplete: {errors[:5] or missing}")
    associations = associate_pages(ms, native_meetings, state)
    for saved in state.values():
        for url, page in saved["pages"].items():
            update = associations[url]
            page["events"] = update["events"]
            if "match_details" in update:
                page["match_details"] = update["match_details"]
    mark_possible_matches(native_meetings, state)
    write_state(path, state)
    found = retained_matches(state)
    for name, rows, fields in zip(("senate_hearing_pages_found", "senate_witnesses_found", "senate_documents_found"), found, (PAGE_FIELDS, WITNESS_FIELDS, DOCUMENT_FIELDS)):
        write_csv(output_dir / f"{name}.csv", rows, fields)
        totals[name] = len(rows)
    print(dict(totals), dict(http.COUNTS))
