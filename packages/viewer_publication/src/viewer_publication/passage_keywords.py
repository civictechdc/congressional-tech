"""Build and verify the SpicyEngine keyword passage Parquet beside a release's passage embeddings.

SpicyEngine's ``attach-passages`` indexes ``keyword_parquet`` for lexical passage ranking. Each row
repeats one vector passage's coordinates and adds ``text``, the exact slice of the document field it
cites. The rows are a pure function of the serving passages (coordinates and excerpts) and the
prepared release documents (title, body and page offsets), so this module derives them from those
two inputs and never from the vectors.

A build writes ``<output>/manifest.json`` with a fingerprint per file. A later release reuses a
previous file by hard link when its custody stamp still matches and both the passage coordinates and
the document texts of every document it holds are unchanged. Every other document is rebuilt from
its text. Before the directory is published, the combined fingerprint of all files must equal the
serving passages' fingerprint, which rules out omitted, extra, duplicated and changed rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from bisect import bisect_right
from contextlib import closing
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

FORMAT = 1
MANIFEST = "manifest.json"
LAYOUT_DUAL = "dual"
LAYOUT_UNIFIED = "unified"
LAYOUTS = (LAYOUT_DUAL, LAYOUT_UNIFIED)
# The same bounds SpicyEngine applies when it validates attached passages.
MAX_CHARS = 16000
MAX_EXCERPT_CHARS = 2000
TEXT_FIELDS = ("body", "title")
KEYWORD_SCHEMA = pa.schema([
    ("source_id", pa.string()),
    ("member_key", pa.string()),
    ("source_field", pa.string()),
    ("char_start", pa.int32()),
    ("char_end", pa.int32()),
    ("page", pa.int32()),
    ("page_at", pa.int32()),
    ("excerpt", pa.string()),
    ("text", pa.string()),
])


def unified_schema(dimensions):
    """Exact Arrow schema for SpicyEngine ``layout="unified"`` passage Parquet."""
    if type(dimensions) is not int or not 1 <= dimensions <= 1024:
        raise ValueError("Unified passage dimensions must be an integer between 1 and 1024")
    return pa.schema([*KEYWORD_SCHEMA, ("vector", pa.list_(pa.float16(), dimensions))])
DOC_COLUMNS = ["source_id", "member_key", "title", "body", "text_sha256", "page_offsets"]
SPAN_COLUMNS = ["source_field", "text_sha256", "char_start", "char_end", "excerpt", "page", "page_at"]
# Explicit casts keep the fingerprint identical for serving and keyword files whatever integer width
# a producer wrote.
_ROW = ("source_id::VARCHAR, member_key::VARCHAR, source_field::VARCHAR, char_start::INTEGER, "
        "char_end::INTEGER, excerpt::VARCHAR, page::INTEGER, page_at::INTEGER")
_REVERSED = ("page_at::INTEGER, page::INTEGER, excerpt::VARCHAR, char_end::INTEGER, char_start::INTEGER, "
             "source_field::VARCHAR, member_key::VARCHAR, source_id::VARCHAR")
_FINGERPRINT = (f"count(*), coalesce(bit_xor(hash({_ROW})), 0), coalesce(sum(hash({_ROW})::HUGEINT), 0), "
                f"coalesce(bit_xor(hash({_REVERSED})), 0), coalesce(sum(hash({_REVERSED})::HUGEINT), 0)")
_EMPTY = (0, 0, 0, 0, 0)
_EMPTY_VEC = (0, 0)
_BUFFER_ROWS = 4096


def combine(a, b):
    """Combine two order-independent multiset fingerprints (count, xor, sum, xor, sum)."""
    return (a[0] + b[0], a[1] ^ b[1], a[2] + b[2], a[3] ^ b[3], a[4] + b[4])


def _combine_vec(a, b):
    return (a[0] ^ b[0], a[1] + b[1])


def _pack_float16_vectors(vector_array, dimensions):
    """Validate and pack a vector column into ``fixed_size_list<float16>[dimensions]``."""
    if vector_array.null_count:
        raise ValueError("Unified passage vectors cannot be null")
    if isinstance(vector_array, pa.ChunkedArray):
        vector_array = vector_array.combine_chunks()
    if pa.types.is_fixed_size_list(vector_array.type):
        if vector_array.type.list_size != dimensions:
            raise ValueError(f"Expected {dimensions}-d vectors, got fixed-size list of {vector_array.type.list_size}")
    else:
        lengths = pc.list_value_length(vector_array)
        if len(vector_array) and not pc.all(pc.equal(lengths, dimensions)).as_py():
            raise ValueError(f"Expected every passage vector to have length {dimensions}")
    flat = pc.list_flatten(vector_array)
    if flat.null_count:
        raise ValueError("Unified passage vectors cannot contain null elements")
    if not pa.types.is_float16(flat.type):
        flat = pc.cast(flat, pa.float16())
    if len(flat) and not pc.all(pc.is_finite(pc.cast(flat, pa.float32()))).as_py():
        raise ValueError("Unified passage vectors must be finite")
    return pa.FixedSizeListArray.from_arrays(flat, dimensions)


def _serving_vectors(db, files, dimensions):
    """Compute per-document serving vector fingerprints and validate vector dimensions."""
    bad = db.execute(
        f"SELECT count(*) FROM read_parquet(?) WHERE vector IS NULL OR len(vector) <> {dimensions}",
        [[str(p) for p in files]],
    ).fetchone()[0]
    if bad:
        raise ValueError(f"{bad} serving passage rows have missing or non-{dimensions}-d vectors")
    rows = db.execute(
        "SELECT source_id, member_key, coalesce(bit_xor(hash(vector)), 0), "
        "coalesce(sum(hash(vector)::HUGEINT), 0) "
        "FROM read_parquet(?) GROUP BY source_id, member_key",
        [[str(p) for p in files]],
    ).fetchall()
    return {(source_id, key): (int(x), int(s)) for source_id, key, x, s in rows}


def _stamp(path):
    stat = Path(path).stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns]


def _hex(value):
    return value.hex() if isinstance(value, (bytes, bytearray)) else value


def _connect(work, memory_limit):
    return duckdb.connect(config={"threads": 1, "memory_limit": memory_limit, "preserve_insertion_order": False,
                                  "temp_directory": str(work)})


def _text_identity(text_sha256, title):
    return hashlib.blake2b(f"{_hex(text_sha256) or ''}\0{title or ''}".encode(), digest_size=16).hexdigest()


def _text_digest(keys, identities):
    digest = hashlib.blake2b(digest_size=16)
    for key in sorted(keys):
        digest.update(f"{key[0]}\0{key[1]}\0{identities[key]}\n".encode())
    return digest.hexdigest()


def _fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _documents(prepared):
    """Map each prepared document to its shard, text identity, and body text SHA-256."""
    parts = sorted(Path(prepared).glob("*.parquet"))
    if not parts:
        raise ValueError(f"No prepared document shards in {prepared}")
    located, identities, body_hashes = {}, {}, {}
    for part in parts:
        table = pq.read_table(part, columns=["source_id", "member_key", "text_sha256", "title"])
        for source_id, key, text_sha256, title in zip(*(table[c].to_pylist() for c in table.column_names),
                                                       strict=True):
            identity = (source_id, key)
            if identity in located:
                raise ValueError(f"Prepared document {key} appears in more than one shard")
            located[identity] = part
            identities[identity] = _text_identity(text_sha256, title)
            body_hashes[identity] = _hex(text_sha256)
    return located, identities, body_hashes


def _serving(db, files, located, body_hashes):
    """Fingerprint the serving passages per document, without reading the vectors."""
    rows = db.execute(
        f"SELECT source_id, member_key, {_FINGERPRINT}, "
        "min(text_sha256) FILTER (WHERE source_field = 'body'), "
        "max(text_sha256) FILTER (WHERE source_field = 'body'), "
        "count(*) FILTER (WHERE source_field = 'body'), "
        "count(text_sha256) FILTER (WHERE source_field = 'body') "
        "FROM read_parquet(?) GROUP BY source_id, member_key", [[str(p) for p in files]]).fetchall()
    per_document = {}
    for source_id, key, *values in rows:
        identity = (source_id, key)
        low, high, body_rows, body_hashed = values[5:]
        if low != high:
            raise ValueError(f"Passages for {key} cite more than one body text version")
        if body_rows and identity in body_hashes:
            expected_sha = body_hashes[identity]
            if (expected_sha is None and body_hashed != 0) or (
                expected_sha is not None and (body_hashed != body_rows or _hex(low) != expected_sha)
            ):
                raise ValueError(f"Passages for {key} cite a different body text version")
        per_document[identity] = tuple(int(v) for v in values[:5])
    missing = per_document.keys() - located.keys()
    if missing:
        raise ValueError(f"{len(missing)} passage documents are not in the prepared release, e.g. {min(missing)[1]}")
    uncovered = located.keys() - per_document.keys()
    if uncovered:
        raise ValueError(f"{len(uncovered)} prepared documents have no passages, e.g. {min(uncovered)[1]}")
    return per_document


def _reusable(previous, per_document, identities):
    """Yield previous files whose stamp, permissions, passages and document texts all still match."""
    path = Path(previous) / MANIFEST
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT or manifest.get("duckdb") != duckdb.__version__:
        return
    for entry in manifest["files"]:
        source = Path(previous) / entry["name"]
        if source.is_symlink() or not source.is_file():
            continue
        source_stat = source.stat()
        if not (source_stat.st_mode & stat.S_IROTH) or _stamp(source) != entry["stamp"]:
            continue
        table = pq.read_table(source, columns=["source_id", "member_key"])
        keys = set(zip(table["source_id"].to_pylist(), table["member_key"].to_pylist(), strict=True))
        if len(keys) != entry["documents"] or not keys <= per_document.keys():
            continue
        fingerprint = _EMPTY
        for key in keys:
            fingerprint = combine(fingerprint, per_document[key])
        if list(fingerprint) == entry["fingerprint"] and _text_digest(keys, identities) == entry["text_digest"]:
            yield source, entry, keys


def _char_pages(body, offsets):
    raw = body.encode()
    if offsets[0] != 0 or offsets != sorted(offsets) or offsets[-1] > len(raw):
        raise ValueError("Invalid physical page offsets")
    chars = [0]
    for start, end in zip(offsets, offsets[1:]):
        chars.append(chars[-1] + len(raw[start:end].decode()))
    return chars


def _keyword_rows(document, spans):
    """Slice each passage's text from its document, checking every coordinate the index relies on."""
    key = document["member_key"]
    body, title = document["body"] or "", document["title"] or ""
    offsets = document["page_offsets"] or []
    char_pages, seen = None, set()
    for field, text_sha256, start, end, excerpt, page, page_at in spans:
        if field not in TEXT_FIELDS:
            raise ValueError(f"Unsupported passage field {field!r} for {key}")
        if (field, start, end) in seen:
            raise ValueError(f"Duplicate passage {(key, field, start, end)}")
        seen.add((field, start, end))
        source = body if field == "body" else title
        if start is None or end is None or not 0 <= start < end <= len(source) or end - start > MAX_CHARS:
            raise ValueError(f"Passage range ({start}, {end}) is invalid for {key} {field}")
        if field == "body" and _hex(text_sha256) != _hex(document["text_sha256"]):
            raise ValueError(f"Passages for {key} cite a different body text version")
        text = source[start:end]
        if not excerpt or len(excerpt) > min(MAX_EXCERPT_CHARS, end - start) or excerpt not in text:
            raise ValueError(f"Excerpt is not a verbatim part of passage {key} {field} [{start}:{end}]")
        if field == "body" and offsets:
            char_pages = char_pages or _char_pages(body, offsets)
            anchor = start
            while anchor + 1 < end and body[anchor].isspace():
                anchor += 1
            expected = bisect_right(char_pages, anchor)
            expected_at = len(body[char_pages[expected - 1]:anchor].encode())
            if (page, page_at) != (expected, expected_at):
                raise ValueError(f"Page anchor ({page}, {page_at}) differs from ({expected}, {expected_at}) for {key}")
        elif page is not None or page_at is not None:
            raise ValueError(f"Unexpected page anchor for {key} {field}")
        yield dict(source_id=document["source_id"], member_key=key, source_field=field, char_start=start,
                   char_end=end, page=page, page_at=page_at, excerpt=excerpt, text=text)


