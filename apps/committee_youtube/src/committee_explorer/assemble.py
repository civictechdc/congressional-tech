"""Assemble source-owned records; retain disagreements and open issue history."""
from collections import ChainMap, Counter, OrderedDict, defaultdict
from collections.abc import Mapping, MutableMapping, MutableSet, Sequence
import gc
import hashlib
from heapq import merge
from operator import attrgetter
import json
import os
from pathlib import Path
import sys
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
    from congress_api.retention.body_keys import body_object_digest
    if isinstance(key, (bytes, bytearray, memoryview)) and len(key) == 32:
        key = bytes(key).hex()
    if not isinstance(key, str):
        return None
    digest = body_object_digest(key)
    if not digest:
        return None
    name = filename if isinstance(filename, str) and filename and not any(
        character in filename for character in "/\\") and not any(ord(character) < 32 or ord(character) == 127 for character in filename) else None
    return digest, name


def apply_saved_copies(assembly, filenames_path):
    """Set saved-copy fields from a document-filenames table before files are projected."""
    import pyarrow.parquet as pq
    by_url = {}
    pf = pq.ParquetFile(filenames_path)
    avail_cols = set(pf.schema.names)
    cols = [c for c in ["source_url", "url", "body_key", "sha256", "filename"] if c in avail_cols]
    for batch in pf.iter_batches(columns=cols, batch_size=4096):
        for row in batch.to_pylist():
            found = saved_copy_from_body_key(row.get("body_key") or row.get("sha256"), row.get("filename"))
            url = row.get("source_url") or row.get("url")
            if url and found and url not in by_url:
                by_url[url] = found
    representations = (
        assembly.records.iter_kind("representation")
        if hasattr(assembly.records, "iter_kind")
        else [
            assembly.records[k]
            for k in list(assembly.records)
            if (assembly.records[k].kind if hasattr(assembly.records[k], "kind") else assembly.records[k].get("kind")) == "representation"
        ]
    )
    for record in representations:
        if getattr(record, "saved_copy_sha256", None):
            continue
        locations = getattr(record, "locations", ()) or ()
        match = next((by_url[loc.url] for loc in locations if hasattr(loc, "url") and loc.url in by_url), None)
        if match is None:
            continue
        digest, name = match
        rec_id = getattr(record, "id", None)
        rec_kind = getattr(record, "kind", "representation")
        if hasattr(record, "model_copy"):
            assembly.records[(rec_kind, rec_id)] = record.model_copy(
                update={"saved_copy_sha256": digest, "saved_filename": name or getattr(record, "saved_filename", None)}
            )
        elif isinstance(record, dict):
            record["saved_copy_sha256"] = digest
            record["saved_filename"] = name or record.get("saved_filename")
    materials = (
        assembly.records.iter_kind("material")
        if hasattr(assembly.records, "iter_kind")
        else [
            assembly.records[k]
            for k in list(assembly.records)
            if (assembly.records[k].kind if hasattr(assembly.records[k], "kind") else assembly.records[k].get("kind")) == "material"
        ]
    )
    for record in materials:
        files = getattr(record, "files", None)
        if files:
            updated_files = []
            changed = False
            for f in files:
                f_url = getattr(f, "url", None) if hasattr(f, "url") else f.get("url") if isinstance(f, dict) else None
                f_saved = getattr(f, "saved_copy_sha256", None) if hasattr(f, "saved_copy_sha256") else f.get("saved_copy_sha256") if isinstance(f, dict) else None
                if not f_saved and f_url and f_url in by_url:
                    digest, name = by_url[f_url]
                    if hasattr(f, "model_copy"):
                        updated_files.append(f.model_copy(update={
                            "saved_copy_sha256": digest,
                            "saved_filename": name or getattr(f, "saved_filename", None),
                        }))
                    elif isinstance(f, dict):
                        f_copy = dict(f)
                        f_copy["saved_copy_sha256"] = digest
                        f_copy["saved_filename"] = name or f_copy.get("saved_filename")
                        updated_files.append(f_copy)
                    else:
                        updated_files.append(f)
                    changed = True
                else:
                    updated_files.append(f)
            if changed:
                rec_id = getattr(record, "id", None) if hasattr(record, "id") else record.get("id")
                rec_kind = getattr(record, "kind", "material") if hasattr(record, "kind") else record.get("kind", "material")
                if hasattr(record, "model_copy"):
                    assembly.records[(rec_kind, rec_id)] = record.model_copy(
                        update={"files": tuple(updated_files)}
                    )
                elif isinstance(record, dict):
                    record["files"] = updated_files


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


_SOURCE_CACHE_LIMIT = 128
_ARENA_BUFFER_BYTES = 262_144


def _cleanup_arena(fd: int, path: Path):
    try:
        os.close(fd)
    except OSError:
        pass
    path.unlink(missing_ok=True)


