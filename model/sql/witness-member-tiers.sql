-- ct-kw85: how each sitting candidate's term agrees with the row's own words. Tier 1: the row names the term's state
-- (and a chamber, a role, or only Congress and places); 2: it names the term's chamber, or Congress, and no state; 3:
-- it opens a field with a congressional role, names no state, and its first name agrees in full. A row that names a
-- state legislature, or a state no candidate's term holds, has no tier. Its own step: witness_member_decisions reads it twice.
WITH row_facts AS (
 SELECT f.id AS witness_key,f.chamber,f.says_role,m.states,m.names_legislature,m.about_congress
 FROM witness_member_mentions m JOIN witness_member_facts f ON f.id=m.witness_key AND f.side='witness'
), agreement AS (
 SELECT c.witness_key,c.bioguide_id,c.strict,c.full_name,bool_or(array_has(r.states,c.state)) AS state_match,
  bool_or(c.chamber=r.chamber) AS chamber_match
 FROM row_facts r JOIN witness_member_candidates c ON c.witness_key=r.witness_key
 GROUP BY c.witness_key,c.bioguide_id,c.strict,c.full_name
)
SELECT a.witness_key,a.bioguide_id,a.strict,
 CASE WHEN r.names_legislature THEN NULL
  WHEN a.state_match THEN CASE WHEN r.chamber IS NOT NULL OR r.says_role OR r.about_congress THEN 1 END
  WHEN cardinality(r.states)>0 THEN NULL
  WHEN r.chamber IN ('senate','house') THEN CASE WHEN a.chamber_match THEN 2 END
  WHEN r.chamber='either' THEN 2
  WHEN r.says_role AND a.full_name THEN 3 END AS tier
FROM row_facts r JOIN agreement a ON a.witness_key=r.witness_key
