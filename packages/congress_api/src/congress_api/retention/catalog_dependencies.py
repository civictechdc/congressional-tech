"""Close a selected catalog's old/new endpoint/body dependency scope.

The selected dependency owner supplies exact keyed source and alias membership
lookups. This module never enumerates the corpus or falls back to old table scans.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass

from . import document_index as index


class DependencyGap(ValueError):
    """The selected lookup cannot establish a complete affected component."""


@dataclass
class AffectedSources:
    before: dict
    after: dict
    sources_read: int
    aliases_read: int


def affected_sources(selected, *, replacements=(), deletions=()):
    """Return complete old components and new neighbors for explicit row edits.

    Replacements are complete interpreted source inputs. A changed identity is
    represented by deleting the old ID and adding the new row. Missing aliases
    mean an empty membership only when the selected owner proves that absence.
    Unknown routing or missing partitions must raise from that owner.
    """
    replacements = list(replacements)
    changed = {index.source_identity(row): deepcopy(row) for row in replacements}
    removed = set(deletions)
    if len(changed) != len(replacements):
        raise ValueError('Duplicate replacement source identity')
    if removed & changed.keys():
        raise ValueError('Replacement and deletion source IDs overlap')
    pending = deque(sorted(removed | changed.keys()))
    queued = set(pending)
    before, after, aliases = {}, {}, {}
    reads = 0
    while pending:
        key = pending.popleft()
        previous = selected.source(key)
        reads += 1
        if previous is None and key not in changed:
            reason = 'Missing changed source' if key in removed else 'Missing dependency source'
            raise DependencyGap(f'{reason}: {key}')
        if previous is not None:
            if index.source_identity(previous) != key:
                raise DependencyGap(f'Dependency source identity mismatch: {key}')
            before[key] = previous
        current = None if key in removed else changed.get(key, previous)
        if current is not None:
            after[key] = deepcopy(current)
        old_aliases = tuple(selected.aliases(key)) if previous is not None else ()
        new_aliases = index.group_aliases(current, key) if current is not None else ()
        for alias in dict.fromkeys((*old_aliases, *new_aliases)):
            if alias not in aliases:
                aliases[alias] = set(selected.members(alias))
            members = aliases[alias]
            # Old aliases are stored values, so explicit upgrades can change
            # the current policy without losing the selected old components.
            if alias in old_aliases and key not in members:
                raise DependencyGap(f'Missing reverse dependency membership: {key} {alias}')
            for member in sorted(members):
                if member not in queued:
                    queued.add(member)
                    pending.append(member)
    return AffectedSources(before, after, reads, len(aliases))


def _encoded_alias(alias):
    return index.compact(alias)


def _decoded_alias(value):
    import json
    kind, key = json.loads(value)
    if kind == 'endpoint' and isinstance(key, list) and len(key) == 2:
        result = kind, tuple(key)
        hash(result)
        return result
    if kind in {'body', 'component'} and isinstance(key, str) and key:
        return kind, key
    raise ValueError('Invalid group alias')


def dependency_schema(source_schema):
    """Store source values and old policy edges as typed application data."""
    import pyarrow as pa
    return pa.schema([
        pa.field('source_id', pa.string(), nullable=False),
        pa.field('source_order', pa.int64(), nullable=False),
        pa.field('source_values', pa.struct(list(source_schema)), nullable=False),
        pa.field('aliases', pa.list_(pa.string()), nullable=False),
    ])


def alias_schema():
    import pyarrow as pa
    return pa.schema([pa.field('alias', pa.string(), nullable=False),
                      pa.field('source_id', pa.string(), nullable=False)])


def dependency_tables(rows, source_schema, *, first_order=0):
    """Prepare one bounded source leaf and its exact reverse dependency rows.

    The caller retains partition routing and writes candidate-specific native
    Runs. These tables do not choose a new application snapshot.
    """
    import pyarrow as pa
    if type(first_order) is not int or first_order < 0:
        raise ValueError('Source order must start at a nonnegative integer')
    sources, aliases, seen = [], [], set()
    for order, original in enumerate(rows, first_order):
        row = deepcopy(original)
        if set(row) - set(source_schema.names):
            raise ValueError('Source row fields are not declared in the application schema')
        key = index.source_identity(row)
        if key in seen:
            raise ValueError(f'Duplicate dependency source identity: {key}')
        seen.add(key)
        aliases_for_row = list(index.group_aliases(row, key))
        if row.get('document_id'):
            aliases_for_row.append(('component', row['document_id']))
        encoded = [_encoded_alias(alias) for alias in aliases_for_row]
        sources.append(dict(source_id=key, source_order=order, source_values=row, aliases=encoded))
        aliases.extend(dict(alias=value, source_id=key) for value in encoded)
    return (pa.Table.from_pylist(sources, schema=dependency_schema(source_schema)),
            pa.Table.from_pylist(aliases, schema=alias_schema()))


class NativeCatalogDependencies:
    """Read only routed exact dependency partitions selected by the application.

    locate_source(source_id) returns one selected bounded leaf pin or None for
    proved absence. locate_alias(encoded_alias) returns the selected member-page
    pins, possibly empty for proved absence. Unknown routing must raise, rather
    than returning absence. source_leaf_schema resolves the exact physical app
    schema when a routing value wraps a release pin and shared schema reference.
    This reader owns no latest pointer or routing engine.
    """
    def __init__(self, *, native, source_schema, locate_source, locate_alias, expected_members=None, expected_rows=None, max_rows=None, max_bytes=None, source_leaf_schema=None):
        self.native = native
        self.source_schema = source_schema
        self.locate_source = locate_source
        self.source_leaf_schema = source_leaf_schema
        self.locate_alias = locate_alias
        self.expected_members = expected_members
        self.expected_rows = expected_rows
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.native_rows_read = self.native_bytes_read = 0
        self._sources, self._aliases = {}, {}
        self._source_pins, self._alias_pins = set(), set()

    def _rows(self, pin, schema):
        count = size = 0
        with self.native.source_batches(deepcopy(pin), schema=schema) as reader:
            if not reader.schema.equals(schema, check_metadata=False):
                raise DependencyGap('Native dependency schema differs from selected application schema')
            for batch in reader:
                if not batch.schema.equals(schema, check_metadata=False):
                    raise DependencyGap('Native dependency batch schema differs')
                count += len(batch)
                size += batch.nbytes
                if ((self.max_rows is not None and count > self.max_rows)
                        or (self.max_bytes is not None and size > self.max_bytes)):
                    raise DependencyGap('Selected dependency partition exceeds its row or byte budget')
                self.native_rows_read += len(batch)
                self.native_bytes_read += batch.nbytes
                yield from batch.to_pylist()
        expected = self.expected_rows(pin) if self.expected_rows is not None else None
        if expected is not None and count != expected:
            raise DependencyGap('Reverse dependency leaf row count differs')

    def _load_source(self, key):
        pin = self.locate_source(key)
        if pin is None:
            return
        pin_key = index.compact(pin)
        if pin_key in self._source_pins:
            return
        pending = {}
        physical = self.source_leaf_schema(pin) if self.source_leaf_schema is not None else self.source_schema
        release = pin['release'] if self.source_leaf_schema is not None else pin
        for row in self._rows(release, dependency_schema(physical)):
            if not physical.equals(self.source_schema, check_metadata=False):
                import pyarrow as pa
                row['source_values'] = pa.scalar(row['source_values'], type=pa.struct(list(self.source_schema))).as_py()
            identity = row['source_id']
            if (identity is None or not isinstance(row['source_values'], dict)
                    or index.source_identity(row['source_values']) != identity
                    or identity in pending or identity in self._sources
                    or type(row['source_order']) is not int or row['source_order'] < 0
                    or not row['aliases'] or len(set(row['aliases'])) != len(row['aliases'])):
                raise DependencyGap('Invalid or repeated native dependency source')
            # Decode now so invalid persisted edges fail before any closure can
            # report success. Old aliases deliberately need not match new rules.
            try:
                for value in row['aliases']:
                    alias = _decoded_alias(value)
                    if alias[0] not in {'body', 'endpoint', 'component'} or _encoded_alias(alias) != value:
                        raise ValueError('Invalid group alias')
            except (ValueError, TypeError) as error:
                raise DependencyGap('Invalid stored dependency alias') from error
            pending[identity] = row
        self._sources.update(pending)
        self._source_pins.add(pin_key)

    def source(self, key):
        if key not in self._sources:
            self._load_source(key)
        stored = self._sources.get(key)
        return deepcopy(stored['source_values']) if stored is not None else None

    def aliases(self, key):
        if key not in self._sources:
            self._load_source(key)
        if key not in self._sources:
            raise DependencyGap(f'Missing source aliases: {key}')
        return tuple(_decoded_alias(value) for value in self._sources[key]['aliases'])

    def order(self, key):
        if key not in self._sources:
            self._load_source(key)
        if key not in self._sources:
            raise DependencyGap(f'Missing source order: {key}')
        return self._sources[key]['source_order']

    def members(self, alias):
        encoded = _encoded_alias(alias)
        for pin in self.locate_alias(encoded):
            pin_key = index.compact(pin)
            if pin_key in self._alias_pins:
                continue
            pending = {}
            for row in self._rows(pin, alias_schema()):
                value, key = row['alias'], row['source_id']
                members = pending.setdefault(value, set())
                if (not value or not key or key in members
                        or key in self._aliases.get(value, ())):
                    raise DependencyGap('Invalid or repeated reverse dependency membership')
                members.add(key)
            for value, members in pending.items():
                self._aliases.setdefault(value, set()).update(members)
            self._alias_pins.add(pin_key)
        result = tuple(sorted(self._aliases.get(encoded, ())))
        expected = self.expected_members(encoded) if self.expected_members is not None else None
        if expected is not None and len(result) != expected:
            raise DependencyGap('Reverse dependency member count differs from selected directory')
        return result
