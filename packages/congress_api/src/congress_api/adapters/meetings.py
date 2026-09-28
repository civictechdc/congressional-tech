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

from .common import digest, material_records, ref, reported_time, web_url, observed_time


def chamber(value):
    return {"house": "house", "senate": "senate", "joint": "joint", "nochamber": "joint"}.get(str(value).lower(), "unknown")


def meeting_key(row):
    return f"congress.gov|{row['congress']}|{chamber(row.get('chamber'))}|{row['eventId']}"


def meeting_type(row):
    text = ' '.join(str(row.get('type') or '').lower().split())
    for label, kind in (('field hearing', 'field_hearing'), ('business meeting', 'business'),
                        ('hearing', 'hearing'), ('markup', 'markup'), ('briefing', 'briefing')):
        if label in text: return kind, '/type'
    if text in ('', 'meeting'):
        title = ' '.join(str(row.get('title') or '').lower().split())
        # Classify the proceeding named at the beginning, not a later agenda
        # item or a second event following a semicolon.
        prefix = (r'^\W*(?:(?:rescheduled|postponed|cancell?ed)\s*:\s*)?'
                  r'(?:(?:to\s+)?(?:receive|received|hold)\s+)?(?:(?:an?|the)\s+)?'
                  r'(?:(?:open|closed|joint|oversight|legislative|public|full|committee|subcommittee|members?|and)\s+)*')
        hearing = r'hearings?(?=\s*(?:$|[:“"\']|\b(?:on|to|with|of|entitled|titled)\b))'
        for pattern, kind in ((r'field\s+' + hearing, 'field_hearing'),
                              (r'business\s+meeting\b', 'business'), (r'briefings?\b', 'briefing'),
                              (r'mark[\s-]?up\b', 'markup'), (hearing, 'hearing')):
            if re.search(prefix + pattern, title): return kind, '/title'
        # Committee names sometimes precede the business-meeting label.
        # A resolution merely authorizing a later event is not that event.
        if not re.match(r'^(?:to\s+)?(?:consider|resolution)\b', title) and re.search(r'\bbusiness meeting\b', title.split(';', 1)[0]):
            return 'business', '/title'
    if text == 'meeting':
        return 'meeting', '/type'
    return 'unknown', '/type'


def meeting_access(row):
    """Keep explicit native access, otherwise use explicit title phrases only."""
    native = str(row.get('type') or '').lower()
    reported = {value for value in ('open', 'closed') if re.search(r'\b' + value + r'\b', native)}
    if reported:
        return ('partly_closed' if len(reported) == 2 else reported.pop()), '/type'
    title = ' '.join(str(row.get('title') or '').lower().split())
    # Possibility is not a declaration that a closed portion will occur.
    title = re.sub(r'\b(?:possibility of|possibly|may (?:be|go into|hold))\s+(?:an?\s+)?(?:closed|open)\s+(?:session|hearing|meeting)\b', '', title)
    event = r'(?:hearings?|briefings?|(?:business\s+)?meetings?|mark[ -]?up(?:\s+sessions?)?|sessions?|panels?|roundtables?)'
    if re.search(r'\b(?:open\s*(?:and|&|/)\s*closed|closed\s*(?:and|&|/)\s*open)(?=\s*(?:[\])]|' + event + r'\b))', title):
        return 'partly_closed', '/title'
    found, primary = set(), set()
    subsequent = re.search(r'\b(?:followed|preceded)\s+by\b', title)
    for access in ('open', 'closed'):
        marker = r'[\[(]\s*' + access + r'\s*(?:[\])]|(?:session|hearing|briefing)\b|in a closed space\b|-\s*possibility of closing\b)'
        phrase = r'\b' + access + r'\s+(?:joint\s+)?' + event + r'\b'
        declaration = r'\b' + event + r'\s+(?:is\s+|will be\s+)?' + access + r'\b|^\W*' + access + r'\s+to (?:the )?public\b'
        matches = [match for pattern in (marker, phrase, declaration) for match in re.finditer(pattern, title)]
        if matches:
            found.add(access)
            if subsequent is None or any(match.start() < subsequent.start() for match in matches):
                primary.add(access)
    if len(found) == 2:
        return 'partly_closed', '/title'
    # A later closed session alone does not establish access to the main event.
    if primary:
        return primary.pop(), '/title'
    return 'unknown', None


def document_title(row):
    return next((value.strip() for key in ("name", "title", "description", "documentType")
                 if isinstance(value := row.get(key), str) and value.strip()), None)


def event_page(url):
    parsed = urlsplit(url or "")
    return parsed.hostname in ("congress.gov", "www.congress.gov") and parsed.path.startswith("/event/")


