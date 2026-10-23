"""Reuse one in-process validation of an unchanged immutable catalog pair."""
from dataclasses import dataclass
from contextlib import ExitStack, closing
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import sqlite3
from tempfile import TemporaryDirectory
import weakref

import pyarrow
import pyarrow.parquet as pq

from .catalog_types import _manifest

_issued = weakref.WeakValueDictionary()


class CatalogReferenceCheck:
    """Check streamed catalog uniqueness and references with bounded SQLite state.

    Finish all changed component chunks before publication. Completeness against
    reused components belongs to the selected dependency-scope owner.
    """
    def __init__(self, source_schema, document_schema):
        source_meta, document_meta = source_schema.metadata or {}, document_schema.metadata or {}
        if not source_meta.get(b'catalog_id') or source_meta[b'catalog_id'] != document_meta.get(b'catalog_id'):
            raise ValueError('Document/source catalog_id values do not match')
        self.source_rows = self.document_rows = 0
        self.failed = self.finished = False
        self.resources = None
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise ValueError('Catalog reference checks cannot be reopened')
        self._entered = True
        self.resources = ExitStack()
        try:
            directory = self.resources.enter_context(TemporaryDirectory(prefix='validate-catalog-'))
            self.db = self.resources.enter_context(closing(sqlite3.connect(Path(directory) / 'references.sqlite')))
            self.db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE sources(source_id TEXT PRIMARY KEY NOT NULL,document_id TEXT NOT NULL); '
                'CREATE INDEX source_groups ON sources(document_id); '
                'CREATE TABLE documents(document_id TEXT PRIMARY KEY NOT NULL,source_id TEXT NOT NULL);')
            return self
        except BaseException:
            self.resources.close()
            self.resources = None
            raise

    def __exit__(self, kind, error, traceback):
        try:
            return self.resources.__exit__(kind, error, traceback)
        finally:
            self.resources = None

    def _require_input(self):
        if self.resources is None or self.failed or self.finished:
            raise ValueError('Catalog reference check is not accepting input')

    def _add(self, batch, *, sources):
        self._require_input()
        try:
            records = batch.select(['source_id', 'document_id']).to_pylist()
            if sources:
                self.db.executemany('INSERT INTO sources VALUES (?,?)',
                    ((row['source_id'], row['document_id']) for row in records))
                self.source_rows += len(records)
            else:
                self.db.executemany('INSERT INTO documents VALUES (?,?)',
                    ((row['document_id'], row['source_id']) for row in records))
                self.document_rows += len(records)
        except sqlite3.IntegrityError as error:
            self.failed = True
            raise ValueError('Document/source index references do not match') from error
        except BaseException:
            self.failed = True
            raise

    def add_sources(self, batch):
        self._add(batch, sources=True)

    def add_documents(self, batch):
        self._add(batch, sources=False)

    def finish(self):
        self._require_input()
        invalid = (self.db.execute('SELECT 1 FROM sources s LEFT JOIN documents d ON s.document_id=d.document_id WHERE d.document_id IS NULL LIMIT 1').fetchone()
                   or self.db.execute('SELECT 1 FROM documents d LEFT JOIN sources s ON d.source_id=s.source_id AND d.document_id=s.document_id WHERE s.source_id IS NULL LIMIT 1').fetchone())
        if invalid:
            self.failed = True
            raise ValueError('Document/source index references do not match')
        self.finished = True
        return dict(source_rows=self.source_rows, document_rows=self.document_rows)


    def source_ids_digest(self, component=None):
        if self.resources is None or not self.finished or self.failed:
            raise ValueError('Catalog reference check has not finished')
        query, parameters = ('SELECT source_id FROM sources ORDER BY source_id', ()) if component is None else (
            'SELECT source_id FROM sources WHERE document_id=? ORDER BY source_id', (component,))
        return catalog_source_ids_digest(row[0] for row in self.db.execute(query, parameters))

    def component_memberships(self):
        if self.resources is None or not self.finished or self.failed:
            raise ValueError('Catalog reference check has not finished')
        for component, rows in self.db.execute('SELECT document_id,count(*) FROM sources GROUP BY document_id ORDER BY document_id'):
            yield component, rows, self.source_ids_digest(component)


def catalog_source_ids_digest(sorted_source_ids):
    """Hash an ordered unique membership set without retaining another ID list."""
    from congress_api.retention.immutable_metadata import encoded
    digest, previous = hashlib.sha256(b'['), None
    for source_id in sorted_source_ids:
        if not isinstance(source_id, str) or previous is not None and source_id <= previous:
            raise ValueError('Catalog membership IDs must be unique sorted strings')
        if previous is not None:
            digest.update(b',')
        digest.update(encoded(source_id))
        previous = source_id
    digest.update(b']')
    return digest.hexdigest()


def catalog_reference_requirements():
    """Portable current requirements for reusing an immutable reference proof."""
    implementation = inspect.getsource(CatalogReferenceCheck) + inspect.getsource(catalog_source_ids_digest)
    from .catalog_rows import FORMAT
    return dict(validator='catalog-references-v1', row_format=FORMAT,
                row_implementation_sha256=hashlib.sha256(Path(__file__).with_name('catalog_rows.py').read_bytes()).hexdigest(),
                implementation_sha256=hashlib.sha256(implementation.encode()).hexdigest(),
                python=sys.version, pyarrow=pyarrow.__version__, sqlite=sqlite3.sqlite_version)


def _issue(proof):
    _issued[id(proof)] = proof
    return proof


