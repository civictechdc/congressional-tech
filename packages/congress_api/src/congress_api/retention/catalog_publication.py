"""Select a complete derived catalog with one conditional manifest update.

Retained receipts remain authoritative. The manifest only selects immutable
Parquet files; root files are accepted as migration inputs when it is absent.
"""
from dataclasses import dataclass, field
import base64
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4
import shutil
import tempfile
import weakref

from congress_api.retention.derived_files import file_identity, check_identity

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention import raw_progress as progress

MANIFEST_KEY = 'indexes/catalog.json'
FILENAMES = 'indexes/document-filenames.parquet'
DOCUMENTS = 'indexes/documents.parquet'


@dataclass
class CatalogSnapshot:
    filenames_path: Path | None
    documents_path: Path | None
    manifest: dict | None
    version: str | None
    directory: Path
    files: dict = field(default_factory=dict)
    identity: dict = field(default_factory=lambda: dict(selector_sha256=None, selected_ref=None))
    _cleanup: object = field(init=False, repr=False)

    def __post_init__(self):
        self._cleanup = weakref.finalize(self, shutil.rmtree, self.directory, ignore_errors=True)

    def __enter__(self):
        return self

    def close(self):
        self._cleanup()

    def preserve(self, error):
        self._cleanup.detach()
        error.add_note(f'Owned catalog snapshot retained for diagnosis: {self.directory}')

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.preserve(error)
        else:
            self.close()


def _properties(path, *, identity=None):
    with pq.ParquetFile(path) as source:
        catalog_id = (source.schema_arrow.metadata or {}).get(b'catalog_id')
        if not catalog_id:
            raise ValueError('Catalog file has no catalog_id')
        actual = identity if identity is not None else file_identity(path)
        actual.update(rows=source.metadata.num_rows, catalog_id=catalog_id.decode())
        return actual


def _manifest(data):
    try:
        manifest = json.loads(data)
        generation = manifest['generation']
        if (manifest['version'] != 1 or not isinstance(generation, str)
                or len(generation) != 32 or any(c not in '0123456789abcdef' for c in generation)
                or not isinstance(manifest['catalog_id'], str) or not manifest['catalog_id']):
            raise ValueError('Invalid catalog manifest')
        for label, name in [('filenames', 'document-filenames.parquet'), ('documents', 'documents.parquet')]:
            item = manifest['files'][label]
            if item['key'] != f'catalog-generations/{generation}/{name}':
                raise ValueError('Invalid catalog generation path')
            if (not isinstance(item['rows'], int) or item['rows'] < 0
                    or not isinstance(item['bytes'], int) or item['bytes'] < 0
                    or not isinstance(item['sha256'], str)):
                raise ValueError('Invalid catalog file properties')
        return manifest
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid selected catalog manifest') from error


def _validate(path, item, catalog_id, *, identity=None):
    if path is None:
        raise ValueError(f"Missing selected catalog file: {item['key']}")
    actual = identity or file_identity(path)
    check_identity(actual, item, item['key'])
    properties = _properties(path, identity=actual)
    if properties['rows'] != item['rows'] or properties['catalog_id'] != catalog_id:
        raise ValueError(f"Selected catalog metadata mismatch: {item['key']}")
    return properties


