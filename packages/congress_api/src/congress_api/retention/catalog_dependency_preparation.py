"""Checked typed preparation for dependency adoption, never a catalog selector.

Parquet files retain exact Arrow values. Disposable SQLite indexes contain only
keys, ordinals and file/row locations and are rebuilt from checked file bytes.
Native Run completion and recovery remain owned by DocSpec.
"""
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from .catalog_dependencies import DependencyGap, dependency_schema, dependency_tables
from .catalog_rows import core_table, fits_chunk
from .derived_files import check_identity, file_identity
from .immutable_metadata import encoded
from .partition_routing import key_hash
from .document_index import source_identity

FORMAT = 'catalog-dependency-preparation-v1'


def _save(path, value):
    body = dict(value)
    body['binding'] = sha256(encoded(body)).hexdigest()
    pending = path.with_suffix('.tmp')
    with pending.open('wb') as stream:
        stream.write(encoded(body))
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return body


def _load(path):
    if path.stat().st_size > 1 << 20:
        raise DependencyGap('Retained dependency preparation receipt exceeds its metadata bound')
    value = json.loads(path.read_bytes())
    binding = value.pop('binding', None)
    if binding != sha256(encoded(value)).hexdigest():
        raise DependencyGap('Retained dependency preparation receipt differs')
    return value


class _BudgetedFile(io.BufferedWriter):
    def __init__(self, path, budget):
        super().__init__(path.open('wb', buffering=0))
        self.budget, self.written = budget, 0

    def write(self, data):
        if self.budget is not None and self.written + len(data) > self.budget:
            raise OSError('Dependency preparation exceeds its staging byte budget')
        size = super().write(data)
        self.written += size
        return size