class _ArenaLog:
    """Append-only binary log with buffered sequential writes and O(1) pread lookups."""

    def __init__(self, prefix: str):
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=".arena")
        self._fd: int | None = fd
        self._path = Path(name)
        self._path.unlink(missing_ok=True)
        self._flushed_offset = 0
        self._write_buf = bytearray()
        self._finalizer = weakref.finalize(self, _cleanup_arena, fd, self._path)

    def append(self, data: bytes) -> tuple[int, int]:
        offset = self._flushed_offset + len(self._write_buf)
        length = len(data)
        self._write_buf.extend(data)
        if len(self._write_buf) >= _ARENA_BUFFER_BYTES:
            self.flush()
        return offset, length

    def flush(self) -> None:
        if not self._write_buf or self._fd is None:
            return
        total = len(self._write_buf)
        written = os.write(self._fd, self._write_buf)
        if written < total:
            with memoryview(self._write_buf) as view:
                while written < total:
                    written += os.write(self._fd, view[written:])
        self._flushed_offset += total
        self._write_buf.clear()

    def read(self, offset: int, length: int) -> bytes:
        if length == 0:
            return b""
        if offset >= self._flushed_offset:
            rel = offset - self._flushed_offset
            return bytes(self._write_buf[rel : rel + length])
        if offset + length > self._flushed_offset:
            self.flush()
        return os.pread(self._fd, length, offset)

    def close(self) -> None:
        self._write_buf.clear()
        self._fd = None
        self._finalizer()


def _source_identity_hash(provider: str, scheme: str, value: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(f"{provider}\0{scheme}\0{value}".encode(), digest_size=16).digest(),
        "big",
    )


# 64-bit integer bit-packing constants for bounded-memory arena indexing.
# Bounded memory design per Lead Architect defense:
# Storing hundreds of thousands of records using (offset, length, meta_idx)
# tuples in RAM costs 72+ bytes per entry. Packing into a single 64-bit integer
# reduces per-entry overhead to 28 bytes while maintaining O(1) random access via pread.
#
# _SpilledSources packing: (offset << 44) | (length << 16) | meta_idx
#   - offset:   44 bits -> file offset up to 16 TiB
#   - length:   28 bits -> compressed payload up to 256 MiB
#   - meta_idx: 16 bits -> up to 65,536 interned (provider, input_snapshot_id) pairs
SOURCE_OFFSET_SHIFT = 44
SOURCE_LENGTH_SHIFT = 16
SOURCE_LENGTH_MASK = (1 << 28) - 1   # 0xFFFFFFF (28 bits)
SOURCE_META_MASK = (1 << 16) - 1     # 0xFFFF (16 bits)
MAX_SOURCE_LENGTH = 1 << 28          # 268,435,456 bytes (256 MiB)
MAX_SOURCE_META_IDX = 1 << 16        # 65,536 items

# _SpilledRecords packing: (offset << 28) | length
#   - offset:   36 bits -> file offset up to 64 GiB
#   - length:   28 bits -> compressed payload up to 256 MiB
RECORD_OFFSET_SHIFT = 28
RECORD_LENGTH_MASK = (1 << 28) - 1   # 0xFFFFFFF (28 bits)
MAX_RECORD_LENGTH = 1 << 28          # 268,435,456 bytes (256 MiB)