def read_catalog(store, *, read=None, native=None, retained_directory=None):
    """Own verified files until the caller closes the selected snapshot.

    A corrupt selection never falls back to root files. Failed reads preserve
    their owned partials and selector bytes, with the directory in the error.
    Explicit retained inputs must match the live file selector byte-for-byte;
    the maintained file owner checks each file before retaining an owned link.
    """
    read = read or store.read
    selected = read(MANIFEST_KEY)
    version = (getattr(store, 'index_etags', {}).get(MANIFEST_KEY)
               if hasattr(store, 'index_etags') else
               sha256(selected).hexdigest() if selected is not None else None)
    if selected is not None:
        try:
            selector = json.loads(selected)
        except json.JSONDecodeError:
            selector = None  # The existing v1 parser retains its failure behavior.
        if isinstance(selector, dict) and selector.get('version') == 2:
            from .catalog_selection import read_native_catalog
            return read_native_catalog(store, selected, version=version, native=native)
    snapshot = CatalogSnapshot(None, None, None, version,
                               Path(tempfile.mkdtemp(prefix='catalog-snapshot-')))
    try:
        snapshot.identity['selector_sha256'] = sha256(selected).hexdigest() if selected is not None else None
        if selected is not None:
            (snapshot.directory / 'selected.json').write_bytes(selected)
            snapshot.manifest = _manifest(selected)
        if retained_directory is not None:
            retained_directory = Path(retained_directory)
            with (retained_directory / 'catalog-selector.json').open('rb') as source:
                retained_selector = source.read((1 << 20) + 1)
            if snapshot.manifest is None or retained_selector != selected:
                raise ValueError('Retained catalog selector differs from the current selected files')
        for label, legacy in [('filenames', FILENAMES), ('documents', DOCUMENTS)]:
            item = snapshot.manifest['files'][label] if snapshot.manifest else None
            key = item['key'] if item else legacy
            path = snapshot.directory / Path(legacy).name
            if retained_directory is None:
                identity = store.read_derived_file(key, path, expected=item)
            else:
                from .derived_files import retain_verified_file
                identity = retain_verified_file(retained_directory / (label + '.parquet'),
                                                path, expected=item, key=key)
            progress.advance('objects_read')
            progress.advance('bytes_read', identity['bytes'] if identity else 0)
            if item:
                _validate(path if identity else None, item, snapshot.manifest['catalog_id'], identity=identity)
            if identity is not None:
                setattr(snapshot, label + '_path', path)
                identity['key'] = key
                snapshot.files[label] = identity
        return snapshot
    except BaseException as error:
        snapshot.preserve(error)
        raise


def publish_catalog(store, filenames_path, documents_path, *, previous, validation=None):
    """Upload immutable pair, then conditionally select it as the final write."""
    from congress_api.retention.document_index import validate_document_indexes
    if hasattr(previous, 'selection'):
        raise ValueError('Native catalog updates require the retained scope publication path')
    if not callable(getattr(store, 'put_catalog_manifest', None)) or not callable(getattr(store, 'put_derived_file', None)):
        raise TypeError('Catalog publication requires conditional selector and exclusive immutable file operations')
    if validation is None:
        from congress_api.retention.catalog_validation import validate_references
        validation = validate_references(filenames_path, documents_path, validator=validate_document_indexes)
    else:
        validation.require(filenames_path, documents_path, validator=validate_document_indexes)
    paths = {'filenames': Path(filenames_path), 'documents': Path(documents_path)}
    properties = {label: _properties(path) for label, path in paths.items()}
    content_validation = validation.content(properties)
    if accept := getattr(store, 'accept_catalog_validation', None):
        accept(content_validation)
    catalog_id = properties['filenames']['catalog_id']
    if catalog_id != properties['documents']['catalog_id']:
        raise ValueError('Catalog pair has different catalog_id values')
    generation = uuid4().hex
    files = {}
    progress.report('publish_catalog_files', completed=0, total=2, unit='tables')
    for label, name in [('filenames', 'document-filenames.parquet'), ('documents', 'documents.parquet')]:
        key = f'catalog-generations/{generation}/{name}'
        files[label] = {'key': key, **{k: v for k, v in properties[label].items() if k != 'catalog_id'}}
        store.put_derived_file(key, paths[label], expected=properties[label])
        progress.report('publish_catalog_files', completed=len(files), total=2, unit='tables')
    manifest = {'version': 1, 'generation': generation, 'catalog_id': catalog_id, 'files': files}
    data = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    # LocalStore compares the exact manifest read before the build. R2Store's
    # indexes/ conditional write uses the ETag retained by read_catalog.
    progress.report('select_catalog_generation')
    store.put_catalog_manifest(data, expected_version=previous.version)
    progress.report('catalog_published', completed=1, total=1, unit='generations')
    return {'manifest_key': MANIFEST_KEY, 'generation': generation, 'catalog_id': catalog_id,
            'filenames_key': files['filenames']['key'], 'documents_key': files['documents']['key']}


