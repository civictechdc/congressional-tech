"""Offline Committee Explorer records from the existing YouTube video cache.

The cache's ``publishedAt`` comes from playlistItems.snippet: it is the time an
item was added to the uploads playlist, not independently verified publication
time. The cache also omits channel IDs. Preserve both limits rather than infer
channel identity from a handle/playlist or publication time from another event.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import math
from typing import Any
from urllib.parse import quote

from committee_meeting.assessments import Assessment
from committee_meeting.committees import Channel
from committee_meeting.common import Identifier, Ref
from committee_meeting.issues import DataIssue
from committee_meeting.materials import (
    Material, MaterialLink, MaterialLocation, MaterialVersion, RecordingDetails,
    Representation,
)
from committee_meeting.provenance import Method, Provenance


def records(
    videos: Iterable[Mapping[str, Any]],
    context,
    *,
    channel_id: str | None = None,
    meetings: Mapping[str, Sequence[tuple[Ref, Provenance]]] | None = None,
):
    """Yield metadata, reported caption assessments and supported relationships.

    ``context`` supplies source/evidence/ids/now, independently of any other
    source package. ``channel_id`` must be an authoritative ID already verified
    in the retained input; an explicit value is recorded alongside the raw row.
    ``meetings`` is keyed by video ID and carries each accepted match's evidence.
    No ID or title matching, downloads, caption acquisition or API calls occur.
    """
    channels_emitted = set()
    for original in videos:
        row = dict(original)
        video = row.get("videoId")
        if not isinstance(video, str) or not video.strip():
            raise ValueError("a retained YouTube video row requires videoId")
        key = f"youtube|{video}"
        url = "https://www.youtube.com/watch?v=" + quote(video, safe="")
        # Keep caller-supplied context distinguishable from the original fields.
        payload = {"video": row, "verified_channel_id": channel_id} if channel_id else row
        pointer = "/video" if channel_id else ""
        source = context.source(key, payload, url=url)
        yield source
        evidence = context.evidence(source)
        canonical = context.evidence(
            source, basis="derived",
            method=Method(name="youtube_api.adapters.canonical-url", version="1"),
        )
        reported_channel = row.get("channelId")
        authoritative_channel = reported_channel if isinstance(reported_channel, str) and reported_channel else channel_id
        channel_ref = None
        if authoritative_channel:
            channel_key = f"youtube|{authoritative_channel}"
            channel_ref = Ref(kind="channel", id=context.ids("channel", channel_key))
            if channel_ref.id not in channels_emitted:
                yield Channel(
                    id=channel_ref.id, provider="youtube",
                    identifiers=(Identifier(scheme="youtube.channel", value=authoritative_channel),),
                    title=row.get("channelTitle") if isinstance(row.get("channelTitle"), str) else None,
                    url="https://www.youtube.com/channel/" + quote(authoritative_channel, safe=""),
                    provenance=canonical,
                )
                channels_emitted.add(channel_ref.id)

        material_ref = Ref(kind="material", id=context.ids("material", key))
        yield Material(
            id=material_ref.id, title=row.get("title") if isinstance(row.get("title"), str) else None,
            identifiers=(Identifier(scheme="youtube.video", value=video),),
            details=RecordingDetails(medium="video", provider="youtube", channel=channel_ref),
            provenance=evidence,
        )
        if channel_id and reported_channel and reported_channel != channel_id:
            yield DataIssue(
                id=context.ids("data_issue", key + "|channel-disagreement"), subject=material_ref,
                category="conflicting", field_path="/details/channel",
                summary="The native channel ID differs from the supplied channel context.",
                explanation="The recording uses its native channel ID; both values remain in the source record.",
                detected_at=context.now, provenance=evidence,
            )
        duration = row.get("duration")
        invalid_duration = duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration < 0
        )
        version_ref = Ref(kind="material_version", id=context.ids("material_version", key + "|reported-edition"))
        yield MaterialVersion(
            id=version_ref.id, material=material_ref,
            label="Reported recording; revision not established",
            duration_seconds=None if invalid_duration else duration,
            provenance=evidence,
        )
        yield Representation(
            id=context.ids("representation", key + "|player"), version=version_ref,
            locations=(MaterialLocation(url=url, role="player"),),
            format_label="YouTube player", provenance=canonical,
        )
        if invalid_duration:
            yield DataIssue(
                id=context.ids("data_issue", key + "|duration"), subject=version_ref,
                category="unverified", field_path="/duration_seconds",
                summary="The retained recording duration is not a valid number of seconds.",
                detected_at=context.now, provenance=evidence,
            )
        if row.get("publishedAt"):
            yield DataIssue(
                id=context.ids("data_issue", key + "|publication-time"), subject=version_ref,
                category="unverified", impact="informational", field_path="/published_at",
                summary="The original video publication time is not established by this cache.",
                explanation="The retained publishedAt field is the playlist-item timestamp. It remains in the source record.",
                detected_at=context.now, provenance=context.evidence(source, selector=pointer + "/publishedAt"),
            )
        caption = row.get("caption")
        yield Assessment(
            id=context.ids("assessment", key + "|captions"), subject=material_ref,
            aspect="captions", status="available" if caption is True else "unknown",
            evaluated_at=context.now, provider="youtube",
            scope="Retained YouTube contentDetails.caption flag; automatic captions were not checked.",
            explanation=(
                "The retained API flag reports published captions; no caption bytes or language were acquired."
                if caption is True else
                "The retained flag does not establish whether automatic captions are available."
                if caption is False else "The retained metadata has no confirmed caption availability."
            ),
            provenance=context.evidence(source, selector=pointer + "/caption") if "caption" in row else evidence,
        )
        associations = (meetings or {}).get(video, ())
        if associations:
            seen = set()
            for meeting, association_evidence in associations:
                if meeting.kind != "meeting":
                    raise ValueError("YouTube meeting associations require meeting references")
                if meeting.id in seen:
                    raise ValueError("repeat meeting association for a YouTube video")
                seen.add(meeting.id)
                yield MaterialLink(
                    id=context.ids("material_link", key + "|meeting|" + meeting.id),
                    material=material_ref, version=version_ref, subject=meeting,
                    role="recording", provenance=association_evidence,
                )
        else:
            yield DataIssue(
                id=context.ids("data_issue", key + "|unlinked"), subject=material_ref,
                category="unlinked", summary="This recording has no verified meeting association.",
                detected_at=context.now, provenance=evidence,
            )
