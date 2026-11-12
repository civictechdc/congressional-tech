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
QUEUED_URLS = 'queued link with no attempts yet'


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
        self.meeting_update = None  # set by updated_meetings()
        self.subject_update = None  # set by updated_subjects()
        self.doc_subjects = None  # set by document_subjects()
        self.witness_update = None  # set by updated_witnesses()
        self.meeting_refetch = None  # set by refetched_meetings()
        self.refetched = None  # set by refetched_files()
        self.dirty_rm = None  # set by _dirty_rm_events()
        self.dirty_captions = None  # set by _dirty_caption_videos()
        self.caption_tx = None  # set by _caption_tx_moves()

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


def witness_collision_sql(*, rc_rel, base_witnesses_rel=None, base_map_rel=None, has_base_map_cols=False):
    """SQL query returning `witness_key` values in `rc_rel(old_key, witness_key)` (unambiguous published
    re-key rows) that collapse two or more distinct base occurrences (live witnesses or base map keys,
    including a witness whose key survives directly)."""
    if not base_witnesses_rel and not (base_map_rel and has_base_map_cols):
        return f'SELECT witness_key FROM {rc_rel} WHERE false'
    prior = []
    if base_witnesses_rel:
        prior.append(f"SELECT witness_key AS old_key,'w:'||witness_key AS base_key FROM {base_witnesses_rel}")
    if base_map_rel and has_base_map_cols:
        prior.append(f"""SELECT old_key,CASE WHEN status='unambiguous' AND witness_key IS NOT NULL
          THEN 'w:'||witness_key ELSE 'm:'||old_key END AS base_key FROM {base_map_rel}""")
    surviving = (f"UNION SELECT r.witness_key,'w:'||s.witness_key FROM {rc_rel} r JOIN {base_witnesses_rel} s USING(witness_key)"
                 if base_witnesses_rel else '')
    return f"""WITH prior AS ({' UNION '.join(prior)}),
      held AS (SELECT r.witness_key,p.base_key FROM {rc_rel} r JOIN prior p USING(old_key) {surviving})
      SELECT witness_key FROM held GROUP BY 1 HAVING count(*)>1"""


def rekeyed(d: Diff):
    """The candidate's unambiguous witness_key_map rows (ct-kb4w) as table `witness_rekey`; False when
    the candidate publishes no map.

    A successor can carry keys from several historical releases. Within the base release, a re-key
    must preserve each occurrence (live witnesses and base map keys), including a witness whose key
    survives directly.
    """
    if d.witness_rekey is None:
        d.witness_rekey = d.has('candidate', 'witness_key_map') and d.has('candidate', 'witnesses')
        if d.witness_rekey:
            d.table('witness_rekey_candidates', """SELECT m.old_key,m.witness_key
              FROM candidate_witness_key_map m JOIN candidate_witnesses w USING(witness_key)
              WHERE m.status='unambiguous'""")
            has_map = (d.has('base', 'witness_key_map')
                       and {'old_key', 'witness_key', 'status'} <= set(d.columns('base', 'witness_key_map')))
            collisions = witness_collision_sql(
                rc_rel='witness_rekey_candidates',
                base_witnesses_rel='base_witnesses' if d.has('base', 'witnesses') else None,
                base_map_rel='base_witness_key_map' if d.has('base', 'witness_key_map') else None,
                has_base_map_cols=has_map)
            d.table('witness_rekey_collisions', collisions)
            d.table('witness_rekey', """SELECT r.* FROM witness_rekey_candidates r
              ANTI JOIN witness_rekey_collisions USING(witness_key)""")
    return d.witness_rekey


# The re-fetch exemption (ct-syp1, ct-uywf, ct-rhqw): a source served again moves the rows that cite
# it. Such a row is set apart as a `verified` group flagged `refetch_only`, which needs no cause entry;
# the unattended gate lets a flagged group through only after it finds every body and read the
# candidate cites for the first time in the capture table, in receipts the live release did not read
# (`release_gate.cited_files_are_new`). A video cache refresh and a byte-identical meeting read may
# move only their citations; a Congress.gov meeting read with new bytes may move everything the
# meeting's record states (owner, 2026-11-11: "Everything from Congress.gov publishes").
MEETING_UPDATE = 'a Congress.gov update of its meeting, read again with new bytes (ct-rhqw)'
FIRST_STATED = 'a meeting Congress.gov states for the first time, read from its detail record (ct-rhqw)'
NEW_SUBJECT = 'a new subject of a Congress.gov meeting update (ct-rhqw)'
# The meeting columns a Congress.gov detail record states, the only ones an update may move. A column
# not named here, such as `transcripts` (GovInfo) or `house_xml_updated` (House XML) or one added
# later, is never exempt. House XML leads several of these (title, date, type, committees, videos,
# meeting-records-merged.sql), so an update also requires the meeting's House sightings unchanged.
UPDATE_COLUMNS = ('chamber', 'chamber_basis', 'title', 'meeting_date', 'meeting_type', 'session', 'status', 'sittings',
                  'committees', 'subject_keys', 'videos', 'congress', 'congress_gov_updated', 'congress_gov_meeting_type',
                  'access', 'access_basis', 'not_held', 'document_references', 'publisher_status',
                  'publisher_status_observations', 'congress_gov_detail_observation')
# The outcome moves with an update only when the candidate bases it on the new read (a Congress.gov
# cancellation names the read's body) and the live outcome was the publisher's too: a print or a
# transcript is another source, and its reference is a release-local row.
OUTCOME = ('outcome', 'outcome_basis', 'outcome_source_reference', 'outcome_reason')
PUBLISHER_OUTCOMES = ('publisher_cancellation', 'no_outcome_evidence')
RESCHEDULED = ('rescheduled_to', 'rescheduled_basis')
RESCHEDULED_BASES = ('publisher_status', 'recording_on_later_twin')


def _equal_except(d: Diff, table, skip, compare=None):
    """SQL for "every column but `skip` equal" on aliases p and l, or None when the check cannot run:
    the two releases' columns or types differ, and a column with no partner has nothing to be equal
    to. Every column not skipped counts, so a column added later is compared until someone skips it.
    `compare` maps a column to the expression it is compared by, as in `Diff.changed`."""
    types = d.arrow_types('base', table)
    if types != d.arrow_types('candidate', table) or not set(skip) <= set(types):
        return None
    terms = []
    for c in types:
        if c not in skip:
            left, right = ((compare or {}).get(c, 'X.{c}').replace('X', s).format(c=f'"{c}"') for s in 'pl')
            terms.append(f'{left} IS NOT DISTINCT FROM {right}')
    return ' AND '.join(terms) or 'true'


def changed_counts(d: Diff, join, groups, where, compare=None):
    """For each `changed <column>` value group of `Diff.changed` in `groups`, the matched rows of `join`
    (aliases p and l) meeting `where` whose column differs, compared as `Diff.changed` compares it.
    A group for a subfield (`column.field`) is not counted, so it stays whole."""
    columns = [g['group'].removeprefix('changed ') for g in groups if g.get('value') and g['cause'] == 'value differs on matched key']
    columns = [c for c in dict.fromkeys(columns) if '.' not in c]
    if not columns:
        return {}
    terms = []
    for c in columns:
        left, right = ((compare or {}).get(c, 'X.{c}').replace('X', s).format(c=f'"{c}"') for s in 'pl')
        terms.append(f'count(*) FILTER (WHERE {left} IS DISTINCT FROM {right})')
    return dict(zip(columns, d.rows(f'SELECT {",".join(terms)} FROM {join} WHERE {where}')[0]))


def refetch_split(groups, counts, cause):
    """Each `changed <column>` value group of `Diff.changed` with `counts[column]` re-fetch rows, those
    rows set apart as a verified group flagged `refetch_only`; the rest stay in the unverified group."""
    out = []
    for g in groups:
        column = g['group'].removeprefix('changed ')
        n = counts.get(column, 0) if g.get('value') and g['cause'] == 'value differs on matched key' else 0
        if n:
            out.append(dict(value_group(column, n), cause=cause, status='verified', refetch_only=True))
            g = dict(g, count=g['count'] - n)
        if g['count'] or g.get('flag'):
            out.append(g)
    return out


def split_group(groups, name, cause, n, flagged_cause):
    """The first group named `name` with `cause`, `n` of its rows set apart as a verified group
    flagged `refetch_only` with `flagged_cause`; the rest keep the group as it was."""
    out, done = [], False
    for g in groups:
        if not done and n and g['group'] == name and g['cause'] == cause:
            done, signed = True, n if g['count'] > 0 else -n
            out.append(dict(g, cause=flagged_cause, count=signed, status='verified', refetch_only=True))
            g = dict(g, count=g['count'] - signed)
        if g['count'] or g.get('flag'):
            out.append(g)
    return out


def document_subjects(d: Diff):
    """Tables `doc_meeting_subjects(event_id,k)` (single-meeting candidate documents' measure_keys, which
    entity-meetings.sql copies into `meetings.subject_keys`) and `new_doc_subjects(k)` (candidate document
    measure_keys absent from base documents)."""
    if d.doc_subjects is None:
        cand_cols = set(d.columns('candidate', 'list')) if d.has('candidate', 'list') else set()
        base_cols = set(d.columns('base', 'list')) if d.has('base', 'list') else set()
        if {'meeting_keys', 'measure_keys'} <= cand_cols:
            d.table('doc_meeting_subjects', """SELECT DISTINCT try_cast(meeting_keys[1] AS BIGINT) AS event_id,
                lower(unnest(measure_keys)) AS k FROM candidate_list
                WHERE len(meeting_keys)=1 AND measure_keys IS NOT NULL AND try_cast(meeting_keys[1] AS BIGINT) IS NOT NULL""")
        else:
            d.table('doc_meeting_subjects', 'SELECT CAST(NULL AS BIGINT) AS event_id,CAST(NULL AS VARCHAR) AS k WHERE false')
        if 'measure_keys' in cand_cols:
            prior = (' EXCEPT SELECT DISTINCT lower(unnest(measure_keys)) FROM base_list WHERE measure_keys IS NOT NULL'
                     if 'measure_keys' in base_cols else '')
            d.table('new_doc_subjects', f'SELECT DISTINCT lower(unnest(measure_keys)) AS k FROM candidate_list WHERE measure_keys IS NOT NULL{prior}')
        else:
            d.table('new_doc_subjects', 'SELECT CAST(NULL AS VARCHAR) AS k WHERE false')
        d.doc_subjects = True
    return d.doc_subjects


