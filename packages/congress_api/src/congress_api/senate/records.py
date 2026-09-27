"""senate-meeting-records: find and read Senate and joint committees' hearing pages.

Read the meeting export, discover listings on 21 committee sites, and match
pages by their own date and at least half their rarity-weighted subject. Ignore
lines/documents shared by more than five pages, business meetings and listings
more than a year away. Tied pages must name the same witnesses. Aging's listing
misdated 68/78 hearings; listing dates therefore only rank candidates.

Write senate_hearing_pages_found.csv, senate_witnesses_found.csv and
senate_documents_found.csv. State retains parsed text lines for the site-wide
menu check, witnesses, documents, listing routes/dates, checks and absences;
never HTML. Weekly discovery stops after two overlapping known listing pages.
New/changed records get priority, with 450 age-based page refreshes per run.
--seed-cache imports the research cache read-only for the initial backfill.

Finding the page. A site's hearings are listed one of two ways:

- the WordPress sites that record when a hearing is held (Homeland Security, Indian Affairs) answer
  /wp-json/wp/v2/<type> for each of their hearing types, a hundred hearings to a request;
- the rest list their hearings a page at a time, at /hearings?PageNum_rs=N, /hearings/?mt_page=N,
  /hearings?page=N and the like. The form a site uses is the one whose second page lists hearings its
  first does not; a site that counts its pages from 0 lists other hearings there than on page 1.

A backfill reads listings back to the first Senate meeting record (June 2019), and fetches
every listed page. Later runs refresh new, changed and due pages. A listing says which pages there are, not when each hearing was: some sites file a hearing
under the day it was announced, and the date read off a listing is the one written nearest the link,
which on some sites is the row above's. The page says when. A page is the hearing's when it names the
hearing's date and holds most of the meeting's subject, both in its own text: a line that more than
five of the site's pages carry is the site's (a menu naming every subcommittee, a panel of coming
hearings with their dates). Subject words are weighed by how rare they are in the committee's titles:
"budget", "fiscal" and "year" are in every Appropriations title and say little; "Interior" says which
hearing. A later page can name the day and the subject too: the business meeting that reports a
nominee gives the day of the nominee's hearing, and an oversight hearing recalls the last one. So a
business meeting's page is not a hearing's, and neither is a page listed more than a year from the
day. Of the rest, the page with the most of the subject is taken when it holds at least half; when two
hold as much, the one listed nearer the day, and when they are listed as near, neither, unless they
list the same witnesses: a site that lists one hearing at two addresses.

A search engine was tried first and found the page for one hearing in five: Congress.gov's titles
paraphrase the committees' ("Hearings to examine the state of patent eligibility in America"), and
searches return testimony files ahead of the page they belong to.

Reading the page. The sites come in seven layouts:

- a list of `vcard`s with `fn`, `title` and `org` (Finance, Appropriations, Budget, Banking);
- a name over `witness-content` details, in a list item, under a "Witnesses", "Nominees" or "Panel"
  heading (Judiciary, Armed Services, HELP, Aging, Foreign Relations ...);
- `capigacr-widget-card`s in a "Testimony" panel (Commerce, Energy);
- list items with a `person` or `full-name`, an `occupation` and an `organization` (Veterans'
  Affairs, Environment and Public Works, Small Business);
- `field-hearing-new-witness` items, the name in a `group-header` (Indian Affairs' older hearings);
- `paragraph--witness` items with a field each for name, position and organization (the Helsinki
  Commission);
- a `jet-listing-grid` under a "Witnesses" heading, first and last name in separate headings (HSGAC).

Senators' statements are laid out like witnesses, under a heading of their own ("Member Statements",
"Opening Remarks"); those sections are passed over. Not read: the Joint Economic Committee's pages,
which name witnesses in running text, and Indian Affairs' newer pages, which fill the list in the
browser. The Helsinki Commission's site, csce.gov, is not the Senate's but is read the same way.

Documents are the files a page links (/download/, /wp-content/uploads/ ...), less the files that more
than five of the site's pages link (the committee's rules, a report in the margin). Each is typed by
what its link or file name says.


"""
import argparse, collections, datetime as dt, json, math, re
from pathlib import Path

