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
    DependencyGap, NativeCatalogDependencies, _encoded_alias, _decoded_alias,
)
from .partition_routing import RoutingPages, split_partition
from .catalog_memberships import CatalogMemberships
from .source_aliases import resolution_candidates



class CatalogDependencyStorage:
    """Prepare exact keyed source/alias state; preserve unaffected native pins."""
    def __init__(self, *, native, store, namespace, source_schema, max_rows, max_bytes):
        if type(max_rows) is not int or max_rows < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Catalog dependency partition budgets must be positive integers')
        self.native, self.source_schema, self.namespace = native, source_schema, namespace
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.sources = RoutingPages(store, namespace + '-sources')
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
        from . import source_aliases
        self.lookup_requirements = sha256(Path(source_aliases.__file__).read_bytes()).hexdigest()
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
            return dict(format='catalog-dependencies-v2', namespace=self.namespace, ownership_edges='document-id-v1', schema_hash=self.schema_hash,
                        max_rows=self.max_rows, max_arrow_bytes=self.max_bytes,
                        source_root=None, alias_root=None, url_root=None, target_root=None, body_root=None, lookup_schema='url-resolution-body-v1',
                        lookup_requirements=self.lookup_requirements, source_schema=base64.b64encode(self.schema_bytes).decode(), next_source_order=0)
        if (selection.get('format') != 'catalog-dependencies-v2'
                or selection.get('namespace') != self.namespace
                or selection.get('ownership_edges') != 'document-id-v1'
                or selection.get('schema_hash') != self.schema_hash
                or selection.get('source_schema') != base64.b64encode(self.schema_bytes).decode()
                or selection.get('max_rows') != self.max_rows
                or selection.get('max_arrow_bytes') != self.max_bytes
                or type(selection.get('next_source_order')) is not int
                or selection['next_source_order'] < 0):
            raise DependencyGap('Catalog dependency selection schema or order basis differs')
        if require_lookup_policy and (selection.get('lookup_requirements') != self.lookup_requirements
                or selection.get('lookup_schema') != 'url-resolution-body-v1'):
            raise DependencyGap('Catalog URL lookup policy changed; qualify an explicit lookup adoption')
        return deepcopy(selection)

    def _read(self, pin, schema):
        with self.native.source_batches(pin, schema=schema) as reader:
            if not reader.schema.equals(schema, check_metadata=False):
                raise DependencyGap('Native dependency leaf schema differs')
            batches = []
            rows = size = 0
            for batch in reader:
                rows += len(batch)
                size += batch.nbytes
                if rows > self.max_rows or size > self.max_bytes:
                    raise DependencyGap('Selected dependency leaf exceeds its row or byte budget')
                batches.append(batch)
            self.rows_read += rows
            self.bytes_read += size
            return pa.Table.from_batches(batches, schema=reader.schema).cast(schema)

    def _write(self, table, kind):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        identity = sha256(sink.getvalue().to_pybytes()).hexdigest()
        pin = self.native.run_table(table, dataset=f'catalog-dep-v2-{kind}-{identity}',
                                   operation='initial', definition='catalog-dependencies-storage-v2')
        self.candidate_rows_submitted += len(table)
        self.candidate_arrow_bytes += table.nbytes
        return pin

    def _replace_rows(self, root, pages, *, key, schema, replacements, deletions, kind):
        changes = {}
        for identity in sorted(set(replacements) | set(deletions)):
            prefix, pin = pages.lookup(root, identity)
            changes.setdefault(prefix, (pin, []))[1].append(identity)
        for prefix, (pin, identities) in sorted(changes.items()):
            existing = self._read(pin, schema).to_pylist() if pin is not None else []
            rows = {row[key]: row for row in existing}
            if len(rows) != len(existing):
                raise DependencyGap('Duplicate keyed catalog dependency rows')
            old = deepcopy(rows)
            for identity in identities:
                rows.pop(identity, None)
                if identity in replacements:
                    rows[identity] = replacements[identity]
            if rows == old:
                continue
            table = pa.Table.from_pylist([rows[identity] for identity in sorted(rows)], schema=schema)
            leaves = {}
            for child, part in split_partition(table, key=key, prefix=prefix,
                    max_rows=self.max_rows, max_bytes=self.max_bytes):
                leaves[child] = self._write(part, kind) if len(part) else None
            root = pages.replace(root, prefix, leaves)
        return root

    def selected(self, selection):
        basis = self._selection(selection)
        member_counts, pin_counts = {}, {}

        def source_pin(key):
            return self.sources.lookup(basis['source_root'], key)[1]

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
            pins = [pin for _, pin in self.members.leaf_items(leaf['root'])]
            if not pins:
                raise DependencyGap('Missing reverse dependency member partitions')
            return pins

        return NativeCatalogDependencies(native=self.native, source_schema=self.source_schema,
            locate_source=source_pin, locate_alias=alias_pins, expected_members=member_counts.__getitem__,
            expected_rows=lambda pin: pin_counts.get(index.compact(pin)),
            max_rows=self.max_rows, max_bytes=self.max_bytes)

    @staticmethod
    def _lookup_keys(row):
        url = row.get('source_url')
        urls = {'url:' + url} if isinstance(url, str) and url else set()
        targets = {'target:' + index.compact(target) for target in resolution_candidates(row)}
        bodies = {'body:' + row['body_key']} if row.get('body_key') else set()
        return urls, targets, bodies

    def _prepare_lookups(self, basis, before, after):
        # Membership owners are source IDs, so removing one version cannot
        # erase another version's URL or recorded resolution evidence.
        with TemporaryDirectory(prefix='catalog-url-changes-') as directory, closing(
                sqlite3.connect(Path(directory) / 'changes.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE changes(kind INTEGER,alias TEXT,source TEXT,old INTEGER,new INTEGER, '
                'PRIMARY KEY(kind,alias,source)); '
                'CREATE TABLE members(kind INTEGER,alias TEXT,source TEXT,PRIMARY KEY(kind,alias,source));')
            for identity in set(before) | set(after):
                old = self._lookup_keys(before[identity]) if identity in before else (set(), set(), set())
                new = self._lookup_keys(after[identity]) if identity in after else (set(), set(), set())
                for kind in (0, 1, 2):
                    for alias in old[kind] ^ new[kind]:
                        db.execute('INSERT INTO changes VALUES (?,?,?,?,?)',
                                   (kind, alias, identity, int(alias in old[kind]), int(alias in new[kind])))
            roots = []
            for kind, owner, label in [(0, self.urls, 'url_root'), (1, self.targets, 'target_root'), (2, self.bodies, 'body_root')]:
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
            return dict(url_root=roots[0], target_root=roots[1], body_root=roots[2])

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

    def adopt(self, chunks):
        """Import exact selected source values without replaying grouping policy.

        Adoption enumerates the prior table once. Temporary hash indexes bound
        native leaf construction even when a whole historical component shares
        one body or endpoint. This path never selects the resulting roots.
        """
        from .partition_routing import key_hash
        with TemporaryDirectory(prefix='catalog-dependency-adoption-') as directory, closing(
                sqlite3.connect(Path(directory) / 'sources.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE sources(identity TEXT PRIMARY KEY,digest TEXT,body BLOB); '
                'CREATE INDEX source_hashes ON sources(digest); '
                'CREATE TABLE aliases(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
                'CREATE TABLE lookups(kind INTEGER,alias TEXT,member TEXT,PRIMARY KEY(kind,alias,member));')
            count = 0
            for chunk in chunks:
                if not chunk.schema.equals(self.source_schema, check_metadata=True):
                    raise DependencyGap('Adoption source schema differs from the selected table')
                for row in chunk.to_pylist():
                    identity = index.source_identity(row)
                    if row.get('source_id') != identity:
                        raise DependencyGap('Adoption source identity differs from its saved key')
                    sources, aliases = dependency_tables([row], self.source_schema, first_order=count)
                    try:
                        db.execute('INSERT INTO sources VALUES (?,?,?)',
                            (identity, key_hash(identity), pickle.dumps(sources.to_pylist()[0])))
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
                if len(table) <= self.max_rows and table.nbytes <= self.max_bytes:
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
            for kind, owner in [(0, self.urls), (1, self.targets), (2, self.bodies)]:
                class Lookups:
                    def __iter__(self):
                        return (row[0] for row in db.execute('SELECT DISTINCT alias FROM lookups WHERE kind=? ORDER BY alias', (kind,)))
                    def __getitem__(self, alias):
                        return (row[0] for row in db.execute('SELECT member FROM lookups WHERE kind=? AND alias=? ORDER BY member', (kind, alias)))
                lookup_roots.append(owner.replace(None, Lookups()))
            return dict(self._selection(None), source_root=source_root, alias_root=alias_root,
                        url_root=lookup_roots[0], target_root=lookup_roots[1], body_root=lookup_roots[2], next_source_order=count)

    def prepare(self, selection, *, replacements=(), deletions=(), source_orders=None):
        """Prepare complete changed scope; the caller later CAS-selects roots.

        The returned metadata may be discarded after a competing writer wins.
        Native candidate datasets are immutable content-named Runs, so a losing
        attempt cannot strand a mutable native head ahead of selected app state.
        """
        basis = self._selection(selection, require_lookup_policy=True)
        replacements, deletions = list(replacements), tuple(deletions)
        if not replacements and not deletions:
            return basis
        selected = self.selected(basis)
        scope = affected_sources(selected, replacements=replacements, deletions=deletions)
        order = basis['next_source_order']
        new_positions = {}
        for row in replacements:
            key = index.source_identity(row)
            if key not in scope.before:
                new_positions[key] = source_orders[key] if source_orders is not None else order
                order += 1
        if set(new_positions.values()) != set(range(basis['next_source_order'], order)):
            raise DependencyGap('New source orders must extend the selected contiguous ordinal range')
        source_rows, old_aliases, new_aliases = {}, {}, {}
        for key in sorted(scope.before):
            for alias in selected.aliases(key):
                old_aliases.setdefault(_encoded_alias(alias), set()).add(key)
        for key, row in sorted(scope.after.items()):
            position = selected.order(key) if key in scope.before else new_positions[key]
            if source_orders is not None and source_orders[key] != position:
                raise DependencyGap('Existing source order changed during candidate preparation')
            table, _ = dependency_tables([row], self.source_schema, first_order=position)
            source_rows[key] = table.to_pylist()[0]
            for alias in source_rows[key]['aliases']:
                new_aliases.setdefault(alias, set()).add(key)
        source_root = self._replace_rows(basis['source_root'], self.sources,
            key='source_id', schema=dependency_schema(self.source_schema), replacements=source_rows,
            deletions=set(scope.before) - set(scope.after), kind='sources')
        alias_changes = {}
        for alias in sorted(old_aliases.keys() | new_aliases.keys()):
            old_members, new_members = old_aliases.get(alias, set()), new_aliases.get(alias, set())
            if set(selected.members(_decoded_alias(alias))) != old_members:
                raise DependencyGap('Affected reverse dependency scope is incomplete')
            if old_members != new_members:
                alias_changes[alias] = new_members
        alias_root = self.memberships.replace(basis['alias_root'], alias_changes)
        lookups = self._prepare_lookups(basis, scope.before, scope.after)
        return {**basis, **lookups, 'source_root': source_root, 'alias_root': alias_root, 'next_source_order': order}
