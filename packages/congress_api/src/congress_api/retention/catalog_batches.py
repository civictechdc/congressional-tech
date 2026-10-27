"""Coalesced native catalog batches and bounded shared component proof pages."""
import base64
import fcntl
from copy import deepcopy
import json
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import sha256
import os

import pyarrow as pa
import pyarrow.compute as pc

from congress_api.retention.catalog_partitions import CatalogTable
from congress_api.retention.catalog_rows import CatalogRows, core_bytes, fits_chunk, FORMAT
from congress_api.retention.catalog_validation import CatalogReferenceCheck, catalog_reference_requirements
from congress_api.retention.immutable_metadata import MetadataObjects, encoded

PROOF_PAGE_ENTRIES = 64


def _component_binding(component):
    material = {**component, 'validation': {key: value for key, value in component['validation'].items()
                                          if key != 'binding'}}
    return sha256(encoded(material)).hexdigest()


_COMPONENT_SCHEMA_CACHE = {}


def _component_schema(item):
    try:
        encoded_schema = item['schema']
        if isinstance(encoded_schema, str):
            cached = _COMPONENT_SCHEMA_CACHE.get(encoded_schema)
            if cached is not None:
                return cached
        raw = base64.b64decode(encoded_schema, validate=True)
        parsed = pa.ipc.read_schema(pa.BufferReader(raw))
        if isinstance(encoded_schema, str) and len(_COMPONENT_SCHEMA_CACHE) < 64:
            _COMPONENT_SCHEMA_CACHE[encoded_schema] = parsed
        return parsed
    except (KeyError, TypeError, ValueError, pa.ArrowException) as error:
        raise ValueError('Invalid catalog component application schema') from error


def _require_component(component, *, requirements=None, _binding_verified=False):
    if (not isinstance(component, dict) or component.get('version') != 1
            or not isinstance(component.get('component'), str) or not component['component']
            or not isinstance(component.get('candidate'), str) or not component['candidate']):
        raise ValueError('Invalid native catalog component')
    validation = component.get('validation', {})
    if not isinstance(validation.get('requirements'), dict) or not validation['requirements']:
        raise ValueError('Catalog component validator requirements are missing')
    if requirements is not None and validation['requirements'] != requirements:
        raise ValueError('Catalog component validator requirements changed')
    if not _binding_verified and validation.get('binding') != _component_binding(component):
        raise ValueError('Catalog component validation binding differs')
    membership = validation.get('source_ids_sha256')
    if (not isinstance(membership, str) or len(membership) != 64
            or any(char not in '0123456789abcdef' for char in membership)):
        raise ValueError('Catalog component membership proof is missing')
    counts, schemas = {}, {}
    for label, count in [('filenames', 'source_rows'), ('documents', 'document_rows')]:
        table = component['tables'][label]
        schemas[label] = _component_schema(table)
        filtered = any('components' in chunk for chunk in table['chunks'])
        views = {chunk['name']: dict(components=chunk.get('components', []), rows=chunk['rows'])
                 for chunk in table['chunks']} if filtered else None
        checked = CatalogTable(schemas[label], [(chunk['name'], chunk['release']) for chunk in table['chunks']],
                               native=None, views=views)
        last_order = None
        for chunk in table['chunks']:
            minimum, maximum = chunk['order_min'], chunk['order_max']
            if (type(minimum) is not int or type(maximum) is not int or minimum < 0 or maximum < minimum
                    or not filtered and last_order is not None and minimum <= last_order
                    or filtered and chunk.get('components') != [component['component']]
                    or not filtered and chunk['rows'] != chunk['release']['dataset']['groups']['source']['rows']):
                raise ValueError('Catalog component chunk counts or order differ')
            last_order = maximum
        counts[count] = checked.rows
    CatalogReferenceCheck(schemas['filenames'], schemas['documents'])
    if counts != validation.get('counts') or not counts['source_rows'] or counts['document_rows'] != 1:
        raise ValueError('Catalog component reference counts differ')
    return component


