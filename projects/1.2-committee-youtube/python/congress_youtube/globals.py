from pathlib import Path
from argparse import ArgumentParser

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
