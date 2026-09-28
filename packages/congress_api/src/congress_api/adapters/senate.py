"""Adapt retained Senate committee pages without fetching or rematching them."""
from collections import Counter, defaultdict
from datetime import date, datetime
import re
from urllib.parse import urlsplit

from committee_meeting.assessments import Assessment
from committee_meeting.common import Identifier
from committee_meeting.issues import DataIssue
from committee_meeting.materials import DocumentDetails, MaterialLink
from committee_meeting.meetings import Affiliation, Appearance, RecordedName, ConveningCommittee, Meeting, MeetingOccurrence
from committee_meeting.provenance import AlternativeValue, FieldEvidence, Method

from congress_api.senate.pages import OWN, SITE, attachment_page
from congress_api.senate.corrections import DATE_CORRECTIONS, selected_date

from .common import digest, material_records, ref, web_url, reported_time
from .meetings import category, meeting_type, meeting_access


MATCH_METHOD = Method(name="senate.records.match_pages", version="1")


def _timestamp(value, now):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed <= now else None
    except (AttributeError, TypeError, ValueError):
        return None


def _live_receipt(page, url, now):
    """Legacy checked dates are scheduling state, not retrieval evidence."""
    check = page.get("observation_check") or page.get("last_check") or {}
    if not isinstance(check, dict) or check.get("mode") != "live":
        return None
    for receipt in reversed(check.get("receipts") or []):
        if not isinstance(receipt, dict) or receipt.get("url") != url:
            continue
        expected = {200: "retrieved", 404: "not_found"}.get(receipt.get("status_code"))
        if expected is None or receipt.get("outcome") != expected:
            continue
        completed = receipt.get("completed_at")
        if not isinstance(completed, str):
            continue
        try:
            observed = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            if observed.tzinfo is not None and observed <= now:
                return observed, expected
        except (KeyError, TypeError, ValueError):
            pass
    return None



def official_events(state):
    """Validated source-owned events for metadata discovery and offline admission."""
    codes = {host: code for code, host in SITE.items()}
    for host, site in sorted(state.items()):
        if host not in codes:
            continue
        for url, page in sorted((site.get("pages") or {}).items()):
            event = page.get("event")
            if page.get("absent") or page.get("status") == "error" or not isinstance(event, dict):
                continue
            if not event.get("title") or event.get("url") != url or (urlsplit(url).hostname or "").removeprefix("www.") != host:
                continue
            try:
                day = date.fromisoformat(selected_date(url, event))
            except (ValueError, TypeError, KeyError):
                continue
            # Congresses since 1935 begin January 3. This collector's explicit
            # historical boundary is much later; dates before that stay raw.
            if day.year < 1935:
                continue
            year = day.year - (1 if (day.month, day.day) < (1, 3) else 0)
            congress = (year - 1789) // 2 + 1
            yield {"host": host, "url": url, "page": page, "event": event,
                   "congress": congress, "committee_code": codes[host]}

