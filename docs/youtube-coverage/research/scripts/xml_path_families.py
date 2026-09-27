"""Inventory document URL families and test at most three cases in each.

    python docs/youtube-coverage/research/scripts/xml_path_families.py
    python docs/youtube-coverage/research/scripts/xml_path_families.py --run

The default writes an inventory, family table, and bounded request plan only.
--run executes the saved plan, reusing this experiment's completed requests.
The earlier full PDF sweep remains stopped. See ../xml_path_families.md.
"""
import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from lxml import etree, html as html_parser

from pdf_xml_probe import Pace, probe

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "docs/youtube-coverage/research/data"
OUT = DATA / "xml_path_families.csv"


def name_family(path):
    name = unquote(path.rsplit("/", 1)[-1]).upper()
    rules = [
        (r"-WSTATE-.*-SD\d", "witness attachment"), (r"-WSTATE-", "witness testimony"),
        (r"-WLIST-", "witness list"), (r"-TTF-", "disclosure"), (r"-BIO-", "biography"),
        (r"-MSTATE-", "member statement"), (r"-QFR", "questions for record"),
        (r"-TRANSCRIPT-|^CHRG-", "hearing transcript"), (r"-VOTE\d", "vote"),
        (r"-AMDT-|^.*HAMDT", "amendment"), (r"-MBRROSTER", "member roster"),
        (r"RCP\d|^CPRT-.*HPRT-RU", "Rules Committee Print"), (r"^BILLS", "bill or resolution"),
        (r"^[CH]RPT-", "committee report"), (r"^CPRT-", "committee print"),
        (r"-SD\d", "meeting support document"), (r"^(HHRG|HMKP|HMTG)-", "meeting notice or other"),
    ]
    return next((label for pattern, label in rules if re.search(pattern, name)), "other filename")


def family(url, form):
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or ":" in p.netloc:
        return ("invalid URL", "unusable address", "unknown", form)
    host, path = p.netloc.lower(), p.path
    lower = path.lower()
    kind = name_family(path)
    if re.match(r"/meetings/[^/]+/[^/]+/\d{8}/\d+/", path):
        route = "/meetings/{committee}/{code}/{date}/{event}/{file}"
    elif "/billsthisweek/" in lower:
        route = "/billsthisweek/{date}/{file}"
    elif re.match(r"/\d+/meeting/[^/]+/\d+/(documents|witnesses)/", path):
        route = "/{congress}/meeting/{chamber}/{event}/" + path.split("/")[5] + "/{file}"
    elif re.match(r"/\d+/(bills|crpt)/", path):
        route = "/{congress}/" + path.split("/")[2] + "/{measure}/{file}"
    elif re.search(r"/(?:content|fdsys)/pkg/", path):
        match = re.search(r"/(content|fdsys)/pkg/([^/]+)/([^/]+)/", path)
        collection = match[2].split("-")[0] if match else "unknown"
        route = f"/{match[1]}/pkg/{collection}-{{package}}/{match[3]}/{{file}}" if match else "/package/{file}"
    elif lower.endswith("/byevent.aspx"):
        route, kind = "/Committee/Calendar/ByEvent.aspx?EventID={event}", "meeting page"
    elif "files.serve" in p.query.lower():
        route, kind = path + "?a=Files.Serve&File_id={id}", "download handler"
    elif "/download/" in lower:
        route, kind = "/download/{document}", "download handler"
    elif "/wp-content/uploads/meetings/" in lower:
        route, kind = "/wp-content/uploads/meetings/{id}/{file}", "uploaded document"
    elif "/wp-content/uploads/" in lower:
        route, kind = "/wp-content/uploads/{path}/{file}", "uploaded document"
    elif "/sites/" in lower and "/files/" in lower:
        route = re.sub(r"/files/.*", "/files/{path}/{file}", path)
        if kind == "other filename":
            kind = "uploaded document"
    elif "/_cache/files/" in lower:
        route, kind = path.split("/_cache/files/")[0] + "/_cache/files/{id}/{file}", "uploaded document"
    elif form == "html page":
        route, kind = "/{hearing-page}", "hearing page"
    else:
        parts = [part for part in path.split("/") if part]
        route = "/" + "/".join(parts[:1] + ["{path}/{file}"]) if len(parts) > 1 else "/{file}"
    return host, route, kind, form


