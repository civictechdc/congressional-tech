-- A page's declared dates, per body: the first valid value by registry format rank, then pointer, then value.
-- Guarded against retroactive CMS upload-folder paths (/wp-content/uploads/YYYY/MM/, /sites/.../files/YYYY-MM/)
-- and 14-digit web-archive capture timestamps (web.archive.org/web/YYYYMMDD..., webharvest.gov/.../YYYYMMDD...).
WITH body_urls AS (
 SELECT body_sha,source_url AS addr FROM (
  SELECT d.body_sha,b.source_url FROM page_metadata_documents d
  JOIN base_normalized b ON b.doc_key=d.doc_key WHERE b.source_url IS NOT NULL
 )
 UNION
 SELECT body_sha,value AS addr FROM page_metadata_values WHERE field='declared_url' AND value IS NOT NULL
 UNION
 SELECT body_sha,base_href AS addr FROM html_metadata_readings WHERE base_href IS NOT NULL
),
cms_upload_bodies AS (
 SELECT DISTINCT body_sha FROM body_urls
 WHERE regexp_like(
  addr,
  '(?i)/(?:wp-content/uploads/[0-9]{4}/[0-9]{2}(?:[/?#]|$)|sites/[^/?#]+/files/(?:[^?#]*/)?[0-9]{4}[-/][0-9]{2}(?:[/?#]|$))'
 )
),
archive_capture_dates AS (
 SELECT DISTINCT body_sha,
  try_cast(
   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[1]
   ||'-'||
   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[2]
   ||'-'||
   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[3]
   AS DATE
  ) AS capture_date
 FROM body_urls
 WHERE regexp_like(
  addr,
  '(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)[0-9]{14}'
 )
),
ranked AS (
 SELECT v.body_sha,v.field,v.date,row_number() OVER(PARTITION BY v.body_sha,v.field
   ORDER BY coalesce(r.number,99),v.path,v.date,v.value) AS choice,v.path
 FROM page_metadata_values v
 LEFT JOIN page_signals r ON r.kind='date_format' AND regexp_like(v.format,r.pattern)
 LEFT JOIN cms_upload_bodies cu ON cu.body_sha=v.body_sha
 LEFT JOIN archive_capture_dates ac ON ac.body_sha=v.body_sha AND ac.capture_date=v.date
 WHERE v.field IN ('published_time','modified_time') AND v.date IS NOT NULL
  AND cu.body_sha IS NULL AND ac.body_sha IS NULL
)
SELECT body_sha,
 max(CASE WHEN field='published_time' THEN date END) AS published_on,
 max(CASE WHEN field='published_time' THEN path END) AS published_path,
 max(CASE WHEN field='modified_time' THEN date END) AS modified_on,
 max(CASE WHEN field='modified_time' THEN path END) AS modified_path
FROM ranked WHERE choice=1 GROUP BY body_sha
