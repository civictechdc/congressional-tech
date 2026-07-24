# Manual drop-files for inflation sources

Some inflation sources have **no free, machine-readable feed**, so their adapters
read a CSV the maintainer drops in here. When a file below is absent, that source
is simply skipped (logged as SKIP) and the pipeline continues.

Each file uses the same shape (monthly or daily; daily is resampled to
month-end):

```csv
date,yoy
2024-01-01,-3.9
2024-02-01,-3.6
```

- `date` — any parseable date (first-of-month preferred).
- `yoy`  — year-over-year inflation, in **percent** (e.g. `2.9`, not `0.029`).
  A negative value means prices fell vs. a year ago.

## Files

| File                  | Source                        | Where to get the numbers |
|-----------------------|-------------------------------|--------------------------|
| `adobe-dpi.csv`       | Adobe Digital Price Index     | Adobe stopped public programmatic access ~July 2025. Copy YoY figures from Adobe's DPI page / press releases: https://business.adobe.com/resources/digital-price-index.html |
| `pricestats-bpp.csv`  | PriceStats / MIT Billion Prices Project | Live feed is commercial (State Street Data Intelligence). Free historical data (2007–2015, static) is on the Harvard Dataverse "Price Indices" dataset, DOI `10.7910/DVN/6RQCRS` — download the US series and convert its index level to YoY %. |

These files are optional. Add them only if you want those columns populated in
`../inflation-sources.csv`.
