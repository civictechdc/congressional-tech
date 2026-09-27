"""
Read Senate committees' own hearing pages for the witness lists and documents Congress.gov doesn't have.

    python docs/youtube-coverage/research/scripts/senate_hearing_pages.py [--cache ~/hearing-text] [--threads 8]

Congress.gov lists no witnesses for Senate meetings and documents for fewer than a third of them. The
committees' sites have both. For every open Senate or joint hearing in the text index whose committee
has a site here, this finds the committee's page for the hearing and reads its witnesses and documents.

Finding the page. A site's hearings are listed one of two ways:

- the WordPress sites that record when a hearing is held (Homeland Security, Indian Affairs) answer
  /wp-json/wp/v2/<type> for each of their hearing types, a hundred hearings to a request;
- the rest list their hearings a page at a time, at /hearings?PageNum_rs=N, /hearings/?mt_page=N,
  /hearings?page=N and the like. The form a site uses is the one whose second page lists hearings its
  first does not.

Listings are read back to the first Senate meeting record (June 2019), and every page they list is
fetched. A listing says which pages there are, not when each hearing was: some sites file a hearing
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

Reading the page. The sites come in six layouts:

- a list of `vcard`s with `fn`, `title` and `org` (Finance, Appropriations, Budget, Banking);
- a name over `witness-content` details, in a list item, under a "Witnesses", "Nominees" or "Panel"
  heading (Judiciary, Armed Services, HELP, Aging, Foreign Relations ...);
- `capigacr-widget-card`s in a "Testimony" panel (Commerce, Energy);
- list items with a `person` or `full-name`, an `occupation` and an `organization` (Veterans'
  Affairs, Environment and Public Works, Small Business);
- `field-hearing-new-witness` items, the name in a `group-header` (Indian Affairs' older hearings);
- a `jet-listing-grid` under a "Witnesses" heading, first and last name in separate headings (HSGAC).

Senators' statements are laid out like witnesses, under a heading of their own ("Member Statements",
"Opening Remarks"); those sections are passed over. Not read: the Joint Economic Committee's pages,
which name witnesses in running text, and Indian Affairs' newer pages, which fill the list in the
browser.

Documents are the files a page links (/download/, /wp-content/uploads/ ...), less the files that more
than five of the site's pages link (the committee's rules, a report in the margin). Each is typed by
what its link or file name says.

Writes, under docs/youtube-coverage/research/data/:

- senate_hearing_pages_found.csv: event_id, page, title (the page's own, which says POSTPONED or
  CANCELLED when the hearing was), witnesses and documents (how many of each the page gave);
- senate_witnesses_found.csv: event_id, name, position, organization, page;
- senate_documents_found.csv: event_id, kind (witness statement, member statement, transcript,
  questions for the record, questionnaire, witness biography, other), name, url, page.

Listings and pages are cached under `--cache`/senate_pages, so a rerun fetches only what failed.
"""
import argparse, collections, csv, datetime as dt, gzip, html, json, math, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
from congress_api.gpo.match import words  # noqa: E402
from congress_api.transcribe.metadata import is_name, witness  # noqa: E402
from meeting_completeness import CLOSED, INDEX, MEETINGS, kind  # noqa: E402

OUT_PAGES = ROOT / "docs/youtube-coverage/research/data/senate_hearing_pages_found.csv"
OUT_WITNESSES = ROOT / "docs/youtube-coverage/research/data/senate_witnesses_found.csv"
OUT_DOCUMENTS = ROOT / "docs/youtube-coverage/research/data/senate_documents_found.csv"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
## where each committee keeps its hearing pages
SITE = {"ssaf00": "agriculture.senate.gov", "ssap00": "appropriations.senate.gov", "ssas00": "armed-services.senate.gov", "ssbk00": "banking.senate.gov",
        "ssbu00": "budget.senate.gov", "sscm00": "commerce.senate.gov", "sseg00": "energy.senate.gov", "ssev00": "epw.senate.gov", "ssfi00": "finance.senate.gov",
        "ssfr00": "foreign.senate.gov", "ssga00": "hsgac.senate.gov", "sshr00": "help.senate.gov", "ssju00": "judiciary.senate.gov", "ssra00": "rules.senate.gov",
        "sssb00": "sbc.senate.gov", "ssva00": "veterans.senate.gov", "slia00": "indian.senate.gov", "spag00": "aging.senate.gov", "slin00": "intelligence.senate.gov",
        "jsec00": "jec.senate.gov"}
