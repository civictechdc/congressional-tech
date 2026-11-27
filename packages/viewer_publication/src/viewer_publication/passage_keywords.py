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
import pyarrow.parquet as pq

FORMAT = 1
MANIFEST = "manifest.json"
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
_BUFFER_ROWS = 4096


def combine(a, b):
    """Combine two order-independent multiset fingerprints (count, xor, sum, xor, sum)."""
    return (a[0] + b[0], a[1] ^ b[1], a[2] + b[2], a[3] ^ b[3], a[4] + b[4])


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


def _existing(output, release_id, serving_stamps):
    """Return a completed build of the same inputs; refuse any other directory at ``output``."""
    manifest = json.loads((output / MANIFEST).read_text(encoding="utf-8")) if (output / MANIFEST).is_file() else {}
    if (manifest.get("format") == FORMAT and manifest.get("release_id") == release_id
            and manifest.get("serving") == serving_stamps
            and {p.name for p in output.glob("*.parquet")} == {f["name"] for f in manifest["files"]}
            and all(_stamp(output / f["name"]) == f["stamp"] for f in manifest["files"])):
        return manifest
    raise ValueError(f"{output} already exists for different inputs; choose a new keyword directory")


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
        return _existing(output, release_id, serving_stamps)
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
    parser.add_argument("--output", required=True, type=Path, help="Target keyword Parquet directory to publish")
    parser.add_argument("--release-id", required=True, help="64-hex release identifier")
    parser.add_argument("--previous", type=Path, help="Prior keyword directory to hard-link unchanged files from")
    parser.add_argument("--expected-passages", type=int, help="Require this exact total passage count")
    parser.add_argument("--expected-documents", type=int, help="Require this exact document count")
    parser.add_argument("--memory-limit", default="256MB", help="DuckDB memory cap (default: 256MB)")
    args = parser.parse_args()
    manifest = ensure_keywords(
        args.serving, args.prepared, args.output, release_id=args.release_id, previous=args.previous,
        expected_passages=args.expected_passages, expected_documents=args.expected_documents,
        memory_limit=args.memory_limit)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
