"""Cli: meetings."""

import argparse
from pathlib import Path

from congress_shared.globals import DEFAULT_MEETINGS_FILE

from congress_api.acquisition.meetings import main


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Keep a local copy of House and joint committee meeting records.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_MEETINGS_FILE)
    parser.add_argument("--nthreads", type=int, default=5)
    args = parser.parse_known_args()[0]
    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
