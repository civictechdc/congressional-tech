"""Build the multi-source inflation table.

Fetches every configured inflation source, normalizes each to the common metric
-- **year-over-year inflation %, monthly** -- aligns them by month, and writes
``data/inflation-sources.csv`` with one column per *available* source. Any source
that cannot run (missing key, missing manual file, network error) is logged and
skipped; the run still succeeds with whatever else is available.

This does NOT touch ``historical-cpi.csv`` (the BLS index grid the Google Sheet
reads) -- that is produced separately by ``fetch-cpi-convert-csv.py`` and this
script only *reads* it to derive the BLS YoY column.

Optional ``--aggregate`` adds a blended composite column. IT IS NOT AN OFFICIAL
INFLATION FIGURE: it averages measures built on different methodologies,
coverage, and revision schedules. It is a derived, judgment-laden number, opt-in
by design. See the README caveat.

Usage:
    python fetch-inflation-sources.py                       # sources only
    python fetch-inflation-sources.py --aggregate           # + equal-weight blend
    python fetch-inflation-sources.py --aggregate \
        --weights "bls_yoy=2,fred_median=1,fred_trimmed=1,fred_sticky=1"
    python fetch-inflation-sources.py --output /path/out.csv --manual-dir /path/manual

Sources: BLS CPI-U (derived YoY), FRED alt-CPI (Cleveland median/trimmed,
Atlanta sticky -- keyless), Adobe DPI (manual drop-file), PriceStats/BPP
(manual drop-file). Truflation was evaluated but excluded (paid API only).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pandas as pd

# Make the sibling ``sources`` package importable when run as a script from the
# repo root (python apps/inflation_gsheets/src/fetch-inflation-sources.py).
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sources import (  # noqa: E402
    CANONICAL_COLUMNS,
    SOURCES,
    SourceConfig,
    SourceUnavailable,
)

DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_OUTPUT = DATA_DIR / "inflation-sources.csv"
DEFAULT_MANUAL_DIR = DATA_DIR / "manual"


def parse_weights(raw: str | None) -> dict[str, float]:
    """Parse 'col=1.5,col2=2' into {col: 1.5, col2: 2.0}."""
    if not raw:
        return {}
    weights: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise SystemExit(f"bad --weights entry '{pair}' (expected col=number)")
        col, val = pair.split("=", 1)
        weights[col.strip()] = float(val.strip())
    return weights


def compute_aggregate(
    df: pd.DataFrame, cols: list[str], weights: dict[str, float]
) -> pd.Series:
    """Weighted mean across available (non-null) source columns, per month.

    Weights are renormalized over whichever columns are present in each row, so a
    month with only some series still gets a defensible blended value. Default
    weight for any column not listed is 1.0 (equal weight).
    """
    present = [c for c in cols if c in df.columns]
    w = pd.Series({c: float(weights.get(c, 1.0)) for c in present})

    values = df[present]
    mask = values.notna()
    # weight matrix zeroed where a value is missing
    wmat = mask.mul(w, axis=1)
    wsum = wmat.sum(axis=1)
    weighted = (values.fillna(0.0) * wmat).sum(axis=1)
    agg = weighted / wsum.replace(0.0, pd.NA)
    return agg.astype(float).round(4)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the multi-source inflation table.")
    ap.add_argument(
        "--aggregate",
        action="store_true",
        help="add a blended composite column (derived, NOT official -- see README).",
    )
    ap.add_argument(
        "--weights",
        default=None,
        help="comma list col=weight for the aggregate (default: equal weight).",
    )
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="output CSV path.")
    ap.add_argument(
        "--manual-dir",
        default=str(DEFAULT_MANUAL_DIR),
        help="dir holding manual drop-files (adobe-dpi.csv, pricestats-bpp.csv).",
    )
    ap.add_argument("--timeout", type=int, default=30, help="network timeout (s).")
    args = ap.parse_args()

    config = SourceConfig(
        data_dir=DATA_DIR,
        manual_dir=Path(args.manual_dir),
        timeout=args.timeout,
    )
    weights = parse_weights(args.weights)

    frames: list[pd.DataFrame] = []
    available_cols: list[str] = []
    status: list[tuple[str, str]] = []

    for source in SOURCES:
        print(f"[{source.key}] {source.label} ...")
        try:
            frame = source.fetch(config)
            if frame is None or frame.empty:
                raise SourceUnavailable("returned no data")
            frames.append(frame)
            got = [c for c in frame.columns]
            available_cols.extend(got)
            n = len(frame)
            latest = frame.index.max().date().isoformat()
            status.append((source.key, f"OK   {got} ({n} months, latest {latest})"))
            print(f"    -> OK: {got}, {n} months, latest {latest}")
        except SourceUnavailable as exc:
            status.append((source.key, f"SKIP {exc}"))
            print(f"    -> SKIP: {exc}")
        except Exception as exc:  # unexpected -- log but keep going
            status.append((source.key, f"ERROR {exc}"))
            print(f"    -> ERROR: {exc}")
            traceback.print_exc(limit=2)

    if not frames:
        print("No sources produced data. Writing nothing.", file=sys.stderr)
        # Still exit 0 so a monthly cron with a transient outage does not fail the
        # whole workflow; the previous CSV (if any) is left in place.
        _print_summary(status)
        return 0

    # Outer-join every source on the monthly index.
    table = pd.concat(frames, axis=1).sort_index()
    table.index.name = "date"

    # Canonical column order, restricted to what actually came back.
    ordered = [c for c in CANONICAL_COLUMNS if c in table.columns]
    # (defensive) append any stray columns not in the canonical list
    ordered += [c for c in table.columns if c not in ordered]
    table = table[ordered]

    if args.aggregate:
        table["aggregate"] = compute_aggregate(table, ordered, weights)
        wdesc = weights or "equal"
        print(f"[aggregate] blended composite added (weights={wdesc}).")
        print("            NOTE: derived, judgment-laden -- NOT an official figure.")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Format the month index as YYYY-MM-01 for the CSV.
    out = table.copy()
    out.index = out.index.strftime("%Y-%m-01")
    out.to_csv(out_path)
    print(f"\nWrote {out_path} ({len(out)} months, columns: {list(out.columns)})")

    _print_summary(status)
    _print_tail(table)
    return 0


def _print_summary(status: list[tuple[str, str]]) -> None:
    print("\n=== source summary ===")
    for key, msg in status:
        print(f"  {key:12s} {msg}")


def _print_tail(table: pd.DataFrame, n: int = 6) -> None:
    print(f"\n=== last {n} months ===")
    tail = table.tail(n).copy()
    tail.index = tail.index.strftime("%Y-%m")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(tail.to_string())


if __name__ == "__main__":
    raise SystemExit(main())