class _SpilledSources(MutableMapping):
    """Disk-backed MutableMapping of ('source_record', id) -> SourceRecord.

    Uses an append-only ``pread`` arena file and packs ``(offset, length, meta_idx)``
    into a single Python ``int`` per source ID, avoiding SQLite B-tree page splits
    and per-row tuple allocations.
    """

    def __init__(self):
        self._arena = _ArenaLog(".explorer-sources-")
        self._index: dict[str, int] = {}
        self._identity_by_id: dict[str, int] = {}
        self._id_by_identity: dict[int, str] = {}
        self._meta_pool: dict[tuple[str, str | None], int] = {}
        self._meta_list: list[tuple[str, str | None]] = []
        self._cache: OrderedDict[str, SourceRecord] = OrderedDict()

    def _intern_meta(self, provider: str, input_snapshot_id: str | None) -> int:
        pair = (
            sys.intern(provider),
            sys.intern(input_snapshot_id) if isinstance(input_snapshot_id, str) else None,
        )
        idx = self._meta_pool.get(pair)
        if idx is None:
            idx = len(self._meta_list)
            self._meta_list.append(pair)
            self._meta_pool[pair] = idx
        return idx

    def _cache_put(self, record: SourceRecord):
        sid = record.id
        self._cache[sid] = record
        self._cache.move_to_end(sid)
        while len(self._cache) > _SOURCE_CACHE_LIMIT:
            self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        self._cache.clear()

    def get_compressed_by_id(self, sid: str) -> bytes | None:
        packed = self._index.get(sid)
        if packed is None:
            return None
        return self._arena.read(
            packed >> SOURCE_OFFSET_SHIFT,
            (packed >> SOURCE_LENGTH_SHIFT) & SOURCE_LENGTH_MASK,
        )

    def get_by_id(self, sid: str) -> SourceRecord | None:
        packed = self._index.get(sid)
        if packed is None:
            return None
        cached = self._cache.get(sid)
        if cached is not None:
            self._cache.move_to_end(sid)
            return cached
        compressed = self._arena.read(
            packed >> SOURCE_OFFSET_SHIFT,
            (packed >> SOURCE_LENGTH_SHIFT) & SOURCE_LENGTH_MASK,
        )
        record = SourceRecord.model_validate_json(zlib.decompress(compressed))
        _share_field_names(record)
        self._cache_put(record)
        return record

    def provider_for_id(self, sid: str) -> str | None:
        packed = self._index.get(sid)
        return self._meta_list[packed & SOURCE_META_MASK][0] if packed is not None else None

    def identity_for_id(self, sid: str) -> int | None:
        return self._identity_by_id.get(sid)

    def id_for_identity(self, ident: int) -> str | None:
        return self._id_by_identity.get(ident)

    def __contains__(self, key):
        return isinstance(key, tuple) and len(key) == 2 and key[0] == "source_record" and key[1] in self._index

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
        meta_idx = self._intern_meta(record.provider, record.input_snapshot_id)
        compressed = zlib.compress(record.model_dump_json().encode(), level=1)
        offset, length = self._arena.append(compressed)
        if length >= MAX_SOURCE_LENGTH or meta_idx >= MAX_SOURCE_META_IDX:
            raise ValueError(
                f"Source record exceeds bit-packing capacity: length={length} (max {MAX_SOURCE_LENGTH}), "
                f"meta_idx={meta_idx} (max {MAX_SOURCE_META_IDX})"
            )
        self._index[sid] = (offset << SOURCE_OFFSET_SHIFT) | (length << SOURCE_LENGTH_SHIFT) | meta_idx
        ident_hash = _source_identity_hash(
            record.provider,
            record.identifier.scheme,
            record.identifier.value,
        )
        self._identity_by_id[sid] = ident_hash
        self._id_by_identity[ident_hash] = sid
        self._cache_put(record)

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        sid = key[1]
        del self._index[sid]
        ident_hash = self._identity_by_id.pop(sid, None)
        if ident_hash is not None and self._id_by_identity.get(ident_hash) == sid:
            del self._id_by_identity[ident_hash]
        self._cache.pop(sid, None)

    def __iter__(self):
        for sid in self._index:
            yield ("source_record", sid)

    def __len__(self):
        return len(self._index)

    def iter_ordered(self):
        for sid in sorted(self._index):
            packed = self._index[sid]
            compressed = self._arena.read(
                packed >> SOURCE_OFFSET_SHIFT,
                (packed >> SOURCE_LENGTH_SHIFT) & SOURCE_LENGTH_MASK,
            )
            record = SourceRecord.model_validate_json(zlib.decompress(compressed))
            _share_field_names(record)
            yield record

    def iter_ordered_json_dicts(self):
        for sid in sorted(self._index):
            packed = self._index[sid]
            compressed = self._arena.read(
                packed >> SOURCE_OFFSET_SHIFT,
                (packed >> SOURCE_LENGTH_SHIFT) & SOURCE_LENGTH_MASK,
            )
            yield json.loads(zlib.decompress(compressed))

    def iter_payloads_for_ids(self, sids):
        items = []
        for sid in sids:
            packed = self._index.get(sid)
            if packed is not None:
                items.append((
                    packed >> SOURCE_OFFSET_SHIFT,
                    (packed >> SOURCE_LENGTH_SHIFT) & SOURCE_LENGTH_MASK,
                    sid,
                ))
        items.sort()
        for offset, length, sid in items:
            compressed = self._arena.read(offset, length)
            yield sid, json.loads(zlib.decompress(compressed)).get("payload")

    def close(self):
        self._cache.clear()
        self._arena.close()