def updated_meetings(d: Diff):
    """Table `meeting_update(event_id,body,added)`: the meetings the candidate read from Congress.gov
    again with new bytes, or for the first time (`added`), with the new body; True when there is one
    (ct-rhqw). On such a meeting every change its record can make publishes without a person: the
    `UPDATE_COLUMNS` of the meeting row, its Congress.gov witnesses (added; removed with a successor;
    edited, reordered), their key-map rows, the documents that name them, its witness coverage and
    its new subjects.

    The read is the meeting's `successful_read`: it names a body and a receipt, is a read of this
    meeting's own record (the address ends in its event ID), is not later than the moment of
    comparison, and the live release cites its body nowhere (no witness, no meeting read), so the
    bytes are new. Every sighting and stamp from another source (`publisher_status_observations`,
    `house_xml_updated`) is unchanged on a matched meeting and absent on a first-stated one (along
    with transcripts and single-meeting document `measure_keys`), because a House read leads title,
    date and videos (`meeting-records-merged.sql`). Cannot see whether the read happened or whether
    a null-status, unchanged-stamp House XML body was also captured: the unattended gate checks
    both against the capture table (`release_gate.cited_files_are_new`). O(meetings).
    """
    if d.meeting_update is None:
        d.meeting_update = False
        cand_cols = set(d.columns('candidate', 'meetings')) if d.has('candidate', 'meetings') else set()
        shared = (set(d.columns('base', 'meetings')) & cand_cols
                  if d.has('base', 'meetings') and d.has('candidate', 'meetings') else set())
        if DETAIL not in shared:
            return False
        document_subjects(d)
        read = lambda side: f'{side}.{DETAIL}.successful_read'
        cited = [f'SELECT lower({DETAIL}.successful_read.body_sha256) b FROM base_meetings',
                 f'SELECT lower({DETAIL}.latest_attempt.evidence.body_sha256) FROM base_meetings']
        if d.has('base', 'witnesses') and 'record_sha' in d.columns('base', 'witnesses'):
            cited.append('SELECT lower(hex(record_sha)) FROM base_witnesses')
        first_terms = ['NOT EXISTS (SELECT 1 FROM doc_meeting_subjects ds WHERE ds.event_id=l.event_id)']
        matched_terms = ['true']
        if STATUSES in cand_cols:
            elsewhere = lambda side: f"list_sort(list_filter({side}.{STATUSES},e->e.source IS DISTINCT FROM 'congress_gov'))"
            first_terms.append(f"len({elsewhere('l')})=0")
            if STATUSES in shared:
                matched_terms.append(f"{elsewhere('p')} IS NOT DISTINCT FROM {elsewhere('l')}")
        if 'house_xml_updated' in cand_cols:
            first_terms.append('l.house_xml_updated IS NULL')
            if 'house_xml_updated' in shared:
                matched_terms.append('p.house_xml_updated IS NOT DISTINCT FROM l.house_xml_updated')
        if 'transcripts' in cand_cols:
            first_terms.append('coalesce(len(l.transcripts),0)=0')
        first_ok, others = ' AND '.join(first_terms), ' AND '.join(matched_terms)
        d.table('meeting_update', f"""WITH cited AS ({' UNION '.join(cited)})
          SELECT l.event_id,lower({read('l')}.body_sha256) AS body,p.event_id IS NULL AS added
          FROM candidate_meetings l LEFT JOIN base_meetings p ON p.event_id=l.event_id
          WHERE {read('l')}.body_sha256 IS NOT NULL AND {read('l')}.receipt_key IS NOT NULL
            AND regexp_extract({read('l')}.source_url,'/([0-9]+)([?#].*)?$',1)=CAST(l.event_id AS VARCHAR)
            AND coalesce({read('l')}.retrieved_at<=TIMESTAMPTZ '{d.now.isoformat()}',false)
            AND lower({read('l')}.body_sha256) NOT IN (SELECT b FROM cited WHERE b IS NOT NULL)
            AND ((p.event_id IS NULL AND {first_ok}) OR (p.event_id IS NOT NULL AND {read('l')}.receipt_key IS DISTINCT FROM {read('p')}.receipt_key
              AND ({read('p')}.retrieved_at IS NULL OR {read('l')}.retrieved_at>{read('p')}.retrieved_at) AND {others}))""")
        d.meeting_update = d.one('SELECT count(*) FROM meeting_update') > 0
    return d.meeting_update


def updated_subjects(d: Diff):
    """Tables `clean_subject_meetings(event_id,added)` and `new_update_subjects(k)`: updated meetings
    whose `subject_keys` carry no transcript change or single-meeting document `measure_keys` injection,
    and the subject keys those updates introduce to the archive for the first time (ct-rhqw)."""
    if d.subject_update is None:
        d.subject_update = False
        shared = (set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings'))
                  if updated_meetings(d) else set())
        if 'subject_keys' not in shared:
            return False
        document_subjects(d)
        same_tx = _same_transcripts(d, non_captions=True)
        empty = 'CAST([] AS VARCHAR[])'
        d.table('clean_subject_meetings', f"""SELECT u.event_id,u.added FROM meeting_update u
          JOIN candidate_meetings l USING(event_id) LEFT JOIN base_meetings p USING(event_id)
          WHERE u.added OR ({same_tx} AND NOT EXISTS (
            SELECT 1 FROM (SELECT lower(unnest(coalesce(l.subject_keys,{empty}))) AS k
              EXCEPT SELECT lower(unnest(coalesce(p.subject_keys,{empty})))) a
            JOIN doc_meeting_subjects ds ON ds.event_id=l.event_id AND ds.k=a.k))""")
        d.table('new_update_subjects', """SELECT DISTINCT lower(unnest(l.subject_keys)) AS k
          FROM clean_subject_meetings u JOIN candidate_meetings l USING(event_id) WHERE l.subject_keys IS NOT NULL
          EXCEPT SELECT DISTINCT lower(unnest(p.subject_keys)) FROM base_meetings p WHERE p.subject_keys IS NOT NULL
          EXCEPT SELECT k FROM doc_meeting_subjects WHERE event_id IN (SELECT event_id FROM clean_subject_meetings)
          EXCEPT SELECT k FROM new_doc_subjects""")
        d.subject_update = True
    return d.subject_update


def updated_witnesses(d: Diff):
    """Tables `witness_update_base(witness_key,occasion)` and `witness_update_candidate(witness_key,occasion)`: the
    Congress.gov witness rows of the meetings `updated_meetings` names, on each side; True when they
    exist. A candidate row counts only when its body is the meeting's new read, so a witness is moved
    by the read that was proven, not by another body; a base row is any of the meeting's live
    Congress.gov witnesses. A MODS print, a House list or a Senate page on the same meeting is
    another source and is not exempt. Interim for re-keys: carried witness keys (ct-46f3) end them.
    """
    if d.witness_update is None:
        d.witness_update = False
        columns = {'source', 'occasion', 'record_sha', 'witness_key'}
        if (updated_meetings(d) and d.has('base', 'witnesses') and d.has('candidate', 'witnesses')
                and columns <= set(d.columns('base', 'witnesses')) & set(d.columns('candidate', 'witnesses'))):
            d.table('witness_update_base', """SELECT w.witness_key,w.occasion FROM meeting_update u JOIN base_witnesses w
              ON w.occasion='meeting:'||u.event_id WHERE w.source='congress_gov' AND NOT u.added""")
            d.table('witness_update_candidate', """SELECT w.witness_key,w.occasion FROM meeting_update u JOIN candidate_witnesses w
              ON w.occasion='meeting:'||u.event_id WHERE w.source='congress_gov' AND lower(hex(w.record_sha))=u.body""")
            d.witness_update = True
    return d.witness_update


def rekeyed_lists(d: Diff, relation, row, column):
    """`relation`'s `column` keys mapped through witness_rekey, sorted and distinct, per `row`, as table
    `<relation>_rekeyed_<column>`. A join, not a MAP value per row: a MAP lookup scans the map."""
    name = f'{relation}_rekeyed_{column}'
    d.table(name, f"""SELECT u.{row},list_sort(list_distinct(list(coalesce(x.witness_key,u.k)))) AS {column}
      FROM (SELECT {row},unnest({column}) AS k FROM {relation}) u LEFT JOIN witness_rekey x ON x.old_key=u.k
      GROUP BY u.{row}""")
    return name


GENERIC_DOC_TITLE_RE = (
    r'(?i)^(?:witness\s+(?:statement|testimony|biography)|(?:prepared|written)\s+statement'
    r'|testimony|biography|truth\s+in\s+testimony(?:\s+form|\s+disclosure(?:\s+form)?)?)$'
)
DOC_UPDATE_COLS = {'meeting_keys', 'title', 'document_date', 'document_date_source', 'document_date_status',
                   'committee_keys', 'chambers', 'congress'}


