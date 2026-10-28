WITH kinds AS (
 SELECT DISTINCT l.source_id,r.basis,r.document_kind
 FROM publisher_links l JOIN publisher_kinds r ON
 (r.basis='doc_type' AND regexp_like(l.doc_type,r.pattern)) OR
 (r.basis='text' AND regexp_like(l.text,r.pattern))
), chosen_kinds AS (
 SELECT * FROM kinds k WHERE basis='doc_type' OR NOT EXISTS (
 SELECT 1 FROM kinds c WHERE c.source_id=k.source_id AND c.basis='doc_type')
), kind_arrays AS (
 SELECT source_id,array_agg(document_kind ORDER BY document_kind) AS document_kind
 FROM (SELECT DISTINCT source_id,document_kind FROM chosen_kinds) GROUP BY source_id
), labels AS (
 SELECT source_id,text,row_number() OVER(PARTITION BY source_id ORDER BY
 cast(first_good_at AS TIMESTAMP WITH TIME ZONE) NULLS LAST,context,page_body,link_index,split_position) AS preference
 FROM publisher_links WHERE nullif(trim(text),'') IS NOT NULL
)
SELECT s.source_id,k.document_kind,l.text AS listing_title FROM source_files s
LEFT JOIN kind_arrays k ON s.source_id=k.source_id
LEFT JOIN labels l ON s.source_id=l.source_id AND l.preference=1
