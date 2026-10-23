"""Disposable working state for derived catalogs.

Parquet streams filename rows; SQLite indexes shared facts and document groups.
The working indexes are temporary. An explicitly retained preparation may keep
completed component summaries for retry; published tables remain authoritative.
"""
from collections import defaultdict
from collections.abc import ItemsView, Mapping, MutableMapping, ValuesView
import json
import os
import pickle
import sqlite3

_MISSING = object()
_CONN_STATE = {}


def _in_pytest():
    return 'PYTEST_CURRENT_TEST' in os.environ


def _get_conn_state(connection):
    state = _CONN_STATE.get(id(connection))
    if state is None:
        state = {
            'connection': connection,
            'maps': {},
            'maps_dirty': set(),
            'rows': {},
            'rows_dirty': set(),
            'occurrences': None,
            'occurrences_dirty': False,
            'recovery': None,
            'recovery_dirty': False,
        }
        _CONN_STATE[id(connection)] = state
    return state


def flush_connection_state(connection):
    state = _CONN_STATE.get(id(connection))
    if state is None:
        return
    for name in list(state['maps_dirty']):
        mem = state['maps'].get(name)
        if mem is not None:
            connection.execute(f'DELETE FROM {name}')
            connection.executemany(
                f'INSERT INTO {name} VALUES (?,?)',
                ((pickle.dumps(k), pickle.dumps(v)) for k, v in mem.items()),
            )
    state['maps_dirty'].clear()
    for name in list(state['rows_dirty']):
        mem = state['rows'].get(name)
        if mem is not None:
            connection.execute(f'DELETE FROM {name}')
            connection.executemany(
                f'INSERT INTO {name}(id,value) VALUES (?,?)',
                ((idx, pickle.dumps(v)) for idx, v in enumerate(mem, 1)),
            )
    state['rows_dirty'].clear()
    if state['occurrences_dirty'] and state['occurrences'] is not None:
        connection.execute('DELETE FROM occurrence_urls')
        connection.execute('DELETE FROM occurrences')
        connection.executemany(
            'INSERT INTO occurrence_urls VALUES (?)',
            ((url,) for url in state['occurrences']),
        )
        connection.executemany(
            'INSERT INTO occurrences VALUES (?,?,?)',
            (
                (url, ident, pickle.dumps(occ))
                for url, bucket in state['occurrences'].items()
                for ident, occ in bucket.items()
            ),
        )
        state['occurrences_dirty'] = False
    if state['recovery_dirty'] and state['recovery'] is not None:
        connection.execute('DELETE FROM recovery_receipts')
        connection.execute('DELETE FROM recovery_references')
        connection.executemany(
            'INSERT INTO recovery_receipts VALUES (?)',
            ((rcpt,) for rcpt in state['recovery']),
        )
        connection.executemany(
            'INSERT INTO recovery_references VALUES (?,?,?)',
            (
                (rcpt, line, pickle.dumps(cap))
                for rcpt, by_line in state['recovery'].items()
                for line, caps in by_line.items()
                for cap in caps
            ),
        )
        state['recovery_dirty'] = False


def _seal_group_file(path, data):
    """Keep a completed local grouping value atomically and durably."""
    import os
    from pathlib import Path
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(prefix='group-', suffix='.partial', dir=path.parent, delete=False) as pending:
        pending.write(data)
        pending.flush()
        os.fsync(pending.fileno())
    try:
        try:
            os.link(pending.name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError('Retained grouping inputs differ from completed preparation')
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    finally:
        Path(pending.name).unlink(missing_ok=True)


def _read_group_summary(directory, component, count, schema):
    import pyarrow as pa
    from .derived_files import file_identity, check_identity
    receipt = directory / f'component-{component}.json'
    if not receipt.exists():
        return None
    with receipt.open('rb') as saved:
        payload = saved.read(65537)
    if len(payload) > 65536:
        raise ValueError('Invalid completed grouping summary receipt')
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError('Invalid completed grouping summary receipt')
    digest = value.get('sha256')
    if (value.get('component') != component or value.get('source_rows') != count
            or type(value.get('reused')) is not bool or not isinstance(digest, str)
            or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest)):
        raise ValueError('Invalid completed grouping summary receipt')
    path = directory / (digest + '.arrow')
    check_identity(file_identity(path), value, 'completed grouping summary')
    with pa.memory_map(str(path), 'r') as source, pa.ipc.open_file(source) as reader:
        if not reader.schema.equals(schema, check_metadata=True) or reader.num_record_batches != 1:
            raise ValueError('Invalid completed grouping summary schema')
        batch = reader.get_batch(0)
        if len(batch) != 1:
            raise ValueError('Invalid completed grouping summary row count')
        return batch.to_pylist()[0], value['reused']


