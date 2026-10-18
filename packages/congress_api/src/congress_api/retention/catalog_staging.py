"""Disposable working state for derived catalogs.

Parquet streams filename rows; SQLite indexes shared facts and document groups.
Both live in temporary directories. Retained receipts and published Parquet
remain the authorities; staging never survives publication.
"""
from collections.abc import ItemsView, Mapping, MutableMapping, ValuesView
import json
import pickle
import sqlite3

_MISSING = object()


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
        for key, value in mapping.connection.execute(f'SELECT key,value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(key), pickle.loads(value)


class DiskValues(ValuesView):
    def __iter__(self):
        mapping = self._mapping
        for value, in mapping.connection.execute(f'SELECT value FROM {mapping.name} ORDER BY rowid'):
            yield pickle.loads(value)


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
            value = self.factory()
            self[key] = value
            return value
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
        result = self.connection.execute(f'SELECT value FROM {self.name} WHERE key=?', (pickle.dumps(key),)).fetchone()
        return pickle.loads(result[0]) if result is not None else default
    def setdefault(self, key, default=None):
        value = self.get(key, _MISSING)
        if value is _MISSING:
            self[key] = default
            return default
        return value
    def clear(self):
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
    """Read detached rows; explicitly save changed batches with write=True."""
    def __init__(self, connection, name='rows'):
        self.connection, self.name = connection, name
        connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY, value BLOB NOT NULL)')
    def append(self, row):
        self.connection.execute(f'INSERT INTO {self.name}(value) VALUES (?)', (pickle.dumps(row),))
    def __len__(self):
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]
    def items(self):
        for key, payload in self.connection.execute(f'SELECT id,value FROM {self.name} ORDER BY id'):
            yield key, pickle.loads(payload)
    def __iter__(self):
        for _, row in self.items():
            yield row
    def batches(self, size=4096, *, write=False):
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


def write_grouped_indexes(destination, rows, schema, *, working, previous=None, previous_documents=None, reuse_groups=True):
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
    previous_schema = (previous.schema_arrow if hasattr(previous,'schema_arrow') else previous.schema) if previous is not None else None
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

    def normalize(row):
        index.apply_capture_record_role(row)
        index.restore_filename_kind(row)
        row['source_id'] = sha256(index.compact([row.get(k) for k in ('body_key','filename','source_url')]).encode()).hexdigest()
        row['record_role'] = row.get('record_role') or ['document']
        row['format'] = (None if row['record_role'] == ['capture-state'] else
                         row.get('body_format') or index.file_formats(row.get('media_type'), row.get('extension')))
        return row

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
                db.execute('INSERT OR REPLACE INTO prior_sources VALUES (?,?,?,?)',
                           (row['source_id'], original.get('document_id'), signature(row), pickle.dumps(original)))
        documents = previous_documents
        for batch in documents.iter_batches(batch_size=256):
            for row in batch.to_pylist():
                db.execute('INSERT OR REPLACE INTO prior_documents VALUES (?,?)', (row['document_id'], pickle.dumps(sparse_row(row))))

    # Only integer parent pointers are resident: eight bytes per source row.
    # Payloads and aliases remain on disk. Preserve the existing union order.
    parents = array('Q', [0])

    def root(key):
        visited = []
        while True:
            parent = parents[key]
            if parent == key:
                break
            visited.append(key)
            key = parent
        for item in visited:
            parents[item] = key
        return key

    def join(kind, alias, key):
        encoded = json.dumps(alias, separators=(',', ':'))
        previous_alias = db.execute('SELECT id FROM aliases WHERE kind=? AND key=?', (kind, encoded)).fetchone()
        if previous_alias is None:
            db.execute('INSERT INTO aliases VALUES (?,?,?)', (kind, encoded, key))
        else:
            parents[root(key)] = root(previous_alias[0])

    index.progress.report('group_documents', completed=0, unit='source_rows')
    for key, row in enumerate(rows, 1):
        normalize(row)
        staged.append(sparse_row(row))
        parents.append(key)
        if reusable and previous_documents is not None:
            db.execute('INSERT INTO current_sources VALUES (?,?,?)', (key,row['source_id'],signature(row)))
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
    db.executemany('INSERT INTO members VALUES (?,?)', ((root(key),key) for key in range(1,len(parents))))
    del parents

    # Streaming interpretation discovers its columns while rows are consumed.
    schema = schema() if callable(schema) else schema

    # Determine the final schema once, then write bounded source batches. The
    # old assembler remains the semantic oracle for one connected component.
    if 'publication_code_code' in schema.names:
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
        if resident_rows is not None:
            yield from resident_rows
            return
        for payload, in db.execute('SELECT r.value FROM members m JOIN group_rows r ON r.id=m.id WHERE component=? ORDER BY m.id', (component,)):
            yield pickle.loads(payload)

    def combine(component):
        preferred = None
        values = defaultdict(set)
        filenames, urls, bodies, retained_bodies = set(), set(), set(), set()
        occurrences = working.mapping("combined_occurrences")
        occurrences.clear()
        hearing_resources = []
        filename_kind = False
        # Only the one resulting document's value sets remain resident. Source
        # dictionaries and occurrence inputs stream from the component index.
        for row in component_rows(component):
            priority = lambda item: (index.source_priority(item), item.get('filename') or '',
                                     item.get('source_url') or '', item['source_id'])
            if preferred is None or priority(row) > priority(preferred):
                preferred = row
            for field, value in row.items():
                if isinstance(value, list) and field not in {'source_occurrences', 'hearing_resources'}:
                    values[field].update(value)
            hearing_resources = index.merge_values('hearing_resources', hearing_resources, row.get('hearing_resources'))
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
        if hearing_resources:
            document['hearing_resources'] = hearing_resources
        document['record_role'] = [next(role for role in ('document','source-record','error-response','capture-state') if role in values['record_role'])]
        index.fill_document_kind(document)
        if filename_kind and 'recovered_filename' in (document.get('document_kind_source') or []):
            document['document_kind_source'] = sorted({
                'filename' if basis == 'recovered_filename' else basis for basis in document['document_kind_source']})
        document.update(filenames=sorted(filenames) or None,source_urls=sorted(urls) or None,body_keys=sorted(retained_bodies) or None)
        return document

    index.progress.report('compare_document_groups')
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
    try:
        with pq.ParquetWriter(temporary_source, source_schema, compression='zstd') as writer:
            for component, count, previous_payload in db.execute('''
                    SELECT c.component,c.source_count,p.value FROM components c
                    LEFT JOIN prior_documents p ON p.document_id=c.previous_document ORDER BY c.component'''):
                resident_rows = None
                document = pickle.loads(previous_payload) if previous_payload is not None else None
                is_reused = document is not None
                if is_reused:
                    reused += 1
                else:
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
                    if len(pending) == 1024:
                        writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
                        pending = []
                if is_reused:
                    document['filename_document_kind'] = sorted(filename_claims) or None
                db.execute('INSERT INTO output_documents VALUES (?,?,?)', ((document.get('filename') or '').casefold(), document['document_id'], pickle.dumps(document)))
            if pending:
                writer.write_table(pa.Table.from_pylist(pending,schema=source_schema))
        with pq.ParquetWriter(temporary_document, document_schema, compression='zstd') as writer:
            pending = []
            for payload, in db.execute('SELECT value FROM output_documents ORDER BY sort_name,id'):
                pending.append(pickle.loads(payload))
                if len(pending) == 1024:
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
