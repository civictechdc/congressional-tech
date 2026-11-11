-- DM 7.5: page facts whose title or heading is a link word ("Download", "Email"; title-rules.json) give no reading title.
WITH link_word_texts AS (
 SELECT DISTINCT x.t FROM (SELECT title AS t FROM page_facts UNION SELECT heading FROM page_facts) x
 JOIN title_rules g ON g.kind='link_word' AND length(x.t)<=64
  AND regexp_like(regexp_replace(trim(x.t),'\s+',' ','g'),g.pattern)
)
SELECT p.body_sha,p.status,p.content_date,CASE WHEN wt.t IS NULL THEN p.title END AS title,
 CASE WHEN wh.t IS NULL THEN p.heading END AS heading
FROM page_facts p LEFT JOIN link_word_texts wt ON wt.t=p.title LEFT JOIN link_word_texts wh ON wh.t=p.heading
