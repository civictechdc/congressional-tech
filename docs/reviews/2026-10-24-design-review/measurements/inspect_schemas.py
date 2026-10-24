import sys, os, glob, collections
import pyarrow.parquet as pq

base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"

def describe(path, show_cols=True):
    pf = pq.ParquetFile(path)
    md = pf.metadata
    size = os.path.getsize(path)
    print(f"=== {os.path.basename(path)}  size={size:,} B  rows={md.num_rows:,}  row_groups={md.num_row_groups}  created_by={md.created_by}")
    # per-column compressed/uncompressed totals
    comp = collections.OrderedDict()
    uncomp = collections.OrderedDict()
    codec = {}
    enc = {}
    for rg in range(md.num_row_groups):
        rgm = md.row_group(rg)
        for c in range(rgm.num_columns):
            col = rgm.column(c)
            name = col.path_in_schema
            comp[name] = comp.get(name, 0) + col.total_compressed_size
            uncomp[name] = uncomp.get(name, 0) + col.total_uncompressed_size
            codec[name] = col.compression
            enc[name] = ",".join(sorted(set(str(e) for e in col.encodings)))
    schema = pf.schema_arrow
    if show_cols:
        print(f"  {'column':48s} {'type':40s} {'comp_B':>14s} {'uncomp_B':>14s} codec enc")
        for f in schema:
            n = f.name
            # nested columns appear with dotted paths; sum those that start with name
            cb = sum(v for k, v in comp.items() if k == n or k.startswith(n + "."))
            ub = sum(v for k, v in uncomp.items() if k == n or k.startswith(n + "."))
            cd = codec.get(n) or next((codec[k] for k in codec if k.startswith(n + ".")), "?")
            ec = enc.get(n) or next((enc[k] for k in enc if k.startswith(n + ".")), "?")
            print(f"  {n:48s} {str(f.type)[:40]:40s} {cb:14,d} {ub:14,d} {cd} {ec}")
    rg0 = md.row_group(0)
    print(f"  rowgroup0 rows={rg0.num_rows:,}  total compressed={sum(comp.values()):,}  uncompressed={sum(uncomp.values()):,}")
    kv = md.metadata or {}
    keys = [k.decode() if isinstance(k, bytes) else k for k in kv.keys()]
    print(f"  kv metadata keys: {keys[:10]}")
    return pf

for name in ["captures.parquet", "state.parquet", "filenames.parquet", "documents.parquet"]:
    describe(os.path.join(base, name))
    print()

# readings
files = sorted(glob.glob(os.path.join(base, "readings", "*.parquet")))
print(f"=== readings: {len(files)} files, total bytes={sum(os.path.getsize(f) for f in files):,}")
describe(files[0])
total_rows = 0
rg_total = 0
for f in files:
    m = pq.ParquetFile(f).metadata
    total_rows += m.num_rows
    rg_total += m.num_row_groups
print(f"  readings total rows={total_rows:,} row_groups={rg_total}")
