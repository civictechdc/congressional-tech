"""Retained SQLite stages for an explicitly requested viewer rendering upgrade."""

from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import sqlite3

from congress_shared.custody import (
    canonical_json_bytes as encoded,
    copy_checked,
    file_identity,
)


class RendererState:
    """Retained SQLite state for an explicitly requested viewer rendering upgrade.

    Maintains intermediate rendering stages across worker restarts without
    ever publishing or selecting unverified release candidates.

    Schema:
        - build(binding, created):
            Stores the canonical JSON input binding and the initial UTC timestamp.
            Guarantees on resume that the renderer configuration has not drifted.
        - progress(task, result):
            Caches the canonical JSON output of completed idempotent rendering
            tasks (keyed by task name). Prevents re-running costly stages.
        - assets(path, bytes, sha256):
            Tracks verified retained publication assets with exact byte lengths
            and SHA-256 digests.
        - discarded(path, bytes, sha256):
            Crash-safe two-phase deletion journal. Deletions are committed to
            this table before files are unlinked, guaranteeing idempotence across
            unexpected process termination.
    """

    def __init__(self, target, binding, *, resume=False, event=None, cache_kib=8192):
        self.target = Path(target)
        self.root = self.target.with_name(self.target.name + ".renderer-upgrade")
        self.event = event
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise ValueError("Invalid renderer upgrade staging directory")
        if resume:
            stages_db = self.root / "stages.sqlite"
            if stages_db.is_symlink() or not stages_db.is_file():
                raise ValueError("Renderer upgrade has no retained stages")
        else:
            self.root.mkdir(parents=True, exist_ok=False)
        self.db = sqlite3.connect(self.root / "stages.sqlite")
        try:
            self.db.executescript(f"""PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;
                PRAGMA cache_size=-{cache_kib};
                CREATE TABLE IF NOT EXISTS build(binding TEXT NOT NULL,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS progress(task TEXT PRIMARY KEY,result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(path TEXT PRIMARY KEY,bytes INTEGER,sha256 TEXT);
                CREATE TABLE IF NOT EXISTS discarded(path TEXT PRIMARY KEY,bytes INTEGER,sha256 TEXT);""")
            saved = self.db.execute("SELECT binding,created FROM build").fetchall()
            raw = encoded(binding).decode()
            if resume:
                if len(saved) != 1 or saved[0][0] != raw:
                    raise ValueError("Renderer upgrade inputs changed")
                self.created = saved[0][1]
            else:
                self.created = datetime.now(timezone.utc).isoformat()
                self.db.execute("INSERT INTO build VALUES (?,?)", (raw, self.created))
                self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def _path(self, relative, expected):
        if (
            not isinstance(relative, str)
            or not isinstance(expected.get("sha256"), str)
            or len(expected["sha256"]) != 64
            or type(expected.get("bytes")) is not int
            or expected["bytes"] < 0
        ):
            raise ValueError("Invalid retained renderer asset identity")
        name = PurePosixPath(relative)
        if (
            name.is_absolute()
            or ".." in name.parts
            or str(name) != relative
            or relative != "manifest.json"
            and not relative.startswith("releases/")
        ):
            raise ValueError("Invalid retained renderer asset path")
        path = self.target / relative
        if path.is_symlink() or not path.resolve().is_relative_to(
            self.target.resolve()
        ):
            raise ValueError("Invalid retained renderer asset path")
        if relative != "manifest.json" and relative.split("/")[1:3] != [
            expected["sha256"][:32],
            expected["sha256"][32:],
        ]:
            raise ValueError("Retained renderer asset address changed")
        return path

    def publish_asset(self, source, destination, *, identity, key):
        # The maintained copier links only complete bytes into publication.
        # Its diagnostic partial stays private across every worker-loss window.
        return copy_checked(
            source,
            destination,
            size=identity["bytes"],
            expected=identity,
            key=key,
            exclusive=True,
            partial_directory=self.root,
        )

    def remember(self, relative, identity):
        self._path(relative, identity)
        self.db.execute(
            "INSERT INTO assets VALUES (?,?,?) ON CONFLICT(path) DO UPDATE "
            "SET bytes=excluded.bytes,sha256=excluded.sha256",
            (relative, identity["bytes"], identity["sha256"]),
        )

    def restore(self, assets):
        for relative, size, digest in self.db.execute("SELECT * FROM discarded"):
            expected = dict(bytes=size, sha256=digest)
            path = self._path(relative, expected)
            if path.exists():
                if file_identity(path) != expected:
                    raise ValueError("Discarded renderer asset changed")
                path.unlink()
        self.db.execute("DELETE FROM discarded")
        self.db.commit()
        for relative, size, digest in self.db.execute("SELECT * FROM assets"):
            expected = dict(bytes=size, sha256=digest)
            path = self._path(relative, expected)
            if not path.is_file():
                raise ValueError("Retained renderer asset changed or disappeared")
            actual = file_identity(path)
            if actual != expected:
                raise ValueError("Retained renderer asset changed")
            assets.identities[relative] = actual

    def discard(self, assets, paths):
        # Record exact owned deletions first. Restart completes them idempotently;
        # no directory scan or unrelated candidate file is deleted.
        for relative in paths:
            identity = assets.identities[relative]
            self.db.execute(
                "INSERT OR REPLACE INTO discarded VALUES (?,?,?)",
                (relative, identity["bytes"], identity["sha256"]),
            )
            self.db.execute("DELETE FROM assets WHERE path=?", (relative,))
        self.db.commit()
        for relative in paths:
            identity = assets.identities.pop(relative)
            self._path(relative, identity).unlink(missing_ok=True)
        self.db.execute("DELETE FROM discarded")
        self.db.commit()

    def result(self, task):
        row = self.db.execute(
            "SELECT result FROM progress WHERE task=?", (task,)
        ).fetchone()
        return row

    def run(self, task, action):
        saved = self.result(task)
        if saved is not None:
            return json.loads(saved[0])
        if self.event:
            self.event(dict(event="renderer_task_started", task=task))
        try:
            result = action()
            self.db.execute(
                "INSERT INTO progress VALUES (?,?)", (task, encoded(result).decode())
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        if self.event:
            self.event(dict(event="renderer_task_completed", task=task))
        return result
