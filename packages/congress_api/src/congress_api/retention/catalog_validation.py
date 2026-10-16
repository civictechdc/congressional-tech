"""Reuse one in-process validation of an unchanged immutable catalog pair."""
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path

import pyarrow
import pyarrow.parquet as pq

from .catalog_publication import _manifest


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
            (source, _identity(Path(source))) if source else None, pyarrow.__version__)


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
        if (Path(root).resolve() != self.root or _manifest_bytes(manifest) != self.manifest_bytes
                or _validator_identity(self.validator) != self.validator_identity
                or (validator is not None and validator is not self.validator)
                or (expected_bodies is not None and frozenset(expected_bodies) != self.expected_bodies)
                or any(_identity(path) != identity for path, identity in self.files)):
            raise ValueError('Catalog pair validation no longer applies')
        return self.coverage


def validate_catalog_pair(root, manifest, *, validator, expected_bodies=()):
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
        table = pq.ParquetFile(path)
        if ((table.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']
                or table.metadata.num_rows != item['rows']):
            raise ValueError('Catalog pair identity differs')
        if label == 'filenames' and expected:
            for batch in table.iter_batches(columns=['body_key']):
                found.update(value for value in batch.column(0).to_pylist() if value in expected)
    if expected - found:
        raise ValueError(f'Imported recovery bodies absent from catalog: {len(expected - found)}')
    validator(*paths)
    proof = CatalogPairValidation(root, encoded, identities, validator, validator_identity, expected,
        dict(expected_bodies=len(expected), missing_bodies=0, catalog_id=manifest['catalog_id']))
    proof.require(root, manifest)
    return proof
