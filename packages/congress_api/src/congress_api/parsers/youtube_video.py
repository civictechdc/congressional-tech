"""Typed fields of one retained YouTube cache row or API video. Upstream API JSON stays in the body."""
import json
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


DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def _iso_seconds(value: Any) -> int | None:
    """ISO 8601 duration such as P1DT10H30M28S, in seconds; anything else is null."""
    match = DURATION.match(value) if isinstance(value, str) and value not in ("P", "PT") else None
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
    return total if total < 2**31 else None


def api_rows(payload: bytes | str) -> list[dict[str, Any]]:
    """Videos of one retained videoListResponse; other API responses state no videos.

    `handle` is empty: an API item names its channel by ID, which the model maps to the
    channel directory."""
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get("kind") != "youtube#videoListResponse":
        return []
    rows = []
    for item in value.get("items") or []:
        if not isinstance(item, dict) or item.get("kind") != "youtube#video" or not isinstance(item.get("id"), str):
            continue
        snippet, details = (item.get(key) if isinstance(item.get(key), dict) else {}
                            for key in ("snippet", "contentDetails"))
        title, description = _text(snippet.get("title")), _text(snippet.get("description"))
        rows.append(dict(handle="", video_id=item["id"], channel_id=_text(snippet.get("channelId")),
            channel_title=_text(snippet.get("channelTitle")), title=title, description=description,
            published_at=_text(snippet.get("publishedAt")), video_published_at=None,
            duration_seconds=_iso_seconds(details.get("duration")),
            available=None, has_caption=_flag(details.get("caption")), details_checked_at=None,
            stated_event_ids=stated_event_ids(title, description)))
    return rows