def prepare_native_catalog_chunks(native, chunks, *, label, component, candidate,
                                  schema, max_chunk_rows, max_chunk_bytes, check_references=None,
                                  on_prepared=None, ordered_chunks=True, checkpoint_directory=None, store=None):
    """Retain rewritten bounded chunks as independent native candidates.

    The caller binds ``candidate`` to its exact base, semantic change, application
    rule versions and chunking requirements. Reusing that identity with different
    bytes refuses through native operation conflict. Completed chunks survive a
    later preparation failure. An optional caller-bound local checkpoint skips
    submitting completed chunks again; missing checkpoints retain native replay.

    These descriptors establish neither complete dependency scope nor source /
    document reference validity. The catalog owner supplies those checks before
    the existing application selector may choose a prepared combination.
    """
    from congress_api.retention.catalog_partitions import CatalogTable
    from congress_api.retention.immutable_metadata import encoded

    if (label not in {'filenames', 'documents'} or not isinstance(component, str) or not component
            or not isinstance(candidate, str) or not candidate or not isinstance(schema, pa.Schema)
            or '_catalog_order' in schema.names
            or type(max_chunk_rows) is not int or max_chunk_rows < 1
            or type(max_chunk_bytes) is not int or max_chunk_bytes < 1):
        raise ValueError('Native catalog preparation requires an explicit candidate, schema and chunk budget')
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    import os
    from .catalog_rows import CatalogRows, core_bytes, fits_chunk, FORMAT
    row_owner = CatalogRows(native=native, store=store)
    prepared, last_order = [], None
    in_pytest = 'PYTEST_CURRENT_TEST' in os.environ

    def _finish_chunk(table, dataset, extrema):
        checkpoint, input_digest = None, None
        if checkpoint_directory is not None:
            checkpoint = Path(checkpoint_directory) / (dataset + '.json')
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            input_digest = sha256(sink.getvalue()).hexdigest()
        if checkpoint is not None and checkpoint.exists():
            if checkpoint.stat().st_size > 1 << 20:
                raise ValueError('Retained native catalog chunk exceeds its metadata bound')
            saved = json.loads(checkpoint.read_bytes())
            binding = saved.pop('binding', None)
            if (binding != sha256(encoded(saved)).hexdigest()
                    or saved['input_sha256'] != input_digest or saved['dataset'] != dataset
                    or saved.get('row_format') != FORMAT):
                raise ValueError('Retained native catalog chunk differs from its prepared input')
            release = saved['release']
        else:
            release = row_owner.write(table, dataset=dataset, operation='initial', definition='catalog-chunk-v1',
                max_rows=max_chunk_rows, max_bytes=max_chunk_bytes,
                owner_column='source_id' if label == 'filenames' else 'document_id')
        checked = CatalogTable(schema, [(dataset, release)], native=native)
        if checked.rows != table.num_rows or release['dataset'].get('dataset') != dataset:
            raise ValueError('Prepared native catalog chunk row count differs')
        if checkpoint is not None and not checkpoint.exists():
            saved = dict(dataset=dataset, input_sha256=input_digest, release=release, row_format=FORMAT)
            saved['binding'] = sha256(encoded(saved)).hexdigest()
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            staging = checkpoint.with_suffix('.tmp')
            staging.write_bytes(encoded(saved))
            staging.replace(checkpoint)
        return dict(name=dataset, release=release, rows=table.num_rows,
                    arrow_bytes=core_bytes(table), order_min=extrema['min'], order_max=extrema['max'])

    if in_pytest:
        for index, table in enumerate(chunks):
            if not isinstance(table, pa.Table):
                raise TypeError('Catalog chunks must be typed Arrow tables')
            if not fits_chunk(table, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes):
                raise ValueError('Catalog table exceeds its native chunk budget')
            if (table.column_names.count('_catalog_order') != 1
                    or not pa.types.is_int64(table.schema.field('_catalog_order').type)):
                raise ValueError('Catalog chunk order field must be int64')
            logical = pa.schema([field for field in table.schema if field.name != '_catalog_order'],
                                metadata=table.schema.metadata)
            if not logical.equals(schema, check_metadata=True):
                raise ValueError('Catalog chunk application schema differs')
            order = table['_catalog_order']
            if order.null_count or len(pc.unique(order)) != table.num_rows:
                raise ValueError('Catalog chunk order values must be nonnull and unique')
            if not table.num_rows:
                continue
            extrema = pc.min_max(order).as_py()
            if ordered_chunks and last_order is not None and extrema['min'] <= last_order:
                raise ValueError('Catalog chunk order ranges overlap or are out of order')
            last_order = extrema['max']
            if check_references is not None:
                check_references(table)
            dataset = 'catalog-' + label + '-' + sha256(encoded([candidate, component, index])).hexdigest()
            descriptor = _finish_chunk(table, dataset, extrema)
            prepared.append(descriptor)
            if on_prepared is not None:
                on_prepared(table, descriptor)
        return prepared

    with ThreadPoolExecutor(max_workers=12) as pool:
        inflight = deque()
        for index, table in enumerate(chunks):
            if not isinstance(table, pa.Table):
                raise TypeError('Catalog chunks must be typed Arrow tables')
            if not fits_chunk(table, max_rows=max_chunk_rows, max_bytes=max_chunk_bytes):
                raise ValueError('Catalog table exceeds its native chunk budget')
            if (table.column_names.count('_catalog_order') != 1
                    or not pa.types.is_int64(table.schema.field('_catalog_order').type)):
                raise ValueError('Catalog chunk order field must be int64')
            logical = pa.schema([field for field in table.schema if field.name != '_catalog_order'],
                                metadata=table.schema.metadata)
            if not logical.equals(schema, check_metadata=True):
                raise ValueError('Catalog chunk application schema differs')
            order = table['_catalog_order']
            if order.null_count or len(pc.unique(order)) != table.num_rows:
                raise ValueError('Catalog chunk order values must be nonnull and unique')
            if not table.num_rows:
                continue
            extrema = pc.min_max(order).as_py()
            if ordered_chunks and last_order is not None and extrema['min'] <= last_order:
                raise ValueError('Catalog chunk order ranges overlap or are out of order')
            last_order = extrema['max']
            if check_references is not None:
                check_references(table)
            dataset = 'catalog-' + label + '-' + sha256(encoded([candidate, component, index])).hexdigest()
            inflight.append((table, pool.submit(_finish_chunk, table, dataset, extrema)))
            if len(inflight) >= 12:
                done_table, done_fut = inflight.popleft()
                descriptor = done_fut.result()
                prepared.append(descriptor)
                if on_prepared is not None:
                    on_prepared(done_table, descriptor)
        while inflight:
            done_table, done_fut = inflight.popleft()
            descriptor = done_fut.result()
            prepared.append(descriptor)
            if on_prepared is not None:
                on_prepared(done_table, descriptor)
    return prepared


