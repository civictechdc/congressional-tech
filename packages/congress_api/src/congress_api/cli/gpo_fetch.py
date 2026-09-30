"""Cli: gpo fetch."""

import argparse
from pathlib import Path

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE

from congress_api.acquisition.gpo import main


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Fetch metadata and transcript links for GPO hearing transcripts."
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_GPO_HEARINGS_FILE,
        help="Path to the output CSV (also used as the cache between runs).",
    )
    parser.add_argument(
        "--chambers",
        default="hsj",
        help="Which chambers to include: any of h (house), s (senate), j (joint).",
    )
    parser.add_argument(
        "--full-relist",
        action="store_true",
        help="List the whole collection instead of only recent changes (after widening filters).",
    )
    parser.add_argument(
        "--min-congress",
        type=int,
        default=None,
        help="Oldest congress to include (default: the oldest in congress_metadata.json).",
    )
    parser.add_argument(
        "--nthreads",
        type=int,
        default=4,
        help="Concurrent metadata downloads.",
    )

    parser.add_argument("--evidence-path", type=Path,
                        help="Gzip JSONL upstream XML/HTML evidence on pipeline-data; kept out of the CSV.")
    parser.add_argument("--refresh-limit", type=int, default=100,
                        help="Maximum unchanged rows to refresh for a newer parser (default: 100).")

    ## ignore the unknown args (e.g. --congress-api-key, read by the key loader)
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
