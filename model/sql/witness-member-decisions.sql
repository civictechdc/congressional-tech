-- ct-kw85: each witness row's own answer. A row with the publisher's ID of a Member in office on the date is that
-- Member. Otherwise the best tier's candidates decide: one candidate is the match; several are narrowed to those
-- whose first name is equal (a nickname from the members data counts), and if that does not leave exactly one the
-- row is 'ambiguous' and stays a witness. A matched row that is the hearing's own nominee is 'nominee'.
-- Its own step: witness_members reads it twice.
WITH tiers AS (
 SELECT * FROM witness_member_tiers WHERE tier IS NOT NULL
), best AS (
 SELECT witness_key,min(tier) AS tier FROM tiers GROUP BY witness_key
), picked AS (
 SELECT t.witness_key,min(t.tier) AS tier,count(t.bioguide_id) AS members,count(t.bioguide_id) FILTER (WHERE t.strict) AS strict_members,
  min(t.bioguide_id) AS any_member,min(t.bioguide_id) FILTER (WHERE t.strict) AS strict_member
 FROM best b JOIN tiers t ON t.witness_key=b.witness_key AND t.tier=b.tier GROUP BY t.witness_key
)
SELECT p.witness_key,f.person,
 CASE WHEN p.members=1 OR p.strict_members=1 THEN CASE WHEN f.says_nominee THEN 'nominee' ELSE 'member' END ELSE 'ambiguous' END AS outcome,
 CASE WHEN p.members=1 THEN p.any_member WHEN p.strict_members=1 THEN p.strict_member END AS bioguide_id,
 'name_'||CASE p.tier WHEN 1 THEN 'state' WHEN 2 THEN 'chamber' ELSE 'role' END AS basis
FROM picked p JOIN witness_member_facts f ON f.id=p.witness_key AND f.side='witness'
UNION ALL
SELECT DISTINCT f.id AS witness_key,f.person,CASE WHEN f.says_nominee THEN 'nominee' ELSE 'member' END AS outcome,
 f.publisher_id AS bioguide_id,'publisher_id' AS basis
FROM member_terms t JOIN (SELECT w.id,w.person,w.publisher_id,w.says_nominee,unnest(w.dates) AS day
 FROM (SELECT DISTINCT id AS bioguide_id FROM witness_member_facts WHERE side='member') i
 JOIN witness_member_facts w ON w.publisher_id=i.bioguide_id WHERE w.side='witness') f ON t.bioguide_id=f.publisher_id
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=f.day AND f.day<=cast(t.end_date AS VARCHAR)
