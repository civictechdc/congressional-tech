"""Collect every discoverable House committee event, across all available history.

The retained official committee directory supplies sites. Follow event listings,
archive filters, sitemaps and supported calendar APIs without downloading files.
Keep unmatched event pages, original bodies, request outcomes and pending work in
house-sites.json.gz. --limit bounds requests per run, not historical coverage;
subsequent runs resume the saved queue. XML fallback reads these same pages.
"""
import argparse
import datetime as dt
import signal
from pathlib import Path
from threading import Event

from congress_api.acquisition.house_sites import main
from congress_api.cli.common import nonnegative, positive


def parse_args_and_run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--committees', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--site', action='append', help='official hostname; otherwise visit every directory site')
    parser.add_argument('--retry-requests', type=Path, help='JSON list of saved {site, request} failures or unavailable observations; no seeds or new discovery; use the same file to resume')
    parser.add_argument('--limit', type=nonnegative, help='request budget; preserve the queue for continuation')
    parser.add_argument('--refresh-limit', type=nonnegative, default=450)
    parser.add_argument('--workers', type=positive, default=8, help='concurrent committee requests (1–32); at most one per committee')
    parser.add_argument('--requests-per-second', type=positive, help='total top-level HTTP attempts/sec across committees, including retries; host pacing still applies')
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reparse', action='store_true', help='with --offline, rebuild readings from retained bodies; stop live collection first')
    parser.add_argument('--zyte', action='store_true')
    parser.add_argument('--zyte-fallback', action='store_true', help='try direct first, then one Zyte attempt on failure; retain both outcomes')
    args = parser.parse_args(argv)
    stop = Event()
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        main(**vars(args), stop=stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if stop.is_set():
        raise SystemExit(2)


if __name__ == '__main__':
    parse_args_and_run()
