"""Cli: gpo transcripts."""

import argparse
from pathlib import Path

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE

from congress_api.cli.common import positive
from congress_api.transcripts.gpo import main


def parse_args_and_run():
    parser = argparse.ArgumentParser(description="Download GPO hearing transcripts as plain text.")
    parser.add_argument("--out-dir", required=True, help="Local folder for <package_id>.txt files.")
    parser.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE)
    parser.add_argument("--congress", type=int, nargs="*", help="Only these congresses, e.g. 118 119.")
    parser.add_argument("--committee", nargs="*", help="Only these committee codes, e.g. hsvr00.")
    parser.add_argument("--chamber", nargs="*", choices=["house", "senate", "joint"])
    parser.add_argument("--package-ids", nargs="*")
    parser.add_argument("--nthreads", type=positive, default=4)
    args = parser.parse_known_args()[0]
    main(args.out_dir, args.gpo_path, args.congress, args.committee, args.chamber, args.package_ids, args.nthreads)


if __name__ == "__main__":
    parse_args_and_run()
