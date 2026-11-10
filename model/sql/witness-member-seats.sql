-- ct-kw85: the seat rule. A witness row that states a House seat (witness_member_mentions.seats: a state and
-- district, a state at large, or a territory's Delegate or Resident Commissioner) and names no state legislature
-- names the Member holding that seat on its hearing date when a word of its name or first field is a word of that
-- Member's family name: a seat has one holder, so no first name is needed ('Page Pomeroy | The Honorable Earl
-- (ND-At Large)', 'San Nicolas | Hon. Michael F.Q. | a Delegate from Guam').
-- The stated seats are few (hundreds), so they are the build side.
SELECT DISTINCT s.witness_key,t.bioguide_id
FROM (SELECT witness_key,seat,seat_words,unnest(dates) AS day
  FROM (SELECT witness_key,unnest(seats) AS seat,seat_words,dates FROM witness_member_mentions
   WHERE NOT names_legislature AND cardinality(seats)>0)) s
 JOIN member_terms t
 ON t.chamber='house' AND t.state=split_part(s.seat,'-',1) AND t.district=cast(split_part(s.seat,'-',2) AS SMALLINT)
 JOIN (SELECT id,toks FROM witness_member_facts WHERE side='member' AND part='family') f ON f.id=t.bioguide_id
WHERE t.start_date IS NOT NULL AND t.end_date IS NOT NULL
 AND cast(t.start_date AS VARCHAR)<=s.day AND s.day<=cast(t.end_date AS VARCHAR) AND array_has_any(s.seat_words,f.toks)
