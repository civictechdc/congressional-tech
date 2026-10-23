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
    from bisect import bisect_left
    if db.execute('SELECT 1 FROM reading_rows LIMIT 1').fetchone() is None:
        return None
    all_rows = db.execute('SELECT digest, body, reference, bytes FROM reading_rows').fetchall()
    all_rows.sort(key=lambda item: item[0])
    digests = [item[0] for item in all_rows]
    byte_prefix = [0] * (len(all_rows) + 1)
    acc = 0
    for idx, item in enumerate(all_rows):
        acc += item[3]
        byte_prefix[idx + 1] = acc

    def leaves(prefix):
        lo = bisect_left(digests, prefix)
        hi = bisect_left(digests, prefix + 'g', lo)
        rows = hi - lo
        if not rows:
            return
        size = byte_prefix[hi] - byte_prefix[lo]
        if rows > LEAF_ENTRIES or size > LEAF_BYTES:
            if len(prefix) == 64:
                raise ValueError('Adopted reading references exceed their hash partition budget')
            for char in '0123456789abcdef':
                yield from leaves(prefix + char)
            return
        slice_rows = sorted(all_rows[lo:hi], key=lambda item: item[1])
        entries = {body: json.loads(reference) for _, body, reference, _ in slice_rows}
        yield prefix, dict(entries=entries)

    return storage.readings.routes.replace_stream(None, '', leaves(''))
