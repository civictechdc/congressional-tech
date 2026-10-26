"""One exact local inventory check per viewer artifact custody boundary."""
from dataclasses import dataclass, replace
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import sys
import weakref

from .derived_files import file_identity, VerifiedFile, custody_identity

_issued = weakref.WeakValueDictionary()


class PreparedManifest(dict):
    def __init__(self, value, identities):
        super().__init__(value)
        self.identities = identities


def _context(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _validator():
    path = Path(__file__)
    return (os.getpid(), sys.version, custody_identity(path), id(verify_inventory.__code__),
            id(InventoryValidation.require.__code__), id(InventoryValidation.file.__code__),
            id(InventoryValidation.bind_context.__code__))


@dataclass(frozen=True)
class InventoryValidation:
    root: Path
    files: dict
    identities: dict
    context: bytes
    validator: tuple

    def _require_authority(self, root, files=None, *, context=None):
        if (_issued.get(id(self)) is not self or Path(root).resolve() != self.root
                or _validator() != self.validator
                or (files is not None and files != self.files)
                or (context is not None and _context(context) != self.context)):
            raise ValueError('Viewer inventory proof no longer applies')

    def require(self, root, files=None, *, context=None):
        self._require_authority(root, files, context=context)
        if self.files != {relative: dict(bytes=proof['bytes'], sha256=proof['sha256'])
                          for relative, proof in self.identities.items()}:
            raise ValueError('Viewer inventory facts changed')
        for relative, proof in self.identities.items():
            proof.require(self.root / relative)
        return self

    def bind_context(self, context):
        """Bind plan metadata to the same issued file facts without rescanning.

        This grants no new file custody: consumers still call require() at the
        next use boundary, which checks every file and the new input binding.
        """
        self._require_authority(self.root)
        result = replace(self, context=_context(context))
        _issued[id(result)] = result
        return result

    def file(self, path, *, expected=None):
        self._require_authority(self.root)
        relative = str(Path(path).resolve().relative_to(self.root))
        proof = self.identities.get(relative)
        if (proof is None or self.files.get(relative) != dict(bytes=proof['bytes'], sha256=proof['sha256'])
                or (expected is not None and any(proof[key] != expected[key] for key in ('bytes', 'sha256')))):
            raise ValueError('Viewer inventory does not cover file: ' + relative)
        return proof.require(path)


def verify_inventory(root, files, *, context):
    root = Path(root).resolve()
    identities, facts = {}, {}
    for relative, expected in files.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Invalid viewer inventory path: ' + relative)
        proof = file_identity(path)
        if expected is not None and any(proof[key] != expected[key] for key in ('bytes', 'sha256')):
            raise ValueError('Prepared publication file changed: ' + relative)
        identities[relative] = proof
        facts[relative] = dict(bytes=proof['bytes'], sha256=proof['sha256'])
    return issue_inventory(root, identities, context=context)


def issue_inventory(root, identities, *, context):
    """Combine issued file proofs; plain serialized digest dictionaries refuse."""
    root = Path(root).resolve()
    facts = {}
    for relative, proof in identities.items():
        path = root / relative
        if (not isinstance(relative, str) or str(PurePosixPath(relative)) != relative
                or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts
                or path.is_symlink() or not path.resolve().is_relative_to(root)):
            raise ValueError('Invalid viewer inventory path: ' + str(relative))
        if not isinstance(proof, VerifiedFile):
            raise ValueError('Issued file proof is required for viewer inventory')
        proof.require(root / relative)
        facts[relative] = dict(bytes=proof['bytes'], sha256=proof['sha256'])
    result = InventoryValidation(root, facts, dict(identities), _context(context), _validator())
    _issued[id(result)] = result
    # Each proof was checked above; issuance itself changes no file facts.
    return result
