"""Assemble source-owned records; retain disagreements and open issue history."""
from collections import ChainMap, Counter, OrderedDict, defaultdict
from collections.abc import Mapping, MutableMapping, Sequence
from heapq import merge
from operator import attrgetter
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import weakref
import zlib

from committee_meeting import Catalog
from committee_meeting.catalog import DomainRecord, _references
from committee_meeting.issues import DataIssue, IssueResolution
from committee_meeting.materials import representation_files
from committee_meeting.provenance import AlternativeValue, FieldEvidence, Method, Provenance, SourceRecord
from committee_meeting.common import Model, Ref
from pydantic import TypeAdapter, ValidationError

from .collector_labels import collector_placeholder_conflict
from .history import RetainedSources


def saved_copy_from_body_key(key, filename=None):
    """Digest and filename for a retained bodies/sha256 object, or nothing."""
    from congress_api.retention.body_keys import body_key_digest
    if not isinstance(key, str):
        return None
    digest = body_key_digest(key)
    if not digest:
        return None
    name = filename if isinstance(filename, str) and filename and not any(
        character in filename for character in "/\\") and not any(ord(character) < 32 or ord(character) == 127 for character in filename) else None
    return digest, name


def apply_saved_copies(assembly, filenames_path):
    """Set saved-copy fields from a document-filenames table before files are projected."""
    import pyarrow.parquet as pq
    by_url = {}
    for row in pq.read_table(filenames_path, columns=["source_url", "body_key", "filename"]).to_pylist():
        found = saved_copy_from_body_key(row.get("body_key"), row.get("filename"))
        url = row.get("source_url")
        if url and found and url not in by_url:
            by_url[url] = found
    for key in list(assembly.records):
        record = assembly.records[key]
        if record.kind != "representation" or record.saved_copy_sha256:
            continue
        match = next((by_url[location.url] for location in record.locations if location.url in by_url), None)
        if match is None:
            continue
        digest, name = match
        assembly.records[key] = record.model_copy(update={"saved_copy_sha256": digest, "saved_filename": name or record.saved_filename})


_DOMAIN_RECORD = TypeAdapter(DomainRecord)
# Several sources can each contribute identifiers, document groups, and files.
# Their union is the record; differing members are not disagreements.
_ACCUMULATED = frozenset({"identifiers", "source_document_groups", "files"})
_FIELD_NAMES = {}  # frozenset of names -> the one set every equal instance shares
_SHARED = set()  # ids of those sets; they live as long as this module


def _share_field_names(value):
    """Point every model in a validated record at one shared set of set-field names.

    Pydantic gives each instance its own ``__pydantic_fields_set__``. At 216-728
    bytes, those sets were nearly half of an assembled record's memory. Frozen
    models never add to theirs, model_copy copies it before an update, and
    revalidation reuses the input's set, so equal sets can be shared without
    changing any dump. Source payloads are JSON, not models, and are not walked.
    """
    if isinstance(value, Model):
        names = value.__pydantic_fields_set__
        if id(names) not in _SHARED:
            key = frozenset(names)
            shared = _FIELD_NAMES.get(key)
            if shared is None:
                shared = _FIELD_NAMES[key] = set(key)
                _SHARED.add(id(shared))
            object.__setattr__(value, "__pydantic_fields_set__", shared)
        for item in value.__dict__.values():
            if isinstance(item, (Model, tuple)):
                _share_field_names(item)
    elif isinstance(value, tuple):
        for item in value:
            if isinstance(item, (Model, tuple)):
                _share_field_names(item)


def validated(record):
    """Validate one record, including nested instances changed with model_copy."""
    try:
        record = SourceRecord.model_validate(record) if isinstance(record, SourceRecord) else _DOMAIN_RECORD.validate_python(record)
    except ValidationError as error:
        # A source payload can be large. Errors must not reproduce input data.
        raise ValueError(str(error.errors(include_input=False, include_url=False)[:10])) from None
    _share_field_names(record)
    return record


