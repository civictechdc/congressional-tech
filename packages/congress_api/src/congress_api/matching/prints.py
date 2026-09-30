"""Match prints to meetings for both the House reader and the final text index.

An event ID, an attached print, a matching title, a collected volume or a unique
committee/day pair establishes ownership. Date alone formerly misassigned 676
prints. Congress.gov's hearingTranscript field also misassigns proceedings and
is not used. A markup may also take a print explicitly titled as a markup.
Collection volumes need title overlap or a unique committee/day—never every
meeting that day. Day occupancy uses native parent codes so select-committee
aliases do not share Judiciary's uniqueness key.
"""

import collections
import re

from congress_api.matching.committees import codes_of, occupancy_codes_of
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


def match_prints(meetings, gpo, attached=None, *, share=True, decisions=None, strong=None):
    """Keep the established match set; optionally append its accepted reasons.

    Each decision records one accepted rule for a meeting/package association.
    An association can have several reasons, including several committee/day
    paths. Scores are actual title similarities, never general confidence.
    When ``strong`` is a dict, it is filled with packages owned by event ID or
    an attached file (callers use that to gate weaker YouTube window matches).
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
    # Native parents only: hlqj00/hlfd00 must not inflate hsju00 uniqueness.
    meetings_that_day = collections.Counter((c, m["date"][:10]) for m in meetings for c in occupancy_codes_of(m))
    out, meeting_evidence = {}, {}
    for m in meetings:
        event, day = m["eventId"], m["date"][:10]
        kind, type_field = meeting_type(m)
        if decisions is not None:
            meeting_evidence[event] = {k: m.get(k) for k in ("eventId", "congress", "date", "type", "title", "committees")}
        tw = words(m.get("title") or "")
        held = attached.get(event, set()) | attached_prints(d.get("url") or "" for d in m.get("meetingDocuments") or [])
        native = set(occupancy_codes_of(m))

        def decision(package, rule, basis, **details):
            if decisions is not None:
                decisions.append({
                    "event_id": event, "package_id": package, "rule": rule,
                    "rule_version": "2" if rule in ("markup_print_day", "unique_committee_day", "collection_day") else "1", "basis": basis,
                    "evidence": {
                        "meeting": meeting_evidence[event],
                        "packages": evidence_rows[package],
                        **details,
                    },
                })

        out[event] = set(by_eid[event])
        if strong is not None:
            strong[event] = set(by_eid[event])
        for package in sorted(by_eid[event]) if decisions is not None else ():
            decision(package, "package_event_id", "derived")
        for c in codes_of(m):
            # Unique ownership only for a native parent code. Aliases still find packages for
            # title/attached/collection, but must not steal Judiciary's unique-day slot.
            unique_day = (kind != "markup" and c in native
                          and meetings_that_day[c, day] == 1 and len(by_day[c, day]) == 1)
            for p in sorted(by_day[c, day]):
                score = similarity(tw, print_words[p])
                title_hit = score >= 0.4
                attached_hit = p in held
                collection_hit = p in collection and (title_hit or unique_day)
                reasons = (
                    (title_hit, "title_similarity", "inferred"),
                    (collection_hit, "collection_day", "inferred"),
                    (attached_hit, "attached_file", "derived"),
                    (kind == "markup" and p in markup_print, "markup_print_day", "inferred"),
                    (unique_day, "unique_committee_day", "inferred"),
                )
                if any(accepted for accepted, _, _ in reasons):
                    out[event].add(p)
                    if strong is not None and (p in by_eid[event] or attached_hit):
                        strong[event].add(p)
                if decisions is not None:
                    for accepted, rule, basis in reasons:
                        if not accepted:
                            continue
                        details = {"matching_committee_code": c, "matching_day": day}
                        if rule in ("markup_print_day", "unique_committee_day", "collection_day"):
                            details.update(meeting_type=kind, meeting_type_source=type_field)
                        if rule == "title_similarity":
                            details.update(score=score, threshold=0.4,
                                           meeting_words=sorted(tw), package_words=sorted(print_words[p]))
                        elif rule == "attached_file":
                            details.update(meeting_document_urls=[d.get("url") or "" for d in m.get("meetingDocuments") or []],
                                           supplemental_attached_packages=sorted(attached.get(event, set())))
                        elif rule in ("unique_committee_day", "collection_day"):
                            details.update(meeting_count=meetings_that_day[c, day] if c in native else 0,
                                           package_count=len(by_day[c, day]))
                        if rule == "collection_day":
                            details.update(title_score=score, title_threshold=0.4, unique_committee_day=unique_day)
                        decision(p, rule, basis, **details)
    ## A joint hearing entered once per committee shares its prints across those entries.
    for (day, key), group in same_day_title_groups(meetings).items() if share else ():
        events = [m["eventId"] for m in group]
        packages = set().union(*(out[e] for e in events))
        before = {event: set(out[event]) for event in events} if decisions is not None else None
        for event in events:
            out[event] = packages
            if strong is not None:
                strong[event] = set().union(*(strong.get(e, set()) for e in events))
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
