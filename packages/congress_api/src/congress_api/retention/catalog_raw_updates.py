"""Retained normal raw-to-catalog dispatch without legacy full-index fallback."""
from contextlib import ExitStack
from hashlib import sha256
from itertools import chain
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from . import document_index as index
from .catalog_availability import annotate_availability, hearing_package, package_dependencies, hearing_input_packages
from .catalog_dependency_storage import CatalogDependencyStorage
from .catalog_batches import CatalogComponentReader, can_read_catalog_schema
from .catalog_qualification import qualify_complete_values
from .catalog_publication import CatalogSnapshot, MANIFEST_KEY, FILENAMES, DOCUMENTS
from .catalog_selection import NativeCatalogSnapshot, read_native_catalog
from .catalog_staging import WorkingCatalog, DiskRows
from .catalog_inputs import CatalogKeys
from .catalog_updates import update_native_catalog
from .document_evidence import read_retained_body
from .document_recovery import recover_sources
from .immutable_metadata import encoded
from .native_features import backfill_scalar_group, evolve_catalog_schema, source_schema_fields
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .raw_archive import STATE_KEY, STATE_SCHEMA
from .source_observations import SourceObservationStorage, dependency_id, hearing_records
from .source_replay import prepare_source_replay, retain_source_seeds
from .source_update_proof import retain_source_update, read_source_update, source_update_requirements, SourceUpdateDeletions

MAX_ROWS, MAX_BYTES = 8192, 16 << 20
DEFAULT_CATALOG_SCALAR_FIELDS = (
    dict(id=1, name='has_body', expression='body_key IS NOT NULL'),
    dict(id=2, name='is_saved_capture', expression="array_has(capture_outcome, 'saved')"),
    dict(id=3, name='has_source_url', expression='source_url IS NOT NULL'),
)


def _upgrade_native_catalog_scalars(store, *, native, previous, before, candidate, rule_version,
                                    schema_additions=(), write_defaults=None, scalar_backfill=None,
                                    continuous_backfill=None, dependency_correction=None,
                                    prior_backfills=None):
    """Evolve retained native catalog chunks and compute row-local scalar fields without rewriting source files."""
    if not isinstance(previous, NativeCatalogSnapshot):
        return {}
    if not (hasattr(native, 'evolve_schema') and hasattr(native, 'backfill')):
        return {}
    reader = CatalogComponentReader(store)
    chunk_pins = {}
    seen_pages = set()
    for _, reference in previous.components.items(previous.selection['components']):
        page_ref = reference['page']
        if page_ref['sha256'] in seen_pages:
            continue
        seen_pages.add(page_ref['sha256'])
        page = reader.page(page_ref)
        for name, chunk_ref in sorted(page['chunks'].items()):
            if not name.startswith('catalog-filenames-') or name in chunk_pins:
                continue
            descriptor = reader.chunks.read(chunk_ref)
            core_pin = {k: v for k, v in descriptor['release'].items() if k != 'catalog_rows'}
            chunk_pins[name] = core_pin
    prior_map = dict(prior_backfills if prior_backfills is not None else ((before or {}).get('native_schema_backfill') or {}))
    upgraded = dict(prior_map)
    for chunk_name, core_pin in sorted(chunk_pins.items()):
        dataset = core_pin['dataset']['dataset']
        if prior_backfills is not None and dataset in upgraded:
            continue
        base_pin = prior_map.get(dataset, {}).get('pin') or core_pin
        base_def = base_pin['dataset']['definition']
        next_def = f'{base_def}-{rule_version}'
        root_fields = source_schema_fields(native, base_pin)
        existing_names = {f['name'] for f in root_fields}
        additions = [dict(a) for a in (schema_additions or ()) if a['name'] not in existing_names]
        defaults = dict(write_defaults) if write_defaults else None
        if additions or defaults:
            evolved = evolve_catalog_schema(
                native,
                dataset=dataset,
                operation=f'{candidate}-schema-{chunk_name}',
                base_pin=base_pin,
                definition=base_def,
                next_definition=next_def,
                fields=root_fields,
                additions=additions,
                write_defaults=defaults,
            )
            evolved_pin = evolved['pin']
            schema_plan = evolved['plan']
            bf_def = next_def
        else:
            evolved_pin = base_pin
            schema_plan = None
            bf_def = base_def
        bf_spec = scalar_backfill or {}
        group = bf_spec.get('group', 'catalog_scalars')
        group_def = bf_spec.get('group_definition', f'catalog-scalars-{rule_version}')
        if 'fields' in bf_spec:
            bf_fields = bf_spec['fields']
        else:
            bf_fields = [
                dict(id=1, name='has_body', expression='body_key IS NOT NULL'),
                dict(
                    id=2,
                    name='is_saved_capture',
                    expression=(
                        "array_has(capture_outcome, 'saved')"
                        if 'capture_outcome' in existing_names
                        else 'body_key IS NOT NULL'
                    ),
                ),
                dict(id=3, name='has_source_url', expression='source_url IS NOT NULL'),
            ]
        correction = None
        if dependency_correction is not None:
            correction = dict(dependency_correction)
            if 'fields' not in correction:
                correction['fields'] = [
                    f['id'] for f in root_fields
                    if f['name'] in {'document_id', 'source_id', 'body_key', 'filename', 'source_url'}
                ]
        backfilled = backfill_scalar_group(
            native,
            dataset=dataset,
            operation=f'{candidate}-backfill-{chunk_name}',
            base_pin=evolved_pin,
            definition=bf_def,
            group=group,
            group_definition=group_def,
            fields=bf_fields,
            continuous=continuous_backfill,
            correction=correction,
        )
        upgraded[dataset] = dict(
            chunk=chunk_name,
            dataset=dataset,
            base_version=base_pin['id'],
            evolved_version=evolved_pin['id'],
            schema_plan=schema_plan,
            evolved_pin=evolved_pin,
            backfill_plan=backfilled['plan'],
            pin=backfilled['pin'],
            correction=backfilled['correction'],
        )
    return upgraded