from congress_api import http
from congress_api.committees import codes_of
from congress_api.gpo.match import words
from congress_api.inventory.common import CLOSED, due, kind, nonnegative, read_meetings, read_state, source_args, write_csv, write_state, text
from congress_api.senate.pages import (SITE, LISTINGS, HEARING_LINK, FIRST_RECORD, OWN, NEAR, BUSINESS, DATE,
    documents, witnesses, lines, written_day, topic)

PAGE_FIELDS = "event_id page title witnesses documents".split()
WITNESS_FIELDS = "event_id name position organization page".split()
DOCUMENT_FIELDS = "event_id kind name url page".split()

def listing_page(site, form, n, get):
    """(day, url, title) for the hearing pages one page of a listing shows. The day is the date written nearest the
    link; a listing that writes no year beside a link files it by year and month (/2026/3/<name>)."""
    page, rows = get(f"https://www.{site}{form.format(n)}"), []
    written = re.sub(r"<[^>]+>", lambda tag: " " * len(tag.group()), page)  # the page's words, each where it stood
    for link in HEARING_LINK.finditer(page):
        near = sorted((abs(m.start() - link.start()), written_day(m)) for m in DATE.finditer(written, max(0, link.start() - 900), link.end() + 900) if written_day(m))
        filed = re.search(r"/(\d{4})/(\d{1,2})/[^/]+$", link.group(1))
        day = near[0][1] if near else dt.date(int(filed.group(1)), int(filed.group(2)), 15) if filed else None
        if day and text(link.group(2)):
            rows.append((day, link.group(1) if link.group(1).startswith("http") else f"https://www.{site}{link.group(1)}", text(link.group(2))))
    return rows


def wordpress_listed(site, get):
    """(day, url, title) for every hearing a WordPress site holds, when the site records the day a hearing is held."""
    try:
        types = json.loads(get(f"https://www.{site}/wp-json/wp/v2/types") or "{}")
    except ValueError:
        return []
    out = []
    for base in sorted({t["rest_base"] for t in types.values() if re.search(r"hearing|meeting", t.get("rest_base", "")) and "file" not in t["rest_base"]} if isinstance(types, dict) else ()):
        for n in range(1, 100):
            try:
                posts = json.loads(get(f"https://www.{site}/wp-json/wp/v2/{base}?per_page=100&page={n}&_fields=link,title,acf") or "[]")
            except ValueError:
                break
            held = [(p["acf"]["hearing_date_time"], p) for p in posts if isinstance(p.get("acf"), dict) and re.match(r"\d{4}-\d\d-\d\d", p["acf"].get("hearing_date_time") or "")]
            out += [(dt.date.fromisoformat(day[:10]), p["link"], text(p["title"]["rendered"])) for day, p in held]
            if len(posts) < 100 or not held:
                break
    return out


def listed(site, get, saved=None):
    """(day, url, title) for the hearing pages a site lists, back to the first Senate meeting record."""
    out = [r for r in wordpress_listed(site, get) if r[0] >= FIRST_RECORD] if not saved or saved.get("wordpress") else []
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
        if max(r[0] for r in new) < FIRST_RECORD:
            break
    return out, {"form": form, "from_0": bool(from_0)}


