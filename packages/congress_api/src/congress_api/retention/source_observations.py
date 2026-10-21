"""Receipt-owned interpretation dependencies selected with catalog source values.

Receipt locators identify observations; event and URL keys identify dependencies.
The disposable SQLite tables below stage only an explicitly affected replay.
Native exact pins and application routing roots retain the durable evidence.
"""
from hashlib import sha256
import json

import pyarrow as pa

from . import document_index as index
from .catalog_dependencies import (
    DependencyGap,
    summarize_alias_observations,
    _aggregate_partition_summaries,
)
from .catalog_memberships import CatalogMemberships
from .immutable_metadata import encoded
from .native_features import inspect_catalog_changes, refresh_catalog_observation_summary
from .source_inputs import collect_source_inputs
from .catalog_availability import package_dependencies, hearing_input_packages

SCHEMA = pa.schema([pa.field('alias', pa.string(), nullable=False),
                    pa.field('observation', pa.string(), nullable=False)])


def observation_id(receipt_key, receipt_line):
    if not isinstance(receipt_key, str) or not receipt_key or type(receipt_line) is not int or receipt_line < 1:
        raise ValueError('Source observation requires an exact positive receipt locator')
    return 'receipt:' + json.dumps([receipt_key, receipt_line], separators=(',', ':'))


def receipt_locator(observation):
    if not isinstance(observation, str) or not observation.startswith('receipt:'):
        raise ValueError('Invalid source observation identity')
    key, line = json.loads(observation[len('receipt:'):])
    if observation_id(key, line) != observation:
        raise ValueError('Noncanonical source observation identity')
    return key, line


def dependency_id(kind, value):
    if kind not in {'event', 'url', 'source', 'source-url', 'capture', 'body', 'package'} or not isinstance(value, str) or not value:
        raise ValueError('Invalid source interpretation dependency')
    return 'dependency:' + json.dumps([kind, value], separators=(',', ':'))