def records(state, context, *, meetings, committee_terms=None, meeting_records=None):
    """Yield every page and document, with only saved, unambiguous associations.

    Lookup keys are (Congress, chamber, eventId). Senate state retains only the
    eventId, so a repeated eventId across those keys cannot establish a link.
    The producer's page match is derived evidence; a listing date is not used.
    """
    committee_terms, meeting_records = committee_terms or {}, meeting_records or {}
    events = {event["url"]: event for event in official_events(state)}
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        if meeting.kind != "meeting":
            raise ValueError("Senate meeting lookup must contain meeting references")
        by_event[str(event)].append(meeting)
    for host, site in sorted(state.items()):
        listing_check = site.get("last_check") or {}
        if isinstance(listing_check, dict) and listing_check.get("mode") == "live":
            listing_source = context.source(f"senate-listing-check|{host}", {"host": host, "last_check": listing_check})
            yield listing_source
            if listing_check.get("outcome") == "error":
                yield DataIssue(
                    id=context.ids("data_issue", listing_source.id + "|failed-listing-refresh"), subject=ref(listing_source), category="unverified",
                    summary="The latest Senate listing refresh failed.", explanation="Previously retained page observations remain available.",
                    detected_at=context.now, last_checked_at=_timestamp(listing_check.get("completed_at"), context.now),
                    provenance=context.evidence(listing_source, selector="/last_check"),
                )
        pages = site.get("pages") or {}
        # Match the producer's exclusion of files carried by more than five
        # listed pages. Keep these materials, but do not call them meeting files.
        shared = Counter(
            document[2]
            for url, page in pages.items() if url in (site.get("listings") or {})
            for document in page.get("documents") or []
            if isinstance(document, (list, tuple)) and len(document) == 3 and isinstance(document[2], str)
        )
        for url, page in sorted(pages.items()):
            key = f"senate-page|{host}|{url}"
            source = context.source(key, page, url)
            live = _live_receipt(page, url, context.now)
            check = page.get("last_check") or {}
            failed = isinstance(check, dict) and check.get("mode") == "live" and check.get("outcome") == "error"
            previous_retrieval = _timestamp(page.get("retrieved_at"), context.now) if isinstance(check, dict) and check.get("mode") == "live" else None
            if live or previous_retrieval:
                source = source.model_copy(update={"retrieved_at": live[0] if live else previous_retrieval})
            yield source
            correction = DATE_CORRECTIONS.get(url)
            correction_evidence = None
            if correction:
                correction_source = context.source("senate-date-correction|" + url, correction, correction["source_url"])
                yield correction_source
                correction_evidence = context.evidence(correction_source, basis="curated", selector="/date")

            def issue(code, category, summary, *, explanation=None, subject=None, selector=None):
                return DataIssue(
                    id=context.ids("data_issue", key + "|" + code), subject=subject or ref(source),
                    category=category, summary=summary, explanation=explanation,
                    detected_at=context.now, provenance=context.evidence(source, selector=selector),
                )

            suspect_pdf = urlsplit(url).path.lower().endswith(".pdf") and not page.get("title") and any(
                isinstance(line, str) and ("\ufffd" in line[:4096] or any(ord(character) < 32 and character not in "\t\r\n" for character in line[:4096]))
                for line in (page.get("lines") or [])[:20]
            )
            if suspect_pdf:
                yield DataIssue(
                    id=context.ids("data_issue", key + "|possible-binary-source"), subject=ref(source), category="unverified",
                    summary="This retained page may contain binary document data decoded as text.",
                    explanation="The URL ends in .pdf, the title is empty, and retained lines contain replacement or control characters. Original response bytes and MIME type are not retained, so the input format remains unverified.",
                    detected_at=context.now,
                    provenance=context.evidence(source, basis="inferred", method=Method(name="congress_api.adapters.senate.input-format", version="1"), selector="/lines"),
                )
            if failed:
                yield DataIssue(
                    id=context.ids("data_issue", key + "|failed-refresh"), subject=ref(source), category="unverified",
                    summary="The latest Senate page refresh failed.", explanation="The previous usable source result is retained; this failure does not establish absence.",
                    detected_at=context.now, last_checked_at=_timestamp(check.get("completed_at"), context.now),
                    provenance=context.evidence(source, selector="/last_check"),
                )
            if not live and not previous_retrieval:
                yield issue("unverified-retrieval", "unverified", "This page has no retained live retrieval receipt.",
                            explanation="The saved checked day may be a cache import or scheduling date. It does not establish when the source was observed.")
            matched, seen_events = {}, set()
            for index, event in enumerate(page.get("events") or []):
                if str(event) in seen_events:
                    continue
                seen_events.add(str(event))
                candidates = by_event.get(str(event), [])
                if len(candidates) == 1:
                    meeting = candidates[0]
                    details = (page.get("match_details") or {}).get(str(event))
                    if details and details.get("method") == "senate.records.match_identifiers":
                        match_evidence = context.evidence(source, basis="derived", method=Method(name=details["method"], version=details["version"]), selector=f"/match_details/{event}")
                    else:
                        match_evidence = context.evidence(source, basis="derived", method=MATCH_METHOD, selector=f"/events/{index}")
                    if correction_evidence:
                        match_evidence = match_evidence.model_copy(update={"citations": match_evidence.citations + correction_evidence.citations})
                    matched[meeting.id] = (meeting, match_evidence)
                else:
                    yield issue(f"unresolved-event|{event}", "unlinked", "A saved page association has no unique meeting reference.",
                                explanation=f"Event {event} resolves to {len(candidates)} entries in the supplied meeting lookup.", selector=f"/events/{index}")
            official = events.get(url)
            event = official["event"] if official else None
            if official and not matched and not seen_events and not page.get("candidate_events"):
                # The official URL is the provider identity. Congress numbers
                # organize the proceeding; no Congress.gov event ID is invented.
                term = committee_terms.get((official["congress"], official["committee_code"]))
                event_evidence = context.evidence(source, selector="/event")
                if term is None:
                    yield issue("unresolved-event-committee", "unlinked", "The official event has no retained committee term.",
                                explanation=f"Committee {official['committee_code']} in Congress {official['congress']} is missing.", selector="/event")
                else:
                    kind = "roundtable" if event.get("type") == "Roundtable" else meeting_type(event)[0]
                    native_key = f"senate.committee|{url}"
                    meeting = Meeting(id=context.ids("meeting", native_key), title=event["title"], congress=official["congress"],
                                      chamber="joint" if official["committee_code"].startswith("j") else "senate", meeting_type=kind,
                                      committees=(ConveningCommittee(committee=term, role="host", provenance=event_evidence),),
                                      identifiers=(Identifier(scheme="senate.committee:page", value=url),), provenance=event_evidence)
                    yield meeting
                    occurrence_evidence = event_evidence
                    date_fields = ()
                    if correction:
                        occurrence_evidence = correction_evidence
                        date_fields = (FieldEvidence(path="/scheduled_start", selected=occurrence_evidence,
                                      alternatives=(AlternativeValue(value=reported_time(event["date"]).model_dump(mode="json"), provenance=event_evidence),),
                                      selection_reason=correction["reason"]),)
                    access, _ = meeting_access(event)
                    yield MeetingOccurrence(id=context.ids("occurrence", native_key + "|sitting"), meeting=ref(meeting),
                                            scheduled_start=reported_time(selected_date(url, event)), access=access,
                                            provenance=occurrence_evidence, field_evidence=date_fields)
                    matched[meeting.id] = (ref(meeting), event_evidence)
            elif event:
                for meeting_ref, match_evidence in matched.values():
                    original = meeting_records.get(meeting_ref.id)
                    if original is None:
                        continue
                    identifier = Identifier(scheme="senate.committee:page", value=url)
                    identifiers = original.identifiers if identifier in original.identifiers else original.identifiers + (identifier,)
                    event_evidence = context.evidence(source, selector="/event")
                    evidence = original.provenance.model_copy(update={"citations": original.provenance.citations + tuple(citation for citation in event_evidence.citations if citation not in original.provenance.citations)})
                    fields = original.field_evidence
                    kind = original.meeting_type
                    if event.get("type") == "Roundtable" and kind != "roundtable":
                        selected = context.evidence(source, selector="/event/type")
                        field = FieldEvidence(path="/meeting_type", selected=selected,
                                              alternatives=(AlternativeValue(value=kind, provenance=original.provenance),),
                                              selection_reason="The convening committee explicitly describes its proceeding as a Roundtable.")
                        fields = tuple(field for field in fields if field.path != "/meeting_type") + (field,)
                        kind = "roundtable"
                    yield original.model_copy(update={"meeting_type": kind, "field_evidence": fields, "identifiers": identifiers, "provenance": evidence})
            if not matched and page.get("candidate_events"):
                yield issue("possible-native-event", "unlinked", "The official event may already have a Congress.gov meeting.",
                            explanation="The same committee has a retained meeting on this date, but the page match is not established; a duplicate meeting was not created.", selector="/candidate_events")
            if not matched:
                yield issue("unlinked-page", "unlinked", "This retained committee page has no supported meeting association.",
                            explanation="Documents remain discoverable. Witness rows remain in the source payload until their meeting is established.")

            seen_documents = set()
            for index, document in enumerate(page.get("documents") or []):
                selector = f"/documents/{index}"
                if not isinstance(document, (list, tuple)) or len(document) != 3 or not all(isinstance(value, str) for value in document):
                    yield issue(f"invalid-document|{index}", "unverified", "A retained document row could not be interpreted.", selector=selector)
                    continue
                document_hash = digest(document)
                if document_hash in seen_documents:
                    continue  # Identical source rows do not add another work.
                seen_documents.add(document_hash)
                kind, title, document_url = document
                document_key = key + "|document|" + document_hash
                cat = "questions_for_record" if kind == "questions for the record" else category({"kind": kind, "name": title})
                ev = context.evidence(source, selector=selector)
                resolved = [entry.get("url") for entry in (page.get("attachments") or {}).get(document_url, []) if isinstance(entry, dict) and web_url(entry.get("url"))]
                urls = [document_url, *resolved]
                built = material_records(context, ev, document_key, title=title, urls=urls, details=DocumentDetails(category=cat))
                if attachment_page(document_url):
                    built = [item.model_copy(update={"locations": tuple(location.model_copy(update={"role": "landing"}) for location in item.locations)})
                             if item.kind == "representation" and item.locations[0].url == document_url else item for item in built]
                yield from built
                material, version = built[:2]
                if not web_url(document_url):
                    yield issue("invalid-url|" + document_hash, "unverified", "A reported document URL is not an absolute HTTP(S) URL.",
                                subject=ref(material), selector=selector)
                is_shared = isinstance(document_url, str) and shared[document_url] > OWN
                if not matched or is_shared:
                    yield issue("unlinked-document|" + document_hash, "unlinked", "This document has no supported meeting association.",
                                explanation="The file appears on more than five pages and may be site-wide content." if is_shared else "The containing page has no unambiguous saved meeting match.",
                                subject=ref(material), selector=selector)
                else:
                    for meeting, match_evidence in matched.values():
                        yield MaterialLink(
                            id=context.ids("material_link", document_key + "|" + meeting.id),
                            material=ref(material), version=ref(version), subject=meeting,
                            role=cat if cat in ("transcript", "statement", "biography", "disclosure", "questions_for_record") else "supporting",
                            provenance=match_evidence,
                        )

            witness_counts = Counter(digest(w) for w in page.get("witnesses") or [])
            seen_witnesses = Counter()
            for index, witness in enumerate(page.get("witnesses") or []):
                if not matched:
                    break
                selector = f"/witnesses/{index}"
                if not isinstance(witness, dict) or not isinstance(witness.get("name"), str) or not witness["name"].strip():
                    yield issue(f"invalid-witness|{index}", "unverified", "A listed witness has no usable name.", selector=selector)
                    continue
                witness_key = digest(witness)
                seen_witnesses[witness_key] += 1
                if witness_counts[witness_key] > 1:
                    witness_key += f"|duplicate|{seen_witnesses[witness_key]}"
                for meeting, match_evidence in matched.values():
                    # Each observed row remains local to its page and meeting;
                    # equal names do not establish a shared person identity.
                    yield Appearance(
                        id=context.ids("appearance", key + "|witness|" + witness_key + "|" + meeting.id),
                        meeting=meeting, name=RecordedName(display=witness["name"]),
                        roles=("witness", "nominee") if re.match(r"^\s*nominee\b", witness.get("position") or "", re.I) else ("witness",), participation="listed",
                        affiliation=Affiliation(organization_name=witness.get("organization") or None, position=witness.get("position") or None),
                        provenance=match_evidence.model_copy(update={"citations": match_evidence.citations + context.evidence(source, selector=selector).citations}),
                    )
            if failed:
                for meeting, match_evidence in matched.values():
                    yield Assessment(
                        id=context.ids("assessment", key + "|reachability|" + meeting.id), subject=meeting,
                        aspect="reachability", status="error", evaluated_at=context.now,
                        observed_at=_timestamp(check.get("completed_at"), context.now), provider=context.provider, scope=url,
                        explanation="The latest refresh failed. Previously retained documents and witnesses remain historical observations.",
                        provenance=match_evidence.model_copy(update={"citations": match_evidence.citations + context.evidence(source, selector="/last_check").citations}),
                    )
            elif page.get("absent"):
                for meeting, match_evidence in matched.values():
                    confirmed = live is not None and live[1] == "not_found"
                    yield Assessment(
                        id=context.ids("assessment", key + "|reachability|" + meeting.id), subject=meeting,
                        aspect="reachability", status="not_found" if confirmed else "unknown", evaluated_at=context.now,
                        observed_at=live[0] if confirmed else None, provider=context.provider, scope=url,
                        explanation="A retained live receipt reports HTTP 404 for this page." if confirmed else "The saved absence has no live receipt; its checked day alone does not establish an observation.",
                        provenance=match_evidence,
                    )
