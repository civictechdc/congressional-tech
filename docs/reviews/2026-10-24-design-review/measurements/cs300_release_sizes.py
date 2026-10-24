"""Size the revision-5 release files and lake folds from the Oct 19 snapshot."""
import os, time, resource, binascii, duckdb, pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/cs300/files"
os.makedirs(out + "/tmp", exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='10GB'; SET threads=4; SET temp_directory='{out}/tmp'; SET max_temp_directory_size='30GiB'; SET preserve_insertion_order=false;")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20
docs = f"read_parquet('{base}/documents.parquet')"; cap = f"read_parquet('{base}/captures.parquet')"

def write(tbl, name, **kw):
    p = f"{out}/{name}.parquet"
    opts = dict(compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True, write_statistics=True, write_page_index=True, row_group_size=131072)
    opts.update(kw); pq.write_table(tbl, p, **opts)
    md = pq.read_metadata(p); size = os.path.getsize(p)
    with open(p, "rb") as fh: fh.seek(-8, 2); flen = int.from_bytes(fh.read(4), "little")
    comp, uncomp, data_end = {}, {}, 0
    for rg in range(md.num_row_groups):
        for c in range(md.row_group(rg).num_columns):
            col = md.row_group(rg).column(c)
            comp[col.path_in_schema] = comp.get(col.path_in_schema, 0) + col.total_compressed_size
            uncomp[col.path_in_schema] = uncomp.get(col.path_in_schema, 0) + col.total_uncompressed_size
            start = min(x for x in (col.dictionary_page_offset, col.data_page_offset) if x)
            data_end = max(data_end, start + col.total_compressed_size)
    oidx = (size - 8 - flen) - data_end; cidx = 0  # page indexes (column + offset) sit between data and footer
    page_kb = kw.get("data_page_size", 1024*1024) / 1024
    per_view = sum(comp[k] / max(1, -(-uncomp[k] // int(page_kb*1024))) for k in comp)
    print(f"  {name:22s} {size/2**20:7.1f} MB rows={md.num_rows:,} rgs={md.num_row_groups} leaves={len(comp)} footer={flen/1024:.0f} KB page_indexes={oidx/1024:.0f} KB est.bytes/view={per_view/1024:.1f} KB")
    return size

t0 = time.time()
# first-captured date per document body (min retrieved_at date), import-day or none
con.execute(f"""create table bdates as select body_key, min(retrieved_at) ra, min(capture_date) cd from {cap} where body_key is not null group by 1""")
print("--- list with first_captured")
lst = con.execute(f"""
select d.filename, d.document_kind[1] document_kind, d.document_family[1] document_family, d.committee_code[1] committee_code,
       try_cast(d.congress[1] as smallint) congress, d.record_role[1] record_role, d.extension[1] ext,
       case when b.ra is not null then substr(b.ra,1,10) when b.cd = '2026-09-29' then '2026-09-29' else null end first_captured,
       case when b.ra is not null then 'captured' when b.cd = '2026-09-29' then 'import_day' else 'unknown' end date_kind
from {docs} d left join bdates b using(body_key)
order by d.filename, first_captured nulls last, d.document_id""").to_arrow_table()
print("   first_captured distinct:", pc.count_distinct(lst['first_captured']).as_py(), " date_kind:", con.execute("select date_kind, count(*) from (select case when b.ra is not null then 'captured' when b.cd='2026-09-29' then 'import_day' else 'unknown' end date_kind from " + docs + " d left join bdates b using(body_key)) group by 1").fetchall())
write(lst, "list_rev5_z3"); write(lst, "list_rev5_z9", compression_level=9)
write(lst.drop_columns(["first_captured","date_kind"]), "list_rev5_nodate_z3")

print("--- detail fold: all populated document fields as (field, value) pairs, 16 KB pages / 256-row batches")
schema = pq.ParquetFile(f"{base}/documents.parquet").schema_arrow
listcols = [f.name for f in schema if str(f.type) == "list<element: string>" and not f.name.startswith(("source_", "state_")) and f.name not in ("body_keys", "source_urls", "filenames", "filename_origins", "source_paths")]
print(f"   folding {len(listcols)} list<string> columns + scalars")
unions = " union all ".join(f"select rn, '{c}' fld, unnest({c}) val from d" for c in listcols)
con.execute(f"""create table d as select row_number() over (order by filename, document_id) - 1 rn, * from {docs}""")
fold = con.execute(f"""
with pairs as (
  select rn, 'source_url' fld, source_url val from d where source_url is not null
  union all select rn, 'saved_body' fld, body_key val from d where body_key is not null
  union all select rn, 'first_captured' fld, coalesce(substr(b.ra,1,10), b.cd) val from d left join bdates b using(body_key) where coalesce(b.ra, b.cd) is not null
  union all select rn, 'occ_range' fld, cast(rn as varchar) || ':' || cast(len(source_occurrences) as varchar) val from d
  union all {unions})
select rn, list(struct_pack(field := fld, value := val) order by fld, val) detail from pairs where val is not null group by rn order by rn""").to_arrow_table()
print(f"   fold rows={fold.num_rows:,} avg pairs/row={pc.sum(pc.list_value_length(fold['detail'])).as_py()/fold.num_rows:.1f} rss={rss():.0f}MB ({time.time()-t0:.0f}s)")
write(fold, "detail_fold_rev5_p16", data_page_size=16*1024, write_batch_size=256, row_group_size=65536)
write(fold, "detail_fold_rev5_p64", data_page_size=64*1024, write_batch_size=1024, row_group_size=65536)
del fold

print("--- links: 8-byte prefix of every body in body sets -> first list row")
links = con.execute(f"""
select unhex(substr(regexp_extract(k, '([0-9a-f]{{64}})', 1), 1, 16)) link_key, min(rn)::integer list_row
from d, unnest(body_keys) as t(k) where k is not null group by 1 order by 1""").to_arrow_table()
links = links.set_column(0, "link_key", links["link_key"].cast(pa.binary(8)))
print(f"   links rows={links.num_rows:,} (all bodies in body sets; real-file filter would shrink it)")
write(links, "links_rev5_p16", data_page_size=16*1024, write_batch_size=512, row_group_size=1<<20)

print("--- url_state with binary sha")
us = con.execute(f"""
select context_url url, count(*)::integer attempts, max(retrieved_at) last_attempt, arg_max(http_status, coalesce(retrieved_at,''))::smallint last_status,
       arg_max(resolution, coalesce(retrieved_at,'')) last_resolution, unhex(arg_max(sha256, coalesce(retrieved_at,''))) last_sha
from {cap} where context_url is not null group by 1 order by 1""").to_arrow_table()
write(us, "url_state_rev5")

print("--- lake fold estimates")
# readings today, folded
rd = con.execute(f"""
with r as (select * from read_parquet('{base}/readings/*.parquet', union_by_name=true)),
pairs as (select body_key, parser_fingerprint, status, 'record_role' f, unnest(record_role) v from r
  union all select body_key, parser_fingerprint, status, 'content_document_kind', unnest(content_document_kind) from r
  union all select body_key, parser_fingerprint, status, 'content_congress', unnest(content_congress) from r
  union all select body_key, parser_fingerprint, status, 'content_citation', unnest(content_citation) from r
  union all select body_key, parser_fingerprint, status, 'source_record_type', unnest(source_record_type) from r
  union all select body_key, parser_fingerprint, status, 'source_record_identifier', unnest(source_record_identifier) from r
  union all select body_key, parser_fingerprint, status, 'body_format', unnest(body_format) from r
  union all select body_key, parser_fingerprint, status, 'content_xml_root', unnest(content_xml_root) from r)
select unhex(regexp_extract(body_key, '([0-9a-f]{{64}})', 1)) body_sha, any_value(parser_fingerprint) parser_version, any_value(status) status,
       list(struct_pack(field := f, value := v) order by f, v) fields
from pairs group by body_key order by body_sha""").to_arrow_table()
rd = rd.set_column(0, "body_sha", rd["body_sha"].cast(pa.binary(32)))
write(rd, "readings_fold_today", row_group_size=65536)

# filename_readings: fold house-naming fields from a 200k sample of filenames.parquet, extrapolate to 1.39M pairs
fschema = pq.ParquetFile(f"{base}/filenames.parquet").schema_arrow
hn = [f.name for f in fschema if str(f.type) == "list<element: string>" and not f.name.startswith(("source_", "state_", "content_", "response_", "hearing_", "body_", "member_bioguide")) and f.name not in ("filename_origins","source_paths","media_type","http_status","capture_outcome","record_role","document_kind_source","filename_document_kind","cache_marker_state")]
print(f"   house-naming-like columns: {len(hn)}")
funions = " union all ".join(f"select rn, '{c}' fld, unnest({c}) val from s" for c in hn)
con.execute(f"create table s as select row_number() over () rn, * from read_parquet('{base}/filenames.parquet') using sample 200000 rows (reservoir, 7)")
fr = con.execute(f"""
with pairs as ({funions})
select rn, any_value(s.filename) filename, any_value(s.source_url) source_url, list(struct_pack(field := fld, value := val) order by fld, val) fields
from pairs join s using(rn) where val is not null group by rn order by filename, source_url""").to_arrow_table()
sz = write(fr, "filename_readings_fold_sample200k", row_group_size=65536)
print(f"   avg pairs/row={pc.sum(pc.list_value_length(fr['fields'])).as_py()/fr.num_rows:.1f}; extrapolated to 1,392,681 pairs: {sz/fr.num_rows*1392681/2**20:.0f} MB")
print(f"peak rss={rss():.0f}MB total {time.time()-t0:.0f}s")