def match_pages(meetings, state):
    code = lambda r: r["committees"].split(";")[0]
    hearings, titles = [], collections.defaultdict(list)
    for m in meetings:
        codes = codes_of(m)
        if m.get("chamber") != "House" and codes:
            c = codes[0]
            titles[c].append(set(words(topic(m.get("title") or ""))))
            if kind(m) == "hearing" and not CLOSED.search(f"{m.get('type')} {m.get('title')}") and c in SITE:
                hearings.append({"event_id": m["eventId"], "date": m["date"][:10], "title": (m.get("title") or "").strip(), "committees": ";".join(codes)})
    ## a subject word weighs by how few of the committee's titles hold it
    held_in = {c: collections.Counter(w for t in ts for w in t) for c, ts in titles.items()}
    weight = lambda c, w: math.log(len(titles[c]) / held_in[c][w])

    sites = sorted({SITE[code(r)] for r in hearings})
    listings = {s: {u: (dt.date.fromisoformat(v[0]), v[1]) for u, v in state[s]["listings"].items()} for s in sites}
    pages = {u: p for s in sites for u, p in state[s]["pages"].items() if u in listings[s]}
    found = {u: p["documents"] for u, p in pages.items()}
    page_words, on_day = {}, collections.defaultdict(list)
    for s in sites:
        print(f"  {s}: {len(listings[s]):,} hearing pages listed, {sum(1 for u in listings[s] if pages[u]):,} read", flush=True)
        ## what many of a site's pages carry or link is the site's, not a hearing's
        written = {u: set(pages[u]["lines"]) for u in listings[s]}
        carried_by = collections.Counter(l for u in listings[s] for l in written[u])
        linked_by = collections.Counter(file for u in listings[s] for _, _, file in found[u])
        for u in listings[s]:
            own = " \n ".join(l for l in written[u] if carried_by[l] <= OWN)
            page_words[u] = set(words(own))
            found[u] = [d for d in found[u] if linked_by[d[2]] <= OWN]
            for day in {written_day(m) for m in DATE.finditer(own)}:
                on_day[s, day].append(u)

    found_pages, found_witnesses, found_documents, stats = [], [], [], collections.Counter(hearings=len(hearings))
    for r in hearings:
        e, c, day = r["event_id"], code(r), dt.date.fromisoformat(r["date"])
        named = lambda u: f"{u.rstrip('/').rsplit('/', 1)[-1]} {listings[SITE[c]][u][1]}"
        its = [(abs((listings[SITE[c]][u][0] - day).days), u) for u in on_day[SITE[c], day] if not BUSINESS.search(named(u)) or re.search(r"hearing|nominat", named(u), re.I)]
        stats["with a page that names the day"] += bool(its)
        subject = set(words(topic(r["title"])))
        whole = sum(weight(c, w) for w in sorted(subject))
        held = sorted((-sum(weight(c, w) for w in sorted(subject & page_words[u])) / whole if whole else 0.0, away, -len(found[u]), u) for away, u in its if away <= NEAR)
        held = [h for h in held if -h[0] >= 0.5]
        best = [(u, pages[u]["witnesses"]) for share, away, _, u in held if (share, away) == held[0][:2]]
        if not best or any(sorted(w["name"] for w in people) != sorted(w["name"] for w in best[0][1]) for _, people in best):
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


def parsed(page, url):
    title = re.search(r'<meta property="og:title" content="([^"]+)"|<title>(.*?)</title>', page, re.S)
    return {"title": text(title.group(1) or title.group(2)).split(" | ")[0] if title else "",
            "lines": sorted(lines(page)), "witnesses": witnesses(page, url), "documents": documents(page, url)}


def seed_fetch(cache, url):
    path = cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
    return path.read_text() if path.exists() else ""


