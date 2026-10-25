from pathlib import Path
from collections import Counter
import json
import time
import sys
import duckdb

sys.dont_write_bytecode = True
PACKAGE = Path('/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/house-naming')
sys.path.insert(0, str(PACKAGE / 'src'))
from house_naming import Engine

root = Path('/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs')
con = duckdb.connect()
con.execute("SET threads = 4")
con.execute("SET memory_limit = '2GB'")
con.execute("SET temp_directory = './naming_tmp'")
pairs = con.execute(f"""SELECT filename,source_url FROM read_parquet('{root / 'filenames.parquet'}')
    GROUP BY 1,2 ORDER BY hash(filename, source_url) LIMIT 10000""").fetchall()
engine = Engine()
start = time.perf_counter()
counts = Counter()
multi = []
failures = []
for filename, url in pairs:
    try:
        item = engine.extract(filename, source_url=url)
    except Exception as exc:
        counts['exceptions'] += 1
        if len(failures) < 10:
            failures.append({'filename': filename, 'url': url, 'error': str(exc)})
        continue
    meta = item['metadata']
    for field in ('congress','meeting_date','document_kind','committee_code','measure_type','measure_number'):
        if meta.get(field): counts[field+'_present'] += 1
        if len(meta.get(field,[])) > 1:
            counts[field+'_multiple'] += 1
            if field in ('congress','document_kind','committee_code') and len(multi)<12:
                multi.append({'filename':filename,'url':url,'field':field,'values':meta[field]})
seconds = time.perf_counter() - start
catalog = json.loads((PACKAGE/'src/house_naming/data/guide.json').read_text())
qualified = {u for rule in catalog['extraction_rules'] for u in rule.get('source_urls', [])}
result = {'sample':len(pairs), 'selection':'lowest DuckDB hashes of distinct filename/source_url pairs',
          'seconds':seconds,'ms_per_pair':seconds/len(pairs)*1000,
          'estimated_minutes_full_backfill':seconds/len(pairs)*1392681/60,
          'exact_qualified_urls':len(qualified),'counts':dict(counts),'multivalue_examples':multi,
          'failure_examples':failures}
Path('naming_measurements.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
