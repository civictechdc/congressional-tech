"""Retain exact reading inputs for the existing bounded raw adoption owner."""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
from tempfile import TemporaryDirectory, NamedTemporaryFile

import pyarrow as pa
import pyarrow.parquet as pq

from .capture_metadata import PREFIX
from .derived_files import file_identity, check_identity
from .immutable_metadata import encoded
from .raw_reading_inventory import LINE_BYTES
from .raw_readings import PART_BYTES, PART_ROWS

CACHE_KEY = 'indexes/processing/bodies.parquet'


def _keys(store, db):
    db.execute('CREATE TABLE part_keys(key TEXT PRIMARY KEY)')
    for key in store.keys(PREFIX):
        if (not isinstance(key, str) or not key.startswith(PREFIX) or len(key.encode()) > LINE_BYTES
                or '..' in PurePosixPath(key).parts):
            raise ValueError('Invalid source reading part key')
        if key.endswith('.parquet'):
            db.execute('INSERT OR IGNORE INTO part_keys VALUES (?)', (key,))
    yield from (key for key, in db.execute('SELECT key FROM part_keys ORDER BY key'))


def verify_reading_sources(store, receipt):
    if store.version(CACHE_KEY) != receipt['cache']['version']:
        raise ValueError('Legacy reader cache changed during adoption')
    with TemporaryDirectory(prefix='reading-source-check-') as scratch, sqlite3.connect(Path(scratch)/'keys.sqlite') as db:
        db.execute('PRAGMA cache_size=-8192')
        digest = sha256()
        for key in _keys(store, db):
            digest.update(encoded(key) + b'\n')
        if digest.hexdigest() != receipt['capture_keys_sha256']:
            raise ValueError('Capture reading inventory changed during adoption')


def prepare_reading_input(store, *, directory):
    """Retain a source-proven JSONL input, never an application pending journal.

    The immutable input and its small receipt survive worker loss. Reopening
    verifies the exact local hash; adoption checks original source versions and
    key inventory immediately before its existing conditional raw selection.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / 'reading-inputs.json'
    if receipt_path.exists():
        with receipt_path.open('rb') as saved:
            raw = saved.read(LINE_BYTES + 1)
        if len(raw) > LINE_BYTES:
            raise ValueError('Reading input receipt exceeds its byte budget')
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict) or receipt.get('version') != 1
                or not isinstance(receipt.get('cache'), dict) or receipt['cache'].get('key') != CACHE_KEY
                or not isinstance(receipt.get('input'), dict)):
            raise ValueError('Unexpected reading input source receipt')
        identity = receipt.get('input', {})
        digest, size = identity.get('sha256'), identity.get('bytes')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)
                or type(size) is not int or size < 0):
            raise ValueError('Invalid retained reading input identity')
        path = directory / (digest + '.jsonl')
        check_identity(file_identity(path), receipt['input'], 'retained reading input')
        return path, receipt
    version = store.version(CACHE_KEY)
    cache = dict(key=CACHE_KEY, version=version)
    source = None
    if version != 'missing':
        source = directory / 'reader-caches' / (sha256(version.encode()).hexdigest() + '.parquet')
        source.parent.mkdir(parents=True, exist_ok=True)
        identity = store.read_body_cache_file(source, expected_version=version)
        if identity['version'] != version:
            raise ValueError('Reader cache source version differs')
        cache.update(bytes=identity['bytes'], sha256=identity['sha256'])
    key_digest, part_digest = sha256(), sha256()
    with TemporaryDirectory(prefix='reading-inputs-', dir=directory) as scratch, \
            sqlite3.connect(Path(scratch)/'parts.sqlite') as db, \
            NamedTemporaryFile(prefix='readings-', suffix='.partial', dir=directory, delete=False) as output:
        db.execute('PRAGMA cache_size=-8192')
        def parts():
            for key in _keys(store, db):
                key_digest.update(encoded(key) + b'\n')
                payload = store.read(key)
                if payload is None or not 0 < len(payload) <= PART_BYTES:
                    raise ValueError('Source reading part exceeds its stored-byte budget')
                rows = pq.ParquetFile(pa.BufferReader(payload)).metadata.num_rows
                if not 0 < rows <= PART_ROWS:
                    raise ValueError('Source reading part exceeds its row budget')
                reference = dict(key=key, bytes=len(payload), sha256=sha256(payload).hexdigest(), rows=rows)
                part_digest.update(encoded(reference) + b'\n')
                yield reference
        if source is None:
            references = parts()
        else:
            from .raw_readings_adoption import iter_adopted_body_readings
            references = iter_adopted_body_readings(store, parts(), cache_path=source,
                expected=identity, directory=directory)
        digest, size = sha256(), 0
        try:
            for reference in references:
                line = encoded(reference) + b'\n'
                if len(line) > LINE_BYTES:
                    raise ValueError('Reading reference exceeds its input line budget')
                output.write(line)
                digest.update(line)
                size += len(line)
        finally:
            references.close()
        output.flush()
        os.fsync(output.fileno())
    receipt = dict(version=1, input=dict(bytes=size, sha256=digest.hexdigest()), cache=cache,
        capture_keys_sha256=key_digest.hexdigest(), capture_parts_sha256=part_digest.hexdigest())
    verify_reading_sources(store, receipt)
    path = directory / (digest.hexdigest() + '.jsonl')
    try:
        os.link(output.name, path)
    except FileExistsError:
        check_identity(file_identity(path), receipt['input'], 'retained reading input')
    Path(output.name).unlink()
    with NamedTemporaryFile(prefix='input-receipt-', suffix='.partial', dir=directory, delete=False) as seal:
        seal.write(encoded(receipt))
        seal.flush()
        os.fsync(seal.fileno())
    try:
        os.link(seal.name, receipt_path)
    except FileExistsError:
        if receipt_path.read_bytes() != encoded(receipt):
            raise ValueError('Concurrent reading adoption inputs differ')
    Path(seal.name).unlink()
    folder = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    return path, receipt