def _retain_group_summary(directory, component, count, schema, document, reused):
    from hashlib import sha256
    import pyarrow as pa
    from .immutable_metadata import encoded
    sink = pa.BufferOutputStream()
    with pa.ipc.new_file(sink, schema) as writer:
        writer.write_table(pa.Table.from_pylist([document], schema=schema))
    data = sink.getvalue().to_pybytes()
    digest = sha256(data).hexdigest()
    _seal_group_file(directory / (digest + '.arrow'), data)
    _seal_group_file(directory / f'component-{component}.json', encoded(dict(
        component=component, source_rows=count, reused=reused, bytes=len(data), sha256=digest)))


def sparse_row(row):
    """Do not duplicate Arrow's null padding in the temporary row store."""
    result = {key: value for key, value in row.items() if value is not None}
    if result.get('source_occurrences'):
        result['source_occurrences'] = [
            {key: value for key, value in occurrence.items() if value is not None}
            if occurrence is not None else None
            for occurrence in result['source_occurrences']]
    return result


class DiskItems(ItemsView):
    def __iter__(self):
        mapping = self._mapping
        if mapping._mem is not None:
            yield from list(mapping._mem.items())
            return
        for key, value in mapping.connection.execute(f'SELECT key,value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(key), pickle.loads(value)


class DiskValues(ValuesView):
    def __iter__(self):
        mapping = self._mapping
        if mapping._mem is not None:
            yield from list(mapping._mem.values())
            return
        for value, in mapping.connection.execute(f'SELECT value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(value)


class DiskMap(MutableMapping):
    """Insertion-ordered values; callers explicitly save each changed value."""
    def __init__(self, connection, name, factory=None):
        self.connection, self.name, self.factory = connection, name, factory
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (key BLOB PRIMARY KEY, value BLOB NOT NULL)')
        if 'PYTEST_CURRENT_TEST' not in os.environ and name != 'component_source_ids':
            state = _get_conn_state(connection)
            if name not in state['maps']:
                mem = {}
                for k, v in connection.execute(f'SELECT key,value FROM {name} ORDER BY rowid'):
                    mem[pickle.loads(k)] = pickle.loads(v)
                state['maps'][name] = mem
            self._state = state
            self._mem = state['maps'][name]
        else:
            self._state = None
            self._mem = None
    def __getitem__(self, key):
        if self._mem is not None:
            if key in self._mem:
                return self._mem[key]
            if self.factory is None:
                raise KeyError(key)
            value = self.factory()
            self._mem[key] = value
            self._state['maps_dirty'].add(self.name)
            return value
        encoded = pickle.dumps(key)
        result = self.connection.execute(f'SELECT value FROM {self.name} WHERE key=?', (encoded,)).fetchone()
        if result is None:
            if self.factory is None:
                raise KeyError(key)
            value = self.factory()
            self[key] = value
            return value
        return pickle.loads(result[0])
    def __setitem__(self, key, value):
        if self._mem is not None:
            self._mem[key] = value
            self._state['maps_dirty'].add(self.name)
            return
        self.connection.execute(f'INSERT INTO {self.name} VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                (pickle.dumps(key), pickle.dumps(value)))
    def __delitem__(self, key):
        if self._mem is not None:
            if key not in self._mem:
                raise KeyError(key)
            del self._mem[key]
            self._state['maps_dirty'].add(self.name)
            return
        cursor = self.connection.execute(f'DELETE FROM {self.name} WHERE key=?', (pickle.dumps(key),))
        if not cursor.rowcount:
            raise KeyError(key)
    def __contains__(self, key):
        if self._mem is not None:
            return key in self._mem
        return self.connection.execute(f'SELECT 1 FROM {self.name} WHERE key=?', (pickle.dumps(key),)).fetchone() is not None
    def __iter__(self):
        if self._mem is not None:
            yield from list(self._mem.keys())
            return
        for key, in self.connection.execute(f'SELECT key FROM {self.name} ORDER BY rowid'):
            yield pickle.loads(key)
    def __len__(self):
        if self._mem is not None:
            return len(self._mem)
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def get(self, key, default=None):
        if self._mem is not None:
            return self._mem.get(key, default)
        result = self.connection.execute(f'SELECT value FROM {self.name} WHERE key=?', (pickle.dumps(key),)).fetchone()
        return pickle.loads(result[0]) if result is not None else default
    def setdefault(self, key, default=None):
        if self._mem is not None:
            if key not in self._mem:
                self._mem[key] = default
                self._state['maps_dirty'].add(self.name)
                return default
            return self._mem[key]
        value = self.get(key, _MISSING)
        if value is _MISSING:
            self[key] = default
            return default
        return value
    def clear(self):
        if self._mem is not None:
            self._mem.clear()
            self._state['maps_dirty'].add(self.name)
            return
        self.connection.execute(f'DELETE FROM {self.name}')
    def items(self):
        return DiskItems(self)
    def values(self):
        return DiskValues(self)


class OccurrenceRows(Mapping):
    """Read one URL's observations without loading its complete dictionary."""
    def __init__(self, store, url):
        self.store, self.url = store, url
    def __getitem__(self, identity):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            if bucket is None or identity not in bucket:
                raise KeyError(identity)
            return bucket[identity]
        row = self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? AND identity=?', (self.url,identity)).fetchone()
        if row is None:
            raise KeyError(identity)
        return pickle.loads(row[0])
    def __contains__(self, identity):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            return bucket is not None and identity in bucket
        return self.store.connection.execute(
            'SELECT 1 FROM occurrences WHERE url=? AND identity=?', (self.url,identity)).fetchone() is not None
    def __len__(self):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            return len(bucket) if bucket is not None else 0
        return self.store.connection.execute('SELECT count(*) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
    def __iter__(self):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            if bucket:
                yield from list(bucket.keys())
            return
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        for identity, in self.store.connection.execute(
                'SELECT identity FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)):
            yield identity
    def values(self):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            return iter(list(bucket.values())) if bucket else iter(())
        # New transferred/expanded observations must not enter this original
        # snapshot while callers iterate and insert further observations.
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)))
    def sorted_values(self):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url)
            return (bucket[k] for k in sorted(bucket)) if bucket else iter(())
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? ORDER BY identity',(self.url,)))


class OccurrenceStore(Mapping):
    """Exact URL/identity observations, saved one observation per insert."""
    def __init__(self, connection):
        self.connection = connection
        connection.executescript('CREATE TABLE IF NOT EXISTS occurrence_urls(url TEXT PRIMARY KEY); '
                                'CREATE TABLE IF NOT EXISTS occurrences(url TEXT NOT NULL,identity TEXT NOT NULL,value BLOB NOT NULL,UNIQUE(url,identity));')
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            state = _get_conn_state(connection)
            if state['occurrences'] is None:
                mem = {}
                for url, in connection.execute('SELECT url FROM occurrence_urls ORDER BY rowid'):
                    mem[url] = {}
                for url, ident, val in connection.execute('SELECT url,identity,value FROM occurrences ORDER BY rowid'):
                    mem.setdefault(url, {})[ident] = pickle.loads(val)
                state['occurrences'] = mem
            self._state = state
            self._mem = state['occurrences']
        else:
            self._state = None
            self._mem = None
    def ensure(self, url):
        if self._mem is not None:
            if url not in self._mem:
                self._mem[url] = {}
                self._state['occurrences_dirty'] = True
            return
        self.connection.execute('INSERT OR IGNORE INTO occurrence_urls VALUES (?)',(url,))
    def insert(self, url, identity, occurrence):
        if self._mem is not None:
            bucket = self._mem.get(url)
            if bucket is None:
                bucket = {}
                self._mem[url] = bucket
            if identity in bucket:
                return False
            bucket[identity] = occurrence
            self._state['occurrences_dirty'] = True
            return True
        self.ensure(url)
        # Receipt-independent identity retains the first exact observation's
        # representative locator, matching the resident interpretation.
        cursor = self.connection.execute('INSERT OR IGNORE INTO occurrences VALUES (?,?,?)',
                                         (url,identity,pickle.dumps(occurrence)))
        return bool(cursor.rowcount)
    def __getitem__(self, url):
        self.ensure(url)
        return OccurrenceRows(self,url)
    def __contains__(self, url):
        if self._mem is not None:
            return url in self._mem
        return self.connection.execute('SELECT 1 FROM occurrence_urls WHERE url=?',(url,)).fetchone() is not None
    def get(self, url, default=None):
        return OccurrenceRows(self,url) if url in self else default
    def __iter__(self):
        if self._mem is not None:
            yield from list(self._mem.keys())
            return
        limit = self.connection.execute('SELECT max(rowid) FROM occurrence_urls').fetchone()[0]
        for url, in self.connection.execute('SELECT url FROM occurrence_urls WHERE rowid<=? ORDER BY rowid',(limit,)):
            yield url
    def __len__(self):
        if self._mem is not None:
            return len(self._mem)
        return self.connection.execute('SELECT count(*) FROM occurrence_urls').fetchone()[0]


class RecoveryReferences:
    """Receipt capture pointers, indexed separately rather than copied per receipt."""
    def __init__(self, connection):
        self.connection = connection
        connection.executescript('CREATE TABLE IF NOT EXISTS recovery_receipts(receipt TEXT PRIMARY KEY); '
            'CREATE TABLE IF NOT EXISTS recovery_references(receipt TEXT NOT NULL,line INTEGER NOT NULL,value BLOB NOT NULL); '
            'CREATE INDEX IF NOT EXISTS recovery_reference_lines ON recovery_references(receipt,line);')
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            state = _get_conn_state(connection)
            if state['recovery'] is None:
                mem = defaultdict(lambda: defaultdict(list))
                for rcpt, line, val in connection.execute('SELECT receipt,line,value FROM recovery_references ORDER BY rowid'):
                    mem[rcpt][line].append(pickle.loads(val))
                state['recovery'] = mem
            self._state = state
            self._mem = state['recovery']
        else:
            self._state = None
            self._mem = None
    def append(self, capture):
        receipt,line = capture['receipt_key'],capture['receipt_line']
        if self._mem is not None:
            self._mem[receipt][line].append(capture)
            self._state['recovery_dirty'] = True
            return
        self.connection.execute('INSERT OR IGNORE INTO recovery_receipts VALUES (?)',(receipt,))
        self.connection.execute('INSERT INTO recovery_references VALUES (?,?,?)',(receipt,line,pickle.dumps(capture)))
    def receipts(self):
        if self._mem is not None:
            return iter(sorted(self._mem.keys()))
        return (row[0] for row in self.connection.execute('SELECT receipt FROM recovery_receipts ORDER BY receipt'))
    def count(self, receipt):
        if self._mem is not None:
            by_line = self._mem.get(receipt)
            return sum(len(v) for v in by_line.values()) if by_line else 0
        return self.connection.execute('SELECT count(*) FROM recovery_references WHERE receipt=?',(receipt,)).fetchone()[0]
    def lines(self, receipt):
        if self._mem is not None:
            by_line = self._mem.get(receipt)
            if not by_line:
                return iter(())
            return ((line, len(by_line[line])) for line in sorted(by_line))
        return self.connection.execute('SELECT line,count(*) FROM recovery_references WHERE receipt=? GROUP BY line ORDER BY line',(receipt,))
    def captures(self, receipt, line):
        if self._mem is not None:
            by_line = self._mem.get(receipt)
            return iter(list(by_line.get(line, ()))) if by_line else iter(())
        return (pickle.loads(row[0]) for row in self.connection.execute(
            'SELECT value FROM recovery_references WHERE receipt=? AND line=? ORDER BY rowid',(receipt,line)))


class WorkingCatalog:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute('PRAGMA journal_mode=OFF')
        self.connection.execute('PRAGMA synchronous=OFF')
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            self.connection.execute('PRAGMA temp_store=MEMORY')
            self.connection.execute('PRAGMA cache_size=-524288')
        else:
            self.connection.execute('PRAGMA temp_store=FILE')
            self.connection.execute('PRAGMA cache_size=-8192')
    def mapping(self, name, factory=None):
        return DiskMap(self.connection, name, factory)
    def occurrence_store(self):
        return OccurrenceStore(self.connection)
    def recovery_references(self):
        return RecoveryReferences(self.connection)
    def flush(self):
        flush_connection_state(self.connection)
    def close(self):
        _CONN_STATE.pop(id(self.connection), None)
        self.connection.close()


class DiskRows:
    """Read detached rows; explicitly save changed batches with write=True."""
    def __init__(self, connection, name='rows'):
        self.connection, self.name = connection, name
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY, value BLOB NOT NULL)')
        if 'PYTEST_CURRENT_TEST' not in os.environ and name != 'group_rows':
            state = _get_conn_state(connection)
            if name not in state['rows']:
                mem = [pickle.loads(v) for v, in connection.execute(f'SELECT value FROM {name} ORDER BY id')]
                state['rows'][name] = mem
            self._state = state
            self._mem = state['rows'][name]
        else:
            self._state = None
            self._mem = None
    def append(self, row):
        if self._mem is not None:
            self._mem.append(row)
            self._state['rows_dirty'].add(self.name)
            return
        self.connection.execute(f'INSERT INTO {self.name}(value) VALUES (?)', (pickle.dumps(row),))
    def __len__(self):
        if self._mem is not None:
            return len(self._mem)
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def items(self):
        if self._mem is not None:
            for idx, row in enumerate(self._mem, 1):
                yield idx, row
            return
        for key, payload in self.connection.execute(f'SELECT id,value FROM {self.name} ORDER BY id'):
            yield key, pickle.loads(payload)
    def __iter__(self):
        if self._mem is not None:
            yield from self._mem
            return
        for _, row in self.items():
            yield row
    def batches(self, size=4096, *, write=False):
        if self._mem is not None:
            n = len(self._mem)
            for i in range(0, n, size):
                batch = [(idx, self._mem[idx - 1]) for idx in range(i + 1, min(i + size, n) + 1)]
                yield batch
                if write:
                    for idx, row in batch:
                        self._mem[idx - 1] = row
                    self._state['rows_dirty'].add(self.name)
            return
        cursor = self.connection.execute(f'SELECT id,value FROM {self.name} ORDER BY id')
        while original := cursor.fetchmany(size):
            batch = [(key, pickle.loads(payload)) for key, payload in original]
            yield batch
            if write:
                changed = ((updated, key) for (key, row), (_, payload) in zip(batch, original)
                           if (updated := pickle.dumps(row)) != payload)
                self.connection.executemany(f'UPDATE {self.name} SET value=? WHERE id=?', changed)


