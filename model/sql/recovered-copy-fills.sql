-- DM 7.5: what a recovered copy's own link says about the document it joined, one row per
-- document. document-normalized.sql shows the copy's own value and takes one of these only where
-- the copy has none; a differing value stays on that link's source annotation.
WITH linked AS (
 SELECT l.component,f.source_id,f.source_url,nullif(f.filename,'') AS filename,coalesce(t.title,a.title) AS title,
  a.document_kind,a.document_family,a.congress,a.filename_date,a.package_id,a.facts
 FROM (SELECT DISTINCT l.source_id,l.body_sha FROM recovered_copy_links l JOIN recovered_copy_members m USING(source_id)) r
 JOIN final_source_labels l ON l.source_id=r.source_id
 JOIN source_files f ON f.source_id=r.source_id
 JOIN source_annotations a ON a.source_id=r.source_id
 -- The recovered body's own page title, read for these bodies only (candidate semi-join).
 LEFT JOIN (SELECT encode(p.body_sha,'hex') AS body_sha,
  CASE
   WHEN nullif(trim(max(p.heading)),'') IS NOT NULL AND (
    nullif(trim(max(p.title)),'') IS NULL
    OR (
     NOT regexp_like(trim(max(p.heading)),'(?i)^(?:(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+)?(?:(?:committee|subcommittee|select\s+committee|special\s+committee|joint\s+committee)\s+on\s+[^|–—-]+|hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?|roundtables?|search)$')
     AND (
      regexp_like(trim(max(p.title)),'(?i)^(?:hearings?|events?|news|press\s+releases?|home|committee\s+hearings?|calendar|business\s+meetings?|markups?)\s*[|–—-]')
      OR (length(trim(max(p.heading)))>length(trim(max(p.title))) AND regexp_like(trim(max(p.title)),'(?i)^(?:(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+)?(?:senate|house(?:\s+of\s+representatives)?)\s+(?:(?:select|special|permanent\s+select|joint)\s+)?committee\s+on\s+[^|:]+$'))
      OR (length(trim(max(p.heading)))>=12 AND regexp_like(trim(max(p.title)),'(?:\.\.\.|…)\s*(?:\||$)'))
     )
    )
   ) THEN trim(max(p.heading))
   ELSE nullif(trim(max(p.title)),'')
  END AS title
  FROM source_annotation_pages p JOIN (SELECT DISTINCT decode(body_sha,'hex') AS sha256 FROM recovered_copy_links) s ON p.body_sha=s.sha256
  WHERE p.status='completed' GROUP BY p.body_sha) t ON t.body_sha=r.body_sha
), fields AS (
 SELECT component,min(filename) AS filename,min(title) AS title,
  array_sort(array_distinct(flatten(array_agg(document_kind)))) AS document_kind,
  array_sort(array_distinct(flatten(array_agg(document_family)))) AS document_family,
  min(congress) AS congress,min(filename_date) AS filename_date,min(package_id) AS package_id
 FROM linked GROUP BY component
), facts AS (
 SELECT component,facts,row_number() OVER(PARTITION BY component ORDER BY source_url,source_id) AS preference
 FROM linked WHERE coalesce(array_length(facts),0)>0
)
SELECT f.*,x.facts FROM facts x RIGHT JOIN fields f ON x.component=f.component AND x.preference=1
