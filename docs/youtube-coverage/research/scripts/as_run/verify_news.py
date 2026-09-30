"""
Check the news-search candidates with the YouTube Data API: exact upload date, length,
description. A candidate is confirmed when it is 30+ minutes, its title shares the
hearing's words, and it was uploaded the day of the hearing (to 3 days after) or its
text carries the hearing's date or event ID. Writes confirmed.csv and review.csv.
"""
import collections
import csv
import datetime as dt
import json
import os
import re
import sys

import requests

sys.path.insert(0, 'packages/congress_api/src'); sys.path.insert(0, 'packages/congress_shared/src')
from congress_api.matching.gpo_videos import EVENT_ID, dates_in_text, similarity, words

S = sys.argv[1]  # scratch dir holding news_candidates.json; the repo copies are research/data/news_search_*.json
cands = json.load(open(f'{S}/news_candidates.json'))
gpo = {r['package_id']: r for r in csv.DictReader(open('apps/committee_youtube/data/gpo_hearings.csv'))}
ids = sorted({c['videoId'] for h in cands for c in h['candidates']})
cache_path = f'{S}/video_details.json'
details = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
need = [i for i in ids if i not in details]
for k in range(0, len(need), 50):
    r = requests.get('https://www.googleapis.com/youtube/v3/videos', params={'part': 'snippet,contentDetails', 'id': ','.join(need[k:k+50]), 'key': os.environ['YOUTUBE_API_KEY']}, timeout=60)
    r.raise_for_status()
    for it in r.json().get('items', []):
        s, c = it['snippet'], it['contentDetails']
        m = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', c['duration']); h_, m_, s_ = (int(x or 0) for x in m.groups())
        details[it['id']] = {'published': s['publishedAt'][:10], 'seconds': h_*3600 + m_*60 + s_, 'title': s['title'], 'description': s['description'], 'channel': s['channelTitle'], 'channelId': s['channelId']}
    for i in need[k:k+50]: details.setdefault(i, None)
json.dump(details, open(cache_path, 'w'), indent=1)
confirmed, review = [], []
for h in cands:
    g = gpo[h['package_id']]; held = g['held_date']; tw = words(re.sub(r'^\[[^\]]*\]\s*', '', g['title']))
    for c in h['candidates']:
        d = details.get(c['videoId'])
        if not d or d['seconds'] < 1800: continue
        text = f"{d['title']} {d['description']}"
        sim = similarity(tw, words(d['title'])); sim_desc = similarity(tw, words(text))
        gap = (dt.date.fromisoformat(d['published']) - dt.date.fromisoformat(held)).days
        date_hit = held in dates_in_text(text); eid_hit = bool(g['event_id']) and g['event_id'] in {a or b for a, b in EVENT_ID.findall(text)}
        row = {'package_id': h['package_id'], 'held_date': held, 'committee': h['committee'], 'hearing_title': g['title'][:120], 'status': h['status'],
               'videoId': c['videoId'], 'channel': d['channel'], 'handle': c['channel'], 'published': d['published'], 'gap_days': gap, 'minutes': d['seconds']//60,
               'sim_title': round(sim, 2), 'sim_text': round(sim_desc, 2), 'date_in_text': date_hit, 'event_id_in_text': eid_hit, 'video_title': d['title'][:120], 'transcript': h['transcript']}
        if (eid_hit or date_hit or 0 <= gap <= 3) and (sim >= 0.5 or sim_desc >= 0.6 or eid_hit):
            confirmed.append(row)
        elif sim >= 0.5 or sim_desc >= 0.6 or 0 <= gap <= 3:
            review.append(row)
for name, rows in (('confirmed', confirmed), ('review', review)):
    with open(f'{S}/{name}.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['package_id']); w.writeheader(); w.writerows(rows)
print(len(cands), 'hearings with candidates;', len(ids), 'videos;', sum(1 for i in ids if not details.get(i)), 'unavailable')
print('confirmed rows', len(confirmed), 'for', len({r['package_id'] for r in confirmed}), 'hearings; review rows', len(review), 'for', len({r['package_id'] for r in review}), 'hearings')
print(collections.Counter(r['channel'] for r in confirmed).most_common(10))
