-- One row per saved HTML document. A single body reading supplies every qualifying
-- capture address for that exact body. The declared address stays literal alongside
-- each resolution. A missing capture context leaves the declaration unresolved.
WITH content AS (
 SELECT body_sha,
  max(CASE WHEN f['field']='main_content:outcome' THEN f['value'] END) AS outcome,
  max(CASE WHEN f['field']='main_content:selector' THEN f['value'] END) AS selector,
  max(CASE WHEN f['field']='main_content:sha256' THEN f['value'] END) AS text_sha256,
  max(CASE WHEN f['field']='main_content:text' THEN f['value'] END) AS selected_text,
  max(CASE WHEN f['field']='main_content:reason' THEN f['value'] END) AS reason,
  max(CASE WHEN f['field']='detail_facts_limit' THEN f['value'] END) AS detail_facts_limit
 FROM (SELECT body_sha,unnest(fields) AS f FROM html_metadata_readings)
 WHERE starts_with(f['field'],'main_content:') OR f['field']='detail_facts_limit' GROUP BY body_sha
),
reading AS (
 -- A reading without a main-content outcome (reader error, size limit) is failed, not unread.
 SELECT h.body_sha,h.parser_version,h.status,h.base_href,h.text_bytes,h.text_head,coalesce(c.outcome,'failed') AS outcome,
  c.selector,c.text_sha256,c.selected_text,coalesce(c.reason,h.error_type) AS reason,c.detail_facts_limit
 FROM html_metadata_readings h LEFT JOIN content c ON c.body_sha=h.body_sha
),
decisions AS (
 SELECT u.body_sha256,u.id,u.parser_version,u.reason,row_number() OVER (
  PARTITION BY u.body_sha256
  ORDER BY CASE WHEN u.parser_version=p.version THEN 0 ELSE 1 END,
           cast(u.decided_at AS TIMESTAMP WITH TIME ZONE) DESC NULLS LAST,u.id) AS preference
 FROM parser_versions p
 JOIN (accepted_versions v JOIN active_unreadable u ON u.parser=v.parser AND u.parser_version=v.version)
 ON p.parser=v.parser
 WHERE p.parser='html_metadata' AND u.body_sha256 IS NOT NULL
),
measured AS (
 SELECT e.*,n.expanded_bytes,n.base_bytes,n.selected_bytes
 FROM document_page_metadata_sizes n JOIN document_page_metadata_entries e ON e.doc_key=n.doc_key
),
listed AS (
 SELECT doc_key,
  array_agg(named_struct('field',field,'value',value,'format',format,'path',path,'date',date,'precision',precision,
   'resolved',CASE WHEN expanded_bytes<=65536 THEN resolved END,'selected',coalesce(selected,false),
   'context_url',CASE WHEN expanded_bytes<=65536 THEN context_url END) ORDER BY field,rank,path,context_url)
   -- Keep the exact pointers for summaries before spending the budget on alternatives.
   FILTER (WHERE expanded_bytes<=65536 OR (literal_position=1 AND
    (base_bytes<=65536 OR (selected AND selected_bytes<=65536)))) AS page_metadata,
  bool_or(contexts_omitted OR expanded_bytes>65536) AS evidence_limited
 FROM measured GROUP BY doc_key
),
labels AS (
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
FROM page_metadata_documents d LEFT JOIN reading r ON r.body_sha=d.body_sha
LEFT JOIN decisions u ON u.body_sha256=d.body_hex AND u.preference=1
LEFT JOIN page_descriptions pd ON pd.doc_key=d.doc_key
LEFT JOIN page_dates pt ON pt.body_sha=d.body_sha
LEFT JOIN labels l ON l.body_sha=d.body_sha
LEFT JOIN listed li ON li.doc_key=d.doc_key
