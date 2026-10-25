import duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB';")
C = f"read_parquet('{base}/captures.parquet')"
def q(label, sql):
    r = con.execute(sql).fetchall()
    print(f"\n## {label}\n{sql.strip()}\n-> {r}")
q("rows, distinct sha, null sha rows, distinct lines, distinct receipt files",
  f"SELECT count(*), count(DISTINCT sha256), count(*) FILTER (WHERE sha256 IS NULL), count(DISTINCT (receipt_key, receipt_line)), count(DISTINCT receipt_key) FROM {C}")
q("reference_kind / resolution distribution",
  f"SELECT reference_kind, resolution, count(*) FROM {C} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20")
q("max captures per receipt line",
  f"SELECT max(n) FROM (SELECT receipt_key, receipt_line, count(*) n FROM {C} GROUP BY 1,2)")
q("largest body bytes; bodies over 5GB; distinct bodies with stored_bytes > 100 MiB",
  f"SELECT max(bytes), count(DISTINCT sha256) FILTER (WHERE bytes > 5*1024*1024*1024), count(DISTINCT sha256) FILTER (WHERE stored_bytes > 100*1024*1024), count(DISTINCT sha256) FILTER (WHERE bytes > 100*1024*1024) FROM {C}")
q("rows with null retrieved_at; rows with null http_status",
  f"SELECT count(*) FILTER (WHERE retrieved_at IS NULL), count(*) FILTER (WHERE http_status IS NULL) FROM {C}")
q("placeholder candidates: bodies seen at > 50/100/200 distinct context_urls; top body",
  f"""WITH per AS (SELECT sha256, count(DISTINCT context_url) u, count(*) rows_ FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1)
      SELECT count(*) FILTER (WHERE u>50), count(*) FILTER (WHERE u>100), count(*) FILTER (WHERE u>200), max(u) FROM per""")
q("top 5 placeholder bodies by distinct context_url with their media type",
  f"""SELECT sha256, count(DISTINCT context_url) u, count(*) rows_, min(media_type), min(bytes) FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5""")
q("attempts and new bodies per capture_date (top 3 days)",
  f"""WITH first_seen AS (SELECT sha256, min(capture_date) d FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1),
      att AS (SELECT capture_date, count(DISTINCT (receipt_key, receipt_line)) attempts, count(*) rows_ FROM {C} GROUP BY 1),
      nb AS (SELECT d, count(*) new_bodies FROM first_seen GROUP BY 1)
      SELECT att.capture_date, attempts, rows_, new_bodies FROM att LEFT JOIN nb ON nb.d = att.capture_date ORDER BY attempts DESC LIMIT 3""")
q("distinct context_url; distinct (context_url, original_path) endpoints",
  f"SELECT count(DISTINCT context_url), count(DISTINCT (context_url, original_path)) FROM {C}")
q("archive members (original_path not null) and HTML-typed members",
  f"SELECT count(*) FILTER (WHERE original_path IS NOT NULL), count(*) FILTER (WHERE original_path IS NOT NULL AND lower(media_type) LIKE '%html%'), count(DISTINCT sha256) FILTER (WHERE original_path IS NOT NULL AND lower(media_type) LIKE '%html%') FROM {C}")
q("fraction of body-bearing rows whose body was already seen on an earlier line (proxy for 412 rate)",
  f"""WITH ranked AS (SELECT sha256, row_number() OVER (PARTITION BY sha256 ORDER BY retrieved_at NULLS FIRST, receipt_key, receipt_line) rn FROM {C} WHERE sha256 IS NOT NULL)
      SELECT count(*) FILTER (WHERE rn>1) * 1.0 / count(*) FROM ranked""")
q("stored_sha256 present rows; stored_bytes present rows",
  f"SELECT count(*) FILTER (WHERE stored_sha256 IS NOT NULL), count(*) FILTER (WHERE stored_bytes IS NOT NULL) FROM {C}")
q("HTML-typed bodies whose URL is file-shaped by the narrow list",
  f"""SELECT count(DISTINCT sha256) FROM {C} WHERE lower(media_type) LIKE '%html%' AND sha256 IS NOT NULL
      AND regexp_matches(lower(coalesce(original_path, context_url)), '(\\.pdf|\\.zip|\\.doc|\\.docx|\\.xml)($|[?#])|/download/|download=1|file_id=')""")
q("HTML-typed bodies whose URL is file-shaped by the broad list",
  f"""SELECT count(DISTINCT sha256) FROM {C} WHERE lower(media_type) LIKE '%html%' AND sha256 IS NOT NULL
      AND regexp_matches(lower(coalesce(original_path, context_url)), '(\\.pdf|\\.zip|\\.doc|\\.docx|\\.xml|\\.pptx|\\.xlsx|\\.txt)($|[?#])|/download/|download=1|file_id=|/files/|/uploadedfiles/|/media/doc/')""")
q("receipt_key prefix shapes (dated vs undated/mixed) counts of files and rows",
  f"""SELECT CASE WHEN receipt_key LIKE '%/undated/%' THEN 'undated' WHEN receipt_key LIKE '%/mixed-dates/%' THEN 'mixed' WHEN regexp_matches(receipt_key, '/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/') THEN 'dated' ELSE 'other' END shape, count(DISTINCT receipt_key), count(*) FROM {C} GROUP BY 1""")
q("sample receipt_key values", f"SELECT receipt_key FROM {C} WHERE receipt_key IS NOT NULL LIMIT 3")
q("rows with http_status outside 2xx, by status (top)", f"SELECT http_status, count(*) FROM {C} GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