def _document_meeting_updates(d: Diff, table, join, shared, compare, clean_w_rel, out):
    """Split held one-to-one document columns that moved solely because a linked Congress.gov meeting
    updated (`meeting_keys` on a matched meeting's newly added witness, `document_date` with source
    `meeting`, `committee_keys`, `chambers`, `congress`, and generic witness-derived `title`, ct-rhqw)."""
    import pyarrow as pa
    changed_cols = {g['group'].removeprefix('changed ') for g in out
                    if g.get('value') and g['cause'] == 'value differs on matched key'}
    if not (changed_cols & DOC_UPDATE_COLS) or not updated_meetings(d):
        return out
    empty = 'CAST([] AS VARCHAR[])'
    clean_mk_rel = f'{table}_clean_mk'
    has_clean_mk = False
    counts = {}
    if 'meeting_keys' in shared and 'witness_keys' in shared and updated_witnesses(d) and 'meeting_keys' in changed_cols:
        left_w_arr = (f"coalesce(pw.witness_keys,p.witness_keys,{empty})" if compare
                      else f"coalesce(p.witness_keys,{empty})")
        w_ok = (f'(p.witness_keys IS NOT DISTINCT FROM l.witness_keys OR p.file_row_number IN (SELECT pr FROM {clean_w_rel}))'
                if clean_w_rel else 'p.witness_keys IS NOT DISTINCT FROM l.witness_keys')
        d.table(clean_mk_rel, f"""WITH cand AS (
              SELECT p.file_row_number AS pr,l.file_row_number AS lr,
                coalesce(p.meeting_keys,{empty}) AS pmk,coalesce(l.meeting_keys,{empty}) AS lmk,
                {left_w_arr} AS pwk,coalesce(l.witness_keys,{empty}) AS lwk
              FROM {join} WHERE p.meeting_keys IS DISTINCT FROM l.meeting_keys AND {w_ok}
                AND list_has_all(coalesce(l.meeting_keys,{empty}),coalesce(p.meeting_keys,{empty}))),
            bad AS (
              SELECT pr FROM (SELECT pr,pmk,pwk,lwk,unnest(lmk) AS mk FROM cand)
              WHERE NOT list_contains(pmk,mk)
                AND (try_cast(mk AS BIGINT) IS NULL
                  OR try_cast(mk AS BIGINT) NOT IN (SELECT event_id FROM meeting_update WHERE NOT added)
                  OR NOT EXISTS (SELECT 1 FROM witness_update_candidate wc
                    WHERE wc.occasion='meeting:'||mk AND list_contains(lwk,wc.witness_key)
                      AND NOT list_contains(pwk,wc.witness_key))))
            SELECT pr,lr FROM cand WHERE pr NOT IN (SELECT pr FROM bad)""")
        has_clean_mk = True
        counts['meeting_keys'] = d.one(f'SELECT count(*) FROM {clean_mk_rel}')

    m_both = d.has('base', 'meetings') and d.has('candidate', 'meetings')
    m_shared = set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings')) if m_both else set()
    if 'meeting_keys' in shared and 'event_id' in m_shared:
        mk_same_upd = f"""(p.meeting_keys IS NOT DISTINCT FROM l.meeting_keys
            AND EXISTS (SELECT 1 FROM unnest(coalesce(l.meeting_keys,{empty})) t(mk)
              WHERE try_cast(mk AS BIGINT) IN (SELECT event_id FROM meeting_update WHERE NOT added)))"""
        mk_ok = f'({mk_same_upd} OR p.file_row_number IN (SELECT pr FROM {clean_mk_rel}))' if has_clean_mk else mk_same_upd
        upd_rel = f'{table}_upd_docs'
        d.table(upd_rel, f'SELECT p.file_row_number AS pr,l.file_row_number AS lr FROM {join} WHERE {mk_ok}')
        if d.one(f'SELECT count(*) FROM {upd_rel}'):
            upd_join = f'{upd_rel} u JOIN base_{table} p ON p.file_row_number=u.pr JOIN candidate_{table} l ON l.file_row_number=u.lr'
            if changed_cols & {'document_date', 'document_date_source', 'document_date_status'} and 'meeting_date' in m_shared and 'document_date' in shared:
                p_md = f"(SELECT min(m.meeting_date) FROM base_meetings m WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(m.event_id AS VARCHAR)))"
                l_md = f"(SELECT min(m.meeting_date) FROM candidate_meetings m WHERE list_contains(coalesce(l.meeting_keys,{empty}),CAST(m.event_id AS VARCHAR)))"
                non_upd_md = f"""NOT EXISTS (SELECT 1 FROM base_meetings bm JOIN candidate_meetings cm USING(event_id)
                    WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(bm.event_id AS VARCHAR))
                      AND bm.event_id NOT IN (SELECT event_id FROM meeting_update WHERE NOT added)
                      AND bm.meeting_date IS DISTINCT FROM cm.meeting_date)"""
                date_join = upd_join
                if 'document_date_source' in shared:
                    src_ok = (f" AND p.document_date_source IS NOT DISTINCT FROM (CASE WHEN {p_md} IS NOT NULL THEN 'meeting' END)"
                              f" AND l.document_date_source IS NOT DISTINCT FROM (CASE WHEN {l_md} IS NOT NULL THEN 'meeting' END)")
                elif (d.has('base', 'detail') and d.has('candidate', 'detail')
                      and 'document_date_source' in set(d.columns('base', 'detail')) & set(d.columns('candidate', 'detail'))):
                    date_join += ' JOIN base_detail bd ON bd.file_row_number=u.pr JOIN candidate_detail cd ON cd.file_row_number=u.lr'
                    src_ok = (f" AND bd.document_date_source IS NOT DISTINCT FROM (CASE WHEN {p_md} IS NOT NULL THEN 'meeting' END)"
                              f" AND cd.document_date_source IS NOT DISTINCT FROM (CASE WHEN {l_md} IS NOT NULL THEN 'meeting' END)")
                else:
                    src_ok = ''
                date_where = f'p.document_date IS NOT DISTINCT FROM {p_md} AND l.document_date IS NOT DISTINCT FROM {l_md} AND {non_upd_md}{src_ok}'
                for col in ('document_date', 'document_date_source'):
                    if col in changed_cols and col in shared:
                        counts[col] = d.one(f'SELECT count(*) FROM {date_join} WHERE p."{col}" IS DISTINCT FROM l."{col}" AND {date_where}')
                if 'document_date_status' in changed_cols and 'document_date_status' in shared:
                    st_where = (f"{date_where} AND p.document_date_status IS NOT DISTINCT FROM (CASE WHEN p.document_date IS NOT NULL THEN 'accepted' END)"
                                f" AND l.document_date_status IS NOT DISTINCT FROM (CASE WHEN l.document_date IS NOT NULL THEN 'accepted' END)")
                    counts['document_date_status'] = d.one(
                        f'SELECT count(*) FROM {date_join} WHERE p.document_date_status IS DISTINCT FROM l.document_date_status AND {st_where}')

            if 'congress' in changed_cols and 'congress' in shared and 'congress' in m_shared:
                p_cg = f"(SELECT min(m.congress) FROM base_meetings m WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(m.event_id AS VARCHAR)))"
                l_cg = f"(SELECT min(m.congress) FROM candidate_meetings m WHERE list_contains(coalesce(l.meeting_keys,{empty}),CAST(m.event_id AS VARCHAR)))"
                non_upd_cg = f"""NOT EXISTS (SELECT 1 FROM base_meetings bm JOIN candidate_meetings cm USING(event_id)
                    WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(bm.event_id AS VARCHAR))
                      AND bm.event_id NOT IN (SELECT event_id FROM meeting_update WHERE NOT added)
                      AND bm.congress IS DISTINCT FROM cm.congress)"""
                counts['congress'] = d.one(
                    f'SELECT count(*) FROM {upd_join} WHERE p.congress IS DISTINCT FROM l.congress '
                    f'AND p.congress IS NOT DISTINCT FROM {p_cg} AND l.congress IS NOT DISTINCT FROM {l_cg} AND {non_upd_cg}')

            def set_follow_count(col, side_list_sql, non_upd_same_sql):
                pc, lc = f'coalesce(p."{col}",{empty})', f'coalesce(l."{col}",{empty})'
                up = side_list_sql('base', 'p.meeting_keys', 'IN')
                ul = side_list_sql('candidate', 'l.meeting_keys', 'IN')
                kp = side_list_sql('base', 'p.meeting_keys', 'NOT IN')
                return d.one(f"""WITH s AS (
                      SELECT {pc} AS pc,{lc} AS lc,{up} AS up,{ul} AS ul,{kp} AS kp
                      FROM {upd_join} WHERE p."{col}" IS DISTINCT FROM l."{col}" AND {non_upd_same_sql})
                    SELECT count(*) FROM s
                    WHERE list_has_all(pc,up) AND list_has_all(lc,ul) AND list_has_all(pc,kp) AND list_has_all(lc,kp)
                      AND len(list_filter(pc,lambda x: NOT list_contains(lc,x) AND (NOT list_contains(up,x) OR list_contains(ul,x) OR list_contains(kp,x))))=0
                      AND len(list_filter(lc,lambda x: NOT list_contains(pc,x) AND (NOT list_contains(ul,x) OR list_contains(up,x) OR list_contains(kp,x))))=0""")

            if 'chambers' in changed_cols and 'chambers' in shared and 'chamber' in m_shared:
                ch_list = lambda side, mk_col, op: (
                    f"coalesce((SELECT list_distinct(list_filter(list(nullif(lower(trim(m.chamber)),'')),lambda v: v IS NOT NULL)) "
                    f"FROM {side}_meetings m WHERE list_contains(coalesce({mk_col},{empty}),CAST(m.event_id AS VARCHAR)) "
                    f"AND m.event_id {op} (SELECT event_id FROM meeting_update WHERE NOT added)),{empty})")
                non_upd_ch = f"""NOT EXISTS (SELECT 1 FROM base_meetings bm JOIN candidate_meetings cm USING(event_id)
                    WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(bm.event_id AS VARCHAR))
                      AND bm.event_id NOT IN (SELECT event_id FROM meeting_update WHERE NOT added)
                      AND nullif(lower(trim(bm.chamber)),'') IS DISTINCT FROM nullif(lower(trim(cm.chamber)),''))"""
                counts['chambers'] = set_follow_count('chambers', ch_list, non_upd_ch)

            comm_type = d.arrow_types('base', 'meetings').get('committees') if 'committees' in m_shared else None
            if ('committee_keys' in changed_cols and 'committee_keys' in shared and comm_type is not None
                    and comm_type == d.arrow_types('candidate', 'meetings').get('committees')
                    and (pa.types.is_list(comm_type) or pa.types.is_large_list(comm_type))
                    and pa.types.is_struct(comm_type.value_type) and comm_type.value_type.get_field_index('system_code') >= 0):
                cm_list = lambda side, mk_col, op: (
                    f"coalesce((SELECT list_distinct(list_filter(list(nullif(lower(trim(mc.c.system_code)),'')),lambda v: v IS NOT NULL)) "
                    f"FROM (SELECT event_id,unnest(committees) AS c FROM {side}_meetings WHERE committees IS NOT NULL) mc "
                    f"WHERE list_contains(coalesce({mk_col},{empty}),CAST(mc.event_id AS VARCHAR)) "
                    f"AND mc.event_id {op} (SELECT event_id FROM meeting_update WHERE NOT added)),{empty})")
                non_upd_cm = f"""NOT EXISTS (SELECT 1 FROM base_meetings bm JOIN candidate_meetings cm USING(event_id)
                    WHERE list_contains(coalesce(p.meeting_keys,{empty}),CAST(bm.event_id AS VARCHAR))
                      AND bm.event_id NOT IN (SELECT event_id FROM meeting_update WHERE NOT added)
                      AND bm.committees IS DISTINCT FROM cm.committees)"""
                counts['committee_keys'] = set_follow_count('committee_keys', cm_list, non_upd_cm)

    w_both = d.has('base', 'witnesses') and d.has('candidate', 'witnesses')
    w_shared = set(d.columns('base', 'witnesses')) & set(d.columns('candidate', 'witnesses')) if w_both else set()
    if 'title' in changed_cols and {'title', 'witness_keys'} <= shared and {'witness_key', 'name'} <= w_shared and updated_witnesses(d):
        not_sup = lambda alias: f'{alias}.superseded_by IS NULL' if 'superseded_by' in w_shared else 'true'
        wname_sql = lambda side, wk_expr: f"""(SELECT CASE
            WHEN count(DISTINCT w.witness_key) FILTER (WHERE {not_sup('w')})=1 THEN min(w.name) FILTER (WHERE {not_sup('w')})
            WHEN count(DISTINCT w.witness_key)=1 THEN min(w.name) END
          FROM {side}_witnesses w WHERE list_contains(coalesce({wk_expr},{empty}),w.witness_key))"""
        has_fn_p = "coalesce(p.filename,'')<>''" if 'filename' in shared else 'true'
        has_fn_l = "coalesce(l.filename,'')<>''" if 'filename' in shared else 'true'
        w_row_ok = [f'p.file_row_number IN (SELECT pr FROM {clean_w_rel})'] if clean_w_rel else []
        sup_touch = (" OR cw.superseded_by IN (SELECT witness_key FROM witness_update_candidate)"
                     if 'superseded_by' in w_shared else '')
        w_row_ok.append(f"""(p.witness_keys IS NOT DISTINCT FROM l.witness_keys
            AND EXISTS (SELECT 1 FROM candidate_witnesses cw
              WHERE list_contains(coalesce(l.witness_keys,{empty}),cw.witness_key)
                AND (cw.witness_key IN (SELECT witness_key FROM witness_update_candidate){sup_touch})))""")
        mk_guard = (f' AND p.file_row_number IN (SELECT pr FROM {table}_upd_docs)'
                    if 'meeting_keys' in shared and 'event_id' in m_shared else '')
        counts['title'] = d.one(f"""WITH t AS (
              SELECT p.title AS pt,l.title AS lt,{has_fn_p} AS pfn,{has_fn_l} AS lfn,
                {wname_sql('base', 'p.witness_keys')} AS pw,{wname_sql('candidate', 'l.witness_keys')} AS lw
              FROM {join} WHERE p.title IS DISTINCT FROM l.title AND ({' OR '.join(w_row_ok)}){mk_guard})
            SELECT count(*) FROM t WHERE pw IS DISTINCT FROM lw AND (
              (pw IS NOT NULL AND lw IS NOT NULL AND pt IS NOT NULL AND lt IS NOT NULL
                AND ends_with(pt,' - '||pw) AND ends_with(lt,' - '||lw)
                AND left(pt,length(pt)-length(' - '||pw))=left(lt,length(lt)-length(' - '||lw))
                AND regexp_matches(trim(left(pt,length(pt)-length(' - '||pw))),'{GENERIC_DOC_TITLE_RE}'))
              OR (pw IS NULL AND lw IS NOT NULL AND lt IS NOT NULL AND ends_with(lt,' - '||lw)
                AND regexp_matches(trim(left(lt,length(lt)-length(' - '||lw))),'{GENERIC_DOC_TITLE_RE}')
                AND ((pt IS NULL AND pfn) OR (pt=left(lt,length(lt)-length(' - '||lw)) AND NOT pfn)))
              OR (pw IS NOT NULL AND lw IS NULL AND pt IS NOT NULL AND ends_with(pt,' - '||pw)
                AND regexp_matches(trim(left(pt,length(pt)-length(' - '||pw))),'{GENERIC_DOC_TITLE_RE}')
                AND ((lt IS NULL AND lfn) OR (lt=left(pt,length(pt)-length(' - '||pw)) AND NOT lfn))))""")

    return refetch_split(out, counts, MEETING_UPDATE) if counts else out


def document_file(table):
    def run(d: Diff):
        groups, shape = d.documents
        join = f'one_to_one JOIN base_{table} p ON p.file_row_number=pr JOIN candidate_{table} l ON l.file_row_number=lr'
        compare, rekeys = None, []
        shared = set(d.columns('base', table)) & set(d.columns('candidate', table))
        if rekeyed(d) and 'witness_keys' in shared:
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
        out = [*groups, *rekeys, *d.changed(table, join, compare, exclude=OFFSETS | {'file_row_number'})]
        clean_w_rel = None
        if 'witness_keys' in shared and updated_witnesses(d):
            # ct-rhqw: a document whose list gained or lost only witnesses of its own updated meetings.
            empty = 'CAST([] AS VARCHAR[])'
            left_w, right_w = (
                (compare['witness_keys'].replace('X', s).format(c='"witness_keys"') for s in 'pl')
                if compare else ('p."witness_keys"', 'l."witness_keys"'))
            if 'meeting_keys' in shared:
                mk_cols = f',coalesce(p.meeting_keys,{empty}) AS pmk,coalesce(l.meeting_keys,{empty}) AS lmk'
                mk_sel = ',pmk,lmk'
                rem_ok = 'EXISTS (SELECT 1 FROM witness_update_base wb WHERE wb.witness_key=k AND list_contains(pmk,split_part(wb.occasion,\':\',2)))'
                add_ok = """EXISTS (SELECT 1 FROM witness_update_candidate wc JOIN meeting_update mu ON wc.occasion='meeting:'||mu.event_id
                    WHERE wc.witness_key=k AND list_contains(lmk,split_part(wc.occasion,':',2))
                      AND (NOT mu.added OR list_contains(pmk,split_part(wc.occasion,':',2))))"""
            else:
                mk_cols, mk_sel = '', ''
                rem_ok = 'k IN (SELECT witness_key FROM witness_update_base)'
                add_ok = 'k IN (SELECT witness_key FROM witness_update_candidate)'
            clean_w_rel = f'{table}_clean_w'
            d.table(clean_w_rel, f"""WITH r AS (SELECT p.file_row_number AS pr,{left_w} IS NOT DISTINCT FROM {right_w} AS mapped,
                  coalesce(p.witness_keys,{empty}) AS pk,coalesce(l.witness_keys,{empty}) AS lk{mk_cols}
                  FROM {join} WHERE p.witness_keys IS DISTINCT FROM l.witness_keys),
                keys AS (SELECT pr,pk,lk{mk_sel},unnest(list_concat(pk,lk)) AS k FROM r),
                outside AS (SELECT DISTINCT pr FROM keys WHERE (list_contains(pk,k) AND NOT list_contains(lk,k) AND NOT ({rem_ok}))
                  OR (list_contains(lk,k) AND NOT list_contains(pk,k) AND NOT ({add_ok})))
              SELECT pr,mapped FROM r WHERE pr NOT IN (SELECT pr FROM outside)""")
            moved, value = d.rows(f'SELECT count(*) FILTER (WHERE mapped),count(*) FILTER (WHERE NOT mapped) FROM {clean_w_rel}')[0]
            if compare:
                out = split_group(out, 'changed witness_keys', 're-keyed through witness_key_map', moved, f're-keyed through witness_key_map; {MEETING_UPDATE}')
            out = refetch_split(out, {'witness_keys': value}, MEETING_UPDATE)
        out = _document_meeting_updates(d, table, join, shared, compare, clean_w_rel, out)
        return out, shape if table == 'list' else {}
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