def _component_binding(component):
    from congress_api.retention.immutable_metadata import encoded
    material = {**component, 'validation': {key: value for key, value in component['validation'].items()
                                          if key != 'binding'}}
    return sha256(encoded(material)).hexdigest()


_COMPONENT_SCHEMA_CACHE = {}


def _component_schema(item):
    try:
        encoded_schema = item['schema']
        if isinstance(encoded_schema, str):
            cached = _COMPONENT_SCHEMA_CACHE.get(encoded_schema)
            if cached is not None:
                return cached
        raw = base64.b64decode(encoded_schema, validate=True)
        parsed = pa.ipc.read_schema(pa.BufferReader(raw))
        if isinstance(encoded_schema, str) and len(_COMPONENT_SCHEMA_CACHE) < 64:
            _COMPONENT_SCHEMA_CACHE[encoded_schema] = parsed
        return parsed
    except (KeyError, TypeError, ValueError, pa.ArrowException) as error:
        raise ValueError('Invalid catalog component application schema') from error


def _require_component(component, *, requirements=None, _binding_verified=False):
    from congress_api.retention.catalog_partitions import CatalogTable
    from congress_api.retention.catalog_validation import CatalogReferenceCheck
    if (not isinstance(component, dict) or component.get('version') != 1
            or not isinstance(component.get('component'), str) or not component['component']
            or not isinstance(component.get('candidate'), str) or not component['candidate']):
        raise ValueError('Invalid native catalog component')
    validation = component.get('validation', {})
    if not isinstance(validation.get('requirements'), dict) or not validation['requirements']:
        raise ValueError('Catalog component validator requirements are missing')
    if requirements is not None and validation['requirements'] != requirements:
        raise ValueError('Catalog component validator requirements changed')
    if not _binding_verified and validation.get('binding') != _component_binding(component):
        raise ValueError('Catalog component validation binding differs')
    membership = validation.get('source_ids_sha256')
    if (not isinstance(membership, str) or len(membership) != 64
            or any(char not in '0123456789abcdef' for char in membership)):
        raise ValueError('Catalog component membership proof is missing')
    counts, schemas = {}, {}
    for label, count in [('filenames', 'source_rows'), ('documents', 'document_rows')]:
        table = component['tables'][label]
        schemas[label] = _component_schema(table)
        filtered = any('components' in chunk for chunk in table['chunks'])
        views = {chunk['name']: dict(components=chunk.get('components', []), rows=chunk['rows'])
                 for chunk in table['chunks']} if filtered else None
        checked = CatalogTable(schemas[label], [(chunk['name'], chunk['release']) for chunk in table['chunks']],
                               native=None, views=views)
        last_order = None
        for chunk in table['chunks']:
            minimum, maximum = chunk['order_min'], chunk['order_max']
            if (type(minimum) is not int or type(maximum) is not int or minimum < 0 or maximum < minimum
                    or not filtered and last_order is not None and minimum <= last_order
                    or filtered and chunk.get('components') != [component['component']]
                    or not filtered and chunk['rows'] != chunk['release']['dataset']['groups']['source']['rows']):
                raise ValueError('Catalog component chunk counts or order differ')
            last_order = maximum
        counts[count] = checked.rows
    CatalogReferenceCheck(schemas['filenames'], schemas['documents'])
    if counts != validation.get('counts') or not counts['source_rows'] or counts['document_rows'] != 1:
        raise ValueError('Catalog component reference counts differ')
    return component


