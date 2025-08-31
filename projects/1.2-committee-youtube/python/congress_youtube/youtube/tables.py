import csv
import logging
import os

from pathlib import Path
from tinydb import TinyDB

from ..globals import DEFAULT_CHANNELS_CSV, DEFAULT_TINYDB_DIR


def get_all_committee_handless(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> list[list[str]]:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
        ## return all the handles for all the committees, ignore the committee name
        return [list(rows[this_index].values())[1:] for this_index in range(len(rows))]


def get_committee_index(
    committee_name: str, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> int:
    committee_names = get_all_commitee_names(with_index=True)
    for this_committee_name in committee_names:
        if this_committee_name[0] == committee_name:
            return this_committee_name[1]
    raise IndexError(f"No committee name matched {committee_name} in {csv_path}")


def get_all_commitee_names(
    with_index: bool = False, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> list[str] | list[(str, int)]:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)
        if not with_index:
            ## return the entry in the first column alone
            return [list(this_row).values()[0] for this_row in rows]
        else:
            ## return the entry in the first column along with its index
            return [(list(this_row).values()[0], i) for i, this_row in enumerate(rows)]


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
        logging.log(f"Using existing tinydb at {path}")
    elif assert_exists:
        raise ValueError(
            f"No existing tinydb file for index {committee_name_or_index} at {path}"
        )
    return TinyDB(path)
