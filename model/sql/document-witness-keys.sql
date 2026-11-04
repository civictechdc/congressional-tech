WITH canonical_expanded AS (
 SELECT component,witness_key FROM document_witness_raw_matches
 UNION
 SELECT m.component,wp.superseded_by AS witness_key
 FROM document_witness_raw_matches m
 JOIN witness_precedence wp ON wp.witness_key=m.witness_key
 WHERE wp.superseded_by IS NOT NULL
), all_matched AS (
 SELECT component,witness_key FROM canonical_expanded
 UNION
 SELECT c.component,wp.witness_key
 FROM canonical_expanded c
 JOIN witness_precedence wp ON wp.superseded_by=c.witness_key
), per_key AS (
 -- One row per (component, witness_key), so the outer counts need no count(DISTINCT): the engine
 -- holds a separate distinct-set accumulator per group for it, ~17 KB each over ~128K components.
 SELECT
  m.component,
  m.witness_key,
  bool_or(wp.superseded_by IS NULL) AS is_current,
  min(w.name) FILTER (WHERE wp.superseded_by IS NULL) AS current_name,
  min(w.name) AS any_name
 FROM all_matched m
 LEFT JOIN appearance_records_resolved w ON w.witness_key=m.witness_key
 LEFT JOIN witness_precedence wp ON wp.witness_key=m.witness_key
 GROUP BY m.component,m.witness_key
)
SELECT
 component,
 array_sort(array_distinct(array_agg(witness_key))) AS witness_keys,
 CASE
  WHEN count(witness_key) FILTER (WHERE is_current)=1
   THEN min(current_name)
  WHEN count(witness_key)=1
   THEN min(any_name)
 END AS witness_name
FROM per_key
GROUP BY component