class SpilledSourceSequence(Sequence):
    """Lazy, ID-sorted Sequence view over _SpilledSources for Catalog.sources."""

    is_id_sorted = True

    def __init__(self, spilled: _SpilledSources, extra: Mapping[str, SourceRecord] | None = None):
        self._spilled = spilled
        self._extra: dict[str, SourceRecord] = dict(extra) if extra else {}
        self._sorted_ids: tuple[str, ...] | None = None

    def source_ids(self):
        if not self._extra:
            return self._spilled._index.keys()
        return self._spilled._index.keys() | self._extra.keys()

    def get_by_id(self, sid: str) -> SourceRecord | None:
        if sid in self._extra:
            return self._extra[sid]
        return self._spilled.get_by_id(sid)

    def iter_payloads_for_ids(self, sids):
        if self._extra:
            remaining = []
            for sid in sids:
                if sid in self._extra:
                    yield sid, self._extra[sid].payload
                else:
                    remaining.append(sid)
            yield from self._spilled.iter_payloads_for_ids(remaining)
        else:
            yield from self._spilled.iter_payloads_for_ids(sids)

    def iter_json_dicts(self):
        if not self._extra:
            yield from self._spilled.iter_ordered_json_dicts()
            return
        spilled_iter = (d for d in self._spilled.iter_ordered_json_dicts() if d["id"] not in self._extra)
        extra_sorted = [r.model_dump(mode="json") for r in sorted(self._extra.values(), key=attrgetter("id"))]
        yield from merge(spilled_iter, extra_sorted, key=lambda d: d["id"])

    def provider_for_id(self, sid: str) -> str | None:
        if sid in self._extra:
            return self._extra[sid].provider
        return self._spilled.provider_for_id(sid)

    def provider_counts(self) -> Counter:
        counts = Counter()
        meta_list = self._spilled._meta_list
        for sid, packed in self._spilled._index.items():
            if sid not in self._extra:
                counts[meta_list[packed & SOURCE_META_MASK][0]] += 1
        for record in self._extra.values():
            counts[record.provider] += 1
        return counts

    def input_snapshot_ids(self) -> set[str]:
        meta_list = self._spilled._meta_list
        inputs = {
            meta_list[packed & SOURCE_META_MASK][1]
            for sid, packed in self._spilled._index.items()
            if sid not in self._extra
        }
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


_RECORD_CACHE_LIMIT = 512
_PINNED_COMMITTEE_KINDS = frozenset({"committee", "committee_term"})


class _SpilledRecords(MutableMapping):
    """Disk-backed MutableMapping of (kind, id) -> DomainRecord.

    Uses an append-only ``pread`` arena and per-kind ``dict[str, int]`` indices
    mapping ``id -> (offset << 28) | length``. Eliminates SQLite B-tree page
    thrashing and avoids allocating 1.4M ``(kind, id)`` 2-tuples in RAM.
    """

    def __init__(self):
        self._arena = _ArenaLog(".explorer-records-")
        self._by_kind: dict[str, dict[str, int]] = defaultdict(dict)
        self._len = 0
        self._conflict_keys: set[tuple[str, str]] = set()
        self._committees: dict[tuple[str, str], DomainRecord] = {}
        self._cache: OrderedDict[tuple[str, str], DomainRecord] = OrderedDict()

    def _cache_put(self, key: tuple[str, str], record: DomainRecord):
        if key[0] in _PINNED_COMMITTEE_KINDS:
            self._committees[key] = record
            return
        self._cache[key] = record
        self._cache.move_to_end(key)
        while len(self._cache) > _RECORD_CACHE_LIMIT:
            self._cache.popitem(last=False)

    def has_key(self, key: tuple[str, str]) -> bool:
        if not (isinstance(key, tuple) and len(key) == 2):
            return False
        kind_map = self._by_kind.get(key[0])
        return bool(kind_map and key[1] in kind_map)

    def iter_keys(self):
        for kind in sorted(self._by_kind):
            ikind = sys.intern(kind)
            for rid in sorted(self._by_kind[kind]):
                yield (ikind, rid)

    def get_by_key(self, key: tuple[str, str]) -> DomainRecord | None:
        if not (isinstance(key, tuple) and len(key) == 2):
            return None
        kind = sys.intern(str(key[0]))
        rid = str(key[1])
        kind_map = self._by_kind.get(kind)
        if not kind_map or rid not in kind_map:
            return None
        ikey = (kind, rid)
        if kind in _PINNED_COMMITTEE_KINDS:
            pinned = self._committees.get(ikey)
            if pinned is not None:
                return pinned
        cached = self._cache.get(ikey)
        if cached is not None:
            self._cache.move_to_end(ikey)
            return cached
        packed = kind_map[rid]
        compressed = self._arena.read(
            packed >> RECORD_OFFSET_SHIFT,
            packed & RECORD_LENGTH_MASK,
        )
        record = _DOMAIN_RECORD.validate_json(zlib.decompress(compressed))
        _share_field_names(record)
        self._cache_put(ikey, record)
        return record

    def get(self, key, default=None):
        record = self.get_by_key(key)
        return default if record is None else record

    def __contains__(self, key):
        return self.has_key(key)

    def __getitem__(self, key):
        record = self.get_by_key(key)
        if record is None:
            raise KeyError(key)
        return record

    def __setitem__(self, key, record):
        record = validated(record)
        if key != (record.kind, record.id) or isinstance(record, SourceRecord):
            raise ValueError("Assembly record does not match its identity or collection")
        kind = sys.intern(record.kind)
        rid = record.id
        ikey = (kind, rid)
        kind_map = self._by_kind[kind]
        if rid not in kind_map:
            self._len += 1
        if any(field.alternatives for field in record.field_evidence):
            self._conflict_keys.add(ikey)
        else:
            self._conflict_keys.discard(ikey)
        compressed = zlib.compress(record.model_dump_json().encode(), level=1)
        offset, length = self._arena.append(compressed)
        if length >= MAX_RECORD_LENGTH:
            raise ValueError(
                f"Domain record exceeds bit-packing capacity: length={length} (max {MAX_RECORD_LENGTH})"
            )
        kind_map[rid] = (offset << RECORD_OFFSET_SHIFT) | length
        self._cache_put(ikey, record)

    def __delitem__(self, key):
        if not self.has_key(key):
            raise KeyError(key)
        kind, rid = key
        del self._by_kind[kind][rid]
        self._len -= 1
        self._conflict_keys.discard(key)
        self._committees.pop(key, None)
        self._cache.pop(key, None)

    def __iter__(self):
        return self.iter_keys()

    def __len__(self):
        return self._len

    def iter_ordered(self):
        for kind in sorted(self._by_kind):
            yield from self.iter_kind(kind)

    def iter_kind(self, kind: str):
        if kind in _PINNED_COMMITTEE_KINDS:
            for key in sorted(k for k in self._committees if k[0] == kind):
                yield self._committees[key]
            return
        kind_map = self._by_kind.get(kind)
        if not kind_map:
            return
        ikind = sys.intern(kind)
        for rid in sorted(kind_map):
            cached = self._cache.get((ikind, rid))
            if cached is not None:
                yield cached
                continue
            packed = kind_map[rid]
            compressed = self._arena.read(
                packed >> RECORD_OFFSET_SHIFT,
                packed & RECORD_LENGTH_MASK,
            )
            record = _DOMAIN_RECORD.validate_json(zlib.decompress(compressed))
            _share_field_names(record)
            yield record

    _JSON_DICT_KIND_ORDER = (
        "committee",
        "committee_term",
        "assessment",
        "meeting",
        "occurrence",
        "legislative_item",
        "communication",
        "nomination",
        "published_print",
        "person",
        "amendment_group",
        "amendment",
        "vote",
        "meeting_subject",
        "appearance",
        "material",
        "material_version",
        "representation",
        "material_link",
        "data_issue",
    )

    def iter_kind_json_dicts(self, kind: str):
        kind_map = self._by_kind.get(kind)
        if not kind_map:
            return
        for rid in sorted(kind_map):
            packed = kind_map[rid]
            compressed = self._arena.read(
                packed >> RECORD_OFFSET_SHIFT,
                packed & RECORD_LENGTH_MASK,
            )
            yield json.loads(zlib.decompress(compressed))

    def iter_json_dicts(self):
        ordered_kinds = [k for k in self._JSON_DICT_KIND_ORDER if k in self._by_kind]
        ordered_kinds.extend(sorted(k for k in self._by_kind if k not in self._JSON_DICT_KIND_ORDER))
        for kind in ordered_kinds:
            yield from self.iter_kind_json_dicts(kind)

    def kinds(self) -> set[str]:
        return set(self._by_kind)

    def close(self):
        self._cache.clear()
        self._committees.clear()
        self._arena.close()