def collect(cache):
    items, sources = {}, []

    def add(raw, source, form_hint="", event=""):
        if not raw:
            return
        url = html.unescape(raw.strip())
        p = urlsplit(url)
        extension = Path(p.path).suffix.lower()
        if extension == ".pdf":
            form = "pdf"
        elif extension in {".htm", ".html"}:
            form = extension[1:]
        elif form_hint == "html page":
            form = form_hint
        elif form_hint == "document" and (not extension or extension in {".cfm", ".aspx"}):
            form = "download (format unknown)"
        else:
            return
        url = urlunsplit(p._replace(fragment=""))
        row = items.setdefault(url, {"url": url, "family": family(url, form), "sources": set(), "events": set()})
        row["sources"].add(source)
        if event:
            row["events"].add(str(event))

    def source(path):
        sources.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    meetings = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
    source(meetings)
    with gzip.open(meetings, "rt") as stream:
        for line in stream:
            meeting = json.loads(line)
            for field in ("meetingDocuments", "witnessDocuments"):
                for doc in meeting.get(field) or []:
                    add(doc.get("url", ""), "Congress.gov meeting export", "document", meeting["eventId"])
    for filename in ("house_documents_found.csv", "senate_documents_found.csv", "senate_hearing_pages_found.csv"):
        path = DATA / filename
        source(path)
        with path.open() as stream:
            for row in csv.DictReader(stream):
                add(row.get("url", ""), filename, "document", row["event_id"])
                add(row.get("page", ""), filename, "html page", row["event_id"])
    path = ROOT / "apps/committee_youtube/data/gpo_hearings.csv"
    source(path)
    with path.open() as stream:
        for row in csv.DictReader(stream):
            for field in ("pdf_url", "html_url"):
                add(row.get(field, ""), "GPO hearing catalogue", event=row["event_id"])
    cache_files = []
    for path in sorted((cache / "docs_house").glob("*.html")):
        content = path.read_bytes()
        cache_files.append((str(path), hashlib.sha256(content).hexdigest()))
        page = "https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + path.stem
        add(page, "cached House page", "html page", path.stem)
        try:
            tree = html_parser.fromstring(content)
        except (etree.ParserError, ValueError):
            continue
        for link in tree.xpath("//a[@href]/@href"):
            add(urljoin(page, link), "cached House page document", event=path.stem)
    for folder in ("meeting", "wlist"):
        for path in sorted((cache / "docs_house_xml" / folder).glob("*.xml")):
            content = path.read_bytes()
            cache_files.append((str(path), hashlib.sha256(content).hexdigest()))
            try:
                tree = etree.fromstring(content, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
            except etree.XMLSyntaxError:
                continue
            for url in tree.xpath("//@doc-url"):
                add(url, "cached House XML", event=path.stem)
    sources.append({"cache_files": len(cache_files), "manifest_sha256": hashlib.sha256(json.dumps(cache_files).encode()).hexdigest()})
    return items, sources, cache_files


def candidates(item, all_items):
    url = item["url"]
    host, route, kind, form = item["family"]
    if host == "invalid URL":
        return []
    p = urlsplit(url)
    if kind == "meeting page":
        event = parse_qs(p.query).get("EventID", [""])[0]
        # Derive from a document actually observed for this event, not its scheduled date.
        docs = all_items.get("house_event_stems", {}).get(event, [])
        if not docs:
            return []
        stem = sorted(docs)[0]
        return [("meeting XML", stem + ".xml", {}), ("witness-list XML", re.sub(r"-(\d{8})$", r"-WList-\1", stem) + ".xml", {})]
    if form == "download (format unknown)":
        return [("XML Accept header", url, {"Accept": "application/xml, text/xml;q=0.9"})]
    newpath = re.sub(r"\.(pdf|html?)$", ".xml", p.path, flags=re.I)
    if newpath == p.path:
        newpath = p.path.rstrip("/") + ".xml"
    out = [("extension replacement", urlunsplit(p._replace(path=newpath)), {})]
    if re.search(r"/(content|fdsys)/pkg/[^/]+/(pdf|html)/", p.path):
        out.append(("format directory + extension", urlunsplit(p._replace(path=re.sub(r"/(pdf|html)/", "/xml/", newpath))), {}))
    return out


def choose(rows, count):
    ordered = sorted(rows, key=lambda row: hashlib.sha256(row["url"].encode()).digest())
    chosen, seen = [], set()
    for row in ordered:
        url = row["url"]
        match = re.search(r"/(20\d{2})\d{4}/|(?:HHRG|HMKP|HMTG|BILLS|CHRG|CRPT)-(\d{3})|congress.gov/(\d{3})/", url, re.I)
        period = next((part for part in match.groups() if part), "unknown") if match else "unknown"
        if period not in seen:
            chosen.append(row);seen.add(period)
            if len(chosen) == count:
                return chosen
    chosen += [row for row in ordered if row not in chosen][:count-len(chosen)]
    return chosen


def plan(cache, work, count, maximum):
    items, sources, manifest = collect(cache)
    groups = collections.defaultdict(list)
    stems = collections.defaultdict(set)
    for row in items.values():
        groups[tuple(row["family"])].append(row)
        match = re.search(r"(https?://docs.house.gov/meetings/[^/]+/[^/]+/\d{8}/(\d+)/)((?:HHRG|HMKP|HMTG)-\d+-[A-Z0-9]+).*?(\d{8})", row["url"], re.I)
        if match:
            stems[match[2]].add(match[1] + match[3] + "-" + match[4])
    with (work / "inventory.jsonl").open("w") as stream:
        for row in items.values():
            stream.write(json.dumps({**row, "sources": sorted(row["sources"]), "events": sorted(row["events"])}) + "\n")
    (work / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    (work / "cache_manifest.json").write_text(json.dumps(manifest) + "\n")
    families, requests = [], []
    for n, (key, rows) in enumerate(sorted(groups.items()), 1):
        fid = f"F{n:03d}"
        families.append({"family_id": fid, "host": key[0], "path_pattern": key[1], "document_family": key[2], "source_format": key[3], "urls": len(rows), "example_url": rows[0]["url"]})
        for row in choose(rows, count):
            for arm, url, headers in candidates(row, {"house_event_stems": stems}):
                requests.append({"family_id": fid, "source_url": row["url"], "arm": arm, "xml_url": url, "headers": headers})
    if len(requests) > maximum:
        raise SystemExit(f"Plan needs {len(requests)} requests across {len(families)} families; exceeds bound {maximum}. Inventory saved; no requests made.")
    (work / "families.json").write_text(json.dumps(families, indent=2) + "\n")
    (work / "plan.json").write_text(json.dumps(requests, indent=2) + "\n")
    with OUT.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(families[0]), lineterminator="\n");writer.writeheader();writer.writerows(families)
    print(json.dumps({"distinct_urls": len(items), "families": len(families), "planned_requests": len(requests), "work": str(work)}), flush=True)


def report(work):
    rows = json.loads((work / "results.json").read_text())
    finished_at = json.loads((work / "summary.json").read_text())["finished_at"]
    families = json.loads((work / "families.json").read_text())
    grouped = collections.defaultdict(list)
    earlier = collections.defaultdict(list)
    earlier_path = work.parent / "pdf_xml_probe/attempts.jsonl"
    if earlier_path.exists():
        latest = {}
        for line in earlier_path.read_text().splitlines():
            row = json.loads(line);latest[row["pdf_url"]] = row
        for row in latest.values():
            earlier[family(row["pdf_url"], "pdf")].append(row)
    for row in rows:
        grouped[row["family_id"]].append(row)
    for family_row in families:
        tests = grouped[family_row["family_id"]]
        previous = earlier[(family_row["host"], family_row["path_pattern"], family_row["document_family"], family_row["source_format"])]
        outcomes = collections.Counter(row["status"] for row in tests)
        family_row.update(sample_urls=len({row["source_url"] for row in tests}),
                          candidate_checks=len(tests),
                          checked=sum(row["status"] != "not_attempted_host_blocked" for row in tests),
                          valid_xml=outcomes["xml"],
                          missing=outcomes["not_found"],
                          other_format=outcomes["html"] + outcomes["not_xml"] + outcomes["xml_error"],
                          inconclusive=sum(outcomes[k] for k in ["blocked", "network_error", "http_error", "too_large", "not_attempted_host_blocked"]),
                          outcomes=json.dumps(dict(outcomes), sort_keys=True),
                          xml_roots=", ".join(sorted({row.get("root", "") for row in tests if row["status"] == "xml"})),
                          xml_example=next((row["xml_url"] for row in tests if row["status"] == "xml"), ""),
                          earlier_checked_urls=len(previous),
                          earlier_valid_xml=sum(row["status"] == "xml" for row in previous),
                          earlier_xml_example=next((row["xml_url"] for row in previous if row["status"] == "xml"), ""))
    with OUT.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(families[0]), lineterminator="\n");writer.writeheader();writer.writerows(families)
    unique = {row["request_key"]: row for row in rows}
    summary = {"finished_at": finished_at,
               "distinct_source_urls": sum(row["urls"] for row in families), "families": len(families),
               "sample_source_urls": len({row["source_url"] for row in rows}),
               "planned_cases": len(rows), "unique_candidates": len(unique),
               "attempted": sum(row["status"] != "not_attempted_host_blocked" for row in unique.values()),
               "deferred": sum(row["status"] == "not_attempted_host_blocked" for row in unique.values()),
               "outcomes": dict(collections.Counter(row["status"] for row in unique.values())),
               "xml_roots": dict(collections.Counter(row.get("root", "") for row in unique.values() if row["status"] == "xml"))}
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def run(work):
    cases = json.loads((work / "plan.json").read_text())
    journal = work / "attempts.jsonl"
    results = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            row = json.loads(line);results[row["request_key"]] = row
    for case in cases:
        case["request_key"] = hashlib.sha256(json.dumps([case["xml_url"], case["headers"]], sort_keys=True).encode()).hexdigest()
    pending = {case["request_key"]: case for case in cases if case["request_key"] not in results}
    (work / "xml").mkdir(exist_ok=True)
    pace = Pace(0.4)

    def check(case):
        row = probe({"pdf_url": case["source_url"], "xml_url": case["xml_url"]}, work, pace, case["headers"], retain_response=True)
        return {**case, **(row or {"status": "not_attempted_host_blocked"})}

    with journal.open("a", buffering=1) as stream, ThreadPoolExecutor(6) as pool:
        for n, future in enumerate(as_completed([pool.submit(check, case) for case in pending.values()]), 1):
            row = future.result();results[row["request_key"]] = row;stream.write(json.dumps(row) + "\n")
            if n % 30 == 0:
                print(json.dumps({"completed": n, "planned_unique": len(pending), "outcomes": dict(collections.Counter(r['status'] for r in results.values()))}), flush=True)
    rows = [{**case, **results[case["request_key"]], "family_id": case["family_id"], "source_url": case["source_url"], "arm": case["arm"]} for case in cases]
    (work / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    fields = ["family_id", "source_url", "arm", "xml_url", "status", "http_status", "content_type", "root", "final_url", "bytes", "checked_at", "body_path", "error"]
    with (DATA / "xml_path_family_samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n");writer.writeheader();writer.writerows(rows)
    summary = {"finished_at": datetime.now(timezone.utc).isoformat(), "planned_cases": len(cases), "unique_requests": len(results), "outcomes": dict(collections.Counter(r["status"] for r in results.values()))}
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report(work)
    print((work / "summary.json").read_text(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("~/hearing-text"))
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=600)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--report", action="store_true", help="Rebuild the family summary from saved results")
    args = parser.parse_args()
    cache = args.cache.expanduser().resolve();work = cache / "xml_path_families";work.mkdir(exist_ok=True)
    if args.report:
        report(work)
    elif args.run:
        run(work)
    else:
        plan(cache, work, args.sample_size, args.max_requests)
