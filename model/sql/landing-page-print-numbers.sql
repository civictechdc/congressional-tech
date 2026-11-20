-- Title Design Stage 2 (ct-n131), reusing landing_page_picks and govinfo_details_title from 1e5b751a
-- without overwriting title: extract the hearing print number printed in a GovInfo Content Details
-- page's <title> (excluding generic chamber-and-Congress labels). Package page ranks before granule.
SELECT component,print_number FROM (
 SELECT p.component,nullif(trim((regexp_match(a.reading_title,t.pattern))[1]),'') AS print_number,
  row_number() OVER(PARTITION BY p.component ORDER BY p.page_url) AS pick
 FROM landing_page_picks p JOIN source_annotations a ON a.source_id=p.source_id
 JOIN (SELECT pattern FROM page_signals WHERE kind='landing_title') t ON regexp_like(a.reading_title,t.pattern)
 WHERE p.component IS NOT NULL
) WHERE pick=1 AND print_number IS NOT NULL
