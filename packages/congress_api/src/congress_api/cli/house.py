"""house-meeting-records: fill House/joint meeting gaps from docs.house.gov.

Read the meeting export and GPO table, then meeting XML and witness-list XML
(page fallback). Write house_documents_found.csv, house_witnesses_found.csv and
house_amendments_found.csv to --output-dir. Keep parsed results, source URLs,
XML update-date, exact source bodies, Congress.gov updateDate, fetch date and confirmed absences in
--state-dir/house.json.gz. --seed-cache imports the research cache read-only.

Readers select from source inputs; the inventory is not an input. An attached
print discovered here can settle selection during this same pass. Changed and
new records are fetched first; at most --refresh-limit unchanged records are
refreshed per run, oldest checks first. --zyte is only a backfill option.
"""

import argparse
from pathlib import Path

from congress_api.acquisition.house import main
from congress_api.cli.common import nonnegative, source_args


def parse_args_and_run():
    p = argparse.ArgumentParser(description=__doc__)
    source_args(p)
    p.add_argument("--gpo-path", type=Path, required=True)
    p.add_argument("--committees", type=Path, help="retained committee snapshots; defaults beside meetings to congress_committees.jsonl.gz")
    p.add_argument("--failed-urls", type=Path, help="one known failed document URL per line; try committee pages for matching meetings")
    p.add_argument("--refresh-limit", type=nonnegative, default=400)
    p.add_argument("--limit", type=nonnegative, help="bound live meeting fetches; incomplete backfills fail")
    p.add_argument("--zyte", action="store_true", help="metered backfill through ZYTE_TOKEN")
    p.add_argument("--threads", type=int, help="workers: one directly, default 16 with --zyte")
    args = p.parse_args()
    args.failed_urls = [line.strip() for line in args.failed_urls.read_text().splitlines() if line.strip()] if args.failed_urls else []
    args.threads = args.threads if args.threads is not None else 16 if args.zyte else 1
    if args.threads < 1 or (args.threads > 1 and not args.zyte):
        p.error("Direct House requests use one worker; parallel backfills require --zyte")
    main(**vars(args))
