"""Base tables for all findings -> vm7.duckdb (in this folder).
Proxies for DM 7.3 (each stated, because the snapshot lacks the target columns):
  status   : row http_status; a null-status row that is not a prior attempt takes its line's final-response status
             (max non-null status among the line's top-level, non-prior rows). Raw receipts confirm WARC and member entries
             carry their line's 200 (vm7_warc_raw_all.out).
  complete : a prior attempt's own raw complete flag (vm7_prior.parquet); and resolution not in (size_limit, request_failed, timeout, resource_limit) and bytes <> 64 MiB (DM 6.1 older-line rule).
  outcome  : resolution not in (http_error, retry_later, request_failed, size_limit, timeout, resource_limit, empty).
  mode     : recovery rows = lines whose raw record.mode = 'retained_import' (vm7_modes.parquet); reference_kind 'metadata' rows have no body.
  format   : old sniff reading body_format when completed, else media type (warc/arc+gzip -> 'warc', gzip is NOT zip), else extension; one format per body (the mode of its rows' non-'other' formats).
             fmt_dm = what DM 6.2's sniff would say: identical except a .warc.gz/.arc.gz original (gzip inside gzip storage) -> 'other'.
  roles    : caption (vtt), playlist (m3u8), api (json at api.*), source_record (xml members dip/mods/premis.xml, and govinfo mods/premis/mets
             families), damaged (pdf with resolution invalid_document or failed reading), HTML error/wrapper/listing NOT applied here
             (no html reading in the snapshot); finding-specific scripts classify the HTML they need from the bodies.
  file_shaped: the narrow list on the locator (member path, else URL with query).
  endpoint : DM's exact (context_url, member_path); ukey = url_key-lite (scheme, www, host case, trailing slash, fragment;
             web.archive.org/web/<ts><mod>/ unwrapped) for comparison.
"""
import duckdb, os
D=os.path.dirname(os.path.abspath(__file__))
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
db=D+'/vm7.duckdb'
if os.path.exists(db): os.remove(db)
con=duckdb.connect(db); con.execute("SET threads=6; SET memory_limit='10GB'; SET preserve_insertion_order=false")
con.execute(f"""CREATE TABLE rd AS SELECT body_key, any_value(lower(body_format[1])) FILTER (WHERE status='completed') bf,
  bool_or(status='failed') rfailed FROM read_parquet('{B}readings/*.parquet', union_by_name=true) GROUP BY 1""")
con.execute(f"CREATE TABLE modes AS SELECT * FROM read_parquet('{D}/vm7_modes.parquet') WHERE mode='retained_import'")
con.execute(f"""CREATE TABLE c0 AS SELECT row_number() OVER () id, family fam, receipt_key rk, receipt_line rl, reference_kind rkind, pointer_json ptr,
  context_url ctx, original_path mem, body_key, sha256 sha, bytes, lower(split_part(coalesce(media_type,''),';',1)) mt, http_status st_row,
  fidelity fid, resolution res, retrieved_at,
  coalesce(pointer_json,'') LIKE '%prior_attempts%' is_prior,
  lower(coalesce(original_path, context_url)) loc
  FROM read_parquet('{B}captures.parquet')""")
con.execute("""CREATE TABLE line0 AS SELECT rk, rl, max(st_row) st0 FROM c0 WHERE mem IS NULL AND NOT is_prior AND st_row IS NOT NULL GROUP BY 1,2""")
con.execute(f"""CREATE TABLE c AS SELECT c0.*, rd.bf, coalesce(rd.rfailed,false) rfailed,
  CASE WHEN is_prior THEN coalesce(pa.http_status, st_row) WHEN st_row IS NOT NULL THEN st_row ELSE l.st0 END eff_st,
  CASE WHEN is_prior THEN coalesce(pa.complete, true) ELSE true END att_complete,
  (m.mode IS NOT NULL) recovery,
  regexp_replace(lower(regexp_replace(coalesce(mem, regexp_replace(ctx,'[?#].*$','')),'^.*/','')),'^.*(\\.[a-z0-9]{{1,5}})$','\\1') ext
  FROM c0 LEFT JOIN line0 l USING (rk, rl) LEFT JOIN rd USING (body_key) LEFT JOIN modes m ON m.receipt_key=c0.rk AND m.receipt_line=c0.rl
  LEFT JOIN read_parquet('{D}/vm7_prior.parquet') pa ON c0.is_prior AND pa.receipt_key=c0.rk AND pa.receipt_line=c0.rl
       AND pa.attempt = TRY_CAST(regexp_extract(c0.ptr, 'prior_attempts", ([0-9]+)', 1) AS INT)""")
