"""Independent raw judge for capture address changes (url, context_url, recovered_url).

    url_judge.py CHANGES.parquet MIRROR_ROOT OUT.json

A changed url is explained when the raw record (or list item) names the new value as its
final_url or resolved_url while the old value is its request address (record url);
context_url and recovered_url follow that final address when the entry names no context
of its own (no entry context_url) or the row is a recovery without recovery_evidence url.
"""
import gzip, json, os, sys
from collections import Counter, defaultdict
import duckdb

changes, mirror, out = sys.argv[1:4]
rows = duckdb.connect().execute(f"""SELECT receipt_key,receipt_line,capture_index,old_url,new_url,
    old_context_url,new_context_url,old_recovered_url,new_recovered_url,family FROM '{changes}'""").fetchall()
by = defaultdict(lambda: defaultdict(list))
for r in rows:
    by[r[0]][r[1]].append(r)
summary, defects = Counter(), []
for key, lines in sorted(by.items()):
    last = max(lines)
    with gzip.open(os.path.join(mirror, key), 'rt', encoding='utf-8') as handle:
        for number, text in enumerate(handle, 1):
            if number > last:
                break
            if number not in lines:
                continue
            line = json.loads(text)
            record = line.get('record')
            primary = line.get('captures') or line.get('file_references') or []
            for _, _, index, ou, nu, oc, nc, orr, nr, family in lines[number]:
                items = record if isinstance(record, list) else [record]
                finals = {i.get('final_url') or i.get('resolved_url') for i in items if isinstance(i, dict)}
                requests = {i.get('url') for i in items if isinstance(i, dict)}
                entry = primary[index] if 0 <= index < len(primary) and isinstance(primary[index], dict) else {}
                for column, old, new in (('url', ou, nu), ('context_url', oc, nc), ('recovered_url', orr, nr)):
                    if old == new:
                        continue
                    ok = new in finals and old in requests and not line.get('url')
                    if column == 'context_url':
                        ok = ok and not entry.get('context_url')
                    cause = 'final_url_from_record' if ok else 'UNEXPLAINED'
                    summary[(column, cause)] += 1
                    if not ok:
                        defects.append([key, number, index, column, old, new])
json.dump(dict(rows=len(rows), classes=[[*k, v] for k, v in sorted(summary.items())], defects=defects[:50],
               defect_count=len(defects)), open(out, 'w'), indent=1)
print(json.dumps(dict(rows=len(rows), defects=len(defects), classes=dict((f'{a}:{b}', v) for (a, b), v in summary.items()))))
