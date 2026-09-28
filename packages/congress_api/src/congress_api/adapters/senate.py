"""Adapt retained Senate committee pages without fetching or rematching them."""
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlsplit

from committee_meeting.assessments import Assessment
from committee_meeting.issues import DataIssue
from committee_meeting.materials import DocumentDetails, MaterialLink
from committee_meeting.meetings import Affiliation, Appearance, RecordedName
from committee_meeting.provenance import Method

from congress_api.senate.pages import OWN

from .common import digest, material_records, ref, web_url
from .meetings import category


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


def records(state, context, *, meetings):
    """Yield every page and document, with only saved, unambiguous associations.

    Lookup keys are (Congress, chamber, eventId). Senate state retains only the
    eventId, so a repeated eventId across those keys cannot establish a link.
    The producer's page match is derived evidence; a listing date is not used.
    """
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
                    matched[meeting.id] = (meeting, context.evidence(source, basis="derived", method=MATCH_METHOD, selector=f"/events/{index}"))
                else:
                    yield issue(f"unresolved-event|{event}", "unlinked", "A saved page association has no unique meeting reference.",
                                explanation=f"Event {event} resolves to {len(candidates)} entries in the supplied meeting lookup.", selector=f"/events/{index}")
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
                built = material_records(context, ev, document_key, title=title, urls=[document_url], details=DocumentDetails(category=cat))
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
                        roles=("witness",), participation="listed",
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
