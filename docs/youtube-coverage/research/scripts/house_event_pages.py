"""
Fill gaps in Congress.gov's House meeting records from docs.house.gov's two XML files.

    .venv/bin/python docs/youtube-coverage/research/scripts/house_event_pages.py [--zyte [--threads 24]] [--no-fetch] [--limit 20] [--cache ~/hearing-text]

Congress.gov's meeting records are built from the House's Committee Repository, but not all of it
arrives: witnesses and documents may be missing, and transcripts posted months later often are.
Read every scheduled House or joint meeting since the 113th Congress whose record has no documents,
no witnesses (for a hearing), or no transcript of its own and no print. Keep that selection independent
of the text source this script supplies. Write what the record lacks to research/data/:

- house_documents_found.csv: event_id, kind, name, url, one row per meeting or witness document the
  record lacks. A document's files are one document in several formats (a bill's PDF and its XML);
  the record has it when it has any of them;
- house_witnesses_found.csv: event_id, name, position, organization, panel, then the name's parts
  (retired is "(Ret.)", which the page adds to the name), location, behalf_of, witness_type,
  testified and bioguide_id, when the record lists no witnesses;
- house_amendments_found.csv: every amendment and vote in the meeting XML read, with its bill,
  number, sponsor, amendment type, enbloc number, description and file URL.

The meeting XML and witness-list XML are beside the documents, named PREFIX-congress-committee-date.xml
and PREFIX-congress-committee-WList-date.xml (PREFIX is HHRG, HMKP or HMTG). See addresses() for where
the address comes from: built from the record's type, committee and date alone, it missed 19 meetings
filed under another committee or day, 166 of the Intelligence and select committees, and 61 witness
lists. A 404 is accepted only after every candidate address has given one.

An audit of 5,594 meetings (house_xml_fields.py --pages) found the same 15,012 witnesses in XML and
pages, every page document in XML, and every page line either an XML value or the stylesheet's words. Of 5,860 cached pages, 283 report
"There was an error retrieving data for this meeting"; XML holds 30 documents and 36 witnesses for
28 House meetings whose page says "No meeting data is available". XML is the source; skip removed
witnesses and documents, as the stylesheet does. Type files by KINDS, then XML type, then description
(SD is generic: many transcripts and witness lists are filed as support documents).

Cache XML under --cache/docs_house_xml/{meeting,wlist}/{eventId}.xml and confirmed 404s as .none;
transient failures stay retryable. Every file is fetched first, then every meeting is read from the
cache. The repository's firewall refuses a client for about 90 seconds after a few hundred requests in
quick succession (389 in 17 seconds; 137 at five a second), so a direct fetch runs one request at a
time, 1.2 seconds apart, and pauses 60 seconds after a 403. With --zyte, requests go through Zyte's API
(zyte.py), which is not refused, in --threads parallel: 24 fetched the 11,000 files in 18 minutes.
Up to three attempts per address. --no-fetch only reads caches. --limit bounds the meetings fetched for.
Fall back to cached --cache/docs_house/{eventId}.html when meeting XML is unavailable, or to its
witness section while a witness list remains unfetched. No HTML is fetched.
"""
import argparse, collections, csv, gzip, html, json, re, sys, threading, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hearing_text_sources import TRANSCRIPT  # noqa: E402
from meeting_completeness import kind  # noqa: E402
from house_xml_fields import parse_xml  # noqa: E402
import zyte  # noqa: E402

MEETINGS = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
INDEX = ROOT / "docs/youtube-coverage/research/data/hearing_text_sources.csv"
OUT_DOCUMENTS = ROOT / "docs/youtube-coverage/research/data/house_documents_found.csv"
OUT_WITNESSES = ROOT / "docs/youtube-coverage/research/data/house_witnesses_found.csv"
OUT_AMENDMENTS = OUT_DOCUMENTS.with_name("house_amendments_found.csv")
## what the repository serves, with a 200, when its page cannot show a meeting
FAILED = "There was an error retrieving data for this meeting"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

