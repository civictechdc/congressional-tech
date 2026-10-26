import duckdb
con=duckdb.connect('p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
con.execute("create or replace table pdfc as select body_key from j where list_contains(media,'application/pdf') or list_contains(bf,'pdf')")
print(q("""select regexp_extract(receipt_key,'receipts/([^/]+/?[^/]*)/',1) fam, fidelity, count(*), count(distinct body_key)
 from pc where resolution='saved' and body_key in (select body_key from pdfc) group by 1,2 order by 3 desc limit 15"""))
print("html bf but saved pdf media", q("select count(*) from j where list_contains(bf,'html') and list_contains(media,'application/pdf') and saved_new"))
print("non-pdf saved", q("select count(*) from j where saved_new and not (list_contains(media,'application/pdf') or list_contains(bf,'pdf'))"))
