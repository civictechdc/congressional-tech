#!/usr/bin/env python3
"""Account for every row-count change between two published archive releases.

Rows are matched on published identity, never on `list_row`, which is release-local.
Each file's groups must sum to its manifest delta; rows no rule explains go to an
`unexplained` group. Either failure exits 1. Evidence, when given, ties body keys to
capture eligibility flips. A clean result proves accounting, not that a row is right.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import duckdb

PARQUETS = 'list detail links urls sources recoveries meetings witnesses recordings bills url_state'.split()
OFFSETS = {'src_start', 'rec_start', 'file_row_number'}  # shift whenever an earlier row changes
TRIPLE = 'receipt_key,receipt_line,capture_index'


class Diff:
    def __init__(self, prev: Path, live: Path):
        self.dirs = {'prev': prev, 'live': live}
        self.manifest = {s: json.loads((d / 'manifest.json').read_text()) for s, d in self.dirs.items()}
        self.entry = {s: {f['name']: f for f in m['files']} for s, m in self.manifest.items()}
        self.con = duckdb.connect()
        for side, directory in self.dirs.items():
            for name in PARQUETS:
                path = directory / f'{name}.parquet'
                if path.exists():
                    extra = ',file_row_number=true' if name in ('list', 'detail') else ''
                    self.view(f'{side}_{name}', f"SELECT * FROM read_parquet('{path}'{extra})")
        self.link_causes = False

    def view(self, name, sql):
        self.con.execute(f'CREATE TEMP VIEW {name} AS {sql}')

    def table(self, name, sql):
        self.con.execute(f'CREATE TEMP TABLE {name} AS {sql}')

    def one(self, sql):
        return self.con.execute(sql).fetchone()[0] or 0

    def rows(self, sql):
        return self.con.execute(sql).fetchall()

    def changed(self, table, join, compare=None, exclude=OFFSETS):
        """Count per column how many matched rows differ; `join` must alias sides p and l."""
        columns = {r[0] for r in self.rows(f'DESCRIBE prev_{table}')} & {r[0] for r in self.rows(f'DESCRIBE live_{table}')}
        out = {}
        for column in sorted(columns - set(exclude)):
            template = (compare or {}).get(column, 'X.{c}')
            left, right = (template.replace('X', s).format(c=f'"{column}"') for s in 'pl')
            count = self.one(f'SELECT count(*) FROM {join} WHERE {left} IS DISTINCT FROM {right}')
            if count:
                out[column] = count
        return out


def group(name, cause, count):
    return {'group': name, 'cause': cause, 'count': int(count)}


def add_evidence(diff: Diff, prev_path: str, live_path: str):
    """Attribute link keys through capture eligibility flips; a flip never proves v20 was right."""
    diff.table('flips', f"""SELECT {TRIPLE},a.member_path,left(hex(a.sha256),16) k,a.is_real_file a_real,b.is_real_file b_real
      FROM (SELECT {TRIPLE},member_path,sha256,is_real_file FROM read_parquet('{prev_path}')) a
      JOIN (SELECT {TRIPLE},is_real_file FROM read_parquet('{live_path}')) b USING({TRIPLE})
      WHERE a.is_real_file IS DISTINCT FROM b.is_real_file""")
    diff.table('real_prev', f"""SELECT left(hex(sha256),16) k,bool_or(member_path IS NULL) top
      FROM read_parquet('{prev_path}') WHERE is_real_file GROUP BY 1""")
    diff.table('link_causes', """
      SELECT hex(p.link_key) k,p.list_row,-1 sign,CASE
        WHEN NOT EXISTS (SELECT 1 FROM flips f WHERE f.k=hex(p.link_key) AND f.a_real AND NOT f.b_real) THEN 'unexplained'
        WHEN r.top THEN 'top-level body no longer eligible' ELSE 'member-only body no longer real' END cause
      FROM prev_links p ANTI JOIN live_links l USING(link_key) LEFT JOIN real_prev r ON r.k=hex(p.link_key)
      UNION ALL
      SELECT hex(l.link_key),l.list_row,1,CASE
        WHEN EXISTS (SELECT 1 FROM flips f WHERE f.k=hex(l.link_key) AND f.b_real AND NOT f.a_real) THEN 'newly eligible body'
        ELSE 'unexplained' END
      FROM live_links l ANTI JOIN prev_links p USING(link_key)""")
    diff.link_causes = True
    flips = diff.rows("""SELECT a_real,b_real,member_path IS NOT NULL,count(*) FROM flips GROUP BY ALL ORDER BY 4 DESC""")
    return [dict(zip(('prev_real', 'live_real', 'member', 'rows'), r)) for r in flips]


def links(d: Diff):
    if d.link_causes:
        return [group(f'{"added" if s > 0 else "removed"} keys', c, s * n)
                for s, c, n in d.rows('SELECT sign,cause,count(*) FROM link_causes GROUP BY ALL ORDER BY 1,2')], {}
    removed = d.one('SELECT count(*) FROM prev_links ANTI JOIN live_links USING(link_key)')
    added = d.one('SELECT count(*) FROM live_links ANTI JOIN prev_links USING(link_key)')
    return [group('removed keys', 'no evidence given', -removed), group('added keys', 'no evidence given', added)], {}


def documents(d: Diff):
    d.table('pairs', 'SELECT DISTINCT p.list_row pr,l.list_row lr FROM prev_links p JOIN live_links l USING(link_key)')
    d.table('pn', 'SELECT pr,count(*) n FROM pairs GROUP BY 1')
    d.table('ln', 'SELECT lr,count(*) n FROM pairs GROUP BY 1')
    d.table('member_rows', 'SELECT DISTINCT list_row FROM prev_sources WHERE member_path IS NOT NULL')
    out = [group('split rows', 'previous row had a member source' if m else 'previous row had no member source', n)
           for m, n in d.rows("""SELECT pr IN (SELECT list_row FROM member_rows),sum(n-1) FROM pn WHERE n>1 GROUP BY 1""")]
    merged = d.one('SELECT sum(n-1) FROM ln WHERE n>1')
    if merged:
        out.append(group('merged rows', 'previous rows now share one document', -merged))
    for side, sign, partner, label in (('prev', -1, 'pn', 'removed'), ('live', 1, 'ln', 'added')):
        key = 'pr' if side == 'prev' else 'lr'
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
              GROUP BY 1"""):
                out.append(group(f'{label} rows', cause, sign * n))
                total -= n
            if total:
                out.append(group(f'{label} rows', 'unexplained', sign * total))
        elif total:
            out.append(group(f'{label} rows', 'no surviving link key', sign * total))
    shape = {'prev_rows_by_live_rows': dict(d.rows('SELECT n::VARCHAR,count(*) FROM pn GROUP BY 1 ORDER BY 1')),
             'live_rows_by_prev_rows': dict(d.rows('SELECT n::VARCHAR,count(*) FROM ln GROUP BY 1 ORDER BY 1')),
             'components_with_split_and_merge': d.one('SELECT count(*) FROM pairs JOIN pn USING(pr) JOIN ln USING(lr) WHERE pn.n>1 AND ln.n>1')}
    d.table('one_to_one', 'SELECT pr,lr FROM pairs JOIN pn USING(pr) JOIN ln USING(lr) WHERE pn.n=1 AND ln.n=1')
    shape['one_to_one_rows'] = d.one('SELECT count(*) FROM one_to_one')
    return out, shape


