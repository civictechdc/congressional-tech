-- ct-kw85: for each witness row the Members it could name, and their terms covering its hearing date. A row with the
-- publisher's ID of a known Member, no family name, no date, or words that keep it a witness (former, a closed span
-- of years, a state legislature, a House or Senate officer or staffer) has none. A Member fits by family name (any
-- later token of the Member's name: 'Bono Mack') and a compatible given name: equal, a one-way nickname, an initial,
-- or the same first three letters ('strict' when equal or a nickname). When no Member at all has the given name and
-- the row states a chamber, every Member of that family name is a candidate ('family' path: Chet/Thomas Edwards).
-- Its own step: witness_member_states and witness_members read these rows several times.
WITH nicknames(nick,formal) AS (VALUES ('bob','robert'),('bobby','robert'),('rob','robert'),('bill','william'),('billy','william'),('will','william'),('dick','richard'),('rick','richard'),('rich','richard'),('ted','edward'),('ned','edward'),('ed','edward'),('eddie','edward'),('liz','elizabeth'),('beth','elizabeth'),('betsy','elizabeth'),('betty','elizabeth'),('libby','elizabeth'),('peggy','margaret'),('maggie','margaret'),('meg','margaret'),('jim','james'),('jimmy','james'),('mike','michael'),('tom','thomas'),('tommy','thomas'),('chuck','charles'),('jack','john'),('hank','henry'),('joe','joseph'),('tony','anthony'),('larry','lawrence'),('harry','harold'),('jerry','gerald'),('sandy','sandra'),('kathy','katherine')), members AS (
 SELECT m.bioguide_id,m.given,coalesce(n.formal,m.given) AS canon,m.family
 FROM nicknames n RIGHT JOIN (SELECT id AS bioguide_id,toks[1] AS given,unnest(array_slice(toks,2,cast(cardinality(toks) AS BIGINT))) AS family
  FROM witness_member_facts WHERE side='member' AND cardinality(toks)>=2) m ON n.nick=m.given
), name_rows AS (
 SELECT f.id,f.given1,f.given2,f.family,f.chamber,f.dates
 FROM (SELECT DISTINCT id AS bioguide_id FROM witness_member_facts WHERE side='member') i
 RIGHT ANTI JOIN witness_member_facts f ON f.publisher_id=i.bioguide_id
 WHERE f.side='witness' AND f.family IS NOT NULL AND coalesce(cardinality(f.dates),0)>0
  AND NOT (f.says_former OR f.says_state_legislature OR f.says_officer)
), witness_givens AS (
 SELECT g.id AS witness_key,g.given,coalesce(k.formal,g.given) AS canon,g.family
 FROM nicknames k RIGHT JOIN (SELECT id,given1 AS given,family FROM name_rows UNION ALL SELECT id,given2,family FROM name_rows WHERE given2 IS NOT NULL) g
  ON k.nick=g.given
), given_pairs AS (
 -- Equal, a nickname, an initial or the same first three letters: all share the first letter or the formal name.
 SELECT w.witness_key,m.bioguide_id,(w.given=m.given OR w.canon=m.canon) AS strict
 FROM members m JOIN witness_givens w ON m.family=w.family AND substr(m.given,1,1)=substr(w.given,1,1)
 WHERE w.given=m.given OR w.canon=m.canon OR (length(w.given)>=3 AND length(m.given)>=3 AND substr(w.given,1,3)=substr(m.given,1,3))
  OR (length(w.given)=1 AND starts_with(m.given,w.given)) OR (length(m.given)=1 AND starts_with(w.given,m.given))
 UNION ALL
 SELECT w.witness_key,m.bioguide_id,true AS strict
 FROM members m JOIN witness_givens w ON m.family=w.family AND substr(m.canon,1,1)=substr(w.canon,1,1)
 WHERE substr(m.given,1,1)<>substr(w.given,1,1) AND w.canon=m.canon
), name_candidates AS (
 SELECT witness_key,bioguide_id,bool_or(strict) AS strict FROM given_pairs GROUP BY witness_key,bioguide_id
), family_candidates AS (
 SELECT DISTINCT r.id AS witness_key,m.bioguide_id,false AS strict
 FROM members m JOIN (SELECT n.* FROM (SELECT DISTINCT witness_key FROM name_candidates) h RIGHT ANTI JOIN name_rows n ON h.witness_key=n.id
  WHERE n.chamber IS NOT NULL) r ON m.family=r.family
), candidates AS (
 SELECT witness_key,bioguide_id,strict,'name' AS path FROM name_candidates
 UNION ALL SELECT witness_key,bioguide_id,strict,'family' AS path FROM family_candidates
), row_dates AS (
 SELECT id AS witness_key,unnest(dates) AS day FROM name_rows
)
SELECT c.witness_key,c.bioguide_id,c.strict,c.path,t.chamber,t.state
FROM member_terms t JOIN candidates c ON t.bioguide_id=c.bioguide_id JOIN row_dates d ON d.witness_key=c.witness_key
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=d.day AND d.day<=cast(t.end_date AS VARCHAR)
GROUP BY c.witness_key,c.bioguide_id,c.strict,c.path,t.chamber,t.state