def _transcript_compare_expr(d: Diff, alias='X', col='{c}', *, non_captions=False):
    """Compare `meetings.transcripts` across all non-`list_row` struct fields (`list_row` is release-local)."""
    import pyarrow as pa
    bt = d.arrow_types('base', 'meetings').get('transcripts') if d.has('base', 'meetings') else None
    ct = d.arrow_types('candidate', 'meetings').get('transcripts') if d.has('candidate', 'meetings') else None
    if (bt is not None and bt == ct and (pa.types.is_list(bt) or pa.types.is_large_list(bt))
            and pa.types.is_struct(bt.value_type)):
        names = {f.name for f in bt.value_type}
        src = f"list_filter({alias}.{col},t->t.source IS DISTINCT FROM 'captions')" if non_captions and 'source' in names else f'{alias}.{col}'
        fields = [f.name for f in bt.value_type if f.name != 'list_row']
        if not fields:
            return f'coalesce(len({src}),0)'
        packed = ','.join(f'"{name}":=t."{name}"' for name in fields)
        return f'list_transform({src},t->struct_pack({packed}))'
    return None


def _meeting_compare(d: Diff):
    expr = _transcript_compare_expr(d)
    return {'transcripts': expr} if expr is not None else {}


def _same_transcripts(d: Diff, left='p', right='l', *, non_captions=False):
    if not (d.has('base', 'meetings') and d.has('candidate', 'meetings')):
        return 'true'
    if 'transcripts' not in set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings')):
        return 'true'
    lp = _transcript_compare_expr(d, left, 'transcripts', non_captions=non_captions)
    rp = _transcript_compare_expr(d, right, 'transcripts', non_captions=non_captions)
    if lp is None or rp is None:
        return (f'{left}.transcripts IS NOT DISTINCT FROM {right}.transcripts'
                if d.arrow_types('base', 'meetings').get('transcripts') == d.arrow_types('candidate', 'meetings').get('transcripts')
                else 'false')
    return f'{lp} IS NOT DISTINCT FROM {rp}'


def _caption_tx_moves(d: Diff):
    """Table `caption_tx_moves(event_id)`: matched `meeting_update` events whose `transcripts` differ solely
    because `videos` linked or unlinked a recording already held in `base_recordings` and `candidate_recordings`
    with unchanged non-empty caption `tracks` (ct-rhqw)."""
    import pyarrow as pa
    if d.caption_tx is None:
        d.caption_tx = False
        if (updated_meetings(d) and d.has('base', 'meetings') and d.has('candidate', 'meetings')
                and d.has('base', 'recordings') and d.has('candidate', 'recordings')):
            m_shared = set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings'))
            r_shared = set(d.columns('base', 'recordings')) & set(d.columns('candidate', 'recordings'))
            bt = d.arrow_types('base', 'meetings').get('transcripts')
            if ({'transcripts', 'videos'} <= m_shared and {'video_key', 'tracks'} <= r_shared
                    and bt is not None and bt == d.arrow_types('candidate', 'meetings').get('transcripts')
                    and (pa.types.is_list(bt) or pa.types.is_large_list(bt)) and pa.types.is_struct(bt.value_type)
                    and {'source', 'package_id', 'video_key'} <= {f.name for f in bt.value_type}):
                dirty_rm = _dirty_rm_events(d, alias='pm')
                dirty_cap = _dirty_caption_videos(d, pm='pm', lm='lm')
                same_non_cap = _same_transcripts(d, 'pm', 'lm', non_captions=True)
                cap_keys = lambda s: (f"list_distinct(list_transform(list_filter(coalesce({s}.transcripts,[]),"
                                      f"lambda t: t.source='captions' AND t.package_id IS NULL),lambda t: t.video_key))")
                bad_cap = lambda s: (f"len(list_filter(coalesce({s}.transcripts,[]),"
                                     f"lambda t: t.source='captions' AND (t.package_id IS NOT NULL OR t.video_key IS NULL)))=0")
                vid_keys = lambda s: (f"list_distinct(list_filter(list_transform(coalesce({s}.videos,[]),"
                                      f"lambda v: v.video_key),lambda vk: vk IS NOT NULL))")
                d.table('caption_tx_moves', f"""WITH held AS (
                      SELECT p.video_key FROM base_recordings p JOIN candidate_recordings l USING(video_key)
                      WHERE coalesce(len(p.tracks),0)>0
                        AND list_transform(p.tracks,lambda t: t.body) IS NOT DISTINCT FROM list_transform(l.tracks,lambda t: t.body)),
                    cand AS (
                      SELECT pm.event_id,{cap_keys('pm')} AS pck,{cap_keys('lm')} AS lck,
                        {vid_keys('pm')} AS pvk,{vid_keys('lm')} AS lvk
                      FROM meeting_update u JOIN base_meetings pm USING(event_id) JOIN candidate_meetings lm USING(event_id)
                      WHERE NOT u.added AND pm.videos IS DISTINCT FROM lm.videos AND {same_non_cap}
                        AND {bad_cap('pm')} AND {bad_cap('lm')} AND NOT ({dirty_rm}) AND NOT ({dirty_cap})),
                    added_bad AS (
                      SELECT event_id FROM (SELECT event_id,pck,lvk,unnest(lck) AS k FROM cand)
                      WHERE NOT list_contains(pck,k) AND (k NOT IN (SELECT video_key FROM held) OR NOT list_contains(lvk,k))),
                    removed_bad AS (
                      SELECT event_id FROM (SELECT event_id,lck,pvk,lvk,unnest(pck) AS k FROM cand)
                      WHERE NOT list_contains(lck,k) AND (k NOT IN (SELECT video_key FROM held)
                        OR NOT list_contains(pvk,k) OR list_contains(lvk,k)))
                    SELECT event_id FROM cand
                    WHERE event_id NOT IN (SELECT event_id FROM added_bad UNION SELECT event_id FROM removed_bad)""")
                d.caption_tx = d.one('SELECT count(*) FROM caption_tx_moves') > 0
    return d.caption_tx


# ct-uywf: the columns a new read of a meeting's Congress.gov detail record moves on an unchanged
# meeting, and the fields of a read that say where and when it happened.
DETAIL, UPDATED, STATUSES = 'congress_gov_detail_observation', 'congress_gov_updated', 'publisher_status_observations'
READ_LOCATOR = ('retrieved_at', 'receipt_key', 'receipt_line', 'capture_index', 'body_sha256')
READS = (('successful_read',), ('latest_attempt', 'evidence'))  # the two reads a detail observation names
MEETING_REFETCHED = 'a new read of the Congress.gov detail record: every other column equal on the meeting'


def _leaves(kind, path=()):
    """Paths of every non-struct field under an arrow struct type."""
    import pyarrow as pa
    if not pa.types.is_struct(kind):
        yield path
        return
    for field in kind:
        yield from _leaves(field.type, (*path, field.name))


def refetched_meetings(d: Diff):
    """Table `meeting_refetch(event_id)`: matched meetings on which nothing moved but what a new read of
    the Congress.gov detail record moves (ct-uywf); True when there is one.

    Every column but the three below is equal (transcripts by package). Of `congress_gov_detail_observation`
    only the two reads' locators move (time, receipt, line, capture index and body digest), each read
    either equal or later than the live read, not later than the moment of comparison and in another
    receipt; the successful read must move, so a read happened; the latest attempt's outcome may only
    go between `stored` and `unchanged` (both a 200 fetch: new bytes, or the same bytes again). Its
    state, coverage, listing, address, HTTP status and reader versions stay equal.
    `congress_gov_updated` (the publisher's own update stamp) is equal, or later and not later than
    the comparison, and only where the successful read names another body.
    `publisher_status_observations`: every live entry is kept with its source, status, date and record;
    a candidate entry is a live one, the same one seen later, or one that cites the new body and states
    a source, status and date the live release already states. So a postponement, a cancellation or a
    moved date on the re-fetched record is a new status entry and stops the meeting.
    Cannot see whether a read happened: the unattended gate finds each new read's receipt line in the
    capture table, outside the live release's receipts, holding the named body for the named address.
    O(matched meetings); the status check unnests only the changed rows.
    """
    if d.meeting_refetch is None:
        import pyarrow as pa
        d.meeting_refetch = False
        has_both = d.has('base', 'meetings') and d.has('candidate', 'meetings')
        shared = set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings')) if has_both else set()
        resched_skip = set(RESCHEDULED) if updated_meetings(d) and set(RESCHEDULED) <= shared else set()
        m_cmp = _meeting_compare(d) if has_both else {}
        same = has_both and _equal_except(d, 'meetings', {'event_id', DETAIL, UPDATED, STATUSES, *resched_skip}, m_cmp)
        kind = d.arrow_types('base', 'meetings').get(DETAIL) if same else None
        leaves = set(_leaves(kind)) if kind is not None and pa.types.is_struct(kind) else set()
        moving = {(*read, f) for read in READS for f in READ_LOCATOR} | {('latest_attempt', 'outcome')}
        if not same or not moving <= leaves:
            return False
        field = lambda side, path: f'{side}.{DETAIL}' + ''.join(f'."{p}"' for p in path)
        now = f"TIMESTAMPTZ '{d.now.isoformat()}'"
        terms = [same] + [f'{field("p", leaf)} IS NOT DISTINCT FROM {field("l", leaf)}' for leaf in sorted(leaves - moving)]
        if resched_skip:
            terms.append("""((p.rescheduled_to IS NOT DISTINCT FROM l.rescheduled_to AND p.rescheduled_basis IS NOT DISTINCT FROM l.rescheduled_basis)
                OR p.rescheduled_to IN (SELECT event_id FROM meeting_update)
                OR l.rescheduled_to IN (SELECT event_id FROM meeting_update))""")
        for read in READS:
            p, l = field('p', read), field('l', read)
            terms.append(f"""({p} IS NOT DISTINCT FROM {l} OR coalesce({l}.retrieved_at>{p}.retrieved_at AND {l}.retrieved_at<={now}
                AND {l}.receipt_key<>{p}.receipt_key,false))""")
        terms.append(f"{field('p', READS[0])} IS DISTINCT FROM {field('l', READS[0])}")
        outcome = [field(s, ('latest_attempt', 'outcome')) for s in 'pl']
        terms.append(f"({outcome[0]} IS NOT DISTINCT FROM {outcome[1]} OR ({outcome[0]} IN ('stored','unchanged') AND {outcome[1]} IN ('stored','unchanged')))")
        body = [field(s, ('successful_read', 'body_sha256')) for s in 'pl']
        terms.append(f"""(p.{UPDATED} IS NOT DISTINCT FROM l.{UPDATED} OR coalesce(l.{UPDATED}>p.{UPDATED} AND l.{UPDATED}<={now}
            AND {body[0]}<>{body[1]},false))""")
        d.table('meeting_refetch_rows', f"""SELECT event_id,{body[1]} AS body FROM base_meetings p JOIN candidate_meetings l USING(event_id)
          WHERE {' AND '.join(terms)}""")
        # Status entries, unnested on the qualifying rows whose statuses differ.
        same_entry = ' AND '.join(f'a.e.{f} IS NOT DISTINCT FROM b.e.{f}' for f in ('source', 'status', 'meeting_date', 'record_sha'))
        stated = ' AND '.join(f'a.e.{f} IS NOT DISTINCT FROM b.e.{f}' for f in ('source', 'status', 'meeting_date'))
        d.table('meeting_refetch', f"""WITH j AS (SELECT r.event_id,r.body,p.{STATUSES} ps,l.{STATUSES} ls
              FROM meeting_refetch_rows r JOIN base_meetings p USING(event_id) JOIN candidate_meetings l USING(event_id)
              WHERE p.{STATUSES} IS DISTINCT FROM l.{STATUSES}),
            pe AS (SELECT event_id,unnest(ps) e FROM j), le AS (SELECT event_id,body,unnest(ls) e FROM j),
            bad AS (SELECT a.event_id FROM pe a WHERE NOT EXISTS (SELECT 1 FROM le b WHERE b.event_id=a.event_id AND {same_entry})
              UNION ALL
              SELECT b.event_id FROM le b WHERE NOT EXISTS (SELECT 1 FROM pe a WHERE a.event_id=b.event_id AND {same_entry}
                  AND (a.e.observed_at IS NOT DISTINCT FROM b.e.observed_at OR coalesce(b.e.observed_at>a.e.observed_at AND b.e.observed_at<={now},false)))
                AND NOT (b.e.record_sha IS NOT DISTINCT FROM b.body
                  AND NOT EXISTS (SELECT 1 FROM pe a WHERE a.event_id=b.event_id AND a.e.record_sha IS NOT DISTINCT FROM b.e.record_sha)
                  AND EXISTS (SELECT 1 FROM pe a WHERE a.event_id=b.event_id AND {stated})))
          SELECT event_id FROM meeting_refetch_rows WHERE event_id NOT IN (SELECT event_id FROM bad)""")
        d.meeting_refetch = d.one('SELECT count(*) FROM meeting_refetch') > 0
    return d.meeting_refetch


