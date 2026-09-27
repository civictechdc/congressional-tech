"""Join public records and fill witness lists in source order.

Congress.gov, House repository, an exclusive GPO print, attached Witness List
PDF, Senate page, then nominees in the meeting title. A shared print cannot
identify one meeting's witnesses. Only documents with URLs count. The matcher
supplies recording coverage for printed hearings independently of text source.
"""
import collections, html, re
from congress_api.inventory.common import CLOSED, kind
from congress_api.inventory.witness_lists import GOVINFO_CONTENT, get_witnesses

FIELDS = ['event_id', 'congress', 'chamber', 'kind', 'closed', 'date', 'committees', 'title', 'recording', 'text_source', 'witnesses', 'witness_source', 'witness_list_document', 'print_shared_with_other_meetings', 'witness_documents', 'meeting_documents', 'documents_found_elsewhere', 'location', 'related_items', 'rescheduled_to', 'not_held']
WITNESS_FIELDS = ['event_id', 'name', 'position', 'organization', 'source', 'from']

NOMINEE = re.compile(r"(?:nominations? of |, (?:and )?)((?:[A-Z][\w.'\u2019\-]*\.? ){1,5}[A-Z][\w'\u2019\-]+(?:,? (?:Jr|Sr|II|III|IV)\.?)?), of (?:the )?[A-Z][\w. ]+?, to be ([^,;.]+(?:, [^,;.]+)??)(?=[,;.]| and )")


def nominees(title):
    """(name, the office they are nominated to) for each nominee a nomination hearing's title names:
    "Hearings to examine the nominations of Thomas Peter Feddo, of Virginia, to be Assistant Secretary of the
    Treasury for Investment Security, Nazak Nikakhtar, of Maryland, to be Under Secretary of Commerce ..."."""
    return [(name.strip(), office.strip()) for name, office in NOMINEE.findall(re.sub(r"\s+", " ", title))] if re.search(r"\bnominations?\b", title, re.I) else []


def build(meetings, index, recorded, house_witnesses, senate_witnesses, documents, gpo, state, today, offline, seed_cache):
    prints_of = {e: r["gpo_packages"].split() for e, r in index.items()}
    meetings_of = collections.defaultdict(list)
    for e, prints in prints_of.items():
        for p in prints:
            meetings_of[p].append(e)
    from_house, from_senate, documents_found = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for rows, into in ((house_witnesses, from_house), (senate_witnesses, from_senate), (documents, documents_found)):
        for row in rows:
            into[row["event_id"]].append(row)
    lacking = [m for m in meetings if kind(m) == "hearing" and not m.get("witnesses") and not from_house[m["eventId"]]]
    ## a print that is one meeting's only print, and matched to no other meeting, names that meeting's witnesses
    own_print = {m["eventId"]: prints_of[m["eventId"]][0] for m in lacking if len(prints_of[m["eventId"]]) == 1 and len(meetings_of[prints_of[m["eventId"]][0]]) == 1}
    witness_list = {m["eventId"]: d["url"] for m in lacking for d in m.get("meetingDocuments") or [] if "witness list" in (d.get("name") or "").lower() and d.get("url")}
    from_gpo, from_list = {}, {}
    for e, package in own_print.items():
        row = gpo[package]
        from_gpo[e] = get_witnesses(package, f"{GOVINFO_CONTENT}/metadata/pkg/{package}/mods.xml", state.setdefault("mods", {}),
            row["last_modified"], row["held_date"], today, offline, seed_cache, package=True)
    by_event = {m["eventId"]: m for m in meetings}
    for e, url in witness_list.items():
        m = by_event[e]
        from_list[e] = get_witnesses(url, url, state.setdefault("witness_lists", {}), m.get("updateDate", ""),
            m["date"][:10], today, offline, seed_cache)

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
            filled += [{"event_id": e, "name": p["name"], "position": p["position"], "organization": html.unescape(p["organization"]), "source": "gpo", "from": own_print[e]} for p in from_gpo[e]]
        elif not listed and from_list.get(e):
            source, count = "witness list document", len(from_list[e])
            filled += [{"event_id": e, **w, "source": "witness list document", "from": witness_list[e]} for w in from_list[e]]
        elif not listed and from_senate[e]:
            source, count = "senate committee page", len(from_senate[e])
            filled += [{"event_id": e, "name": w["name"], "position": w["position"], "organization": w["organization"], "source": "senate committee page", "from": w["page"]} for w in from_senate[e]]
        elif not listed and kind(m) == "hearing" and nominees(m.get("title") or ""):
            named = nominees(m["title"])
            source, count = "meeting title (nominees)", len(named)
            filled += [{"event_id": e, "name": n, "position": f"nominee to be {office}", "organization": "", "source": "meeting title (nominees)", "from": m["_url"]} for n, office in named]
        shared = [p for p in prints_of[e] if p not in own_print.values()]
        rows.append({"event_id": e, "congress": m["congress"], "chamber": m.get("chamber", ""), "kind": kind(m), "closed": "yes" if m.get("type", "").startswith("Closed") or CLOSED.search(m.get("title") or "") else "",
                     "date": m["date"][:10], "committees": r["committees"], "title": r["title"].replace("\r\n", "\n").replace("\r", "\n"),
                     ## a printed hearing's recording is matched to its print by the weekly matcher
                     "recording": "yes" if r["youtube_ids"] or r["senate_urls"] or r["other_recordings"] or recorded & set(prints_of[e]) else "", "text_source": r["text_source"],
                     "witnesses": count, "witness_source": source,
                     "witness_list_document": ("yes" if from_list.get(e) else "unparsed" if state["witness_lists"][witness_list[e]].get("text_present") else "scan") if e in witness_list else "",
                     "print_shared_with_other_meetings": "yes" if not source and shared else "",
                     "witness_documents": sum(1 for d in m.get("witnessDocuments") or [] if d.get("url")), "meeting_documents": sum(1 for d in m.get("meetingDocuments") or [] if d.get("url")),
                     ## on docs.house.gov, or on the Senate committee's page for the hearing
                     "documents_found_elsewhere": len(documents_found[e]),
                     "location": "yes" if m.get("location") else "", "related_items": len(m.get("relatedItems") or []),
                     "rescheduled_to": r["rescheduled_to"], "not_held": r["not_held"]})
    return sorted(rows, key=lambda r: (r["date"], r["event_id"])), sorted(filled, key=lambda w: (w["event_id"], w["name"]))
