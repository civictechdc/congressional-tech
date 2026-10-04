"""Import retained manual meeting-recording associations without rematching."""

from collections import defaultdict

from committee_meeting.common import Identifier
from committee_meeting.issues import DataIssue
from committee_meeting.materials import RecordingDetails

from congress_api.adapters.common import digest, material_records, ref
from congress_api.parsers import media


def normalized_reference(parsed):
    """Map parsed source identity into the normalized model's identifier scheme."""
    if parsed.provider == "youtube":
        identifiers = (Identifier(scheme="youtube.video", value=parsed.identifier),)
    elif parsed.provider == "senate":
        identifiers = (Identifier(scheme="senate.filename", value=parsed.identifier, scope=parsed.scope),)
    else:
        identifiers = (Identifier(scheme="url", value=parsed.url),)
    return parsed.key, parsed.url, parsed.provider, identifiers


def offsite_reference(url):
    """Compatibility wrapper for explicitly offsite normalized findings."""
    return normalized_reference(media.offsite_reference(url))


def recording_reference(token):
    """Compatibility wrapper; provider interpretation belongs to the source parser."""
    parsed = media.recording_reference(token)
    return normalized_reference(parsed) if parsed else None


def records(rows, context, *, meetings):
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        by_event[str(event)].append(meeting)
    for row in rows:
        source = context.source("recording-finding|" + digest(row), row)
        yield source
        evidence = context.evidence(source, basis="curated")
        parsed = recording_reference(row.get("recording") or "")
        if parsed is None:
            yield DataIssue(id=context.ids("data_issue", source.id + "|invalid"), subject=ref(source),
                category="unverified", summary="The retained recording reference could not be interpreted.",
                detected_at=context.now, provenance=evidence)
            continue
        key, url, provider, identifiers = parsed
        candidates = by_event.get(str(row.get("event_id") or ""), [])
        meeting = candidates[0] if len(candidates) == 1 else None
        built = material_records(context, evidence, key, title=None, urls=[url],
            details=RecordingDetails(medium="video" if provider else "unknown", provider=provider),
            subject=meeting, role="recording", identifiers=identifiers)
        yield from built
        if meeting is None:
            yield DataIssue(id=context.ids("data_issue", source.id + "|unlinked"), subject=ref(built[0]),
                category="unlinked", summary="The retained recording has no unique meeting association.",
                detected_at=context.now, provenance=evidence)
