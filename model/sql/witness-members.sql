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
WITH covered_rows AS (
 SELECT f.id AS witness_key,f.person,f.field_text,f.chamber,f.says_role,f.says_nominee
 FROM (SELECT DISTINCT witness_key FROM witness_member_candidates) c JOIN witness_member_facts f ON f.id=c.witness_key
), field_segments AS (
 SELECT witness_key,unnest(string_to_array(field_text,'|')) AS segment FROM covered_rows
), about_congress AS (
 -- Every field speaks of Congress or a place: a stated state with nothing else is not someone else's employer.
 SELECT witness_key,bool_and(regexp_like(segment,'congress|senat|house|representative|delegate|commissioner|member|committee|caucus|chair|ranking|district|statement|leader|whip|speaker|majority|minority|conference|subcommittee|delegation|panel|introduc|sponsor|testimony|honorable|\bhon\b|northern mariana islands|district of columbia|american samoa|north carolina|south carolina|virgin islands|massachusetts|new hampshire|west virginia|north dakota|pennsylvania|rhode island|south dakota|connecticut|mississippi|puerto rico|california|new jersey|new mexico|washington|louisiana|minnesota|tennessee|wisconsin|arkansas|colorado|delaware|illinois|kentucky|maryland|michigan|missouri|nebraska|new york|oklahoma|virginia|alabama|arizona|florida|georgia|indiana|montana|vermont|wyoming|alaska|hawaii|kansas|nevada|oregon|idaho|maine|texas|guam|iowa|ohio|utah')) AS about_congress
 FROM field_segments WHERE regexp_like(segment,'\S') GROUP BY witness_key
), state_matches AS (
 SELECT DISTINCT c.witness_key,c.bioguide_id FROM witness_member_states s JOIN witness_member_candidates c ON c.witness_key=s.witness_key AND c.state=s.code
), chamber_matches AS (
 SELECT DISTINCT c.witness_key,c.bioguide_id FROM covered_rows r JOIN witness_member_candidates c ON c.witness_key=r.witness_key AND c.chamber=r.chamber
), stating_rows AS (
 SELECT DISTINCT witness_key FROM witness_member_states
), tiers AS (
 -- 1: the row names the term's state; 2: its chamber or Congress and no state; 3: a committee role and nothing else.
 SELECT p.witness_key,p.bioguide_id,p.strict,p.path,
  CASE WHEN sm.witness_key IS NOT NULL THEN CASE WHEN r.chamber IS NOT NULL OR r.says_role OR coalesce(a.about_congress,true) THEN 1 END
   WHEN st.witness_key IS NOT NULL THEN NULL
   WHEN r.chamber IN ('senate','house') THEN CASE WHEN cm.witness_key IS NOT NULL THEN 2 END
   WHEN r.chamber='either' THEN 2
   WHEN r.says_role THEN 3 END AS tier
 FROM chamber_matches cm RIGHT JOIN (state_matches sm RIGHT JOIN (stating_rows st RIGHT JOIN (about_congress a RIGHT JOIN (
  (SELECT DISTINCT witness_key,bioguide_id,strict,path FROM witness_member_candidates) p JOIN covered_rows r ON r.witness_key=p.witness_key)
  ON a.witness_key=p.witness_key) ON st.witness_key=p.witness_key) ON sm.witness_key=p.witness_key AND sm.bioguide_id=p.bioguide_id)
  ON cm.witness_key=p.witness_key AND cm.bioguide_id=p.bioguide_id
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
 SELECT p.witness_key,r.person,
  CASE WHEN p.members=1 OR (p.path='name' AND p.strict_members=1) THEN CASE WHEN r.says_nominee THEN 'nominee' ELSE 'member' END
   ELSE 'ambiguous' END AS outcome,
  CASE WHEN p.members=1 THEN p.any_member WHEN p.path='name' AND p.strict_members=1 THEN p.strict_member END AS bioguide_id,
  p.path||'_'||CASE p.tier WHEN 1 THEN 'state' WHEN 2 THEN 'chamber' ELSE 'role' END AS basis
 FROM picked p JOIN covered_rows r ON r.witness_key=p.witness_key
), publisher_decisions AS (
 SELECT DISTINCT f.id AS witness_key,f.person,CASE WHEN f.says_nominee THEN 'nominee' ELSE 'member' END AS outcome,
  f.publisher_id AS bioguide_id,'publisher_id' AS basis
 FROM member_terms t JOIN (SELECT w.id,w.person,w.publisher_id,w.says_nominee,unnest(w.dates) AS day
  FROM (SELECT DISTINCT id AS bioguide_id FROM witness_member_facts WHERE side='member') i
  JOIN witness_member_facts w ON w.publisher_id=i.bioguide_id WHERE w.side='witness') f ON t.bioguide_id=f.publisher_id
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
