"""Adapt retained Senate committee pages without fetching or rematching them."""

from collections import Counter, defaultdict
from datetime import date
from urllib.parse import urlsplit

from committee_meeting.assessments import Assessment
from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.materials import DocumentDetails, MaterialLink, RecordingDetails
from committee_meeting.meetings import (
    Affiliation,
    Appearance,
    ConveningCommittee,
    Meeting,
    MeetingOccurrence,
    RecordedName,
)
from committee_meeting.provenance import AlternativeValue, FieldEvidence, Method

from congress_api.adapters.common import digest, material_records, observed_time, ref, reported_time, web_url, witness_roles
from congress_api.adapters.meetings import category
from congress_api.adapters.recordings import recording_reference
from congress_api.matching.meetings import meeting_access, meeting_type
from congress_api.matching.senate_corrections import DATE_CORRECTIONS, selected_date
from congress_api.models.senate import SenatePage, SenateSite
from congress_api.parsers.senate_page import DATE, OWN, SITE, attachment_page, written_day

MATCH_METHOD = Method(name="senate.records.match_pages", version="1")


def _attachment_aliases(page):
    """Group only an explicit landing-page resolution to one listed direct file.

    Keep the direct document's identity. Equal names or URL basenames do not
    establish this relation; the retained attachment response must report it.
    """
    documents, aliases, skipped = page.get("documents") or [], defaultdict(list), set()
    valid = [(index, document) for index, document in enumerate(documents)
             if isinstance(document, (list, tuple)) and len(document) == 3 and all(isinstance(value, str) for value in document)]
    metadata = page.get("document_metadata") or {}
    for index, document in valid:
        kind, _, url = document
        if not attachment_page(url):
            continue
        files = {entry.get("url") for entry in (page.get("attachments") or {}).get(url, []) if isinstance(entry, dict) and web_url(entry.get("url"))}
        if len(files) != 1:
            continue
        direct_url = next(iter(files))
        owners = set(metadata.get(url, {}).get("witness_indexes") or [])
        candidates = [(candidate, other) for candidate, other in valid if other[2] == direct_url and other[0] == kind
                      and not attachment_page(other[2]) and set(metadata.get(other[2], {}).get("witness_indexes") or []) == owners]
        if len(candidates) == 1:
            aliases[candidates[0][0]].append((index, document))
            skipped.add(index)
    return aliases, skipped


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
        observed = observed_time(receipt.get("completed_at"), now)
        if observed is not None:
            return observed, expected
    return None


def _site_data(site):
    if isinstance(site, SenateSite):
        return site.source_dict()
    pages = site.get("pages") or {}
    if any(isinstance(page, SenatePage) for page in pages.values()):
        return {**site, "pages": {url: page.source_dict() if isinstance(page, SenatePage) else page for url, page in pages.items()}}
    return site


def official_events(state):
    """Validated source-owned events for metadata discovery and offline admission."""
    codes = {host: code for code, host in SITE.items()}
    for host, site in sorted(state.items()):
        site = _site_data(site)
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