con.execute("""ALTER TABLE c ADD COLUMN fmt VARCHAR; UPDATE c SET fmt = CASE
  WHEN mt IN ('application/warc+gzip','application/arc+gzip') THEN 'warc'
  WHEN bf IN ('pdf','html','zip','xml') THEN bf
  WHEN bf IN ('jpeg','png') THEN 'image'
  WHEN mt LIKE '%html%' THEN 'html' WHEN mt = 'application/pdf' THEN 'pdf' WHEN mt IN ('application/zip','application/x-zip-compressed') THEN 'zip'
  WHEN mt LIKE '%xml%' THEN 'xml' WHEN mt LIKE '%json%' THEN 'json' WHEN mt = 'text/vtt' THEN 'vtt' WHEN mt LIKE '%mpegurl%' THEN 'm3u8'
  WHEN mt LIKE 'image/%' THEN 'image' WHEN mt = 'application/msword' THEN 'doc' WHEN mt LIKE '%wordprocessingml%' THEN 'docx'
  WHEN mt LIKE 'text/plain%' THEN 'text'
  WHEN mt IN ('','application/x-octet-stream','application/octet-stream') THEN CASE
     WHEN ext='.pdf' THEN 'pdf' WHEN ext='.zip' THEN 'zip' WHEN ext IN ('.htm','.html') THEN 'html' WHEN ext='.xml' THEN 'xml'
     WHEN ext='.vtt' THEN 'vtt' WHEN ext='.m3u8' THEN 'm3u8' WHEN ext='.json' THEN 'json' WHEN ext='.docx' THEN 'docx' WHEN ext='.doc' THEN 'doc'
     WHEN ext='.txt' THEN 'text' ELSE 'other' END
  ELSE 'other' END""")
# a body has one format: rows with no media type (provider_response copies) take the body's typed rows' format
con.execute("""CREATE TABLE bfmt AS SELECT sha, coalesce(mode(fmt) FILTER (WHERE fmt<>'other'), 'other') f FROM c WHERE sha IS NOT NULL GROUP BY 1""")
con.execute("UPDATE c SET fmt = bfmt.f FROM bfmt WHERE c.sha = bfmt.sha")
con.execute("ALTER TABLE c ADD COLUMN fmt_dm VARCHAR; UPDATE c SET fmt_dm = CASE WHEN fmt='warc' THEN 'other' ELSE fmt END")
con.execute("""CREATE TABLE placeholders AS SELECT sha FROM c WHERE sha IS NOT NULL GROUP BY 1 HAVING count(DISTINCT ctx) > 100""")
con.execute("""ALTER TABLE c ADD COLUMN good BOOLEAN; UPDATE c SET good = sha IS NOT NULL AND rkind <> 'metadata' AND NOT recovery
  AND eff_st BETWEEN 200 AND 299
  AND coalesce(res,'') NOT IN ('size_limit','request_failed','timeout','resource_limit','http_error','retry_later','empty')
  AND bytes <> 67108864 AND att_complete""")
con.execute("""ALTER TABLE c ADD COLUMN role VARCHAR; UPDATE c SET role = CASE
  WHEN fmt='vtt' THEN 'caption' WHEN fmt='m3u8' THEN 'playlist'
  WHEN fmt='pdf' AND (res='invalid_document' OR rfailed) THEN 'damaged'
  WHEN fmt='json' AND ctx LIKE '%://api.%' THEN 'api'
  WHEN fmt='xml' AND (regexp_matches(lower(coalesce(mem,'')), '(^|/)(dip|mods|premis)\\.xml$') OR fam IN ('govinfo/mods','govinfo/premis','govinfo/mets')) THEN 'source_record'
  ELSE 'document' END""")
con.execute("""ALTER TABLE c ADD COLUMN file_shaped BOOLEAN; UPDATE c SET file_shaped =
  regexp_matches(loc, '\\.(pdf|zip|doc|docx|xml)($|[?#])') OR loc LIKE '%/download/%' OR loc LIKE '%download=1%' OR loc LIKE '%file_id=%'""")
con.execute("""ALTER TABLE c ADD COLUMN ukey VARCHAR; UPDATE c SET ukey =
  regexp_replace(regexp_replace(lower(regexp_extract(regexp_replace(ctx,'^https?://web\\.archive\\.org/web/[0-9]+[a-z_]*/',''),'^(?:[a-z]+://)?(?:www\\.)?([^/?#]*)',1)),':(80|443)$',''),'^www\\.','')
  || regexp_replace(regexp_replace(regexp_extract(regexp_replace(ctx,'^https?://web\\.archive\\.org/web/[0-9]+[a-z_]*/',''),'^(?:[a-z]+://)?[^/?#]*([^#]*)',1),'/$',''),'/\\?','?')""")
con.execute("""CREATE TABLE real AS SELECT * FROM c WHERE good AND bytes > 0 AND sha NOT IN (SELECT sha FROM placeholders)
  AND role='document' AND NOT (fmt='html' AND file_shaped)""")
for s in ["SELECT count(*), count(DISTINCT sha) FROM c", "SELECT count(*) FILTER (WHERE good), count(*) FILTER (WHERE recovery) FROM c",
          "SELECT count(*) FROM placeholders", "SELECT fmt, count(*), count(DISTINCT sha) FROM real GROUP BY 1 ORDER BY 2 DESC",
          "SELECT ctx, ukey FROM c WHERE ctx LIKE '%web.archive.org%' LIMIT 3", "SELECT ctx, ukey FROM c USING SAMPLE 3"]:
    print(s); print('  ', con.execute(s).fetchall())
