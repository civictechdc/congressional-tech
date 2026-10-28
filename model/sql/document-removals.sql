-- A re-added address on the same page has a later page context without removal.
WITH latest AS (
 SELECT p.*,m.component,max(p.last_good_at) OVER(PARTITION BY m.component,p.context_url) AS latest_page
 FROM publisher_links p JOIN document_members m ON p.source_id=m.source_id
 WHERE regexp_like(p.context_url,'(?i)^https://docs[.]house[.]gov/meetings/.*[.]xml(?:[?].*)?$')
), selected AS (
 SELECT component,try_cast(remove_date AS DATE) AS removed FROM latest WHERE last_good_at=latest_page
)
SELECT component,min(removed) AS removed_on FROM selected GROUP BY component HAVING count(removed)=count(*)
