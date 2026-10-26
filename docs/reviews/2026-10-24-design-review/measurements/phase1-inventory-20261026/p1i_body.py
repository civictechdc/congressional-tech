import duckdb
con=duckdb.connect('/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/phase1-inventory/p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
C='/Users/mikewolfd/Work/congressional-tech/.cache/nara-filename-estimate-20261015/publication-all-20261015/'
V=C+'current-viewer/2afcc0bcc9e2441c8592bde89eae4113/viewer-v2/filenames.parquet'
q=lambda s: con.execute(s).fetchall()
con.execute(f"""create or replace table idx as select body_key, any_value(sha256) sha256, max(bytes) bytes, max(stored_bytes) stored_bytes,
  list_distinct(list(lower(split_part(media_type,';',1)))) media, list_distinct(list(resolution)) res, list_distinct(list(family)) fam,
  list_distinct(list(fidelity)) fid, count(*) nrows
  from read_parquet('{C}new-captures.parquet') where body_key is not null group by 1""")
con.execute(f"""create or replace table vb as select body_key, list_sort(list_distinct(flatten(list(coalesce(body_format,[]))))) bf,
  list_sort(list_distinct(flatten(list(coalesce(format,[]))))) fmt, list_sort(list_distinct(flatten(list(coalesce(response_format,[]))))) rf,
  list_sort(list_distinct(flatten(list(coalesce(record_role,[]))))) rr
  from read_parquet('{V}') where body_key is not null group by 1""")
print(q("select count(*), count(vb.body_key) from idx left join vb using(body_key)"))
print("bodies by old bf (all idx bodies)", q("select vb.bf, count(*), sum(idx.bytes)/1e9 from idx left join vb using(body_key) group by 1 order by 2 desc"))
print("media top for no-bf", q("select media[1], count(*) from idx left join vb using(body_key) where vb.bf is null or len(vb.bf)=0 group by 1 order by 2 desc limit 15"))
