"""Bounded catalog reverse membership leaves over shared native storage.

Grouping aliases and retained-source dependency keys share only this physical
member layout. Callers retain meanings, identities, typed schemas and selection.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import json
from tempfile import TemporaryDirectory

import pyarrow as pa

from .catalog_dependencies import DependencyGap
from .partition_routing import RoutingPages, split_partition, key_hash


class CatalogMemberships:
    def __init__(self, *, store, namespace, schema, member_column, max_rows, max_bytes,
                 read, write, validate_alias):
        self.routes = RoutingPages(store, namespace + '-aliases')
        self.members = RoutingPages(store, namespace + '-members')
        self.routes.objects.max_cache_entries = self.members.objects.max_cache_entries = 16
        self.schema, self.member_column = schema, member_column
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self._read, self._write, self.validate_alias = read, write, validate_alias

    def _groups(self, value):
        if value is None:
            return {}
        if value.get('kind') == 'members':
            if (not isinstance(value.get('alias'), str) or type(value.get('count')) is not int
                    or value['count'] < 1 or value.get('root') is None):
                raise DependencyGap('Invalid large-alias dependency metadata')
            return {value['alias']: value}
        if value.get('kind') != 'rows':
            raise DependencyGap('Unknown alias dependency leaf format')
        table = self._read(value['release'], self.schema)
        if len(table) != value.get('rows'):
            raise DependencyGap('Alias dependency leaf row count differs')
        groups, seen = {}, set()
        for row in table.to_pylist():
            pair = row['alias'], row[self.member_column]
            if pair in seen:
                raise DependencyGap('Duplicate reverse dependency membership')
            seen.add(pair)
            self.validate_alias(row['alias'])
            groups.setdefault(row['alias'], []).append(row)
        return {alias: pa.Table.from_pylist(rows, schema=self.schema) for alias, rows in groups.items()}

    def values(self, root, alias):
        """Stream one alias's members with at most one native leaf resident."""
        _, value = self.routes.lookup(root, alias)
        if value is None:
            return
        if value.get('kind') == 'rows':
            yield from (row[self.member_column] for row in self._groups(value).get(
                alias, pa.Table.from_pylist([], schema=self.schema)).to_pylist())
            return
        if value.get('kind') != 'members':
            raise DependencyGap('Unknown alias dependency leaf format')
        if alias != value.get('alias'):
            return
        count = 0
        for prefix, pin in self.members.leaf_items(value['root']):
            previous = set()
            for row in self._read(pin, self.schema).to_pylist():
                member = row[self.member_column]
                if (row['alias'] != alias or member in previous
                        or not key_hash(member).startswith(prefix)):
                    raise DependencyGap('Invalid routed reverse dependency member')
                previous.add(member)
                count += 1
                yield member
        if count != value['count']:
            raise DependencyGap('Reverse dependency member count differs from selected directory')

    def _member_value(self, alias, members):
        # One prolific parent or shared body can have more members than one
        # native leaf. Spill membership keys, not the source values, while
        # constructing its secondary hash tree. No entire large list/table.
        pending, size, seen = [], 0, set()
        iterator = iter(members)
        for member in iterator:
            if member in seen:
                raise DependencyGap('Duplicate reverse dependency membership')
            seen.add(member)
            row = {'alias': alias, self.member_column: member}
            pending.append(row)
            size += pa.Table.from_pylist([row], schema=self.schema).nbytes
            if len(pending) > self.max_rows or size > self.max_bytes:
                break
        else:
            return pa.Table.from_pylist(pending, schema=self.schema)
        with TemporaryDirectory(prefix='catalog-members-') as directory, closing(
                sqlite3.connect(Path(directory) / 'members.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE members(value TEXT PRIMARY KEY,digest TEXT); '
                'CREATE INDEX member_hashes ON members(digest);')
            def insert(member):
                try:
                    db.execute('INSERT INTO members VALUES (?,?)', (member, key_hash(member)))
                except sqlite3.IntegrityError as error:
                    raise DependencyGap('Duplicate reverse dependency membership') from error
            for row in pending:
                insert(row[self.member_column])
            pending.clear()
            seen.clear()
            for member in iterator:
                insert(member)
            count = db.execute('SELECT count(*) FROM members').fetchone()[0]
            def leaves(prefix):
                rows = [{'alias': alias, self.member_column: value} for value, in db.execute(
                    'SELECT value FROM members WHERE digest>=? AND digest<? ORDER BY value LIMIT ?',
                    (prefix, prefix + 'g', self.max_rows + 1))]
                table = pa.Table.from_pylist(rows, schema=self.schema)
                if len(table) <= self.max_rows and table.nbytes <= self.max_bytes:
                    if len(table):
                        yield prefix, self._write(table, 'members')
                    return
                if len(table) == 1 or len(prefix) == 64:
                    raise DependencyGap('One reverse dependency member exceeds its partition budget')
                for char in '0123456789abcdef':
                    yield from leaves(prefix + char)
            root = self.members.replace_stream(None, '', leaves(''))
            return dict(kind='members', alias=alias, count=count, root=root)

    def replace(self, root, replacements):
        """Coalesce changed aliases on disk before writing affected native leaves."""
        with TemporaryDirectory(prefix='catalog-aliases-') as directory, closing(
                sqlite3.connect(Path(directory) / 'aliases.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE changes(alias TEXT PRIMARY KEY,prefix TEXT,digest TEXT); '
                'CREATE TABLE bases(prefix TEXT PRIMARY KEY,body TEXT); '
                'CREATE TABLE groups(alias TEXT PRIMARY KEY,digest TEXT,body TEXT); '
                'CREATE INDEX group_hashes ON groups(digest); '
                'CREATE TABLE rows(alias TEXT,member TEXT,PRIMARY KEY(alias,member));')
            for alias in replacements:
                prefix, value = self.routes.lookup(root, alias)
                db.execute('INSERT INTO changes VALUES (?,?,?)', (alias, prefix, key_hash(alias)))
                db.execute('INSERT OR IGNORE INTO bases VALUES (?,?)', (prefix, json.dumps(value)))
            def save(alias, value):
                digest = key_hash(alias)
                if isinstance(value, pa.Table):
                    if not len(value):
                        return
                    db.execute('INSERT INTO groups VALUES (?,?,NULL)', (alias, digest))
                    db.executemany('INSERT INTO rows VALUES (?,?)', ((alias, row[self.member_column])
                        for row in value.to_pylist()))
                else:
                    db.execute('INSERT INTO groups VALUES (?,?,?)', (alias, digest, json.dumps(value)))
            for prefix, basis in db.execute('SELECT prefix,body FROM bases ORDER BY prefix'):
                db.execute('DELETE FROM groups')
                db.execute('DELETE FROM rows')
                for alias, value in self._groups(json.loads(basis)).items():
                    if db.execute('SELECT 1 FROM changes WHERE alias=?', (alias,)).fetchone() is None:
                        save(alias, value)
                for alias, in db.execute('SELECT alias FROM changes WHERE prefix=? ORDER BY alias', (prefix,)):
                    members = replacements[alias]
                    save(alias, self._member_value(alias,
                        iter(sorted(members)) if isinstance(members, set) else members))
                def leaves(child):
                    query = (child, child + 'g')
                    count = db.execute('SELECT count(*) FROM groups WHERE digest>=? AND digest<?', query).fetchone()[0]
                    if not count:
                        return
                    heavy = db.execute('SELECT body FROM groups WHERE digest>=? AND digest<? AND body IS NOT NULL LIMIT 1', query).fetchone()
                    if heavy and count == 1:
                        yield child, json.loads(heavy[0])
                        return
                    if not heavy:
                        rows = [{'alias': alias, self.member_column: member} for alias, member in db.execute(
                            'SELECT r.alias,r.member FROM rows r JOIN groups g ON r.alias=g.alias '
                            'WHERE g.digest>=? AND g.digest<? ORDER BY r.alias,r.member LIMIT ?',
                            (*query, self.max_rows + 1))]
                        table = pa.Table.from_pylist(rows, schema=self.schema)
                        if len(table) <= self.max_rows and table.nbytes <= self.max_bytes:
                            yield child, dict(kind='rows', release=self._write(table, 'aliases'),
                                              rows=len(table), arrow_bytes=table.nbytes)
                            return
                    if len(child) == 64:
                        raise DependencyGap('Alias hash collision cannot fit the dependency budget')
                    for char in '0123456789abcdef':
                        yield from leaves(child + char)
                generated = iter(leaves(prefix))
                first = next(generated, None)
                if first is None:
                    root = self.routes.replace(root, prefix, {prefix: None})
                else:
                    from itertools import chain
                    root = self.routes.replace_stream(root, prefix, chain([first], generated))
        return root
