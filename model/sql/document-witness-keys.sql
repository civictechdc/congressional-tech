WITH canonical_expanded AS (
 SELECT component,witness_key FROM document_witness_raw_matches
 UNION
 SELECT m.component,wp.superseded_by AS witness_key
 FROM witness_precedence wp
 JOIN document_witness_raw_matches m ON wp.witness_key=m.witness_key
 WHERE wp.superseded_by IS NOT NULL
), per_key AS (
 -- One row per (component, witness_key), so the outer counts need no count(DISTINCT): the engine
 -- holds a separate distinct-set accumulator per group for it, ~17 KB each over ~128K components.
 -- Superseded keys resolve to their canonical witness_key and are omitted when a current key stands (cat2-8ai9).
 SELECT
  m.component,
  m.witness_key,
  bool_or(wp.superseded_by IS NULL) AS is_current,
  min(w.name) FILTER (WHERE wp.superseded_by IS NULL) AS current_name,
  min(w.name) AS any_name
 FROM witness_precedence wp
 RIGHT JOIN (
  appearance_records_resolved w
  RIGHT JOIN canonical_expanded m ON w.witness_key=m.witness_key
 ) ON wp.witness_key=m.witness_key
 GROUP BY m.component,m.witness_key
)
SELECT
 component,
 CASE
  WHEN count(witness_key) FILTER (WHERE is_current)>0
   THEN array_sort(array_distinct(array_agg(witness_key) FILTER (WHERE is_current)))
  ELSE array_sort(array_distinct(array_agg(witness_key)))
 END AS witness_keys,
 CASE
  WHEN count(witness_key) FILTER (WHERE is_current)=1
   THEN min(current_name)
  WHEN count(witness_key)=1
   THEN min(any_name)
 END AS witness_name
FROM per_key
GROUP BY component