def document_file(table):
    def run(d: Diff):
        groups, shape = d.documents
        join = f'one_to_one JOIN prev_{table} p ON p.file_row_number=pr JOIN live_{table} l ON l.file_row_number=lr'
        return groups, {**(shape if table == 'list' else {}), 'one_to_one_field_changes': d.changed(table, join)}
    return run


def counted(d: Diff, table, key):
    """Compare key multiplicity; the FULL JOIN matches NULL keys with IS NOT DISTINCT FROM."""
    names = [k.strip() for k in key.split(',')]
    on = ' AND '.join(f'p.{k} IS NOT DISTINCT FROM l.{k}' for k in names)
    picked = ','.join(f'coalesce(p.{k},l.{k}) {k}' for k in names)
    d.table(f'{table}_diff', f"""SELECT {picked},coalesce(p.n,0) pn,coalesce(l.n,0) ln FROM
      (SELECT {key},count(*) n FROM prev_{table} GROUP BY ALL) p FULL JOIN
      (SELECT {key},count(*) n FROM live_{table} GROUP BY ALL) l ON {on} WHERE coalesce(p.n,0)<>coalesce(l.n,0)""")


def urls(d: Diff):
    counted(d, 'urls', 'lookup_key')
    gone, new, fewer, more = d.rows("""SELECT sum(ln-pn) FILTER(ln=0),sum(ln-pn) FILTER(pn=0),
      sum(ln-pn) FILTER(pn>0 AND ln>0 AND ln<pn),sum(ln-pn) FILTER(pn>0 AND ln>pn) FROM urls_diff""")[0]
    histogram = [dict(zip(('prev_rows', 'live_rows', 'keys'), r)) for r in
                 d.rows('SELECT pn,ln,count(*) FROM urls_diff GROUP BY 1,2 ORDER BY 3 DESC,1,2')]
    return [group('keys gone', 'every row for the key was removed', gone or 0),
            group('keys new', 'key absent from the previous release', new or 0),
            group('keys with fewer rows', 'fewer documents answer the key', fewer or 0),
            group('keys with more rows', 'more documents answer the key', more or 0)], {'histogram': histogram}


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
             'same_url_rows_on_removed_documents': d.one("""SELECT count(*) FROM prev_sources s JOIN sources_diff x
               ON s.url=x.url AND x.member_path IS NULL AND x.pn>x.ln AND x.ln>0 WHERE s.member_path IS NULL
               AND s.list_row IN (SELECT r FROM removed_rows)""")}
    return out, notes


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
    return groups, {'shared_field_changes': d.changed('meetings', 'prev_meetings p JOIN live_meetings l USING(event_id)', compare, set())}


