# Project 5.1: Inflation Calculator for Google Sheets


## Provided Information:
### Problem: 
Manually calculating inflation across different years in spreadsheets is inefficient and prone to errors.

### Solution:
Create a custom formula for Google Sheets that leverages inflation data from the Bureau of Labor Statistics (BLS) or another reliable source to automatically calculate the inflation-adjusted value of a monetary amount.
* Formula Structure: The formula should take three inputs:
    * `source_cell`: The cell containing the original monetary amount.
    * `start_year_cell`: The cell containing the year of the original amount.
    * `end_year_cell`: The cell containing the year to which the amount should be adjusted.
* Example Formula: `=INFLATION(A2, B2, C2)` (where A2 contains the amount, B2 the start year, and C2 the end year).
* The formula should also be "drag-able" to automatically update references for a range of data, allowing the inflation calculations to be easily expanded down a column.

### Value:
* Congressional-Tech: A useful tool for staff performing economic analysis, cost adjustments, and budget projections in spreadsheets.
* Civic-Tech: A widely applicable utility for general users who need to perform inflation calculations in their spreadsheets, enhancing the functionality of Google Sheets.


## Technical Solution: 
contributors: [agurvich](https://github.com/agurvich)

[A template Google Sheet](https://docs.google.com/spreadsheets/d/1mhBVKwUEV-J53n7Jrwzc1BldqS5mWqIW5k0CxsDffHc/edit?usp=sharing), containing the function `INFLATION(source_cell, start_year_cell, end_year_cell)`. To use the function, the template sheet should be duplicated and any existing data should be imported. 

Within the Template Google Sheet there is
### 1 named range:

`BLS_CPI = CPIData!A1:M1000`
Which provides access to the hidden sheet `CPIData`, which loads the latest CPI data by reading a [csv file](https://raw.githubusercontent.com/agurvich/congressional-tech/refs/heads/main/projects/5.1-inflation-gsheets/data/historical-cpi.csv) that is automatically kept up-to-date by a Github Action.

On the 3rd of every month, the workflow will: 
1. Open the current .csv
2. Query the Bureau of Labor Statistics data API at `https://api.bls.gov/publicAPI/v2/timeseries/data/` with a `POST` request whose body contains:
    * `end_year = datetime.now().year`
    * `start_year = end_year - 9` (the API rate limits unauthenticated requests to 10 years at a time)
    * `seriesid = CUUR0000SA0` 
3. Appends the new data to the `.csv`
4. Commits and pushes the modified `.csv`

### 2 named functions:

`FLOATYEARDATE`, which converts a floating point year into a `DATE` object and

```
FLOATYEARDATE(input_year) = DATE(INT(input_year), 1, 1) + (input_year - INT(input_year)) * 365.25
```

`INFLATION`, which calculates the inflation adjusted dollar amount between two floating point years using the ratio of the corresponding Consumer Price Indices.

```
INFLATION(start_dollar_amount, start_year, end_year) = 
INDEX(BLS_CPI, DATEDIF(DATE(1913,1,1),FLOATYEARDATE(end_year),"Y")+2, MONTH(FLOATYEARDATE(end_year))+1) /
INDEX(BLS_CPI, DATEDIF(DATE(1913,1,1),FLOATYEARDATE(start_year),"Y")+2, MONTH(FLOATYEARDATE(start_year))+1) * start_dollar_amount
```

> NOTE: `INFLATION` could be "improved" if instead of ingesting years (as requested) it ingested `DATE` objects, then you could avoid the multiple calls to `FLOATYEARDATE`.

---

## Multi-source inflation table (`inflation-sources.csv`)

Alongside the official BLS CPI index grid (`data/historical-cpi.csv`, which is
unchanged and still feeds the Google Sheet), the pipeline also builds
`data/inflation-sources.csv`: a side-by-side comparison of several inflation
measures, plus an optional blended composite.

### Common metric

Every source is normalized to the **one unit they all share**:

> **year-over-year inflation % (the 12-month percent change), monthly frequency.**

This makes the columns directly comparable and the aggregate defensible. The
BLS index levels are converted to YoY% for this table
(`(index[m] / index[m-12] - 1) * 100`); the raw index grid stays untouched in
`historical-cpi.csv`. Daily sources are resampled to monthly (last reading per
month).

### Architecture

A small source-adapter framework lives in `src/sources/`. Each source is one
module exposing an `InflationSource` subclass with `fetch(config) -> DataFrame`
that returns a month-indexed frame of YoY% floats. A source that cannot run
(missing key, missing manual file, network error) raises `SourceUnavailable`;
the orchestrator logs it and continues with whatever is available — **one source
being down never breaks the run.**

- `src/sources/base.py` — interface, config, month-normalization helpers.
- `src/sources/bls.py` — `bls_yoy` (derived from `historical-cpi.csv`).
- `src/sources/fred.py` — `fred_median`, `fred_trimmed`, `fred_sticky`.
- `src/sources/adobe.py` — `adobe` (manual drop-file).
- `src/sources/pricestats.py` — `pricestats` (manual drop-file).
- `src/fetch-inflation-sources.py` — orchestrator + aggregate.

Run it:

```bash
python src/fetch-inflation-sources.py                 # source columns only
python src/fetch-inflation-sources.py --aggregate     # + equal-weight composite
python src/fetch-inflation-sources.py --aggregate \
    --weights "bls_yoy=2,fred_median=1,fred_trimmed=1,fred_sticky=1"
```

Output columns: `date, bls_yoy, fred_median, fred_trimmed, fred_sticky[,
adobe, pricestats][, aggregate]`. Only *available* sources get a column.

### Sources: access reality (honest)

| Column(s) | Source | Access | Key? | Notes |
|-----------|--------|--------|------|-------|
| `bls_yoy` | BLS CPI-U, all items (`CUUR0000SA0`) | Derived from `historical-cpi.csv` (produced by the existing BLS API step) | No | No second API call; YoY computed from the index grid. |
| `fred_median` | Cleveland Fed **Median CPI**, YoY (`MEDCPIM159SFRBCLE`) | FRED **keyless** CSV: `fredgraph.csv?id=<ID>` | No | Live. Already published as YoY %. |
| `fred_trimmed` | Cleveland Fed **16% Trimmed-Mean CPI**, YoY (`TRMMEANCPIM159SFRBCLE`) | FRED keyless CSV | No | Live. Already YoY %. |
| `fred_sticky` | Atlanta Fed **Sticky-Price CPI**, YoY (`CORESTICKM159SFRBATL`) | FRED keyless CSV | No | Live. Already YoY %. |
| `adobe` | Adobe **Digital Price Index** | Manual drop-file `data/manual/adobe-dpi.csv` | No | No clean/stable public API; public programmatic access discontinued ~July 2025. Skips if file absent. |
| `pricestats` | **PriceStats / MIT Billion Prices Project** | Manual drop-file `data/manual/pricestats-bpp.csv` | No | Live feed is commercial (State Street). Free historical data (2007–2015, static) on Harvard Dataverse DOI `10.7910/DVN/6RQCRS`. Skips if file absent. |

> **NOTE on the `...M159...` FRED IDs:** the `...M158...` siblings exist but are
> 1-month *annualized* rates (volatile); the `...M159...` variants are
> "Percent Change from Year Ago" (true YoY) — that is what we use, verified
> against the live feed.

**Truflation was evaluated and excluded.** It has a real REST API
(`GET https://api.truflation.com/api/v1/feed/truflation/macro-data-us/truflation_us_cpi_yoy`,
auth via the `Authorization` header — confirmed against their published
`openapi.json`), but there is **no free/keyless tier** and the paid access is
not cost-justified here. The endpoint details are recorded so it can be added
back as a key-gated adapter later if that changes.

See `data/manual/README.md` for the drop-file format.

### The aggregate ("calculative option") — read this

`--aggregate` adds an `aggregate` column: a **weighted average of whichever
source columns are present that month**, weights renormalized over the available
series (default = equal weight; override with `--weights`).

> ⚠️ **The aggregate is NOT an official inflation figure.** It blends measures
> built on different methodologies (headline vs. median vs. trimmed-mean vs.
> sticky-price vs. online-only), different coverage, and different revision
> schedules. It is a **derived, judgment-laden** number, opt-in by design (it
> only appears when you pass `--aggregate`). Do not present it as *the*
> inflation rate. The same caveat is stamped in the code
> (`fetch-inflation-sources.py`) and printed at runtime.

### Automation

The monthly workflow (`.github/workflows/bls-cpi-update.yml`) runs the existing
BLS step first (refreshing `historical-cpi.csv`), then the multi-source step
(`--aggregate`), and commits both CSVs. Unavailable sources are tolerated.