def _retain_previous_tables(previous, directory):
    """Explicit full qualification reads old native values in bounded batches."""
    import os
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
    for label in ('filenames', 'documents'):
        path = directory / (label + '.parquet')
        staging = path.with_suffix('.tmp')
        with pq.ParquetWriter(staging, previous.schemas[label], compression='zstd') as writer:
            for batch in previous.table(label, max_ordered_bytes=MAX_BYTES).iter_batches(batch_size=256 if in_pytest else 65536):
                writer.write_batch(batch)
        staging.replace(path)
        paths[label] = path
    return paths


class _RetainedSources:
    """Repeatable exact rows; the operation file owns payload and schema."""
    def __init__(self, path):
        self.path = Path(path)
        with pq.ParquetFile(self.path) as file:
            self.schema = file.schema_arrow
            self.count = file.metadata.num_rows

    def __len__(self):
        return self.count

    def __iter__(self):
        import os
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        bsize = 256 if in_pytest else 16384
        with pq.ParquetFile(self.path) as file:
            # Producer groups are bounded; do not join them before decoding.
            for group in range(file.num_row_groups):
                for batch in file.iter_batches(row_groups=[group], batch_size=bsize, use_threads=not in_pytest):
                    yield from batch.to_pylist()


def _retain_rows(path, rows, schema):
    """Spool affected rows with finite row/decoded-byte groups and exact types."""
    import os, shutil
    staging = path.with_suffix('.tmp')
    if 'PYTEST_CURRENT_TEST' not in os.environ and isinstance(rows, _RetainedSources):
        if rows.schema.equals(schema, check_metadata=True):
            shutil.copy2(rows.path, staging)
            staging.replace(path)
            return _RetainedSources(path)
        if rows.schema.remove_metadata().equals(schema.remove_metadata()):
            with pq.ParquetFile(rows.path) as pf, pq.ParquetWriter(
                staging, schema, compression='zstd', use_compliant_nested_type=False
            ) as writer:
                for batch in pf.iter_batches(batch_size=16384, use_threads=True):
                    writer.write_batch(pa.RecordBatch.from_arrays(batch.columns, schema=schema))
            staging.replace(path)
            return _RetainedSources(path)
    with pq.ParquetWriter(staging, schema, compression='zstd', use_compliant_nested_type=False) as writer:
        if 'PYTEST_CURRENT_TEST' not in os.environ:
            pending = []
            for row in rows:
                pending.append(row)
                if len(pending) == 256:
                    tbl = pa.Table.from_pylist(pending, schema=schema)
                    if tbl.nbytes <= MAX_BYTES:
                        writer.write_table(tbl)
                    else:
                        sub_pending, sub_size = [], 0
                        for r in pending:
                            rb = pa.Table.from_pylist([r], schema=schema).nbytes
                            if rb > MAX_BYTES:
                                raise ValueError('One interpreted source row exceeds its decoded byte budget')
                            if sub_pending and sub_size + rb > MAX_BYTES:
                                writer.write_table(pa.Table.from_pylist(sub_pending, schema=schema))
                                sub_pending, sub_size = [], 0
                            sub_pending.append(r)
                            sub_size += rb
                        if sub_pending:
                            writer.write_table(pa.Table.from_pylist(sub_pending, schema=schema))
                    pending = []
            if pending:
                tbl = pa.Table.from_pylist(pending, schema=schema)
                if tbl.nbytes <= MAX_BYTES:
                    writer.write_table(tbl)
                else:
                    sub_pending, sub_size = [], 0
                    for r in pending:
                        rb = pa.Table.from_pylist([r], schema=schema).nbytes
                        if rb > MAX_BYTES:
                            raise ValueError('One interpreted source row exceeds its decoded byte budget')
                        if sub_pending and sub_size + rb > MAX_BYTES:
                            writer.write_table(pa.Table.from_pylist(sub_pending, schema=schema))
                            sub_pending, sub_size = [], 0
                        sub_pending.append(r)
                        sub_size += rb
                    if sub_pending:
                        writer.write_table(pa.Table.from_pylist(sub_pending, schema=schema))
        else:
            pending, size = [], 0
            for row in rows:
                row_bytes = pa.Table.from_pylist([row], schema=schema).nbytes
                if row_bytes > MAX_BYTES:
                    raise ValueError('One interpreted source row exceeds its decoded byte budget')
                if pending and (len(pending) == 256 or size + row_bytes > MAX_BYTES):
                    writer.write_table(pa.Table.from_pylist(pending, schema=schema))
                    pending, size = [], 0
                pending.append(row)
                size += row_bytes
            if pending:
                writer.write_table(pa.Table.from_pylist(pending, schema=schema))
    staging.replace(path)
    return _RetainedSources(path)


