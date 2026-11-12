-- Same-person given-name agreement shared by print_meeting_agreement, witness_precedence, witness_key_map,
-- and witness_member_candidates (ct-kw85):
--   strict:        equal as written or through person_nicknames (Tom / Thomas, Bob / Robert)
--   full_match:    strict, or shared first three letters when both have 3+ characters
--   initial_match: not full_match, and one side is a single-letter initial matching the other's first letter
WITH fold(accented,plain) AS (
 VALUES ('áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ','aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld')
), raw_tokens AS (
 SELECT DISTINCT given AS token FROM appearance_people WHERE given IS NOT NULL AND given<>''
 UNION
 SELECT DISTINCT unnest(string_to_array(trim(regexp_replace(translate(lower(
  regexp_replace(split_part(regexp_replace(coalesce(a['name'],a['name_key'],''),'\([^)]*\)',' ','g'),',',1),'[''’`]','','g')
 ),f.accented,f.plain),'[^a-z]+',' ','g')),' ')) AS token
 FROM fold f CROSS JOIN (
  SELECT unnest(appearances) AS a FROM selected_appearance_records WHERE status='completed' AND appearances IS NOT NULL
 ) r
 UNION
 SELECT DISTINCT unnest(string_to_array(trim(regexp_replace(translate(lower(
  regexp_replace(regexp_replace(coalesce(name_first,'')||' '||coalesce(name_nickname,'')||' '||coalesce(name_middle,'')||' '||coalesce(name_official_full,''),'[()]',' ','g'),'[''’`]','','g')
 ),f.accented,f.plain),'[^a-z]+',' ','g')),' ')) AS token
 FROM fold f CROSS JOIN spicy_members WHERE bioguide_id IS NOT NULL
), tokens AS (
 SELECT t.token AS given,coalesce(k.formal,t.token) AS canon,
  substr(t.token,1,1) AS p1,
  CASE WHEN length(t.token)>=3 THEN substr(t.token,1,3) END AS p3,
  length(t.token) AS len
 FROM person_nicknames k RIGHT JOIN (SELECT token FROM raw_tokens WHERE token IS NOT NULL AND token<>'') t ON k.nick=t.token
), raw_pairs AS (
 SELECT a.given AS left_given,b.given AS right_given,true AS strict,true AS full_match,false AS initial_match
 FROM tokens a JOIN tokens b ON a.canon=b.canon
 UNION ALL
 SELECT a.given,b.given,false AS strict,true AS full_match,false AS initial_match
 FROM (SELECT given,p3 FROM tokens WHERE p3 IS NOT NULL) a
 JOIN (SELECT given,p3 FROM tokens WHERE p3 IS NOT NULL) b ON a.p3=b.p3
 UNION ALL
 SELECT a.given,b.given,false AS strict,false AS full_match,true AS initial_match
 FROM (SELECT given,p1 FROM tokens WHERE len=1) a JOIN tokens b ON a.p1=b.p1
 UNION ALL
 SELECT a.given,b.given,false AS strict,false AS full_match,true AS initial_match
 FROM tokens a JOIN (SELECT given,p1 FROM tokens WHERE len=1) b ON a.p1=b.p1
)
SELECT left_given,right_given,
 bool_or(strict) AS strict,
 bool_or(full_match) AS full_match,
 bool_or(initial_match) AND NOT bool_or(full_match) AS initial_match
FROM raw_pairs
GROUP BY left_given,right_given