def main(meetings, state_dir, output_dir, seed_cache=None, offline=False, as_of=None, refresh_limit=450, site=None, limit=None):
    ms, path = read_meetings(meetings), state_dir / "senate.json.gz"
    state, totals = read_state(path), collections.Counter()
    versions = collections.defaultdict(dict)
    for m in ms:
        codes = codes_of(m)
        if m.get("chamber") != "House" and codes and codes[0] in SITE:
            versions[SITE[codes[0]]][m["eventId"]] = m.get("updateDate", "")
    errors, live_pages, refreshed = [], 0, 0
    for host in sorted(versions):
        if site and host not in site:
            continue
        saved = state.get(host, {})
        importing = not saved and seed_cache is not None
        if offline and not importing:
            if not saved:
                errors.append(f"{host}: no saved listing")
            continue
        def get(url):
            if importing:
                return seed_fetch(seed_cache, url)
            response = http.get_with_retry(None, url, allowed=(200, 400, 404))
            return response.content.decode("utf-8", "replace") if response.status_code == 200 else ""
        try:
            if importing or not saved or saved.get("versions") != versions[host] or (as_of - dt.date.fromisoformat(saved["checked"])).days >= 7:
                rows, route = listed(host, get, saved)
                if not rows and not importing:
                    raise ValueError(f"{host}: previously working listing returned no hearings")
                listing = {**saved.get("listings", {}), **{u: [d.isoformat(), t] for d, u, t in rows}}
                saved = {**saved, **route, "checked": as_of.isoformat(), "listings": listing, "pages": saved.get("pages", {})}
                totals["sites listed"] += 1
            pages = saved["pages"]
            changed = {e for e, v in versions[host].items() if saved.get("versions", {}).get(e) != v}
            urgent, aged = [], []
            for url, (day, _) in saved["listings"].items():
                previous = pages.get(url)
                if not previous or changed.intersection(previous.get("events", [])):
                    urgent.append(url)
                elif due(previous, day, previous.get("version"), as_of):
                    aged.append(url)
            aged.sort(key=lambda u: (pages[u]["checked"], u))
            for url in urgent + aged[:max(0, refresh_limit - refreshed)]:
                if limit is not None and live_pages >= limit and not importing:
                    break
                if importing:
                    page, absent = get(url), False
                else:
                    response = http.get_with_retry(None, url, allowed=(200, 404))
                    page, absent = response.content.decode("utf-8", "replace"), response.status_code == 404
                if absent:
                    # A gone page is a confirmed absence. Other HTTP failures raise above.
                    result = {"title": "", "lines": [], "witnesses": [], "documents": [], "absent": True}
                else:
                    result = parsed(page, url)
                    if not importing and not result["title"]:
                        raise ValueError(f"{host}: unrecognized hearing page {url}")
                pages[url] = {**result, "checked": as_of.isoformat(), "version": "", "events": pages.get(url, {}).get("events", [])}
                totals["pages seeded" if importing else "pages fetched"] += 1
                if not importing:
                    live_pages += 1
                    refreshed += url in aged
            if limit is None or live_pages < limit:
                saved["versions"] = versions[host]
            state[host] = saved
        except (ValueError, RuntimeError, OSError) as error:
            errors.append(str(error))
            if saved:
                state[host] = saved
    write_state(path, state)
    missing = [host for host in versions if host not in state or any(u not in state[host]["pages"] for u in state[host]["listings"])]
    if errors or missing:
        raise RuntimeError(f"Senate source incomplete: {errors[:5] or missing}")
    found = match_pages(ms, state)
    for host in state:
        for page in state[host]["pages"].values():
            page["events"] = []
    for r in found[0]:
        for host in state:
            if r["page"] in state[host]["pages"]:
                state[host]["pages"][r["page"]]["events"].append(r["event_id"])
    write_state(path, state)
    for name, rows, fields in zip(("senate_hearing_pages_found", "senate_witnesses_found", "senate_documents_found"), found, (PAGE_FIELDS, WITNESS_FIELDS, DOCUMENT_FIELDS)):
        write_csv(output_dir / f"{name}.csv", rows, fields)
        totals[name] = len(rows)
    print(dict(totals), dict(http.COUNTS))


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--refresh-limit", type=nonnegative, default=450)
    p.add_argument("--site", action="append", choices=sorted(SITE.values()), help="limit live fetching to these sites; retain other saved sites")
    p.add_argument("--limit", type=nonnegative, help="maximum live hearing pages (listings are additional)")
    main(**vars(p.parse_args()))
