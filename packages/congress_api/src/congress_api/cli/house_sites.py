"""Collect every discoverable House committee event, across all available history.

The retained official committee directory supplies sites. Follow event listings,
archive filters, sitemaps and supported calendar APIs without downloading files.
Keep unmatched event pages, original bodies, request outcomes and pending work in
house-sites.json.gz. --limit bounds requests per run, not historical coverage;
subsequent runs resume the saved queue. XML fallback reads these same pages.
"""
import argparse
import datetime as dt
from pathlib import Path

from congress_api.acquisition.house_sites import main
from congress_api.cli.common import nonnegative


def parse_args_and_run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--committees', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--site', action='append', help='official hostname; otherwise visit every directory site')
    parser.add_argument('--limit', type=nonnegative, help='request budget; preserve the queue for continuation')
    parser.add_argument('--refresh-limit', type=nonnegative, default=450)
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reparse', action='store_true', help='with --offline, rebuild readings from retained bodies; stop live collection first')
    parser.add_argument('--zyte', action='store_true')
    main(**vars(parser.parse_args()))


if __name__ == '__main__':
    parse_args_and_run()
