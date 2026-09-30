"""Cli: common."""

import datetime as dt
from pathlib import Path


def source_args(parser):
    parser.add_argument("--meetings", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-cache", type=lambda s: Path(s).expanduser(), help="read-only research cache, for one-time import")
    parser.add_argument("--offline", action="store_true", help="require saved results; make no requests")
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.datetime.now(dt.UTC).date())


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise ValueError("must be nonnegative")
    return number


def positive(value):
    number = int(value)
    if number < 1:
        raise ValueError("must be positive")
    return number
