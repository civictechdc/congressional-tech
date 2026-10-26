import duckdb,pyarrow.parquet as pq,pyarrow as pa,os,sys
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
c=duckdb.connect()
print(c.sql(f"""select count(*) filter (where len(source_document_label)>0) dl, count(*) filter (where len(source_link_label)>0) ll, count(*) filter (where len(source_page_title)>0) pt,
 count(*) filter (where len(source_document_label)>0 or len(source_link_label)>0) anylabel from '{I}/documents.parquet'""").fetchall())
t=c.sql(f"""select coalesce(list_sort(source_document_label)[1], list_sort(source_link_label)[1]) lbl from '{I}/documents.parquet' order by all""").fetch_arrow_table()
vals=[v for v in t.column(0).to_pylist() if v]
print('nonnull',len(vals),'avg chars',sum(map(len,vals))/len(vals),'distinct',len(set(vals)))
p=sys.argv[1]+'/v8k_label.parquet'; pq.write_table(t,p,compression='zstd',use_dictionary=False,row_group_size=65536); print('parquet MB',os.path.getsize(p)/1e6)
heap=sum(16+(2 if any(ord(ch)>255 for ch in v) else 1)*len(v) for v in vals)+8*t.num_rows
print('heap MB',heap/1e6, 'scaled to 0.65M rows', heap/1e6*650000/t.num_rows)
print(c.sql(f"select lbl, count(*) from (select coalesce(list_sort(source_document_label)[1], list_sort(source_link_label)[1]) lbl from '{I}/documents.parquet') where lbl is not null group by 1 order by 2 desc limit 8").fetchall())
