"""Run maintained grouping on a closed source scope and emit bounded chunks."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import document_index as index
from .catalog_dependencies import DependencyGap

ORDER = '_catalog_order'


@dataclass
class PreparedCatalogScope:
    scope: object
    filenames_path: Path
    documents_path: Path
    source_schema: pa.Schema
    document_schema: pa.Schema
    source_orders: dict
    candidate: str
    source_document_ids: dict
    document_ids: tuple

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
        positions = {key: i for i, key in enumerate(self.document_ids)}
        return self._chunks(self.documents_path, self.document_schema,
            lambda row: positions[row['document_id']], max_rows=max_rows, max_bytes=max_bytes)

    def source_links(self):
        """Preserve imported source order and explain changed document mappings."""
        for key in sorted(set(self.scope.before) | set(self.source_document_ids),
                          key=self.source_orders.__getitem__):
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
    keys = set(scope.before) | set(scope.after)
    try:
        bounded_orders = {key: source_orders[key] for key in keys}
    except KeyError as error:
        raise DependencyGap('Missing immutable source order for the affected scope') from error
    orders = list(bounded_orders.values())
    if any(type(value) is not int or value < 0 for value in orders) or len(set(orders)) != len(orders):
        raise DependencyGap('Affected source order must be nonnegative and unique')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    filename_path, document_path = directory / 'document-filenames.parquet', directory / 'documents.parquet'
    rows = (deepcopy(scope.after[key]) for key in sorted(scope.after, key=source_orders.__getitem__))
    index.write_document_indexes(filename_path, rows, schema, catalog_id=candidate, preserve_columns=True)
    with pq.ParquetFile(filename_path) as sources, pq.ParquetFile(document_path) as documents:
        source_schema, document_schema = sources.schema_arrow, documents.schema_arrow
        mapping = {}
        for batch in sources.iter_batches(columns=['source_id', 'document_id'], batch_size=256):
            for row in batch.to_pylist():
                if row['source_id'] in mapping:
                    raise DependencyGap('Repeated grouped source identity')
                mapping[row['source_id']] = row['document_id']
        document_ids = tuple(row['document_id'] for batch in documents.iter_batches(
            columns=['document_id'], batch_size=256) for row in batch.to_pylist())
    if set(mapping) != set(scope.after):
        raise DependencyGap('Grouped source identities differ from the closed affected scope')
    return PreparedCatalogScope(scope, filename_path, document_path, source_schema, document_schema,
                                bounded_orders, candidate, mapping, document_ids)


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
                         read_component, read_new_component=None, rules):
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
    old = dependencies.selected(dependency_before)
    before, after = prepared.scope.before, prepared.source_document_ids
    removed = set(before) - set(after)
    closed = affected_sources(old, replacements=prepared.source_values(), deletions=removed)
    if set(closed.before) != set(before) or set(closed.after) != set(after):
        raise DependencyGap('Prepared source scope is not closed under old/new dependencies')
    old_members, new_members = {}, {}
    for key, row in before.items():
        if old.source(key) != row or old.order(key) != prepared.source_orders[key]:
            raise DependencyGap('Old source values or order differ from the selected dependency version')
        component = row.get('document_id')
        if not component:
            raise DependencyGap('Missing selected document ownership for source ' + key)
        old_members.setdefault(component, []).append(key)
    for key, component in after.items():
        if key not in before and old.source(key) is not None:
            raise DependencyGap('Candidate source ID collides with an unaffected selected source')
        new_members.setdefault(component, []).append(key)
    retired = []
    for component, members in sorted(old_members.items()):
        reference = component_lookup(component)
        value = read_component(reference)
        if (value['component'] != component
                or value['validation']['counts'] != dict(source_rows=len(members), document_rows=1)
                or value['validation']['source_ids_sha256'] != catalog_source_ids_digest(iter(sorted(members)))):
            raise DependencyGap('Retired component ownership is incomplete: ' + component)
        retired.append((component, reference))
    read_new_component = read_new_component or read_component
    incoming, seen = [], set()
    for component, reference in prepared_components:
        if component in seen or component not in new_members:
            raise DependencyGap('Unexpected or repeated prepared component')
        seen.add(component)
        value = read_new_component(reference)
        members = new_members[component]
        if (value['component'] != component or value['candidate'] != prepared.candidate
                or value['validation']['counts'] != dict(source_rows=len(members), document_rows=1)
                or value['validation']['source_ids_sha256'] != catalog_source_ids_digest(iter(sorted(members)))):
            raise DependencyGap('Prepared component membership differs from grouped source outputs')
        incoming.append((component, reference))
    if seen != set(new_members):
        raise DependencyGap('Missing prepared component for the closed source scope')
    # Only the maintained affected-leaf preparation may determine new roots.
    # Checking changed rows alone would allow silently dropping unrelated leaves.
    expected = dependencies.prepare(dependency_before, replacements=prepared.source_values(),
        deletions=removed, source_orders=prepared.source_orders)
    if expected != dependency_after:
        raise DependencyGap('Candidate changed unrelated or unaffected dependency routing')
    current = dependencies.selected(dependency_after)
    for row in prepared.source_values():
        key = row['source_id']
        if (current.source(key) != row or current.order(key) != prepared.source_orders[key]):
            raise DependencyGap('Candidate dependency values differ from grouped source outputs')
    if any(current.source(key) is not None for key in removed):
        raise DependencyGap('Deleted source survives in candidate dependency state')
    result = dict(version=1, base=deepcopy(base), dependency_before=deepcopy(dependency_before),
        dependency_after=deepcopy(dependency_after), candidate=prepared.candidate,
        schemas=dict(filenames=base64.b64encode(prepared.source_schema.serialize().to_pybytes()).decode(),
                     documents=base64.b64encode(prepared.document_schema.serialize().to_pybytes()).decode()),
        retired=_component_pages(store, retired), prepared=_component_pages(store, incoming),
        counts=dict(retired_source_rows=len(before), prepared_source_rows=len(after),
                    retired_document_rows=len(old_members), prepared_document_rows=len(new_members)),
        rules=deepcopy(rules), mapping=None, requirements=catalog_scope_requirements())
    result['binding'] = sha256(encoded(result)).hexdigest()
    return MetadataObjects(store, 'catalog-scope-proofs-v1').put(result)