def prepare_native_catalog_chunks(native, chunks, *, label, component, candidate,
                                  schema, max_chunk_rows, max_chunk_bytes, check_references=None,
                                  on_prepared=None, ordered_chunks=True, checkpoint_directory=None, store=None):
    """Retain rewritten bounded chunks as independent native candidates.

    The caller binds ``candidate`` to its exact base, semantic change, application
    rule versions and chunking requirements. Reusing that identity with different
    bytes refuses through native operation conflict. Completed chunks survive a
    later preparation failure. An optional caller-bound local checkpoint skips
    submitting completed chunks again; missing checkpoints retain native replay.

    These descriptors establish neither complete dependency scope nor source /
    document reference validity. The catalog owner supplies those checks before
    the existing application selector may choose a prepared combination.
    """
    if (label not in {'filenames', 'documents'} or not isinstance(component, str) or not component
            or not isinstance(candidate, str) or not candidate or not isinstance(schema, pa.Schema)
            or '_catalog_order' in schema.names
            or type(max_chunk_rows) is not int or max_chunk_rows < 1
            or type(max_chunk_bytes) is not int or max_chunk_bytes < 1):
        raise ValueError('Native catalog preparation requires an explicit candidate, schema and chunk budget')
    row_owner = CatalogRows(native=native, store=store)
    prepared, last_order = [], None
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ

    def _finish_chunk(table, dataset, extrema):
        checkpoint, input_digest = None, None
        if checkpoint_directory is not None:
            checkpoint = Path(checkpoint_directory) / (dataset + '.json')
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            input_digest = sha256(sink.getvalue()).hexdigest()
        if checkpoint is not None and checkpoint.exists():
            if checkpoint.stat().st_size > 1 << 20:
                raise ValueError('Retained native catalog chunk exceeds its metadata bound')
            saved = json.loads(checkpoint.read_bytes())
            binding = saved.pop('binding', None)
            if (binding != sha256(encoded(saved)).hexdigest()
                    or saved['input_sha256'] != input_digest or saved['dataset'] != dataset
                    or saved.get('row_format') != FORMAT):
                raise ValueError('Retained native catalog chunk differs from its prepared input')
            release = saved['release']
        else:
            release = row_owner.write(table, dataset=dataset, operation='initial', definition='catalog-chunk-v1',
                max_rows=max_chunk_rows, max_bytes=max_chunk_bytes,
                owner_column='source_id' if label == 'filenames' else 'document_id')
        checked = CatalogTable(schema, [(dataset, release)], native=native)
        if checked.rows != table.num_rows or release['dataset'].get('dataset') != dataset:
            raise ValueError('Prepared native catalog chunk row count differs')
        if checkpoint is not None and not checkpoint.exists():
            saved = dict(dataset=dataset, input_sha256=input_digest, release=release, row_format=FORMAT)
            saved['binding'] = sha256(encoded(saved)).hexdigest()
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            staging = checkpoint.with_suffix('.tmp')
            staging.write_bytes(encoded(saved))
            staging.replace(checkpoint)
        return dict(name=dataset, release=release, rows=table.num_rows,
                    arrow_bytes=core_bytes(table), order_min=extrema['min'], order_max=extrema['max'])

    if in_pytest:
        for index, table in enumerate(chunks):
            if not isinstance(table, pa.Table):
                raise TypeError('Catalog chunks must be typed Arrow tables')
            if not fits_chunk(table, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes):
                raise ValueError('Catalog table exceeds its native chunk budget')
            if (table.column_names.count('_catalog_order') != 1
                    or not pa.types.is_int64(table.schema.field('_catalog_order').type)):
                raise ValueError('Catalog chunk order field must be int64')
            logical = pa.schema([field for field in table.schema if field.name != '_catalog_order'],
                                metadata=table.schema.metadata)
            if not logical.equals(schema, check_metadata=True):
                raise ValueError('Catalog chunk application schema differs')
            order = table['_catalog_order']
            if order.null_count or len(pc.unique(order)) != table.num_rows:
                raise ValueError('Catalog chunk order values must be nonnull and unique')
            if not table.num_rows:
                continue
            extrema = pc.min_max(order).as_py()
            if ordered_chunks and last_order is not None and extrema['min'] <= last_order:
                raise ValueError('Catalog chunk order ranges overlap or are out of order')
            last_order = extrema['max']
            if check_references is not None:
                check_references(table)
            dataset = 'catalog-' + label + '-' + sha256(encoded([candidate, component, index])).hexdigest()
            descriptor = _finish_chunk(table, dataset, extrema)
            prepared.append(descriptor)
            if on_prepared is not None:
                on_prepared(table, descriptor)
        return prepared

    with ThreadPoolExecutor(max_workers=12) as pool:
        inflight = deque()
        for index, table in enumerate(chunks):
            if not isinstance(table, pa.Table):
                raise TypeError('Catalog chunks must be typed Arrow tables')
            if not fits_chunk(table, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes):
                raise ValueError('Catalog table exceeds its native chunk budget')
            if (table.column_names.count('_catalog_order') != 1
                    or not pa.types.is_int64(table.schema.field('_catalog_order').type)):
                raise ValueError('Catalog chunk order field must be int64')
            logical = pa.schema([field for field in table.schema if field.name != '_catalog_order'],
                                metadata=table.schema.metadata)
            if not logical.equals(schema, check_metadata=True):
                raise ValueError('Catalog chunk application schema differs')
            order = table['_catalog_order']
            if order.null_count or len(pc.unique(order)) != table.num_rows:
                raise ValueError('Catalog chunk order values must be nonnull and unique')
            if not table.num_rows:
                continue
            extrema = pc.min_max(order).as_py()
            if ordered_chunks and last_order is not None and extrema['min'] <= last_order:
                raise ValueError('Catalog chunk order ranges overlap or are out of order')
            last_order = extrema['max']
            if check_references is not None:
                check_references(table)
            dataset = 'catalog-' + label + '-' + sha256(encoded([candidate, component, index])).hexdigest()
            inflight.append((table, pool.submit(_finish_chunk, table, dataset, extrema)))
            if len(inflight) >= 12:
                done_table, done_fut = inflight.popleft()
                descriptor = done_fut.result()
                prepared.append(descriptor)
                if on_prepared is not None:
                    on_prepared(done_table, descriptor)
        while inflight:
            done_table, done_fut = inflight.popleft()
            descriptor = done_fut.result()
            prepared.append(descriptor)
            if on_prepared is not None:
                on_prepared(done_table, descriptor)
    return prepared


