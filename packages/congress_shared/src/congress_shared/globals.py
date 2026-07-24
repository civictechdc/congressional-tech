import json
import logging
import sys

from pathlib import Path
from argparse import ArgumentParser

## setup the logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(asctime)s : [%(name)s.%(funcName)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

## All paths are resolved relative to this shared package so the tooling finds
## its bundled config (committee CSV + congress metadata) no matter which
## package the console script lives in, and no matter the current directory.
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"

DEFAULT_TINYDB_DIR = DATA_DIR
DEFAULT_CHANNELS_CSV = PACKAGE_DIR / "youtube" / "youtube-accounts.csv"
DEFAULT_YOUTUBE_REPORT_FILE = DATA_DIR / "youtube_event_id_report.csv"


def add_global_args(parser: ArgumentParser) -> None:
    """Add shared arguments to an argparser for re-use throughout different modules."""

    parser.add_argument(
        "--tinydb_dir",
        type=lambda x: Path(x).expanduser().resolve(),
        default=DEFAULT_TINYDB_DIR,
        help="Path to the directory containing TinyDB database json files.",
    )


def add_youtube_args(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--channels-csv-path",  ## dashes are automatically converted to underscores
        type=str,
        default=DEFAULT_CHANNELS_CSV,
        help="Path to the CSV file mapping committee names to their YouTube handles",
    )


with open(DATA_DIR / "congress_metadata.json", "r") as handle:
    CONGRESS_METADATA = json.load(handle)