def records(state, context, *, meetings, committee_terms=None, meeting_records=None, occurrence_records=None):
    """Normalize native SenatePage/SenateSite models or legacy saved dictionaries.

    Yield every page and document, with only saved, unambiguous associations.

    Lookup keys are (Congress, chamber, eventId). Senate state retains only the
    eventId, so a repeated eventId across those keys cannot establish a link.
    The producer's page match is derived evidence; a listing date is not used.
    """
    committee_terms, meeting_records = committee_terms or {}, meeting_records or {}
    occurrences = dict(occurrence_records or {})
    events = {event["url"]: event for event in official_events(state)}
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        if meeting.kind != "meeting":
            raise ValueError("Senate meeting lookup must contain meeting references")
        by_event[str(event)].append(meeting)
    for host, site in sorted(state.items()):
        site = _site_data(site)
        listing_check = site.get("last_check") or {}
        if (isinstance(listing_check, dict) and listing_check.get("mode") == "live") or site.get("source_bodies"):
            payload = {"host": host, "last_check": listing_check}
            if site.get("source_bodies"):
                payload["source_bodies"] = site["source_bodies"]
            listing_source = context.source(f"senate-listing-check|{host}", payload)
            yield listing_source
            if isinstance(listing_check, dict) and listing_check.get("outcome") == "error":
                yield DataIssue(
                    id=context.ids("data_issue", listing_source.id + "|failed-listing-refresh"), subject=ref(listing_source), category="unverified",
                    summary="The latest Senate listing refresh failed.", explanation="Previously retained page observations remain available.",
                    detected_at=context.now, last_checked_at=observed_time(listing_check.get("completed_at"), context.now),
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
        shared_media = Counter()
        for saved_page in pages.values():
            references = [recording_reference((media.get("attributes") or {}).get("src") or "")
                          for media in (saved_page.get("page_metadata") or {}).get("media") or []]
            shared_media.update({reference[0] for reference in references if reference})
        for url, page in sorted(pages.items()):
            key = f"senate-page|{host}|{url}"
            source = context.source(key, page, url)
            live = _live_receipt(page, url, context.now)
            check = page.get("last_check") or {}
            failed = isinstance(check, dict) and check.get("mode") == "live" and check.get("outcome") == "error"
            previous_retrieval = observed_time(page.get("retrieved_at"), context.now) if isinstance(check, dict) and check.get("mode") == "live" else None
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
                    detected_at=context.now, last_checked_at=observed_time(check.get("completed_at"), context.now),
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
                    if details and details.get("method") in ("senate.records.match_identifiers", "senate.records.match_pages"):
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
                    kind = meeting_type(event)[0]
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

            # Only explicit publisher access labels and the event's own date
            # can fill an existing sitting. Generic hearing types prove neither.
            labels = {item.get("text", "").strip(" :").casefold(): index
                      for index, item in enumerate((page.get("page_metadata") or {}).get("heading_prefixes") or [])}
            access_labels = {"open": "open", "closed": "closed", "open/closed": "partly_closed", "open and closed": "partly_closed"}
            stated = {access_labels[label] for label in labels if label in access_labels}
            dated_lines = [(index, written_day(found)) for index, line in enumerate(page.get("lines") or [])
                           if line.strip().casefold().startswith("date:") and (found := DATE.search(line))]
            page_days = {date.fromisoformat(selected_date(url, event))} if event else {day for _, day in dated_lines if day}
            if len(stated) == 1 and len(page_days) == 1:
                access = next(iter(stated))
                label_index = next(index for label, index in labels.items() if access_labels.get(label) == access)
                label_evidence = context.evidence(source, selector=f"/page_metadata/heading_prefixes/{label_index}")
                date_evidence = context.evidence(source, selector="/event/date" if event else f"/lines/{dated_lines[0][0]}")
                for meeting, match_evidence in matched.values():
                    sittings = [item for item in occurrences.values() if item.meeting.id == meeting.id
                                and item.scheduled_start and item.scheduled_start.date in page_days]
                    if len(sittings) != 1:
                        continue
                    original = sittings[0]
                    selected = label_evidence.model_copy(update={"citations": label_evidence.citations + date_evidence.citations + match_evidence.citations})
                    field = next((field for field in original.field_evidence if field.path == "/access"), None)
                    previous = field.selected if field else original.provenance
                    if original.access == "unknown":
                        field = FieldEvidence(path="/access", selected=selected,
                                              alternatives=field.alternatives if field else (),
                                              selection_reason="The matched committee page explicitly labels access for this dated sitting.")
                        updated = original.model_copy(update={"access": access})
                    elif original.access != access:
                        alternative = AlternativeValue(value=access, provenance=selected)
                        field = FieldEvidence(path="/access", selected=previous,
                                              alternatives=(field.alternatives if field else ()) + (alternative,),
                                              selection_reason="Keep the existing explicit access value; the committee page provides conflicting evidence.")
                        updated = original
                    else:
                        continue
                    updated = updated.model_copy(update={"field_evidence": tuple(f for f in original.field_evidence if f.path != "/access") + (field,)})
                    occurrences[updated.id] = updated
                    yield updated

            for message_index, message in enumerate((page.get("page_metadata") or {}).get("video_messages") or []):
                if message.get("text", "").strip().casefold() != "there is no video broadcast for this event.":
                    continue
                notice_evidence = context.evidence(source, selector=f"/page_metadata/video_messages/{message_index}")
                for meeting, match_evidence in matched.values():
                    yield Assessment(id=context.ids("assessment", key + "|no-video-broadcast|" + meeting.id),
                        subject=meeting, aspect="recording", status="not_applicable", evaluated_at=context.now,
                        observed_at=live[0] if live else previous_retrieval, provider=context.provider,
                        scope="Video broadcast by the committee for the event on " + url,
                        explanation=message["text"],
                        provenance=notice_evidence.model_copy(update={"citations": notice_evidence.citations + match_evidence.citations}))

            # Embedded publishers identify recordings more precisely than a
            # same-committee/day archive probe. Keep the native URL and selector.
            seen_media = set()
            for media_index, media in enumerate((page.get("page_metadata") or {}).get("media") or []):
                attributes = media.get("attributes") or {}
                recording = recording_reference(attributes.get("src") or "")
                if recording is None:
                    continue
                recording_key, recording_url, provider, identifiers = recording
                if not provider and media.get("tag") not in ("audio", "video", "source"):
                    continue  # An arbitrary iframe can be a map or another widget.
                if recording_key in seen_media:
                    continue
                seen_media.add(recording_key)
                ev = context.evidence(source, selector=f"/page_metadata/media/{media_index}")
                built = material_records(context, ev, recording_key, title=attributes.get("title"), urls=[recording_url],
                    details=RecordingDetails(medium="audio" if media.get("tag") == "audio" else "unknown" if media.get("tag") == "source" else "video", provider=provider), identifiers=identifiers)
                yield from built
                material, version = built[:2]
                for meeting, match_evidence in (matched.values() if shared_media[recording_key] <= OWN else ()):
                    yield MaterialLink(id=context.ids("material_link", recording_key + "|" + meeting.id),
                        material=ref(material), version=ref(version), subject=meeting, role="recording",
                        provenance=match_evidence.model_copy(update={"citations": match_evidence.citations + ev.citations}))

            witness_counts = Counter(digest(w) for w in page.get("witnesses") or [])
            seen_witnesses = Counter()
            appearance_keys = {}
            for index, witness in enumerate(page.get("witnesses") or []):
                if not isinstance(witness, dict) or not isinstance(witness.get("name"), str) or not witness["name"].strip():
                    continue
                witness_key = digest(witness)
                seen_witnesses[witness_key] += 1
                if witness_counts[witness_key] > 1:
                    witness_key += f"|duplicate|{seen_witnesses[witness_key]}"
                appearance_keys[index] = key + "|witness|" + witness_key

            aliases, skipped = _attachment_aliases(page)
            seen_documents = set()
            for index, document in enumerate(page.get("documents") or []):
                if index in skipped:
                    continue
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
                for alias_index, alias_document in aliases.get(index, []):
                    attachment_selector = "/attachments/" + alias_document[2].replace("~", "~0").replace("/", "~1")
                    ev = ev.model_copy(update={"citations": ev.citations + context.evidence(source, selector=f"/documents/{alias_index}").citations
                                               + context.evidence(source, selector=attachment_selector).citations})
                metadata = (page.get("document_metadata") or {}).get(document_url, {})
                metadata_selector = "/document_metadata/" + document_url.replace("~", "~0").replace("/", "~1")
                if metadata:
                    ev = ev.model_copy(update={"citations": ev.citations + context.evidence(source, selector=metadata_selector).citations})
                resolved = [entry.get("url") for entry in (page.get("attachments") or {}).get(document_url, []) if isinstance(entry, dict) and web_url(entry.get("url"))]
                urls = [document_url, *resolved, *(alias_document[2] for _, alias_document in aliases.get(index, []))]
                if title.strip().lower() in ("here", "download", "view", "read") and len(aliases.get(index, [])) == 1:
                    title = aliases[index][0][1][1]
                # Some vcard templates put names in spans, so the older document
                # reader selected the section heading instead of the file's owner.
                owners = metadata.get("witness_indexes") or []
                if title.strip().lower() in ("witnesses", "nominees", "panel") and len(owners) == 1:
                    owner_index = owners[0]
                    people = page.get("witnesses") or []
                    if type(owner_index) is int and 0 <= owner_index < len(people):
                        owner = people[owner_index].get("name")
                        if owner:
                            label = kind.capitalize() if kind != "other" else "Document"
                            title = f"{owner} — {label}"
                built = material_records(context, ev, document_key, title=title, urls=urls, details=DocumentDetails(category=cat))
                media_types = {attributes.get("type") for attributes in metadata.get("attributes", []) if isinstance(attributes, dict) and attributes.get("type")}
                if len(media_types) == 1:
                    built = [item.model_copy(update={"media_type": next(iter(media_types))})
                             if item.kind == "representation" and item.locations[0].url == document_url else item for item in built]
                built = [item.model_copy(update={"locations": tuple(location.model_copy(update={"role": "landing"}) if attachment_page(location.url) else location for location in item.locations)})
                         if item.kind == "representation" else item for item in built]
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
                        for witness_index in dict.fromkeys(metadata.get("witness_indexes") or []):
                            if type(witness_index) is not int or witness_index not in appearance_keys:
                                continue
                            appearance = Ref(kind="appearance", id=context.ids("appearance", appearance_keys[witness_index] + "|" + meeting.id))
                            yield MaterialLink(
                                id=context.ids("material_link", document_key + "|" + appearance.id),
                                material=ref(material), version=ref(version), subject=appearance,
                                role=cat if cat in ("transcript", "statement", "biography", "disclosure", "questions_for_record") else "supporting",
                                provenance=ev.model_copy(update={"citations": ev.citations + match_evidence.citations}),
                            )

            for index, witness in enumerate(page.get("witnesses") or []):
                if not matched:
                    break
                selector = f"/witnesses/{index}"
                if not isinstance(witness, dict) or not isinstance(witness.get("name"), str) or not witness["name"].strip():
                    yield issue(f"invalid-witness|{index}", "unverified", "A listed witness has no usable name.", selector=selector)
                    continue
                metadata = (page.get("witness_metadata") or {}).get(str(index), {})
                witness_evidence = context.evidence(source, selector=selector)
                if metadata:
                    witness_evidence = witness_evidence.model_copy(update={"citations": witness_evidence.citations + context.evidence(source, selector=f"/witness_metadata/{index}").citations})
                for meeting, match_evidence in matched.values():
                    # Each observed row remains local to its page and meeting;
                    # equal names do not establish a shared person identity.
                    yield Appearance(
                        id=context.ids("appearance", appearance_keys[index] + "|" + meeting.id),
                        meeting=meeting, name=RecordedName(display=witness["name"]),
                        roles=witness_roles(witness.get("position")), participation="listed",
                        affiliation=Affiliation(organization_name=witness.get("organization") or None, position=witness.get("position") or None,
                                                location=metadata.get("location") or None),
                        provenance=match_evidence.model_copy(update={"citations": match_evidence.citations + witness_evidence.citations}),
                    )
            if failed:
                for meeting, match_evidence in matched.values():
                    yield Assessment(
                        id=context.ids("assessment", key + "|reachability|" + meeting.id), subject=meeting,
                        aspect="reachability", status="error", evaluated_at=context.now,
                        observed_at=observed_time(check.get("completed_at"), context.now), provider=context.provider, scope=url,
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
