-- Retained publisher repair: never split query, fragment, whitespace or wrapper layouts.
WITH literals AS (SELECT DISTINCT href FROM link_inputs), wrapped AS (
 SELECT l.href,count(w.id) AS wrappers FROM url_rules w RIGHT JOIN literals l
 ON w.kind='wrapper' AND regexp_like(l.href,w.pattern) GROUP BY l.href
), matches AS (
 SELECT l.href,count(r.id) AS repair_matches,
 max(regexp_replace(l.href,r.pattern,r.replacement,'g')) AS repaired
 FROM url_rules r RIGHT JOIN wrapped l ON r.kind='repair' AND l.wrappers=0
 AND regexp_like(l.href,'(?i)^https?://.+https?://')
 AND NOT regexp_like(l.href,'[[:space:]?#]') AND regexp_like(l.href,r.pattern)
 GROUP BY l.href
)
SELECT href,repair_matches,CASE WHEN repair_matches=1 THEN string_to_array(substr(repaired,2),chr(10))
 ELSE make_array(href) END AS parts FROM matches
