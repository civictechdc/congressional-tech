"""Compact, publication-pinned issue history with lazy record loading.

Only issues and the typed references needed to inspect their evidence survive.
SQLite keeps traversal and migration queues on disk. Loading history does not
load a previous catalog or deserialize every historical record. Sources that
only history still cites are published and carried forward from this file.
"""
from collections import ChainMap
from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zlib

from typing import get_args
from pydantic import TypeAdapter, ValidationError

from committee_meeting import SCHEMA_VERSION
from committee_meeting.catalog import DomainRecord, _references
from committee_meeting.provenance import SourceRecord
from committee_meeting.publication import SchemaVersion


FORMAT_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = frozenset(get_args(SchemaVersion)) | {SCHEMA_VERSION}
_RECORD = TypeAdapter(SourceRecord | DomainRecord)


def _path(state_dir, publication_id):
    if not isinstance(publication_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", publication_id):
        raise ValueError("Invalid issue-history publication ID")
    return Path(state_dir) / "issue-history" / (publication_id + ".sqlite")


def _connect(path, *, readonly=False):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) if readonly else sqlite3.connect(path)
    connection.execute("PRAGMA cache_size=-2048")
    connection.execute("PRAGMA temp_store=FILE")
    if readonly:
        connection.execute("PRAGMA query_only=ON")
    return connection


def _initialize(connection):
    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID")
    connection.execute("CREATE TABLE records (kind TEXT, id TEXT, payload BLOB, PRIMARY KEY (kind, id)) WITHOUT ROWID")
    connection.execute("CREATE INDEX pending ON records(kind, id) WHERE payload IS NULL")


def _decode(payload):
    try:
        raw = zlib.decompress(payload)
    except zlib.error as error:
        raise ValueError(f"Invalid issue-history record: {error}") from None
    try:
        return _RECORD.validate_json(raw)
    except ValidationError:
        try:
            import json
            data = json.loads(raw)
            if isinstance(data, dict):
                kind = data.get("kind")
                if (
                    kind == "appearance"
                    and isinstance(data.get("affiliation"), dict)
                    and data["affiliation"].get("organization") is None
                ):
                    data["affiliation"].pop("organization", None)
                elif kind == "material_link" and data.get("extent") is None:
                    data.pop("extent", None)
            return _RECORD.validate_python(data)
        except (ValidationError, ValueError) as error:
            detail = error.errors(include_input=False, include_url=False)[:10] if isinstance(error, ValidationError) else str(error)
            raise ValueError(f"Invalid issue-history record: {detail}") from None


class IssueHistory(Mapping):
    """Read-only record mapping. Each lookup validates only the requested row."""

    def __init__(self, path):
        self.path = Path(path)
        self.connection = _connect(self.path, readonly=True)

    def __getitem__(self, key):
        row = self.connection.execute("SELECT payload FROM records WHERE kind=? AND id=?", key).fetchone()
        if row is None or row[0] is None:
            raise KeyError(key)
        return _decode(row[0])

    def __contains__(self, key):
        return self.connection.execute("SELECT 1 FROM records WHERE kind=? AND id=?", key).fetchone() is not None

    def __iter__(self):
        yield from self.connection.execute("SELECT kind, id FROM records ORDER BY kind, id")

    def __len__(self):
        return self.connection.execute("SELECT count(*) FROM records").fetchone()[0]

    def iter_issues(self):
        for (payload,) in self.connection.execute("SELECT payload FROM records WHERE kind='data_issue' ORDER BY id"):
            yield _decode(payload)

    def iter_records(self, kind, ids):
        """Decode the records of one kind whose IDs are in ``ids``, in ID order.

        The primary key orders this scan; other rows are skipped undecoded.
        """
        for identity, payload in self.connection.execute("SELECT id, payload FROM records WHERE kind=? ORDER BY id", (kind,)):
            if identity in ids:
                yield _decode(payload)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class RetainedSources(Mapping):
    """Source observations that only retained issue history still cites.

    The assembled catalog holds current sources. These stay in the previous
    history file and are published from it: membership is an in-memory ID set,
    and lookups and the ordered scan decode one row at a time.
    """

    def __init__(self, history=None, ids=frozenset()):
        self.history, self.ids = history, ids  # ids: a set of source IDs held in history.

    def __contains__(self, key):
        return key[0] == "source_record" and key[1] in self.ids

    def __getitem__(self, key):
        if key not in self:
            raise KeyError(key)
        return self.history[key]

    def __iter__(self):
        return (("source_record", identity) for identity in sorted(self.ids))

    def __len__(self):
        return len(self.ids)

    def records(self):
        """Yield every retained source in ascending ID order, as write_tables requires."""
        if isinstance(self.history, IssueHistory):
            yield from self.history.iter_records("source_record", self.ids)
        else:
            for key in self:
                yield self.history[key]


