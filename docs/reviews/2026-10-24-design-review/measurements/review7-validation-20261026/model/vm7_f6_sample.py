"""F6: 60 random pairs from the 2,250 one-line page-version endpoints: the prior attempt's body and the final body, for vm7_classify.py."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
con.execute(f"""COPY (WITH e AS (SELECT ctx FROM real WHERE fmt='html' AND mem IS NULL GROUP BY 1 HAVING count(DISTINCT sha)>=2 AND count(DISTINCT (rk,rl))=1 ORDER BY hash(ctx) LIMIT 60)
  SELECT DISTINCT r.sha, r.body_key, r.ctx || CASE WHEN r.is_prior THEN '#prior' ELSE '#final' END ctx FROM real r JOIN e USING (ctx) WHERE r.fmt='html') TO '{D}/vm7_f6_html_in.parquet'""")
print(con.execute(f"SELECT count(*) FROM '{D}/vm7_f6_html_in.parquet'").fetchall())
