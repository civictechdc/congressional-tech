"""Re-review checks: filename_readings key cardinality; grouping with placeholder rule; detail layouts."""
import os, time, array, json, binascii, resource
import duckdb, pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc

base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/browser-files"
os.makedirs(out + "/tmp", exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='8GB'; SET threads=4; SET temp_directory='{out}/tmp'; SET max_temp_directory_size='20GiB'; SET preserve_insertion_order=false;")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20

print("=== (1) filename_readings key cardinality")
print(" filenames.parquet distinct (filename, source_url):", con.execute(f"select count(*) from (select distinct filename, source_url from read_parquet('{base}/filenames.parquet'))").fetchone()[0])
print(" filenames.parquet distinct (filename, host):", con.execute(f"select count(*) from (select distinct filename, regexp_extract(source_url, '^[a-z]+://([^/]+)', 1) from read_parquet('{base}/filenames.parquet'))").fetchone()[0])
print(" filenames.parquet distinct filename:", con.execute(f"select count(distinct filename) from read_parquet('{base}/filenames.parquet')").fetchone()[0])
print(" captures distinct context_url (= pairs when filename derives from URL):", con.execute(f"select count(distinct context_url) from read_parquet('{base}/captures.parquet')").fetchone()[0])
print(" captures distinct (basename, url) where sha present:", con.execute(f"select count(*) from (select distinct regexp_extract(context_url, '([^/?#]+)(?:[?#].*)?$', 1), context_url from read_parquet('{base}/captures.parquet') where sha256 is not null)").fetchone()[0])
# how many filenames rows are recovered (filename != url basename)?
print(" filenames rows where filename != basename(source_url):", con.execute(f"select count(*) from read_parquet('{base}/filenames.parquet') where filename is not null and source_url is not null and filename <> regexp_extract(source_url, '([^/?#]+)(?:[?#].*)?$', 1)").fetchone()[0])
print(" duplicate-body attempts: attempts with sha256 minus distinct bodies:", con.execute(f"select count(*) - count(distinct sha256) from read_parquet('{base}/captures.parquet') where sha256 is not null").fetchone()[0])
print(" normal-day duplicates (Oct 13-16): ", con.execute(f"""with f as (select sha256, min(capture_date) d0 from read_parquet('{base}/captures.parquet') where sha256 is not null group by 1)
  select c.capture_date, count(*) attempts_with_body, sum(case when f.d0 < c.capture_date then 1 else 0 end) hit_existing from read_parquet('{base}/captures.parquet') c join f using(sha256) where c.capture_date in ('2026-10-13','2026-10-14','2026-10-15','2026-10-16') group by 1 order by 1""").fetchall())
print(" receipt key prefixes that are not dates:", con.execute(f"select regexp_extract(receipt_key, '^receipts/[^/]+(?:/[^/]+)?/([^/]+)/', 1) seg, count(distinct receipt_key) files, count(*) n_rows from read_parquet('{base}/captures.parquet') where receipt_key not similar to 'receipts/.*/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/.*' group by 1 order by 3 desc limit 5").fetchall())
print(" families whose lexicographically-largest receipt key is non-date:", con.execute(f"""with m as (select family, max(receipt_key) mx from read_parquet('{base}/captures.parquet') group by 1)
  select family, mx from m where mx not similar to 'receipts/.*/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/.*' order by 1""").fetchall())

print("=== (2) grouping with placeholder rule (edges: source-body, plus source-(filename,url) endpoint)")
t=time.time()
con.execute(f"""create table f as select source_id, body_key, source_url, filename, record_role[1] rr, media_type[1] mt from read_parquet('{base}/filenames.parquet')""")
con.execute("""create table bdeg as select body_key, count(*) deg from f where body_key is not null group by 1""")
print(" body degree distribution:", con.execute("select max(deg), quantile_cont(deg,0.999), sum(case when deg>10 then 1 else 0 end) over10, sum(case when deg>50 then 1 else 0 end) over50, sum(case when deg>200 then 1 else 0 end) over200, sum(case when deg>1000 then 1 else 0 end) over1000 from bdeg").fetchall())
con.execute("""create table nodes as select node, row_number() over () - 1 as nid from (select distinct node from (
   select source_id node from f union all select body_key from f union all select filename || '|' || source_url from f) where node is not null)""")
n = con.execute("select count(*) from nodes").fetchone()[0]
def cc(rows, n, label):
    t=time.time(); parent = array.array('i', range(n))
    def find(x):
        r = x
        while parent[r] != r: r = parent[r]
        while parent[x] != r: parent[x], x = r, parent[x]
        return r
    for a,b in rows:
        ra, rb = find(a), find(b)
        if ra != rb: parent[max(ra,rb)] = min(ra,rb)
    sizes = {}
    for i in range(n):
        r = find(i); sizes[r] = sizes.get(r,0)+1
    s = sorted(sizes.values(), reverse=True)
    print(f" {label}: components={len(s):,} largest={s[:6]} >1000: {sum(1 for x in s if x>1000)}  ({time.time()-t:.1f}s)")
e_end = con.execute("select a.nid, b.nid from f join nodes a on a.node=f.source_id join nodes b on b.node = f.filename || '|' || f.source_url").fetchall()
for k in (None, 1000, 200, 50, 10):
    cond = "" if k is None else f" and f.body_key in (select body_key from bdeg where deg <= {k})"
    e_body = con.execute(f"select a.nid, b.nid from f join nodes a on a.node=f.source_id join nodes b on b.node=f.body_key where f.rr <> 'error-response'{cond}").fetchall()
    cc(e_body + e_end, n, f"k={k} (non-error sources; body edges with degree<=k; endpoint edges)")
e_body = con.execute("select a.nid, b.nid from f join nodes a on a.node=f.source_id join nodes b on b.node=f.body_key where f.rr <> 'error-response' and f.body_key in (select body_key from bdeg where deg <= 50) and (f.mt is null or f.mt not like 'text/html%')").fetchall()
cc(e_body + e_end, n, "k=50 and HTML bodies excluded (D4 §6.1 rule)")
print(f" rss={rss():.0f}MB")

print("=== (3) detail layouts: flat binary columns vs List<Struct<field,value>> fold vs one blob column")
t=time.time()
det = con.execute(f"""
select document_id, source_id, body_key, source_url, body_keys, source_urls, filenames, filename
from read_parquet('{base}/documents.parquet') order by filename, document_id""").fetch_arrow_table()
nrows = det.num_rows
def hex2bin(col, n=32):
    return pa.array([binascii.unhexlify(h) if h and len(h)==2*n else None for h in col.to_pylist()], pa.binary(n))
def key2bin(col):
    out=[]
    for k in col.to_pylist():
        if k is None: out.append(None); continue
        s = k.rsplit('/',1)[-1].split('.')[0]
        out.append(binascii.unhexlify(s) if len(s)==64 else None)
    return pa.array(out, pa.binary(32))
doc_b = hex2bin(det["document_id"]); src_b = hex2bin(det["source_id"]); body_b = key2bin(det["body_key"])
bks = det["body_keys"].to_pylist()
body_list = pa.array([[binascii.unhexlify(k.rsplit('/',1)[-1].split('.')[0]) for k in (l or []) if len(k.rsplit('/',1)[-1].split('.')[0])==64] for l in bks], pa.list_(pa.binary(32)))
occ_start = pa.array(range(nrows), pa.int32()); occ_len = pa.array([4]*nrows, pa.int16())
flat = pa.table({"document_id": doc_b, "source_id": src_b, "body_sha": body_b, "source_url": det["source_url"],
                 "body_shas": body_list, "source_urls": det["source_urls"], "filenames": det["filenames"], "occ_start": occ_start, "occ_len": occ_len})
# blob: one JSON object per row (hashes as hex to stay JSON)
urls = det["source_urls"].to_pylist(); fns = det["filenames"].to_pylist()
blob = pa.array([json.dumps({"d": d, "s": s, "b": b, "u": u, "bs": [k.rsplit('/',1)[-1].split('.')[0] for k in (bk or [])], "us": us or [], "fn": fn or [], "o": [i, 4]}, separators=(",",":"))
                 for i,(d,s,b,u,bk,us,fn) in enumerate(zip(det["document_id"].to_pylist(), det["source_id"].to_pylist(), det["body_key"].to_pylist(), det["source_url"].to_pylist(), bks, urls, fns))], pa.string())
blobt = pa.table({"row": pa.array(range(nrows), pa.int32()), "detail": blob})
# fold: List<Struct<field, value>> with each value as a string (hex for hashes)
fold_vals = []
for i,(d,s,b,u,bk,us,fn) in enumerate(zip(det["document_id"].to_pylist(), det["source_id"].to_pylist(), det["body_key"].to_pylist(), det["source_url"].to_pylist(), bks, urls, fns)):
    items = [("d", d), ("s", s), ("b", b), ("u", u), ("o", f"{i}:4")]
    items += [("bs", k.rsplit('/',1)[-1].split('.')[0]) for k in (bk or [])]
    items += [("us", x) for x in (us or [])] + [("fn", x) for x in (fn or [])]
    fold_vals.append([{"field": f, "value": v} for f, v in items if v is not None])
fold = pa.table({"row": pa.array(range(nrows), pa.int32()), "detail": pa.array(fold_vals, pa.list_(pa.struct([("field", pa.string()), ("value", pa.string())])))})
print(f" built variants in {time.time()-t:.1f}s rss={rss():.0f}MB")

def report(tbl, name, page_kb=64):
    p = f"{out}/{name}.parquet"
    pq.write_table(tbl, p, compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True,
                   write_statistics=True, write_page_index=True, row_group_size=131072, data_page_size=page_kb*1024)
    md = pq.read_metadata(p); size = os.path.getsize(p)
    comp, uncomp = {}, {}
    for rg in range(md.num_row_groups):
        for c in range(md.row_group(rg).num_columns):
            col = md.row_group(rg).column(c)
            comp[col.path_in_schema] = comp.get(col.path_in_schema,0)+col.total_compressed_size
            uncomp[col.path_in_schema] = uncomp.get(col.path_in_schema,0)+col.total_uncompressed_size
    # estimate: pages per leaf = ceil(uncomp / page size); bytes per point read = sum over leaves of comp/pages
    per_read = 0; leaves = 0
    for k in comp:
        pages = max(1, -(-uncomp[k] // (page_kb*1024)))
        per_read += comp[k] / pages; leaves += 1
    with open(p, "rb") as fh:
        fh.seek(-8, 2); flen = int.from_bytes(fh.read(4), "little")
    print(f" {name:12s} page={page_kb}KB: file={size/2**20:7.1f} MB  leaf columns={leaves}  est. bytes per detail read={per_read/1024:6.1f} KB in {leaves} requests  FileMetaData={flen/1024:.0f} KB  rgs={md.num_row_groups}")
for pk in (64, 16):
    report(flat, "detail_flat", pk); report(fold, "detail_fold", pk); report(blobt, "detail_blob", pk)
print(f" rss={rss():.0f}MB total")

print("=== (4) row-group granularity (hyparquet reads whole column chunks of a row group): footer vs bytes per detail view")
for rg_rows in (1024, 4096, 16384, 131072):
    p = f"{out}/detail_flat_rg{rg_rows}.parquet"
    pq.write_table(flat, p, compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True,
                   write_statistics=True, write_page_index=True, row_group_size=rg_rows, data_page_size=64*1024)
    md = pq.read_metadata(p)
    with open(p, "rb") as fh:
        fh.seek(-8, 2); flen = int.from_bytes(fh.read(4), "little")
    per_rg = [sum(md.row_group(i).column(c).total_compressed_size for c in range(md.row_group(i).num_columns)) for i in range(min(md.num_row_groups, 200))]
    print(f" rows/rowgroup={rg_rows:6d}: rowgroups={md.num_row_groups:5d} FileMetaData={flen/1024:7.1f} KB  bytes per detail view (one row group, all 9 chunks) avg={sum(per_rg)/len(per_rg)/1024:7.1f} KB max={max(per_rg)/1024:7.1f} KB  file={os.path.getsize(p)/2**20:.1f} MB")
