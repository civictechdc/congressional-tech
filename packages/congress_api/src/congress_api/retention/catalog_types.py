"""Shared catalog types, manifest parsing, and adoption proof helpers.

Breaks circular dependencies between catalog_batches, catalog_selection,
catalog_publication, catalog_validation, and catalog_adoption.
"""
from dataclasses import dataclass, field
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import weakref

import pyarrow.parquet as pq

from congress_api.retention.derived_files import file_identity
from congress_api.retention.immutable_metadata import MetadataObjects, encoded

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


def adoption_requirements():
    return dict(validator='catalog-native-adoption-v1',
                implementation_sha256=sha256(
                    Path(__file__).with_name('catalog_adoption.py').read_bytes()
                    + Path(__file__).with_name('catalog_rows.py').read_bytes()
                ).hexdigest())


def read_adoption_proof(store, reference, *, previous, scope_reference, scope):
    proof = MetadataObjects(store, 'catalog-adoption-v1', max_cache_entries=1).read(reference)
    binding = proof.get('binding')
    if (proof.get('version') != 1 or proof.get('requirements') != adoption_requirements()
            or binding != sha256(encoded({k: v for k, v in proof.items() if k != 'binding'})).hexdigest()
            or proof.get('base') != previous.identity or proof.get('files') != previous.files
            or proof.get('scope_reference') != scope_reference or proof.get('schemas') != scope['schemas']
            or proof.get('dependency_after') != scope['dependency_after']
            or scope['dependency_before'] is not None or scope['retired']['count'] != 0):
        raise ValueError('Native adoption proof differs from the exact selected file basis')
    for label, count in [('filenames', 'source'), ('documents', 'document')]:
        evidence = proof['readback'][label]
        with pq.ParquetFile(previous.filenames_path if label == 'filenames' else previous.documents_path) as old:
            old_count = old.metadata.num_rows
            old_schema = base64.b64encode(old.schema_arrow.serialize().to_pybytes()).decode()
        if (evidence['rows'] != old_count or proof['schemas'][label] != old_schema
                or evidence['rows'] != scope['counts']['prepared_' + count + '_rows']
                or any(not isinstance(evidence.get(name), str) or len(evidence[name]) != 64
                       for name in ('all_fields_sha256', 'ordered_ids_sha256'))):
            raise ValueError('Native adoption completeness or mapping proof differs')
    return proof


STATE_FIELDS = frozenset({'state_outcome', 'state_body_key', 'state_checked_at',
                          'state_retrieved_at', 'state_family'})
AVAILABILITY_FIELDS = STATE_FIELDS | {'hearing_package_id', 'hearing_resources'}
FIELDS = AVAILABILITY_FIELDS
RESOURCE_FIELDS = ('package_id', 'url', 'body_key', 'format', 'outcome',
                   'association_basis', 'api_response_body_key', 'publisher_format_url')

