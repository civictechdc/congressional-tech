-- One row per saved HTML document. A single body reading supplies every qualifying
-- capture address for that exact body. The declared address stays literal alongside
-- each resolution. A missing capture context leaves the declaration unresolved.
WITH docs AS (
 SELECT doc_key,body_hex,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha
 FROM base_normalized WHERE format='html' AND body_hex IS NOT NULL
), contexts AS (
 SELECT *,count(*) OVER (PARTITION BY doc_key) AS context_count,
  sum(octet_length(context_url)) OVER (PARTITION BY doc_key) AS context_bytes,
  row_number() OVER (PARTITION BY doc_key ORDER BY context_url) AS context_position
 FROM (
  SELECT DISTINCT d.doc_key,c.context_url
  FROM docs d JOIN (SELECT DISTINCT body_sha FROM page_metadata_values WHERE field='declared_url') declared
  ON declared.body_sha=d.body_sha
  JOIN document_identities i ON d.doc_key=i.document_id
  JOIN document_members m ON m.component=i.component AND m.body_sha=d.body_hex
  JOIN capture_sources c ON c.source_id=m.source_id AND c.body_sha=m.body_sha
  WHERE c.is_real_file AND c.outcome NOT IN ('reference','saved-record') AND c.context_url IS NOT NULL
 ) distinct_contexts
), declarations AS (
 SELECT *,count(*) OVER (PARTITION BY body_sha,field) AS field_count FROM page_metadata_values
), content AS (
 SELECT body_sha,
  max(CASE WHEN f['field']='main_content:outcome' THEN f['value'] END) AS outcome,
  max(CASE WHEN f['field']='main_content:selector' THEN f['value'] END) AS selector,
  max(CASE WHEN f['field']='main_content:sha256' THEN f['value'] END) AS text_sha256,
  max(CASE WHEN f['field']='main_content:text' THEN f['value'] END) AS selected_text,
  max(CASE WHEN f['field']='main_content:reason' THEN f['value'] END) AS reason,
  max(CASE WHEN f['field']='detail_facts_limit' THEN f['value'] END) AS detail_facts_limit
 FROM (SELECT body_sha,unnest(fields) AS f FROM html_metadata_readings)
 WHERE starts_with(f['field'],'main_content:') OR f['field']='detail_facts_limit' GROUP BY body_sha
), reading AS (
 -- A reading without a main-content outcome (reader error, size limit) is failed, not unread.
 SELECT h.body_sha,h.parser_version,h.status,h.base_href,h.text_bytes,h.text_head,coalesce(c.outcome,'failed') AS outcome,
  c.selector,c.text_sha256,c.selected_text,coalesce(c.reason,h.error_type) AS reason,c.detail_facts_limit
 FROM html_metadata_readings h LEFT JOIN content c ON c.body_sha=h.body_sha
), decisions AS (
 SELECT u.body_sha256,u.id,u.parser_version,u.reason,row_number() OVER (
  PARTITION BY u.body_sha256
  ORDER BY CASE WHEN u.parser_version=p.version THEN 0 ELSE 1 END,
           cast(u.decided_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,u.id) AS preference
 FROM parser_versions p
 JOIN (accepted_versions v JOIN active_unreadable u ON u.parser=v.parser AND u.parser_version=v.version)
 ON p.parser=v.parser
 WHERE p.parser='html_metadata' AND u.body_sha256 IS NOT NULL
), qualified AS (
 SELECT d.doc_key,v.field,v.value,v.format,v.path,v.date,v.precision,c.context_url,c.context_position,r.base_href,
  coalesce(c.context_count*v.field_count>512 OR c.context_bytes+c.context_count*
   (octet_length(v.value)+coalesce(octet_length(r.base_href),0))>65536,false) AS contexts_omitted,
  (v.field='description' AND v.path=pd.path) OR (v.field='published_time' AND v.path=pt.published_path)
   OR (v.field='modified_time' AND v.path=pt.modified_path) OR v.field='section' AS selected,
  coalesce(f.number,99) AS rank
 FROM docs d JOIN declarations v ON v.body_sha=d.body_sha
 -- Keep one placeholder when the address count alone exceeds the detail budget.
 LEFT JOIN contexts c ON c.doc_key=d.doc_key AND v.field='declared_url'
  AND (c.context_count*v.field_count<=512 OR c.context_position=1)
 LEFT JOIN html_metadata_readings r ON r.body_sha=d.body_sha
 LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
 LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
 LEFT JOIN page_signals f ON f.kind='description_format' AND regexp_like(v.format,f.pattern)
), eligible AS (
 SELECT * EXCLUDE(context_url,base_href),
  CASE WHEN NOT contexts_omitted THEN context_url END AS context_url,
  CASE WHEN NOT contexts_omitted THEN base_href END AS base_href
 FROM qualified WHERE NOT contexts_omitted OR context_position=1
), entries AS (
 SELECT * EXCLUDE(base_href,context_position),
  CASE WHEN context_url IS NOT NULL THEN url_resolve(trim(value),
   coalesce(url_resolve(base_href,context_url),context_url)) END AS resolved
 FROM eligible
), sized AS (
 -- JSON supplies the escaped scalar sizes. Reserve 128 bytes per entry for keys,
 -- null address fields and punctuation. Account for the actual resolved address.
 SELECT *,
  128+octet_length(json_array(field,value,format,path,cast(date AS VARCHAR),precision,cast(selected AS VARCHAR))) AS literal_bytes,
  octet_length(json_array(context_url,resolved)) AS address_bytes,
  row_number() OVER (PARTITION BY doc_key,field,path ORDER BY context_url) AS literal_position
 FROM entries
), measured AS (
 SELECT *,
  sum(literal_bytes+address_bytes) OVER (PARTITION BY doc_key) AS expanded_bytes,
  sum(CASE WHEN literal_position=1 THEN literal_bytes ELSE 0 END) OVER (PARTITION BY doc_key) AS base_bytes,
  sum(CASE WHEN literal_position=1 AND selected THEN literal_bytes ELSE 0 END) OVER (PARTITION BY doc_key) AS selected_bytes
 FROM sized
), listed AS (
 SELECT doc_key,
  array_agg(named_struct('field',field,'value',value,'format',format,'path',path,'date',date,'precision',precision,
   'resolved',CASE WHEN expanded_bytes<=65536 THEN resolved END,'selected',coalesce(selected,false),
   'context_url',CASE WHEN expanded_bytes<=65536 THEN context_url END) ORDER BY field,rank,path,context_url)
   -- Keep the exact pointers for summaries before spending the budget on alternatives.
   FILTER (WHERE expanded_bytes<=65536 OR (literal_position=1 AND
    (base_bytes<=65536 OR (selected AND selected_bytes<=65536)))) AS page_metadata,
  bool_or(contexts_omitted OR expanded_bytes>65536) AS evidence_limited
 FROM measured GROUP BY doc_key
), labels AS (
 SELECT body_sha,array_agg(value ORDER BY path) AS publisher_labels
 FROM (SELECT body_sha,trim(value) AS value,min(path) AS path FROM page_metadata_values
       WHERE field='section' AND trim(value)<>'' GROUP BY body_sha,trim(value))
 GROUP BY body_sha
)
SELECT d.doc_key,
 CASE WHEN array_length(li.page_metadata)>0 THEN pd.description END AS description,
 CASE WHEN array_length(li.page_metadata)>0 THEN pt.published_on END AS published_on,
 CASE WHEN array_length(li.page_metadata)>0 THEN pt.modified_on END AS modified_on,
 coalesce(CASE WHEN array_length(li.page_metadata)>0 THEN l.publisher_labels END,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS publisher_labels,
 coalesce(li.page_metadata,array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR),
  'format',cast(NULL AS VARCHAR),'path',cast(NULL AS VARCHAR),'date',cast(NULL AS DATE),'precision',cast(NULL AS VARCHAR),
  'resolved',cast(NULL AS VARCHAR),'selected',cast(NULL AS BOOLEAN),'context_url',cast(NULL AS VARCHAR))),1,0)) AS page_metadata,
 named_struct('outcome',CASE r.outcome WHEN 'fallback_required' THEN 'fallback' WHEN 'marked' THEN 'marked'
   WHEN 'marked_no_content' THEN 'marked_no_content' WHEN 'failed' THEN 'failed' WHEN 'none' THEN 'none'
   ELSE CASE WHEN u.id IS NOT NULL THEN 'unreadable' ELSE 'unread' END END,
  'selector',r.selector,'text_sha256',r.text_sha256,'text_bytes',r.text_bytes,
  'snippet',CASE WHEN r.outcome IN ('marked','marked_no_content') THEN r.text_head END,
  'reader_version',coalesce(r.parser_version,u.parser_version),
  'reading_status',coalesce(r.status,CASE WHEN u.id IS NOT NULL THEN 'unreadable' END),
  'reason',CASE WHEN r.body_sha IS NOT NULL THEN r.reason ELSE u.reason END,
  'facts_limited',r.detail_facts_limit IS NOT NULL,'text_available',r.selected_text IS NOT NULL,
  'decision_id',CASE WHEN r.body_sha IS NULL THEN u.id END,
  'evidence_limited',coalesce(li.evidence_limited,false)) AS main_content,
 r.selected_text
FROM docs d LEFT JOIN reading r ON r.body_sha=d.body_sha
LEFT JOIN decisions u ON u.body_sha256=d.body_hex AND u.preference=1
LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
LEFT JOIN labels l ON l.body_sha=d.body_sha
LEFT JOIN listed li ON li.doc_key=d.doc_key
