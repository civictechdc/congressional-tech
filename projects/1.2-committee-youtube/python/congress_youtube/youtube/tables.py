import csv
import logging
import os

from pathlib import Path
from tinydb import TinyDB
from typing import TypedDict

from ..globals import DEFAULT_CHANNELS_CSV, DEFAULT_TINYDB_DIR


class YoutubeChannelMetadata(TypedDict):
    name: str
    handles: list[str]


def map_system_code_committee_handles(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> dict[str, YoutubeChannelMetadata]:
    system_code_mapper = {}
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)

        for row in rows:
            ## unpack the row
            name = row["committee"]
            systemCode = row["systemCode"]
            handle = row["handle"]
            secondary = row["secondary"]

            handles = [handle] + [secondary] * (secondary != " ")
            system_code_mapper[systemCode] = {
                "name": name,
                "handles": handles,
            }
    return system_code_mapper


def get_all_committee_handless(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> list[list[str]]:
    system_code_mapper = map_system_code_committee_handles(csv_path)
    return [meta["handles"] for meta in system_code_mapper.values()]


def get_all_commitee_names(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> list[str]:
    system_code_mapper = map_system_code_committee_handles(csv_path)
    return [meta["name"] for meta in system_code_mapper.values()]


def get_committee_index(
    committee_name: str, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> int:
    committee_names: list[str] = get_all_commitee_names()
    index = committee_names.index(committee_name)
    if index == -1:
        raise IndexError(f"No committee name matched {committee_name} in {csv_path}")
    else:
        return index


def open_tinydb_for_committee(
    committee_name_or_index: str | int,
    csv_path: Path = DEFAULT_CHANNELS_CSV,
    tinydb_dir: Path = DEFAULT_TINYDB_DIR,
    assert_exists: bool = False,
) -> TinyDB:
    ## convert the name to an index
    if isinstance(committee_name_or_index, str):
        committee_name_or_index = get_committee_index(committee_name_or_index, csv_path)

    ## format the path
    path = tinydb_dir / "youtube_{index:02d}.json".format(index=committee_name_or_index)

    ## check for existence, when analyzing we want to break on
    ##  non-existent DBs, when fetching we want to create them
    if os.path.exists(path=path):
        logging.info(f"Using existing tinydb at {path}")
    elif assert_exists:
        raise ValueError(
            f"No existing tinydb file for index {committee_name_or_index} at {path}"
        )
    return TinyDB(path)
