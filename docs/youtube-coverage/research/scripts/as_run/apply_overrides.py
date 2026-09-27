"""Merge agent_overrides.csv into hearing_video_overrides.csv: rows replace existing ones by package_id."""
import csv, sys
S = sys.argv[1]
path = 'apps/committee_youtube/data/hearing_video_overrides.csv'
rows = list(csv.DictReader(open(path))); cols = list(rows[0].keys()); by = {r['package_id']: r for r in rows}
new = list(csv.DictReader(open(f'{S}/agent_overrides.csv')))
replaced = added = 0
for r in new:
    if r['package_id'] in by:
        prev = by[r['package_id']]
        if prev['verdict'] in ('found_tracked', 'found_untracked') and r['verdict'] == 'found_offsite':
            continue  # a YouTube recording already known beats an offsite one
        prev.update(r); replaced += 1
    else:
        rows.append(r); by[r['package_id']] = r; added += 1
with open(path, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f'{len(new)} agent rows: replaced {replaced}, added {added}; overrides now {len(rows)}')