class SpilledRecordSequence(Sequence):
    """Lazy, (kind, id)-sorted Sequence view over _SpilledRecords for Catalog.records."""

    is_key_sorted = True

    def __init__(self, spilled: _SpilledRecords, extra: Mapping[tuple[str, str], DomainRecord] | None = None):
        self._spilled = spilled
        self._extra: dict[tuple[str, str], DomainRecord] = dict(extra) if extra else {}
        self._sorted_keys: tuple[tuple[str, str], ...] | None = None

    def kinds(self) -> set[str]:
        return set(self._spilled.kinds()) | {k[0] for k in self._extra}

    def has_key(self, key: tuple[str, str]) -> bool:
        return key in self._extra or self._spilled.has_key(key)

    def iter_keys(self):
        if not self._extra:
            yield from self._spilled.iter_keys()
            return
        spilled_keys = (k for k in self._spilled.iter_keys() if k not in self._extra)
        extra_keys = sorted(self._extra.keys())
        yield from merge(spilled_keys, extra_keys)

    def get_by_key(self, key: tuple[str, str]) -> DomainRecord | None:
        if key in self._extra:
            return self._extra[key]
        return self._spilled.get_by_key(key)

    def iter_kind(self, kind: str):
        if not self._extra:
            yield from self._spilled.iter_kind(kind)
            return
        extra_for_kind = {k[1]: rec for k, rec in self._extra.items() if k[0] == kind}
        if not extra_for_kind:
            yield from self._spilled.iter_kind(kind)
            return
        spilled_iter = (r for r in self._spilled.iter_kind(kind) if r.id not in extra_for_kind)
        extra_sorted = sorted(extra_for_kind.values(), key=attrgetter("id"))
        yield from merge(spilled_iter, extra_sorted, key=attrgetter("id"))

    def iter_json_dicts(self):
        if not self._extra:
            yield from self._spilled.iter_json_dicts()
            return
        all_kinds = set(self._spilled._by_kind) | {k[0] for k in self._extra}
        ordered_kinds = [k for k in self._spilled._JSON_DICT_KIND_ORDER if k in all_kinds]
        ordered_kinds.extend(sorted(k for k in all_kinds if k not in self._spilled._JSON_DICT_KIND_ORDER))
        for kind in ordered_kinds:
            extra_for_kind = {k[1]: rec.model_dump(mode="json") for k, rec in self._extra.items() if k[0] == kind}
            if not extra_for_kind:
                yield from self._spilled.iter_kind_json_dicts(kind)
            else:
                spilled_iter = (d for d in self._spilled.iter_kind_json_dicts(kind) if d["id"] not in extra_for_kind)
                extra_sorted = [extra_for_kind[rid] for rid in sorted(extra_for_kind)]
                yield from merge(spilled_iter, extra_sorted, key=lambda d: d["id"])

    def with_additional(self, records) -> "SpilledRecordSequence":
        merged = dict(self._extra)
        for rec in records:
            rec = validated(rec)
            merged[(rec.kind, rec.id)] = rec
        return SpilledRecordSequence(self._spilled, merged)

    def as_mapping(self) -> Mapping[tuple[str, str], DomainRecord]:
        if not self._extra:
            return self._spilled
        return ChainMap(self._extra, self._spilled)

    def __len__(self) -> int:
        if not self._extra:
            return len(self._spilled)
        extra_new = sum(1 for k in self._extra if not self._spilled.has_key(k))
        return len(self._spilled) + extra_new

    def __iter__(self):
        if not self._extra:
            yield from self._spilled.iter_ordered()
            return
        spilled_iter = (
            r for r in self._spilled.iter_ordered() if (r.kind, r.id) not in self._extra
        )
        extra_sorted = sorted(self._extra.values(), key=lambda r: (r.kind, r.id))
        yield from merge(spilled_iter, extra_sorted, key=lambda r: (r.kind, r.id))

    def __getitem__(self, index):
        if self._sorted_keys is None:
            self._sorted_keys = tuple(self.iter_keys())
        if isinstance(index, slice):
            return tuple(self.get_by_key(k) for k in self._sorted_keys[index])
        return self.get_by_key(self._sorted_keys[index])

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, (SpilledRecordSequence, tuple, list)):
            if len(self) != len(other):
                return False
            return all(a == b for a, b in zip(self, other))
        return NotImplemented


