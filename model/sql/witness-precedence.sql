-- Precedence per person, not per source (red-f2). On a meeting, a witness row is superseded_by the same
-- person (family name, first initial or a nickname, one-letter slips in names of 5+ letters) stated by a
-- higher-ranked body: source priority, then record digest. Print entries labelled statements never match.
-- Its own step: as a CTE it re-ran the whole appearance resolution and exhausted the sort budget.
WITH people AS (
 SELECT w.witness_key,w.occasion,s.priority,w.record_sha_hex,p.family,p.initial
 FROM appearance_records_resolved w
 JOIN meeting_sources s ON s.kind='appearance' AND s.source=w.source
 JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex AND p.source=w.source AND p.ordinal=w.ordinal
 WHERE w.occasion LIKE 'meeting:%' AND NOT p.statement AND p.family IS NOT NULL
)
SELECT a.witness_key,min(b.witness_key) AS superseded_by
FROM people a JOIN people b ON a.occasion=b.occasion
 AND (b.priority<a.priority OR (b.priority=a.priority AND b.record_sha_hex<a.record_sha_hex))
WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
 AND (a.initial IS NULL OR b.initial IS NULL OR a.initial=b.initial
  -- Nicknames: Bob/Bill/Dick for Robert/William/Richard, Ted/Ned/Liz/Betsy for Edward/Elizabeth, Peggy.
  OR concat(least(a.initial,b.initial),greatest(a.initial,b.initial)) IN ('br','bw','dr','et','en','el','be','mp'))
GROUP BY a.witness_key