class _ValidatedRecords(MutableMapping):
    """Every replacement, including a caller's model_copy, crosses validation."""

    def __init__(self, *, sources=False):
        self._records = {}
        self._sources = sources

    def __getitem__(self, key):
        return self._records[key]

    def __setitem__(self, key, record):
        record = validated(record)
        if key != (record.kind, record.id) or isinstance(record, SourceRecord) != self._sources:
            raise ValueError("Assembly record does not match its identity or collection")
        self._records[key] = record

    def __delitem__(self, key):
        del self._records[key]

    def __iter__(self):
        return iter(self._records)

    def __len__(self):
        return len(self._records)


_SOURCE_CACHE_LIMIT = 256
_SOURCE_FLUSH_BATCH = 512


def _cleanup_spilled_sqlite(connection, path: Path):
    try:
        connection.close()
    except Exception:
        pass
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


class _SpilledSources(MutableMapping):
    """Disk-backed MutableMapping of ('source_record', id) -> SourceRecord.

    Keeps only lightweight (provider, input_snapshot_id) metadata and a small
    bounded LRU cache in Python RAM while spilling compressed source payloads to
    a temporary SQLite B-tree indexed by source ID.
    """

    def __init__(self):
        fd, name = tempfile.mkstemp(prefix=".explorer-sources-", suffix=".sqlite")
        os.close(fd)
        self._path = Path(name)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=OFF")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA temp_store=FILE")
        self._conn.execute("PRAGMA cache_size=-2048")
        self._conn.execute("CREATE TABLE sources (id TEXT PRIMARY KEY, payload BLOB NOT NULL) WITHOUT ROWID")
        self._meta: dict[str, tuple[str, str | None]] = {}
        self._pending: dict[str, bytes] = {}
        self._cache: OrderedDict[str, SourceRecord] = OrderedDict()
        self._finalizer = weakref.finalize(self, _cleanup_spilled_sqlite, self._conn, self._path)

    def _flush(self):
        if not self._pending:
            return
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO sources(id, payload) VALUES (?, ?)",
                self._pending.items(),
            )
        self._pending.clear()

    def _cache_put(self, record: SourceRecord):
        sid = record.id
        self._cache[sid] = record
        self._cache.move_to_end(sid)
        while len(self._cache) > _SOURCE_CACHE_LIMIT:
            self._cache.popitem(last=False)

    def get_by_id(self, sid: str) -> SourceRecord | None:
        if sid not in self._meta:
            return None
        cached = self._cache.get(sid)
        if cached is not None:
            self._cache.move_to_end(sid)
            return cached
        compressed = self._pending.get(sid)
        if compressed is None:
            row = self._conn.execute("SELECT payload FROM sources WHERE id=?", (sid,)).fetchone()
            if row is None:
                return None
            compressed = row[0]
        record = SourceRecord.model_validate_json(zlib.decompress(compressed))
        _share_field_names(record)
        self._cache_put(record)
        return record

    def provider_for_id(self, sid: str) -> str | None:
        meta = self._meta.get(sid)
        return meta[0] if meta is not None else None

    def __contains__(self, key):
        return isinstance(key, tuple) and len(key) == 2 and key[0] == "source_record" and key[1] in self._meta

    def __getitem__(self, key):
        if not (isinstance(key, tuple) and len(key) == 2 and key[0] == "source_record"):
            raise KeyError(key)
        record = self.get_by_id(key[1])
        if record is None:
            raise KeyError(key)
        return record

    def __setitem__(self, key, record):
        record = validated(record)
        if key != (record.kind, record.id) or not isinstance(record, SourceRecord):
            raise ValueError("Assembly record does not match its identity or collection")
        sid = record.id
        self._meta[sid] = (record.provider, record.input_snapshot_id)
        self._pending[sid] = zlib.compress(record.model_dump_json().encode(), level=1)
        self._cache_put(record)
        if len(self._pending) >= _SOURCE_FLUSH_BATCH:
            self._flush()

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        sid = key[1]
        del self._meta[sid]
        self._pending.pop(sid, None)
        self._cache.pop(sid, None)
        with self._conn:
            self._conn.execute("DELETE FROM sources WHERE id=?", (sid,))

    def __iter__(self):
        for sid in self._meta:
            yield ("source_record", sid)

    def __len__(self):
        return len(self._meta)

    def iter_ordered(self):
        self._flush()
        for (compressed,) in self._conn.execute("SELECT payload FROM sources ORDER BY id"):
            record = SourceRecord.model_validate_json(zlib.decompress(compressed))
            _share_field_names(record)
            yield record

    def close(self):
        self._pending.clear()
        self._cache.clear()
        self._finalizer()


