import duckdb, json, sys
root, final = sys.argv[1], sys.argv[2]
con = duckdb.connect()
con.execute(f"""create view c as select *, regexp_extract(receipt_key, '/([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})/', 1) rdate from '{root}/captures.parquet'""")
con.execute(f"create view r as select regexp_extract(body_key, '([0-9a-f]{{64}})', 1) sha256, status, list_contains(body_format,'pdf') is_pdf from '{root}/readings/*.parquet'")
con.execute("create temp table k as select sha256, max(bytes) bytes from c where media_type ilike '%pdf%' group by 1")
con.execute("create temp table fin(sha256 varchar)")
con.executemany("insert into fin values (?)", [(s,) for s in json.load(open(final))])
con.execute("create temp table legacy as select distinct sha256 from r where status='completed' and is_pdf")
con.execute("create temp table u as select * from k where sha256 not in (select sha256 from fin) and sha256 not in (select sha256 from legacy)")
q = lambda l, s: print(l, con.execute(s).fetchall())
q("unchecked n, GB, p50 MB, p90 MB, max MB", "select count(*), round(sum(bytes)/1e9,1), round(quantile_cont(bytes,.5)/1e6,1), round(quantile_cont(bytes,.9)/1e6,1), round(max(bytes)/1e6) from u")
q("exactly 64 MiB (cut-off, not real files anyway)", "select count(*), round(sum(bytes)/1e9,1) from u where bytes = 67108864")
q("old reading status", "select coalesce(r.status,'(none)'), count(distinct u.sha256), round(sum(u.bytes)/1e9,1) from u left join r using (sha256) group by 1 order by 2 desc")
q("size bands", """select case when bytes < 1e6 then '<1MB' when bytes < 10e6 then '1-10MB' when bytes < 67108864 then '10MB-64MiB'
     when bytes = 67108864 then '=64MiB' else '>64MiB' end b, count(*), round(sum(bytes)/1e9,1) from u group by 1 order by 1""")
q("lines for unchecked: dated before 10-01 / undated / >=10-01 non-final", """select count(distinct sha256) filter (where rdate <> '' and rdate < '2026-10-01'),
     count(distinct sha256) filter (where rdate = ''), count(distinct sha256) filter (where rdate >= '2026-10-01')
     from c where sha256 in (select sha256 from u)""")
q("fidelity of unchecked", "select fidelity, count(distinct sha256) from c where sha256 in (select sha256 from u) group by 1 order by 2 desc")
q("CHECKED population: n, p50 MB, p90 MB, share > 10 MB", """select count(*), round(quantile_cont(bytes,.5)/1e6,2), round(quantile_cont(bytes,.9)/1e6,2),
     round(100.0*count(*) filter (where bytes > 10e6)/count(*),2) from k where sha256 not in (select sha256 from u)""")
q("unchecked excluding the 950 HTML: n, GB, share > 10 MB", """select count(*), round(sum(bytes)/1e9,1), round(100.0*count(*) filter (where bytes > 10e6)/count(*),1)
     from u where sha256 not in (select sha256 from r where status='completed')""")
q("invalid_document rate among final-checked", "select 45.0/228969")
