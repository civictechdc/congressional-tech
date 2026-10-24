"""DuckDB proxy for the model plan: url_state, filenames (sources x readings), members aggregation, sorted export.
Runner-like limits: 4 threads, 10 GB memory."""
import time, resource, os, duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/model-proxy"
os.makedirs(out, exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='10GB'; SET threads=4; SET temp_directory='{out}/tmp'; SET preserve_insertion_order=false;")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20
def mem():
    r = con.execute("select sum(memory_usage_bytes) from duckdb_memory()").fetchone()[0]
    return (r or 0)/2**20
T0=time.time()
def step(name, sql):
    t=time.time(); con.execute(sql); print(f"{name:34s} {time.time()-t:7.1f}s  duckdb_mem={mem():7.0f}MB  rss={rss():6.0f}MB", flush=True)

step("register captures (view)", f"create view cap as select * from read_parquet('{base}/captures.parquet')")
step("url_state (arg_max per url)", """
create table url_state as
select context_url url, count(*) attempts, max(retrieved_at) last_attempt,
       arg_max(http_status, coalesce(retrieved_at,'')) last_status,
       arg_max(resolution, coalesce(retrieved_at,'')) last_resolution,
       arg_max(sha256, coalesce(retrieved_at,'')) last_sha
from cap where context_url is not null group by context_url""")
print("  url_state rows:", con.execute("select count(*) from url_state").fetchone()[0])

step("sources = distinct (url, body)", """
create table sources as
select context_url url, sha256, any_value(media_type) media_type, min(retrieved_at) first_seen, count(*) attempts,
       regexp_extract(context_url, '([^/?#]+)(?:[?#].*)?$', 1) filename
from cap where sha256 is not null and context_url is not null group by context_url, sha256""")
print("  sources rows:", con.execute("select count(*) from sources").fetchone()[0])

step("readings (721 files -> table)", f"""
create table readings as select body_key, parser_fingerprint, status, record_role, content_document_kind, content_congress, content_citation
from read_parquet('{base}/readings/*.parquet', union_by_name=true)""")
print("  readings rows:", con.execute("select count(*) from readings").fetchone()[0])

step("filenames = sources ⟕ readings", """
create table filenames_m as
select s.*, r.status reading_status, r.record_role, r.content_document_kind, r.content_congress
from sources s left join readings r on r.body_key = 'bodies/sha256/' || substr(s.sha256,1,2) || '/' || s.sha256 || '.gz'""")
print("  joined rows:", con.execute("select count(*) from filenames_m").fetchone()[0],
      " with reading:", con.execute("select count(*) from filenames_m where reading_status is not null").fetchone()[0])

step("members = urls per body (list agg)", """
create table members as select sha256, list(url order by url) urls, count(*) n from sources group by sha256""")

step("export filenames sorted (zstd)", f"""
copy (select * from filenames_m order by filename, sha256, url) to '{out}/filenames_m.parquet' (format parquet, compression zstd, row_group_size 131072)""")
step("export url_state sorted (zstd)", f"""
copy (select * from url_state order by url) to '{out}/url_state.parquet' (format parquet, compression zstd, row_group_size 131072)""")
step("export members sorted (zstd)", f"""
copy (select * from members order by sha256) to '{out}/members.parquet' (format parquet, compression zstd, row_group_size 131072)""")
for f in ["filenames_m.parquet","url_state.parquet","members.parquet"]:
    print(f"  {f}: {os.path.getsize(os.path.join(out,f))/2**20:.1f} MB")
# determinism check: run the export twice and compare bytes
import hashlib
def h(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
a = h(f"{out}/url_state.parquet")
con.execute("SET threads=2")
con.execute(f"copy (select * from url_state order by url) to '{out}/url_state_2.parquet' (format parquet, compression zstd, row_group_size 131072)")
b = h(f"{out}/url_state_2.parquet")
print(f"  determinism (same sort, threads 4 vs 2): {'IDENTICAL' if a==b else 'DIFFERENT'}")
print(f"TOTAL {time.time()-T0:.1f}s peak rss={rss():.0f}MB")
