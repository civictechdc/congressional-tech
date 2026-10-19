"""Explicit shared command setup, with no import-time logging changes."""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from .paths import DEFAULT_TINYDB_DIR
from .resources import DEFAULT_CHANNELS_CSV


def configure_logging() -> None:
    """Retain the commands' INFO/stdout logging; respect existing root handlers."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(asctime)s : [%(name)s.%(funcName)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
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
