-- ct-kw85: for each eligible witness row the Members sitting on its hearing date who share its family name and the
-- initial of a first name (witness_member_names), with the terms that cover the date and how the first names agree:
--  agrees     a word of the row's first names equals one of the Member's, or both are the same common name (Tom and
--             Thomas), or they share their first three letters, or it reads the Member's abbreviation ('William' for
--             'Wm.'); 'strict' marks an equal or common-name agreement, 'full_name' one longer than a letter;
--  initial    otherwise, one side is a bare initial ('C.' Cox, 'J. Smith') and the other starts with it.
-- A bare initial never agrees with a full first name: only the initial rule (witness_member_tiers) reads it, and it
-- counts every Member sharing the family name and initial, so the rest are kept too. Only Members in office on the
-- date are candidates, so a former namesake never blocks a sitting one.
WITH compared AS (
 SELECT p.id AS witness_key,p.member_id AS bioguide_id,p.given,
  coalesce(gm.strict,false) AS strict,
  coalesce(gm.full_match,false) OR coalesce(regexp_like(p.given,p.abbreviation),false) AS agrees,
  coalesce(gm.initial_match,false) AS initial
 FROM person_given_matches gm RIGHT JOIN (
  SELECT w.id,m.id AS member_id,w.given,m.given AS member_given,m.abbreviation
  FROM (SELECT id,family,given,abbreviation FROM witness_member_names WHERE side='member') m
   JOIN (SELECT id,family,given FROM witness_member_names WHERE side='witness') w
   ON m.family=w.family AND substr(m.given,1,1)=substr(w.given,1,1)
 ) p ON gm.left_given=p.given AND gm.right_given=p.member_given
 UNION ALL
 -- A common name whose short form starts with another letter (Bob and Robert).
 SELECT w.id AS witness_key,m.id AS bioguide_id,w.given,gm.strict,gm.full_match AS agrees,false AS initial
 FROM (SELECT id,family,given FROM witness_member_names WHERE side='member') m
  JOIN (SELECT id,family,given FROM witness_member_names WHERE side='witness') w
  ON m.family=w.family
  JOIN person_given_matches gm ON gm.left_given=w.given AND gm.right_given=m.given
 WHERE substr(m.given,1,1)<>substr(w.given,1,1)
), pairs AS (
 SELECT witness_key,bioguide_id,bool_or(strict) AS strict,bool_or(agrees) AS agrees,
  bool_or(agrees AND length(given)>1) AS full_name,bool_or(initial AND NOT agrees) AS initial
 FROM compared GROUP BY witness_key,bioguide_id
)
SELECT p.witness_key,p.bioguide_id,p.strict,p.agrees,p.full_name,p.initial,t.chamber,t.state
FROM member_terms t JOIN pairs p ON t.bioguide_id=p.bioguide_id
 JOIN (SELECT id AS witness_key,unnest(dates) AS day FROM witness_member_facts WHERE eligible AND family IS NOT NULL) d
 ON d.witness_key=p.witness_key
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=d.day AND d.day<=cast(t.end_date AS VARCHAR)
GROUP BY p.witness_key,p.bioguide_id,p.strict,p.agrees,p.full_name,p.initial,t.chamber,t.state
