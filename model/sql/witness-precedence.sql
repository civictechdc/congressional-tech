-- Precedence per person, not per source (red-f2). On a meeting, a witness row is superseded_by the same
-- person stated by a higher-ranked body (source priority, then record digest). The same person: the same
-- family name (one-letter slips in names of 5+ letters), and given names that agree as written, through a
-- one-way nickname, by a shared first three letters, or as an initial; a row with no given name matches only
-- when that family name is unique among the higher rows (red-f3: Barbara and Joan Smith are not Robert and
-- John Smith). Print entries labelled statements are matched too: a statement by someone the meeting's own
-- list names is that witness. Its own step: as a CTE it re-ran the whole appearance resolution.
WITH people AS (
 SELECT w.witness_key,w.occasion,s.priority,w.record_sha_hex,p.family,p.given,p.given_canon
 FROM appearance_records_resolved w
 JOIN meeting_sources s ON s.kind='appearance' AND s.source=w.source
 JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex AND p.source=w.source AND p.ordinal=w.ordinal
 WHERE w.occasion LIKE 'meeting:%' AND p.family IS NOT NULL
), pairs AS (
 SELECT a.witness_key,a.given IS NULL AS open_given,b.witness_key AS higher,b.family AS higher_family
 FROM people a JOIN people b ON a.occasion=b.occasion
  AND (b.priority<a.priority OR (b.priority=a.priority AND b.record_sha_hex<a.record_sha_hex))
 WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
  AND (a.given IS NULL OR b.given IS NULL OR a.given_canon=b.given_canon
   OR (length(a.given)>=3 AND length(b.given)>=3 AND substr(a.given,1,3)=substr(b.given,1,3))
   OR (length(a.given)=1 AND a.given=substr(b.given,1,1)) OR (length(b.given)=1 AND b.given=substr(a.given,1,1)))
)
SELECT witness_key,min(higher) AS superseded_by
FROM pairs
GROUP BY witness_key
-- An open given name names nobody in particular when the higher rows hold several people of that family.
HAVING NOT bool_or(open_given) OR count(DISTINCT higher)=1