class _Writer:
    """Write keyword rows in bounded row groups to a partial file."""

    def __init__(self, path):
        self.path, self.rows, self.buffer = path, 0, []
        self.writer = pq.ParquetWriter(path.with_suffix(".partial"), KEYWORD_SCHEMA, compression="zstd",
                                       compression_level=2,
                                       use_dictionary=["source_id", "member_key", "source_field"])

    def write(self, rows):
        for row in rows:
            self.buffer.append(row)
            if len(self.buffer) >= _BUFFER_ROWS:
                self.flush()

    def flush(self):
        if self.buffer:
            self.writer.write_table(pa.Table.from_pylist(self.buffer, schema=KEYWORD_SCHEMA))
            self.rows += len(self.buffer)
            self.buffer.clear()

    def close(self):
        self.flush()
        self.writer.close()
        partial = self.path.with_suffix(".partial")
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        os.chmod(partial, 0o444)
        os.replace(partial, self.path)


def _fill(writer, shard, routes):
    """Append the keyword rows of one prepared shard's routed documents."""
    routed = pq.read_table(sorted((routes / f"part={shard.stem}").glob("*.parquet")),
                           columns=["source_id", "member_key", *SPAN_COLUMNS])
    spans = {}
    for source_id, key, *span in zip(*(routed[c].to_pylist() for c in routed.column_names), strict=True):
        spans.setdefault((source_id, key), []).append(tuple(span))
    del routed
    for batch in pq.ParquetFile(shard).iter_batches(batch_size=16, columns=DOC_COLUMNS):
        for document in batch.to_pylist():
            document_spans = spans.pop((document["source_id"], document["member_key"]), None)
            if document_spans is not None:
                writer.write(_keyword_rows(document, document_spans))
    if spans:
        raise ValueError(f"{len(spans)} routed documents are missing from {shard.name}")


