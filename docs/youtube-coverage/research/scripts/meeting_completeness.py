"""
What each committee meeting since the 113th Congress has on the public record, and what it lacks.

    python docs/youtube-coverage/research/scripts/meeting_completeness.py [--cache ~/hearing-text]

One row per Congress.gov meeting record (scheduled or rescheduled), from the meeting export and the
text index (`hearing_text_sources.csv`): its recording, where its text is, its witness list, its
witness and meeting documents, its location and its related bills or nominations. Congress.gov lists
witnesses for House meetings only, and not for all of them, so a hearing's witness list is filled from
two other places when it is missing:

- the House's Committee Repository (docs.house.gov), whose page for the event lists witnesses that
  Congress.gov's record lacks (`house_event_pages.py` reads them);
- the GPO record (MODS) of the hearing's print, when the print and the meeting are each other's only
  match (a volume or a same-day print shared by several meetings can't say whose witnesses are whose);
- the "Witness List" document attached to the meeting, read with `pdftotext` when it has a text layer;
- the meeting's own title, for a Senate nomination hearing: the nominees it names are its witnesses;
- the Senate committee's own page for the hearing (`senate_hearing_pages.py` reads them), for the Senate
  hearings the first four leave without a list.

Writes docs/youtube-coverage/research/data/meeting_completeness.csv (one row per meeting) and
meeting_witnesses.csv (the witnesses filled from those two places; Congress.gov's own are in the
meeting export), and prints the totals. MODS records and documents are cached under `--cache`.
"""
import argparse, collections, csv, gzip, html, json, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages/congress_api/src")); sys.path.insert(0, str(ROOT / "packages/congress_shared/src"))
from congress_api.transcribe.metadata import TITLE, is_name, people_in_mods  # noqa: E402

MEETINGS = ROOT.parent / "pipeline-data/congress_meetings.jsonl.gz"
INDEX = ROOT / "docs/youtube-coverage/research/data/hearing_text_sources.csv"
PRINT_VIDEOS = ROOT / "apps/committee_youtube/data/gpo_hearing_videos.csv"
OUT = ROOT / "docs/youtube-coverage/research/data/meeting_completeness.csv"
OUT_WITNESSES = ROOT / "docs/youtube-coverage/research/data/meeting_witnesses.csv"
HOUSE_WITNESSES = ROOT / "docs/youtube-coverage/research/data/house_witnesses_found.csv"
HOUSE_DOCUMENTS = ROOT / "docs/youtube-coverage/research/data/house_documents_found.csv"
SENATE_WITNESSES = ROOT / "docs/youtube-coverage/research/data/senate_witnesses_found.csv"
UA = {"User-Agent": "Mozilla/5.0"}
CLOSED = re.compile(r"closed|briefing|deposition|executive session", re.I)


def kind(m):
    """hearing, markup or business: Congress.gov types House meetings; every Senate and joint record is a "Meeting",
    and its title says which ("Hearings to examine ...", "Business meeting to consider ...")."""
    title = (m.get("title") or "").strip().lower()
    if m.get("type") == "Markup" or re.match(r"(closed )?(business meeting to )?mark ?up", title):
        return "markup"
    if m.get("type") == "Hearing" or (m.get("chamber") != "House" and re.match(r"(an? )?(oversight |closed |open |joint )*hearings?\b", title)):
        return "hearing"
    return "business"


NOMINEE = re.compile(r"(?:nominations? of |, (?:and )?)((?:[A-Z][\w.'\u2019\-]*\.? ){1,5}[A-Z][\w'\u2019\-]+(?:,? (?:Jr|Sr|II|III|IV)\.?)?), of (?:the )?[A-Z][\w. ]+?, to be ([^,;.]+(?:, [^,;.]+)??)(?=[,;.]| and )")


def nominees(title):
    """(name, the office they are nominated to) for each nominee a nomination hearing's title names:
    "Hearings to examine the nominations of Thomas Peter Feddo, of Virginia, to be Assistant Secretary of the
    Treasury for Investment Security, Nazak Nikakhtar, of Maryland, to be Under Secretary of Commerce ..."."""
    return [(name.strip(), office.strip()) for name, office in NOMINEE.findall(re.sub(r"\s+", " ", title))] if re.search(r"\bnominations?\b", title, re.I) else []


