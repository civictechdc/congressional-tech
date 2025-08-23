from pathlib import Path
from argparse import ArgumentParser

DEFAULT_TINYDB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "congress_youtube_db.json"
)
DEFAULT_CHANNELS_CSV = Path(__file__) / "youtube" / "youtube-accounts.csv"


def add_global_args(parser: ArgumentParser) -> None:
    """Add shared arguments to an argparser for re-use throughout different modules."""

    parser.add_argument(
        "--tinydb_path",
        type=str,
        default=DEFAULT_TINYDB_PATH,
        help="Path to the TinyDB database json file.",
    )
