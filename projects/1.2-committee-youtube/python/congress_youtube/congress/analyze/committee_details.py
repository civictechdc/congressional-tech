from dataclasses import dataclass, field, asdict
from datetime import datetime
import os
from tinydb import TinyDB, Query
from typing import TypedDict, Literal, Dict, List, Optional

from ..api import congress_api_get
from ...globals import DEFAULT_TINYDB_DIR

DETAILS_TB = None


class DocCount(TypedDict):
    count: int
    url: str


class CommitteeEntry(TypedDict, total=False):
    name: str
    systemCode: str
    url: str


# Replaces: ## TODO: replace with typed dict (history)
class HistoryEntry(TypedDict, total=False):
    updateDate: str  # ISO-8601 string from API; keep as str here to mirror source


ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


class _TinyDBMemoizer:
    """Memoizes TinyDB instances per (tinydb_dir, chamber)."""

    def __init__(self) -> None:
        self._cache: Dict[tuple[str, str], TinyDB] = {}

    def get(self, tinydb_dir: str, chamber: Literal["house", "senate"]) -> TinyDB:
        if not os.path.isdir(tinydb_dir):
            raise OSError(f"{tinydb_dir} does not exist. Cannot create details tinydb")
        if chamber not in {"house", "senate"}:
            raise ValueError(
                f"Invalid chamber: {chamber}, must be one of: 'house', 'senate'"
            )
        key = (os.path.abspath(tinydb_dir), chamber)
        db = self._cache.get(key)
        if db is None:
            db = TinyDB(os.path.join(tinydb_dir, f"{chamber}-committee-details.json"))
            self._cache[key] = db
        return db


_DB_MEMO = _TinyDBMemoizer()


@dataclass(slots=True)
class CommitteeDetails:
    bills: Optional[DocCount] = field(default_factory=lambda: {"count": 0, "url": ""})
    communications: Optional[DocCount] = field(
        default_factory=lambda: {"count": 0, "url": ""}
    )
    reports: Optional[DocCount] = field(default_factory=lambda: {"count": 0, "url": ""})
    history: List[HistoryEntry] = field(default_factory=list)
    isCurrent: bool = False
    parent: Optional[CommitteeEntry] = None
    subcommittees: Optional[List[CommitteeEntry]] = None
    systemCode: str = ""
    ctype: str = ""
    # store as datetime in memory; serialize to string on write
    updateDate: datetime = field(default_factory=lambda: datetime.min)

    # ---- Persistence helpers ----
    def store(
        self,
        update: bool = False,
        tinydb_dir: str = DEFAULT_TINYDB_DIR,
        chamber: Literal["house", "senate"] = "house",
    ) -> None:
        """
        Insert/update this record in TinyDB.
        - When update=False and a record exists, skip (preserves current DB value).
        - When update=True, overwrite the stored fields with this instance.
        """
        db = _DB_MEMO.get(tinydb_dir=tinydb_dir, chamber=chamber)
        details_q = Query()
        payload = self.to_dict()

        if db.count(details_q.systemCode == self.systemCode) > 0:
            ## update the entry storing, it's already in the db
            if update:
                db.update(payload, details_q.systemCode == self.systemCode)
            else:
                ## skip storing, it's already in the db
                pass
        else:
            db.insert(payload)

    # ---- (De)serialization ----
    @staticmethod
    def _parse_dt(value: Optional[str | datetime]) -> datetime:
        if value is None:
            return datetime.min
        if isinstance(value, datetime):
            return value
        return datetime.strptime(value, ISO_FMT)

    @staticmethod
    def _format_dt(dt: datetime) -> str:
        return dt.strftime(ISO_FMT)

    def to_dict(self) -> Dict:
        """Controlled serialization (don't persist transient attrs / __dict__)."""
        d = asdict(self)
        d["updateDate"] = self._format_dt(self.updateDate)
        # map internal key back to API field name if needed elsewhere
        d["type"] = d.pop("ctype")
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> "CommitteeDetails":
        inst_data = dict(data)

        ## make a copy
        new_dict = {**inst_data}
        ## rename the "type" arg to "ctype" (committee type)
        if "type" in new_dict and "ctype" not in new_dict:
            new_dict["ctype"] = new_dict.pop("type")
        # parse updateDate to datetime in-memory
        if "updateDate" in new_dict:
            new_dict["updateDate"] = cls._parse_dt(new_dict["updateDate"])  # type: ignore[assignment]
        return cls(**new_dict)  # type: ignore[arg-type]

    @classmethod
    def from_system_code(cls, system_code):
        # Check if the committee is already in the memoized DB
        db = _DB_MEMO.get(
            DEFAULT_TINYDB_DIR, "house"
        )  # Assuming "house" or "senate" can be determined here
        details_q = Query()
        result = db.get(details_q.systemCode == system_code)
        if result:
            return cls.from_dict(result)
        else:
            ## explicitly return None
            return None

    @classmethod
    def from_spec(cls, chamber: str, system_code: str, api_key: str, force_fetch: bool):
        ## TODO: need to validate chamber with extracted logic
        endpoint = f"committee/{chamber}/{system_code}"

        if not force_fetch:
            ## attempt to load the instance from the tinydb
            inst = cls.from_system_code(system_code)
        else:
            ## manually set to None so we are forced to fetch it below
            inst = None

        if inst is None:
            # Fetch from the URL if not in DB
            details = congress_api_get(endpoint, pagination=False, api_key=api_key)[
                "committee"
            ]
            inst = cls.from_dict(details)
            inst.store(update=force_fetch)
        return inst
