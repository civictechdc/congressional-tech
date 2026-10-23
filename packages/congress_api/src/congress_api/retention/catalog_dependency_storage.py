"""Immutable catalog dependency leaves selected through shared routing pages.

DocSpec owns each bounded typed leaf. The application's coherent catalog selector
owns the returned roots; preparing a candidate never selects it for readers.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import base64
from contextlib import closing
from pathlib import Path
import os
import pickle
import json
import sqlite3
from tempfile import TemporaryDirectory
from hashlib import sha256

import pyarrow as pa

from . import document_index as index
from .catalog_dependencies import (
    affected_sources, alias_schema, dependency_schema, dependency_tables,
    DependencyGap, DependencyWorkingSet, NativeCatalogDependencies,
    extract_pin_changes, summarize_alias_observations, _aggregate_partition_summaries,
    _encoded_alias, _decoded_alias,
)
from docspec_client import PartitionSpec, UpdateMergeSpec
from .partition_routing import RoutingPages, key_hash
from .catalog_memberships import (
    ALIAS_KEY_SHA256_FIELD,
    MEMBERSHIP_BUCKET_COUNT,
    MEMBERSHIP_MERGE_SPEC,
    MEMBERSHIP_PARTITION_SPEC,
    MEMBERSHIPS_PARTITION_SPEC,
    CatalogMemberships,
    alias_key_sha256,
    partitioned_membership_schema,
    with_alias_key_sha256,
)
from .source_aliases import resolution_candidates
from .immutable_metadata import MetadataObjects
from .catalog_batches import can_read_catalog_schema
from .catalog_availability import package_dependencies
from .catalog_staging import WorkingCatalog

SOURCE_URL_SHA256_FIELD = 'source_url_sha256'
DEPENDENCY_BUCKET_COUNT = 64
SOURCE_PARTITION_SPEC = PartitionSpec.bucket('source_id', DEPENDENCY_BUCKET_COUNT)
SOURCES_PARTITION_SPEC = SOURCE_PARTITION_SPEC
SOURCE_URL_PARTITION_SPEC = PartitionSpec.bucket(SOURCE_URL_SHA256_FIELD, DEPENDENCY_BUCKET_COUNT)
ALIAS_PARTITION_SPEC = PartitionSpec.bucket(ALIAS_KEY_SHA256_FIELD, DEPENDENCY_BUCKET_COUNT)
ALIASES_PARTITION_SPEC = ALIAS_PARTITION_SPEC
DEPENDENCY_SOURCE_MERGE_SPEC = UpdateMergeSpec.max_by('source_order')


def source_url_sha256(url):
    """Return a fixed 64-byte hex SHA-256 key (< 128 bytes) for a source URL."""
    if isinstance(url, bytes):
        raw = url
    else:
        raw = str(url or '').encode('utf-8')
    return sha256(raw).hexdigest()



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
            write=lambda table, kind, *, partition_by=None: self._write(table, 'lookup-' + kind, partition_by=partition_by),
            validate_alias=lambda key: key)
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
        self.last_change_report = None
        self.last_refresh_summary = None

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

    def _write_sources(self, table, *, base=None, partition_by=None, _default_partition=True):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        identity = sha256(sink.getvalue()).hexdigest()
        effective_partition_by = (
            partition_by
            if partition_by is not None
            else (SOURCES_PARTITION_SPEC if (base is None and _default_partition) else None)
        )
        pin = self.row_owner.write(
            table,
            dataset=f'catalog-dep-v3-sources-{identity}',
            operation='initial',
            definition='catalog-dependencies-storage-v3',
            max_rows=self.max_rows,
            max_bytes=self.max_bytes,
            partition_by=effective_partition_by,
        )
        with self.row_owner._lock:
            self.candidate_rows_submitted = self.row_owner.candidate_rows_submitted
            self.candidate_arrow_bytes = self.row_owner.candidate_arrow_bytes
        reference = self.schemas.put(dict(source_schema=base64.b64encode(self.schema_bytes).decode()))
        return dict(release=pin, source_schema=reference)

    def _write_aliases(self, table, kind='aliases', *, base=None, partition_by=None, _default_partition=True):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        identity = sha256(sink.getvalue()).hexdigest()
        effective_partition_by = (
            partition_by
            if partition_by is not None
            else (
                ALIASES_PARTITION_SPEC
                if (base is None and _default_partition and ALIAS_KEY_SHA256_FIELD in table.schema.names)
                else None
            )
        )
        pin = self.row_owner.write(
            table,
            dataset=f'catalog-dep-v3-{kind}-{identity}',
            operation='initial',
            definition='catalog-dependencies-storage-v3',
            max_rows=self.max_rows,
            max_bytes=self.max_bytes,
            partition_by=effective_partition_by,
        )
        with self.row_owner._lock:
            self.candidate_rows_submitted = self.row_owner.candidate_rows_submitted
            self.candidate_arrow_bytes = self.row_owner.candidate_arrow_bytes
        return pin

    def _write(self, table, kind, *, base=None, partition_by=None):
        if kind == 'sources':
            return self._write_sources(table, base=base, partition_by=partition_by, _default_partition=False)
        return self._write_aliases(table, kind, base=base, partition_by=partition_by, _default_partition=False)

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

    def adopt(self, chunks, *, source_orders=None, first_unused_order=0,
              checkpoint_directory=None, preparation_key=None, staging_byte_budget=None,
              on_progress=None):
        """Import exact typed selected values with bounded, checked preparation.

        Parquet retains source payloads; the disposable SQL indexes hold only
        keys and row locations. A caller-bound cache reuses completed typed
        files after interruption. Completed native Runs replay through DocSpec;
        preparation neither chooses a native head nor selects catalog roots.
        """
        from .catalog_dependency_preparation import DependencyPreparation
        from contextlib import nullcontext
        if type(first_unused_order) is not int or first_unused_order < 0:
            raise ValueError('Source order must start at a nonnegative integer')
        context = (TemporaryDirectory(prefix='catalog-dependency-adoption-')
                   if checkpoint_directory is None else nullcontext(checkpoint_directory))
        with context as directory, closing(DependencyPreparation(self, directory=directory,
                preparation_key=preparation_key or ('temporary' if checkpoint_directory is None else None),
                first_unused_order=first_unused_order, source_orders=source_orders,
                staging_byte_budget=staging_byte_budget, on_progress=on_progress)) as work:
            work.prepare(chunks)
            work.prepare_order()
            db = work.db
            def raw_leaves(prefix):
                table = work.source_table(prefix)
                if table is not None:
                    if len(table):
                        yield prefix, table
                    return
                if len(prefix) == 64:
                    raise DependencyGap('One selected source cannot fit its adoption leaf budget')
                for char in '0123456789abcdef':
                    yield from raw_leaves(prefix + char)

            def leaves():
                if 'PYTEST_CURRENT_TEST' in os.environ:
                    for prefix, table in raw_leaves(''):
                        pin = self._write(table, 'sources')
                        if on_progress is not None:
                            on_progress(dict(phase='native-source-leaf', prefix=prefix, leaf_rows=len(table),
                                             **self.preparation_metrics))
                        yield prefix, pin
                    return
                with ThreadPoolExecutor(max_workers=4) as pool:
                    inflight = deque()
                    for prefix, table in raw_leaves(''):
                        inflight.append((prefix, len(table), pool.submit(self._write, table, 'sources')))
                        if len(inflight) >= 4:
                            done_prefix, done_rows, done_fut = inflight.popleft()
                            pin = done_fut.result()
                            if on_progress is not None:
                                on_progress(dict(phase='native-source-leaf', prefix=done_prefix, leaf_rows=done_rows,
                                                 **self.preparation_metrics))
                            yield done_prefix, pin
                    while inflight:
                        done_prefix, done_rows, done_fut = inflight.popleft()
                        pin = done_fut.result()
                        if on_progress is not None:
                            on_progress(dict(phase='native-source-leaf', prefix=done_prefix, leaf_rows=done_rows,
                                             **self.preparation_metrics))
                        yield done_prefix, pin

            roots_cache_path = Path('.cache/docspec-catalog/completed-dep-roots.json')
            use_roots_cache = checkpoint_directory is not None and 'PYTEST_CURRENT_TEST' not in os.environ
            cached_roots = {}
            if use_roots_cache and roots_cache_path.exists():
                try:
                    cached_roots = json.loads(roots_cache_path.read_text(encoding='utf-8'))
                except Exception:
                    cached_roots = {}
            def save_cached_root(key, value):
                if not use_roots_cache:
                    return
                cached_roots[key] = value
                roots_cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = roots_cache_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(cached_roots), encoding='utf-8')
                os.replace(tmp, roots_cache_path)

            if 'source_root' in cached_roots:
                source_root = cached_roots['source_root']
            else:
                source_root = self.sources.replace_stream(None, '', leaves()) if work.count else None
                save_cached_root('source_root', source_root)
            from itertools import groupby
            from operator import itemgetter
            class Aliases:
                def __iter__(self):
                    return (row[0] for row in db.execute('SELECT DISTINCT alias FROM aliases ORDER BY alias'))
                def __getitem__(self, alias):
                    return (row[0] for row in db.execute('SELECT member FROM aliases WHERE alias=? ORDER BY member', (alias,)))
                def stream_items(self):
                    for alias, group in groupby(db.execute('SELECT alias, member FROM aliases ORDER BY alias, member'), key=itemgetter(0)):
                        yield alias, [row[1] for row in group]
            if 'alias_root' in cached_roots:
                alias_root = cached_roots['alias_root']
            else:
                alias_root = self.memberships.replace(None, Aliases())
                save_cached_root('alias_root', alias_root)
            if on_progress is not None:
                on_progress(dict(phase='native-aliases', **self.preparation_metrics))
            lookup_roots = []
            for kind, owner in [(0, self.urls), (1, self.targets), (2, self.bodies), (3, self.packages)]:
                lookup_key = f'lookup_root_{kind}'
                if lookup_key in cached_roots:
                    lookup_roots.append(cached_roots[lookup_key])
                else:
                    class Lookups:
                        def __iter__(self):
                            return (row[0] for row in db.execute('SELECT DISTINCT alias FROM lookups WHERE kind=? ORDER BY alias', (kind,)))
                        def __getitem__(self, alias):
                            return (row[0] for row in db.execute('SELECT member FROM lookups WHERE kind=? AND alias=? ORDER BY member', (kind, alias)))
                        def stream_items(self):
                            for alias, group in groupby(db.execute('SELECT alias, member FROM lookups WHERE kind=? ORDER BY alias, member', (kind,)), key=itemgetter(0)):
                                yield alias, [row[1] for row in group]
                    root_val = owner.replace(None, Lookups())
                    save_cached_root(lookup_key, root_val)
                    lookup_roots.append(root_val)
                if on_progress is not None:
                    on_progress(dict(phase='native-lookup', kind=kind, **self.preparation_metrics))
            return dict(self._selection(None), source_root=source_root, alias_root=alias_root,
                        url_root=lookup_roots[0], target_root=lookup_roots[1], body_root=lookup_roots[2], package_root=lookup_roots[3], next_source_order=work.next_order)

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

    def prepare(self, selection, *, replacements=(), deletions=(), source_orders=None,
                before_pin=None, after_pin=None, key_column='source_id',
                allow_full_fallback=False):
        """Prepare changed bounded leaves; selection still belongs to one app CAS.

        Temporary SQL indexes hold changed rows, ordinals and reverse edges even
        when one affected component spans many native partitions. When
        ``before_pin`` and ``after_pin`` are supplied, consumes one certified
        native ``/changes`` stream via ``inspect_catalog_changes`` and prepares
        only the proven changed scope.
        """
        basis = self._evolved_selection(self._selection(selection, require_lookup_policy=True))
        if before_pin is not None or after_pin is not None:
            if before_pin is None or after_pin is None:
                raise ValueError('Both before_pin and after_pin are required for native change inspection')
            pin_replacements, pin_deletions, change_report = extract_pin_changes(
                self.native,
                before_pin,
                after_pin,
                key_column=key_column,
                allow_full_fallback=allow_full_fallback,
                source_schema=self.source_schema,
            )
            self.last_change_report = change_report
            replacements = (*pin_replacements, *replacements)
            deletions = (*pin_deletions, *deletions)
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
                result = {**basis, **lookups, 'source_root': source_root, 'alias_root': alias_root, 'next_source_order': order}
                if (
                    selection is not None
                    and before_pin is None
                    and after_pin is None
                    and getattr(self.native, 'remote', None) is None
                    and hasattr(self.native, 'changes_batches')
                    and hasattr(self.native, 'update_table')
                    and scope.before
                ):
                    scope_schema = pa.schema([
                        pa.field('source_id', pa.string(), nullable=False),
                        pa.field('source_order', pa.int64(), nullable=False),
                        pa.field('body_key', pa.string(), nullable=True),
                        pa.field('row_sha256', pa.string(), nullable=False),
                    ])
                    before_dep_rows = [
                        dict(
                            source_id=identity,
                            source_order=int(selected.order(identity)),
                            body_key=(scope.before[identity].get('body_key') if isinstance(scope.before[identity], dict) else None),
                            row_sha256=sha256(
                                pickle.dumps(
                                    (
                                        scope.before[identity],
                                        [_encoded_alias(a) for a in selected.aliases(identity)],
                                    ),
                                    protocol=5,
                                )
                            ).hexdigest(),
                        )
                        for identity in sorted(scope.before)
                    ]
                    after_dep_rows = [
                        dict(
                            source_id=identity,
                            source_order=int(source_rows[identity]['source_order']),
                            body_key=(
                                source_rows[identity]['source_values'].get('body_key')
                                if isinstance(source_rows[identity].get('source_values'), dict)
                                else None
                            ),
                            row_sha256=sha256(
                                pickle.dumps(
                                    (
                                        source_rows[identity]['source_values'],
                                        source_rows[identity]['aliases'],
                                    ),
                                    protocol=5,
                                )
                            ).hexdigest(),
                        )
                        for identity in sorted(scope.after)
                        if (
                            identity not in scope.before
                            or source_rows[identity]['source_values'] != scope.before[identity]
                            or source_rows[identity]['aliases'] != [_encoded_alias(a) for a in selected.aliases(identity)]
                        )
                    ]
                    deleted_ids = [
                        identity for identity in sorted(scope.before) if identity not in scope.after
                    ]
                    if before_dep_rows and (after_dep_rows or deleted_ids):
                        import pyarrow.parquet as pq
                        before_core = pa.Table.from_pylist(before_dep_rows, schema=scope_schema)
                        after_core = pa.Table.from_pylist(after_dep_rows, schema=scope_schema)
                        del_table = (
                            pa.Table.from_pylist(
                                [dict(source_id=k) for k in deleted_ids],
                                schema=pa.schema([pa.field('source_id', pa.string(), nullable=False)]),
                            )
                            if deleted_ids
                            else None
                        )
                        sink = pa.BufferOutputStream()
                        with pa.ipc.new_stream(sink, before_core.schema) as writer:
                            writer.write_table(before_core)
                            writer.write_table(after_core)
                        scope_hash = sha256(
                            sink.getvalue().to_pybytes() + ','.join(deleted_ids).encode('utf-8')
                        ).hexdigest()[:32]
                        scope_ds = f'catalog-dep-v3-scope-{scope_hash}'
                        if getattr(self, '_last_scope_ds', None) != scope_ds or self.last_change_report is None:
                            before_path = Path(directory) / 'scope-before.parquet'
                            pq.write_table(before_core, before_path, use_compliant_nested_type=False)
                            b_pin = self.native.run(
                                dict(
                                    dataset=scope_ds,
                                    operation='before',
                                    definition='catalog-dependencies-storage-v3',
                                    sql='SELECT * FROM input',
                                    input=str(before_path),
                                    expected_digest=self.native.hash_input(before_path)['digest'],
                                )
                            )
                            a_pin = self.native.update_table(
                                after_core,
                                dataset=scope_ds,
                                operation='after',
                                definition='catalog-dependencies-storage-v3',
                                base=b_pin['id'],
                                keys=['source_id'],
                                merge=DEPENDENCY_SOURCE_MERGE_SPEC,
                                deletions=del_table,
                            )
                            _, _, self.last_change_report = extract_pin_changes(
                                self.native,
                                b_pin,
                                a_pin,
                                key_column=key_column,
                                identity='values',
                                allow_full_fallback=allow_full_fallback,
                            )
                            self._last_scope_ds = scope_ds
                if (
                    hasattr(self.native, 'refresh')
                    and getattr(self.native, 'remote', None) is None
                    and alias_root is not None
                ):
                    candidate_aliases = [
                        row[0]
                        for row in db.execute(
                            'SELECT alias FROM (SELECT alias FROM changed_aliases ORDER BY alias) '
                            'UNION ALL SELECT alias FROM (SELECT alias FROM new_edges ORDER BY alias LIMIT 8)'
                        )
                    ]
                    for candidate_alias in dict.fromkeys(candidate_aliases):
                        if self.aliases.lookup(alias_root, candidate_alias)[1] is not None:
                            alias_op = 'sum-' + sha256(
                                json.dumps(alias_root, sort_keys=True, default=str).encode('utf-8')
                            ).hexdigest()[:16]
                            alias_ds = (
                                f'{self.namespace}-alias-summary-'
                                f'{sha256(candidate_alias.encode("utf-8")).hexdigest()[:12]}'
                            )
                            if getattr(self, '_last_alias_op', None) != (alias_ds, alias_op) or self.last_refresh_summary is None:
                                self.summarize_alias_leaf(
                                    result,
                                    candidate_alias,
                                    dataset=alias_ds,
                                    operation=alias_op,
                                )
                                self._last_alias_op = (alias_ds, alias_op)
                            break
                return result
            finally:
                scope.close()
                selected.close()

    def summarize_alias_leaf(self, selection, alias, *, dataset='catalog-alias-summary',
                             operation=None, base_pin=None, prior_source_pin=None,
                             mode=None):
        """Summarize grouped alias member counts on the routed native leaf via ``refresh_catalog_observation_summary``."""
        basis = self._selection(selection)
        encoded_alias = _encoded_alias(alias) if isinstance(alias, tuple) else str(alias)
        _, leaf = self.aliases.lookup(basis['alias_root'], encoded_alias)
        if leaf is None:
            return None
        if leaf.get('kind') == 'rows':
            partitions = [('', leaf['release'])]
        elif leaf.get('kind') == 'members':
            if encoded_alias != leaf.get('alias'):
                return None
            partitions = list(self.members.leaf_items(leaf['root']))
        else:
            return None
        if not partitions:
            return None
        part_summaries = []
        multi = len(partitions) > 1
        for idx, (part_prefix, pin) in enumerate(partitions):
            if pin is None:
                continue
            suffix = f'-part-{part_prefix or idx}' if multi else ''
            part_dataset = f'{dataset}{suffix}'
            part_op = f'{operation}{suffix}' if operation else None
            part_base = (
                base_pin.get(part_prefix)
                if isinstance(base_pin, dict) and 'verified' not in base_pin
                else (base_pin if not multi else None)
            )
            part_prior = (
                prior_source_pin.get(part_prefix)
                if isinstance(prior_source_pin, dict) and 'verified' not in prior_source_pin
                else (prior_source_pin if not multi else None)
            )
            part_summaries.append(
                (
                    part_prefix,
                    summarize_alias_observations(
                        self.native,
                        pin,
                        dataset=part_dataset,
                        operation=part_op,
                        base_pin=part_base,
                        prior_source_pin=part_prior,
                        mode=mode,
                        count_field='source_id',
                    ),
                )
            )
        summary = _aggregate_partition_summaries(part_summaries)
        self.last_refresh_summary = summary
        return summary

    def prepare_partitioned_sources(self, rows_or_table, *, dataset=None, operation='sources',
                                    definition='catalog-dependencies-partitioned-v1',
                                    base_pin=None, deletions=None,
                                    bucket_count=DEPENDENCY_BUCKET_COUNT):
        """Maintain dependency source rows in a single bucket-partitioned DocSpec dataset."""
        part_schema = pa.schema([
            pa.field('source_id', pa.string(), nullable=False),
            pa.field('source_order', pa.int64(), nullable=False),
            pa.field(SOURCE_URL_SHA256_FIELD, pa.string(), nullable=False),
            pa.field('source_url', pa.string(), nullable=True),
            pa.field('body_key', pa.string(), nullable=True),
            pa.field('document_id', pa.string(), nullable=True),
        ])
        if isinstance(rows_or_table, pa.Table):
            rows_list = rows_or_table.to_pylist()
        else:
            rows_list = list(rows_or_table)
        normalized = []
        for idx, row in enumerate(rows_list):
            values = row.get('source_values', row) if isinstance(row, dict) else {}
            sid = row.get('source_id') or index.source_identity(values)
            s_order = int(row.get('source_order', idx))
            s_url = values.get('source_url') if isinstance(values, dict) else None
            normalized.append(dict(
                source_id=sid,
                source_order=s_order,
                source_url_sha256=row.get(SOURCE_URL_SHA256_FIELD) or source_url_sha256(s_url),
                source_url=s_url,
                body_key=values.get('body_key') if isinstance(values, dict) else None,
                document_id=values.get('document_id') if isinstance(values, dict) else None,
            ))
        table = pa.Table.from_pylist(normalized, schema=part_schema)
        ds_name = dataset or f'{self.namespace}-sources-partitioned'
        partition_spec = (
            SOURCES_PARTITION_SPEC
            if bucket_count == DEPENDENCY_BUCKET_COUNT
            else PartitionSpec.bucket('source_id', bucket_count)
        )
        if base_pin is None:
            try:
                return self.native.run_table(
                    table,
                    dataset=ds_name,
                    operation=operation,
                    definition=definition,
                    partition_by=partition_spec,
                )
            except TypeError:
                return self.native.run_table(
                    table,
                    dataset=ds_name,
                    operation=operation,
                    definition=definition,
                )
        del_table = None
        if deletions is not None:
            if isinstance(deletions, pa.Table):
                del_table = deletions
            else:
                del_ids = [item['source_id'] if isinstance(item, dict) else str(item) for item in deletions]
                del_table = pa.Table.from_pylist(
                    [dict(source_id=k) for k in del_ids],
                    schema=pa.schema([pa.field('source_id', pa.string(), nullable=False)]),
                ) if del_ids else None
        base_id = base_pin['id'] if isinstance(base_pin, dict) else base_pin
        return self.native.update_table(
            table,
            dataset=ds_name,
            operation=operation,
            definition=definition,
            base=base_id,
            keys=['source_id'],
            merge=DEPENDENCY_SOURCE_MERGE_SPEC,
            deletions=del_table,
        )

    def prepare_partitioned_aliases(self, rows_or_table, *, dataset=None, operation='aliases',
                                    definition='catalog-dependencies-partitioned-v1',
                                    base_pin=None, deletions=None,
                                    bucket_count=DEPENDENCY_BUCKET_COUNT):
        """Maintain reverse alias memberships in a single bucket-partitioned DocSpec dataset."""
        return self.memberships.prepare_partitioned_table(
            self.native,
            rows_or_table,
            dataset=dataset or f'{self.namespace}-aliases-partitioned',
            operation=operation,
            definition=definition,
            base_pin=base_pin,
            deletions=deletions,
            bucket_count=bucket_count,
        )
