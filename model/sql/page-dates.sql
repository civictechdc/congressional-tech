-- A page's declared dates, per body: the first valid value by registry format rank, then pointer, then value.
-- Guarded against retroactive CMS upload-folder paths (/wp-content/uploads/YYYY/MM/, /sites/.../files/YYYY-MM/)
-- and exact 14-digit web-archive capture timestamp injections while preserving genuine same-day publication dates.
WITH body_urls AS (
 SELECT d.body_sha,b.source_url AS addr
 FROM page_metadata_documents d JOIN base_normalized b ON b.doc_key=d.doc_key
 WHERE b.source_url IS NOT NULL
 UNION
 SELECT body_sha,value AS addr FROM page_metadata_values WHERE field='declared_url' AND value IS NOT NULL
 UNION
 SELECT body_sha,base_href AS addr FROM html_metadata_readings WHERE base_href IS NOT NULL
),
url_flags AS (
 SELECT body_sha,
  bool_or(cms_flag) AS is_cms_upload,
  array_agg(ts14) FILTER (WHERE ts14 IS NOT NULL) AS archive_ts14s
 FROM (
  SELECT body_sha,
   regexp_like(
    addr,
    '(?i)/(?:wp-content/uploads/[0-9]{4}/[0-9]{2}(?:[/?#]|$)|sites/[^/?#]+/files/(?:[^?#]*/)?[0-9]{4}[-/][0-9]{2}(?:[/?#]|$))'
   ) AS cms_flag,
   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{14})'))[1] AS ts14
  FROM body_urls
 )
 WHERE cms_flag OR ts14 IS NOT NULL
 GROUP BY body_sha
),
dated_values AS (
 SELECT v.body_sha,v.field,v.date,v.path,v.value,v.format
 FROM url_flags uf
 RIGHT JOIN page_metadata_values v ON uf.body_sha=v.body_sha
 WHERE v.field IN ('published_time','modified_time') AND v.date IS NOT NULL
  AND NOT coalesce(uf.is_cms_upload,false)
  AND NOT (
   uf.archive_ts14s IS NOT NULL
   AND v.precision='second'
   AND array_has(uf.archive_ts14s,regexp_replace(substr(trim(v.value),1,19),'[^0-9]','','g'))
  )
),
ranked AS (
 SELECT v.body_sha,v.field,v.date,row_number() OVER(PARTITION BY v.body_sha,v.field
   ORDER BY coalesce(r.number,99),v.path,v.date,v.value) AS choice,v.path
 FROM (SELECT pattern,number FROM page_signals WHERE kind='date_format') r
 RIGHT JOIN dated_values v ON regexp_like(v.format,r.pattern)
)
SELECT body_sha,
 max(CASE WHEN field='published_time' THEN date END) AS published_on,
 max(CASE WHEN field='published_time' THEN path END) AS published_path,
 max(CASE WHEN field='modified_time' THEN date END) AS modified_on,
 max(CASE WHEN field='modified_time' THEN path END) AS modified_path
FROM ranked WHERE choice=1 GROUP BY body_sha
