"""Full Congress.gov meeting records, including statuses omitted by inventory reports."""
from collections import Counter
from urllib.parse import urlsplit
import re

from committee_meeting.common import Identifier, Location
from committee_meeting.committees import Committee, CommitteeTerm
from committee_meeting.issues import DataIssue
from committee_meeting.legislation import LegislativeItem, MeetingSubject
from committee_meeting.materials import DocumentDetails, RecordingDetails
from committee_meeting.meetings import Affiliation, Appearance, ConveningCommittee, Meeting, MeetingOccurrence, RecordedName
from committee_meeting.provenance import FieldEvidence

from .common import digest, material_records, ref, reported_time, web_url


def chamber(value):
    return {"house": "house", "senate": "senate", "joint": "joint", "nochamber": "joint"}.get(str(value).lower(), "unknown")


def meeting_key(row):
    return f"congress.gov|{row['congress']}|{chamber(row.get('chamber'))}|{row['eventId']}"


def meeting_type(row):
    text = str(row.get('type') or '').lower()
    for label, kind in (('field hearing', 'field_hearing'), ('business meeting', 'business'),
                        ('hearing', 'hearing'), ('markup', 'markup'), ('briefing', 'briefing')):
        if label in text: return kind, '/type'
    # Some older records use the generic type Meeting and name the business
    # meeting explicitly in the title. Keep that distinction in field evidence.
    if text == 'meeting' and re.search(r'\bbusiness meeting\b', str(row.get('title') or ''), re.I):
        return 'business', '/title'
    return 'unknown', '/type'


def document_title(row):
    return next((value.strip() for key in ("name", "title", "description", "documentType")
                 if isinstance(value := row.get(key), str) and value.strip()), None)


def event_page(url):
    parsed = urlsplit(url or "")
    return parsed.hostname in ("congress.gov", "www.congress.gov") and parsed.path.startswith("/event/")


def category(row):
    text = f"{row.get('documentType', '')} {row.get('kind', '')} {row.get('name', '')}".lower()
    for needle, value in (("truth in testimony", "disclosure"), ("transcript", "transcript"), ("witness list", "witness_list"), ("statement", "statement"),
                          ("testimony", "statement"), ("biograph", "biography"), ("disclosure", "disclosure"),
                          ("amendment", "amendment"), ("vote", "vote"), ("bill", "bill_text")):
        if needle in text:
            return value
    return "unknown"