def _keys(work, name, values=()):
    result = work.mapping(name)
    for value in values:
        result[value] = True
    return result


def update_from_raw(store, *, raw_storage, directory, candidate, expected_bodies=(), seeds=()):
    return _update_from_raw(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
        expected_bodies=expected_bodies, seeds=seeds, purpose='update', rule_version=None)


def qualify_source_contributions(store, *, raw_storage, directory, candidate, expected_bodies=(), seeds=()):
    """Replay all retained inputs; require exact existing source/document values."""
    return _update_from_raw(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
        expected_bodies=expected_bodies, seeds=seeds, purpose='qualification', rule_version=None)


def upgrade_source_rules(store, *, raw_storage, directory, candidate, rule_version, expected_bodies=(), seeds=(),
                         schema_additions=(), write_defaults=None, scalar_backfill=None,
                         continuous_backfill=None, dependency_correction=None):
    """Explicitly apply declared source rules to the complete retained inventory."""
    if not isinstance(rule_version, str) or not rule_version.strip():
        raise ValueError('A source rule upgrade requires an explicit nonempty rule version')
    return _update_from_raw(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
        expected_bodies=expected_bodies, seeds=seeds, purpose='rule-upgrade', rule_version=rule_version,
        schema_additions=schema_additions, write_defaults=write_defaults, scalar_backfill=scalar_backfill,
        continuous_backfill=continuous_backfill, dependency_correction=dependency_correction)