def read_catalog_component(store, reference, *, requirements=None):
    """Read historical evidence; new-selection admission supplies current requirements.

    The admission owner computes requirements once for the entire selection.
    An installed validator upgrade never makes an older exact snapshot unreadable.
    """
    if not isinstance(reference, dict) or 'page' not in reference:
        raise ValueError('Catalog components require an exact proof page member')
    from congress_api.retention.catalog_batches import CatalogComponentReader
    return CatalogComponentReader(store, requirements=requirements).read(reference)


def local_catalog_paths(root):
    """Resolve a local pair without loading either whole Parquet file in memory."""
    root = Path(root)
    selection = root / MANIFEST_KEY
    manifest = _manifest(selection.read_bytes()) if selection.is_file() else None
    paths = []
    ids = []
    for label, legacy in [('filenames', FILENAMES), ('documents', DOCUMENTS)]:
        item = manifest['files'][label] if manifest else None
        path = root / (item['key'] if item else legacy)
        if not path.is_file():
            raise ValueError(f'Missing selected catalog file: {path}')
        properties = _validate(path, item, manifest['catalog_id']) if item else _properties(path)
        ids.append(properties['catalog_id'])
        paths.append(path)
    if ids[0] != ids[1]:
        raise ValueError('Legacy catalog pair has different catalog_id values')
    return tuple(paths)
