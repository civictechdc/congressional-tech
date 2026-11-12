-- ct-kw85 / ct-eofd: the first names witness_member_candidates compares, read once for both sides. Per Member: each
-- word of the family name (name_last: 'Bono Mack') with each first name (name_first, a nickname it holds in
-- parentheses, the members data's name_nickname, and multi-letter non-family words from name_middle /
-- name_official_full). Per eligible witness row with a family name (witness_member_facts): that family name
-- with each first name. A common name is also read in its formal form (Bob and Robert: the members data holds a
-- nickname for 273 Members only), and a Member's abbreviated first name ('Wm.') as its letters in order, from the
-- first. Common-name pairs come from person_nicknames (including 'lou' -> 'luis' for J. Luis Correa), shared with
-- appearance_people and person_given_matches.
-- Its own step: both arms of the candidate comparison read each side.
WITH given AS (
 SELECT 'witness' AS side,id,family,unnest(givens) AS given,false AS abbreviated
 FROM witness_member_facts WHERE eligible AND family IS NOT NULL
 UNION ALL
 SELECT DISTINCT 'member' AS side,f.id,f.family,g.given,g.is_abbreviated AS abbreviated
 FROM (SELECT id,toks AS family_toks,unnest(toks) AS family FROM witness_member_facts WHERE side='member' AND part='family') f
  JOIN (
   SELECT w.id,w.part,unnest(w.toks) AS given,CASE WHEN w.part='given' THEN w.abbreviated ELSE false END AS is_abbreviated
   FROM witness_member_facts w WHERE w.side='member' AND w.part IN ('given','middle')
  ) g ON g.id=f.id
 WHERE g.part='given' OR (length(g.given)>=2 AND NOT array_has(f.family_toks,g.given))
)
SELECT g.side,g.id,g.family,g.given,coalesce(k.formal,g.given) AS canon,
 -- 'Wm.' -> ^w[a-z]*m[a-z]*$
 CASE WHEN g.abbreviated THEN '^'||substr(g.given,1,1)||'[a-z]*'||substr(g.given,2,1)||'[a-z]*'||substr(g.given,3,1)||'[a-z]*'
  ||substr(g.given,4,1)||'[a-z]*$' END AS abbreviation
FROM person_nicknames k RIGHT JOIN given g ON k.nick=g.given