## the repository names its files by what they are: HHRG-115-VR09-Wstate-MurphyT-20170214.pdf. A hearing's print is
##  attached under GPO's name for it (CHRG-113hhrg86486.pdf); -RCP is a Rules Committee Print, a bill's text.
KINDS = [("transcript", r"-Transcript-|^CHRG-"), ("witness list", r"-WList-"), ("witness statement", r"-Wstate-"), ("witness biography", r"-Bio-"),
         ("truth in testimony", r"-TTF-"), ("member statement", r"-MState-"), ("questions for the record", r"-QFR"),
         ("recorded vote", r"-Vote\d"), ("report", r"^[CH]RPT-"), ("bill or amendment", r"^BILLS-|^CPRT-|-Amdt-")]
## what the page calls a document, when its file is only numbered (HHRG-113-IF03-20130319-SD007.pdf, "Transcript")
NAMED = [("transcript", r"\btranscript\b"), ("witness list", r"\bwitness list\b"), ("questions for the record", r"\bquestions? for the record\b|\bQFRs?\b")]
## the sections of a page
SECTIONS = {"text of legislation": "bill or amendment", "amendments": "bill or amendment", "votes": "recorded vote", "member statements": "member statement",
            "hearing record": "hearing record", "support documents": "support document"}
## a document's name runs from its own list item: the first on a page would otherwise begin in the menu
DOCUMENT = re.compile(r"<li>((?:(?!<li\b).)*?)\[<a [^>]*href=\"([^\"]+)\"[^>]*>\s*(?:PDF|XML|DOC[X]?|HTML?)\s*</a>\]", re.I | re.S)
WITNESS = re.compile(r"<h3 class=\"witPanelHeader\">(.*?)</h3>|<p><strong>(.*?)</strong>\s*(?:<br\s*/?>)?\s*(?:<small[^>]*>(.*?)</small>)?", re.S)
text = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


## SD says only "support document"; its description supplies the more specific kind when there is one.
XML_KINDS = {"WS": "witness statement", "WT": "truth in testimony", "WB": "witness biography", "WD": "witness support document",
             "HT": "transcript", "HW": "witness list", "HQ": "questions for the record", "MS": "member statement", "CV": "recorded vote",
             "CR": "report", "FR": "report", "BR": "bill or amendment", "CA": "bill or amendment", "HA": "bill or amendment",
             "FA": "bill or amendment", "HM": "hearing record", "HC": "hearing record", "SD": "support document"}
## a meeting file's name: prefix, Congress, committee, then the day, at once or after the document's own name
FILED = re.compile(r"^(H[A-Z]{3})-(\d{3})-([A-Z]{2}\w{2})-(?:[^.]*?-)?(\d{8})(?=[-.])")
WITNESS_FIELDS = "event_id name position organization panel honorific first middle last suffix retired location behalf_of witness_type testified bioguide_id".split()
## the parts of a witness's name, in the order the page writes them: "Colonel Brian Hastings (Ret.)"
NAME = (("honorific", "honorific"), ("first", "firstname"), ("middle", "middlename"), ("last", "lastname"), ("suffix", "suffix"), ("retired", "retired"))
AMENDMENT_FIELDS = "event_id kind bill number sponsor_bioguide amendment_type enbloc description url".split()
value = lambda e, at: re.sub(r"\s+", " ", e.findtext(at) or "").strip()
active = lambda e: not e.get("remove-date", "").strip()
number = lambda s: (0, int(s)) if s.isdigit() else (1, 0)


