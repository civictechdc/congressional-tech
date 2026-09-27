"""Match prints to meetings for both the House reader and the final text index.

An event ID, an attached print, a matching title, a collected volume or a unique
committee/day pair establishes ownership. Date alone formerly misassigned 676
prints. Congress.gov's hearingTranscript field also misassigns proceedings and
is not used. A markup may also take a print explicitly titled as a markup.
"""
import collections
import re

from congress_api.committees import codes_of
from congress_api.gpo.match import matching_days, similarity, words

PRINT_FILE = re.compile(r"/(CHRG-\d{3}[hsj]hrg[\w\-]+?)(?:\.\w+)?$", re.I)
COLLECTION = re.compile(r"APPROPRIATIONS FOR (FISCAL YEAR )?\d{4}|AUTHORIZATION FOR APPROPRIATIONS|NOMINATIONS OF THE \d+\w* CONGRESS|NOMINATIONS BEFORE THE", re.I)


def title_key(title):
    distinct = words(title)
    return " ".join(sorted(distinct)) if len(distinct) >= 4 else ""


def attached_prints(urls):
    return {"CHRG-" + p[5:].lower() for url in urls for p in PRINT_FILE.findall(url)}


def match_prints(meetings, gpo, attached=None, *, share=True):
    attached = attached or {}
    gpo = [r for r in gpo if int(r["congress"]) >= 113]
    by_eid, by_day = collections.defaultdict(set), collections.defaultdict(set)
    print_words = {r["package_id"]: words(r["title"]) for r in gpo}
    collection = {r["package_id"] for r in gpo if COLLECTION.search(r["title"]) or ";" in r["hearing_dates"]}
    markup_print = {r["package_id"] for r in gpo if re.search(r"\bmark-?up\b", r["title"], re.I)}
    for r in gpo:
        if r["event_id"]:
            by_eid[r["event_id"]].add(r["package_id"])
        for day in matching_days(r):
            by_day[r["committee_code"], day].add(r["package_id"])
    meetings_that_day = collections.Counter((c, m["date"][:10]) for m in meetings for c in codes_of(m))
    out, twins = {}, collections.defaultdict(list)
    for m in meetings:
        event, day = m["eventId"], m["date"][:10]
        tw = words(m.get("title") or "")
        held = attached.get(event, set()) | attached_prints(d.get("url") or "" for d in m.get("meetingDocuments") or [])
        out[event] = set(by_eid[event]) | {
            p for c in codes_of(m) for p in by_day[c, day]
            if similarity(tw, print_words[p]) >= 0.4 or p in collection or p in held
            or (m.get("type") == "Markup" and p in markup_print)
            or (m.get("type") != "Markup" and meetings_that_day[c, day] == 1 and len(by_day[c, day]) == 1)}
        key = title_key(m.get("title") or "")
        if key:
            twins[day, key].append(event)
    ## A joint hearing entered once per committee shares its prints across those entries.
    for events in twins.values() if share else ():
        packages = set().union(*(out[e] for e in events))
        for event in events:
            out[event] = packages
    return out