def _identity(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _manifest_bytes(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()


def _validator_identity(validator):
    # Function/code identity catches replacement in memory. File identity catches
    # an edited validator; the publication guard separately pins its full closure.
    source = inspect.getsourcefile(validator) if inspect.isfunction(validator) else None
    return (id(validator), id(getattr(validator, '__code__', None)),
            (source, _identity(Path(source))) if source else None,
            os.getpid(), sys.version, pyarrow.__version__)


@dataclass(frozen=True)
class CatalogReferenceValidation:
    files: tuple
    validator: object
    validator_identity: tuple

    def require(self, filenames, documents, *, validator):
        paths = tuple(Path(path).resolve() for path in (filenames, documents))
        if (_issued.get(id(self)) is not self or validator is not self.validator
                or _validator_identity(validator) != self.validator_identity
                or paths != tuple(path for path, _ in self.files)
                or any(_identity(path) != identity for path, identity in self.files)):
            raise ValueError('Catalog reference validation no longer applies')
        return self

    def install(self, filenames, documents):
        """Move the caller-owned validated pair and rebind its changed paths."""
        self.require(*(path for path, _ in self.files), validator=self.validator)
        installed = []
        for (source, before), destination in zip(self.files, (filenames, documents), strict=True):
            if _identity(source) != before:
                raise ValueError('Catalog changed before installation')
            destination = Path(destination).resolve()
            source.replace(destination)
            after = _identity(destination)
            if after[:4] != before[:4]:
                raise ValueError('Catalog changed during installation')
            installed.append((destination, after))
        return _issue(CatalogReferenceValidation(tuple(installed), self.validator, self.validator_identity))

    def content(self, properties):
        """Bind reference semantics to already hashed exact bytes before copying."""
        self.require(*(path for path, _ in self.files), validator=self.validator)
        for (path, _), item in zip(self.files, properties.values(), strict=True):
            item.require(path)
        return _issue(CatalogContentValidation(
            tuple((label, item['bytes'], item['sha256']) for label, item in properties.items()),
            self.validator, self.validator_identity))


@dataclass(frozen=True)
class CatalogContentValidation:
    files: tuple
    validator: object
    validator_identity: tuple

    def require(self, manifest, *, validator):
        if (_issued.get(id(self)) is not self or validator is not self.validator
                or _validator_identity(validator) != self.validator_identity
                or self.files != tuple((label, manifest['files'][label]['bytes'], manifest['files'][label]['sha256'])
                                      for label in ('filenames', 'documents'))):
            raise ValueError('Catalog content validation no longer applies')


class CatalogBuildResult(dict):
    """Public JSON statistics plus an intentionally unserializable local proof."""
    def __init__(self, *args, validation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.validation = validation


def validate_references(filenames, documents, *, validator, **counts):
    paths = tuple(Path(path).resolve() for path in (filenames, documents))
    before = tuple((path, _identity(path)) for path in paths)
    identity = _validator_identity(validator)
    validator(*paths, **counts)
    proof = _issue(CatalogReferenceValidation(before, validator, identity))
    return proof.require(*paths, validator=validator)


@dataclass(frozen=True)
class CatalogPairValidation:
    root: Path
    manifest_bytes: bytes
    files: tuple
    validator: object
    validator_identity: tuple
    expected_bodies: frozenset
    coverage: dict

    def require(self, root, manifest, *, validator=None, expected_bodies=None):
        """Refuse stale proof; callers decide whether to perform a fresh validation."""
        if (_issued.get(id(self)) is not self or Path(root).resolve() != self.root or _manifest_bytes(manifest) != self.manifest_bytes
                or _validator_identity(self.validator) != self.validator_identity
                or (validator is not None and validator is not self.validator)
                or (expected_bodies is not None and frozenset(expected_bodies) != self.expected_bodies)
                or any(_identity(path) != identity for path, identity in self.files)):
            raise ValueError('Catalog pair validation no longer applies')
        return self.coverage


def validate_catalog_pair(root, manifest, *, validator, expected_bodies=(), references=None):
    """Hash both files, verify identity and coverage, then run the pair validator.

    No proof survives a process restart. Its file identity includes change time,
    so rewriting bytes or replacing a path invalidates reuse even at equal size.
    """
    root = Path(root).resolve()
    encoded = _manifest_bytes(manifest)
    manifest = _manifest(encoded)
    expected = frozenset(expected_bodies)
    paths = tuple(root/manifest['files'][label]['key'] for label in ('filenames', 'documents'))
    identities = tuple((path, _identity(path)) for path in paths)
    validator_identity = _validator_identity(validator)
    found = set()
    for label, path in zip(('filenames', 'documents'), paths, strict=True):
        item = manifest['files'][label]
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != item['bytes'] or digest != item['sha256']:
            raise ValueError('Catalog pair bytes differ')
        with pq.ParquetFile(path) as table:
            if ((table.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']
                    or table.metadata.num_rows != item['rows']):
                raise ValueError('Catalog pair identity differs')
            if label == 'filenames' and expected:
                for batch in table.iter_batches(columns=['body_key']):
                    found.update(value for value in batch.column(0).to_pylist() if value in expected)
    if expected - found:
        raise ValueError(f'Imported recovery bodies absent from catalog: {len(expected - found)}')
    if references is None:
        validator(*paths)
    elif isinstance(references, CatalogContentValidation):
        references.require(manifest, validator=validator)
    else:
        references.require(*paths, validator=validator)
    proof = _issue(CatalogPairValidation(root, encoded, identities, validator, validator_identity, expected,
        dict(expected_bodies=len(expected), missing_bodies=0, catalog_id=manifest['catalog_id'])))
    proof.require(root, manifest)
    return proof
