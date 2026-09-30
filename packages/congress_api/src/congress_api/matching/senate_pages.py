"""Associate Senate pages with meetings and report retained decisions."""

import collections
import datetime as dt
import json
import math
import re

from congress_api.matching.committees import codes_of
from congress_api.matching.gpo_videos import words
from congress_api.matching.meetings import HEARING_TYPES, meeting_access, meeting_type
from congress_api.matching.senate_corrections import DATE_CORRECTIONS, selected_date
from congress_api.parsers.senate_page import BUSINESS, DATE, NEAR, OWN, SITE, topic, written_day


def match_pages(meetings, state):
    code = lambda r: r["committees"].split(";")[0]
    hearings, titles = [], collections.defaultdict(list)
    for m in meetings:
        codes = codes_of(m)
        if m.get("chamber") != "House" and codes:
            c = codes[0]
            titles[c].append(set(words(topic(m.get("title") or ""))))
            if c in SITE and m.get("date") and (meeting_access(m)[0] != "closed" or c in ("slia00", "scnc00")):
                hearings.append({"event_id": m["eventId"], "date": m["date"][:10], "title": (m.get("title") or "").strip(), "committees": ";".join(codes), "kind": meeting_type(m)[0]})
    ## a subject word weighs by how few of the committee's titles hold it
    held_in = {c: collections.Counter(w for t in ts for w in t) for c, ts in titles.items()}
    weight = lambda c, w: math.log(len(titles[c]) / held_in[c][w])

    sites = sorted({SITE[code(r)] for r in hearings} & set(state))
    hearings = [row for row in hearings if SITE[code(row)] in sites]
    listings = {s: {u: (dt.date.fromisoformat(v[0]), v[1]) for u, v in state[s]["listings"].items()} for s in sites}
    pages = {u: p for s in sites for u, p in state[s]["pages"].items() if u in listings[s]}
    found = {u: p.get("documents", []) for u, p in pages.items()}
    for listing in listings.values():
        for url in listing:
            found.setdefault(url, [])
    page_words, on_day = {}, collections.defaultdict(list)
    for s in sites:
        print(f"  {s}: {len(listings[s]):,} hearing pages listed, {sum(1 for u in listings[s] if pages.get(u, {})):,} read", flush=True)
        ## what many of a site's pages carry or link is the site's, not a hearing's
        written = {u: set(pages.get(u, {}).get("lines", [])) for u in listings[s]}
        carried_by = collections.Counter(l for u in listings[s] for l in written[u])
        linked_by = collections.Counter(file for u in listings[s] for _, _, file in found[u])
        for u in listings[s]:
            own = " \n ".join(l for l in written[u] if carried_by[l] <= OWN)
            page_words[u] = set(words(own))
            found[u] = [d for d in found[u] if linked_by[d[2]] <= OWN]
            event = pages.get(u, {}).get("event")
            days = {dt.date.fromisoformat(selected_date(u, event))} if event else {written_day(m) for m in DATE.finditer(own)}
            if u in DATE_CORRECTIONS:
                days.add(dt.date.fromisoformat(DATE_CORRECTIONS[u]["date"]))
            for day in days:
                on_day[s, day].append(u)

    found_pages, found_witnesses, found_documents, stats = [], [], [], collections.Counter(hearings=len(hearings))
    for r in hearings:
        e, c, day = r["event_id"], code(r), dt.date.fromisoformat(r["date"])
        named = lambda u: f"{u.rstrip('/').rsplit('/', 1)[-1]} {listings[SITE[c]][u][1]}"
        its = [(abs((listings[SITE[c]][u][0] - day).days), u) for u in on_day[SITE[c], day] if r["kind"] not in HEARING_TYPES or not BUSINESS.search(named(u)) or re.search(r"hearing|nominat", named(u), re.I)]
        stats["with a page that names the day"] += bool(its)
        subject = set(words(topic(r["title"])))
        whole = sum(weight(c, w) for w in sorted(subject))
        held = sorted((-sum(weight(c, w) for w in sorted(subject & page_words[u])) / whole if whole else -len(subject & page_words[u]) / max(1, len(subject)), away, -len(found[u]), u) for away, u in its if away <= NEAR)
        held = [h for h in held if -h[0] >= 0.5]
        best = [(u, pages.get(u, {}).get("witnesses", [])) for share, away, _, u in held if (share, away) == held[0][:2]]
        if not best or (len(best) > 1 and not best[0][1]) or any(sorted(w["name"] for w in people) != sorted(w["name"] for w in best[0][1]) for _, people in best):
            stats["whose pages that day hold under half of the subject"] += bool(its and not best)
            stats["whose pages that day hold as much of the subject as each other"] += bool(best)
            continue
        page, people = best[0]
        stats["with its page"] += 1
        files = found[page]
        found_pages.append({"event_id": e, "page": page, "title": pages[page]["title"], "witnesses": len(people), "documents": len(files)})
        found_witnesses += [{"event_id": e, **w, "page": page} for w in people]
        found_documents += [{"event_id": e, "kind": k, "name": n, "url": f, "page": page} for k, n, f in files]
        stats["with witnesses"] += bool(people)
        stats["with documents"] += bool(files)
        stats["with a transcript"] += any(k == "transcript" for k, _, _ in files)
    return found_pages, found_witnesses, found_documents


def retained_matches(state):
    """CSV views use the same saved associations as the downstream adapter."""
    pages, witnesses, documents = [], [], []
    for site in state.values():
        shared = collections.Counter(document[2] for url, page in site.get("pages", {}).items() if url in site.get("listings", {}) for document in page.get("documents", []))
        for url, page in site.get("pages", {}).items():
            files = [document for document in page.get("documents", []) if shared[document[2]] <= OWN]
            people = page.get("witnesses", [])
            for event in page.get("events", []):
                pages.append({"event_id": event, "page": url, "title": page.get("title", ""), "witnesses": len(people), "documents": len(files)})
                for index, person in enumerate(people):
                    metadata = (page.get("witness_metadata") or {}).get(str(index), {})
                    witnesses.append({"event_id": event, **person, "page": url, "location": metadata.get("location", "")})
                for kind, name, file in files:
                    metadata = (page.get("document_metadata") or {}).get(file, {})
                    indexes = metadata.get("witness_indexes", [])
                    documents.append({"event_id": event, "kind": kind, "name": name, "url": file, "page": url,
                                      "source_labels": json.dumps(metadata.get("labels", []), ensure_ascii=False),
                                      "witness_indexes": json.dumps(indexes),
                                      "witness_names": json.dumps([people[index]["name"] for index in indexes if isinstance(index, int) and 0 <= index < len(people)], ensure_ascii=False)})
    return pages, witnesses, documents


def mark_possible_matches(meetings, state):
    """Unresolved same-day native events prevent accidental duplicate admission.

    A date/committee collision alone never establishes a match. Keep the source
    event and its evidence, and expose the unresolved association for review.
    """
    native = collections.defaultdict(set)
    for meeting in meetings:
        if meeting.get("chamber") == "House" or not meeting.get("date"):
            continue
        for code in codes_of(meeting):
            host = SITE.get(code)
            if host:
                native[host, meeting["date"][:10]].add(str(meeting["eventId"]))
    for host, site in state.items():
        for url, page in site.get("pages", {}).items():
            if event := page.get("event"):
                page["candidate_events"] = sorted(native[host, selected_date(url, event)] - set(map(str, page.get("events") or [])))
