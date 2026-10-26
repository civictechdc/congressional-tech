"""F2 population: endpoints with >=2 distinct real bodies (no fingerprints yet, so an upper bound on ambiguity), WARC excluded
(F1's fix), by format set. Writes vm7_f2_html.parquet: HTML bodies at endpoints that also hold a real PDF."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
def q(l,s):
    rows=con.execute(s).fetchall(); print(f'\n## {l}')
    for r in rows[:30]: print('  ',r)
for nm,key in [('exact',"ctx || '|' || coalesce(mem,'')"),('ukey',"ukey || '|' || coalesce(mem,'')")]:
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ep_{nm} AS SELECT {key} k, any_value(ctx) ctx, any_value(mem) mem, count(DISTINCT sha) nb, list_sort(list_distinct(list(fmt))) fs
       FROM real WHERE fmt<>'warc' GROUP BY 1 HAVING count(DISTINCT sha)>=2""")
    q(f"[{nm}] endpoints with >=2 distinct real bodies, WARC excluded: by format set, member?", f"SELECT fs::VARCHAR, mem IS NOT NULL, count(*), sum(nb) FROM ep_{nm} GROUP BY ALL ORDER BY 3 DESC")
con.execute("""CREATE TEMP TABLE hp AS SELECT k, ctx FROM ep_exact WHERE list_contains(fs,'html') AND list_contains(fs,'pdf')""")
q("[exact] html+pdf endpoints: count, by format set, host", "SELECT regexp_extract(ctx,'^https?://([^/]+)',1) h, count(*) FROM hp GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
con.execute(f"""COPY (SELECT DISTINCT r.sha, r.body_key, r.ctx, r.mem FROM real r JOIN hp ON r.ctx || '|' || coalesce(r.mem,'') = hp.k WHERE r.fmt='html') TO '{D}/vm7_f2_html.parquet'""")
q("html bodies to classify", f"SELECT count(*), count(DISTINCT sha) FROM '{D}/vm7_f2_html.parquet'")
q("pdf bodies at those endpoints", "SELECT count(DISTINCT sha), round(sum(DISTINCT bytes)/1e9,2) FROM real r JOIN hp ON r.ctx || '|' || coalesce(r.mem,'') = hp.k WHERE r.fmt='pdf'")
q("example endpoints", "SELECT ctx[1:110] FROM hp USING SAMPLE 10")