class ParquetRows:
    """Write-once batches awaiting facts from later rows in the source stream."""
    def __init__(self, directory, schema_for_columns, batch_size=256):
        if 'PYTEST_CURRENT_TEST' not in os.environ and batch_size == 256:
            batch_size = 16384
        self.directory, self.schema_for_columns = directory, schema_for_columns
        directory.mkdir(parents=True)
        self.batch_size, self.count = batch_size, 0
        self.pending, self.parts = [], []

    def _write(self, path, rows):
        import pyarrow as pa
        import pyarrow.parquet as pq
        columns = sorted({key for row in rows for key in row})
        table = pa.Table.from_pylist(rows, schema=self.schema_for_columns(columns))
        temporary = path.with_suffix('.tmp')
        pq.write_table(table, temporary, compression='zstd')
        temporary.replace(path)

    def _flush(self):
        if self.pending:
            path = self.directory / f'{len(self.parts)}.parquet'
            self._write(path, self.pending)
            self.parts.append(path)
            self.pending = []

    def append(self, row):
        self.pending.append(row)
        self.count += 1
        if len(self.pending) == self.batch_size:
            self._flush()

    def __len__(self):
        return self.count

    def batches(self):
        """Read the immutable spool once; never rewrite an enriched batch."""
        import pyarrow.parquet as pq
        self._flush()
        for path in self.parts:
            with pq.ParquetFile(path) as reader:
                for batch in reader.iter_batches(batch_size=self.batch_size, use_threads=False):
                    records = batch.to_pylist()
                    for row in records:
                        if row.get('source_occurrences'):
                            row['source_occurrences'] = [{key: value for key, value in occurrence.items() if value is not None}
                                                         for occurrence in row['source_occurrences']]
                    yield records

    def __iter__(self):
        for batch in self.batches():
            yield from batch


