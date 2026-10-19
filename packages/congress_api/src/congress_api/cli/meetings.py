"""Cli: meetings."""

import argparse
from pathlib import Path

from congress_shared.cli import configure_logging
from congress_shared.paths import DEFAULT_MEETINGS_FILE

from congress_api.cli.common import positive
from congress_api.acquisition.meetings import main


def parse_args_and_run():
    configure_logging()
    parser = argparse.ArgumentParser(description="Keep a local copy of House and joint committee meeting records.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MEETINGS_FILE)
    parser.add_argument("--nthreads", type=positive, default=5)
    args = parser.parse_known_args()[0]
    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