def cached(path, fetch):
    """The file at `path`, fetched once."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(fetch())
        except (requests.RequestException, OSError):
            path.write_bytes(b"")
    return path.read_bytes()


def gpo_witnesses(package_id, cache):
    """Witnesses named in a print's GPO record."""
    mods = cached(cache / "mods" / f"{package_id}.xml", lambda: requests.get(f"https://www.govinfo.gov/metadata/pkg/{package_id}/mods.xml", timeout=60, headers=UA).content)
    people, _ = people_in_mods(mods.decode("utf-8", "replace"))
    return [p for p in people.values() if p.role == "witness" and p.name]


def document_witnesses(url, cache):
    """Witnesses named in a Witness List document: each name stands on its own line and opens with a title
    ("Ms. Lauren Ploch Blanchard"); the lines under it give the position and organization. [] for a scan."""
    pdf = cached(cache / "witness_lists" / re.sub(r"\W+", "_", url.split("/meeting/")[-1]), lambda: requests.get(url, timeout=60, headers=UA).content)
    if not pdf.startswith(b"%PDF"):
        return []
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf); f.flush()
        text = subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout  # reading order: a two-column list column by column
    out, current = [], None
    for line in (l.strip() for l in text.splitlines()):
        title = TITLE.match(line + " ")
        name = re.sub(r",.*$", "", line[title.end():]).strip() if title else ""
        if is_name(name) and len(line.split()) <= 8 and not line.endswith(":"):
            current = {"name": name, "details": []}
            out.append(current)
        elif not line or re.match(r"(panel|witnesses)\b", line, re.I):
            current = None
        elif current is not None and len(current["details"]) < 4:
            current["details"].append(line)
    return [{"name": w["name"], "position": w["details"][0] if w["details"] else "", "organization": ", ".join(w["details"][1:])} for w in out]