class SpilledSourceSequence(Sequence):
    """Lazy, ID-sorted Sequence view over _SpilledSources for Catalog.sources."""

    is_id_sorted = True

    def __init__(self, spilled: _SpilledSources, extra: Mapping[str, SourceRecord] | None = None):
        self._spilled = spilled
        self._extra: dict[str, SourceRecord] = dict(extra) if extra else {}
        self._sorted_ids: tuple[str, ...] | None = None

    def source_ids(self):
        if not self._extra:
            return self._spilled._meta.keys()
        return self._spilled._meta.keys() | self._extra.keys()

    def get_by_id(self, sid: str) -> SourceRecord | None:
        if sid in self._extra:
            return self._extra[sid]
        return self._spilled.get_by_id(sid)

    def provider_for_id(self, sid: str) -> str | None:
        if sid in self._extra:
            return self._extra[sid].provider
        return self._spilled.provider_for_id(sid)

    def provider_counts(self) -> Counter:
        counts = Counter()
        for sid, (provider, _) in self._spilled._meta.items():
            if sid not in self._extra:
                counts[provider] += 1
        for record in self._extra.values():
            counts[record.provider] += 1
        return counts

    def input_snapshot_ids(self) -> set[str]:
        inputs = {inp for sid, (_, inp) in self._spilled._meta.items() if sid not in self._extra}
        inputs.update(record.input_snapshot_id for record in self._extra.values())
        return inputs

    def with_additional(self, sources) -> "SpilledSourceSequence":
        merged = dict(self._extra)
        for src in sources:
            src = validated(src)
            merged[src.id] = src
        return SpilledSourceSequence(self._spilled, merged)

    def as_mapping(self) -> Mapping[tuple[str, str], SourceRecord]:
        if not self._extra:
            return self._spilled
        return ChainMap({("source_record", sid): rec for sid, rec in self._extra.items()}, self._spilled)

    def __len__(self) -> int:
        if not self._extra:
            return len(self._spilled)
        return len(self.source_ids())

    def __iter__(self):
        if not self._extra:
            yield from self._spilled.iter_ordered()
            return
        spilled_iter = (r for r in self._spilled.iter_ordered() if r.id not in self._extra)
        extra_sorted = sorted(self._extra.values(), key=attrgetter("id"))
        yield from merge(spilled_iter, extra_sorted, key=attrgetter("id"))

    def __getitem__(self, index):
        if self._sorted_ids is None:
            self._sorted_ids = tuple(sorted(self.source_ids()))
        if isinstance(index, slice):
            return tuple(self.get_by_id(sid) for sid in self._sorted_ids[index])
        return self.get_by_id(self._sorted_ids[index])

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, (SpilledSourceSequence, tuple, list)):
            if len(self) != len(other):
                return False
            return all(a == b for a, b in zip(self, other))
        return NotImplemented


