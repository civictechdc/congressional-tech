"""Folded detail / links / url_state / lake folds, streamed in batches (bounded memory)."""
import os, time, resource, duckdb, pyarrow as pa, pyarrow.parquet as pq
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/cs300/files"
os.makedirs(out + "/tmp", exist_ok=True)
con = duckdb.connect(); con.execute(f"SET memory_limit='10GB'; SET threads=4; SET temp_directory='{out}/tmp'; SET max_temp_directory_size='30GiB'; SET preserve_insertion_order=true;")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20
docs = f"read_parquet('{base}/documents.parquet')"; cap = f"read_parquet('{base}/captures.parquet')"

def stream_write(sql, name, page_kb=64, batch_rows=1024, rg_rows=65536, cast=None):
    p = f"{out}/{name}.parquet"; t = time.time()
    reader = con.execute(sql).fetch_record_batch(rg_rows)
    writer = None; n = 0
    for batch in reader:
        tbl = pa.Table.from_batches([batch])
        if cast: tbl = cast(tbl)
        if writer is None:
            writer = pq.ParquetWriter(p, tbl.schema, compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True,
                                      write_statistics=True, write_page_index=True, data_page_size=page_kb*1024, write_batch_size=batch_rows)
        writer.write_table(tbl, row_group_size=rg_rows); n += tbl.num_rows
    writer.close()
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
    pidx = (size - 8 - flen) - data_end
    per_view = sum(comp[k] / max(1, -(-uncomp[k] // (page_kb*1024))) for k in comp)
    print(f"  {name:26s} {size/2**20:7.1f} MB rows={n:,} rgs={md.num_row_groups} leaves={len(comp)} footer={flen/1024:.0f} KB page_indexes={pidx/1024:.0f} KB est.bytes/view={per_view/1024:.1f} KB ({time.time()-t:.0f}s, rss {rss():.0f} MB)")
    print("     leaves:", {k: f"{v/2**20:.1f}MB" for k, v in comp.items()})
    return size, n

t0 = time.time()
con.execute(f"create table bdates as select body_key, min(retrieved_at) ra, min(capture_date) cd from {cap} where body_key is not null group by 1")
schema = pq.ParquetFile(f"{base}/documents.parquet").schema_arrow
listcols = [f.name for f in schema if str(f.type) == "list<element: string>" and not f.name.startswith(("source_", "state_")) and f.name not in ("body_keys", "source_urls", "filenames", "filename_origins", "source_paths")]
print(f"--- detail fold over {len(listcols)} list<string> columns + scalars (flatten, streamed)")
parts = [f"list_transform(coalesce(d.{c}, []), x -> struct_pack(field := '{c}', value := x))" for c in listcols]
parts += ["case when d.source_url is null then [] else [struct_pack(field := 'source_url', value := d.source_url)] end",
          "case when d.body_key is null then [] else [struct_pack(field := 'saved_body', value := d.body_key)] end",
          "case when coalesce(b.ra, b.cd) is null then [] else [struct_pack(field := 'first_captured', value := coalesce(substr(b.ra,1,10), b.cd))] end",
          "[struct_pack(field := 'occ_range', value := cast(d.rn as varchar) || ':' || cast(len(d.source_occurrences) as varchar))]"]
con.execute(f"create table d as select row_number() over (order by filename, document_id) - 1 rn, * from {docs}")
sql = f"select d.rn, flatten([{', '.join(parts)}]) detail from d left join bdates b using(body_key) order by d.rn"
stream_write(sql, "detail_fold_rev5_p16", page_kb=16, batch_rows=256)
stream_write(sql, "detail_fold_rev5_p64", page_kb=64, batch_rows=1024)
print("   avg pairs per row:", con.execute(f"select avg(len(flatten([{', '.join(parts)}]))) from d left join bdates b using(body_key)").fetchone()[0])

print("--- links: 8-byte prefix of every body in body sets -> first list row")
def cast_links(t): return t.set_column(0, "link_key", t["link_key"].cast(pa.binary(8)))
stream_write(f"""select unhex(substr(regexp_extract(k, '([0-9a-f]{{64}})', 1), 1, 16)) link_key, min(rn)::integer list_row
                 from d, unnest(body_keys) as t(k) where k is not null group by 1 order by 1""", "links_rev5_p16", page_kb=16, batch_rows=512, rg_rows=1<<20, cast=cast_links)

print("--- url_state with binary sha")
stream_write(f"""select context_url url, count(*)::integer attempts, max(retrieved_at) last_attempt, arg_max(http_status, coalesce(retrieved_at,''))::smallint last_status,
                 arg_max(resolution, coalesce(retrieved_at,'')) last_resolution, unhex(arg_max(sha256, coalesce(retrieved_at,''))) last_sha
                 from {cap} where context_url is not null group by 1 order by 1""", "url_state_rev5", page_kb=1024, batch_rows=4096, rg_rows=131072)

print("--- readings today, folded")
rcols = ["record_role","content_document_kind","content_congress","content_citation","source_record_type","source_record_identifier","body_format","content_xml_root","content_legis_num","content_amendment_type","attempted_url","cache_marker_state"]
rparts = [f"list_transform(coalesce(r.{c}, []), x -> struct_pack(field := '{c}', value := x))" for c in rcols]
def cast_rd(t): return t.set_column(0, "body_sha", t["body_sha"].cast(pa.binary(32)))
stream_write(f"""select unhex(regexp_extract(r.body_key, '([0-9a-f]{{64}})', 1)) body_sha, r.parser_fingerprint parser_version, r.status, flatten([{', '.join(rparts)}]) fields
                 from read_parquet('{base}/readings/*.parquet', union_by_name=true) r order by 1""", "readings_fold_today", page_kb=1024, batch_rows=4096, rg_rows=65536, cast=cast_rd)

print("--- filename_readings fold: house-naming-like columns, 200k-row sample, extrapolated")
fschema = pq.ParquetFile(f"{base}/filenames.parquet").schema_arrow
hn = [f.name for f in fschema if str(f.type) == "list<element: string>" and not f.name.startswith(("source_", "state_", "content_", "response_", "hearing_", "body_", "member_bioguide")) and f.name not in ("filename_origins","source_paths","media_type","http_status","capture_outcome","record_role","document_kind_source","filename_document_kind","cache_marker_state")]
print(f"   house-naming-like columns: {len(hn)}")
fparts = [f"list_transform(coalesce(s.{c}, []), x -> struct_pack(field := '{c}', value := x))" for c in hn]
con.execute(f"create table s as select * from read_parquet('{base}/filenames.parquet') using sample 200000 rows (reservoir, 7)")
sz, n = stream_write(f"select s.filename, s.source_url, flatten([{', '.join(fparts)}]) fields from s order by filename, source_url", "filename_readings_fold_sample200k", page_kb=1024, batch_rows=4096, rg_rows=65536)
print(f"   avg pairs/row: {con.execute(f'select avg(len(flatten([{", ".join(fparts)}]))) from s').fetchone()[0]:.1f}; extrapolated to 1,392,681 pairs: {sz/n*1392681/2**20:.0f} MB")
print(f"peak rss={rss():.0f}MB total {time.time()-t0:.0f}s")