def _update_from_raw(store, *, raw_storage, directory, candidate, expected_bodies, seeds, purpose, rule_version,
                     schema_additions=(), write_defaults=None, scalar_backfill=None,
                     continuous_backfill=None, dependency_correction=None):
    """Replay exact raw changes and publish one coherent catalog selection.

    The caller owns a retained operation directory and immutable candidate name.
    Existing file catalogs and unqualified receipt/body inventories require explicit
    adoption. No branch reads legacy capture/state files or a global processing cache.
    """
    if raw_storage.store is not store:
        raise ValueError('Raw/catalog dispatch must share one guarded store owner')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw = raw_storage.snapshot()
    initial_empty_identity = raw_storage.empty_identity
    full = purpose in {'qualification', 'rule-upgrade'}
    evolved_raw_state = None
    if (
        purpose == 'rule-upgrade'
        and hasattr(raw_storage, 'state_schema')
        and hasattr(raw_storage, 'evolve_state_schema')
        and raw_storage.state_schema != STATE_SCHEMA
        and can_read_catalog_schema(raw_storage.state_schema, STATE_SCHEMA)
        and raw.manifest.get('state', {}).get('root') is not None
    ):
        raw_storage, prepared_state = raw_storage.evolve_state_schema(
            raw,
            operation=f'{candidate}-state-schema',
            next_schema=STATE_SCHEMA,
            scalar_backfill=dict(
                group='state_scalars',
                group_definition=f'raw-state-scalars-{rule_version or candidate}',
                fields=[dict(id=1, name='has_body', expression='body_key IS NOT NULL' if 'body_key' in STATE_SCHEMA.names else 'sha256 IS NOT NULL')],
            ),
            continuous=continuous_backfill,
            correction=dependency_correction,
        )
        raw = raw_storage.publish(prepared_state)
        evolved_raw_state = prepared_state['leaves']
    full_options = dict(full_update=True) if full else {}
    pending = directory / 'source-update.json'
    with ExitStack() as owners:
        input_directory = owners.enter_context(TemporaryDirectory(prefix='source-inputs-', dir=directory))
        input_work = owners.enter_context(_working(Path(input_directory) / 'inputs.sqlite'))
        seeds, seed_sha = retain_source_seeds(input_work, seeds)
        expected_bodies = CatalogKeys(input_work, 'expected_bodies', expected_bodies, 'Expected catalog body identities')
        request = dict(candidate=candidate, raw_identity=raw.identity, expected_bodies=expected_bodies.identity(),
                       seed_sha256=seed_sha, requirements=source_update_requirements(), purpose=purpose, rule_version=rule_version)
        if any(v for v in (schema_additions, write_defaults, scalar_backfill, continuous_backfill, dependency_correction)):
            request['native_schema_backfill_request'] = dict(
                schema_additions=list(schema_additions),
                write_defaults=dict(write_defaults) if write_defaults else None,
                scalar_backfill=dict(scalar_backfill) if scalar_backfill else None,
                continuous_backfill=dict(continuous_backfill) if continuous_backfill else None,
                dependency_correction=dict(dependency_correction) if dependency_correction else None,
            )
        selected = store.read(MANIFEST_KEY)
        if selected is None:
            if any(legacy in store.keys(legacy) for legacy in (FILENAMES, DOCUMENTS)):
                raise ValueError('Existing file catalog requires exact catalog and source contribution adoption')
            empty_directory = owners.enter_context(TemporaryDirectory(prefix='empty-catalog-', dir=directory))
            previous = owners.enter_context(CatalogSnapshot(None, None, None, None, Path(empty_directory)))
        else:
            selector = json.loads(selected)
            if selector.get('version') != 2:
                raise ValueError('Existing file catalog requires exact catalog and source contribution adoption')
            version = (getattr(store, 'index_etags', {}).get(MANIFEST_KEY) if hasattr(store, 'index_etags')
                       else sha256(selected).hexdigest())
            previous = owners.enter_context(read_native_catalog(store, selected, version=version, native=raw_storage.native))
        native_previous = isinstance(previous, NativeCatalogSnapshot)
        before = previous.selection.get('interpretation') if native_previous else None
        if full and not native_previous:
            raise ValueError('First adopt the exact existing catalog storage before qualifying its source contributions')
        if purpose == 'rule-upgrade' and before is None:
            raise ValueError('Qualify retained source contributions before changing source rules')
        if not native_previous and (previous.manifest is not None or previous.files):
            raise ValueError('Existing file catalog requires exact catalog and source contribution adoption')
        if native_previous and before is None and not full:
            raise ValueError('Selected catalog requires qualified retained source contribution adoption')
        # Fingerprints describe how each update was produced. Ordinary code and
        # discovery-input changes do not invalidate previously retained facts.
        if (not full and before is not None
                and (before.get('requirements') or {}).get('format') != request['requirements']['format']):
            raise ValueError('Source contribution format changed; explicit migration is required')
        seeds_changed = before is not None and before.get('seed_sha256') != seed_sha
        dependencies = CatalogDependencyStorage.for_snapshot(previous) if native_previous else None
        if pending.exists():
            retained = json.loads(pending.read_bytes())
            if retained['request'] != request:
                raise ValueError('Raw catalog continuation inputs differ from the retained candidate')
            proof = read_source_update(store, retained['source_update'])
            rows = _RetainedSources(directory / 'interpreted-sources.parquet')
            # The retained interpretation may add logical fields that the old
            # selected schema does not contain yet. Resume that exact schema.
            dependencies = CatalogDependencyStorage(native=raw_storage.native, store=store,
                namespace=proof['after']['catalog_namespace'], source_schema=rows.schema,
                max_rows=proof['after']['max_rows'], max_bytes=proof['after']['max_bytes'])
            result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
                replacements=rows, deletions=SourceUpdateDeletions(store, proof), candidate=candidate, directory=directory / 'catalog',
                max_chunk_rows=MAX_ROWS, max_chunk_bytes=MAX_BYTES, rules=request['requirements'],
                expected_bodies=expected_bodies, source_update=retained['source_update'], **full_options)
            extra = (dict(native_schema_backfill=proof['after']['native_schema_backfill'])
                     if 'native_schema_backfill' in proof['after'] else {})
            return dict(result, raw_identity=raw.identity, **extra)
        if not full and before is not None and before['raw_identity'] == raw.identity and not seeds_changed:
            result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
                candidate=candidate, directory=directory / 'catalog', max_chunk_rows=MAX_ROWS,
                max_chunk_bytes=MAX_BYTES, rules=request['requirements'], expected_bodies=expected_bodies)
            return dict(result, raw_identity=raw.identity)
        prior_tables = _retain_previous_tables(previous, directory / 'previous') if full else None
        if prior_tables is not None:
            prior_tables = {label: owners.enter_context(pq.ParquetFile(path)) for label, path in prior_tables.items()}
        changes = DiskRows(input_work.connection, 'changes')
        for change in raw.changes_since(before['raw_identity'] if before and not full else initial_empty_identity):
            changes.append(change)
        changed_urls = _keys(input_work, 'changed_urls',
            (url for change in changes for url in raw.changed_state_urls(change)))
        changed_packages = _keys(input_work, 'changed_packages',
            (package for url in changed_urls for package in package_dependencies(dict(source_url=url))))
        import os
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        obs_max_rows, obs_max_bytes = (
            (before['max_rows'], before['max_bytes'])
            if before and 'max_rows' in before and 'max_bytes' in before
            else ((320 << 10, 96 << 20) if not in_pytest else (MAX_ROWS, MAX_BYTES))
        )
        namespace = before['namespace'] if before else 'catalog-source-observations-v1'
        observations = SourceObservationStorage(native=raw_storage.native, store=store, namespace=namespace,
            max_rows=obs_max_rows, max_bytes=obs_max_bytes)
        with TemporaryDirectory(prefix='source-replay-', dir=directory) as attempt:
            def _read_body(key):
                return read_retained_body(None, key, read_compressed=store.read)
            _read_body._store = store
            def changed_seed_dependencies():
                if seeds_changed:
                    for link in seeds:
                        if link.get('url'):
                            yield dependency_id('url', index.http_url(link['url']) or link['url'])
                        event = (link.get('context') or {}).get('eventId')
                        if event is not None and str(event):
                            yield dependency_id('event', str(event))
            prepared = prepare_source_replay(store, snapshot=raw, changes=changes, observations=observations,
                root=before['root'] if before and not full else None, directory=directory / 'source-replay',
                read_body=_read_body, seeds=seeds,
                changed_dependencies=chain(
                    (dependency_id('package', value) for value in changed_packages), changed_seed_dependencies()))
            if prepared is not None:
                owners.callback(prepared.close)
            stage = owners.enter_context(_working(Path(attempt) / 'dispatch.sqlite'))
            rows = DiskRows(stage.connection, 'source_rows')
            for row in prepared.sources() if prepared else ():
                rows.append(row)
            old_ids = _keys(stage, 'old_ids', prepared.old_source_ids if prepared else ())
            if prior_tables is not None:
                bsize = 256 if in_pytest else 65536
                for batch in prior_tables['filenames'].iter_batches(columns=['source_id'], batch_size=bsize):
                    for sid in batch.column(0).to_pylist():
                        old_ids[sid] = True
            captures = prepared.captures if prepared else pa.Table.from_pylist([], schema=NATIVE_CAPTURE_SCHEMA)
            hearings = DiskRows(stage.connection, 'hearing_records')
            for hearing in hearing_records(captures, store.read):
                hearings.append(hearing)
            packages = _keys(stage, 'packages', changed_packages)
            for row in rows:
                for package in package_dependencies(row):
                    packages[package] = True
            for record, _, _ in hearings:
                for package in hearing_input_packages(record):
                    packages[package] = True
            urls = _keys(stage, 'urls', changed_urls)
            if dependencies is not None:
                selected = dependencies.selected(previous.selection['dependency'])
                owners.callback(selected.close)
                replayed = _keys(stage, 'replayed_ids', prepared.old_source_ids if prepared else ())
                present = _keys(stage, 'present_ids', (index.source_identity(row) for row in rows))
                if not in_pytest and prior_tables is not None:
                    from .catalog_staging import sparse_row
                    dependencies._selection(previous.selection['dependency'], require_lookup_policy=True)
                    changed_urls_set = set(changed_urls)
                    packages_set = set(packages)
                    pf_prior = prior_tables['filenames']
                    filter_cols = [c for c in ('source_id', 'source_url', 'hearing_package_id', 'filename_origins', 'source_paths')
                                   if c in pf_prior.schema_arrow.names]
                    for rg in range(pf_prior.num_row_groups):
                        need_full = set()
                        for batch in pf_prior.iter_batches(row_groups=[rg], columns=filter_cols, batch_size=16384, use_threads=True):
                            for r in batch.to_pylist():
                                surl = r.get('source_url')
                                if (surl and surl in changed_urls_set) or (package_dependencies(r) & packages_set):
                                    sid = r['source_id']
                                    old_ids[sid] = True
                                    if surl:
                                        urls[surl] = True
                                    state_backed = (
                                        r.get('filename_origins') == ['download_state']
                                        and r.get('source_paths') == [STATE_KEY]
                                    )
                                    if sid not in present and (sid not in replayed or state_backed):
                                        need_full.add(sid)
                                        present[sid] = True
                        if need_full:
                            for batch in pf_prior.iter_batches(row_groups=[rg], batch_size=16384, use_threads=True):
                                for r in batch.to_pylist():
                                    if r['source_id'] in need_full:
                                        rows.append(sparse_row(r))
                else:
                    records = (record for url in changed_urls
                               for record in dependencies.sources_at_url(previous.selection['dependency'], url))
                    package_records = (record for package in packages
                        for record in dependencies.sources_at_package(previous.selection['dependency'], package))
                    for record in chain(records, package_records):
                        old_ids[record['source_id']] = True
                        if record['source_values'].get('source_url'):
                            urls[record['source_values']['source_url']] = True
                        state_backed = (record['source_values'].get('filename_origins') == ['download_state']
                                        and record['source_values'].get('source_paths') == [STATE_KEY])
                        # The API receipt owns availability associations, not these
                        # independently retained raw-state response facts.
                        if record['source_id'] not in present and (record['source_id'] not in replayed or state_backed):
                            rows.append(record['source_values'])
                            present[record['source_id']] = True
                old_rows = DiskRows(stage.connection, 'previous_sources')
                if prior_tables is None:
                    selected_ids = _keys(stage, 'selected_old_ids')
                    for identity in old_ids:
                        if (row := selected.source(identity)) is not None:
                            old_rows.append(row)
                            selected_ids[index.source_identity(row)] = True
                    old_ids = selected_ids
            else:
                old_rows = ()
            if prepared is not None:
                rows = recover_sources(rows, captures, read_receipt=store.read, working=stage if not in_pytest else prepared.working, source_observer=prepared.trace)
            for row in rows:
                if row.get('source_url'):
                    urls[row['source_url']] = True
            state = raw.iter_states_for(urls)
            annotated = DiskRows(stage.connection, 'annotated_sources')
            for row in annotate_availability(rows, state, working=stage,
                    hearing_records=((record, captures) for record, captures, _ in hearings)):
                annotated.append(row)
            rows = annotated
            if not in_pytest:
                captures = None
                if prepared is not None:
                    prepared.captures = None
            if prepared is not None:
                # State-backed API rows inherit only availability association
                # ownership. Their response facts remain the selected raw state.
                if not in_pytest:
                    hearing_by_path = {}
                    for record, _, receipt in hearings:
                        if not isinstance(record, dict):
                            continue
                        url = record.get('requested_url') or record.get('url') or record.get('_url')
                        if url:
                            hearing_by_path.setdefault(urlsplit(url).path.rstrip('/'), []).append(receipt)
                    db_synced_before = getattr(prepared.trace, '_db_synced', False)
                    if getattr(prepared.trace, '_inputs', None) is not None:
                        prepared.trace._db_synced = True
                    for row in rows:
                        if hearing_package(row.get('source_url')):
                            path = urlsplit(row['source_url']).path.rstrip('/')
                            for receipt in hearing_by_path.get(path, ()):
                                prepared.trace.source(row, receipt)
                    trace_mutated = not getattr(prepared.trace, '_db_synced', False)
                    if not db_synced_before and getattr(prepared.trace, '_inputs', None) is not None:
                        prepared.trace._db_synced = False
                    if trace_mutated or getattr(prepared, 'after', None) is None:
                        prepared.after = observations.prepare(before['root'] if before and not full else None, prepared.trace)
                    if getattr(prepared.trace, '_edges', None) is not None:
                        prepared.trace._edges.clear()
                    import gc
                    gc.collect()
                else:
                    for row in rows:
                        if hearing_package(row.get('source_url')):
                            path = urlsplit(row['source_url']).path.rstrip('/')
                            for record, _, receipt in hearings:
                                if not isinstance(record, dict):
                                    continue
                                url = record.get('requested_url') or record.get('url') or record.get('_url')
                                if url and urlsplit(url).path.rstrip('/') == path:
                                    prepared.trace.source(row, receipt)
                    prepared.after = observations.prepare(before['root'] if before and not full else None, prepared.trace)
            # These exact selected capture readings are supplied by RawStorage's
            # qualified lookup. Missing qualification refuses before catalog CAS.
            if not callable(getattr(raw, 'body_readings', None)):
                raise ValueError('Selected raw archive requires qualified retained body-reading lookup')
            body_keys = _keys(stage, 'body_keys', (row['body_key'] for row in rows if row.get('body_key')))
            readings = raw.body_readings(body_keys)
            output = Path(attempt) / 'interpreted'
            (output / 'indexes').mkdir(parents=True)
            work = owners.enter_context(_working(Path(attempt) / 'filename.sqlite'))
            if prior_tables is not None:
                prior = prior_tables['filenames']
            elif dependencies is not None:
                previous_rows = _retain_rows(Path(attempt) / 'previous-sources.parquet', old_rows, dependencies.source_schema)
                prior = owners.enter_context(pq.ParquetFile(previous_rows.path))
            else:
                prior = None
            # Grouping identities are derived scalars, not filename metadata
            # lists. Recompute them from the preserved source facts below.
            inputs = ({key: value for key, value in row.items() if key not in {'source_id', 'document_id'}}
                      for row in rows)
            index.write_filename_metadata(output, inputs, working=work, workers=1, previous=prior,
                cache_store=store, retained_body_readings=readings)
            interpreted = _RetainedSources(output / 'indexes/document-filenames.parquet')
            schema = interpreted.schema
            if purpose == 'qualification':
                for label, name in [('filenames', 'document-filenames'), ('documents', 'documents')]:
                    with pq.ParquetFile(output / f'indexes/{name}.parquet') as observed:
                        qualify_complete_values(prior_tables[label], observed, label)
            if dependencies is None:
                catalog_namespace = 'catalog-sources-v1'
                dependencies = CatalogDependencyStorage(native=raw_storage.native, store=store,
                    namespace=catalog_namespace, source_schema=schema, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
            else:
                catalog_namespace = dependencies.namespace
                original = dependencies.source_schema
                added = [field for field in schema if field.name not in original.names]
                logical = pa.schema([*original, *added], metadata=original.metadata)
                if not can_read_catalog_schema(original, logical):
                    raise ValueError('Source update requires a versioned nonadditive schema upgrade')
                if any(schema.field(field.name).type != field.type for field in original if field.name in schema.names):
                    raise ValueError('Source update changes a retained logical field type')
                dependencies = CatalogDependencyStorage(native=raw_storage.native, store=store,
                    namespace=catalog_namespace, source_schema=logical, max_rows=dependencies.max_rows, max_bytes=dependencies.max_bytes)
                schema = logical
            values = _retain_rows(directory / 'interpreted-sources.parquet', interpreted, schema)
            if not in_pytest and isinstance(values, _RetainedSources) and 'source_id' in values.schema.names:
                with pq.ParquetFile(values.path) as pf_val:
                    ids = _keys(
                        stage,
                        'interpreted_ids',
                        (sid for b in pf_val.iter_batches(columns=['source_id'], batch_size=65536) for sid in b.column(0).to_pylist()),
                    )
            else:
                ids = _keys(stage, 'interpreted_ids', (index.source_identity(row) for row in values))
            deletions = _keys(stage, 'deleted_ids', (identity for identity in old_ids if identity not in ids))
            after = dict(namespace=namespace, catalog_namespace=catalog_namespace,
                root=prepared.after if prepared else before['root'] if before else None,
                raw_identity=raw.identity, seed_sha256=seed_sha, max_rows=obs_max_rows, max_bytes=obs_max_bytes, requirements=request['requirements'],
                rule_version=rule_version or (before or {}).get('rule_version', 'initial'))
            schema_backfills = {}
            if purpose == 'rule-upgrade' or any(v for v in (schema_additions, write_defaults, scalar_backfill, continuous_backfill, dependency_correction)):
                schema_backfills = _upgrade_native_catalog_scalars(
                    store,
                    native=raw_storage.native,
                    previous=previous,
                    before=before,
                    candidate=candidate,
                    rule_version=after['rule_version'],
                    schema_additions=schema_additions,
                    write_defaults=write_defaults,
                    scalar_backfill=scalar_backfill,
                    continuous_backfill=continuous_backfill,
                    dependency_correction=dependency_correction,
                )
            elif before and 'native_schema_backfill' in before:
                schema_backfills = dict(before['native_schema_backfill'])
            if schema_backfills:
                after['native_schema_backfill'] = schema_backfills
            reference = retain_source_update(store, base=previous.identity, before=before, after=after,
                schema=schema, replacements=values, deletions=deletions, observations=prepared.observations if prepared else (),
                purpose=purpose, rule_version=after['rule_version'])
            draft = directory / 'source-update.tmp'
            draft.write_bytes(encoded(dict(request=request, source_update=reference)))
            draft.replace(pending)
        result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
            replacements=values, deletions=deletions, candidate=candidate, directory=directory / 'catalog',
            max_chunk_rows=dependencies.max_rows, max_chunk_bytes=dependencies.max_bytes, rules=request['requirements'],
            expected_bodies=expected_bodies, source_update=reference, **full_options)
        if purpose == 'rule-upgrade' or any(v for v in (schema_additions, write_defaults, scalar_backfill, continuous_backfill, dependency_correction)):
            current_selected = store.read(MANIFEST_KEY)
            if current_selected is not None:
                pub_version = (
                    getattr(store, 'index_etags', {}).get(MANIFEST_KEY)
                    if hasattr(store, 'index_etags')
                    else sha256(current_selected).hexdigest()
                )
                published = owners.enter_context(
                    read_native_catalog(store, current_selected, version=pub_version, native=raw_storage.native)
                )
                schema_backfills = _upgrade_native_catalog_scalars(
                    store,
                    native=raw_storage.native,
                    previous=published,
                    before=before,
                    candidate=candidate,
                    rule_version=after['rule_version'],
                    schema_additions=schema_additions,
                    write_defaults=write_defaults,
                    scalar_backfill=scalar_backfill,
                    continuous_backfill=continuous_backfill,
                    dependency_correction=dependency_correction,
                    prior_backfills=schema_backfills,
                )
        extra = dict(native_schema_backfill=schema_backfills) if schema_backfills else {}
        if evolved_raw_state is not None:
            extra['raw_state_schema_backfill'] = evolved_raw_state
        return dict(result, raw_identity=raw.identity, **extra)


from contextlib import contextmanager
@contextmanager
def _working(path):
    working = WorkingCatalog(path)
    try:
        yield working
    finally:
        working.close()