def bills(d: Diff):
    removed = d.one('SELECT count(*) FROM prev_bills ANTI JOIN live_bills USING(bill_id)')
    d.table('bill_refs', """SELECT DISTINCT lower(unnest(subject_keys)) k,'new meeting subject' cause FROM live_meetings""")
    added = d.rows("""SELECT coalesce(r.cause,'unexplained'),count(*) FROM (SELECT bill_id FROM live_bills ANTI JOIN prev_bills USING(bill_id)) b
      LEFT JOIN bill_refs r ON r.k=lower(b.bill_id) GROUP BY 1""")
    out = [group('added bills', cause, n) for cause, n in added]
    if removed:
        out.append(group('removed bills', 'unexplained', -removed))
    return out, {'shared_field_changes': d.changed('bills', 'prev_bills p JOIN live_bills l USING(bill_id)', exclude=set())}


def recordings(d: Diff):
    groups, _ = key_file('recordings', 'video_key')(d)
    groups = [g | {'cause': 'new key with empty event_ids'} if g['group'] == 'added keys' else g for g in groups]
    tracks = {'tracks': 'list_transform(X.{c},t->t.body)'}
    return groups, {'shared_field_changes': d.changed('recordings', 'prev_recordings p JOIN live_recordings l USING(video_key)', tracks, set())}


def witnesses(d: Diff):
    d.table('wp', "SELECT occasion,lower(trim(name)) n,count(*) c FROM prev_witnesses GROUP BY 1,2")
    d.table('wl', "SELECT occasion,lower(trim(name)) n,count(*) c FROM live_witnesses GROUP BY 1,2")
    d.table('wd', """SELECT coalesce(p.occasion,l.occasion) o,coalesce(p.n,l.n) n,coalesce(p.c,0) pc,coalesce(l.c,0) lc FROM wp p
      FULL JOIN wl l ON p.occasion=l.occasion AND p.n IS NOT DISTINCT FROM l.n WHERE coalesce(p.c,0)<>coalesce(l.c,0)""")
    out = []
    for name, cause, where in (
        ('pairs only previous, occasion gone', 'occasion absent from live', 'lc=0 AND o NOT IN (SELECT occasion FROM wl)'),
        ('pairs only previous, occasion kept', 'name absent from this occasion in live', 'lc=0 AND o IN (SELECT occasion FROM wl)'),
        ('pairs only live, new occasion', 'occasion absent from previous', 'pc=0 AND o NOT IN (SELECT occasion FROM wp)'),
        ('pairs only live, occasion kept', 'name absent from this occasion in previous', 'pc=0 AND o IN (SELECT occasion FROM wp)'),
        ('repeated occurrences', 'same name counted more often on a shared occasion', 'pc>0 AND lc>pc'),
        ('fewer occurrences', 'same name counted less often on a shared occasion', 'lc>0 AND pc>lc'),
    ):
        out.append(group(name, cause, d.one(f'SELECT sum(lc-pc) FROM wd WHERE {where}')))
    return out, {'occasions': {s: d.one(f'SELECT count(DISTINCT occasion) FROM {s}_witnesses') for s in d.dirs},
                 'note': 'witness_key was compared by (occasion, lower(trim(name))) because keys were redefined'}


