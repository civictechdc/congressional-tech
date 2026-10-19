"""Bundled reference data; importing this module only reads package resources."""

import json
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCE_DATA_DIR = PACKAGE_DIR / "data"
DEFAULT_CHANNELS_CSV = PACKAGE_DIR / "youtube" / "youtube-accounts.csv"

with open(RESOURCE_DATA_DIR / "congress_metadata.json", "r") as handle:
    CONGRESS_METADATA = json.load(handle)
