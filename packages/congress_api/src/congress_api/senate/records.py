"""Collect Senate/joint committee pages and retain replayable parsed source data.

Discovery reads official hearing listings on the supported sites. The default
boundary is June 2019. An earlier --since requires an explicit --site scope;
that boundary and the latest collection date remain in each site's state.
WordPress event dates rank listings when available. Publication dates are only
ranking hints, never evidence of a proceeding's date.

Page associations use the page's own date and at least half the native title's
rarity-weighted subject. Shared menu lines and files are excluded from matching;
ambiguous ties remain unlinked. Existing associations survive changes in rarity
weights unless a newly explicit event date contradicts the native record.

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
import argparse, collections, datetime as dt, gzip, json, math, re
from pathlib import Path
from html import unescape

from lxml import html as dom

from congress_api import http
from congress_api.committees import codes_of
from congress_api.gpo.match import words
from congress_api.meeting_rules import HEARING_TYPES, meeting_access, meeting_type
from congress_api.inventory.common import due, in_inventory_scope, nonnegative, read_state, source_args, write_csv, write_state, text
from congress_api.senate.pages import (SITE, LISTINGS, HEARING_LINK, FIRST_RECORD, OWN, NEAR, BUSINESS, DATE,
    documents, witnesses, lines, written_day, topic, attachment_page, event_details, document_labels, source_details, KINDS)
from congress_api.senate.corrections import DATE_CORRECTIONS, selected_date
from congress_api.senate.matching import match_identifiers
from congress_api.models.content import RawContent
from congress_api.models.senate import ListingRow, SenatePage, WordPressHearingFields, WORDPRESS_POSTS, WORDPRESS_TYPES

PAGE_FIELDS = "event_id page title witnesses documents".split()
WITNESS_FIELDS = "event_id name position organization page location".split()
DOCUMENT_FIELDS = "event_id kind name url page source_labels witness_indexes witness_names".split()
PARSER_VERSION = 5

def listing_page(site, form, n, get):
    """(day, url, title) for the hearing pages one page of a listing shows. The day is the date written nearest the
    link; a listing that writes no year beside a link files it by year and month (/2026/3/<name>)."""
    page, rows = get(f"https://www.{site}{form.format(n)}"), []
    if not page.strip():
        return rows
    # Source row boundaries take precedence over proximity to another row.
    row_days = {}
    for anchor in dom.fromstring(page).xpath(".//a[@href]"):
        dates = anchor.xpath(".//time")
        if not dates:
            table_rows = anchor.xpath("ancestor::tr[1]")
            if table_rows:
                dates = table_rows[0].xpath(".//td[contains(concat(' ', normalize-space(@class), ' '), ' recordListDate ')]")
        day = next((written_day(match) for node in dates for match in DATE.finditer(node.text_content()) if written_day(match)), None)
        if day:
            row_days[anchor.get("href"), text(dom.tostring(anchor, encoding="unicode", with_tail=False))] = day
    written = re.sub(r"<[^>]+>", lambda tag: " " * len(tag.group()), page)  # the page's words, each where it stood
    for link in HEARING_LINK.finditer(page):
        near = sorted((abs(m.start() - link.start()), written_day(m)) for m in DATE.finditer(written, max(0, link.start() - 900), link.end() + 900) if written_day(m))
        filed = re.search(r"/(\d{4})/(\d{1,2})/[^/]+$", link.group(1))
        day = row_days.get((unescape(link.group(1)), text(link.group(2)))) or (near[0][1] if near else dt.date(int(filed.group(1)), int(filed.group(2)), 15) if filed else None)
        if day and text(link.group(2)):
            href = unescape(link.group(1))
            row = ListingRow(day=day, url=href if href.startswith("http") else f"https://www.{site}{href}", title=text(link.group(2)))
            rows.append((row.day, row.url, row.title))
    return rows


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
            if len(posts) < 100 or not held:
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


def match_pages(meetings, state):
    code = lambda r: r["committees"].split(";")[0]
    hearings, titles = [], collections.defaultdict(list)
    for m in meetings:
        codes = codes_of(m)
        if m.get("chamber") != "House" and codes:
            c = codes[0]
            titles[c].append(set(words(topic(m.get("title") or ""))))
            if c in SITE and m.get("date") and (meeting_access(m)[0] != "closed" or c in ("slia00", "scnc00")):
                hearings.append({"event_id": m["eventId"], "date": m["date"][:10], "title": (m.get("title") or "").strip(), "committees": ";".join(codes), "kind": meeting_type(m)[0]})
    ## a subject word weighs by how few of the committee's titles hold it
    held_in = {c: collections.Counter(w for t in ts for w in t) for c, ts in titles.items()}
    weight = lambda c, w: math.log(len(titles[c]) / held_in[c][w])

    sites = sorted({SITE[code(r)] for r in hearings} & set(state))
    hearings = [row for row in hearings if SITE[code(row)] in sites]
    listings = {s: {u: (dt.date.fromisoformat(v[0]), v[1]) for u, v in state[s]["listings"].items()} for s in sites}
    pages = {u: p for s in sites for u, p in state[s]["pages"].items() if u in listings[s]}
    found = {u: p.get("documents", []) for u, p in pages.items()}
    for listing in listings.values():
        for url in listing:
            found.setdefault(url, [])
    page_words, on_day = {}, collections.defaultdict(list)
    for s in sites:
        print(f"  {s}: {len(listings[s]):,} hearing pages listed, {sum(1 for u in listings[s] if pages.get(u, {})):,} read", flush=True)
        ## what many of a site's pages carry or link is the site's, not a hearing's
        written = {u: set(pages.get(u, {}).get("lines", [])) for u in listings[s]}
        carried_by = collections.Counter(l for u in listings[s] for l in written[u])
        linked_by = collections.Counter(file for u in listings[s] for _, _, file in found[u])
        for u in listings[s]:
            own = " \n ".join(l for l in written[u] if carried_by[l] <= OWN)
            page_words[u] = set(words(own))
            found[u] = [d for d in found[u] if linked_by[d[2]] <= OWN]
            event = pages.get(u, {}).get("event")
            days = {dt.date.fromisoformat(selected_date(u, event))} if event else {written_day(m) for m in DATE.finditer(own)}
            if u in DATE_CORRECTIONS:
                days.add(dt.date.fromisoformat(DATE_CORRECTIONS[u]["date"]))
            for day in days:
                on_day[s, day].append(u)

    found_pages, found_witnesses, found_documents, stats = [], [], [], collections.Counter(hearings=len(hearings))
    for r in hearings:
        e, c, day = r["event_id"], code(r), dt.date.fromisoformat(r["date"])
        named = lambda u: f"{u.rstrip('/').rsplit('/', 1)[-1]} {listings[SITE[c]][u][1]}"
        its = [(abs((listings[SITE[c]][u][0] - day).days), u) for u in on_day[SITE[c], day] if r["kind"] not in HEARING_TYPES or not BUSINESS.search(named(u)) or re.search(r"hearing|nominat", named(u), re.I)]
        stats["with a page that names the day"] += bool(its)
        subject = set(words(topic(r["title"])))
        whole = sum(weight(c, w) for w in sorted(subject))
        held = sorted((-sum(weight(c, w) for w in sorted(subject & page_words[u])) / whole if whole else -len(subject & page_words[u]) / max(1, len(subject)), away, -len(found[u]), u) for away, u in its if away <= NEAR)
        held = [h for h in held if -h[0] >= 0.5]
        best = [(u, pages.get(u, {}).get("witnesses", [])) for share, away, _, u in held if (share, away) == held[0][:2]]
        if not best or (len(best) > 1 and not best[0][1]) or any(sorted(w["name"] for w in people) != sorted(w["name"] for w in best[0][1]) for _, people in best):
            stats["whose pages that day hold under half of the subject"] += bool(its and not best)
            stats["whose pages that day hold as much of the subject as each other"] += bool(best)
            continue
        page, people = best[0]
        stats["with its page"] += 1
        files = found[page]
        found_pages.append({"event_id": e, "page": page, "title": pages[page]["title"], "witnesses": len(people), "documents": len(files)})
        found_witnesses += [{"event_id": e, **w, "page": page} for w in people]
        found_documents += [{"event_id": e, "kind": k, "name": n, "url": f, "page": page} for k, n, f in files]
        stats["with witnesses"] += bool(people)
        stats["with documents"] += bool(files)
        stats["with a transcript"] += any(k == "transcript" for k, _, _ in files)
    return found_pages, found_witnesses, found_documents




def retained_matches(state):
    """CSV views use the same saved associations as the downstream adapter."""
    pages, witnesses, documents = [], [], []
    for site in state.values():
        shared = collections.Counter(document[2] for url, page in site.get("pages", {}).items() if url in site.get("listings", {}) for document in page.get("documents", []))
        for url, page in site.get("pages", {}).items():
            files = [document for document in page.get("documents", []) if shared[document[2]] <= OWN]
            people = page.get("witnesses", [])
            for event in page.get("events", []):
                pages.append({"event_id": event, "page": url, "title": page.get("title", ""), "witnesses": len(people), "documents": len(files)})
                for index, person in enumerate(people):
                    metadata = (page.get("witness_metadata") or {}).get(str(index), {})
                    witnesses.append({"event_id": event, **person, "page": url, "location": metadata.get("location", "")})
                for kind, name, file in files:
                    metadata = (page.get("document_metadata") or {}).get(file, {})
                    indexes = metadata.get("witness_indexes", [])
                    documents.append({"event_id": event, "kind": kind, "name": name, "url": file, "page": url,
                                      "source_labels": json.dumps(metadata.get("labels", []), ensure_ascii=False),
                                      "witness_indexes": json.dumps(indexes),
                                      "witness_names": json.dumps([people[index]["name"] for index in indexes if isinstance(index, int) and 0 <= index < len(people)], ensure_ascii=False)})
    return pages, witnesses, documents

def mark_possible_matches(meetings, state):
    """Unresolved same-day native events prevent accidental duplicate admission.

    A date/committee collision alone never establishes a match. Keep the source
    event and its evidence, and expose the unresolved association for review.
    """
    native = collections.defaultdict(set)
    for meeting in meetings:
        if meeting.get("chamber") == "House" or not meeting.get("date"):
            continue
        for code in codes_of(meeting):
            host = SITE.get(code)
            if host:
                native[host, meeting["date"][:10]].add(str(meeting["eventId"]))
    for host, site in state.items():
        for url, page in site.get("pages", {}).items():
            if event := page.get("event"):
                page["candidate_events"] = sorted(native[host, selected_date(url, event)] - set(map(str, page.get("events") or [])))

def parse_page(page: str | bytes, url: str) -> SenatePage:
    """Read source bytes into a source model before normalization or storage."""
    original = page if isinstance(page, bytes) else page.encode("utf-8")
    page = original.decode("utf-8", "replace") if isinstance(page, bytes) else page
    title = re.search(r'<meta property="og:title" content="([^"]+)"|<title>(.*?)</title>', page, re.S)
    result = {"title": text(title.group(1) or title.group(2)).split(" | ")[0] if title else "",
              "lines": sorted(lines(page)), "witnesses": witnesses(page, url), "documents": documents(page, url)}
    if labels := document_labels(page, url):
        result["document_labels"] = labels
    result["document_metadata"], result["witness_metadata"], result["page_metadata"] = source_details(page, url, result["witnesses"])
    known = {row[2] for row in result["documents"]}
    for file, metadata in result["document_metadata"].items():
        if file not in known:
            label = next(iter(metadata["labels"]), "")
            kind = next((kind for kind, pattern in KINDS if re.search(pattern, f"{label} {file.rsplit('/', 1)[-1]}", re.I)), "other")
            result["documents"].append((kind, label or file.rsplit("/", 1)[-1], file))
    event = event_details(page, url)
    if event:
        result["event"] = event
        result["title"] = result["title"] or event["title"]
    result["raw_html"] = RawContent.from_bytes(original, "text/html").source_dict()
    return SenatePage.model_validate(result)


def parsed(page, url):
    """Compatibility writer for callers that need the existing dictionary shape."""
    return parse_page(page, url).model_dump(mode="python", by_alias=True, exclude_unset=True)


def seed_fetch(cache, url):
    path = cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
    return path.read_bytes().decode("utf-8", "replace") if path.exists() else ""


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
    """The hearing-page reader accepts text, never a PDF decoded as UTF-8."""
    headers = getattr(response, "headers", {})
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    if response.content.lstrip().startswith(b"%PDF-") or content_type.split(";", 1)[0].strip().lower() == "application/pdf":
        receipt.update(outcome="unsupported_format", detected_format="pdf")
        if content_type:
            receipt["content_type"] = content_type
        raise ValueError(f"Senate hearing-page reader received PDF content from {url}")
    return response.content.decode("utf-8", "replace")


def fetch_page(url, previous, today, *, cache=None, check=None):
    """Read one page, retaining schedule dates separately from actual receipts."""
    check = check if check is not None else {}
    if cache is not None:
        result = parsed(seed_fetch(cache, url), url)
        path = cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
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
    if since is not None and since < FIRST_RECORD and not site:
        raise ValueError("Historical collection before June 2019 requires an explicit --site scope")
    # Collection/admission must see canceled and historical native meetings too;
    # the inventory's reporting filter would make them look like missing events.
    with gzip.open(meetings, "rt", encoding="utf-8") as stream:
        native_meetings = list(map(json.loads, stream))
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
                raw_path = seed_cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
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
    found = match_pages(ms, state)
    # A changing site corpus changes rarity weights. Keep a previously supported
    # association unless the page's explicit event date now contradicts it.
    previous = {url: list(page.get("events") or []) for saved in state.values() for url, page in saved["pages"].items()}
    native = collections.defaultdict(list)
    for meeting in native_meetings:
        native[str(meeting["eventId"])].append(meeting)
    for host, saved in state.items():
        for url, page in saved["pages"].items():
            event = page.get("event")
            page["events"] = [identifier for identifier in previous[url] if not event or any(
                meeting.get("date", "")[:10] == selected_date(url, event) and any(SITE.get(code) == host for code in codes_of(meeting))
                for meeting in native[str(identifier)])]
    for row in found[0]:
        for saved in state.values():
            if row["page"] in saved["pages"]:
                page = saved["pages"][row["page"]]
                if row["event_id"] not in page["events"]:
                    page["events"].append(row["event_id"])
                    page.setdefault("match_details", {})[row["event_id"]] = {
                        "method": "senate.records.match_pages", "version": "2",
                    }
    match_identifiers(native_meetings, state)
    mark_possible_matches(native_meetings, state)
    write_state(path, state)
    found = retained_matches(state)
    for name, rows, fields in zip(("senate_hearing_pages_found", "senate_witnesses_found", "senate_documents_found"), found, (PAGE_FIELDS, WITNESS_FIELDS, DOCUMENT_FIELDS)):
        write_csv(output_dir / f"{name}.csv", rows, fields)
        totals[name] = len(rows)
    print(dict(totals), dict(http.COUNTS))


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--refresh-limit", type=nonnegative, default=450)
    p.add_argument("--site", action="append", choices=sorted(SITE.values()), help="limit live fetching to these sites; retain other saved sites")
    p.add_argument("--since", type=dt.date.fromisoformat, help="earliest listing day; before June 2019 requires --site")
    p.add_argument("--limit", type=nonnegative, help="maximum live hearing pages (listings are additional)")
    main(**vars(p.parse_args()))
