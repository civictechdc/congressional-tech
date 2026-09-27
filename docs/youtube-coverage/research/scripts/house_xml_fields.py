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
"""
import argparse, collections, csv, re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "docs/youtube-coverage/research/data/house_xml_fields.csv"
## names in the stylesheet's expressions that are XSLT's or the stylesheet's own, not the XML's
NOT_FIELDS = set("""and or not position last count string-length substring concat normalize-space translate contains text node current true false div mod name
    local-name starts-with format-number number string boolean sum floor ceiling round docType docTypeName fullDocTypeName fullWitnessPosition timeStringFormat
    dateStringFormat timeFrame meetingSTime meetingETime meetingDate pubDate addDate types doctypes key file-type at m d e lt""".split())


def fields(path):
    """(path, attribute or "", value) for every element and attribute of a file; "" as the value of an element with no text of its own."""
    root = ET.fromstring(path.read_bytes().lstrip(b"\xef\xbb\xbf"))
    walk = [(root.tag, root)]
    while walk:
        at, element = walk.pop()
        yield at, "", (element.text or "").strip()
        for name, value in element.attrib.items():
            yield at, name, value.strip()
        walk += [(f"{at}/{child.tag}", child) for child in element]


def main(cache, stylesheet):
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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--stylesheet")
    a = p.parse_args(); main(Path(a.cache).expanduser(), a.stylesheet)
