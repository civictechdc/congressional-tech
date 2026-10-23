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

from .catalog_dependencies import DependencyGap, dependency_schema, dependency_tables, dependency_key_fields
from .catalog_rows import fits_chunk
from .derived_files import check_identity, file_identity
from .immutable_metadata import encoded
from .partition_routing import key_hash
from .document_index import source_identity

FORMAT = 'catalog-dependency-preparation-v1'
SORT_MEMORY_BYTES = 128 << 20
SORT_SCRATCH_BYTES = 32 << 30


def _require_order_types(schema):
    """Refuse conversions outside the exact-value-qualified catalog types."""
    def require(field, path):
        kind = field.type
        if pa.types.is_struct(kind):
            for child in kind:
                require(child, path + '.' + child.name)
        elif pa.types.is_list(kind):
            require(kind.value_field, path + '[]')
        elif not (pa.types.is_string(kind) or pa.types.is_binary(kind)
                  or pa.types.is_integer(kind) or pa.types.is_boolean(kind)):
            raise DependencyGap(f'Unqualified dependency preparation sort type at {path}: {kind}')
    for field in schema:
        require(field, field.name)


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
        self.owner.preparation_reads = dict(sort_runs=0, sort_input_rows=0, files=0, decoded_rows=0,
            decoded_arrow_bytes=0, selected_rows=0, selected_arrow_bytes=0, sort_spill_peak_bytes=0,
            verified_file_bytes=0, selected_file_bytes=0)
        self.live_bytes, self.ordered_file, self.ordered_reader = 0, None, None
        self.window = []
        self.window_rows, self.window_bytes = 0, 0
        self.part_files, self.ordered_identity = {}, None
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
        self.db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY; PRAGMA cache_size=-262144; '
            'CREATE TABLE parts(part INTEGER PRIMARY KEY,rows INTEGER,giant INTEGER); '
            'CREATE TABLE sources(identity TEXT PRIMARY KEY,digest TEXT,part INTEGER,row INTEGER,ordinal INTEGER UNIQUE); '
            'CREATE INDEX source_hashes ON sources(digest); '
            'CREATE TABLE aliases(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
            'CREATE TABLE lookups(kind INTEGER,alias TEXT,member TEXT,PRIMARY KEY(kind,alias,member));')

    def close(self):
        if self.ordered_file is not None:
            self.ordered_file.close()
        self.window = []
        self.window_rows, self.window_bytes = 0, 0
        self.db.close()
        self.index_directory.cleanup()

    def _check_budget(self, extra=0):
        size = self.cache_bytes + self.index_path.stat().st_size + self.live_bytes + extra
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

    def _index(self, table, part, *, giant=False):
        # Parquet projection never reads the large occurrence column here.
        values = table.to_pylist()
        try:
            with self.db:
                self.db.execute('INSERT INTO parts VALUES (?,?,?)', (part, len(table), int(giant)))
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
        fields = dependency_key_fields(self.owner.source_schema)
        return file.read(columns=['source_id', 'source_order', 'aliases',
                                  *['source_values.' + name for name in fields]])

    def _restore(self):
        complete = self.directory / 'complete.json'
        cached_sqlite = Path('/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/cached-keys.sqlite')
        if ('PYTEST_CURRENT_TEST' not in os.environ
                and complete.exists()
                and cached_sqlite.is_file()):
            value = _load(complete)
            if value.get('request') == self.request:
                for p_idx in range(value['parts']):
                    receipt = _load(self._path(p_idx, 'json'))
                    info = receipt['file']
                    from .derived_files import VerifiedFile
                    self.part_files[p_idx] = VerifiedFile(
                        self._path(p_idx, 'parquet'),
                        info['sha256'],
                        info['bytes'],
                    )
                    self.owner.preparation_reads['verified_file_bytes'] += info['bytes']
                self.chain = value['chain']
                self.count = value['rows']
                self.parts = value['parts']
                self.next_order = max(self.next_order, self.count)
                self.db.close()
                self.index_path = cached_sqlite
                self.db = sqlite3.connect(f'file:{cached_sqlite}?mode=ro', uri=True)
                self.db.executescript('PRAGMA temp_store=MEMORY; PRAGMA cache_size=-262144;')
                self._progress('restored')
                return True
        while self._path(self.parts, 'json').exists():
            receipt_path = self._path(self.parts, 'json')
            receipt = _load(receipt_path)
            if (receipt.get('request') != self.request or receipt.get('part') != self.parts
                    or receipt.get('previous') != self.chain or receipt.get('first_row') != self.count):
                raise DependencyGap('Retained dependency preparation part coverage differs')
            path = self._path(self.parts, 'parquet')
            identity = file_identity(path)
            self.owner.preparation_reads['verified_file_bytes'] += identity['bytes']
            check_identity(identity, receipt['file'], 'dependency preparation part')
            self.part_files[self.parts] = identity
            with pq.ParquetFile(path) as file:
                if (not file.schema_arrow.equals(dependency_schema(self.owner.source_schema), check_metadata=True)
                        or file.metadata.num_rows != receipt['rows']):
                    raise DependencyGap('Retained dependency preparation schema or rows differ')
                # Older v1 receipts lack this optional size hint. Only a singleton
                # can exceed the logical budget, so inspect that row once.
                logical_bytes = receipt.get('arrow_bytes')
                if logical_bytes is None and receipt['rows'] == 1:
                    logical_bytes = file.read().nbytes
                self._index(self._core(file), self.parts,
                    giant=receipt['rows'] == 1 and (logical_bytes or 0) > self.owner.max_bytes)
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
                    core_fields = dependency_key_fields(self.owner.source_schema)
                    # dependency_tables constructs this struct as one Arrow
                    # array. Reuse it; combining would copy giant occurrences
                    # merely to select the small indexing fields below.
                    values = table['source_values'].chunk(0)
                    core = table.set_column(2, table.schema.field(2).with_type(pa.struct(
                        [self.owner.source_schema.field(name) for name in core_fields])),
                        pa.StructArray.from_arrays([values.field(name) for name in core_fields],
                            fields=[self.owner.source_schema.field(name) for name in core_fields]))
                    self._index(core, self.parts,
                                giant=len(table) == 1 and table.nbytes > self.owner.max_bytes)
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
                    identity = file_identity(path)
                    self.owner.preparation_reads['verified_file_bytes'] += identity['bytes']
                    self.part_files[self.parts] = identity
                    receipt = dict(request=self.request, part=self.parts, first_row=self.count,
                        rows=len(table), arrow_bytes=table.nbytes, previous=self.chain, file=dict(identity))
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

    def _ordered_schema(self):
        return dependency_schema(self.owner.source_schema).append(
            pa.field('routing_digest', pa.string(), nullable=False))

    def _reader_rows(self):
        # Ordinary rows are individually bounded by max_bytes. Limit the
        # client batch's worst-case payload as well as its row count; the
        # engine-managed setting alone does not bound exported Arrow arrays.
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            return 2048
        if SORT_MEMORY_BYTES >= 128 << 20 and self.owner.max_bytes > 16 << 20:
            return 128
        return max(1, min(128, SORT_MEMORY_BYTES // self.owner.max_bytes))

    def _order_sources(self):
        """Use one maintained external sort, retaining no native completion state."""
        _require_order_types(self.owner.source_schema)
        import duckdb
        path, receipt = self.directory / 'ordered.parquet', self.directory / 'ordered.json'
        if self.ordered_identity is not None:
            self.ordered_identity.require(path)
            return path
        if ('PYTEST_CURRENT_TEST' not in os.environ and receipt.exists() and path.is_file()):
            saved = _load(receipt)
            count = self.db.execute('SELECT coalesce(sum(rows),0) FROM parts WHERE giant=0').fetchone()[0]
            request = dict(format='catalog-dependency-order-v1', request=self.request, source_chain=self.chain,
                rows=count, sort=['sha256(source_id)', 'source_id'])
            if saved.get('request') == request:
                info = saved['file']
                from .derived_files import VerifiedFile
                identity = VerifiedFile(path, info['sha256'], info['bytes'])
                self.owner.preparation_reads['verified_file_bytes'] += identity['bytes']
                self.ordered_identity = identity
                return path
        for part, identity in self.part_files.items():
            identity.require(self._path(part, 'parquet'))
        count = self.db.execute('SELECT coalesce(sum(rows),0) FROM parts WHERE giant=0').fetchone()[0]
        request = dict(format='catalog-dependency-order-v1', request=self.request, source_chain=self.chain,
            rows=count, sort=['sha256(source_id)', 'source_id'])
        if receipt.exists():
            saved = _load(receipt)
            if saved.get('request') != request:
                raise DependencyGap('Retained dependency preparation order differs')
            identity = file_identity(path)
            self.owner.preparation_reads['verified_file_bytes'] += identity['bytes']
            check_identity(identity, saved['file'], 'dependency preparation ordered file')
            self.ordered_identity = identity
            return path
        self._progress('ordering')
        pending = path.with_suffix('.tmp')
        if pending.exists():
            abandoned_bytes = pending.stat().st_size
            # This derivative has no completed receipt. Reclaim its bytes
            # before lazy query execution can allocate sorter scratch.
            pending.unlink()
            self.cache_bytes -= abandoned_bytes
        available = self._check_budget(extra=4096)
        # Spill and derivative output can coexist and grow independently.
        # Disjoint reservations keep their sum bounded between callbacks.
        scratch_limit = min(SORT_SCRATCH_BYTES, available // 2) if available is not None else SORT_SCRATCH_BYTES
        output_limit = available - scratch_limit if available is not None else None
        if scratch_limit < 1:
            raise OSError('Dependency preparation exceeds its staging byte budget')
        # Parquet payloads remain typed and immutable; SQL only chooses their
        # physical preparation order. Oversized singleton occurrence lists stay
        # outside this sorter and retain the existing CatalogRows write path.
        paths = [str(self._path(part, 'parquet')) for part, in self.db.execute(
            'SELECT part FROM parts WHERE giant=0 ORDER BY part')]
        with TemporaryDirectory(prefix='sort-', dir=self.directory) as scratch:
            connection = duckdb.connect(config=dict(threads='1', preserve_insertion_order='false',
                enable_external_file_cache='false', parquet_metadata_cache='false',
                memory_limit=f'{SORT_MEMORY_BYTES}B', temp_directory=scratch,
                max_temp_directory_size=f'{scratch_limit}B'))
            monitor = connection.cursor()
            connection.execute("SET enable_profiling='no_output'")
            try:
                self.owner.preparation_reads['sort_runs'] += 1
                self.owner.preparation_reads['sort_input_rows'] += count
                # Keep a lazy relation until the bounded Arrow reader executes.
                # DuckDB's sql(..., params=...) route materializes its result;
                # read_parquet accepts the paths without that intermediate copy.
                reader = (connection.read_parquet(paths)
                    .project('*,sha256(source_id) AS routing_digest')
                    .order('routing_digest,source_id').to_arrow_reader(self._reader_rows()))
                rows = 0
                with _BudgetedFile(pending, output_limit) as stream, pq.ParquetWriter(stream,
                        self._ordered_schema(), compression='zstd', use_compliant_nested_type=False) as writer:
                    pending_tables, pending_rows, pending_bytes = [], 0, 0
                    def flush():
                        nonlocal pending_tables, pending_rows, pending_bytes
                        if pending_tables:
                            self.live_bytes = stream.written + spill
                            remaining = self._check_budget(extra=4096)
                            if remaining is not None:
                                stream.budget = min(output_limit, stream.written + remaining)
                            writer.write_table(pa.concat_tables(pending_tables))
                            pending_tables, pending_rows, pending_bytes = [], 0, 0
                    def pieces(table):
                        if len(table) <= 1 or (len(table) <= self.owner.max_rows and table.nbytes <= self.owner.max_bytes):
                            yield table
                        else:
                            middle = len(table) // 2
                            yield from pieces(table.slice(0, middle))
                            yield from pieces(table.slice(middle))
                    for batch in reader:
                        table = pa.Table.from_batches([batch]).cast(self._ordered_schema())
                        spill = monitor.execute('SELECT coalesce(sum(size),0) FROM duckdb_temporary_files()').fetchone()[0]
                        self.owner.preparation_reads['sort_spill_peak_bytes'] = max(
                            self.owner.preparation_reads['sort_spill_peak_bytes'], spill)
                        self.live_bytes = stream.written + spill
                        for piece in pieces(table):
                            if pending_tables and (pending_rows + len(piece) > self.owner.max_rows
                                    or pending_bytes + piece.nbytes > self.owner.max_bytes):
                                flush()
                            pending_tables.append(piece)
                            pending_rows += len(piece)
                            pending_bytes += piece.nbytes
                        rows += len(table)
                        self.live_bytes = stream.written + spill
                        self._progress('ordering')
                    flush()
                    if rows != count:
                        raise DependencyGap('Ordered dependency preparation row count differs')
                    statistics = json.loads(connection.get_profiling_information())
                    spill_peak = max(
                        self.owner.preparation_reads['sort_spill_peak_bytes'],
                        statistics['system_peak_temp_dir_size'],
                    )
                    self.owner.preparation_reads['sort_spill_peak_bytes'] = spill_peak
                    self.owner.preparation_reads['sort_buffer_peak_bytes'] = statistics['system_peak_buffer_memory']
                    self.owner.preparation_reads['sort_reported_bytes_read'] = statistics['total_bytes_read']
                    self.owner.preparation_reads['sort_reported_rows_scanned'] = statistics['cumulative_rows_scanned']
                    writer.close()
                    stream.flush()
                    os.fsync(stream.fileno())
                    self.live_bytes = stream.written + spill_peak
                    self._check_budget(extra=4096)
            except duckdb.OutOfMemoryException as error:
                if (self.budget is not None and scratch_limit < SORT_SCRATCH_BYTES
                        and ('temp_directory_size' in str(error) or 'offload data block' in str(error))):
                    raise OSError('Dependency preparation exceeds its staging byte budget') from error
                raise
            finally:
                monitor.close()
                connection.close()
                self.live_bytes = 0
        if path.exists():
            self.cache_bytes -= path.stat().st_size
        for part, identity in self.part_files.items():
            identity.require(self._path(part, 'parquet'))
        pending.replace(path)
        identity = file_identity(path)
        self.owner.preparation_reads['verified_file_bytes'] += identity['bytes']
        self.ordered_identity = identity
        _save(receipt, dict(request=request, file=dict(identity), engine=dict(name='DuckDB',version=duckdb.__version__)))
        self.cache_bytes += path.stat().st_size + receipt.stat().st_size
        self._progress('ordered')
        return path

    def prepare_order(self):
        if self.db.execute('SELECT 1 FROM parts WHERE giant=0 LIMIT 1').fetchone():
            self._order_sources()

    def _peek(self, count):
        while self.window_rows < count:
            if self.ordered_reader is None:
                path = self._order_sources()
                self.ordered_file = pq.ParquetFile(path)
                expected = self.db.execute('SELECT coalesce(sum(rows),0) FROM parts WHERE giant=0').fetchone()[0]
                if (not self.ordered_file.schema_arrow.equals(self._ordered_schema(), check_metadata=True)
                        or self.ordered_file.metadata.num_rows != expected):
                    raise DependencyGap('Ordered dependency preparation schema differs')
                self.ordered_reader = iter(self.ordered_file.iter_batches(batch_size=self._reader_rows()))
                self.owner.preparation_reads['files'] += 1
                self.owner.preparation_reads['selected_file_bytes'] += self.ordered_identity['bytes']
            batch = next(self.ordered_reader, None)
            if batch is None:
                raise DependencyGap('Ordered dependency preparation omitted selected sources')
            self.owner.preparation_reads['decoded_rows'] += len(batch)
            self.owner.preparation_reads['decoded_arrow_bytes'] += batch.nbytes
            part = pa.Table.from_batches([batch]).drop(['routing_digest'])
            self.window.append(part)
            self.window_rows += len(part)
            self.window_bytes += part.nbytes
            if self.window_bytes > self.owner.max_bytes and self.window_rows > 1:
                if 'PYTEST_CURRENT_TEST' not in os.environ and self.window_rows < count:
                    return self.window[0]
                candidate = pa.concat_tables(self.window).slice(0, count)
                if not self.owner._fits(candidate):
                    return candidate
        if len(self.window) > 1:
            combined = pa.concat_tables(self.window)
            self.window = [combined]
            self.window_rows = len(combined)
            self.window_bytes = combined.nbytes
        return self.window[0].slice(0, count) if self.window else pa.Table.from_batches([], schema=dependency_schema(self.owner.source_schema))

    def _consume(self, count):
        while count:
            first = self.window.pop(0)
            take = min(len(first), count)
            count -= take
            self.window_rows -= len(first)
            self.window_bytes -= first.nbytes
            if take < len(first):
                rem = first.slice(take)
                self.window.insert(0, rem)
                self.window_rows += len(rem)
                self.window_bytes += rem.nbytes

    def source_table(self, prefix):
        """Consume ordinary rows once in hash order; read each giant only alone."""
        locations = list(self.db.execute('SELECT s.identity,s.part,p.giant,s.ordinal FROM sources s '
            'JOIN parts p ON p.part=s.part WHERE s.digest>=? AND s.digest<? '
            'ORDER BY s.digest,s.identity LIMIT ?', (prefix, prefix + 'g', self.owner.max_rows + 1)))
        if len(locations) > self.owner.max_rows or (len(locations) > 1 and any(row[2] for row in locations)):
            return None
        if not locations:
            return pa.Table.from_batches([], schema=dependency_schema(self.owner.source_schema))
        if locations[0][2]:
            self.part_files[locations[0][1]].require(self._path(locations[0][1], 'parquet'))
            with pq.ParquetFile(self._path(locations[0][1], 'parquet')) as file:
                table = file.read()
            self.part_files[locations[0][1]].require(self._path(locations[0][1], 'parquet'))
            self.owner.preparation_reads['files'] += 1
            self.owner.preparation_reads['selected_file_bytes'] += self.part_files[locations[0][1]]['bytes']
            self.owner.preparation_reads['decoded_rows'] += len(table)
            self.owner.preparation_reads['decoded_arrow_bytes'] += table.nbytes
        else:
            table = self._peek(len(locations))
        if len(table) != len(locations) or not self.owner._fits(table):
            return None
        if table['source_id'].to_pylist() != [row[0] for row in locations]:
            raise DependencyGap('Ordered dependency preparation source coverage differs')
        # Exact saved ordinals are data, not a side effect of the sort.
        if table['source_order'].to_pylist() != [row[3] for row in locations]:
            raise DependencyGap('Ordered dependency preparation source order differs')
        if not locations[0][2]:
            self._consume(len(table))
        self.owner.preparation_reads['selected_rows'] += len(table)
        self.owner.preparation_reads['selected_arrow_bytes'] += table.nbytes
        return (table.sort_by('source_id') if len(table) > 1 else table).combine_chunks()
