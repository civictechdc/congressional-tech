"""Typed fields of one retained YouTube cache row. Upstream API JSON stays in the body."""
import re
from typing import Any

from congress_shared.youtube_cache import decode_cache

# Extracted in Python because the engine's Rust regex has no lookahead.
EVENT_ID = re.compile(r"(?:event\s*id|\bid)\s*[:=#]?\s*(1\d{5})(?!\d)|house-event/(1\d{5})(?!\d)", re.I)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False}.get(value.lower()) if isinstance(value, str) else None


def _seconds(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def stated_event_ids(*texts: str | None) -> list[int]:
    """Event IDs a video's own text names: a claim, since committees mistag videos."""
    found = set()
    for text in texts:
        found.update(int(a or b) for a, b in EVENT_ID.findall(text or ""))
    return sorted(found)


def video_row(handle: str, raw: dict[str, Any]) -> dict[str, Any]:
    """One collected upload; a missing field stays null rather than taking a default."""
    title, description = _text(raw.get("title")), _text(raw.get("description"))
    return dict(handle=handle, video_id=str(raw["videoId"]), channel_id=_text(raw.get("channelId")),
        channel_title=_text(raw.get("channelTitle")), title=title, description=description,
        published_at=_text(raw.get("publishedAt")), video_published_at=_text(raw.get("videoPublishedAt")),
        duration_seconds=_seconds(raw.get("duration")), available=_flag(raw.get("available")),
        has_caption=_flag(raw.get("caption")), details_checked_at=_text(raw.get("details_checked_at")),
        stated_event_ids=stated_event_ids(title, description))


def channel_row(raw: dict[str, Any]) -> dict[str, Any]:
    return dict(handle=str(raw["handle"]), channel_id=_text(raw.get("channelId")), title=_text(raw.get("title")),
        custom_url=_text(raw.get("customUrl")), uploads_scan_complete=_flag(raw.get("uploads_scan_complete")))


def cache_rows(payload: bytes | str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(channels, videos) of one retained cache file, in retained order."""
    cache = decode_cache(payload)
    try:
        return [channel_row(row) for row in cache.channels()], [video_row(handle, row) for handle, row in cache.videos()]
    except (AttributeError, TypeError) as error:
        raise ValueError(f"Unexpected YouTube cache shape: {error}") from error
