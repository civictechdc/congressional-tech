import duckdb
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
con.execute("SET threads=4; SET memory_limit='6GB';")
C = f"read_parquet('{base}/captures.parquet')"
def q(label, sql):
    r = con.execute(sql).fetchall()
    print(f"\n## {label}\n-> {r}")
q("largest body bytes; bodies over 5GB; distinct bodies with stored_bytes > 100 MiB; with bytes > 100 MiB",
  f"SELECT max(bytes), count(DISTINCT sha256) FILTER (WHERE bytes > 5::BIGINT*1024*1024*1024), count(DISTINCT sha256) FILTER (WHERE stored_bytes > 100::BIGINT*1024*1024), count(DISTINCT sha256) FILTER (WHERE bytes > 100::BIGINT*1024*1024) FROM {C}")
q("distinct bodies > 100 MiB that are not PDFs (by server media type)",
  f"SELECT count(DISTINCT sha256) FROM {C} WHERE bytes > 100::BIGINT*1024*1024 AND lower(coalesce(media_type,'')) NOT LIKE '%pdf%'")
q("rows with null retrieved_at; rows with null http_status",
  f"SELECT count(*) FILTER (WHERE retrieved_at IS NULL), count(*) FILTER (WHERE http_status IS NULL) FROM {C}")
q("placeholder candidates: bodies seen at > 50/100/200 distinct context_urls; max",
  f"""WITH per AS (SELECT sha256, count(DISTINCT context_url) u FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1)
      SELECT count(*) FILTER (WHERE u>50), count(*) FILTER (WHERE u>100), count(*) FILTER (WHERE u>200), max(u) FROM per""")
q("top 5 placeholder bodies by distinct context_url",
  f"""SELECT left(sha256,12), count(DISTINCT context_url) u, count(*) rows_, min(media_type), min(bytes) FROM {C} WHERE sha256 IS NOT NULL GROUP BY sha256 ORDER BY 2 DESC LIMIT 5""")
q("attempts and new bodies per capture_date (top 3 days by attempts)",
  f"""WITH first_seen AS (SELECT sha256, min(capture_date) d FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1),
      att AS (SELECT capture_date, count(DISTINCT (receipt_key, receipt_line)) attempts, count(*) rows_ FROM {C} GROUP BY 1),
      nb AS (SELECT d, count(*) new_bodies FROM first_seen GROUP BY 1)
      SELECT att.capture_date, attempts, rows_, new_bodies FROM att LEFT JOIN nb ON nb.d = att.capture_date ORDER BY attempts DESC LIMIT 3""")
q("normal-day range: attempts per capture_date percentiles over the last 60 dated days",
  f"""WITH att AS (SELECT capture_date, count(DISTINCT (receipt_key, receipt_line)) attempts FROM {C} WHERE capture_date IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 60)
      SELECT min(attempts), quantile_cont(attempts, 0.5), max(attempts) FROM att WHERE attempts < 100000""")
q("distinct context_url; distinct (context_url, original_path) endpoints",
  f"SELECT count(DISTINCT context_url), count(DISTINCT (context_url, coalesce(original_path,''))) FROM {C}")
q("archive member rows; HTML-typed member rows; distinct HTML member bodies; member rows at .zip container URLs",
  f"SELECT count(*) FILTER (WHERE original_path IS NOT NULL), count(*) FILTER (WHERE original_path IS NOT NULL AND lower(media_type) LIKE '%html%'), count(DISTINCT sha256) FILTER (WHERE original_path IS NOT NULL AND lower(media_type) LIKE '%html%'), count(*) FILTER (WHERE original_path IS NOT NULL AND lower(context_url) LIKE '%.zip%') FROM {C}")
q("media_type distribution among archive member rows (top 8)",
  f"SELECT media_type, count(*) FROM {C} WHERE original_path IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("member rows whose path ends .htm/.html",
  f"SELECT count(*), count(DISTINCT sha256) FROM {C} WHERE original_path IS NOT NULL AND regexp_matches(lower(original_path), '\\.html?$')")
q("fraction of body-bearing rows whose body was already seen on an earlier line (412 proxy)",
  f"""WITH ranked AS (SELECT sha256, row_number() OVER (PARTITION BY sha256 ORDER BY retrieved_at NULLS FIRST, receipt_key, receipt_line) rn FROM {C} WHERE sha256 IS NOT NULL)
      SELECT round(count(*) FILTER (WHERE rn>1) * 1.0 / count(*), 3) FROM ranked""")
q("HTML-typed bodies file-shaped by the narrow list (server media type; approximation of sniffed html)",
  f"""SELECT count(DISTINCT sha256) FROM {C} WHERE lower(media_type) LIKE '%html%' AND sha256 IS NOT NULL
      AND regexp_matches(lower(coalesce(original_path, context_url)), '(\\.pdf|\\.zip|\\.docx?|\\.xml)([?#].*)?$|/download/|download=1|file_id=')""")
q("HTML-typed bodies file-shaped by a broad list",
  f"""SELECT count(DISTINCT sha256) FROM {C} WHERE lower(media_type) LIKE '%html%' AND sha256 IS NOT NULL
      AND regexp_matches(lower(coalesce(original_path, context_url)), '(\\.pdf|\\.zip|\\.docx?|\\.xml|\\.pptx?|\\.xlsx?|\\.txt)([?#].*)?$|/download/|download=1|file_id=|/files/|/uploadedfiles/|/media/doc/')""")
q("distinct HTML-typed bodies total", f"SELECT count(DISTINCT sha256) FROM {C} WHERE lower(media_type) LIKE '%html%' AND sha256 IS NOT NULL")
q("receipt_key shapes", 
  f"""SELECT CASE WHEN receipt_key LIKE '%/undated/%' THEN 'undated' WHEN receipt_key LIKE '%/mixed-dates/%' THEN 'mixed' WHEN regexp_matches(receipt_key, '/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/') THEN 'dated' ELSE 'other' END shape, count(DISTINCT receipt_key), count(*) FROM {C} GROUP BY 1""")
q("sample receipt_key values", f"SELECT DISTINCT receipt_key FROM {C} LIMIT 4")
q("http_status distribution (top 8)", f"SELECT http_status, count(*) FROM {C} GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("bodies whose every row is in the 2026-09-29 import day (import-only bodies), and import-day source_file names",
  f"""WITH per AS (SELECT sha256, min(capture_date) mn, max(capture_date) mx FROM {C} WHERE sha256 IS NOT NULL GROUP BY 1)
      SELECT count(*) FROM per WHERE mn = mx AND mn = (SELECT capture_date FROM {C} GROUP BY 1 ORDER BY count(*) DESC LIMIT 1)""")
q("busiest capture_date and its distinct source_file (run) count", f"SELECT capture_date, count(DISTINCT source_file), count(DISTINCT receipt_key) FROM {C} GROUP BY 1 ORDER BY count(*) DESC LIMIT 2")
q("cut-off candidates: rows with bytes exactly 64 MiB", f"SELECT count(*), count(DISTINCT sha256), count(DISTINCT context_url) FROM {C} WHERE bytes = 64*1024*1024")
q("lines with resolution size_limit / request_failed: distinct URLs", f"SELECT resolution, count(DISTINCT context_url) FROM {C} WHERE resolution IN ('size_limit','request_failed') GROUP BY 1")
