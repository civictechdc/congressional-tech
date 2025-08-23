from pathlib import Path
from argparse import ArgumentParser

default_records_path = (
    Path(__file__).resolve().parent.parent / "data" / "congress_youtube_db.json"
)
default_channels_csv = Path(__file__) / "youtube" / "youtube-accounts.csv"


def add_global_args(parser: ArgumentParser) -> None:
    """Add shared arguments to an argparser for re-use throughout different modules."""

    parser.add_argument(
        "--records_path",
        type=str,
        default=default_records_path,
        help="Path to the TinyDB database json file.",
    )
