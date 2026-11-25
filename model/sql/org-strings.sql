-- Extract non-empty organization and on_behalf_of strings from appearance_records_resolved,
-- compute L2 location-stripped normalized text, string_key, sorted non-stopword tokens, and bag_key (ct-6him).
WITH raw_mentions AS (
 SELECT m['raw_text'] AS raw_text
 FROM (
  SELECT unnest(make_array(
   named_struct('field','organization','raw_text',nullif(trim(organization),'')),
   named_struct('field','on_behalf_of','raw_text',nullif(trim(on_behalf_of),''))
  )) AS m
  FROM appearance_records_resolved
 )
 WHERE m['raw_text'] IS NOT NULL
), raw_counts AS (
 SELECT raw_text,count(*) AS raw_count
 FROM raw_mentions
 GROUP BY raw_text
), folded AS (
 SELECT raw_text,raw_count,
  translate(
   regexp_replace(
    replace(replace(replace(replace(replace(replace(lower(raw_text),'ß','ss'),'ﬀ','ff'),'ﬁ','fi'),'ﬂ','fl'),'ﬃ','ffi'),'ﬄ','ffl'),
    '\p{Mn}','','g'
   ),
   'áàâäãåāăąçćčďéèêëēėęěğíìîïīįñńņňóòôöõōőřśšşťúùûüūůűýÿźżž',
   'aaaaaaaaacccdeeeeeeeegiiiiiinnnnooooooorssstuuuuuuuyyzzz'
  ) AS folded_text
 FROM raw_counts
), pre_l2 AS (
 SELECT raw_text,raw_count,folded_text,
  regexp_replace(
   trim(regexp_replace(
    regexp_replace(
     regexp_replace(
      replace(folded_text,'&',' and '),
      '[^a-z0-9 ,]',' ','g'
     ),
     '\b(?:statement\s+submitted\s+for\s+the\s+record|written\s+statement|testimony|statement|the|u\s+s|us|united\s+states|inc|llc|corp|corporation)\b',
     ' ','g'
    ),
    '\s+',' ','g'
   ),' ,'),
   '\s*,\s*',',','g'
  ) AS s1_csv
 FROM folded
), seg_items AS (
 SELECT raw_text,raw_count,folded_text,
  regexp_replace(trim(s1_csv,','),',+',',','g') AS s1_clean,
  CASE
   WHEN regexp_replace(trim(s1_csv,','),',+',',','g')=''
    THEN arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
   ELSE string_to_array(regexp_replace(trim(s1_csv,','),',+',',','g'),',')
  END AS segs
 FROM pre_l2
), seg_idx AS (
 SELECT raw_text,raw_count,folded_text,s1_clean,
  cast(cardinality(segs) AS BIGINT) AS n,
  unnest(CASE WHEN cardinality(segs)>0 THEN segs ELSE make_array(cast(NULL AS VARCHAR)) END) AS seg,
  unnest(range(1,cast(greatest(cardinality(segs),1) AS BIGINT)+1)) AS idx
 FROM seg_items
), loc_cut AS (
 SELECT raw_text,
  min(raw_count) AS raw_count,
  min(folded_text) AS folded_text,
  min(s1_clean) AS s1_clean,
  min(n) AS n,
  max(CASE
   WHEN idx=1 OR seg IS NULL OR NOT regexp_like(seg,'^(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|district of columbia|puerto rico|washington d ?c|d ?c|u ?s ?a|al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|pr|vi|gu)$')
   THEN idx
  END) AS m_state
 FROM seg_idx
 GROUP BY raw_text
), seg_rebuilt AS (
 SELECT raw_text,raw_count,folded_text,n,m_state,
  CASE
   WHEN s1_clean='' THEN arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
   ELSE string_to_array(s1_clean,',')
  END AS segs
 FROM loc_cut
), seg_sliced AS (
 SELECT raw_text,raw_count,folded_text,
  CASE
   WHEN n=0 THEN arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
   ELSE array_slice(segs,1,
    CASE
     WHEN m_state=1 AND n=2 AND cardinality(string_to_array(segs[1],' '))=1
      THEN n
     WHEN m_state=n-1 AND m_state>1
      AND NOT (m_state=2 AND regexp_like(segs[1],'^(?:university of |california state university|state university of )'))
      AND cardinality(string_to_array(segs[m_state],' '))<=3
      AND NOT regexp_like(segs[m_state],'\b(?:association|assoc|council|institute|university|college|school|department|dept|agency|office|service|services|bureau|commission|commissioner|commissioners|administration|foundation|center|centre|division|branch|section|program|programs|committee|board|hospital|clinic|laboratory|lab|labs|union|coalition|alliance|society|federation|corporation|corp|company|group|partners|firm|law|llp|llc|pllc|ltd|bank|church|tribe|nation)\b')
     THEN m_state-1
     ELSE m_state
    END
   )
  END AS kept_segs
 FROM seg_rebuilt
), l2_built AS (
 SELECT raw_text,raw_count,
  coalesce(
   nullif(trim(regexp_replace(regexp_replace(regexp_replace(
    CASE
     WHEN cardinality(kept_segs)=2 AND kept_segs[2]='co'
      THEN regexp_replace(kept_segs[1],'\bco\b',' ','g')||', co'
     ELSE regexp_replace(array_to_string(kept_segs,', '),'\bco\b',' ','g')
    END,
   '\s*,\s*',', ','g'),'(?:\s*,\s*)+',', ','g'),'\s+',' ','g'),' ,'),''),
   nullif(trim(regexp_replace(regexp_replace(folded_text,'[^a-z0-9]+',' ','g'),'\s+',' ','g')),''),
   lower(raw_text)
  ) AS l2_text
 FROM seg_sliced
), string_keyed AS (
 SELECT raw_text,raw_count,l2_text,
  substr(encode(sha256('org-string-v1'||l2_text),'hex'),1,16) AS string_key
 FROM l2_built
), grouped AS (
 SELECT
  string_key,
  min(l2_text) AS l2_text,
  (array_agg(raw_text ORDER BY raw_count DESC,raw_text ASC))[1] AS display_text,
  array_agg(raw_text ORDER BY raw_text ASC) AS raw_texts,
  cast(sum(raw_count) AS BIGINT) AS appearance_count
 FROM string_keyed
 GROUP BY string_key
), bag_cleaned AS (
 SELECT
  string_key,
  l2_text,
  display_text,
  raw_texts,
  appearance_count,
  string_to_array(l2_text,', ') AS segments,
  trim(regexp_replace(
   regexp_replace(
    regexp_replace(l2_text,'[^a-z0-9]+',' ','g'),
    '\b(?:of|and|for|the|on|in|at|to|a|an)\b',' ','g'
   ),
   '\s+',' ','g'
  )) AS bag_clean
 FROM grouped
), tokenized_grouped AS (
 SELECT
  string_key,
  l2_text,
  display_text,
  raw_texts,
  appearance_count,
  segments,
  CASE
   WHEN bag_clean='' THEN arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
   ELSE array_sort(string_to_array(bag_clean,' '))
  END AS bag_tokens
 FROM bag_cleaned
), with_bag AS (
 SELECT
  string_key,
  l2_text,
  segments,
  array_sort(array_distinct(bag_tokens)) AS tokens,
  bag_tokens,
  array_to_string(bag_tokens,' ') AS bag_text,
  display_text,
  raw_texts,
  appearance_count
 FROM tokenized_grouped
)
SELECT
 string_key,
 l2_text,
 segments,
 tokens,
 bag_text,
 substr(encode(sha256(
  CASE WHEN cardinality(bag_tokens)>0 THEN 'org-bag-v1'||bag_text ELSE 'org-bag-empty-v1'||string_key END
 ),'hex'),1,16) AS bag_key,
 display_text,
 raw_texts,
 appearance_count
FROM with_bag
