"""Optional body-inspection results and catalog input fingerprints.

Source and filename reuse comes from the published inventory, not extra tables.
Empty result rows mean an inspection completed without a classification. Missing
bodies never create result rows. All source bytes and receipts remain authoritative.
"""

from hashlib import sha256
from pathlib import Path
import json
import os
import re
from itertools import islice
import tempfile
import time

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.raw_archive import decode_table, encode_table


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def read(self, key):
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def keys(self, prefix):
        return (str(path.relative_to(self.root))
                for path in sorted((self.root / prefix).rglob('*')) if path.is_file())

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
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)


    def put_catalog_manifest(self, data, *, expected_version):
        """Compare and replace the selector while holding a local writer lock."""
        import fcntl
        from congress_api.retention.catalog_publication import MANIFEST_KEY
        lock = self.root / 'indexes/.catalog.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            current = self.read(MANIFEST_KEY)
            version = sha256(current).hexdigest() if current is not None else None
            if version != expected_version:
                raise RuntimeError('Concurrent catalog update; selected snapshot preserved')
            self.put(MANIFEST_KEY, data)



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


def result_checkpoint(store, name, fingerprint, keys, results, *, interval=60, clock=None):
    """Periodically retain completed results, without introducing another format."""
    clock = clock or time.monotonic
    saved_at, saved_count = clock(), len(results)

    def checkpoint(*, force=False):
        nonlocal saved_at, saved_count
        now = clock()
        if force or (len(results) != saved_count and now - saved_at >= interval):
            save_results(store, name, fingerprint, keys, results)
            saved_at, saved_count = now, len(results)

    return checkpoint


def capture_digest(table):
    """Versioned logical rows: independent of Parquet encoding and Arrow chunks.

    Capture columns contain strings and integers. Include ordered field names,
    types and nullability, then one JSON array per row. Ignore schema metadata;
    it describes the checkpoint, not the captured evidence.
    """
    digest = sha256(b'capture-rows-v1\n')

    def add(value):
        digest.update(json.dumps(value, ensure_ascii=True, allow_nan=False,
                                 separators=(',', ':')).encode('ascii'))
        digest.update(b'\n')

    add([[field.name, str(field.type), field.nullable] for field in table.schema])
    add(len(table))
    for batch in table.to_batches(max_chunksize=4096):
        for row in zip(*(column.to_pylist() for column in batch.columns)):
            add(row)
    return 'rows-v1:' + digest.hexdigest()


def legacy_capture_digest(table):
    """Verify old checkpoints with their original, pinned Parquet writer only."""
    digest = sha256()
    for offset in range(0, len(table), 4096):
        batch = table.slice(offset, 4096).combine_chunks().to_batches()[0]
        digest.update(
            encode_table(pa.Table.from_batches([batch]).replace_schema_metadata(None))
        )
    return digest.hexdigest()


def capture_digest_matches(table, expected):
    """Accept a verified legacy checkpoint; all subsequent writes use rows-v1.

    A legacy writer mismatch never authorizes replay or bypasses verification.
    Keep the archive's PyArrow pin until legacy checkpoints have been replaced
    by successful, explicitly requested capture/update operations.
    """
    if not isinstance(expected, bytes):
        return False
    if expected.startswith(b'rows-v1:'):
        return expected == capture_digest(table).encode()
    if re.fullmatch(rb'[0-9a-f]{64}', expected):
        return expected == legacy_capture_digest(table).encode()
    return False


def source_fingerprint():
    """Source interpretation changes independently of filename and PDF-cover rules."""
    from congress_api.retention import document_index, document_recovery, raw_catalog, catalog_staging
    from congress_api import parsers, models

    paths = [
        Path(__file__),
        *(
            Path(module.__file__)
            for module in (document_index, document_recovery, raw_catalog, catalog_staging)
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
