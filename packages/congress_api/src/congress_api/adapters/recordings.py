"""Import retained manual meeting-recording associations without rematching."""

import re
from collections import defaultdict

from committee_meeting.common import Identifier
from committee_meeting.issues import DataIssue
from committee_meeting.materials import RecordingDetails

from congress_api.adapters.common import digest, material_records, ref, web_url


def offsite_reference(url):
    """Shared offsite player identity for curated findings and GPO match rows."""
    return "offsite|" + url, url, None, (Identifier(scheme="url", value=url),)


def recording_reference(token):
    """Use the same recording identity for native pages and curated findings."""
    from urllib.parse import urlsplit

    from congress_api.matching.gpo_videos import VIDEO_ID
    from congress_api.parsers.senate_player import parse_player_url

    if not isinstance(token, str):
        return None
    url = web_url(token)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", token):
        return "youtube|" + token, "https://www.youtube.com/watch?v=" + token, "youtube", (Identifier(scheme="youtube.video", value=token),)
    if not url:
        return None
    parsed = urlsplit(url)
    host = (parsed.hostname or "").removeprefix("www.")
    if host in ("youtube.com", "youtu.be", "youtube-nocookie.com"):
        youtube = VIDEO_ID.search(url.replace("youtube-nocookie.com", "youtube.com"))
        if youtube:
            video = youtube.group(1)
            return "youtube|" + video, url, "youtube", (Identifier(scheme="youtube.video", value=video),)
    if host == "senate.gov" and parsed.path.rstrip("/") == "/isvp":
        player = parse_player_url(url)
        if player:
            return "senate|" + "|".join(player), url, "senate", (Identifier(scheme="senate.filename", value=player[1], scope=player[0]),)
    return offsite_reference(url)


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
