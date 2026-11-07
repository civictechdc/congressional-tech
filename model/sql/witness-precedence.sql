-- Precedence per person, not per source (red-f2). On a meeting, a witness row is superseded_by the same
-- person stated by a higher-ranked body (source priority, then record digest, then ordinal). The same person:
-- the same family name (one-letter slips in names of 5+ letters), and given names that agree as written, through a
-- one-way nickname, by a shared first three letters, or as an initial; a row with no given name matches only
-- when that family name is unique among the higher rows (red-f3: Barbara and Joan Smith are not Robert and
-- John Smith). Print entries labelled statements are matched too: a statement by someone the meeting's own
-- list names is that witness. Within one record, collapse repeats when the normalized name and appearance facts agree.
-- Its own step: as a CTE it re-ran the whole appearance resolution.
WITH people AS (
 SELECT w.witness_key,w.occasion,s.priority,w.source,w.record_sha_hex,w.source_locator,w.ordinal,w.name_key,p.statement,p.family,p.given,p.given_canon,
  sha256(json_array(w.position,w.organization,w.on_behalf_of,w.location,w.panel,w.panel_order,
   w.witness_type,w.testified,w.bioguide_id,array_sort(array_distinct(w.document_urls)))) AS occurrence_facts
 FROM appearance_records_resolved w
 JOIN meeting_sources s ON s.kind='appearance' AND s.source=w.source
 JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex AND p.source=w.source AND p.ordinal=w.ordinal
 -- The publisher numbers Official Briefer slots and supplies no names for them.
 WHERE p.family IS NOT NULL AND NOT (w.source='senate_page' AND w.name_key='official briefer')
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
    AND b.name_key=a.name_key AND b.occurrence_facts=a.occurrence_facts AND NOT a.statement AND NOT b.statement
    -- Reviewed multi-date prints: equal names and affiliation do not identify the same listed position.
    AND NOT (a.source='mods' AND (
     (a.record_sha_hex='c19faf04fd9ff3e540201000432f1c2618171da2c9923a636da99e1ae2d002a7'
      AND a.source_locator='mods:witness[17]' AND b.source_locator='mods:witness[12]') -- Akaka: different nominations
     OR (a.record_sha_hex='756c789edf803c341270b65b47a0f270a2f3c9eb0bf3810429f94f12cc5af792'
      AND a.source_locator='mods:witness[79]' AND b.source_locator='mods:witness[26]') -- Torres Small: different companion lists
     OR (a.record_sha_hex='50015b69c0cc39055f21052eef025933b2bdf34f96be2ec3061ec91a8e909451'
      AND a.source_locator='mods:witness[86]' AND b.source_locator='mods:witness[53]') -- McCants: shared affiliation only
    ))))
 WHERE (a.statement OR NOT b.statement)
  AND (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
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

