"""
Read docs.house.gov for the House meetings whose Congress.gov record is missing something.

    python docs/youtube-coverage/research/scripts/house_event_pages.py [--cache ~/hearing-text] [--threads 6]

Congress.gov's meeting records are built from the House's Committee Repository (docs.house.gov), but
not all of it arrives: some records have no witnesses or documents although the repository's page for
the event has both, and transcripts posted months after a hearing are often absent. This reads the
repository's page for every scheduled House or joint meeting since the 113th Congress whose record has
no documents, no witnesses (for a hearing), or no transcript or print, and writes what the page has
that the record lacks:

- docs/youtube-coverage/research/data/house_documents_found.csv: one row per document (`kind`:
  transcript, witness list, witness statement, witness biography, truth in testimony, member
  statement, questions for the record, bill or amendment, recorded vote, report, support document);
- docs/youtube-coverage/research/data/house_witnesses_found.csv: one row per witness (name, position,
  organization, panel).

Pages are cached under `--cache`/docs_house, so a rerun fetches only new events.
"""
import argparse, collections, csv, gzip, html, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meeting_completeness import kind  # noqa: E402

MEETINGS = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
INDEX = ROOT / "docs/youtube-coverage/research/data/hearing_text_sources.csv"
OUT_DOCUMENTS = ROOT / "docs/youtube-coverage/research/data/house_documents_found.csv"
OUT_WITNESSES = ROOT / "docs/youtube-coverage/research/data/house_witnesses_found.csv"
PAGE = "https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

## the repository names its files by what they are: HHRG-115-VR09-Wstate-MurphyT-20170214.pdf
KINDS = [("transcript", r"-Transcript-"), ("witness list", r"-WList-"), ("witness statement", r"-Wstate-"), ("witness biography", r"-Bio-"),
         ("truth in testimony", r"-TTF-"), ("member statement", r"-MState-"), ("questions for the record", r"-QFR-"),
         ("recorded vote", r"-RCP|-Vote"), ("report", r"^CRPT-"), ("bill or amendment", r"^BILLS-|-Amdt-"), ("support document", r"-SD\d")]
DOCUMENT = re.compile(r"<li>(.*?)\[<a [^>]*href=\"([^\"]+)\"[^>]*>\s*(?:PDF|XML|DOC[X]?|HTML?)\s*</a>\]", re.I | re.S)
WITNESS = re.compile(r"<h3 class=\"witPanelHeader\">(.*?)</h3>|<p><strong>(.*?)</strong>\s*(?:<br\s*/?>)?\s*(?:<small[^>]*>(.*?)</small>)?", re.S)
text = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def fetch(event_id, cache):
    path = cache / "docs_house" / f"{event_id}.html"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(PAGE.format(event_id), timeout=60, headers=UA)
            path.write_text(r.text if r.status_code == 200 else "")
        except requests.RequestException:
            return ""
    return path.read_text()


def documents(page):
    """(kind, name, url) for each document the page links."""
    out = []
    for name, url in DOCUMENT.findall(page):
        file = url.rsplit("/", 1)[-1]
        out.append((next((k for k, pattern in KINDS if re.search(pattern, file)), "other"), text(name), url.replace("http://", "https://")))
    return out


def witnesses(page):
    """(name, position, organization, panel) for each witness the page lists."""
    start, end = page.find("<h2>Witnesses"), page.find("<h2>", page.find("<h2>Witnesses") + 1)
    if start < 0:
        return []
    out, panel = [], ""
    for header, name, details in WITNESS.findall(page[start:end if end > 0 else len(page)]):
        if header:
            panel = text(header)
        elif text(name):
            ## "(Accompanying Mr. Thomas) Deputy Under Secretary ..., on behalf of U.S. Department of Veterans Affairs"
            position, _, organization = text(details).partition(", on behalf of ")
            out.append((text(name), position, organization, panel))
    return out


def main(cache, threads):
    index = {r["event_id"]: r for r in csv.DictReader(open(INDEX))}
    lacking = []
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            r = index.get(m["eventId"])
            if r and m.get("chamber") != "Senate" and not r["not_held"] and (
                    not (m.get("meetingDocuments") or m.get("witnessDocuments"))
                    or (kind(m) == "hearing" and not m.get("witnesses"))
                    or r["text_source"] not in ("gpo", "committee_transcript")):
                lacking.append(m)
    with ThreadPoolExecutor(threads) as pool:
        pages = dict(zip([m["eventId"] for m in lacking], pool.map(lambda m: fetch(m["eventId"], cache), lacking)))
    found_documents, found_witnesses, totals = [], [], collections.Counter()
    for m in lacking:
        page = pages[m["eventId"]]
        totals["pages read"] += 1
        totals["pages with nothing (no such event in the repository)"] += not page
        have = {d["url"].rsplit("/", 1)[-1] for d in (m.get("meetingDocuments") or []) + (m.get("witnessDocuments") or []) if d.get("url")}
        new = [d for d in documents(page) if d[2].rsplit("/", 1)[-1] not in have]
        found_documents += [{"event_id": m["eventId"], "kind": k, "name": n, "url": u} for k, n, u in new]
        totals["meetings with documents the record lacks"] += bool(new)
        totals["meetings with a transcript the record lacks"] += any(k == "transcript" for k, _, _ in new)
        if not m.get("witnesses"):
            listed = witnesses(page)
            found_witnesses += [{"event_id": m["eventId"], "name": n, "position": p, "organization": o, "panel": pn} for n, p, o, pn in listed]
            totals["meetings with witnesses the record lacks"] += bool(listed)
    for path, rows in ((OUT_DOCUMENTS, found_documents), (OUT_WITNESSES, found_witnesses)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"{len(found_documents):,} documents -> {OUT_DOCUMENTS.relative_to(ROOT)}, {len(found_witnesses):,} witnesses -> {OUT_WITNESSES.relative_to(ROOT)}")
    for k, v in totals.items():
        print(f"  {k}: {v:,}")
    print("  documents by kind: " + ", ".join(f"{k} {v:,}" for k, v in collections.Counter(d["kind"] for d in found_documents).most_common()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text"); p.add_argument("--threads", type=int, default=6)
    a = p.parse_args(); main(Path(a.cache).expanduser(), a.threads)
