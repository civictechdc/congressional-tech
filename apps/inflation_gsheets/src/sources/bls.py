"""BLS CPI-U adapter.

The headline BLS series ``CUUR0000SA0`` (CPI-U, all items, US city average) is
already fetched as *index levels* by ``fetch-cpi-convert-csv.py`` and stored in
``data/historical-cpi.csv`` (the year x month grid the Google Sheet reads). To
keep a single source of truth and avoid a second BLS API call, this adapter
derives the year-over-year % change directly from that grid rather than
re-hitting the API.

YoY% for month m = (index[m] / index[m-12] - 1) * 100.
"""

from __future__ import annotations

import pandas as pd

from .base import InflationSource, SourceConfig, SourceUnavailable, to_month_start

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class BLSSource(InflationSource):
    key = "bls"
    label = "BLS CPI-U (CUUR0000SA0)"
    columns = ["bls_yoy"]
    requires_key = False

    def fetch(self, config: SourceConfig) -> pd.DataFrame:
        path = config.data_dir / "historical-cpi.csv"
        if not path.exists():
            raise SourceUnavailable(
                f"BLS index grid not found at {path} "
                "(run fetch-cpi-convert-csv.py first)"
            )

        grid = pd.read_csv(path)
        if "year" not in grid.columns:
            raise SourceUnavailable("historical-cpi.csv missing 'year' column")

        # Wide grid -> long monthly series of index levels.
        long = grid.melt(id_vars="year", var_name="month", value_name="index_level")
        long = long[long["month"].isin(MONTH_ORDER)]
        long["month_num"] = long["month"].map({m: i + 1 for i, m in enumerate(MONTH_ORDER)})
        long["date"] = pd.to_datetime(
            dict(year=long["year"], month=long["month_num"], day=1)
        )
        long["index_level"] = pd.to_numeric(long["index_level"], errors="coerce")
        long = long.dropna(subset=["index_level"]).sort_values("date")

        s = long.set_index("date")["index_level"]
        s.index = to_month_start(s.index)

        # Reindex onto a gap-free monthly grid so the 12-month shift aligns by
        # actual calendar date (any missing month stays NaN, not silently
        # positionally shifted).
        full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
        s = s.reindex(full)

        # YoY% = 12-month percent change of the index level.
        yoy = (s / s.shift(12) - 1.0) * 100.0
        yoy = yoy.dropna()
        return yoy.round(4).to_frame(name="bls_yoy")
