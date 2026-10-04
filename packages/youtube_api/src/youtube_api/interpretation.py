"""Pure meanings of retained YouTube fields, independent of storage and output.

Historical ``publishedAt`` is playlistItems.snippet.publishedAt (playlist
addition); ``videoPublishedAt`` is videos.list.snippet.publishedAt. Neither
field substitutes for the other. Original values and rows are never changed.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

DateBasis = Literal["playlist_added", "video_publication"]
DATE_FIELDS = {"playlist_added": "publishedAt", "video_publication": "videoPublishedAt"}


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class SourceTime:
    basis: DateBasis
    field: str
    original: Any
    instant: datetime | None


def source_time(row: Mapping[str, Any], *, basis: DateBasis) -> SourceTime:
    """Read the explicitly chosen source time; absent/invalid values stay unknown."""
    field = DATE_FIELDS[basis]
    value = row.get(field)
    instant = _instant(value)
    return SourceTime(basis, field, value, instant.astimezone(timezone.utc) if instant else None)


@dataclass(frozen=True)
class ScopedAvailability:
    status: Literal["available", "not_found", "unknown"]
    field: str | None
    observed_at: datetime | None
    scope: str
    explanation: str


@dataclass(frozen=True)
class AvailabilityFacts:
    api: ScopedAvailability
    captions: ScopedAvailability


def availability_facts(row: Mapping[str, Any], *, evaluated_at: datetime) -> AvailabilityFacts:
    """Interpret a successful detail check within its API/flag scope.

    The collector writes ``available=False`` only after a successful videos.list
    response omits the ID. A missing, invalid or future check time cannot support
    dated absence. Caption false/missing never establishes automatic-caption
    absence, and a true flag does not establish retained bytes or a language.
    """
    checked = _instant(row.get("details_checked_at"))
    observed_at = checked if checked is not None and checked <= evaluated_at else None
    available = row.get("available")
    api = ScopedAvailability(
        status=("not_found" if available is False and observed_at else
                "available" if available is True else "unknown"),
        field="available" if "available" in row else None,
        observed_at=observed_at,
        scope="YouTube Data API videos.list response for this video ID; the web player was not checked.",
        explanation=(
            "The API omitted this video from a successful response. This does not establish whether it was deleted, made private, or can be played elsewhere."
            if available is False else
            "The retained API response returned this video ID; web playback was not checked."
            if available is True else "The retained metadata has no confirmed API availability."
        ),
    )
    caption = row.get("caption")
    captions = ScopedAvailability(
        status="available" if caption is True else "unknown",
        field="caption" if "caption" in row else None,
        observed_at=observed_at,
        scope="Retained YouTube contentDetails.caption flag; automatic captions were not checked.",
        explanation=(
            "The retained API flag reports published captions; no caption bytes or language were acquired."
            if caption is True else
            "The retained flag does not establish whether automatic captions are available."
            if caption is False else "The retained metadata has no confirmed caption availability."
        ),
    )
    return AvailabilityFacts(api, captions)
