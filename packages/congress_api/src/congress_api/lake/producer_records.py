"""Gate 5 records for lake snapshots appended after the checked-in anchors (ct-ud0b).

A table's head after a nightly run is a snapshot no checked-in record names. The daily
producer writes one record for each table it moved: its job, the clean commit that ran,
the head it left and the head it started from (`base`), with the base's own record pinned
by hash. Following the bases leads back to an anchor, a record checked in beside the
publish spec (the release's Basin import records), or to an empty table.

Records are written once under lake/producers/<table_uuid>/<snapshot>.json in the raw
bucket: outside provenance/, which the publisher pins exactly, and outside the public
viewer-publications/. A local root holds the same keys for local catalogs.

Owed records (ct-8unc). Before its first append a daily run leaves, for each table, the
record it will owe minus its head under lake/producers/owed/<table_uuid>/<base>.json, keyed
by the head it appends onto. Its last step marks the moved ones recorded, or all of them
refused if its checkout changed. If the run dies or the catalog stops answering first,
the next preflight finds the unrecorded head's nearest recorded ancestor (the record
chain stops at the first recorded snapshot, so an owed record at an older base is never
read), checks that the head was reached from it by appends only, and writes the owed
record. Owed records are state, not proof: they change by compare-and-swap, and gate 5
reads only records.

One base rule (ct-medh). base_problems is what gate 5 (viewer_publication.producer_proof)
refuses about the snapshot a daily record appended onto, and what the daily preflight
(daily._producer_bases) refuses before it appends onto a head, in the same words. The
preflight cannot see the parts of gate 5 that need the publish model: a head record's
versions recomputed at its commit (record_problems' `versions`; gate 5 also judges a
table the night leaves unmoved as a head) and the per-row version counts. It judges
reachability from its own checkout's HEAD with its own anchors, which in the publish job
are gate 5's.

Cannot see: rows appended between a base and its head by a writer outside the
raw-source-mirror concurrency group (the hosted capture, publish, backfill and
maintenance jobs), the only writer exclusion; the lineage check only proves the base is
an ancestor reached by appends. A late completion widens that window to the time between
the run and the completion. Accepted risk (owner, 2026-11-08: "Keep auto-complete"): a
run whose checkout changed and that then died before checking it is completed under the
commit it started from.
"""
import base64
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from congress_api.lake.tables import table_input

PREFIX = 'lake/producers/'
OWED = PREFIX + 'owed/'
DAILY_JOB = 'packages/congress_api/src/congress_api/lake/daily.py'
CAPTURES_STAGE = 'packages/congress_api/src/congress_api/cli/captures_ingest.py'
BACKFILL = 'packages/viewer_publication/src/viewer_publication/archive_backfill_job.py'
IMPORT = 'packages/viewer_publication/src/viewer_publication/archive_import_job.py'
# The checked-in jobs that may produce each table; a record naming any other file refuses.
PRODUCERS = {
    'captures': {CAPTURES_STAGE, DAILY_JOB, BACKFILL, IMPORT},
    'readings': {'packages/congress_api/src/congress_api/cli/readings.py', DAILY_JOB, BACKFILL, IMPORT},
    'filename_readings': {DAILY_JOB, BACKFILL, IMPORT},
    'meeting_records': {DAILY_JOB, BACKFILL, IMPORT},
    'appearance_records': {DAILY_JOB, BACKFILL, IMPORT},
    'video_records': {DAILY_JOB, BACKFILL, IMPORT},
    'committee_records': {DAILY_JOB, BACKFILL, IMPORT},
    'playlist_records': {DAILY_JOB, BACKFILL, IMPORT},
    'transcript_headings': {DAILY_JOB, BACKFILL, IMPORT},
}
PIN_FIELDS = ('metadata_location', 'table_uuid', 'snapshot', 'schema_id')
RECORD_BYTES = 1 << 20
METADATA_BYTES = 64 << 20


def pin_of(selector):
    return {k: selector.get(k) for k in PIN_FIELDS}


def _uuid(pin):
    uuid = pin.get('table_uuid')
    if not isinstance(uuid, str) or re.fullmatch('[0-9a-f-]{8,64}', uuid) is None:
        raise ValueError('Producer record key requires a table UUID')
    return uuid


def key_for(pin):
    uuid, snapshot = _uuid(pin), pin.get('snapshot')
    if type(snapshot) is not int:
        raise ValueError('Producer record key requires a snapshot id')
    return f'{PREFIX}{uuid}/{snapshot}.json'


