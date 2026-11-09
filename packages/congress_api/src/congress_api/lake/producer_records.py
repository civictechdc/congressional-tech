"""Gate 5 records for lake snapshots appended after the checked-in anchors (ct-ud0b).

A table's head after a nightly run is a snapshot no checked-in record names. The daily
producer writes one record for each table it moved: its job, the clean commit that ran,
the head it left and the head it started from (`base`), with the base's own record pinned
by hash. Following the bases leads back to an anchor, a record checked in beside the
publish spec (the release's Basin import records), or to an empty table.

Records are written once under lake/producers/<table_uuid>/<snapshot>.json in the raw
bucket: outside provenance/, which the publisher pins exactly, and outside the public
viewer-publications/. A local root holds the same keys for local catalogs.

Before its first append a run writes the records it may owe (writer, bases, initial heads)
to producer-owed.json in its work directory and deletes the file once they are written.
If the final head read keeps failing, the file stays; daily.complete_owed_records writes
the records later (ct-8unc).

Cannot see: rows appended between a base and its head by a writer that bypassed the
shared R2 lock; the lineage check only proves the base is an ancestor reached by appends.
A late completion widens that window to the time between the run and its completion.
"""
import gzip
import hashlib
import json
from pathlib import Path
import re

PREFIX = 'lake/producers/'
DAILY_JOB = 'packages/congress_api/src/congress_api/lake/daily.py'
PIN_FIELDS = ('metadata_location', 'table_uuid', 'snapshot', 'schema_id')
RECORD_BYTES = 1 << 20
METADATA_BYTES = 64 << 20


def pin_of(selector):
    return {k: selector.get(k) for k in PIN_FIELDS}


def key_for(pin):
    uuid, snapshot = pin.get('table_uuid'), pin.get('snapshot')
    if not isinstance(uuid, str) or re.fullmatch('[0-9a-f-]{8,64}', uuid) is None:
        raise ValueError('Producer record key requires a table UUID')
    if type(snapshot) is not int:
        raise ValueError('Producer record key requires a snapshot id')
    return f'{PREFIX}{uuid}/{snapshot}.json'


def _code(error):
    response = getattr(error, 'response', None)
    if not isinstance(response, dict):
        return None
    return str((response.get('Error') or {}).get('Code'))


def encode(record):
    return (json.dumps(record, indent=1, sort_keys=True) + '\n').encode()


def identity(data):
    return dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


class ProducerRecords:
    """Checked-in anchors by table, then write-once records in R2 or under a local root."""

    def __init__(self, anchors=None, *, client=None, bucket=None, root=None):
        if (root is None) == (client is None or bucket is None):
            raise ValueError('Producer records need either an R2 client and bucket or a local root')
        self.anchors = dict(anchors or {})
        self.client, self.bucket = client, bucket
        self.root = Path(root).resolve() if root is not None else None

    def _get(self, key):
        if self.root is not None:
            path = self.root / key
            if not path.is_file():
                return None
            if path.stat().st_size > RECORD_BYTES:
                raise ValueError('Producer record exceeds its size bound: ' + key)
            return path.read_bytes()
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)['Body']
        except Exception as error:
            if _code(error) in {'404', 'NoSuchKey', 'NotFound'}:
                return None
            raise
        data = body.read(RECORD_BYTES + 1)
        if len(data) > RECORD_BYTES:
            raise ValueError('Producer record exceeds its size bound: ' + key)
        return data

    def find(self, name, pin):
        """(record, reference) for the record naming exactly this snapshot, or None."""
        data = self.anchors.get(name)
        if data is not None:
            record = json.loads(data)
            if pin_of(record.get('selector') or {}) == pin_of(pin):
                return record, dict(anchor=name, **identity(data))
        if pin.get('snapshot') is None:
            return None
        key = key_for(pin)
        data = self._get(key)
        if data is None:
            return None
        return json.loads(data), dict(key=key, **identity(data))

    def write(self, record):
        """Create the record once; an existing different record at that key refuses."""
        data = encode(record)
        key = key_for(record['selector'])
        if self.root is not None:
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open('xb') as target:
                    target.write(data)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError('Another producer record already names this snapshot: ' + key) from None
            return dict(key=key, **identity(data))
        import base64
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, IfNoneMatch='*',
                                   ContentType='application/json',
                                   ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode())
        except Exception as error:
            if _code(error) not in {'PreconditionFailed', '412'}:
                raise
            if self._get(key) != data:
                raise ValueError('Another producer record already names this snapshot: ' + key) from None
        return dict(key=key, **identity(data))

    def lineage(self, location):
        """{snapshot id: (parent id, operation)} from a table's Iceberg metadata file."""
        if location.startswith('s3://'):
            if self.client is None:
                raise ValueError('Remote table metadata needs the R2 client')
            bucket, key = location[len('s3://'):].split('/', 1)
            if bucket != self.bucket:
                raise ValueError('Table metadata lives outside the producer record bucket')
            data = self.client.get_object(Bucket=bucket, Key=key)['Body'].read(METADATA_BYTES + 1)
        else:
            path = Path(location.removeprefix('file://'))
            if path.stat().st_size > METADATA_BYTES:
                raise ValueError('Table metadata exceeds its size bound')
            data = path.read_bytes()
        if data[:2] == b'\x1f\x8b':
            data = gzip.decompress(data)
        if len(data) > METADATA_BYTES:
            raise ValueError('Table metadata exceeds its size bound')
        value = json.loads(data)
        return {s['snapshot-id']: (s.get('parent-snapshot-id'), (s.get('summary') or {}).get('operation'))
                for s in value.get('snapshots') or []}


def appended_from(lineage, head, base):
    """True when `base` (None: the table's first snapshot) is reached from `head` by appends only."""
    seen = set()
    current = head
    while current is not None and current != base:
        if current in seen or current not in lineage:
            return False
        seen.add(current)
        parent, operation = lineage[current]
        if operation != 'append':
            return False
        current = parent
    return current == base
