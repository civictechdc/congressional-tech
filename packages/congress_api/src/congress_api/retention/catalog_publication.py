"""Select a complete derived catalog with one conditional manifest update.

Retained receipts remain authoritative. The manifest only selects immutable
Parquet files; root files are accepted as migration inputs when it is absent.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import raw_progress as progress

MANIFEST_KEY = 'indexes/catalog.json'
FILENAMES = 'indexes/document-filenames.parquet'
DOCUMENTS = 'indexes/documents.parquet'


@dataclass
class CatalogSnapshot:
    filenames: bytes | None
    documents: bytes | None
    manifest: dict | None
    version: str | None


def _properties(data):
    source = pq.ParquetFile(pa.BufferReader(data))
    catalog_id = (source.schema_arrow.metadata or {}).get(b'catalog_id')
    if not catalog_id:
        raise ValueError('Catalog file has no catalog_id')
    return {'sha256': sha256(data).hexdigest(), 'bytes': len(data),
            'rows': source.metadata.num_rows, 'catalog_id': catalog_id.decode()}


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


def _validate(data, item, catalog_id):
    if data is None:
        raise ValueError(f"Missing selected catalog file: {item['key']}")
    # Check bytes before passing any potentially corrupted file to Parquet.
    if len(data) != item['bytes'] or sha256(data).hexdigest() != item['sha256']:
        raise ValueError(f"Selected catalog checksum mismatch: {item['key']}")
    properties = _properties(data)
    if properties['rows'] != item['rows'] or properties['catalog_id'] != catalog_id:
        raise ValueError(f"Selected catalog metadata mismatch: {item['key']}")


def read_catalog(store, *, read=None):
    """Read the selection once. A corrupt selection never falls back to roots."""
    read = read or store.read
    selected = read(MANIFEST_KEY)
    version = (getattr(store, 'index_etags', {}).get(MANIFEST_KEY)
               if hasattr(store, 'index_etags') else
               sha256(selected).hexdigest() if selected is not None else None)
    if selected is None:
        # Legacy files can be absent or mismatched: the rebuild repairs them.
        return CatalogSnapshot(read(FILENAMES), read(DOCUMENTS), None, version)
    manifest = _manifest(selected)
    contents = {}
    for label, item in manifest['files'].items():
        if label not in ('filenames', 'documents'):
            continue
        contents[label] = read(item['key'])
        _validate(contents[label], item, manifest['catalog_id'])
    return CatalogSnapshot(contents['filenames'], contents['documents'], manifest, version)


def publish_catalog(store, filenames_path, documents_path, *, previous):
    """Upload immutable pair, then conditionally select it as the final write."""
    from congress_api.retention.document_index import validate_document_indexes
    validate_document_indexes(filenames_path, documents_path)
    contents = {'filenames': Path(filenames_path).read_bytes(),
                'documents': Path(documents_path).read_bytes()}
    properties = {label: _properties(data) for label, data in contents.items()}
    catalog_id = properties['filenames']['catalog_id']
    if catalog_id != properties['documents']['catalog_id']:
        raise ValueError('Catalog pair has different catalog_id values')
    generation = uuid4().hex
    files = {}
    progress.report('publish_catalog_files', completed=0, total=2, unit='tables')
    for label, name in [('filenames', 'document-filenames.parquet'), ('documents', 'documents.parquet')]:
        key = f'catalog-generations/{generation}/{name}'
        files[label] = {'key': key, **{k: v for k, v in properties[label].items() if k != 'catalog_id'}}
        store.put(key, contents[label], immutable=True)
        progress.report('publish_catalog_files', completed=len(files), total=2, unit='tables')
    manifest = {'version': 1, 'generation': generation, 'catalog_id': catalog_id, 'files': files}
    data = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    # LocalStore compares the exact manifest read before the build. R2Store's
    # indexes/ conditional write uses the ETag retained by read_catalog.
    progress.report('select_catalog_generation')
    if hasattr(store, 'put_catalog_manifest'):
        store.put_catalog_manifest(data, expected_version=previous.version)
    else:
        store.put(MANIFEST_KEY, data)
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
        if item:
            digest = sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            if path.stat().st_size != item['bytes'] or digest.hexdigest() != item['sha256']:
                raise ValueError(f'Selected catalog checksum mismatch: {path}')
        source = pq.ParquetFile(path)
        catalog_id = (source.schema_arrow.metadata or {}).get(b'catalog_id')
        if not catalog_id:
            raise ValueError('Catalog file has no catalog_id')
        ids.append(catalog_id.decode())
        if item and (source.metadata.num_rows != item['rows'] or ids[-1] != manifest['catalog_id']):
            raise ValueError(f'Selected catalog metadata mismatch: {path}')
        paths.append(path)
    if ids[0] != ids[1]:
        raise ValueError('Legacy catalog pair has different catalog_id values')
    return tuple(paths)
