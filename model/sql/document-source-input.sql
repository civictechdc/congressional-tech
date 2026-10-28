WITH listings AS (
 SELECT *,row_number() OVER(PARTITION BY source_id ORDER BY first_good_at NULLS LAST,context,page_body,link_index,split_position) AS selected
 FROM publisher_links
)
SELECT d.document_id AS doc_key,min(a.source_id) AS source_key,a.url,a.member_path,
 bool_or(a.source_id=s.source_id) AS is_saved,cast(min(a.first_fetched) AS DATE) AS first_seen,
 max(l.context_url) AS listed_on,max(l.text) AS link_text,max(l.doc_type) AS doc_type,
 max(try_cast(l.add_date AS DATE)) AS posted
FROM document_addresses a JOIN document_identities d USING(component)
JOIN saved_files s ON a.component=s.component AND s.saved_rank=1
LEFT JOIN listings l ON a.source_id=l.source_id AND l.selected=1
GROUP BY d.document_id,a.url,a.member_path
