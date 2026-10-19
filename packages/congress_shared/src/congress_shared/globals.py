"""Compatibility imports; new callers use resources, paths, or cli directly."""

from .cli import add_global_args, add_youtube_args
from .paths import (
    DEFAULT_GPO_HEARINGS_FILE,
    DEFAULT_HEARING_VIDEOS_FILE,
    DEFAULT_MEETINGS_FILE,
    DEFAULT_TINYDB_DIR,
    DEFAULT_YOUTUBE_REPORT_FILE,
)
from .resources import CONGRESS_METADATA, DEFAULT_CHANNELS_CSV, PACKAGE_DIR, RESOURCE_DATA_DIR

# Historical public name: callers may use this for bundled data or old outputs.
DATA_DIR = RESOURCE_DATA_DIR
