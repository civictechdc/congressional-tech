import csv
import json
import logging
import re
from pathlib import Path
from tinydb import TinyDB
from tinydb.storages import Storage
from typing import TypedDict

from congress_shared.custody import write_atomic_bytes
from congress_shared.resources import DEFAULT_CHANNELS_CSV
from congress_shared.paths import DEFAULT_TINYDB_DIR


class AtomicJSONStorage(Storage):
    """Keep the previous capture intact until its replacement is fully written."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, data):
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        write_atomic_bytes(self.path, encoded, temp_mode="unique")


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

            ## "secondary" holds any other channels, separated by semicolons
            handles = [handle] + [h.strip() for h in secondary.split(";") if h.strip()]
            ## "member_channels": personal channels of chairs that hold a committee's
            ##  hearings (e.g. a select committee's chair). They're fetched and used for
            ##  matching hearings, but not counted as committee videos in the report.
            members = [h.strip() for h in (row.get("member_channels") or "").split(";") if h.strip()]
            system_code_mapper[systemCode] = {
                "name": name,
                "handles": handles,
                "member_handles": members,
            }
    return system_code_mapper


def get_channel_id_overrides(csv_path: Path = DEFAULT_CHANNELS_CSV) -> dict[str, str]:
    """Read optional stable IDs without changing literal handles or table names."""
    channel_ids = {}
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        for row in csv.DictReader(csvfile):
            configured = json.loads(row.get("channel_ids") or "{}")
            handles = {
                handle.strip()
                for column in ("handle", "secondary", "member_channels")
                for handle in (row.get(column) or "").split(";")
                if handle.strip()
            }
            if not isinstance(configured, dict):
                raise ValueError("channel_ids must be a JSON object")
            for handle, channel_id in configured.items():
                if (
                    handle not in handles
                    or not isinstance(channel_id, str)
                    or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id)
                ):
                    raise ValueError(f"Invalid configured YouTube channel ID for {handle}")
                if handle in channel_ids and channel_ids[handle] != channel_id:
                    raise ValueError(f"Conflicting configured YouTube channel IDs for {handle}")
                channel_ids[handle] = channel_id
    return channel_ids


def get_all_committee_handles(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
    include_member_channels: bool = False,
) -> list[list[str]]:
    system_code_mapper = map_system_code_committee_handles(csv_path)
    return [
        meta["handles"] + (meta["member_handles"] if include_member_channels else [])
        for meta in system_code_mapper.values()
    ]


get_all_committee_handless = get_all_committee_handles


def get_all_committee_names(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
    with_index: bool = False,
) -> list[str] | list[tuple[str, int]]:
    system_code_mapper = map_system_code_committee_handles(csv_path)
    names = [meta["name"] for meta in system_code_mapper.values()]
    if with_index:
        ## pair each name with its row index so callers can build the
        ## programmatic ``youtube_{index:02d}.json`` filenames.
        return [(name, index) for index, name in enumerate(names)]
    return names


get_all_commitee_names = get_all_committee_names


def get_committee_index(
    committee_name: str, csv_path: Path = DEFAULT_CHANNELS_CSV
) -> int:
    committee_names: list[str] = get_all_committee_names(csv_path=csv_path)
    try:
        return committee_names.index(committee_name)
    except ValueError:
        raise IndexError(f"No committee name matched {committee_name} in {csv_path}")


def open_tinydb_for_committee(
    committee_name_or_index: str | int,
    csv_path: Path = DEFAULT_CHANNELS_CSV,
    tinydb_dir: Path = DEFAULT_TINYDB_DIR,
    assert_exists: bool = False,
    require_exists: bool | None = None,
) -> TinyDB:
    must_exist = assert_exists if require_exists is None else require_exists

    ## convert the name to an index
    if isinstance(committee_name_or_index, str):
        committee_name_or_index = get_committee_index(committee_name_or_index, csv_path)

    ## format the path
    path = tinydb_dir / "youtube_{index:02d}.json".format(index=committee_name_or_index)

    ## check for existence, when analyzing we want to break on
    ##  non-existent DBs, when fetching we want to create them
    if path.exists():
        logging.info(f"Using existing tinydb at {path}")
    elif must_exist:
        raise ValueError(
            f"No existing tinydb file for index {committee_name_or_index} at {path}"
        )
    return TinyDB(path, storage=AtomicJSONStorage)
