from pathlib import Path
import os
import csv
from tinydb import TinyDB
from tinydb.table import Table

from ..globals import DEFAULT_CHANNELS_CSV


def get_committee_handles(
    committee_name_or_index: str | int, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> str:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        if isinstance(committee_name_or_index, str):
            for row in reader:
                if row["committee"].lower() == committee_name_or_index.lower():
                    return [value for value in list(row.values())[1:]]
            raise ValueError(
                f"No handle found for committee: {committee_name_or_index}"
            )
        elif isinstance(committee_name_or_index, int):
            rows = list(reader)
            if 0 <= committee_name_or_index < len(rows):
                return list(rows[committee_name_or_index].values())[1:]
            else:
                raise IndexError(
                    f"Index out of bounds for committee list {csv_path} (length {len(rows)})."
                )


def open_tinydb_for_committee(
    committee_name_or_index: str | int, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> TinyDB:
    if isinstance(committee_name_or_index, int):
        path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "data"
            / "youtube{index}.json".format(index=committee_name_or_index)
        )
        if os.path.exists(path=path):
            return TinyDB(path)
        else:
            raise ValueError(f"No tinydb file at index {committee_name_or_index}")
    elif isinstance(committee_name_or_index, str):
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for index, row in enumerate(reader):
                if row["committee"].lower() == committee_name_or_index.lower():
                    path = (
                        Path(__file__).resolve().parent.parent.parent.parent
                        / "data"
                        / "youtube{index}.json".format(index=index)
                    )
                    if os.path.exists(path=path):
                        return TinyDB(path)
                    else:
                        raise ValueError(
                            f"No tinydb file for committee {committee_name_or_index}"
                        )


def get_all_commitee_names(
    csv_path: Path = DEFAULT_CHANNELS_CSV, with_index: bool = False
) -> list[str] | list[(str, int)]:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        committe_names = []
        for index, row in enumerate(reader):
            if with_index:
                committe_names.append((row["committee"], index))
            else:
                committe_names.append(row["committee"])
        return committe_names
