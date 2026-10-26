import duckdb
con = duckdb.connect(); con.execute("SET threads=4")
L="read_csv('/Users/mikewolfd/Work/congressional-tech/output/r2-survey-20261019/congressional-tech-raw-objects.csv.gz', header=true, columns={'key':'VARCHAR','bytes':'BIGINT','last_modified_utc':'VARCHAR'})"
con.execute(f"create table l as select * from {L}")
q=lambda s: con.execute(s).fetchall()
print(q("select split_part(key,'/',1) p, count(*), sum(bytes)/1e9 from l group by 1 order by 2 desc"))
print(q("select regexp_extract(key,'(\\.[a-z]+)$',1), count(*), sum(bytes)/1e9 from l where key like 'bodies/%' group by 1"))
print(q("select max(last_modified_utc), count(*) filter (where last_modified_utc >= '2026-10-15') from l where key like 'bodies/%'"))
caps="read_parquet('/Users/mikewolfd/Work/congressional-tech/.cache/nara-filename-estimate-20261015/publication-all-20261015/new-captures.parquet')"
con.execute(f"create table b as select distinct body_key, sha256, stored_bytes from {caps} where body_key is not null")
print("idx bodies", q("select count(*), count(distinct body_key) from b"))
print("idx bodies in listing", q("select count(*), count(*) filter (where l.bytes = b.stored_bytes) from b join l on l.key=b.body_key"))
print("listing bodies not in idx", q("select count(*), sum(l.bytes)/1e9 from l where key like 'bodies/%' and key not in (select body_key from b)"))