def url_state(d: Diff):
    scope = json.loads((d.dirs['live'] / 'capture_scope.json').read_text())
    patterns = {re.compile(p) for e in scope['entries'] for p in e.get('exclusions', [])}
    removed = [r[0] for r in d.rows('SELECT requested_url FROM prev_url_state ANTI JOIN live_url_state USING(requested_url)')]
    excluded = sum(any(p.search(u) for p in patterns) for u in removed)
    added = d.rows("""SELECT attempts=0,count(*) FROM live_url_state ANTI JOIN prev_url_state USING(requested_url) GROUP BY 1""")
    out = [group('removed URLs', 'matches a live capture scope exclusion', -excluded)]
    if len(removed) - excluded:
        out.append(group('removed URLs', 'unexplained', excluded - len(removed)))
    out += [group('added URLs', 'queued link with no attempts yet' if queued else 'new attempts', n) for queued, n in added]
    return out, {'shared_field_changes': d.changed('url_state', 'prev_url_state p JOIN live_url_state l USING(requested_url)', exclude=set())}


HANDLERS = {'list': document_file('list'), 'detail': document_file('detail'), 'links': links, 'urls': urls, 'sources': sources, 'meetings': meetings,
            'recoveries': key_file('recoveries', 'body,recovered_url,kind'), 'witnesses': witnesses,
            'recordings': recordings, 'bills': bills, 'url_state': url_state}


def account(d: Diff):
    d.documents = documents(d)  # sources and both document files read its row sets
    report = {}
    for name in sorted(set(d.entry['prev']) | set(d.entry['live'])):
        prev, live = d.entry['prev'].get(name), d.entry['live'].get(name)
        stem = name.removesuffix('.parquet')
        rows = {'prev': (prev or {}).get('rows', 0), 'live': (live or {}).get('rows', 0)}
        delta = rows['live'] - rows['prev']
        same = bool(prev and live and prev['sha256'] == live['sha256'])
        groups, notes = [], {}
        if not same and stem in HANDLERS:
            groups, notes = HANDLERS[stem](d)
            for side, entry in (('prev', prev), ('live', live)):
                actual = d.one(f'SELECT count(*) FROM {side}_{stem}')
                if entry and actual != entry['rows']:
                    groups.append(group(f'{side} manifest disagrees with file', 'unexplained', entry['rows'] - actual))
        groups = [g for g in groups if g['count']]
        residual = delta - sum(g['count'] for g in groups)
        if residual:
            groups.append(group('residual', 'unexplained', residual))
        report[name] = {'rows': rows, 'delta': delta, 'digest_identical': same, 'groups': groups, **notes,
                        'check': {'sum': sum(g['count'] for g in groups), 'ok': not residual}}
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
    rows = d.rows(f"""SELECT lower(hex(p.link_key)),{cause},l.filename FROM prev_links p ANTI JOIN live_links x USING(link_key)
      {source} JOIN prev_list l ON l.file_row_number=p.list_row ORDER BY 1""")
    with open(path, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as compressed:
        with io.TextIOWrapper(compressed, encoding='utf-8', newline='') as text:
            writer = csv.writer(text, lineterminator='\n')
            writer.writerow(['link_key', 'cause', 'previous_filename'])
            writer.writerows(rows)
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prev', type=Path, required=True)
    parser.add_argument('--live', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence-prev')
    parser.add_argument('--evidence-live')
    parser.add_argument('--record-digest', action='append', default=[], help='extra input file to size and hash in the output')
    parser.add_argument('--removed-keys', type=Path, help='write removed link keys with cause as deterministic .csv.gz')
    args = parser.parse_args(argv)
    if bool(args.evidence_prev) != bool(args.evidence_live):
        parser.error('--evidence-prev and --evidence-live go together')
    d = Diff(args.prev, args.live)
    flips = add_evidence(d, args.evidence_prev, args.evidence_live) if args.evidence_prev else None
    files = account(d)
    result = {'prev_release': d.manifest['prev']['release_id'], 'live_release': d.manifest['live']['release_id'],
              'capture_flips': flips, 'files': files,
              'inputs': [digest(p) for p in [args.evidence_prev, args.evidence_live, *args.record_digest] if p]}
    if args.removed_keys:
        result['removed_keys_written'] = write_removed_keys(d, args.removed_keys)
    unexplained = [(n, g) for n, f in files.items() for g in f['groups'] if g['cause'] == 'unexplained']
    failed = [n for n, f in files.items() if not f['check']['ok']]
    result['ok'] = not unexplained and not failed
    args.output.write_text(json.dumps(result, indent=1, default=str) + '\n')
    for name, group_ in unexplained:
        print(f'unexplained {name}: {group_}', file=sys.stderr)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
