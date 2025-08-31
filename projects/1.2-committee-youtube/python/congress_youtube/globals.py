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
    "106": {
        "congress_began": "January 3, 1999",
        "congress_ended": "January 3, 2001",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 6, 1999",
                "end": "November 22, 1999",
            },
            {
                "name": "2nd session",
                "start": "January 24, 2000",
                "end": "December 15, 2000",
            },
        ],
    },
    "107": {
        "congress_began": "January 3, 2001",
        "congress_ended": "January 3, 2003",
        "senate_control": "Democratic / Republican / Democratic",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2001",
                "end": "December 20, 2001",
                "senate_control": "Democratic / Republican",
            },
            {
                "name": "2nd session",
                "start": "January 23, 2002",
                "end": "November 22, 2002",
                "senate_control": "Republican",
            },
        ],
    },
    "108": {
        "congress_began": "January 3, 2003",
        "congress_ended": "January 3, 2005",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 7, 2003",
                "end": "December 9, 2003",
            },
            {
                "name": "2nd session",
                "start": "January 20, 2004",
                "end": "December 8, 2004",
            },
        ],
    },
    "109": {
        "congress_began": "January 3, 2005",
        "congress_ended": "January 3, 2007",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 4, 2005",
                "end": "December 22, 2005",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2006",
                "end": "December 9, 2006",
            },
        ],
    },
    "110": {
        "congress_began": "January 3, 2007",
        "congress_ended": "January 3, 2009",
        "senate_control": "Democratic",
        "house_control": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 4, 2007",
                "end": "December 19, 2007",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2008",
                "end": "January 3, 2009",
            },
        ],
    },
    "111": {
        "congress_began": "January 3, 2009",
        "congress_ended": "January 3, 2011",
        "senate_control": "Democratic",
        "house_control": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 6, 2009",
                "end": "December 24, 2009",
            },
            {
                "name": "2nd session",
                "start": "January 5, 2010",
                "end": "December 22, 2010",
            },
        ],
    },
    "112": {
        "congress_began": "January 3, 2011",
        "congress_ended": "January 3, 2013",
        "senate_control": "Democratic",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 5, 2011",
                "end": "January 3, 2012",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2012",
                "end": "January 3, 2013",
            },
        ],
    },
    "113": {
        "congress_began": "January 3, 2013",
        "congress_ended": "January 3, 2015",
        "senate_control": "Democratic",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2013",
                "end": "December 26, 2013",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2014",
                "end": "December 16, 2014",
            },
        ],
    },
    "114": {
        "congress_began": "January 3, 2015",
        "congress_ended": "January 3, 2017",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 6, 2015",
                "end": "December 18, 2015",
            },
            {
                "name": "2nd session",
                "start": "January 4, 2016",
                "end": "January 3, 2017",
            },
        ],
    },
    "115": {
        "congress_began": "January 3, 2017",
        "congress_ended": "January 3, 2019",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2017",
                "end": "January 3, 2018",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2018",
                "end": "January 3, 2019",
            },
        ],
    },
    "116": {
        "congress_began": "January 3, 2019",
        "congress_ended": "January 3, 2021",
        "senate_control": "Republican",
        "house_control": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2019",
                "end": "January 3, 2020",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2020",
                "end": "January 3, 2021",
            },
        ],
    },
    "117": {
        "congress_began": "January 3, 2021",
        "congress_ended": "January 3, 2023",
        "senate_control": "Democratic",
        "house_control": "Democratic",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2021",
                "end": "January 3, 2022",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2022",
                "end": "January 3, 2023",
            },
        ],
    },
    "118": {
        "congress_began": "January 3, 2023",
        "congress_ended": "January 3, 2025",
        "senate_control": "Democratic",
        "house_control": "Republican",
        "sessions": [
            {
                "name": "1st session",
                "start": "January 3, 2023",
                "end": "January 3, 2024",
            },
            {
                "name": "2nd session",
                "start": "January 3, 2024",
                "end": "January 3, 2025",
            },
        ],
    },
    "119": {
        "congress_began": "January 3, 2025",
        "congress_ended": "January 3, 2027",
        "senate_control": "Republican",
        "house_control": "Republican",
        "sessions": [
            {"name": "1st session", "start": "January 3, 2025", "end": "present"}
        ],
    },
}
