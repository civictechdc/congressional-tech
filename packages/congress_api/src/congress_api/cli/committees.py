"""Retain Congress-scoped committee lists plus full committee details and history."""

import argparse
from pathlib import Path

from congress_shared.auth import load_congress_api_key

from congress_api.acquisition.committees import collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meetings-path', type=Path, required=True)
    parser.add_argument('--gpo-path', type=Path, help='Include Congresses represented by retained GPO documents')
    parser.add_argument('--output-path', type=Path, required=True)
    ## ignore the unknown args (e.g. --congress-api-key, read by the key loader)
    args = parser.parse_known_args()[0]
    collect(**vars(args), api_key=load_congress_api_key())


def parse_args_and_run():
    """Console entry point; preserve main() for existing callers."""
    return main()


if __name__ == '__main__':
    main()
