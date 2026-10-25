import duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB';")
R = f"read_parquet('{base}/readings/*.parquet', union_by_name=true)"
C = f"read_parquet('{base}/captures.parquet')"
def q(label, sql):
    r = con.execute(sql).fetchall()
    print(f"\n## {label}\n-> {r}")
q("readings: rows, distinct body_key, distinct parser_fingerprint, status distribution",
  f"SELECT count(*), count(DISTINCT body_key), count(DISTINCT parser_fingerprint) FROM {R}")
q("readings status", f"SELECT status, count(*) FROM {R} GROUP BY 1 ORDER BY 2 DESC")
q("record_role distribution", f"SELECT r, count(*) FROM (SELECT unnest(record_role) r FROM {R}) GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
q("body_format distribution", f"SELECT f, count(*) FROM (SELECT unnest(body_format) f FROM {R}) GROUP BY 1 ORDER BY 2 DESC LIMIT 14")
q("content_xml_root top", f"SELECT x, count(*) FROM (SELECT unnest(content_xml_root) x FROM {R}) GROUP BY 1 ORDER BY 2 DESC LIMIT 10")
q("null retrieved_at by receipt shape",
  f"""SELECT CASE WHEN receipt_key LIKE '%/undated/%' THEN 'undated' WHEN receipt_key LIKE '%/mixed-dates/%' THEN 'mixed' ELSE 'dated' END shape,
      count(*) rows_, count(*) FILTER (WHERE retrieved_at IS NULL) null_retrieved, count(*) FILTER (WHERE http_status IS NULL) null_status, count(*) FILTER (WHERE sha256 IS NULL) bodiless FROM {C} GROUP BY 1""")
q("null retrieved_at among body rows (sha not null) by reference_kind",
  f"SELECT reference_kind, count(*), count(*) FILTER (WHERE retrieved_at IS NULL) FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
q("distinct bodies with no dated row at all", 
  f"SELECT count(*) FROM (SELECT sha256 FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1 HAVING count(retrieved_at) = 0)")
q("distinct bodies whose only dated rows are on 2026-09-29 (import-day proxy)",
  f"""SELECT count(*) FROM (SELECT sha256 FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1 HAVING count(retrieved_at)>0 AND min(substr(retrieved_at,1,10)) = '2026-09-29' AND max(substr(retrieved_at,1,10)) = '2026-09-29')""")
q("retrieved_at sample values", f"SELECT retrieved_at, capture_date FROM {C} WHERE retrieved_at IS NOT NULL LIMIT 3")