def owed_key(base):
    """Where a run leaves the record it owes for the table it appends onto `base`."""
    snapshot = base.get('snapshot')
    if snapshot is not None and type(snapshot) is not int:
        raise ValueError('Owed producer record key requires a snapshot id or an empty table')
    return f'{OWED}{_uuid(base)}/{"empty" if snapshot is None else snapshot}.json'


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

    def _read(self, key):
        """(bytes, version) or None; the version is the local bytes or the R2 ETag."""
        if self.root is not None:
            path = self.root / key
            if not path.is_file():
                return None
            if path.stat().st_size > RECORD_BYTES:
                raise ValueError('Producer record exceeds its size bound: ' + key)
            data = path.read_bytes()
            return data, data
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if _code(error) in {'404', 'NoSuchKey', 'NotFound'}:
                return None
            raise
        data = response['Body'].read(RECORD_BYTES + 1)
        if len(data) > RECORD_BYTES:
            raise ValueError('Producer record exceeds its size bound: ' + key)
        return data, response['ETag']

    def _get(self, key):
        found = self._read(key)
        return None if found is None else found[0]

    def at(self, name, table_uuid, snapshot):
        """(record, reference) naming this table's snapshot, by id alone, or None."""
        data = self.anchors.get(name)
        if data is not None:
            record = json.loads(data)
            selector = record.get('selector') or {}
            if (selector.get('table_uuid'), selector.get('snapshot')) == (table_uuid, snapshot):
                return record, dict(anchor=name, **identity(data))
        key = key_for(dict(table_uuid=table_uuid, snapshot=snapshot))
        data = self._get(key)
        return None if data is None else (json.loads(data), dict(key=key, **identity(data)))

    def owed(self, base):
        """(intent, key, version) a run left for the table at `base`, or None."""
        key = owed_key(base)
        found = self._read(key)
        return None if found is None else (json.loads(found[0]), key, found[1])

    def owe(self, intent, version):
        """Write an owed intent if `version` (None: absent) is still current, else refuse."""
        data = encode(intent)
        key = owed_key(intent['base']['selector'])
        changed = 'Owed producer record changed concurrently: ' + key
        if self.root is not None:
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            # The lock makes the comparison and the replace one step, as R2's conditional PUT is.
            with path.with_name(path.name + '.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current = path.read_bytes() if path.is_file() else None
                if current != version:
                    raise ValueError(changed)
                temporary = path.with_name(f'{path.name}.{uuid4().hex}.tmp')
                temporary.write_bytes(data)
                temporary.replace(path)
            return key
        condition = {'IfNoneMatch': '*'} if version is None else {'IfMatch': version}
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType='application/json',
                                   ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode(), **condition)
        except Exception as error:
            if _code(error) in {'PreconditionFailed', '412'}:
                raise ValueError(changed) from None
            raise
        return key

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
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, IfNoneMatch='*',
                                   ContentType='application/json',
                                   ContentMD5=base64.b64encode(hashlib.md5(data).digest()).decode())
        except Exception as error:
            if _code(error) not in {'PreconditionFailed', '412'}:
                # A lost response is not a failed write (run 44087092120 died here on a read
                # timeout after the table had moved). The record is create-once and its bytes are
                # known, so look before failing; the caller's append is not repeated either way.
                try:
                    stored = self._get(key)
                except Exception:
                    stored = None
                if stored != data:
                    raise
            elif self._get(key) != data:
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


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def is_delta(record):
    return record.get('delta_only') is True or record.get('final_reconciliation_required') is True


def import_origin_problem(name, source, origin):
    """Check that a pinned origin can account for the complete file being imported."""
    if not isinstance(origin, dict):
        return 'an import needs a producer record object'
    if origin.get('input') != name:
        return 'the import origin names another table'
    if is_delta(origin):
        return 'a staged delta cannot be the origin of a complete table'
    selector = origin.get('selector')
    if not isinstance(selector, dict) or selector.get('kind') not in ('parquet', 'native_table'):
        return 'the import origin must name a Parquet artifact or native snapshot'
    if selector['kind'] == 'native_table':
        try:
            table_input(name, {key: selector[key] for key in PIN_FIELDS})
        except (KeyError, ValueError):
            return 'the import origin needs an exact native table pin'
    elif (not isinstance(source, dict)
          or any(source.get(key) is None or source[key] != selector.get(key) for key in ('sha256', 'size'))):
        return 'the Parquet origin does not match the import source pin'
    return None


