-- The six D5 detail columns, one row per saved html document. A body read at several
-- addresses is read once; `resolved` resolves declared_url against each document's own
-- address (declared base first). An html document with no reading is `unread`: a gap.
WITH docs AS (
 SELECT doc_key,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,source_url
 FROM base_normalized WHERE format='html' AND body_hex IS NOT NULL
), content AS (
 SELECT body_sha,
  max(CASE WHEN f['field']='main_content:outcome' THEN f['value'] END) AS outcome,
  max(CASE WHEN f['field']='main_content:selector' THEN f['value'] END) AS selector,
  max(CASE WHEN f['field']='main_content:sha256' THEN f['value'] END) AS text_sha256
 FROM (SELECT body_sha,unnest(fields) AS f FROM html_metadata_readings)
 WHERE starts_with(f['field'],'main_content:') GROUP BY body_sha
), reading AS (
 -- A reading without a main-content outcome (reader error, size limit) is failed, not unread.
 SELECT h.body_sha,h.base_href,h.text_bytes,h.text_head,coalesce(c.outcome,'failed') AS outcome,c.selector,c.text_sha256
 FROM html_metadata_readings h LEFT JOIN content c ON c.body_sha=h.body_sha
), entries AS (
 SELECT d.doc_key,v.field,v.value,v.format,v.path,v.date,v.precision,
  CASE WHEN v.field='declared_url' AND d.source_url IS NOT NULL THEN url_resolve(trim(v.value),
   CASE WHEN r.base_href IS NOT NULL THEN coalesce(url_resolve(r.base_href,d.source_url),d.source_url) ELSE d.source_url END) END AS resolved,
  (v.field='description' AND v.path=pd.path) OR (v.field='published_time' AND v.path=pt.published_path)
   OR (v.field='modified_time' AND v.path=pt.modified_path) OR v.field='section' AS selected,
  coalesce(f.number,99) AS rank
 FROM docs d JOIN page_metadata_values v ON v.body_sha=d.body_sha
 LEFT JOIN reading r ON r.body_sha=d.body_sha
 LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
 LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
 LEFT JOIN page_signals f ON f.kind='description_format' AND regexp_like(v.format,f.pattern)
), listed AS (
 SELECT doc_key,
  array_agg(named_struct('field',field,'value',value,'format',format,'path',path,'date',date,'precision',precision,
   'resolved',resolved,'selected',coalesce(selected,false)) ORDER BY field,rank,path) AS page_metadata
 FROM entries GROUP BY doc_key
), labels AS (
 SELECT doc_key,array_agg(value ORDER BY path) AS publisher_labels
 FROM (SELECT doc_key,trim(value) AS value,min(path) AS path FROM entries WHERE field='section' AND trim(value)<>'' GROUP BY doc_key,trim(value))
 GROUP BY doc_key
)
SELECT d.doc_key,pd.description,pt.published_on,pt.modified_on,
 coalesce(l.publisher_labels,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS publisher_labels,
 coalesce(li.page_metadata,array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR),
  'format',cast(NULL AS VARCHAR),'path',cast(NULL AS VARCHAR),'date',cast(NULL AS DATE),'precision',cast(NULL AS VARCHAR),
  'resolved',cast(NULL AS VARCHAR),'selected',cast(NULL AS BOOLEAN))),1,0)) AS page_metadata,
 named_struct('outcome',CASE r.outcome WHEN 'fallback_required' THEN 'fallback' WHEN 'marked' THEN 'marked'
   WHEN 'marked_no_content' THEN 'marked_no_content' WHEN 'failed' THEN 'failed' WHEN 'none' THEN 'none'
   ELSE 'unread' END,
  'selector',r.selector,'text_sha256',r.text_sha256,'text_bytes',r.text_bytes,
  'snippet',CASE WHEN r.outcome IN ('marked','marked_no_content') THEN r.text_head END) AS main_content
FROM docs d LEFT JOIN reading r ON r.body_sha=d.body_sha
LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
LEFT JOIN labels l ON l.doc_key=d.doc_key
LEFT JOIN listed li ON li.doc_key=d.doc_key
