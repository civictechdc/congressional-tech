import duckdb
con=duckdb.connect('p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
con.execute("""create or replace table rb as select body_key, any_value(body_format) bf, any_value(status) st, count(*) n from rd group by 1""")
con.execute("create or replace table j as select pb.*, rb.bf, rb.st from pb left join rb using(body_key)")
print("reading coverage", q("select count(*), count(st), count(*) filter (where st='completed'), count(bf) from j"))
print("bf x status", q("select bf, st, count(*), round(sum(stored_bytes)/1e9,1) from j group by 1,2 order by 3 desc limit 20"))
print("pdf cand", q("""select count(*), round(sum(stored_bytes)/1e9,1), count(*) filter (where list_contains(bf,'pdf')),
  count(*) filter (where saved_new), count(*) filter (where saved_any), count(*) filter (where list_contains(res,'invalid_document')),
  count(*) filter (where not coalesce(saved_new,false) and not list_contains(coalesce(bf,[]),'pdf'))
  from j where list_contains(media,'application/pdf') or list_contains(bf,'pdf')"""))
print("pdf cand no bf by status", q("select st, count(*), round(sum(stored_bytes)/1e9,1), round(avg(bytes)/1e6,2) from j where list_contains(media,'application/pdf') and not list_contains(coalesce(bf,[]),'pdf') group by 1 order by 2 desc"))