def meetings(d: Diff):
    """Event IDs by multiplicity, then value groups on matched meetings. A swapped or wiped subject key is
    a `changed subject_keys` group. Set apart as verified groups flagged `refetch_only`: the
    `UPDATE_COLUMNS` of a meeting `updated_meetings` names, its `OUTCOME` columns where the candidate
    bases the outcome on the new read and the live one was the publisher's, and each meeting
    Congress.gov states for the first time (ct-rhqw); and the three columns a byte-identical read
    moves (`refetched_meetings`, ct-uywf). The updated meetings are listed in the report
    (`congress_gov_updates`) for the morning report."""
    join = 'base_meetings p JOIN candidate_meetings l USING(event_id)'
    m_cmp = _meeting_compare(d)
    groups, notes = key_file('meetings', 'event_id')(d)[0], {}
    groups += d.changed('meetings', join, m_cmp, set())
    elsewhere = 'true'
    if updated_meetings(d):
        updated = 'event_id IN (SELECT event_id FROM meeting_update WHERE NOT added)'
        counts = changed_counts(d, join, groups, updated, m_cmp)
        if 'subject_keys' in counts and updated_subjects(d):
            counts['subject_keys'] = changed_counts(
                d, join, [g for g in groups if g['group'] == 'changed subject_keys'],
                'event_id IN (SELECT event_id FROM clean_subject_meetings WHERE NOT added)', m_cmp).get('subject_keys', 0)
        shared = set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings'))
        outcome, resched, cap_tx = {}, {}, {}
        if {'outcome_basis', 'outcome_source_reference'} <= shared:
            publisher = "','".join(PUBLISHER_OUTCOMES)
            uncanceled_extra = []
            if 'outcome' in shared:
                uncanceled_extra.append("c.outcome='unknown'")
            if 'not_held' in shared:
                uncanceled_extra.append('c.not_held IS NOT TRUE')
            uncanceled_ok = (' AND ' + ' AND '.join(uncanceled_extra)) if uncanceled_extra else ''
            same_tx_out = _same_transcripts(d, 'p', 'c', non_captions=True)
            outcome = changed_counts(d, join, [g for g in groups if g['group'].removeprefix('changed ') in OUTCOME], f"""event_id IN (
                SELECT u.event_id FROM meeting_update u JOIN candidate_meetings c USING(event_id) JOIN base_meetings p USING(event_id)
                WHERE NOT u.added AND p.outcome_basis IN ('{publisher}') AND {same_tx_out}
                  AND (lower(c.outcome_source_reference)=u.body
                       OR (p.outcome_basis='publisher_cancellation' AND c.outcome_basis='no_outcome_evidence'
                           AND c.outcome_source_reference IS NULL{uncanceled_ok})))""")
        tx_groups = [g for g in groups if g['group'] == 'changed transcripts']
        if tx_groups and _caption_tx_moves(d):
            cap_tx = changed_counts(d, join, tx_groups, 'event_id IN (SELECT event_id FROM caption_tx_moves)', m_cmp)
        resched_groups = [g for g in groups if g['group'].removeprefix('changed ') in RESCHEDULED]
        if resched_groups and set(RESCHEDULED) <= shared:
            refetched_meetings(d)
            same_strict = _equal_except(d, 'meetings', {'event_id', *RESCHEDULED}, m_cmp)
            same_refetch = _equal_except(d, 'meetings', {'event_id', *(shared & {DETAIL, UPDATED, STATUSES}), *RESCHEDULED}, m_cmp)
            if same_strict and same_refetch:
                in_refetch = 'event_id IN (SELECT event_id FROM meeting_refetch)' if d.meeting_refetch else 'false'
                d.table('unchanged_twins', f"""SELECT event_id FROM base_meetings p JOIN candidate_meetings l USING(event_id)
                  WHERE ({same_strict}) OR ({in_refetch} AND ({same_refetch}))""")
                twin_ok = '(SELECT event_id FROM meeting_update UNION SELECT event_id FROM unchanged_twins)'
                same_tx = _same_transcripts(d, non_captions=True)
                bases = "','".join(RESCHEDULED_BASES)
                resched = changed_counts(d, join, resched_groups, f"""(p.rescheduled_basis IS NULL OR p.rescheduled_basis IN ('{bases}'))
                  AND (l.rescheduled_basis IS NULL OR l.rescheduled_basis IN ('{bases}'))
                  AND (p.rescheduled_to IS NULL OR p.rescheduled_to IN {twin_ok})
                  AND (l.rescheduled_to IS NULL OR l.rescheduled_to IN {twin_ok})
                  AND ((event_id IN (SELECT event_id FROM meeting_update WHERE NOT added) AND {same_tx})
                    OR (event_id IN (SELECT event_id FROM unchanged_twins)
                        AND (p.rescheduled_to IN (SELECT event_id FROM meeting_update)
                             OR l.rescheduled_to IN (SELECT event_id FROM meeting_update))))""", m_cmp)
        counts = {**{c: n for c, n in counts.items() if c in UPDATE_COLUMNS}, **outcome, **resched, **cap_tx}
        groups = refetch_split(groups, counts, MEETING_UPDATE)
        groups = split_group(groups, 'added keys', 'unexplained', d.one('SELECT count(*) FROM meeting_update WHERE added'), FIRST_STATED)
        notes['congress_gov_updates'] = [r[0] for r in d.rows('SELECT event_id FROM meeting_update ORDER BY 1')]
        elsewhere = 'event_id NOT IN (SELECT event_id FROM meeting_update)'
    if refetched_meetings(d):
        counts = {c: d.one(f"""SELECT count(*) FROM meeting_refetch JOIN base_meetings p USING(event_id)
            JOIN candidate_meetings l USING(event_id) WHERE p.{c} IS DISTINCT FROM l.{c} AND {elsewhere}""") for c in (DETAIL, UPDATED, STATUSES)}
        groups = refetch_split(groups, counts, MEETING_REFETCHED)
    return groups, notes


def nominations(d: Diff):
    """The registry comparison, with each added nomination that a Congress.gov meeting update newly
    names as a subject set apart as a verified group flagged `refetch_only` (ct-rhqw): its ID is in
    `new_update_subjects` (not previously a meeting subject, and not supplied by a document's
    `measure_keys` or a transcript change). Any other added, removed or changed nomination still
    needs a cause."""
    groups, notes = generic('nominations')(d)
    if updated_subjects(d) and 'nomination_id' in d.columns('candidate', 'nominations'):
        n = d.one("""SELECT count(*) FROM candidate_nominations ANTI JOIN base_nominations USING(nomination_id)
          WHERE lower(nomination_id) IN (SELECT k FROM new_update_subjects)""")
        groups = split_group(groups, 'added keys', 'no evidence given', n, NEW_SUBJECT)
    return groups, notes


def _stated_event_resolved_where(d: Diff):
    """SQL predicate on `base_recording_matches p` and `candidate_recording_matches l` (joined on `match_id`)
    for a held `video_states_event_id` claim resolved when its `first_stated` meeting appears (ct-rhqw)."""
    if not (updated_meetings(d) and d.has('base', 'recording_matches') and d.has('candidate', 'recording_matches')):
        return 'false'
    rm_shared = set(d.columns('base', 'recording_matches')) & set(d.columns('candidate', 'recording_matches'))
    if not PUBLISHER_MATCH_COLS <= rm_shared:
        return 'false'
    skip = {'match_id', 'event_id', 'score', 'note', *({'meeting_links'} if 'meeting_links' in rm_shared else set())}
    same_rest = _equal_except(d, 'recording_matches', skip)
    if not same_rest:
        return 'false'
    links_ok = (" AND coalesce(len(p.meeting_links),0)=0 AND len(l.meeting_links)=1 "
                "AND l.meeting_links[1].event_id=l.event_id AND l.meeting_links[1].basis='direct_event' "
                "AND l.meeting_links[1].scope='event'" if 'meeting_links' in rm_shared else '')
    return (f"({same_rest} AND p.basis='video_states_event_id' AND p.subject_kind='event' "
            f"AND p.event_id IS NULL AND l.event_id IN (SELECT event_id FROM meeting_update WHERE added) "
            f"AND p.subject_id=CAST(l.event_id AS VARCHAR) AND p.decision='linked' AND p.status='claimed' "
            f"AND p.score IS NULL AND l.score=95 "
            f"AND p.note='stated event id '||p.subject_id||' has no meeting' AND l.note IS NULL{links_ok})")


def _dirty_rm_events(d: Diff, alias='pm'):
    """Events touched by any non-`publisher_link` recording_matches addition, removal or content change."""
    if d.dirty_rm is None:
        d.dirty_rm = False
        if d.has('base', 'recording_matches') and d.has('candidate', 'recording_matches'):
            shared = set(d.columns('base', 'recording_matches')) & set(d.columns('candidate', 'recording_matches'))
            if {'match_id', 'basis', 'event_id'} <= shared:
                same = _equal_except(d, 'recording_matches', {'match_id', 'source_ref'}) or 'false'
                stated_ok = _stated_event_resolved_where(d)
                changed_rm = f"(p.basis IS DISTINCT FROM 'publisher_link' OR l.basis IS DISTINCT FROM 'publisher_link') AND NOT ({same}) AND NOT ({stated_ok})"
                parts = [
                    "SELECT event_id FROM candidate_recording_matches ANTI JOIN base_recording_matches USING(match_id) WHERE basis IS DISTINCT FROM 'publisher_link'",
                    "SELECT event_id FROM base_recording_matches ANTI JOIN candidate_recording_matches USING(match_id) WHERE basis IS DISTINCT FROM 'publisher_link'",
                    f'SELECT p.event_id FROM base_recording_matches p JOIN candidate_recording_matches l USING(match_id) WHERE {changed_rm}',
                    f'SELECT l.event_id FROM base_recording_matches p JOIN candidate_recording_matches l USING(match_id) WHERE {changed_rm}']
                if 'meeting_links' in shared:
                    parts += [
                        """SELECT unnest(meeting_links).event_id FROM candidate_recording_matches ANTI JOIN base_recording_matches USING(match_id)
                           WHERE basis IS DISTINCT FROM 'publisher_link' AND meeting_links IS NOT NULL""",
                        """SELECT unnest(meeting_links).event_id FROM base_recording_matches ANTI JOIN candidate_recording_matches USING(match_id)
                           WHERE basis IS DISTINCT FROM 'publisher_link' AND meeting_links IS NOT NULL""",
                        f'SELECT unnest(p.meeting_links).event_id FROM base_recording_matches p JOIN candidate_recording_matches l USING(match_id) WHERE {changed_rm} AND p.meeting_links IS NOT NULL',
                        f'SELECT unnest(l.meeting_links).event_id FROM base_recording_matches p JOIN candidate_recording_matches l USING(match_id) WHERE {changed_rm} AND l.meeting_links IS NOT NULL']
                d.table('dirty_rm_events', f"SELECT DISTINCT event_id FROM ({' UNION ALL '.join(parts)}) WHERE event_id IS NOT NULL")
                d.dirty_rm = d.one('SELECT count(*) FROM dirty_rm_events') > 0
    return f'{alias}.event_id IN (SELECT event_id FROM dirty_rm_events)' if d.dirty_rm else 'false'


