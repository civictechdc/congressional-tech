"""Check the release-diff JSON by other routes: pyarrow and Python only, no SQL, and where
possible a different identity than the diagnostic uses.

  metadata   Parquet footers, not manifests, for row counts.
  bodies     saved bodies and alternates, not link keys, for splits and merges.
  evidence   capture real-file sets, not flips or public links, for removed keys.

Usage: verify.py DOWNLOADS BUILD RESULT_JSON. Exits 1 on any disagreement. What it cannot
see: both routes read the same published files, and neither says a row is right.
"""
import collections
import json
import sys

import pyarrow.compute as pc
import pyarrow.parquet as pq

d, build, result = sys.argv[1:4]
report = json.load(open(result))
files = report['files']
failures = []


def check(name, got, want):
    ok = got == want
    print('ok ' if ok else 'BAD', name, got, '' if ok else f'want {want}')
    if not ok:
        failures.append(name)


def table(side, name, columns):
    return pq.read_table(f'{d}/{side}/{name}.parquet', columns=columns).to_pylist()


def group(name, label, cause=None):
    return sum(g['count'] for g in files[f'{name}.parquet']['groups'] if g['group'] == label and cause in (None, g['cause']))


# metadata: footer counts against both the manifest and the JSON delta.
for name in 'list detail links urls sources recoveries meetings witnesses recordings bills url_state'.split():
    rows = {s: pq.read_metadata(f'{d}/{s}/{name}.parquet').num_rows for s in ('prev', 'live')}
    check(f'{name} footer delta', rows['live'] - rows['prev'], files[f'{name}.parquet']['delta'])

# evidence: real body sets alone predict the removed and added link keys.
evidence = {}
for side, version in (('prev', 'publish_v20'), ('live', 'publish_v21')):
    t = pq.read_table(f'{build}/{version}/model/evidence/capture_sources.parquet',
                      columns=['sha256', 'member_path', 'is_real_file', 'source_id', 'context_url', 'outcome'],
                      filters=None)
    real = pc.fill_null(t.column('is_real_file'), False)
    kept = t.filter(real)
    top = {}
    for sha, member in zip(kept.column('sha256').to_pylist(), kept.column('member_path').to_pylist()):
        top[sha[:8]] = top.get(sha[:8], False) or member is None
    evidence[side] = top
    if side == 'live':
        real_sources = set(kept.column('source_id').to_pylist())
        null_context = t.filter(pc.is_null(t.column('context_url')))
        null_sources = {s for s, o in zip(null_context.column('source_id').to_pylist(), null_context.column('outcome').to_pylist())
                        if o not in ('reference', 'saved-record')}
        both = real_sources & null_sources
        null_source_bodies = {sha for sha, s in zip(kept.column('sha256').to_pylist(), kept.column('source_id').to_pylist()) if s in both}
gone = set(evidence['prev']) - set(evidence['live'])
check('removed keys, member-only', sum(not evidence['prev'][k] for k in gone), -group('links', 'removed keys', 'member-only body no longer real'))
check('removed keys, top-level', sum(evidence['prev'][k] for k in gone), -group('links', 'removed keys', 'top-level body no longer eligible'))
check('added keys', len(set(evidence['live']) - set(evidence['prev'])), group('links', 'added keys', 'newly eligible body'))
check('real sources holding a NULL context', len(real_sources & null_sources), group('sources', 'NULL url'))

# bodies: which live rows hold each previous row's bodies, without reading links.parquet.
def row_bodies(side):
    out = collections.defaultdict(set)
    for i, r in enumerate(table(side, 'detail', ['saved_body', 'alternates'])):
        if r['saved_body']:
            out[i].add(r['saved_body'])
        out[i].update(a['body'] for a in r['alternates'] or [])
    return out


prev_bodies, live_bodies = row_bodies('prev'), row_bodies('live')
holders = collections.defaultdict(set)
for row, bodies in live_bodies.items():
    for body in bodies:
        holders[body].add(row)
# About 4,000 bodies sit on several live rows. Count distinct holder sets, so no tie-break is involved.
by_body = {row: {frozenset(holders[b]) for b in bodies if b in holders} for row, bodies in prev_bodies.items()}
by_key = collections.defaultdict(set)
prev_key_rows = collections.defaultdict(set)
for r in table('prev', 'links', ['link_key', 'list_row']):
    prev_key_rows[r['link_key']].add(r['list_row'])
