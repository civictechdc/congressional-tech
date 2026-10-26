"""F1: a 150-body random sample (hash order) of the HTML payloads in WARC lines, for role classification by vm7_classify.py."""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
con.execute(f"""COPY (SELECT sha, any_value(body_key) body_key, any_value(ctx) ctx FROM c
  WHERE (rk, rl) IN (SELECT rk, rl FROM c WHERE fmt='warc') AND fmt='html' AND NOT file_shaped GROUP BY 1 ORDER BY hash(sha) LIMIT 150) TO '{D}/vm7_f1_html_in.parquet'""")
print(con.execute(f"SELECT count(*) FROM '{D}/vm7_f1_html_in.parquet'").fetchall())
