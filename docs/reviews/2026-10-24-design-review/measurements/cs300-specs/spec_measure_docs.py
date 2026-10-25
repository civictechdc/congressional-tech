import duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB';")
F = f"read_parquet('{base}/filenames.parquet')"
D = f"read_parquet('{base}/documents.parquet')"
S = f"read_parquet('{base}/state.parquet')"
def q(label, sql):
    r = con.execute(sql).fetchall()
    print(f"\n## {label}\n-> {r}")
q("response_format distribution (top 12)",
  f"SELECT f, count(*) FROM (SELECT unnest(response_format) f FROM {F}) GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
q("archive-member rows (source_paths non-empty) whose response_format/body_format is html-ish",
  f"SELECT count(*) FILTER (WHERE len(source_paths)>0 AND (list_contains(response_format,'html') OR list_contains(body_format,'html'))), count(*) FILTER (WHERE len(source_paths)>0 AND regexp_matches(lower(source_paths[1]), '\\.html?$')) FROM {F}")
q("documents: rows, distinct document_id, docs with >1 body key, docs with 0 body keys",
  f"SELECT count(*), count(DISTINCT document_id), count(*) FILTER (WHERE len(body_keys)>1), count(*) FILTER (WHERE body_keys IS NULL OR len(body_keys)=0) FROM {D}")
q("body keys that appear in more than one old document (plan F0 says 141,762)",
  f"SELECT count(*) FROM (SELECT bk FROM (SELECT document_id, unnest(body_keys) bk FROM {D}) GROUP BY bk HAVING count(DISTINCT document_id) > 1)")
q("state: rows, distinct url, outcome distribution top 6",
  f"SELECT count(*), count(DISTINCT url) FROM {S}")
q("state outcomes", f"SELECT outcome, count(*) FROM {S} GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("state: urls with http_status 404/410 (plan parks 36,137 documents' URLs)", f"SELECT http_status, count(*) FROM {S} WHERE http_status IN (404,410) GROUP BY 1")
q("documents: distinct filename-stem groups across formats (rough rendition proxy): same dir+stem with different extensions, count groups and docs",
  f"""WITH x AS (SELECT document_id, source_url, regexp_replace(regexp_replace(source_url,'[?#].*$',''),'\\.[A-Za-z0-9]{{1,5}}$','') stem, lower(regexp_extract(regexp_replace(source_url,'[?#].*$',''),'\\.([A-Za-z0-9]{{1,5}})$',1)) ext FROM {D} WHERE source_url IS NOT NULL),
      g AS (SELECT stem, count(DISTINCT document_id) nd, count(DISTINCT ext) ne FROM x WHERE ext IN ('pdf','xml','htm','html','doc','docx','txt') AND NOT regexp_matches(lower(stem), '/(index|document|download|file|default)$') GROUP BY 1 HAVING count(DISTINCT ext) > 1 AND count(DISTINCT document_id) > 1)
      SELECT count(*), sum(nd) FROM g""")