def addresses(m, root=None, page=""):
    """Where a meeting's XML can be. From the record: the prefix, committee and day its documents' file names carry
    (HHRG-115-AS26-Wstate-ManfraJ-20181114.pdf), on the record or the page, commonest first; then the folder a
    document is in (.../RU/RU00/20150226/103102/CRPT-114-RU00-Vote029-20150226.pdf); then its type, committee
    and date. Where the prefix is not named, all three are tried, the meeting's type's first. A joint hearing is filed under one of its committees and a
    rescheduled one under either day (108754 is Homeland Security's record, filed under Armed Services' AS26), so
    the file names come first. From a cached meeting file: its own prefix, with the directory its documents
    are in, then each committee and subcommittee it names: a meeting of a committee and its subcommittee is filed
    under either (103995 lists AS00 and AS26 and is filed under AS00)."""
    if root is not None:
        prefix, congress = root.get("meeting-type"), root.get("congress-num")
        ## A document's directory preserves the original date even if the meeting was rescheduled.
        directory = re.compile(r"https?://docs\.house\.gov/meetings/([A-Z]{2})/([A-Z]{2}\w{2})/(\d{8})/" + re.escape(m["eventId"]) + "/")
        day = value(root, "meeting-details/meeting-date/calendar-date").replace("-", "")
        places = [(d[2], d[3]) for f in root.iter("file") if (d := directory.search(f.get("doc-url", "")))]
        places += [(c.get("id", ""), day) for c in root.findall("meeting-details/committees/committee-name") + root.findall("meeting-details/subcommittees/committee-name")]
        return list(dict.fromkeys(f"https://docs.house.gov/meetings/{code[:2]}/{code}/{d}/{m['eventId']}/{prefix}-{congress}-{code}-{d}.xml" for code, d in places if code and d))
    links = [d.get("url") or "" for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or [])] + re.findall(r"href=\"([^\"]+)\"", page)
    named = collections.Counter(f.groups() for u in links if (f := FILED.search(u.rsplit("/", 1)[-1])))
    found = [f"https://docs.house.gov/meetings/{code[:2]}/{code}/{day}/{m['eventId']}/{prefix}-{congress}-{code}-{day}.xml" for (prefix, congress, code, day), _ in named.most_common()]
    folders = [f.groups() for u in links if (f := re.search(r"/meetings/[A-Z]{2}/([A-Z]{2}\w{2})/(\d{8})/" + re.escape(m["eventId"]) + "/", u))]
    ## House codes: hs for standing committees, hl for Intelligence and the select committees (hlig00 is IG00)
    code = next((c["systemCode"][2:].upper() for c in m.get("committees", []) if re.match(r"h[sl]", c.get("systemCode", ""))), "")
    places = [p for p, _ in collections.Counter(folders).most_common()] + ([(code, m.get("date", "")[:10].replace("-", ""))] if code else [])
    prefix = {"Hearing": "HHRG", "Markup": "HMKP"}.get(m.get("type"), "HMTG")
    built = [f"https://docs.house.gov/meetings/{c[:2]}/{c}/{day}/{m['eventId']}/{p}-{m.get('congress')}-{c}-{day}.xml"
             for c, day in places if day for p in [prefix] + [p for p in ("HHRG", "HMKP", "HMTG") if p != prefix]]
    return list(dict.fromkeys(found + built))


def cached_xml(path):
    if path.exists() and path.stat().st_size:
        try:
            root = parse_xml(path.read_bytes())
            if root.tag == ("committee-meeting" if path.parent.name == "meeting" else "witness-list"):
                return root
        except ET.ParseError:
            pass
    return None


