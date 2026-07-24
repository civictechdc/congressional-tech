"""FRED alternative-CPI adapter (keyless).

Pulls the Federal Reserve's alternative "core-ish" inflation gauges via FRED's
public CSV download endpoint, which needs **no API key**:

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>

The ``...M159...`` variants are published as **"Percent Change from Year Ago"**
(i.e. already YoY %), which is exactly our common metric, so no conversion is
needed. (The ``...M158...`` siblings are 1-month annualized rates -- NOT what we
want; verified against the live feed before wiring these up.)

Series:
  * MEDCPIM159SFRBCLE     - Cleveland Fed Median CPI, YoY %          (from 1983-12)
  * TRMMEANCPIM159SFRBCLE - Cleveland Fed 16% Trimmed-Mean CPI, YoY %(from 1983-12)
  * CORESTICKM159SFRBATL  - Atlanta Fed Sticky-Price CPI, YoY %      (from 1968-01)

Each series is fetched independently; if one 404s or times out the others still
come through.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from .base import InflationSource, SourceConfig, SourceUnavailable, to_month_start

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# output column -> FRED series id (all YoY %, monthly)
FRED_SERIES = {
    "fred_median": "MEDCPIM159SFRBCLE",
    "fred_trimmed": "TRMMEANCPIM159SFRBCLE",
    "fred_sticky": "CORESTICKM159SFRBATL",
}


def _fetch_one(series_id: str, colname: str, timeout: int) -> pd.DataFrame:
    resp = requests.get(FRED_CSV, params={"id": series_id}, timeout=timeout)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    # Header is: observation_date,<SERIES_ID>
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col])
    out = pd.Series(
        df[val_col].values,
        index=to_month_start(pd.to_datetime(df[date_col])),
        name=colname,
    )
    return out.round(4).to_frame()


class FREDSource(InflationSource):
    key = "fred"
    label = "FRED alt-CPI (Cleveland median/trimmed, Atlanta sticky)"
    columns = list(FRED_SERIES.keys())
    requires_key = False

    def fetch(self, config: SourceConfig) -> pd.DataFrame:
        frames = []
        errors = []
        for colname, series_id in FRED_SERIES.items():
            try:
                frames.append(_fetch_one(series_id, colname, config.timeout))
                print(f"    [fred] {colname} <- {series_id}: ok")
            except Exception as exc:  # per-series resilience
                errors.append(f"{series_id} ({colname}): {exc}")
                print(f"    [fred] {colname} <- {series_id}: FAILED ({exc})")

        if not frames:
            raise SourceUnavailable(
                "all FRED series failed: " + "; ".join(errors)
            )
        return pd.concat(frames, axis=1).sort_index()
