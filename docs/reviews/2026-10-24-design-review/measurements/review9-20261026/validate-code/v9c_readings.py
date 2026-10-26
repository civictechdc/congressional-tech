import sys, glob, pyarrow.parquet as pq, pyarrow as pa, collections
d = sys.argv[1]
files = sorted(glob.glob(d + '/**/*.parquet', recursive=True))
print(len(files), 'files')
t = pa.concat_tables([pq.read_table(f) for f in files], promote_options='default')
print(t.schema)
print(t.num_rows)
rows = t.to_pylist()
c = collections.Counter()
for r in rows:
    bf = tuple(r.get('body_format') or [])
    if 'pdf' not in bf: continue
    other = sorted(k for k, v in r.items() if k not in ('body_key','parser_fingerprint','status','error_type','body_format') and v)
    c[(r['status'], tuple(other))] += 1
for k, v in c.most_common(30): print(v, k)