for r in table('live', 'links', ['link_key', 'list_row']):
    for row in prev_key_rows.get(r['link_key'], ()):
        by_key[row].add(r['list_row'])
names = table('prev', 'list', ['filename'])
differ = [(row, len(by_key[row]), len(by_body[row])) for row in sorted(by_body) if max(len(by_key[row]), 1) != max(len(by_body[row]), 1)]
print('split rows, route by body holder sets', sum(max(len(v) - 1, 0) for v in by_body.values()), 'route by link keys', sum(max(len(v) - 1, 0) for v in by_key.values()))
print('rows where the routes differ (row, key route live rows, body route live rows, filename):', len(differ))
for row, keys, bodies in differ:
    print('  ', row, keys, bodies, names[row]['filename'][:70])
# A different identity, so equality is not expected. The measured gap is unexplained, not zero.
check('rows where the split routes differ, net live rows', (len(differ), sum(b - k for _, k, b in differ)), (18, 14))
check('split rows by link keys', sum(max(len(v) - 1, 0) for v in by_key.values()), group('list', 'split rows'))

# Direct recounts of the public numbers in the evidence file.
sources = {s: table(s, 'sources', ['list_row', 'url', 'member_path', 'is_saved']) for s in ('prev', 'live')}
check('member rows, live', sum(r['member_path'] is not None for r in sources['live']), 0)
null_rows = [r for r in sources['live'] if r['url'] is None]
check('NULL rows', len(null_rows), 72)
addresses = collections.Counter(r['list_row'] for r in sources['live'])
check('documents with only a NULL address', sum(addresses[r['list_row']] == 1 for r in null_rows), 12)
check('NULL rows with is_saved false', sum(not r['is_saved'] for r in null_rows), 32)
saved = table('live', 'detail', ['saved_body'])
saved_null = sum(not r['is_saved'] and saved[r['list_row']]['saved_body'] in null_source_bodies for r in null_rows)
check('NULL rows holding the saved body with is_saved false', saved_null, 31)

witnesses = {s: table(s, 'witnesses', ['witness_key']) for s in ('prev', 'live')}
check('witness keys surviving', len({r['witness_key'] for r in witnesses['prev']} & {r['witness_key'] for r in witnesses['live']}), 0)

for side, want in (('prev', (363, 78603, 34184, 23934, 10250)), ('live', (34039, 138980, 34019, 34019, 0))):
    rows = table(side, 'list', ['format', 'document_kind', 'title', 'meeting_keys', 'document_date'])
    got = (sum(r['format'] == 'zip' for r in rows),
           sum('published-hearing' in (r['document_kind'] or []) for r in rows),
           sum(r['title'] == 'ZIP' for r in rows),
           sum(r['title'] == 'ZIP' and not r['meeting_keys'] and r['document_date'] is None for r in rows),
           sum(r['title'] == 'ZIP' and bool(r['meeting_keys']) for r in rows))
    check(f'{side} zip format, published-hearing, ZIP title, ZIP title with no meeting or date, ZIP title with a meeting', got, want)

state = {s: {r['requested_url']: r for r in table(s, 'url_state', ['requested_url', 'last_attempt', 'next_attempt_at'])} for s in ('prev', 'live')}
moves = collections.Counter()
for url, p in state['prev'].items():
    l = state['live'].get(url)
    if l and p['next_attempt_at'] != l['next_attempt_at']:
        moves[(round((p['next_attempt_at'] - p['last_attempt']).total_seconds() / 86400),
               round((l['next_attempt_at'] - l['last_attempt']).total_seconds() / 86400))] += 1
check('interval moves in days', dict(moves), {(365, 7): 9301, (28, 7): 901, (7, 365): 3})

duplicated = {}
for side, entries, events in (('prev', 20531, 3199), ('live', 32882, 11263)):
    rows = table(side, 'meetings', ['event_id', 'transcripts'])
    check(f'{side} transcript entries', sum(len(r['transcripts'] or []) for r in rows), entries)
    duplicated[side] = {r['event_id'] for r in rows if len(p := [t['package_id'] for t in r['transcripts'] or []]) > len(set(p))}
    check(f'{side} events with duplicate transcripts', len(duplicated[side]), events)
check('newly duplicated events', len(duplicated['live'] - duplicated['prev']), 8064)

print(f'{len(failures)} disagreements')
sys.exit(1 if failures else 0)
