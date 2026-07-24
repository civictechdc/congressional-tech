"""Inflation source adapters.

Each adapter emits the same common metric -- year-over-year inflation %, monthly
frequency -- so the resulting columns are directly comparable. ``SOURCES`` is the
ordered registry the orchestrator iterates over; canonical output column order is
derived from it.
"""

from __future__ import annotations

from .adobe import AdobeSource
from .base import InflationSource, SourceConfig, SourceUnavailable
from .bls import BLSSource
from .fred import FREDSource
from .pricestats import PriceStatsSource

# Registry order == canonical column order in inflation-sources.csv.
#
# Truflation was evaluated but intentionally excluded: its US CPI feed is behind
# a paid API with no free/keyless tier, and the cost is not justified here. The
# research (real endpoint + auth) is preserved in the README so it can be added
# back later if that changes.
SOURCES: list[InflationSource] = [
    BLSSource(),
    FREDSource(),
    AdobeSource(),
    PriceStatsSource(),
]

# Flattened canonical list of every column any source can emit, in order.
CANONICAL_COLUMNS: list[str] = [col for src in SOURCES for col in src.columns]

__all__ = [
    "SOURCES",
    "CANONICAL_COLUMNS",
    "InflationSource",
    "SourceConfig",
    "SourceUnavailable",
    "BLSSource",
    "FREDSource",
    "AdobeSource",
    "PriceStatsSource",
]