def _dirty_caption_videos(d: Diff, pm='pm', lm='lm'):
    """SQL condition true when any video on `{pm}.videos` or `{lm}.videos` changed caption state or tracks."""
    if d.dirty_captions is None:
        parts = []
        if d.has('base', 'videos') and d.has('candidate', 'videos'):
            v_shared = set(d.columns('base', 'videos')) & set(d.columns('candidate', 'videos'))
            if {'video_key', 'has_caption'} <= v_shared:
                parts += [
                    'SELECT video_key FROM candidate_videos ANTI JOIN base_videos USING(video_key) WHERE coalesce(has_caption,false)',
                    'SELECT video_key FROM base_videos ANTI JOIN candidate_videos USING(video_key) WHERE coalesce(has_caption,false)',
                    'SELECT p.video_key FROM base_videos p JOIN candidate_videos l USING(video_key) WHERE p.has_caption IS DISTINCT FROM l.has_caption']
        if d.has('base', 'recordings') and d.has('candidate', 'recordings'):
            r_shared = set(d.columns('base', 'recordings')) & set(d.columns('candidate', 'recordings'))
            if {'video_key', 'tracks'} <= r_shared:
                parts += [
                    'SELECT video_key FROM candidate_recordings ANTI JOIN base_recordings USING(video_key) WHERE coalesce(len(tracks),0)>0',
                    'SELECT video_key FROM base_recordings ANTI JOIN candidate_recordings USING(video_key) WHERE coalesce(len(tracks),0)>0',
                    """SELECT p.video_key FROM base_recordings p JOIN candidate_recordings l USING(video_key)
                       WHERE list_transform(p.tracks,t->t.body) IS DISTINCT FROM list_transform(l.tracks,t->t.body)"""]
        if not parts:
            d.dirty_captions = False
        else:
            d.table('dirty_caption_videos', f"SELECT DISTINCT video_key FROM ({' UNION ALL '.join(parts)}) WHERE video_key IS NOT NULL")
            d.dirty_captions = d.one('SELECT count(*) FROM dirty_caption_videos') > 0
    if not d.dirty_captions:
        return 'false'
    empty = 'CAST([] AS VARCHAR[])'
    return f"""list_has_any(list_concat(coalesce(list_transform({pm}.videos,v->v.video_key),{empty}),
        coalesce(list_transform({lm}.videos,v->v.video_key),{empty})),
        (SELECT list(video_key) FROM dirty_caption_videos))"""


def meeting_coverage(d: Diff):
    """The registry comparison, with the coverage a Congress.gov meeting update moves set apart as
    verified groups flagged `refetch_only` (ct-rhqw): the rows of a meeting Congress.gov states for
    the first time, and on a matched updated meeting its `witnesses` aspect, `recording` and `captions`
    when moved by `meetings.videos` alone, `transcript` zero-count jacket status (`not_stated`/`unknown`
    vs `unresolved` with unchanged `transcripts`), and zero-count `documents` status (`stated_documents_not_held`
    or `senate_page_links_pending`). Present documents/transcripts and curated recording decisions still
    need a cause."""
    groups, notes = generic('meeting_coverage')(d)
    cov_shared = set(d.columns('base', 'meeting_coverage')) & set(d.columns('candidate', 'meeting_coverage')) if updated_meetings(d) else set()
    if {'event_id', 'aspect'} <= cov_shared:
        first = d.one("""SELECT count(*) FROM candidate_meeting_coverage ANTI JOIN base_meeting_coverage USING(event_id,aspect)
          WHERE event_id IN (SELECT event_id FROM meeting_update WHERE added)""")
        groups = split_group(groups, 'added keys', 'no evidence given', first, FIRST_STATED)
        m_shared = (set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings'))
                    if d.has('base', 'meetings') and d.has('candidate', 'meetings') else set())
        same_tx = _same_transcripts(d, 'pm', 'lm')
        same_non_cap_tx = _same_transcripts(d, 'pm', 'lm', non_captions=True)
        w_basis = " AND p.basis='appearance_records' AND l.basis='appearance_records'" if 'basis' in cov_shared else ''
        arms = [f"(p.aspect='witnesses'{w_basis} AND {same_non_cap_tx})"]
        if {'state', 'basis', 'count', 'reason'} <= cov_shared:
            dirty_rm = _dirty_rm_events(d)
            if 'videos' in m_shared:
                dirty_cap = _dirty_caption_videos(d)
                arms.append(f"""(p.aspect='recording' AND pm.videos IS DISTINCT FROM lm.videos
                    AND p.basis IN ('recording_matches','none') AND l.basis IN ('recording_matches','none')
                    AND p.state NOT IN ('confirmed_absent','not_public') AND l.state NOT IN ('confirmed_absent','not_public')
                    AND NOT ({dirty_rm}))""")
                arms.append(f"""(p.aspect='captions' AND pm.videos IS DISTINCT FROM lm.videos AND {same_non_cap_tx}
                    AND p.basis='videos.has_caption,recordings.tracks' AND l.basis='videos.has_caption,recordings.tracks'
                    AND p.state<>'not_stated' AND l.state<>'not_stated' AND NOT ({dirty_rm}) AND NOT ({dirty_cap}))""")
            valid_tx = lambda s: (f"(({s}.state='unresolved' AND {s}.reason IS NULL) OR ({s}.state='not_stated' AND {s}.reason IS NULL) "
                                  f"OR ({s}.state='unknown' AND {s}.reason='package_names_meeting_unlinked'))")
            cap_tx_or = (
                ' OR (pm.event_id IN (SELECT event_id FROM caption_tx_moves)'
                ' AND p.count=coalesce(len(pm.transcripts),0) AND l.count=coalesce(len(lm.transcripts),0))'
                if _caption_tx_moves(d)
                else ''
            )
            arms.append(f"""(p.aspect='transcript' AND p.basis='meetings.transcripts' AND l.basis='meetings.transcripts'
                AND (({same_tx} AND p.count=0 AND l.count=0 AND {valid_tx('p')} AND {valid_tx('l')}
                      AND (p.state='unresolved' OR l.state='unresolved')){cap_tx_or}))""")
            if 'document_references' in m_shared:
                valid_doc = lambda s: (f"(({s}.state='unresolved' AND {s}.reason='stated_documents_not_held') "
                                       f"OR ({s}.state='unknown' AND {s}.reason='senate_page_links_pending') "
                                       f"OR ({s}.state='not_stated' AND {s}.reason IS NULL))")
                arms.append(f"""(p.aspect='documents' AND p.basis='list.meeting_keys' AND l.basis='list.meeting_keys'
                    AND p.count=0 AND l.count=0 AND {valid_doc('p')} AND {valid_doc('l')}
                    AND (pm.document_references IS DISTINCT FROM lm.document_references
                         OR (p.state IN ('unknown','not_stated') AND l.state IN ('unknown','not_stated'))))""")
        join = ('base_meeting_coverage p JOIN candidate_meeting_coverage l USING(event_id,aspect) '
                'JOIN base_meetings pm USING(event_id) JOIN candidate_meetings lm USING(event_id)')
        where = f"pm.event_id IN (SELECT event_id FROM meeting_update WHERE NOT added) AND ({' OR '.join(arms)})"
        groups = refetch_split(groups, changed_counts(d, join, groups, where), MEETING_UPDATE)
    return groups, notes


def bills(d: Diff):
    import pyarrow as pa
    removed = d.one('SELECT count(*) FROM base_bills ANTI JOIN candidate_bills USING(bill_id)')
    d.table('bill_refs', """SELECT DISTINCT lower(unnest(subject_keys)) k,'new meeting subject' cause FROM candidate_meetings
      EXCEPT SELECT DISTINCT lower(unnest(subject_keys)),'new meeting subject' FROM base_meetings""")
    added = d.rows("""SELECT coalesce(r.cause,'unexplained'),count(*) FROM (SELECT bill_id FROM candidate_bills ANTI JOIN base_bills USING(bill_id)) b
      LEFT JOIN bill_refs r ON r.k=lower(b.bill_id) GROUP BY 1""")
    out = [group('added bills', cause, n, 'verified') for cause, n in added]
    if updated_subjects(d) and 'bill_id' in d.columns('candidate', 'bills'):
        n = d.one("""SELECT count(*) FROM candidate_bills ANTI JOIN base_bills USING(bill_id)
          WHERE lower(bill_id) IN (SELECT k FROM new_update_subjects)""")
        out = split_group(out, 'added bills', 'new meeting subject', n, NEW_SUBJECT)
        rel_type = d.arrow_types('candidate', 'bills').get('related_bills')
        if (rel_type is not None and (pa.types.is_list(rel_type) or pa.types.is_large_list(rel_type))
                and pa.types.is_struct(rel_type.value_type) and rel_type.value_type.get_field_index('bill_id') >= 0):
            d.table('update_related_bills', """SELECT DISTINCT lower(r.bill_id) AS k
              FROM (SELECT bill_id,unnest(related_bills) AS r FROM candidate_bills WHERE related_bills IS NOT NULL)
              WHERE lower(bill_id) IN (SELECT k FROM new_update_subjects) AND r.bill_id IS NOT NULL
              UNION
              SELECT DISTINCT lower(bill_id) AS k
              FROM (SELECT bill_id,unnest(related_bills) AS r FROM candidate_bills WHERE related_bills IS NOT NULL)
              WHERE lower(r.bill_id) IN (SELECT k FROM new_update_subjects) AND bill_id IS NOT NULL""")
            n_rel = d.one("""SELECT count(*) FROM candidate_bills ANTI JOIN base_bills USING(bill_id)
              WHERE lower(bill_id) NOT IN (SELECT k FROM bill_refs)
                AND lower(bill_id) NOT IN (SELECT k FROM new_doc_subjects)
                AND lower(bill_id) IN (SELECT k FROM update_related_bills)""")
            out = split_group(out, 'added bills', 'unexplained', n_rel, NEW_SUBJECT)
    if removed:
        out.append(group('removed bills', 'unexplained', -removed))
    return out + d.changed('bills', 'base_bills p JOIN candidate_bills l USING(bill_id)', exclude=set()), {}


