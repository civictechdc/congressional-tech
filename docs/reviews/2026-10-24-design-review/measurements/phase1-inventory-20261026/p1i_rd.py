import duckdb, pyarrow.parquet as pq, glob, collections
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
fs=sorted(glob.glob(A+'readings/*.parquet'))
cols=collections.Counter(); metas=collections.Counter(); fv=collections.Counter()
for f in fs:
    s=pq.read_schema(f)
    for n in s.names: cols[n]+=1
    m=s.metadata or {}
    fv[m.get(b'format_version')]+=1
    for k in m: metas[k]+=1
print(len(fs), fv, metas.most_common())
print(sorted(cols.items(), key=lambda x:-x[1]))
for k in (b'source_cache_version', b'source_cache_sha256'):
    vals=collections.Counter((pq.read_schema(f).metadata or {}).get(k) for f in fs)
    print(k, vals.most_common(5))
m=pq.read_schema(A+'filenames.parquet').metadata
print({k.decode():v.decode()[:100] for k,v in m.items()})
