-- ct-kw85: how each sitting candidate's term agrees with the row's own words, in one pass. For a candidate whose
-- first name agrees (witness_member_candidates.agrees), tier 1: the row names the term's state (and a chamber, a role,
-- or only Congress and places); 2: it names the term's chamber, or Congress, and no state; 3: it opens a field with a
-- congressional role, names no state, and its first name agrees in full;
-- 6: it is a name alone at a Member Day hearing. For any other candidate, tier 5, the initial rule's pool: the row
-- names the term's state and a chamber that is the term's ('Member of Congress' is either). A row that names a state
-- legislature, or a state no candidate's term holds, has no tier.
WITH agreement AS (
 SELECT c.witness_key,c.bioguide_id,c.strict,c.agrees,c.full_name,c.initial,
  bool_or(array_has(m.states,c.state)) AS state_match,bool_or(c.chamber=m.chamber) AS chamber_match,
  bool_or(array_has(m.states,c.state) AND (m.chamber='either' OR c.chamber=m.chamber)) AS office_state_match,
  max(m.chamber) AS chamber,bool_or(m.says_role) AS says_role,bool_or(m.names_legislature) AS names_legislature,
  bool_or(m.about_congress) AS about_congress,max(cardinality(m.states)) AS states,bool_or(m.member_day_name_only) AS member_day
 FROM witness_member_mentions m JOIN witness_member_candidates c ON c.witness_key=m.witness_key
 GROUP BY c.witness_key,c.bioguide_id,c.strict,c.agrees,c.full_name,c.initial
)
SELECT witness_key,bioguide_id,strict,initial,
 CASE WHEN names_legislature THEN NULL
  WHEN NOT agrees THEN CASE WHEN office_state_match THEN 5 END
  WHEN state_match THEN CASE WHEN chamber IS NOT NULL OR says_role OR about_congress THEN 1 END
  WHEN states>0 THEN NULL
  WHEN chamber IN ('senate','house') THEN CASE WHEN chamber_match THEN 2 END
  WHEN chamber='either' THEN 2
  WHEN says_role AND full_name THEN 3
  WHEN member_day THEN 6 END AS tier
FROM agreement
