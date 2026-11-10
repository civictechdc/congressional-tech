-- ct-kw85: for each witness row the Members sitting on its hearing date whom its name could be, with the terms that
-- cover the date. The family name is the row's last name word and any word of the Member's name_last ('Bono Mack').
-- The first name must agree: a word of the row's first names equals one of the Member's (name_first, a nickname in
-- it, or the members data's name_nickname: 'Chet' Edwards), or both share their first three letters, or it reads the
-- Member's abbreviated first name in order ('William' for 'Wm.'). An initial agrees only with the same initial, so a
-- bare initial never matches a full first name ('strict' marks an equal first name; 'full' one longer than a letter).
-- Only Members in office on the date are candidates, so a former namesake never blocks a sitting one. Rows with the
-- publisher's ID of a known Member, no family name, no date, or words that keep them witnesses (former, a closed span
-- of years, a state legislature, a House or Senate officer or staffer) have none.
-- Its own step: witness_member_mentions and witness_member_tiers read these rows.
WITH member_names AS (
 SELECT f.bioguide_id,f.family,g.given,g.abbreviated,
  -- 'Wm.' -> ^w[a-z]*m[a-z]*$: the abbreviation's letters in order, from the first.
  CASE WHEN g.abbreviated THEN '^'||substr(g.given,1,1)||'[a-z]*'||substr(g.given,2,1)||'[a-z]*'||substr(g.given,3,1)||'[a-z]*'
   ||substr(g.given,4,1)||'[a-z]*$' END AS abbreviation
 FROM (SELECT id AS bioguide_id,unnest(toks) AS family FROM witness_member_facts WHERE side='member' AND part='family') f
 JOIN (SELECT id AS bioguide_id,unnest(toks) AS given,abbreviated FROM witness_member_facts WHERE side='member' AND part='given') g
  ON g.bioguide_id=f.bioguide_id
), name_rows AS (
 SELECT f.id,f.family,f.givens,f.dates
 FROM (SELECT DISTINCT id AS bioguide_id FROM witness_member_facts WHERE side='member') i
 RIGHT ANTI JOIN witness_member_facts f ON f.publisher_id=i.bioguide_id
 WHERE f.side='witness' AND f.family IS NOT NULL AND coalesce(cardinality(f.dates),0)>0
  AND NOT (f.says_former OR f.says_state_legislature OR f.says_officer)
), pairs AS (
 SELECT w.witness_key,m.bioguide_id,bool_or(w.given=m.given) AS strict,bool_or(length(w.given)>1) AS full_name
 FROM member_names m JOIN (SELECT id AS witness_key,family,unnest(givens) AS given FROM name_rows) w
  ON m.family=w.family AND substr(m.given,1,1)=substr(w.given,1,1)
 WHERE w.given=m.given OR (length(w.given)>=3 AND length(m.given)>=3 AND substr(w.given,1,3)=substr(m.given,1,3))
  OR (m.abbreviated AND regexp_like(w.given,m.abbreviation))
 GROUP BY w.witness_key,m.bioguide_id
)
SELECT p.witness_key,p.bioguide_id,p.strict,p.full_name,t.chamber,t.state
FROM member_terms t JOIN pairs p ON t.bioguide_id=p.bioguide_id
 JOIN (SELECT id AS witness_key,unnest(dates) AS day FROM name_rows) d ON d.witness_key=p.witness_key
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=d.day AND d.day<=cast(t.end_date AS VARCHAR)
GROUP BY p.witness_key,p.bioguide_id,p.strict,p.full_name,t.chamber,t.state