class Fetcher:
    def __init__(self, through_zyte=False, threads=1):
        self.zyte, self.gap, self.lock, self.next_request, self.totals = through_zyte, 0 if through_zyte else 1.2, threading.Lock(), 0, collections.Counter()
        self.session = requests.Session()
        self.session.headers.update(UA)
        self.session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=max(10, threads)))

    def count(self, key):
        with self.lock:
            self.totals[key] += 1

    def get(self, url):
        """(status, body); status None when the request itself failed."""
        with self.lock:
            at = max(self.next_request, time.monotonic())
            self.next_request = at + self.gap
        time.sleep(max(0, at - time.monotonic()))
        try:
            if self.zyte:
                return zyte.get(url, self.session)
            r = self.session.get(url, timeout=60)
            return r.status_code, r.content
        except requests.RequestException:
            return None, b""

    def fetch(self, path, urls):
        """Keep only valid XML or confirmed absence; a refusal is not an empty meeting."""
        if path.with_suffix(".none").exists() or not urls:
            return None, ""
        for url in urls:
            status = None
            for attempt in range(3):
                status, body = self.get(url)
                self.count(f"HTTP {status}" if status else "request errors")
                if status == 200:
                    try:
                        root = parse_xml(body)
                        if root.tag != ("committee-meeting" if path.parent.name == "meeting" else "witness-list"):
                            raise ET.ParseError("unexpected root")
                    except ET.ParseError:
                        self.count("invalid XML responses")
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                    self.count(f"{path.parent.name} files fetched")
                    return root, url
                if status == 404:
                    break
                ## a direct client that is refused waits out the firewall; Zyte's own 429/503/520 are brief
                with self.lock:
                    self.next_request = max(self.next_request, time.monotonic() + (60 if status == 403 and not self.zyte else 5 * (attempt + 1)))
            if status != 404:
                return None, ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".none").touch()
        self.count(f"{path.parent.name} confirmed absent")
        return None, ""

    def meeting(self, m, cache):
        """Both files of a meeting, whichever the cache lacks: the witness list's address comes from the meeting's."""
        path, wpath = cache / "docs_house_xml/meeting" / f"{m['eventId']}.xml", cache / "docs_house_xml/wlist" / f"{m['eventId']}.xml"
        page = cache / "docs_house" / f"{m['eventId']}.html"
        page = page.read_text(errors="replace") if page.exists() else ""
        root, url = cached_xml(path), ""
        if root is None:
            root, url = self.fetch(path, addresses(m, page=page))
        if root is not None and cached_xml(wpath) is None:
            ## beside the meeting file: where it was found, else wherever the record or the file itself says it may be
            bases = [url] + [a for a in addresses(m, page=page) if f"/{root.get('meeting-type')}-" in a] + addresses(m, root)
            self.fetch(wpath, [re.sub(r"-(\d{8})\.xml$", r"-WList-\1.xml", b) for b in dict.fromkeys(bases) if b])


def witness_rows(root):
    """Page-compatible names, with the XML's separate fields and numeric panel/display ordering."""
    out = []
    for panel in sorted(root.findall("panel"), key=lambda p: number(p.get("sort-order", ""))):
        for w in sorted(panel.findall("witness"), key=lambda w: (number(w.get("display-order", "")), value(w, "lastname"), value(w, "firstname"))):
            if not active(w):
                continue
            parts = {k: value(w, tag) for k, tag in NAME}
            out.append({"name": text(" ".join(parts.values())), "position": value(w, "position"), "organization": value(w, "organization"), "panel": panel.get("sort-order", ""),
                        **parts, "location": value(w, "location"), "behalf_of": value(w, "behalf-of"), "witness_type": value(w, "witness-type") or w.get("witness-type", ""),
                        "testified": value(w, "testified") or w.get("testified", ""), "bioguide_id": value(w, "bioguideID")})
    return out


def xml_documents(root, wlist):
    """Active document elements and the owning witness's name, without flattening their metadata."""
    for d in root.findall("meeting-documents/meeting-document"):
        if active(d):
            yield d, ""
    if wlist is not None:
        for w in wlist.findall("panel/witness"):
            if active(w):
                name = text(" ".join(value(w, tag) for _, tag in NAME))
                for d in w.findall("witness-documents/witness-document"):
                    if active(d):
                        yield d, name


