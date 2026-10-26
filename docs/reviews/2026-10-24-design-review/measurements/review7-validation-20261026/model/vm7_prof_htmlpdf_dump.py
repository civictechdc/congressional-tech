"""Copy of prof7_grouping2.py up to its endpoint table, dumping the [html,pdf]-containing endpoints for comparison."""
"""Corrected real-data tests of DM §7.3/§7.5 (media-type-first format; url_key-lite endpoints; same-stem groups on the old catalog's effective filenames)."""
import time, duckdb
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
con=duckdb.connect(); con.execute("SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false;")
def q(l,s):
    t=time.time(); rows=con.execute(s).fetchall(); print(f'\n## {l}  ({time.time()-t:.1f}s)')
    for r in rows[:40]: print('  ',r)
C=f"read_parquet('{B}captures.parquet')"; F=f"read_parquet('{B}filenames.parquet')"
con.execute(f"""CREATE TABLE c AS SELECT receipt_key, receipt_line, reference_kind, context_url, sha256, bytes, media_type, http_status, original_path, fidelity,
  lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) AS loc,
  CASE WHEN media_type ILIKE '%html%' THEN 'html'
       WHEN media_type ILIKE '%pdf%' THEN 'pdf'
       WHEN media_type ILIKE '%zip%' THEN 'zip'
       WHEN media_type ILIKE '%xml%' THEN 'xml'
       WHEN media_type ILIKE '%json%' THEN 'json'
       WHEN media_type ILIKE '%vtt%' THEN 'vtt'
       WHEN media_type ILIKE '%mpegurl%' THEN 'm3u8'
       WHEN media_type ILIKE 'image/%' THEN 'image'
       WHEN media_type ILIKE '%msword%' OR media_type ILIKE '%officedocument%' THEN 'docx'
       WHEN media_type IS NULL OR media_type='' OR media_type ILIKE '%octet-stream%' OR media_type ILIKE '%unknown%' THEN
            CASE WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) LIKE '%.pdf' THEN 'pdf'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) LIKE '%.zip' THEN 'zip'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) SIMILAR TO '%\\.(htm|html)' THEN 'html'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) LIKE '%.xml' THEN 'xml'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) SIMILAR TO '%\\.(jpg|jpeg|png|gif)' THEN 'image'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) LIKE '%.m3u8' THEN 'm3u8'
                 WHEN lower(coalesce(original_path, regexp_replace(context_url, '[?#].*$', ''))) LIKE '%.vtt' THEN 'vtt'
                 ELSE 'other' END
       WHEN media_type ILIKE 'text/plain%' THEN 'text'
       ELSE 'other' END AS fmt,
  -- url_key-lite: unwrap web.archive.org, drop scheme/www/trailing slash, lowercase host
  regexp_replace(regexp_replace(regexp_replace(regexp_replace(context_url, '^https?://web\\.archive\\.org/web/[0-9]+[a-z_]*/', ''), '^https?://(www\\.)?', ''), '/$', ''), '#.*$', '') AS ukey
  FROM {C}""")
q("'other' format: top media types", "SELECT media_type, count(*) FROM c WHERE fmt='other' GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
con.execute("CREATE TABLE linestat AS SELECT receipt_key, receipt_line, max(http_status) st FROM c WHERE original_path IS NULL GROUP BY 1,2")
con.execute("CREATE TABLE placeholders AS SELECT sha256 FROM c WHERE sha256 IS NOT NULL GROUP BY 1 HAVING count(DISTINCT context_url) > 100")
con.execute("""CREATE TABLE real AS
 SELECT c.*, coalesce(c.http_status, l.st) AS eff_status
 FROM c LEFT JOIN linestat l USING (receipt_key, receipt_line)
 WHERE c.sha256 IS NOT NULL AND c.bytes > 0 AND c.reference_kind <> 'retained-file'
   AND (coalesce(c.http_status, l.st) BETWEEN 200 AND 299)
   AND c.sha256 NOT IN (SELECT sha256 FROM placeholders)
   AND c.fmt NOT IN ('vtt','m3u8','json')
   AND NOT (c.fmt='html' AND (c.loc SIMILAR TO '%\\.(pdf|zip|doc|docx|xml)' OR c.context_url LIKE '%/download/%' OR c.context_url LIKE '%download=1%' OR c.context_url LIKE '%file_id=%'))""")
q("real-file proxy by format: rows, bodies", "SELECT fmt, count(*) n_rows, count(DISTINCT sha256) bodies FROM real GROUP BY 1 ORDER BY 2 DESC")
con.execute("CREATE TABLE ep AS SELECT ukey, original_path, count(DISTINCT sha256) nb, list_sort(list_distinct(list(fmt))) fmts FROM real GROUP BY 1,2")
q("edition-ambiguous endpoints, upper bound (no fingerprints): by formats present",
  "SELECT original_path IS NOT NULL is_member, fmts::VARCHAR, count(*) endpoints, max(nb) max_bodies FROM ep WHERE nb>=2 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 12")
con.execute("CREATE TABLE amb AS SELECT DISTINCT r.sha256, r.fmt FROM real r JOIN ep ON r.ukey=ep.ukey AND r.original_path IS NOT DISTINCT FROM ep.original_path WHERE ep.nb>=2")

D="/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-7/validate-model/"
con.execute(f"COPY (SELECT r.ukey, r.original_path, r.receipt_key, r.receipt_line, r.sha256, r.fmt, r.media_type, r.http_status, r.eff_status, r.context_url, ep.fmts::VARCHAR fmts FROM real r JOIN ep ON r.ukey=ep.ukey AND r.original_path IS NOT DISTINCT FROM ep.original_path WHERE ep.nb>=2 AND (list_contains(ep.fmts,'html') AND list_contains(ep.fmts,'pdf'))) TO '{D}vm7_prof_htmlpdf.parquet'")