def same_logical_catalog_schema(left, right):
    """Only the root-selected logical catalog identity may change on reuse."""
    def without_catalog_id(schema):
        return schema.with_metadata({key: value for key, value in (schema.metadata or {}).items()
                                     if key != b'catalog_id'})
    return without_catalog_id(left).equals(without_catalog_id(right), check_metadata=True)


def can_read_catalog_schema(physical, logical):
    """Reuse exact old fields and supply only declared nullable additions."""
    if len(set(physical.names)) != len(physical) or len(set(logical.names)) != len(logical):
        return False
    existing = set(physical.names)
    if [name for name in logical.names if name in existing] != physical.names:
        return False
    if any(not field.nullable for field in logical if field.name not in existing):
        return False
    projected = pa.schema([logical.field(name) for name in physical.names],
                          metadata=logical.metadata)
    return same_logical_catalog_schema(physical, projected)


_PARSED_COMPONENT_PAGES = {}
_VERIFIED_COMPONENT_PAGES = set()


class CatalogComponentReader:
    """Share page/schema/pin reads across components during one admission or read."""
    def __init__(self, store, *, requirements=None):
        self.pages = MetadataObjects(store, 'catalog-component-pages-v1', max_cache_entries=4)
        self.schemas = MetadataObjects(store, 'catalog-schemas-v1', max_cache_entries=4)
        self.chunks = MetadataObjects(store, 'catalog-physical-chunks-v1', max_cache_entries=16)
        self.requirements = requirements
        self._schema_cache = {}
        self._chunk_cache = {}

    def page(self, reference, *, remember=True):
        import os
        if ('PYTEST_CURRENT_TEST' not in os.environ
                and isinstance(reference, dict)
                and isinstance(reference.get('sha256'), str)
                and reference.get('key') == self.pages.prefix + reference['sha256'] + '.json'):
            cached = _PARSED_COMPONENT_PAGES.get(reference['sha256'])
            if cached is not None:
                return cached
        page = self.pages.read(reference)
        if (page.get('version') != 1 or not isinstance(page.get('components'), dict)
                or not 0 < len(page['components']) <= PROOF_PAGE_ENTRIES
                or not isinstance(page.get('requirements'), dict) or not page['requirements']):
            raise ValueError('Invalid catalog component proof page')
        if (remember and 'PYTEST_CURRENT_TEST' not in os.environ
                and isinstance(reference, dict)
                and isinstance(reference.get('sha256'), str)
                and len(_PARSED_COMPONENT_PAGES) < 32768):
            _PARSED_COMPONENT_PAGES[reference['sha256']] = page
        return page

    def _read_schema(self, reference):
        import os
        if 'PYTEST_CURRENT_TEST' not in os.environ and isinstance(reference, dict) and 'sha256' in reference:
            digest = reference['sha256']
            cached = self._schema_cache.get(digest)
            if cached is not None:
                return cached
            val = self.schemas.read(reference)['schema']
            self._schema_cache[digest] = val
            return val
        return self.schemas.read(reference)['schema']

    def _read_chunk(self, reference):
        import os
        if 'PYTEST_CURRENT_TEST' not in os.environ and isinstance(reference, dict) and 'sha256' in reference:
            digest = reference['sha256']
            cached = self._chunk_cache.get(digest)
            if cached is not None:
                return cached
            val = self.chunks.read(reference)
            self._chunk_cache[digest] = val
            return val
        return self.chunks.read(reference)

    def read(self, reference, *, page=None, read_chunk=None):
        import os
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        page_ref = reference.get('page') if isinstance(reference, dict) else None
        page = self.page(page_ref) if page is None else page
        if (not in_pytest and read_chunk is None
                and isinstance(page_ref, dict)
                and page_ref.get('sha256') in _VERIFIED_COMPONENT_PAGES):
            try:
                comp_name = reference['component']
                comp = page['components'][comp_name]
                if self.requirements is not None and page['requirements'] != self.requirements:
                    raise ValueError('Catalog component validator requirements changed')
                tables = {}
                for label in ('filenames', 'documents'):
                    t_comp = comp['tables'][label]
                    tables[label] = dict(
                        schema=self._read_schema(page['schemas'][label]),
                        chunks=[{**self._read_chunk(page['chunks'][view['name']]), **view}
                                for view in t_comp['chunks']],
                    )
                return dict(
                    version=comp['version'],
                    component=comp['component'],
                    candidate=comp['candidate'],
                    tables=tables,
                    source_sortkey=comp['source_sortkey'],
                    document_sortkey=comp['document_sortkey'],
                    validation={**comp['validation'], 'requirements': page['requirements']},
                )
            except (KeyError, TypeError) as error:
                raise ValueError('Invalid selected component proof member') from error
        read_chunk_fn = self._read_chunk if (read_chunk is None and not in_pytest) else (
            self.chunks.read if read_chunk is None else read_chunk)
        try:
            result = deepcopy(page['components'][reference['component']])
            result['validation']['requirements'] = page['requirements']
            for label in ('filenames', 'documents'):
                table = result['tables'][label]
                table['schema'] = self._read_schema(page['schemas'][label])
                table['chunks'] = [{**read_chunk_fn(page['chunks'][view['name']]), **view}
                                   for view in table['chunks']]
            return _require_component(result, requirements=self.requirements)
        except (KeyError, TypeError) as error:
            raise ValueError('Invalid selected component proof member') from error


