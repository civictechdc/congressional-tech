-- A page's declared dates, per body: the first valid value by registry format rank, then pointer, then value.
WITH ranked AS (
 SELECT v.body_sha,v.field,v.date,row_number() OVER(PARTITION BY v.body_sha,v.field
   ORDER BY coalesce(r.number,99),v.path,v.date,v.value) AS choice,v.path
 FROM page_metadata_values v LEFT JOIN page_signals r ON r.kind='date_format' AND regexp_like(v.format,r.pattern)
 WHERE v.field IN ('published_time','modified_time') AND v.date IS NOT NULL
)
SELECT body_sha,
 max(CASE WHEN field='published_time' THEN date END) AS published_on,
 max(CASE WHEN field='published_time' THEN path END) AS published_path,
 max(CASE WHEN field='modified_time' THEN date END) AS modified_on,
 max(CASE WHEN field='modified_time' THEN path END) AS modified_path
FROM ranked WHERE choice=1 GROUP BY body_sha