def record_problems(name, record, root, *, label, allow_delta=False, versions=None):
    """One record's refusals: not a staged delta, a known format, a job registered for the
    table, a full commit reachable from HEAD at `root` and the job checked in there; then,
    given `versions(record, label)`, the publisher's version rule."""
    if not allow_delta and is_delta(record):
        return [f'producer proof: {label}: a staged delta cannot produce a complete table']
    commit, job = record.get('commit'), record.get('job')
    if record.get('version') != 1:
        return [f'producer proof: {label}: unknown producer record version {record.get("version")!r}']
    if job not in PRODUCERS.get(name, ()):
        return [f'producer proof: {label}: job {job!r} is not a producer registered for this table']
    if not isinstance(commit, str) or re.fullmatch('[0-9a-f]{40}', commit) is None:
        return [f'producer proof: {label}: the producer record has no full commit']
    if git(root, 'merge-base', '--is-ancestor', commit, 'HEAD').returncode != 0:
        return [f'producer proof: {label}: producing commit {commit[:12]} is not reachable from HEAD']
    if git(root, 'cat-file', '-e', f'{commit}:{job}').returncode != 0:
        return [f'producer proof: {label}: job {job!r} is not a file checked in at {commit[:12]}']
    return versions(record, label) if versions else []


def import_problems(name, record, root, *, label, versions=None):
    """An import copies rows it did not produce: it names the record of the job that did
    (never another import), that origin accounts for the copied source, and passes
    record_problems."""
    origin = record.get('origin')
    if not isinstance(origin, dict) or not isinstance(origin.get('record'), dict):
        return [f'producer proof: {label}: an import record needs the origin record of the job that produced the rows']
    if origin['record'].get('job') == IMPORT:
        return [f'producer proof: {label}: an import cannot name another import as its origin']
    if problem := import_origin_problem(name, record.get('source'), origin['record']):
        return [f'producer proof: {label} origin: {problem}']
    return record_problems(name, origin['record'], root, label=f'{label} origin', versions=versions)


def link_problems(record, lineage, *, label):
    """A daily record's link: it names a base of its own table, reached from its snapshot by
    appends only (`lineage`, from appended_from)."""
    base = record.get('base')
    if not isinstance(base, dict) or not isinstance(base.get('selector'), dict):
        return [f'producer proof: {label}: a daily record must name the base snapshot it appended onto']
    if base['selector'].get('table_uuid') != record['selector'].get('table_uuid'):
        return [f'producer proof: {label}: the base snapshot belongs to another table']
    if not appended_from(lineage, record['selector']['snapshot'], base['selector'].get('snapshot')):
        return [f'producer proof: {label}: base snapshot {base["selector"].get("snapshot")} is not an ancestor reached by appends only']
    return []


def base_problems(name, base, records, root, *, label, lineage=None):
    """Refusals for appending onto `base`, {selector, record}: a snapshot and the pin of its record.

    Walks the records back to an empty table, a checked-in import, or a snapshot another
    registered producer wrote (a capture stage, a backfill), which names no base. Each record
    is the one pinned by hash, names this snapshot and table, and passes record_problems
    (import_problems for an import); a daily record's own link must hold (link_problems).
    Versions are not checked: the rows' versions are the row rule's, the head's gate 5's.

    One record read and two git calls per link, and one table metadata read (`lineage`,
    read from the first base when not given) once a daily record is walked: linear in the
    nightly records since the chain's root.
    """
    seen = set()
    while True:
        selector, pinned = base['selector'], base.get('record')
        if selector.get('snapshot') is None:
            return [] if pinned is None else [f'producer proof: {label}: an empty base has no record']
        if selector['snapshot'] in seen:
            return [f'producer proof: {label}: the base chain repeats a snapshot']
        seen.add(selector['snapshot'])
        found = records.find(name, selector)
        if (found is None or not isinstance(pinned, dict)
                or {k: found[1].get(k) for k in ('sha256', 'size')} != {k: pinned.get(k) for k in ('sha256', 'size')}):
            return [f'producer proof: {label}: the record of base snapshot {selector["snapshot"]} is missing or differs from its pin']
        prior, reference = found
        if pin_of(prior.get('selector') or {}) != pin_of(selector):
            return [f'producer proof: {label}: the base record names another snapshot']
        link = f'{label} base {selector["snapshot"]}'
        if prior.get('job') == IMPORT:
            if 'anchor' not in reference:
                return [f'producer proof: {link}: an import record in the chain must be checked in beside the publish spec']
            return record_problems(name, prior, root, label=link) or import_problems(name, prior, root, label=link)
        # Another registered producer's snapshot (run 44087092120: daily.py appended onto a
        # captures_ingest.py snapshot, the one the live release was published from) ends the chain.
        problems = record_problems(name, prior, root, label=link)
        if not problems and prior.get('input') != name:
            problems = [f'producer proof: {link}: the base record names another table']
        if problems or prior.get('job') != DAILY_JOB:
            return problems
        if lineage is None:
            lineage = records.lineage(selector['metadata_location'])
        if problems := link_problems(prior, lineage, label=label):
            return problems
        base = prior['base']