class Assembly:
    def __init__(self, previous=None, *, ids=None, now=None):
        self.sources = _SpilledSources()
        self.records = _ValidatedRecords()
        self.current = set()
        self.previous = previous
        self.retained = RetainedSources()  # Filled by finish() from the previous history.
        self.ids, self.now = ids, now

    def add(self, items):
        for item in items:
            into = self.sources if isinstance(item, SourceRecord) else self.records
            key = (item.kind, item.id)
            old = into.get(key)
            if old is not None and old != item and not isinstance(item, SourceRecord):
                citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *item.provenance.citations)}
                ev = item.provenance.model_copy(update={"citations": tuple(citations[k] for k in sorted(citations))})
                old_fields = {f.path: f for f in old.field_evidence}
                incoming_fields = {f.path: f for f in item.field_evidence}
                fields = dict(old_fields)
                for path, field in incoming_fields.items():
                    alternatives = {a.model_dump_json(): a for a in (
                        *(old_fields[path].alternatives if path in old_fields else ()), *field.alternatives)}
                    fields[path] = field.model_copy(update={"alternatives": tuple(alternatives.values())})
                updates = {}
                for name in type(item).model_fields:
                    if name in ("id", "kind", "provenance", "field_evidence"):
                        continue
                    before, after = getattr(old, name), getattr(item, name)
                    if before == after:
                        continue
                    if after is None or after == "" or after == ():
                        updates[name] = before
                        if "/" + name in old_fields:
                            fields["/" + name] = old_fields["/" + name]
                        else:
                            fields.pop("/" + name, None)
                    elif before is not None and before != "" and before != ():
                        if name in _ACCUMULATED:
                            updates[name] = tuple({v if isinstance(v, str) else v.model_dump_json(): v
                                                   for v in (*before, *after)}.values())
                        elif not isinstance(item, DataIssue):
                            if item.kind in ("occurrence", "meeting") and name == "access" and before == "unknown":
                                continue  # Filling absent access is not a source disagreement.
                            path = "/" + name
                            alternatives = list(fields[path].alternatives) if path in fields else []
                            alt = AlternativeValue(value=old.model_dump(mode="json")[name],
                                                   provenance=old_fields[path].selected if path in old_fields else old.provenance)
                            if all(a.value != alt.value for a in alternatives):
                                alternatives.append(alt)
                            selected = incoming_fields.get(path)
                            fields[path] = FieldEvidence(path=path, selected=selected.selected if selected else item.provenance,
                                                         alternatives=tuple(alternatives), selection_reason=selected.selection_reason if selected
                                                         else "Later record in deterministic source order; alternatives retained.")
                item = item.model_copy(update={**updates, "provenance": ev, "field_evidence": tuple(fields.values())})
            into[key] = item
            self.current.add(key)

    def _review_old_label_conflict(self, issue, previous):
        """Record a lasting correction to a known collector-generated conflict."""
        if (self.now is None or issue.status != "open" or issue.category != "conflicting"
                or issue.subject.kind != "material_version" or issue.field_path != "/label"
                or (issue.kind, issue.id) in self.current):
            return issue
        subject_key = (issue.subject.kind, issue.subject.id)
        current = self.records.get(subject_key)
        if current is not None and any(field.path == "/label" and field.alternatives for field in current.field_evidence):
            return issue  # A current disagreement needs its own review.
        previous_version = previous.get(subject_key)
        field = next((field for field in previous_version.field_evidence if field.path == "/label" and field.alternatives), None) if previous_version else None
        if field is None:
            return issue
        values = [previous_version.label, *(alternative.value for alternative in field.alternatives)]
        if not collector_placeholder_conflict(values):
            return issue
        evidence = (issue.provenance, previous_version.provenance, field.selected,
                    *(alternative.provenance for alternative in field.alternatives))
        citations = {citation.model_dump_json(): citation for provenance in evidence for citation in provenance.citations}
        resolution = IssueResolution(
            decided_at=self.now,
            explanation=("Collectors assigned different internal edition labels. This is not evidence of a disagreement in source content. "
                         f"Original selected value: {json.dumps(values[0])}. Original alternatives: {json.dumps(values[1:])}."),
            provenance=Provenance(citations=tuple(citations[key] for key in sorted(citations)), basis="derived",
                                 method=Method(name="committee-explorer.dismiss-collector-label-conflict", version="1"),
                                 explanation=field.selection_reason),
        )
        return issue.model_copy(update={"status": "dismissed", "resolution": resolution})

    def _project_materials(self):
        """Copy representations onto Material.files.

        Versions and representations remain the authorities. MaterialLink remains
        the association, so this does not copy link targets onto the material.
        A material that already has files keeps them when it has no representation.
        """
        files = defaultdict(list)
        for key in sorted(self.records):
            record = self.records[key]
            if record.kind != "representation":
                continue
            version = self.records.get(("material_version", record.version.id))
            if version is None:
                continue
            if record.retained is not None and not record.saved_copy_sha256:
                saved = saved_copy_from_body_key(record.retained.uri, record.saved_filename)
                if saved:
                    digest, name = saved
                    record = record.model_copy(update={"saved_copy_sha256": digest, "saved_filename": name or record.saved_filename})
            files[version.material.id].extend(representation_files(
                record, version_label=version.label, published_at=version.published_at,
                duration_seconds=version.duration_seconds))
        for material_id, projected in files.items():
            key = ("material", material_id)
            material = self.records.get(key)
            if material is None:
                continue
            merged = tuple({item.model_dump_json(): item for item in (*material.files, *projected)}.values())
            if merged != material.files:
                self.records[key] = material.model_copy(update={"files": merged})

    def finish(self):
        if self.ids:
            for record in list(self.records.values()):
                for field in record.field_evidence:
                    if not field.alternatives:
                        continue
                    issue = DataIssue(id=self.ids("data_issue", f"conflict|{record.kind}|{record.id}|{field.path}"),
                                      subject=Ref(kind=record.kind, id=record.id), field_path=field.path, category="conflicting",
                                      summary=f"Sources disagree about {field.path.lstrip('/')}", detected_at=self.now,
                                      provenance=Provenance(citations=record.provenance.citations, basis="derived", method=Method(name="committee-explorer.compare-fields", version="1")))
                    self.records[(issue.kind, issue.id)] = issue
                    self.current.add((issue.kind, issue.id))
        # An unchecked/missing source does not resolve a previous issue. Keep its
        # supporting graph so every retained issue remains inspectable.
        if self.previous is not None:
            # Production uses a disk-backed Mapping; Catalog compatibility is
            # useful for small callers but must not load a previous full export.
            if isinstance(self.previous, Mapping):
                previous = self.previous
            elif hasattr(self.previous.sources, "as_mapping"):
                previous = ChainMap(
                    {(v.kind, v.id): v for v in self.previous.records},
                    self.previous.sources.as_mapping(),
                )
            else:
                previous = {(v.kind, v.id): v for values in (self.previous.sources, self.previous.records) for v in values}
            issues = previous.iter_issues() if hasattr(previous, "iter_issues") else (v for k, v in previous.items() if k[0] == "data_issue")
            # Old sources are not loaded. Each weekly input snapshot re-keys whole
            # providers, so sources that only old issues cite grow with every
            # generation. Their IDs suffice for the graph; their content streams
            # from the previous history into publication and the next history.
            retained = set()
            seen = set()
            for issue in issues:
                issue = self._review_old_label_conflict(issue, previous)
                pending = [issue]
                while pending:
                    old = pending.pop()
                    key = (old.kind, old.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    if key not in self.records:
                        self.records[key] = old
                    elif isinstance(old, DataIssue):
                        now = self.records[key]
                        # Preserve original detection/evidence. A current finding
                        # can reopen a closed issue; disappearance never closes it.
                        citations = {c.model_dump_json(): c for c in (*old.provenance.citations, *now.provenance.citations)}
                        provenance = now.provenance.model_copy(update={"citations": tuple(citations[k] for k in sorted(citations))})
                        self.records[key] = now.model_copy(update={"detected_at": old.detected_at, "provenance": provenance})
                    for reference in _references(old):
                        refkey = (reference.kind, reference.id)
                        if reference.kind == "source_record":
                            # Sources cite nothing further. As for every record,
                            # a current observation replaces the retained one.
                            if refkey in self.sources or reference.id in retained:
                                continue
                            if refkey not in previous:
                                raise ValueError(f"Issue history is missing {reference.kind}/{reference.id}")
                            retained.add(reference.id)
                        elif refkey not in seen:
                            try:
                                pending.append(previous[refkey])
                            except KeyError:
                                raise ValueError(f"Issue history is missing {reference.kind}/{reference.id}") from None
            self.retained = RetainedSources(previous, retained)
        self._project_materials()
        # Every record crossed validated() individually. Constructing the sequence
        # must not ask Pydantic to copy the entire corpus a second time. The full
        # graph validator still checks all links, ownership rules and cycles.
        sources_seq = (
            SpilledSourceSequence(self.sources)
            if isinstance(self.sources, _SpilledSources)
            else tuple(self.sources[k] for k in sorted(self.sources))
        )
        catalog = Catalog.model_construct(sources=sources_seq,
                                          records=tuple(self.records[k] for k in sorted(self.records)))
        return catalog.check_graph_with(self.retained)
