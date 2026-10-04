"""Disposable, indexed working state for derived catalogs.

SQLite files live only in a rebuild's temporary directory. Retained receipts and
published Parquet remain the authorities; staging never survives publication.
"""
from collections.abc import Mapping, MutableMapping
import json
import pickle
import sqlite3


class DiskMap(MutableMapping):
    """Insertion-ordered values; callers explicitly save each changed value."""
    def __init__(self, connection, name, factory=None):
        self.connection, self.name, self.factory = connection, name, factory
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (key BLOB PRIMARY KEY, value BLOB NOT NULL)')
    def __getitem__(self, key):
        encoded = pickle.dumps(key)
        result = self.connection.execute(f'SELECT value FROM {self.name} WHERE key=?', (encoded,)).fetchone()
        if result is None:
            if self.factory is None:
                raise KeyError(key)
            self[key] = self.factory()
            return self[key]
        return pickle.loads(result[0])
    def __setitem__(self, key, value):
        self.connection.execute(f'INSERT INTO {self.name} VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                (pickle.dumps(key), pickle.dumps(value)))
    def __delitem__(self, key):
        cursor = self.connection.execute(f'DELETE FROM {self.name} WHERE key=?', (pickle.dumps(key),))
        if not cursor.rowcount:
            raise KeyError(key)
    def __contains__(self, key):
        return self.connection.execute(f'SELECT 1 FROM {self.name} WHERE key=?', (pickle.dumps(key),)).fetchone() is not None
    def __iter__(self):
        for key, in self.connection.execute(f'SELECT key FROM {self.name} ORDER BY rowid'):
            yield pickle.loads(key)
    def __len__(self):
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def get(self, key, default=None):
        return self[key] if key in self else default
    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]
    def clear(self):
        self.connection.execute(f'DELETE FROM {self.name}')


