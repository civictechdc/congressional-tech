"""Persistent opaque IDs; source observation keys are distinct from domain IDs."""
import json
from pathlib import Path
from uuid import uuid4


class _Released:
    """Stands in for staged values: a later lookup is a bug, never an allocation."""

    def _closed(self, *args):
        raise RuntimeError("The ID registry was staged for saving; allocation is closed")

    __contains__ = __getitem__ = __setitem__ = get = _closed


class IdRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.values = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.staged = None  # The written registry, once stage() has released it.

    def __call__(self, kind, key):
        # JSON encoding avoids collisions when source keys contain separators.
        scoped = json.dumps([kind, key], ensure_ascii=False)
        if scoped not in self.values:
            self.values[scoped] = str(uuid4())
        return self.values[scoped]

    def existing(self, kind, key):
        """Inspect an identity without allocating an ID."""
        return self.values.get(json.dumps([kind, key], ensure_ascii=False))

    def alias(self, kind, key, existing_key):
        """Give a newly encountered source key an already retained identity.

        Existing keys never move. In particular, this cannot merge two records
        whose different public IDs have already been allocated.
        """
        target = self.existing(kind, existing_key)
        if target is None:
            return False
        scoped = json.dumps([kind, key], ensure_ascii=False)
        if scoped in self.values:
            return self.values[scoped] == target
        self.values[scoped] = target
        return True

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open('w', encoding='utf-8') as stream:
            json.dump(self.values, stream, sort_keys=True, ensure_ascii=False, indent=1)
            stream.write('\n')
        return tmp

    def stage(self):
        """Write the registry beside ids.json and release it; allocation is over.

        The registry keeps every key ever allocated, so it grows with each
        re-keyed input snapshot (2.85M keys, 1.35 GB resident on 2026-10-17).
        Publication, the export's memory peak, allocates nothing. save() then
        renames the staged file, so ids.json still changes only after the
        publication is verified. Any later lookup fails instead of allocating.
        """
        self.staged, self.values = self._write(), _Released()

    def discard(self):
        """Remove a staged registry whose publication did not complete."""
        if self.staged is not None:
            self.staged.unlink(missing_ok=True)

    def save(self):
        (self.staged or self._write()).replace(self.path)
        self.staged = None