## the forms a listing's address takes
LISTINGS = ["/hearings?PageNum_rs={}", "/committee-activity/hearings?PageNum_rs={}", "/hearings/?mt_page={}", "/committee-activity/hearings/?mt_page={}",
            "/hearings?page={}", "/public/index.cfm/hearings?page={}", "/public/index.cfm/hearings-calendar?page={}", "/hearings-and-markups?PageNum_rs={}"]
## a hearing's page: /hearings/<name>, /meetings/<name>, hearings?ID=<id>, /2024/5/<name>
HEARING_LINK = re.compile(r"<a[^>]+href=\"((?:https?://[\w.\-]+)?/(?:[\w\-/.]*/)?(?:(?:hearings?|meetings|hearings-and-markups)/[^\"#?]+|hearings(?:-calendar)?\?(?:ID|id)=[\w\-]+"
                          r"|\d{4}/\d{1,2}/[^\"#?/]+))\"[^>]*>(.*?)</a>", re.S)
FIRST_RECORD = dt.date(2019, 6, 1)  # Congress.gov's Senate meeting records begin in June 2019
OWN = 5  # a line on more of a site's pages than this is the site's, not a hearing's
NEAR = 365  # days between a page's place in the listing and its hearing, at most
## a page that is a business meeting's, by its name in the address and its title in the listing
BUSINESS = re.compile(r"business[ \-_]meeting|executive[ \-_](?:business[ \-_])?session|mark[ \-_]?up", re.I)
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
## "6/12/2019", "06.12.19", "June 12, 2019", "Wednesday, March 11th, 2026", "Jun 24, 2026", "2019-06-12"
DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b|\b((?:" + "|".join(MONTHS) + r")[a-z]*)\.? (\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", re.I)
## a file a page links, and what its link or name says it is
FILE = re.compile(r"<a\b[^>]*href=\"([^\"]*(?:/download/|/wp-content/uploads/|/_cache/files/|/imo/media/doc/|/services/files/|/sites/default/files/|files\.serve|\.pdf)[^\"]*)\"[^>]*>(.*?)</a>", re.S | re.I)
KINDS = [("transcript", r"transcript"), ("questions for the record", r"qfr|questions?[ \-_]for[ \-_]the[ \-_]record|responses?[ \-_]to[ \-_](?:written[ \-_])?questions"),
         ("questionnaire", r"questionnaire"), ("witness biography", r"\bbio(?:graphy)?\b|/bio_"), ("witness statement", r"testimony"), ("member statement", r"statement")]
text = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def person(name, details, page):
    """One witness row from a name as the page writes it ("The Honorable Jay Bhattacharya, M.D., Ph.D.") and the lines under it."""
    details = [d for d in (text(d) for d in details) if d and not re.match(r"(download|view|watch) ", d, re.I)]
    return {"name": witness(text(name)).name, "position": details[0] if details else "", "organization": ", ".join(details[1:3]), "page": page}


def sections(page_html, levels):
    """The page cut at its headings, less the sections headed as statements or remarks: the senators', laid out like witnesses."""
    return [s for s in re.split(rf"(?=<h[{levels}]\b)", page_html) if not (s.startswith("<h") and re.search(r"statement|remarks", text(s.split("</h")[0]), re.I))]


def witnesses(page_html, url):
    """The witnesses a hearing page lists, by whichever of the six layouts it uses."""
    page_html, out = re.sub(r"<!--.*?-->", "", page_html, flags=re.S), []
    if "capigacr-widget-card" in page_html:
        for section in re.split(r"capigacr-widget-card__panel-section\"", page_html)[1:]:
            heading = re.search(r"panel-section-title[^>]*>(.*?)</h2>", section, re.S)
            if heading and re.search(r"statement", text(heading.group(1)), re.I):
                continue  # senators' statements are laid out like witnesses
            for card in re.split(r"<li class=\"capigacr-widget-card\"", section)[1:]:
                name = re.search(r"capigacr-widget-card__title[^>]*>(.*?)</h3>", card, re.S)
                if name:
                    out.append(person(name.group(1), re.findall(r"member-detail-item[^>]*>(.*?)</div>", card, re.S), url))
    elif "witness-content" in page_html:
        for item in ("<li" + i for s in sections(page_html, "2") for i in re.split(r"<li\b", s)[1:]):
            details = re.search(r"<div class=\"witness-content[^\"]*\">(.*?)</div>\s*</div>", item, re.S)
            if details:
                ## the name is the item's heading, and what stands between it and the details is the post; with no
                ##  heading, the name is the last line above the details: "1. XIAO Qiang", "Robert L. Listenbee, Jr."
                above = [l for l in (text(l) for l in re.split(r"</(?:p|div|h\d)>", item[:details.start()])) if l]
                heading = list(re.finditer(r"<h\d[^>]*>(.*?)</h\d>", item[:details.start()], re.S))
                post = [l for l in (text(l) for l in re.split(r"</(?:p|div)>", item[heading[-1].end():details.start()])) if l] if heading else []
                if above:
                    out.append(person(re.sub(r"^\d+\.\s*", "", text(heading[-1].group(1)) if heading else above[-1]),
                                      post + re.findall(r"<div>(.*?)</div>", details.group(1), re.S), url))
    elif "class=\"vcard" in page_html:
        start = re.search(r">\s*(Witnesses|Nominees|Panel)", page_html)
        for card in re.split(r"<li[^>]*class=\"vcard", page_html[start.start() if start else 0:])[1:]:
            card = card.split("</li>")[0] if "class=\"party\"" not in card.split("<ul")[0] else ""
            name = re.search(r"class=\"fn\">((?:\s*<span[^>]*>[^<]*</span>)*[^<]*)</span>", card, re.S)  # "<span>Dr.</span> Saule T. Omarova"
            if name:
                prefix = re.search(r"class=\"honorific-prefix\">(.*?)</span>", card, re.S)
                out.append(person(f"{text(prefix.group(1)) if prefix else ''} {text(name.group(1))}", re.findall(r"class=\"(?:title|org)\">(.*?)</div>", card, re.S), url))
    elif re.search(r"class=\"(?:full-name|person)\"", page_html):
        for item in (i for s in sections(page_html, "23") for i in re.split(r"<li class=\"[^\"]*list-group-item", s)[1:]):
            name = re.search(r"class=\"(?:full-name|person)\">(.*?)</(?:h4|div)>", item, re.S)
            if name:
                out.append(person(name.group(1), re.findall(r"class=\"(?:occupation|organization)\">(.*?)</div>", item, re.S), url))
    elif "field-hearing-new-witness" in page_html:
        for item in re.split(r"field-collection-item-field-hearing-new-witness", page_html)[1:]:
            name = re.search(r"class=\"group-header\">(.*?)</div>", item, re.S)
            if name:
                out.append(person(name.group(1), re.findall(r"<(?:em|span)>(.*?)</(?:em|span)>", item.split("more-link")[0], re.S), url))
    else:
        start = re.search(r">\s*Witnesses\s*</h\d>", page_html)
        for item in re.split(r"jet-listing-grid__item ", page_html[start.start():] if start else "")[1:]:
            names = re.findall(r"<h3 class=\"jet-listing-dynamic-field__content\">(.*?)</h3>", item, re.S)
            if names:
                out.append(person(" ".join(names), re.findall(r"<div class=\"jet-listing-dynamic-field__content\">(.*?)</div>", item, re.S), url))
    seen = set()
    return [w for w in out if is_name(w["name"]) and not (w["name"] in seen or seen.add(w["name"]))]


def documents(page_html, url):
    """(kind, name, file) for each file a hearing page links. The name is the link's own words, or, under a button
    ("Download Testimony"), the heading it stands under: the witness or senator whose file it is."""
    page_html, out = re.sub(r"<!--.*?-->", "", page_html, flags=re.S), {}
    for link in FILE.finditer(page_html):
        file = html.unescape(link.group(1)).strip()
        if re.search(r"\.(jpe?g|png|gif|svg|css|js|ico)($|\?)", file, re.I):
            continue
        file = file if file.startswith("http") else "https://" + re.match(r"https?://([^/]+)", url).group(1) + "/" + file.lstrip("/")
        said = text(link.group(2))
        heading = re.findall(r"<h[2-5][^>]*>(.*?)</h[2-5]>", page_html[max(0, link.start() - 2500):link.start()], re.S)
        name = text(heading[-1]) if heading and (not said or re.match(r"(download|view|read|open)\b", said, re.I)) else said
        out.setdefault(file, (next((k for k, pattern in KINDS if re.search(pattern, f"{said} {file.rsplit('/', 1)[-1]}", re.I)), "other"), name, file))
    return list(out.values())


def written_day(match):
    try:
        if match.group(1):
            year = int(match.group(3))
            return dt.date(year if year > 99 else 2000 + year, int(match.group(1)), int(match.group(2)))
        if match.group(4):
            return dt.date(int(match.group(6)), MONTHS.index(match.group(4)[:3].lower()) + 1, int(match.group(5)))
        return dt.date(int(match.group(7)), int(match.group(8)), int(match.group(9)))
    except ValueError:
        return None


def lines(page_html):
    """The lines of a page's text: what stands between one block's tag and the next."""
    page_html = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", " ", page_html, flags=re.S)
    return {text(l) for l in re.split(r"</?(?:div|p|li|ul|ol|h\d|tr|td|th|table|section|article|header|footer|nav|aside|main|form|dl|dt|dd|br)\b[^>]*>", page_html)} - {""}


def fetch(url, cache):
    """The page at `url`, fetched once; a failed fetch is not kept, so a rerun tries it again."""
    path = cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
    if not path.exists() or not path.stat().st_size:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = requests.get(url, timeout=45, headers=UA)
        except requests.RequestException:
            return ""
        if response.status_code != 200:
            return ""
        path.write_text(response.text)
    return path.read_text()


def listing_page(site, form, n, cache):
    """(day, url, title) for the hearing pages one page of a listing shows. The day is the date written nearest the
    link; a listing that writes no year beside a link files it by year and month (/2026/3/<name>)."""
    page, rows = fetch(f"https://www.{site}{form.format(n)}", cache), []
    written = re.sub(r"<[^>]+>", lambda tag: " " * len(tag.group()), page)  # the page's words, each where it stood
    for link in HEARING_LINK.finditer(page):
        near = sorted((abs(m.start() - link.start()), written_day(m)) for m in DATE.finditer(written, max(0, link.start() - 900), link.end() + 900) if written_day(m))
        filed = re.search(r"/(\d{4})/(\d{1,2})/[^/]+$", link.group(1))
        day = near[0][1] if near else dt.date(int(filed.group(1)), int(filed.group(2)), 15) if filed else None
        if day and text(link.group(2)):
            rows.append((day, link.group(1) if link.group(1).startswith("http") else f"https://www.{site}{link.group(1)}", text(link.group(2))))
    return rows


def wordpress_listed(site, cache):
    """(day, url, title) for every hearing a WordPress site holds, when the site records the day a hearing is held."""
    try:
        types = json.loads(fetch(f"https://www.{site}/wp-json/wp/v2/types", cache) or "{}")
    except ValueError:
        return []
    out = []
    for base in sorted({t["rest_base"] for t in types.values() if re.search(r"hearing|meeting", t.get("rest_base", "")) and "file" not in t["rest_base"]} if isinstance(types, dict) else ()):
        for n in range(1, 100):
            try:
                posts = json.loads(fetch(f"https://www.{site}/wp-json/wp/v2/{base}?per_page=100&page={n}&_fields=link,title,acf", cache) or "[]")
            except ValueError:
                break
            held = [(p["acf"]["hearing_date_time"], p) for p in posts if isinstance(p.get("acf"), dict) and re.match(r"\d{4}-\d\d-\d\d", p["acf"].get("hearing_date_time") or "")]
            out += [(dt.date.fromisoformat(day[:10]), p["link"], text(p["title"]["rendered"])) for day, p in held]
            if len(posts) < 100 or not held:
                break
    return out


def listed(site, cache):
    """(day, url, title) for the hearing pages a site lists, back to the first Senate meeting record."""
    out = [r for r in wordpress_listed(site, cache) if r[0] >= FIRST_RECORD]
    if out:
        return out
    first = {f: {r[1] for r in listing_page(site, f, 1, cache)} for f in LISTINGS}
    form = next((f for f in LISTINGS if first[f] and {r[1] for r in listing_page(site, f, 2, cache)} - first[f]), None) or next((f for f in LISTINGS if first[f]), None)
    for n in range(1, 300) if form else ():
        have = {o[1] for o in out}
        new = [r for r in listing_page(site, form, n, cache) if r[1] not in have]
        if not new:
            break  # past the last page, the site repeats or empties
        out += new
        if max(r[0] for r in new) < FIRST_RECORD:
            break
    return out


def topic(title):
    """The subject of a Senate meeting title: "Hearings to examine improving veterans' employment ..." -> "improving veterans' employment ..."."""
    return re.sub(r"^\s*(an? )?(oversight |joint )*hearings? (to examine|to receive testimony on|on)\s+", "", re.sub(r"\s+", " ", title), flags=re.I)


def main(cache, threads):
    index = {r["event_id"]: r for r in csv.DictReader(open(INDEX))}
    code = lambda r: r["committees"].split(";")[0]
    hearings, titles = [], collections.defaultdict(list)
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            r = index.get(m["eventId"])
            if r and m.get("chamber") != "House":
                titles[code(r)].append(set(words(topic(r["title"]))))
                ## a record of a hearing that was put off is read too: its page is what says so
                if kind(m) == "hearing" and not CLOSED.search(f"{m.get('type')} {m.get('title')}") and code(r) in SITE:
                    hearings.append(r)
    ## a subject word weighs by how few of the committee's titles hold it
    held_in = {c: collections.Counter(w for t in ts for w in t) for c, ts in titles.items()}
    weight = lambda c, w: math.log(len(titles[c]) / held_in[c][w])

    with ThreadPoolExecutor(threads) as pool:
        sites = sorted({SITE[code(r)] for r in hearings})
        listings = dict(zip(sites, pool.map(lambda s: {u: (d, t) for d, u, t in listed(s, cache)}, sites)))
        urls = [u for s in sites for u in listings[s]]
        pages = dict(zip(urls, pool.map(lambda u: fetch(u, cache), urls)))
    found = {u: documents(p, u) for u, p in pages.items()}
    page_words, on_day = {}, collections.defaultdict(list)
    for s in sites:
        print(f"  {s}: {len(listings[s]):,} hearing pages listed, {sum(1 for u in listings[s] if pages[u]):,} read", flush=True)
        ## what many of a site's pages carry or link is the site's, not a hearing's
        written = {u: lines(pages[u]) for u in listings[s]}
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
        whole = sum(weight(c, w) for w in subject)
        held = sorted((-sum(weight(c, w) for w in subject & page_words[u]) / whole if whole else 0.0, away, -len(found[u]), u) for away, u in its if away <= NEAR)
        held = [h for h in held if -h[0] >= 0.5]
        best = [(u, witnesses(pages[u], u)) for share, away, _, u in held if (share, away) == held[0][:2]]
        if not best or any(sorted(w["name"] for w in people) != sorted(w["name"] for w in best[0][1]) for _, people in best):
            stats["whose pages that day hold under half of the subject"] += bool(its and not best)
            stats["whose pages that day hold as much of the subject as each other"] += bool(best)
            continue
        page, people = best[0]
        stats["with its page"] += 1
        files = found[page]
        title = re.search(r"<meta property=\"og:title\" content=\"([^\"]+)\"|<title>(.*?)</title>", pages[page], re.S)
        found_pages.append({"event_id": e, "page": page, "title": text(title.group(1) or title.group(2)).split(" | ")[0] if title else "", "witnesses": len(people), "documents": len(files)})
        found_witnesses += [{"event_id": e, **w, "page": page} for w in people]
        found_documents += [{"event_id": e, "kind": k, "name": n, "url": f, "page": page} for k, n, f in files]
        stats["with witnesses"] += bool(people)
        stats["with documents"] += bool(files)
        stats["with a transcript"] += any(k == "transcript" for k, _, _ in files)
    for path, rows in ((OUT_PAGES, found_pages), (OUT_WITNESSES, found_witnesses), (OUT_DOCUMENTS, found_documents)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"{len(found_pages):,} pages -> {OUT_PAGES.relative_to(ROOT)}, {len(found_witnesses):,} witnesses -> {OUT_WITNESSES.relative_to(ROOT)}, {len(found_documents):,} documents -> {OUT_DOCUMENTS.relative_to(ROOT)}")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")
    print("  documents by kind: " + ", ".join(f"{k} {v:,}" for k, v in collections.Counter(d["kind"] for d in found_documents).most_common()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--threads", type=int, default=8)
    a = p.parse_args(); main(Path(a.cache).expanduser(), a.threads)
