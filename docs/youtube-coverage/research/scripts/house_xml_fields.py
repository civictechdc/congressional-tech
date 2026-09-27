"""
Every field in docs.house.gov's meeting XML, counted over the files in hand.

    python docs/youtube-coverage/research/scripts/house_xml_fields.py [--cache ~/hearing-text] [--stylesheet cr-public.xslt]

The House's Committee Repository publishes two XML files for a meeting, beside its documents:

    https://docs.house.gov/meetings/{C}/{Cnn}/{YYYYMMDD}/{eventId}/{PREFIX}-{congress}-{Cnn}-{YYYYMMDD}.xml
    https://docs.house.gov/meetings/{C}/{Cnn}/{YYYYMMDD}/{eventId}/{PREFIX}-{congress}-{Cnn}-WList-{YYYYMMDD}.xml

The first is the meeting: its date, place, committees and documents, among them a markup's amendments
and votes. The second is the witness list: panels, and each witness's name in parts, position,
organization, kind and documents. `{PREFIX}` is HHRG for a hearing, HMKP for a markup, HMTG for any
other meeting. A meeting with no witnesses has no second file.

This reads every file under `--cache`/docs_house_xml/meeting and /wlist with an XML parser and counts,
for each element and attribute by its path from the root: the files that have it, how often it
occurs, how many different values it takes, and the commonest of them. With `--stylesheet`, the
repository's own stylesheet (docs.house.gov/xslt/cr-public.xslt), it also lists the names the
stylesheet reads that no file in hand shows: fields that exist and were not met.

Writes docs/youtube-coverage/research/data/house_xml_fields.csv (file, path, attribute, files,
occurrences, values, commonest) and prints it.

With `--pages`, it also sets each meeting's XML against its page on docs.house.gov (cached under
`--cache`/docs_house by house_event_pages.py), for the meetings whose witness list has been fetched or
found absent: the documents and witnesses each gives, every line of the page's meeting area that no
XML value accounts for, and for each XML field the share of its values the page shows.
"""
import argparse, collections, csv, datetime as dt, html, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "docs/youtube-coverage/research/data/house_xml_fields.csv"
## names in the stylesheet's expressions that are XSLT's or the stylesheet's own, not the XML's
NOT_FIELDS = set("""and or not position last count string-length substring concat normalize-space translate contains text node current true false div mod name
    local-name starts-with format-number number string boolean sum floor ceiling round docType docTypeName fullDocTypeName fullWitnessPosition timeStringFormat
    dateStringFormat timeFrame meetingSTime meetingETime meetingDate pubDate addDate types doctypes key file-type at m d e lt""".split())


def parse_xml(data):
    """The repository serves UTF-8 XML, sometimes with a BOM before its stylesheet instruction."""
    return ET.fromstring(data.removeprefix(b"\xef\xbb\xbf"))


def fields(path):
    """(path, attribute or "", value) for every element and attribute of a file; "" as the value of an element with no text of its own."""
    root = parse_xml(path.read_bytes())
    walk = [(root.tag, root)]
    while walk:
        at, element = walk.pop()
        yield at, "", (element.text or "").strip()
        for name, value in element.attrib.items():
            yield at, name, value.strip()
        walk += [(f"{at}/{child.tag}", child) for child in element]


def plain(s):
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(s).lower().replace("\u2019", "'")).strip()


def written(value):
    """The ways the repository's stylesheet writes a timestamp or a time: "06/22/2023 at 02:00 PM", "March 4, 2025"."""
    out = set()
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)(?:T(\d\d):(\d\d))?", value)
    if m:
        d = dt.datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0))
        out |= {d.strftime("%m/%d/%Y"), d.strftime("%B %-d, %Y"), d.strftime("%A, %B %-d, %Y")}
        if m[4]:
            out |= {d.strftime("%m/%d/%Y at %I:%M %p"), d.strftime("%B %-d, %Y at %I:%M %p"), d.strftime("%I:%M %p")}
    m = re.match(r"^(\d\d):(\d\d):\d\d$", value)
    if m:
        out |= {dt.time(int(m[1]), int(m[2])).strftime("%I:%M %p"), dt.time(int(m[1]), int(m[2])).strftime("%-I:%M %p")}
    return {plain(o) for o in out}


