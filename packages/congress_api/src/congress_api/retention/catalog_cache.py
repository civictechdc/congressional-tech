"""Small, disposable Parquet checkpoints for completed interpretation.

These are internal processing state, separate from the public document tables.
Empty result rows mean an inspection completed without a classification. Missing
bodies never create result rows. All source bytes and receipts remain authoritative.
"""

from hashlib import sha256
from pathlib import Path
import os
from itertools import islice
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.raw_archive import decode_table, encode_table


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def read(self, key):
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def put(self, key, data, *, immutable=False):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if immutable and path.exists():
            if path.read_bytes() != data:
                raise ValueError(f"Conflicting immutable object: {key}")
            return
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def load_results(store, name, fingerprint, keys, *, reuse=True):
    payload = store.read(f"indexes/processing/{name}.parquet")
    if payload is None or not reuse:
        return {}
    table = decode_table(payload)
    if (table.schema.metadata or {}).get(b"parser_fingerprint") != fingerprint.encode():
        return {}
    return {
        tuple(row.pop(key) for key in keys): {
            k: v for k, v in row.items() if v is not None
        }
        for batch in table.to_batches(max_chunksize=4096)
        for row in batch.to_pylist()
    }


def save_results(store, name, fingerprint, keys, results):
    fields = sorted({field for values in results.values() for field in values})
    schema = pa.schema(
        [
            *(pa.field(key, pa.string()) for key in keys),
            *(pa.field(field, pa.list_(pa.string())) for field in fields),
        ],
        metadata={"parser_fingerprint": fingerprint},
    )
    rows = ({**dict(zip(keys, key)), **values} for key, values in results.items())
    store.put(f"indexes/processing/{name}.parquet", encode_rows(rows, schema))


def capture_digest(table):
    """Check an append-only prefix, independent of Arrow's input chunk boundaries."""
    digest = sha256()
    for offset in range(0, len(table), 4096):
        batch = table.slice(offset, 4096).combine_chunks().to_batches()[0]
        digest.update(
            encode_table(pa.Table.from_batches([batch]).replace_schema_metadata(None))
        )
    return digest.hexdigest()


SOURCES_KEY = "indexes/processing/sources.parquet"


def source_fingerprint():
    """Source interpretation changes independently of filename and PDF-cover rules."""
    from congress_api.retention import document_index, document_recovery, raw_catalog
    from congress_api import parsers, models

    paths = [
        Path(__file__),
        *(
            Path(module.__file__)
            for module in (document_index, document_recovery, raw_catalog)
        ),
    ]
    for module in (parsers, models):
        paths.extend(
            path
            for path in Path(module.__file__).parent.rglob("*.py")
            if path.name != "document_cover.py"
        )
    digest = sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def encode_rows(rows, schema):
    """Serialize bounded batches without duplicating the decoded catalog in memory."""
    stream = pa.BufferOutputStream()
    rows = iter(rows)
    with pq.ParquetWriter(stream, schema, compression="zstd") as writer:
        while batch := list(islice(rows, 4096)):
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    return stream.getvalue().to_pybytes()


def source_checkpoint(rows, context, metadata):
    """Keep source rows, meeting facts and exact URL associations in one table."""
    from congress_api.retention import document_index as index

    def entries():
        for row in rows:
            yield dict(row, _entry="source")
        for url in context.by_url:
            yield dict(context.for_url(url), _entry="url", _key=url)
        for key, values in context.meetings.items():
            yield dict(
                {k: sorted(v) for k, v in values.items()},
                _entry="meeting",
                _key="/".join(key),
            )
        for original, edges in context.transfers.items():
            for target, values in edges:
                yield dict(values, _entry="transfer", _key=original, _target=target)

    strings = {"_entry", "_key", "_target", "body_key", "filename", "source_url"}
    names = strings | index.SOURCE_CONTEXT_FIELDS | {key for row in rows for key in row}
    schema = pa.schema(
        [
            (name, pa.string() if name in strings else index.metadata_type(name))
            for name in sorted(names)
        ],
        metadata=metadata,
    )
    return encode_rows(entries(), schema)


def restore_sources(table):
    from congress_api.retention import document_index as index

    context, sources, transfers = index.DocumentSources(), {}, []
    for row in (
        row
        for batch in table.to_batches(max_chunksize=4096)
        for row in batch.to_pylist()
    ):
        kind, key, target = (row.pop(name) for name in ("_entry", "_key", "_target"))
        row = {k: v for k, v in row.items() if v is not None}
        if kind == "source":
            identity = tuple(
                row.get(name) for name in ("body_key", "filename", "source_url")
            )
            sources[identity] = {
                **dict(zip(("body_key", "filename", "source_url"), identity)),
                **row,
            }
        else:
            values = {k: v for k, v in row.items() if k in index.SOURCE_CONTEXT_FIELDS}
            if kind == "url":
                context.add_url(key, values)
            elif kind == "meeting":
                meeting = tuple(key.split("/"))
                context.meetings[meeting] = {k: set(v) for k, v in values.items()}
                context.events[meeting[2]].add(meeting)
            elif kind == "transfer":
                transfers.append((key, target, values))
            else:
                raise ValueError(f"Unknown source checkpoint entry: {kind}")
    for original, target, values in transfers:
        context.add_transfer(original, target, values)
    return sources, context
