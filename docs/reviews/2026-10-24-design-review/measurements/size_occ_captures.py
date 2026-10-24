import os, time, duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/browser-files"
os.makedirs(out + "/tmp", exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='8GB'; SET threads=4; SET temp_directory='{out}/tmp'; SET max_temp_directory_size='20GiB'; SET preserve_insertion_order=false;")

t=time.time()
# project the 47-field struct down to 9 scalars inside the scan, then number rows, then unnest
con.execute(f"""
create table d as
select filename, document_id,
       list_transform(source_occurrences, o -> struct_pack(
           capture_url := o.source_capture_url[1], page_url := o.source_page_url[1], meeting_date := o.source_meeting_date[1],
           document_label := o.source_document_label[1], committee_code := o.source_committee_code[1], congress := o.source_congress[1],
           receipt_key := o.source_receipt_key[1], receipt_line := o.source_receipt_line[1], scope := o.source_occurrence_scope[1])) occs
from read_parquet('{base}/documents.parquet')""")
print(f"projected occurrences in {time.time()-t:.1f}s")
t=time.time()
con.execute("""
create table occ as
with d2 as (select row_number() over (order by filename, document_id) - 1 as list_row, occs from d),
     u as (select list_row, generate_subscripts(occs, 1) - 1 as ordinal, unnest(occs) as o from d2)
select list_row, ordinal, o.capture_url, o.page_url, o.meeting_date, o.document_label, o.committee_code, o.congress, o.receipt_key,
       try_cast(o.receipt_line as integer) receipt_line, o.scope
from u""")
n = con.execute("select count(*) from occ").fetchone()[0]
print(f"occurrences rows={n:,} built in {time.time()-t:.1f}s")
for cols, name in [("*", "occ_full"), ("list_row, ordinal, capture_url, page_url, meeting_date, document_label, scope", "occ_lean"), ("list_row, ordinal, capture_url, receipt_key, receipt_line", "occ_min")]:
    p = f"{out}/{name}.parquet"
    con.execute(f"copy (select {cols} from occ order by list_row, ordinal) to '{p}' (format parquet, compression zstd, row_group_size 262144)")
    print(f"  {name}: {os.path.getsize(p)/2**20:.1f} MB")
print(con.execute("select count(distinct capture_url) urls, count(distinct page_url) pages, count(distinct receipt_key) receipts, count(distinct document_label) labels, sum(case when receipt_key is null then 1 else 0 end) no_receipt from occ").fetchall())

# captures lake table, compact: binary hashes, no derivable body_key, typed timestamp/status
t=time.time()
p = f"{out}/captures_compact.parquet"
con.execute(f"""
copy (select family, capture_date, receipt_key, receipt_line, reference_kind, pointer_json, context_url,
             unhex(sha256) sha256, bytes, unhex(stored_sha256) stored_sha256, stored_bytes, fidelity, media_type,
             try_cast(retrieved_at as timestamptz) retrieved_at, cast(http_status as smallint) http_status, resolution, original_path, source_file, source_line
      from read_parquet('{base}/captures.parquet') order by context_url, retrieved_at nulls first, receipt_key, receipt_line)
to '{p}' (format parquet, compression zstd, row_group_size 262144)""")
print(f"captures_compact (binary hashes, no body_key, sorted by url): {os.path.getsize(p)/2**20:.1f} MB vs original {os.path.getsize(base+'/captures.parquet')/2**20:.1f} MB  ({time.time()-t:.1f}s)")
import pyarrow.parquet as pq
md = pq.read_metadata(p); cols={}
for rg in range(md.num_row_groups):
    for c in range(md.row_group(rg).num_columns):
        col = md.row_group(rg).column(c); cols[col.path_in_schema] = cols.get(col.path_in_schema,0)+col.total_compressed_size
print("  per column MB:", {k: round(v/2**20,1) for k,v in sorted(cols.items(), key=lambda kv:-kv[1])})

p2 = f"{out}/captures_day_20261016.parquet"
con.execute(f"""copy (select family, capture_date, receipt_key, receipt_line, reference_kind, pointer_json, context_url, unhex(sha256) sha256, bytes, unhex(stored_sha256) stored_sha256, stored_bytes, fidelity, media_type, retrieved_at, http_status, resolution, original_path, source_file, source_line
   from read_parquet('{base}/captures.parquet') where capture_date='2026-10-16' order by context_url) to '{p2}' (format parquet, compression zstd)""")
print(f"one day (2026-10-16) append as parquet: {os.path.getsize(p2)/1024:.0f} KB, rows={con.execute(f"select count(*) from read_parquet('{p2}')").fetchone()[0]}")

print("--- body size extremes (stored_bytes):", con.execute(f"""select max(stored_bytes) mx, sum(case when stored_bytes>5e9 then 1 else 0 end) over5g, sum(case when stored_bytes>1e9 then 1 else 0 end) over1g, sum(case when stored_bytes>100e6 then 1 else 0 end) over100m, sum(case when stored_bytes>5e6 then 1 else 0 end) over5m from (select sha256, max(stored_bytes) stored_bytes from read_parquet('{base}/captures.parquet') where sha256 is not null group by 1)""").fetchall())
print("--- readings today by media type of body:", con.execute(f"""
with r as (select distinct body_key from read_parquet('{base}/readings/*.parquet', union_by_name=true)),
     c as (select body_key, any_value(media_type) mt, any_value(family) fam, max(stored_bytes) sb from read_parquet('{base}/captures.parquet') where body_key is not null group by 1)
select coalesce(mt,'None') mt, count(*) n, sum(sb) stored_bytes from r join c using(body_key) group by 1 order by 2 desc limit 12""").fetchall())
print("--- readings today by family:", con.execute(f"""
with r as (select distinct body_key from read_parquet('{base}/readings/*.parquet', union_by_name=true)),
     c as (select body_key, any_value(family) fam from read_parquet('{base}/captures.parquet') where body_key is not null group by 1)
select fam, count(*) n from r join c using(body_key) group by 1 order by 2 desc limit 12""").fetchall())
