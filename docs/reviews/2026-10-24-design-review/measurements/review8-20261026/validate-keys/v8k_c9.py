import duckdb,pyarrow.parquet as pq,pyarrow as pa,os,sys
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
O=sys.argv[1]; c=duckdb.connect()
t=c.sql(f"""select filename,
  list_sort(source_link_label)[1] link_label,
  list_sort(source_page_title)[1] page_title,
  list_sort(source_meeting_title)[1] meeting_title,
  coalesce(list_sort(source_link_label)[1], filename) label_or_filename
  from '{I}/documents.parquet' order by filename""").fetch_arrow_table()
n=t.num_rows; print('rows',n)
for col in t.column_names:
    a=t.column(col); vals=[v for v in a.to_pylist() if v is not None]
    chars=sum(len(v) for v in vals); utf8=sum(len(v.encode()) for v in vals)
    p=os.path.join(O,f'v8k_{col}.parquet')
    pq.write_table(pa.table({col:a}),p,compression='zstd',use_dictionary=False,row_group_size=65536,data_page_version='2.0')
    sz=os.path.getsize(p)
    # V8 heap: sequential string header ~16B (pointer-compressed 12B) + 1B/char one-byte or 2B/char two-byte; plus array slot 4-8B
    twobyte=sum(1 for v in vals if any(ord(ch)>255 for ch in v))
    heap=sum(16+ (2*len(v) if any(ord(ch)>255 for ch in v) else len(v)) for v in vals)+8*n
    print(f"{col:18s} nonnull={len(vals):7d} distinct={len(set(vals)):7d} avgchars={chars/max(1,len(vals)):6.1f} utf8MB={utf8/1e6:6.2f} parquetMB={sz/1e6:5.2f} twobyte={twobyte} heapMB~{heap/1e6:5.1f}")
