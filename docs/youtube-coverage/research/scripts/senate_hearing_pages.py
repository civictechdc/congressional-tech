"""
Read Senate committees' own hearing pages for the witness lists Congress.gov doesn't have.

    python docs/youtube-coverage/research/scripts/senate_hearing_pages.py [--cache ~/hearing-text] [--threads 8]

Congress.gov lists no witnesses for Senate meetings. `meeting_completeness.py` fills what it can from
GPO's records and from nomination hearings' titles; this reads the rest from the committees' sites.

Finding the page. Senate committee sites list their hearings, twenty to a page, at
/hearings?PageNum_rs=N or /hearings/?mt_page=N. The listings are read back to the first Senate meeting
record (June 2019), which gives every hearing page and roughly when it was held. A search engine was tried
first and found the page for one hearing in five: Congress.gov's titles paraphrase the committees'
("Hearings to examine the state of patent eligibility in America"), and searches return testimony
files ahead of the page they belong to.

Reading the page. For each open Senate or joint hearing still without a witness list
(`meeting_completeness.csv`), the pages listed within a week of it are fetched. A page is the hearing's
when it names the hearing's date, or names no date and was listed on that day; when the committee held
several hearings that day, the page that holds most of the words of the meeting's subject. Its
witnesses are then read.
The sites come in four layouts:

- a list of `vcard`s with `fn`, `title` and `org` (Finance, Appropriations, Budget, Armed Services ...);
- a name over `witness-content` details, in a list item (Judiciary, HELP, Aging, Foreign Relations ...);
- `capigacr-widget-card`s in a "Testimony" panel (Commerce, Energy ...);
- a `jet-listing-grid` under a "Witnesses" heading, first and last name in separate headings (HSGAC).

Writes docs/youtube-coverage/research/data/senate_witnesses_found.csv (event_id, name, position,
organization, page). Listings and pages are cached under `--cache`/senate_pages.
"""
import argparse, collections, csv, datetime as dt, html, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
from congress_api.gpo.match import words  # noqa: E402
from congress_api.transcribe.metadata import is_name, witness  # noqa: E402

COMPLETENESS = ROOT / "docs/youtube-coverage/research/data/meeting_completeness.csv"
OUT = ROOT / "docs/youtube-coverage/research/data/senate_witnesses_found.csv"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
## where each committee keeps its hearing pages
SITE = {"ssaf00": "agriculture.senate.gov", "ssap00": "appropriations.senate.gov", "ssas00": "armed-services.senate.gov", "ssbk00": "banking.senate.gov",
        "ssbu00": "budget.senate.gov", "sscm00": "commerce.senate.gov", "sseg00": "energy.senate.gov", "ssev00": "epw.senate.gov", "ssfi00": "finance.senate.gov",
        "ssfr00": "foreign.senate.gov", "ssga00": "hsgac.senate.gov", "sshr00": "help.senate.gov", "ssju00": "judiciary.senate.gov", "ssra00": "rules.senate.gov",
        "sssb00": "sbc.senate.gov", "ssva00": "veterans.senate.gov", "slia00": "indian.senate.gov", "spag00": "aging.senate.gov", "slin00": "intelligence.senate.gov",
        "jsec00": "jec.senate.gov"}
## the forms a listing's address takes; the first that lists anything on its first page is the site's
LISTINGS = ["/hearings?PageNum_rs={}", "/committee-activity/hearings?PageNum_rs={}", "/hearings/?mt_page={}", "/committee-activity/hearings/?mt_page={}",
            "/public/index.cfm/hearings?PageNum_rs={}", "/hearings-and-markups?PageNum_rs={}"]
