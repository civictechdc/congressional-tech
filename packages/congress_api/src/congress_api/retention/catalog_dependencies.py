"""Close a selected catalog's old/new endpoint/body dependency scope.

The selected dependency owner supplies exact keyed source and alias membership
lookups. This module never enumerates the corpus or falls back to old table scans.
"""
from copy import deepcopy
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from weakref import finalize
import pickle
import pyarrow as pa

from .catalog_staging import WorkingCatalog

from . import document_index as index


class DependencyGap(ValueError):
    """The selected lookup cannot establish a complete affected component."""


class DependencyWorkingSet:
    """Disposable SQL indexes; retained native selections remain authoritative."""
    def __init__(self):
        directory = TemporaryDirectory(prefix='catalog-dependency-work-')
        self.work = WorkingCatalog(Path(directory.name) / 'working.sqlite')
        self._cleanup = finalize(self, self._close, self.work, directory)

    @staticmethod
    def _close(work, directory):
        work.close()
        directory.cleanup()

    def close(self):
        self._cleanup()


@dataclass
class AffectedSources:
    before: object
    after: object
    sources_read: int
    aliases_read: int
    _working: object = None

    def close(self):
        if self._working is not None:
            self._working.close()


def affected_sources(selected, *, replacements=(), deletions=()):
    """Close old/new components with row values and the frontier staged on disk.

    The returned mappings own their disposable working directory. Missing aliases
    mean absence only when the selected owner proves it; missing routing raises.
    Replacements remain complete interpreted rows, with exact typed Python values
    preserved by the existing WorkingCatalog pickle storage policy.
    """
    working = DependencyWorkingSet()
    db = working.work.connection
    before, after = working.work.mapping('before_rows'), working.work.mapping('after_rows')
    # A caller may retain an individual mapping after releasing the scope.
    before.working_owner = after.working_owner = working
    db.executescript('CREATE TABLE changes(identity TEXT PRIMARY KEY,value BLOB); '
        'CREATE TABLE removed(identity TEXT PRIMARY KEY); '
        'CREATE TABLE frontier(position INTEGER PRIMARY KEY,identity TEXT UNIQUE,processed INTEGER DEFAULT 0); '
        'CREATE INDEX frontier_pending ON frontier(processed,position); '
        'CREATE TABLE aliases(alias TEXT PRIMARY KEY); '
        'CREATE TABLE edges(alias TEXT,identity TEXT,PRIMARY KEY(alias,identity));')
    try:
        for row in replacements:
            key = index.source_identity(row)
            if db.execute('SELECT 1 FROM changes WHERE identity=?', (key,)).fetchone():
                raise ValueError('Duplicate replacement source identity')
            db.execute('INSERT INTO changes VALUES (?,?)', (key, pickle.dumps(row)))
        db.executemany('INSERT OR IGNORE INTO removed VALUES (?)', ((key,) for key in deletions))
        if db.execute('SELECT 1 FROM changes JOIN removed USING(identity) LIMIT 1').fetchone():
            raise ValueError('Replacement and deletion source IDs overlap')
        db.execute('INSERT INTO frontier(identity) SELECT identity FROM changes UNION '
                   'SELECT identity FROM removed ORDER BY identity')
        reads = 0
        while entry := db.execute('SELECT position,identity FROM frontier WHERE processed=0 ORDER BY position LIMIT 1').fetchone():
            position, key = entry
            previous = selected.source(key)
            reads += 1
            changed = db.execute('SELECT value FROM changes WHERE identity=?', (key,)).fetchone()
            removed = db.execute('SELECT 1 FROM removed WHERE identity=?', (key,)).fetchone() is not None
            if previous is None and changed is None:
                reason = 'Missing changed source' if removed else 'Missing dependency source'
                raise DependencyGap(f'{reason}: {key}')
            if previous is not None:
                if index.source_identity(previous) != key:
                    raise DependencyGap(f'Dependency source identity mismatch: {key}')
                before[key] = previous
            current = None if removed else pickle.loads(changed[0]) if changed is not None else previous
            if current is not None:
                after[key] = current
            old_aliases = tuple(selected.aliases(key)) if previous is not None else ()
            new_aliases = index.group_aliases(current, key) if current is not None else ()
            for alias in dict.fromkeys((*old_aliases, *new_aliases)):
                encoded = _encoded_alias(alias)
                if db.execute('INSERT OR IGNORE INTO aliases VALUES (?)', (encoded,)).rowcount:
                    db.executemany('INSERT OR IGNORE INTO edges VALUES (?,?)',
                                   ((encoded, member) for member in selected.members(alias)))
                    db.execute('INSERT OR IGNORE INTO frontier(identity) SELECT identity FROM edges WHERE alias=? ORDER BY identity', (encoded,))
                if alias in old_aliases and not db.execute('SELECT 1 FROM edges WHERE alias=? AND identity=?', (encoded, key)).fetchone():
                    raise DependencyGap(f'Missing reverse dependency membership: {key} {alias}')
            db.execute('UPDATE frontier SET processed=1 WHERE position=?', (position,))
        return AffectedSources(before, after, reads,
            db.execute('SELECT count(*) FROM aliases').fetchone()[0], working)
    except BaseException:
        working.close()
        raise


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
    typed = isinstance(rows, pa.Table)
    if typed:
        if not rows.schema.equals(source_schema, check_metadata=True):
            raise ValueError('Dependency source table schema differs')
        # Grouping and lookup use the core values. Keep potentially huge
        # occurrence lists in Arrow rather than round-tripping Python structs.
        from .catalog_rows import core_table, COUNT, ROW
        core = core_table(rows)
        projected = core.drop([name for name in (COUNT, ROW) if name in core.column_names])
        originals = projected.to_pylist()
    else:
        originals = rows
    sources, aliases, seen, keys, positions, edges = [], [], set(), [], [], []
    for order, original in enumerate(originals, first_order):
        row = original if typed else deepcopy(original)
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
        if typed:
            keys.append(key)
            positions.append(order)
            edges.append(encoded)
        else:
            sources.append(dict(source_id=key, source_order=order, source_values=row, aliases=encoded))
        aliases.extend(dict(alias=value, source_id=key) for value in encoded)
    if typed:
        sources = pa.Table.from_arrays([
            pa.array(keys, type=pa.string()), pa.array(positions, type=pa.int64()),
            pa.StructArray.from_arrays([rows[name].combine_chunks() for name in source_schema.names],
                                       fields=list(source_schema)),
            pa.array(edges, type=pa.list_(pa.string())),
        ], schema=dependency_schema(source_schema))
    else:
        sources = pa.Table.from_pylist(sources, schema=dependency_schema(source_schema))
    return sources, pa.Table.from_pylist(aliases, schema=alias_schema())


