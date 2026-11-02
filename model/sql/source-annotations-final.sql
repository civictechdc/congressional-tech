WITH link_word_texts AS (
 -- A page titled with a link word ("Download", "Email") has no reading title either.
 SELECT DISTINCT x.t FROM (SELECT title AS t FROM page_facts UNION SELECT heading FROM page_facts) x
 JOIN page_signals g ON g.kind='link_word' AND length(x.t)<=64
  AND regexp_like(regexp_replace(trim(x.t),'\s+',' ','g'),g.pattern)
), pages AS (
 SELECT p.body_sha,p.status,p.content_date,CASE WHEN wt.t IS NULL THEN p.title END AS title,
  CASE WHEN wh.t IS NULL THEN p.heading END AS heading
 FROM page_facts p LEFT JOIN link_word_texts wt ON wt.t=p.title LEFT JOIN link_word_texts wh ON wh.t=p.heading
), packages AS (
 SELECT source_id,min(package_id) AS package_id FROM source_annotation_addresses
 WHERE package_id IS NOT NULL AND NOT publisher GROUP BY source_id
)
SELECT s.source_id,
 CASE WHEN f.status='completed' AND coalesce(array_length(f.document_kind),0)>0
 THEN array_sort(array_distinct(f.document_kind)) ELSE coalesce(k.document_kind,{{EMPTY_STRINGS}}) END AS document_kind,
 coalesce(CASE WHEN f.status='completed' THEN array_sort(array_distinct(f.document_family)) END,{{EMPTY_STRINGS}}) AS document_family,
 CASE WHEN f.status='completed' THEN f.congress END AS congress,
 coalesce(u.package_id,CASE WHEN f.status='completed' THEN f.package_id END) AS package_id,
 CASE WHEN f.status='completed' THEN f.filename_date END AS filename_date,
 CASE WHEN p.status='completed' THEN cast(p.content_date AS DATE) END AS content_date,
 coalesce(CASE WHEN p.status='completed' AND nullif(trim(p.title),'') IS NOT NULL THEN p.title END,
 CASE WHEN p.status='completed' AND nullif(trim(p.heading),'') IS NOT NULL THEN p.heading END,k.listing_title) AS title,
 coalesce(CASE WHEN p.status='completed' AND nullif(trim(p.title),'') IS NOT NULL THEN p.title END,
 CASE WHEN p.status='completed' AND nullif(trim(p.heading),'') IS NOT NULL THEN p.heading END) AS reading_title,
 k.listing_title,
 coalesce(m.meeting_keys,{{EMPTY_STRINGS}}) AS meeting_keys,
 coalesce(CASE WHEN f.status='completed' THEN array_sort(array_distinct(f.measure_keys)) END,{{EMPTY_STRINGS}}) AS measure_keys,
 coalesce(CASE WHEN f.status='completed' THEN array_sort(array_distinct(f.bioguide_ids)) END,{{EMPTY_STRINGS}}) AS bioguide_ids,
 coalesce(c.committee_keys,{{EMPTY_STRINGS}}) AS committee_keys,
 array_sort(array_distinct(array_concat(coalesce(c.chambers,{{EMPTY_STRINGS}}),coalesce(m.chambers,{{EMPTY_STRINGS}})))) AS chambers,
 coalesce(d.facts,{{EMPTY_FACTS}}) AS facts,f.status AS filename_status
FROM packages u RIGHT JOIN (
 source_annotation_meetings m RIGHT JOIN (
  source_annotation_facts d RIGHT JOIN (
   source_annotation_committees c RIGHT JOIN (
    source_annotation_publisher k RIGHT JOIN (
     pages p RIGHT JOIN (
      source_files s LEFT JOIN source_filename_readings f ON s.source_id=f.source_id
     ) ON s.body_sha=encode(p.body_sha,'hex')
    ) ON s.source_id=k.source_id
   ) ON s.source_id=c.source_id
  ) ON s.source_id=d.source_id
 ) ON s.source_id=m.source_id
) ON s.source_id=u.source_id