def _build(db, files, located, pending, staging, work, delta_name):
    """Route pending documents' passages by prepared shard, then slice each shard's texts once.

    A full build writes one file per prepared shard; an incremental build writes ``delta_name``.
    """
    routes = work / "routes"
    db.register("pending_documents", pa.table({
        "source_id": [k[0] for k in pending], "member_key": [k[1] for k in pending],
        "part": [located[k].stem for k in pending]}))
    target = str(routes).replace("'", "''")
    db.execute(
        "COPY (SELECT p.part, s.source_id, s.member_key, " + ", ".join(f"s.{c}" for c in SPAN_COLUMNS) +
        " FROM read_parquet(?) s JOIN pending_documents p USING (source_id, member_key)) "
        f"TO '{target}' (FORMAT parquet, PARTITION_BY (part))", [[str(p) for p in files]])
    db.unregister("pending_documents")
    shards = sorted({located[k] for k in pending})
    groups = [(delta_name, shards)] if delta_name else [(f"{s.stem}.parquet", [s]) for s in shards]
    written = []
    for name, members in groups:
        writer = _Writer(staging / name)
        try:
            for shard in members:
                _fill(writer, shard, routes)
        except BaseException:
            writer.writer.close()
            raise
        writer.close()
        written.append(staging / name)
    return written


