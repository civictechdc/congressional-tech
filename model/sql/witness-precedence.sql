-- Precedence per person, not per source (red-f2). On a meeting, a witness row is superseded_by the same
-- person stated by a higher-ranked body (source priority, then record digest, then ordinal). The same person:
-- the same family name (one-letter slips in names of 5+ letters), and given names that agree as written, through a
-- one-way nickname, by a shared first three letters, or as an initial; a row with no given name matches only
-- when that family name is unique among the higher rows (red-f3: Barbara and Joan Smith are not Robert and
-- John Smith). Print entries labelled statements are matched too: a statement by someone the meeting's own
-- list names is that witness. Within one record, collapse repeat entries only when their appearance facts agree.
-- Its own step: as a CTE it re-ran the whole appearance resolution.
WITH people AS (
 SELECT w.witness_key,w.occasion,s.priority,w.source,w.record_sha_hex,w.ordinal,p.statement,p.family,p.given,p.given_canon,
  sha256(json_array(w.position,w.organization,w.on_behalf_of,w.location,w.panel,w.panel_order,
   w.witness_type,w.testified,w.bioguide_id,array_sort(array_distinct(w.document_urls)))) AS occurrence_facts
 FROM appearance_records_resolved w
 JOIN meeting_sources s ON s.kind='appearance' AND s.source=w.source
 JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex AND p.source=w.source AND p.ordinal=w.ordinal
 WHERE p.family IS NOT NULL
), pairs AS (
 SELECT
  a.witness_key,
  a.given IS NULL AS open_given,
  b.witness_key AS higher,
  coalesce(b.family||'|'||substr(b.given_canon,1,3),b.witness_key) AS higher_person_key,
  first_value(b.witness_key) OVER (
   PARTITION BY a.witness_key
   ORDER BY b.priority ASC,b.record_sha_hex ASC,b.ordinal ASC
  ) AS root_higher
 FROM people a JOIN people b ON a.occasion=b.occasion
  AND ((a.occasion LIKE 'meeting:%' AND (b.priority<a.priority OR (b.priority=a.priority AND b.record_sha_hex<a.record_sha_hex)))
   -- A list can repeat a witness or list them in separate roles (ct-x78c). Keep distinct facts and statements.
   OR (b.source=a.source AND b.record_sha_hex=a.record_sha_hex AND b.ordinal<a.ordinal
    AND b.occurrence_facts=a.occurrence_facts AND NOT a.statement AND NOT b.statement))
 WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
  AND (a.given IS NULL OR b.given IS NULL OR a.given_canon=b.given_canon
   OR (length(a.given)>=3 AND length(b.given)>=3 AND substr(a.given,1,3)=substr(b.given,1,3))
   OR (length(a.given)=1 AND a.given=substr(b.given,1,1)) OR (length(b.given)=1 AND b.given=substr(a.given,1,1)))
), direct_precedence AS (
 SELECT witness_key,min(root_higher) AS superseded_by
 FROM pairs
 GROUP BY witness_key
 -- An open given name names nobody in particular when the higher rows hold several distinct people of that family.
 HAVING NOT bool_or(open_given) OR min(higher_person_key)=max(higher_person_key)
)
SELECT a.witness_key,coalesce(b.superseded_by,a.superseded_by) AS superseded_by
FROM direct_precedence a
LEFT JOIN direct_precedence b ON a.superseded_by=b.witness_key

