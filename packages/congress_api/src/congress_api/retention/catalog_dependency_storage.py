"""Immutable catalog dependency leaves selected through shared routing pages.

DocSpec owns each bounded typed leaf. The application's coherent catalog selector
owns the returned roots; preparing a candidate never selects it for readers.
"""
from copy import deepcopy
from hashlib import sha256

import pyarrow as pa

from . import document_index as index
from .catalog_dependencies import (
    affected_sources, alias_schema, dependency_schema, dependency_tables,
    DependencyGap, NativeCatalogDependencies, _encoded_alias, _decoded_alias,
)
from .partition_routing import RoutingPages, split_partition, key_hash



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
            return dict(format='catalog-dependencies-v2', schema_hash=self.schema_hash,
                        max_rows=self.max_rows, max_arrow_bytes=self.max_bytes,
                        source_root=None, alias_root=None, next_source_order=0)
        if (selection.get('format') != 'catalog-dependencies-v2'
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

    def _alias_groups(self, value):
        if value is None:
            return {}
        if value.get('kind') == 'members':
            if (not isinstance(value.get('alias'), str) or type(value.get('count')) is not int
                    or value['count'] < 1 or value.get('root') is None):
                raise DependencyGap('Invalid large-alias dependency metadata')
            return {value['alias']: value}
        if value.get('kind') != 'rows':
            raise DependencyGap('Unknown alias dependency leaf format')
        table = self._read(value['release'], alias_schema())
        if len(table) != value.get('rows'):
            raise DependencyGap('Alias dependency leaf row count differs')
        groups, seen = {}, set()
        for row in table.to_pylist():
            pair = row['alias'], row['source_id']
            if pair in seen:
                raise DependencyGap('Duplicate reverse dependency membership')
            seen.add(pair)
            _decoded_alias(row['alias'])
            groups.setdefault(row['alias'], []).append(row)
        return {alias: pa.Table.from_pylist(rows, schema=alias_schema()) for alias, rows in groups.items()}

    def _alias_leaves(self, groups, prefix):
        # Common aliases share physical native leaves. Only one alias whose
        # members exceed a leaf budget gets secondary source-ID routing.
        groups = dict(groups)
        for alias, value in groups.items():
            if isinstance(value, pa.Table) and (len(value) > self.max_rows or value.nbytes > self.max_bytes):
                leaves = {child: self._write(part, 'members') if len(part) else None
                    for child, part in split_partition(value, key='source_id', prefix='',
                        max_rows=self.max_rows, max_bytes=self.max_bytes)}
                groups[alias] = dict(kind='members', alias=alias, count=len(value),
                                     root=self.members.replace(None, '', leaves))
        if not groups:
            return {prefix: None}
        heavy = {alias: value for alias, value in groups.items() if not isinstance(value, pa.Table)}
        if heavy:
            if len(groups) == 1:
                return {prefix: next(iter(heavy.values()))}
            if len(prefix) == 64:
                raise DependencyGap('Alias hash collision cannot fit the dependency budget')
            leaves = {}
            for char in '0123456789abcdef':
                child = prefix + char
                subset = {alias: value for alias, value in groups.items() if key_hash(alias).startswith(child)}
                if subset:
                    leaves.update(self._alias_leaves(subset, child))
            return leaves
        table = pa.concat_tables([groups[alias] for alias in sorted(groups)])
        leaves = {}
        for child, part in split_partition(table, key='alias', prefix=prefix,
                max_rows=self.max_rows, max_bytes=self.max_bytes, allow_duplicate_keys=True):
            leaves[child] = (dict(kind='rows', release=self._write(part, 'aliases'),
                                 rows=len(part), arrow_bytes=part.nbytes) if len(part) else None)
        return leaves

    def _replace_aliases(self, root, replacements):
        changes = {}
        for alias in sorted(replacements):
            prefix, value = self.aliases.lookup(root, alias)
            changes.setdefault(prefix, (value, []))[1].append(alias)
        for prefix, (value, aliases) in sorted(changes.items()):
            groups = self._alias_groups(value)
            for alias in aliases:
                members = replacements[alias]
                if members:
                    groups[alias] = pa.Table.from_pylist([dict(alias=alias, source_id=key)
                        for key in sorted(members)], schema=alias_schema())
                else:
                    groups.pop(alias, None)
            root = self.aliases.replace(root, prefix, self._alias_leaves(groups, prefix))
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
        alias_changes = {}
        for alias in sorted(old_aliases.keys() | new_aliases.keys()):
            old_members, new_members = old_aliases.get(alias, set()), new_aliases.get(alias, set())
            if set(selected.members(_decoded_alias(alias))) != old_members:
                raise DependencyGap('Affected reverse dependency scope is incomplete')
            if old_members != new_members:
                alias_changes[alias] = new_members
        alias_root = self._replace_aliases(basis['alias_root'], alias_changes)
        return {**basis, 'source_root': source_root, 'alias_root': alias_root, 'next_source_order': order}