class DependencyPreparation:
    """Bounded typed files plus rebuilt indexes for one immutable input receipt.

    The caller must bind preparation_key to immutable inputs, their ordering and
    policy. A callable input takes the number of already prepared source rows,
    so an interrupted file scan can skip completed row groups. Iterable callers
    remain supported and skip that prefix without preparing its payload again.
    A completed cache never enumerates the original inputs. Cached native pins
    are deliberately absent: exact content-named Runs replay through DocSpec.
    """
    def __init__(self, owner, *, directory, preparation_key, first_unused_order,
                 source_orders, staging_byte_budget=None, on_progress=None):
        if staging_byte_budget is not None and (type(staging_byte_budget) is not int or staging_byte_budget < 1):
            raise ValueError('Dependency preparation byte budget must be a positive integer')
        if not isinstance(preparation_key, str) or not preparation_key:
            raise ValueError('Retained dependency preparation requires an immutable input key')
        self.owner, self.directory = owner, Path(directory)
        self.source_orders, self.on_progress = source_orders, on_progress
        self.budget, self.cache_bytes = staging_byte_budget, 0
        self.count, self.parts, self.chain, self.next_order = 0, 0, None, first_unused_order
        self.directory.mkdir(parents=True, exist_ok=True)
        # Hash the current metadata-bearing schema, not a construction-time cache.
        self.request = dict(format=FORMAT, preparation_key=preparation_key,
            schema=sha256(owner.source_schema.serialize()).hexdigest(),
            max_rows=owner.max_rows, max_bytes=owner.max_bytes,
            first_unused_order=first_unused_order, saved_orders=source_orders is not None,
            staging_byte_budget=staging_byte_budget)
        request_path = self.directory / 'request.json'
        if request_path.exists():
            if _load(request_path) != self.request:
                raise DependencyGap('Retained dependency preparation inputs, schema or budgets differ')
        else:
            _save(request_path, self.request)
        # Include abandoned partials in capacity accounting. Their absence from
        # the receipt chain prevents them from proving completed preparation.
        self.cache_bytes = sum(path.stat().st_size for path in self.directory.rglob('*') if path.is_file())
        self.index_directory = TemporaryDirectory(prefix='keys-', dir=self.directory)
        self.index_path = Path(self.index_directory.name) / 'keys.sqlite'
        self.db = sqlite3.connect(self.index_path)
        self.db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
            'CREATE TABLE sources(identity TEXT PRIMARY KEY,digest TEXT,part INTEGER,row INTEGER,ordinal INTEGER UNIQUE); '
            'CREATE INDEX source_hashes ON sources(digest); '
            'CREATE TABLE aliases(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
            'CREATE TABLE lookups(kind INTEGER,alias TEXT,member TEXT,PRIMARY KEY(kind,alias,member));')

    def close(self):
        self.db.close()
        self.index_directory.cleanup()

    def _check_budget(self, extra=0):
        size = self.cache_bytes + self.index_path.stat().st_size + extra
        if self.budget is not None and size > self.budget:
            raise OSError('Dependency preparation exceeds its staging byte budget')
        self.owner.preparation_metrics = dict(format=FORMAT, rows=self.count, parts=self.parts,
            retained_bytes=self.cache_bytes, index_bytes=self.index_path.stat().st_size,
            staging_bytes=size)
        return None if self.budget is None else self.budget - size

    def _progress(self, phase):
        self._check_budget()
        if self.on_progress is not None:
            self.on_progress(dict(phase=phase, **self.owner.preparation_metrics))

    def _path(self, number, suffix):
        return self.directory / f'part-{number:08d}.{suffix}'

    def _index(self, table, part):
        # Parquet projection never reads the large occurrence column here.
        values = table.to_pylist()
        try:
            with self.db:
                for offset, row in enumerate(values):
                    identity, position = row['source_id'], row['source_order']
                    if row['source_values'].get('source_id') != identity:
                        raise DependencyGap('Adoption source identity differs from its saved key')
                    if source_identity(row['source_values']) != identity:
                        raise DependencyGap('Adoption source identity differs from its saved key')
                    expected = self.count + offset if self.source_orders is None else self.source_orders[identity]
                    if type(position) is not int or position < 0 or type(expected) is not int or expected != position:
                        raise DependencyGap('Retained dependency preparation source order differs')
                    self.db.execute('INSERT INTO sources VALUES (?,?,?,?,?)',
                        (identity, key_hash(identity), part, offset, position))
                    self.db.executemany('INSERT INTO aliases VALUES (?,?)',
                        ((alias, identity) for alias in row['aliases']))
                    for kind, keys in enumerate(self.owner._lookup_keys(row['source_values'])):
                        self.db.executemany('INSERT OR IGNORE INTO lookups VALUES (?,?,?)',
                            ((kind, key, identity) for key in keys))
                    self.next_order = max(self.next_order, position + 1)
        except sqlite3.IntegrityError as error:
            raise DependencyGap('Repeated selected source identity during adoption') from error

    def _core(self, file):
        fields = [field.name for field in self.owner.source_schema if field.name != 'source_occurrences']
        return file.read(columns=['source_id', 'source_order', 'aliases',
                                  *['source_values.' + name for name in fields]])

    def _restore(self):
        while self._path(self.parts, 'json').exists():
            receipt_path = self._path(self.parts, 'json')
            receipt = _load(receipt_path)
            if (receipt.get('request') != self.request or receipt.get('part') != self.parts
                    or receipt.get('previous') != self.chain or receipt.get('first_row') != self.count):
                raise DependencyGap('Retained dependency preparation part coverage differs')
            path = self._path(self.parts, 'parquet')
            check_identity(file_identity(path), receipt['file'], 'dependency preparation part')
            with pq.ParquetFile(path) as file:
                if (not file.schema_arrow.equals(dependency_schema(self.owner.source_schema), check_metadata=True)
                        or file.metadata.num_rows != receipt['rows']):
                    raise DependencyGap('Retained dependency preparation schema or rows differ')
                self._index(self._core(file), self.parts)
            self.chain = sha256(encoded(receipt)).hexdigest()
            self.count += receipt['rows']
            self.parts += 1
            self._progress('restored')
        complete = self.directory / 'complete.json'
        if complete.exists():
            value = _load(complete)
            if value != dict(request=self.request, parts=self.parts, rows=self.count, chain=self.chain):
                raise DependencyGap('Retained dependency preparation completion differs')
            self._progress('restored')
            return True
        return False

    def _bounded(self, table):
        sources, _ = dependency_tables(table, self.owner.source_schema, first_order=self.count)
        if fits_chunk(sources, max_rows=self.owner.max_rows, max_bytes=self.owner.max_bytes):
            yield sources
        elif len(table) <= 1:
            raise DependencyGap('One selected source cannot fit its adoption leaf budget')
        else:
            middle = len(table) // 2
            yield from self._bounded(table.slice(0, middle))
            yield from self._bounded(table.slice(middle))

    def prepare(self, chunks):
        if self._restore():
            return
        completed = self.count
        stream = chunks(completed) if callable(chunks) else chunks
        skip = 0 if callable(chunks) else completed
        for chunk in stream:
            if not chunk.schema.equals(self.owner.source_schema, check_metadata=True):
                raise DependencyGap('Adoption source schema differs from the selected table')
            if skip:
                take = min(skip, len(chunk))
                chunk, skip = chunk.slice(take), skip - take
            if not len(chunk):
                continue
            # Slice before normalization; an iterable caller may supply many rows.
            for batch in chunk.to_batches(max_chunksize=self.owner.max_rows):
                for table in self._bounded(pa.Table.from_batches([batch])):
                    if self.source_orders is not None:
                        positions = [self.source_orders[key] for key in table['source_id'].to_pylist()]
                        if any(type(value) is not int or value < 0 for value in positions):
                            raise DependencyGap('Source order must be a nonnegative integer')
                        table = table.set_column(1, table.schema.field(1), pa.array(positions, type=pa.int64()))
                    self._index(core_table(table).drop(['_catalog_occurrence_count', '_catalog_physical_row'])
                                if 'source_occurrences' in self.owner.source_schema.names else table, self.parts)
                    pending = self._path(self.parts, 'parquet.tmp')
                    # Reserve the small receipt before writing; enforce bytes as
                    # Parquet emits them, including the rebuilt SQL indexes.
                    if pending.exists():
                        self.cache_bytes -= pending.stat().st_size
                    available = self._check_budget(extra=4096)
                    with _BudgetedFile(pending, available) as stream:
                        pq.write_table(table, stream, compression='zstd', use_compliant_nested_type=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    path = self._path(self.parts, 'parquet')
                    if path.exists():
                        self.cache_bytes -= path.stat().st_size
                    pending.replace(path)
                    receipt = dict(request=self.request, part=self.parts, first_row=self.count,
                        rows=len(table), previous=self.chain, file=dict(file_identity(path)))
                    receipt_path = self._path(self.parts, 'json')
                    if receipt_path.exists():
                        self.cache_bytes -= receipt_path.stat().st_size
                    _save(receipt_path, receipt)
                    self.chain = sha256(encoded(receipt)).hexdigest()
                    self.cache_bytes += path.stat().st_size + self._path(self.parts, 'json').stat().st_size
                    self.count += len(table)
                    self.parts += 1
                    self._progress('prepared')
        if skip:
            raise DependencyGap('Retained dependency preparation exceeds the supplied input rows')
        complete = self.directory / 'complete.json'
        _save(complete, dict(request=self.request, parts=self.parts, rows=self.count, chain=self.chain))
        self.cache_bytes += complete.stat().st_size
        self._progress('complete')

    def source_table(self, prefix):
        """Read only one candidate leaf; stop before materializing an oversized union."""
        locations = list(self.db.execute('SELECT part,row FROM sources WHERE digest>=? AND digest<? '
            'ORDER BY identity LIMIT ?', (prefix, prefix + 'g', self.owner.max_rows + 1)))
        if len(locations) > self.owner.max_rows:
            return None
        by_part = {}
        for part, row in locations:
            by_part.setdefault(part, []).append(row)
        pending = []
        for part, rows in sorted(by_part.items()):
            with pq.ParquetFile(self._path(part, 'parquet')) as file:
                physical = file.read()
            value = (physical.slice(rows[0], 1) if len(physical) == len(rows) == 1
                     else physical.take(pa.array(rows, type=pa.int64())))
            # A giant logical row must be isolated before concatenating it with
            # anything else. CatalogRows will split its occurrences at admission.
            if len(locations) > 1 and value.nbytes > self.owner.max_bytes:
                return None
            pending.append(value)
            table = pa.concat_tables(pending).combine_chunks()
            if not fits_chunk(table, max_rows=self.owner.max_rows, max_bytes=self.owner.max_bytes):
                return None
        table = (pa.concat_tables(pending) if pending
                 else pa.Table.from_batches([], schema=dependency_schema(self.owner.source_schema)))
        return (table.sort_by('source_id') if len(table) > 1 else table).combine_chunks()

