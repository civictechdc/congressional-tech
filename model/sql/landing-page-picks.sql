-- DM 7.3, ct-m878. One row per landing page: the document named for it, or none when no file of its
-- name is saved (landing-pages.sql then looks for its parts). Of the documents holding a file named
-- for it, the one whose file comes first in format preference (the PDF before the HTML text), then
-- one the page itself links (its package's own copy, directly or through the ZIP it links, before
-- another site's copy under the same name), then by source ID. Its link key is never added: it
-- retires through retired-links.sql's ordinary rules.
WITH linked AS (
 SELECT DISTINCT n.page_id,n.source_id FROM landing_page_files n
 JOIN publisher_links l ON l.page_body=n.page_body AND l.source_id=n.source_id
)
SELECT page_id AS source_id,page_body,page_url,first_fetched,component FROM (
 SELECT n.page_id,n.page_body,n.page_url,n.first_fetched,n.component,row_number() OVER(PARTITION BY n.page_id
  ORDER BY coalesce(p.rank,2147483647),k.page_id IS NULL,n.source_id) AS pick
 FROM formats p RIGHT JOIN (linked k RIGHT JOIN landing_page_files n ON k.page_id=n.page_id AND k.source_id=n.source_id)
  ON p.kind='preference' AND p.value=n.format
) WHERE pick=1