def load_history(state_dir, publication_id):
    """Return None when migration is needed; reject incompatible history."""
    path = _path(state_dir, publication_id)
    if not path.exists():
        return None
    history = IssueHistory(path)
    try:
        metadata = dict(history.connection.execute("SELECT key, value FROM metadata"))
        if (
            metadata.get("format_version") != FORMAT_VERSION
            or metadata.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
            or metadata.get("publication_id") != publication_id
        ):
            raise ValueError("Issue history format, schema or publication ID does not match")
        if history.connection.execute("SELECT 1 FROM records WHERE payload IS NULL LIMIT 1").fetchone():
            raise ValueError("Issue history has incomplete records")
    except BaseException:
        history.close()
        raise
    return history


def _issues(records):
    if hasattr(records, "iter_issues"):
        yield from records.iter_issues()
    elif isinstance(records, ChainMap):
        # ChainMap.__iter__ constructs a union of all keys. Avoid that allocation
        # for the large, disjoint source/domain dictionaries used by assembly.
        # Iterate keys: a disk-backed mapping decodes only the issues it yields.
        for index, mapping in enumerate(records.maps):
            for key in mapping:
                if key[0] == "data_issue" and not any(key in earlier for earlier in records.maps[:index]):
                    yield mapping[key]
    else:
        for key, record in records.items():
            if key[0] == "data_issue":
                yield record


def save_history(state_dir, publication_id, records):
    """Atomically save issue/reference closure from an already validated mapping.

    Call after all issue decisions, before updating the publication pointer.
    Snapshots are immutable, so a failed publication cannot overwrite the prior
    history. ``ChainMap(assembly.records, assembly.sources, assembly.retained)``
    needs no new index; retained sources are decoded one at a time from the
    previous history, which must stay open until this returns.
    """
    if not isinstance(records, Mapping):
        raise TypeError("save_history requires a record mapping; use migrate_history for iterables")
    target = _path(state_dir, publication_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".building-", suffix=".sqlite", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    connection = _connect(temporary)
    try:
        _initialize(connection)
        for issue in _issues(records):
            connection.execute("INSERT OR IGNORE INTO records(kind,id) VALUES (?,?)", (issue.kind, issue.id))
        while (pending := connection.execute("SELECT kind,id FROM records WHERE payload IS NULL LIMIT 1").fetchone()) is not None:
            try:
                record = records[pending]
            except KeyError:
                raise ValueError(f"Issue history is missing {pending[0]}/{pending[1]}") from None
            if (record.kind, record.id) != pending:
                raise ValueError(f"Issue history mapping key differs from record: {pending}")
            connection.execute("UPDATE records SET payload=? WHERE kind=? AND id=?",
                               (zlib.compress(record.model_dump_json().encode(), level=1), *pending))
            connection.executemany("INSERT OR IGNORE INTO records(kind,id) VALUES (?,?)",
                                   ((reference.kind, reference.id) for reference in _references(record)))
        digest = hashlib.sha256()
        for kind, identity, payload in connection.execute("SELECT kind,id,payload FROM records ORDER BY kind,id"):
            for value in (kind.encode(), identity.encode(), zlib.decompress(payload)):
                digest.update(len(value).to_bytes(8, "big"))
                digest.update(value)
        metadata = {"format_version": FORMAT_VERSION, "schema_version": SCHEMA_VERSION,
                    "publication_id": publication_id, "content_sha256": digest.hexdigest()}
        connection.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", metadata.items())
        connection.commit()
        connection.close()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if target.exists():
            with load_history(state_dir, publication_id) as existing:
                prior_digest = existing.connection.execute("SELECT value FROM metadata WHERE key='content_sha256'").fetchone()
                if prior_digest != (metadata["content_sha256"],):
                    raise ValueError("An immutable issue-history publication already has different records")
        else:
            temporary.replace(target)
        return target
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def migrate_history(state_dir, publication_id, records):
    """Stream old source/detail partitions through disk, retaining issue closure.

    ``records`` yields individual JSON dictionaries or typed models. This helper
    never loads the old Catalog; the caller verifies partition hashes first.
    """
    directory = _path(state_dir, publication_id).parent
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".migration-", suffix=".sqlite", dir=directory)
    os.close(descriptor)
    staging = Path(name)
    connection = _connect(staging)
    try:
        _initialize(connection)
        for value in records:
            try:
                record = _RECORD.validate_python(value)
            except ValidationError as error:
                raise ValueError(str(error.errors(include_input=False, include_url=False)[:10])) from None
            payload = zlib.compress(record.model_dump_json().encode(), level=1)
            try:
                connection.execute("INSERT INTO records VALUES (?,?,?)", (record.kind, record.id, payload))
            except sqlite3.IntegrityError:
                previous = connection.execute("SELECT payload FROM records WHERE kind=? AND id=?", (record.kind, record.id)).fetchone()[0]
                if previous != payload:
                    raise ValueError(f"Conflicting historical record: {record.kind}/{record.id}") from None
        connection.commit()
        connection.close()
        with IssueHistory(staging) as previous:
            return save_history(state_dir, publication_id, previous)
    finally:
        connection.close()
        staging.unlink(missing_ok=True)
