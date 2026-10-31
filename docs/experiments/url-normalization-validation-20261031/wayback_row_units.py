"""Reconcile CDX row occurrences, mismatching originals, and candidate counts."""
from common import *
from collections import Counter
from corpus_recovery.discovery import _wayback_page,validate_wayback_replay
from corpus_recovery.cdx import key
r=json.loads((HERE/'evidence/wayback-results.json').read_text());counts=Counter();pages=[]
for item in r['details']:
 if item['status']!=200:continue
 final=json.loads(Path(item['evidence']).read_text())['final']
 body=Path(final['body']['path']).read_bytes()
 assert hashlib.sha256(body).hexdigest()==final['body']['sha256']
 if json.loads(body)==[]:counts['empty_pages']+=1;continue
 records,_=_wayback_page(body);counts['nonempty_pages']+=1;counts['row_occurrences']+=len(records)
 for row in records:
  counts['different_original']+=row['original']!=item['target']
  counts['surt_equal']+=row['urlkey']==key(item['target'])==key(row['original'])
  replay=f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"
  counts['exact_returned_replay_valid']+=validate_wayback_replay(replay,row['original'],row['timestamp'])
  if item['before']=='invalid_index_response':counts['rows_on_rejected_pages']+=1
 pages.append({'target':item['target'],'rows':len(records),'different_original':sum(v['original']!=item['target'] for v in records)})
result={'counts':dict(counts),'pages':pages}
dump('wayback-row-unit-check.json',result)
(HERE/'evidence/wayback-row-unit-check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(counts),indent=2))