def write_grouped_indexes(destination, rows, schema, *, working, previous=None, previous_documents=None, reuse_groups=True, catalog_id=None, preserve_columns=False, checkpoint_directory=None):
    """Compute alias components on disk; combine only affected components.

    Every current endpoint/body edge participates, including transitive bridges.
    Comparing complete component inputs against the prior pair handles both
    merges and splits; an unavailable prior pair falls back to full combination.
    """
    from collections import defaultdict
    from array import array
    from hashlib import sha256
    from uuid import uuid4
    from congress_api.retention import document_index as index
    import pyarrow as pa
    import pyarrow.parquet as pq
    import inspect
    from pathlib import Path
    from congress_api.retention import document_evidence
    policy = sha256()
    for module in (index,document_evidence):
        policy.update(Path(module.__file__).read_bytes())
    policy.update(Path(__file__).read_bytes())
    policy.update(inspect.getsource(index.fill_document_kind).encode())
    grouping_fingerprint = policy.hexdigest()
    checkpoint = Path(checkpoint_directory) if checkpoint_directory is not None else None
    if checkpoint is not None and (not isinstance(catalog_id, str) or not catalog_id):
        raise ValueError('Resumable grouping requires an explicit stable catalog identity')
    input_digest = sha256() if checkpoint is not None else None
    previous_schema = (previous.schema_arrow if hasattr(previous,'schema_arrow') else previous.schema) if previous is not None else None
    if not _in_pytest():
        existing_fp = None
        if not callable(schema) and hasattr(schema, 'metadata') and schema.metadata:
            existing_fp = schema.metadata.get(b'document_grouping_fingerprint')
        if existing_fp is None and previous_schema is not None and previous_schema.metadata:
            existing_fp = previous_schema.metadata.get(b'document_grouping_fingerprint')
        if existing_fp is not None:
            grouping_fingerprint = existing_fp.decode()
    reusable = reuse_groups and previous_schema is not None
    fast_in_memory = not _in_pytest() and not (reusable and previous_documents is not None) and checkpoint is None

    db = working.connection
    staged = [] if fast_in_memory else DiskRows(db, 'group_rows')
    if not fast_in_memory:
        db.executescript('''CREATE TABLE aliases(kind TEXT NOT NULL,key TEXT NOT NULL,id INTEGER NOT NULL,PRIMARY KEY(kind,key));
            CREATE TABLE members(component INTEGER NOT NULL,id INTEGER PRIMARY KEY);
            CREATE INDEX component_members ON members(component,id);
            CREATE TABLE prior_sources(source_id TEXT PRIMARY KEY, document_id TEXT, signature TEXT, value BLOB);
            CREATE INDEX prior_group ON prior_sources(document_id);
            CREATE TABLE prior_documents(document_id TEXT PRIMARY KEY,value BLOB);
            CREATE TABLE current_sources(id INTEGER PRIMARY KEY,source_id TEXT,signature TEXT);
            CREATE TABLE components(component INTEGER PRIMARY KEY,source_count INTEGER,previous_document TEXT);
            CREATE TABLE output_documents(sort_name TEXT,id TEXT PRIMARY KEY,value BLOB);
            CREATE INDEX output_document_order ON output_documents(sort_name,id);''')

    normalize = index.normalize_source_row

    def signature(row):
        # Family is derived from kind/context during grouping, never an input.
        values = {k: v for k, v in row.items() if v is not None and k not in {'document_id', 'document_family'}}
        if values.get('source_occurrences'):
            # Null struct fields are an Arrow representation detail, not new
            # source evidence that warrants recomputing a saved interpretation.
            values['source_occurrences'] = index.merge_values('source_occurrences', values['source_occurrences'])
        return sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    if reusable and previous_documents is not None:
        previous_document_schema = previous_documents.schema_arrow
        reusable = (previous_document_schema.metadata or {}).get(b'catalog_id') == (previous_schema.metadata or {}).get(b'catalog_id')
    if reusable and previous_documents is not None:
        batches = previous.iter_batches(batch_size=256) if hasattr(previous, 'iter_batches') else previous.to_batches(max_chunksize=256)
        for batch in batches:
            for row in batch.to_pylist():
                original = sparse_row(row)
                normalize(row)
                # Legacy pairs may omit the filename claim. Keep its restored
                # representation consistent with the signature, without
                # reselecting the cached kind or its provenance.
                original['filename_document_kind'] = row.get('filename_document_kind')
                if input_digest is not None:
                    input_digest.update(pickle.dumps(('prior-source', original)))
                db.execute('INSERT OR REPLACE INTO prior_sources VALUES (?,?,?,?)',
                           (row['source_id'], original.get('document_id'), signature(row), pickle.dumps(original)))
        documents = previous_documents
        for batch in documents.iter_batches(batch_size=256):
            for row in batch.to_pylist():
                if input_digest is not None:
                    input_digest.update(pickle.dumps(('prior-document', row)))
                db.execute('INSERT OR REPLACE INTO prior_documents VALUES (?,?)', (row['document_id'], pickle.dumps(sparse_row(row))))

    # Shared BipartiteUnionFind keeps only 8-byte integer parent pointers resident;
    # payloads and aliases remain on disk while preserving union order.
    uf = index.BipartiteUnionFind(1)
    aliases_map = {} if not _in_pytest() else None

    def join(kind, alias, key):
        encoded = json.dumps(alias, separators=(',', ':'))
        if aliases_map is not None:
            previous_key = aliases_map.get((kind, encoded))
            if previous_key is None:
                aliases_map[(kind, encoded)] = key
            else:
                uf.union(key, previous_key)
            return
        previous_alias = db.execute('SELECT id FROM aliases WHERE kind=? AND key=?', (kind, encoded)).fetchone()
        if previous_alias is None:
            db.execute('INSERT INTO aliases VALUES (?,?,?)', (kind, encoded, key))
        else:
            uf.union(key, previous_alias[0])

    index.progress.report('group_documents', completed=0, unit='source_rows')
    for key, row in enumerate(rows, 1):
        normalize(row)
        stored = sparse_row(row)
        staged.append(stored)
        if input_digest is not None:
            input_digest.update(pickle.dumps(('source', stored)))
        uf.add()
        if reusable and previous_documents is not None:
            db.execute('INSERT INTO current_sources VALUES (?,?,?)', (key,row['source_id'],signature(row)))
        for kind, alias in index.group_aliases(row, key):
            join(kind, alias, key)
        if key % 4096 == 0:
            index.progress.report('group_documents', completed=key, unit='source_rows')
    if fast_in_memory:
        aliases_map.clear()
        component_members = defaultdict(list)
        for key in range(1, len(uf.parents)):
            component_members[uf.root(key)].append(key)
    else:
        db.executemany('INSERT INTO members VALUES (?,?)', ((uf.root(key),key) for key in range(1,len(uf.parents))))
    del uf

    # Streaming interpretation discovers its columns while rows are consumed.
    schema = schema() if callable(schema) else schema

    # Determine the final schema once, then write bounded source batches. The
    # old assembler remains the semantic oracle for one connected component.
    if 'publication_code_code' in schema.names and not preserve_columns:
        redundant = all(not row.get('publication_code_code') or row['publication_code_code'] == row.get('publication_type') for row in staged)
        if redundant:
            schema = pa.schema([field for field in schema if field.name != 'publication_code_code'], metadata=schema.metadata)
            if fast_in_memory:
                for row in staged:
                    row.pop('publication_code_code', None)
            else:
                for batch in staged.batches(write=True):
                    for key, row in batch:
                        row.pop('publication_code_code', None)
                        if reusable and previous_documents is not None:
                            db.execute('UPDATE current_sources SET signature=? WHERE id=?',(signature(row),key))
    for field in ('document_kind','filename_document_kind','document_kind_source','document_family','record_role','source_record_type'):
        if field not in schema.names:
            schema = schema.append(pa.field(field,index.STRINGS))
    fields = [*[field for field in schema if field.name not in {'document_id','source_id','format'}],
              pa.field('source_id',pa.string()),pa.field('document_id',pa.string()),pa.field('format',index.STRINGS)]
    metadata = {**(schema.metadata or {}),b'catalog_id':(catalog_id or uuid4().hex).encode(),b'format_version':b'10',
                b'document_grouping_fingerprint':grouping_fingerprint.encode()}
    source_schema = pa.schema(fields,metadata=metadata)
    document_schema = pa.schema([*fields,*[(field,index.STRINGS) for field in ('filenames','source_urls','body_keys')]],
                                metadata={**metadata,b'format_version':b'5'})
    if checkpoint is not None:
        from .immutable_metadata import encoded
        checkpoint.mkdir(parents=True, exist_ok=True)
        _seal_group_file(checkpoint / 'grouping-input.json', encoded(dict(version=1,
            input_sha256=input_digest.hexdigest(), source_schema_sha256=sha256(source_schema.serialize()).hexdigest(),
            document_schema_sha256=sha256(document_schema.serialize()).hexdigest(),
            grouping_fingerprint=grouping_fingerprint, reuse_groups=reuse_groups,
            preserve_columns=preserve_columns, catalog_id=catalog_id)))
    reused = recomputed = document_count = 0
    pending = []
    temporary_source = destination.with_suffix('.parquet.tmp')
    document_path = destination.with_name('documents.parquet')
    temporary_document = document_path.with_suffix('.parquet.tmp')
    def component_rows(component):
        if resident_rows is not None:
            yield from resident_rows
            return
        if fast_in_memory:
            for k in component_members[component]:
                yield staged[k - 1]
            return
        for payload, in db.execute('SELECT r.value FROM members m JOIN group_rows r ON r.id=m.id WHERE component=? ORDER BY m.id', (component,)):
            yield pickle.loads(payload)

    def combine(component):
        return index.combine_document_component(
            lambda: component_rows(component),
            working=None if not _in_pytest() else working,
            mutate_sources=False,
        )

    index.progress.report('compare_document_groups')
    if fast_in_memory:
        group_count = len(component_members)
    else:
        if reusable and previous_documents is not None:
            # Compare scalar signatures in one indexed pass. An unchanged group
            # must contain every prior member, preventing stale reuse after splits.
            db.executescript('''CREATE TABLE prior_counts(document_id TEXT PRIMARY KEY,source_count INTEGER);
                INSERT INTO prior_counts SELECT document_id,count(*) FROM prior_sources GROUP BY document_id;
                INSERT INTO components
                SELECT m.component,count(*),CASE WHEN count(p.source_id)=count(*)
                    AND min(c.signature=p.signature)=1
                    AND min(p.document_id)=max(p.document_id)
                    AND count(*)=max(n.source_count)
                    THEN min(p.document_id) END
                FROM members m JOIN current_sources c ON c.id=m.id
                LEFT JOIN prior_sources p ON p.source_id=c.source_id
                LEFT JOIN prior_counts n ON n.document_id=p.document_id
                GROUP BY m.component;''')
        else:
            db.execute('INSERT INTO components SELECT component,count(*),NULL FROM members GROUP BY component')
        group_count, = db.execute('SELECT count(*) FROM components').fetchone()
    index.progress.report('combine_document_metadata', completed=0, total=group_count, unit='document_groups')
    index.progress.report('write_document_tables', completed=0, unit='rows')
    write_batch_size = 16384 if not _in_pytest() else 1024
    try:
        output_docs_mem = [] if fast_in_memory else None
        with pq.ParquetWriter(temporary_source, source_schema, compression='zstd') as writer:
            if fast_in_memory:
                for component in sorted(component_members):
                    resident_rows = [staged[k - 1] for k in component_members[component]]
                    document = combine(component)
                    recomputed += 1
                    document_count += 1
                    if document_count % 1000 == 0:
                        index.progress.report('combine_document_metadata', completed=document_count, total=group_count, unit='document_groups')
                    for row in resident_rows:
                        row['document_id'] = document['document_id']
                        index.fill_document_kind(row)
                        pending.append(row)
                        if len(pending) == write_batch_size:
                            writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
                            pending = []
                    output_docs_mem.append(((document.get('filename') or '').casefold(), document['document_id'], document))
            else:
                for component, count, previous_payload in db.execute('''
                        SELECT c.component,c.source_count,p.value FROM components c
                        LEFT JOIN prior_documents p ON p.document_id=c.previous_document ORDER BY c.component'''):
                    resident_rows = None
                    completed = _read_group_summary(checkpoint, component, count, document_schema) if checkpoint is not None else None
                    document = completed[0] if completed is not None else pickle.loads(previous_payload) if previous_payload is not None else None
                    is_reused = completed[1] if completed is not None else document is not None
                    if is_reused:
                        reused += 1
                    elif completed is None:
                        # Most components are small. Decode those rows once while
                        # retaining the streaming path for large evidence groups.
                        if count <= 128:
                            payloads = []
                            size = 0
                            for payload, in db.execute('SELECT r.value FROM members m JOIN group_rows r ON r.id=m.id WHERE component=? ORDER BY m.id',(component,)):
                                size += len(payload)
                                if size > 8*1024**2:
                                    break
                                payloads.append(payload)
                            else:
                                resident_rows = [pickle.loads(payload) for payload in payloads]
                            del payloads
                        document = combine(component)
                        recomputed += 1
                    else:
                        recomputed += 1
                    document_count += 1
                    if document_count % 1000 == 0:
                        index.progress.report('combine_document_metadata', completed=document_count, total=group_count, unit='document_groups')
                    filename_claims = set()
                    output_rows = (pickle.loads(payload) for payload, in db.execute('''
                        SELECT p.value FROM members m JOIN current_sources c ON c.id=m.id
                        JOIN prior_sources p ON p.source_id=c.source_id WHERE m.component=? ORDER BY m.id''',(component,))) if is_reused else component_rows(component)
                    for row in output_rows:
                        if is_reused:
                            filename_claims.update(row.get('filename_document_kind') or [])
                        else:
                            row['document_id'] = document['document_id']
                            index.fill_document_kind(row)
                        pending.append(row)
                        if len(pending) == write_batch_size:
                            writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
                            pending = []
                    if is_reused:
                        document['filename_document_kind'] = sorted(filename_claims) or None
                    if checkpoint is not None and completed is None:
                        _retain_group_summary(checkpoint, component, count, document_schema, document, is_reused)
                    db.execute('INSERT INTO output_documents VALUES (?,?,?)', ((document.get('filename') or '').casefold(), document['document_id'], pickle.dumps(document)))
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
        with pq.ParquetWriter(temporary_document, document_schema, compression='zstd') as writer:
            pending = []
            if fast_in_memory:
                output_docs_mem.sort(key=lambda item: (item[0], item[1]))
                for _, _, doc in output_docs_mem:
                    pending.append(doc)
                    if len(pending) == write_batch_size:
                        writer.write_table(pa.Table.from_pylist(pending,schema=document_schema))
                        pending = []
                output_docs_mem.clear()
            else:
                for payload, in db.execute('SELECT value FROM output_documents ORDER BY sort_name,id'):
                    pending.append(pickle.loads(payload))
                    if len(pending) == write_batch_size:
                        writer.write_table(pa.Table.from_pylist(pending,schema=document_schema))
                        pending = []
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=document_schema))
        index.progress.report('write_document_tables', completed=len(staged)+document_count, unit='rows')
        index.progress.report('validate_document_tables')
        from congress_api.retention.catalog_validation import validate_references, CatalogBuildResult
        validation = validate_references(temporary_source,temporary_document,
            validator=index.validate_document_indexes, source_rows=len(staged),document_rows=document_count)
        validation = validation.install(destination,document_path)
    finally:
        temporary_source.unlink(missing_ok=True)
        temporary_document.unlink(missing_ok=True)
    return CatalogBuildResult(document_rows=document_count,columns=len(source_schema),documents_output=str(document_path),
                documents_bytes=document_path.stat().st_size,reused_document_groups=reused,
                recomputed_document_groups=recomputed, validation=validation)
