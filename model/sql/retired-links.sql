-- Data model §8.2, Retired keys. Release-sized inputs only (links, details, source_rows,
-- body_fingerprints, prior_links, prior_sources, base_retired, landing_pages); captures and
-- readings are never read here.
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
  GROUP BY link_key HAVING min(successor_key)=max(successor_key)
), address_rows AS (
  -- Third rule: a candidate document at one of the prior row's exact addresses (url, member_path).
  SELECT g.link_key,d.link_key AS successor_key FROM gone g
  JOIN prior_sources ps ON ps.release_rank=g.release_rank AND ps.list_row=g.list_row
  JOIN source_rows sr ON sr.url=ps.url AND sr.member_path IS NOT DISTINCT FROM ps.member_path
  JOIN details d ON d.list_row=sr.list_row
), old_prints AS (
  -- An address holds editions (§7.5: an edition never joins another), so the address rule
  -- redirects only to a document holding the same text fingerprint as the retired body.
  SELECT g.link_key,f.fingerprint FROM gone g
  JOIN body_fingerprints f ON substr(f.body_sha,1,16)=lower(encode(g.link_key,'hex'))
), document_prints AS (
  SELECT r.primary_key,f.fingerprint FROM row_of r
  JOIN body_fingerprints f ON substr(f.body_sha,1,16)=lower(encode(r.link_key,'hex'))
), by_address AS (
  SELECT a.link_key,min(a.successor_key) AS successor_key FROM address_rows a
  JOIN old_prints o ON o.link_key=a.link_key
  JOIN document_prints d ON d.primary_key=a.successor_key AND d.fingerprint=o.fingerprint
  GROUP BY a.link_key HAVING min(a.successor_key)=max(a.successor_key)
), address_versions AS (
  SELECT link_key,array_sort(array_agg(DISTINCT successor_key)) AS versions FROM address_rows GROUP BY link_key
), fresh AS (
  SELECT g.link_key,coalesce(p.successor_key,s.successor_key,a.successor_key) AS successor_key,
    g.release_id AS last_release_id,g.filename AS last_filename,
    CASE WHEN coalesce(p.successor_key,s.successor_key,a.successor_key) IS NULL THEN v.versions END AS address_versions
  FROM gone g LEFT JOIN by_primary p ON p.link_key=g.link_key LEFT JOIN by_sibling s ON s.link_key=g.link_key
  LEFT JOIN by_address a ON a.link_key=g.link_key LEFT JOIN address_versions v ON v.link_key=g.link_key
), carried AS (
  -- One hop: a successor still published resolves to its row's primary key; a successor
  -- retired in this release takes that row's successor; otherwise a removal notice.
  SELECT b.link_key,coalesce(r.primary_key,f.successor_key) AS successor_key,b.last_release_id,b.last_filename,
    CASE WHEN coalesce(r.primary_key,f.successor_key) IS NULL THEN b.address_versions END AS address_versions
  FROM base_retired b
  LEFT JOIN row_of r ON r.link_key=b.successor_key
  LEFT JOIN fresh f ON f.link_key=b.successor_key
  WHERE NOT EXISTS (SELECT 1 FROM links c WHERE c.link_key=b.link_key)
    AND NOT EXISTS (SELECT 1 FROM fresh x WHERE x.link_key=b.link_key)
), landing_versions AS (
  -- DM 7.3, ct-egoo: a landing page's key (its body's first 8 bytes) lists the documents now at the
  -- page's own address, the hearing that took it or a package's parts. A carried notice has no prior
  -- row to read that address from, so this is how a notice written empty learns of the parts.
  SELECT link_key,array_sort(array_agg(successor_key)) AS versions FROM (
    SELECT DISTINCT arrow_cast(decode(substr(l.page_body,1,16),'hex'),'FixedSizeBinary(8)') AS link_key,d.link_key AS successor_key
    FROM landing_pages l JOIN source_rows sr ON sr.url=l.page_url AND sr.member_path IS NULL
    JOIN details d ON d.list_row=sr.list_row) pairs
  GROUP BY link_key
)
SELECT r.link_key,r.successor_key,r.last_release_id,r.last_filename,
  CASE WHEN r.successor_key IS NULL THEN coalesce(v.versions,r.address_versions) END AS address_versions
FROM landing_versions v RIGHT JOIN (
  SELECT link_key,successor_key,last_release_id,last_filename,address_versions FROM fresh
  UNION ALL
  SELECT link_key,successor_key,last_release_id,last_filename,address_versions FROM carried
) r ON v.link_key=r.link_key
