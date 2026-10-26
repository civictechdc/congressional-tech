import duckdb, json, sys
root, final = sys.argv[1], sys.argv[2]
con = duckdb.connect()
con.execute(f"create view c as select * from '{root}/captures.parquet'")
con.execute(f"create view r as select regexp_extract(body_key, '([0-9a-f]{{64}})', 1) sha256, status, list_contains(body_format,'pdf') is_pdf from '{root}/readings/*.parquet'")
con.execute("create temp table k as select sha256, max(bytes) bytes from c where media_type ilike '%pdf%' group by 1")
con.execute("create temp table fin(sha256 varchar)")
con.executemany("insert into fin values (?)", [(s,) for s in json.load(open(final))])
con.execute("create temp table legacy as select distinct sha256 from r where status='completed' and is_pdf")
print(con.execute("""select count(*), count(*) filter (where sha256 in (select sha256 from fin)),
   count(*) filter (where sha256 in (select sha256 from legacy) and sha256 not in (select sha256 from fin)),
   count(*) filter (where sha256 in (select sha256 from legacy) and sha256 in (select sha256 from fin)),
   count(*) filter (where sha256 not in (select sha256 from fin) and sha256 not in (select sha256 from legacy)),
   round(sum(bytes) filter (where sha256 not in (select sha256 from fin) and sha256 not in (select sha256 from legacy))/1e9,1)
   from k""").fetchone(), "(cand, final-checked, legacy-only, both, unchecked, unchecked GB)")
