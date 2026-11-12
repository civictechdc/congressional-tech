WITH contexts AS (
 SELECT * FROM document_page_context_ranked
),
declarations AS (
 SELECT v.*,n.field_count FROM page_metadata_field_counts n
 JOIN page_metadata_values v ON v.body_sha=n.body_sha AND v.field=n.field
),
qualified AS (
 SELECT d.doc_key,v.field,v.value,v.format,v.path,v.date,v.precision,c.context_url,c.context_position,r.base_href,
  coalesce(c.context_count*v.field_count>512 OR c.context_bytes+c.context_count*
   (octet_length(v.value)+coalesce(octet_length(r.base_href),0))>65536,false) AS contexts_omitted,
  (v.field='description' AND v.path=pd.path) OR (v.field='published_time' AND v.path=pt.published_path)
   OR (v.field='modified_time' AND v.path=pt.modified_path) OR v.field='section' AS selected,
  coalesce(f.number,99) AS rank
 FROM page_metadata_documents d JOIN declarations v ON v.body_sha=d.body_sha
 -- Keep one placeholder when the address count alone exceeds the detail budget.
 LEFT JOIN contexts c ON c.doc_key=d.doc_key AND v.field='declared_url'
  AND (c.context_count*v.field_count<=512 OR c.context_position=1)
 LEFT JOIN html_metadata_readings r ON r.body_sha=d.body_sha
 LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
 LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
 LEFT JOIN page_signals f ON f.kind='description_format' AND regexp_like(v.format,f.pattern)
),
eligible AS (
 SELECT * EXCLUDE(context_url,base_href),
  CASE WHEN NOT contexts_omitted THEN context_url END AS context_url,
  CASE WHEN NOT contexts_omitted THEN base_href END AS base_href
 FROM qualified WHERE NOT contexts_omitted OR context_position=1
),
entries AS (
 SELECT * EXCLUDE(base_href,context_position),
  CASE WHEN context_url IS NOT NULL THEN url_resolve(trim(value),
   coalesce(url_resolve(base_href,context_url),context_url)) END AS resolved
 FROM eligible
),
sized AS (
 -- JSON supplies the escaped scalar sizes. Reserve 128 bytes per entry for keys,
 -- null address fields and punctuation. Account for the actual resolved address.
 SELECT *,
  128+octet_length(json_array(field,value,format,path,cast(date AS VARCHAR),precision,cast(selected AS VARCHAR))) AS literal_bytes,
  octet_length(json_array(context_url,resolved)) AS address_bytes,
  row_number() OVER (PARTITION BY doc_key,field,path ORDER BY context_url,value,format) AS literal_position
 FROM entries
)
SELECT * FROM sized