def read_xml(root, wlist):
    """(kind, name, url, every file's name) per document, and the amendments and votes. A document's files are one
    document in several formats (a bill's PDF and its XML); the record has the document when it has any of them."""
    docs, amendments = [], []
    for d, witness in xml_documents(root, wlist):
        code = d.get("type") or value(d, "type") or value(d, "filename-metadata/doc-type") or value(d, "filename-metadata/type")
        description = value(d, "description") or value(d, "filename-metadata/description")
        files = [f.get("doc-url", "").replace("http://", "https://") for f in d.findall("files/file") if active(f) and f.get("doc-url")]
        if files:
            url = next((u for u in files if u.lower().endswith(".pdf")), files[0])
            file = url.rsplit("/", 1)[-1]
            k = (next((k for k, pattern in KINDS if re.search(pattern, file, re.I)), "") or (XML_KINDS.get(code, "") if code != "SD" else "")
                 or next((k for k, pattern in NAMED if re.search(pattern, description, re.I)), "") or "support document")
            name = description or (f"{k}: {witness}" if witness else file)
            docs.append((k, name, url, {u.rsplit("/", 1)[-1] for u in files}))
        if d.tag == "meeting-document" and code in ("CA", "HA", "FA", "CV"):
            for url in files or [""]:
                amendments.append({"kind": "vote" if code == "CV" else "amendment", "bill": value(d, "legis-num") or value(d, "filename-metadata/legis-num"),
                                   "number": value(d, "filename-metadata/" + ("vote-num" if code == "CV" else "amdt-num")),
                                   "sponsor_bioguide": value(d, "filename-metadata/bioguideID"), "amendment_type": value(d, "filename-metadata/amdt-type"),
                                   "enbloc": value(d, "filename-metadata/enbloc-num"), "description": description, "url": url})
    return docs, amendments


def documents(page):
    """(kind, name, url) for each document the page links."""
    out, sections = [], [(h.start(), text(h.group(1)).lower()) for h in re.finditer(r"<h2[^>]*>(.*?)</h2>", page, re.S)]
    for link in DOCUMENT.finditer(page):
        name, url = text(re.sub(r"<strong class=\"newFlags\">.*?</strong>", "", link.group(1), flags=re.S)), link.group(2)
        file, section = url.rsplit("/", 1)[-1], next((s for at, s in reversed(sections) if at < link.start()), "")
        kind = (next((k for k, pattern in KINDS if re.search(pattern, file, re.I)), "") or next((k for k, pattern in NAMED if re.search(pattern, name, re.I)), "")
                or SECTIONS.get(section, "") or ("support document" if re.search(r"-SD\d", file) else "other"))
        out.append((kind, name, url.replace("http://", "https://")))
    return out


def witness_area(page):
    start, end = page.find("<h2>Witnesses"), page.find("<h2>", page.find("<h2>Witnesses") + 1)
    return page[start:end if end > 0 else len(page)] if start >= 0 else ""


def witnesses(page):
    """(name, position, organization, panel) for each witness the page lists."""
    out, panel = [], ""
    for header, name, details in WITNESS.findall(witness_area(page)):
        if header:
            panel = text(header)
        elif text(name):
            ## "(Accompanying Mr. Thomas) Deputy Under Secretary ..., on behalf of U.S. Department of Veterans Affairs"
            position, _, organization = text(details).partition(", on behalf of ")
            out.append((text(name), position, organization, panel))
    return out


