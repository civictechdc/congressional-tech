-- DM 7.3, ct-m878, ct-egoo. Each landing page with every document its address belongs to, as a ZIP's
-- address stays on its contents: the one its pick names (landing-page-picks.sql). A package page that
-- names no saved file (a multi-part GovInfo package has no package-level file) belongs to each of its
-- parts instead (owner, 2026-11-11): the documents its granule pages, at its address then one more path
-- segment, picked. A page with neither keeps one row with no document (metadata unplaced_landing_pages).
-- Both sides read the materialized picks; the granule side is the ON clause's build.
SELECT DISTINCT p.source_id,p.page_body,p.page_url,p.first_fetched,coalesce(p.component,g.component) AS component
FROM (SELECT component,regexp_replace(page_url,'/[^/]+$','') AS package_url FROM landing_page_picks WHERE component IS NOT NULL) g
RIGHT JOIN landing_page_picks p ON p.component IS NULL AND g.package_url=p.page_url
