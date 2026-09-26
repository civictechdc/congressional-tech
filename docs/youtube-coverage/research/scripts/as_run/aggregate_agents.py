"""
Turn the investigation agents' results.jsonl files into override rows and a summary.

    python aggregate_agents.py <scratch>   -> <scratch>/agent_overrides.csv, prints counts

Verdict mapping (agent -> overrides file):
  found_youtube  -> found_tracked if the channel is in youtube-accounts.csv, else found_untracked
  found_cspan / found_archived / found_other_site -> found_offsite (URLs in video_ids, host in channel)
  clips_only / not_public / not_found -> no row (the existing verdict stands)
Only high- and medium-confidence finds become rows; low-confidence ones are listed for review.
"""
import csv, glob, json, os, re, sys, collections, urllib.parse
import requests
S = sys.argv[1]


def youtube_details(ids):
    """videoId -> {seconds, published, title, channel} from the Data API (50 per call); missing IDs are absent."""
    out, key = {}, os.environ.get("YOUTUBE_API_KEY")
    ids = sorted(set(ids))
    for k in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,contentDetails", "id": ",".join(ids[k:k+50]), "key": key}, timeout=60)
        r.raise_for_status()
        for it in r.json().get("items", []):
            m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", it["contentDetails"]["duration"])
            h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)  # "P0D" for a live or unprocessed video
            out[it["id"]] = {"seconds": h * 3600 + mi * 60 + se, "published": it["snippet"]["publishedAt"][:10], "title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"]}
    return out
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
## every claimed YouTube video must exist and be long enough to be a proceeding
details = youtube_details([v for r in results.values() if r['verdict'] == 'found_youtube' for v in (r.get('video_ids') or [])])
decisions = json.load(open(f'{S}/review_decisions.json')) if os.path.exists(f'{S}/review_decisions.json') else {}
rows, review = [], []
for pid, r in sorted(results.items()):
    if r['verdict'] == 'not_public' and r.get('confidence') == 'high':
        rows.append({'package_id': pid, 'verdict': 'not_public', 'video_ids': '', 'channel': '', 'lock': '', 'note': f"{r['agent']} (high): {r.get('evidence', '')}".replace('\n', ' ')})
        continue
    if r['verdict'] == 'found_youtube':
        ids = r.get('video_ids') or []
        missing = [v for v in ids if v not in details]
        total = sum(details[v]['seconds'] for v in ids if v in details)
        if missing or total < 1200:
            r = dict(r, confidence='low', evidence=f"[check: {'missing ' + ' '.join(missing) if missing else ''}{' total %d min' % (total // 60) if total < 1200 else ''}] " + r.get('evidence', ''))
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
    if pid in decisions.get('reject', []):
        continue
    if (conf == 'low' and pid not in decisions.get('accept_low', [])) or not row['video_ids']:
        review.append(row)
    else:
        rows.append(row)
for pid in decisions.get('not_public_extra', []):
    rows.append({'package_id': pid, 'verdict': 'not_public', 'video_ids': '', 'channel': '', 'lock': '', 'note': decisions['not_public_extra_why']})
with open(f'{S}/agent_overrides.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['package_id', 'verdict', 'video_ids', 'channel', 'lock', 'note']); w.writeheader(); w.writerows(rows)
with open(f'{S}/agent_review.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['package_id', 'verdict', 'video_ids', 'channel', 'lock', 'note']); w.writeheader(); w.writerows(review)
print(len(rows), 'override rows;', len(review), 'low-confidence or empty finds for review;', sum(1 for r in rows if r['package_id'] in existing), 'replace an existing override row')
print(collections.Counter(r['verdict'] for r in rows), collections.Counter(r['channel'] for r in rows).most_common(8))
