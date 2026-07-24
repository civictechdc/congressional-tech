"""PriceStats / MIT Billion Prices Project (BPP) adapter -- manual drop-file.

The Billion Prices Project (MIT/Harvard, Cavallo & Rigobon) computed daily online
price indices. The **live** feed is now commercial: PriceStats is part of State
Street's Data Intelligence unit (statestreet.com/.../pricestats) -- no free API.

The **free** data is the historical BPP release, which is static and ends in
~2015. It lives on the Harvard Dataverse ("Price Indices" dataset,
DOI 10.7910/DVN/6RQCRS), behind a terms-of-use click, so it is not directly
machine-fetchable without accepting terms and picking a file id.

So there is no free, live, keyless feed to hit. This adapter reads a
maintainer-supplied CSV (e.g. the US monthly index from the Dataverse export,
converted to YoY %) and skips gracefully when absent.

Manual data path (default): ``data/manual/pricestats-bpp.csv``
    date,yoy
    2013-01-01,1.8
    2013-02-01,1.7
See README for the Dataverse DOI and how to derive YoY % from the BPP index.
"""

from __future__ import annotations

import pandas as pd

from .base import InflationSource, SourceConfig
from .manual import load_manual_series


class PriceStatsSource(InflationSource):
    key = "pricestats"
    label = "PriceStats / MIT BPP (manual drop-file)"
    columns = ["pricestats"]
    requires_key = False

    def fetch(self, config: SourceConfig) -> pd.DataFrame:
        path = config.manual_dir / "pricestats-bpp.csv"
        return load_manual_series(path, "pricestats")
