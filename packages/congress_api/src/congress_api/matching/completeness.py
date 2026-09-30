"""Join public records and fill witness lists in source order.

Congress.gov, House repository, an exclusive GPO print, attached Witness List
PDF, Senate page, then nominees in the meeting title. A shared print cannot
identify one meeting's witnesses. Only documents with URLs count. The matcher
supplies recording coverage for printed hearings independently of text source.
"""

import collections
import html
import re

from congress_api.matching.meetings import is_hearing, meeting_access, meeting_type

FIELDS = ['event_id', 'congress', 'chamber', 'kind', 'access', 'closed', 'date', 'committees', 'title', 'recording', 'text_source', 'witnesses', 'witness_source', 'witness_list_document', 'print_shared_with_other_meetings', 'witness_documents', 'meeting_documents', 'documents_found_elsewhere', 'location', 'related_items', 'rescheduled_to', 'not_held']


WITNESS_FIELDS = ['event_id', 'name', 'position', 'organization', 'source', 'from']


NOMINEE = re.compile(r"(?:nominations? of |, (?:and )?)((?:[A-Z][\w.'\u2019\-]*\.? ){1,5}[A-Z][\w'\u2019\-]+(?:,? (?:Jr|Sr|II|III|IV)\.?)?), of (?:the )?[A-Z][\w. ]+?, to be ([^,;.]+(?:, [^,;.]+)??)(?=[,;.]| and )")


def nominees(title):
    """(name, the office they are nominated to) for each nominee a nomination hearing's title names:
    "Hearings to examine the nominations of Thomas Peter Feddo, of Virginia, to be Assistant Secretary of the
    Treasury for Investment Security, Nazak Nikakhtar, of Maryland, to be Under Secretary of Commerce ..."."""
    return [(name.strip(), office.strip()) for name, office in NOMINEE.findall(re.sub(r"\s+", " ", title))] if re.search(r"\bnominations?\b", title, re.I) else []


def witness_sources(meetings, index, house_witnesses):
    """Select exclusive prints and linked PDFs; do not read or fetch them."""
    prints_of = {e: r["gpo_packages"].split() for e, r in index.items()}
    meetings_of = collections.defaultdict(list)
    for event, prints in prints_of.items():
        for package in prints:
            meetings_of[package].append(event)
    from_house = {row["event_id"] for row in house_witnesses}
    lacking = [m for m in meetings if is_hearing(m) and not m.get("witnesses") and m["eventId"] not in from_house]
    # A print names this meeting's witnesses only if neither side is shared.
    own_print = {m["eventId"]: prints_of[m["eventId"]][0] for m in lacking
                 if len(prints_of[m["eventId"]]) == 1 and len(meetings_of[prints_of[m["eventId"]][0]]) == 1}
    witness_list = {m["eventId"]: d["url"] for m in lacking for d in m.get("meetingDocuments") or []
                    if "witness list" in (d.get("name") or "").lower() and d.get("url")}
    return own_print, witness_list


def build(meetings, index, recorded, house_witnesses, senate_witnesses, documents,
          own_print, witness_list, mods_observations, pdf_observations):
    """Build reports from collected observations; callers own acquisition and storage."""
    prints_of = {e: r["gpo_packages"].split() for e, r in index.items()}
    from_house, from_senate, documents_found = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for source_rows, into in ((house_witnesses, from_house), (senate_witnesses, from_senate), (documents, documents_found)):
        for row in source_rows:
            into[row["event_id"]].append(row)
    from_gpo = {event: mods_observations[package]["people"] for event, package in own_print.items()}
    from_list = {event: pdf_observations[url]["people"] for event, url in witness_list.items()}
    exclusive_prints = set(own_print.values())

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
        elif not listed and is_hearing(m) and (named := nominees(m.get("title") or "")):
            source, count = "meeting title (nominees)", len(named)
            filled += [{"event_id": e, "name": n, "position": f"nominee to be {office}", "organization": "", "source": "meeting title (nominees)", "from": m["_url"]} for n, office in named]
        shared = [p for p in prints_of[e] if p not in exclusive_prints]
        access = meeting_access(m)[0]
        rows.append({"event_id": e, "congress": m["congress"], "chamber": m.get("chamber", ""), "kind": meeting_type(m)[0], "access": access,
                     "closed": "yes" if access == "closed" else "",
                     "date": m["date"][:10], "committees": r["committees"], "title": r["title"].replace("\r\n", "\n").replace("\r", "\n"),
                     ## a printed hearing's recording is matched to its print by the weekly matcher
                     "recording": "yes" if r["youtube_ids"] or r["senate_urls"] or r["other_recordings"] or recorded & set(prints_of[e]) else "", "text_source": r["text_source"],
                     "witnesses": count, "witness_source": source,
                     "witness_list_document": ("yes" if from_list.get(e) else "unparsed" if pdf_observations[witness_list[e]].get("text_present") else "scan") if e in witness_list else "",
                     "print_shared_with_other_meetings": "yes" if not source and shared else "",
                     "witness_documents": sum(1 for d in m.get("witnessDocuments") or [] if d.get("url")), "meeting_documents": sum(1 for d in m.get("meetingDocuments") or [] if d.get("url")),
                     ## on docs.house.gov, or on the Senate committee's page for the hearing
                     "documents_found_elsewhere": len(documents_found[e]),
                     "location": "yes" if m.get("location") else "", "related_items": len(m.get("relatedItems") or []),
                     "rescheduled_to": r["rescheduled_to"], "not_held": r["not_held"]})
    return sorted(rows, key=lambda r: (r["date"], r["event_id"])), sorted(filled, key=lambda w: (w["event_id"], w["name"]))