def main(cache, no_fetch=False, limit=None, through_zyte=False, threads=1):
    index = {r["event_id"]: r for r in csv.DictReader(open(INDEX))}
    lacking = []
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            r = index.get(m["eventId"])
            ## what the record itself lacks: the index's text source would count the transcripts this script found
            transcript = any(TRANSCRIPT.search(f"{d.get('documentType')} {d.get('name')}") for d in m.get("meetingDocuments") or [] if d.get("url"))
            if r and m.get("chamber") != "Senate" and not r["not_held"] and (
                    not (m.get("meetingDocuments") or m.get("witnessDocuments"))
                    or (kind(m) == "hearing" and not m.get("witnesses"))
                    or not (r["gpo_packages"] or transcript)):
                lacking.append(m)
    fetcher = Fetcher(through_zyte, threads)
    missing = lambda p: cached_xml(p) is None and not p.with_suffix(".none").exists()
    todo = [] if no_fetch else [m for m in lacking if missing(cache / "docs_house_xml/meeting" / f"{m['eventId']}.xml")
                                or missing(cache / "docs_house_xml/wlist" / f"{m['eventId']}.xml")][:limit]
    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(lambda m: fetcher.meeting(m, cache), todo))
    found_documents, found_witnesses, found_amendments = [], [], []
    totals = collections.Counter(dict.fromkeys(("meetings read from XML", "meetings read from the page", "meetings read from neither", "witness lists found",
                                              "XML meetings using the page's witness section", "pages read", "pages that failed to load", "pages that cannot show the meeting"), 0))
    for m in lacking:
        e = m["eventId"]
        path, wpath = cache / "docs_house_xml/meeting" / f"{e}.xml", cache / "docs_house_xml/wlist" / f"{e}.xml"
        root = cached_xml(path)
        page_path = cache / "docs_house" / f"{e}.html"
        page = page_path.read_text() if page_path.exists() else ""
        if root is not None:
            totals["meetings read from XML"] += 1
            wlist = cached_xml(wpath)
            totals["witness lists found"] += wlist is not None
            listed = witness_rows(wlist) if wlist is not None else []
            docs, amendments = read_xml(root, wlist)
            found_amendments += [{"event_id": e, **a} for a in amendments]
            ## A partial cache is not evidence of an empty witness list; retain its page until XML settles it.
            if wlist is None and not wpath.with_suffix(".none").exists() and witness_area(page):
                totals["XML meetings using the page's witness section"] += 1
                docs += [(k, n, u, {u.rsplit("/", 1)[-1]}) for k, n, u in documents(witness_area(page))]
                listed = [dict(zip(WITNESS_FIELDS[1:5], w)) for w in witnesses(page)]
        else:
            totals["meetings read from the page" if page else "meetings read from neither"] += 1
            totals["pages read"] += bool(page)
            totals["pages that failed to load"] += not page
            totals["pages that cannot show the meeting"] += FAILED in page
            docs, listed = [(k, n, u, {u.rsplit("/", 1)[-1]}) for k, n, u in documents(page)], [dict(zip(WITNESS_FIELDS[1:5], w)) for w in witnesses(page)]
        have = {d["url"].rsplit("/", 1)[-1] for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or []) if d.get("url")}
        new = [d[:3] for d in docs if not d[3] & have]
        found_documents += [{"event_id": m["eventId"], "kind": k, "name": n, "url": u} for k, n, u in new]
        totals["meetings with documents the record lacks"] += bool(new)
        totals["meetings with a transcript the record lacks"] += any(k == "transcript" for k, _, _ in new)
        if not m.get("witnesses"):
            found_witnesses += [{"event_id": e, **w} for w in listed]
            totals["meetings with witnesses the record lacks"] += bool(listed)
    for path, rows, columns in ((OUT_DOCUMENTS, found_documents, ["event_id", "kind", "name", "url"]), (OUT_WITNESSES, found_witnesses, WITNESS_FIELDS),
                                (OUT_AMENDMENTS, found_amendments, AMENDMENT_FIELDS)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns); w.writeheader(); w.writerows(rows)
    print(f"{len(found_documents):,} documents -> {OUT_DOCUMENTS.relative_to(ROOT)}, {len(found_witnesses):,} witnesses -> {OUT_WITNESSES.relative_to(ROOT)}")
    totals["meetings fetched for"] = len(todo)
    totals.update(fetcher.totals)
    totals["amendments written"] = sum(a["kind"] == "amendment" for a in found_amendments)
    totals["votes written"] = sum(a["kind"] == "vote" for a in found_amendments)
    for k, v in totals.items():
        print(f"  {k}: {v:,}")
    print("  documents by kind: " + ", ".join(f"{k} {v:,}" for k, v in collections.Counter(d["kind"] for d in found_documents).most_common()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--limit", type=int, help="fetch for at most N meetings")
    p.add_argument("--zyte", action="store_true", help="fetch through Zyte's API, which the repository's firewall does not refuse (metered)")
    p.add_argument("--threads", type=int, help="parallel requests (default 1, or 16 with --zyte)")
    a = p.parse_args()
    if a.limit is not None and a.limit < 0:
        p.error("--limit must be nonnegative")
    if a.threads and a.threads > 1 and not a.zyte:
        p.error("a direct fetch runs one request at a time: the repository refuses a faster client")
    main(Path(a.cache).expanduser(), a.no_fetch, a.limit, a.zyte, a.threads or (16 if a.zyte else 1))