def recordings(d: Diff):
    groups, _ = key_file('recordings', 'video_key')(d)
    groups = [g for g in groups if g['group'] != 'added keys']
    cand_cols = set(d.columns('candidate', 'recordings'))
    if 'event_ids' not in cand_cols:
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
    join = 'base_recordings p JOIN candidate_recordings l USING(video_key)'
    groups += d.changed('recordings', join, tracks, set())
    r_shared = set(d.columns('base', 'recordings')) & cand_cols if updated_meetings(d) else set()
    if {'video_key', 'event_ids', 'tracks'} <= r_shared:
        flips = ("EXISTS (SELECT 1 FROM flips f WHERE f.b_real AND NOT f.a_real AND split_part(l.video_key,':',2)<>'' AND contains(f.address,split_part(l.video_key,':',2)))"
                 if d.link_causes else 'false')
        first_rec = d.one(f"""SELECT count(*) FROM (SELECT * FROM candidate_recordings ANTI JOIN base_recordings USING(video_key)) l
          WHERE NOT ({flips}) AND coalesce(len(l.tracks),0)=0 AND coalesce(len(l.event_ids),0)>0
            AND NOT EXISTS (SELECT 1 FROM (SELECT unnest(l.event_ids) AS e) WHERE e NOT IN (SELECT event_id FROM meeting_update WHERE added))""")
        upd_rec = d.one(f"""SELECT count(*) FROM (SELECT * FROM candidate_recordings ANTI JOIN base_recordings USING(video_key)) l
          WHERE NOT ({flips}) AND coalesce(len(l.tracks),0)=0 AND coalesce(len(l.event_ids),0)>0
            AND NOT EXISTS (SELECT 1 FROM (SELECT unnest(l.event_ids) AS e) WHERE e NOT IN (SELECT event_id FROM meeting_update))
            AND EXISTS (SELECT 1 FROM (SELECT unnest(l.event_ids) AS e) WHERE e IN (SELECT event_id FROM meeting_update WHERE NOT added))""")
        rem_rec = d.one("""SELECT count(*) FROM (SELECT * FROM base_recordings ANTI JOIN candidate_recordings USING(video_key)) p
          WHERE coalesce(len(p.tracks),0)=0 AND coalesce(len(p.event_ids),0)>0
            AND NOT EXISTS (SELECT 1 FROM (SELECT unnest(p.event_ids) AS e) WHERE e NOT IN (SELECT event_id FROM meeting_update WHERE NOT added))""")
        groups = split_group(groups, 'added keys', 'with event_ids; source not traced', first_rec, f'with event_ids; {FIRST_STATED}')
        groups = split_group(groups, 'added keys', 'with event_ids; source not traced', upd_rec, f'with event_ids; {MEETING_UPDATE}')
        groups = split_group(groups, 'removed keys', 'unexplained', rem_rec, MEETING_UPDATE)
        ev_groups = [g for g in groups if g['group'] == 'changed event_ids']
        if ev_groups:
            ev_where = """list_transform(p.tracks,t->t.body) IS NOT DISTINCT FROM list_transform(l.tracks,t->t.body)
              AND (coalesce(len(l.event_ids),0)>0 OR coalesce(len(p.tracks),0)>0)
              AND NOT EXISTS (SELECT 1 FROM (SELECT unnest(coalesce(l.event_ids,CAST([] AS BIGINT[]))) AS e
                  EXCEPT SELECT unnest(coalesce(p.event_ids,CAST([] AS BIGINT[]))))
                WHERE e NOT IN (SELECT event_id FROM meeting_update))
              AND NOT EXISTS (SELECT 1 FROM (SELECT unnest(coalesce(p.event_ids,CAST([] AS BIGINT[]))) AS e
                  EXCEPT SELECT unnest(coalesce(l.event_ids,CAST([] AS BIGINT[]))))
                WHERE e NOT IN (SELECT event_id FROM meeting_update WHERE NOT added))"""
            groups = refetch_split(groups, changed_counts(d, join, ev_groups, ev_where, tracks), MEETING_UPDATE)
    return groups, {}


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
    A Congress.gov meeting update (`updated_witnesses`, ct-rhqw) sets apart as groups flagged
    `refetch_only`: its live Congress.gov witnesses removed with a published successor, its new ones
    (successors or not), and every value that changed on a pair of them on the same meeting. A
    removed key the map does not resolve to one witness (no row, ambiguous, unresolved, or a successor
    not published) is a lost key and still stops (owner, 2026-11-11: until a dropped witness is kept
    as "no longer listed"), as does a map that collapses two witnesses and any row of another source
    or another meeting.
    """
    if not rekeyed(d):
        return generic('witnesses')(d)
    out = []
    update = updated_witnesses(d)
    flagged = lambda name, cause, n: dict(group(name, f'{cause}; {MEETING_UPDATE}', n, 'verified'), refetch_only=True)
    on_update = 'b.witness_key IN (SELECT witness_key FROM witness_update_base)' if update else 'false'
    for status, mapped, collision, updated, n in d.rows(f"""SELECT coalesce(m.status,''),x.old_key IS NOT NULL,
          c.witness_key IS NOT NULL AND m.status='unambiguous',{on_update},count(*)
          FROM (SELECT witness_key FROM base_witnesses ANTI JOIN candidate_witnesses USING(witness_key)) b
          LEFT JOIN candidate_witness_key_map m ON m.old_key=b.witness_key LEFT JOIN witness_rekey x ON x.old_key=b.witness_key
          LEFT JOIN witness_rekey_collisions c ON c.witness_key=m.witness_key
          GROUP BY ALL ORDER BY ALL"""):
        if mapped:
            cause = 're-keyed: witness_key_map names the published successor'
            out.append(flagged('removed keys', cause, -n) if updated else group('removed keys', cause, -n, 'verified'))
        elif collision:
            out.append(group('removed keys', 'witness_key_map collapses distinct base occurrences', -n, 'defect'))
        elif status in ('ambiguous', 'unresolved'):
            cause = f'witness_key_map states the key {status}'
            out.append(group('removed keys', cause, -n))
        elif status:
            out.append(group('removed keys', 'unexplained', -n))  # an unambiguous row whose successor is not published
        else:
            out.append(group('removed keys', 'no evidence given', -n))
    on_update = 'witness_key IN (SELECT witness_key FROM witness_update_candidate)' if update else 'false'
    for successor, updated, n in d.rows(f"""SELECT witness_key IN (SELECT x.witness_key FROM witness_rekey x JOIN base_witnesses p ON p.witness_key=x.old_key),
          {on_update},count(*) FROM candidate_witnesses ANTI JOIN base_witnesses USING(witness_key) GROUP BY 1,2 ORDER BY 1,2"""):
        if updated:
            out.append(flagged('added keys', 'successor of a re-keyed witness' if successor else 'new on its meeting', n))
        else:
            out.append(group('added keys', 'successor of a re-keyed witness', n, 'verified') if successor
                       else group('added keys', 'no evidence given', n))
    d.view('base_witnesses_paired', """SELECT p.* REPLACE (coalesce(x.witness_key,p.witness_key) AS witness_key,
          coalesce(s.witness_key,p.superseded_by) AS superseded_by)
        FROM base_witnesses p LEFT JOIN witness_rekey x ON x.old_key=p.witness_key LEFT JOIN witness_rekey s ON s.old_key=p.superseded_by""")
    d.view('candidate_witnesses_paired', 'SELECT * FROM candidate_witnesses')
    join = 'base_witnesses_paired p JOIN candidate_witnesses_paired l USING(witness_key)'
    out += d.changed('witnesses_paired', join, exclude=OCCURRENCE)
    if update:
        where = ("witness_key IN (SELECT witness_key FROM witness_update_candidate) AND p.source='congress_gov' AND p.occasion=l.occasion "
                 "AND p.occasion IN (SELECT 'meeting:'||event_id FROM meeting_update WHERE NOT added)")
        out = refetch_split(out, changed_counts(d, join, out, where), MEETING_UPDATE)
        sup_groups = [g for g in out if g['group'] == 'changed superseded_by']
        same_other = _equal_except(d, 'witnesses', {'witness_key', 'superseded_by'}) if sup_groups else None
        if sup_groups and same_other:
            sup_n = d.one(f"""SELECT count(*) FROM base_witnesses_paired bp JOIN candidate_witnesses_paired lp USING(witness_key)
              WHERE bp.superseded_by IS DISTINCT FROM lp.superseded_by
                AND bp.source IN ('senate_page','mods') AND bp.source=lp.source AND bp.occasion=lp.occasion
                AND lp.occasion IN (SELECT 'meeting:'||event_id FROM meeting_update)
                AND EXISTS (SELECT 1 FROM base_witnesses p JOIN candidate_witnesses l USING(witness_key)
                  WHERE p.witness_key=bp.witness_key AND {same_other}
                    AND (l.superseded_by IN (SELECT witness_key FROM witness_update_candidate wc WHERE wc.occasion=l.occasion)
                         OR p.superseded_by IN (SELECT witness_key FROM witness_update_base wb WHERE wb.occasion=p.occasion)))""")
            out = refetch_split(out, {'superseded_by': sup_n}, MEETING_UPDATE)
    return out, {}


def witness_key_map(d: Diff):
    """Old keys added to or dropped from the map; successors compare through the map.

    Verified: an added old key the base published in witnesses (retired in this release) or never
    published (it resolves no key a base reader could hold), and a dropped old key the candidate
    publishes again. A dropped key the candidate does not publish no longer resolves: unverified.
    A successor that moved is the same witness when the base successor itself maps to it.
    A Congress.gov meeting update (`updated_witnesses`, ct-rhqw) sets apart as groups flagged
    `refetch_only` the rows of its Congress.gov keys that resolve unambiguously through
    `witness_rekey` to one of that meeting's updated Congress.gov witnesses: added rows (an old key
    the live release published must be one of that meeting's live Congress.gov witnesses), and every
    value that changed on a matched row whose live and candidate rows both belong to the meeting.
    Any other successor (unpublished, on another meeting, or colliding), a row that turns ambiguous
    or unresolved, or a dropped row is a lost key and stops.
    """
    if not d.has('base', 'witness_key_map'):
        return generic('witness_key_map')(d)
    rekeyed(d)
    update = (updated_witnesses(d) and bool(d.witness_rekey)
              and {'source', 'occasion', 'status', 'witness_key'} <= set(d.columns('base', 'witness_key_map')) & set(d.columns('candidate', 'witness_key_map')))
    on_any_update = "{x}source='congress_gov' AND {x}occasion IN (SELECT 'meeting:'||event_id FROM meeting_update)"
    on_meeting = "{x}source='congress_gov' AND {x}occasion IN (SELECT 'meeting:'||event_id FROM meeting_update WHERE NOT added)"
    resolves = ("{x}status='unambiguous' AND EXISTS (SELECT 1 FROM witness_rekey r "
                "JOIN witness_update_candidate w USING(witness_key) "
                "WHERE r.old_key={x}old_key AND r.witness_key={x}witness_key AND w.occasion={x}occasion)")
    added = (f"coalesce({on_any_update.format(x='m.')} AND {resolves.format(x='m.')} "
             "AND (NOT EXISTS (SELECT 1 FROM base_witnesses b WHERE b.witness_key=m.old_key) "
             "OR EXISTS (SELECT 1 FROM witness_update_base b WHERE b.witness_key=m.old_key AND b.occasion=m.occasion)),false)")
    out = []
    for published, updated, n in d.rows(f"""SELECT m.old_key IN (SELECT witness_key FROM base_witnesses),{added if update else 'false'},count(*)
          FROM candidate_witness_key_map m ANTI JOIN base_witness_key_map USING(old_key) GROUP BY 1,2 ORDER BY 1,2"""):
        cause = 'key retired from witnesses in this release' if published else 'a key no base witness carries'
        out.append(dict(group('added keys', f'{cause}; {MEETING_UPDATE}', n, 'verified'), refetch_only=True) if updated
                   else group('added keys', cause, n, 'verified'))
    for again, n in d.rows("""SELECT old_key IN (SELECT witness_key FROM candidate_witnesses),count(*)
          FROM base_witness_key_map ANTI JOIN candidate_witness_key_map USING(old_key) GROUP BY 1 ORDER BY 1"""):
        out.append(group('removed keys', 'published again in witnesses', -n, 'verified') if again
                   else group('removed keys', 'no longer resolves', -n))
    join = 'base_witness_key_map p JOIN candidate_witness_key_map l USING(old_key)'
    for side, alias in (('base', 'pc'), ('candidate', 'lc')):
        mapped_keys = rekeyed_lists(d, f'{side}_witness_key_map', 'old_key', 'candidate_keys')
        join += f' LEFT JOIN {mapped_keys} {alias} ON {alias}.old_key=p.old_key'
    join += ' LEFT JOIN witness_rekey ps ON ps.old_key=p.witness_key LEFT JOIN witness_rekey ls ON false'
    compare = {'witness_key': 'coalesce(Xs.{c},X.{c})', 'candidate_keys': 'coalesce(Xc.{c},X.{c})'}
    out += d.changed('witness_key_map', join, compare, exclude={'old_key'})
    if update:
        both = f"coalesce({on_meeting.format(x='p.')} AND {on_meeting.format(x='l.')} AND p.occasion=l.occasion AND {resolves.format(x='l.')},false)"
        out = refetch_split(out, changed_counts(d, join, out, both, compare), MEETING_UPDATE)
    return out, {}


def url_state(d: Diff):
    scope = json.loads((d.dirs['candidate'] / 'capture_scope.json').read_text())
    patterns = {re.compile(p) for e in scope['entries'] for p in e.get('exclusions', [])}
    removed = d.rows('SELECT requested_url,attempts FROM base_url_state ANTI JOIN candidate_url_state USING(requested_url)')
    matching = [(u, n) for u, n in removed if any(p.search(u) for p in patterns)]
    excluded = sum(not n for _, n in matching)
    attempted = len(matching) - excluded
    added = d.rows(f"""SELECT CASE WHEN attempts>0 THEN '{ATTEMPTED_URLS}'
        WHEN attempts=0 THEN '{QUEUED_URLS}' ELSE 'invalid attempt count' END,count(*)
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
    return _equal_except(d, table, {key, *cited})


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


