"""
Turn the investigation agents' results.jsonl files into override rows and a summary.

    python aggregate_agents.py <scratch>   -> <scratch>/agent_overrides.csv, prints counts

Verdict mapping (agent -> overrides file):
  found_youtube  -> found_tracked if the channel is in youtube-accounts.csv, else found_untracked
  found_cspan / found_archived / found_other_site -> found_offsite (URLs in video_ids, host in channel)
  clips_only / not_public / not_found -> no row (the existing verdict stands)
Only high- and medium-confidence finds become rows; low-confidence ones are listed for review.
"""
import csv, glob, json, sys, collections, urllib.parse
S = sys.argv[1]
chan = list(csv.DictReader(open('packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv')))
tracked = {h.lower() for c in chan for h in [c['handle']] + c['secondary'].split(';') + (c.get('member_channels') or '').split(';') if h.strip()}
existing = {r['package_id'] for r in csv.DictReader(open('apps/committee_youtube/data/hearing_video_overrides.csv'))}
results, done = {}, {}
for path in sorted(glob.glob(f'{S}/agents/agent_*/results.jsonl')):
    agent = path.split('/')[-2]
    for line in open(path):
        line = line.strip()
        if not line: continue
        d = json.loads(line)
        if d.get('done'): done[agent] = d; continue
        results[d['package_id']] = dict(d, agent=agent)  # last line wins
counts = collections.Counter((r['verdict'], r.get('confidence', '')) for r in results.values())
print(len(results), 'hearings with a verdict;', 'agents done:', sorted(done))
for k, n in sorted(counts.items()): print('  ', k, n)
rows, review = [], []
for pid, r in sorted(results.items()):
    v, conf = r['verdict'], r.get('confidence', 'low')
    if not v.startswith('found'): continue
    note = f"{r['agent']} ({conf}): {r.get('evidence', '')}".replace('\n', ' ')
    if v == 'found_youtube':
        ch = (r.get('channel') or '').strip(); ids = ' '.join(r.get('video_ids') or [])
        row = {'package_id': pid, 'verdict': 'found_tracked' if ch.lower() in tracked else 'found_untracked', 'video_ids': ids, 'channel': ch, 'lock': '', 'note': note}
    else:
        urls = r.get('urls') or []
        host = urllib.parse.urlparse(urls[0]).netloc.replace('www.', '') if urls else (r.get('channel') or '')
        row = {'package_id': pid, 'verdict': 'found_offsite', 'video_ids': ' '.join(urls), 'channel': host, 'lock': '', 'note': note}
    if conf == 'low' or not row['video_ids']:
        review.append(row)
    else:
        rows.append(row)
with open(f'{S}/agent_overrides.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['package_id', 'verdict', 'video_ids', 'channel', 'lock', 'note']); w.writeheader(); w.writerows(rows)
with open(f'{S}/agent_review.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['package_id', 'verdict', 'video_ids', 'channel', 'lock', 'note']); w.writeheader(); w.writerows(review)
print(len(rows), 'override rows;', len(review), 'low-confidence or empty finds for review;', sum(1 for r in rows if r['package_id'] in existing), 'replace an existing override row')
print(collections.Counter(r['verdict'] for r in rows), collections.Counter(r['channel'] for r in rows).most_common(8))
