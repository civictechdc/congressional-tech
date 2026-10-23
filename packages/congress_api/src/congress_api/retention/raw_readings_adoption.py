"""Explicit, bounded import of a retained per-reader cache into raw selection.

Only selected reading references change. The source cache and capture parts
remain untouched. Native normal updates read only the resulting keyed parts.
"""
from contextlib import closing
from hashlib import sha256
import base64
import json
from pathlib import Path
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq

from .derived_files import file_identity, check_identity
from .immutable_metadata import encoded
from .raw_readings import PART_BYTES, PART_ROWS, READER_PREFIX, part_rows
from .capture_metadata import RESULT_COLUMNS


def adopt_body_readings(store, parts, *, cache_path, expected, directory):
    """Offline convenience for small seeds; maintained adoption streams refs."""
    return list(iter_adopted_body_readings(store, parts, cache_path=cache_path,
                                         expected=expected, directory=directory))


def iter_adopted_body_readings(store, parts, *, cache_path, expected, directory):
    """Import exact retained cache bytes; caller pins their source provenance.

    Duplicate (reader, body) records keep the last value, matching the existing
    cache loader. Each body's reader results precede its first capture fallback.
    SQLite holds the archive-sized grouping; each emitted part is bounded.
    """
    identity = file_identity(cache_path)
    check_identity(identity, expected, 'retained body cache')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # The staging file is disposable. Content-addressed outputs make retry safe.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='readings-', dir=directory) as attempt, \
            pq.ParquetFile(cache_path) as source, \
            closing(sqlite3.connect(Path(attempt) / 'readings.sqlite')) as db:
        schema = source.schema_arrow
        if (not {'reader', 'body_key'} <= set(schema.names)
                or any(field.type != (pa.string() if field.name in ('reader', 'body_key')
                                      else pa.list_(pa.string())) for field in schema)):
            raise ValueError('Unexpected legacy reader cache schema')
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192;'
                         'CREATE TABLE results(body TEXT, reader TEXT, value TEXT, PRIMARY KEY(body,reader));'
                         'CREATE TABLE capture(body TEXT PRIMARY KEY, value TEXT, reference TEXT);'
                         'CREATE TABLE original_parts(ordinal INTEGER PRIMARY KEY, value TEXT);')
        fields = set(schema.names) - {'reader', 'body_key'}
        for batch in source.iter_batches(batch_size=256):
            if batch.nbytes > PART_BYTES:
                raise ValueError('Legacy reader cache batch exceeds decoded-byte budget')
            for row in batch.to_pylist():
                body, reader = row['body_key'], row['reader']
                if not isinstance(body, str) or not body or not isinstance(reader, str) or not reader:
                    raise ValueError('Legacy reader cache lacks exact reader/body identity')
                db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)', (body, reader, encoded(row).decode()))
        identity.require(cache_path)
        for ordinal, reference in enumerate(parts):
            db.execute('INSERT INTO original_parts VALUES (?,?)', (ordinal, encoded(reference).decode()))
            for row in part_rows(store, reference):
                if db.execute('SELECT 1 FROM results WHERE body=? LIMIT 1', (row['body_key'],)).fetchone():
                    fields.update(set(row) - set(RESULT_COLUMNS))
                    db.execute('INSERT OR IGNORE INTO capture VALUES (?,?,?)',
                               (row['body_key'], encoded(row).decode(), encoded(reference).decode()))
        schema = pa.schema(
            [(name, pa.string()) for name in (*RESULT_COLUMNS, 'reader')]
            + [(name, pa.list_(pa.string())) for name in sorted(fields)],
            metadata=dict(format_version='2', source_cache_sha256=identity['sha256'],
                          source_cache_bytes=str(identity['bytes']),
                          source_cache_version=str(expected.get('version', 'local-retained-file')),
                          source_cache_schema=base64.b64encode(source.schema_arrow.serialize().to_pybytes()).decode()))
        buffer, provenance = [], {}
        buffer_bytes = 0

        def flush():
            nonlocal buffer_bytes
            if not buffer:
                return
            selected_schema = schema.with_metadata({**schema.metadata,
                b'capture_parts': encoded([provenance[key] for key in sorted(provenance)])})
            table = pa.Table.from_pylist(buffer, schema=selected_schema)
            if table.nbytes > PART_BYTES:
                raise ValueError('Adopted reader part exceeds decoded-byte budget')
            sink = pa.BufferOutputStream()
            pq.write_table(table, sink, compression='zstd', compression_level=3)
            data = sink.getvalue().to_pybytes()
            if len(data) > PART_BYTES:
                raise ValueError('Adopted reader part exceeds stored-byte budget')
            digest = sha256(data).hexdigest()
            key = READER_PREFIX + 'adopted-' + digest + '.parquet'
            from .raw_readings import _READING_PART_CACHE
            raw_cache_dir = getattr(store, 'cache_dir', None)
            if raw_cache_dir is not None:
                cache_dir = Path(raw_cache_dir) / 'reading-parts'
                cache_file = cache_dir / (sha256(key.encode()).hexdigest() + '.parquet')
                if not cache_file.is_file():
                    store.put(key, data, immutable=True)
                    try:
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        tmp = cache_file.with_suffix('.tmp')
                        tmp.write_bytes(data)
                        tmp.replace(cache_file)
                    except OSError:
                        pass
                if len(_READING_PART_CACHE) < 4096:
                    _READING_PART_CACHE[key] = data
            else:
                store.put(key, data, immutable=True)
            reference = dict(key=key, bytes=len(data), sha256=digest, rows=len(buffer))
            buffer.clear()
            buffer_bytes = 0
            provenance.clear()
            return reference

        for body, in db.execute('SELECT DISTINCT body FROM results ORDER BY body'):
            row_count, = db.execute('SELECT count(*) FROM results WHERE body=?', (body,)).fetchone()
            capture = db.execute('SELECT value,reference FROM capture WHERE body=?', (body,)).fetchone()
            if row_count + bool(capture) > PART_ROWS:
                raise ValueError('One body exceeds adopted reader part bounds')
            group, staged_bytes = [], 0
            for value, in db.execute('SELECT value FROM results WHERE body=? ORDER BY reader', (body,)):
                staged_bytes += len(value.encode())
                if staged_bytes > PART_BYTES:
                    raise ValueError('One body exceeds adopted reader staging-byte budget')
                group.append(json.loads(value))
            if capture:
                staged_bytes += len(capture[0].encode())
                if staged_bytes > PART_BYTES:
                    raise ValueError('One body exceeds adopted reader staging-byte budget')
                group.append(json.loads(capture[0]))
            group_bytes = pa.Table.from_pylist(group, schema=schema).nbytes
            if len(group) > PART_ROWS or group_bytes > PART_BYTES:
                raise ValueError('One body exceeds adopted reader part bounds')
            if buffer and (len(buffer) + len(group) > PART_ROWS or
                           buffer_bytes + group_bytes > PART_BYTES):
                yield flush()
            buffer.extend(group)
            buffer_bytes += group_bytes
            if capture:
                reference = json.loads(capture[1])
                provenance[reference['key']] = reference
        if buffer:
            yield flush()
        # Adopted entries win first; capture-only bodies keep their exact parts.
        for value, in db.execute('SELECT value FROM original_parts ORDER BY ordinal'):
            yield json.loads(value)
