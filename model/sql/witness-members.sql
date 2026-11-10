-- Sitting Members of Congress acting officially are Member appearances, not witnesses (ct-kw85, owner decisions
-- 2026-11-10). A witness row is a Member appearance when it names a Member who held office on the hearing date:
--  publisher_id     the publisher's Bioguide ID (house_xml), with a term covering the date;
--  name_state       the Member's family and given name (equal, a one-way nickname, an initial or the same first three
--                   letters), a term covering the date, and the row naming that term's state;
--  name_chamber     ...the row naming that term's chamber ('U.S. Senator', 'Representative in Congress') or Congress
--                   ('Member of Congress') and no state;
--  name_role        ...the row opening a field with a committee, caucus or commission role, or a leadership office;
--  family_state, family_chamber  no Member has the row's given name at all (Chet/Thomas Edwards): the family name and
--                   the row's stated chamber, every field about Congress or a place;
--  group            another row of the same appearance (witness_precedence) matched.
-- A name match never stands on the name alone. The row's own words keep it a witness when it says former or gives a
-- closed span of years, a state legislature, a House or Senate officer or staffer. When several sitting Members fit,
-- the given name must single one out ('Mary Miller', not 'Mariannette Miller-Meeks'); otherwise the row is
-- 'ambiguous' and stays a witness. A sitting Member who is the hearing's own nominee ('to be ...', or a nomination
-- hearing whose title names them) is 'nominee' and stays a witness; a nominee row keeps its whole appearance a
-- witness, and two different Members in one appearance leave it 'ambiguous'. bioguide_id stays the publisher's; the
-- matched Member is published separately as matched_bioguide_id with match_basis.
-- Nothing here feeds witness_precedence, appearance_people or document matching, so no key or link moves.
WITH member_names AS (
 -- Every later token of a Member's name is a possible family name ('Bono Mack', 'Hernandez Rivera').
 SELECT id AS bioguide_id,toks[1] AS given,unnest(array_slice(toks,2,cardinality(toks))) AS family
 FROM witness_member_facts WHERE side='member' AND cardinality(toks)>=2
), nicknames(nick,formal) AS (VALUES ('bob','robert'),('bobby','robert'),('rob','robert'),('bill','william'),('billy','william'),('will','william'),('dick','richard'),('rick','richard'),('rich','richard'),('ted','edward'),('ned','edward'),('ed','edward'),('eddie','edward'),('liz','elizabeth'),('beth','elizabeth'),('betsy','elizabeth'),('betty','elizabeth'),('libby','elizabeth'),('peggy','margaret'),('maggie','margaret'),('meg','margaret'),('jim','james'),('jimmy','james'),('mike','michael'),('tom','thomas'),('tommy','thomas'),('chuck','charles'),('jack','john'),('hank','henry'),('joe','joseph'),('tony','anthony'),('larry','lawrence'),('harry','harold'),('jerry','gerald'),('sandy','sandra'),('kathy','katherine')), members AS (
 SELECT m.bioguide_id,m.given,coalesce(n.formal,m.given) AS canon,m.family FROM member_names m LEFT JOIN nicknames n ON n.nick=m.given
), member_ids AS (
 SELECT DISTINCT id AS bioguide_id FROM witness_member_facts WHERE side='member'
), name_rows AS (
 -- No publisher ID of a known Member, a name to match, a date to match it on, and nothing that keeps it a witness.
 SELECT f.* FROM member_ids i RIGHT ANTI JOIN witness_member_facts f ON f.publisher_id=i.bioguide_id
 WHERE f.side='witness' AND f.family IS NOT NULL AND coalesce(cardinality(f.dates),0)>0
  AND NOT (f.says_former OR f.says_state_legislature OR f.says_officer)
), witness_givens AS (
 SELECT n.id AS witness_key,g.given,coalesce(k.formal,g.given) AS canon,n.family
 FROM nicknames k RIGHT JOIN (SELECT id,given1 AS given FROM name_rows UNION ALL SELECT id,given2 FROM name_rows WHERE given2 IS NOT NULL) g
  ON k.nick=g.given JOIN name_rows n ON n.id=g.id
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
), named_rows AS (
 SELECT DISTINCT witness_key FROM name_candidates
), family_candidates AS (
 SELECT DISTINCT r.id AS witness_key,m.bioguide_id,false AS strict
 FROM members m JOIN (SELECT n.* FROM named_rows h RIGHT ANTI JOIN name_rows n ON h.witness_key=n.id WHERE n.chamber IS NOT NULL) r
  ON m.family=r.family
), candidates AS (
 SELECT witness_key,bioguide_id,strict,'name' AS path FROM name_candidates
 UNION ALL SELECT witness_key,bioguide_id,strict,'family' AS path FROM family_candidates
), row_dates AS (
 SELECT id AS witness_key,unnest(dates) AS day FROM name_rows
), covering AS (
 -- The candidate's terms that cover a hearing date.
 SELECT c.witness_key,c.bioguide_id,t.chamber,t.state
 FROM member_terms t JOIN candidates c ON t.bioguide_id=c.bioguide_id JOIN row_dates d ON d.witness_key=c.witness_key
 WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
  AND cast(t.start_date AS VARCHAR)<=d.day AND d.day<=cast(t.end_date AS VARCHAR)
 GROUP BY c.witness_key,c.bioguide_id,t.chamber,t.state
), covered_rows AS (
 SELECT n.id AS witness_key,n.full_text,n.field_text,n.raw_text,n.chamber,n.says_role
 FROM (SELECT DISTINCT witness_key FROM covering) c JOIN name_rows n ON n.id=c.witness_key
), states(name,code) AS (VALUES ('alabama','AL'),('alaska','AK'),('arizona','AZ'),('arkansas','AR'),('california','CA'),('colorado','CO'),('connecticut','CT'),('delaware','DE'),('florida','FL'),('georgia','GA'),('hawaii','HI'),('idaho','ID'),('illinois','IL'),('indiana','IN'),('iowa','IA'),('kansas','KS'),('kentucky','KY'),('louisiana','LA'),('maine','ME'),('maryland','MD'),('massachusetts','MA'),('michigan','MI'),('minnesota','MN'),('mississippi','MS'),('missouri','MO'),('montana','MT'),('nebraska','NE'),('nevada','NV'),('new hampshire','NH'),('new jersey','NJ'),('new mexico','NM'),('new york','NY'),('north carolina','NC'),('north dakota','ND'),('ohio','OH'),('oklahoma','OK'),('oregon','OR'),('pennsylvania','PA'),('rhode island','RI'),('south carolina','SC'),('south dakota','SD'),('tennessee','TN'),('texas','TX'),('utah','UT'),('vermont','VT'),('virginia','VA'),('washington','WA'),('west virginia','WV'),('wisconsin','WI'),('wyoming','WY'),('american samoa','AS'),('district of columbia','DC'),('guam','GU'),('northern mariana islands','MP'),('puerto rico','PR'),('virgin islands','VI')), row_states AS (
 -- States the row names: 'from (the State of) X', 'State of X', "X's 2nd District", 'District of X', a field that is
 -- the state, or '(D-XX)', '(XX-3)'.
 SELECT DISTINCT r.witness_key,s.code
 FROM states s JOIN covered_rows r ON regexp_like(r.full_text,'\bfrom\s+(the\s+)?((state|commonwealth|territory)\s+of\s+)?'||s.name||'\b|\b(state|commonwealth|territory)\s+of\s+'||s.name||'\b|\b'||s.name||'(''s|’s)?,?\s+(\w+\s+){0,2}(congressional\s+)?district\b|\b(at[- ]large|\w+) (congressional )?district of '||s.name||'\b|\bdistrict[,;]?\s+'||s.name||'\b|(^|\|)\s*(of (the (state|commonwealth|territory) of )?)?'||s.name||'[\s.,;:]*($|\|)') OR regexp_like(r.raw_text,'\b[DRI]\s*[-–]\s*'||s.code||'\b|\('||s.code||'-(\d+|AL)\)')
), field_segments AS (
 SELECT witness_key,unnest(string_to_array(field_text,'|')) AS segment FROM covered_rows
), about_congress AS (
 -- Every field speaks of Congress or a place: a stated state with nothing else is not someone else's employer.
 SELECT witness_key,bool_and(regexp_like(segment,'congress|senat|house|representative|delegate|commissioner|member|committee|caucus|chair|ranking|district|statement|leader|whip|speaker|majority|minority|conference|subcommittee|delegation|panel|introduc|sponsor|testimony|honorable|\bhon\b|northern mariana islands|district of columbia|american samoa|north carolina|south carolina|virgin islands|massachusetts|new hampshire|west virginia|north dakota|pennsylvania|rhode island|south dakota|connecticut|mississippi|puerto rico|california|new jersey|new mexico|washington|louisiana|minnesota|tennessee|wisconsin|arkansas|colorado|delaware|illinois|kentucky|maryland|michigan|missouri|nebraska|new york|oklahoma|virginia|alabama|arizona|florida|georgia|indiana|montana|vermont|wyoming|alaska|hawaii|kansas|nevada|oregon|idaho|maine|texas|guam|iowa|ohio|utah')) AS about_congress
 FROM field_segments WHERE regexp_like(segment,'\S') GROUP BY witness_key
), state_matches AS (
 SELECT DISTINCT c.witness_key,c.bioguide_id FROM row_states s JOIN covering c ON c.witness_key=s.witness_key AND c.state=s.code
), chamber_matches AS (
 SELECT DISTINCT c.witness_key,c.bioguide_id FROM covered_rows r JOIN covering c ON c.witness_key=r.witness_key AND c.chamber=r.chamber
), stating_rows AS (
 SELECT DISTINCT witness_key FROM row_states
), tiers AS (
 SELECT p.witness_key,p.bioguide_id,p.strict,p.path,
  CASE WHEN sm.witness_key IS NOT NULL THEN CASE WHEN r.chamber IS NOT NULL OR r.says_role OR coalesce(a.about_congress,true) THEN 1 END
   WHEN st.witness_key IS NOT NULL THEN NULL
   WHEN r.chamber IN ('senate','house') THEN CASE WHEN cm.witness_key IS NOT NULL THEN 2 END
   WHEN r.chamber='either' THEN 2
   WHEN r.says_role THEN 3 END AS tier
 FROM (SELECT DISTINCT c.witness_key,c.bioguide_id,c.strict,c.path FROM covering v JOIN candidates c ON c.witness_key=v.witness_key AND c.bioguide_id=v.bioguide_id) p
 JOIN covered_rows r ON r.witness_key=p.witness_key
 LEFT JOIN about_congress a ON a.witness_key=p.witness_key
 LEFT JOIN stating_rows st ON st.witness_key=p.witness_key
 LEFT JOIN state_matches sm ON sm.witness_key=p.witness_key AND sm.bioguide_id=p.bioguide_id
 LEFT JOIN chamber_matches cm ON cm.witness_key=p.witness_key AND cm.bioguide_id=p.bioguide_id
 WHERE p.path='name' OR coalesce(a.about_congress,true)
), kept_tiers AS (
 SELECT * FROM tiers WHERE tier IS NOT NULL AND (path='name' OR tier IN (1,2))
), best AS (
 SELECT witness_key,min(tier) AS tier FROM kept_tiers GROUP BY witness_key
), picked AS (
 SELECT k.witness_key,min(k.path) AS path,min(k.tier) AS tier,count(k.bioguide_id) AS members,
  count(k.bioguide_id) FILTER (WHERE k.strict) AS strict_members,min(k.bioguide_id) AS any_member,
  min(k.bioguide_id) FILTER (WHERE k.strict) AS strict_member
 FROM best b JOIN kept_tiers k ON k.witness_key=b.witness_key AND k.tier=b.tier GROUP BY k.witness_key
), name_decisions AS (
 SELECT p.witness_key,n.person,
  CASE WHEN p.members=1 OR (p.path='name' AND p.strict_members=1) THEN CASE WHEN n.says_nominee THEN 'nominee' ELSE 'member' END
   ELSE 'ambiguous' END AS outcome,
  CASE WHEN p.members=1 THEN p.any_member WHEN p.path='name' AND p.strict_members=1 THEN p.strict_member END AS bioguide_id,
  p.path||'_'||CASE p.tier WHEN 1 THEN 'state' WHEN 2 THEN 'chamber' ELSE 'role' END AS basis
 FROM picked p JOIN name_rows n ON n.id=p.witness_key
), publisher_decisions AS (
 SELECT DISTINCT f.id AS witness_key,f.person,CASE WHEN f.says_nominee THEN 'nominee' ELSE 'member' END AS outcome,
  f.publisher_id AS bioguide_id,'publisher_id' AS basis
 FROM member_terms t JOIN (SELECT w.*,unnest(w.dates) AS day FROM member_ids i JOIN witness_member_facts w ON w.publisher_id=i.bioguide_id
  WHERE w.side='witness') f ON t.bioguide_id=f.publisher_id
 WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
  AND cast(t.start_date AS VARCHAR)<=f.day AND f.day<=cast(t.end_date AS VARCHAR)
), decisions AS (
 SELECT * FROM name_decisions UNION ALL SELECT * FROM publisher_decisions
), group_members AS (
 SELECT person,bioguide_id,bool_or(outcome='nominee') AS nominee FROM decisions WHERE outcome IN ('member','nominee')
 GROUP BY person,bioguide_id
), groups AS (
 SELECT person,count(bioguide_id) AS members,min(bioguide_id) AS bioguide_id,bool_or(nominee) AS nominee
 FROM group_members GROUP BY person
), resolved AS (
 SELECT f.id AS witness_key,d.outcome AS own_outcome,d.basis AS own_basis,g.person AS group_person,g.members,g.nominee,g.bioguide_id
 FROM groups g RIGHT JOIN (decisions d RIGHT JOIN witness_member_facts f ON d.witness_key=f.id) ON g.person=f.person
 WHERE f.side='witness' AND (d.witness_key IS NOT NULL OR g.person IS NOT NULL)
), outcomes AS (
 SELECT witness_key,own_basis,bioguide_id,
  CASE WHEN group_person IS NULL THEN own_outcome
   WHEN nominee THEN CASE WHEN own_outcome='member' THEN 'nominee' ELSE own_outcome END
   WHEN members>1 THEN CASE WHEN own_outcome='member' THEN 'ambiguous' ELSE own_outcome END
   ELSE 'member' END AS outcome,
  own_outcome
 FROM resolved
)
SELECT witness_key,outcome,
 CASE WHEN outcome='member' THEN bioguide_id END AS matched_bioguide_id,
 CASE WHEN outcome='member' THEN CASE WHEN own_outcome='member' THEN own_basis ELSE 'group' END END AS match_basis
FROM outcomes WHERE outcome IS NOT NULL