def _verify(db, path):
    """Read a written file back and return its fingerprint and documents after checking every row."""
    if not pq.read_schema(path).equals(KEYWORD_SCHEMA):
        raise ValueError(f"Unexpected keyword schema in {path.name}")
    row = db.execute(
        f"SELECT {_FINGERPRINT}, "
        "count(*) - count(DISTINCT (source_id, member_key, source_field, char_start, char_end)), "
        f"count(*) FILTER (WHERE source_field IS NULL OR source_field NOT IN ('body', 'title') "
        f"OR char_start IS NULL OR char_end IS NULL OR char_start < 0 OR char_end <= char_start "
        f"OR char_end - char_start > {MAX_CHARS} OR excerpt IS NULL OR length(excerpt) < 1 "
        f"OR length(excerpt) > least({MAX_EXCERPT_CHARS}, char_end - char_start) "
        "OR (page IS NULL) <> (page_at IS NULL) OR page < 1 OR page_at < 0), "
        "count(*) FILTER (WHERE text IS NULL OR length(text) <> char_end - char_start OR strpos(text, excerpt) = 0) "
        "FROM read_parquet(?)", [str(path)]).fetchone()
    fingerprint, duplicates, invalid, mismatched = tuple(int(v) for v in row[:5]), *row[5:]
    if duplicates or invalid or mismatched:
        raise ValueError(f"{path.name}: {duplicates} duplicate, {invalid} invalid and {mismatched} mismatched rows")
    table = pq.read_table(path, columns=["source_id", "member_key"])
    return fingerprint, set(zip(table["source_id"].to_pylist(), table["member_key"].to_pylist(), strict=True))


class _UnifiedWriter:
    """Write unified keyword + float16-vector rows in bounded row groups to a partial file."""

    def __init__(self, path, dimensions):
        self.path, self.dimensions, self.rows = path, dimensions, 0
        self.schema = unified_schema(dimensions)
        self.row_buffer, self.vec_chunks = [], []
        self.writer = pq.ParquetWriter(
            path.with_suffix(".partial"), self.schema, compression="zstd", compression_level=2,
            use_dictionary=["source_id", "member_key", "source_field"])

    def write(self, rows, vectors):
        if not rows:
            return
        self.row_buffer.extend(rows)
        self.vec_chunks.append(vectors)
        if len(self.row_buffer) >= _BUFFER_ROWS:
            self.flush()

    def flush(self):
        if self.row_buffer:
            base = pa.Table.from_pylist(self.row_buffer, schema=KEYWORD_SCHEMA)
            packed = _pack_float16_vectors(pa.chunked_array(self.vec_chunks), self.dimensions)
            table = base.append_column(self.schema.field("vector"), packed)
            self.writer.write_table(table)
            self.rows += len(self.row_buffer)
            self.row_buffer.clear()
            self.vec_chunks.clear()

    def close(self):
        self.flush()
        self.writer.close()
        partial = self.path.with_suffix(".partial")
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        os.chmod(partial, 0o444)
        os.replace(partial, self.path)


def _fill_unified(writer, shard, routes):
    """Append unified keyword + vector rows of one prepared shard's routed documents."""
    routed = pq.read_table(sorted((routes / f"part={shard.stem}").glob("*.parquet")),
                           columns=["source_id", "member_key", *SPAN_COLUMNS, "vector"])
    vec_col = routed["vector"].combine_chunks()
    meta_cols = [routed[c].to_pylist() for c in ("source_id", "member_key", *SPAN_COLUMNS)]
    spans, positions = {}, {}
    for idx, (source_id, key, *span) in enumerate(zip(*meta_cols, strict=True)):
        doc_key = (source_id, key)
        spans.setdefault(doc_key, []).append(tuple(span))
        positions.setdefault(doc_key, []).append(idx)
    del routed, meta_cols
    for batch in pq.ParquetFile(shard).iter_batches(batch_size=16, columns=DOC_COLUMNS):
        for document in batch.to_pylist():
            doc_key = (document["source_id"], document["member_key"])
            document_spans = spans.pop(doc_key, None)
            if document_spans is not None:
                doc_indices = positions.pop(doc_key)
                rows = list(_keyword_rows(document, document_spans))
                writer.write(rows, vec_col.take(pa.array(doc_indices, type=pa.int64())))
    if spans:
        raise ValueError(f"{len(spans)} routed documents are missing from {shard.name}")


