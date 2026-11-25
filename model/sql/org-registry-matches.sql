-- Whole-segment hash-equality joins against pinned RefSpec 1.3 federal agencies.
-- Every CTE below is referenced at most once; shared intermediate sets are
-- materialized as separate model steps (org_registry_resolved_orgs,
-- org_registry_raw_keys, org_registry_keys, org_registry_segments).
-- Small side (org_registry_keys) sits on the left of the hash join.
WITH expanded_candidates AS (
  SELECT
    string_key,
    bag_key,
    raw_seg,
    raw_acronym_candidate,
    c['cand_key'] AS cand_key,
    c['form_rank'] AS form_rank
  FROM (
    SELECT
      string_key,
      bag_key,
      raw_seg,
      raw_acronym_candidate,
      unnest(make_array(
        named_struct('cand_key', norm_key, 'form_rank', 1),
        CASE WHEN regexp_like(
          norm_key,
          '^(department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard) of .+$'
        ) THEN named_struct(
          'cand_key',
          regexp_replace(
            norm_key,
            '^(department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard) of (.+)$',
            '\2 \1'
          ),
          'form_rank', 2
        ) END,
        CASE WHEN regexp_like(
          norm_key,
          '^.+? (department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard)$'
        ) THEN named_struct(
          'cand_key',
          regexp_replace(
            norm_key,
            '^(.+?) (department|office|bureau|division|institute|center|centers|council|board|commission|service|agency|administration|authority|foundation|corps|force|guard)$',
            '\2 of \1'
          ),
          'form_rank', 3
        ) END
      )) AS c
    FROM org_registry_segments
  ) s
  WHERE c IS NOT NULL
),
matched_segments AS (
  SELECT
    c.string_key,
    c.bag_key,
    k.anchor,
    k.fr_id,
    k.fr_resource,
    k.fr_relation,
    k.evidence_id,
    k.canonical_name,
    k.parent_fr_iri,
    k.key_kind,
    k.key_priority,
    c.form_rank,
    c.raw_seg,
    CASE WHEN k.fr_relation = 'same' THEN 0 ELSE 1 END AS rel_rank
  FROM org_registry_keys k
  JOIN expanded_candidates c
    ON k.match_key = c.cand_key
  WHERE k.raw_acronym IS NULL
     OR c.raw_acronym_candidate = k.raw_acronym
     OR regexp_replace(c.raw_acronym_candidate, '\.', '', 'g') = k.raw_acronym
),
ranked_matches AS (
  SELECT
    string_key,
    bag_key,
    anchor,
    fr_id,
    fr_resource,
    fr_relation,
    evidence_id,
    canonical_name,
    parent_fr_iri,
    key_kind,
    raw_seg AS matched_segment,
    'registry' AS method,
    1.0 AS score,
    row_number() OVER (
      PARTITION BY string_key
      ORDER BY rel_rank ASC, key_priority ASC, form_rank ASC, coalesce(fr_id, 999999999) ASC, anchor ASC
    ) AS rn
  FROM matched_segments
)
SELECT
  string_key,
  bag_key,
  anchor,
  fr_id,
  fr_resource,
  fr_relation,
  evidence_id,
  canonical_name,
  parent_fr_iri,
  key_kind,
  matched_segment,
  method,
  score
FROM ranked_matches
WHERE rn = 1