HEARING_LINK = re.compile(r"<a[^>]+href=\"((?:https?://[\w.\-]+)?/(?:[\w\-/.]*/)?(?:(?:hearings?|meetings|hearings-and-markups)/[^\"#?]+|hearings\?ID=[\w\-]+))\"[^>]*>(.*?)</a>", re.S)
FIRST_RECORD = dt.date(2019, 6, 1)  # Congress.gov's Senate meeting records begin in June 2019
MONTHS = "January February March April May June July August September October November December".split()
## "6/12/2019", "06.12.19", "June 12, 2019", "2019-06-12"
DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b|\b(" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
text = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def person(name, details, page):
    """One witness row from a name as the page writes it ("The Honorable Jay Bhattacharya, M.D., Ph.D.") and the lines under it."""
    details = [d for d in (text(d) for d in details) if d and not re.match(r"(download|view|watch) ", d, re.I)]
    return {"name": witness(text(name)).name, "position": details[0] if details else "", "organization": ", ".join(details[1:3]), "page": page}


def witnesses(page_html, url):
    """The witnesses a hearing page lists, by whichever of the four layouts it uses."""
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
        ## the page's sections open with a heading; "Member Statements" are the senators', laid out like witnesses
        sections = [s for s in re.split(r"(?=<h2\b)", page_html) if not re.search(r"statement", text(s.split("</h2>")[0]) if s.startswith("<h2") else "", re.I)]
        for item in ("<li" + i for s in sections for i in re.split(r"<li\b", s)[1:]):
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
            name = re.search(r"class=\"fn\">(.*?)</span>", card, re.S)
            if name:
                prefix = re.search(r"class=\"honorific-prefix\">(.*?)</span>", card, re.S)
                out.append(person(f"{text(prefix.group(1)) if prefix else ''} {text(name.group(1))}", re.findall(r"class=\"(?:title|org)\">(.*?)</div>", card, re.S), url))
    else:
        start = re.search(r">\s*Witnesses\s*</h\d>", page_html)
        for item in re.split(r"jet-listing-grid__item ", page_html[start.start():] if start else "")[1:]:
            names = re.findall(r"<h3 class=\"jet-listing-dynamic-field__content\">(.*?)</h3>", item, re.S)
            if names:
                out.append(person(" ".join(names), re.findall(r"<div class=\"jet-listing-dynamic-field__content\">(.*?)</div>", item, re.S), url))
    seen = set()
    return [w for w in out if is_name(w["name"]) and not (w["name"] in seen or seen.add(w["name"]))]


def written_day(match):
    try:
        if match.group(1):
            year = int(match.group(3))
            return dt.date(year if year > 99 else 2000 + year, int(match.group(1)), int(match.group(2)))
        if match.group(4):
            return dt.date(int(match.group(6)), MONTHS.index(match.group(4)) + 1, int(match.group(5)))
        return dt.date(int(match.group(7)), int(match.group(8)), int(match.group(9)))
    except ValueError:
        return None


def names_the_date(page_html, day):
    return dt.date.fromisoformat(day) in {written_day(m) for m in DATE.finditer(text(page_html))} or day in page_html


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
    """(day, url, title) for the hearing pages one page of a listing shows."""
    page, rows = fetch(f"https://www.{site}{form.format(n)}", cache), []
    for link in HEARING_LINK.finditer(page):
        before = min(900, link.start())
        around = page[link.start() - before:link.end() + 900]
        near = sorted((abs(m.start() - before), written_day(m)) for m in DATE.finditer(around) if written_day(m))
        if near and text(link.group(2)):
            rows.append((near[0][1], link.group(1) if link.group(1).startswith("http") else f"https://www.{site}{link.group(1)}", text(link.group(2))))
    return rows


def listed(site, cache):
    """(day, url, title) for the hearing pages a site's listing shows, back to the first Senate meeting record. The
    day is the date written nearest the link, which can be a neighbouring row's: it says roughly when, and the
    page itself says exactly."""
    form = next((f for f in LISTINGS if listing_page(site, f, 1, cache)), None)
    out = []
    for n in range(1, 200) if form else ():
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
    rows = [r for r in csv.DictReader(open(COMPLETENESS)) if r["chamber"] != "House" and r["kind"] == "hearing" and not r["closed"]
            and r["witness_source"] in ("", "senate committee page") and not r["rescheduled_to"] and not r["not_held"] and SITE.get(r["committees"].split(";")[0])]
    site = lambda r: SITE[r["committees"].split(";")[0]]
    with ThreadPoolExecutor(threads) as pool:
        sites = sorted({site(r) for r in rows})
        listings = dict(zip(sites, pool.map(lambda s: listed(s, cache), sites)))
        for s in sites:
            print(f"  {s}: {len(listings[s]):,} hearing pages listed" + (f", back to {min(d for d, _, _ in listings[s])}" if listings[s] else ""), flush=True)
        candidates = {r["event_id"]: [(d, u) for d, u, _ in listings[site(r)] if abs((d - dt.date.fromisoformat(r["date"])).days) <= 7] for r in rows}
        urls = sorted({u for us in candidates.values() for _, u in us})
        pages = dict(zip(urls, pool.map(lambda u: fetch(u, cache), urls)))
    page_words = {u: set(words(text(p))) for u, p in pages.items()}
    dateless = {u for u, p in pages.items() if not any(written_day(m) for m in DATE.finditer(text(p)))}

    found, stats = [], collections.Counter(hearings=len(rows))
    for r in rows:
        day = dt.date.fromisoformat(r["date"])
        its = [u for d, u in candidates[r["event_id"]] if names_the_date(pages[u], r["date"]) or (u in dateless and d == day)]
        stats["with a listed page within a week"] += bool(candidates[r["event_id"]])
        stats["with a page for that day"] += bool(its)
        ## several of the committee's hearings that day: the page holding most of the words of the meeting's subject
        subject = set(words(topic(r["title"])))
        held = sorted(((len(subject & page_words[u]) / max(1, len(subject)), u) for u in its), reverse=True)
        if len(held) > 1 and (held[0][0] < 0.5 or held[0][0] == held[1][0]):
            stats["several pages that day, none clearly this hearing's"] += 1
            continue
        people = witnesses(pages[held[0][1]], held[0][1]) if held else []
        if people:
            found += [{"event_id": r["event_id"], **w} for w in people]
            stats["with witnesses"] += 1
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "name", "position", "organization", "page"]); w.writeheader(); w.writerows(found)
    print(f"{len(found):,} witnesses -> {OUT.relative_to(ROOT)}")
    for k, v in stats.items():
        print(f"  {k}: {v:,}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--threads", type=int, default=8)
    a = p.parse_args(); main(Path(a.cache).expanduser(), a.threads)
