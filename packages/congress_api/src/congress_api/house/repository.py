"""House repository XML and page parsing. See `house-meeting-records` for fetching.

Addresses come from document filenames and folders before committee/date guesses:
otherwise 19 meetings, 166 select-committee records and 61 witness lists were missed.
An audit of 5,594 pages found every page document and the same 15,012 witnesses
in XML. Removed elements stay out; multiple file formats count as one document.
"""
import collections, html, re
import xml.etree.ElementTree as ET

from congress_api.xml import parse_xml
from congress_api.inventory.common import text

FAILED = "There was an error retrieving data for this meeting"
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


def witness_rows(root):
    """Page-compatible names, with the XML's separate fields and numeric panel/display ordering."""
    out = []
    for panel in sorted(root.findall("panel"), key=lambda p: number(p.get("sort-order", ""))):
        if not active(panel):
            continue
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
        for w in (w for panel in wlist.findall("panel") if active(panel) for w in panel.findall("witness")):
            if active(w):
                name = text(" ".join(value(w, tag) for _, tag in NAME))
                for d in w.findall("witness-documents/witness-document"):
                    if active(d):
                        yield d, name


def document_kind(code, description, url):
    file = url.rsplit("/", 1)[-1]
    return (next((k for k, pattern in KINDS if re.search(pattern, file, re.I)), "")
            or (XML_KINDS.get(code, "") if code != "SD" else "")
            or next((k for k, pattern in NAMED if re.search(pattern, description, re.I)), "") or "support document")


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
            k = document_kind(code, description, url)
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
