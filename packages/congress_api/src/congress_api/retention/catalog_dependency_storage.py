"""Immutable catalog dependency leaves selected through shared routing pages.

DocSpec owns each bounded typed leaf. The application's coherent catalog selector
owns the returned roots; preparing a candidate never selects it for readers.
"""
from copy import deepcopy
from hashlib import sha256
import json

import pyarrow as pa

from . import document_index as index
from .catalog_dependencies import (
    affected_sources, alias_schema, dependency_schema, dependency_tables,
    DependencyGap, NativeCatalogDependencies, _encoded_alias, _decoded_alias,
)
from .immutable_metadata import encoded
from .partition_routing import RoutingPages, split_partition

DIRECTORY_SCHEMA = pa.schema([
    pa.field('alias', pa.string(), nullable=False),
    pa.field('members_root', pa.string(), nullable=False),
    pa.field('member_count', pa.int64(), nullable=False),
])


class CatalogDependencyStorage:
    """Prepare exact keyed source/alias state; preserve unaffected native pins."""
    def __init__(self, *, native, store, namespace, source_schema, max_rows, max_bytes):
        if type(max_rows) is not int or max_rows < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Catalog dependency partition budgets must be positive integers')
        self.native, self.source_schema = native, source_schema
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.sources = RoutingPages(store, namespace + '-sources')
        self.aliases = RoutingPages(store, namespace + '-aliases')
        self.members = RoutingPages(store, namespace + '-members')
        self.schema_hash = sha256(source_schema.remove_metadata().serialize().to_pybytes()).hexdigest()
        self.rows_read = self.bytes_read = 0
        self.candidate_rows_submitted = self.candidate_arrow_bytes = 0

    def _selection(self, selection):
        if selection is None:
            return dict(format='catalog-dependencies-v1', schema_hash=self.schema_hash,
                        max_rows=self.max_rows, max_arrow_bytes=self.max_bytes,
                        source_root=None, alias_root=None, next_source_order=0)
        if (selection.get('format') != 'catalog-dependencies-v1'
                or selection.get('schema_hash') != self.schema_hash
                or selection.get('max_rows') != self.max_rows
                or selection.get('max_arrow_bytes') != self.max_bytes
                or type(selection.get('next_source_order')) is not int
                or selection['next_source_order'] < 0):
            raise DependencyGap('Catalog dependency selection schema or order basis differs')
        return deepcopy(selection)

    def _read(self, pin, schema):
        with self.native.source_batches(pin) as reader:
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
        pin = self.native.run_table(table, dataset=f'catalog-dep-{kind}-{identity}',
                                   operation='initial', definition='catalog-dependencies-storage-v1')
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
        directory_cache, member_counts = {}, {}

        def source_pin(key):
            return self.sources.lookup(basis['source_root'], key)[1]

        def alias_pins(value):
            _, pin = self.aliases.lookup(basis['alias_root'], value)
            if pin is None:
                member_counts[value] = 0
                return ()
            pin_key = index.compact(pin)
            if pin_key not in directory_cache:
                rows = self._read(pin, DIRECTORY_SCHEMA).to_pylist()
                directory_cache[pin_key] = {row['alias']: row for row in rows}
                if len(directory_cache[pin_key]) != len(rows):
                    raise DependencyGap('Duplicate reverse dependency directory keys')
            row = directory_cache[pin_key].get(value)
            if row is None:
                member_counts[value] = 0
                return ()
            if type(row['member_count']) is not int or row['member_count'] < 1:
                raise DependencyGap('Invalid reverse dependency member count')
            member_counts[value] = row['member_count']
            try:
                root = json.loads(row['members_root'])
            except (TypeError, ValueError) as error:
                raise DependencyGap('Invalid reverse dependency member root') from error
            pins = [pin for _, pin in self.members.leaf_items(root)]
            if not pins:
                raise DependencyGap('Missing reverse dependency member partitions')
            return pins

        return NativeCatalogDependencies(native=self.native, source_schema=self.source_schema,
            locate_source=source_pin, locate_alias=alias_pins,
            expected_members=member_counts.__getitem__, max_rows=self.max_rows, max_bytes=self.max_bytes)

    def prepare(self, selection, *, replacements=(), deletions=()):
        """Prepare complete changed scope; the caller later CAS-selects roots.

        The returned metadata may be discarded after a competing writer wins.
        Native candidate datasets are immutable content-named Runs, so a losing
        attempt cannot strand a mutable native head ahead of selected app state.
        """
        basis = self._selection(selection)
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
                new_positions[key] = order
                order += 1
        source_rows, old_aliases, new_aliases = {}, {}, {}
        for key in sorted(scope.before):
            for alias in selected.aliases(key):
                old_aliases.setdefault(_encoded_alias(alias), set()).add(key)
        for key, row in sorted(scope.after.items()):
            position = selected.order(key) if key in scope.before else new_positions[key]
            table, _ = dependency_tables([row], self.source_schema, first_order=position)
            source_rows[key] = table.to_pylist()[0]
            for alias in index.group_aliases(row, key):
                new_aliases.setdefault(_encoded_alias(alias), set()).add(key)
        source_root = self._replace_rows(basis['source_root'], self.sources,
            key='source_id', schema=dependency_schema(self.source_schema), replacements=source_rows,
            deletions=set(scope.before) - set(scope.after), kind='sources')
        directories, removed_aliases = {}, set()
        for alias in sorted(old_aliases.keys() | new_aliases.keys()):
            old_members, new_members = old_aliases.get(alias, set()), new_aliases.get(alias, set())
            if set(selected.members(_decoded_alias(alias))) != old_members:
                raise DependencyGap('Affected reverse dependency scope is incomplete')
            if old_members == new_members:
                continue
            if not new_members:
                removed_aliases.add(alias)
                continue
            table = pa.Table.from_pylist([dict(alias=alias, source_id=key)
                for key in sorted(new_members)], schema=alias_schema())
            leaves = {prefix: self._write(part, 'members') if len(part) else None
                for prefix, part in split_partition(table, key='source_id', prefix='',
                    max_rows=self.max_rows, max_bytes=self.max_bytes)}
            root = self.members.replace(None, '', leaves)
            directories[alias] = dict(alias=alias, members_root=encoded(root).decode(),
                                      member_count=len(new_members))
        alias_root = self._replace_rows(basis['alias_root'], self.aliases,
            key='alias', schema=DIRECTORY_SCHEMA, replacements=directories,
            deletions=removed_aliases, kind='aliases')
        return {**basis, 'source_root': source_root, 'alias_root': alias_root, 'next_source_order': order}
