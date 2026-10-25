import duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB';")
F = f"read_parquet('{base}/filenames.parquet')"
def q(label, sql):
    r = con.execute(sql).fetchall()
    print(f"\n## {label}\n{sql.strip()}\n-> {r}")
q("source files; null source_url; filename != url last segment; distinct body_key; null body_key",
  f"""SELECT count(*), count(*) FILTER (WHERE source_url IS NULL),
      count(*) FILTER (WHERE source_url IS NOT NULL AND filename <> regexp_extract(regexp_replace(source_url, '[?#].*$', ''), '([^/]*)$', 1)),
      count(DISTINCT body_key), count(*) FILTER (WHERE body_key IS NULL) FROM {F}""")
q("body_keys that appear in more than one source file row (old filenames grain)",
  f"SELECT count(*) FROM (SELECT body_key FROM {F} WHERE body_key IS NOT NULL GROUP BY 1 HAVING count(*)>1)")
q("multi-valued facets: >1 document_kind, >1 document_family, >1 committee_code",
  f"SELECT count(*) FILTER (WHERE len(document_kind)>1), count(*) FILTER (WHERE len(document_family)>1), count(*) FILTER (WHERE len(committee_code)>1) FROM {F}")
q("rows with non-empty source_paths (archive members) and response_format html among them",
  f"SELECT count(*) FILTER (WHERE len(source_paths)>0), count(*) FILTER (WHERE len(source_paths)>0 AND list_contains(response_format,'html')) FROM {F}")
q("response_format distribution (top 12)",
  f"SELECT unnest(response_format) f, count(*) FROM {F} GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
q("source_url sample where filename differs from last segment", 
  f"SELECT filename, source_url FROM {F} WHERE source_url IS NOT NULL AND filename <> regexp_extract(regexp_replace(source_url, '[?#].*$', ''), '([^/]*)$', 1) LIMIT 5")
q("distinct (filename, source_url) pairs", f"SELECT count(DISTINCT (filename, coalesce(source_url,''))) FROM {F}")
q("rows where body_key null: sample", f"SELECT filename, source_url, filename_origins, capture_outcome FROM {F} WHERE body_key IS NULL LIMIT 3")
q("source_url host distribution for null-body rows (top 5)", f"SELECT regexp_extract(source_url, '^https?://([^/]+)', 1) h, count(*) FROM {F} WHERE body_key IS NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