class _CurrentKeys(MutableSet):
    """Compact current-selection key view backed by Assembly.records and Assembly.sources."""

    def __init__(self, records: _SpilledRecords, sources: _SpilledSources):
        self._records = records
        self._sources = sources
        self._historical: set[tuple[str, str]] = set()
        self._extra: set[tuple[str, str]] = set()

    def mark_historical(self, key: tuple[str, str]) -> None:
        if key not in self._extra:
            self._historical.add((sys.intern(str(key[0])), str(key[1])))

    def add(self, value: tuple[str, str]) -> None:
        key = (sys.intern(str(value[0])), str(value[1]))
        self._historical.discard(key)
        if key not in self._records and key not in self._sources:
            self._extra.add(key)

    def discard(self, value: tuple[str, str]) -> None:
        key = (sys.intern(str(value[0])), str(value[1]))
        self._extra.discard(key)
        if key in self._records or key in self._sources:
            self._historical.add(key)

    def __contains__(self, value: object) -> bool:
        if not (isinstance(value, tuple) and len(value) == 2):
            return False
        if value in self._historical:
            return False
        if value in self._records or value in self._sources:
            return True
        return value in self._extra

    def __iter__(self):
        for key in self._records:
            if key not in self._historical:
                yield key
        for key in self._sources:
            if key not in self._historical:
                yield key
        for key in self._extra:
            if key not in self._historical and key not in self._records and key not in self._sources:
                yield key

    def __len__(self) -> int:
        base = len(self._records) + len(self._sources)
        hist_in_base = sum(1 for k in self._historical if k in self._records or k in self._sources)
        extra_only = sum(
            1 for k in self._extra
            if k not in self._historical and k not in self._records and k not in self._sources
        )
        return base - hist_in_base + extra_only


