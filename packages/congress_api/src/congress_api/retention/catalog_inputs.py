"""Repeatable catalog identifiers with a fixed-size request identity."""
from hashlib import sha256
import re
import sqlite3

from .immutable_metadata import encoded


class CatalogKeys:
    """Sort unique identifiers on disk instead of retaining a corpus-sized list."""

    def __init__(self, work, name, values, label, *, reject_duplicates=False):
        if re.fullmatch(r'[a-z][a-z0-9_]*', name) is None:
            raise ValueError('Invalid catalog identifier table name')
        self.connection, self.name = work.connection, name
        self.connection.execute(f'CREATE TABLE {name} (value TEXT PRIMARY KEY)')
        for value in values:
            if not isinstance(value, str) or not value:
                raise ValueError(f'{label} must be nonempty strings')
            try:
                self.connection.execute(f'INSERT INTO {name} VALUES (?)', (value,))
            except sqlite3.IntegrityError:
                if reject_duplicates:
                    raise ValueError(f'{label} must not repeat') from None

    def __iter__(self):
        return (value for value, in self.connection.execute(
            f'SELECT value FROM {self.name} ORDER BY value'))

    def __len__(self):
        return self.connection.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0]

    def __contains__(self, value):
        return self.connection.execute(
            f'SELECT 1 FROM {self.name} WHERE value=?', (value,)).fetchone() is not None

    def identity(self):
        """Match the existing canonical JSON list digest, one identifier at a time."""
        digest, count = sha256(b'['), 0
        for value in self:
            if count:
                digest.update(b',')
            digest.update(encoded(value))
            count += 1
        digest.update(b']')
        return dict(count=count, sha256=digest.hexdigest())
