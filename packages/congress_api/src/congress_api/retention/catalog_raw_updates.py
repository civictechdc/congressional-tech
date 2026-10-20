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
from .catalog_batches import can_read_catalog_schema
from .catalog_publication import CatalogSnapshot, MANIFEST_KEY, FILENAMES, DOCUMENTS
from .catalog_selection import NativeCatalogSnapshot, read_native_catalog
from .catalog_staging import WorkingCatalog
from .catalog_updates import update_native_catalog
from .document_evidence import read_retained_body
from .document_recovery import recover_sources
from .immutable_metadata import encoded
from .raw_values import NATIVE_CAPTURE_SCHEMA
from .raw_archive import STATE_KEY
from .source_observations import SourceObservationStorage, dependency_id, hearing_records
from .source_replay import prepare_source_replay
from .source_update_proof import retain_source_update, read_source_update, source_update_requirements

MAX_ROWS, MAX_BYTES = 8192, 16 << 20


def update_from_raw(store, *, raw_storage, directory, candidate, expected_bodies=(), seeds=()):
    """Replay exact raw changes and publish one coherent catalog selection.

    The caller owns a retained operation directory and immutable candidate name.
    Existing file catalogs and unqualified receipt/body inventories require explicit
    adoption. No branch reads legacy capture/state files or a global processing cache.
    """
    if raw_storage.store is not store:
        raise ValueError('Raw/catalog dispatch must share one guarded store owner')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    seeds = list(seeds)
    seed_sha = sha256(encoded(seeds)).hexdigest()
    raw = raw_storage.snapshot()
    request = dict(candidate=candidate, raw_identity=raw.identity, expected_bodies=sorted(set(expected_bodies)),
                   seed_sha256=seed_sha, requirements=source_update_requirements())
    pending = directory / 'source-update.json'
    with ExitStack() as owners:
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
        if not native_previous and (previous.manifest is not None or previous.files):
            raise ValueError('Existing file catalog requires exact catalog and source contribution adoption')
        if native_previous and before is None:
            raise ValueError('Selected catalog requires qualified retained source contribution adoption')
        if before is not None and (before.get('requirements') != source_update_requirements()
                or before.get('seed_sha256') != seed_sha):
            raise ValueError('Source interpretation rules or seeds changed; qualify explicit contribution adoption')
        dependencies = CatalogDependencyStorage.for_snapshot(previous) if native_previous else None
        if pending.exists():
            retained = json.loads(pending.read_bytes())
            if retained['request'] != request:
                raise ValueError('Raw catalog continuation inputs differ from the retained candidate')
            proof = read_source_update(store, retained['source_update'])
            with pq.ParquetFile(directory / 'interpreted-sources.parquet') as file:
                rows = [row for batch in file.iter_batches(batch_size=256) for row in batch.to_pylist()]
                if dependencies is None:
                    dependencies = CatalogDependencyStorage(native=raw_storage.native, store=store,
                        namespace=proof['after']['catalog_namespace'], source_schema=file.schema_arrow,
                        max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
            result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
                replacements=rows, deletions=proof['deletions'], candidate=candidate, directory=directory / 'catalog',
                max_chunk_rows=MAX_ROWS, max_chunk_bytes=MAX_BYTES, rules=request['requirements'],
                expected_bodies=request['expected_bodies'], source_update=retained['source_update'])
            return dict(result, raw_identity=raw.identity)
        if before is not None and before['raw_identity'] == raw.identity:
            result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
                candidate=candidate, directory=directory / 'catalog', max_chunk_rows=MAX_ROWS,
                max_chunk_bytes=MAX_BYTES, rules=request['requirements'], expected_bodies=request['expected_bodies'])
            return dict(result, raw_identity=raw.identity)
        changes = list(raw.changes_since(before['raw_identity'] if before else raw_storage.empty_identity))
        changed_urls = {url for change in changes for url in raw.changed_state_urls(change)}
        changed_packages = {package for url in changed_urls for package in package_dependencies(dict(source_url=url))}
        namespace = before['namespace'] if before else 'catalog-source-observations-v1'
        observations = SourceObservationStorage(native=raw_storage.native, store=store, namespace=namespace,
            max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
        with TemporaryDirectory(prefix='source-replay-', dir=directory) as attempt:
            prepared = prepare_source_replay(store, snapshot=raw, changes=changes, observations=observations,
                root=before['root'] if before else None, directory=Path(attempt),
                read_body=lambda key: read_retained_body(None, key, read_compressed=store.read), seeds=seeds,
                changed_dependencies=tuple(dependency_id('package', value) for value in sorted(changed_packages)))
            if prepared is not None:
                owners.callback(prepared.close)
            rows = list(prepared.sources()) if prepared else []
            old_ids = set(prepared.old_source_ids) if prepared else set()
            captures = prepared.captures if prepared else pa.Table.from_pylist([], schema=NATIVE_CAPTURE_SCHEMA)
            hearings = list(hearing_records(captures, store.read))
            packages = changed_packages | {package for row in rows for package in package_dependencies(row)}
            packages.update(package for record, _, _ in hearings for package in hearing_input_packages(record))
            urls = set(changed_urls)
            if dependencies is not None:
                selected = dependencies.selected(previous.selection['dependency'])
                replayed = set(old_ids)
                present = {index.source_identity(row) for row in rows}
                records = (record for url in changed_urls
                           for record in dependencies.sources_at_url(previous.selection['dependency'], url))
                package_records = (record for package in sorted(packages)
                    for record in dependencies.sources_at_package(previous.selection['dependency'], package))
                for record in chain(records, package_records):
                    old_ids.add(record['source_id'])
                    if record['source_values'].get('source_url'):
                        urls.add(record['source_values']['source_url'])
                    state_backed = (record['source_values'].get('filename_origins') == ['download_state']
                                    and record['source_values'].get('source_paths') == [STATE_KEY])
                    # The API receipt owns availability associations, not these
                    # independently retained raw-state response facts.
                    if record['source_id'] not in present and (record['source_id'] not in replayed or state_backed):
                        rows.append(record['source_values'])
                        present.add(record['source_id'])
                old_rows = [row for identity in old_ids if (row := selected.source(identity)) is not None]
                old_ids = {index.source_identity(row) for row in old_rows}
            else:
                old_rows = []
            if prepared is not None:
                rows = list(recover_sources(rows, captures, read_receipt=store.read, working=prepared.working, source_observer=prepared.trace))
            urls.update(row['source_url'] for row in rows if row.get('source_url'))
            state = pa.Table.from_pylist(list(raw.states_for(urls).values()), schema=raw_storage.state_schema)
            rows = list(annotate_availability(rows, state, hearing_records=((record, captures) for record, captures, _ in hearings)))
            if prepared is not None:
                # State-backed API rows inherit only availability association
                # ownership. Their response facts remain the selected raw state.
                for row in rows:
                    if hearing_package(row.get('source_url')):
                        path = urlsplit(row['source_url']).path.rstrip('/')
                        for record, _, receipt in hearings:
                            if not isinstance(record, dict):
                                continue
                            url = record.get('requested_url') or record.get('url') or record.get('_url')
                            if url and urlsplit(url).path.rstrip('/') == path:
                                prepared.trace.source(row, receipt)
                prepared.after = observations.prepare(before['root'] if before else None, prepared.trace)
            # These exact selected capture readings are supplied by RawStorage's
            # qualified lookup. Missing qualification refuses before catalog CAS.
            if not callable(getattr(raw, 'body_readings', None)):
                raise ValueError('Selected raw archive requires qualified retained body-reading lookup')
            readings = list(raw.body_readings({row['body_key'] for row in rows if row.get('body_key')}))
            output = Path(attempt) / 'interpreted'
            (output / 'indexes').mkdir(parents=True)
            work = owners.enter_context(_working(Path(attempt) / 'filename.sqlite'))
            prior = pa.Table.from_pylist(old_rows, schema=dependencies.source_schema) if dependencies else None
            # Grouping identities are derived scalars, not filename metadata
            # lists. Recompute them from the preserved source facts below.
            inputs = ({key: value for key, value in row.items() if key not in {'source_id', 'document_id'}}
                      for row in rows)
            index.write_filename_metadata(output, inputs, working=work, workers=1, previous=prior,
                cache_store=store, retained_body_readings=readings)
            file = pq.ParquetFile(output / 'indexes/document-filenames.parquet')
            values = [row for batch in file.iter_batches(batch_size=256) for row in batch.to_pylist()]
            schema = file.schema_arrow
            file.close()
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
                    namespace=catalog_namespace, source_schema=logical, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
                values = pa.Table.from_pylist(values, schema=logical).to_pylist()
                schema = logical
            ids = {index.source_identity(row) for row in values}
            deletions = sorted(old_ids - ids)
            after = dict(namespace=namespace, catalog_namespace=catalog_namespace,
                root=prepared.after if prepared else before['root'] if before else None,
                raw_identity=raw.identity, seed_sha256=seed_sha, max_rows=MAX_ROWS, max_bytes=MAX_BYTES, requirements=request['requirements'])
            reference = retain_source_update(store, base=previous.identity, before=before, after=after,
                schema=schema, replacements=values, deletions=deletions, observations=prepared.observations if prepared else ())
            pq.write_table(pa.Table.from_pylist(values, schema=schema), directory / 'interpreted-sources.parquet')
            draft = directory / 'source-update.tmp'
            draft.write_bytes(encoded(dict(request=request, source_update=reference)))
            draft.replace(pending)
        result = update_native_catalog(store, native=raw_storage.native, previous=previous, dependencies=dependencies,
            replacements=values, deletions=deletions, candidate=candidate, directory=directory / 'catalog',
            max_chunk_rows=MAX_ROWS, max_chunk_bytes=MAX_BYTES, rules=request['requirements'],
            expected_bodies=request['expected_bodies'], source_update=reference)
        return dict(result, raw_identity=raw.identity)


from contextlib import contextmanager
@contextmanager
def _working(path):
    working = WorkingCatalog(path)
    try:
        yield working
    finally:
        working.close()
