-- Block distinct bag groups by rarest non-stopword token, filter candidate pairs
-- with Jaccard >= 0.75 and Levenshtein ratio >= 0.85 using DataFusion built-ins only,
-- exclude place/scope mismatches and already-decided pairs (ct-6him).
WITH blocked_raw AS (
 SELECT
  a.bag_key AS bag_key_a,
  b.bag_key AS bag_key_b,
  a.string_key AS string_key_a,
  b.string_key AS string_key_b,
  a.l2_text AS l2_text_a,
  b.l2_text AS l2_text_b,
  a.display_text AS display_text_a,
  b.display_text AS display_text_b,
  a.tokens AS tokens_a,
  b.tokens AS tokens_b,
  a.appearance_count AS appearance_count_a,
  b.appearance_count AS appearance_count_b,
  a.rarest_token,
  a.rarest_df,
  row_number() OVER (
   PARTITION BY a.string_key,b.string_key
   ORDER BY a.rarest_df ASC,a.rarest_token ASC
  ) AS block_rn
 FROM org_bag_rarest a
 JOIN org_bag_rarest b
  ON a.rarest_token=b.rarest_token
  AND a.string_key<b.string_key
  AND 4*least(cardinality(a.tokens),cardinality(b.tokens))>=3*greatest(cardinality(a.tokens),cardinality(b.tokens))
  AND abs(length(a.l2_text)-length(b.l2_text))*20<=3*greatest(length(a.l2_text),length(b.l2_text),1)
), blocked AS (
 SELECT
  bag_key_a,bag_key_b,string_key_a,string_key_b,l2_text_a,l2_text_b,
  display_text_a,display_text_b,tokens_a,tokens_b,
  appearance_count_a,appearance_count_b,rarest_token,rarest_df
 FROM blocked_raw
 WHERE block_rn=1
), scored AS (
 SELECT
  bag_key_a,
  bag_key_b,
  string_key_a,
  string_key_b,
  l2_text_a,
  l2_text_b,
  display_text_a,
  display_text_b,
  appearance_count_a,
  appearance_count_b,
  appearance_count_a+appearance_count_b AS combined_appearances,
  rarest_token,
  rarest_df,
  cast(cardinality(array_intersect(tokens_a,tokens_b)) AS DOUBLE)
   /cast(greatest(cardinality(array_union(tokens_a,tokens_b)),1) AS DOUBLE) AS jaccard,
  1.0-cast(levenshtein(l2_text_a,l2_text_b) AS DOUBLE)
   /cast(greatest(length(l2_text_a),length(l2_text_b),1) AS DOUBLE) AS lev_ratio,
  array_union(array_except(tokens_a,tokens_b),array_except(tokens_b,tokens_a)) AS sym_diff
 FROM blocked
), qualified AS (
 SELECT
  bag_key_a,
  bag_key_b,
  string_key_a,
  string_key_b,
  l2_text_a,
  l2_text_b,
  display_text_a,
  display_text_b,
  appearance_count_a,
  appearance_count_b,
  combined_appearances,
  rarest_token,
  rarest_df,
  jaccard,
  lev_ratio
 FROM scored
 WHERE jaccard>=0.75
  AND lev_ratio>=0.85
  AND cardinality(array_intersect(
   sym_diff,
   make_array(
    'alabama','alaska','arizona','arkansas','california','colorado','connecticut','delaware','florida','georgia',
    'hawaii','idaho','illinois','indiana','iowa','kansas','kentucky','louisiana','maine','maryland',
    'massachusetts','michigan','minnesota','mississippi','missouri','montana','nebraska','nevada','hampshire',
    'jersey','mexico','york','north','carolina','dakota','ohio','oklahoma','oregon','pennsylvania',
    'rhode','island','south','tennessee','texas','utah','vermont','virginia','washington','west',
    'wisconsin','wyoming','district','columbia','puerto','rico','dc',
    'east','northern','southern','eastern','western','central',
    'county','city','town','village','borough','parish','state','national','local','federal',
    'international','global','world','american','america','regional','municipal','tribal','rural','urban'
   )
  ))=0
), decided AS (
 SELECT DISTINCT
  least(subject_key,object_key) AS k_lo,
  greatest(subject_key,object_key) AS k_hi
 FROM org_decisions_current
 WHERE subject_kind='bag' AND object_kind='bag'
  AND verdict IN ('same','different','unsure')
  AND subject_key IS NOT NULL AND object_key IS NOT NULL
)
SELECT q.*
FROM decided d
RIGHT ANTI JOIN qualified q
 ON d.k_lo=least(q.bag_key_a,q.bag_key_b)
 AND d.k_hi=greatest(q.bag_key_a,q.bag_key_b)