class OccurrenceRows(Mapping):
    """Read one URL's observations without loading its complete dictionary."""
    def __init__(self, store, url):
        self.store, self.url = store, url
    def __getitem__(self, identity):
        row = self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? AND identity=?', (self.url,identity)).fetchone()
        if row is None:
            raise KeyError(identity)
        return pickle.loads(row[0])
    def __contains__(self, identity):
        return self.store.connection.execute(
            'SELECT 1 FROM occurrences WHERE url=? AND identity=?', (self.url,identity)).fetchone() is not None
    def __len__(self):
        return self.store.connection.execute('SELECT count(*) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
    def __iter__(self):
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        for identity, in self.store.connection.execute(
                'SELECT identity FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)):
            yield identity
    def values(self):
        # New transferred/expanded observations must not enter this original
        # snapshot while callers iterate and insert further observations.
        limit = self.store.connection.execute('SELECT max(rowid) FROM occurrences WHERE url=?',(self.url,)).fetchone()[0]
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? AND rowid<=? ORDER BY rowid',(self.url,limit)))
    def sorted_values(self):
        return (pickle.loads(row[0]) for row in self.store.connection.execute(
            'SELECT value FROM occurrences WHERE url=? ORDER BY identity',(self.url,)))


class OccurrenceStore(Mapping):
    """Exact URL/identity observations, saved one observation per insert."""
    def __init__(self, connection):
        self.connection = connection
        connection.executescript('CREATE TABLE IF NOT EXISTS occurrence_urls(url TEXT PRIMARY KEY); '
                                'CREATE TABLE IF NOT EXISTS occurrences(url TEXT NOT NULL,identity TEXT NOT NULL,value BLOB NOT NULL,UNIQUE(url,identity));')
    def ensure(self, url):
        self.connection.execute('INSERT OR IGNORE INTO occurrence_urls VALUES (?)',(url,))
    def insert(self, url, identity, occurrence):
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
        return self.connection.execute('SELECT 1 FROM occurrence_urls WHERE url=?',(url,)).fetchone() is not None
    def get(self, url, default=None):
        return OccurrenceRows(self,url) if url in self else default
    def __iter__(self):
        limit = self.connection.execute('SELECT max(rowid) FROM occurrence_urls').fetchone()[0]
        for url, in self.connection.execute('SELECT url FROM occurrence_urls WHERE rowid<=? ORDER BY rowid',(limit,)):
            yield url
    def __len__(self):
        return self.connection.execute('SELECT count(*) FROM occurrence_urls').fetchone()[0]


class RecoveryReferences:
    """Receipt capture pointers, indexed separately rather than copied per receipt."""
    def __init__(self, connection):
        self.connection = connection
        connection.executescript('CREATE TABLE IF NOT EXISTS recovery_receipts(receipt TEXT PRIMARY KEY); '
            'CREATE TABLE IF NOT EXISTS recovery_references(receipt TEXT NOT NULL,line INTEGER NOT NULL,value BLOB NOT NULL); '
            'CREATE INDEX IF NOT EXISTS recovery_reference_lines ON recovery_references(receipt,line);')
    def append(self, capture):
        receipt,line = capture['receipt_key'],capture['receipt_line']
        self.connection.execute('INSERT OR IGNORE INTO recovery_receipts VALUES (?)',(receipt,))
        self.connection.execute('INSERT INTO recovery_references VALUES (?,?,?)',(receipt,line,pickle.dumps(capture)))
    def receipts(self):
        return (row[0] for row in self.connection.execute('SELECT receipt FROM recovery_receipts ORDER BY receipt'))
    def count(self, receipt):
        return self.connection.execute('SELECT count(*) FROM recovery_references WHERE receipt=?',(receipt,)).fetchone()[0]
    def lines(self, receipt):
        return self.connection.execute('SELECT line,count(*) FROM recovery_references WHERE receipt=? GROUP BY line ORDER BY line',(receipt,))
    def captures(self, receipt, line):
        return (pickle.loads(row[0]) for row in self.connection.execute(
            'SELECT value FROM recovery_references WHERE receipt=? AND line=? ORDER BY rowid',(receipt,line)))


class WorkingCatalog:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute('PRAGMA journal_mode=OFF')
        self.connection.execute('PRAGMA synchronous=OFF')
        self.connection.execute('PRAGMA temp_store=FILE')
        self.connection.execute('PRAGMA cache_size=-8192')
    def mapping(self, name, factory=None):
        return DiskMap(self.connection, name, factory)
    def occurrence_store(self):
        return OccurrenceStore(self.connection)
    def recovery_references(self):
        return RecoveryReferences(self.connection)
    def close(self):
        self.connection.close()


class DiskRows:
    """Replayable row sequence; each mutation is saved before the next row."""
    def __init__(self, connection, name='rows'):
        self.connection, self.name = connection, name
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY, value BLOB NOT NULL)')
    def append(self, row):
        self.connection.execute(f'INSERT INTO {self.name}(value) VALUES (?)', (pickle.dumps(row),))
    def __len__(self):
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def items(self):
        for key, payload in self.connection.execute(f'SELECT id,value FROM {self.name} ORDER BY id'):
            row = pickle.loads(payload)
            yield key, row
            updated = pickle.dumps(row)
            if updated != payload:
                self.connection.execute(f'UPDATE {self.name} SET value=? WHERE id=?', (updated, key))
    def __iter__(self):
        for _, row in self.items():
            yield row
    def batches(self, size=4096):
        pending = []
        for key, row in self.items():
            pending.append((key, row))
            if len(pending) == size:
                yield pending
                self.save(pending)
                pending = []
        if pending:
            yield pending
            self.save(pending)
    def save(self, items):
        self.connection.executemany(f'UPDATE {self.name} SET value=? WHERE id=?',
                                   ((pickle.dumps(row), key) for key, row in items))


def write_grouped_indexes(destination, rows, schema, *, working, previous=None, previous_documents=None, reuse_groups=True):
    """Compute alias components on disk; combine only affected components.

    Every current endpoint/body edge participates, including transitive bridges.
    Comparing complete component inputs against the prior pair handles both
    merges and splits; an unavailable prior pair falls back to full combination.
    """
    from collections import defaultdict
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
    previous_schema = (previous.schema_arrow if hasattr(previous,'schema_arrow') else previous.schema) if previous is not None else None
    reusable = (reuse_groups and previous_schema is not None and
                (previous_schema.metadata or {}).get(b'document_grouping_fingerprint') == grouping_fingerprint.encode())

    db = working.connection
    staged = DiskRows(db, 'group_rows')
    db.executescript('''CREATE TABLE parents(id INTEGER PRIMARY KEY, parent INTEGER NOT NULL);
        CREATE TABLE aliases(kind TEXT NOT NULL,key TEXT NOT NULL,id INTEGER NOT NULL,PRIMARY KEY(kind,key));
        CREATE TABLE members(component INTEGER NOT NULL,id INTEGER PRIMARY KEY);
        CREATE INDEX component_members ON members(component,id);
        CREATE TABLE prior_sources(source_id TEXT PRIMARY KEY, document_id TEXT, signature TEXT, value BLOB);
        CREATE INDEX prior_group ON prior_sources(document_id);
        CREATE TABLE prior_documents(document_id TEXT PRIMARY KEY,value BLOB);
        CREATE TABLE output_documents(sort_name TEXT,id TEXT PRIMARY KEY,value BLOB);
        CREATE INDEX output_document_order ON output_documents(sort_name,id);''')

    def normalize(row):
        index.apply_capture_record_role(row)
        if any(value in index.DERIVED_KIND_SOURCES for value in row.get('document_kind_source') or []):
            row['document_kind'] = None
        row.pop('document_kind_source', None)
        row['source_id'] = sha256(index.compact([row.get(k) for k in ('body_key','filename','source_url')]).encode()).hexdigest()
        row['record_role'] = row.get('record_role') or ['document']
        row['format'] = (None if row['record_role'] == ['capture-state'] else
                         row.get('body_format') or index.file_formats(row.get('media_type'), row.get('extension')))
        return row

    def signature(row):
        return sha256(json.dumps({k: v for k, v in row.items() if v is not None and k != 'document_id'},
                                 sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    if reusable and (schema.metadata or {}).get(b'source_fingerprint') != (previous_schema.metadata or {}).get(b'source_fingerprint'):
        reusable = False
    if reusable and previous_documents is not None:
        previous_document_schema = (pq.read_schema(pa.BufferReader(previous_documents)) if isinstance(previous_documents,bytes) else previous_documents.schema_arrow)
        reusable = (previous_document_schema.metadata or {}).get(b'catalog_id') == (previous_schema.metadata or {}).get(b'catalog_id')
    if reusable and previous_documents is not None:
        batches = previous.iter_batches(batch_size=4096) if hasattr(previous, 'iter_batches') else previous.to_batches(max_chunksize=4096)
        for batch in batches:
            for row in batch.to_pylist():
                original = dict(row)
                normalize(row)
                db.execute('INSERT OR REPLACE INTO prior_sources VALUES (?,?,?,?)',
                           (row['source_id'], original.get('document_id'), signature(row), pickle.dumps(original)))
        documents = pq.ParquetFile(pa.BufferReader(previous_documents)) if isinstance(previous_documents, bytes) else previous_documents
        for batch in documents.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                db.execute('INSERT OR REPLACE INTO prior_documents VALUES (?,?)', (row['document_id'], pickle.dumps(row)))

    def root(key):
        visited = []
        while True:
            parent, = db.execute('SELECT parent FROM parents WHERE id=?', (key,)).fetchone()
            if parent == key:
                break
            visited.append(key)
            key = parent
        db.executemany('UPDATE parents SET parent=? WHERE id=?', ((key, item) for item in visited))
        return key

    def join(kind, alias, key):
        encoded = json.dumps(alias, separators=(',', ':'))
        previous_alias = db.execute('SELECT id FROM aliases WHERE kind=? AND key=?', (kind, encoded)).fetchone()
        if previous_alias is None:
            db.execute('INSERT INTO aliases VALUES (?,?,?)', (kind, encoded, key))
        else:
            db.execute('UPDATE parents SET parent=? WHERE id=?', (root(previous_alias[0]), root(key)))

    index.progress.report('group_documents', completed=0, unit='source_rows')
    for key, row in enumerate(rows, 1):
        normalize(row)
        staged.append(row)
        db.execute('INSERT INTO parents VALUES (?,?)', (key,key))
        endpoint = index.entry_key(row.get('filename'), row.get('source_url'), key)
        resolved = row.get('source_resolved_url')
        if endpoint == ('row', key) and row.get('source_url') and resolved and len(resolved) == 1:
            endpoint = index.entry_key(row.get('filename'), resolved[0], key)
        join('endpoint', endpoint, key)
        body = index.document_body(row.get('body_key'), row.get('media_type'), row.get('http_status'),
                                   row.get('capture_outcome'), row.get('body_format'), row)
        if body:
            join('body', body, key)
        if key % 4096 == 0:
            index.progress.report('group_documents', completed=key, unit='source_rows')
    for key, in db.execute('SELECT id FROM parents ORDER BY id'):
        db.execute('INSERT INTO members VALUES (?,?)', (root(key),key))

    # Determine the final schema once, then write bounded source batches. The
    # old assembler remains the semantic oracle for one connected component.
    if 'publication_code_code' in schema.names:
        redundant = all(not row.get('publication_code_code') or row['publication_code_code'] == row.get('publication_type') for row in staged)
        if redundant:
            schema = pa.schema([field for field in schema if field.name != 'publication_code_code'], metadata=schema.metadata)
            for row in staged:
                row.pop('publication_code_code', None)
    for field in ('document_kind','document_kind_source','document_family','record_role','source_record_type'):
        if field not in schema.names:
            schema = schema.append(pa.field(field,index.STRINGS))
    fields = [*[field for field in schema if field.name not in {'document_id','source_id','format'}],
              pa.field('source_id',pa.string()),pa.field('document_id',pa.string()),pa.field('format',index.STRINGS)]
    metadata = {**(schema.metadata or {}),b'catalog_id':uuid4().hex.encode(),b'format_version':b'10',
                b'document_grouping_fingerprint':grouping_fingerprint.encode()}
    source_schema = pa.schema(fields,metadata=metadata)
    document_schema = pa.schema([*fields,*[(field,index.STRINGS) for field in ('filenames','source_urls','body_keys')]],
                                metadata={**metadata,b'format_version':b'5'})
    reused = recomputed = document_count = 0
    pending = []
    temporary_source = destination.with_suffix('.parquet.tmp')
    document_path = destination.with_name('documents.parquet')
    temporary_document = document_path.with_suffix('.parquet.tmp')
    def component_rows(component):
        for payload, in db.execute('SELECT r.value FROM members m JOIN group_rows r ON r.id=m.id WHERE component=? ORDER BY m.id', (component,)):
            yield pickle.loads(payload)

    def combine(component):
        preferred = None
        values = defaultdict(set)
        filenames, urls, bodies, retained_bodies = set(), set(), set(), set()
        occurrences = working.mapping("combined_occurrences")
        occurrences.clear()
        filename_kind = False
        # Only the one resulting document's value sets remain resident. Source
        # dictionaries and occurrence inputs stream from the component index.
        for row in component_rows(component):
            priority = lambda item: (index.source_priority(item), item.get('filename') or '',
                                     item.get('source_url') or '', item['source_id'])
            if preferred is None or priority(row) > priority(preferred):
                preferred = row
            for field, value in row.items():
                if isinstance(value, list) and field != 'source_occurrences':
                    values[field].update(value)
            for occurrence in row.get('source_occurrences') or []:
                occurrences[index.compact(occurrence)] = occurrence
            for field, target in (('filename', filenames),('source_url', urls),('body_key', retained_bodies)):
                if row.get(field):
                    target.add(row[field])
            body = index.document_body(row.get('body_key'),row.get('media_type'),row.get('http_status'),
                                       row.get('capture_outcome'),row.get('body_format'),row)
            if body:
                bodies.add(body)
            filename_kind |= bool(row.get('document_kind') and not row.get('recovered_filename'))
        if bodies:
            document_id = sha256(index.compact(['bodies', sorted(bodies)]).encode()).hexdigest()
        else:
            # Preserve the exact old JSON digest without collecting all IDs.
            ids = working.mapping("component_source_ids")
            ids.clear()
            for row in component_rows(component):
                ids[row['source_id']] = True
            digest = sha256(b'["sources",[')
            first = True
            for key, in db.execute('SELECT key FROM component_source_ids ORDER BY key'):
                if not first:
                    digest.update(b',')
                first = False
                digest.update(index.compact(pickle.loads(key)).encode())
            digest.update(b']]')
            document_id = digest.hexdigest()
        document = {field:preferred.get(field) for field in ('source_id','body_key','filename','source_url')}
        document.update(document_id=document_id,
            filename=index.display_filename((preferred.get('recovered_filename') or [preferred.get('filename')])[0]))
        document.update({field:sorted(items) for field,items in values.items() if items})
        paired = index.merge_values('source_occurrences', list(occurrences.values()))
        if paired:
            document['source_occurrences'] = paired
        document['record_role'] = [next(role for role in ('document','source-record','error-response','capture-state') if role in values['record_role'])]
        index.fill_document_kind(document)
        if filename_kind:
            document['document_kind_source'] = ['filename']
        document.update(filenames=sorted(filenames) or None,source_urls=sorted(urls) or None,body_keys=sorted(retained_bodies) or None)
        return document

    index.progress.report('combine_document_metadata', completed=0, unit='document_groups')
    index.progress.report('write_document_tables', completed=0, unit='rows')
    try:
        with pq.ParquetWriter(temporary_source, source_schema, compression='zstd') as writer:
            for component, in db.execute('SELECT DISTINCT component FROM members ORDER BY component'):
                document = None
                old_document_id = None
                unchanged, count = True, 0
                for row in component_rows(component):
                    count += 1
                    old = db.execute('SELECT document_id,signature FROM prior_sources WHERE source_id=?',(row['source_id'],)).fetchone()
                    if old is None or old[1] != signature(row) or old_document_id is not None and old_document_id != old[0]:
                        unchanged = False
                        break
                    old_document_id = old[0]
                if unchanged and old_document_id is not None:
                    prior_count, = db.execute('SELECT count(*) FROM prior_sources WHERE document_id=?',(old_document_id,)).fetchone()
                    candidate = db.execute('SELECT value FROM prior_documents WHERE document_id=?',(old_document_id,)).fetchone()
                    if count == prior_count and candidate is not None:
                        document = pickle.loads(candidate[0])
                        reused += 1
                is_reused = document is not None
                if document is None:
                    document = combine(component)
                    recomputed += 1
                document_count += 1
                if document_count % 1000 == 0:
                    index.progress.report('combine_document_metadata', completed=document_count, unit='document_groups')
                db.execute('INSERT INTO output_documents VALUES (?,?,?)', ((document.get('filename') or '').casefold(), document['document_id'], pickle.dumps(document)))
                for row in component_rows(component):
                    if is_reused:
                        payload, = db.execute('SELECT value FROM prior_sources WHERE source_id=?',(row['source_id'],)).fetchone()
                        row = pickle.loads(payload)
                    else:
                        row['document_id'] = document['document_id']
                        index.fill_document_kind(row)
                    pending.append(row)
                    if len(pending) == 4096:
                        writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
                        pending = []
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
        with pq.ParquetWriter(temporary_document, document_schema, compression='zstd') as writer:
            pending = []
            for payload, in db.execute('SELECT value FROM output_documents ORDER BY sort_name,id'):
                pending.append(pickle.loads(payload))
                if len(pending) == 4096:
                    writer.write_table(pa.Table.from_pylist(pending,schema=document_schema))
                    pending = []
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=document_schema))
        index.progress.report('write_document_tables', completed=len(staged)+document_count, unit='rows')
        index.progress.report('validate_document_tables')
        index.validate_document_indexes(temporary_source,temporary_document,source_rows=len(staged),document_rows=document_count)
        temporary_source.replace(destination)
        temporary_document.replace(document_path)
    finally:
        temporary_source.unlink(missing_ok=True)
        temporary_document.unlink(missing_ok=True)
    return dict(document_rows=document_count,columns=len(source_schema),documents_output=str(document_path),
                documents_bytes=document_path.stat().st_size,reused_document_groups=reused,
                recomputed_document_groups=recomputed)