def _build_unified(db, files, located, pending, staging, work, delta_name, dimensions):
    """Route pending documents' passages + vectors by prepared shard, then write unified shards."""
    routes = work / "routes"
    db.register("pending_documents", pa.table({
        "source_id": [k[0] for k in pending], "member_key": [k[1] for k in pending],
        "part": [located[k].stem for k in pending]}))
    target = str(routes).replace("'", "''")
    db.execute(
        "COPY (SELECT p.part, s.source_id, s.member_key, "
        + ", ".join(f"s.{c}" for c in SPAN_COLUMNS)
        + ", s.vector FROM read_parquet(?) s JOIN pending_documents p USING (source_id, member_key)) "
        f"TO '{target}' (FORMAT parquet, PARTITION_BY (part))", [[str(p) for p in files]])
    db.unregister("pending_documents")
    shards = sorted({located[k] for k in pending})
    groups = [(delta_name, shards)] if delta_name else [(f"{s.stem}.parquet", [s]) for s in shards]
    written = []
    for name, members in groups:
        writer = _UnifiedWriter(staging / name, dimensions)
        try:
            for shard in members:
                _fill_unified(writer, shard, routes)
        except BaseException:
            writer.writer.close()
            raise
        writer.close()
        written.append(staging / name)
    return written


def _verify_unified(db, path, dimensions, *, expect_vector_fp=None):
    """Read a written unified file back and verify schema, metadata, text, and float16 vectors."""
    expected_schema = unified_schema(dimensions)
    if not pq.read_schema(path).equals(expected_schema):
        raise ValueError(f"Unexpected unified passage schema in {path.name}")
    row = db.execute(
        f"SELECT {_FINGERPRINT}, "
        "count(*) - count(DISTINCT (source_id, member_key, source_field, char_start, char_end)), "
        f"count(*) FILTER (WHERE source_field IS NULL OR source_field NOT IN ('body', 'title') "
        f"OR char_start IS NULL OR char_end IS NULL OR char_start < 0 OR char_end <= char_start "
        f"OR char_end - char_start > {MAX_CHARS} OR excerpt IS NULL OR length(excerpt) < 1 "
        f"OR length(excerpt) > least({MAX_EXCERPT_CHARS}, char_end - char_start) "
        "OR (page IS NULL) <> (page_at IS NULL) OR page < 1 OR page_at < 0), "
        "count(*) FILTER (WHERE text IS NULL OR length(text) <> char_end - char_start OR strpos(text, excerpt) = 0), "
        f"count(*) FILTER (WHERE vector IS NULL OR len(vector) <> {dimensions}), "
        "coalesce(bit_xor(hash(vector)), 0), coalesce(sum(hash(vector)::HUGEINT), 0) "
        "FROM read_parquet(?)", [str(path)]).fetchone()
    fingerprint = tuple(int(v) for v in row[:5])
    duplicates, invalid, mismatched, bad_vectors = row[5:9]
    vec_fp = (int(row[9]), int(row[10]))
    if duplicates or invalid or mismatched or bad_vectors:
        raise ValueError(
            f"{path.name}: {duplicates} duplicate, {invalid} invalid, {mismatched} text-mismatched, "
            f"and {bad_vectors} bad-vector rows"
        )
    for batch in pq.ParquetFile(path).iter_batches(batch_size=_BUFFER_ROWS, columns=["vector"]):
        _pack_float16_vectors(batch.column(0), dimensions)
    if expect_vector_fp is not None and vec_fp != expect_vector_fp:
        raise ValueError(f"Unified vector fingerprint mismatch in {path.name}")
    table = pq.read_table(path, columns=["source_id", "member_key"])
    return fingerprint, vec_fp, set(zip(table["source_id"].to_pylist(), table["member_key"].to_pylist(), strict=True))


def _reusable_unified(previous, per_document, identities, per_doc_vectors, dimensions):
    """Yield previous unified files whose stamp, permissions, coordinates, texts, and vectors all match."""
    path = Path(previous) / MANIFEST
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (manifest.get("format") != FORMAT or manifest.get("layout") != LAYOUT_UNIFIED
            or manifest.get("dimensions") != dimensions or manifest.get("duckdb") != duckdb.__version__):
        return
    for entry in manifest["files"]:
        source = Path(previous) / entry["name"]
        if source.is_symlink() or not source.is_file():
            continue
        source_stat = source.stat()
        if not (source_stat.st_mode & stat.S_IROTH) or _stamp(source) != entry["stamp"]:
            continue
        table = pq.read_table(source, columns=["source_id", "member_key"])
        keys = set(zip(table["source_id"].to_pylist(), table["member_key"].to_pylist(), strict=True))
        if len(keys) != entry["documents"] or not keys <= per_document.keys():
            continue
        fingerprint, vec_fp = _EMPTY, _EMPTY_VEC
        for key in keys:
            fingerprint = combine(fingerprint, per_document[key])
            vec_fp = _combine_vec(vec_fp, per_doc_vectors[key])
        if (list(fingerprint) == entry["fingerprint"]
                and _text_digest(keys, identities) == entry["text_digest"]
                and list(vec_fp) == entry.get("serving_vector_fingerprint")):
            yield source, entry, keys


