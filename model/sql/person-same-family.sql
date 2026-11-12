-- Same-person family-name agreement shared by print_meeting_agreement, witness_precedence, and witness_key_map:
-- exact equality, or at most one edit in a left-hand family name of 5+ characters.
-- Partitioning 5-character names by 2-character halves and 6+-character names by disjoint 3-character halves
-- turns the Levenshtein bound into exact equi-joins over distinct family strings.
WITH families AS (
 SELECT DISTINCT family FROM appearance_people WHERE family IS NOT NULL AND family<>''
), keys_a AS (
 SELECT family,length(family) AS len,
  CASE WHEN length(family)=5 THEN 'p2:'||substr(family,1,2) ELSE 'p3:'||substr(family,1,3) END AS k1,
  CASE WHEN length(family)=5 THEN 's2:'||substr(family,4,2) ELSE 's3:'||substr(family,length(family)-2,3) END AS k2
 FROM families WHERE length(family)>=5
), keys_b AS (
 SELECT family,unnest(make_array(len-1,len,len+1)) AS target_len,key FROM (
  SELECT family,length(family) AS len,'p2:'||substr(family,1,2) AS key FROM families WHERE length(family) IN (4,5,6)
  UNION ALL SELECT family,length(family),'s2:'||substr(family,length(family)-1,2) FROM families WHERE length(family) IN (4,5,6)
  UNION ALL SELECT family,length(family),'p3:'||substr(family,1,3) FROM families WHERE length(family)>=5
  UNION ALL SELECT family,length(family),'s3:'||substr(family,length(family)-2,3) FROM families WHERE length(family)>=5
 )
)
SELECT family AS left_family,family AS right_family FROM families
UNION
SELECT a.family,b.family FROM keys_a a JOIN keys_b b ON a.k1=b.key AND a.len=b.target_len AND a.family<>b.family
WHERE levenshtein(a.family,b.family)<=1
UNION
SELECT a.family,b.family FROM keys_a a JOIN keys_b b ON a.k2=b.key AND a.len=b.target_len AND a.family<>b.family
WHERE levenshtein(a.family,b.family)<=1