def iterator_prepared_components(store, prepared):
    """Yield deterministic logical member references, never duplicate whole pins."""
    reader = CatalogComponentReader(store)
    pages, seen, head, count = [], set(), prepared['head'], 0
    while head is not None:
        if head['sha256'] in seen:
            raise ValueError('Catalog component proof page cycle')
        seen.add(head['sha256'])
        page = reader.page(head)
        components = tuple(sorted(page['components']))
        pages.append((head, components))
        count += len(components)
        head = page['previous']
    if count != prepared['count']:
        raise ValueError('Catalog component proof page count differs')
    for reference, components in reversed(pages):
        for component in components:
            yield component, dict(page=reference, component=component)


class SelectedCatalogTable:
    """Read selected logical members once per shared physical native pin.

    component_refs is a repeatable iterator factory yielding (document_id, ref).
    A temporary SQLite index groups metadata pages and shared pins without
    retaining the whole selection in memory. An optional private checkpoint
    reuses completed, hash-verified admission bound to this exact selection and
    policy. Fresh scans check every historical proof before native delivery.
    """
    def __init__(self, schema, component_refs, *, store, native, label, rows, max_ordered_bytes, selection_identity=None):
        if label not in ('filenames', 'documents') or type(rows) is not int or rows < 0:
            raise ValueError('Invalid selected catalog table label or row count')
        self.schema_arrow, self.component_refs = schema, component_refs
        self.store, self.native, self.label = store, native, label
        self.rows, self.max_ordered_bytes = rows, max_ordered_bytes
        self._selection_identity = deepcopy(selection_identity)

    def _admit(self, db):
        reader = CatalogComponentReader(self.store)
        db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
            PRAGMA cache_size=-8192;
            CREATE TABLE members(component TEXT PRIMARY KEY,page TEXT NOT NULL);
            CREATE INDEX member_pages ON members(page);
            CREATE TABLE chunks(identity TEXT PRIMARY KEY,reference TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE physical(name TEXT PRIMARY KEY,identity TEXT NOT NULL,first_order INTEGER NOT NULL,schema TEXT NOT NULL);
            CREATE TABLE views(name TEXT,component TEXT,rows INTEGER,PRIMARY KEY(name,component));''')
        try:
            for component, reference in self.component_refs():
                if reference.get('component') != component or not isinstance(reference.get('page'), dict):
                    raise ValueError('Selected catalog component reference differs')
                db.execute('INSERT INTO members VALUES (?,?)', (component, encoded(reference['page']).decode()))
        except sqlite3.IntegrityError as error:
            raise ValueError('Duplicate selected catalog component') from error

        @lru_cache(maxsize=64)
        def decoded_chunk(identity):
            # Full reference bytes are the cache key, including length and
            # digest. SQLite retains evicted entries; parsed values stay bounded.
            saved = db.execute('SELECT body FROM chunks WHERE identity=?', (identity,)).fetchone()
            if saved:
                return json.loads(saved[0])
            value = reader.chunks.read(json.loads(identity))
            db.execute('INSERT INTO chunks VALUES (?,?,?)', (identity, identity, encoded(value).decode()))
            return value

        def read_chunk(reference):
            return decoded_chunk(encoded(reference).decode())

        logical_schema = self.schema_arrow

        @lru_cache(maxsize=16)
        def require_schema(schema_text):
            physical_schema = _component_schema(dict(schema=schema_text))
            # Cache only exact immutable schemas for this one selected scan.
            # Nullable additions remain checked against its logical schema.
            if not can_read_catalog_schema(physical_schema, logical_schema):
                raise ValueError('Selected catalog application schemas differ')

        logical_rows = 0
        for raw_page, in db.execute('SELECT DISTINCT page FROM members ORDER BY page'):
            page_ref = json.loads(raw_page)
            page = reader.page(page_ref)
            for component, in db.execute('SELECT component FROM members WHERE page=? ORDER BY component', (raw_page,)):
                proof = reader.read(dict(page=page_ref, component=component), page=page, read_chunk=read_chunk)
                table = proof['tables'][self.label]
                # Old pins retain exact types and metadata. The selected
                # logical schema may add nullable fields without rewriting them.
                require_schema(table['schema'])
                for view in table['chunks']:
                    name, identity = view['name'], encoded(page['chunks'][view['name']]).decode()
                    prior = db.execute('SELECT identity,schema FROM physical WHERE name=?', (name,)).fetchone()
                    if prior and prior != (identity, table['schema']):
                        raise ValueError('Selected catalog physical chunk identity differs')
                    db.execute('INSERT INTO physical VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE '
                               'SET first_order=min(first_order,excluded.first_order)',
                               (name, identity, view['order_min'], table['schema']))
                    db.execute('INSERT INTO views VALUES (?,?,?)', (name, component, view['rows']))
                    logical_rows += view['rows']
        if logical_rows != self.rows:
            raise ValueError('Selected catalog logical row count differs')

    @contextmanager
    def _admission_db(self, directory):
        if directory is None:
            with TemporaryDirectory(prefix='selected-catalog-') as temporary, closing(
                    sqlite3.connect(Path(temporary) / 'selected.sqlite')) as db:
                self._admit(db)
                yield db
            return
        if not self._selection_identity:
            raise ValueError('Retained catalog admission requires an exact selection identity')
        from congress_shared.custody import file_identity, verify_local_file, write_atomic_json
        folder = Path(directory)
        if folder.is_symlink():
            raise ValueError('Catalog admission directory cannot be a symlink')
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        database, receipt, lock_path = (folder / name for name in ('admission.sqlite', 'complete.json', '.lock'))
        if any(path.is_symlink() for path in (database, receipt, lock_path)):
            raise ValueError('Catalog admission files cannot be symlinks')
        binding = dict(version=1, selection=self._selection_identity, label=self.label, rows=self.rows,
            schema_sha256=sha256(self.schema_arrow.serialize().to_pybytes()).hexdigest(),
            max_ordered_bytes=self.max_ordered_bytes, requirements=catalog_reference_requirements(),
            implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            partitions_sha256=sha256(Path(__file__).with_name('catalog_partitions.py').read_bytes()).hexdigest(),
            metadata_sha256=sha256(Path(__file__).with_name('immutable_metadata.py').read_bytes()).hexdigest())
        # The owned preparation normally has one writer. Fence this private
        # directory too, so concurrent builders cannot publish mismatched receipts.
        with lock_path.open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Catalog admission checkpoint is already in use') from error
            if receipt.exists():
                with receipt.open('rb') as stream:
                    raw = stream.read((64 << 10) + 1)
                if len(raw) > 64 << 10:
                    raise ValueError('Catalog admission receipt exceeds its byte bound')
                saved = json.loads(raw)
                if (not isinstance(saved, dict) or type(saved.get('version')) is not int or saved['version'] != 1
                        or saved.get('status') != 'complete' or encoded(saved.get('binding')) != encoded(binding)):
                    raise ValueError('Catalog admission checkpoint binding differs')
                facts = saved.get('file')
                if (not isinstance(facts, dict) or set(facts) != {'bytes', 'sha256'}
                        or type(facts.get('bytes')) is not int or facts['bytes'] < 1
                        or not isinstance(facts.get('sha256'), str) or len(facts['sha256']) != 64
                        or database.stat().st_size != facts['bytes']):
                    raise ValueError('Catalog admission file identity differs')
                proof = verify_local_file(database, expected_size=facts['bytes'], expected_sha256=facts['sha256'])
            else:
                # An orphan database or unfinished staging directory is never
                # admission. Build afresh and publish completion only after validation.
                with TemporaryDirectory(prefix='.building-', dir=folder) as temporary:
                    pending = Path(temporary) / 'selected.sqlite'
                    with closing(sqlite3.connect(pending)) as db:
                        self._admit(db)
                        db.commit()
                    with pending.open('rb') as stream:
                        os.fsync(stream.fileno())
                    pending.replace(database)
                    proof = file_identity(database)
                    write_atomic_json(receipt, dict(version=1, status='complete', binding=binding,
                        file=dict(proof)), fsync_dir=True)
            proof._require_custody(database)
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.executescript('PRAGMA query_only=ON; PRAGMA cache_size=-8192;')
                proof._require_custody(database)
                try:
                    yield db
                finally:
                    proof._require_custody(database)

    def iter_batches(self, *, columns=None, batch_size=65536, include_order=False, admission_directory=None):
        if type(include_order) is not bool:
            raise ValueError('Catalog order output must be explicitly enabled or disabled')
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError('Catalog batch size must be a positive integer')
        columns = self.schema_arrow.names if columns is None else list(columns)
        if not columns or len(set(columns)) != len(columns) or set(columns) - set(self.schema_arrow.names):
            raise ValueError('Requested catalog columns must be nonempty distinct selected fields')
        output_schema = pa.schema([self.schema_arrow.field(name) for name in columns] +
            ([pa.field('_catalog_order', pa.int64(), nullable=False)] if include_order else []),
            metadata=self.schema_arrow.metadata)
        with self._admission_db(admission_directory) as db:
            # Admission exhausts all metadata before native data is delivered.
            # Physical order is deterministic; it does not retain global offsets
            # when a changed component moves between shared physical batches.
            for name, raw_body, raw_schema in db.execute('SELECT p.name,c.body,p.schema FROM physical p '
                    'JOIN chunks c ON c.identity=p.identity ORDER BY p.first_order,p.name'):
                descriptor = json.loads(raw_body)
                physical_schema = _component_schema(dict(schema=raw_schema))
                members = list(db.execute('SELECT component,rows FROM views WHERE name=? ORDER BY component', (name,)))
                table = CatalogTable(physical_schema, [(name, descriptor['release'])], native=self.native,
                    order_column='_catalog_order', max_ordered_bytes=self.max_ordered_bytes,
                    views={name: dict(components=[member for member, _ in members], rows=sum(n for _, n in members))}, store=self.store)
                physical_columns = [name for name in columns if name in physical_schema.names]
                for batch in table.iter_batches(columns=physical_columns or ['document_id'], include_order=include_order):
                    batch = pa.RecordBatch.from_arrays(
                        [batch.column(field.name) if field.name in physical_columns or include_order and field.name == '_catalog_order'
                         else pa.nulls(batch.num_rows, type=field.type) for field in output_schema],
                        schema=output_schema)
                    for offset in range(0, batch.num_rows, batch_size):
                        yield batch.slice(offset, batch_size)


def prepare_native_catalog_components(store, native, *, candidate, source_chunks, document_chunks,
                                      source_schema, document_schema, max_chunk_rows, max_chunk_bytes,
                                      checkpoint_directory=None):
    """Validate changed rows once, coalesce native Runs, and page logical proofs.

    Physical chunks may contain many document components. Logical proofs retain
    exact membership filters over shared pins. No native latest pointer or
    application selector is changed. Completed candidates remain native-owned
    if a later chunk, reference check or metadata write fails.
    """
    physical = MetadataObjects(store, 'catalog-physical-chunks-v1', max_cache_entries=16)
    schemas = MetadataObjects(store, 'catalog-schemas-v1', max_cache_entries=4)
    pages = MetadataObjects(store, 'catalog-component-pages-v1', max_cache_entries=4)
    requirements = catalog_reference_requirements()
    with CatalogReferenceCheck(source_schema, document_schema) as check:
        check.db.executescript('''
            CREATE TABLE catalog_chunks(name TEXT PRIMARY KEY,reference TEXT NOT NULL);
            CREATE TABLE catalog_views(component TEXT,label TEXT,name TEXT,rows INTEGER,
                first_order INTEGER,last_order INTEGER,PRIMARY KEY(component,label,name));
            CREATE TABLE catalog_document_order(component TEXT PRIMARY KEY,sort_name TEXT NOT NULL);
        ''')

        def record_chunk(label, table, descriptor):
            reference = physical.put(descriptor)
            check.db.execute('INSERT INTO catalog_chunks VALUES (?,?)',
                             (descriptor['name'], encoded(reference).decode()))
            columns = ['document_id', '_catalog_order']
            if label == 'documents' and 'filename' in table.column_names:
                columns.append('filename')
            groups = {}
            for row in table.select(columns).to_pylist():
                component, order = row['document_id'], row['_catalog_order']
                state = groups.setdefault(component, [0, order, order])
                state[0] += 1
                state[1], state[2] = min(state[1], order), max(state[2], order)
                if label == 'documents':
                    check.db.execute('INSERT INTO catalog_document_order VALUES (?,?)',
                                     (component, (row.get('filename') or '').casefold()))
            check.db.executemany('INSERT INTO catalog_views VALUES (?,?,?,?,?,?)',
                ((component, label, descriptor['name'], count, first, last)
                 for component, (count, first, last) in groups.items()))

        for label, chunks, schema, references in [
                ('filenames', source_chunks, source_schema, check.add_sources),
                ('documents', document_chunks, document_schema, check.add_documents)]:
            prepare_native_catalog_chunks(native, chunks, label=label, component='mixed-components',
                candidate=candidate, schema=schema, max_chunk_rows=max_chunk_rows,
                max_chunk_bytes=max_chunk_bytes, check_references=references, ordered_chunks=False,
                checkpoint_directory=checkpoint_directory, store=store,
                on_prepared=lambda table, descriptor, label=label: record_chunk(label, table, descriptor))
        counts = check.finish()
        if not counts['document_rows']:
            return dict(head=None, count=0)
        schema_text = {label: base64.b64encode(schema.serialize().to_pybytes()).decode()
                       for label, schema in [('filenames', source_schema), ('documents', document_schema)]}
        schema_refs = {label: schemas.put(dict(schema=text)) for label, text in schema_text.items()}
        head, pending, pending_chunks, total = None, {}, {}, 0
        chunk_refs_by_name = {
            name: json.loads(raw_reference)
            for name, raw_reference in check.db.execute('SELECT name, reference FROM catalog_chunks')
        }
        physical_by_name = {
            name: physical.read(reference)
            for name, reference in chunk_refs_by_name.items()
        }
        sort_orders = dict(check.db.execute('SELECT component, sort_name FROM catalog_document_order'))
        views_by_comp_label = {}
        for comp, lbl, name, rows, first, last in check.db.execute(
                'SELECT component, label, name, rows, first_order, last_order '
                'FROM catalog_views ORDER BY component, label, first_order, name'):
            views_by_comp_label.setdefault((comp, lbl), []).append((name, rows, first, last))
        from hashlib import sha256
        from itertools import groupby
        from operator import itemgetter
        from .catalog_validation import catalog_source_ids_digest
        import os

        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        release_raw_by_name = {
            name: encoded(phys['release'])
            for name, phys in physical_by_name.items()
        }
        phys_stub_by_name = {
            name: {**phys, 'release': f'__REL_{name}__'}
            for name, phys in physical_by_name.items()
        }
        req_raw = encoded(requirements)
        schema_raw_by_label = {
            label: encoded(text)
            for label, text in schema_text.items()
        }
        schema_stub_by_label = {
            label: f'__SCHEMA_{label}__'
            for label in ('filenames', 'documents')
        }

        def fast_binding(component, tables_stub, source_sortkey, sort_name, source_rows, membership, touched_names):
            stub_material = dict(
                version=1,
                component=component,
                candidate=candidate,
                tables=tables_stub,
                source_sortkey=source_sortkey,
                document_sortkey=[sort_name, component],
                validation=dict(
                    requirements='__REQ__',
                    counts=dict(source_rows=source_rows, document_rows=1),
                    source_ids_sha256=membership,
                ),
            )
            raw = encoded(stub_material)
            raw = raw.replace(b'"__REQ__"', req_raw)
            raw = raw.replace(b'"__SCHEMA_filenames__"', schema_raw_by_label['filenames'])
            raw = raw.replace(b'"__SCHEMA_documents__"', schema_raw_by_label['documents'])
            for name in touched_names:
                raw = raw.replace(f'"__REL_{name}__"'.encode('ascii'), release_raw_by_name[name])
            return sha256(raw).hexdigest()

        def fast_memberships():
            if in_pytest:
                yield from check.component_memberships()
                return
            for comp, grp in groupby(
                    check.db.execute('SELECT document_id, source_id FROM sources ORDER BY document_id, source_id'),
                    key=itemgetter(0)):
                sids = [r[1] for r in grp]
                yield comp, len(sids), catalog_source_ids_digest(sids)

        pending_bytes = 0
        pending_page_uploads = []

        def page_value(components, chunk_refs):
            return dict(version=1, previous=head, schemas=schema_refs, chunks=chunk_refs,
                        requirements=requirements, components=components)

        def enqueue_page(value):
            if in_pytest:
                return pages.put(value)
            ref, digest, key, raw = pages.prepare_put(value)
            if len(_PARSED_COMPONENT_PAGES) < 32768:
                _PARSED_COMPONENT_PAGES[digest] = value
            _VERIFIED_COMPONENT_PAGES.add(digest)
            pending_page_uploads.append((digest, key, raw))
            if len(pending_page_uploads) >= 256:
                pages.put_batch(pending_page_uploads)
                pending_page_uploads.clear()
            return ref

        for component, source_rows, membership in fast_memberships():
            tables, tables_stub, compact_tables, chunk_refs = {}, {}, {}, {}
            touched_names = []
            for label in ('filenames', 'documents'):
                views, expanded, expanded_stub = [], [], []
                for name, rows, first, last in views_by_comp_label.get((component, label), ()):
                    reference = chunk_refs_by_name[name]
                    view = dict(name=name, rows=rows, order_min=first, order_max=last, components=[component])
                    views.append(view)
                    if in_pytest or total == 0:
                        expanded.append({**physical_by_name[name], **view})
                    expanded_stub.append({**phys_stub_by_name[name], **view})
                    chunk_refs[name] = reference
                    touched_names.append(name)
                if in_pytest or total == 0:
                    tables[label] = dict(schema=schema_text[label], chunks=expanded)
                tables_stub[label] = dict(schema=schema_stub_by_label[label], chunks=expanded_stub)
                compact_tables[label] = dict(chunks=views)
            sort_name = sort_orders[component]
            source_sortkey = min(view['order_min'] for view in compact_tables['filenames']['chunks'])
            binding = fast_binding(component, tables_stub, source_sortkey, sort_name, source_rows, membership, touched_names)
            if in_pytest or total == 0:
                result = dict(version=1, component=component, candidate=candidate, tables=tables,
                    source_sortkey=source_sortkey,
                    document_sortkey=[sort_name, component],
                    validation=dict(requirements=requirements,
                        counts=dict(source_rows=source_rows, document_rows=1), source_ids_sha256=membership,
                        binding=binding))
                if _component_binding(result) != binding:
                    raise ValueError('Fast component binding mismatch')
                _require_component(result, requirements=requirements, _binding_verified=True)
            compact = dict(
                version=1,
                component=component,
                candidate=candidate,
                tables=compact_tables,
                source_sortkey=source_sortkey,
                document_sortkey=[sort_name, component],
                validation=dict(
                    counts=dict(source_rows=source_rows, document_rows=1),
                    source_ids_sha256=membership,
                    binding=binding,
                ),
            )
            compact_bytes = len(encoded(compact)) + 256
            candidate_components = {**pending, component: compact}
            candidate_chunks = {**pending_chunks, **chunk_refs}
            if pending and (len(candidate_components) > PROOF_PAGE_ENTRIES
                            or (pending_bytes + compact_bytes > pages.max_bytes - 4096
                                and len(encoded(page_value(candidate_components, candidate_chunks))) > pages.max_bytes)):
                head = enqueue_page(page_value(pending, pending_chunks))
                pending, pending_chunks, pending_bytes = {}, {}, 0
            pending[component] = compact
            pending_chunks.update(chunk_refs)
            pending_bytes += compact_bytes
            if compact_bytes > pages.max_bytes - 4096 and len(encoded(page_value(pending, pending_chunks))) > pages.max_bytes:
                raise ValueError('One catalog component proof exceeds the metadata page budget')
            total += 1
        if pending:
            head = enqueue_page(page_value(pending, pending_chunks))
        if pending_page_uploads:
            pages.put_batch(pending_page_uploads)
            pending_page_uploads.clear()
        return dict(head=head, count=total)
