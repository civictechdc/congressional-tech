"""Match prints to meetings for both the House reader and the final text index.

An event ID, an attached print, a matching title, a collected volume or a unique
committee/day pair establishes ownership. Date alone formerly misassigned 676
prints. Congress.gov's hearingTranscript field also misassigns proceedings and
is not used. A markup may also take a print explicitly titled as a markup.
"""

import collections
import re

from congress_api.matching.committees import codes_of
from congress_api.matching.gpo_videos import matching_days, similarity, words
from congress_api.matching.meetings import meeting_type

PRINT_FILE = re.compile(r"/(CHRG-\d{3}[hsj]hrg[\w\-]+?)(?:\.\w+)?$", re.I)


COLLECTION = re.compile(r"APPROPRIATIONS FOR (FISCAL YEAR )?\d{4}|AUTHORIZATION FOR APPROPRIATIONS|NOMINATIONS OF THE \d+\w* CONGRESS|NOMINATIONS BEFORE THE", re.I)


def title_key(title):
    distinct = words(title)
    return " ".join(sorted(distinct)) if len(distinct) >= 4 else ""


def same_day_title_groups(rows):
    """One sharing rule for prints and recordings; never merge meeting IDs."""
    groups = collections.defaultdict(list)
    for row in rows:
        if key := title_key(row.get("title") or ""):
            groups[row["date"][:10], key].append(row)
    return groups


def attached_prints(urls):
    return {"CHRG-" + p[5:].lower() for url in urls for p in PRINT_FILE.findall(url)}


def match_prints(meetings, gpo, attached=None, *, share=True, decisions=None):
    """Keep the established match set; optionally append its accepted reasons.

    Each decision records one accepted rule for a meeting/package association.
    An association can have several reasons, including several committee/day
    paths. Scores are actual title similarities, never general confidence.
    """
    attached = attached or {}
    gpo = [r for r in gpo if int(r["congress"]) >= 113]
    evidence_rows = collections.defaultdict(list)
    if decisions is not None:
        for r in gpo:
            evidence_rows[r["package_id"]].append({k: r.get(k) for k in (
                "package_id", "congress", "event_id", "committee_code", "committee_code_gpo", "held_date", "hearing_dates", "title")})
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
    out, meeting_evidence = {}, {}
    for m in meetings:
        event, day = m["eventId"], m["date"][:10]
        kind, type_field = meeting_type(m)
        if decisions is not None:
            meeting_evidence[event] = {k: m.get(k) for k in ("eventId", "congress", "date", "type", "title", "committees")}
        tw = words(m.get("title") or "")
        held = attached.get(event, set()) | attached_prints(d.get("url") or "" for d in m.get("meetingDocuments") or [])

        def decision(package, rule, basis, **details):
            if decisions is not None:
                decisions.append({
                    "event_id": event, "package_id": package, "rule": rule,
                    "rule_version": "2" if rule in ("markup_print_day", "unique_committee_day") else "1", "basis": basis,
                    "evidence": {
                        "meeting": meeting_evidence[event],
                        "packages": evidence_rows[package],
                        **details,
                    },
                })

        out[event] = set(by_eid[event])
        for package in sorted(by_eid[event]) if decisions is not None else ():
            decision(package, "package_event_id", "derived")
        for c in codes_of(m):
            for p in sorted(by_day[c, day]):
                score = similarity(tw, print_words[p])
                reasons = (
                    (score >= 0.4, "title_similarity", "inferred"),
                    (p in collection, "collection_day", "inferred"),
                    (p in held, "attached_file", "derived"),
                    (kind == "markup" and p in markup_print, "markup_print_day", "inferred"),
                    (kind != "markup" and meetings_that_day[c, day] == 1 and len(by_day[c, day]) == 1, "unique_committee_day", "inferred"),
                )
                if any(accepted for accepted, _, _ in reasons):
                    out[event].add(p)
                if decisions is not None:
                    for accepted, rule, basis in reasons:
                        if not accepted:
                            continue
                        details = {"matching_committee_code": c, "matching_day": day}
                        if rule in ("markup_print_day", "unique_committee_day"):
                            details.update(meeting_type=kind, meeting_type_source=type_field)
                        if rule == "title_similarity":
                            details.update(score=score, threshold=0.4,
                                           meeting_words=sorted(tw), package_words=sorted(print_words[p]))
                        elif rule == "attached_file":
                            details.update(meeting_document_urls=[d.get("url") or "" for d in m.get("meetingDocuments") or []],
                                           supplemental_attached_packages=sorted(attached.get(event, set())))
                        elif rule == "unique_committee_day":
                            details.update(meeting_count=meetings_that_day[c, day], package_count=len(by_day[c, day]))
                        decision(p, rule, basis, **details)
    ## A joint hearing entered once per committee shares its prints across those entries.
    for (day, key), group in same_day_title_groups(meetings).items() if share else ():
        events = [m["eventId"] for m in group]
        packages = set().union(*(out[e] for e in events))
        before = {event: set(out[event]) for event in events} if decisions is not None else None
        for event in events:
            out[event] = packages
            if decisions is not None:
                for package in sorted(packages - before[event]):
                    origins = sorted({e for e in events if package in before[e]})
                    decisions.append({
                        "event_id": event, "package_id": package, "rule": "same_day_title_sharing", "rule_version": "1", "basis": "inferred",
                        "shared_from": origins,
                        "evidence": {"matching_day": day, "title_key": key, "meeting_event_ids": list(events),
                                     "meeting": meeting_evidence[event], "shared_from_meetings": [meeting_evidence[e] for e in origins],
                                     "packages": evidence_rows[package]},
                    })
    return out