READ_FIELDS = ('receipt_key', 'receipt_line', 'capture_index', 'body_sha256', 'source_url', 'retrieved_at')


def _detail_reads(directory):
    """Every read the meetings' Congress.gov detail observations name (ct-uywf), as tuples of
    READ_FIELDS. O(meetings)."""
    import pyarrow.parquet as pq
    path = Path(directory) / 'meetings.parquet'
    if not path.exists() or DETAIL not in pq.read_schema(path).names:
        return set()
    found = set()
    for observation in pq.read_table(path, columns=[DETAIL])[DETAIL].to_pylist():
        for read in READS:
            value = observation
            for name in read:
                value = (value or {}).get(name)
            if value and value.get('receipt_key'):
                found.add(tuple(value.get(f) for f in READ_FIELDS))
    return found


def new_citations(base_dir, candidate_dir):
    """Hex of every body a re-fetch row cites in the candidate and the base cites nowhere: the cache
    files of channels and videos (ct-syp1), and witness record bodies and the bodies of the
    meetings' detail reads (ct-uywf).

    The unattended gate checks each against the capture table (release_gate): a file the
    candidate cites for the first time must be a body some new receipt delivered. O(rows): 67k
    videos, 172k witnesses, 19k meetings.
    """
    import pyarrow.parquet as pq
    def cited(directory):
        found = set()
        for table in ('channels', 'videos', 'witnesses'):
            path = Path(directory) / f'{table}.parquet'
            if path.exists() and 'record_sha' in pq.read_schema(path).names:
                found.update(v.hex() if isinstance(v, bytes) else v.lower()
                             for v in pq.read_table(path, columns=['record_sha'])['record_sha'].to_pylist() if v)
        return found | {read[3].lower() for read in _detail_reads(directory) if read[3]}
    return sorted(cited(candidate_dir) - cited(base_dir))


def new_reads(base_dir, candidate_dir):
    """The meetings' detail reads (`_detail_reads`) the candidate names and the base does not, as
    dicts: the unattended gate finds each one's receipt line in the capture table (ct-uywf)."""
    return [dict(zip(READ_FIELDS, read)) for read in sorted(_detail_reads(candidate_dir) - _detail_reads(base_dir), key=str)]


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
    Such rows become a `verified` group flagged `refetch_only`; the rest of the column's
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
        return refetch_split(groups, dict(zip(CITATIONS[table][1], checked)), cause), notes
    return run


PUBLISHER_MATCH_COLS = {'match_id', 'subject_kind', 'subject_id', 'event_id', 'package_id', 'video_key', 'url',
                        'basis', 'decision', 'score', 'recording_scope', 'status', 'note', 'source_ref'}


def recording_matches(d: Diff):
    """The video cache refresh (`cache_churn`), plus `publisher_link` rows of Congress.gov meeting
    updates (`meetings.videos`, ct-rhqw) set apart as verified groups flagged `refetch_only`."""
    groups, notes = cache_churn('recording_matches')(d)
    rm_shared = (set(d.columns('base', 'recording_matches')) & set(d.columns('candidate', 'recording_matches'))
                 if updated_meetings(d) else set())
    m_shared = (set(d.columns('base', 'meetings')) & set(d.columns('candidate', 'meetings'))
                if rm_shared and d.has('base', 'meetings') and d.has('candidate', 'meetings') else set())
    if PUBLISHER_MATCH_COLS <= rm_shared and 'videos' in m_shared:
        def pub_row(alias, side):
            links_ok = (f" AND len({alias}.meeting_links)=1 AND {alias}.meeting_links[1].event_id={alias}.event_id "
                        f"AND {alias}.meeting_links[1].basis='direct_event' AND {alias}.meeting_links[1].scope='event'"
                        if 'meeting_links' in set(d.columns(side, 'recording_matches')) else '')
            in_videos = (f"EXISTS (SELECT 1 FROM (SELECT unnest(m.videos) AS v FROM {side}_meetings m "
                         f"WHERE m.event_id={alias}.event_id AND m.videos IS NOT NULL) "
                         f"WHERE v.video_key IS NOT DISTINCT FROM {alias}.video_key AND v.url IS NOT DISTINCT FROM {alias}.url)")
            return (f"({alias}.subject_kind='event' AND {alias}.subject_id=CAST({alias}.event_id AS VARCHAR) "
                    f"AND {alias}.package_id IS NULL AND {alias}.basis='publisher_link' AND {alias}.decision='linked' "
                    f"AND {alias}.score=100 AND {alias}.recording_scope='unknown' AND {alias}.status='asserted' "
                    f"AND {alias}.note IS NULL AND {alias}.source_ref='meetings.videos'{links_ok} AND {in_videos})")
        first_added = d.one(f"""SELECT count(*) FROM candidate_recording_matches r ANTI JOIN base_recording_matches USING(match_id)
          WHERE r.event_id IN (SELECT event_id FROM meeting_update WHERE added) AND {pub_row('r', 'candidate')}""")
        upd_added = d.one(f"""SELECT count(*) FROM candidate_recording_matches r ANTI JOIN base_recording_matches USING(match_id)
          WHERE r.event_id IN (SELECT event_id FROM meeting_update WHERE NOT added) AND {pub_row('r', 'candidate')}""")
        upd_removed = d.one(f"""SELECT count(*) FROM base_recording_matches r ANTI JOIN candidate_recording_matches USING(match_id)
          WHERE r.event_id IN (SELECT event_id FROM meeting_update WHERE NOT added) AND {pub_row('r', 'base')}""")
        groups = split_group(groups, 'added keys', 'no evidence given', first_added, FIRST_STATED)
        groups = split_group(groups, 'added keys', 'no evidence given', upd_added, MEETING_UPDATE)
        groups = split_group(groups, 'removed keys', 'no evidence given', upd_removed, MEETING_UPDATE)
        join = 'base_recording_matches p JOIN candidate_recording_matches l USING(match_id)'
        where = (f"p.event_id=l.event_id AND l.event_id IN (SELECT event_id FROM meeting_update WHERE NOT added) "
                 f"AND {pub_row('p', 'base')} AND {pub_row('l', 'candidate')}")
        rm_groups = [g for g in groups if g['group'].removeprefix('changed ') in ('video_key', 'url')]
        groups = refetch_split(groups, changed_counts(d, join, rm_groups, where), MEETING_UPDATE)
        stated_ok = _stated_event_resolved_where(d)
        stated_groups = [g for g in groups if g['group'].removeprefix('changed ') in ('event_id', 'score', 'note', 'meeting_links')]
        if stated_groups and stated_ok != 'false':
            groups = refetch_split(groups, changed_counts(d, join, stated_groups, stated_ok), FIRST_STATED)
    return groups, notes


HANDLERS = {'list': document_file('list'), 'detail': document_file('detail'), 'links': links, 'urls': urls, 'sources': sources, 'meetings': meetings,
            'recoveries': recoveries,
            'recordings': recordings, 'bills': bills, 'url_state': url_state, 'witnesses': witnesses, 'witness_key_map': witness_key_map,
            'meeting_coverage': meeting_coverage, 'nominations': nominations,
            **{table: cache_churn(table) for table in CITATIONS}, 'recording_matches': recording_matches}


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
    _mark_list_row_reorders(d, report)
    return report


def _mark_list_row_reorders(d: Diff, report):
    """Mark byte-only `list_row` permutations in document-indexed tables when `list.parquet` re-sorted
    one-to-one rows solely because a Congress.gov meeting update moved `document_date` (ct-rhqw)."""
    list_entry = report.get('list.parquet')
    if not (d.meeting_update and list_entry and list_entry['groups']):
        return
    if not (d.documents[1]['one_to_one_rows'] == list_entry['rows']['base'] == list_entry['rows']['candidate']):
        return
    if not all(g['status'] == 'verified' and g.get('refetch_only') for g in list_entry['groups']):
        return
    if not any(g['group'] == 'changed document_date' for g in list_entry['groups']):
        return
    if 'document_date' not in set(d.columns('base', 'list')) & set(d.columns('candidate', 'list')):
        return
    if not d.one('SELECT count(*) FROM one_to_one WHERE pr<>lr'):
        return
    bad_inversion = d.one("""SELECT count(*) FROM
        one_to_one a JOIN base_list pa ON pa.file_row_number=a.pr JOIN candidate_list la ON la.file_row_number=a.lr,
        one_to_one b JOIN base_list pb ON pb.file_row_number=b.pr JOIN candidate_list lb ON lb.file_row_number=b.lr
      WHERE a.pr<b.pr AND a.lr>b.lr
        AND pa.document_date IS NOT DISTINCT FROM la.document_date
        AND pb.document_date IS NOT DISTINCT FROM lb.document_date""")
    if bad_inversion:
        return
    if d.has('base', 'links') and d.has('candidate', 'links') and d.one(
            'SELECT count(*) FROM (SELECT link_key,list_row FROM candidate_links '
            'EXCEPT SELECT p.link_key,o.lr FROM base_links p JOIN one_to_one o ON o.pr=p.list_row)'):
        return
    unexplained = flag('changed bytes, no key or value difference found', 'unexplained')
    verified_reorder = dict(flag('changed bytes, no key or value difference found',
                                 f'release-local list_row order followed list.parquet; {MEETING_UPDATE}', 'verified'),
                            refetch_only=True)
    for stem in ('links', 'urls', 'sources', 'recoveries', 'detail'):
        entry = report.get(f'{stem}.parquet')
        if entry and entry['groups'] == [unexplained]:
            entry['groups'] = [dict(verified_reorder)]


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
    listed with the live and candidate file and body.
    lookup_changed, address_changed: the same for lookup keys and addresses (`changed_addresses`),
    each listed with the bodies of every candidate row it reaches.
    Each count is of keys; the answers list the first `sample` keys whole, so a count above the
    keys listed means some were not listed.
    unchecked: why one of those three could not run (a column the rule reads is missing). The
    rule then fails: a check that did not run is never a pass.
    No record overrides missing, dangling or unchecked. A changed, lookup_changed or
    address_changed key passes only where the reviewed cause record names it, with both bodies,
    as a correction (`release_gate.verdict`, ct-4nax); `ok` here still reports it.
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
            # Every live row of the first `sample` keys, so a key is listed whole or not at all.
            # candidate_bodies: the saved body of each row reached, null for a row with none.
            fields = ('key', 'live_row', 'live_file', 'live_body', 'candidate_rows', 'candidate_files', 'candidate_bodies')
            out[f'{label}_changed_answers'] = [dict(zip(fields, r)) for r in d.rows(f"""SELECT {shown},c.pr,any_value(pl.filename),c.live_body,
                list_sort(list_distinct(list(l.list_row))),list_sort(list_distinct(list(ll.filename))),
                list_sort(array_agg(DISTINCT lower(hex(ld.saved_body))))
              FROM rule_changed_{table} c JOIN candidate_{table} l ON {on} LEFT JOIN candidate_detail ld ON ld.file_row_number=l.list_row
              LEFT JOIN {name('base')} pl ON pl.file_row_number=c.pr LEFT JOIN {name('candidate')} ll ON ll.file_row_number=l.list_row
              WHERE {shown} IN (SELECT DISTINCT {shown} FROM rule_changed_{table} c ORDER BY 1 LIMIT {int(sample)})
              GROUP BY 1,2,4 ORDER BY 1,2""")]
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
