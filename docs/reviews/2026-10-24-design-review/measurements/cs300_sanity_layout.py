"""Layout checks: delta-encoded filename column; list with meeting ids; typed detail core bytes per view."""
import os, time, binascii, duckdb, pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/cs300/files"
os.makedirs(out, exist_ok=True)
con = duckdb.connect(); con.execute("SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false;")
docs = f"read_parquet('{base}/documents.parquet')"; cap = f"read_parquet('{base}/captures.parquet')"

def measure(tbl, name, page_kb=64, batch=1024, rg=65536, **kw):
    p = f"{out}/{name}.parquet"
    opts = dict(compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True, write_statistics=True,
                write_page_index=True, data_page_size=page_kb*1024, write_batch_size=batch, row_group_size=rg); opts.update(kw)
    if "column_encoding" in opts and opts.get("use_dictionary") is True:
        opts["use_dictionary"] = [c for c in tbl.column_names if c not in opts["column_encoding"]]
    pq.write_table(tbl, p, **opts)
    md = pq.read_metadata(p); size = os.path.getsize(p); comp, uncomp = {}, {}
    for r in range(md.num_row_groups):
        for c in range(md.row_group(r).num_columns):
            col = md.row_group(r).column(c)
            comp[col.path_in_schema] = comp.get(col.path_in_schema, 0) + col.total_compressed_size
            uncomp[col.path_in_schema] = uncomp.get(col.path_in_schema, 0) + col.total_uncompressed_size
    per_view = sum(comp[k] / max(1, -(-uncomp[k] // (page_kb*1024))) for k in comp)
    print(f"  {name:28s} {size/2**20:6.2f} MB rows={md.num_rows:,} leaves={len(comp)} est.bytes/view={per_view/1024:6.1f} KB  " + " ".join(f"{k.split('.')[0]}={v/2**20:.2f}" for k,v in comp.items()))
    return size

if False:
  print("--- A. filename column: dictionary vs DELTA_BYTE_ARRAY (DM §4: 2.54 vs 3.22 MB on 1.13M sorted filenames)")
  fnames = con.execute(f"select filename from {docs} where filename is not null order by filename, document_id").to_arrow_table()
  print("   non-null filenames:", fnames.num_rows)
  measure(fnames, "fn_dict", page_kb=1024, batch=4096)
  measure(fnames, "fn_delta", page_kb=1024, batch=4096, use_dictionary=False, column_encoding={"filename": "DELTA_BYTE_ARRAY"})
  half = fnames.slice(0, 500000)
  measure(half, "fn_dict_500k", page_kb=1024, batch=4096); measure(half, "fn_delta_500k", page_kb=1024, batch=4096, use_dictionary=False, column_encoding={"filename": "DELTA_BYTE_ARRAY"})

print("--- B. list with meeting ids, document date, saved_kind (DM §4: about 1.5 MB at 0.5M; meeting_event_ids about 1 MB)")
lst = con.execute(f"""
with d as (select *, row_number() over (order by filename, document_id) rn from {docs}),
     m as (select document_id, list(distinct cast(id as bigint)) ids from (
             select document_id, regexp_extract(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{{2}}/[A-Za-z0-9]+/\\d{{8}}/(\\d+)', 1) id from d, unnest(source_urls) t(su) where regexp_matches(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{{2}}/[A-Za-z0-9]+/\\d{{8}}/\\d+')
             union all
             select document_id, regexp_extract(su, 'congress\\.gov/\\d+/meeting/(house|senate|joint)/(\\d+)', 2) from d, unnest(source_urls) t(su) where regexp_matches(su, 'congress\\.gov/\\d+/meeting/(house|senate|joint)/\\d+')) group by 1),
     b as (select body_key, min(retrieved_at) ra from {cap} where body_key is not null group by 1)
select d.filename, d.document_kind[1] document_kind, d.document_family[1] document_family, d.committee_code[1] committee_name, try_cast(d.congress[1] as smallint) congress,
       d.media_type[1] fmt, try_cast(d.meeting_date[1] as date) document_date, try_cast(substr(b.ra,1,10) as date) first_captured,
       case when b.ra is not null then 'captured' else 'unknown' end date_kind, 'original' saved_kind, coalesce(m.ids, []) meeting_event_ids
from d left join m using(document_id) left join b using(body_key) order by d.filename, first_captured nulls last, d.document_id""").to_arrow_table()
print("   docs with meeting ids:", pc.sum(pc.greater(pc.list_value_length(lst["meeting_event_ids"]), 0)).as_py())
measure(lst, "list_rev7_delta", page_kb=1024, batch=4096, column_encoding={"filename": "DELTA_BYTE_ARRAY"})
import random; random.seed(1)
idx = sorted(random.sample(range(lst.num_rows), 500000))
sub = lst.take(pa.array(idx))
measure(sub, "list_rev7_delta_500k", page_kb=1024, batch=4096, column_encoding={"filename": "DELTA_BYTE_ARRAY"})
measure(sub.drop_columns(["meeting_event_ids"]), "list_rev7_500k_nomeet", page_kb=1024, batch=4096, column_encoding={"filename": "DELTA_BYTE_ARRAY"})

print("--- C. detail typed core (DM §4) bytes per view at 64 KB and 16 KB pages (fold excluded; fold measured 11-43 KB)")
core = con.execute(f"""
with d as (select *, row_number() over (order by filename, document_id) - 1 rn from {docs}),
     m as (select document_id, list(struct_pack(chamber := 'house', event_id := cast(id as bigint))) refs from (
             select distinct document_id, regexp_extract(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{{2}}/[A-Za-z0-9]+/\\d{{8}}/(\\d+)', 1) id from d, unnest(source_urls) t(su) where regexp_matches(su, 'docs\\.house\\.gov/meetings/[A-Za-z]{{2}}/[A-Za-z0-9]+/\\d{{8}}/\\d+')) group by 1)
select unhex(d.document_id) document_id, unhex(substr(regexp_extract(d.body_key, '([0-9a-f]{{64}})', 1), 1, 16)) link_key, d.body_key saved_key,
       cast(d.rn as integer) occ_start, cast(len(d.source_occurrences) as integer) occ_len,
       []::struct(kind varchar, key varchar, imported_at date)[] recoveries,
       []::struct(format varchar, key varchar, size bigint)[] alternates,
       coalesce(m.refs, []) meeting_refs,
       regexp_extract(d.source_url, 'govinfo\\.gov/content/pkg/([A-Za-z0-9._-]+)', 1) govinfo_package_id,
       coalesce(d.measure_references, []) measure_keys, coalesce(d.bioguide_token, []) bioguide_ids
from d left join m using(document_id) order by d.rn""").to_arrow_table()
core = core.set_column(0, "document_id", core["document_id"].cast(pa.binary(32))).set_column(1, "link_key", core["link_key"].cast(pa.binary(8)))
measure(core, "detail_core_p64", page_kb=64, batch=1024)
measure(core, "detail_core_p16", page_kb=16, batch=256)
measure(core.drop_columns(["document_id"]), "detail_core_p64_noid", page_kb=64, batch=1024)
