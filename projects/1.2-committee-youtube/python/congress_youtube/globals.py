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

DEFAULT_TINYDB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_CHANNELS_CSV = (
    Path(__file__).resolve().parent / "youtube" / "youtube-accounts.csv"
)
DEFAULT_YOUTUBE_REPORT_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "youtube_event_id_report.csv"
)


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


CONGRESS_METADATA = {
    106: {
        "start": "1999-01-03",
        "end": "2001-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "1999-01-06",
                "end": "1999-11-22",
            },
            {
                "name": "2nd session",
                "start": "2000-01-24",
                "end": "2000-12-15",
            },
        ],
    },
    107: {
        "start": "2001-01-03",
        "end": "2003-01-03",
        "senate": "Democratic / Republican / Democratic",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2001-01-03",
                "end": "2001-12-20",
                "senate": "Democratic / Republican",
            },
            {
                "name": "2nd session",
                "start": "2002-01-23",
                "end": "2002-11-22",
                "senate": "Republican",
            },
        ],
    },
    108: {
        "start": "2003-01-03",
        "end": "2005-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2003-01-07",
                "end": "2003-12-09",
            },
            {
                "name": "2nd session",
                "start": "2004-01-20",
                "end": "2004-12-08",
            },
        ],
    },
    109: {
        "start": "2005-01-03",
        "end": "2007-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2005-01-04",
                "end": "2005-12-22",
            },
            {
                "name": "2nd session",
                "start": "2006-01-03",
                "end": "2006-12-09",
            },
        ],
    },
    110: {
        "start": "2007-01-03",
        "end": "2009-01-03",
        "senate": "Democratic",
        "house": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "2007-01-04",
                "end": "2007-12-19",
            },
            {
                "name": "2nd session",
                "start": "2008-01-03",
                "end": "2009-01-03",
            },
        ],
    },
    111: {
        "start": "2009-01-03",
        "end": "2011-01-03",
        "senate": "Democratic",
        "house": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "2009-01-06",
                "end": "2009-12-24",
            },
            {
                "name": "2nd session",
                "start": "2010-01-05",
                "end": "2010-12-22",
            },
        ],
    },
    112: {
        "start": "2011-01-03",
        "end": "2013-01-03",
        "senate": "Democratic",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2011-01-05",
                "end": "2012-01-03",
            },
            {
                "name": "2nd session",
                "start": "2012-01-03",
                "end": "2013-01-03",
            },
        ],
    },
    113: {
        "start": "2013-01-03",
        "end": "2015-01-03",
        "senate": "Democratic",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2013-01-03",
                "end": "2013-12-26",
            },
            {
                "name": "2nd session",
                "start": "2014-01-03",
                "end": "2014-12-16",
            },
        ],
    },
    114: {
        "start": "2015-01-03",
        "end": "2017-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2015-01-06",
                "end": "2015-12-18",
            },
            {
                "name": "2nd session",
                "start": "2016-01-04",
                "end": "2017-01-03",
            },
        ],
    },
    115: {
        "start": "2017-01-03",
        "end": "2019-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2017-01-03",
                "end": "2018-01-03",
            },
            {
                "name": "2nd session",
                "start": "2018-01-03",
                "end": "2019-01-03",
            },
        ],
    },
    116: {
        "start": "2019-01-03",
        "end": "2021-01-03",
        "senate": "Republican",
        "house": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "2019-01-03",
                "end": "2020-01-03",
            },
            {
                "name": "2nd session",
                "start": "2020-01-03",
                "end": "2021-01-03",
            },
        ],
    },
    117: {
        "start": "2021-01-03",
        "end": "2023-01-03",
        "senate": "Democratic",
        "house": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "2021-01-03",
                "end": "2022-01-03",
            },
            {
                "name": "2nd session",
                "start": "2022-01-03",
                "end": "2023-01-03",
            },
        ],
    },
    118: {
        "start": "2023-01-03",
        "end": "2025-01-03",
        "senate": "Democratic",
        "house": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "2023-01-03",
                "end": "2024-01-03",
            },
            {
                "name": "2nd session",
                "start": "2024-01-03",
                "end": "2025-01-03",
            },
        ],
    },
    119: {
        "start": "2025-01-03",
        "end": "2027-01-03",
        "senate": "Republican",
        "house": "Republican",
        "sessions": [{"name": "1st session", "start": "2025-01-03", "end": "present"}],
    },
}
