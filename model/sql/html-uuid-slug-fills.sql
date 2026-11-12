-- ct-esuu: Senate HTML pages whose URL path ends in a bare UUID segment preceded by a descriptive
-- slug (for example /hearings/2021/11/business-meeting-pending-nominations/<uuid>, or redirecting to
-- /hearings/hearings-2021-11-business-meeting-pending-nominations-<uuid>/) retain their slug-derived
-- filename and any event document_kind / document_family / facts it states, without changing the
-- pinned filename_readings catalog version or touching generic container paths (/hearings/<uuid>).
-- Every large relation (saved_files, source_annotations, document_addresses) is scanned at most once.
WITH sibling_ranked AS (
 SELECT c.doc_key,s.filename,a.document_kind,a.document_family,a.facts,
  row_number() OVER(PARTITION BY c.doc_key ORDER BY s.saved_rank,s.source_id) AS rn
 FROM html_uuid_candidates c
 JOIN saved_files s ON s.component=c.component
 JOIN source_annotations a ON a.source_id=s.source_id
 WHERE s.format='html'
  AND coalesce(s.filename,'')<>''
  AND NOT regexp_like(s.filename,'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
), sibling_fills AS (
 SELECT doc_key AS sf_doc_key,filename AS sf_filename,
  document_kind AS sf_document_kind,document_family AS sf_document_family,facts AS sf_facts
 FROM sibling_ranked
 WHERE rn=1
), candidate_urls AS (
 SELECT doc_key,filename AS uuid_name,1 AS url_rank,regexp_replace(source_url,'[?#].*$','') AS clean_url
 FROM html_uuid_candidates WHERE source_url IS NOT NULL
 UNION ALL
 SELECT u.doc_key,u.filename AS uuid_name,2 AS url_rank,regexp_replace(da.url,'[?#].*$','') AS clean_url
 FROM html_uuid_candidates u JOIN document_addresses da ON da.component=u.component
 WHERE da.url IS NOT NULL
), extracted AS (
 SELECT doc_key,uuid_name,url_rank,clean_url,
  array_element(regexp_match(clean_url,'^https?://[^/]+(?:/.*)?/([^/]+)/+$'),1) AS trailing_seg,
  array_element(regexp_match(clean_url,'(?i)^https?://[^/]+(?:/.*)?/([^/]+)/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/*$'),1) AS parent_seg
 FROM candidate_urls
), qualified AS (
 SELECT doc_key,url_rank,clean_url,
  CASE
   WHEN trailing_seg IS NOT NULL
    AND strpos(lower(trailing_seg),lower(uuid_name))>0
    AND regexp_like(trailing_seg,'[A-Za-z]')
    AND NOT regexp_like(trailing_seg,'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    AND NOT regexp_like(trailing_seg,'(?i)^(?:files?|documents?|docs?|services?|downloads?|uploads?|media|assets?|attachments?|items?|nodes?|pages?|posts?|events?|hearings?|meetings?|press|releases?|news|articles?|publications?|reports?|library|content|view|detail|details|index)$')
   THEN 1
   WHEN parent_seg IS NOT NULL
    AND regexp_like(parent_seg,'[A-Za-z]')
    AND NOT regexp_like(parent_seg,'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    AND NOT regexp_like(parent_seg,'(?i)^(?:files?|documents?|docs?|services?|downloads?|uploads?|media|assets?|attachments?|items?|nodes?|pages?|posts?|events?|hearings?|meetings?|press|releases?|news|articles?|publications?|reports?|library|content|view|detail|details|index)$')
   THEN 2
  END AS mode_rank,
  CASE
   WHEN trailing_seg IS NOT NULL
    AND strpos(lower(trailing_seg),lower(uuid_name))>0
    AND regexp_like(trailing_seg,'[A-Za-z]')
    AND NOT regexp_like(trailing_seg,'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    AND NOT regexp_like(trailing_seg,'(?i)^(?:files?|documents?|docs?|services?|downloads?|uploads?|media|assets?|attachments?|items?|nodes?|pages?|posts?|events?|hearings?|meetings?|press|releases?|news|articles?|publications?|reports?|library|content|view|detail|details|index)$')
   THEN trailing_seg
   WHEN parent_seg IS NOT NULL
    AND regexp_like(parent_seg,'[A-Za-z]')
    AND NOT regexp_like(parent_seg,'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    AND NOT regexp_like(parent_seg,'(?i)^(?:files?|documents?|docs?|services?|downloads?|uploads?|media|assets?|attachments?|items?|nodes?|pages?|posts?|events?|hearings?|meetings?|press|releases?|news|articles?|publications?|reports?|library|content|view|detail|details|index)$')
   THEN parent_seg||'-'||lower(uuid_name)
  END AS filename
 FROM extracted
), picked AS (
 SELECT doc_key,filename,
  regexp_like(filename,'(?i)(^|[^a-z0-9])business[-_ ]meeting($|[^a-z0-9])') AS has_bm,
  regexp_like(filename,'(?i)(^|[^a-z0-9])field[-_ ]hearing($|[^a-z0-9])') AS has_fh,
  regexp_like(filename,'(?i)(^|[^a-z0-9])panel[-_ ]discussion($|[^a-z0-9])') AS has_pd,
  NOT regexp_like(filename,'(?i)(^|[^a-z0-9])business[-_ ]meeting($|[^a-z0-9])')
   AND regexp_like(filename,'(?i)(^|[^a-z0-9])nominations?($|[^a-z0-9])') AS has_nom,
  row_number() OVER(PARTITION BY doc_key ORDER BY mode_rank,url_rank,filename,clean_url) AS rn
 FROM qualified
 WHERE filename IS NOT NULL
), url_slug_fills AS (
 SELECT doc_key AS uf_doc_key,filename AS uf_filename,
  array_sort(array_distinct(array_concat(
   array_concat(
    CASE WHEN has_bm THEN arrow_cast(make_array('business-meeting'),'List(Utf8)')
     ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END,
    CASE WHEN has_fh THEN arrow_cast(make_array('field-hearing'),'List(Utf8)')
     ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END
   ),
   array_concat(
    CASE WHEN has_pd THEN arrow_cast(make_array('panel-discussion'),'List(Utf8)')
     ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END,
    CASE WHEN has_nom THEN arrow_cast(make_array('nomination'),'List(Utf8)')
     ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END
   )
  ))) AS uf_kinds,
  array_sort(array_distinct(array_concat(
   array_concat(
    CASE WHEN has_bm THEN make_array(
     named_struct('field','document_family','value','business-meeting'),
     named_struct('field','document_kind','value','business-meeting'))
     ELSE array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR))),1,0) END,
    CASE WHEN has_fh THEN make_array(
     named_struct('field','document_family','value','field-hearing'),
     named_struct('field','document_kind','value','field-hearing'))
     ELSE array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR))),1,0) END
   ),
   array_concat(
    CASE WHEN has_pd THEN make_array(
     named_struct('field','document_family','value','panel-discussion'),
     named_struct('field','document_kind','value','panel-discussion'))
     ELSE array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR))),1,0) END,
    CASE WHEN has_nom THEN make_array(
     named_struct('field','document_family','value','nomination'),
     named_struct('field','document_kind','value','nomination'))
     ELSE array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR))),1,0) END
   )
  ))) AS uf_facts
 FROM picked
 WHERE rn=1
)
SELECT c.doc_key,
 coalesce(sf.sf_filename,uf.uf_filename) AS filename,
 CASE WHEN sf.sf_doc_key IS NOT NULL THEN sf.sf_document_kind ELSE uf.uf_kinds END AS document_kind,
 CASE WHEN sf.sf_doc_key IS NOT NULL THEN sf.sf_document_family ELSE uf.uf_kinds END AS document_family,
 CASE WHEN sf.sf_doc_key IS NOT NULL THEN sf.sf_facts ELSE uf.uf_facts END AS facts
FROM sibling_fills sf
RIGHT JOIN (url_slug_fills uf RIGHT JOIN html_uuid_candidates c ON uf.uf_doc_key=c.doc_key)
 ON sf.sf_doc_key=c.doc_key
WHERE sf.sf_doc_key IS NOT NULL OR uf.uf_doc_key IS NOT NULL
