"""Date and Congress utilities for congressional data processing."""
from __future__ import annotations

from datetime import datetime, timezone


def year_to_congress(year: int) -> int:
    """Return the 1-based Congress number for a given calendar year.

    The 1st Congress began in 1789, and each Congress spans two years.
    """
    if year < 1789:
        raise ValueError(f"Year {year} precedes the 1st Congress (1789)")
    return (year - 1789) // 2 + 1


def congress_to_years(congress: int) -> tuple[int, int]:
    """Return the pair of calendar years (start_year, end_year) for a Congress number."""
    if congress < 1:
        raise ValueError(f"Congress number must be >= 1, got {congress}")
    first_year = 1789 + 2 * (congress - 1)
    return (first_year, first_year + 1)


def parse_utc_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO-8601 formatted timestamp string into a UTC-aware datetime.

    Accepts ISO-8601 strings (e.g. '2025-01-01T12:00:00Z', '2025-01-01T12:00:00+00:00')
    or timezone-aware datetime instances. Converts the result to UTC.
    Raises ValueError if value is unparseable or lacks timezone information.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"Timestamp lacks timezone: {value}")
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise TypeError(f"Expected str or datetime, got {type(value).__name__}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp lacks timezone offset: {value!r}")
    return parsed.astimezone(timezone.utc)
