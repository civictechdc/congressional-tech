-- DM 7.3, ct-m878. A landing page (page signals kind landing_url: a GovInfo Content Details page) is a
-- wrapper that describes the one file its address's last path segment names, when that segment is a
-- GovInfo package or granule ID (kind landing_name): a sub-page with another last segment names no
-- file, so it never takes another site's file of that stem (review finding 3), and
-- landing_page_invariants counts its address if no published row carries it. Each such page with
-- every real file of that name, any extension: the package's or granule's PDF and HTML text, or
-- another site's copy under the same GovInfo name; one row with no file when none is saved.
-- The page set is read once (its regex joins run once); the page side is small, so it builds.
SELECT p.source_id AS page_id,p.body_sha AS page_body,p.source_url AS page_url,p.first_fetched,
 f.component,f.source_id,f.format
FROM (
 SELECT m.source_id,m.body_sha,m.source_url,m.filename,m.first_fetched
 FROM (SELECT pattern FROM page_signals WHERE kind='landing_url') r
 JOIN document_members m ON regexp_like(m.source_url,r.pattern)
 JOIN (SELECT pattern FROM page_signals WHERE kind='landing_name') n ON regexp_like(m.filename,n.pattern)
 WHERE m.record_role='wrapper' AND coalesce(m.filename,'')<>''
) p LEFT JOIN document_members f
 ON f.is_real_file AND regexp_replace(f.filename,'[.][^./]*$','')=p.filename