class SourceObservationTrace:
    """Spill exact parent dependencies while the maintained interpreter runs."""
    def __init__(self, working, *, retained=False):
        self.working, self.db = working, working.connection
        if retained:
            for name in ('observation_inputs', 'observation_edges', 'observation_source_owners'):
                if self.db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', name)).fetchone() is None:
                    raise ValueError('Retained source replay omits observation staging')
            return
        self.db.executescript('CREATE TABLE observation_inputs(observation TEXT PRIMARY KEY); '
            'CREATE TABLE observation_edges(observation TEXT,dependency TEXT,access TEXT, '
            'PRIMARY KEY(observation,dependency,access)); '
            'CREATE TABLE observation_source_owners(source TEXT,observation TEXT,PRIMARY KEY(source,observation));')

    def register(self, receipt_key, receipt_line):
        observation = observation_id(receipt_key, receipt_line)
        self.db.execute('INSERT OR IGNORE INTO observation_inputs VALUES (?)', (observation,))
        return observation

    def __call__(self, item):
        observation = self.register(item['receipt_key'], item['receipt_line'])
        if item['access'] not in {'read', 'write'}:
            raise ValueError('Invalid source dependency access')
        self.db.execute('INSERT OR IGNORE INTO observation_edges VALUES (?,?,?)',
            (observation, dependency_id(item['kind'], item['value']), item['access']))

    def observations(self):
        return (row[0] for row in self.db.execute('SELECT observation FROM observation_inputs ORDER BY observation'))

    def edges(self, observation):
        return self.db.execute('SELECT dependency,access FROM observation_edges WHERE observation=? '
                               'ORDER BY dependency,access', (observation,))

    def _source(self, row, observation):
        identity = index.source_identity(row)
        self.db.execute('INSERT OR IGNORE INTO observation_source_owners VALUES (?,?)', (identity, observation))
        key, line = receipt_locator(observation)
        for kind, value, access in [('source', identity, 'write'),
                ('url', index.http_url(row.get('source_url')) or row.get('source_url'), 'read'),
                ('body', row.get('body_key'), 'read'),
                ('source-url', index.http_url(row.get('source_url')) or row.get('source_url'), 'write')]:
            if value:
                self(dict(receipt_key=key, receipt_line=line, kind=kind, value=value, access=access))
        for package in package_dependencies(row):
            self(dict(receipt_key=key, receipt_line=line, kind='package', value=package, access='read'))

    def source(self, row, receipt):
        keys, lines = receipt.get('source_receipt_key') or [], receipt.get('source_receipt_line') or []
        if len(keys) == len(lines) == 1:
            self._source(row, self.register(next(iter(keys)), int(next(iter(lines)))))

    def merged(self, old, new):
        """Follow the maintained placeholder-to-captured-row fact transfer."""
        for observation, in self.db.execute('SELECT observation FROM observation_source_owners WHERE source=?',
                                            (index.source_identity(old),)):
            self._source(new, observation)

    def context(self, row, collector):
        """Bind final source identities to all actual URL context writers.

        Occurrence deduplication intentionally keeps one representative locator.
        The trace retains every emitter before that deduplication, so repeated
        copies and multiple parents still own their exact final source rows.
        """
        url = index.http_url(row.get('source_url')) or row.get('source_url')
        if url:
            for observation, in self.db.execute('SELECT DISTINCT observation FROM observation_edges '
                    'WHERE dependency=? AND access=?', (dependency_id('url', url), 'write')):
                self._source(row, observation)

    def finish(self, sources):
        """Only final emitted source identities own selected contributions."""
        self.db.execute('CREATE TEMP TABLE final_source_owners(source TEXT PRIMARY KEY)')
        for row in sources.values():
            self.db.execute('INSERT OR IGNORE INTO final_source_owners VALUES (?)', (index.source_identity(row),))
        for identity, in self.db.execute('SELECT DISTINCT source FROM observation_source_owners WHERE source NOT IN '
                                         '(SELECT source FROM final_source_owners)'):
            self.db.execute('DELETE FROM observation_edges WHERE dependency=?', (dependency_id('source', identity),))
        self.db.execute('DELETE FROM observation_source_owners WHERE source NOT IN (SELECT source FROM final_source_owners)')
        self.db.execute('DROP TABLE final_source_owners')

    def replay(self, captures, read, read_body, *, seeds=(), retained_capture_inputs=False):
        columns = [name for name in ['receipt_key', 'receipt_line', '_capture_order', 'context_url', 'body_key']
                   if name in index.capture_schema(captures).names]
        for batch in index.capture_batches(captures, columns):
            for row in batch.to_pylist():
                self.register(row['receipt_key'], row['receipt_line'])
                for kind, value, access in [('capture', str(row['_capture_order']) if '_capture_order' in row and not retained_capture_inputs else None, 'write'),
                        ('url', index.http_url(row.get('context_url')) or row.get('context_url'), 'read'),
                        ('body', row.get('body_key'), 'read')]:
                    if value:
                        self(dict(receipt_key=row['receipt_key'], receipt_line=row['receipt_line'],
                                  kind=kind, value=value, access=access))
        context = index.DocumentSources(working=self.working, observe=self)
        index.read_document_sources(captures=captures, read_receipt=read,
                                    read_body=read_body, context=context)
        sources = self.working.mapping('sources')
        collect_source_inputs(sources, context, captures, read, working=self.working,
                              seeds=seeds, source_observer=self)
        # Hearing API records supply availability associations even though they
        # deliberately do not enter the document capture inventory.
        for record, rows, receipt in hearing_records(captures, read):
            for package in hearing_input_packages(record):
                self(dict(receipt_key=next(iter(receipt['source_receipt_key'])),
                          receipt_line=int(next(iter(receipt['source_receipt_line']))),
                          kind='package', value=package, access='write'))
        return sources


def hearing_records(captures, read):
    return index.retained_records(captures, read, family='congress/hearings')


