"""Bounded adoption of reviewed body-reading references through existing routes.

SQLite is disposable input sorting space. Only the existing raw selector chooses
these immutable references; no pending work or record lifecycle is stored here.
"""
import json

from .immutable_metadata import encoded
from .partition_routing import key_hash
from .raw_readings import LEAF_ENTRIES, part_rows

LINE_BYTES = 1 << 20
LEAF_BYTES = 1 << 19


def stage_inventory(storage, db, path):
    db.executescript('CREATE TABLE reading_parts(ordinal INTEGER PRIMARY KEY,value TEXT);'
        'CREATE TABLE reading_rows(body TEXT PRIMARY KEY,digest TEXT,reference TEXT,bytes INTEGER);'
        'CREATE INDEX reading_route ON reading_rows(digest);')
    with path.open('rb') as source:
        ordinal = 0
        while line := source.readline(LINE_BYTES + 1):
            if len(line) > LINE_BYTES:
                raise ValueError('Reading reference input line exceeds its byte budget')
            try:
                reference = json.loads(line)
            except (ValueError, UnicodeError) as error:
                raise ValueError('Invalid investigated reading reference') from error
            if not isinstance(reference, dict) or set(reference) != {'key', 'bytes', 'sha256', 'rows'}:
                raise ValueError('Invalid investigated reading reference')
            raw = encoded(reference).decode()
            db.execute('INSERT INTO reading_parts VALUES (?,?)', (ordinal, raw))
            ordinal += 1
            for row in part_rows(storage.store, reference):
                body = row['body_key']
                if not isinstance(body, str) or not body:
                    raise ValueError('Reading reference lacks its body identity')
                # Sum an upper bound for the complete encoded metadata leaf,
                # including escaping; decoded Arrow size alone is insufficient.
                size = len(encoded(dict(entries={body: reference}))) + 256
                if size > LEAF_BYTES:
                    raise ValueError('One adopted reading reference exceeds its metadata budget')
                db.execute('INSERT OR IGNORE INTO reading_rows VALUES (?,?,?,?)',
                           (body, key_hash(body), raw, size))


def inventory_references(db):
    for value, in db.execute('SELECT value FROM reading_parts ORDER BY ordinal'):
        yield json.loads(value)


def select_inventory(storage, db):
    def leaves(prefix):
        where, args = 'digest>=? AND digest<?', (prefix, prefix + 'g')
        rows, size = db.execute(f'SELECT count(*),coalesce(sum(bytes),0) FROM reading_rows WHERE {where}', args).fetchone()
        if not rows:
            return
        if rows > LEAF_ENTRIES or size > LEAF_BYTES:
            if len(prefix) == 64:
                raise ValueError('Adopted reading references exceed their hash partition budget')
            for char in '0123456789abcdef':
                yield from leaves(prefix + char)
            return
        entries = {body: json.loads(reference) for body, reference in db.execute(
            f'SELECT body,reference FROM reading_rows WHERE {where} ORDER BY body', args)}
        yield prefix, dict(entries=entries)
    if db.execute('SELECT 1 FROM reading_rows LIMIT 1').fetchone() is None:
        return None
    return storage.readings.routes.replace_stream(None, '', leaves(''))
