-- A re-added address on the same page has a later page context without removal.
WITH appearances AS (
 SELECT m.component,p.context_url,p.last_good_at,p.remove_date
 FROM document_members m JOIN publisher_links p ON p.source_id=m.source_id
 WHERE regexp_like(p.context_url,'(?i)^https://docs[.]house[.]gov/meetings/.*[.]xml(?:[?].*)?$')
), latest AS (
 SELECT component,context_url,max(last_good_at) AS latest_page FROM appearances
 GROUP BY component,context_url
), selected AS (
 SELECT a.component,try_cast(a.remove_date AS DATE) AS removed
 FROM latest l JOIN appearances a
 ON (a.component IS NOT DISTINCT FROM l.component)
 AND (a.context_url IS NOT DISTINCT FROM l.context_url)
 AND (a.last_good_at IS NOT DISTINCT FROM l.latest_page)
 WHERE a.last_good_at IS NOT NULL
)
SELECT component,min(removed) AS removed_on FROM selected GROUP BY component HAVING count(removed)=count(*)
