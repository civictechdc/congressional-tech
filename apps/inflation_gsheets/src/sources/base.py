"""Source-adapter framework for the multi-source inflation table.

Common metric across every source: **year-over-year inflation %** (the
12-month percent change), at **monthly** frequency. That is the one unit all
of these measures share, so the columns are directly comparable and any
aggregate is defensible.

Every adapter returns a pandas ``DataFrame`` indexed by month (a ``DatetimeIndex``
pinned to the first of each month) whose columns are YoY% floats. Adapters that
cannot run right now (missing API key, missing manual drop-file, network error)
signal that by raising ``SourceUnavailable``; the orchestrator logs it and keeps
going with whatever else is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


class SourceUnavailable(Exception):
    """Raised when an adapter cannot produce data (expected, non-fatal).

    Use this for the *graceful skip* cases: no API key configured, no manual
    CSV dropped in, a source that is intentionally offline. The orchestrator
    catches it, logs a SKIP line, and continues. Unexpected failures should
    raise their own exception type (also caught, but logged as ERROR).
    """


@dataclass
class SourceConfig:
    """Runtime configuration handed to every adapter."""

    data_dir: Path
    manual_dir: Path
    # request timeout (seconds) for network adapters
    timeout: int = 30


def to_month_start(index) -> pd.DatetimeIndex:
    """Normalize any datetime-like (Index, Series, or array) to first-of-month."""
    dti = pd.DatetimeIndex(pd.to_datetime(index))
    return dti.to_period("M").to_timestamp()


def monthly_from_daily(dates, values, colname: str) -> pd.DataFrame:
    """Resample an irregular/daily YoY series to monthly.

    Takes the last observation within each calendar month (the most recent
    reading for that month), then pins the index to month-start. Returns a
    one-column DataFrame.
    """
    s = pd.Series(
        pd.to_numeric(pd.Series(values), errors="coerce").values,
        index=pd.to_datetime(pd.Series(dates)),
        name=colname,
    ).dropna()
    if s.empty:
        return pd.DataFrame(columns=[colname])
    monthly = s.resample("MS").last().dropna()
    monthly.index = to_month_start(monthly.index)
    return monthly.to_frame()


class InflationSource:
    """Base class / interface every source adapter implements.

    Subclass contract:
      * ``key``          - short machine id for the source (also log label)
      * ``columns``      - the output column name(s) this adapter emits
      * ``requires_key`` - True if it needs a secret to run at all
      * ``fetch(config)``- return a month-indexed DataFrame of YoY% floats,
                            or raise ``SourceUnavailable`` to be skipped.
    """

    key: str = "base"
    label: str = "base"
    columns: list[str] = field(default_factory=list)
    requires_key: bool = False

    def fetch(self, config: SourceConfig) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError
