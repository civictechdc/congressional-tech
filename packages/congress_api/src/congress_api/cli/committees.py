"""Retain Congress-scoped committee lists plus full committee details and history."""

import argparse
import tempfile
from pathlib import Path

from congress_shared.cli import configure_logging
from congress_shared.auth import load_congress_api_key

from congress_api.acquisition.committees import collect
from congress_api.acquisition.public_release import PUBLIC_POINTER, release_meetings
from congress_api.retention.meetings import all_meetings


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', default=PUBLIC_POINTER,
                        help='Archive release pointer URL or local release directory holding meetings.parquet')
    parser.add_argument('--gpo-path', type=Path, help='Include Congresses represented by retained GPO documents')
    parser.add_argument('--output-path', type=Path, required=True)
    ## ignore the unknown args (e.g. --congress-api-key, read by the key loader)
    args = parser.parse_known_args()[0]
    with tempfile.TemporaryDirectory(prefix='congress-committees-release-') as work:
        try:
            meetings = release_meetings(args.release, work=Path(work) / 'release', scope=all_meetings)
        except ValueError as error:
            parser.exit(2, f'congress-committees: {error}\n')
    collect(meetings, output_path=args.output_path, gpo_path=args.gpo_path, api_key=load_congress_api_key())


def parse_args_and_run():
    """Console entry point; preserve main() for existing callers."""
    return main()


if __name__ == '__main__':
    main()
