"""Gate 1 (ct-tk10): compare a candidate release with the live (base) release, key by key and value by value.

Rows are matched on published identity, never on `list_row`, which is release-local.
Every manifest file is covered: a special handler, the registry's primary key, a
`file added`/`file removed` group, or a refusal for a changed file with no comparison.
Row groups sum to the file's row delta (the `list` sum always does), so a matching sum
proves only that no row was dropped. Value groups (`changed <column>`) count matched rows
whose column differs and stand outside that sum. Only `verified` means a cause was checked
against data; any other status, or a sum miss, fails: `unverified` (sized, cause not
checked), `defect`, `unexplained`. `release_gate` accepts a failing group only with a
recorded cause of the exact count.

Cannot see: a defect present in both releases (no difference); content of split, merged
or added rows (no matched partner); a second cause hiding inside one column group of the
same count; whether a recorded cause is true. Witnesses compare by witness_key, which
448651e7 redefined, so against c94bfedc every key appears removed and added; a candidate
that publishes witness_key_map pairs re-keyed rows through it (ct-kb4w).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import duckdb

OFFSETS = {'src_start', 'rec_start', 'file_row_number'}  # shift whenever an earlier row changes
TRIPLE = 'receipt_key,receipt_line,capture_index'
ADDED_URL_STATE = 'candidate_url_state ANTI JOIN base_url_state USING(requested_url)'
ATTEMPTED_URLS = 'new attempts'


class Diff:
    def __init__(self, base: Path, candidate: Path, history=(), now=None):
        self.dirs = {'base': base, 'candidate': candidate}
        # The gate's own clock: the one time in a comparison that the candidate does not supply.
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.manifest = {s: json.loads((d / 'manifest.json').read_text()) for s, d in self.dirs.items()}
        self.entry = {s: {f['name']: f for f in m['files']} for s, m in self.manifest.items()}
        self.con = duckdb.connect()
        for side, directory in self.dirs.items():
            for entry in self.manifest[side]['files']:
                name = entry['name'].removesuffix('.parquet')
                path = directory / entry['name']
                if entry['name'].endswith('.parquet') and path.exists():
                    extra = ',file_row_number=true' if name in ('list', 'detail') else ''
                    self.view(f'{side}_{name}', f"SELECT * FROM read_parquet('{path}'{extra})")
        self.identities = identities(self.dirs)
        self.cannot_see = []  # stated limits for this comparison, never silence
        # Earlier releases named by the publish (link_history): their link keys must not vanish either.
        self.history = []
        for index, directory in enumerate(history):
            name = f'history{index}_links'
            self.view(name, f"SELECT * FROM read_parquet('{Path(directory) / 'links.parquet'}')")
            self.history.append(name)
        self.link_causes = False
        self.witness_rekey = None  # set by rekeyed()
        self.refetched = None  # set by refetched_files()

    def has(self, side, table):
        return bool(self.rows(f"SELECT 1 FROM duckdb_views() WHERE view_name='{side}_{table}'"))

    def columns(self, side, table):
        return [r[0] for r in self.rows(f'DESCRIBE {side}_{table}')]

    def view(self, name, sql):
        self.con.execute(f'CREATE TEMP VIEW {name} AS {sql}')

    def table(self, name, sql):
        self.con.execute(f'CREATE TEMP TABLE {name} AS {sql}')

    def one(self, sql):
        return self.con.execute(sql).fetchone()[0] or 0

    def rows(self, sql):
        return self.con.execute(sql).fetchall()

    def arrow_types(self, side, table):
        return {field.name: field.type for field in self.con.execute(f'SELECT * FROM {side}_{table} LIMIT 0').arrow().schema}

    def changed(self, table, join, compare=None, exclude=OFFSETS, only=None):
        """One value group per column whose matched rows differ; `join` must alias sides p and l.

        One query per table: each column costs one IS DISTINCT FROM per matched row,
        O(matched rows x columns), with no per-column rescan. A struct or list-of-struct
        column whose subfields differ between the releases is compared subfield by subfield
        on the shared ones, so a change inside an old subfield is not hidden by a new one;
        new subfields are their own addition group. Columns new in the candidate have no
        base values: they are listed in `cannot_see`, never read as agreement.
        """
        import pyarrow as pa
        base_types, candidate_types = self.arrow_types('base', table), self.arrow_types('candidate', table)
        columns = set(base_types) & set(candidate_types)
        if only is not None:
            columns &= set(only)
        selected = sorted(columns - set(exclude))
        groups = []
        for column in sorted(set(candidate_types) - set(base_types) - set(exclude)):
            if only is None or column in only:
                self.cannot_see.append(f'{table}.{column}: new in the candidate; no base values to compare')
        for column in sorted(set(base_types) - set(candidate_types) - set(exclude)):
            if only is None or column in only:
                groups.append(flag(f'column {column} removed', 'unexplained'))
        terms, labels = [], []

        def fields(kind):
            if pa.types.is_struct(kind):
                return '', {f.name for f in kind}
            if (pa.types.is_list(kind) or pa.types.is_large_list(kind)) and pa.types.is_struct(kind.value_type):
                return '[]', {f.name for f in kind.value_type}
            return None, None

        for column in selected:
            if (compare or {}).get(column) is None:
                (shape, old), (shape_new, new) = fields(base_types[column]), fields(candidate_types[column])
                if shape is not None and shape == shape_new and old != new:
                    for name in sorted(old & new):
                        if shape == '[]':
                            left, right = (f'list_transform({s}."{column}",e->e."{name}")' for s in 'pl')
                        else:
                            left, right = (f'{s}."{column}"."{name}"' for s in 'pl')
                        terms.append(f'count(*) FILTER (WHERE {left} IS DISTINCT FROM {right})')
                        labels.append(('value', f'{column}{shape}.{name}'))
                    for name in sorted(new - old):
                        value = (f'len(list_filter(l."{column}",e->e."{name}" IS NOT NULL))>0' if shape == '[]'
                                 else f'l."{column}"."{name}" IS NOT NULL')
                        terms.append(f'count(*) FILTER (WHERE {value})')
                        labels.append(('added', f'{column}{shape}.{name}'))
                    for name in sorted(old - new):
                        groups.append(flag(f'subfield {column}{shape}.{name} removed', 'unexplained'))
                    continue
            template = (compare or {}).get(column, 'X.{c}')
            left, right = (template.replace('X', s).format(c=f'"{column}"') for s in 'pl')
            terms.append(f'count(*) FILTER (WHERE {left} IS DISTINCT FROM {right})')
            labels.append(('value', column))
        if terms:
            counts = self.con.execute(f'SELECT {",".join(terms)} FROM {join}').fetchone()
            for (kind, label), n in zip(labels, counts):
                if not n:
                    continue
                groups.append(value_group(label, n) if kind == 'value' else
                              dict(group(f'added subfield {label}', 'subfield new in the candidate, set on matched rows', n), value=True))
        return groups


def group(name, cause, count, status='unverified'):
    if cause == 'unexplained':
        status = 'unexplained'
    return {'group': name, 'cause': cause, 'count': int(count), 'status': status}


def value_group(column, count):
    """A matched-key value change: sized, outside the row-delta sum, unverified until a cause is recorded."""
    return {'group': f'changed {column}', 'cause': 'value differs on matched key', 'count': int(count),
            'status': 'unverified', 'value': True}


def identities(dirs):
    """Primary keys from the candidate's published schema, else the base's, else the registry."""
    found = {}
    sources = [d / 'schema.json' for d in (dirs['candidate'], dirs['base'])]
    for path in sources:
        if path.exists():
            for table in json.loads(path.read_text()).get('files', []):
                found.setdefault(table['name'].removesuffix('.parquet'), table['identity'])
    from viewer_publication.archive_schema import build_schema
    for table in build_schema()['files']:
        found.setdefault(table['name'].removesuffix('.parquet'), table['identity'])
    return found


def flag(name, cause, status='unverified'):
    """A finding that moves no rows, so it survives the zero-count filter and adds nothing to the sum."""
    return group(name, cause, 0, status) | {'flag': True}


def add_evidence(diff: Diff, base_path: str, candidate_path: str):
    """Attribute link keys through capture eligibility flips; a flip never proves v20 was right."""
    diff.table('flips', f"""SELECT {TRIPLE},a.member_path,a.context_url,left(hex(a.sha256),16) k,a.is_real_file a_real,b.is_real_file b_real,
      coalesce(b.url,b.requested_url,'') address
      FROM (SELECT {TRIPLE},member_path,context_url,sha256,is_real_file FROM read_parquet('{base_path}')) a
      JOIN (SELECT {TRIPLE},is_real_file,url,requested_url FROM read_parquet('{candidate_path}')) b USING({TRIPLE})
      WHERE a.is_real_file IS DISTINCT FROM b.is_real_file""")
    diff.table('real_base', f"""SELECT left(hex(sha256),16) k,bool_or(member_path IS NULL) top
      FROM read_parquet('{base_path}') WHERE is_real_file GROUP BY 1""")
    diff.table('real_candidate', f"""SELECT DISTINCT left(hex(sha256),16) k FROM read_parquet('{candidate_path}') WHERE is_real_file""")
    diff.table('link_causes', """
      SELECT hex(p.link_key) k,p.list_row,-1 sign,CASE
        WHEN NOT EXISTS (SELECT 1 FROM flips f WHERE f.k=hex(p.link_key) AND f.a_real AND NOT f.b_real) THEN 'unexplained'
        WHEN hex(p.link_key) IN (SELECT k FROM real_candidate) THEN 'unexplained'
        WHEN r.top THEN 'top-level body no longer eligible' ELSE 'member-only body no longer real' END cause
      FROM base_links p ANTI JOIN candidate_links l USING(link_key) LEFT JOIN real_base r ON r.k=hex(p.link_key)
      UNION ALL
      SELECT hex(l.link_key),l.list_row,1,CASE
        WHEN EXISTS (SELECT 1 FROM flips f WHERE f.k=hex(l.link_key) AND f.b_real AND NOT f.a_real) THEN 'newly eligible body'
        ELSE 'unexplained' END
      FROM candidate_links l ANTI JOIN base_links p USING(link_key)""")
    diff.link_causes = True
    flips = diff.rows("""SELECT a_real,b_real,member_path IS NOT NULL,count(*) FROM flips GROUP BY ALL ORDER BY 4 DESC""")
    return [dict(zip(('base_real', 'candidate_real', 'member', 'rows'), r)) for r in flips]


def links(d: Diff):
    if d.link_causes:
        return [group(f'{"added" if s > 0 else "removed"} keys', c, s * n, 'verified')
                for s, c, n in d.rows('SELECT sign,cause,count(*) FROM link_causes GROUP BY ALL ORDER BY 1,2')], {}
    removed = d.one('SELECT count(*) FROM base_links ANTI JOIN candidate_links USING(link_key)')
    added = d.one('SELECT count(*) FROM candidate_links ANTI JOIN base_links USING(link_key)')
    return [group('removed keys', 'no evidence given', -removed), group('added keys', 'no evidence given', added)], {}


def documents(d: Diff):
    # One join of the two link tables serves the document pairs and the link rule's answer check.
    d.table('key_pairs', 'SELECT p.link_key,p.list_row pr,l.list_row lr FROM base_links p JOIN candidate_links l USING(link_key)')
    d.table('pairs', 'SELECT DISTINCT pr,lr FROM key_pairs')
    d.table('pn', 'SELECT pr,count(*) n FROM pairs GROUP BY 1')
    d.table('ln', 'SELECT lr,count(*) n FROM pairs GROUP BY 1')
    d.table('member_rows', 'SELECT DISTINCT list_row FROM base_sources WHERE member_path IS NOT NULL')
    out = [group('split rows', 'previous row had a member source' if m else 'previous row had no member source', n)
           for m, n in d.rows("""SELECT pr IN (SELECT list_row FROM member_rows),sum(n-1) FROM pn WHERE n>1 GROUP BY 1""")]
    merged = d.one('SELECT sum(n-1) FROM ln WHERE n>1')
    if merged:
        out.append(group('merged rows', 'previous rows now share one document', -merged))
    for side, sign, partner, label in (('base', -1, 'pn', 'removed'), ('candidate', 1, 'ln', 'added')):
        key = 'pr' if side == 'base' else 'lr'
        d.table(f'{label}_rows', f"""SELECT file_row_number::INT r FROM {side}_list
          ANTI JOIN {partner} ON file_row_number={key}""")
        unkeyed = d.one(f'SELECT count(*) FROM {label}_rows WHERE r NOT IN (SELECT list_row FROM {side}_links)')
        if unkeyed:
            out.append(group(f'{label} rows without a link key', 'unexplained', sign * unkeyed))
        total = d.one(f'SELECT count(*) FROM {label}_rows WHERE r IN (SELECT list_row FROM {side}_links)')
        if d.link_causes:
            want = sign
            for cause, n in d.rows(f"""SELECT coalesce(c.cause,'unexplained'),count(*) FROM (
              SELECT r,min(cause) cause FROM {label}_rows JOIN link_causes ON list_row=r AND sign={want} GROUP BY 1) c
              GROUP BY 1 ORDER BY 1"""):
                out.append(group(f'{label} rows', cause, sign * n, 'verified'))
                total -= n
            if total:
                out.append(group(f'{label} rows', 'unexplained', sign * total))
        elif total:
            out.append(group(f'{label} rows', 'no surviving link key', sign * total))
    shape = {'base_rows_by_candidate_rows': dict(d.rows('SELECT n::VARCHAR,count(*) FROM pn GROUP BY 1 ORDER BY 1')),
             'candidate_rows_by_base_rows': dict(d.rows('SELECT n::VARCHAR,count(*) FROM ln GROUP BY 1 ORDER BY 1')),
             'components_with_split_and_merge': d.one('SELECT count(*) FROM pairs JOIN pn USING(pr) JOIN ln USING(lr) WHERE pn.n>1 AND ln.n>1')}
    d.table('one_to_one', 'SELECT pr,lr FROM pairs JOIN pn USING(pr) JOIN ln USING(lr) WHERE pn.n=1 AND ln.n=1')
    shape['one_to_one_rows'] = d.one('SELECT count(*) FROM one_to_one')
    return out, shape


def rekeyed(d: Diff):
    """The candidate's unambiguous witness_key_map rows (ct-kb4w) as table `witness_rekey`; False when
    the candidate publishes no map.

    A successor can carry keys from several historical releases. Within the base release, a re-key
    must preserve each occurrence, including a witness whose key survives directly.
    """
    if d.witness_rekey is None:
        d.witness_rekey = d.has('candidate', 'witness_key_map') and d.has('candidate', 'witnesses')
        if d.witness_rekey:
            d.table('witness_rekey_candidates', """SELECT m.old_key,m.witness_key
              FROM candidate_witness_key_map m JOIN candidate_witnesses w USING(witness_key)
              WHERE m.status='unambiguous'""")
            collisions = 'SELECT witness_key FROM witness_rekey_candidates WHERE false'
            if d.has('base', 'witnesses'):
                collisions = """SELECT r.witness_key FROM witness_rekey_candidates r
                  JOIN base_witnesses old ON old.witness_key=r.old_key
                  LEFT JOIN base_witnesses surviving ON surviving.witness_key=r.witness_key
                  GROUP BY r.witness_key HAVING count(*)>1 OR count(surviving.witness_key)>0"""
            d.table('witness_rekey_collisions', collisions)
            d.table('witness_rekey', """SELECT r.* FROM witness_rekey_candidates r
              ANTI JOIN witness_rekey_collisions USING(witness_key)""")
    return d.witness_rekey


def rekeyed_lists(d: Diff, relation, row, column):
    """`relation`'s `column` keys mapped through witness_rekey, sorted and distinct, per `row`, as table
    `<relation>_rekeyed_<column>`. A join, not a MAP value per row: a MAP lookup scans the map."""
    name = f'{relation}_rekeyed_{column}'
    d.table(name, f"""SELECT u.{row},list_sort(list_distinct(list(coalesce(x.witness_key,u.k)))) AS {column}
      FROM (SELECT {row},unnest({column}) AS k FROM {relation}) u LEFT JOIN witness_rekey x ON x.old_key=u.k
      GROUP BY u.{row}""")
    return name


def document_file(table):
    def run(d: Diff):
        groups, shape = d.documents
        join = f'one_to_one JOIN base_{table} p ON p.file_row_number=pr JOIN candidate_{table} l ON l.file_row_number=lr'
        compare, rekeys = None, []
        if rekeyed(d) and 'witness_keys' in set(d.columns('base', table)) & set(d.columns('candidate', table)):
            # Keys re-keyed through the candidate's witness_key_map count as the same witness.
            for side, alias in (('base', 'pw'), ('candidate', 'lw')):
                mapped_keys = rekeyed_lists(d, f'{side}_{table}', 'file_row_number', 'witness_keys')
                join += f' LEFT JOIN {mapped_keys} {alias} ON {alias}.file_row_number={alias[0]}.file_row_number'
            mapped = 'coalesce(Xw.{c},X.{c})'  # a row with no keys has no mapped row
            compare = {'witness_keys': mapped}
            left, right = (mapped.replace('X', s).format(c='"witness_keys"') for s in 'pl')
            n = d.one(f'SELECT count(*) FROM {join} WHERE p.witness_keys IS DISTINCT FROM l.witness_keys AND {left} IS NOT DISTINCT FROM {right}')
            if n:
                rekeys = [dict(group('changed witness_keys', 're-keyed through witness_key_map', n, 'verified'), value=True)]
        return [*groups, *rekeys, *d.changed(table, join, compare, exclude=OFFSETS | {'file_row_number'})], shape if table == 'list' else {}
    return run


def counted(d: Diff, table, key):
    """Compare key multiplicity; the FULL JOIN matches NULL keys with IS NOT DISTINCT FROM."""
    names = [k.strip() for k in key.split(',')]
    on = ' AND '.join(f'p.{k} IS NOT DISTINCT FROM l.{k}' for k in names)
    picked = ','.join(f'coalesce(p.{k},l.{k}) {k}' for k in names)
    d.table(f'{table}_diff', f"""SELECT {picked},coalesce(p.n,0) pn,coalesce(l.n,0) ln FROM
      (SELECT {key},count(*) n FROM base_{table} GROUP BY ALL) p FULL JOIN
      (SELECT {key},count(*) n FROM candidate_{table} GROUP BY ALL) l ON {on} WHERE coalesce(p.n,0)<>coalesce(l.n,0)""")


def urls(d: Diff):
    counted(d, 'urls', 'lookup_key')
    gone, new, fewer, more = d.rows("""SELECT sum(ln-pn) FILTER(ln=0),sum(ln-pn) FILTER(pn=0),
      sum(ln-pn) FILTER(pn>0 AND ln>0 AND ln<pn),sum(ln-pn) FILTER(pn>0 AND ln>pn) FROM urls_diff""")[0]
    histogram = [dict(zip(('base_rows', 'candidate_rows', 'keys'), r)) for r in
                 d.rows('SELECT pn,ln,count(*) FROM urls_diff GROUP BY 1,2 ORDER BY 3 DESC,1,2')]
    return [group('keys gone', 'every row for the key was removed', gone or 0),
            group('keys new', 'key absent from the previous release', new or 0),
            group('keys with fewer rows', 'fewer documents answer the key', fewer or 0),
            group('keys with more rows', 'more documents answer the key', more or 0),
            *moved(d, 'urls', ['lookup_key'])], {'histogram': histogram}


def sources(d: Diff):
    counted(d, 'sources', 'url,member_path')
    q = lambda where: d.one(f'SELECT sum(ln-pn) FROM sources_diff WHERE {where}')
    out = [group('member rows removed', 'archive member no longer a real file', q('member_path IS NOT NULL AND ln<pn')),
           group('member rows added', 'archive member newly real', q('member_path IS NOT NULL AND ln>pn')),
           group('NULL url', 'defect: a published source address must not be null', q('url IS NULL AND member_path IS NULL')),
           group('URLs gone', 'no live row has this address', q('url IS NOT NULL AND member_path IS NULL AND ln=0')),
           group('new URLs', 'no previous row has this address', q('url IS NOT NULL AND member_path IS NULL AND pn=0')),
           group('same-URL rows removed', 'fewer documents list the address', q('url IS NOT NULL AND member_path IS NULL AND pn>0 AND ln>0 AND ln<pn')),
           group('same-URL rows added', 'more documents list the address', q('url IS NOT NULL AND member_path IS NULL AND pn>0 AND ln>pn'))]
    notes = {'null_url_rows': {s: d.one(f'SELECT count(*) FROM {s}_sources WHERE url IS NULL') for s in d.dirs},
             'member_rows': {s: d.one(f'SELECT count(*) FROM {s}_sources WHERE member_path IS NOT NULL') for s in d.dirs},
             'same_url_rows_on_removed_documents': (on_removed := d.one("""SELECT count(*) FROM base_sources s JOIN sources_diff x
               ON s.url=x.url AND x.member_path IS NULL AND x.pn>x.ln AND x.ln>0 WHERE s.member_path IS NULL
               AND s.list_row IN (SELECT r FROM removed_rows)"""))}
    for g in out:
        if g['group'] == 'same-URL rows removed' and on_removed == -g['count']:
            g.update(status='verified', cause='every such row sat on a removed document')
        if g['group'] == 'NULL url':
            g['status'] = 'defect'
        if g['group'] == 'member rows removed' and d.link_causes and not d.one("""SELECT count(*) FROM sources_diff x
                WHERE x.member_path IS NOT NULL AND x.ln<x.pn AND NOT EXISTS (SELECT 1 FROM flips f WHERE f.a_real AND NOT f.b_real
                AND f.member_path=x.member_path AND f.context_url IS NOT DISTINCT FROM x.url)"""):
            g.update(status='verified', cause='every removed address has its own real-to-not flip')
    out = [g for g in out if g['count']] + moved(d, 'sources', ['url', 'member_path'])
    if {'list_row', 'url', 'member_path'} <= set(d.columns('base', 'sources')) & set(d.columns('candidate', 'sources')):
        out += d.changed('sources', paired('sources', ['url', 'member_path']),
                         only=['is_saved', 'first_seen', 'listed_on', 'link_text', 'doc_type', 'posted'])
    return out, notes


def moved(d: Diff, table, fields):
    """Keys on both sides whose documents differ, mapping base rows through the document pairs.

    Catches a source address, lookup key or recovery that now answers another document at
    the same multiplicity. A key on a removed or added document counts too: its answer
    changed. Set operations compare NULL fields as equal.
    """
    if not {'list_row', *fields} <= set(d.columns('base', table)) & set(d.columns('candidate', table)):
        return []
    cols = ','.join(fields)
    on = ' AND '.join(f's.{f} IS NOT DISTINCT FROM x.{f}' for f in fields)
    count = d.one(f"""WITH b AS (SELECT DISTINCT {','.join('p.' + f for f in fields)},x.lr AS r FROM base_{table} p JOIN pairs x ON p.list_row=x.pr),
      c AS (SELECT DISTINCT {cols},list_row AS r FROM candidate_{table}),
      shared AS (SELECT DISTINCT {cols} FROM base_{table} INTERSECT SELECT DISTINCT {cols} FROM candidate_{table}),
      diff AS (SELECT DISTINCT {cols} FROM ((SELECT * FROM b EXCEPT SELECT * FROM c) UNION ALL (SELECT * FROM c EXCEPT SELECT * FROM b)))
      SELECT count(*) FROM shared s WHERE EXISTS (SELECT 1 FROM diff x WHERE {on})""")
    return [dict(group('documents changed for a shared key', 'the key now answers other documents', count), value=True)] if count else []


def paired(table, fields):
    """Rows on one-to-one document pairs whose address is unique on both sides, aliased p and l."""
    on = ' AND '.join(f'p.{f} IS NOT DISTINCT FROM l.{f}' for f in fields)
    unique = lambda side, alias: (f"""(SELECT * FROM {side}_{table} QUALIFY count(*) OVER
        (PARTITION BY list_row,{','.join(fields)})=1) {alias}""")
    return (f"one_to_one o JOIN {unique('base', 'p')} ON p.list_row=o.pr "
            f"JOIN {unique('candidate', 'l')} ON l.list_row=o.lr AND {on}")


def recoveries(d: Diff):
    groups, notes = key_file('recoveries', 'body,recovered_url,kind')(d)
    groups += moved(d, 'recoveries', ['body', 'recovered_url', 'kind'])
    if 'list_row' in set(d.columns('base', 'recoveries')) & set(d.columns('candidate', 'recoveries')):
        groups += d.changed('recoveries', paired('recoveries', ['body', 'recovered_url', 'kind']),
                            only=['suffix', 'bytes', 'imported_at', 'identity_note'])
    return groups, notes


def generic(table):
    """Registry primary key: rows added and removed by identity, then value groups on matched rows."""
    def run(d: Diff):
        fields = d.identities[table]['fields']
        using = ','.join(f'"{f}"' for f in fields)
        removed = d.one(f'SELECT count(*) FROM base_{table} ANTI JOIN candidate_{table} USING({using})')
        added = d.one(f'SELECT count(*) FROM candidate_{table} ANTI JOIN base_{table} USING({using})')
        out = [group('removed keys', 'no evidence given', -removed), group('added keys', 'no evidence given', added)]
        return out + d.changed(table, f'base_{table} p JOIN candidate_{table} l USING({using})', exclude=set(fields)), {}
    return run


def key_file(table, key):
    def run(d: Diff):
        counted(d, table, key)
        removed, added = d.rows(f'SELECT sum(ln-pn) FILTER(ln<pn),sum(ln-pn) FILTER(ln>pn) FROM {table}_diff')[0]
        out = []
        if removed:
            out.append(group('removed keys', 'unexplained', removed))
        if added:
            out.append(group('added keys', 'unexplained', added))
        return out, {}
    return run


def meetings(d: Diff):
    groups, _ = key_file('meetings', 'event_id')(d)
    compare = {'transcripts': 'list_transform(X.{c},t->t.package_id)'}  # transcript list_row is release-local
    # A swapped or wiped subject key is a `changed subject_keys` group.
    return groups + d.changed('meetings', 'base_meetings p JOIN candidate_meetings l USING(event_id)', compare, set()), {}


def bills(d: Diff):
    removed = d.one('SELECT count(*) FROM base_bills ANTI JOIN candidate_bills USING(bill_id)')
    d.table('bill_refs', """SELECT DISTINCT lower(unnest(subject_keys)) k,'new meeting subject' cause FROM candidate_meetings
      EXCEPT SELECT DISTINCT lower(unnest(subject_keys)),'new meeting subject' FROM base_meetings""")
    added = d.rows("""SELECT coalesce(r.cause,'unexplained'),count(*) FROM (SELECT bill_id FROM candidate_bills ANTI JOIN base_bills USING(bill_id)) b
      LEFT JOIN bill_refs r ON r.k=lower(b.bill_id) GROUP BY 1""")
    out = [group('added bills', cause, n, 'verified') for cause, n in added]
    if removed:
        out.append(group('removed bills', 'unexplained', -removed))
    return out + d.changed('bills', 'base_bills p JOIN candidate_bills l USING(bill_id)', exclude=set()), {}


def recordings(d: Diff):
    groups, _ = key_file('recordings', 'video_key')(d)
    groups = [g for g in groups if g['group'] != 'added keys']
    if 'event_ids' not in {r[0] for r in d.rows('DESCRIBE candidate_recordings')}:
        groups.append(flag('event_ids column missing', 'unexplained'))
        added = d.one('SELECT count(*) FROM candidate_recordings ANTI JOIN base_recordings USING(video_key)')
        groups.append(group('added keys', 'event_ids unreadable', added))
    else:
        flips = ("EXISTS (SELECT 1 FROM flips f WHERE f.b_real AND NOT f.a_real AND split_part(l.video_key,':',2)<>'' AND contains(f.address,split_part(l.video_key,':',2)))"
                 if d.link_causes else 'false')
        for empty, tied, n in d.rows(f'''SELECT coalesce(len(event_ids),0)=0,{flips},count(*) FROM candidate_recordings l
          ANTI JOIN base_recordings USING(video_key) GROUP BY ALL ORDER BY ALL'''):
            events = 'empty event_ids' if empty else 'with event_ids'
            groups.append(group('added keys', f"{events}; {'capture newly real' if tied else 'source not traced'}", n,
                                'verified' if tied else 'unverified'))
    tracks = {'tracks': 'list_transform(X.{c},t->t.body)'}
    return groups + d.changed('recordings', 'base_recordings p JOIN candidate_recordings l USING(video_key)', tracks, set()), {}


OCCURRENCE = {'witness_key', 'record_sha', 'source_locator', 'context_key'}  # what witness_key hashes, besides occasion and source


def witnesses(d: Diff):
    """Witness keys by identity, and through the candidate's witness_key_map (ct-kb4w).

    Verified: a removed key whose unambiguous map row names a published witness (a re-key), and an
    added key that is such a successor. A removed key the map states ambiguous or unresolved, or
    does not list, a map that collapses distinct base occurrences, and any other added key stay
    unverified. Rows pair by key or through the map;
    value groups skip the occurrence the key hashes, which a direct match makes equal and a re-key
    changes by definition, and compare superseded_by through the map. Cannot see whether the map
    chose the right successor: the model's matching rules and their fixtures own that.
    """
    if not rekeyed(d):
        return generic('witnesses')(d)
    out = []
    for status, mapped, collision, n in d.rows("""SELECT coalesce(m.status,''),x.old_key IS NOT NULL,
          c.witness_key IS NOT NULL AND m.status='unambiguous',count(*)
          FROM (SELECT witness_key FROM base_witnesses ANTI JOIN candidate_witnesses USING(witness_key)) b
          LEFT JOIN candidate_witness_key_map m ON m.old_key=b.witness_key LEFT JOIN witness_rekey x ON x.old_key=b.witness_key
          LEFT JOIN witness_rekey_collisions c ON c.witness_key=m.witness_key
          GROUP BY ALL ORDER BY ALL"""):
        if mapped:
            out.append(group('removed keys', 're-keyed: witness_key_map names the published successor', -n, 'verified'))
        elif collision:
            out.append(group('removed keys', 'witness_key_map collapses distinct base occurrences', -n, 'defect'))
        elif status in ('ambiguous', 'unresolved'):
            out.append(group('removed keys', f'witness_key_map states the key {status}', -n))
        elif status:
            out.append(group('removed keys', 'unexplained', -n))  # an unambiguous row whose successor is not published
        else:
            out.append(group('removed keys', 'no evidence given', -n))
    for successor, n in d.rows("""SELECT witness_key IN (SELECT x.witness_key FROM witness_rekey x JOIN base_witnesses p ON p.witness_key=x.old_key),
          count(*) FROM candidate_witnesses ANTI JOIN base_witnesses USING(witness_key) GROUP BY 1 ORDER BY 1"""):
        out.append(group('added keys', 'successor of a re-keyed witness', n, 'verified') if successor
                   else group('added keys', 'no evidence given', n))
    d.view('base_witnesses_paired', """SELECT p.* REPLACE (coalesce(x.witness_key,p.witness_key) AS witness_key,
          coalesce(s.witness_key,p.superseded_by) AS superseded_by)
        FROM base_witnesses p LEFT JOIN witness_rekey x ON x.old_key=p.witness_key LEFT JOIN witness_rekey s ON s.old_key=p.superseded_by""")
    d.view('candidate_witnesses_paired', 'SELECT * FROM candidate_witnesses')
    return out + d.changed('witnesses_paired', 'base_witnesses_paired p JOIN candidate_witnesses_paired l USING(witness_key)',
                           exclude=OCCURRENCE), {}


def witness_key_map(d: Diff):
    """Old keys added to or dropped from the map; successors compare through the map.

    Verified: an added old key the base published in witnesses (retired in this release) or never
    published (it resolves no key a base reader could hold), and a dropped old key the candidate
    publishes again. A dropped key the candidate does not publish no longer resolves: unverified.
    A successor that moved is the same witness when the base successor itself maps to it.
    """
    if not d.has('base', 'witness_key_map'):
        return generic('witness_key_map')(d)
    rekeyed(d)
    out = []
    for published, n in d.rows("""SELECT old_key IN (SELECT witness_key FROM base_witnesses),count(*)
          FROM candidate_witness_key_map ANTI JOIN base_witness_key_map USING(old_key) GROUP BY 1 ORDER BY 1"""):
        out.append(group('added keys', 'key retired from witnesses in this release' if published
                         else 'a key no base witness carries', n, 'verified'))
    for again, n in d.rows("""SELECT old_key IN (SELECT witness_key FROM candidate_witnesses),count(*)
          FROM base_witness_key_map ANTI JOIN candidate_witness_key_map USING(old_key) GROUP BY 1 ORDER BY 1"""):
        out.append(group('removed keys', 'published again in witnesses', -n, 'verified') if again
                   else group('removed keys', 'no longer resolves', -n))
    join = 'base_witness_key_map p JOIN candidate_witness_key_map l USING(old_key)'
    for side, alias in (('base', 'pc'), ('candidate', 'lc')):
        mapped_keys = rekeyed_lists(d, f'{side}_witness_key_map', 'old_key', 'candidate_keys')
        join += (f' LEFT JOIN {mapped_keys} {alias} ON {alias}.old_key=p.old_key'
                 f' LEFT JOIN witness_rekey {alias[0]}s ON {alias[0]}s.old_key={alias[0]}.witness_key')
    compare = {'witness_key': 'coalesce(Xs.{c},X.{c})', 'candidate_keys': 'coalesce(Xc.{c},X.{c})'}
    return out + d.changed('witness_key_map', join, compare, exclude={'old_key'}), {}


def url_state(d: Diff):
    scope = json.loads((d.dirs['candidate'] / 'capture_scope.json').read_text())
    patterns = {re.compile(p) for e in scope['entries'] for p in e.get('exclusions', [])}
    removed = d.rows('SELECT requested_url,attempts FROM base_url_state ANTI JOIN candidate_url_state USING(requested_url)')
    matching = [(u, n) for u, n in removed if any(p.search(u) for p in patterns)]
    excluded = sum(not n for _, n in matching)
    attempted = len(matching) - excluded
    added = d.rows(f"""SELECT CASE WHEN attempts>0 THEN '{ATTEMPTED_URLS}'
        WHEN attempts=0 THEN 'queued link with no attempts yet' ELSE 'invalid attempt count' END,count(*)
        FROM {ADDED_URL_STATE} GROUP BY 1""")
    out = [group('removed URLs', 'never attempted and matches a live capture scope exclusion', -excluded, 'verified')]
    if attempted:
        out.append(group('removed URLs', 'matches an exclusion, but had fetch attempts', -attempted))
    if len(removed) - len(matching):
        out.append(group('removed URLs', 'unexplained', len(matching) - len(removed)))
    out += [group('added URLs', cause, n) for cause, n in added]
    return out + d.changed('url_state', 'base_url_state p JOIN candidate_url_state l USING(requested_url)', exclude=set()), {}


# ct-syp1: the weekly video cache refresh. `record_sha` (videos, channels) is the hash of the cache
# FILE a row was read from, and `recording_matches.source_ref` cites it; the file embeds fetch
# times, so a refresh rewrites every citation with no content change. Per table: its key and the
# columns that only cite or date the fetch. Every other column is content, by exclusion, so a
# column added later is content until someone lists it here. Content today:
#   channels: channel_id, system_code, committee_label, role, title, custom_url,
#     uploads_scan_complete, mapping_basis
#   videos: handle, channel_id, system_code, title, source_description, published_at,
#     video_published_at, duration_seconds, available, has_caption, stated_event_ids
#   recording_matches: subject_kind, subject_id, event_id, package_id, video_key, url, basis,
#     decision, score, recording_scope, status, note, meeting_links
CITATIONS = {'channels': ('handle', ('record_sha',)), 'videos': ('video_key', ('record_sha', 'details_checked_at')),
             'recording_matches': ('match_id', ('source_ref',))}
# The causes say what was checked, which is the two releases against each other and nothing else.
CITATION_MOVED = 'only the file citation moved: every content column equal on the row'
CITATION_FOLLOWS = "citation follows the video's record_sha: every other column equal on the row"


def _content_equal(d: Diff, table):
    """SQL for "every content column equal" on aliases p and l, or None when the check cannot run.

    It cannot run when the published key is not the one named here or the two releases' columns
    or types differ: a column with no partner has nothing to be equal to.
    """
    key, cited = CITATIONS[table]
    if not (d.has('base', table) and d.has('candidate', table)) or d.identities.get(table, {}).get('fields') != [key]:
        return None
    types = d.arrow_types('base', table)
    if types != d.arrow_types('candidate', table) or not {key, *cited} <= set(types):
        return None
    return ' AND '.join(f'p."{c}" IS NOT DISTINCT FROM l."{c}"' for c in types if c != key and c not in cited) or 'true'


def refetched_files(d: Diff):
    """Table `refetched_files(handle,o,n)`: channels whose cited file hash was replaced, old to new.

    A channel row qualifies when its content is equal, both hashes are present and differ, over
    all matched channels its old hash went to that one new hash and the new hash came from that
    one old hash, and the base release cites the new hash nowhere (not for a channel, not for a
    video). So one row re-pointed, two files folded into one, two files swapped, and a row that
    now cites another channel's old file each qualify nothing they touch.
    False when the check cannot run. One pass over channels (119 rows), built once.
    """
    if d.refetched is None:
        same = _content_equal(d, 'channels')
        d.refetched = same is not None
        if d.refetched:
            cited = ['SELECT record_sha FROM base_channels']
            if d.has('base', 'videos') and 'record_sha' in d.columns('base', 'videos'):
                cited.append('SELECT record_sha FROM base_videos')
            d.table('refetched_files', f"""WITH m AS (SELECT p.handle,p.record_sha o,l.record_sha n,({same}) same
                FROM base_channels p JOIN candidate_channels l USING(handle)),
              olds AS (SELECT o FROM m GROUP BY o HAVING count(DISTINCT n)=1),
              news AS (SELECT n FROM m GROUP BY n HAVING count(DISTINCT o)=1),
              cited AS (SELECT DISTINCT record_sha FROM ({' UNION ALL '.join(cited)}) WHERE record_sha IS NOT NULL)
              SELECT DISTINCT handle,o,n FROM m JOIN olds USING(o) JOIN news USING(n)
              WHERE same AND o<>n AND n NOT IN (SELECT record_sha FROM cited)""")
    return d.refetched


def new_citations(base_dir, candidate_dir):
    """Hex of every `record_sha` the candidate's channels and videos cite that the base's do not.

    The unattended gate checks each against the capture table (release_gate): a file the
    candidate cites for the first time must be a body some new receipt delivered. O(rows), 67k.
    """
    import pyarrow.parquet as pq
    def cited(directory):
        found = set()
        for table in ('channels', 'videos'):
            path = Path(directory) / f'{table}.parquet'
            if path.exists() and 'record_sha' in pq.read_schema(path).names:
                found.update(v for v in pq.read_table(path, columns=['record_sha'])['record_sha'].to_pylist() if v)
        return found
    return sorted(v.hex() for v in cited(candidate_dir) - cited(base_dir))


def cache_churn(table):
    """The registry comparison, with the rows of a citation group on which nothing else moved set
    apart as `verified` (ct-syp1).

    What is checked is the candidate against the live release, never a raw file:
      channels: see `refetched_files`.
      videos: content equal; the row cites its own channel's file in both releases and that
        channel qualified; `details_checked_at` is equal, or later than the live value and not
        later than the moment of comparison (a check is a past event; the gate's clock is the
        one time the candidate does not supply).
      recording_matches: every column but `source_ref` equal, and `source_ref` is
        `video_records:` plus that video's `record_sha` in each release.
    Such rows become a `verified` group flagged `citation_only`; the rest of the column's
    changed rows stay in the unverified `value differs on matched key` group and still need a
    recorded cause, as does every content column, added key and removed key. A row with any
    content change qualifies for nothing, so its citation change is counted with the
    unverified rows. Each check is one more aggregate over the matched rows the registry
    comparison already joins: O(rows), hash joins on the keys.
    The limit, stated plainly: this is self-consistency of what the candidate says about
    itself. A made-up hash applied consistently to every row of one old file is `verified`
    here, because the comparison reads two releases and no file. It does not show that a
    refresh happened, that the new hash is any file's, or that the file holds the published
    values. The unattended gate closes the first two against the capture table, which the
    candidate does not control (`release_gate.cited_files_are_new`); a reviewed publish has
    this check and a person.
    """
    def run(d: Diff):
        groups, notes = generic(table)(d)
        same = _content_equal(d, table)
        if same is None:
            return groups, notes
        if table == 'recording_matches':
            if not (d.has('base', 'videos') and d.has('candidate', 'videos')):
                return groups, notes
            cause = CITATION_FOLLOWS
            checked = d.rows(f"""SELECT count(*) FROM base_recording_matches p JOIN candidate_recording_matches l USING(match_id)
              JOIN base_videos pv ON pv.video_key=p.video_key JOIN candidate_videos lv ON lv.video_key=l.video_key
              WHERE {same} AND p.source_ref<>l.source_ref AND p.source_ref='video_records:'||lower(hex(pv.record_sha))
              AND l.source_ref='video_records:'||lower(hex(lv.record_sha))""")[0]
        elif not refetched_files(d):
            return groups, notes
        elif table == 'channels':
            cause = CITATION_MOVED
            checked = d.rows('SELECT count(*) FROM refetched_files')[0]
        else:
            cause = CITATION_MOVED
            later = f"(l.details_checked_at>p.details_checked_at AND l.details_checked_at<=TIMESTAMPTZ '{d.now.isoformat()}')"
            checked = d.rows(f"""SELECT count(*),count(*) FILTER (WHERE l.details_checked_at>p.details_checked_at)
              FROM base_videos p JOIN candidate_videos l USING(video_key)
              JOIN refetched_files f ON f.handle=l.handle AND f.o=p.record_sha AND f.n=l.record_sha
              WHERE {same} AND (p.details_checked_at IS NOT DISTINCT FROM l.details_checked_at OR {later})""")[0]
        out = []
        for g in groups:
            column = g['group'].removeprefix('changed ')
            n = checked[CITATIONS[table][1].index(column)] if g.get('value') and column in CITATIONS[table][1] else 0
            if n:
                out.append(dict(value_group(column, n), cause=cause, status='verified', citation_only=True))
                g = dict(g, count=g['count'] - n)
            if g['count'] or g.get('flag'):
                out.append(g)
        return out, notes
    return run


HANDLERS = {'list': document_file('list'), 'detail': document_file('detail'), 'links': links, 'urls': urls, 'sources': sources, 'meetings': meetings,
            'recoveries': recoveries,
            'recordings': recordings, 'bills': bills, 'url_state': url_state, 'witnesses': witnesses, 'witness_key_map': witness_key_map,
            **{table: cache_churn(table) for table in CITATIONS}}


def account(d: Diff):
    d.documents = documents(d)  # sources and both document files read its row sets
    report = {}
    for name in sorted(set(d.entry['base']) | set(d.entry['candidate'])):
        base, candidate = d.entry['base'].get(name), d.entry['candidate'].get(name)
        stem = name.removesuffix('.parquet')
        rows = {'base': (base or {}).get('rows', 0), 'candidate': (candidate or {}).get('rows', 0)}
        delta = rows['candidate'] - rows['base']
        same = bool(base and candidate and base['sha256'] == candidate['sha256'])
        groups, notes = [], {}
        handler = HANDLERS.get(stem)
        if handler is None and name.endswith('.parquet') and d.identities.get(stem, {}).get('kind') == 'primary_key':
            handler = generic(stem)
        if base is None or candidate is None:
            side = 'base' if base is None else 'candidate'
            groups = [group('file added' if base is None else 'file removed', f'file absent from the {side} release', delta)]
        elif not same and handler is not None:
            groups, notes = handler(d)
            for side, entry in (('base', base), ('candidate', candidate)):
                actual = d.one(f'SELECT count(*) FROM {side}_{stem}')
                if entry and actual != entry['rows']:
                    groups.append(group(f'{side} manifest disagrees with file', 'unexplained', entry['rows'] - actual))
        groups = [g for g in groups if g['count'] or g.get('flag')]
        for side, entry in (('base', base), ('candidate', candidate)):
            path = d.dirs[side] / name
            if entry and path.exists() and digest(path)['sha256'] != entry['sha256']:
                groups.append(flag(f'{side} manifest digest disagrees with file', 'unexplained'))
        if stem == 'sources' and candidate:
            # The 'NULL url' group is net (candidate minus base): only a positive part is new NULLs.
            # Subtracting a negative net (NULLs removed) used to report removed NULLs as persisting.
            persisting = d.one('SELECT count(*) FROM candidate_sources WHERE url IS NULL') - max(
                sum(g['count'] for g in groups if g['group'] == 'NULL url'), 0)
            if persisting:
                groups.append(flag(f'{persisting} NULL urls also present in the previous release', 'a published source address must not be null', 'defect'))
        if base and candidate and not same and handler is None:
            # A digest change that no comparison explains, such as an equal-count value change
            # in a file without a handler, used to pass silently.
            groups.append(flag('changed file without a comparison', 'unexplained'))
        elif base and candidate and not same and not groups:
            # A handler compared the file and found nothing, yet its bytes changed (for example
            # release-local row positions only). That claim needs a recorded cause, never silence.
            groups.append(flag('changed bytes, no key or value difference found', 'unexplained'))
        rowsum = sum(g['count'] for g in groups if not g.get('value'))
        residual = delta - rowsum
        if residual:
            groups.append(group('residual', 'unexplained', residual))
        report[name] = {'rows': rows, 'delta': delta, 'digest_identical': same, 'groups': groups, **notes,
                        'check': {'sum': delta - residual if residual else rowsum, 'ok': not residual}}
    return report


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return {'path': str(path), 'size': Path(path).stat().st_size, 'sha256': h.hexdigest()}


def write_removed_keys(d: Diff, path: Path):
    cause = "c.cause" if d.link_causes else "'no evidence given'"
    source = "LEFT JOIN link_causes c ON c.k=hex(p.link_key) AND c.sign=-1" if d.link_causes else ''
    rows = d.rows(f"""SELECT lower(hex(p.link_key)),{cause},l.filename FROM base_links p ANTI JOIN candidate_links x USING(link_key)
      {source} JOIN base_list l ON l.file_row_number=p.list_row ORDER BY 1""")
    with open(path, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as compressed:
        with io.TextIOWrapper(compressed, encoding='utf-8', newline='') as text:
            writer = csv.writer(text, lineterminator='\n')
            writer.writerow(['link_key', 'cause', 'previous_filename'])
            writer.writerows(rows)
    return len(rows)


def changed_answers(d: Diff):
    """Table `rule_changed`: live link keys that the candidate answers with another file (ct-4qld).

    A key the live release and the candidate both publish must reach a candidate row that serves
    either the live file (the live row's saved body) or the file the key names (a body whose
    SHA-256 begins with the key, data model §8.2). A row serves its saved body, its alternates and
    its recoveries. So these pass: the same saved file; the live file kept on the row as an
    alternate or a recovery while another body became the saved one; and a key that reaches its
    own file after a wrong join was split. This refuses: a key whose row serves neither, as when
    several documents are fused and only one file survives (a70ebc3d1466: six PDFs, one row).
    A retired key is the ledger's business and is not judged here. A live row with no saved body
    served no file, so its keys have nothing to compare.
    Two hash anti-joins over the key pairs `documents` already built: O(link keys + served bodies).
    Cannot see: whether an alternate or recovery recorded on a row is truly the same document
    (cae8e4ea34ec603a, ct-u9y4: two testimonies, one row; the saved_body value group reports it).
    Lookup keys and addresses are judged by `changed_addresses`, which reads the `served` table.
    Also builds `rule_demoted`: keys that pass only because the live file is now an alternate
    of a row that shows another body first. That is what a correct rendition join looks like
    and also what a wrong one does (a70ebc3d1466: 13 pages fused into PDFs), and "alternate" is
    the candidate's own claim, so `compare` reports them as a group that needs a recorded cause.
    Returns a reason, and builds nothing, when a release's detail has no saved_body: the rule
    then cannot run, and `link_rule` fails closed.
    """
    if not all(d.has(side, 'detail') and 'saved_body' in d.columns(side, 'detail') for side in d.dirs):
        return 'a release has no detail.saved_body, so no live key could be checked for answering another file'
    served = ["SELECT file_row_number r,saved_body body,'saved' how FROM candidate_detail"]
    if 'alternates' in d.columns('candidate', 'detail'):
        served.append("SELECT file_row_number,unnest(alternates).body,'alternate' FROM candidate_detail")
    if d.has('candidate', 'recoveries') and {'list_row', 'body'} <= set(d.columns('candidate', 'recoveries')):
        served.append("SELECT list_row,body,'recovery' FROM candidate_recoveries")
    d.table('served', f"SELECT DISTINCT r,body,left(hex(body),16) named,how FROM ({' UNION ALL '.join(served)}) WHERE body IS NOT NULL")
    d.table('rule_changed', """SELECT lower(hex(k.link_key)) k,k.pr,k.lr,lower(hex(p.saved_body)) live_body
      FROM key_pairs k JOIN base_detail p ON p.file_row_number=k.pr
      WHERE p.saved_body IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM served s WHERE s.r=k.lr AND s.body=p.saved_body)
      AND NOT EXISTS (SELECT 1 FROM served s WHERE s.r=k.lr AND s.named=hex(k.link_key))""")
    d.table('rule_demoted', """SELECT lower(hex(k.link_key)) k,k.pr,k.lr,lower(hex(p.saved_body)) live_body
      FROM key_pairs k JOIN base_detail p ON p.file_row_number=k.pr JOIN candidate_detail l ON l.file_row_number=k.lr
      WHERE p.saved_body IS NOT NULL AND l.saved_body IS DISTINCT FROM p.saved_body
      AND EXISTS (SELECT 1 FROM served s WHERE s.r=k.lr AND s.body=p.saved_body AND s.how='alternate')""")
    return None


ADDRESSED = {'urls': ('lookup_key',), 'sources': ('url', 'member_path')}  # what a reader follows to a document


def changed_addresses(d: Diff, table):
    """Table `rule_changed_<table>`: live lookup keys (`urls`) or addresses (`sources`) that the
    candidate answers with another file (ct-wscb). Run after `changed_answers`.

    A lookup key hashes a URL and an address is a URL (and archive member), so neither names a
    body the way a link key does, and the release carries no body beside them. The live row
    does: its saved body, and the bodies its own link keys name (the files that document
    published). So a key or address that both releases publish, on a live row with a saved body
    whose document the candidate still holds (one of its link keys is still a candidate link),
    must reach at least one candidate row that serves the live saved body or a body one of the
    live row's link keys names. These pass: the same file on any row (an address can hold
    several editions, each its own row); the live file kept as an alternate or recovery; and,
    after a wrong join is split, the half that holds one of the live document's own files.
    This refuses: an address whose every row serves none of them, as when documents are fused
    and one file survives (a70ebc3d1466: 12 lookup keys and 12 addresses of six PDFs).
    A key or address the candidate no longer publishes is the comparison's `keys gone` or
    `URLs gone` group, not judged here. Nor is a live document the candidate removed: its keys
    are retired by the ledger, its row is a `removed rows` group, and its address may rightly
    show only a newer edition (the removal notice lists it, §8.2). `moved` cannot see these: it maps live rows through
    the document pairs, so a merge leaves every key on "the same" document.
    Hash anti-joins over the rows of both tables and `served`: O(rows + served bodies + link keys).
    Cannot see: which of a wrongly joined live document's files an address named (the capture
    table knows, the release does not), so after a split an address sent to the wrong half
    passes; nor whether a recorded alternate or recovery is the same document.
    Returns a reason, and builds nothing, when either release lacks the table's columns:
    `link_rule` fails closed.
    """
    fields = ADDRESSED[table]
    if not all(d.has(side, table) and {'list_row', *fields} <= set(d.columns(side, table)) for side in d.dirs):
        return f'a release has no {table} with {", ".join(fields)}, so none could be checked for answering another file'
    on = ' AND '.join(f'l.{f} IS NOT DISTINCT FROM p.{f}' for f in fields)
    d.table(f'reach_{table}', f"""SELECT DISTINCT {','.join('l.' + f for f in fields)},s.body,s.named
      FROM candidate_{table} l JOIN served s ON s.r=l.list_row""")
    d.table(f'rule_changed_{table}', f"""SELECT {','.join('p.' + f for f in fields)},p.list_row pr,lower(hex(b.saved_body)) live_body
      FROM base_{table} p JOIN base_detail b ON b.file_row_number=p.list_row
      WHERE b.saved_body IS NOT NULL AND p.{fields[0]} IS NOT NULL
      AND EXISTS (SELECT 1 FROM pairs x WHERE x.pr=p.list_row)
      AND EXISTS (SELECT 1 FROM candidate_{table} l WHERE {on})
      AND NOT EXISTS (SELECT 1 FROM reach_{table} l WHERE {on} AND l.body=b.saved_body)
      AND NOT EXISTS (SELECT 1 FROM reach_{table} l JOIN base_links k ON hex(k.link_key)=l.named
                      WHERE {on} AND k.list_row=p.list_row)""")
    return None


def link_rule(d: Diff, sample=100):
    """Gate 2's publish check: no key published by the base or its ledger may vanish, and no
    live link key, lookup key or address may answer another file.

    missing: (base links ∪ base retired_links ∪ every named history release's links) minus
    (candidate links ∪ candidate retired_links).
    dangling: a candidate successor_key that is not a candidate link.
    changed: a live key the candidate answers with another file (`changed_answers`); each is
    listed with the live and candidate file.
    lookup_changed, address_changed: the same for lookup keys and addresses (`changed_addresses`).
    unchecked: why one of those three could not run (a column the rule reads is missing). The
    rule then fails: a check that did not run is never a pass.
    No record overrides any of the six.
    demoted: keys whose live file is now only an alternate of the row. Not a refusal of the
    rule; `compare` turns the count into a comparison group that needs a recorded cause.
    Cannot see whether a successor is the right document, or keys outside links (lookup keys,
    event IDs, witness keys, bill IDs), which value groups and release notes cover.
    """
    def keys(side):
        parts = [f'SELECT link_key FROM {side}_links']
        if d.has(side, 'retired_links'):
            parts.append(f'SELECT link_key FROM {side}_retired_links')
        if side == 'base':
            parts += [f'SELECT link_key FROM {name}' for name in d.history]
        return ' UNION '.join(parts)
    d.table('rule_missing', f"SELECT lower(hex(link_key)) k FROM ({keys('base')}) EXCEPT SELECT lower(hex(link_key)) FROM ({keys('candidate')})")
    dangling_sql = ("SELECT lower(hex(successor_key)) k FROM candidate_retired_links WHERE successor_key IS NOT NULL "
                    "EXCEPT SELECT lower(hex(link_key)) FROM candidate_links") if d.has('candidate', 'retired_links') else \
                   "SELECT cast(NULL AS VARCHAR) k WHERE false"
    d.table('rule_dangling', dangling_sql)
    out = {}
    for name in ('missing', 'dangling'):
        out[name] = d.one(f'SELECT count(*) FROM rule_{name}')
        out[name + '_keys'] = [r[0] for r in d.rows(f'SELECT k FROM rule_{name} ORDER BY k LIMIT {int(sample)}')]
    for label in ('', 'lookup_', 'address_'):
        out[label + 'changed'], out[label + 'changed_keys'], out[label + 'changed_answers'] = 0, [], []
    out['demoted'], out['demoted_keys'], out['unchecked'] = 0, [], []
    name = lambda side: f'{side}_list' if 'filename' in d.columns(side, 'list') else '(SELECT NULL filename,NULL file_row_number)'
    missing_input = changed_answers(d)
    if missing_input:
        out['unchecked'].append(missing_input)
    else:
        fields = ('key', 'live_row', 'live_file', 'live_body', 'candidate_row', 'candidate_file', 'candidate_body')
        for rule, label in (('rule_changed', 'changed'), ('rule_demoted', 'demoted')):
            out[label] = d.one(f'SELECT count(*) FROM {rule}')
            out[f'{label}_answers'] = [dict(zip(fields, r)) for r in d.rows(f"""SELECT c.k,c.pr,pl.filename,c.live_body,c.lr,ll.filename,lower(hex(ld.saved_body))
              FROM {rule} c JOIN candidate_detail ld ON ld.file_row_number=c.lr
              LEFT JOIN {name('base')} pl ON pl.file_row_number=c.pr LEFT JOIN {name('candidate')} ll ON ll.file_row_number=c.lr
              ORDER BY 1 LIMIT {int(sample)}""")]
            out[f'{label}_keys'] = [a['key'] for a in out[f'{label}_answers']]
        for table, label in (('urls', 'lookup'), ('sources', 'address')):
            missing_input = changed_addresses(d, table)
            if missing_input:
                out['unchecked'].append(missing_input)
                continue
            # One name per key or address: the hex lookup key, or the URL with its archive member.
            shown = ('lower(hex(c.lookup_key))' if table == 'urls' else
                     "c.url||CASE WHEN c.member_path IS NULL THEN '' ELSE ' member '||c.member_path END")
            on = ' AND '.join(f'l.{f} IS NOT DISTINCT FROM c.{f}' for f in ADDRESSED[table])
            out[f'{label}_changed'] = d.one(f'SELECT count(DISTINCT {shown}) FROM rule_changed_{table} c')
            fields = ('key', 'live_row', 'live_file', 'live_body', 'candidate_rows', 'candidate_files')
            out[f'{label}_changed_answers'] = [dict(zip(fields, r)) for r in d.rows(f"""SELECT {shown},c.pr,any_value(pl.filename),c.live_body,
                list_sort(list_distinct(list(l.list_row))),list_sort(list_distinct(list(ll.filename)))
              FROM rule_changed_{table} c JOIN candidate_{table} l ON {on}
              LEFT JOIN {name('base')} pl ON pl.file_row_number=c.pr LEFT JOIN {name('candidate')} ll ON ll.file_row_number=l.list_row
              GROUP BY 1,2,4 ORDER BY 1,2 LIMIT {int(sample)}""")]
            out[f'{label}_changed_keys'] = sorted({a['key'] for a in out[f'{label}_changed_answers']})
    out['ok'] = not any(out[name] for name in ('missing', 'dangling', 'changed', 'lookup_changed', 'address_changed', 'unchecked'))
    return out


def compare(base, candidate, *, evidence_base=None, evidence_candidate=None, record_digest=(), removed_keys=None, history=(), now=None):
    """Compare two local release directories; the report is the gate's only input.

    `now` is the moment of comparison (default: the clock), the upper bound for a check time.
    """
    if bool(evidence_base) != bool(evidence_candidate):
        raise ValueError('--evidence-base and --evidence-candidate go together')
    d = Diff(Path(base), Path(candidate), history, now)
    flips = add_evidence(d, evidence_base, evidence_candidate) if evidence_base else None
    files = account(d)
    rule = link_rule(d)
    if rule['demoted'] and 'links.parquet' in files:
        # ct-4qld review: the key still reaches its live file, but only as an alternate of a row
        # that shows another body. A right join and a wrong one look the same, so a person decides.
        files['links.parquet']['groups'].append(dict(group(
            'live file now an alternate', 'the key reaches a row whose saved file is another body', rule['demoted']), value=True))
    result = {'base_release': d.manifest['base']['release_id'], 'candidate_release': d.manifest['candidate']['release_id'],
              'compared_at': d.now.isoformat(), 'capture_flips': flips, 'files': files, 'link_rule': rule, 'cannot_see': d.cannot_see,
              'inputs': [digest(p) for p in [evidence_base, evidence_candidate, *record_digest] if p]}
    if removed_keys:
        result['removed_keys_written'] = write_removed_keys(d, removed_keys)
    failing = [{'file': n, **g} for n, f in files.items() for g in f['groups'] if g['status'] != 'verified']
    failed = [n for n, f in files.items() if not f['check']['ok']]
    result['ok'] = not failing and not failed and result['link_rule']['ok']
    result['failing'] = failing
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence-base')
    parser.add_argument('--evidence-candidate')
    parser.add_argument('--record-digest', action='append', default=[], help='extra input file to size and hash in the output')
    parser.add_argument('--removed-keys', type=Path, help='write removed link keys with cause as deterministic .csv.gz')
    args = parser.parse_args(argv)
    if bool(args.evidence_base) != bool(args.evidence_candidate):
        parser.error('--evidence-base and --evidence-candidate go together')
    result = compare(args.base, args.candidate, evidence_base=args.evidence_base, evidence_candidate=args.evidence_candidate,
                     record_digest=args.record_digest, removed_keys=args.removed_keys)
    args.output.write_text(json.dumps(result, indent=1, default=str) + '\n')
    for entry in result['failing']:
        print(f"{entry['status']} {entry['file']}: {entry['count']} {entry['group']} ({entry['cause']})", file=sys.stderr)
    for limit in result['cannot_see']:
        print(f'cannot see: {limit}', file=sys.stderr)
    rule = result['link_rule']
    if not rule['ok']:
        print(f"link rule: {rule['missing']} missing, {rule['dangling']} dangling; answering another file: {rule['changed']} link keys, "
              f"{rule['lookup_changed']} lookup keys, {rule['address_changed']} addresses; not checked: {rule['unchecked']}", file=sys.stderr)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
