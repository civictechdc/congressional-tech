"""Persistent opaque IDs; source observation keys are distinct from domain IDs."""
import json
from pathlib import Path
from uuid import uuid4


class IdRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.values = json.loads(self.path.read_text()) if self.path.exists() else {}

    def __call__(self, kind, key):
        # JSON encoding avoids collisions when source keys contain separators.
        scoped = json.dumps([kind, key], ensure_ascii=False)
        if scoped not in self.values:
            self.values[scoped] = str(uuid4())
        return self.values[scoped]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.values, sort_keys=True, ensure_ascii=False, indent=1) + "\n")
        tmp.replace(self.path)
