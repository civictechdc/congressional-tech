"""Immutable catalog dependency leaves selected through shared routing pages.

DocSpec owns each bounded typed leaf. The application's coherent catalog selector
owns the returned roots; preparing a candidate never selects it for readers.
"""
from copy import deepcopy
import base64
from contextlib import closing
from pathlib import Path
import pickle
import json
import sqlite3
from tempfile import TemporaryDirectory
from hashlib import sha256

import pyarrow as pa

from . import document_index as index
from .catalog_dependencies import (
    affected_sources, alias_schema, dependency_schema, dependency_tables,
    DependencyGap, DependencyWorkingSet, NativeCatalogDependencies, _encoded_alias, _decoded_alias,
)
from .partition_routing import RoutingPages, key_hash
from .catalog_memberships import CatalogMemberships
from .source_aliases import resolution_candidates
from .immutable_metadata import MetadataObjects
from .catalog_batches import can_read_catalog_schema
from .catalog_availability import package_dependencies
from .catalog_staging import WorkingCatalog



class CatalogDependencyStorage:
    """Prepare exact keyed source/alias state; preserve unaffected native pins."""
    def __init__(self, *, native, store, namespace, source_schema, max_rows, max_bytes):
        if type(max_rows) is not int or max_rows < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Catalog dependency partition budgets must be positive integers')
        self.native, self.source_schema, self.namespace = native, source_schema, namespace
        from .catalog_rows import CatalogRows
        self.row_owner = CatalogRows(native=native, store=store)
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.sources = RoutingPages(store, namespace + '-sources')
        self.sources.objects.max_cache_entries = 16
        self.schemas = MetadataObjects(store, namespace + '-source-schemas', max_cache_entries=4)
        self.memberships = CatalogMemberships(store=store, namespace=namespace, schema=alias_schema(),
            member_column='source_id', max_rows=max_rows, max_bytes=max_bytes,
            read=self._read, write=self._write, validate_alias=_decoded_alias)
        self.aliases, self.members = self.memberships.routes, self.memberships.members
        lookup_options = dict(store=store, schema=alias_schema(), member_column='source_id',
            max_rows=max_rows, max_bytes=max_bytes, read=self._read,
            write=lambda table, kind: self._write(table, 'lookup-' + kind), validate_alias=lambda key: key)
        self.urls = CatalogMemberships(namespace=namespace + '-source-url', **lookup_options)
        self.targets = CatalogMemberships(namespace=namespace + '-resolved-target', **lookup_options)
        self.bodies = CatalogMemberships(namespace=namespace + '-body-key', **lookup_options)
        self.packages = CatalogMemberships(namespace=namespace + '-hearing-package', **lookup_options)
        from . import source_aliases, catalog_availability
        self.lookup_requirements = sha256(Path(source_aliases.__file__).read_bytes() +
                                          Path(catalog_availability.__file__).read_bytes()).hexdigest()
        self.schema_bytes = source_schema.remove_metadata().serialize().to_pybytes()
        self.schema_hash = sha256(self.schema_bytes).hexdigest()
        self.rows_read = self.bytes_read = 0
        self.candidate_rows_submitted = self.candidate_arrow_bytes = 0

    @classmethod
    def for_snapshot(cls, snapshot):
        """Restore the selected lookup owner on a fresh configured host."""
        if snapshot.native is None:
            raise ValueError('Catalog lookups require the configured native client')
        basis = snapshot.selection['dependency']
        return cls(native=snapshot.native, store=snapshot.store, namespace=basis['namespace'],
            source_schema=pa.ipc.read_schema(pa.BufferReader(base64.b64decode(basis['source_schema']))).with_metadata(
                snapshot.schemas['filenames'].metadata), max_rows=basis['max_rows'],
            max_bytes=basis['max_arrow_bytes'])

    def _selection(self, selection, *, require_lookup_policy=False):
        if selection is None:
            return dict(format='catalog-dependencies-v3', namespace=self.namespace, ownership_edges='document-id-v1', schema_hash=self.schema_hash,
                        max_rows=self.max_rows, max_arrow_bytes=self.max_bytes,
                        source_root=None, alias_root=None, url_root=None, target_root=None, body_root=None, package_root=None, lookup_schema='url-resolution-body-package-v1',
                        lookup_requirements=self.lookup_requirements, source_schema=base64.b64encode(self.schema_bytes).decode(), next_source_order=0)
        if (selection.get('format') != 'catalog-dependencies-v3'
                or selection.get('namespace') != self.namespace
                or selection.get('ownership_edges') != 'document-id-v1'
                or selection.get('max_rows') != self.max_rows
                or selection.get('max_arrow_bytes') != self.max_bytes
                or type(selection.get('next_source_order')) is not int
                or selection['next_source_order'] < 0):
            raise DependencyGap('Catalog dependency selection schema or order basis differs')
        stored = self._source_schema(selection.get('source_schema'))
        if (selection.get('schema_hash') != sha256(base64.b64decode(selection['source_schema'], validate=True)).hexdigest()
                or not can_read_catalog_schema(stored, self.source_schema.remove_metadata())):
            raise DependencyGap('Catalog dependency selection schema or order basis differs')
        if require_lookup_policy and (selection.get('lookup_requirements') != self.lookup_requirements
                or selection.get('lookup_schema') != 'url-resolution-body-package-v1'):
            raise DependencyGap('Catalog URL lookup policy changed; qualify an explicit lookup adoption')
        return deepcopy(selection)

    def _source_schema(self, value):
        if isinstance(value, dict):
            value = self.schemas.read(value)['source_schema']
        try:
            schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(value, validate=True)))
        except (ValueError, TypeError, pa.ArrowException) as error:
            raise DependencyGap('Invalid retained dependency source schema') from error
        return schema

    def _source_reference(self, pin, basis):
        if pin is None or 'source_schema' in pin:
            return pin
        return dict(release=pin, source_schema=basis.get('legacy_source_schema') or basis['source_schema'])

    def _source_leaf_schema(self, reference):
        schema = self._source_schema(reference['source_schema'])
        if not can_read_catalog_schema(schema, self.source_schema.remove_metadata()):
            raise DependencyGap('Retained dependency leaf cannot supply selected logical source schema')
        return schema

    def _evolved_selection(self, basis):
        if basis['source_schema'] == base64.b64encode(self.schema_bytes).decode():
            return basis
        return dict(basis, legacy_source_schema=basis.get('legacy_source_schema') or basis['source_schema'],
                    source_schema=base64.b64encode(self.schema_bytes).decode(), schema_hash=self.schema_hash)

    def _read(self, pin, schema):
        stored_schema = (dependency_schema(self._source_leaf_schema(pin))
                         if 'source_schema' in pin else schema)
        release = pin['release'] if 'source_schema' in pin else pin
        before=(self.row_owner.rows_read,self.row_owner.bytes_read)
        batches=[];rows=size=0
        from .catalog_rows import core_bytes
        for batch in self.row_owner.read(release, schema=stored_schema):
            rows+=len(batch)
            size+=core_bytes(pa.Table.from_batches([batch]))
            if rows>self.max_rows or size>self.max_bytes:
                raise DependencyGap('Selected dependency leaf exceeds its row or byte budget')
            batches.append(batch)
        self.rows_read+=self.row_owner.rows_read-before[0]
        self.bytes_read+=self.row_owner.bytes_read-before[1]
        table=pa.Table.from_batches(batches,schema=stored_schema)
        return (table.cast(schema) if stored_schema.equals(schema,check_metadata=True)
                else pa.Table.from_pylist(table.to_pylist(),schema=schema))

    def _write(self, table, kind):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        identity = sha256(sink.getvalue().to_pybytes()).hexdigest()
        before=(self.row_owner.candidate_rows_submitted,self.row_owner.candidate_arrow_bytes)
        pin = self.row_owner.write(table, dataset=f'catalog-dep-v3-{kind}-{identity}',
            operation='initial', definition='catalog-dependencies-storage-v3',
            max_rows=self.max_rows, max_bytes=self.max_bytes)
        self.candidate_rows_submitted += self.row_owner.candidate_rows_submitted-before[0]
        self.candidate_arrow_bytes += self.row_owner.candidate_arrow_bytes-before[1]
        if kind == 'sources':
            reference = self.schemas.put(dict(source_schema=base64.b64encode(self.schema_bytes).decode()))
            return dict(release=pin, source_schema=reference)
        return pin

    def _replace_rows(self, root, pages, *, key, schema, replacements, deletions, kind, basis=None):
        # Partition changes on disk first. Inserting many new rows into an empty
        # route must not assemble the entire affected scope before splitting.
        with TemporaryDirectory(prefix='catalog-source-changes-') as directory, closing(
                WorkingCatalog(Path(directory) / 'changes.sqlite')) as work:
            db = work.connection
            db.executescript('CREATE TABLE changes(identity TEXT PRIMARY KEY,prefix TEXT,body BLOB); '
                'CREATE TABLE bases(prefix TEXT PRIMARY KEY,body BLOB); '
                'CREATE TABLE rows(identity TEXT PRIMARY KEY,digest TEXT,body BLOB); '
                'CREATE INDEX row_hashes ON rows(digest);')
            for identity in deletions:
                prefix, pin = pages.lookup(root, identity)
                db.execute('INSERT OR IGNORE INTO bases VALUES (?,?)', (prefix, pickle.dumps(pin)))
                db.execute('INSERT INTO changes VALUES (?,?,NULL)', (identity, prefix))
            for identity in replacements:
                prefix, pin = pages.lookup(root, identity)
                db.execute('INSERT OR IGNORE INTO bases VALUES (?,?)', (prefix, pickle.dumps(pin)))
                db.execute('INSERT INTO changes VALUES (?,?,?) ON CONFLICT(identity) '
                    'DO UPDATE SET body=excluded.body', (identity, prefix, pickle.dumps(replacements[identity])))
            for prefix, pin_body in db.execute('SELECT prefix,body FROM bases ORDER BY prefix'):
                pin = pickle.loads(pin_body)
                stored = self._source_reference(pin, basis) if kind == 'sources' else pin
                existing = self._read(stored, schema).to_pylist() if stored is not None else []
                db.execute('DELETE FROM rows')
                try:
                    db.executemany('INSERT INTO rows VALUES (?,?,?)',
                        ((row[key], key_hash(row[key]), pickle.dumps(row)) for row in existing))
                except sqlite3.IntegrityError as error:
                    raise DependencyGap('Duplicate keyed catalog dependency rows') from error
                changed = False
                for identity, body in db.execute('SELECT identity,body FROM changes WHERE prefix=? ORDER BY identity', (prefix,)):
                    prior = db.execute('SELECT body FROM rows WHERE identity=?', (identity,)).fetchone()
                    if (pickle.loads(prior[0]) if prior else None) == (pickle.loads(body) if body is not None else None):
                        continue
                    changed = True
                    db.execute('DELETE FROM rows WHERE identity=?', (identity,))
                    if body is not None:
                        db.execute('INSERT INTO rows VALUES (?,?,?)', (identity, key_hash(identity), body))
                if not changed:
                    continue
                def leaves(child):
                    values = [pickle.loads(body) for body, in db.execute(
                        'SELECT body FROM rows WHERE digest>=? AND digest<? ORDER BY identity LIMIT ?',
                        (child, child + 'g', self.max_rows + 1))]
                    table = pa.Table.from_pylist(values, schema=schema)
                    if self._fits(table):
                        if len(table):
                            yield child, self._write(table, kind)
                        return
                    if len(table) == 1 or len(child) == 64:
                        raise DependencyGap('One selected source cannot fit its dependency leaf budget')
                    for char in '0123456789abcdef':
                        yield from leaves(child + char)
                generated = iter(leaves(prefix))
                first = next(generated, None)
                if first is None:
                    root = pages.replace(root, prefix, {prefix: None})
                else:
                    from itertools import chain
                    root = pages.replace_stream(root, prefix, chain([first], generated))
        return root

    def _fits(self, table):
        from .catalog_rows import fits_chunk
        return fits_chunk(table, max_rows=self.max_rows, max_bytes=self.max_bytes)

    def read_source_leaf(self, selection, value, *, source_columns=None):
        """Read one selected routing value using its exact physical app schema."""
        basis = self._selection(selection)
        reference=self._source_reference(value,basis)
        if source_columns is None:
            return self._read(reference,dependency_schema(self.source_schema))
        source_schema=self._source_leaf_schema(reference)
        available=[name for name in source_columns if name in source_schema.names]
        schema=dependency_schema(source_schema)
        batches=list(self.row_owner.read(reference['release'],schema=schema,source_columns=available))
        physical=schema.set(schema.get_field_index('source_values'),schema.field('source_values').with_type(pa.struct([source_schema.field(name)for name in available])))
        table=pa.Table.from_batches(batches,schema=physical)
        logical=dependency_schema(pa.schema([self.source_schema.field(name)for name in source_columns]))
        return table if physical.equals(logical,check_metadata=True) else pa.Table.from_pylist(table.to_pylist(),schema=logical)

    def source_occurrences(self, selection, value, source_id):
        basis=self._selection(selection)
        reference=self._source_reference(value,basis)
        if 'source_occurrences' not in self._source_leaf_schema(reference).names:
            return None
        return self.row_owner.occurrences(reference['release'],schema=dependency_schema(self._source_leaf_schema(reference)),owner_id=source_id)

    def selected(self, selection):
        basis = self._selection(selection)
        working = DependencyWorkingSet()
        member_counts = working.work.mapping('expected_members')
        pin_counts = working.work.mapping('expected_pin_rows')

        def source_pin(key):
            return self._source_reference(self.sources.lookup(basis['source_root'], key)[1], basis)

        def alias_pins(value):
            _, leaf = self.aliases.lookup(basis['alias_root'], value)
            if leaf is None:
                member_counts[value] = 0
                return ()
            if leaf.get('kind') == 'rows':
                pin_counts[index.compact(leaf['release'])] = leaf['rows']
                # The exact complete native leaf proves all aliases it stores;
                # no separate per-alias directory or native Run is necessary.
                member_counts[value] = None
                return (leaf['release'],)
            if leaf.get('kind') != 'members':
                raise DependencyGap('Unknown alias dependency leaf format')
            if value != leaf.get('alias'):
                member_counts[value] = 0
                return ()
            member_counts[value] = leaf['count']
            def pins():
                count = 0
                for _, pin in self.members.leaf_items(leaf['root']):
                    count += 1
                    yield pin
                if not count:
                    raise DependencyGap('Missing reverse dependency member partitions')
            return pins()

        return NativeCatalogDependencies(native=self.native, source_schema=self.source_schema,
            locate_source=source_pin, locate_alias=alias_pins, source_leaf_schema=self._source_leaf_schema, expected_members=member_counts.__getitem__,
            expected_rows=lambda pin: pin_counts.get(index.compact(pin)),
            max_rows=self.max_rows, max_bytes=self.max_bytes, working=working, row_owner=self.row_owner)

    @staticmethod
    def _lookup_keys(row):
        url = row.get('source_url')
        urls = {'url:' + url} if isinstance(url, str) and url else set()
        targets = {'target:' + index.compact(target) for target in resolution_candidates(row)}
        bodies = {'body:' + row['body_key']} if row.get('body_key') else set()
        packages = {'package:' + value for value in package_dependencies(row)}
        return urls, targets, bodies, packages

    def _prepare_lookups(self, basis, before, after):
        # Membership owners are source IDs, so removing one version cannot
        # erase another version's URL or recorded resolution evidence.
        with TemporaryDirectory(prefix='catalog-url-changes-') as directory, closing(
                sqlite3.connect(Path(directory) / 'changes.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE changes(kind INTEGER,alias TEXT,source TEXT,old INTEGER,new INTEGER, '
                'PRIMARY KEY(kind,alias,source)); '
                'CREATE TABLE members(kind INTEGER,alias TEXT,source TEXT,PRIMARY KEY(kind,alias,source)); '
                'CREATE TABLE scope_keys(identity TEXT PRIMARY KEY);')
            db.executemany('INSERT INTO scope_keys VALUES (?)', ((key,) for key in before))
            db.executemany('INSERT OR IGNORE INTO scope_keys VALUES (?)', ((key,) for key in after))
            for identity, in db.execute('SELECT identity FROM scope_keys ORDER BY identity'):
                old = self._lookup_keys(before[identity]) if identity in before else (set(), set(), set(), set())
                new = self._lookup_keys(after[identity]) if identity in after else (set(), set(), set(), set())
                for kind in (0, 1, 2, 3):
                    for alias in old[kind] ^ new[kind]:
                        db.execute('INSERT INTO changes VALUES (?,?,?,?,?)',
                                   (kind, alias, identity, int(alias in old[kind]), int(alias in new[kind])))
            roots = []
            for kind, owner, label in [(0, self.urls, 'url_root'), (1, self.targets, 'target_root'), (2, self.bodies, 'body_root'), (3, self.packages, 'package_root')]:
                for alias, in db.execute('SELECT DISTINCT alias FROM changes WHERE kind=?', (kind,)):
                    for identity in owner.values(basis[label], alias):
                        if db.execute('SELECT 1 FROM changes WHERE kind=? AND alias=? AND source=? AND old=1',
                                      (kind, alias, identity)).fetchone() is None:
                            db.execute('INSERT OR IGNORE INTO members VALUES (?,?,?)', (kind, alias, identity))
                    db.execute('INSERT OR IGNORE INTO members SELECT kind,alias,source FROM changes '
                               'WHERE kind=? AND alias=? AND new=1', (kind, alias))
                class Changes:
                    def __iter__(self):
                        return (row[0] for row in db.execute('SELECT DISTINCT alias FROM changes WHERE kind=? ORDER BY alias', (kind,)))
                    def __getitem__(self, alias):
                        return (row[0] for row in db.execute('SELECT source FROM members WHERE kind=? AND alias=? ORDER BY source', (kind, alias)))
                roots.append(owner.replace(basis[label], Changes()))
            return dict(url_root=roots[0], target_root=roots[1], body_root=roots[2], package_root=roots[3])

    def _lookup_sources(self, selection, owner, root, alias):
        selected = self.selected(selection)
        for identity in owner.values(root, alias):
            row = selected.source(identity)
            if row is None:
                raise DependencyGap('URL lookup refers to a missing selected source')
            yield dict(source_id=identity, source_order=selected.order(identity), source_values=row)

    def sources_at_url(self, selection, url):
        basis = self._selection(selection, require_lookup_policy=True)
        return self._lookup_sources(basis, self.urls, basis['url_root'], 'url:' + url)

    def originals_targeting(self, selection, target):
        basis = self._selection(selection, require_lookup_policy=True)
        return self._lookup_sources(basis, self.targets, basis['target_root'], 'target:' + index.compact(target))

    def sources_at_body(self, selection, body_key):
        basis = self._selection(selection, require_lookup_policy=True)
        return self._lookup_sources(basis, self.bodies, basis['body_root'], 'body:' + body_key)

    def sources_at_package(self, selection, package):
        basis = self._selection(selection, require_lookup_policy=True)
        return self._lookup_sources(basis, self.packages, basis['package_root'], 'package:' + package)

    def adopt(self, chunks, *, source_orders=None, first_unused_order=0):
        """Import exact selected source values without replaying grouping policy.

        Adoption enumerates the prior table once. Temporary hash indexes bound
        native leaf construction even when a whole historical component shares
        one body or endpoint. This path never selects the resulting roots.
        """
        from .partition_routing import key_hash
        with TemporaryDirectory(prefix='catalog-dependency-adoption-') as directory, closing(
                sqlite3.connect(Path(directory) / 'sources.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE sources(identity TEXT PRIMARY KEY,digest TEXT,body BLOB,ordinal INTEGER UNIQUE); '
                'CREATE INDEX source_hashes ON sources(digest); '
                'CREATE TABLE aliases(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
                'CREATE TABLE lookups(kind INTEGER,alias TEXT,member TEXT,PRIMARY KEY(kind,alias,member));')
            count, next_order = 0, first_unused_order
            for chunk in chunks:
                if not chunk.schema.equals(self.source_schema, check_metadata=True):
                    raise DependencyGap('Adoption source schema differs from the selected table')
                for row in chunk.to_pylist():
                    identity = index.source_identity(row)
                    if row.get('source_id') != identity:
                        raise DependencyGap('Adoption source identity differs from its saved key')
                    position = count if source_orders is None else source_orders[identity]
                    if type(position) is not int or position < 0:
                        raise DependencyGap('Source order must be a nonnegative integer')
                    next_order = max(next_order, position + 1)
                    sources, aliases = dependency_tables([row], self.source_schema, first_order=position)
                    try:
                        db.execute('INSERT INTO sources VALUES (?,?,?,?)',
                            (identity, key_hash(identity), pickle.dumps(sources.to_pylist()[0]), position))
                    except sqlite3.IntegrityError as error:
                        raise DependencyGap('Repeated selected source identity during adoption') from error
                    db.executemany('INSERT INTO aliases VALUES (?,?)',
                        ((edge['alias'], edge['source_id']) for edge in aliases.to_pylist()))
                    for kind, keys in enumerate(self._lookup_keys(row)):
                        db.executemany('INSERT OR IGNORE INTO lookups VALUES (?,?,?)',
                                       ((kind, key, identity) for key in keys))
                    count += 1
            def leaves(prefix):
                rows = [pickle.loads(body) for body, in db.execute(
                    'SELECT body FROM sources WHERE digest>=? AND digest<? ORDER BY identity LIMIT ?',
                    (prefix, prefix + 'g', self.max_rows + 1))]
                table = pa.Table.from_pylist(rows, schema=dependency_schema(self.source_schema))
                if self._fits(table):
                    if len(table):
                        yield prefix, self._write(table, 'sources')
                    return
                if len(table) == 1 or len(prefix) == 64:
                    raise DependencyGap('One selected source cannot fit its adoption leaf budget')
                for char in '0123456789abcdef':
                    yield from leaves(prefix + char)
            source_root = self.sources.replace_stream(None, '', leaves('')) if count else None
            class Aliases:
                def __iter__(self):
                    return (row[0] for row in db.execute('SELECT DISTINCT alias FROM aliases ORDER BY alias'))
                def __getitem__(self, alias):
                    return (row[0] for row in db.execute('SELECT member FROM aliases WHERE alias=? ORDER BY member', (alias,)))
            alias_root = self.memberships.replace(None, Aliases())
            lookup_roots = []
            for kind, owner in [(0, self.urls), (1, self.targets), (2, self.bodies), (3, self.packages)]:
                class Lookups:
                    def __iter__(self):
                        return (row[0] for row in db.execute('SELECT DISTINCT alias FROM lookups WHERE kind=? ORDER BY alias', (kind,)))
                    def __getitem__(self, alias):
                        return (row[0] for row in db.execute('SELECT member FROM lookups WHERE kind=? AND alias=? ORDER BY member', (kind, alias)))
                lookup_roots.append(owner.replace(None, Lookups()))
            return dict(self._selection(None), source_root=source_root, alias_root=alias_root,
                        url_root=lookup_roots[0], target_root=lookup_roots[1], body_root=lookup_roots[2], package_root=lookup_roots[3], next_source_order=next_order)

    def prepare_full(self, selection, *, replacements, source_orders):
        """Prepare a complete reviewed inventory using the bounded adoption owner.

        Scope admission separately proves that every selected source and document
        is accounted for before these immutable candidates can be selected.
        """
        basis = self._selection(selection)
        selected = self.selected(basis)
        next_order = basis['next_source_order']

        def chunks():
            nonlocal next_order
            pending = []
            for row in replacements:
                key = index.source_identity(row)
                if selected.source(key) is not None:
                    if source_orders[key] != selected.order(key):
                        raise DependencyGap('Full replacement changed an existing source order')
                else:
                    if source_orders[key] != next_order:
                        raise DependencyGap('New source orders must extend the selected contiguous ordinal range')
                    next_order += 1
                pending.append(row)
                if len(pending) == 256:
                    yield pa.Table.from_pylist(pending, schema=self.source_schema)
                    pending = []
            if pending:
                yield pa.Table.from_pylist(pending, schema=self.source_schema)

        return self.adopt(chunks(), source_orders=source_orders, first_unused_order=next_order)

    def prepare(self, selection, *, replacements=(), deletions=(), source_orders=None):
        """Prepare changed bounded leaves; selection still belongs to one app CAS.

        Temporary SQL indexes hold changed rows, ordinals and reverse edges even
        when one affected component spans many native partitions.
        """
        basis = self._evolved_selection(self._selection(selection, require_lookup_policy=True))
        with TemporaryDirectory(prefix='catalog-dependency-changes-') as directory, closing(
                WorkingCatalog(Path(directory) / 'scope.sqlite')) as work:
            db = work.connection
            replacement_rows = work.mapping('replacements')
            db.executescript('CREATE TABLE removed(identity TEXT PRIMARY KEY); '
                'CREATE TABLE new_positions(identity TEXT PRIMARY KEY,ordinal INTEGER UNIQUE); '
                'CREATE TABLE old_edges(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
                'CREATE TABLE new_edges(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
                'CREATE TABLE changed_aliases(alias TEXT PRIMARY KEY);')
            for row in replacements:
                identity = index.source_identity(row)
                if identity in replacement_rows:
                    raise ValueError('Duplicate replacement source identity')
                replacement_rows[identity] = row
            db.executemany('INSERT OR IGNORE INTO removed VALUES (?)', ((key,) for key in deletions))
            if not replacement_rows and not db.execute('SELECT 1 FROM removed LIMIT 1').fetchone():
                return basis
            selected = self.selected(basis)
            scope = affected_sources(selected, replacements=replacement_rows.values(),
                                     deletions=(row[0] for row in db.execute('SELECT identity FROM removed')))
            try:
                order = basis['next_source_order']
                for identity in replacement_rows:
                    if identity not in scope.before:
                        position = source_orders[identity] if source_orders is not None else order
                        if type(position) is not int or position < 0:
                            raise DependencyGap('New source orders must extend the selected contiguous ordinal range')
                        try:
                            db.execute('INSERT INTO new_positions VALUES (?,?)', (identity, position))
                        except sqlite3.IntegrityError as error:
                            raise DependencyGap('New source orders must extend the selected contiguous ordinal range') from error
                        order += 1
                low, high = db.execute('SELECT min(ordinal),max(ordinal) FROM new_positions').fetchone()
                if low is not None and (low != basis['next_source_order'] or high != order - 1):
                    raise DependencyGap('New source orders must extend the selected contiguous ordinal range')
                source_rows = work.mapping('source_rows')
                for identity in scope.before:
                    db.executemany('INSERT INTO old_edges VALUES (?,?)',
                        ((_encoded_alias(alias), identity) for alias in selected.aliases(identity)))
                for identity, row in scope.after.items():
                    position = (selected.order(identity) if identity in scope.before else
                        db.execute('SELECT ordinal FROM new_positions WHERE identity=?', (identity,)).fetchone()[0])
                    if source_orders is not None and source_orders[identity] != position:
                        raise DependencyGap('Existing source order changed during candidate preparation')
                    table, _ = dependency_tables([row], self.source_schema, first_order=position)
                    stored = table.to_pylist()[0]
                    source_rows[identity] = stored
                    db.executemany('INSERT INTO new_edges VALUES (?,?)',
                                   ((alias, identity) for alias in stored['aliases']))
                source_root = self._replace_rows(basis['source_root'], self.sources,
                    key='source_id', schema=dependency_schema(self.source_schema), replacements=source_rows,
                    deletions=(identity for identity in scope.before if identity not in scope.after),
                    kind='sources', basis=basis)
                from itertools import zip_longest
                for alias, in db.execute('SELECT alias FROM old_edges UNION SELECT alias FROM new_edges ORDER BY alias'):
                    old_members = (row[0] for row in db.execute('SELECT member FROM old_edges WHERE alias=? ORDER BY member', (alias,)))
                    if any(old != actual for old, actual in zip_longest(old_members, selected.members(_decoded_alias(alias)))):
                        raise DependencyGap('Affected reverse dependency scope is incomplete')
                    if (db.execute('SELECT member FROM old_edges WHERE alias=? EXCEPT SELECT member FROM new_edges WHERE alias=? LIMIT 1', (alias, alias)).fetchone()
                            or db.execute('SELECT member FROM new_edges WHERE alias=? EXCEPT SELECT member FROM old_edges WHERE alias=? LIMIT 1', (alias, alias)).fetchone()):
                        db.execute('INSERT INTO changed_aliases VALUES (?)', (alias,))
                class AliasChanges:
                    def __iter__(self):
                        return (row[0] for row in db.execute('SELECT alias FROM changed_aliases ORDER BY alias'))
                    def __getitem__(self, alias):
                        return (row[0] for row in db.execute('SELECT member FROM new_edges WHERE alias=? ORDER BY member', (alias,)))
                alias_root = self.memberships.replace(basis['alias_root'], AliasChanges())
                lookups = self._prepare_lookups(basis, scope.before, scope.after)
                return {**basis, **lookups, 'source_root': source_root, 'alias_root': alias_root, 'next_source_order': order}
            finally:
                scope.close()
                selected.close()
