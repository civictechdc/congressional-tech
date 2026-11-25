-- Publish resolved organizations with display names, appearance counts, anchor IDs,
-- bag/string memberships, RefSpec federal agency names/parents (ct-w34j),
-- Wikidata display labels (ct-39u8), and Ban, Park & You (APSR 2023) taxonomy (ct-6him).
WITH single_successors AS (
 SELECT original,min(successor) AS successor
 FROM refspec_current_successors
 GROUP BY original
 HAVING count(*)=1
), refspec_resolved AS (
 SELECT
  'fr_agency:'||cast(t.fr_id AS VARCHAR) AS anchor,
  t.name AS refspec_name,
  coalesce(ps.successor,t.parent) AS parent_iri
 FROM refspec_organizations t
 LEFT JOIN single_successors ps ON ps.original=t.parent
 UNION ALL
 SELECT
  'refspec_target:'||a.target AS anchor,
  initcap(a.name_key) AS refspec_name,
  cast(NULL AS VARCHAR) AS parent_iri
 FROM refspec_aliases a
 WHERE a.fr_resource IS NULL AND a.target IS NOT NULL
), refspec_by_anchor AS (
 SELECT
  r.anchor,
  min(r.refspec_name) AS refspec_name,
  min('fr_agency:'||cast(p.fr_id AS VARCHAR)) AS parent_anchor
 FROM refspec_resolved r
 LEFT JOIN refspec_organizations p ON p.resource_iri=r.parent_iri
 GROUP BY r.anchor
), raw_text_counts AS (
 SELECT group_key,raw_text,count(*) AS mention_cnt
 FROM org_resolved_mentions
 GROUP BY group_key,raw_text
), raw_display_names AS (
 SELECT group_key,
  (array_agg(raw_text ORDER BY mention_cnt DESC,raw_text ASC))[1] AS raw_display_name
 FROM raw_text_counts
 GROUP BY group_key
), display_names AS (
 SELECT
  ad.group_key,
  coalesce(ad.refspec_name,wl.wikidata_label,ad.raw_display_name) AS display_name,
  ad.is_refspec,
  ad.parent_anchor
 FROM org_wikidata_labels wl
 RIGHT JOIN (
  SELECT
   ad0.group_key,
   ad0.raw_display_name,
   CASE WHEN rb.anchor IS NOT NULL THEN true ELSE false END AS is_refspec,
   rb.refspec_name,
   rb.parent_anchor
  FROM refspec_by_anchor rb
  RIGHT JOIN (
   SELECT a.group_key,a.anchor,rd.raw_display_name
   FROM org_group_anchors a
   JOIN raw_display_names rd ON rd.group_key=a.group_key
  ) ad0 ON rb.anchor=ad0.anchor
 ) ad ON wl.group_key=ad.group_key
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
  d.is_refspec,
  d.parent_anchor,
  t.id AS taxonomy_category,
  t.parent_id AS taxonomy_parent,
  CASE WHEN d.is_refspec THEN 'government' ELSE t.org_kind END AS kind,
  row_number() OVER (
   PARTITION BY d.group_key
   ORDER BY CASE WHEN t.id IS NULL THEN 1 ELSE 0 END ASC,t.priority ASC,t.id ASC
  ) AS rn
 FROM ban_park_you_org_taxonomy t
 RIGHT JOIN display_names d
  ON t.pattern IS NOT NULL AND regexp_like(d.display_name,t.pattern)
), classified AS (
 SELECT group_key,display_name,taxonomy_category,taxonomy_parent,kind,parent_anchor
 FROM tax_ranked
 WHERE rn=1
), parent_org_lookup AS (
 SELECT anchor,min(org_id) AS org_id
 FROM org_group_anchors
 WHERE anchor LIKE 'fr_agency:%' OR anchor LIKE 'refspec_target:%'
 GROUP BY anchor
)
SELECT
 o.org_id,
 o.display_name,
 o.kind,
 o.taxonomy_parent,
 o.taxonomy_category,
 CASE WHEN pa.org_id IS NOT NULL AND pa.org_id<>o.org_id THEN pa.org_id ELSE cast(NULL AS VARCHAR) END AS parent_org_id,
 o.appearance_count,
 o.bag_keys,
 o.string_keys,
 o.anchor,
 o.has_conflict
FROM parent_org_lookup pa
RIGHT JOIN (
 SELECT
  a.org_id,a.anchor,a.has_conflict,
  c.display_name,c.kind,c.taxonomy_parent,c.taxonomy_category,c.parent_anchor,
  wc.appearance_count,bl.bag_keys,sl.string_keys
 FROM org_group_anchors a
 JOIN classified c ON c.group_key=a.group_key
 JOIN witness_counts wc ON wc.group_key=a.group_key
 JOIN bag_lists bl ON bl.group_key=a.group_key
 JOIN string_lists sl ON sl.group_key=a.group_key
) o ON pa.anchor=o.parent_anchor