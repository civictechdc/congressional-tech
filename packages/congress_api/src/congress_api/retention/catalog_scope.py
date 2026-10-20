"""Run maintained grouping on a closed source scope and emit bounded chunks."""
from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Mapping, Collection
from contextlib import ExitStack, closing
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import document_index as index
from .catalog_dependencies import DependencyGap, DependencyWorkingSet

ORDER = '_catalog_order'


class ScopeSourceIndex(Mapping):
    """Exact ordinals or document mappings backed by the grouping scratch DB."""
    def __init__(self, working, *, documents=False):
        self.working, self.documents = working, documents
        self.column = 'document' if documents else 'ordinal'
        self.where = 'WHERE current=1' if documents else ''

    def __getitem__(self, key):
        row = self.working.work.connection.execute(
            f'SELECT {self.column} FROM sources WHERE identity=?' + (' AND current=1' if self.documents else ''), (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row[0]

    def __iter__(self):
        return (row[0] for row in self.working.work.connection.execute(
            f'SELECT identity FROM sources {self.where} ORDER BY ordinal'))

    def __len__(self):
        return self.working.work.connection.execute(f'SELECT count(*) FROM sources {self.where}').fetchone()[0]


class ScopeDocumentIDs(Collection):
    def __init__(self, working):
        self.working = working

    def __iter__(self):
        return (row[0] for row in self.working.work.connection.execute('SELECT identity FROM documents ORDER BY ordinal'))

    def __len__(self):
        return self.working.work.connection.execute('SELECT count(*) FROM documents').fetchone()[0]

    def __contains__(self, key):
        return self.working.work.connection.execute('SELECT 1 FROM documents WHERE identity=?', (key,)).fetchone() is not None

    def position(self, key):
        row = self.working.work.connection.execute('SELECT ordinal FROM documents WHERE identity=?', (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row[0]


class ScopeMembers(Mapping):
    """Component ownership keys and counts, without per-component Python lists."""
    def __init__(self, db, name):
        self.db, self.name = db, name
        db.execute(f'CREATE TABLE {name}(component TEXT,member TEXT,PRIMARY KEY(component,member))')

    def add(self, component, member):
        self.db.execute(f'INSERT INTO {self.name} VALUES (?,?)', (component, member))

    def __iter__(self):
        return (row[0] for row in self.db.execute(f'SELECT DISTINCT component FROM {self.name} ORDER BY component'))

    def __len__(self):
        return self.db.execute(f'SELECT count(DISTINCT component) FROM {self.name}').fetchone()[0]

    def __getitem__(self, component):
        count = self.db.execute(f'SELECT count(*) FROM {self.name} WHERE component=?', (component,)).fetchone()[0]
        if not count:
            raise KeyError(component)
        return ScopeMemberIDs(self, component, count)


class ScopeMemberIDs(Collection):
    def __init__(self, owner, component, count):
        self.owner, self.component, self.count = owner, component, count

    def __iter__(self):
        return (row[0] for row in self.owner.db.execute(
            f'SELECT member FROM {self.owner.name} WHERE component=? ORDER BY member', (self.component,)))

    def __len__(self):
        return self.count

    def __contains__(self, key):
        return self.owner.db.execute(f'SELECT 1 FROM {self.owner.name} WHERE component=? AND member=?',
                                     (self.component, key)).fetchone() is not None


def _same_keys(left, right):
    return len(left) == len(right) and all(key in right for key in left)


def _body_coverage(db, prepared, expected, encoded):
    from hashlib import sha256
    db.execute('CREATE TABLE bodies(value TEXT PRIMARY KEY,expected INTEGER DEFAULT 0,prepared INTEGER DEFAULT 0)')
    db.executemany('INSERT OR IGNORE INTO bodies(value,expected) VALUES (?,1)', ((value,) for value in expected))
    for row in prepared.source_values():
        if row.get('body_key'):
            db.execute('INSERT INTO bodies(value,prepared) VALUES (?,1) ON CONFLICT(value) '
                       'DO UPDATE SET prepared=1', (row['body_key'],))
    if db.execute('SELECT 1 FROM bodies WHERE expected=1 AND prepared=0 LIMIT 1').fetchone():
        raise ValueError('Catalog affected outputs omit an expected retained body')
    def digest(label):
        result, first = sha256(b'['), True
        for value, in db.execute(f'SELECT value FROM bodies WHERE {label}=1 ORDER BY value'):
            if not first:
                result.update(b',')
            first = False
            result.update(encoded(value))
        result.update(b']')
        return result.hexdigest()
    return dict(expected_count=db.execute('SELECT count(*) FROM bodies WHERE expected=1').fetchone()[0],
                expected_sha256=digest('expected'),
                prepared_count=db.execute('SELECT count(*) FROM bodies WHERE prepared=1').fetchone()[0],
                prepared_sha256=digest('prepared'))


@dataclass
class PreparedCatalogScope:
    scope: object
    filenames_path: Path
    documents_path: Path
    source_schema: pa.Schema
    document_schema: pa.Schema
    source_orders: object
    candidate: str
    source_document_ids: object
    document_ids: object
    _working: object = None

    def close(self):
        if self._working is not None:
            self._working.close()

    @property
    def source_rows(self):
        return len(self.source_document_ids)

    def _chunks(self, path, schema, order_for_row, *, max_rows, max_bytes):
        if type(max_rows) is not int or max_rows < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Catalog chunk budgets must be positive integers')
        physical = schema.append(pa.field(ORDER, pa.int64(), nullable=False))
        pending, size = [], 0
        with pq.ParquetFile(path) as file:
            for batch in file.iter_batches(batch_size=max_rows):
                for row in batch.to_pylist():
                    row[ORDER] = order_for_row(row)
                    row_bytes = pa.Table.from_pylist([row], schema=physical).nbytes
                    if row_bytes > max_bytes:
                        raise ValueError('One catalog row exceeds its native chunk byte budget')
                    if pending and (len(pending) == max_rows or size + row_bytes > max_bytes):
                        yield pa.Table.from_pylist(pending, schema=physical)
                        pending, size = [], 0
                    pending.append(row)
                    size += row_bytes
        if pending:
            yield pa.Table.from_pylist(pending, schema=physical)

    def source_chunks(self, *, max_rows, max_bytes):
        """Mixed-component physical chunks; old ordinals remain explicit data."""
        return self._chunks(self.filenames_path, self.source_schema,
            lambda row: self.source_orders[row['source_id']], max_rows=max_rows, max_bytes=max_bytes)

    def document_chunks(self, *, max_rows, max_bytes):
        return self._chunks(self.documents_path, self.document_schema,
            lambda row: self.document_ids.position(row['document_id']), max_rows=max_rows, max_bytes=max_bytes)

    def source_links(self):
        """Preserve imported source order and explain changed document mappings."""
        for key in self.source_orders:
            yield dict(source_id=key, source_order=self.source_orders[key],
                       old_document_id=self.scope.before.get(key, {}).get('document_id'),
                       new_document_id=self.source_document_ids.get(key))

    def source_values(self):
        with pq.ParquetFile(self.filenames_path) as file:
            for batch in file.iter_batches(batch_size=256):
                yield from batch.to_pylist()


def prepare_catalog_scope(directory, scope, *, schema, source_orders, candidate):
    """Use the current grouping owner; never reconstruct unrelated catalog rows.

    The caller first establishes complete old/new closure through selected
    dependency state. Schema columns belong to the complete logical catalog:
    they cannot be dropped because this particular affected subset is redundant.
    """
    if not isinstance(candidate, str) or not candidate or ORDER in schema.names:
        raise ValueError('Catalog scope requires a candidate and unreserved application schema')
    working = DependencyWorkingSet()
    db = working.work.connection
    db.executescript('CREATE TABLE sources(identity TEXT PRIMARY KEY,ordinal INTEGER UNIQUE,current INTEGER,document TEXT); '
                     'CREATE TABLE documents(identity TEXT PRIMARY KEY,ordinal INTEGER UNIQUE);')
    try:
        def add(key, current):
            try:
                position = source_orders[key]
            except KeyError as error:
                raise DependencyGap('Missing immutable source order for the affected scope') from error
            if type(position) is not int or position < 0:
                raise DependencyGap('Affected source order must be nonnegative and unique')
            try:
                db.execute('INSERT INTO sources VALUES (?,?,?,NULL)', (key, position, int(current)))
            except sqlite3.IntegrityError as error:
                raise DependencyGap('Affected source order must be nonnegative and unique') from error
        for key in scope.before:
            add(key, key in scope.after)
        for key in scope.after:
            if key not in scope.before:
                add(key, True)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        filename_path, document_path = directory / 'document-filenames.parquet', directory / 'documents.parquet'
        rows = (deepcopy(scope.after[key]) for key, in db.execute('SELECT identity FROM sources WHERE current=1 ORDER BY ordinal'))
        index.write_document_indexes(filename_path, rows, schema, catalog_id=candidate, preserve_columns=True)
        with pq.ParquetFile(filename_path) as sources, pq.ParquetFile(document_path) as documents:
            source_schema, document_schema = sources.schema_arrow, documents.schema_arrow
            for batch in sources.iter_batches(columns=['source_id', 'document_id'], batch_size=256):
                for row in batch.to_pylist():
                    key = row['source_id']
                    prior = db.execute('SELECT document FROM sources WHERE identity=? AND current=1', (key,)).fetchone()
                    if prior is None:
                        raise DependencyGap('Grouped source identities differ from the closed affected scope')
                    if prior[0] is not None:
                        raise DependencyGap('Repeated grouped source identity')
                    if not row['document_id']:
                        raise DependencyGap('Grouped source is missing its document identity')
                    db.execute('UPDATE sources SET document=? WHERE identity=?', (row['document_id'], key))
            ordinal = 0
            for batch in documents.iter_batches(columns=['document_id'], batch_size=256):
                for row in batch.to_pylist():
                    try:
                        db.execute('INSERT INTO documents VALUES (?,?)', (row['document_id'], ordinal))
                    except sqlite3.IntegrityError as error:
                        raise DependencyGap('Repeated grouped document identity') from error
                    ordinal += 1
        if db.execute('SELECT 1 FROM sources WHERE current=1 AND document IS NULL LIMIT 1').fetchone():
            raise DependencyGap('Grouped source identities differ from the closed affected scope')
        return PreparedCatalogScope(scope, filename_path, document_path, source_schema, document_schema,
            ScopeSourceIndex(working), candidate, ScopeSourceIndex(working, documents=True),
            ScopeDocumentIDs(working), working)
    except BaseException:
        working.close()
        raise


def catalog_scope_requirements():
    """Bind new scope admission to this reviewed implementation."""
    from hashlib import sha256
    return dict(validator='catalog-scope-v1', implementation_sha256=sha256(
        Path(__file__).read_bytes()).hexdigest())


def _component_pages(store, values):
    from .immutable_metadata import MetadataObjects
    from contextlib import closing
    import json
    import sqlite3
    from tempfile import TemporaryDirectory
    objects = MetadataObjects(store, 'catalog-scope-components-v1', max_cache_entries=1)
    pending, head, count = [], None, 0
    with TemporaryDirectory(prefix='scope-members-') as directory, closing(
            sqlite3.connect(Path(directory) / 'members.sqlite')) as db:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                         'CREATE TABLE members(name TEXT PRIMARY KEY,reference TEXT);')
        try:
            db.executemany('INSERT INTO members VALUES (?,?)', ((name, json.dumps(reference))
                                                               for name, reference in values))
        except sqlite3.IntegrityError as error:
            raise ValueError('Repeated catalog scope component') from error
        for name, reference in db.execute('SELECT name,reference FROM members ORDER BY name DESC'):
            pending.append(dict(component=name, reference=json.loads(reference)))
            count += 1
            if len(pending) == 64:
                head = objects.put(dict(version=1, previous=head, components=list(reversed(pending))))
                pending = []
        if pending:
            head = objects.put(dict(version=1, previous=head, components=list(reversed(pending))))
    return dict(head=head, count=count)


def iterator_scope_components(store, proof, label):
    """Read bounded immutable metadata pages; never reopen old native payloads."""
    from .immutable_metadata import MetadataObjects
    if label not in {'retired', 'prepared'}:
        raise ValueError('Unknown catalog scope component set')
    objects = MetadataObjects(store, 'catalog-scope-components-v1', max_cache_entries=1)
    item, count, previous = proof[label], 0, None
    current = item['head']
    while current is not None:
        page = objects.read(current)
        if page.get('version') != 1 or not 1 <= len(page.get('components', ())) <= 64:
            raise ValueError('Invalid catalog scope component page')
        for entry in page['components']:
            name = entry['component']
            if not isinstance(name, str) or not name or previous is not None and name <= previous:
                raise ValueError('Catalog scope components must be unique ordered names')
            previous, count = name, count + 1
            if count > item['count']:
                raise ValueError('Catalog scope component count differs')
            yield name, entry['reference']
        current = page['previous']
    if count != proof[label]['count']:
        raise ValueError('Catalog scope component count differs')


def read_catalog_scope(store, reference, *, requirements=None):
    from hashlib import sha256
    from .immutable_metadata import MetadataObjects, encoded
    result = MetadataObjects(store, 'catalog-scope-proofs-v1').read(reference)
    binding = result.get('binding')
    if (result.get('version') != 1
            or binding != sha256(encoded({k: v for k, v in result.items() if k != 'binding'})).hexdigest()
            or requirements is not None and result.get('requirements') != requirements):
        raise ValueError('Catalog scope proof binding or requirements differ')
    for label in ('retired', 'prepared'):
        item = result.get(label, {})
        if type(item.get('count')) is not int or item['count'] < 0 or bool(item.get('head')) != bool(item['count']):
            raise ValueError('Invalid catalog scope component inventory')
    return result


def verify_catalog_scope(store, *, dependencies, dependency_before, dependency_after,
                         prepared, base, component_lookup, prepared_components,
                         read_component, read_new_component=None, rules, expected_bodies=(), source_update=None,
                         interpretation_before=None, complete_counts=None):
    """Prove closed old ownership, candidate membership and no unrelated ID reuse.

    Component readers must verify their immutable proof bindings. Historical old
    proofs establish exact selected ownership; new proofs also meet the current
    reference requirements. The publication owner supplies those two readers.
    """
    import base64
    from hashlib import sha256
    from .catalog_dependencies import affected_sources
    from .catalog_validation import catalog_source_ids_digest
    from .immutable_metadata import MetadataObjects, encoded
    if not isinstance(base, dict) or not isinstance(rules, dict) or not rules:
        raise ValueError('Scope admission requires an exact base identity and explicit rules')
    with ExitStack() as stack:
        working = stack.enter_context(closing(DependencyWorkingSet()))
        old = stack.enter_context(closing(dependencies.selected(dependency_before)))
        before, after = prepared.scope.before, prepared.source_document_ids
        removed = working.work.mapping('removed')
        for key in before:
            if key not in after:
                removed[key] = True
        closed = stack.enter_context(closing(affected_sources(old, replacements=prepared.source_values(), deletions=removed)))
        if not _same_keys(closed.before, before) or not _same_keys(closed.after, after):
            raise DependencyGap('Prepared source scope is not closed under old/new dependencies')
        old_members = ScopeMembers(working.work.connection, 'old_members')
        new_members = ScopeMembers(working.work.connection, 'new_members')
        for key, row in before.items():
            if old.source(key) != row or old.order(key) != prepared.source_orders[key]:
                raise DependencyGap('Old source values or order differ from the selected dependency version')
            component = row.get('document_id')
            if not component:
                raise DependencyGap('Missing selected document ownership for source ' + key)
            old_members.add(component, key)
        for key, component in after.items():
            if key not in before and old.source(key) is not None:
                raise DependencyGap('Candidate source ID collides with an unaffected selected source')
            new_members.add(component, key)
        if complete_counts is not None:
            from .source_update_proof import read_source_update
            purpose = read_source_update(store, source_update).get('purpose') if source_update else None
            if purpose not in {'qualification', 'rule-upgrade'}:
                raise DependencyGap('Complete dependency replacement requires retained source qualification')
            if complete_counts != dict(source_rows=len(before), document_rows=len(old_members)):
                raise DependencyGap('Complete source replacement omits selected source or document ownership')
            if purpose == 'qualification':
                if not _same_keys(before, after):
                    raise DependencyGap('Source qualification changed selected source identities')
                for row in prepared.source_values():
                    old_row = before[row['source_id']]
                    if any(old_row.get(name) != row.get(name) for name in prepared.source_schema.names):
                        raise DependencyGap('Source qualification changed selected values or document mappings')
        retired = working.work.mapping('retired')
        for component, members in old_members.items():
            reference = component_lookup(component)
            value = read_component(reference)
            if (value['component'] != component
                    or value['validation']['counts'] != dict(source_rows=len(members), document_rows=1)
                    or value['validation']['source_ids_sha256'] != catalog_source_ids_digest(iter(members))):
                raise DependencyGap('Retired component ownership is incomplete: ' + component)
            retired[component] = reference
        if complete_counts is not None and purpose == 'qualification':
            from .catalog_batches import SelectedCatalogTable
            from .catalog_qualification import qualify_complete_values
            selected = MetadataObjects(store, 'catalog-selections-v2').read(base['selected_ref'])
            schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(selected['schemas']['documents'], validate=True)))
            old_documents = SelectedCatalogTable(schema, lambda: iter(retired.items()), store=store,
                native=dependencies.native, label='documents', rows=len(old_members),
                max_ordered_bytes=dependencies.max_bytes)
            with pq.ParquetFile(prepared.documents_path) as documents:
                qualify_complete_values(old_documents, documents, 'documents')
        read_new_component = read_new_component or read_component
        incoming, seen = working.work.mapping('incoming'), working.work.mapping('seen')
        for component, reference in prepared_components:
            if component in seen or component not in new_members:
                raise DependencyGap('Unexpected or repeated prepared component')
            seen[component] = True
            value = read_new_component(reference)
            members = new_members[component]
            if (value['component'] != component or value['candidate'] != prepared.candidate
                    or value['validation']['counts'] != dict(source_rows=len(members), document_rows=1)
                    or value['validation']['source_ids_sha256'] != catalog_source_ids_digest(iter(members))):
                raise DependencyGap('Prepared component membership differs from grouped source outputs')
            incoming[component] = reference
        if not _same_keys(seen, new_members):
            raise DependencyGap('Missing prepared component for the closed source scope')
        # Only the maintained affected-leaf preparation may determine new roots.
        # Checking changed rows alone would allow silently dropping unrelated leaves.
        expected = (dependencies.prepare_full(dependency_before, replacements=prepared.source_values(),
                                             source_orders=prepared.source_orders)
                    if complete_counts is not None else dependencies.prepare(dependency_before,
                        replacements=prepared.source_values(), deletions=removed, source_orders=prepared.source_orders))
        if expected != dependency_after:
            raise DependencyGap('Candidate changed unrelated or unaffected dependency routing')
        current = stack.enter_context(closing(dependencies.selected(dependency_after)))
        for row in prepared.source_values():
            key = row['source_id']
            if (current.source(key) != row or current.order(key) != prepared.source_orders[key]):
                raise DependencyGap('Candidate dependency values differ from grouped source outputs')
        if any(current.source(key) is not None for key in removed):
            raise DependencyGap('Deleted source survives in candidate dependency state')
        interpretation_after = interpretation_before
        if source_update is None and interpretation_before is not None:
            from . import document_index as index
            fields = set(index.SOURCE_SCHEMA.names) | index.SOURCE_CONTEXT_FIELDS | index.AVAILABILITY_FIELDS | {'capture_outcome'}
            unchanged = _same_keys(before, after)
            for row in prepared.source_values():
                old_row = before.get(row['source_id'])
                unchanged = unchanged and old_row is not None and all(old_row.get(name) == row.get(name) for name in fields)
            if not unchanged:
                interpretation_after = None  # Complete interpreted replacements alone do not prove receipt attribution.
        if source_update is not None:
            from .source_update_proof import verify_source_update
            interpretation_after = verify_source_update(store, source_update, native=dependencies.native, base=base, before=interpretation_before,
                rows=prepared.source_values(), deletions=removed)
        body_coverage = _body_coverage(working.work.connection, prepared, expected_bodies, encoded)
        result = dict(version=1, base=deepcopy(base), dependency_before=deepcopy(dependency_before),
            dependency_after=deepcopy(dependency_after), candidate=prepared.candidate,
            schemas=dict(filenames=base64.b64encode(prepared.source_schema.serialize().to_pybytes()).decode(),
                         documents=base64.b64encode(prepared.document_schema.serialize().to_pybytes()).decode()),
            retired=_component_pages(store, retired.items()), prepared=_component_pages(store, incoming.items()),
            counts=dict(retired_source_rows=len(before), prepared_source_rows=len(after),
                        retired_document_rows=len(old_members), prepared_document_rows=len(new_members)),
            rules=deepcopy(rules), mapping=None, body_coverage=body_coverage, source_update=source_update,
            complete_replacement=complete_counts is not None,
            interpretation_before=interpretation_before, interpretation_after=interpretation_after, requirements=catalog_scope_requirements())
        result['binding'] = sha256(encoded(result)).hexdigest()
        return MetadataObjects(store, 'catalog-scope-proofs-v1').put(result)
