"""Persistent opaque IDs; source observation keys are distinct from domain IDs."""
from collections import OrderedDict
from collections.abc import MutableMapping
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

_SPILL_THRESHOLD_BYTES = 4 * 1024 * 1024
_BATCH_SIZE = 8192
_CACHE_SIZE = 4096


class _Released:
    """Stands in for staged values: a later lookup is a bug, never an allocation."""

    def _closed(self, *args):
        raise RuntimeError("The ID registry was staged for saving; allocation is closed")

    __contains__ = __getitem__ = __setitem__ = get = _closed

    def close(self):
        pass


class _SpilledIdDict(MutableMapping):
    """Disk-backed SQLite WITHOUT ROWID mapping for multi-hundred-MB ids.json files."""

    def __init__(self, source_path: Path):
        fd, db_path = tempfile.mkstemp(prefix="explorer-ids-", suffix=".sqlite")
        os.close(fd)
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=OFF")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA temp_store=FILE")
        self._conn.execute("PRAGMA locking_mode=EXCLUSIVE")
        self._conn.execute("PRAGMA cache_size=-16384")
        self._conn.execute(
            "CREATE TABLE ids (k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID"
        )
        self._pending: dict[str, str] = {}
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._load_streaming(source_path)

    def _load_streaming(self, source_path: Path) -> None:
        batch: list[tuple[str, str]] = []
        with source_path.open("r", encoding="utf-8") as stream:
            first_line = stream.readline()
            if not first_line:
                return
            stripped_first = first_line.strip()
            if stripped_first == "{":
                for raw_line in stream:
                    line = raw_line.strip()
                    if not line or line == "}":
                        continue
                    if line.endswith(","):
                        line = line[:-1]
                    colon = line.rfind('": "')
                    if colon != -1 and line.startswith('"') and line.endswith('"'):
                        k = json.loads(line[: colon + 1])
                        v = line[colon + 4 : -1]
                    else:
                        k, v = next(iter(json.loads("{" + line + "}").items()))
                    batch.append((k, v))
                    if len(batch) >= _BATCH_SIZE:
                        self._flush_batch(batch)
                        batch.clear()
                if batch:
                    self._flush_batch(batch)
                    batch.clear()
            else:
                stream.seek(0)
                data = json.load(stream)
                for k, v in data.items():
                    batch.append((k, v))
                    if len(batch) >= _BATCH_SIZE:
                        self._flush_batch(batch)
                        batch.clear()
                if batch:
                    self._flush_batch(batch)
                    batch.clear()

    def _flush_batch(self, batch: list[tuple[str, str]]) -> None:
        self._conn.execute("BEGIN")
        self._conn.executemany(
            "INSERT OR REPLACE INTO ids (k, v) VALUES (?, ?)", batch
        )
        self._conn.execute("COMMIT")

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        self._flush_batch(list(self._pending.items()))
        self._pending.clear()

    def _remember(self, key: str, value: str) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)

    def __getitem__(self, key: str) -> str:
        if key in self._pending:
            return self._pending[key]
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        row = self._conn.execute("SELECT v FROM ids WHERE k = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        val = row[0]
        self._remember(key, val)
        return val

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: str, value: str) -> None:
        self._pending[key] = value
        self._remember(key, value)
        if len(self._pending) >= _BATCH_SIZE:
            self._flush_pending()

    def __delitem__(self, key: str) -> None:
        self._flush_pending()
        self._cache.pop(key, None)
        cur = self._conn.execute("DELETE FROM ids WHERE k = ?", (key,))
        if cur.rowcount == 0:
            raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self._pending or key in self._cache:
            return True
        row = self._conn.execute("SELECT 1 FROM ids WHERE k = ?", (key,)).fetchone()
        return row is not None

    def __iter__(self):
        self._flush_pending()
        for (k,) in self._conn.execute("SELECT k FROM ids ORDER BY k"):
            yield k

    def __len__(self) -> int:
        self._flush_pending()
        row = self._conn.execute("SELECT count(*) FROM ids").fetchone()
        return int(row[0]) if row else 0

    def iter_sorted_items(self):
        self._flush_pending()
        yield from self._conn.execute("SELECT k, v FROM ids ORDER BY k")

    def close(self) -> None:
        if getattr(self, "_conn", None) is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if getattr(self, "_db_path", None) is not None:
            self._db_path.unlink(missing_ok=True)
            self._db_path = None

    def __del__(self):
        self.close()


class IdRegistry:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            self.values = {}
        elif self.path.stat().st_size >= _SPILL_THRESHOLD_BYTES:
            self.values = _SpilledIdDict(self.path)
        else:
            self.values = json.loads(self.path.read_text())
        self.staged = None  # The written registry, once stage() has released it.

    def __call__(self, kind, key):
        # JSON encoding avoids collisions when source keys contain separators.
        scoped = json.dumps([kind, key], ensure_ascii=False)
        existing_val = self.values.get(scoped)
        if existing_val is None:
            existing_val = str(uuid4())
            self.values[scoped] = existing_val
        return existing_val

    def existing(self, kind, key):
        """Inspect an identity without allocating an ID."""
        return self.values.get(json.dumps([kind, key], ensure_ascii=False))

    def alias(self, kind, key, existing_key):
        """Give a newly encountered source key an already retained identity.

        Existing keys never move. In particular, this cannot merge two records
        whose different public IDs have already been allocated.
        """
        target = self.existing(kind, existing_key)
        if target is None:
            return False
        scoped = json.dumps([kind, key], ensure_ascii=False)
        current = self.values.get(scoped)
        if current is not None:
            return current == target
        self.values[scoped] = target
        return True

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            if isinstance(self.values, _SpilledIdDict):
                items = self.values.iter_sorted_items()
            else:
                items = ((k, self.values[k]) for k in sorted(self.values))
            first = True
            for k, v in items:
                if first:
                    stream.write("{\n ")
                    first = False
                else:
                    stream.write(",\n ")
                stream.write(json.dumps(k, ensure_ascii=False))
                stream.write(": ")
                stream.write(json.dumps(v, ensure_ascii=False))
            if first:
                stream.write("{}\n")
            else:
                stream.write("\n}\n")
        return tmp

    def stage(self):
        """Write the registry beside ids.json and release it; allocation is over.

        The registry keeps every key ever allocated, so it grows with each
        re-keyed input snapshot (2.85M keys, 1.35 GB resident on 2026-10-17).
        Publication, the export's memory peak, allocates nothing. save() then
        renames the staged file, so ids.json still changes only after the
        publication is verified. Any later lookup fails instead of allocating.
        """
        staged = self._write()
        if isinstance(self.values, _SpilledIdDict):
            self.values.close()
        self.staged, self.values = staged, _Released()

    def discard(self):
        """Remove a staged registry whose publication did not complete."""
        if isinstance(self.values, _SpilledIdDict):
            self.values.close()
        if self.staged is not None:
            self.staged.unlink(missing_ok=True)

    def save(self):
        staged = self.staged or self._write()
        if isinstance(self.values, _SpilledIdDict):
            self.values.close()
        staged.replace(self.path)
        self.staged = None
