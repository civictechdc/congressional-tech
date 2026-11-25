-- Publish resolved organizations with display names, appearance counts, anchor IDs,
-- bag/string memberships, and Ban, Park & You (APSR 2023) taxonomy classification (ct-6him).
WITH raw_text_counts AS (
 SELECT group_key,raw_text,count(*) AS mention_cnt
 FROM org_resolved_mentions
 GROUP BY group_key,raw_text
), display_names AS (
 SELECT group_key,
  (array_agg(raw_text ORDER BY mention_cnt DESC,raw_text ASC))[1] AS display_name
 FROM raw_text_counts
 GROUP BY group_key
), distinct_witnesses AS (
 SELECT DISTINCT group_key,witness_key
 FROM org_resolved_mentions
), witness_counts AS (
 SELECT group_key,cast(count(witness_key) AS BIGINT) AS appearance_count
 FROM distinct_witnesses
 GROUP BY group_key
), distinct_bags AS (
 SELECT DISTINCT group_key,bag_key
 FROM org_resolved_mentions
), bag_lists AS (
 SELECT group_key,array_agg(bag_key ORDER BY bag_key ASC) AS bag_keys
 FROM distinct_bags
 GROUP BY group_key
), distinct_strings AS (
 SELECT DISTINCT group_key,string_key
 FROM org_resolved_mentions
), string_lists AS (
 SELECT group_key,array_agg(string_key ORDER BY string_key ASC) AS string_keys
 FROM distinct_strings
 GROUP BY group_key
), tax_ranked AS (
 SELECT
  d.group_key,
  d.display_name,
  t.id AS taxonomy_category,
  t.parent_id AS taxonomy_parent,
  t.org_kind AS kind,
  row_number() OVER (
   PARTITION BY d.group_key
   ORDER BY CASE WHEN t.id IS NULL THEN 1 ELSE 0 END ASC,t.priority ASC,t.id ASC
  ) AS rn
 FROM ban_park_you_org_taxonomy t
 RIGHT JOIN display_names d
  ON t.pattern IS NOT NULL AND regexp_like(d.display_name,t.pattern)
), classified AS (
 SELECT group_key,display_name,taxonomy_category,taxonomy_parent,kind
 FROM tax_ranked
 WHERE rn=1
)
SELECT
 a.org_id,
 c.display_name,
 c.kind,
 c.taxonomy_parent,
 c.taxonomy_category,
 cast(NULL AS VARCHAR) AS parent_org_id,
 wc.appearance_count,
 bl.bag_keys,
 sl.string_keys,
 a.anchor,
 a.has_conflict
FROM org_group_anchors a
JOIN classified c ON c.group_key=a.group_key
JOIN witness_counts wc ON wc.group_key=a.group_key
JOIN bag_lists bl ON bl.group_key=a.group_key
JOIN string_lists sl ON sl.group_key=a.group_key