class NativeAliasMembers(Collection):
    """Ordered membership view; keep its disposable SQL owner alive."""
    def __init__(self, working, alias):
        self.working, self.alias = working, alias

    def __iter__(self):
        return (row[0] for row in self.working.work.connection.execute(
            'SELECT identity FROM native_aliases WHERE alias=? ORDER BY identity', (self.alias,)))

    def __len__(self):
        return self.working.work.connection.execute(
            'SELECT count(*) FROM native_aliases WHERE alias=?', (self.alias,)).fetchone()[0]

    def __contains__(self, key):
        return self.working.work.connection.execute(
            'SELECT 1 FROM native_aliases WHERE alias=? AND identity=?', (self.alias, key)).fetchone() is not None


class NativeCatalogDependencies:
    """Read only routed exact dependency partitions selected by the application.

    locate_source(source_id) returns one selected bounded leaf pin or None for
    proved absence. locate_alias(encoded_alias) returns the selected member-page
    pins, possibly empty for proved absence. Unknown routing must raise, rather
    than returning absence. source_leaf_schema resolves the exact physical app
    schema when a routing value wraps a release pin and shared schema reference.
    This reader owns no latest pointer or routing engine.
    """
    def __init__(self, *, native, source_schema, locate_source, locate_alias, expected_members=None, expected_rows=None, max_rows=None, max_bytes=None, source_leaf_schema=None, working=None, row_owner=None):
        self.row_owner = row_owner
        self.native = native
        self.source_schema = source_schema
        self.locate_source = locate_source
        self.source_leaf_schema = source_leaf_schema
        self.locate_alias = locate_alias
        self.expected_members = expected_members
        self.expected_rows = expected_rows
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.native_rows_read = self.native_bytes_read = 0
        self._working = working or DependencyWorkingSet()
        self._sources = self._working.work.mapping('native_sources')
        self._source_pins = self._working.work.mapping('native_source_pins')
        self._alias_pins = self._working.work.mapping('native_alias_pins')
        self._working.work.connection.execute('CREATE TABLE native_aliases(alias TEXT,identity TEXT,PRIMARY KEY(alias,identity))')

    def close(self):
        self._working.close()

    def _rows(self, pin, schema):
        count = size = 0
        from .catalog_rows import core_bytes
        context=(pa.RecordBatchReader.from_batches(schema,self.row_owner.read(deepcopy(pin),schema=schema))
                 if self.row_owner is not None else self.native.source_batches(deepcopy(pin),schema=schema))
        before=(self.row_owner.rows_read,self.row_owner.bytes_read) if self.row_owner is not None else None
        with context as reader:
            if not reader.schema.equals(schema, check_metadata=False):
                raise DependencyGap('Native dependency schema differs from selected application schema')
            for batch in reader:
                if not batch.schema.equals(schema, check_metadata=False):
                    raise DependencyGap('Native dependency batch schema differs')
                count += len(batch)
                size += core_bytes(pa.Table.from_batches([batch]))
                if ((self.max_rows is not None and count > self.max_rows)
                        or (self.max_bytes is not None and size > self.max_bytes)):
                    raise DependencyGap('Selected dependency partition exceeds its row or byte budget')
                if self.row_owner is None:
                    self.native_rows_read += len(batch)
                    self.native_bytes_read += batch.nbytes
                else:
                    self.native_rows_read += self.row_owner.rows_read-before[0]
                    self.native_bytes_read += self.row_owner.bytes_read-before[1]
                    before=(self.row_owner.rows_read,self.row_owner.bytes_read)
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
        self._source_pins[pin_key] = True

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
        db = self._working.work.connection
        for pin in self.locate_alias(encoded):
            pin_key = index.compact(pin)
            if pin_key in self._alias_pins:
                continue
            pending = {}
            for row in self._rows(pin, alias_schema()):
                value, key = row['alias'], row['source_id']
                members = pending.setdefault(value, set())
                if (not value or not key or key in members
                        or db.execute('SELECT 1 FROM native_aliases WHERE alias=? AND identity=?', (value, key)).fetchone()):
                    raise DependencyGap('Invalid or repeated reverse dependency membership')
                members.add(key)
            db.executemany('INSERT INTO native_aliases VALUES (?,?)',
                           ((value, key) for value, members in pending.items() for key in members))
            self._alias_pins[pin_key] = True
        count = db.execute('SELECT count(*) FROM native_aliases WHERE alias=?', (encoded,)).fetchone()[0]
        expected = self.expected_members(encoded) if self.expected_members is not None else None
        if expected is not None and count != expected:
            raise DependencyGap('Reverse dependency member count differs from selected directory')
        return NativeAliasMembers(self._working, encoded)
