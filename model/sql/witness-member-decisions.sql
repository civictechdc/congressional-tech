-- ct-kw85: each witness row's own answer, read in one pass. A row with the publisher's ID of a Member in office on
-- the date is that Member ('publisher_id'). Otherwise, in order:
--  name     the row's name tier (witness_member_tiers 1-3): one candidate is the match; several are narrowed to those
--           whose first name is equal (a nickname from the members data counts);
--  seat     else the holder of the seat it states (witness_member_seats), when there is one;
--  initial  else, when the row has no name-tier candidate, the one Member in the stated chamber and state sharing its
--           family name and initial (tier 5), when that Member's agreement is a bare initial ('C. Cox', 'JD Vance');
--  member_day  else, for a name alone at a Member Day hearing (tier 6), the one sitting Member whose family and
--           first name agree, narrowed like the name tiers to an equal first name.
-- A row with candidates and no single answer is 'ambiguous' and stays a witness; a matched row that is the hearing's
-- own nominee is 'nominee'.
WITH ranked AS (
 SELECT witness_key,bioguide_id,strict,initial,tier FROM witness_member_tiers WHERE tier IS NOT NULL
 UNION ALL
 SELECT witness_key,bioguide_id,true AS strict,false AS initial,4 AS tier FROM witness_member_seats
), picked AS (
 SELECT witness_key,min(tier) FILTER (WHERE tier<=3) AS name_tier,
  count(*) FILTER (WHERE tier<=3) AS name_members,min(bioguide_id) FILTER (WHERE tier<=3) AS name_member,
  count(*) FILTER (WHERE tier<=3 AND strict) AS strict_members,min(bioguide_id) FILTER (WHERE tier<=3 AND strict) AS strict_member,
  count(*) FILTER (WHERE tier=4) AS seat_members,min(bioguide_id) FILTER (WHERE tier=4) AS seat_member,
  count(*) FILTER (WHERE tier=5) AS initial_pool,count(*) FILTER (WHERE tier=5 AND initial) AS initial_members,
  min(bioguide_id) FILTER (WHERE tier=5 AND initial) AS initial_member,
  count(*) FILTER (WHERE tier=6) AS day_members,min(bioguide_id) FILTER (WHERE tier=6) AS day_member,
  count(*) FILTER (WHERE tier=6 AND strict) AS day_strict_members,min(bioguide_id) FILTER (WHERE tier=6 AND strict) AS day_strict_member
 FROM ranked GROUP BY witness_key
), decided AS (
 SELECT witness_key,
  CASE WHEN name_members=1 THEN name_member WHEN strict_members=1 THEN strict_member WHEN seat_members=1 THEN seat_member
   WHEN name_members=0 AND initial_pool=1 AND initial_members=1 THEN initial_member
   WHEN day_members=1 THEN day_member WHEN day_strict_members=1 THEN day_strict_member END AS bioguide_id,
  CASE WHEN name_members=1 OR strict_members=1 THEN 'name_'||CASE name_tier WHEN 1 THEN 'state' WHEN 2 THEN 'chamber' ELSE 'role' END
   WHEN seat_members=1 THEN 'seat' WHEN name_members=0 AND initial_pool=1 AND initial_members=1 THEN 'initial'
   WHEN day_members=1 OR day_strict_members=1 THEN 'member_day' END AS basis
 FROM picked WHERE name_members>0 OR seat_members>0 OR initial_members>0 OR day_members>0
)
SELECT d.witness_key,m.person,
 CASE WHEN d.bioguide_id IS NULL THEN 'ambiguous' WHEN m.says_nominee THEN 'nominee' ELSE 'member' END AS outcome,
 d.bioguide_id,d.basis
FROM decided d JOIN witness_member_mentions m ON m.witness_key=d.witness_key
UNION ALL
SELECT DISTINCT f.id AS witness_key,f.person,CASE WHEN f.says_nominee THEN 'nominee' ELSE 'member' END AS outcome,
 f.publisher_id AS bioguide_id,'publisher_id' AS basis
FROM member_terms t JOIN (SELECT id,person,publisher_id,says_nominee,unnest(dates) AS day FROM witness_member_facts
 WHERE side='witness' AND publisher_member) f ON t.bioguide_id=f.publisher_id
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=f.day AND f.day<=cast(t.end_date AS VARCHAR)
