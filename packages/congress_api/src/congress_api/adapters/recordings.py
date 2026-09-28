"""Import retained manual meeting-recording associations without rematching."""
from collections import defaultdict
import re

from committee_meeting.common import Identifier
from committee_meeting.issues import DataIssue
from committee_meeting.materials import RecordingDetails
from .common import digest, material_records, ref, web_url


def records(rows, context, *, meetings):
    by_event = defaultdict(list)
    for (_, _, event), meeting in meetings.items():
        by_event[str(event)].append(meeting)
    for row in rows:
        source = context.source("recording-finding|" + digest(row), row)
        yield source
        evidence = context.evidence(source, basis="curated")
        token = row.get("recording") or ""
        url = web_url(token)
        identifiers = ()
        provider = None
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", token):
            url = "https://www.youtube.com/watch?v=" + token
            key, provider = "youtube|" + token, "youtube"
            identifiers = (Identifier(scheme="youtube.video", value=token),)
        elif url:
            from congress_api.gpo.match import VIDEO_ID
            from congress_api.senate.isvp import parse_player_url
            youtube, player = VIDEO_ID.search(url), parse_player_url(url)
            if youtube:
                token = youtube.group(1)
                key, provider = "youtube|" + token, "youtube"
                identifiers = (Identifier(scheme="youtube.video", value=token),)
            elif player:
                key, provider = "senate|" + "|".join(player), "senate"
                identifiers = (Identifier(scheme="senate.filename", value=player[1], scope=player[0]),)
            else:
                key = "offsite|" + url
        else:
            yield DataIssue(id=context.ids("data_issue", source.id + "|invalid"), subject=ref(source),
                category="unverified", summary="The retained recording reference could not be interpreted.",
                detected_at=context.now, provenance=evidence)
            continue
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
