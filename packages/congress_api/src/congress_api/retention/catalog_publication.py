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
from congress_api.retention.catalog_validation import validate_references, CatalogReferenceCheck

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
    from congress_api.retention import document_index as index
    if hasattr(previous, 'selection'):
        raise ValueError('Native catalog updates require the retained scope publication path')
    if not callable(getattr(store, 'put_catalog_manifest', None)) or not callable(getattr(store, 'put_derived_file', None)):
        raise TypeError('Catalog publication requires conditional selector and exclusive immutable file operations')
    if validation is None:
        validation = validate_references(filenames_path, documents_path, validator=index.validate_document_indexes)
    else:
        validation.require(filenames_path, documents_path, validator=index.validate_document_indexes)
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