def _existing(output, release_id, serving_stamps, *, layout=None, dimensions=None):
    """Return a completed build of the same inputs; refuse any other directory at ``output``."""
    manifest = json.loads((output / MANIFEST).read_text(encoding="utf-8")) if (output / MANIFEST).is_file() else {}
    if (manifest.get("format") == FORMAT and manifest.get("release_id") == release_id
            and (layout is None or manifest.get("layout", LAYOUT_DUAL) == layout)
            and (dimensions is None or manifest.get("dimensions") == dimensions)
            and manifest.get("serving") == serving_stamps
            and {p.name for p in output.glob("*.parquet")} == {f["name"] for f in manifest["files"]}
            and all(_stamp(output / f["name"]) == f["stamp"] for f in manifest["files"])):
        return manifest
    raise ValueError(f"{output} already exists for different inputs; choose a new output directory")


def stamp_keywords_manifest(serving, prepared, output, *, release_id, expected_passages=None,
                            expected_documents=None, memory_limit="256MB"):
    """Verify an existing keyword Parquet directory and atomically seed ``manifest.json`` in place.

    Never rewrites existing Parquet files. Once stamped, subsequent ``ensure_keywords(..., previous=...)``
    runs can hard-link unchanged files directly.
    """
    serving, prepared, output = Path(serving), Path(prepared), Path(output)
    if not output.is_dir():
        raise ValueError(f"Keyword directory does not exist: {output}")
    serving_files = sorted(serving.glob("*.parquet"))
    if not serving_files:
        raise ValueError(f"No passage Parquet files in {serving}")
    serving_stamps = [[p.name, *_stamp(p)] for p in serving_files]
    if (output / MANIFEST).exists():
        return _existing(output, release_id, serving_stamps, layout=LAYOUT_DUAL)
    kw_files = sorted(output.glob("*.parquet"))
    if not kw_files:
        raise ValueError(f"No keyword Parquet files in {output}")
    work = output.parent / f".{output.name}.stamp-{os.getpid()}"
    work.mkdir()
    try:
        located, identities, body_hashes = _documents(prepared)
        with closing(_connect(work, memory_limit)) as db:
            per_document = _serving(db, serving_files, located, body_hashes)
            total = _EMPTY
            for fingerprint in per_document.values():
                total = combine(total, fingerprint)
            if expected_passages is not None and total[0] != expected_passages:
                raise ValueError(f"Serving holds {total[0]} passages, not the declared {expected_passages}")
            if expected_documents is not None and len(per_document) != expected_documents:
                raise ValueError(f"Serving covers {len(per_document)} documents, not the declared {expected_documents}")
            entries, covered, combined = [], set(), _EMPTY
            for path in kw_files:
                if path.is_symlink():
                    raise ValueError(f"Refusing to stamp symlinked keyword file: {path.name}")
                if not (path.stat().st_mode & stat.S_IROTH):
                    raise ValueError(f"Keyword file is not world-readable: {path.name}")
                fingerprint, keys = _verify(db, path)
                if keys & covered:
                    raise ValueError(f"{path.name} repeats documents held by another keyword file")
                covered |= keys
                combined = combine(combined, fingerprint)
                entries.append(dict(name=path.name, rows=fingerprint[0], documents=len(keys),
                                    fingerprint=list(fingerprint), text_digest=_text_digest(keys, identities),
                                    stamp=_stamp(path)))
        if combined != total or covered != per_document.keys():
            raise ValueError("Existing keyword passages differ from the serving passages")
        manifest = dict(format=FORMAT, release_id=release_id, duckdb=duckdb.__version__, passages=total[0],
                        documents=len(per_document), fingerprint=list(total), serving=serving_stamps,
                        reused=0, files=sorted(entries, key=lambda e: e["name"]))
        tmp_manifest = output / f".{MANIFEST}.tmp-{os.getpid()}"
        try:
            tmp_manifest.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            with tmp_manifest.open("rb") as stream:
                os.fsync(stream.fileno())
            os.chmod(tmp_manifest, 0o444)
            os.replace(tmp_manifest, output / MANIFEST)
            _fsync_dir(output)
        finally:
            tmp_manifest.unlink(missing_ok=True)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_unified_passages(serving, prepared, output, *, release_id, dimensions, previous=None,
                           expected_passages=None, expected_documents=None, memory_limit="256MB"):
    """Build, verify, and atomically publish a ``layout="unified"`` passage Parquet directory.

    Each output file combines passage metadata, verbatim ``text``, and ``vector: fixed_size_list<float16>[D]``
    matching SpicyEngine's unified passage index contract. Unchanged shards from ``previous`` are reused
    via hard link when their custody stamp, coordinates, document texts, and serving vectors all match.
    """
    serving, prepared, output = Path(serving), Path(prepared), Path(output)
    unified_schema(dimensions)
    files = sorted(serving.glob("*.parquet"))
    if not files:
        raise ValueError(f"No passage Parquet files in {serving}")
    serving_stamps = [[p.name, *_stamp(p)] for p in files]
    if output.exists():
        return _existing(output, release_id, serving_stamps, layout=LAYOUT_UNIFIED, dimensions=dimensions)
    serving_is_fp16 = True
    for p in files:
        schema = pq.read_schema(p)
        if "vector" not in schema.names:
            raise ValueError(f"Serving file {p.name} lacks required vector column")
        vec_type = schema.field("vector").type
        if not (pa.types.is_list(vec_type) or pa.types.is_fixed_size_list(vec_type)):
            raise ValueError(f"Serving file {p.name} vector column must be a list or fixed-size list")
        if not pa.types.is_float16(vec_type.value_type):
            serving_is_fp16 = False
    for stale in [*output.parent.glob(f".{output.name}.tmp-*"), *output.parent.glob(f".{output.name}.work-*")]:
        shutil.rmtree(stale)
    staging = output.parent / f".{output.name}.tmp-{os.getpid()}"
    work = output.parent / f".{output.name}.work-{os.getpid()}"
    staging.mkdir(mode=0o755)
    work.mkdir()
    try:
        located, identities, body_hashes = _documents(prepared)
        with closing(_connect(work, memory_limit)) as db:
            per_document = _serving(db, files, located, body_hashes)
            per_doc_vectors = _serving_vectors(db, files, dimensions)
            total, total_vec = _EMPTY, _EMPTY_VEC
            for doc_key, fingerprint in per_document.items():
                total = combine(total, fingerprint)
                total_vec = _combine_vec(total_vec, per_doc_vectors[doc_key])
            if expected_passages is not None and total[0] != expected_passages:
                raise ValueError(f"Serving holds {total[0]} passages, not the declared {expected_passages}")
            if expected_documents is not None and len(per_document) != expected_documents:
                raise ValueError(f"Serving covers {len(per_document)} documents, not the declared {expected_documents}")
            entries, covered, combined, combined_vec = [], set(), _EMPTY, _EMPTY_VEC
            for source, entry, keys in (
                _reusable_unified(previous, per_document, identities, per_doc_vectors, dimensions)
                if previous else ()
            ):
                if keys & covered:
                    continue
                try:
                    os.link(source, staging / entry["name"])
                except OSError:
                    continue
                covered |= keys
                combined = combine(combined, tuple(entry["fingerprint"]))
                combined_vec = _combine_vec(combined_vec, tuple(entry["serving_vector_fingerprint"]))
                entries.append(entry | {"reused_from": str(source)})
            pending = sorted(per_document.keys() - covered)
            if pending:
                name = None
                if entries:
                    taken = {e["name"] for e in entries}
                    name = next(n for n in (f"delta-{release_id[:12]}{s}.parquet" for s in ("", *range(1, 1000)))
                                if n not in taken)
                for path in _build_unified(db, files, located, pending, staging, work, name, dimensions):
                    table_keys = pq.read_table(path, columns=["source_id", "member_key"])
                    file_keys = set(zip(table_keys["source_id"].to_pylist(), table_keys["member_key"].to_pylist(),
                                        strict=True))
                    expected_file_vec_fp = _EMPTY_VEC
                    for doc_key in file_keys:
                        expected_file_vec_fp = _combine_vec(expected_file_vec_fp, per_doc_vectors[doc_key])
                    fingerprint, written_vec_fp, keys = _verify_unified(
                        db, path, dimensions, expect_vector_fp=expected_file_vec_fp if serving_is_fp16 else None)
                    if keys & covered:
                        raise ValueError(f"{path.name} repeats documents held by another unified file")
                    covered |= keys
                    combined = combine(combined, fingerprint)
                    combined_vec = _combine_vec(combined_vec, expected_file_vec_fp)
                    entries.append(dict(
                        name=path.name, rows=fingerprint[0], documents=len(keys),
                        fingerprint=list(fingerprint), text_digest=_text_digest(keys, identities),
                        serving_vector_fingerprint=list(expected_file_vec_fp),
                        vector_fingerprint=list(written_vec_fp), stamp=_stamp(path)))
        if combined != total or combined_vec != total_vec or covered != per_document.keys():
            raise ValueError("Unified passages differ from the serving passages")
        manifest = dict(
            format=FORMAT, layout=LAYOUT_UNIFIED, release_id=release_id, dimensions=dimensions,
            duckdb=duckdb.__version__, passages=total[0], documents=len(per_document),
            fingerprint=list(total), serving_vector_fingerprint=list(total_vec),
            serving=serving_stamps, reused=sum("reused_from" in e for e in entries),
            files=sorted(entries, key=lambda e: e["name"]))
        (staging / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(staging / MANIFEST, 0o444)
        os.chmod(staging, 0o755)
        _fsync_dir(staging)
        os.rename(staging, output)
        _fsync_dir(output.parent)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


def ensure_keywords(serving, prepared, output, *, release_id, previous=None, expected_passages=None,
                    expected_documents=None, memory_limit="256MB"):
    """Build, verify and atomically publish ``output`` (``keyword_parquet`` = ``<output>/*.parquet``).

    ``serving`` holds the release's passage Parquet and ``prepared`` its prepared document shards.
    ``previous`` names an earlier keyword directory to hard-link unchanged files from. Rerunning with
    unchanged serving files returns the existing manifest; any other existing ``output`` is refused.
    """
    serving, prepared, output = Path(serving), Path(prepared), Path(output)
    files = sorted(serving.glob("*.parquet"))
    if not files:
        raise ValueError(f"No passage Parquet files in {serving}")
    serving_stamps = [[p.name, *_stamp(p)] for p in files]
    if output.exists():
        return _existing(output, release_id, serving_stamps, layout=LAYOUT_DUAL)
    for stale in [*output.parent.glob(f".{output.name}.tmp-*"), *output.parent.glob(f".{output.name}.work-*")]:
        shutil.rmtree(stale)
    staging = output.parent / f".{output.name}.tmp-{os.getpid()}"
    work = output.parent / f".{output.name}.work-{os.getpid()}"
    staging.mkdir(mode=0o755)
    work.mkdir()
    try:
        located, identities, body_hashes = _documents(prepared)
        with closing(_connect(work, memory_limit)) as db:
            per_document = _serving(db, files, located, body_hashes)
            total = _EMPTY
            for fingerprint in per_document.values():
                total = combine(total, fingerprint)
            if expected_passages is not None and total[0] != expected_passages:
                raise ValueError(f"Serving holds {total[0]} passages, not the declared {expected_passages}")
            if expected_documents is not None and len(per_document) != expected_documents:
                raise ValueError(f"Serving covers {len(per_document)} documents, not the declared {expected_documents}")
            entries, covered, combined = [], set(), _EMPTY
            for source, entry, keys in (_reusable(previous, per_document, identities) if previous else ()):
                if keys & covered:
                    continue
                try:
                    os.link(source, staging / entry["name"])
                except OSError:
                    continue  # Another filesystem: rebuild these documents instead of copying.
                covered |= keys
                combined = combine(combined, tuple(entry["fingerprint"]))
                entries.append(entry | {"reused_from": str(source)})
            pending = sorted(per_document.keys() - covered)
            if pending:
                name = None
                if entries:
                    taken = {e["name"] for e in entries}
                    name = next(n for n in (f"delta-{release_id[:12]}{s}.parquet" for s in ("", *range(1, 1000)))
                                if n not in taken)
                for path in _build(db, files, located, pending, staging, work, name):
                    fingerprint, keys = _verify(db, path)
                    if keys & covered:
                        raise ValueError(f"{path.name} repeats documents held by another keyword file")
                    covered |= keys
                    combined = combine(combined, fingerprint)
                    entries.append(dict(name=path.name, rows=fingerprint[0], documents=len(keys),
                                        fingerprint=list(fingerprint), text_digest=_text_digest(keys, identities),
                                        stamp=_stamp(path)))
        if combined != total or covered != per_document.keys():
            raise ValueError("Keyword passages differ from the serving passages")
        manifest = dict(format=FORMAT, release_id=release_id, duckdb=duckdb.__version__, passages=total[0],
                        documents=len(per_document), fingerprint=list(total), serving=serving_stamps,
                        reused=sum("reused_from" in e for e in entries),
                        files=sorted(entries, key=lambda e: e["name"]))
        (staging / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(staging / MANIFEST, 0o444)
        os.chmod(staging, 0o755)
        _fsync_dir(staging)
        os.rename(staging, output)
        _fsync_dir(output.parent)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving", required=True, type=Path, help="Directory holding passage embedding Parquet")
    parser.add_argument("--prepared", required=True, type=Path, help="Directory holding prepared document shards")
    parser.add_argument("--output", required=True, type=Path, help="Target keyword or unified Parquet directory")
    parser.add_argument("--release-id", required=True, help="64-hex release identifier")
    parser.add_argument("--previous", type=Path, help="Prior output directory to hard-link unchanged files from")
    parser.add_argument("--expected-passages", type=int, help="Require this exact total passage count")
    parser.add_argument("--expected-documents", type=int, help="Require this exact document count")
    parser.add_argument("--memory-limit", default="256MB", help="DuckDB memory cap (default: 256MB)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build-unified", action="store_true",
                      help="Build combined text + float16 vector Parquet for SpicyEngine layout='unified'")
    mode.add_argument("--stamp-manifest", action="store_true",
                      help="Verify an existing keyword Parquet directory and seed manifest.json in place")
    parser.add_argument("--dimensions", type=int, help="Embedding dimensions (required with --build-unified)")
    args = parser.parse_args()
    if args.build_unified:
        if args.dimensions is None:
            parser.error("--build-unified requires --dimensions")
        manifest = build_unified_passages(
            args.serving, args.prepared, args.output, release_id=args.release_id, dimensions=args.dimensions,
            previous=args.previous, expected_passages=args.expected_passages,
            expected_documents=args.expected_documents, memory_limit=args.memory_limit)
    elif args.stamp_manifest:
        manifest = stamp_keywords_manifest(
            args.serving, args.prepared, args.output, release_id=args.release_id,
            expected_passages=args.expected_passages, expected_documents=args.expected_documents,
            memory_limit=args.memory_limit)
    else:
        manifest = ensure_keywords(
            args.serving, args.prepared, args.output, release_id=args.release_id, previous=args.previous,
            expected_passages=args.expected_passages, expected_documents=args.expected_documents,
            memory_limit=args.memory_limit)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
