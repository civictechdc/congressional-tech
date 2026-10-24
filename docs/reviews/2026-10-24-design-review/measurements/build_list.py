"""Build candidate browser files from documents.parquet and measure bytes.
Variants: list (with id as hex64 / bin32 / bin8 / no id), ids, and detail page-size trade-off."""
import os, sys, time, resource
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
import duckdb

base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
out = "/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/browser-files"
os.makedirs(out, exist_ok=True)
con = duckdb.connect(); con.execute("SET memory_limit='6GB'; SET threads=4;")

t0 = time.time()
# first element of list columns; congress as int; date = meeting_date else date_token
tbl = con.execute(f"""
select filename, document_id,
       document_kind[1] as document_kind, document_family[1] as document_family,
       committee_code[1] as committee_code, try_cast(congress[1] as smallint) as congress,
       record_role[1] as record_role, coalesce(meeting_date[1], date_token[1]) as date_text,
       extension[1] as extension
from read_parquet('{base}/documents.parquet')
order by filename, document_id
""").fetch_arrow_table()
print(f"documents rows={tbl.num_rows:,} loaded+sorted in {time.time()-t0:.1f}s; maxrss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20:.0f} MB")
for name in ["document_kind","document_family","committee_code","record_role","congress","extension"]:
    print(f"  distinct {name}: {pc.count_distinct(tbl[name]).as_py():,}  nulls: {tbl[name].null_count:,}")
print(f"  distinct filename: {pc.count_distinct(tbl['filename']).as_py():,}; distinct date_text: {pc.count_distinct(tbl['date_text']).as_py():,}")

ids_hex = tbl["document_id"]
# are they 64-hex?
lens = pc.utf8_length(ids_hex)
print(f"  document_id length min={pc.min(lens).as_py()} max={pc.max(lens).as_py()}; sample={ids_hex[0].as_py()}")
import binascii
hexlist = ids_hex.to_pylist()
bin32 = pa.array([binascii.unhexlify(h) if h and len(h)==64 else None for h in hexlist], pa.binary(32))
bin8 = pa.array([binascii.unhexlify(h[:16]) if h and len(h)>=16 else None for h in hexlist], pa.binary(8))
# collision check for 8-byte prefix
print(f"  8-byte prefix collisions: {len(hexlist) - pc.count_distinct(bin8).as_py()}")

def write(table, path, **kw):
    opts = dict(compression="zstd", compression_level=3, data_page_version="2.0", use_dictionary=True,
                write_statistics=True, write_page_index=True, row_group_size=131072)
    opts.update(kw)
    pq.write_table(table, path, **opts)
    size = os.path.getsize(path)
    md = pq.read_metadata(path)
    # footer size: serialized metadata length is the file length minus the data; approximate via file footer length field
    with open(path, "rb") as fh:
        fh.seek(-8, 2); footer_len = int.from_bytes(fh.read(4), "little")
    cols = {}
    for rg in range(md.num_row_groups):
        for c in range(md.row_group(rg).num_columns):
            col = md.row_group(rg).column(c)
            cols[col.path_in_schema] = cols.get(col.path_in_schema, 0) + col.total_compressed_size
    return size, footer_len, md, cols

base_cols = ["filename","document_kind","document_family","committee_code","congress","record_role","date_text","extension"]
facets = tbl.select(base_cols)
variants = {
    "list_hex64": facets.append_column("document_id", ids_hex),
    "list_bin32": facets.append_column("document_id", bin32),
    "list_bin8":  facets.append_column("document_id", bin8),
    "list_noid":  facets,
    "list_min_noid": tbl.select(["filename","document_kind","document_family","committee_code","congress","date_text"]),
}
for name, t in variants.items():
    for lvl in (3, 9):
        p = os.path.join(out, f"{name}_z{lvl}.parquet")
        size, flen, md, cols = write(t, p, compression_level=lvl)
        print(f"{name:14s} zstd{lvl}: {size/2**20:7.2f} MB  footer={flen/1024:6.1f} KB  rgs={md.num_row_groups}  " + " ".join(f"{k}={v/2**20:.2f}" for k,v in cols.items()))

# ids file: sorted by id -> (id, list_row)
rows = pa.array(range(tbl.num_rows), pa.int32())
for name, idcol in (("ids_bin32", bin32), ("ids_bin8", bin8), ("ids_hex64", ids_hex)):
    t = pa.table({"id": idcol, "list_row": rows})
    idx = pc.sort_indices(t, sort_keys=[("id","ascending")])
    t = t.take(idx)
    for page_kb in (64, 256):
        p = os.path.join(out, f"{name}_p{page_kb}.parquet")
        size, flen, md, cols = write(t, p, data_page_size=page_kb*1024, row_group_size=1<<20)
        # count pages via page index
        print(f"{name:10s} page={page_kb}KB: {size/2**20:6.2f} MB footer={flen/1024:6.1f} KB rgs={md.num_row_groups}")

# detail-like file: identifiers + urls + body hash (same row order as list)
t1 = time.time()
det = con.execute(f"""
select filename, document_id, source_id, body_key, source_url,
       body_keys, source_urls, filenames
from read_parquet('{base}/documents.parquet') order by filename, document_id
""").fetch_arrow_table()
print(f"detail cols loaded in {time.time()-t1:.1f}s; maxrss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20:.0f} MB")
for page_kb in (64, 256, 1024):
    p = os.path.join(out, f"detail_p{page_kb}.parquet")
    size, flen, md, cols = write(det, p, data_page_size=page_kb*1024, row_group_size=1<<20)
    # measure page sizes from the offset index of column 0 in row group 0
    pf = pq.ParquetFile(p)
    print(f"detail page={page_kb}KB: {size/2**20:7.2f} MB footer={flen/1024:7.1f} KB rgs={md.num_row_groups} cols=" + " ".join(f"{k}={v/2**20:.1f}" for k,v in cols.items()))
print(f"peak maxrss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20:.0f} MB total {time.time()-t0:.1f}s")