class SourceObservationStorage:
    """Persist event/URL receipt ownership in shared bounded native leaves."""
    def __init__(self, *, native, store, namespace, max_rows, max_bytes):
        self.native, self.max_rows, self.max_bytes = native, max_rows, max_bytes
        self.namespace = namespace
        self.last_change_report = None
        self.last_refresh_summary = None
        self.members = CatalogMemberships(store=store, namespace=namespace, schema=SCHEMA,
            member_column='observation', max_rows=max_rows, max_bytes=max_bytes,
            read=self._read, write=self._write, validate_alias=self._validate_key)

    @staticmethod
    def _validate_key(value):
        if value.startswith(('read:', 'write:')):
            SourceObservationStorage._validate_key(value.split(':', 1)[1])
        elif value.startswith('receipt:'):
            receipt_locator(value)
        elif value.startswith('dependency:'):
            kind, key = json.loads(value[len('dependency:'):])
            if dependency_id(kind, key) != value:
                raise ValueError('Noncanonical dependency identity')
        else:
            raise ValueError('Unknown observation dependency key')

    def _read(self, pin, schema):
        with self.native.source_batches(pin, schema=schema) as reader:
            tables, rows, size = [], 0, 0
            for batch in reader:
                rows, size = rows + len(batch), size + batch.nbytes
                if rows > self.max_rows or size > self.max_bytes:
                    raise DependencyGap('Source observation leaf exceeds its selected budget')
                tables.append(batch)
            return pa.Table.from_batches(tables, schema=schema)

    def _write(self, table, kind):
        identity = sha256(encoded(table.to_pylist())).hexdigest()
        return self.native.run_table(table, dataset='source-observations-' + kind + '-' + identity,
            operation='initial', definition='source-observation-dependencies-v1')

    def prepare(self, root, trace):
        """Replace complete observations; retain every unaffected owner edge."""
        db = trace.db
        db.executescript('DROP TABLE IF EXISTS observation_changes; DROP TABLE IF EXISTS observation_changed_aliases; '
            'CREATE TABLE observation_changes(alias TEXT,member TEXT,PRIMARY KEY(alias,member)); '
            'CREATE TABLE observation_changed_aliases(alias TEXT PRIMARY KEY);')
        def add(alias, member):
            db.execute('INSERT OR IGNORE INTO observation_changed_aliases VALUES (?)', (alias,))
            db.execute('INSERT OR IGNORE INTO observation_changes VALUES (?,?)', (alias, member))
        for observation in trace.observations():
            db.execute('INSERT OR IGNORE INTO observation_changed_aliases VALUES (?)', (observation,))
            for old in self.members.values(root, observation):
                dependency, access = json.loads(old)
                db.execute('INSERT OR IGNORE INTO observation_changed_aliases VALUES (?)', (access + ':' + dependency,))
            for dependency, access in trace.edges(observation):
                add(observation, json.dumps([dependency, access], separators=(',', ':')))
                add(access + ':' + dependency, observation)
        for alias, in db.execute('SELECT alias FROM observation_changed_aliases WHERE alias NOT LIKE ?', ('receipt:%',)):
            for observation in self.members.values(root, alias):
                if db.execute('SELECT 1 FROM observation_inputs WHERE observation=?', (observation,)).fetchone() is None:
                    add(alias, observation)
        class Changes:
            def __iter__(self):
                return (row[0] for row in db.execute('SELECT alias FROM observation_changed_aliases ORDER BY alias'))
            def __getitem__(self, alias):
                return (row[0] for row in db.execute('SELECT member FROM observation_changes WHERE alias=? ORDER BY member', (alias,)))
        changed_aliases = [
            row[0] for row in db.execute('SELECT alias FROM observation_changed_aliases ORDER BY alias')
        ]
        if (
            root is not None
            and changed_aliases
            and hasattr(self.native, 'changes_batches')
            and hasattr(self.native, 'update_table')
        ):
            before_obs_rows = [
                dict(alias=a, observation=m)
                for a in changed_aliases
                for m in self.members.values(root, a)
            ]
            after_obs_rows = [
                dict(alias=a, observation=m)
                for a in changed_aliases
                for (m,) in db.execute(
                    'SELECT member FROM observation_changes WHERE alias=? ORDER BY member',
                    (a,),
                )
            ]
            if before_obs_rows and before_obs_rows != after_obs_rows:
                before_set = {(r['alias'], r['observation']) for r in before_obs_rows}
                after_set = {(r['alias'], r['observation']) for r in after_obs_rows}
                added_obs = [dict(alias=a, observation=m) for (a, m) in sorted(after_set - before_set)]
                removed_obs = [dict(alias=a, observation=m) for (a, m) in sorted(before_set - after_set)]
                scope_hash = sha256(
                    encoded(before_obs_rows) + encoded(after_obs_rows)
                ).hexdigest()[:32]
                obs_ds = f'source-obs-scope-{scope_hash}'
                b_pin = self.native.run_table(
                    pa.Table.from_pylist(before_obs_rows, schema=SCHEMA),
                    dataset=obs_ds,
                    operation='before',
                    definition='source-observation-dependencies-v1',
                )
                a_pin = self.native.update_table(
                    pa.Table.from_pylist(added_obs, schema=SCHEMA),
                    dataset=obs_ds,
                    operation='after',
                    definition='source-observation-dependencies-v1',
                    base=b_pin['id'],
                    keys=['alias', 'observation'],
                    deletions=(
                        pa.Table.from_pylist(removed_obs, schema=SCHEMA)
                        if removed_obs
                        else None
                    ),
                )
                self.last_change_report = inspect_catalog_changes(
                    self.native,
                    b_pin,
                    a_pin,
                    key_column='alias',
                    identity='values',
                    allow_full_fallback=False,
                )
        new_root = self.members.replace(root, Changes())
        if (
            new_root is not None
            and changed_aliases
            and hasattr(self.native, 'refresh')
            and getattr(self.native, 'remote', None) is None
        ):
            for candidate_alias in changed_aliases:
                if self.members.routes.lookup(new_root, candidate_alias)[1] is not None:
                    alias_op = 'sum-' + sha256(
                        json.dumps(new_root, sort_keys=True, default=str).encode('utf-8')
                    ).hexdigest()[:16]
                    alias_ds = (
                        f'{self.namespace}-obs-summary-'
                        f'{sha256(candidate_alias.encode("utf-8")).hexdigest()[:12]}'
                    )
                    self.summarize_alias(
                        new_root,
                        candidate_alias,
                        dataset=alias_ds,
                        operation=alias_op,
                    )
                    break
        return new_root

    def affected(self, before, after, observations, *, working, changed_dependencies=()):
        """Replay changed outputs, including their immutable upstream owners.

        A read dependency needs writers for context. It does not make unrelated
        readers change. Separate reverse read/write keys keep that distinction
        bounded when many pages refer to the same unresolved event identifier.
        """
        # An absent graph contributes no edges. Looking it up would evict the
        # selected graph's validated immutable leaf between closure lookups.
        roots = tuple(root for root in (before, after) if root is not None)
        db = working.connection
        db.executescript('CREATE TABLE affected_observations(observation TEXT PRIMARY KEY,changed INTEGER,done INTEGER); '
            'CREATE TABLE affected_dependencies(dependency TEXT,access TEXT,PRIMARY KEY(dependency,access));')
        def include(observation, changed):
            receipt_locator(observation)
            db.execute('INSERT INTO affected_observations VALUES (?,?,-1) '
                'ON CONFLICT(observation) DO UPDATE SET changed=max(changed,excluded.changed)', (observation, changed))
        def owners(dependency, access, changed):
            if not db.execute('INSERT OR IGNORE INTO affected_dependencies VALUES (?,?)', (dependency, access)).rowcount:
                return
            for root in roots:
                for member in self.members.values(root, access + ':' + dependency):
                    include(member, changed)
        def impact(dependency):
            self._validate_key(dependency)
            owners(dependency, 'read', 1)
            owners(dependency, 'write', 0)
        for observation in observations:
            include(observation, 1)
        for dependency in changed_dependencies:
            impact(dependency)
        while pending := db.execute('SELECT observation,changed FROM affected_observations WHERE done<changed LIMIT 1').fetchone():
            observation, changed = pending
            for root in roots:
                for outgoing in self.members.values(root, observation):
                    dependency, access = json.loads(outgoing)
                    self._validate_key(dependency)
                    if access not in {'read', 'write'}:
                        raise DependencyGap('Invalid persisted dependency access')
                    owners(dependency, 'write', 0)
                    if changed and access == 'write':
                        impact(dependency)
            db.execute('UPDATE affected_observations SET done=? WHERE observation=?', (changed, observation))
        return (row[0] for row in db.execute('SELECT observation FROM affected_observations ORDER BY observation'))

    def summarize_pin(self, source_pin, *, dataset='source-observation-summary',
                      operation=None, base_pin=None, prior_source_pin=None,
                      mode=None, collect_field=None):
        """Maintain or query grouped ``(alias -> total_rows, distinct_observations)`` via ``refresh_catalog_observation_summary``."""
        return summarize_alias_observations(
            self.native,
            source_pin,
            dataset=dataset,
            operation=operation,
            base_pin=base_pin,
            prior_source_pin=prior_source_pin,
            mode=mode,
            keys=('alias',),
            count_field='observation',
            collect_field=collect_field,
        )

    def summarize_alias(self, root, alias, *, dataset='source-observation-summary',
                        operation=None, base_pin=None, prior_source_pin=None,
                        mode=None):
        """Summarize the native leaf pin routed for ``alias`` via ``refresh_catalog_observation_summary``."""
        self._validate_key(alias)
        _, leaf = self.members.routes.lookup(root, alias)
        if leaf is None:
            return None
        if leaf.get('kind') == 'rows':
            partitions = [('', leaf['release'])]
        elif leaf.get('kind') == 'members':
            if alias != leaf.get('alias'):
                return None
            partitions = list(self.members.members.leaf_items(leaf['root']))
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
                    self.summarize_pin(
                        pin,
                        dataset=part_dataset,
                        operation=part_op,
                        base_pin=part_base,
                        prior_source_pin=part_prior,
                        mode=mode,
                    ),
                )
            )
        summary = _aggregate_partition_summaries(part_summaries)
        self.last_refresh_summary = summary
        return summary
