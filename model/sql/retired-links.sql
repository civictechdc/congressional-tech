-- Data model §8.2, Retired keys. Release-sized inputs only (links, details, prior_links,
-- base_retired); captures and readings are never read here.
WITH latest AS (
  SELECT link_key,release_rank,release_id,list_row,primary_key,filename FROM (
    SELECT p.*,row_number() OVER (PARTITION BY p.link_key ORDER BY p.release_rank) AS rn FROM prior_links p) ranked
  WHERE rn=1
), gone AS (
  SELECT g.* FROM latest g WHERE NOT EXISTS (SELECT 1 FROM links c WHERE c.link_key=g.link_key)
), row_of AS (
  SELECT c.link_key,d.link_key AS primary_key FROM links c JOIN details d ON d.list_row=c.list_row
), by_primary AS (
  SELECT g.link_key,r.primary_key AS successor_key FROM gone g JOIN row_of r ON r.link_key=g.primary_key
), sibling_rows AS (
  SELECT g.link_key,r.primary_key AS successor_key FROM gone g
  JOIN prior_links s ON s.release_rank=g.release_rank AND s.list_row=g.list_row
  JOIN row_of r ON r.link_key=s.link_key
), by_sibling AS (
  SELECT link_key,min(successor_key) AS successor_key FROM sibling_rows
  GROUP BY link_key HAVING count(DISTINCT successor_key)=1
), fresh AS (
  SELECT g.link_key,coalesce(p.successor_key,s.successor_key) AS successor_key,
    g.release_id AS last_release_id,g.filename AS last_filename
  FROM gone g LEFT JOIN by_primary p ON p.link_key=g.link_key LEFT JOIN by_sibling s ON s.link_key=g.link_key
), carried AS (
  -- One hop: a successor still published resolves to its row's primary key; a successor
  -- retired in this release takes that row's successor; otherwise a removal notice.
  SELECT b.link_key,coalesce(r.primary_key,f.successor_key) AS successor_key,b.last_release_id,b.last_filename
  FROM base_retired b
  LEFT JOIN row_of r ON r.link_key=b.successor_key
  LEFT JOIN fresh f ON f.link_key=b.successor_key
  WHERE NOT EXISTS (SELECT 1 FROM links c WHERE c.link_key=b.link_key)
    AND NOT EXISTS (SELECT 1 FROM fresh x WHERE x.link_key=b.link_key)
)
SELECT link_key,successor_key,last_release_id,last_filename FROM fresh
UNION ALL
SELECT link_key,successor_key,last_release_id,last_filename FROM carried
