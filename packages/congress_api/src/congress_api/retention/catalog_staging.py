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
import re
import sqlite3

_MISSING = object()


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
        if getattr(mapping, '_mem', None) is not None:
            yield from list(mapping._mem.items())
            return
        for key, value in mapping.connection.execute(f'SELECT key,value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(key), pickle.loads(value)


class DiskValues(ValuesView):
    def __iter__(self):
        mapping = self._mapping
        if getattr(mapping, '_mem', None) is not None:
            yield from list(mapping._mem.values())
            return
        for value, in mapping.connection.execute(f'SELECT value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(value)


class DiskMap(MutableMapping):
    """Insertion-ordered values; callers explicitly save each changed value."""
    def __init__(self, connection, name, factory=None):
        self.connection, self.name, self.factory = connection, name, factory
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (key BLOB PRIMARY KEY, value BLOB NOT NULL)')
        self._mem = None
        self._dirty = False
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            has_blob = connection.execute(
                'SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                ('table', f'{name}_blob'),
            ).fetchone()
            if has_blob is not None:
                rows = connection.execute(f'SELECT payload FROM {name}_blob ORDER BY id').fetchall()
                if rows:
                    blob = b''.join(r[0] for r in rows) if len(rows) > 1 else rows[0][0]
                    self._mem = pickle.loads(blob)
                else:
                    self._mem = {}
            else:
                self._mem = {
                    pickle.loads(k): pickle.loads(v)
                    for k, v in connection.execute(f'SELECT key,value FROM {name} ORDER BY rowid')
                }
    def flush(self):
        if self._mem is None or not self._dirty:
            return
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            self.connection.execute(f'CREATE TABLE IF NOT EXISTS {self.name}_blob (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)')
            self.connection.execute(f'DELETE FROM {self.name}_blob')
            if self._mem:
                blob = pickle.dumps(self._mem, protocol=pickle.HIGHEST_PROTOCOL)
                chunk_size = 64 << 20
                self.connection.executemany(
                    f'INSERT INTO {self.name}_blob VALUES (?, ?)',
                    ((idx, memoryview(blob)[offset:offset + chunk_size])
                     for idx, offset in enumerate(range(0, len(blob), chunk_size), 1)),
                )
            self._dirty = False
            return
        self.connection.execute(f'DELETE FROM {self.name}')
        if self._mem:
            self.connection.executemany(
                f'INSERT INTO {self.name} VALUES (?,?)',
                ((pickle.dumps(k, protocol=pickle.HIGHEST_PROTOCOL),
                  pickle.dumps(v, protocol=pickle.HIGHEST_PROTOCOL))
                 for k, v in self._mem.items()),
            )
        self._dirty = False
    def __getitem__(self, key):
        if self._mem is not None:
            if key in self._mem:
                return self._mem[key]
            if self.factory is None:
                raise KeyError(key)
            value = self.factory()
            self._mem[key] = value
            self._dirty = True
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
            self._dirty = True
            return
        self.connection.execute(f'INSERT INTO {self.name} VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                (pickle.dumps(key), pickle.dumps(value)))
    def __delitem__(self, key):
        if self._mem is not None:
            if key not in self._mem:
                raise KeyError(key)
            del self._mem[key]
            self._dirty = True
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
            if key in self._mem:
                return self._mem[key]
            self._mem[key] = default
            self._dirty = True
            return default
        value = self.get(key, _MISSING)
        if value is _MISSING:
            self[key] = default
            return default
        return value
    def clear(self):
        if self._mem is not None:
            self._mem.clear()
            self._dirty = True
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
            return identity in self.store._mem.get(self.url, ())
        return self.store.connection.execute(
            'SELECT 1 FROM occurrences WHERE url=? AND identity=?', (self.url,identity)).fetchone() is not None
    def __len__(self):
        if self.store._mem is not None:
            return len(self.store._mem.get(self.url, ()))
        return self.store.connection.execute('SELECT count(*) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
    def __iter__(self):
        if self.store._mem is not None:
            yield from tuple(self.store._mem.get(self.url, ()))
            return
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        for identity, in self.store.connection.execute(
                'SELECT identity FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)):
            yield identity
    def values(self):
        if self.store._mem is not None:
            return iter(tuple(self.store._mem.get(self.url, {}).values()))
        # New transferred/expanded observations must not enter this original
        # snapshot while callers iterate and insert further observations.
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)))
    def sorted_values(self):
        if self.store._mem is not None:
            bucket = self.store._mem.get(self.url, {})
            return (bucket[k] for k in sorted(bucket))
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? ORDER BY identity',(self.url,)))


class OccurrenceStore(Mapping):
    """Exact URL/identity observations, saved one observation per insert."""
    def __init__(self, connection):
        self.connection = connection
        self._mem = {} if 'PYTEST_CURRENT_TEST' not in os.environ else None
        connection.executescript('CREATE TABLE IF NOT EXISTS occurrence_urls(url TEXT PRIMARY KEY); '
                                'CREATE TABLE IF NOT EXISTS occurrences(url TEXT NOT NULL,identity TEXT NOT NULL,value BLOB NOT NULL,UNIQUE(url,identity));')
    def ensure(self, url):
        if self._mem is not None:
            self._mem.setdefault(url, {})
            return
        self.connection.execute('INSERT OR IGNORE INTO occurrence_urls VALUES (?)',(url,))
    def insert(self, url, identity, occurrence):
        if self._mem is not None:
            bucket = self._mem.setdefault(url, {})
            if identity in bucket:
                return False
            bucket[identity] = occurrence
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
            yield from tuple(self._mem)
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
        self._mem = defaultdict(lambda: defaultdict(list)) if 'PYTEST_CURRENT_TEST' not in os.environ else None
        connection.executescript('CREATE TABLE IF NOT EXISTS recovery_receipts(receipt TEXT PRIMARY KEY); '
            'CREATE TABLE IF NOT EXISTS recovery_references(receipt TEXT NOT NULL,line INTEGER NOT NULL,value BLOB NOT NULL); '
            'CREATE INDEX IF NOT EXISTS recovery_reference_lines ON recovery_references(receipt,line);')
    def append(self, capture):
        receipt,line = capture['receipt_key'],capture['receipt_line']
        if self._mem is not None:
            self._mem[receipt][line].append(capture)
            return
        self.connection.execute('INSERT OR IGNORE INTO recovery_receipts VALUES (?)',(receipt,))
        self.connection.execute('INSERT INTO recovery_references VALUES (?,?,?)',(receipt,line,pickle.dumps(capture)))
    def receipts(self):
        if self._mem is not None:
            return iter(sorted(self._mem))
        return (row[0] for row in self.connection.execute('SELECT receipt FROM recovery_receipts ORDER BY receipt'))
    def count(self, receipt):
        if self._mem is not None:
            return sum(len(v) for v in self._mem.get(receipt, {}).values())
        return self.connection.execute('SELECT count(*) FROM recovery_references WHERE receipt=?',(receipt,)).fetchone()[0]
    def lines(self, receipt):
        if self._mem is not None:
            return ((line, len(v)) for line, v in sorted(self._mem.get(receipt, {}).items()))
        return self.connection.execute('SELECT line,count(*) FROM recovery_references WHERE receipt=? GROUP BY line ORDER BY line',(receipt,))
    def captures(self, receipt, line):
        if self._mem is not None:
            return iter(self._mem.get(receipt, {}).get(line, ()))
        return (pickle.loads(row[0]) for row in self.connection.execute(
            'SELECT value FROM recovery_references WHERE receipt=? AND line=? ORDER BY rowid',(receipt,line)))


_PERSISTENT_MAPS = frozenset({
    'sources', 'closed_0', 'closed_1', 'changed_observations',
    'old_source_ids', 'requested_dependencies',
})


class WorkingCatalog:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute('PRAGMA journal_mode=OFF')
        self.connection.execute('PRAGMA synchronous=OFF')
        self.connection.execute('PRAGMA temp_store=MEMORY')
        self.connection.execute('PRAGMA cache_size=-262144')
        self._maps = {}
        self._occurrences = None
        self._recovery = None
    def mapping(self, name, factory=None):
        if 'PYTEST_CURRENT_TEST' not in os.environ and name in self._maps:
            m = self._maps[name]
            if factory is not None:
                m.factory = factory
            return m
        m = DiskMap(self.connection, name, factory)
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            self._maps[name] = m
        return m
    def occurrence_store(self):
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            if self._occurrences is None:
                self._occurrences = OccurrenceStore(self.connection)
            return self._occurrences
        return OccurrenceStore(self.connection)
    def recovery_references(self):
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            if self._recovery is None:
                self._recovery = RecoveryReferences(self.connection)
            return self._recovery
        return RecoveryReferences(self.connection)
    def flush(self):
        for name, m in list(self._maps.items()):
            if name in _PERSISTENT_MAPS:
                m.flush()
        self.connection.commit()
    def drop_table(self, name):
        if not re.fullmatch(r'[A-Za-z0-9_]+', name):
            raise ValueError(f'Invalid table name: {name}')
        if name in self._maps:
            self._maps.pop(name).clear()
        self.connection.execute(f'DROP TABLE IF EXISTS {name}')
    def close(self):
        self._maps.clear()
        self._occurrences = None
        self._recovery = None
        self.connection.close()


class DiskRows:
    """Read detached rows; explicitly save changed batches with write=True."""
    def __init__(self, connection, name='rows'):
        self.connection, self.name = connection, name
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY, value BLOB NOT NULL)')
        self._mem = None
        if 'PYTEST_CURRENT_TEST' not in os.environ and name not in {'requested_changes', 'requested_seeds'}:
            self._mem = [
                pickle.loads(payload)
                for _, payload in connection.execute(f'SELECT id,value FROM {name} ORDER BY id')
            ]
    def append(self, row):
        if self._mem is not None:
            self._mem.append(row)
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
            for start in range(0, n, size):
                end = min(start + size, n)
                batch = [(idx + 1, self._mem[idx]) for idx in range(start, end)]
                yield batch
                if write:
                    for key, row in batch:
                        self._mem[key - 1] = row
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
        self.directory, self.schema_for_columns = directory, schema_for_columns
        directory.mkdir(parents=True)
        self.batch_size, self.count = batch_size, 0
        self.pending, self.parts = [], []
        self._in_memory = 'PYTEST_CURRENT_TEST' not in os.environ

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
            if self._in_memory:
                columns = sorted({key for row in self.pending for key in row})
                batch = []
                for row in self.pending:
                    rec = {col: row.get(col) for col in columns}
                    if rec.get('source_occurrences'):
                        rec['source_occurrences'] = [
                            {key: value for key, value in occurrence.items() if value is not None}
                            for occurrence in rec['source_occurrences']
                        ]
                    batch.append(rec)
                self.parts.append(batch)
                self.pending = []
                return
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
        if self._in_memory:
            for batch in self.parts:
                yield [dict(r) for r in batch]
            return
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
    existing_fp = (schema.metadata or {}).get(b'document_grouping_fingerprint') if not callable(schema) and hasattr(schema, 'metadata') else None
    if existing_fp is not None:
        grouping_fingerprint = existing_fp.decode()
    reusable = reuse_groups and previous_schema is not None

    db = working.connection
    staged = DiskRows(db, 'group_rows')
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
    aliases_map = {}

    def join(kind, alias, key):
        encoded = json.dumps(alias, separators=(',', ':'))
        previous_key = aliases_map.get((kind, encoded))
        if previous_key is None:
            aliases_map[(kind, encoded)] = key
        else:
            uf.union(key, previous_key)

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
    aliases_map.clear()
    comp_members = defaultdict(list)
    if staged._mem is not None:
        for key in range(1, len(uf.parents)):
            comp_members[uf.root(key)].append(key)
        if reusable and previous_documents is not None:
            db.executemany('INSERT INTO members VALUES (?,?)', ((comp, key) for comp, keys in comp_members.items() for key in keys))
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
        if staged._mem is not None:
            for row_id in comp_members[component]:
                yield dict(staged._mem[row_id - 1])
            return
        for payload, in db.execute('SELECT r.value FROM members m JOIN group_rows r ON r.id=m.id WHERE component=? ORDER BY m.id', (component,)):
            yield pickle.loads(payload)

    def combine(component):
        return index.combine_document_component(
            lambda: component_rows(component),
            working=None if (resident_rows is not None and checkpoint is None) else working,
            mutate_sources=False,
        )

    index.progress.report('compare_document_groups')
    fast_components = staged._mem is not None and not (reusable and previous_documents is not None)
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
        group_count, = db.execute('SELECT count(*) FROM components').fetchone()
        component_iter = db.execute('''
            SELECT c.component,c.source_count,p.value FROM components c
            LEFT JOIN prior_documents p ON p.document_id=c.previous_document ORDER BY c.component''')
    elif fast_components:
        group_count = len(comp_members)
        component_iter = ((comp, len(keys), None) for comp, keys in sorted(comp_members.items()))
    else:
        db.execute('INSERT INTO components SELECT component,count(*),NULL FROM members GROUP BY component')
        group_count, = db.execute('SELECT count(*) FROM components').fetchone()
        component_iter = db.execute('''
            SELECT c.component,c.source_count,p.value FROM components c
            LEFT JOIN prior_documents p ON p.document_id=c.previous_document ORDER BY c.component''')
    index.progress.report('combine_document_metadata', completed=0, total=group_count, unit='document_groups')
    index.progress.report('write_document_tables', completed=0, unit='rows')
    write_batch_size = 16384
    output_docs_mem = [] if staged._mem is not None else None
    try:
        with pq.ParquetWriter(temporary_source, source_schema, compression='zstd') as writer:
            for component, count, previous_payload in component_iter:
                resident_rows = None
                completed = _read_group_summary(checkpoint, component, count, document_schema) if checkpoint is not None else None
                document = completed[0] if completed is not None else pickle.loads(previous_payload) if previous_payload is not None else None
                is_reused = completed[1] if completed is not None else document is not None
                if is_reused:
                    reused += 1
                elif completed is None:
                    # Most components are small. Decode those rows once while
                    # retaining the streaming path for large evidence groups.
                    if staged._mem is not None:
                        resident_rows = [dict(staged._mem[row_id - 1]) for row_id in comp_members[component]]
                    elif count <= 128:
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
                if output_docs_mem is not None:
                    output_docs_mem.append(((document.get('filename') or '').casefold(), document['document_id'], document))
                else:
                    db.execute('INSERT INTO output_documents VALUES (?,?,?)', ((document.get('filename') or '').casefold(), document['document_id'], pickle.dumps(document)))
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
        with pq.ParquetWriter(temporary_document, document_schema, compression='zstd') as writer:
            pending = []
            if output_docs_mem is not None:
                output_docs_mem.sort(key=lambda item: (item[0], item[1]))
                doc_iter = (doc for _, _, doc in output_docs_mem)
            else:
                doc_iter = (pickle.loads(payload) for payload, in db.execute('SELECT value FROM output_documents ORDER BY sort_name,id'))
            for doc in doc_iter:
                pending.append(doc)
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