def main(cache):
    index = {r["event_id"]: r for r in csv.DictReader(open(INDEX))}
    recorded = {r["package_id"] for r in csv.DictReader(open(PRINT_VIDEOS)) if r["status"] in ("full_recording", "full_recording_offsite")}
    meetings = []
    with gzip.open(MEETINGS, "rt", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            if m["eventId"] in index:
                meetings.append(m)
    prints_of = {e: r["gpo_packages"].split() for e, r in index.items()}
    meetings_of = collections.defaultdict(list)
    for e, prints in prints_of.items():
        for p in prints:
            meetings_of[p].append(e)
    from_house, house_documents, from_senate = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for path, into in ((HOUSE_WITNESSES, from_house), (HOUSE_DOCUMENTS, house_documents), (SENATE_WITNESSES, from_senate)):
        if path.exists():
            for r in csv.DictReader(open(path)):
                into[r["event_id"]].append(r)
    lacking = [m for m in meetings if kind(m) == "hearing" and not m.get("witnesses") and not from_house[m["eventId"]]]
    ## a print that is one meeting's only print, and matched to no other meeting, names that meeting's witnesses
    own_print = {m["eventId"]: prints_of[m["eventId"]][0] for m in lacking if len(prints_of[m["eventId"]]) == 1 and len(meetings_of[prints_of[m["eventId"]][0]]) == 1}
    witness_list = {m["eventId"]: d["url"] for m in lacking for d in m.get("meetingDocuments") or [] if "witness list" in (d.get("name") or "").lower() and d.get("url")}
    with ThreadPoolExecutor(12) as pool:
        from_gpo = dict(zip(own_print, pool.map(lambda p: gpo_witnesses(p, cache), own_print.values())))
        from_list = dict(zip(witness_list, pool.map(lambda u: document_witnesses(u, cache), witness_list.values())))

    rows, filled = [], []
    for m in meetings:
        e, r = m["eventId"], index[m["eventId"]]
        listed = m.get("witnesses") or []
        source, count = ("congress.gov", len(listed)) if listed else ("", 0)
        if not listed and from_house[e]:
            source, count = "docs.house.gov", len(from_house[e])
            filled += [{"event_id": e, "name": w["name"], "position": w["position"], "organization": w["organization"], "source": "docs.house.gov", "from": f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={e}"} for w in from_house[e]]
        elif not listed and from_gpo.get(e):
            source, count = "gpo", len(from_gpo[e])
            filled += [{"event_id": e, "name": p.name, "position": p.position, "organization": html.unescape(p.organization), "source": "gpo", "from": own_print[e]} for p in from_gpo[e]]
        elif not listed and from_list.get(e):
            source, count = "witness list document", len(from_list[e])
            filled += [{"event_id": e, **w, "source": "witness list document", "from": witness_list[e]} for w in from_list[e]]
        elif not listed and kind(m) == "hearing" and nominees(m.get("title") or ""):
            named = nominees(m["title"])
            source, count = "meeting title (nominees)", len(named)
            filled += [{"event_id": e, "name": n, "position": f"nominee to be {office}", "organization": "", "source": "meeting title (nominees)", "from": m["_url"]} for n, office in named]
        elif not listed and from_senate[e]:
            source, count = "senate committee page", len(from_senate[e])
            filled += [{"event_id": e, "name": w["name"], "position": w["position"], "organization": w["organization"], "source": "senate committee page", "from": w["page"]} for w in from_senate[e]]
        shared = [p for p in prints_of[e] if p not in own_print.values()]
        rows.append({"event_id": e, "congress": m["congress"], "chamber": m.get("chamber", ""), "kind": kind(m), "closed": "yes" if m.get("type", "").startswith("Closed") or CLOSED.search(m.get("title") or "") else "",
                     "date": m["date"][:10], "committees": r["committees"], "title": r["title"],
                     ## a printed hearing's recording is matched to its print by the weekly matcher
                     "recording": "yes" if r["youtube_ids"] or r["senate_urls"] or r["other_recordings"] or recorded & set(prints_of[e]) else "", "text_source": r["text_source"],
                     "witnesses": count, "witness_source": source,
                     "witness_list_document": "scan" if e in witness_list and not from_list.get(e) else "yes" if e in witness_list else "",
                     "print_shared_with_other_meetings": "yes" if not source and shared else "",
                     "witness_documents": len(m.get("witnessDocuments") or []), "meeting_documents": len(m.get("meetingDocuments") or []),
                     "documents_only_on_docs_house_gov": len(house_documents[e]),
                     "location": "yes" if m.get("location") else "", "related_items": len(m.get("relatedItems") or []),
                     "rescheduled_to": r["rescheduled_to"], "not_held": r["not_held"]})
    rows.sort(key=lambda r: (r["date"], r["event_id"]))
    for path, data in ((OUT, rows), (OUT_WITNESSES, sorted(filled, key=lambda w: (w["event_id"], w["name"])))):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys())); w.writeheader(); w.writerows(data)
    print(len(rows), "meetings ->", OUT.relative_to(ROOT), "|", len(filled), "witnesses filled ->", OUT_WITNESSES.relative_to(ROOT))

    held = [r for r in rows if not r["rescheduled_to"] and not r["not_held"]]
    for chamber in ("House", "Senate", "NoChamber"):
        hearings = [r for r in held if r["chamber"] == chamber and r["kind"] == "hearing" and not r["closed"]]
        if hearings:
            n = len(hearings)
            c = collections.Counter(r["witness_source"] or ("none (a scanned witness list)" if r["witness_list_document"] == "scan" else "none (print shared with other meetings)" if r["print_shared_with_other_meetings"] else "none") for r in hearings)
            print(f"  {chamber} open hearings ({n:,}) witness list: " + ", ".join(f"{k} {v:,} ({v / n:.0%})" for k, v in c.most_common()))
            any_document = sum(1 for r in hearings if r["witness_documents"] or r["meeting_documents"] or r["documents_only_on_docs_house_gov"])
            print(f"      recording {sum(1 for r in hearings if r['recording']) / n:.0%}, text {sum(1 for r in hearings if r['text_source'] != 'no_video' and r['text_source'] != 'video_no_captions') / n:.0%}, "
                  f"any document {any_document / n:.0%} (in Congress.gov's record {sum(1 for r in hearings if r['witness_documents'] or r['meeting_documents']) / n:.0%}), location {sum(1 for r in hearings if r['location']) / n:.0%}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cache", default="~/hearing-text", help="folder for fetched GPO records and documents")
    main(Path(p.parse_args().cache).expanduser())