def category(row):
    native = str(row.get("documentType") or "").strip().lower()
    # These labels describe the document itself; a title mentioning a bill or
    # witness must not replace the publisher's more specific classification.
    explicit = {
        "hearing: questions for the record": "questions_for_record",
        "committee report": "report", "conference report": "report",
        "hearing: member roster": "hearing_record", "hearing: cover page": "hearing_record",
        "hearing: table of contents": "hearing_record",
    }
    if native in explicit:
        return explicit[native]
    text = f"{row.get('documentType', '')} {row.get('kind', '')} {row.get('name', '')}".lower()
    for needle, value in (("truth in testimony", "disclosure"), ("transcript", "transcript"), ("witness list", "witness_list"), ("statement", "statement"),
                          ("testimony", "statement"), ("biograph", "biography"), ("disclosure", "disclosure"),
                          ("amendment", "amendment"), ("vote", "vote"), ("bill", "bill_text")):
        if needle in text:
            return value
    return "supporting" if native == "support document" else "unknown"


def related_item_identity(family, item, congress):
    """Native nomination/treaty references omit the bill-specific type field."""
    number = item.get("number")
    if number in (None, ""):
        return None
    ic = int(item.get("congress") or congress)
    typ = item.get("type")
    if family == "nominations":
        part = str(item.get("part") or "")
        suffix = f"-{part}" if part and part != "00" else ""
        value = f"PN/{number}" + (f"/{part}" if part else "")
        return ic, f"congress.gov|{ic}|PN|{number}|{part}", "nomination", f"PN{number}{suffix}", value
    if family == "treaties":
        return ic, f"congress.gov|{ic}|treaty|{number}", "treaty", f"Treaty Doc. {ic}-{number}", f"treaty/{number}"
    if not typ:
        return None
    kind = "resolution" if family == "bills" and str(typ).upper().endswith("RES") else "bill" if family == "bills" else "other"
    return ic, f"congress.gov|{ic}|{typ}|{number}", kind, f"{typ} {number}", f"{typ}/{number}"


def records(rows, context):
    for row in rows:
        key = meeting_key(row)
        source = context.source(key, row, row.get("_url"))
        captured_at = observed_time(row.get("_retrieved_at"), context.now)
        if captured_at is not None:
            source = source.model_copy(update={"retrieved_at": captured_at})
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
        kind, type_field = meeting_type(row)
        type_evidence = (FieldEvidence(path='/meeting_type', selected=context.evidence(source, selector=type_field,
                         basis='derived', method='congress_api.meeting_type'), selection_reason='The source title explicitly identifies this meeting type.'),) if type_field == '/title' else ()
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
        access, access_field = meeting_access(row)
        access_evidence = (FieldEvidence(path='/access', selected=context.evidence(source, selector=access_field,
                           basis='derived' if access_field == '/title' else 'reported',
                           method='congress_api.meeting_access' if access_field == '/title' else None),
                           selection_reason='The source title explicitly describes access to the proceeding.' if access_field == '/title'
                                            else 'The source meeting type explicitly describes access to the proceeding.'),) if access_field else ()
        yield MeetingOccurrence(id=context.ids("occurrence", key + "|sitting"), meeting=ref(meeting), status=status,
                                scheduled_start=start, location=loc, access=access, provenance=evidence, field_evidence=access_evidence)
        for i, continuation in enumerate(row.get("continuations") or []):
            ev = context.evidence(source, selector=f"/continuations/{i}")
            try:
                continuation_start = reported_time(continuation.get("continuationDate"))
            except (ValueError, TypeError):
                continuation_start = None
            if continuation_start is None:
                yield DataIssue(id=context.ids("data_issue", key + "|invalid-continuation|" + digest(continuation)),
                                subject=ref(meeting), category="unverified", summary="Continuation date could not be interpreted",
                                detected_at=context.now, provenance=ev)
                continue
            yield MeetingOccurrence(id=context.ids("occurrence", key + "|continuation|" + continuation["continuationDate"]),
                                    meeting=ref(meeting), label="Continuation", scheduled_start=continuation_start, provenance=ev)
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
                                             subject=ref(meeting), role="recording" if recording else "vote_record" if cat == "vote" else cat if cat in ("transcript", "statement", "biography", "disclosure", "amendment", "questions_for_record") else "supporting",
                                             details=RecordingDetails(medium="video", provider=provider) if recording else DocumentDetails(category=cat), identifiers=identifiers)
        for family, items in (row.get("relatedItems") or {}).items():
            for i, item in enumerate(items or []):
                identity = related_item_identity(family, item, congress)
                if identity is None:
                    continue
                ic, ikey, itype, designation, identifier = identity
                ev = context.evidence(source, selector=f"/relatedItems/{family}/{i}")
                item_record = LegislativeItem(id=context.ids("legislative_item", ikey), congress=ic, designation=designation, item_type=itype,
                                             identifiers=(Identifier(scheme="congress.gov:legislation", value=identifier, scope=str(ic)),), provenance=ev)
                yield item_record
                yield MeetingSubject(id=context.ids("meeting_subject", key + "|" + ikey), meeting=ref(meeting), item=ref(item_record), relationship="related", provenance=ev)
