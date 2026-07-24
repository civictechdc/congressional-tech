"""Adobe Digital Price Index (DPI) adapter -- manual drop-file.

Adobe's DPI is an online-prices inflation gauge (Fisher index, modeled after the
CPI) built from Adobe Analytics data. There is **no clean, stable public API or
CSV feed**: Adobe historically surfaced the numbers as JSON behind its marketing
page (business.adobe.com/resources/digital-price-index.html) and press releases,
but public programmatic access was discontinued around July 2025. Values are now
released piecemeal in press releases.

Rather than scrape a fragile, undocumented endpoint or fabricate one, this
adapter reads a maintainer-supplied CSV and skips gracefully when it is absent.

Manual data path (default): ``data/manual/adobe-dpi.csv``
    date,yoy
    2024-01-01,-3.9
    2024-02-01,-3.6
Populate it by hand from Adobe's press releases / DPI page (YoY % values), or
drop a wider export renamed to this file. See README for the source URL.
"""

from __future__ import annotations

import pandas as pd

from .base import InflationSource, SourceConfig
from .manual import load_manual_series


class AdobeSource(InflationSource):
    key = "adobe"
    label = "Adobe Digital Price Index (manual drop-file)"
    columns = ["adobe"]
    requires_key = False

    def fetch(self, config: SourceConfig) -> pd.DataFrame:
        path = config.manual_dir / "adobe-dpi.csv"
        return load_manual_series(path, "adobe")
