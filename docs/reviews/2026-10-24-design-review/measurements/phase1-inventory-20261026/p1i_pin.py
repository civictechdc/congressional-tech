import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
con=duckdb.connect('/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/phase1-inventory/p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
print(q(f"describe select * from read_parquet('{A}captures.parquet')"))
con.execute(f"""create or replace table pc as select body_key, sha256, bytes, stored_bytes, lower(split_part(media_type,';',1)) media, resolution, fidelity, reference_kind, family,
   regexp_extract(receipt_key, '/(\\d{{4}}-\\d{{2}}-\\d{{2}})/', 1) rdate, receipt_key, context_url from read_parquet('{A}captures.parquet')""")
print("rows", q("select count(*), count(body_key), count(distinct body_key), sum(case when body_key is null then 1 else 0 end) from pc"))
con.execute("""create or replace table pb as select body_key, any_value(sha256) sha256, max(bytes) bytes, max(stored_bytes) stored_bytes,
  list_distinct(list(media)) media, list_distinct(list(resolution)) res, list_distinct(list(fidelity)) fid,
  bool_or(resolution='saved' and rdate>='2026-10-01') saved_new, bool_or(resolution='saved') saved_any, min(rdate) mind
  from pc where body_key is not null group by 1""")
print("bodies", q("select count(*), sum(bytes)/1e9, sum(stored_bytes)/1e9 from pb"))
print("rdate null share", q("select count(*) filter (where rdate=''), count(*) from pc"))
