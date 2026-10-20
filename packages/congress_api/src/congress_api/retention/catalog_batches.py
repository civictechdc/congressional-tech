"""Coalesced native catalog batches and bounded shared component proof pages."""
import base64
from copy import deepcopy
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa

from congress_api.retention.catalog_partitions import CatalogTable

from congress_api.retention.catalog_publication import (
    _component_binding, _component_schema, _require_component, prepare_native_catalog_chunks,
)
from congress_api.retention.catalog_validation import CatalogReferenceCheck, catalog_reference_requirements
from congress_api.retention.immutable_metadata import MetadataObjects, encoded

PROOF_PAGE_ENTRIES = 64


def same_logical_catalog_schema(left, right):
    """Only the root-selected logical catalog identity may change on reuse."""
    def without_catalog_id(schema):
        return schema.with_metadata({key: value for key, value in (schema.metadata or {}).items()
                                     if key != b'catalog_id'})
    return without_catalog_id(left).equals(without_catalog_id(right), check_metadata=True)


class CatalogComponentReader:
    """Share page/schema/pin reads across components during one admission or read."""
    def __init__(self, store, *, requirements=None):
        self.pages = MetadataObjects(store, 'catalog-component-pages-v1', max_cache_entries=4)
        self.schemas = MetadataObjects(store, 'catalog-schemas-v1', max_cache_entries=4)
        self.chunks = MetadataObjects(store, 'catalog-physical-chunks-v1', max_cache_entries=16)
        self.requirements = requirements

    def page(self, reference):
        page = self.pages.read(reference)
        if (page.get('version') != 1 or not isinstance(page.get('components'), dict)
                or not 0 < len(page['components']) <= PROOF_PAGE_ENTRIES
                or not isinstance(page.get('requirements'), dict) or not page['requirements']):
            raise ValueError('Invalid catalog component proof page')
        return page

    def read(self, reference, *, page=None, read_chunk=None):
        page = self.page(reference['page']) if page is None else page
        read_chunk = self.chunks.read if read_chunk is None else read_chunk
        try:
            result = deepcopy(page['components'][reference['component']])
            result['validation']['requirements'] = page['requirements']
            for label in ('filenames', 'documents'):
                table = result['tables'][label]
                table['schema'] = self.schemas.read(page['schemas'][label])['schema']
                table['chunks'] = [{**read_chunk(page['chunks'][view['name']]), **view}
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
        pages.append(head)
        count += len(page['components'])
        head = page['previous']
    if count != prepared['count']:
        raise ValueError('Catalog component proof page count differs')
    for reference in reversed(pages):
        for component in sorted(reader.page(reference)['components']):
            yield component, dict(page=reference, component=component)


class SelectedCatalogTable:
    """Read selected logical members once per shared physical native pin.

    component_refs is a repeatable iterator factory yielding (document_id, ref).
    A temporary SQLite index groups metadata pages and shared pins without
    retaining the whole selection in memory. Each scan checks exact historical
    proofs; publication admission separately supplies current requirements.
    """
    def __init__(self, schema, component_refs, *, store, native, label, rows, max_ordered_bytes):
        if label not in ('filenames', 'documents') or type(rows) is not int or rows < 0:
            raise ValueError('Invalid selected catalog table label or row count')
        self.schema_arrow, self.component_refs = schema, component_refs
        self.store, self.native, self.label = store, native, label
        self.rows, self.max_ordered_bytes = rows, max_ordered_bytes

    def iter_batches(self, *, columns=None, batch_size=65536):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError('Catalog batch size must be a positive integer')
        reader = CatalogComponentReader(self.store)
        with TemporaryDirectory(prefix='selected-catalog-') as directory, closing(
                sqlite3.connect(Path(directory) / 'selected.sqlite')) as db:
            db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
                PRAGMA cache_size=-8192;
                CREATE TABLE members(component TEXT PRIMARY KEY,page TEXT NOT NULL);
                CREATE INDEX member_pages ON members(page);
                CREATE TABLE chunks(identity TEXT PRIMARY KEY,reference TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE physical(name TEXT PRIMARY KEY,identity TEXT NOT NULL,first_order INTEGER NOT NULL);
                CREATE TABLE views(name TEXT,component TEXT,rows INTEGER,PRIMARY KEY(name,component));''')
            try:
                for component, reference in self.component_refs():
                    if reference.get('component') != component or not isinstance(reference.get('page'), dict):
                        raise ValueError('Selected catalog component reference differs')
                    db.execute('INSERT INTO members VALUES (?,?)', (component, encoded(reference['page']).decode()))
            except sqlite3.IntegrityError as error:
                raise ValueError('Duplicate selected catalog component') from error

            def read_chunk(reference):
                identity = encoded(reference).decode()
                saved = db.execute('SELECT body FROM chunks WHERE identity=?', (identity,)).fetchone()
                if saved:
                    return json.loads(saved[0])
                value = reader.chunks.read(reference)
                db.execute('INSERT INTO chunks VALUES (?,?,?)', (identity, identity, encoded(value).decode()))
                return value

            logical_rows = 0
            for raw_page, in db.execute('SELECT DISTINCT page FROM members ORDER BY page'):
                page_ref = json.loads(raw_page)
                page = reader.page(page_ref)
                for component, in db.execute('SELECT component FROM members WHERE page=? ORDER BY component', (raw_page,)):
                    proof = reader.read(dict(page=page_ref, component=component), page=page, read_chunk=read_chunk)
                    table = proof['tables'][self.label]
                    physical_schema = _component_schema(table)
                    # catalog_id names the selected logical pair. Reused pins
                    # retain their original exact schema/proof, while the root
                    # explicitly selects the new logical pair identity. Other
                    # application and field metadata must match exactly.
                    if not same_logical_catalog_schema(physical_schema, self.schema_arrow):
                        raise ValueError('Selected catalog application schemas differ')
                    for view in table['chunks']:
                        name, identity = view['name'], encoded(page['chunks'][view['name']]).decode()
                        prior = db.execute('SELECT identity FROM physical WHERE name=?', (name,)).fetchone()
                        if prior and prior[0] != identity:
                            raise ValueError('Selected catalog physical chunk identity differs')
                        db.execute('INSERT INTO physical VALUES (?,?,?) ON CONFLICT(name) DO UPDATE '
                                   'SET first_order=min(first_order,excluded.first_order)',
                                   (name, identity, view['order_min']))
                        db.execute('INSERT INTO views VALUES (?,?,?)', (name, component, view['rows']))
                        logical_rows += view['rows']
            if logical_rows != self.rows:
                raise ValueError('Selected catalog logical row count differs')
            # Admission exhausts all metadata before native data is delivered.
            # Physical order is deterministic; it does not retain global offsets
            # when a changed component moves between shared physical batches.
            for name, raw_body in db.execute('SELECT p.name,c.body FROM physical p '
                    'JOIN chunks c ON c.identity=p.identity ORDER BY p.first_order,p.name'):
                descriptor = json.loads(raw_body)
                members = list(db.execute('SELECT component,rows FROM views WHERE name=? ORDER BY component', (name,)))
                table = CatalogTable(self.schema_arrow, [(name, descriptor['release'])], native=self.native,
                    order_column='_catalog_order', max_ordered_bytes=self.max_ordered_bytes,
                    views={name: dict(components=[member for member, _ in members], rows=sum(n for _, n in members))})
                for batch in table.iter_batches(columns=columns):
                    for offset in range(0, batch.num_rows, batch_size):
                        yield batch.slice(offset, batch_size)


def prepare_native_catalog_components(store, native, *, candidate, source_chunks, document_chunks,
                                      source_schema, document_schema, max_chunk_rows, max_chunk_bytes):
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
                on_prepared=lambda table, descriptor, label=label: record_chunk(label, table, descriptor))
        counts = check.finish()
        if not counts['document_rows']:
            return dict(head=None, count=0)
        schema_text = {label: base64.b64encode(schema.serialize().to_pybytes()).decode()
                       for label, schema in [('filenames', source_schema), ('documents', document_schema)]}
        schema_refs = {label: schemas.put(dict(schema=text)) for label, text in schema_text.items()}
        head, pending, pending_chunks, total = None, {}, {}, 0

        def page_value(components, chunk_refs):
            return dict(version=1, previous=head, schemas=schema_refs, chunks=chunk_refs,
                        requirements=requirements, components=components)

        for component, source_rows, membership in check.component_memberships():
            tables, chunk_refs = {}, {}
            for label in ('filenames', 'documents'):
                views, expanded = [], []
                for name, rows, first, last, raw_reference in check.db.execute('''
                        SELECT v.name,v.rows,v.first_order,v.last_order,c.reference
                        FROM catalog_views v JOIN catalog_chunks c ON v.name=c.name
                        WHERE v.component=? AND v.label=? ORDER BY v.first_order,v.name''', (component, label)):
                    reference = json.loads(raw_reference)
                    view = dict(name=name, rows=rows, order_min=first, order_max=last, components=[component])
                    views.append(view)
                    expanded.append({**physical.read(reference), **view})
                    chunk_refs[name] = reference
                tables[label] = dict(schema=schema_text[label], chunks=expanded)
            sort_name, = check.db.execute('SELECT sort_name FROM catalog_document_order WHERE component=?',
                                         (component,)).fetchone()
            result = dict(version=1, component=component, candidate=candidate, tables=tables,
                source_sortkey=min(view['order_min'] for view in tables['filenames']['chunks']),
                document_sortkey=[sort_name, component],
                validation=dict(requirements=requirements,
                    counts=dict(source_rows=source_rows, document_rows=1), source_ids_sha256=membership))
            result['validation']['binding'] = _component_binding(result)
            _require_component(result, requirements=requirements)
            compact = deepcopy(result)
            del compact['validation']['requirements']
            for label in ('filenames', 'documents'):
                compact['tables'][label] = dict(chunks=[
                    {key: value for key, value in view.items() if key != 'release' and key != 'arrow_bytes'}
                    for view in result['tables'][label]['chunks']])
            candidate_components = {**pending, component: compact}
            candidate_chunks = {**pending_chunks, **chunk_refs}
            if pending and (len(candidate_components) > PROOF_PAGE_ENTRIES
                            or len(encoded(page_value(candidate_components, candidate_chunks))) > pages.max_bytes):
                head = pages.put(page_value(pending, pending_chunks))
                pending, pending_chunks = {}, {}
            pending[component] = compact
            pending_chunks.update(chunk_refs)
            if len(encoded(page_value(pending, pending_chunks))) > pages.max_bytes:
                raise ValueError('One catalog component proof exceeds the metadata page budget')
            total += 1
        if pending:
            head = pages.put(page_value(pending, pending_chunks))
        return dict(head=head, count=total)
