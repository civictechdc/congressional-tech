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
    member_handles: list[str]


def _read_committee_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        return list(csv.DictReader(csvfile))


def _committee_metadata(rows):
    """Keep CSV order and literal handles as the committee cache keys."""
    committees = {}
    for row in rows:
        committees[row["systemCode"]] = {
            "name": row["committee"],
            "handles": [row["handle"]] + [h.strip() for h in row["secondary"].split(";") if h.strip()],
            "member_handles": [h.strip() for h in (row.get("member_channels") or "").split(";") if h.strip()],
        }
    return committees


def map_system_code_committee_handles(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> dict[str, YoutubeChannelMetadata]:
    return _committee_metadata(_read_committee_rows(csv_path))


def _channel_id_overrides(rows):
    channel_ids = {}
    for row in rows:
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


def get_channel_id_overrides(csv_path: Path = DEFAULT_CHANNELS_CSV) -> dict[str, str]:
    """Read optional stable IDs without changing literal handles or table names."""
    return _channel_id_overrides(_read_committee_rows(csv_path))


def load_committee_configuration(
    csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> tuple[dict[str, YoutubeChannelMetadata], dict[str, str]]:
    """One command owns one freshly read, validated configuration snapshot."""
    rows = _read_committee_rows(csv_path)
    return _committee_metadata(rows), _channel_id_overrides(rows)


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