def against_pages(cache):
    """The XML and the page, each checked for what the other lacks."""
    from house_event_pages import FAILED, documents, witnesses

    xml_dir, page_dir = cache / "docs_house_xml", cache / "docs_house"
    file = lambda u: html.unescape(u).rsplit("/", 1)[-1].lower()
    totals, lines_left, shown, held, example = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), {}
    for path in sorted((xml_dir / "meeting").glob("*.xml")):
        e, page = path.stem, page_dir / f"{path.stem}.html"
        wlist = xml_dir / "wlist" / f"{e}.xml"
        if not (page.exists() and page.stat().st_size) or not (wlist.exists() or (xml_dir / "wlist" / f"{e}.none").exists()):
            continue
        t = page.read_text(errors="replace")
        values = list(fields(path)) + (list(fields(wlist)) if wlist.exists() else [])
        in_xml = {file(v) for _, name, v in values if name == "doc-url"}
        on_page = {file(u) for _, _, u in documents(t)}
        state = "page says no meeting data" if "No meeting data is available" in t else "page shows the meeting"
        totals[state, "meetings"] += 1
        totals[state, "documents in the XML"] += len(in_xml); totals[state, "documents on the page"] += len(on_page)
        totals[state, "XML documents not on the page"] += len(in_xml - on_page); totals[state, "page documents not in the XML"] += len(on_page - in_xml)
        totals[state, "witnesses in the XML"] += sum(1 for at, name, _ in values if at.endswith("/witness") and name == "")
        totals[state, "witnesses on the page"] += len(witnesses(t))
        if state != "page shows the meeting":
            continue
        area = re.sub(r"<(script|style)\b.*?</\1>", " ", t[t.find('<div id="DivMeetingContent">'):t.find('<div class="button-row">')], flags=re.S)
        lines = [re.sub(r"\s+", " ", html.unescape(l)).strip() for l in re.split(r"<[^>]+>", area)]
        xml_text, forms = " | ".join(plain(v) for _, _, v in values), set().union(*(written(v) for _, _, v in values))
        for line in lines:
            n = plain(line)
            if n and n not in ("pdf", "xml", "doc", "docx") and n not in xml_text and not any(n in f or f in n for f in forms if len(f) > 6):
                key = re.sub(r"\d+", "N", line)[:60]
                lines_left[key] += 1; example.setdefault(key, e)
        page_text = plain(" ".join(lines))
        for at, name, v in values:
            if not v or name == "doc-url":
                continue  # an element that only holds others; a file's address, checked above as a document
            key = at.split("/", 1)[-1] + (f" @{name}" if name else "")
            held[key] += 1
            shown[key] += bool(plain(v)) and (plain(v) in page_text or any(f in page_text for f in written(v)))
    print("\nXML against page:")
    for (state, what), n in sorted(totals.items()):
        print(f"  {state}: {what} {n:,}")
    print("  lines of the page's meeting area that no XML value accounts for (the stylesheet's own words):")
    for key, n in lines_left.most_common(25):
        print(f"    {n:5,} {key!r} (event {example[key]})")
    print("  XML fields, share of values the page shows:")
    for key in sorted(held, key=lambda k: (shown[k] / held[k], k)):
        print(f"    {shown[key]:6,}/{held[key]:<6,} {key}")
    failed = [p for p in page_dir.glob("*.html") if FAILED in p.read_text(errors="replace")]
    print(f"  cached pages that report \"{FAILED}\": {len(failed):,}, of which say no meeting data: "
          f"{sum(1 for p in failed if 'No meeting data is available' in p.read_text(errors='replace')):,}")


def main(cache, stylesheet, pages):
    rows, seen, totals = [], set(), {}
    for kind in ("meeting", "wlist"):
        files = sorted((cache / "docs_house_xml" / kind).glob("*.xml"))
        in_files, occurrences, values = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
        roots = collections.Counter()
        for path in files:
            try:
                found = list(fields(path))
            except ET.ParseError:
                roots["(not XML)"] += 1
                continue
            roots[found[0][0]] += 1
            for key in {(at, name) for at, name, _ in found}:
                in_files[key] += 1
            for at, name, value in found:
                occurrences[at, name] += 1
                values[at, name][value] += 1
                seen |= {at.rsplit("/", 1)[-1], name}
        totals[kind] = (len(files), dict(roots))
        for (at, name), n in sorted(in_files.items()):
            given = {v: c for v, c in values[at, name].items() if v}
            rows.append({"file": kind, "path": at, "attribute": name, "files": n, "occurrences": occurrences[at, name], "with_a_value": sum(given.values()), "values": len(given),
                         "commonest": "; ".join(f"{v[:60]} ({c})" for v, c in sorted(given.items(), key=lambda x: -x[1])[:8])})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    for kind, (n, roots) in totals.items():
        print(f"{kind}: {n:,} files, roots {roots}")
        for r in rows:
            if r["file"] == kind:
                print(f"  {r['files']:5,} {r['occurrences']:6,} {r['values']:6,}  {r['path']}{' @' + r['attribute'] if r['attribute'] else ''}  |  {r['commonest'][:150]}")
    print(f"{len(rows)} fields -> {OUT.relative_to(ROOT)}")
    if stylesheet:
        sheet = Path(stylesheet).expanduser().read_text()
        named = {n.lstrip("@") for e in re.findall(r"(?:select|match|test)=\"([^\"]*)\"", sheet) for n in re.findall(r"@?[a-zA-Z][\w\-]*", re.sub(r"'[^']*'|\$[\w\-]+", " ", e))} - NOT_FIELDS
        print("names the stylesheet reads that no file in hand shows:", ", ".join(sorted(named - seen)) or "none")
        print("names in the files that the stylesheet does not read:", ", ".join(sorted(seen - named - {""})) or "none")
    if pages:
        against_pages(cache)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--stylesheet")
    p.add_argument("--pages", action="store_true", help="set each meeting's XML against its cached docs.house.gov page")
    a = p.parse_args(); main(Path(a.cache).expanduser(), a.stylesheet, a.pages)
