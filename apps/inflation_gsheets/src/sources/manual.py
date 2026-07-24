"""Shared helper for adapters backed by a maintainer-supplied CSV.

Some sources have no free, machine-readable feed. Rather than invent a fake
endpoint, those adapters read a small CSV that the maintainer drops into
``data/manual/`` and gracefully skip when the file is absent.

Expected drop-file format (either works):
    date,yoy
    2024-01-01,3.1
    2024-02-01,2.9
or a daily file with a ``date`` column and any single value column -- it is
coerced to numeric and resampled to monthly (last reading per month).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import SourceUnavailable, monthly_from_daily


def load_manual_series(path: Path, colname: str) -> pd.DataFrame:
    """Load a manual YoY% CSV into a monthly, month-indexed one-column frame."""
    if not path.exists():
        raise SourceUnavailable(
            f"no manual data file at {path} -- drop a 'date,yoy' CSV there to "
            "enable this source (see README)."
        )

    df = pd.read_csv(path)
    if df.empty:
        raise SourceUnavailable(f"manual data file {path} is empty")

    cols = {c.lower().strip(): c for c in df.columns}
    date_col = cols.get("date") or df.columns[0]
    # value column: prefer an explicit 'yoy'/'value' column, else the 2nd column
    val_col = (
        cols.get("yoy")
        or cols.get("yoy_pct")
        or cols.get("value")
        or cols.get(colname)
        or df.columns[1]
    )

    frame = monthly_from_daily(df[date_col], df[val_col], colname)
    if frame.empty:
        raise SourceUnavailable(f"manual data file {path} has no usable rows")
    return frame.round(4)