def records(rows, context):
    for row in rows:
        key = meeting_key(row)
        source = context.source(key, row, row.get("_url"))
        yield source
        evidence = context.evidence(source)
        congress = int(row["congress"])
        comms = []
        seen_committees = set()
        for c in row.get("committees") or []:
            code = c.get("systemCode")
            if not code:
                continue
            if code in seen_committees:
                yield DataIssue(id=context.ids("data_issue", key + "|repeated-committee|" + code), subject=ref(source), category="duplicate",
                                summary="Source repeats the same convening committee", explanation="The selected meeting association is listed once; the raw repeated entries remain in evidence.",
                                detected_at=context.now, provenance=evidence)
                continue
            seen_committees.add(code)
            # A Congress-scoped identity does not claim continuity through reused codes.
            ckey = f"congress.gov|{congress}|{code}"
            committee = Committee(id=context.ids("committee", ckey), label=c.get("name") or code, provenance=evidence)
            term = CommitteeTerm(id=context.ids("committee_term", ckey), committee=ref(committee), congress=congress,
                                 name=c.get("name") or None, chamber=chamber(row.get("chamber")),
                                 identifiers=(Identifier(scheme="congress.gov:committee", value=code, scope=str(congress)),), provenance=evidence)
            yield committee
            yield term
            comms.append(ConveningCommittee(committee=ref(term), role="unknown", provenance=evidence))
        raw_type = str(row.get("type") or "").lower()
        kind, type_field = meeting_type(row)
        type_evidence = (FieldEvidence(path='/meeting_type', selected=context.evidence(source, selector=type_field,
                         basis='derived', method='congress_api.meeting_type'), selection_reason='The source title explicitly identifies a business meeting.'),) if type_field == '/title' else ()
        meeting = Meeting(id=context.ids("meeting", key), title=row.get("title") or None, congress=congress,
                          chamber=chamber(row.get("chamber")), meeting_type=kind, committees=tuple(comms), provenance=evidence,
                          field_evidence=type_evidence,
                          identifiers=(Identifier(scheme="congress.gov:event", value=str(row["eventId"]), scope=f"{congress}/{chamber(row.get('chamber'))}"),))
        yield meeting
        start = None
        try:
            start = reported_time(row.get("date"))
        except (ValueError, TypeError):
            yield DataIssue(id=context.ids("data_issue", key + "|invalid-date"), subject=ref(source), category="unverified",
                            summary="Meeting date could not be interpreted", detected_at=context.now, provenance=evidence)
        location = row.get("location") or {}
        loc = Location(**{k: str(location[k]) for k in ("building", "room", "city", "region", "country") if location.get(k)}) if isinstance(location, dict) and location else None
        status = {"Scheduled": "scheduled", "Rescheduled": "rescheduled", "Postponed": "postponed", "Canceled": "canceled", "Cancelled": "canceled", "Held": "held"}.get(row.get("meetingStatus"), "unknown")
        yield MeetingOccurrence(id=context.ids("occurrence", key + "|sitting"), meeting=ref(meeting), status=status,
                                scheduled_start=start, location=loc, access="closed" if "closed" in raw_type else "unknown", provenance=evidence)
        witnesses = row.get("witnesses") or []
        names = Counter(w.get("name") for w in witnesses)
        for i, w in enumerate(witnesses):
            name = w.get("name")
            if not name or not name.strip():
                yield DataIssue(id=context.ids("data_issue", key + "|unreadable-witness|" + digest(w)), subject=ref(meeting),
                                category="unverified", summary="A listed witness has no usable name", detected_at=context.now,
                                provenance=context.evidence(source, selector=f"/witnesses/{i}"))
                continue
            wkey = key + "|witness|" + name
            if names[name] > 1:
                wkey += "|" + digest(w)
                yield DataIssue(id=context.ids("data_issue", key + "|ambiguous-witness|" + name), subject=ref(meeting),
                                category="duplicate", summary="Same-name witness rows need identity review", detected_at=context.now, provenance=evidence)
            yield Appearance(id=context.ids("appearance", wkey), meeting=ref(meeting), name=RecordedName(display=name), roles=("witness",),
                             participation="listed", affiliation=Affiliation(organization_name=w.get("organization") or None, position=w.get("position") or None),
                             provenance=context.evidence(source, selector=f"/witnesses/{i}"))
        for group in ("meetingDocuments", "witnessDocuments", "videos"):
            for i, d in enumerate(row.get(group) or []):
                url = web_url(d.get("url"))
                dkey = key + "|" + group + "|" + (url or digest(d))
                ev = context.evidence(source, selector=f"/{group}/{i}")
                cat = category(d)
                recording = group == "videos"
                # An event landing page is not a second recording. Its exact
                # URL remains in the retained native source record.
                if recording and event_page(url): continue
                provider = None
                identifiers = ()
                if recording and url:
                    from congress_api.gpo.match import VIDEO_ID
                    match = VIDEO_ID.search(url)
                    if match:
                        provider = "youtube"
                        dkey = "youtube|" + match.group(1)
                        identifiers = (Identifier(scheme="youtube.video", value=match.group(1)),)
                    else:
                        from congress_api.senate.isvp import parse_player_url
                        player = parse_player_url(url)
                        if player:
                            provider = "senate"
                            dkey = "senate|" + "|".join(player)
                            identifiers = (Identifier(scheme="senate.filename", value=player[1], scope=player[0]),)
                yield from material_records(context, ev, dkey, title=document_title(d), urls=[url] if url else [],
                                             subject=ref(meeting), role="recording" if recording else cat if cat in ("transcript", "statement", "biography", "disclosure", "amendment") else "supporting",
                                             details=RecordingDetails(medium="video", provider=provider) if recording else DocumentDetails(category=cat), identifiers=identifiers)
        for family, items in (row.get("relatedItems") or {}).items():
            for i, item in enumerate(items or []):
                num, typ = item.get("number"), item.get("type")
                if not num or not typ:
                    continue
                ic = int(item.get("congress") or congress)
                ikey = f"congress.gov|{ic}|{typ}|{num}"
                ev = context.evidence(source, selector=f"/relatedItems/{family}/{i}")
                itype = "bill" if family == "bills" else "nomination" if family == "nominations" else "treaty" if family == "treaties" else "other"
                item_record = LegislativeItem(id=context.ids("legislative_item", ikey), congress=ic, designation=f"{typ} {num}", item_type=itype,
                                             identifiers=(Identifier(scheme="congress.gov:legislation", value=f"{typ}/{num}", scope=str(ic)),), provenance=ev)
                yield item_record
                yield MeetingSubject(id=context.ids("meeting_subject", key + "|" + ikey), meeting=ref(meeting), item=ref(item_record), relationship="related", provenance=ev)
