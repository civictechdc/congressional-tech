-- Address metadata and publisher evidence each retain their own grain.
WITH addresses AS (
 SELECT a.component,d.document_id AS doc_key,min(a.source_id) AS source_key,a.url,a.member_path,
 bool_or(a.source_id=s.source_id) AS is_saved,
 cast(min(cast(a.first_fetched AS TIMESTAMP WITH TIME ZONE)) AS DATE) AS first_seen
 FROM saved_files s JOIN (
  document_identities d JOIN document_addresses a USING(component)
 ) ON a.component=s.component AND s.saved_rank=1
 GROUP BY a.component,d.document_id,a.url,a.member_path
), compatible AS (
 SELECT a.component,a.url,a.member_path,l.context_url,l.text,l.doc_type,l.add_date,
 row_number() OVER(PARTITION BY a.component,a.url,a.member_path
 ORDER BY cast(l.first_good_at AS TIMESTAMP WITH TIME ZONE) NULLS LAST,
 l.context,l.page_body,l.link_index,l.split_position) AS selected
 FROM model_url_keys k RIGHT JOIN (
  document_addresses a JOIN publisher_links l ON a.source_id=l.source_id
 ) ON a.url=k.url AND k.error IS NULL
 WHERE (a.member_path IS NULL AND l.target_member_path IS NULL)
 OR (a.member_path IS NOT NULL AND l.url_key=k.url_key
 AND (l.target_member_path IS NULL OR l.target_member_path=a.member_path))
)
SELECT a.doc_key,a.source_key,a.url,a.member_path,a.is_saved,a.first_seen,
 l.context_url AS listed_on,l.text AS link_text,l.doc_type,try_cast(l.add_date AS DATE) AS posted
FROM (SELECT * FROM compatible WHERE selected=1 AND component IS NOT NULL AND url IS NOT NULL) l RIGHT JOIN addresses a
 ON (a.component IS NOT DISTINCT FROM l.component) AND (a.url IS NOT DISTINCT FROM l.url)
 AND (a.member_path IS NOT DISTINCT FROM l.member_path)
