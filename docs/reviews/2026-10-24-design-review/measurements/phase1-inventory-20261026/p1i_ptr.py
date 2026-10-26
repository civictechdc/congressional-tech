import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/captures.parquet'
con=duckdb.connect('p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
con.execute(f"create or replace table pp as select body_key, resolution, regexp_replace(pointer_json,'[0-9]+','N','g') ptr, regexp_extract(receipt_key, '/(\\d{{4}}-\\d{{2}}-\\d{{2}})/', 1) rdate from read_parquet('{A}') where body_key in (select body_key from pdfc)")
print(q("select ptr, resolution, count(*), count(distinct body_key) from pp group by 1,2 order by 3 desc limit 15"))
print("pdf bodies with saved on final-content pointer", q("""select count(distinct body_key) from pp where resolution='saved' and rdate>='2026-10-01' and ptr not like '%prior%' and ptr not like '%attempt%'"""))
