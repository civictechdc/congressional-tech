"""Reuse one in-process validation of an unchanged immutable catalog pair."""
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import weakref

import pyarrow
import pyarrow.parquet as pq

from .catalog_publication import _manifest

_issued = weakref.WeakValueDictionary()


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