class Assembly:
    def __init__(self, previous=None, *, ids=None, now=None):
        self.sources = _SpilledSources()
        self.records = _SpilledRecords()
        self.current = _CurrentKeys(self.records, self.sources)
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
        if hasattr(self.records, "iter_kind"):
            if hasattr(self.records, "_by_kind") and not self.records._by_kind.get("representation"):
                return
            from committee_meeting.materials import MaterialFile

            date_cache = {}
            version_meta = {}
            for v in self.records.iter_kind("material_version"):
                pub = v.published_at
                if pub is not None:
                    dkey = (pub.date, pub.precision, pub.original)
                    pub = date_cache.setdefault(dkey, pub)
                version_meta[v.id] = (
                    v.material.id,
                    sys.intern(v.label) if v.label else v.label,
                    pub,
                    v.duration_seconds,
                )
            del date_cache
            for record in self.records.iter_kind("representation"):
                v_info = version_meta.get(record.version.id)
                if v_info is None:
                    continue
                material_id, v_label, v_published_at, v_duration = v_info
                if record.retained is not None and not record.saved_copy_sha256:
                    saved = saved_copy_from_body_key(record.retained.uri, record.saved_filename)
                    if saved:
                        digest, name = saved
                        record = record.model_copy(
                            update={"saved_copy_sha256": digest, "saved_filename": name or record.saved_filename}
                        )
                for mf in representation_files(
                    record,
                    version_label=v_label,
                    published_at=v_published_at,
                    duration_seconds=v_duration,
                ):
                    files[material_id].append(zlib.compress(mf.model_dump_json().encode(), level=1))
            del version_meta
            for material in self.records.iter_kind("material"):
                projected = files.pop(material.id, None)
                if not projected:
                    continue
                by_json = {item.model_dump_json(): item for item in material.files}
                for comp in projected:
                    raw_json = zlib.decompress(comp).decode()
                    if raw_json not in by_json:
                        mf = MaterialFile.model_validate_json(raw_json)
                        _share_field_names(mf)
                        by_json[raw_json] = mf
                merged = tuple(by_json.values())
                if merged != material.files:
                    self.records[("material", material.id)] = material.model_copy(update={"files": merged})
            files.clear()
            gc.collect()
        else:
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

    def _source_id_for_identity(self, ident: int) -> str | None:
        if hasattr(self.sources, "id_for_identity"):
            return self.sources.id_for_identity(ident)
        if not hasattr(self, "_fallback_ident_map"):
            self._fallback_ident_map = {}
            for k, src in self.sources.items():
                if isinstance(k, tuple) and len(k) == 2 and k[0] == "source_record":
                    h = _source_identity_hash(src.provider, src.identifier.scheme, src.identifier.value)
                    self._fallback_ident_map[h] = src.id
        return self._fallback_ident_map.get(ident)

    def _source_identity_for_id(self, sid: str, previous=None, identity_cache=None) -> tuple[int, str] | None:
        if ("source_record", sid) in self.sources:
            ident = (
                self.sources.identity_for_id(sid)
                if hasattr(self.sources, "identity_for_id")
                else None
            )
            if ident is None:
                src = self.sources[("source_record", sid)]
                ident = _source_identity_hash(src.provider, src.identifier.scheme, src.identifier.value)
            elif isinstance(ident, tuple):
                ident = _source_identity_hash(*ident)
            return (ident, "")
        if identity_cache is not None and sid in identity_cache:
            return identity_cache[sid]
        if previous is not None:
            cached = None
            if hasattr(previous, "source_identity"):
                found = previous.source_identity(sid)
                if found is not None:
                    raw_ident, imp = found
                    cached = (
                        _source_identity_hash(*raw_ident) if isinstance(raw_ident, tuple) else raw_ident,
                        imp,
                    )
            elif ("source_record", sid) in previous:
                src = previous[("source_record", sid)]
                cached = (
                    _source_identity_hash(src.provider, src.identifier.scheme, src.identifier.value),
                    src.imported_at.isoformat() if src.imported_at else "",
                )
            if cached is not None:
                if identity_cache is not None:
                    identity_cache[sid] = cached
                return cached
        return None

    def _dedup_citations(self, citations, previous, identity_cache):
        """Deduplicate citations by (source_identity, selector_type, selector, quote).

        Each weekly snapshot re-keys whole providers with a new input_snapshot_id,
        generating a fresh source_record UUID for the same (provider, scheme, value).
        When an issue recurs across snapshots, the current observation replaces the
        prior snapshot observation for the same source identity and selector.
        """
        if not citations:
            return ()
        best = {}
        unresolved = []
        for c in citations:
            sid = c.source.id
            resolved = self._source_identity_for_id(sid, previous, identity_cache)
            if resolved is None:
                unresolved.append(c)
                continue
            ident, imp = resolved
            if ("source_record", sid) in self.sources:
                rank = (1, "", sid)
            else:
                current_sid = self._source_id_for_identity(ident)
                if current_sid is not None:
                    c = c.model_copy(update={"source": Ref(kind="source_record", id=current_sid)})
                    rank = (1, "", current_sid)
                else:
                    rank = (0, imp, sid)
            dkey = (ident, c.selector_type, c.selector, c.quote)
            prev = best.get(dkey)
            if prev is None or rank >= prev[0]:
                best[dkey] = (rank, c)
        merged = {c.model_dump_json(): c for _, c in best.values()}
        for c in unresolved:
            merged[c.model_dump_json()] = c
        return tuple(merged[k] for k in sorted(merged))

    def finish(self):
        if self.ids:
            conflict_records = (
                [self.records[k] for k in sorted(self.records._conflict_keys)]
                if hasattr(self.records, "_conflict_keys")
                else list(self.records.values())
            )
            for record in conflict_records:
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
                prev_records = (
                    self.previous.records.as_mapping()
                    if hasattr(self.previous.records, "as_mapping")
                    else {(v.kind, v.id): v for v in self.previous.records}
                )
                previous = ChainMap(
                    prev_records,
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
            identity_cache = {}
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
                        if isinstance(old, DataIssue):
                            deduped_cits = self._dedup_citations(
                                old.provenance.citations, previous, identity_cache
                            )
                            res = old.resolution
                            deduped_res_cits = (
                                self._dedup_citations(
                                    res.provenance.citations, previous, identity_cache
                                )
                                if res is not None
                                else None
                            )
                            updates = {}
                            if deduped_cits != old.provenance.citations:
                                updates["provenance"] = old.provenance.model_copy(
                                    update={"citations": deduped_cits}
                                )
                            if (
                                res is not None
                                and deduped_res_cits != res.provenance.citations
                            ):
                                updates["resolution"] = res.model_copy(
                                    update={
                                        "provenance": res.provenance.model_copy(
                                            update={"citations": deduped_res_cits}
                                        )
                                    }
                                )
                            if old.subject.kind == "source_record" and ("source_record", old.subject.id) not in self.sources:
                                resolved_subj = self._source_identity_for_id(old.subject.id, previous, identity_cache)
                                if resolved_subj is not None:
                                    curr_subj_sid = self._source_id_for_identity(resolved_subj[0])
                                    if curr_subj_sid is not None:
                                        updates["subject"] = Ref(kind="source_record", id=curr_subj_sid)
                            if updates:
                                old = old.model_copy(update=updates)
                        self.records[key] = old
                        if hasattr(self.current, "mark_historical"):
                            self.current.mark_historical(key)
                    elif isinstance(old, DataIssue):
                        now = self.records[key]
                        # Preserve original detection/evidence. A current finding
                        # can reopen a closed issue; disappearance never closes it.
                        deduped_cits = self._dedup_citations(
                            (*old.provenance.citations, *now.provenance.citations),
                            previous,
                            identity_cache,
                        )
                        provenance = now.provenance.model_copy(update={"citations": deduped_cits})
                        updates = {"detected_at": old.detected_at, "provenance": provenance}
                        if old.resolution is not None and now.resolution is not None:
                            deduped_res_cits = self._dedup_citations(
                                (*old.resolution.provenance.citations, *now.resolution.provenance.citations),
                                previous,
                                identity_cache,
                            )
                            updates["resolution"] = now.resolution.model_copy(
                                update={"provenance": now.resolution.provenance.model_copy(update={"citations": deduped_res_cits})}
                            )
                        if now.subject.kind == "source_record" and ("source_record", now.subject.id) not in self.sources:
                            resolved_subj = self._source_identity_for_id(now.subject.id, previous, identity_cache)
                            if resolved_subj is not None:
                                curr_subj_sid = self._source_id_for_identity(resolved_subj[0])
                                if curr_subj_sid is not None:
                                    updates["subject"] = Ref(kind="source_record", id=curr_subj_sid)
                        self.records[key] = now.model_copy(update=updates)
                    refs = list(_references(self.records[key]))
                    if (
                        isinstance(old, DataIssue)
                        and old.resolution is not None
                        and self.records[key].resolution is None
                    ):
                        res_cits = self._dedup_citations(
                            old.resolution.provenance.citations, previous, identity_cache
                        )
                        refs.extend(c.source for c in res_cits)
                    for reference in refs:
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
            del identity_cache, seen
        if hasattr(self.sources, "_identity_by_id"):
            self.sources._identity_by_id.clear()
        if hasattr(self.sources, "_id_by_identity"):
            self.sources._id_by_identity.clear()
        if hasattr(self, "_fallback_ident_map"):
            self._fallback_ident_map.clear()
        if hasattr(self.sources, "clear_cache"):
            self.sources.clear_cache()
        gc.collect()
        self._project_materials()
        # Every record crossed validated() individually. Constructing the sequence
        # must not ask Pydantic to copy the entire corpus a second time. The full
        # graph validator still checks all links, ownership rules and cycles.
        sources_seq = (
            SpilledSourceSequence(self.sources)
            if isinstance(self.sources, _SpilledSources)
            else tuple(self.sources[k] for k in sorted(self.sources))
        )
        records_seq = (
            SpilledRecordSequence(self.records)
            if isinstance(self.records, _SpilledRecords)
            else tuple(self.records[k] for k in sorted(self.records))
        )
        catalog = Catalog.model_construct(sources=sources_seq, records=records_seq)
        return catalog.check_graph_with(self.retained)
