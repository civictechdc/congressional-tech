"""Decode retained TinyDB tables without file access or acquisition imports."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YouTubeCache:
    """An unchanged cache with table and row insertion order preserved.

    Read each table family only when requested: video-only consumers need not
    inspect channel metadata. Invalid table shapes raise the ordinary mapping
    errors rather than being silently dropped or repaired.
    """

    tables: dict[str, Any]

    def videos(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Yield (literal table handle, unchanged video row), including repeats."""
        prefix = "youtube_videos_"
        for name, rows in self.tables.items():
            if name.startswith(prefix):
                for row in rows.values():
                    yield name[len(prefix):], row

    def channels(self) -> Iterator[dict[str, Any]]:
        """Yield unchanged channel metadata in retained row order."""
        yield from self.tables.get("youtube_channels", {}).values()


def decode_cache(data: bytes | str | dict[str, Any]) -> YouTubeCache:
    """Accept retained JSON bytes/text or decoded tables; never change inputs.

    Callers own file reads, retained byte snapshots, selection and matching.
    JSON errors propagate; this reader does not validate native API responses.
    """
    return YouTubeCache(json.loads(data) if isinstance(data, (bytes, str)) else data)
