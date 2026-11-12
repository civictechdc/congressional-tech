-- DM 7.5: page facts whose title or heading is a link word ("Download", "Email"; title-rules.json) give no reading title.
-- Strip GPO's literal leading '- ' prefix (cat2-x47u F3), Senate ColdFusion SR-only 'Hearing status...: Hearing title...'
-- prefixes on <h1> (cat2-x47u P2-9), and extract Rules Committee Print titles from <amendment-doc> XML text_head (cat2-x47u F4).
WITH link_word_texts AS (
 SELECT DISTINCT x.t FROM (
  SELECT CASE
   WHEN xml_root='amendment-doc' AND nullif(trim(coalesce(title,'')),'') IS NULL AND text_head IS NOT NULL
    THEN nullif(trim((regexp_match(regexp_replace(text_head,'\s+',' ','g'),'(?i)(Rules Committee Print\s+[0-9]+\s*[-–—]+\s*[0-9]+(?:\s+(?:Text of|for|to)\b.{1,320}?)?)(?:\.?\s+(?:Offered by\b|1[0-9]{2}th\b|(?:January|February|March|April|May|June|July|August|September|October|November|December|[A-Z]{3,9})\s+[0-9]{1,2},\s+20[0-9]{2}\b|\[?\s*(?:Showing|Reflecting|Based on)\b|At\s+the\s+end\s+of\b|[0-9]+\.\s*Short\s+title\b|TITLE\s+I\b|DIVISION\s+A\b|Section\s+1\b|SEC\.\s+1\b|That\s+at\b|Resolved\b|Page\s+1\b|In\s+the\s+(?:House|Senate)\b|Be\s+it\s+enacted\b|Strike\s+all\b|Page\s+and\s+line\b|[0-9]+\s+(?:SECTION\b|SEC\.|In\s+general))|$)'))[1]),'')
   ELSE nullif(trim(regexp_replace(title,'^\s*[-–—]+\s+','')),'')
  END AS t FROM page_facts
  UNION
  SELECT nullif(trim(regexp_replace(regexp_replace(regexp_replace(heading,'^\s*[-–—]+\s+',''),'(?i)^Hearing\s+status\s*([^:]+:\s*)Hearing\s+title\s*','$1'),'(?i)^Hearing\s+title\s*','')),'') AS t FROM page_facts
 ) x
 JOIN title_rules g ON g.kind='link_word' AND length(x.t)<=64
  AND regexp_like(regexp_replace(trim(x.t),'\s+',' ','g'),g.pattern)
)
SELECT p.body_sha,p.status,p.content_date,
 CASE WHEN wt.t IS NULL THEN p.clean_title END AS title,
 CASE WHEN wh.t IS NULL THEN p.clean_heading END AS heading
FROM (
 SELECT body_sha,status,content_date,
  CASE
   WHEN xml_root='amendment-doc' AND nullif(trim(coalesce(title,'')),'') IS NULL AND text_head IS NOT NULL
    THEN nullif(trim((regexp_match(regexp_replace(text_head,'\s+',' ','g'),'(?i)(Rules Committee Print\s+[0-9]+\s*[-–—]+\s*[0-9]+(?:\s+(?:Text of|for|to)\b.{1,320}?)?)(?:\.?\s+(?:Offered by\b|1[0-9]{2}th\b|(?:January|February|March|April|May|June|July|August|September|October|November|December|[A-Z]{3,9})\s+[0-9]{1,2},\s+20[0-9]{2}\b|\[?\s*(?:Showing|Reflecting|Based on)\b|At\s+the\s+end\s+of\b|[0-9]+\.\s*Short\s+title\b|TITLE\s+I\b|DIVISION\s+A\b|Section\s+1\b|SEC\.\s+1\b|That\s+at\b|Resolved\b|Page\s+1\b|In\s+the\s+(?:House|Senate)\b|Be\s+it\s+enacted\b|Strike\s+all\b|Page\s+and\s+line\b|[0-9]+\s+(?:SECTION\b|SEC\.|In\s+general))|$)'))[1]),'')
   ELSE nullif(trim(regexp_replace(title,'^\s*[-–—]+\s+','')),'')
  END AS clean_title,
  nullif(trim(regexp_replace(regexp_replace(regexp_replace(heading,'^\s*[-–—]+\s+',''),'(?i)^Hearing\s+status\s*([^:]+:\s*)Hearing\s+title\s*','$1'),'(?i)^Hearing\s+title\s*','')),'') AS clean_heading
 FROM page_facts
) p
LEFT JOIN link_word_texts wt ON wt.t=p.clean_title
LEFT JOIN link_word_texts wh ON wh.t=p.clean_heading
