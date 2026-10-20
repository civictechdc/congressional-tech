"""Mutable acquisition working rows backed by exact selected native state keys."""
from collections.abc import MutableMapping
from copy import deepcopy


class RawStateMap(MutableMapping):
    """Load only accessed URL leaves; keep changed working rows until one save.

    Iteration is an explicit full export for reference/planning callers. The
    scheduler uses selected candidate rows instead of this mapping's iteration.
    """
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.rows, self.original = {}, {}
        self.added = 0

    def __getitem__(self, key):
        if key not in self.rows:
            row = self.snapshot.state(key)
            if row is None:
                raise KeyError(key)
            self.rows[key] = row
            self.original[key] = deepcopy(row)
        return self.rows[key]

    def __setitem__(self, key, value):
        if not isinstance(value, dict) or value.get('url') != key:
            raise ValueError('Acquisition state key differs from its URL')
        if key not in self.original:
            try:
                self[key]
            except KeyError:
                self.original[key] = None
                self.added += 1
        self.rows[key] = value

    def __delitem__(self, key):
        raise TypeError('Raw URL state deletion requires an explicit reviewed operation')

    def __len__(self):
        return self.snapshot.manifest['state']['rows'] + self.added

    def __iter__(self):
        # This is the declared full-export boundary, never a key lookup.
        existing = set()
        for row in self.snapshot.states().to_pylist():
            key = row['url']
            existing.add(key)
            if key not in self.rows:
                self.rows[key] = row
                self.original[key] = deepcopy(row)
            yield key
        yield from (key for key in self.rows if key not in existing)

    def changed(self):
        return [row for key, row in self.rows.items() if self.original[key] != row]

    def admit_selected(self, row):
        """Keep an already verified selected row without a second native read."""
        key = row['url']
        if key not in self.rows:
            self.rows[key] = row
            self.original[key] = deepcopy(row)
        return self.rows[key]

    def rebase(self, snapshot):
        self.snapshot = snapshot
        # Keep exposed row objects alive across saves, matching dict semantics.
        self.original = {key: deepcopy(row) for key, row in self.rows.items()}
        self.added = 0
